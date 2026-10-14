"""Tests for setting up, running and unloading the Barco Cinema Projector integration."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.barco_projector.const import DOMAIN
from custom_components.barco_projector.coordinator import storage_key
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_MODEL,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import (
    ENTRY_ID,
    ICMP_ENTRY_DATA,
    MACROS,
    FakeIcmp,
    FakeProjector,
    stored_capabilities,
)

SERVICES = ("execute_macro", "send_raw", "send_automation", "gpio_pulse", "gpio_set")


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look an entity up by its unique ID, independent of its name."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{ENTRY_ID}_{key}")
    assert entity_id is not None, f"{platform} {key} was not created"
    return entity_id


def _state(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return the state of an entity looked up by its unique ID."""
    state = hass.states.get(_entity_id(hass, platform, key))
    assert state is not None
    return state.state


def _exists(hass: HomeAssistant, platform: str, key: str) -> bool:
    """Return whether an entity with this key is in the registry."""
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{ENTRY_ID}_{key}") is not None


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll the projector once."""
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """The entry loads, creates the device and its entities, and unloads cleanly."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ENTRY_ID)})
    assert device is not None
    assert device.manufacturer == "Barco"
    assert device.model == "Digital cinema projector"

    assert _state(hass, "media_player", "projector") == STATE_OFF
    assert _state(hass, "binary_sensor", "lamp") == STATE_OFF
    assert _state(hass, "binary_sensor", "connectivity") == STATE_ON
    assert _state(hass, "switch", "dowser") == STATE_OFF
    assert _state(hass, "sensor", "dowser_state") == "closed"
    assert _state(hass, "sensor", "errors") == "1"
    assert _state(hass, "sensor", "warnings") == "0"
    assert _state(hass, "sensor", "notifications") == "1"
    select = hass.states.get(_entity_id(hass, "select", "macro"))
    assert select is not None
    assert select.attributes["options"] == MACROS
    assert _entity_id(hass, "button", "lens_zoom_in")

    # What the projector reported is kept for a restart while it is off.
    assert hass_storage[storage_key(ENTRY_ID)]["data"] == {
        "macros": MACROS,
        "unsupported": ["sleep"],
    }

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    projector.async_close.assert_awaited()


