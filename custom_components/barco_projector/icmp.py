"""Client for the Barco ICMP/ICMP-X "Automation over IP" protocol.

A plain text, fire-and-forget protocol on TCP 43748::

    TARGET.ACTION[,P1,P2...];
    CONTROL[,P1,P2...];

The server only answers when acknowledgement is enabled (``ACK,1;``), and even
then the answer is purely syntactic: it says the command was parsed, not that
the target device did anything.  There are no status queries, so everything
built on top of this client is optimistic.
"""

from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

READ_TIMEOUT = 2.0
# Bytes read per acknowledgement; anything beyond that is not needed.
REPLY_READ_SIZE = 128
# Longest command sent in one go, including several commands joined by ';'.
MAX_COMMAND_LENGTH = 1024
# Longest quoted string parameter, such as a macro name.
MAX_STRING_LENGTH = 255
# Minimum pause between two commands, so a script cannot hammer the server.
SEND_INTERVAL = 0.1
GPIO_OUTPUTS = range(1, 9)


class IcmpError(Exception):
    """Base error for the automation protocol."""


class IcmpConnectionError(IcmpError):
    """Raised when the ICMP cannot be reached."""


class IcmpNotAcknowledged(IcmpError):
    """Raised when the ICMP replies with NACK."""


class IcmpInvalidInput(IcmpError, ValueError):
    """Raised when a value cannot be sent to the ICMP as given."""


def _is_printable_ascii(value: str) -> bool:
    """Return whether every character is printable ASCII (space to tilde)."""
    return all(" " <= char <= "~" for char in value)


def validate_command(command: str) -> str:
    """Return ``command`` if it is safe to send, else raise.

    The protocol only defines printable ASCII; a line break or a character
    outside that range used to be dropped silently on the way out.
    """
    if not command:
        raise IcmpInvalidInput("a command may not be empty")
    if len(command) > MAX_COMMAND_LENGTH:
        raise IcmpInvalidInput(f"a command may be at most {MAX_COMMAND_LENGTH} characters")
    if not _is_printable_ascii(command):
        raise IcmpInvalidInput("a command may only contain printable ASCII characters")
    return command


def quote(value: str) -> str:
    """Return ``value`` as an escaped, quoted protocol string.

    Inside quotes the specification reserves only the backslash and the
    quotation mark, so ',' and ';' cannot end the parameter or the command.
    """
    if not value:
        raise IcmpInvalidInput("a text value may not be empty")
    if len(value) > MAX_STRING_LENGTH:
        raise IcmpInvalidInput(f"a text value may be at most {MAX_STRING_LENGTH} characters")
    if not _is_printable_ascii(value):
        raise IcmpInvalidInput("a text value may only contain printable ASCII characters")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def normalise_gpio_mask(mask: str) -> str:
    """Return a GPIO output list such as ``1=Up,2=Down`` in canonical form, else raise."""
    entries: dict[int, str] = {}
    for item in mask.split(","):
        output, separator, state = (part.strip() for part in item.partition("="))
        if not separator or not output.isdigit() or int(output) not in GPIO_OUTPUTS:
            raise IcmpInvalidInput(
                f"'{item.strip()}' is not an output from 1 to 8 followed by =Up or =Down"
            )
        if state.lower() not in ("up", "down"):
            raise IcmpInvalidInput(f"'{item.strip()}' must end in =Up or =Down")
        if int(output) in entries:
            raise IcmpInvalidInput(f"output {int(output)} is listed more than once")
        entries[int(output)] = state.capitalize()
    return ",".join(f"{output}={state}" for output, state in entries.items())


class IcmpClient:
    """Maintain a TCP connection to the ICMP automation server."""

    def __init__(self, host: str, port: int, timeout: float = 6.0, use_ack: bool = True) -> None:
        """Initialise the client."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.use_ack = use_ack
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._last_send = 0.0

    @property
    def connected(self) -> bool:
        """Return whether a socket is currently open."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        """Open the connection and enable acknowledgements."""
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
            raise IcmpConnectionError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        if self.use_ack:
            # The server may fall back to its default when a socket is reset.
            await self._write("ACK,1;")
            await self._read_reply()

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

    async def _write(self, command: str) -> None:
        if self._writer is None:
            raise IcmpConnectionError("not connected")
        _LOGGER.debug("ICMP TX %s", command)
        self._writer.write(command.encode("ascii"))
        await self._writer.drain()

    async def _read_reply(self) -> str | None:
        if not self.use_ack or self._reader is None:
            return None
        try:
            raw = await asyncio.wait_for(self._reader.read(REPLY_READ_SIZE), READ_TIMEOUT)
        except (TimeoutError, OSError) as err:
            _LOGGER.debug("No acknowledgement read back: %s", err)
            return None
        if not raw:
            return None
        reply = raw.decode("ascii", errors="replace").strip()
        _LOGGER.debug("ICMP RX %s", reply)
        return reply

    async def async_send(self, command: str) -> None:
        """Send a raw command; a trailing semicolon is added when missing."""
        validate_command(command)
        if not command.endswith(";"):
            command = f"{command};"
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._last_send + SEND_INTERVAL - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                await self._async_send_locked(command)
            finally:
                self._last_send = loop.time()

    async def _async_send_locked(self, command: str) -> None:
        """Send one command, retrying once on a fresh connection."""
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                await self._ensure_connected()
                await self._write(command)
                reply = await self._read_reply()
                if reply and "NACK" in reply.upper():
                    raise IcmpNotAcknowledged(f"{command} was rejected")
                return
            except IcmpNotAcknowledged:
                raise
            except (OSError, TimeoutError, IcmpConnectionError) as err:
                last_error = err
                await self._close()
                if attempt == 2:
                    break
        raise IcmpConnectionError(
            f"sending to {self.host}:{self.port} failed: {last_error}"
        ) from last_error

    # --- player ----------------------------------------------------------
    async def async_player(self, action: str, *params: str) -> None:
        """Send a PLAYER action."""
        await self._async_action("PLAYER", action, *params)

    async def async_projector(self, action: str, *params: str) -> None:
        """Send a PROJECTOR action (routed by the ICMP to the projector)."""
        await self._async_action("PROJECTOR", action, *params)

    async def async_gpio(self, action: str, *params: str) -> None:
        """Send a GPIO action."""
        await self._async_action("GPIO", action, *params)

    async def _async_action(self, target: str, action: str, *params: str) -> None:
        parts = [f"{target}.{action}", *params]
        await self.async_send(",".join(parts))
