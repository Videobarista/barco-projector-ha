"""Switch entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import BarcoConfigEntry
from .const import SHUTTER_OPEN
from .entity import BarcoMediaBlockEntity, BarcoProjectorEntity
from .icmp import IcmpError
from .protocol import BarcoError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    data = entry.runtime_data
    entities: list[SwitchEntity] = [BarcoDowserSwitch(data.coordinator, entry)]

    if "sleep" not in data.coordinator.unsupported:
        entities.append(BarcoSleepSwitch(data.coordinator, entry))

    if data.icmp is not None:
        entities.append(
            IcmpToggleSwitch(
                data.icmp,
                entry,
                key="icmp_schedule",
                on_action="Enable Schedule",
                off_action="Disable Schedule",
            )
        )
        entities.append(
            IcmpToggleSwitch(
                data.icmp,
                entry,
                key="icmp_repeat",
                on_action="Enable Repeat",
                off_action="Disable Repeat",
            )
        )

    async_add_entities(entities)


class BarcoDowserSwitch(BarcoProjectorEntity, SwitchEntity):
    """The mechanical dowser; on means open (light on screen)."""

    _attr_translation_key = "dowser"
    _attr_icon = "mdi:camera-iris"

    def __init__(self, coordinator, entry) -> None:
        """Initialise the dowser switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_dowser"

    @property
    def is_on(self) -> bool | None:
        """Return True when the dowser is open."""
        shutter = self.coordinator.data.shutter
        if shutter is None:
            return None
        return shutter == SHUTTER_OPEN

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open the dowser."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the dowser."""
        await self._set(False)

    async def _set(self, open_shutter: bool) -> None:
        try:
            await self.coordinator.projector.async_set_shutter(open_shutter)
        except BarcoError as err:
            raise HomeAssistantError(f"Setting the dowser failed: {err}") from err
        await self.coordinator.async_request_refresh()
        async_call_later(self.hass, 4, self._delayed_refresh)

    async def _delayed_refresh(self, _now) -> None:
        await self.coordinator.async_request_refresh()


class BarcoSleepSwitch(BarcoProjectorEntity, SwitchEntity):
    """Sleep (energy saving) mode; supported on DP2K-10S and 10Sx."""

    _attr_translation_key = "sleep_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sleep"

    def __init__(self, coordinator, entry) -> None:
        """Initialise the sleep switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_sleep"

    @property
    def available(self) -> bool:
        """Hide the switch when the projector does not answer the command."""
        return super().available and "sleep" not in self.coordinator.unsupported

    @property
    def is_on(self) -> bool | None:
        """Return True when the projector is asleep."""
        return self.coordinator.data.sleep

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Put the projector to sleep."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Wake the projector."""
        await self._set(False)

    async def _set(self, sleep: bool) -> None:
        try:
            await self.coordinator.projector.async_set_sleep(sleep)
        except BarcoError as err:
            raise HomeAssistantError(f"Setting sleep mode failed: {err}") from err
        await self.coordinator.async_request_refresh()


class IcmpToggleSwitch(BarcoMediaBlockEntity, SwitchEntity):
    """An optimistic ICMP switch with separate on and off actions."""

    def __init__(self, icmp, entry, key: str, on_action: str, off_action: str) -> None:
        """Initialise the switch."""
        super().__init__(icmp, entry)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._on_action = on_action
        self._off_action = off_action
        self._attr_is_on = False

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Make the optimistic nature of this entity visible."""
        return {"state_is_optimistic": True}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the enable action."""
        await self._send(self._on_action, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the disable action."""
        await self._send(self._off_action, False)

    async def _send(self, action: str, state: bool) -> None:
        try:
            await self._icmp.async_player(action)
        except IcmpError as err:
            raise HomeAssistantError(f"ICMP command '{action}' failed: {err}") from err
        self._attr_is_on = state
        self.async_write_ha_state()
