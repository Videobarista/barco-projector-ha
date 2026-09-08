"""Diagnostics support for the Barco Cinema Projector integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import BarcoConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BarcoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    coordinator = data.coordinator
    return {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "unsupported_commands": sorted(coordinator.unsupported),
            "update_interval": str(coordinator.update_interval),
            "data": asdict(coordinator.data) if coordinator.data else None,
        },
        "media_block": {
            "configured": data.icmp is not None,
            "connected": data.icmp.connected if data.icmp else None,
        },
    }
