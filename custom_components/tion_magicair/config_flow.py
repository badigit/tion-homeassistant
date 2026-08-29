"""Config flow интеграции Tion MagicAir."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from tion import TionApi
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


async def async_validate_credentials(
    hass: HomeAssistant, username: str, password: str
) -> None:
    """Проверить логин и пароль живым обращением к облаку."""

    def _login() -> None:
        # auth_fname=None — не писать токен на диск: это только проверка.
        api = TionApi(username, password, auth_fname=None)
        if not api.authorization:
            raise InvalidAuth
        if not api.get_devices():
            raise CannotConnect

    await hass.async_add_executor_job(_login)


class TionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Диалог настройки Tion MagicAir."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Спросить учётные данные аккаунта Tion."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            errors = await self._async_check(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(title=username, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Облако перестало принимать сохранённые данные."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Спросить новый пароль."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]

        if user_input is not None:
            errors = await self._async_check(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )

    async def _async_check(self, username: str, password: str) -> dict[str, str]:
        """Вернуть словарь ошибок формы для введённых данных."""
        try:
            await async_validate_credentials(self.hass, username, password)
        except InvalidAuth:
            return {"base": "invalid_auth"}
        except CannotConnect:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Не удалось проверить учётные данные Tion")
            return {"base": "unknown"}
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Вернуть диалог опций."""
        return TionOptionsFlow()


class TionOptionsFlow(OptionsFlow):
    """Опции: как часто опрашивать облако."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Показать и сохранить интервал опроса."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )


class CannotConnect(Exception):
    """Облако Tion недоступно или не отдало устройства."""


class InvalidAuth(Exception):
    """Облако Tion не приняло логин и пароль."""
