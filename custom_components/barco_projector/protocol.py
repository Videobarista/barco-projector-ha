"""Client for the Barco LCD/DLP protocol used by DP/DP2K cinema projectors.

The protocol is a byte framed request/response protocol, originally designed
for RS232 and later exposed over TCP.  Framing::

    \\xfe <address> <command bytes> [<data bytes>] <checksum> \\xff

The checksum is ``(address + command + data) modulo 256``.  Any command, data
or checksum byte equal to \\x80, \\xfe or \\xff is escaped on the wire.

Communication is strictly blocking: one request at a time, the projector never
talks on its own initiative.  Every request is answered with an acknowledge
frame, followed by an answer frame for read commands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

_LOGGER = logging.getLogger(__name__)

START: Final = 0xFE
STOP: Final = 0xFF
ESCAPE: Final = 0x80

ACK: Final = b"\x00\x06"
NACK: Final = b"\x00\x15"

# --- command identifiers -------------------------------------------------
CMD_LAMP_WRITE: Final = b"\x76\x1a"
CMD_LAMP_READ: Final = b"\x76\x9a"
CMD_SHUTTER_OPEN: Final = b"\x22\x42"
CMD_SHUTTER_CLOSE: Final = b"\x23\x42"
CMD_SHUTTER_READ: Final = b"\x21\x42"
CMD_MACRO_EXECUTE: Final = b"\xe8\x81"
CMD_MACRO_READ: Final = b"\xe8\x01"
CMD_BUTTON_READ_MACRO: Final = b"\xe8\x05"
CMD_ERRORS_READ: Final = b"\x81\x04\x17"
CMD_SLEEP_READ: Final = b"\x67\x01"
CMD_SLEEP_WRITE: Final = b"\x66"
CMD_AWAKE_WRITE: Final = b"\x65"
CMD_LENS_SHIFT: Final = b"\xf4\x81"
CMD_LENS_ZOOM: Final = b"\xf4\x82"
CMD_LENS_FOCUS: Final = b"\xf4\x83"

LENS_SHIFT_UP: Final = 0x00
LENS_SHIFT_DOWN: Final = 0x01
LENS_SHIFT_LEFT: Final = 0x02
LENS_SHIFT_RIGHT: Final = 0x03
LENS_ZOOM_IN: Final = 0x00
LENS_ZOOM_OUT: Final = 0x01
LENS_FOCUS_NEAR: Final = 0x00
LENS_FOCUS_FAR: Final = 0x01


class BarcoError(Exception):
    """Base error for the Barco protocol."""


class BarcoConnectionError(BarcoError):
    """Raised when the projector cannot be reached."""


class BarcoNotAcknowledged(BarcoError):
    """Raised when the projector rejects a command (NACK)."""


class BarcoProtocolError(BarcoError):
    """Raised on malformed frames."""


def _escape(payload: bytes) -> bytes:
    """Escape the bytes that may not appear literally inside a frame."""
    out = bytearray()
    for byte in payload:
        if byte == 0x80:
            out += b"\x80\x00"
        elif byte == 0xFE:
            out += b"\x80\x7e"
        elif byte == 0xFF:
            out += b"\x80\x7f"
        else:
            out.append(byte)
    return bytes(out)


def _unescape(payload: bytes) -> bytes:
    """Reverse :func:`_escape`."""
    out = bytearray()
    index = 0
    length = len(payload)
    while index < length:
        byte = payload[index]
        if byte == ESCAPE and index + 1 < length:
            nxt = payload[index + 1]
            if nxt == 0x00:
                out.append(0x80)
            elif nxt == 0x7E:
                out.append(0xFE)
            elif nxt == 0x7F:
                out.append(0xFF)
            else:  # not a known escape sequence, keep both bytes
                out.append(byte)
                out.append(nxt)
            index += 2
            continue
        out.append(byte)
        index += 1
    return bytes(out)


def build_frame(address: int, command: bytes, data: bytes = b"") -> bytes:
    """Build a complete frame for ``command``."""
    body = command + data
    checksum = (address + sum(body)) & 0xFF
    return (
        bytes([START])
        + _escape(bytes([address]))
        + _escape(body)
        + _escape(bytes([checksum]))
        + bytes([STOP])
    )


def parse_frame(raw: bytes) -> tuple[int, bytes]:
    """Return ``(address, payload)`` for a raw frame including start/stop."""
    start = raw.rfind(bytes([START]))
    if start == -1 or not raw.endswith(bytes([STOP])):
        raise BarcoProtocolError(f"malformed frame: {raw.hex(' ')}")
    content = _unescape(raw[start + 1 : -1])
    if len(content) < 3:
        raise BarcoProtocolError(f"frame too short: {raw.hex(' ')}")
    address = content[0]
    payload = content[1:-1]
    checksum = content[-1]
    if (address + sum(payload)) & 0xFF != checksum:
        # Barco's own documentation contains at least one example with a
        # miscalculated checksum, so do not throw the answer away over it.
        _LOGGER.warning("Checksum mismatch in frame %s", raw.hex(" "))
    return address, payload


def c_string(value: str) -> bytes:
    """Encode ``value`` as a NULL terminated C string."""
    return value.encode("ascii", errors="ignore") + b"\x00"


def split_c_strings(payload: bytes) -> list[str]:
    """Split a payload of concatenated C strings."""
    parts = payload.split(b"\x00")
    return [part.decode("ascii", errors="replace") for part in parts if part]


class BarcoClient:
    """Maintain a single TCP connection to the projector."""

    def __init__(
        self,
        host: str,
        port: int,
        address: int = 0x00,
        timeout: float = 8.0,
    ) -> None:
        """Initialise the client."""
        self.host = host
        self.port = port
        self.address = address
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return whether a socket is currently open."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        """Open the connection (no-op when already connected)."""
        async with self._lock:
            await self._ensure_connected()

    async def async_close(self) -> None:
        """Close the connection."""
        async with self._lock:
            await self._close()

    async def _ensure_connected(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            self._reader = self._writer = None
            raise BarcoConnectionError(
                f"cannot connect to {self.host}:{self.port}: {err}"
            ) from err

    async def _close(self) -> None:
        writer = self._writer
        self._reader = self._writer = None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Error while closing the connection: %s", err)

    async def async_request(
        self, command: bytes, data: bytes = b"", *, expect_answer: bool = False
    ) -> bytes:
        """Send a command and return the answer payload (without command echo).

        Series 2 projectors drop idle sockets after 15 minutes, so a failed
        attempt is retried once on a fresh connection.
        """
        async with self._lock:
            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    await self._ensure_connected()
                    return await self._transact(command, data, expect_answer)
                except BarcoNotAcknowledged:
                    raise
                except (
                    OSError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                    asyncio.TimeoutError,
                    BarcoProtocolError,
                    BarcoConnectionError,
                ) as err:
                    last_error = err
                    await self._close()
                    if attempt == 2:
                        break
                    _LOGGER.debug("Retrying %s after %s", command.hex(), err)
            raise BarcoConnectionError(
                f"communication with {self.host}:{self.port} failed: {last_error}"
            ) from last_error

    async def _transact(
        self, command: bytes, data: bytes, expect_answer: bool
    ) -> bytes:
        if self._writer is None:
            raise BarcoConnectionError("not connected")
        frame = build_frame(self.address, command, data)
        _LOGGER.debug("TX %s", frame.hex(" "))
        self._writer.write(frame)
        await self._writer.drain()

        _, payload = await self._read_frame()
        if payload == NACK:
            raise BarcoNotAcknowledged(f"command {command.hex()} not acknowledged")
        if payload != ACK:
            # Some firmware answers straight away; treat it as the answer.
            return self._strip_echo(command, payload)
        if not expect_answer:
            return b""
        _, payload = await self._read_frame()
        return self._strip_echo(command, payload)

    async def _read_frame(self) -> tuple[int, bytes]:
        if self._reader is None:
            raise BarcoConnectionError("not connected")
        raw = await asyncio.wait_for(
            self._reader.readuntil(bytes([STOP])), self.timeout
        )
        _LOGGER.debug("RX %s", raw.hex(" "))
        return parse_frame(raw)

    @staticmethod
    def _strip_echo(command: bytes, payload: bytes) -> bytes:
        if payload.startswith(command):
            return payload[len(command) :]
        return payload


class BarcoProjector:
    """High level projector commands built on :class:`BarcoClient`."""

    def __init__(self, client: BarcoClient) -> None:
        """Initialise with a connected or connectable client."""
        self.client = client

    async def async_close(self) -> None:
        """Close the underlying connection."""
        await self.client.async_close()

    # --- lamp ------------------------------------------------------------
    async def async_get_lamp(self) -> bool:
        """Return True when the lamp/light source is on."""
        answer = await self.client.async_request(CMD_LAMP_READ, expect_answer=True)
        if not answer:
            raise BarcoProtocolError("empty lamp status answer")
        return answer[0] == 0x01

    async def async_set_lamp(self, turn_on: bool) -> None:
        """Switch the lamp on or off."""
        await self.client.async_request(
            CMD_LAMP_WRITE, bytes([0x01 if turn_on else 0x00])
        )

    # --- dowser ----------------------------------------------------------
    async def async_get_shutter(self) -> int:
        """Return the dowser position (0 closed, 1 open, 2 undetermined)."""
        answer = await self.client.async_request(CMD_SHUTTER_READ, expect_answer=True)
        if not answer:
            raise BarcoProtocolError("empty shutter status answer")
        return answer[0]

    async def async_set_shutter(self, open_shutter: bool) -> None:
        """Open or close the dowser."""
        command = CMD_SHUTTER_OPEN if open_shutter else CMD_SHUTTER_CLOSE
        await self.client.async_request(command, b"\x00")

    # --- macros ----------------------------------------------------------
    async def async_execute_macro(self, name: str) -> None:
        """Execute a macro by name."""
        await self.client.async_request(CMD_MACRO_EXECUTE, c_string(name))

    async def async_get_last_macro(self) -> str | None:
        """Return the name of the last executed macro."""
        answer = await self.client.async_request(CMD_MACRO_READ, expect_answer=True)
        names = split_c_strings(answer)
        return names[0] if names else None

    async def async_get_macro_buttons(self, last: int) -> list[str]:
        """Return the macro names bound to keypad buttons 1..last."""
        names: list[str] = []
        try:
            answer = await self.client.async_request(
                CMD_BUTTON_READ_MACRO, bytes([0x01, last]), expect_answer=True
            )
            # Answer repeats the "from" and "to" button numbers first.
            names = split_c_strings(answer[2:])
        except (BarcoNotAcknowledged, BarcoProtocolError):
            names = []

        if names:
            return _dedupe(names)

        for button in range(1, last + 1):
            try:
                answer = await self.client.async_request(
                    CMD_BUTTON_READ_MACRO, bytes([button]), expect_answer=True
                )
            except (BarcoNotAcknowledged, BarcoProtocolError):
                continue
            found = split_c_strings(answer[1:])
            names.extend(found)
        return _dedupe(names)

    # --- diagnostics -----------------------------------------------------
    async def async_get_error_counts(self) -> tuple[int, int, int]:
        """Return (notifications, warnings, errors); series 2 only."""
        answer = await self.client.async_request(CMD_ERRORS_READ, expect_answer=True)
        if len(answer) < 12:
            raise BarcoProtocolError("short error count answer")
        values = [
            int.from_bytes(answer[index : index + 4], "big") for index in (0, 4, 8)
        ]
        return values[0], values[1], values[2]

    # --- sleep mode (DP2K-10S / 10Sx) ------------------------------------
    async def async_get_sleep(self) -> bool:
        """Return True when the projector is in sleep (energy saving) mode."""
        answer = await self.client.async_request(CMD_SLEEP_READ, expect_answer=True)
        if not answer:
            raise BarcoProtocolError("empty sleep mode answer")
        return answer[0] == 0x00

    async def async_set_sleep(self, sleep: bool) -> None:
        """Put the projector to sleep or wake it up."""
        await self.client.async_request(CMD_SLEEP_WRITE if sleep else CMD_AWAKE_WRITE)

    # --- lens ------------------------------------------------------------
    async def async_lens(self, command: bytes, direction: int) -> None:
        """Send a lens focus/zoom/shift step."""
        await self.client.async_request(command, bytes([direction]))

    # --- raw -------------------------------------------------------------
    async def async_send_raw(
        self, command: bytes, data: bytes = b"", *, expect_answer: bool = False
    ) -> bytes:
        """Send an arbitrary command; escaping and checksum are handled."""
        return await self.client.async_request(
            command, data, expect_answer=expect_answer
        )


def _dedupe(names: list[str]) -> list[str]:
    """Return the unique, non-empty names in their original order."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        clean = name.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
