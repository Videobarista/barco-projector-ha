"""Tests for the Barco LCD/DLP protocol client.

The frames come from Barco's "Communication Interface Barco DP Projectors"
document and from the debug log of a DP2K-6E.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.barco_projector.protocol import (
    CMD_LAMP_READ,
    CMD_LAMP_WRITE,
    BarcoClient,
    BarcoConnectionError,
    BarcoNotAcknowledged,
    BarcoProjector,
    BarcoProtocolError,
    build_frame,
    c_string,
    parse_frame,
    split_c_strings,
)


def _hex(frame: str) -> bytes:
    """Return bytes for a frame written as in the logs."""
    return bytes.fromhex(frame.replace(" ", ""))


@pytest.mark.parametrize(
    ("address", "command", "data", "expected"),
    [
        # Barco documentation examples
        (0x01, b"\xe8\x05", b"\x02", "fe 01 e8 05 02 f0 ff"),
        (0x00, b"\x76\x9a", b"", "fe 00 76 9a 10 ff"),
        (0x01, b"\x23\x42", b"\x00", "fe 01 23 42 00 66 ff"),
        (0x01, b"\x22\x42", b"\x00", "fe 01 22 42 00 65 ff"),
        (0x01, b"\x21\x42", b"", "fe 01 21 42 64 ff"),
        (0x01, b"\xf4\x83", b"\x00", "fe 01 f4 83 00 78 ff"),
        (0x01, b"\xf4\x81", b"\x00", "fe 01 f4 81 00 76 ff"),
        (0x01, b"\xf4\x82", b"\x00", "fe 01 f4 82 00 77 ff"),
        (0x01, b"\xe8\x85", b"\x02ABC\x00", "fe 01 e8 85 02 41 42 43 00 36 ff"),
        # The document prints 91 here, leaving the address out of the sum.
        (0x01, b"\x76\x1a", b"\x01", "fe 01 76 1a 01 92 ff"),
        # Frames a DP2K-6E accepted
        (0x00, b"\x81\x04\x17", b"", "fe 00 81 04 17 9c ff"),
        (0x00, b"\xe8\x81", c_string("DCI 185"), "fe 00 e8 81 44 43 49 20 31 38 35 00 f7 ff"),
        # A checksum of fe is escaped on the wire.
        (0x00, b"\xe8\x05", b"\x01\x10", "fe 00 e8 05 01 10 80 7e ff"),
    ],
)
def test_build_frame(address: int, command: bytes, data: bytes, expected: str) -> None:
    """Frames match the documented and the field-tested bytes."""
    assert build_frame(address, command, data) == _hex(expected)


def test_escape_round_trip() -> None:
    """Every byte survives escaping and unescaping."""
    payload = bytes(range(256))
    frame = build_frame(0x00, b"\x00", payload)
    assert b"\xfe" not in frame[1:-1]
    assert b"\xff" not in frame[1:-1]
    address, parsed = parse_frame(frame)
    assert address == 0x00
    assert parsed == b"\x00" + payload


def test_parse_macro_list_from_projector() -> None:
    """The keypad macro answer of a DP2K-6E decodes to its sixteen macro names."""
    frame = _hex(
        "fe 00 e8 05 01 10 44 43 49 20 31 38 35 00 44 43 49 20 32 33 39 00 44 43 49 20 31 33 33 00 "
        "44 43 49 20 31 37 38 00 44 43 49 20 32 30 30 00 44 43 49 20 46 55 4c 4c 20 43 4f 4e 54 41 "
        "49 4e 45 52 00 44 56 49 20 31 39 32 30 20 53 43 4f 50 45 00 44 56 49 20 31 39 32 30 20 46 "
        "4c 41 54 00 44 56 49 20 37 30 32 50 20 53 43 4f 50 45 00 44 56 49 20 37 32 30 50 20 46 4c "
        "41 54 00 33 44 20 53 43 4f 50 45 20 31 39 32 30 00 33 44 20 46 4c 41 54 20 31 39 32 30 00 "
        "33 44 20 4c 69 76 65 20 31 39 32 30 00 50 41 55 5a 45 00 33 44 20 4c 69 76 65 20 37 32 30 "
        "50 00 33 44 5f 44 4f 4c 42 59 5f 53 43 4f 50 45 00 69 ff"
    )
    address, payload = parse_frame(frame)
    assert address == 0x00
    names = split_c_strings(payload[4:])
    assert len(names) == 16
    assert names[:2] == ["DCI 185", "DCI 239"]
    assert names[-1] == "3D_DOLBY_SCOPE"


def test_parse_frame_rejects_garbage() -> None:
    """Frames without framing bytes, or too short, are refused."""
    with pytest.raises(BarcoProtocolError):
        parse_frame(b"\x00\x06")
    with pytest.raises(BarcoProtocolError):
        parse_frame(b"\xfe\x00\xff")


def test_bad_checksum_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A wrong checksum is logged, not thrown away."""
    with caplog.at_level(logging.WARNING):
        _, payload = parse_frame(_hex("fe 01 76 1a 01 91 ff"))
    assert payload == b"\x76\x1a\x01"
    assert "Checksum mismatch" in caplog.text


