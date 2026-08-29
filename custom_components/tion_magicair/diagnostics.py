"""Диагностика Tion MagicAir."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import TionConfigEntry, TionDevice

REDACT_CONFIG = {CONF_PASSWORD, CONF_USERNAME}

# Читаем через getattr: у бризера и MagicAir наборы полей разные.
DEVICE_FIELDS = (
    "name",
    "valid",
    "co2",
    "temperature",
    "humidity",
    "t_in",
    "t_out",
    "t_set",
    "t_min",
    "t_max",
    "is_on",
    "heater_installed",
    "heater_enabled",
    "speed",
    "speed_min_set",
    "speed_max_set",
    "speed_limit",
    "gate",
    "filter_need_replace",
)


def _describe(device: TionDevice) -> dict[str, Any]:
    """Собрать снимок устройства для диагностики."""
    snapshot: dict[str, Any] = {
        "model": type(device).__name__,
        **{field: getattr(device, field, None) for field in DEVICE_FIELDS},
    }
    if (zone := getattr(device, "zone", None)) is not None:
        snapshot["zone"] = {
            "name": zone.name,
            "mode": zone.mode,
            "target_co2": zone.target_co2,
        }
    return snapshot


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TionConfigEntry
) -> dict[str, Any]:
    """Вернуть диагностику записи конфигурации."""
    coordinator = entry.runtime_data

    return {
        "config_entry": async_redact_data(entry.as_dict(), REDACT_CONFIG),
        "last_update_success": coordinator.last_update_success,
        "devices": {
            guid: _describe(device) for guid, device in coordinator.data.items()
        },
    }
