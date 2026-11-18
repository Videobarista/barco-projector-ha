"""Tests for the ICMP Automation over IP client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.barco_projector.icmp import (
    MAX_COMMAND_LENGTH,
    MAX_STRING_LENGTH,
    IcmpClient,
    IcmpInvalidInput,
    normalise_gpio_mask,
    quote,
    validate_command,
)


def test_quote_escapes() -> None:
    """Only the backslash and the quotation mark need escaping inside quotes."""
    assert quote('2D "FLAT"') == '"2D \\"FLAT\\""'
    assert quote("a\\b") == '"a\\\\b"'
    assert quote("x;PLAYER.Stop;") == '"x;PLAYER.Stop;"'


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "may not be empty"),
        ("a" * (MAX_STRING_LENGTH + 1), "at most 255"),
        ("Café", "printable ASCII"),
        ("2D_FLAT\r\nPLAYER.Stop", "printable ASCII"),
    ],
)
def test_quote_rejects(value: str, reason: str) -> None:
    """Text that the protocol does not define is refused instead of dropped."""
    with pytest.raises(IcmpInvalidInput, match=reason):
        quote(value)


def test_validate_command() -> None:
    """Commands are printable ASCII up to the length limit; ';' is allowed."""
    assert validate_command("PLAYER.Pause (seconds),10;PLAYER.Play") == (
        "PLAYER.Pause (seconds),10;PLAYER.Play"
    )
    with pytest.raises(IcmpInvalidInput, match="may not be empty"):
        validate_command("")
    with pytest.raises(IcmpInvalidInput, match="at most 1024"):
        validate_command("a" * (MAX_COMMAND_LENGTH + 1))
    with pytest.raises(IcmpInvalidInput, match="printable ASCII"):
        validate_command("PLAYER.Play\n")


@pytest.mark.parametrize(
    ("mask", "expected"),
    [
        ("1=Up,2=Down", "1=Up,2=Down"),
        ("1=up, 2 = DOWN ,8=Up", "1=Up,2=Down,8=Up"),
    ],
)
def test_gpio_mask(mask: str, expected: str) -> None:
    """Output lists are normalised to the spelling of the specification."""
    assert normalise_gpio_mask(mask) == expected


@pytest.mark.parametrize(
    ("mask", "reason"),
    [
        ("", "output from 1 to 8"),
        ("9=Up", "output from 1 to 8"),
        ("0=Up", "output from 1 to 8"),
        ("1=Sideways", "=Up or =Down"),
        ("1=Up,1=Down", "more than once"),
        ('1=Up";PLAYER.Stop;"', "=Up or =Down"),
    ],
)
def test_gpio_mask_rejects(mask: str, reason: str) -> None:
    """Anything that is not a list of outputs and states is refused."""
    with pytest.raises(IcmpInvalidInput, match=reason):
        normalise_gpio_mask(mask)


def _server(*replies: bytes) -> tuple[AsyncMock, MagicMock]:
    """Return an open_connection replacement and the writer it hands out."""
    reader = asyncio.StreamReader()
    for reply in replies:
        reader.feed_data(reply)
    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    return AsyncMock(return_value=(reader, writer)), writer


async def test_invalid_command_is_not_sent() -> None:
    """A refused command never opens a connection."""
    connect, _ = _server()
    with patch("asyncio.open_connection", connect):
        client = IcmpClient("192.0.2.11", 43748, use_ack=False)
        with pytest.raises(IcmpInvalidInput):
            await client.async_send("PLAYER.Play\r\nPLAYER.Stop")
    connect.assert_not_awaited()


async def test_commands_are_paced() -> None:
    """Two commands in a row are at least the send interval apart."""
    connect, writer = _server()
    with (
        patch("asyncio.open_connection", connect),
        patch("custom_components.barco_projector.icmp.SEND_INTERVAL", 0.2),
    ):
        client = IcmpClient("192.0.2.11", 43748, use_ack=False)
        loop = asyncio.get_running_loop()
        start = loop.time()
        await client.async_player("Play")
        await client.async_player("Pause")
        elapsed = loop.time() - start
    assert elapsed >= 0.19
    assert [call.args[0] for call in writer.write.call_args_list] == [
        b"PLAYER.Play;",
        b"PLAYER.Pause;",
    ]
