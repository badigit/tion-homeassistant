"""Поведение при недоступной сети и молчащем облаке.

Второй круг ревью. Каждый тест падает на коде до правки — проверено прогоном
против коммита 61c87ba.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.tion_magicair import api as tion_api
from custom_components.tion_magicair.api import (
    API_BASE,
    AUTH_URL,
    LOCATION_URL,
    TionApiClient,
    TionAuthError,
    TionCommandError,
    TionConnectionError,
    TionError,
    parse_snapshot,
)

from .conftest import BREEZER_GUID, RAW_LOCATION

TOKEN = {"token_type": "Bearer", "access_token": "abc123"}
CLIMATE = "climate.gostinaia_brizer"
PORTAL_HTML = "<html><body>Вход в сеть отеля</body></html>"


def _client(hass: HomeAssistant, **kwargs: Any) -> TionApiClient:
    """Клиент на сессии Home Assistant."""
    return TionApiClient(
        async_get_clientsession(hass), "owner@example.com", "секрет", **kwargs
    )


# --- captive portal ----------------------------------------------------------


async def test_portal_403_is_not_wrong_password(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """403 от прокси не должен выглядеть как неверный пароль.

    Иначе запись уходит в reauth, и после возвращения сети сама уже не
    поднимется: Home Assistant не возобновляет опрос записи с провалом
    авторизации. Пароль при этом верный.
    """
    aioclient_mock.post(AUTH_URL, status=403, text=PORTAL_HTML)
    aioclient_mock.get(LOCATION_URL, status=403, text=PORTAL_HTML)

    with pytest.raises(TionConnectionError):
        await _client(hass, token="Bearer прежний").async_fetch()


async def test_real_auth_rejection_still_asks_for_password(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """А настоящий отказ облака по-прежнему ведёт в повторный вход."""
    aioclient_mock.post(
        AUTH_URL, status=400, json={"error": "invalid_grant"}
    )

    with pytest.raises(TionAuthError):
        await _client(hass).async_authenticate()


async def test_portal_html_with_200_on_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTML со статусом 200 на логин — ошибка связи, а не трейсбек в логе."""
    aioclient_mock.post(AUTH_URL, text=PORTAL_HTML)

    with pytest.raises(TionConnectionError):
        await _client(hass).async_authenticate()


async def test_portal_keeps_entry_retrying(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Запись за порталом уходит в повтор, а не в диалог ввода пароля."""
    mock_api.async_fetch.side_effect = TionConnectionError("ответ пришёл не от Tion")
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.config_entries.flow.async_progress()


# --- дедлайн команды ---------------------------------------------------------


async def test_command_has_overall_deadline(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ожидание задачи ограничено по времени, а не только по числу попыток.

    Раньше двадцать попыток по пятнадцать секунд складывались в шесть минут
    удержания блокировки команд.
    """
    monkeypatch.setattr(tion_api, "COMMAND_TIMEOUT", 0.2)
    monkeypatch.setattr(tion_api, "TASK_POLL_INTERVAL", 0.05)

    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "queued", "task_id": "task-1"},
    )
    aioclient_mock.get(f"{API_BASE}/task/task-1", json={"status": "queued"})

    with pytest.raises(TionCommandError, match="не ответило за"):
        await client.async_send_breezer(breezer, speed=3)


async def test_no_sleep_after_last_attempt(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пауза идёт перед повтором, а не после последней попытки."""
    monkeypatch.setattr(tion_api, "TASK_ATTEMPTS", 3)
    sleeps: list[float] = []

    real_sleep = asyncio.sleep

    async def counting_sleep(delay: float) -> None:
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(tion_api.asyncio, "sleep", counting_sleep)

    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "queued", "task_id": "task-2"},
    )
    aioclient_mock.get(f"{API_BASE}/task/task-2", json={"status": "queued"})

    with pytest.raises(TionCommandError):
        await client.async_send_breezer(breezer)

    # Три попытки — две паузы между ними, и ни одной лишней в конце.
    assert len(sleeps) == 2


# --- неоднозначный результат -------------------------------------------------


async def test_refresh_after_ambiguous_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Связь оборвалась после постановки задачи — состояние перечитывается.

    Команда могла выполниться, поэтому оставлять в интерфейсе старое значение
    до планового опроса нельзя: при своём интервале это до часа.
    """
    mock_api.async_fetch.reset_mock()
    mock_api.async_send_breezer.side_effect = TionConnectionError("связь оборвалась")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 18},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert mock_api.async_fetch.await_count >= 1


# --- неполный снимок ---------------------------------------------------------


@pytest.mark.parametrize(
    "missing", ["speed", "speed_min_set", "speed_max_set", "t_set"]
)
def test_incomplete_snapshot_refuses_command(missing: str) -> None:
    """Пропавшее поле не заменяется выдуманным значением.

    Полное состояние уходит в облако целиком: подстановка нуля выключила бы
    бризер, подстановка десятки сбила бы уставку, подстановка потолка —
    границы автоматики.
    """
    raw = copy.deepcopy(RAW_LOCATION)
    del raw[0]["zones"][0]["devices"][1]["data"][missing]
    breezer = parse_snapshot(raw).devices[BREEZER_GUID]

    with pytest.raises(TionCommandError, match=missing):
        breezer.mode_payload()


def test_missing_target_co2_refuses_zone_command() -> None:
    """Порог CO2 тоже не выдумывается: он бы затёр настройку в облаке."""
    raw = copy.deepcopy(RAW_LOCATION)
    del raw[0]["zones"][0]["mode"]["auto_set"]
    zone = parse_snapshot(raw).devices[BREEZER_GUID].zone

    with pytest.raises(TionCommandError, match="порог CO2"):
        zone.mode_payload(mode="auto")


def test_complete_snapshot_still_works() -> None:
    """Полный снимок команду по-прежнему собирает."""
    breezer = parse_snapshot(copy.deepcopy(RAW_LOCATION)).devices[BREEZER_GUID]
    assert breezer.mode_payload(speed=2)["speed"] == 2


# --- поведение сущностей -----------------------------------------------------


async def test_turn_on_does_not_start_heater(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """«Включи бризер» летом не должно запускать нагрев."""
    raw = copy.deepcopy(RAW_LOCATION)
    data = raw[0]["zones"][0]["devices"][1]["data"]
    data["is_on"] = False
    data["speed"] = 0.0
    data["heater_enabled"] = False
    mock_api.async_fetch.return_value = parse_snapshot(raw)

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )
    await hass.async_block_till_done()

    assert mock_api.async_send_breezer.await_args.kwargs["heater_enabled"] is False


async def test_turn_on_keeps_heater_when_it_was_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """А если нагрев был включён, включение его сохраняет."""
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )
    await hass.async_block_till_done()

    assert mock_api.async_send_breezer.await_args.kwargs["heater_enabled"] is True


async def test_speed_ceiling_follows_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Потолок ползунка скорости следует за снимком, а не за первым ответом."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    entity_id = "number.gostinaia_brizer_maximum_speed_in_auto"
    assert hass.states.get(entity_id).attributes["max"] == 6

    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["devices"][1]["data"]["speed_limit"] = 4.0
    mock_api.async_fetch.return_value = parse_snapshot(raw)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).attributes["max"] == 4
