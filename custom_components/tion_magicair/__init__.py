"""The Tion integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from tion import TionApi

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BINARY_SENSOR,
]


@dataclass
class TionData:
    """Data for Tion integration."""

    api: TionApi
    coordinator: DataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tion from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    api = await hass.async_add_executor_job(TionApi, username, password)

    async def async_update_data():
        """Fetch data from Tion API."""
        try:
            # api.get_zones() returns all zones and devices with their current states
            zones = await hass.async_add_executor_job(api.get_zones)
            # Flatten devices into a single dict for easier access
            devices = {}
            for zone in zones:
                for device in zone.devices:
                    # Load state for each device to have the latest telemetry
                    await hass.async_add_executor_job(device.load_state)
                    devices[device.guid] = device
            return devices
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = TionData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # entry.runtime_data is automatically cleaned up if not referenced elsewhere
        pass

    return unload_ok
