"""Бризер Tion как climate-сущность."""

from __future__ import annotations

from typing import Any

from tion import Breezer

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

from .const import DEFAULT_MAX_SPEED
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator
from .entity import TionEntity

ZONE_MODE_AUTO = "auto"
ZONE_MODE_MANUAL = "manual"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать climate-сущности для бризеров."""
    coordinator = entry.runtime_data

    async_add_entities(
        TionClimate(coordinator, device)
        for device in coordinator.data.values()
        if isinstance(device, Breezer)
    )


class TionClimate(TionEntity, ClimateEntity):
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
        self, coordinator: TionDataUpdateCoordinator, device: Breezer
    ) -> None:
        """Инициализировать сущность бризера."""
        super().__init__(coordinator, device, "climate")

        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        if device.heater_installed:
            self._attr_hvac_modes.append(HVACMode.HEAT)

        # Потолок скорости у моделей разный: O₂ отдаёт 4, S3/S4 — 6.
        max_speed = int(device.speed_limit or DEFAULT_MAX_SPEED)
        self._attr_fan_modes = [FAN_OFF, FAN_AUTO] + [
            str(speed) for speed in range(1, max_speed + 1)
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
        return str(int(device.speed))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Показать режим зоны и её порог CO₂ — их нет в основных атрибутах."""
        if (device := self.device) is None:
            return None
        return {
            "zone_mode": device.zone.mode,
            "zone_target_co2": device.zone.target_co2,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Переключить режим работы."""
        device = self._require_device()

        if hvac_mode is HVACMode.OFF:
            await self._async_apply(device, zone_mode=ZONE_MODE_MANUAL, speed=0)
            return

        # Ниже первой скорости бризер выключен, поэтому включаем её при переходе.
        speed = int(device.speed) or 1
        await self._async_apply(
            device,
            zone_mode=None,
            speed=speed,
            heater_enabled=hvac_mode is HVACMode.HEAT,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Задать скорость или отдать зону под автоматику облака."""
        device = self._require_device()

        if fan_mode == FAN_AUTO:
            await self._async_apply(device, zone_mode=ZONE_MODE_AUTO)
        elif fan_mode == FAN_OFF:
            await self._async_apply(device, zone_mode=ZONE_MODE_MANUAL, speed=0)
        else:
            await self._async_apply(
                device, zone_mode=ZONE_MODE_MANUAL, speed=int(fan_mode)
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Задать целевую температуру нагрева."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._async_apply(self._require_device(), t_set=int(temperature))

    async def async_turn_on(self) -> None:
        """Включить бризер."""
        await self.async_set_hvac_mode(
            HVACMode.HEAT if HVACMode.HEAT in self.hvac_modes else HVACMode.FAN_ONLY
        )

    async def async_turn_off(self) -> None:
        """Выключить бризер."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def _require_device(self) -> Breezer:
        """Получить устройство или сказать, что команду выполнять не на чем."""
        if (device := self.device) is None:
            raise HomeAssistantError("Бризер пропал из аккаунта Tion")
        return device

    async def _async_apply(
        self,
        device: Breezer,
        *,
        zone_mode: str | None = None,
        **changes: Any,
    ) -> None:
        """Отправить изменения в облако и обновить состояние."""
        await self.hass.async_add_executor_job(
            self._apply, device, zone_mode, changes
        )
        await self.coordinator.async_request_refresh()

    @staticmethod
    def _apply(device: Breezer, zone_mode: str | None, changes: dict[str, Any]) -> None:
        """Синхронная отправка: сначала режим зоны, затем параметры бризера."""
        if zone_mode is not None and device.zone.mode != zone_mode:
            device.zone.mode = zone_mode
            if not device.zone.send():
                raise HomeAssistantError("Облако Tion отклонило смену режима зоны")

        if not changes:
            return

        for attribute, value in changes.items():
            setattr(device, attribute, value)
        if not device.send():
            raise HomeAssistantError("Облако Tion отклонило команду бризеру")
