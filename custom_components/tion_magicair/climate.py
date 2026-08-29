"""Бризер Tion как climate-сущность."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_OFF,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ZONE_MODE_AUTO, ZONE_MODE_MANUAL, TionBreezer
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionBreezerEntity

# Команды бризеру шлём по одной: облако принимает состояние
# целиком, и параллельные записи затирали бы друг друга.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать climate-сущности для бризеров."""
    coordinator = entry.runtime_data

    async_add_entities(
        TionClimate(coordinator, device)
        for device in coordinator.data.devices.values()
        if isinstance(device, TionBreezer)
    )


class TionClimate(TionBreezerEntity, ClimateEntity):
    """Бризер: нагрев, скорость и целевая температура."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    coordinator: TionDataUpdateCoordinator

    def __init__(
        self, coordinator: TionDataUpdateCoordinator, device: TionBreezer
    ) -> None:
        """Инициализировать сущность бризера."""
        super().__init__(coordinator, device, "climate")

        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        if device.heater_installed:
            self._attr_hvac_modes.append(HVACMode.HEAT)

        self._attr_fan_modes = [FAN_OFF, FAN_AUTO] + [
            str(speed) for speed in range(1, device.max_speed + 1)
        ]

        if device.t_min is not None:
            self._attr_min_temp = device.t_min
        if device.t_max is not None:
            self._attr_max_temp = device.t_max

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Выключен, греет или только продувает."""
        if (device := self.device) is None:
            return None
        if not device.is_on:
            return HVACMode.OFF
        if device.heater_enabled:
            return HVACMode.HEAT
        return HVACMode.FAN_ONLY

    @property
    def current_temperature(self) -> float | None:
        """Температура воздуха на выходе бризера."""
        if (device := self.device) is None:
            return None
        return device.t_out

    @property
    def target_temperature(self) -> float | None:
        """Заданная температура нагрева."""
        if (device := self.device) is None:
            return None
        return device.t_set

    @property
    def fan_mode(self) -> str | None:
        """Скорость: auto — когда зоной управляет облако по CO₂."""
        if (device := self.device) is None:
            return None
        if device.zone.mode == ZONE_MODE_AUTO:
            return FAN_AUTO
        if not device.is_on:
            return FAN_OFF
        return str(int(device.speed or 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Показать режим зоны и её порог CO₂ — их нет в основных атрибутах."""
        if (device := self.device) is None:
            return None
        return {
            "zone_name": device.zone.name,
            "zone_mode": device.zone.mode,
            "zone_target_co2": device.zone.target_co2,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Переключить режим работы."""
        device = self._require_device()

        if hvac_mode is HVACMode.OFF:
            await self.coordinator.async_send_zone(device.zone, mode=ZONE_MODE_MANUAL)
            await self.coordinator.async_send_breezer(device, speed=0)
            return

        # Ниже первой скорости бризер выключен, поэтому включаем её при переходе.
        await self.coordinator.async_send_breezer(
            device,
            speed=int(device.speed or 0) or 1,
            heater_enabled=hvac_mode is HVACMode.HEAT,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Задать скорость или отдать зону под автоматику облака."""
        device = self._require_device()

        if fan_mode == FAN_AUTO:
            await self.coordinator.async_send_zone(device.zone, mode=ZONE_MODE_AUTO)
            return

        if device.zone.mode != ZONE_MODE_MANUAL:
            await self.coordinator.async_send_zone(device.zone, mode=ZONE_MODE_MANUAL)
            device = self._require_device()

        speed = 0 if fan_mode == FAN_OFF else int(fan_mode)
        await self.coordinator.async_send_breezer(device, speed=speed)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Задать целевую температуру нагрева."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_send_breezer(
            self._require_device(), t_set=int(temperature)
        )

    async def async_turn_on(self) -> None:
        """Включить бризер."""
        await self.async_set_hvac_mode(
            HVACMode.HEAT if HVACMode.HEAT in self.hvac_modes else HVACMode.FAN_ONLY
        )

    async def async_turn_off(self) -> None:
        """Выключить бризер."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def _require_device(self) -> TionBreezer:
        """Получить бризер или сказать, что команду выполнять не на чем."""
        if (device := self.device) is None:
            raise HomeAssistantError("Бризер пропал из аккаунта Tion")
        return device
