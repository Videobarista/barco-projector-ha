"""The Barco Cinema Projector integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MEDIA_BLOCK,
    CONF_MEDIA_BLOCK_HOST,
    CONF_MEDIA_BLOCK_PORT,
    CONF_SCAN_INTERVAL_SECONDS,
    DEFAULT_ICMP_PORT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    MEDIA_BLOCK_ICMP,
    MEDIA_BLOCK_NONE,
)
from .coordinator import BarcoCoordinator
from .icmp import IcmpClient
from .protocol import BarcoClient, BarcoProjector

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class BarcoRuntimeData:
    """Objects shared between the platforms of one config entry."""

    coordinator: BarcoCoordinator
    icmp: IcmpClient | None


type BarcoConfigEntry = ConfigEntry[BarcoRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Set up Barco Cinema Projector from a config entry."""
    options = {**entry.data, **entry.options}

    client = BarcoClient(
        host=options[CONF_HOST],
        port=options.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = BarcoCoordinator(
        hass,
        BarcoProjector(client),
        scan_interval=options.get(CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL),
        entry_title=entry.title,
    )

    await coordinator.async_config_entry_first_refresh()

    icmp: IcmpClient | None = None
    if options.get(CONF_MEDIA_BLOCK, MEDIA_BLOCK_NONE) == MEDIA_BLOCK_ICMP:
        icmp = IcmpClient(
            host=options.get(CONF_MEDIA_BLOCK_HOST) or options[CONF_HOST],
            port=options.get(CONF_MEDIA_BLOCK_PORT, DEFAULT_ICMP_PORT),
        )

    entry.runtime_data = BarcoRuntimeData(coordinator=coordinator, icmp=icmp)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()
        if entry.runtime_data.icmp is not None:
            await entry.runtime_data.icmp.async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
