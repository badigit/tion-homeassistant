"""Бинарные сенсоры Tion MagicAir."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tion import Breezer

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TionConfigEntry, TionDataUpdateCoordinator, TionDevice
from .entity import TionDescribedEntity


@dataclass(frozen=True, kw_only=True)
class TionBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Описание бинарного сенсора Tion."""

    value_fn: Callable[[TionDevice], bool | None]


BREEZER_BINARY_SENSORS: tuple[TionBinarySensorEntityDescription, ...] = (
    TionBinarySensorEntityDescription(
        key="fan_state",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: device.is_on,
    ),
    TionBinarySensorEntityDescription(
        key="filter_need_replace",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda device: device.filter_need_replace,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать бинарные сенсоры бризеров."""
    coordinator = entry.runtime_data

    async_add_entities(
        TionBinarySensor(coordinator, device, description)
        for device in coordinator.data.values()
        if isinstance(device, Breezer)
        for description in BREEZER_BINARY_SENSORS
    )


class TionBinarySensor(TionDescribedEntity, BinarySensorEntity):
    """Бинарное состояние бризера."""

    entity_description: TionBinarySensorEntityDescription
    coordinator: TionDataUpdateCoordinator

    @property
    def is_on(self) -> bool | None:
        """Текущее состояние."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)
