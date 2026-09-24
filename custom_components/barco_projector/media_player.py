"""Media player entities for the Barco Cinema Projector integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import BarcoConfigEntry
from .const import (
    ATTR_COMMAND,
    ATTR_DATA,
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_MACRO,
    ATTR_MASK,
    ATTR_OUTPUT,
    SERVICE_EXECUTE_MACRO,
    SERVICE_GPIO_PULSE,
    SERVICE_GPIO_SET,
    SERVICE_SEND_AUTOMATION,
    SERVICE_SEND_RAW,
)
from .entity import BarcoMediaBlockEntity, BarcoProjectorEntity
from .icmp import IcmpError, quote
from .protocol import BarcoError

_LOGGER = logging.getLogger(__name__)

REFRESH_DELAYS = (2, 10, 30, 60)


def _hex_to_bytes(value: str) -> bytes:
    """Convert a hex string like ``76 1a`` or ``0x761a`` into bytes."""
    cleaned = value.lower().replace("0x", "").replace(",", " ").replace("\\x", " ")
    cleaned = cleaned.replace(" ", "")
    if len(cleaned) % 2:
        raise HomeAssistantError(f"'{value}' is not a whole number of bytes")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as err:
        raise HomeAssistantError(f"'{value}' is not valid hex") from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media players."""
    data = entry.runtime_data
    entities: list[MediaPlayerEntity] = [
        BarcoProjectorMediaPlayer(data.coordinator, entry)
    ]
    if data.icmp is not None:
        entities.append(BarcoIcmpMediaPlayer(data.icmp, entry))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_EXECUTE_MACRO,
        {vol.Required(ATTR_MACRO): cv.string},
        "async_execute_macro",
    )
    platform.async_register_entity_service(
        SERVICE_SEND_RAW,
        {
            vol.Required(ATTR_COMMAND): cv.string,
            vol.Optional(ATTR_DATA, default=""): cv.string,
        },
        "async_send_raw",
    )
    platform.async_register_entity_service(
        SERVICE_SEND_AUTOMATION,
        {vol.Required(ATTR_COMMAND): cv.string},
        "async_send_automation",
    )
    platform.async_register_entity_service(
        SERVICE_GPIO_PULSE,
        {
            vol.Required(ATTR_OUTPUT): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(ATTR_DURATION, default=500): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=60000)
            ),
            vol.Optional(ATTR_DIRECTION, default="up"): vol.In(["up", "down"]),
        },
        "async_gpio_pulse",
    )
    platform.async_register_entity_service(
        SERVICE_GPIO_SET,
        {vol.Required(ATTR_MASK): cv.string},
        "async_gpio_set",
    )


