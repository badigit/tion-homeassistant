"""Сенсоры Tion MagicAir."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDensity,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TionBreezer, TionDevice, TionMagicAir
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionDescribedEntity

SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True, kw_only=True)
class TionSensorEntityDescription(SensorEntityDescription):
    """Описание сенсора Tion."""

    value_fn: Callable[[TionDevice], float | str | None]
    # Датчик может физически отсутствовать в модели — тогда сущность не заводим.
    exists_fn: Callable[[TionDevice], bool] = lambda device: True


def _seconds_to_days(seconds: float | None) -> float | None:
    """Перевести секунды в дни."""
    return None if seconds is None else seconds / SECONDS_PER_DAY


def _seconds_to_hours(seconds: float | None) -> float | None:
    """Перевести секунды в часы."""
    return None if seconds is None else seconds / SECONDS_PER_HOUR


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
    TionSensorEntityDescription(
        key="airflow",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda device: device.speed_m3h,
        exists_fn=lambda device: device.speed_m3h is not None,
    ),
    TionSensorEntityDescription(
        key="filter_days_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda device: _seconds_to_days(device.filter_time_seconds),
        exists_fn=lambda device: device.filter_time_seconds is not None,
    ),
    TionSensorEntityDescription(
        key="run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda device: _seconds_to_hours(device.run_seconds),
        exists_fn=lambda device: device.run_seconds is not None,
    ),
    TionSensorEntityDescription(
        key="signal_level",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.signal_level,
        exists_fn=lambda device: device.signal_level is not None,
    ),
    TionSensorEntityDescription(
        key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.error_code,
        exists_fn=lambda device: device.error_code is not None,
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
    TionSensorEntityDescription(
        key="pm1",
        device_class=SensorDeviceClass.PM1,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.pm1,
        exists_fn=lambda device: device.pm1 is not None,
    ),
    TionSensorEntityDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.pm25,
        exists_fn=lambda device: device.pm25 is not None,
    ),
    TionSensorEntityDescription(
        key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.pm10,
        exists_fn=lambda device: device.pm10 is not None,
    ),
    TionSensorEntityDescription(
        key="wifi_signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.wifi_signal,
        exists_fn=lambda device: device.wifi_signal is not None,
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
    for device in coordinator.data.devices.values():
        if isinstance(device, TionBreezer):
            descriptions = BREEZER_SENSORS
        elif isinstance(device, TionMagicAir):
            descriptions = MAGICAIR_SENSORS
        else:
            continue
        entities.extend(
            TionSensor(coordinator, device, description)
            for description in descriptions
            if description.exists_fn(device)
        )

    async_add_entities(entities)


class TionSensor(TionDescribedEntity, SensorEntity):
    """Одна измеряемая величина устройства Tion."""

    entity_description: TionSensorEntityDescription
    coordinator: TionDataUpdateCoordinator

    @property
    def native_value(self) -> float | str | None:
        """Текущее значение."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)
