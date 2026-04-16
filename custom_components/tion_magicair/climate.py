"""Support for Tion breezers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import TionData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tion breezer climate platform."""
    data: TionData = entry.runtime_data
    coordinator = data.coordinator

    async_add_entities(
        TionClimate(coordinator, guid)
        for guid, device in coordinator.data.items()
        if device.type == "breezer"
    )


class TionClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Tion breezer."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.FAN_ONLY]
    _attr_fan_modes = ["1", "2", "3", "4", "5", "6"]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator, guid):
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._guid = guid
        device = coordinator.data[guid]
        self._attr_name = device.name
        self._attr_unique_id = f"{DOMAIN}_{guid}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, guid)},
            "name": device.name,
            "manufacturer": "Tion",
            "model": device.type,
        }

    @property
    def device(self):
        """Return the device from coordinator."""
        return self.coordinator.data[self._guid]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current hvac mode."""
        if not self.device.is_on:
            return HVACMode.OFF
        if self.device.heater_enabled:
            return HVACMode.HEAT
        return HVACMode.FAN_ONLY

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.device.temp_in

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.device.target_temp

    @property
    def fan_mode(self) -> str | None:
        """Return the fan mode."""
        return str(self.device.fan_speed)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.hass.async_add_executor_job(
                self.device.set_state, {"is_on": False}
            )
        elif hvac_mode == HVACMode.HEAT:
            await self.hass.async_add_executor_job(
                self.device.set_state, {"is_on": True, "heater_enabled": True}
            )
        elif hvac_mode == HVACMode.FAN_ONLY:
            await self.hass.async_add_executor_job(
                self.device.set_state, {"is_on": True, "heater_enabled": False}
            )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self.hass.async_add_executor_job(
            self.device.set_state, {"fan_speed": int(fan_mode)}
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.hass.async_add_executor_job(
                self.device.set_state, {"target_temp": int(temp)}
            )
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self.async_set_hvac_mode(HVACMode.FAN_ONLY)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
