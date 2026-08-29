"""Бинарные сенсоры Tion MagicAir."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TionBreezer, TionDevice, TionMagicAir
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionDescribedEntity, async_add_entities_dynamically

# Обновление централизовано координатором.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TionBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Описание бинарного сенсора Tion."""

    value_fn: Callable[[TionDevice], bool | None]
    # Связь сообщает как раз о том, что устройство недоступно, поэтому такая
    # сущность не должна уходить в unavailable вместе с ним.
    ignore_device_validity: bool = False


CONNECTIVITY_SENSOR = TionBinarySensorEntityDescription(
    key="connectivity",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda device: device.is_online,
    ignore_device_validity=True,
)

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
    CONNECTIVITY_SENSOR,
)

MAGICAIR_BINARY_SENSORS: tuple[TionBinarySensorEntityDescription, ...] = (
    CONNECTIVITY_SENSOR,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать бинарные сенсоры всех устройств аккаунта."""
    async_add_entities_dynamically(entry.runtime_data, async_add_entities, _build)


def _build(coordinator: TionDataUpdateCoordinator) -> list[TionBinarySensor]:
    """Собрать бинарные сенсоры по текущему снимку."""
    entities: list[TionBinarySensor] = []
    for device in coordinator.data.devices.values():
        if isinstance(device, TionBreezer):
            descriptions = BREEZER_BINARY_SENSORS
        elif isinstance(device, TionMagicAir):
            descriptions = MAGICAIR_BINARY_SENSORS
        else:
            # Без этой ветки чужой объект в снимке ронял всю платформу целиком,
            # и HA оставался вообще без бинарных сенсоров.
            continue
        entities.extend(
            TionBinarySensor(coordinator, device, description)
            for description in descriptions
        )

    return entities


class TionBinarySensor(TionDescribedEntity, BinarySensorEntity):
    """Бинарное состояние устройства Tion."""

    entity_description: TionBinarySensorEntityDescription
    coordinator: TionDataUpdateCoordinator

    @property
    def available(self) -> bool:
        """Связь остаётся доступной, даже когда устройство offline."""
        if self.entity_description.ignore_device_validity:
            return (
                self.coordinator.last_update_success and self.device is not None
            )
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Текущее состояние."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)
