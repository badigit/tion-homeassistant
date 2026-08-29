"""Сенсоры Tion MagicAir."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tion import Breezer, MagicAir

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfRatio, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TionConfigEntry, TionDataUpdateCoordinator, TionDevice
from .entity import TionDescribedEntity


@dataclass(frozen=True, kw_only=True)
class TionSensorEntityDescription(SensorEntityDescription):
    """Описание сенсора Tion."""

    value_fn: Callable[[TionDevice], float | None]


BREEZER_SENSORS: tuple[TionSensorEntityDescription, ...] = (
    TionSensorEntityDescription(
        key="temp_in",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.t_in,
    ),
    TionSensorEntityDescription(
        key="temp_out",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.t_out,
    ),
    TionSensorEntityDescription(
        key="speed",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.speed,
    ),
)

MAGICAIR_SENSORS: tuple[TionSensorEntityDescription, ...] = (
    TionSensorEntityDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.co2,
    ),
    TionSensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.temperature,
    ),
    TionSensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.humidity,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать сенсоры для всех устройств аккаунта."""
    coordinator = entry.runtime_data

    entities: list[TionSensor] = []
    for device in coordinator.data.values():
        if isinstance(device, Breezer):
            descriptions = BREEZER_SENSORS
        elif isinstance(device, MagicAir):
            descriptions = MAGICAIR_SENSORS
        else:
            continue
        entities.extend(
            TionSensor(coordinator, device, description) for description in descriptions
        )

    async_add_entities(entities)


class TionSensor(TionDescribedEntity, SensorEntity):
    """Одна измеряемая величина устройства Tion."""

    entity_description: TionSensorEntityDescription
    coordinator: TionDataUpdateCoordinator

    @property
    def native_value(self) -> float | None:
        """Текущее значение."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)
