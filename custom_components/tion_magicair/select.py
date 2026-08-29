"""Выбор источника воздуха для бризера Tion."""

from __future__ import annotations

from tion import Breezer

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import GATE_OPTIONS
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionEntity

OPTION_TO_GATE = {option: gate for gate, option in GATE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать выбор заслонки — только у бризеров, которые её отдают."""
    coordinator = entry.runtime_data

    async_add_entities(
        TionGateSelect(coordinator, device)
        for device in coordinator.data.values()
        if isinstance(device, Breezer) and device.gate is not None
    )


class TionGateSelect(TionEntity, SelectEntity):
    """Заслонка: улица, помещение или смешанный режим."""

    _attr_translation_key = "gate"
    _attr_options = list(GATE_OPTIONS.values())
    coordinator: TionDataUpdateCoordinator

    def __init__(
        self, coordinator: TionDataUpdateCoordinator, device: Breezer
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
        await self.hass.async_add_executor_job(
            self._set_gate, device, OPTION_TO_GATE[option]
        )
        await self.coordinator.async_request_refresh()

    @staticmethod
    def _set_gate(device: Breezer, gate: int) -> None:
        """Синхронная отправка положения заслонки."""
        # Библиотека кладёт gate в запрос только в ручном режиме зоны.
        if device.zone.mode != "manual":
            device.zone.mode = "manual"
            if not device.zone.send():
                raise HomeAssistantError("Облако Tion отклонило смену режима зоны")

        device.gate = gate
        if not device.send():
            raise HomeAssistantError("Облако Tion отклонило смену заслонки")
