r"""UDP broadcast discovery for Barco digital cinema projectors.

Projectors answer a single byte datagram ('?', \x3f) sent to port 0xA001 with
an array of NULL terminated key=value strings: hostname, ip-address,
mac-address and type. Series 1 DP90 and DP100 leave out the type, series 2
projectors leave out the MAC address.

Discovery is best effort. A broadcast does not always reach another VLAN, and
some container setups block it entirely, so every failure here is silent and
the caller falls back to manual entry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import socket

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 0xA001  # 40961
DISCOVERY_PAYLOAD = b"\x3f"
DISCOVERY_TIMEOUT = 2.5


@dataclass
class DiscoveredProjector:
    """A projector that answered the broadcast."""

    host: str
    hostname: str | None = None
    model: str | None = None
    mac: str | None = None

    @property
    def label(self) -> str:
        """Return a human readable one-line description."""
        parts = [self.model or "Barco projector", self.host]
        if self.hostname:
            parts.append(f"({self.hostname})")
        return " - ".join(parts[:2]) + (f" {parts[2]}" if len(parts) > 2 else "")


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect the answers to the discovery broadcast."""

    def __init__(self, found: dict[str, DiscoveredProjector]) -> None:
        """Initialise with the dict to fill."""
        self._found = found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Parse one answer."""
        values: dict[str, str] = {}
        for part in data.split(b"\x00"):
            if not part:
                continue
            text = part.decode("ascii", errors="replace")
            key, separator, value = text.partition("=")
            if separator:
                values[key.strip().lower()] = value.strip()
        host = values.get("ip-address") or addr[0]
        self._found[host] = DiscoveredProjector(
            host=host,
            hostname=values.get("hostname") or None,
            model=values.get("type") or None,
            mac=values.get("mac-address") or None,
        )
        _LOGGER.debug("Discovery answer from %s: %s", addr[0], values)

    def error_received(self, exc: Exception) -> None:
        """Log socket errors instead of raising them."""
        _LOGGER.debug("Discovery socket error: %s", exc)


async def _async_broadcast_addresses(hass: HomeAssistant) -> list[str]:
    """Return the broadcast addresses of the enabled interfaces."""
    try:
        from homeassistant.components import network

        addresses = await network.async_get_ipv4_broadcast_addresses(hass)
        return [str(address) for address in addresses] or ["255.255.255.255"]
    except Exception as err:  # discovery must never break a config flow
        _LOGGER.debug("Falling back to the global broadcast address: %s", err)
        return ["255.255.255.255"]


async def async_discover(
    hass: HomeAssistant, timeout: float = DISCOVERY_TIMEOUT
) -> list[DiscoveredProjector]:
    """Broadcast a discovery request and return the projectors that answer."""
    found: dict[str, DiscoveredProjector] = {}
    loop = asyncio.get_running_loop()
    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(found),
            family=socket.AF_INET,
            allow_broadcast=True,
            local_addr=("0.0.0.0", 0),
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
