"""Support for Tion sensors."""

from __future__ import annotations

from dataclasses import dataclass
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import TionData


@dataclass
class TionSensorEntityDescription(SensorEntityDescription):
    """Class describing Tion sensor entities."""

    attr_name: str = ""


SENSOR_TYPES: dict[str, list[TionSensorEntityDescription]] = {
    "breezer": [
        TionSensorEntityDescription(
            key="temp_in",
            name="Inlet Temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            attr_name="temp_in",
        ),
        TionSensorEntityDescription(
            key="temp_out",
            name="Outlet Temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            attr_name="temp_out",
        ),
    ],
    "magicair": [
        TionSensorEntityDescription(
            key="co2",
            name="CO2",
            native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
            device_class=SensorDeviceClass.CO2,
            state_class=SensorStateClass.MEASUREMENT,
            attr_name="co2",
        ),
        TionSensorEntityDescription(
            key="temperature",
            name="Temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            attr_name="temperature",
        ),
        TionSensorEntityDescription(
            key="humidity",
            name="Humidity",
            native_unit_of_measurement=PERCENTAGE,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            attr_name="humidity",
        ),
    ],
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tion sensor platform."""
    data: TionData = entry.runtime_data
    coordinator = data.coordinator

    entities = []
    for guid, device in coordinator.data.items():
        if device.type in SENSOR_TYPES:
            for description in SENSOR_TYPES[device.type]:
                entities.append(TionSensor(coordinator, guid, description))

    async_add_entities(entities)


class TionSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tion sensor."""

    entity_description: TionSensorEntityDescription

    def __init__(self, coordinator, guid, description):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._guid = guid
        self.entity_description = description
        device = coordinator.data[guid]
        self._attr_name = f"{device.name} {description.name}"
        self._attr_unique_id = f"{DOMAIN}_{guid}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, guid)},
            "name": device.name,
            "manufacturer": "Tion",
            "model": device.type,
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        device = self.coordinator.data[self._guid]
        return getattr(device, self.entity_description.attr_name, None)
