"""Sensor entities for the Barco Cinema Projector integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BarcoConfigEntry
from .const import SHUTTER_STATES
from .coordinator import BarcoCoordinator, BarcoData
from .entity import BarcoProjectorEntity


@dataclass(frozen=True, kw_only=True)
class BarcoSensorDescription(SensorEntityDescription):
    """Describes a Barco sensor."""

    value_fn: Callable[[BarcoData], str | int | datetime | None]
    supported_key: str | None = None


SENSORS: tuple[BarcoSensorDescription, ...] = (
    BarcoSensorDescription(
        key="last_macro",
        translation_key="last_macro",
        icon="mdi:script-text-play",
        value_fn=lambda data: data.last_macro,
        supported_key="last_macro",
    ),
    BarcoSensorDescription(
        key="dowser_state",
        translation_key="dowser_state",
        icon="mdi:camera-iris",
        device_class=SensorDeviceClass.ENUM,
        options=list(SHUTTER_STATES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: SHUTTER_STATES.get(data.shutter)
        if data.shutter is not None
        else None,
    ),
    BarcoSensorDescription(
        key="errors",
        translation_key="errors",
        icon="mdi:alert-circle",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.errors,
        supported_key="errors",
    ),
    BarcoSensorDescription(
        key="warnings",
        translation_key="warnings",
        icon="mdi:alert",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.warnings,
        supported_key="errors",
    ),
    BarcoSensorDescription(
        key="notifications",
        translation_key="notifications",
        icon="mdi:information",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.notifications,
        supported_key="errors",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        BarcoSensor(coordinator, entry, description)
        for description in SENSORS
        if description.supported_key not in coordinator.unsupported
    ]
    entities.append(BarcoLastSeenSensor(coordinator, entry))
    async_add_entities(entities)


class BarcoSensor(BarcoProjectorEntity, SensorEntity):
    """A value read from the projector."""

    entity_description: BarcoSensorDescription

    def __init__(
        self,
        coordinator: BarcoCoordinator,
        entry,
        description: BarcoSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data)


class BarcoLastSeenSensor(BarcoProjectorEntity, SensorEntity):
    """When the projector last answered a poll."""

    _attr_translation_key = "last_seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BarcoCoordinator, entry) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_seen"

    @property
    def available(self) -> bool:
        """Stay available so the value survives an outage."""
        return True

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the last successful poll."""
        return self.coordinator.last_seen