def test_c_strings() -> None:
    """C strings are NULL terminated and split back apart."""
    assert c_string("ABC") == b"ABC\x00"
    assert split_c_strings(b"ABC\x00\x00DEF\x00") == ["ABC", "DEF"]


class FakeStream:
    """A projector on the other end of a socket, answering from a script."""

    def __init__(self, *answers: str) -> None:
        """Queue the frames the projector sends back."""
        self.reader = asyncio.StreamReader()
        for answer in answers:
            self.reader.feed_data(_hex(answer))
        self.writer = MagicMock()
        self.writer.is_closing.return_value = False
        self.writer.drain = AsyncMock()
        self.writer.wait_closed = AsyncMock()

    @property
    def sent(self) -> list[bytes]:
        """Return the frames written to the socket."""
        return [call.args[0] for call in self.writer.write.call_args_list]


def _connect(*streams: FakeStream | Exception) -> AsyncMock:
    """Return an open_connection replacement serving these streams in turn."""
    results = [
        stream if isinstance(stream, Exception) else (stream.reader, stream.writer)
        for stream in streams
    ]
    return AsyncMock(side_effect=results)


async def test_read_lamp() -> None:
    """A read waits for the acknowledge, then for the answer."""
    stream = FakeStream("fe 00 00 06 06 ff", "fe 00 76 9a 01 11 ff")
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        assert await projector.async_get_lamp() is True
        await projector.async_close()
    assert stream.sent == [build_frame(0x00, CMD_LAMP_READ)]
    stream.writer.close.assert_called_once()


async def test_write_only_waits_for_acknowledge() -> None:
    """A write returns after the acknowledge."""
    stream = FakeStream("fe 00 00 06 06 ff")
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        await projector.async_set_lamp(True)
    assert stream.sent == [build_frame(0x00, CMD_LAMP_WRITE, b"\x01")]


async def test_not_acknowledged() -> None:
    """A rejected command raises without retrying."""
    stream = FakeStream("fe 00 00 15 15 ff")
    with patch("asyncio.open_connection", _connect(stream)) as connect:
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        with pytest.raises(BarcoNotAcknowledged):
            await projector.async_set_lamp(True)
    assert connect.await_count == 1


async def test_reconnects_once() -> None:
    """A dropped socket is reopened once before giving up."""
    stream = FakeStream("fe 00 00 06 06 ff", "fe 00 21 42 01 64 ff")
    with patch("asyncio.open_connection", _connect(OSError("reset"), stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        assert await projector.async_get_shutter() == 1


async def test_unreachable() -> None:
    """A projector without power raises a connection error."""
    error = OSError(113, "No route to host")
    with patch("asyncio.open_connection", _connect(error, error)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        with pytest.raises(BarcoConnectionError):
            await projector.async_get_lamp()


async def test_error_counts() -> None:
    """The error count answer of a DP2K-6E: one notification, one error."""
    stream = FakeStream(
        "fe 00 00 06 06 ff",
        "fe 00 81 04 17 00 00 00 01 00 00 00 00 00 00 00 01 9e ff",
    )
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        assert await projector.async_get_error_counts() == (1, 0, 1)


async def test_sleep_mode_without_answer() -> None:
    """The 6E acknowledges the sleep mode read but returns no data."""
    stream = FakeStream("fe 00 00 06 06 ff", "fe 00 67 01 68 ff")
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        with pytest.raises(BarcoProtocolError):
            await projector.async_get_sleep()


async def test_last_macro_empty_after_boot() -> None:
    """Before a macro has run, macro read (1) returns no name."""
    stream = FakeStream("fe 00 00 06 06 ff", "fe 00 e8 01 e9 ff")
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        assert await projector.async_get_last_macro() is None


async def test_macro_buttons_fall_back_to_single_reads() -> None:
    """Projectors that refuse the range read are asked button by button."""
    stream = FakeStream(
        "fe 00 00 15 15 ff",  # range read refused
        "fe 00 00 06 06 ff",
        "fe 00 e8 05 01 44 43 49 20 31 38 35 00 7c ff",  # button 1: DCI 185
        "fe 00 00 15 15 ff",  # button 2: not bound
    )
    with patch("asyncio.open_connection", _connect(stream)):
        projector = BarcoProjector(BarcoClient("192.0.2.10", 43728))
        assert await projector.async_get_macro_buttons(2) == ["DCI 185"]
