"""Diagnostics support for the Barco Cinema Projector integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant

from . import BarcoConfigEntry
from .const import CONF_MEDIA_BLOCK_HOST

# Diagnostics end up in public issue reports, so leave out where the projector
# lives on the network and what it was called.
TO_REDACT = {CONF_HOST, CONF_MEDIA_BLOCK_HOST, CONF_NAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BarcoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    coordinator = data.coordinator
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "answered_before": coordinator.answered_before,
            "unsupported_commands": sorted(coordinator.unsupported),
            "update_interval": str(coordinator.update_interval),
            "data": asdict(coordinator.data) if coordinator.data else None,
        },
        "media_block": {
            "configured": data.icmp is not None,
            "connected": data.icmp.connected if data.icmp else None,
        },
    }
