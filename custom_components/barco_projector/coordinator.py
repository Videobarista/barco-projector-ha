"""Polling coordinator for the Barco Cinema Projector integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

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

    reachable: bool = True
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
        self._reachable = True

    async def async_shutdown(self) -> None:
        """Close the socket when the entry is unloaded."""
        await super().async_shutdown()
        await self.projector.async_close()

    @property
    def last_seen(self) -> datetime | None:
        """Return when the projector last answered."""
        return self._last_seen

    async def _async_update_data(self) -> BarcoData:
        """Poll the projector, treating an unreachable one as a normal state.

        A projector that is switched off at the wall stops answering, which is
        expected rather than an error. Raising here would put a red line in the
        log on every power cycle, so the unreachable state is carried in the
        data instead and the entities go unavailable.
        """
        try:
            return await self._async_poll()
        except BarcoConnectionError as err:
            return self._async_unreachable(err)
        except BarcoError as err:
            # A malformed answer is a real anomaly, so this one does get logged.
            raise UpdateFailed(f"unexpected answer: {err}") from err

    async def _async_poll(self) -> BarcoData:
        data = BarcoData()
        data.lamp = await self.projector.async_get_lamp()
        data.shutter = await self.projector.async_get_shutter()
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
        if not self._reachable:
            _LOGGER.info("%s is answering again", self.name)
            self._reachable = True
        return data

    def _async_unreachable(self, err: Exception) -> BarcoData:
        """Return an unreachable snapshot, keeping what we already knew."""
        if self._reachable:
            _LOGGER.info(
                "%s is not answering, entities are unavailable until it returns: %s",
                self.name,
                err,
            )
        else:
            _LOGGER.debug("%s is still not answering: %s", self.name, err)
        self._reachable = False
        return BarcoData(
            reachable=False,
            macros=list(self._macros),
            last_seen=self._last_seen,
        )

    async def _read_last_macro(self) -> str | None:
        return await self.projector.async_get_last_macro()

    async def _read_macros(self) -> list[str]:
        return await self.projector.async_get_macro_buttons(MAX_MACRO_BUTTONS)

    async def _optional(self, key: str, func: Callable) -> Any:
        """Run a command that not every model supports."""
        if key in self.unsupported:
            return None
        try:
            return await func()
        except (BarcoNotAcknowledged, BarcoProtocolError) as err:
            _LOGGER.debug("%s is not supported by this projector: %s", key, err)
            self.unsupported.add(key)
            return None
