"""Числовые настройки бризера и его зоны."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfRatio
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TionBreezer
from .const import MAX_TARGET_CO2, MIN_TARGET_CO2
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionBreezerEntity, async_add_entities_dynamically

# Команды бризеру и зоне шлём по одной.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TionNumberEntityDescription(NumberEntityDescription):
    """Описание числовой настройки Tion."""

    value_fn: Callable[[TionBreezer], float | None]
    set_fn: Callable[[TionDataUpdateCoordinator, TionBreezer, float], Awaitable[None]]
    # Верхняя граница у скоростей зависит от модели, поэтому считается на месте.
    max_fn: Callable[[TionBreezer], float] | None = None


async def _async_set_speed_min(
    coordinator: TionDataUpdateCoordinator, breezer: TionBreezer, value: float
) -> None:
    """Задать нижнюю границу скорости для режима auto."""
    await coordinator.async_send_breezer(breezer, speed_min_set=value)


async def _async_set_speed_max(
    coordinator: TionDataUpdateCoordinator, breezer: TionBreezer, value: float
) -> None:
    """Задать верхнюю границу скорости для режима auto."""
    await coordinator.async_send_breezer(breezer, speed_max_set=value)


async def _async_set_target_co2(
    coordinator: TionDataUpdateCoordinator, breezer: TionBreezer, value: float
) -> None:
    """Задать порог CO₂, по которому облако ведёт зону."""
    await coordinator.async_send_zone(breezer.zone, target_co2=value)


NUMBERS: tuple[TionNumberEntityDescription, ...] = (
    TionNumberEntityDescription(
        key="speed_min_set",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=0,
        native_step=1,
        max_fn=lambda breezer: breezer.max_speed,
        value_fn=lambda breezer: breezer.speed_min_set,
        set_fn=_async_set_speed_min,
    ),
    TionNumberEntityDescription(
        key="speed_max_set",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=0,
        native_step=1,
        max_fn=lambda breezer: breezer.max_speed,
        value_fn=lambda breezer: breezer.speed_max_set,
        set_fn=_async_set_speed_max,
    ),
    TionNumberEntityDescription(
        key="target_co2",
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_TARGET_CO2,
        native_max_value=MAX_TARGET_CO2,
        native_step=50,
        value_fn=lambda breezer: breezer.zone.target_co2,
        set_fn=_async_set_target_co2,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать числовые настройки бризеров."""
    async_add_entities_dynamically(entry.runtime_data, async_add_entities, _build)


def _build(coordinator: TionDataUpdateCoordinator) -> list[TionNumber]:
    """Собрать числовые настройки по текущему снимку."""
    return [
        TionNumber(coordinator, device, description)
        for device in coordinator.data.devices.values()
        if isinstance(device, TionBreezer)
        for description in NUMBERS
    ]


class TionNumber(TionBreezerEntity, NumberEntity):
    """Числовая настройка бризера."""

    entity_description: TionNumberEntityDescription
    coordinator: TionDataUpdateCoordinator

    def __init__(
        self,
        coordinator: TionDataUpdateCoordinator,
        device: TionBreezer,
        description: TionNumberEntityDescription,
    ) -> None:
        """Инициализировать настройку."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key

    @property
    def native_max_value(self) -> float:
        """Потолок берётся у модели и следует за снимком, а не за первым ответом."""
        device = self.device
        if device is not None and self.entity_description.max_fn is not None:
            return self.entity_description.max_fn(device)
        return super().native_max_value

    @property
    def native_value(self) -> float | None:
        """Текущее значение."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)

    async def async_set_native_value(self, value: float) -> None:
        """Отправить новое значение в облако."""
        if (device := self.device) is None:
            # Молчаливый выход выглядел бы как применённая настройка.
            raise HomeAssistantError("Бризер пропал из аккаунта Tion")
        await self.entity_description.set_fn(self.coordinator, device, value)
