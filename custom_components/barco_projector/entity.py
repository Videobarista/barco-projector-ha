"""Base entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_MODEL
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MEDIA_BLOCK_MODEL, PROJECTOR_MODEL
from .coordinator import BarcoCoordinator

# Home Assistant 2026.8 replaced DeviceInfo["via_device"] with "via_device_id".
# Check the TypedDict itself so the integration keeps working on both.
SUPPORTS_VIA_DEVICE_ID = "via_device_id" in getattr(DeviceInfo, "__annotations__", {})


def projector_device_info(entry) -> DeviceInfo:
    """Return the device info of the projector itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name=entry.title,
        model=entry.data.get(CONF_MODEL) or PROJECTOR_MODEL,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )


def media_block_device_info(entry) -> DeviceInfo:
    """Return the device info of the media block inside the projector."""
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_icmp")},
        manufacturer=MANUFACTURER,
        name=f"{entry.title} ICMP",
        model=MEDIA_BLOCK_MODEL,
    )
    if SUPPORTS_VIA_DEVICE_ID:
        device_id = getattr(entry.runtime_data, "projector_device_id", None)
        if device_id:
            info["via_device_id"] = device_id
    else:
        info["via_device"] = (DOMAIN, entry.entry_id)
    return info


class BarcoProjectorEntity(CoordinatorEntity[BarcoCoordinator]):
    """Entity tied to the projector controller."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BarcoCoordinator, entry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = projector_device_info(entry)

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
        self._attr_device_info = media_block_device_info(entry)
