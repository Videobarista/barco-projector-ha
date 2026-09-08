"""Button entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BarcoConfigEntry
from .entity import BarcoMediaBlockEntity, BarcoProjectorEntity
from .icmp import IcmpError
from .protocol import (
    CMD_LENS_FOCUS,
    CMD_LENS_SHIFT,
    CMD_LENS_ZOOM,
    LENS_FOCUS_FAR,
    LENS_FOCUS_NEAR,
    LENS_SHIFT_DOWN,
    LENS_SHIFT_LEFT,
    LENS_SHIFT_RIGHT,
    LENS_SHIFT_UP,
    LENS_ZOOM_IN,
    LENS_ZOOM_OUT,
    BarcoError,
)

LENS_BUTTONS: tuple[tuple[str, bytes, int, str], ...] = (
    ("focus_near", CMD_LENS_FOCUS, LENS_FOCUS_NEAR, "mdi:image-filter-center-focus"),
    ("focus_far", CMD_LENS_FOCUS, LENS_FOCUS_FAR, "mdi:image-filter-center-focus"),
    ("zoom_in", CMD_LENS_ZOOM, LENS_ZOOM_IN, "mdi:magnify-plus"),
    ("zoom_out", CMD_LENS_ZOOM, LENS_ZOOM_OUT, "mdi:magnify-minus"),
    ("shift_up", CMD_LENS_SHIFT, LENS_SHIFT_UP, "mdi:arrow-up"),
    ("shift_down", CMD_LENS_SHIFT, LENS_SHIFT_DOWN, "mdi:arrow-down"),
    ("shift_left", CMD_LENS_SHIFT, LENS_SHIFT_LEFT, "mdi:arrow-left"),
    ("shift_right", CMD_LENS_SHIFT, LENS_SHIFT_RIGHT, "mdi:arrow-right"),
)

ICMP_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("icmp_play_scheduled_show", "Play Scheduled Show", "mdi:calendar-play"),
    ("icmp_emergency_stop", "Emergency Stop", "mdi:stop-circle"),
    ("icmp_jump_to_clip_end", "Jump To Clip End", "mdi:skip-forward"),
    ("icmp_recover", "Recover", "mdi:backup-restore"),
    ("icmp_recover_and_play", "Recover And Play", "mdi:play-protected-content"),
    ("icmp_ignore_recovery", "Ignore Recovery", "mdi:close-circle-outline"),
    ("icmp_clear", "Clear", "mdi:eraser"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    data = entry.runtime_data
    entities: list[ButtonEntity] = [
        BarcoLensButton(data.coordinator, entry, key, command, direction, icon)
        for key, command, direction, icon in LENS_BUTTONS
    ]
    if data.icmp is not None:
        entities.extend(
            IcmpActionButton(data.icmp, entry, key, action, icon)
            for key, action, icon in ICMP_BUTTONS
        )
    async_add_entities(entities)


class BarcoLensButton(BarcoProjectorEntity, ButtonEntity):
    """One step of lens focus, zoom or shift."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, key, command, direction, icon) -> None:
        """Initialise the lens button."""
        super().__init__(coordinator, entry)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._command = command
        self._direction = direction

    async def async_press(self) -> None:
        """Send one lens step."""
        try:
            await self.coordinator.projector.async_lens(self._command, self._direction)
        except BarcoError as err:
            raise HomeAssistantError(f"Lens command failed: {err}") from err


class IcmpActionButton(BarcoMediaBlockEntity, ButtonEntity):
    """A one-shot PLAYER action on the ICMP."""

    def __init__(self, icmp, entry, key: str, action: str, icon: str) -> None:
        """Initialise the ICMP button."""
        super().__init__(icmp, entry)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._action = action

    async def async_press(self) -> None:
        """Send the action."""
        try:
            await self._icmp.async_player(self._action)
        except IcmpError as err:
            raise HomeAssistantError(
                f"ICMP command '{self._action}' failed: {err}"
            ) from err