async def test_discovered_model_on_device(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """A model found by discovery names the device."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_MODEL: "DP2K-6E"}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ENTRY_ID)})
    assert device is not None
    assert device.model == "DP2K-6E"


async def test_sleep_mode_when_supported(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """Projectors that answer the sleep mode read get the sleep switch."""
    projector.sleep_supported = True
    await _setup(hass, mock_config_entry)
    assert _state(hass, "switch", "sleep") == STATE_OFF

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: _entity_id(hass, "switch", "sleep")},
        blocking=True,
    )
    projector.async_set_sleep.assert_awaited_once_with(True)


async def test_sleep_mode_not_supported(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """The 6E acknowledges the sleep mode read without an answer: no switch."""
    await _setup(hass, mock_config_entry)
    assert not _exists(hass, "switch", "sleep")


async def test_never_answered_waits(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """A projector that has never answered keeps the entry waiting."""
    projector.online = False
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_offline_setup_from_memory(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A projector that answered before is set up while off, entities unavailable."""
    stored_capabilities(hass_storage, macros=MACROS, unsupported=["sleep"])
    projector.online = False
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert _state(hass, "media_player", "projector") == STATE_UNAVAILABLE
    assert _state(hass, "switch", "dowser") == STATE_UNAVAILABLE
    assert _state(hass, "binary_sensor", "connectivity") == STATE_OFF
    assert _state(hass, "select", "macro") == STATE_UNAVAILABLE
    assert not _exists(hass, "switch", "sleep")

    projector.online = True
    await _refresh(hass, mock_config_entry)
    assert _state(hass, "media_player", "projector") == STATE_OFF
    assert _state(hass, "binary_sensor", "connectivity") == STATE_ON
    assert _state(hass, "switch", "dowser") == STATE_OFF


async def test_goes_offline_while_running(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """Losing the projector makes the entities unavailable instead of failing."""
    await _setup(hass, mock_config_entry)
    last_seen = _state(hass, "sensor", "last_seen")

    projector.online = False
    await _refresh(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.coordinator.last_update_success
    assert _state(hass, "media_player", "projector") == STATE_UNAVAILABLE
    assert _state(hass, "binary_sensor", "connectivity") == STATE_OFF
    assert _state(hass, "sensor", "last_seen") == last_seen

    await _refresh(hass, mock_config_entry)
    assert _state(hass, "binary_sensor", "connectivity") == STATE_OFF

    projector.online = True
    await _refresh(hass, mock_config_entry)
    assert _state(hass, "binary_sensor", "connectivity") == STATE_ON
    assert _state(hass, "media_player", "projector") == STATE_OFF


async def test_unsupported_entity_removed(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A sleep switch left from a setup while the projector was off is cleaned up."""
    # Stored before the sleep mode read had been tried.
    stored_capabilities(hass_storage, macros=MACROS, unsupported=[])
    projector.online = False
    await _setup(hass, mock_config_entry)
    assert _exists(hass, "switch", "sleep")

    projector.online = True
    await _refresh(hass, mock_config_entry)
    assert not _exists(hass, "switch", "sleep")
    assert hass_storage[storage_key(ENTRY_ID)]["data"]["unsupported"] == ["sleep"]


async def test_stale_entity_removed_at_setup(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Entities an earlier version created for unanswered commands are dropped."""
    stored_capabilities(hass_storage, macros=MACROS, unsupported=["sleep"])
    mock_config_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{ENTRY_ID}_sleep", config_entry=mock_config_entry
    )
    projector.online = False
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert not _exists(hass, "switch", "sleep")


async def test_projector_controls(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """Power, dowser, macro select and lens buttons reach the projector."""
    await _setup(hass, mock_config_entry)
    media_player = _entity_id(hass, "media_player", "projector")

    await hass.services.async_call(
        "media_player", "turn_on", {ATTR_ENTITY_ID: media_player}, blocking=True
    )
    projector.async_set_lamp.assert_awaited_with(True)
    await _refresh(hass, mock_config_entry)
    assert _state(hass, "media_player", "projector") == STATE_ON

    await hass.services.async_call(
        "media_player", "turn_off", {ATTR_ENTITY_ID: media_player}, blocking=True
    )
    projector.async_set_lamp.assert_awaited_with(False)

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: _entity_id(hass, "switch", "dowser")}, blocking=True
    )
    projector.async_set_shutter.assert_awaited_with(True)
    await _refresh(hass, mock_config_entry)
    assert _state(hass, "switch", "dowser") == STATE_ON

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: _entity_id(hass, "select", "macro"), "option": "DCI 239"},
        blocking=True,
    )
    projector.async_execute_macro.assert_awaited_with("DCI 239")
    await _refresh(hass, mock_config_entry)
    assert _state(hass, "select", "macro") == "DCI 239"
    assert _state(hass, "sensor", "last_macro") == "DCI 239"

    await hass.services.async_call(
        "media_player",
        "select_source",
        {ATTR_ENTITY_ID: media_player, "source": "PAUZE"},
        blocking=True,
    )
    projector.async_execute_macro.assert_awaited_with("PAUZE")

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _entity_id(hass, "button", "lens_zoom_in")},
        blocking=True,
    )
    projector.async_lens.assert_awaited_once()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_command_while_offline(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """A command that cannot reach the projector raises a readable error."""
    await _setup(hass, mock_config_entry)
    projector.online = False
    with pytest.raises(HomeAssistantError, match="Setting the dowser failed"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: _entity_id(hass, "switch", "dowser")},
            blocking=True,
        )


