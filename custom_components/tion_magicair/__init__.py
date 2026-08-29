"""Интеграция Tion MagicAir."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import TionConfigEntry, TionDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Поднять запись конфигурации."""
    coordinator = TionDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: TionConfigEntry) -> None:
    """Перечитать запись после смены опций."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Выгрузить запись конфигурации."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
