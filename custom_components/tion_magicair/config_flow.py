"""Config flow for Tion integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from tion import TionApi

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # Use executor as TionApi is likely synchronous
    api = await hass.async_add_executor_job(
        TionApi, data[CONF_USERNAME], data[CONF_PASSWORD]
    )

    # Check if we can get zones to verify credentials
    zones = await hass.async_add_executor_job(api.get_zones)

    if not zones:
        # If no zones, we might still be authenticated but have no devices
        # However, usually get_zones would raise an exception on auth failure
        pass

    return {"title": data[CONF_USERNAME]}


class TionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