async def test_actions(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """The actions are registered once and reach the projector."""
    await _setup(hass, mock_config_entry)
    media_player = _entity_id(hass, "media_player", "projector")
    for action in SERVICES:
        assert hass.services.has_service(DOMAIN, action)

    await hass.services.async_call(
        DOMAIN, "execute_macro", {ATTR_ENTITY_ID: media_player, "macro": "DCI 185"}, blocking=True
    )
    projector.async_execute_macro.assert_awaited_with("DCI 185")

    await hass.services.async_call(
        DOMAIN,
        "send_raw",
        {ATTR_ENTITY_ID: media_player, "command": "76 9a", "data": ""},
        blocking=True,
    )
    projector.async_send_raw.assert_awaited_with(b"\x76\x9a", b"")

    await hass.services.async_call(
        DOMAIN,
        "send_raw",
        {ATTR_ENTITY_ID: media_player, "command": "0x761a", "data": "01"},
        blocking=True,
    )
    projector.async_send_raw.assert_awaited_with(b"\x76\x1a", b"\x01")

    with pytest.raises(HomeAssistantError, match="not valid hex"):
        await hass.services.async_call(
            DOMAIN, "send_raw", {ATTR_ENTITY_ID: media_player, "command": "zz"}, blocking=True
        )
    with pytest.raises(HomeAssistantError, match="whole number of bytes"):
        await hass.services.async_call(
            DOMAIN, "send_raw", {ATTR_ENTITY_ID: media_player, "command": "761"}, blocking=True
        )
    with pytest.raises(HomeAssistantError, match="only works on the ICMP"):
        await hass.services.async_call(
            DOMAIN,
            "send_automation",
            {ATTR_ENTITY_ID: media_player, "command": "PLAYER.Play"},
            blocking=True,
        )


async def test_icmp(
    hass: HomeAssistant, projector: FakeProjector, icmp: FakeIcmp, hass_storage: dict[str, Any]
) -> None:
    """With an ICMP the player gets its own device, linked to the projector."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="DP2K-6E", entry_id=ENTRY_ID, data=dict(ICMP_ENTRY_DATA)
    )
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    registry = dr.async_get(hass)
    projector_device = registry.async_get_device(identifiers={(DOMAIN, ENTRY_ID)})
    icmp_device = registry.async_get_device(identifiers={(DOMAIN, f"{ENTRY_ID}_icmp")})
    assert projector_device is not None
    assert icmp_device is not None
    assert icmp_device.via_device_id == projector_device.id

    player = _entity_id(hass, "media_player", "icmp_player")
    await hass.services.async_call(
        "media_player", "media_play", {ATTR_ENTITY_ID: player}, blocking=True
    )
    icmp.async_player.assert_awaited_with("Play")
    await hass.services.async_call(
        "media_player", "media_pause", {ATTR_ENTITY_ID: player}, blocking=True
    )
    icmp.async_player.assert_awaited_with("Pause")
    await hass.services.async_call(
        "media_player", "media_play", {ATTR_ENTITY_ID: player}, blocking=True
    )
    icmp.async_player.assert_awaited_with("Resume")
    player_state = hass.states.get(player)
    assert player_state is not None
    assert player_state.state == "playing"

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: _entity_id(hass, "switch", "icmp_schedule")},
        blocking=True,
    )
    icmp.async_player.assert_awaited_with("Enable Schedule")
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _entity_id(hass, "button", "icmp_emergency_stop")},
        blocking=True,
    )
    icmp.async_player.assert_awaited_with("Emergency Stop")

    await hass.services.async_call(
        DOMAIN, "gpio_pulse", {ATTR_ENTITY_ID: player, "output": 2}, blocking=True
    )
    icmp.async_gpio.assert_awaited_with("Pulse Up", "2", "500")
    await hass.services.async_call(
        DOMAIN, "gpio_set", {ATTR_ENTITY_ID: player, "mask": "1=Up,2=Down"}, blocking=True
    )
    icmp.async_gpio.assert_awaited_with("Set Outputs", '"1=Up,2=Down"')
    await hass.services.async_call(
        DOMAIN, "execute_macro", {ATTR_ENTITY_ID: player, "macro": "2D_FLAT"}, blocking=True
    )
    icmp.async_projector.assert_awaited_with("Execute Macro", '"2D_FLAT"')
    await hass.services.async_call(
        DOMAIN,
        "send_automation",
        {ATTR_ENTITY_ID: player, "command": "PLAYER.Pause (seconds),10"},
        blocking=True,
    )
    icmp.async_send.assert_awaited_with("PLAYER.Pause (seconds),10")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    icmp.async_close.assert_awaited()


async def test_remove_entry_forgets_projector(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Deleting the entry deletes what was stored about the projector."""
    await _setup(hass, mock_config_entry)
    assert storage_key(ENTRY_ID) in hass_storage

    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert storage_key(ENTRY_ID) not in hass_storage
