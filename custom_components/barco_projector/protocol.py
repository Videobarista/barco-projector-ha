r"""Client for the Barco LCD/DLP protocol used by DP/DP2K cinema projectors.

The protocol is a byte framed request/response protocol, originally designed
for RS232 and later exposed over TCP.  Framing::

    \xfe <address> <command bytes> [<data bytes>] <checksum> \xff

The checksum is ``(address + command + data) modulo 256``.  Any command, data
or checksum byte equal to \x80, \xfe or \xff is escaped on the wire.

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

# --- limits --------------------------------------------------------------
# Longest name accepted from Home Assistant or the projector. Barco limits its
# own Pascal strings to 255 characters, and 255 is also Home Assistant's limit
# for an entity state such as the last macro.
MAX_NAME_LENGTH: Final = 255
# Raw commands: Barco command identifiers are 1 to 3 bytes; data stays small.
MAX_RAW_COMMAND_LENGTH: Final = 8
MAX_RAW_DATA_LENGTH: Final = 256
# Minimum pause between two write commands, so a script cannot hammer the
# controller (for example by pressing a lens button in a tight loop).
WRITE_INTERVAL: Final = 0.1

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


class BarcoInvalidInput(BarcoError, ValueError):
    """Raised when a value cannot be sent to the projector as given."""


def is_printable_ascii(value: str) -> bool:
    """Return whether every character is printable ASCII (space to tilde)."""
    return all(" " <= char <= "~" for char in value)


def validate_macro_name(name: str) -> str:
    """Return ``name`` if it can be sent as a macro name, else raise.

    Characters outside printable ASCII used to be dropped silently, which
    could run a different macro than the one asked for.
    """
    if not name:
        raise BarcoInvalidInput("a macro name may not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise BarcoInvalidInput(f"a macro name may be at most {MAX_NAME_LENGTH} characters")
    if not is_printable_ascii(name):
        raise BarcoInvalidInput("a macro name may only contain printable ASCII characters")
    return name


def parse_hex(value: str) -> bytes:
    """Convert hex such as ``76 1a``, ``0x761a`` or ``\\x76\\x1a`` into bytes."""
    cleaned = value.lower().replace("0x", "").replace("\\x", "").replace(",", "")
    cleaned = "".join(cleaned.split())
    if len(cleaned) % 2:
        raise BarcoInvalidInput(f"'{value}' is not a whole number of bytes")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as err:
        raise BarcoInvalidInput(f"'{value}' is not valid hex") from err


def validate_raw(command: bytes, data: bytes) -> None:
    """Raise unless ``command`` and ``data`` fit the raw command limits."""
    if not 1 <= len(command) <= MAX_RAW_COMMAND_LENGTH:
        raise BarcoInvalidInput(
            f"a command must be 1 to {MAX_RAW_COMMAND_LENGTH} bytes, got {len(command)}"
        )
    if len(data) > MAX_RAW_DATA_LENGTH:
        raise BarcoInvalidInput(f"data may be at most {MAX_RAW_DATA_LENGTH} bytes, got {len(data)}")


def clean_text(value: str, max_length: int = MAX_NAME_LENGTH) -> str | None:
    """Return text from the device without control characters, or None.

    None means the value is empty or longer than ``max_length``; a truncated
    name could point at a different macro, so it is dropped instead.
    """
    text = "".join(char for char in value if " " <= char and char != "\x7f").strip()
    if not text or len(text) > max_length:
        return None
    return text


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


def _split_frame(raw: bytes) -> tuple[int, bytes, bool]:
    """Return ``(address, payload, checksum_ok)`` for a raw frame."""
    start = raw.rfind(bytes([START]))
    if start == -1 or not raw.endswith(bytes([STOP])):
        raise BarcoProtocolError(f"malformed frame: {raw.hex(' ')}")
    content = _unescape(raw[start + 1 : -1])
    if len(content) < 3:
        raise BarcoProtocolError(f"frame too short: {raw.hex(' ')}")
    address = content[0]
    payload = content[1:-1]
    checksum_ok = (address + sum(payload)) & 0xFF == content[-1]
    return address, payload, checksum_ok


def parse_frame(raw: bytes) -> tuple[int, bytes]:
    """Return ``(address, payload)`` for a raw frame including start/stop.

    A wrong checksum is logged, not fatal: Barco's own documentation contains
    at least one example with a miscalculated checksum. TCP already protects
    the bytes in transit, so the checksum adds no security here.
    """
    address, payload, checksum_ok = _split_frame(raw)
    if not checksum_ok:
        _LOGGER.warning("Checksum mismatch in frame %s", raw.hex(" "))
    return address, payload


def c_string(value: str) -> bytes:
    """Encode ``value`` as a NULL terminated C string; it must be ASCII."""
    return value.encode("ascii") + b"\x00"


def split_c_strings(payload: bytes) -> list[str]:
    """Split a payload of concatenated C strings into clean names."""
    names: list[str] = []
    for part in payload.split(b"\x00"):
        name = clean_text(part.decode("ascii", errors="replace"))
        if name is not None:
            names.append(name)
    return names


class BarcoClient:
    """Maintain a single TCP connection to the projector."""

    def __init__(
        self,
        host: str,
        port: int,
        address: int = 0x00,
        timeout: float = 15.0,
        write_interval: float = WRITE_INTERVAL,
    ) -> None:
        """Initialise the client."""
        self.host = host
        self.port = port
        self.address = address
        self.timeout = timeout
        self.write_interval = write_interval
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._last_write = 0.0
        self._checksum_warned = False

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
        except (OSError, TimeoutError) as err:
            self._reader = self._writer = None
            raise BarcoConnectionError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        self._checksum_warned = False

    async def _close(self) -> None:
        writer = self._writer
        self._reader = self._writer = None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("Error while closing the connection: %s", err)

    async def async_request(
        self, command: bytes, data: bytes = b"", *, expect_answer: bool = False
    ) -> bytes:
        """Send a command and return the answer payload (without command echo).

        Series 2 projectors drop idle sockets after 15 minutes, so a failed
        attempt is retried once on a fresh connection.
        """
        async with self._lock:
            if not expect_answer:
                await self._pace_write()
            try:
                return await self._request(command, data, expect_answer)
            finally:
                if not expect_answer:
                    self._last_write = asyncio.get_running_loop().time()

    async def _pace_write(self) -> None:
        """Wait until ``write_interval`` has passed since the previous write."""
        wait = self._last_write + self.write_interval - asyncio.get_running_loop().time()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _request(self, command: bytes, data: bytes, expect_answer: bool) -> bytes:
        """Send one request, retrying once on a fresh connection."""
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
                TimeoutError,
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

    async def _transact(self, command: bytes, data: bytes, expect_answer: bool) -> bytes:
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
        # readuntil stops at the StreamReader limit (64 KiB), so a projector
        # that never sends a stop byte cannot make this buffer grow unbounded.
        raw = await asyncio.wait_for(self._reader.readuntil(bytes([STOP])), self.timeout)
        _LOGGER.debug("RX %s", raw.hex(" "))
        address, payload, checksum_ok = _split_frame(raw)
        if not checksum_ok:
            # Warn once per connection, so a projector with a firmware quirk
            # does not fill the log with a warning on every poll.
            level = logging.DEBUG if self._checksum_warned else logging.WARNING
            _LOGGER.log(level, "Checksum mismatch in frame %s", raw.hex(" "))
            self._checksum_warned = True
        return address, payload

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
        await self.client.async_request(CMD_LAMP_WRITE, bytes([0x01 if turn_on else 0x00]))

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
        await self.client.async_request(CMD_MACRO_EXECUTE, c_string(validate_macro_name(name)))

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
            return _dedupe(names)[:last]

        for button in range(1, last + 1):
            try:
                answer = await self.client.async_request(
                    CMD_BUTTON_READ_MACRO, bytes([button]), expect_answer=True
                )
            except (BarcoNotAcknowledged, BarcoProtocolError):
                continue
            found = split_c_strings(answer[1:])
            names.extend(found)
        return _dedupe(names)[:last]

    # --- diagnostics -----------------------------------------------------
    async def async_get_error_counts(self) -> tuple[int, int, int]:
        """Return (notifications, warnings, errors); series 2 only."""
        answer = await self.client.async_request(CMD_ERRORS_READ, expect_answer=True)
        if len(answer) < 12:
            raise BarcoProtocolError("short error count answer")
        values = [int.from_bytes(answer[index : index + 4], "big") for index in (0, 4, 8)]
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
        validate_raw(command, data)
        return await self.client.async_request(command, data, expect_answer=expect_answer)


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
