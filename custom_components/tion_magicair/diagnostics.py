"""Диагностика Tion MagicAir."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import TionConfigEntry

REDACT_CONFIG = {CONF_PASSWORD, CONF_USERNAME}
# guid и MAC однозначно указывают на конкретное железо владельца.
REDACT_DATA = {"guid", "mac", "serial_number", "location_guid"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TionConfigEntry
) -> dict[str, Any]:
    """Вернуть диагностику записи конфигурации."""
    coordinator = entry.runtime_data
    snapshot = coordinator.data

    return {
        "config_entry": async_redact_data(entry.as_dict(), REDACT_CONFIG),
        "last_update_success": coordinator.last_update_success,
        "locations": [
            async_redact_data(asdict(location), REDACT_DATA)
            for location in snapshot.locations.values()
        ],
        "devices": [
            async_redact_data(asdict(device), REDACT_DATA)
            for device in snapshot.devices.values()
        ],
    }
