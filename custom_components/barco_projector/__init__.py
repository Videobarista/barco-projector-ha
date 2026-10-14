"""The Barco Cinema Projector integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr, service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_COMMAND,
    ATTR_DATA,
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_MACRO,
    ATTR_MASK,
    ATTR_OUTPUT,
    CONF_MEDIA_BLOCK,
    CONF_MEDIA_BLOCK_HOST,
    CONF_MEDIA_BLOCK_PORT,
    CONF_SCAN_INTERVAL_SECONDS,
    DEFAULT_ICMP_PORT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MEDIA_BLOCK_ICMP,
    MEDIA_BLOCK_NONE,
    SERVICE_EXECUTE_MACRO,
    SERVICE_GPIO_PULSE,
    SERVICE_GPIO_SET,
    SERVICE_SEND_AUTOMATION,
    SERVICE_SEND_RAW,
    STORAGE_VERSION,
)
from .coordinator import BarcoCoordinator, async_remove_unsupported_entities, storage_key
from .entity import projector_device_info
from .icmp import IcmpClient
from .protocol import BarcoClient, BarcoProjector

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class BarcoRuntimeData:
    """Objects shared between the platforms of one config entry."""

    coordinator: BarcoCoordinator
    icmp: IcmpClient | None
    projector_device_id: str | None = None


type BarcoConfigEntry = ConfigEntry[BarcoRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, which act on the media players of this integration."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_EXECUTE_MACRO,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required(ATTR_MACRO): cv.string},
        func="async_execute_macro",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SEND_RAW,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required(ATTR_COMMAND): cv.string,
            vol.Optional(ATTR_DATA, default=""): cv.string,
        },
        func="async_send_raw",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SEND_AUTOMATION,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required(ATTR_COMMAND): cv.string},
        func="async_send_automation",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GPIO_PULSE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required(ATTR_OUTPUT): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(ATTR_DURATION, default=500): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=60000)
            ),
            vol.Optional(ATTR_DIRECTION, default="up"): vol.In(["up", "down"]),
        },
        func="async_gpio_pulse",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GPIO_SET,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required(ATTR_MASK): cv.string},
        func="async_gpio_set",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Set up a projector from a config entry.

    A projector that does not answer is set up from what it reported last
    time, with its entities unavailable until it does. Only one that has
    never answered keeps the entry waiting.
    """
    options = {**entry.data, **entry.options}

    client = BarcoClient(
        host=options[CONF_HOST],
        port=options.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = BarcoCoordinator(
        hass,
        entry,
        BarcoProjector(client),
        scan_interval=options.get(CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_load_stored()
    await coordinator.async_config_entry_first_refresh()
    async_remove_unsupported_entities(hass, entry.entry_id, coordinator.unsupported)

    icmp: IcmpClient | None = None
    if options.get(CONF_MEDIA_BLOCK, MEDIA_BLOCK_NONE) == MEDIA_BLOCK_ICMP:
        icmp = IcmpClient(
            host=options.get(CONF_MEDIA_BLOCK_HOST) or options[CONF_HOST],
            port=options.get(CONF_MEDIA_BLOCK_PORT, DEFAULT_ICMP_PORT),
        )

    entry.runtime_data = BarcoRuntimeData(coordinator=coordinator, icmp=icmp)

    # Register the projector before the platforms add entities, so the media
    # block can be linked to it by device id.
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **projector_device_info(entry)
    )
    entry.runtime_data.projector_device_id = device.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator shuts itself down and closes the projector socket when the
    entry unloads; only the media block connection is closed here.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.runtime_data.icmp is not None:
        await entry.runtime_data.icmp.async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> None:
    """Forget what the projector reported once its entry is deleted."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