class BarcoProjectorMediaPlayer(BarcoProjectorEntity, MediaPlayerEntity):
    """The projector itself: power, and macros as sources."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator, entry) -> None:
        """Initialise the projector media player."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_projector"

    @property
    def state(self) -> MediaPlayerState | None:
        """Return on when the light source is running."""
        lamp = self.coordinator.data.lamp
        if lamp is None:
            return None
        if lamp:
            return MediaPlayerState.ON
        if self.coordinator.data.sleep:
            return MediaPlayerState.STANDBY
        return MediaPlayerState.OFF

    @property
    def source_list(self) -> list[str] | None:
        """Return the macros stored on the projector keypad."""
        return self.coordinator.data.macros or None

    @property
    def source(self) -> str | None:
        """Return the macro that was executed last."""
        return self.coordinator.data.last_macro

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the raw dowser position next to the state."""
        return {"dowser": self.coordinator.data.shutter}

    async def async_turn_on(self) -> None:
        """Wake the projector if needed and ignite the light source."""
        try:
            if self.coordinator.data.sleep:
                await self.coordinator.projector.async_set_sleep(False)
            await self.coordinator.projector.async_set_lamp(True)
        except BarcoError as err:
            raise HomeAssistantError(f"Turning the projector on failed: {err}") from err
        self._schedule_refresh()

    async def async_turn_off(self) -> None:
        """Extinguish the light source."""
        try:
            await self.coordinator.projector.async_set_lamp(False)
        except BarcoError as err:
            raise HomeAssistantError(f"Turning the projector off failed: {err}") from err
        self._schedule_refresh()

    async def async_select_source(self, source: str) -> None:
        """Execute the macro with this name."""
        await self.async_execute_macro(source)

    async def async_execute_macro(self, macro: str) -> None:
        """Execute a macro by name (also exposed as a service)."""
        try:
            await self.coordinator.projector.async_execute_macro(macro)
        except BarcoError as err:
            raise HomeAssistantError(f"Macro '{macro}' failed: {err}") from err
        self._schedule_refresh()

    async def async_send_raw(self, command: str, data: str = "") -> None:
        """Send an arbitrary Barco command (service)."""
        command_bytes = _hex_to_bytes(command)
        data_bytes = _hex_to_bytes(data) if data else b""
        if not command_bytes:
            raise HomeAssistantError("command may not be empty")
        try:
            await self.coordinator.projector.async_send_raw(command_bytes, data_bytes)
        except BarcoError as err:
            raise HomeAssistantError(f"Raw command failed: {err}") from err
        self._schedule_refresh()

    async def async_send_automation(self, command: str) -> None:
        """Reject automation commands on the projector entity."""
        raise HomeAssistantError(
            "send_automation only works on the ICMP media player entity"
        )

    async def async_gpio_pulse(self, output: int, duration: int, direction: str) -> None:
        """Reject GPIO commands on the projector entity."""
        raise HomeAssistantError("GPIO services only work on the ICMP entity")

    async def async_gpio_set(self, mask: str) -> None:
        """Reject GPIO commands on the projector entity."""
        raise HomeAssistantError("GPIO services only work on the ICMP entity")

    def _schedule_refresh(self) -> None:
        """Poll again shortly; lamp and dowser need seconds to settle."""
        for delay in REFRESH_DELAYS:
            async_call_later(self.hass, delay, self._delayed_refresh)

    async def _delayed_refresh(self, _now) -> None:
        await self.coordinator.async_request_refresh()


class BarcoIcmpMediaPlayer(BarcoMediaBlockEntity, MediaPlayerEntity):
    """The ICMP player; optimistic because the protocol reports no status."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )

    def __init__(self, icmp, entry) -> None:
        """Initialise the ICMP media player."""
        super().__init__(icmp, entry)
        self._attr_unique_id = f"{entry.entry_id}_icmp_player"
        self._attr_state = MediaPlayerState.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Make the optimistic nature of this entity visible."""
        return {"state_is_optimistic": True}

    async def _send(self, action: str, *params: str) -> None:
        try:
            await self._icmp.async_player(action, *params)
        except IcmpError as err:
            self._attr_available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"ICMP command '{action}' failed: {err}") from err
        self._attr_available = True

    async def async_media_play(self) -> None:
        """Start playback, or resume when the player was paused."""
        action = "Resume" if self._attr_state == MediaPlayerState.PAUSED else "Play"
        await self._send(action)
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._send("Pause")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self._send("Stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Jump to the next clip."""
        await self._send("Next")

    async def async_media_previous_track(self) -> None:
        """Jump to the previous clip."""
        await self._send("Previous")

    async def async_send_automation(self, command: str) -> None:
        """Send a raw automation command (service)."""
        try:
            await self._icmp.async_send(command)
        except IcmpError as err:
            raise HomeAssistantError(f"Automation command failed: {err}") from err

    async def async_gpio_pulse(self, output: int, duration: int, direction: str) -> None:
        """Pulse a GPIO output (service)."""
        action = "Pulse Up" if direction == "up" else "Pulse Down"
        try:
            await self._icmp.async_gpio(action, str(output), str(duration))
        except IcmpError as err:
            raise HomeAssistantError(f"GPIO pulse failed: {err}") from err

    async def async_gpio_set(self, mask: str) -> None:
        """Set GPIO outputs, e.g. ``1=Up,2=Down`` (service)."""
        try:
            await self._icmp.async_gpio("Set Outputs", quote(mask))
        except IcmpError as err:
            raise HomeAssistantError(f"GPIO set failed: {err}") from err

    async def async_execute_macro(self, macro: str) -> None:
        """Execute a projector macro through the ICMP (service)."""
        try:
            await self._icmp.async_projector("Execute Macro", quote(macro))
        except IcmpError as err:
            raise HomeAssistantError(f"Macro '{macro}' failed: {err}") from err

    async def async_send_raw(self, command: str, data: str = "") -> None:
        """Reject binary projector commands on the ICMP entity."""
        raise HomeAssistantError("send_raw only works on the projector media player")
