"""Base entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BarcoCoordinator


def projector_device_info(entry_id: str, title: str, host: str) -> DeviceInfo:
    """Return the device info of the projector itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer=MANUFACTURER,
        name=title,
        model="Digital cinema projector",
        configuration_url=f"http://{host}",
    )


def media_block_device_info(entry_id: str, title: str) -> DeviceInfo:
    """Return the device info of the media block inside the projector."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_icmp")},
        manufacturer=MANUFACTURER,
        name=f"{title} ICMP",
        model="ICMP / ICMP-X",
        via_device=(DOMAIN, entry_id),
    )


class BarcoProjectorEntity(CoordinatorEntity[BarcoCoordinator]):
    """Entity tied to the projector controller."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BarcoCoordinator, entry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = projector_device_info(
            entry.entry_id, entry.title, entry.data[CONF_HOST]
        )

    @property
    def available(self) -> bool:
        """Return whether the projector answered the last poll."""
        return self.coordinator.last_update_success


class BarcoMediaBlockEntity(Entity):
    """Entity tied to the media block; the protocol has no status feedback."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, icmp, entry) -> None:
        """Initialise the entity."""
        self._icmp = icmp
        self._entry = entry
        self._attr_device_info = media_block_device_info(entry.entry_id, entry.title)
