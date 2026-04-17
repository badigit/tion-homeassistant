"""Support for Tion binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TionEntity
from . import TionData

BINARY_SENSOR_TYPES: list[BinarySensorEntityDescription] = [
    BinarySensorEntityDescription(
        key="filter_need_replace",
        name="Filter Replacement Required",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tion binary sensor platform."""
    data: TionData = entry.runtime_data
    coordinator = data.coordinator

    entities = []
    for guid, device in coordinator.data.items():
        if device.type == "breezer":
            for description in BINARY_SENSOR_TYPES:
                entities.append(TionBinarySensor(coordinator, guid, description))

    async_add_entities(entities)


class TionBinarySensor(TionEntity, BinarySensorEntity):
    """Representation of a Tion binary sensor."""

    def __init__(self, coordinator, guid, description):
        """Initialize the binary sensor."""
        super().__init__(coordinator, guid)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{DOMAIN}_{guid}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return getattr(self.device, self.entity_description.key, None)
