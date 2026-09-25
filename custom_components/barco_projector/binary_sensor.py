"""Binary sensor entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BarcoConfigEntry
from .coordinator import BarcoCoordinator
from .entity import BarcoProjectorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            BarcoLampSensor(coordinator, entry),
            BarcoConnectivitySensor(coordinator, entry),
        ]
    )


class BarcoLampSensor(BarcoProjectorEntity, BinarySensorEntity):
    """Whether the light source is running."""

    _attr_translation_key = "lamp"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: BarcoCoordinator, entry) -> None:
        """Initialise the lamp sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_lamp"

    @property
    def is_on(self) -> bool | None:
        """Return True when the lamp is on."""
        return self.coordinator.data.lamp


class BarcoConnectivitySensor(BarcoProjectorEntity, BinarySensorEntity):
    """Whether the projector answers on the control port."""

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BarcoCoordinator, entry) -> None:
        """Initialise the connectivity sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_connectivity"

    @property
    def available(self) -> bool:
        """Stay available so the sensor can report the outage itself."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True while the projector is answering."""
        return self.coordinator.last_update_success and self.coordinator.data.reachable
