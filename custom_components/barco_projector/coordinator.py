"""Polling coordinator for the Barco Cinema Projector integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MACRO_REFRESH_EVERY, MAX_MACRO_BUTTONS
from .protocol import (
    BarcoConnectionError,
    BarcoError,
    BarcoNotAcknowledged,
    BarcoProjector,
    BarcoProtocolError,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class BarcoData:
    """Snapshot of everything we poll from the projector."""

    lamp: bool | None = None
    shutter: int | None = None
    last_macro: str | None = None
    notifications: int | None = None
    warnings: int | None = None
    errors: int | None = None
    sleep: bool | None = None
    macros: list[str] = field(default_factory=list)
    last_seen: datetime | None = None


class BarcoCoordinator(DataUpdateCoordinator[BarcoData]):
    """Poll the projector over the blocking Barco protocol."""

    def __init__(
        self,
        hass: HomeAssistant,
        projector: BarcoProjector,
        scan_interval: int,
        entry_title: str,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry_title}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.projector = projector
        self.unsupported: set[str] = set()
        self._poll_count = 0
        self._macros: list[str] = []
        self._last_seen: datetime | None = None

    async def async_shutdown(self) -> None:
        """Close the socket when the entry is unloaded."""
        await super().async_shutdown()
        await self.projector.async_close()

    async def _async_update_data(self) -> BarcoData:
        data = BarcoData()
        try:
            data.lamp = await self.projector.async_get_lamp()
            data.shutter = await self.projector.async_get_shutter()
        except BarcoConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except BarcoError as err:
            raise UpdateFailed(f"unexpected answer: {err}") from err

        data.last_macro = await self._optional("last_macro", self._read_last_macro)
        counts = await self._optional("errors", self.projector.async_get_error_counts)
        if counts is not None:
            data.notifications, data.warnings, data.errors = counts
        data.sleep = await self._optional("sleep", self.projector.async_get_sleep)

        if self._poll_count % MACRO_REFRESH_EVERY == 0 or not self._macros:
            macros = await self._optional("macros", self._read_macros)
            if macros:
                self._macros = macros
        data.macros = list(self._macros)

        self._poll_count += 1
        self._last_seen = dt_util.utcnow()
        data.last_seen = self._last_seen
        return data

    @property
    def last_seen(self) -> datetime | None:
        """Return when the projector last answered."""
        return self._last_seen

    async def _read_last_macro(self) -> str | None:
        return await self.projector.async_get_last_macro()

    async def _read_macros(self) -> list[str]:
        return await self.projector.async_get_macro_buttons(MAX_MACRO_BUTTONS)

    async def _optional(self, key, func):
        """Run a command that not every model supports."""
        if key in self.unsupported:
            return None
        try:
            return await func()
        except (BarcoNotAcknowledged, BarcoProtocolError) as err:
            _LOGGER.debug("%s is not supported by this projector: %s", key, err)
            self.unsupported.add(key)
            return None
        except BarcoConnectionError as err:
            raise UpdateFailed(str(err)) from err
