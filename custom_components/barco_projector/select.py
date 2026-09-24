"""Select entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import BarcoConfigEntry
from .entity import BarcoProjectorEntity
from .protocol import BarcoError

REFRESH_DELAYS = (2, 10, 30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the macro select."""
    async_add_entities([BarcoMacroSelect(entry.runtime_data.coordinator, entry)])


class BarcoMacroSelect(BarcoProjectorEntity, SelectEntity):
    """The macros on the projector keypad, as a dropdown.

    The Barco protocol has no command to pick an input or a format directly:
    source, aspect ratio, lens position and processing all live inside a macro.
    Running a macro is therefore the way to switch between HDMI, DVI, SDI and
    the media block.
    """

    _attr_translation_key = "macro"
    _attr_icon = "mdi:script-text-play"

    def __init__(self, coordinator, entry) -> None:
        """Initialise the macro select."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_macro"

    @property
    def options(self) -> list[str]:
        """Return the macros bound to the keypad buttons."""
        return self.coordinator.data.macros

    @property
    def current_option(self) -> str | None:
        """Return the last executed macro, if it is one of the options."""
        last = self.coordinator.data.last_macro
        if last and last in self.coordinator.data.macros:
            return last
        return None

    async def async_select_option(self, option: str) -> None:
        """Execute the selected macro."""
        try:
            await self.coordinator.projector.async_execute_macro(option)
        except BarcoError as err:
            raise HomeAssistantError(f"Macro '{option}' failed: {err}") from err
        for delay in REFRESH_DELAYS:
            async_call_later(self.hass, delay, self._delayed_refresh)

    async def _delayed_refresh(self, _now) -> None:
        await self.coordinator.async_request_refresh()
