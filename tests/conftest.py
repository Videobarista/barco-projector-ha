"""Fixtures for the Barco Cinema Projector tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.barco_projector.const import (
    CONF_MEDIA_BLOCK,
    CONF_MEDIA_BLOCK_HOST,
    CONF_MEDIA_BLOCK_PORT,
    DOMAIN,
    MEDIA_BLOCK_ICMP,
    MEDIA_BLOCK_NONE,
)
from custom_components.barco_projector.coordinator import storage_key
from custom_components.barco_projector.icmp import IcmpConnectionError
from custom_components.barco_projector.protocol import (
    BarcoConnectionError,
    BarcoProtocolError,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

# Documentation address (RFC 5737); the macro names are the ones a DP2K-6E reported.
HOST = "192.0.2.10"
PORT = 43728
ENTRY_ID = "barco_projector_test_entry"
MACROS = ["DCI 185", "DCI 239", "DVI 1920 FLAT", "PAUZE"]

ENTRY_DATA: dict[str, Any] = {
    CONF_NAME: "DP2K-6E",
    CONF_HOST: HOST,
    CONF_PORT: PORT,
    CONF_MEDIA_BLOCK: MEDIA_BLOCK_NONE,
}

ICMP_ENTRY_DATA: dict[str, Any] = {
    **ENTRY_DATA,
    CONF_MEDIA_BLOCK: MEDIA_BLOCK_ICMP,
    CONF_MEDIA_BLOCK_HOST: "",
    CONF_MEDIA_BLOCK_PORT: 43748,
}


class FakeProjector:
    """A DP2K-6E with the lamp off and the dowser closed.

    Set ``online`` to False to make every request fail the way a projector
    without power does. Write commands are AsyncMocks so tests can inspect them.
    """

    def __init__(self) -> None:
        """Start reachable, with the lamp off."""
        self.online = True
        self.lamp = False
        self.shutter = 0
        self.last_macro: str | None = None
        self.macros = list(MACROS)
        self.sleep_supported = False
        self.async_set_lamp = AsyncMock(side_effect=self._set_lamp)
        self.async_set_shutter = AsyncMock(side_effect=self._set_shutter)
        self.async_execute_macro = AsyncMock(side_effect=self._execute_macro)
        self.async_set_sleep = AsyncMock()
        self.async_lens = AsyncMock()
        self.async_send_raw = AsyncMock(return_value=b"")
        self.async_close = AsyncMock()

    def _check(self) -> None:
        if not self.online:
            raise BarcoConnectionError(f"cannot connect to {HOST}:{PORT}: [Errno 113]")

    async def _set_lamp(self, turn_on: bool) -> None:
        self._check()
        self.lamp = turn_on

    async def _set_shutter(self, open_shutter: bool) -> None:
        self._check()
        self.shutter = 1 if open_shutter else 0

    async def _execute_macro(self, name: str) -> None:
        self._check()
        self.last_macro = name

    async def async_get_lamp(self) -> bool:
        """Lamp, read on/off."""
        self._check()
        return self.lamp

    async def async_get_shutter(self) -> int:
        """Shutter-dowser, read."""
        self._check()
        return self.shutter

    async def async_get_last_macro(self) -> str | None:
        """Macro, read (1): empty until a macro has run since the last boot."""
        self._check()
        return self.last_macro

    async def async_get_error_counts(self) -> tuple[int, int, int]:
        """Errors, read count: one notification and one error, as on the 6E."""
        self._check()
        return 1, 0, 1

    async def async_get_sleep(self) -> bool:
        """Sleep mode, read: the 6E acknowledges but sends an empty answer."""
        self._check()
        if not self.sleep_supported:
            raise BarcoProtocolError("empty sleep mode answer")
        return False

    async def async_get_macro_buttons(self, last: int) -> list[str]:
        """Button, read macro."""
        self._check()
        return list(self.macros)


class FakeIcmp:
    """An ICMP automation server that accepts every command."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Start reachable."""
        self.reachable = True
        self.connected = False
        self.async_send = AsyncMock()
        self.async_player = AsyncMock()
        self.async_projector = AsyncMock()
        self.async_gpio = AsyncMock()
        self.async_close = AsyncMock()

    async def async_connect(self) -> None:
        """Open the connection, or fail like a projector without an ICMP."""
        if not self.reachable:
            raise IcmpConnectionError(f"cannot connect to {HOST}:43748: [Errno 113]")
        self.connected = True


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def projector() -> Generator[FakeProjector]:
    """Patch the projector everywhere it is created; return the fake."""
    fake = FakeProjector()
    with (
        patch("custom_components.barco_projector.BarcoProjector", return_value=fake),
        patch("custom_components.barco_projector.config_flow.BarcoProjector", return_value=fake),
    ):
        yield fake


@pytest.fixture
def icmp() -> Generator[FakeIcmp]:
    """Patch the ICMP client everywhere it is created; return the fake."""
    fake = FakeIcmp()
    with (
        patch("custom_components.barco_projector.IcmpClient", return_value=fake),
        patch("custom_components.barco_projector.config_flow.IcmpClient", return_value=fake),
    ):
        yield fake


@pytest.fixture
def mock_discovery() -> Generator[AsyncMock]:
    """Make the discovery broadcast find nothing unless a test says otherwise."""
    with (
        patch(
            "custom_components.barco_projector.config_flow.async_discover",
            new=AsyncMock(return_value=[]),
        ) as discover,
        patch(
            "custom_components.barco_projector.config_flow.async_discover_model",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield discover


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry, for config flow tests."""
    with patch(
        "custom_components.barco_projector.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the projector."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="DP2K-6E",
        unique_id=f"{HOST}:{PORT}",
        entry_id=ENTRY_ID,
        data=dict(ENTRY_DATA),
    )


def stored_capabilities(
    hass_storage: dict[str, Any], *, macros: list[str], unsupported: list[str]
) -> None:
    """Pretend the projector answered on an earlier run."""
    key = storage_key(ENTRY_ID)
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"macros": macros, "unsupported": unsupported},
    }
