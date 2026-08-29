"""Выбор источника воздуха для бризера Tion."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    GATE_INSIDE,
    GATE_MIXED,
    GATE_OUTSIDE,
    ZONE_MODE_MANUAL,
    TionBreezer,
)
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionBreezerEntity, async_add_entities_dynamically

# Команды бризеру шлём по одной.
PARALLEL_UPDATES = 1

GATE_OPTIONS = {
    GATE_INSIDE: "inside",
    GATE_MIXED: "mixed",
    GATE_OUTSIDE: "outside",
}
OPTION_TO_GATE = {option: gate for gate, option in GATE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать выбор заслонки — только у бризеров, которые её отдают."""
    async_add_entities_dynamically(entry.runtime_data, async_add_entities, _build)


def _build(coordinator: TionDataUpdateCoordinator) -> list[TionGateSelect]:
    """Собрать выбор заслонки по текущему снимку."""
    return [
        TionGateSelect(coordinator, device)
        for device in coordinator.data.devices.values()
        if isinstance(device, TionBreezer) and device.gate is not None
    ]


class TionGateSelect(TionBreezerEntity, SelectEntity):
    """Заслонка: улица, помещение или смешанный режим."""

    _attr_translation_key = "gate"
    _attr_options = list(GATE_OPTIONS.values())
    coordinator: TionDataUpdateCoordinator

    def __init__(
        self, coordinator: TionDataUpdateCoordinator, device: TionBreezer
    ) -> None:
        """Инициализировать сущность."""
        super().__init__(coordinator, device, "gate")

    @property
    def current_option(self) -> str | None:
        """Текущее положение заслонки."""
        if (device := self.device) is None:
            return None
        return GATE_OPTIONS.get(device.gate)

    async def async_select_option(self, option: str) -> None:
        """Переставить заслонку."""
        if (device := self.device) is None:
            raise HomeAssistantError("Бризер пропал из аккаунта Tion")

        # Облако принимает заслонку только в ручном режиме зоны.
        if device.zone.mode != ZONE_MODE_MANUAL:
            await self.coordinator.async_send_zone(device.zone, mode=ZONE_MODE_MANUAL)
            if (device := self.device) is None:
                raise HomeAssistantError("Бризер пропал из аккаунта Tion")

        await self.coordinator.async_send_breezer(
            device, gate=OPTION_TO_GATE[option]
        )
