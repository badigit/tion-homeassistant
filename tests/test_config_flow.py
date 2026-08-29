"""Тесты диалога настройки Tion MagicAir."""

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tion_magicair.api import (
    TionAuthError,
    TionConnectionError,
    TionError,
)
from custom_components.tion_magicair.const import DOMAIN

USER_INPUT = {
    CONF_USERNAME: "Owner@Example.COM",
    CONF_PASSWORD: "пароль-от-облака",
}
UNIQUE_ID = USER_INPUT[CONF_USERNAME].lower()

# Все четыре ветки разбора ошибки в _async_check: три своих типа клиента и
# любое постороннее исключение.
ERROR_CASES = [
    (TionAuthError("облако не приняло пароль"), "invalid_auth"),
    (TionConnectionError("облако молчит"), "cannot_connect"),
    (TionError("облако ответило неожиданно"), "unknown"),
    (RuntimeError("совсем неожиданно"), "unknown"),
]


def _entry() -> MockConfigEntry:
    """Уже настроенная запись конфигурации."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        title=USER_INPUT[CONF_USERNAME],
        data=dict(USER_INPUT),
    )


async def test_user_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Успешная настройка с нуля."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == USER_INPUT[CONF_USERNAME]
    assert result["data"] == USER_INPUT
    # Почта приводится к нижнему регистру, иначе один аккаунт заведётся дважды.
    assert result["result"].unique_id == UNIQUE_ID
    mock_client.async_validate.assert_awaited_once()
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(("side_effect", "expected"), ERROR_CASES)
async def test_user_flow_errors_then_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_setup_entry: AsyncMock,
    side_effect: Exception,
    expected: str,
) -> None:
    """Ошибка показывается в форме, и та же форма принимает вторую попытку."""
    mock_client.async_validate.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}

    mock_client.async_validate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Тот же аккаунт второй раз не заводится."""
    _entry().add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # До облака дело даже не доходит.
    mock_client.async_validate.assert_not_awaited()


async def test_reauth_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Смена пароля через повторный вход."""
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    # Кроме нашего username Home Assistant подставляет в reauth свой name.
    assert result["description_placeholders"][CONF_USERNAME] == USER_INPUT[CONF_USERNAME]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "новый-пароль"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "новый-пароль"
    # Почта берётся из записи, а не спрашивается заново.
    assert entry.data[CONF_USERNAME] == USER_INPUT[CONF_USERNAME]


async def test_reauth_flow_error_then_success(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Неверный пароль при повторном входе не закрывает диалог."""
    entry = _entry()
    entry.add_to_hass(hass)
    mock_client.async_validate.side_effect = TionAuthError("не тот пароль")

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "мимо"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]

    mock_client.async_validate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "новый-пароль"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "новый-пароль"


async def test_options_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Интервал опроса меняется в настройках интеграции."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 30
