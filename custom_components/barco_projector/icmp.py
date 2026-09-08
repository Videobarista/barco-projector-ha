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


class IcmpError(Exception):
    """Base error for the automation protocol."""


class IcmpConnectionError(IcmpError):
    """Raised when the ICMP cannot be reached."""


class IcmpNotAcknowledged(IcmpError):
    """Raised when the ICMP replies with NACK."""


def quote(value: str) -> str:
    """Return ``value`` as an escaped, quoted protocol string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class IcmpClient:
    """Maintain a TCP connection to the ICMP automation server."""

    def __init__(
        self, host: str, port: int, timeout: float = 6.0, use_ack: bool = True
    ) -> None:
        """Initialise the client."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.use_ack = use_ack
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

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
        except (OSError, asyncio.TimeoutError) as err:
            self._reader = self._writer = None
            raise IcmpConnectionError(
                f"cannot connect to {self.host}:{self.port}: {err}"
            ) from err
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
        except (OSError, asyncio.TimeoutError):  # pragma: no cover
            pass

    async def _write(self, command: str) -> None:
        assert self._writer is not None
        _LOGGER.debug("ICMP TX %s", command)
        self._writer.write(command.encode("ascii", errors="ignore"))
        await self._writer.drain()

    async def _read_reply(self) -> str | None:
        if not self.use_ack or self._reader is None:
            return None
        try:
            raw = await asyncio.wait_for(self._reader.read(128), READ_TIMEOUT)
        except (asyncio.TimeoutError, OSError):
            return None
        if not raw:
            return None
        reply = raw.decode("ascii", errors="replace").strip()
        _LOGGER.debug("ICMP RX %s", reply)
        return reply

    async def async_send(self, command: str) -> None:
        """Send a raw command; a trailing semicolon is added when missing."""
        if not command.endswith(";"):
            command = f"{command};"
        async with self._lock:
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
                except (OSError, asyncio.TimeoutError, IcmpConnectionError) as err:
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
