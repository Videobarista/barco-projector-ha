r"""UDP broadcast discovery for Barco digital cinema projectors.

Projectors answer a single byte datagram ('?', \x3f) sent to port 0xA001 with
an array of NULL terminated key=value strings: hostname, ip-address,
mac-address and type. Series 1 DP90 and DP100 leave out the type, series 2
projectors leave out the MAC address.

Discovery is best effort. A broadcast does not always reach another VLAN, and
some container setups block it entirely, so every failure here is logged at
debug level and the caller falls back to manual entry.

Anyone on the network can answer a broadcast, so the answers are treated as
untrusted: the address is taken from the sender rather than from the answer,
text fields are cleaned and capped, and only a limited number of answers is
kept. The user still confirms the address, and it is tested before saving.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import socket

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .protocol import clean_text

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 0xA001  # 40961
DISCOVERY_PAYLOAD = b"\x3f"
DISCOVERY_TIMEOUT = 2.5
# Answers kept per broadcast; a real network holds a handful of projectors.
MAX_ANSWERS = 16
# Longest hostname or model name kept from an answer.
MAX_FIELD_LENGTH = 64


@dataclass
class DiscoveredProjector:
    """A projector that answered the broadcast."""

    host: str
    hostname: str | None = None
    model: str | None = None

    @property
    def label(self) -> str:
        """Return a human readable one-line description."""
        label = f"{self.model or 'Barco projector'} - {self.host}"
        if self.hostname:
            label += f" ({self.hostname})"
        return label


def parse_answer(data: bytes) -> dict[str, str]:
    """Return the key=value pairs of an answer, with cleaned and capped values.

    The MAC address is left out: nothing uses it, so it is not kept or logged.
    """
    values: dict[str, str] = {}
    for part in data.split(b"\x00"):
        key, separator, value = part.decode("ascii", errors="replace").partition("=")
        key = key.strip().lower()
        if not separator or key not in ("hostname", "ip-address", "type"):
            continue
        cleaned = clean_text(value, MAX_FIELD_LENGTH)
        if cleaned is not None:
            values[key] = cleaned
    return values


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect the answers to the discovery broadcast."""

    def __init__(self, found: dict[str, DiscoveredProjector]) -> None:
        """Initialise with the dict to fill."""
        self._found = found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Parse one answer."""
        host = addr[0]
        if host not in self._found and len(self._found) >= MAX_ANSWERS:
            _LOGGER.debug("Ignoring discovery answer from %s: enough answers", host)
            return
        values = parse_answer(data)
        if values.get("ip-address", host) != host:
            _LOGGER.debug(
                "Discovery answer from %s names %s; using the sender address",
                host,
                values["ip-address"],
            )
        self._found[host] = DiscoveredProjector(
            host=host,
            hostname=values.get("hostname"),
            model=values.get("type"),
        )
        _LOGGER.debug("Discovery answer from %s (model %s)", host, values.get("type"))

    def error_received(self, exc: Exception) -> None:
        """Log socket errors instead of raising them."""
        _LOGGER.debug("Discovery socket error: %s", exc)


async def _async_broadcast_addresses(hass: HomeAssistant) -> list[str]:
    """Return the broadcast addresses of the enabled interfaces."""
    try:
        from homeassistant.components import network

        addresses = await network.async_get_ipv4_broadcast_addresses(hass)
    except (HomeAssistantError, OSError, ValueError) as err:
        _LOGGER.debug("Falling back to the global broadcast address: %s", err)
        return ["255.255.255.255"]
    return [str(address) for address in addresses] or ["255.255.255.255"]


async def async_discover(
    hass: HomeAssistant, timeout: float = DISCOVERY_TIMEOUT
) -> list[DiscoveredProjector]:
    """Broadcast a discovery request and return the projectors that answer.

    The socket listens on a random port for ``timeout`` seconds and is then
    closed; the integration keeps no port open outside a configuration form.
    """
    found: dict[str, DiscoveredProjector] = {}
    loop = asyncio.get_running_loop()
    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(found),
            family=socket.AF_INET,
            allow_broadcast=True,
            # All interfaces, because the answers come back on whichever
            # interface reached the projector. The port is random and the
            # socket only lives for the length of the broadcast.
            local_addr=("0.0.0.0", 0),  # noqa: S104
        )
        for address in await _async_broadcast_addresses(hass):
            try:
                transport.sendto(DISCOVERY_PAYLOAD, (address, DISCOVERY_PORT))
            except OSError as err:
                _LOGGER.debug("Cannot broadcast to %s: %s", address, err)
        await asyncio.sleep(timeout)
    except OSError as err:
        _LOGGER.debug("Discovery is not available on this host: %s", err)
    finally:
        if transport is not None:
            transport.close()

    projectors = sorted(found.values(), key=lambda item: item.host)
    _LOGGER.debug("Discovered %s projector(s)", len(projectors))
    return projectors


async def async_discover_model(hass: HomeAssistant, host: str) -> str | None:
    """Return the model reported by the projector at ``host``, if any."""
    for projector in await async_discover(hass):
        if projector.host == host:
            return projector.model
    return None
