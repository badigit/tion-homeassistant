"""DataUpdateCoordinator for Tion MagicAir integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from tion import TionApi

_LOGGER = logging.getLogger(__name__)


class TionDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from Tion API."""

    def __init__(self, hass: HomeAssistant, api: TionApi) -> None:
        """Initialize."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict:
        """Update data via library."""
        try:
            zones = await self.hass.async_add_executor_job(self.api.get_zones)
            devices = {}
            for zone in zones:
                for device in zone.devices:
                    await self.hass.async_add_executor_job(device.load_state)
                    devices[device.guid] = device
            return devices
        except Exception as error:
            # Tion library specific error handling could be added here
            # For now, we wrap general exceptions
            if "auth" in str(error).lower() or "unauthorized" in str(error).lower():
                raise ConfigEntryAuthFailed("Authentication failed") from error
            raise UpdateFailed(f"Error communicating with API: {error}") from error
