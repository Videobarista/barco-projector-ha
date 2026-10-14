"""Tests for the Barco Cinema Projector config and options flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.barco_projector.const import (
    CONF_MEDIA_BLOCK,
    CONF_MEDIA_BLOCK_HOST,
    CONF_MEDIA_BLOCK_PORT,
    CONF_SCAN_INTERVAL_SECONDS,
    DEFAULT_NAME,
    DOMAIN,
    MANUAL_ENTRY,
    MEDIA_BLOCK_ICMP,
    MEDIA_BLOCK_NONE,
)
from custom_components.barco_projector.discovery import DiscoveredProjector
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_MODEL, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ENTRY_DATA, HOST, PORT, FakeIcmp, FakeProjector

pytestmark = pytest.mark.usefixtures("mock_setup_entry", "mock_discovery")

USER_INPUT: dict[str, Any] = dict(ENTRY_DATA)
DISCOVERED = DiscoveredProjector(host=HOST, hostname="zaal1", model="DP2K-6E")
OPTIONS_INPUT: dict[str, Any] = {
    CONF_SCAN_INTERVAL_SECONDS: 20,
    CONF_MEDIA_BLOCK: MEDIA_BLOCK_NONE,
    CONF_MEDIA_BLOCK_HOST: "",
    CONF_MEDIA_BLOCK_PORT: 43748,
}


def _default(result: ConfigFlowResult, key: str) -> Any:
    """Return the value a form field is prefilled with."""
    schema = result["data_schema"]
    assert schema is not None
    for marker in schema.schema:
        if marker == key:
            return marker.default()
    raise AssertionError(f"{key} is not on the form")


async def _start(hass: HomeAssistant) -> ConfigFlowResult:
    """Open the user step."""
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_manual_flow(hass: HomeAssistant, projector: FakeProjector) -> None:
    """Without discovery results the address is entered by hand."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {}
    assert _default(result, CONF_NAME) == DEFAULT_NAME
    assert _default(result, CONF_PORT) == PORT

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DP2K-6E"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == f"{HOST}:{PORT}"
    projector.async_close.assert_awaited()


async def test_manual_flow_cannot_connect(hass: HomeAssistant, projector: FakeProjector) -> None:
    """A projector that does not answer shows an error, and the flow recovers."""
    projector.online = False
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert _default(result, CONF_HOST) == HOST

    projector.online = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_manual_flow_strips_host(hass: HomeAssistant, projector: FakeProjector) -> None:
    """Spaces around the address do not end up in the entry."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: f"  {HOST} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == HOST


async def test_already_configured(
    hass: HomeAssistant, projector: FakeProjector, mock_config_entry: MockConfigEntry
) -> None:
    """The same address and port are not added twice, and are not contacted."""
    mock_config_entry.add_to_hass(hass)
    projector.online = False
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovered_projector(
    hass: HomeAssistant, projector: FakeProjector, mock_discovery: AsyncMock
) -> None:
    """Picking a discovered projector prefills the form and stores its model."""
    mock_discovery.return_value = [DISCOVERED]
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick"
    assert _default(result, CONF_DEVICE) == HOST

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DEVICE: HOST})
    assert result["step_id"] == "manual"
    assert _default(result, CONF_NAME) == "DP2K-6E"
    assert _default(result, CONF_HOST) == HOST

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_NAME: "Screen 1"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Screen 1"
    assert result["data"][CONF_MODEL] == "DP2K-6E"


async def test_discovered_without_type(
    hass: HomeAssistant, projector: FakeProjector, mock_discovery: AsyncMock
) -> None:
    """A series 1 projector reports no type, so its hostname becomes the name."""
    mock_discovery.return_value = [DiscoveredProjector(host=HOST, hostname="dp100")]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DEVICE: HOST})
    assert _default(result, CONF_NAME) == "dp100"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MODEL not in result["data"]


async def test_discovered_other_address(
    hass: HomeAssistant, projector: FakeProjector, mock_discovery: AsyncMock
) -> None:
    """The last option of the list leads to an empty form."""
    mock_discovery.return_value = [DISCOVERED]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE: MANUAL_ENTRY}
    )
    assert result["step_id"] == "manual"
    assert _default(result, CONF_HOST) == ""
    assert _default(result, CONF_NAME) == DEFAULT_NAME

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.0.2.20"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MODEL not in result["data"]


async def test_discovery_skips_configured(
    hass: HomeAssistant,
    projector: FakeProjector,
    mock_discovery: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A projector that is already set up is not offered again."""
    mock_config_entry.add_to_hass(hass)
    mock_discovery.return_value = [DISCOVERED]
    result = await _start(hass)
    assert result["step_id"] == "manual"


async def test_icmp_flow(hass: HomeAssistant, projector: FakeProjector, icmp: FakeIcmp) -> None:
    """Choosing the ICMP adds a step, which checks the automation port."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_MEDIA_BLOCK: MEDIA_BLOCK_ICMP}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "media_block"
    assert _default(result, CONF_MEDIA_BLOCK_PORT) == 43748

    icmp.reachable = False
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MEDIA_BLOCK_HOST: "", CONF_MEDIA_BLOCK_PORT: 43748}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect_icmp"}

    icmp.reachable = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MEDIA_BLOCK_HOST: " 192.0.2.11 ", CONF_MEDIA_BLOCK_PORT: 43748}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MEDIA_BLOCK] == MEDIA_BLOCK_ICMP
    assert result["data"][CONF_MEDIA_BLOCK_HOST] == "192.0.2.11"
    assert result["data"][CONF_MEDIA_BLOCK_PORT] == 43748
    icmp.async_close.assert_awaited()


async def test_options_flow(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """The poll interval and the media block are stored as options."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _default(result, CONF_SCAN_INTERVAL_SECONDS) == 30

    result = await hass.config_entries.options.async_configure(result["flow_id"], OPTIONS_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == OPTIONS_INPUT
    assert CONF_MODEL not in mock_config_entry.data


async def test_options_flow_icmp(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, icmp: FakeIcmp
) -> None:
    """Turning the ICMP on is only saved once it answers."""
    mock_config_entry.add_to_hass(hass)
    icmp.reachable = False
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS_INPUT, CONF_MEDIA_BLOCK: MEDIA_BLOCK_ICMP}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect_icmp"}
    assert mock_config_entry.options == {}

    icmp.reachable = True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS_INPUT, CONF_MEDIA_BLOCK: MEDIA_BLOCK_ICMP}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_MEDIA_BLOCK] == MEDIA_BLOCK_ICMP


async def test_options_flow_fills_in_model(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An entry created without discovery picks up its model when the options are saved."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.barco_projector.config_flow.async_discover_model",
        new=AsyncMock(return_value="DP2K-6E"),
    ) as discover_model:
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], OPTIONS_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    discover_model.assert_awaited_once_with(hass, HOST)
    assert mock_config_entry.data[CONF_MODEL] == "DP2K-6E"
    assert mock_config_entry.options == OPTIONS_INPUT


async def test_options_flow_keeps_known_model(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An entry that knows its model does not broadcast again."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_MODEL: "DP4K-32B"}
    )
    with patch(
        "custom_components.barco_projector.config_flow.async_discover_model",
        new=AsyncMock(return_value="DP2K-6E"),
    ) as discover_model:
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], OPTIONS_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    discover_model.assert_not_awaited()
    assert mock_config_entry.data[CONF_MODEL] == "DP4K-32B"
