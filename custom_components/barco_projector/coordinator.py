"""Polling coordinator for the Barco Cinema Projector integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CAPABILITY_ENTITIES,
    CAPABILITY_ERRORS,
    CAPABILITY_LAST_MACRO,
    CAPABILITY_MACROS,
    CAPABILITY_SLEEP,
    DOMAIN,
    FOLLOWUP_REFRESH_DELAYS,
    MACRO_REFRESH_EVERY,
    MAX_MACRO_BUTTONS,
    REQUEST_REFRESH_COOLDOWN,
    STORAGE_VERSION,
)
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


def storage_key(entry_id: str) -> str:
    """Return the storage key for what a projector reported on earlier runs."""
    return f"{DOMAIN}.{entry_id}"


@callback
def async_remove_unsupported_entities(
    hass: HomeAssistant, entry_id: str, unsupported: set[str]
) -> None:
    """Drop entities that belong to read commands this projector does not answer.

    Which optional commands a projector answers is only known after it has been
    polled. Entities created before that, for example by a setup while the
    projector was switched off, would otherwise stay "unavailable" forever.
    """
    registry = er.async_get(hass)
    for capability in unsupported:
        for platform, key in CAPABILITY_ENTITIES.get(capability, ()):
            entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry_id}_{key}")
            if entity_id:
                _LOGGER.debug("Removing %s, the projector does not answer it", entity_id)
                registry.async_remove(entity_id)


class BarcoCoordinator(DataUpdateCoordinator[BarcoData]):
    """Poll the projector over the blocking Barco protocol."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        projector: BarcoProjector,
        scan_interval: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan_interval),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REQUEST_REFRESH_COOLDOWN, immediate=True
            ),
        )
        self.projector = projector
        self.unsupported: set[str] = set()
        self._poll_count = 0
        self._macros: list[str] = []
        self._last_seen: datetime | None = None
        self._reachable = True
        self._answered_before = False
        self._stored_macros: list[str] = []
        self._stored_unsupported: set[str] = set()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._followups: list[CALLBACK_TYPE] = []
        self._followup_job = HassJob(
            self._async_followup_refresh,
            f"{DOMAIN} follow-up refresh",
            cancel_on_shutdown=True,
        )

    @property
    def last_seen(self) -> datetime | None:
        """Return when the projector last answered."""
        return self._last_seen

    @property
    def answered_before(self) -> bool:
        """Return whether this projector has ever answered a poll."""
        return self._answered_before

    async def async_load_stored(self) -> None:
        """Restore what the projector reported on an earlier run."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        self._answered_before = True
        macros = stored.get("macros")
        if isinstance(macros, list):
            self._macros = [name for name in macros if isinstance(name, str)]
        unsupported = stored.get("unsupported")
        if isinstance(unsupported, list):
            self.unsupported = {key for key in unsupported if isinstance(key, str)}
        self._stored_macros = list(self._macros)
        self._stored_unsupported = set(self.unsupported)

    async def async_shutdown(self) -> None:
        """Cancel pending polls and close the socket when the entry is unloaded."""
        self.async_cancel_followups()
        await super().async_shutdown()
        await self.projector.async_close()

    @callback
    def async_schedule_followups(self) -> None:
        """Poll again a few times after a command; the projector needs time to settle."""
        self.async_cancel_followups()
        self._followups = [
            async_call_later(self.hass, delay, self._followup_job)
            for delay in FOLLOWUP_REFRESH_DELAYS
        ]

    @callback
    def async_cancel_followups(self) -> None:
        """Cancel follow-up polls that have not run yet."""
        for cancel in self._followups:
            cancel()
        self._followups.clear()

    async def _async_followup_refresh(self, _now: datetime) -> None:
        await self.async_request_refresh()

    async def _async_update_data(self) -> BarcoData:
        """Poll the projector, treating an unreachable one as a normal state.

        A projector that is switched off at the wall stops answering, which is
        expected rather than an error. Raising here would put a red line in the
        log on every power cycle, so the unreachable state is carried in the
        data instead and the entities go unavailable. Only a projector that has
        never answered fails the update, which keeps its entry waiting.
        """
        try:
            return await self._async_poll()
        except BarcoConnectionError as err:
            if not self._answered_before:
                raise UpdateFailed(f"the projector has not answered yet: {err}") from err
            return self._async_unreachable(err)
        except BarcoError as err:
            # A malformed answer is a real anomaly, so this one does get logged.
            raise UpdateFailed(f"unexpected answer: {err}") from err

    async def _async_poll(self) -> BarcoData:
        data = BarcoData()
        data.lamp = await self.projector.async_get_lamp()
        data.shutter = await self.projector.async_get_shutter()
        data.last_macro = await self._optional(
            CAPABILITY_LAST_MACRO, self.projector.async_get_last_macro
        )
        counts = await self._optional(CAPABILITY_ERRORS, self.projector.async_get_error_counts)
        if counts is not None:
            data.notifications, data.warnings, data.errors = counts
        data.sleep = await self._optional(CAPABILITY_SLEEP, self.projector.async_get_sleep)

        if self._poll_count % MACRO_REFRESH_EVERY == 0 or not self._macros:
            macros = await self._optional(CAPABILITY_MACROS, self._async_read_macros)
            if macros:
                self._macros = macros
        data.macros = list(self._macros)

        self._poll_count += 1
        self._last_seen = dt_util.utcnow()
        data.last_seen = self._last_seen
        if not self._reachable:
            _LOGGER.info("%s is answering again", self.name)
            self._reachable = True

        await self._async_remember()
        return data

    async def _async_remember(self) -> None:
        """Store what the projector reported, so a restart while it is off has it."""
        newly_unsupported = self.unsupported - self._stored_unsupported
        if newly_unsupported:
            async_remove_unsupported_entities(
                self.hass, self.config_entry.entry_id, newly_unsupported
            )
        if (
            self._answered_before
            and self.unsupported == self._stored_unsupported
            and self._macros == self._stored_macros
        ):
            return
        self._answered_before = True
        self._stored_macros = list(self._macros)
        self._stored_unsupported = set(self.unsupported)
        await self._store.async_save(
            {"macros": list(self._macros), "unsupported": sorted(self.unsupported)}
        )

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

    async def _async_read_macros(self) -> list[str]:
        return await self.projector.async_get_macro_buttons(MAX_MACRO_BUTTONS)

    async def _optional(self, key: str, func: Callable[[], Awaitable[Any]]) -> Any:
        """Run a read command that not every model answers."""
        if key in self.unsupported:
            return None
        try:
            return await func()
        except (BarcoNotAcknowledged, BarcoProtocolError) as err:
            _LOGGER.debug("%s is not supported by this projector: %s", key, err)
            self.unsupported.add(key)
            return None
