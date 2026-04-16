"""Diagnostics support for Tion."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TionData

REDACT_CONFIG = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data: TionData = entry.runtime_data
    coordinator = data.coordinator

    # Redact sensitive info from config entry
    diag_data = {
        "config_entry": async_redact_data(entry.as_dict(), REDACT_CONFIG),
        "coordinator_data": {},
    }

    # Redact and include coordinator data
    for guid, device in coordinator.data.items():
        device_dict = {
            "name": device.name,
            "type": device.type,
            "guid": device.guid,
            # Add other relevant but non-sensitive attributes
            "is_on": getattr(device, "is_on", None),
            "fan_speed": getattr(device, "fan_speed", None),
            "target_temp": getattr(device, "target_temp", None),
            "gate": getattr(device, "gate", None),
        }
        diag_data["coordinator_data"][guid] = device_dict

    return diag_data
