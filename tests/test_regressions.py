"""Регрессии по находкам ревью.

Каждый тест здесь падает на коде до правки — иначе он бесполезен.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.tion_magicair.api import (
    API_BASE,
    AUTH_URL,
    LOCATION_URL,
    ZONE_MODE_AUTO,
    ZONE_MODE_MANUAL,
    TionApiClient,
    TionCommandError,
    TionConnectionError,
    parse_snapshot,
)

from .conftest import BREEZER_GUID, RAW_LOCATION

TOKEN = {"token_type": "Bearer", "access_token": "abc123"}
CLIMATE = "climate.gostinaia_brizer"


def _client(hass: HomeAssistant, **kwargs: Any) -> TionApiClient:
    """Клиент на сессии Home Assistant."""
    return TionApiClient(
        async_get_clientsession(hass), "owner@example.com", "секрет", **kwargs
    )


def _breezer(**data_overrides: Any):
    """Разобранный бризер с подменёнными полями телеметрии."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["devices"][1]["data"].update(data_overrides)
    return parse_snapshot(raw).devices[BREEZER_GUID]


# --- транспорт ---------------------------------------------------------------


async def test_forbidden_triggers_relogin(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """403 на отозванный токен — повод перелогиниться, а не «нет связи».

    Раньше любой не-401 статус превращался в TionConnectionError, и повторный
    вход не запускался бы никогда: координатор вечно писал «ошибка связи», а
    сущности оставались недоступными.
    """
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, status=403)

    from custom_components.tion_magicair.api import TionAuthError

    with pytest.raises(TionAuthError):
        await _client(hass, token="Bearer отозванный").async_fetch()


async def test_command_rejection_is_not_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """400 от endpoint команды — отказ команды, а не проблема сети."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        status=400,
        json={"description": "поле gate не поддерживается"},
    )

    with pytest.raises(TionCommandError, match="gate не поддерживается"):
        await client.async_send_breezer(breezer, speed=1)


async def test_server_error_is_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Пятисотка остаётся проблемой связи."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, status=503)

    with pytest.raises(TionConnectionError):
        await _client(hass).async_fetch()


async def test_html_instead_of_json(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Прокси вернул страницу вместо JSON — это связь, а не трейсбек."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, text="<html>502 Bad Gateway</html>")

    with pytest.raises(TionConnectionError):
        await _client(hass).async_fetch()


async def test_queued_without_task_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Ответ «принято» без идентификатора задачи — ошибка команды, не KeyError."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode", json={"status": "queued"}
    )

    with pytest.raises(TionCommandError, match="идентификатор задачи"):
        await client.async_send_breezer(breezer)


async def test_task_failure_reported_immediately(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Провал задачи виден сразу и с причиной, а не через десять секунд."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode",
        json={"status": "queued", "task_id": "task-9"},
    )
    aioclient_mock.get(
        f"{API_BASE}/task/task-9",
        json={"status": "failed", "description": "устройство offline"},
    )

    with pytest.raises(TionCommandError, match="устройство offline"):
        await client.async_send_breezer(breezer)


# --- разбор ответа -----------------------------------------------------------


def test_location_without_guid_is_skipped() -> None:
    """Битый узел пропускается, а не роняет весь опрос KeyError."""
    payload = [
        {"name": "Без guid", "zones": []},
        copy.deepcopy(RAW_LOCATION)[0],
    ]
    snapshot = parse_snapshot(payload)
    assert BREEZER_GUID in snapshot.devices
    assert len(snapshot.locations) == 1


def test_device_without_guid_is_skipped() -> None:
    """Устройство без guid тоже пропускается."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["devices"].append({"name": "Безымянный", "type": "breezer3"})
    assert len(parse_snapshot(raw).devices) == 2


def test_missing_is_on_does_not_switch_breezer_off() -> None:
    """Модель не отдала is_on — бризер не должен считаться выключенным.

    Раньше скорость обнулялась, и ЛЮБАЯ команда уходила с is_on: false, то есть
    правка минимальной скорости физически гасила бы работающий бризер.
    """
    raw = copy.deepcopy(RAW_LOCATION)
    data = raw[0]["zones"][0]["devices"][1]["data"]
    del data["is_on"]
    data["speed"] = 3.0

    breezer = parse_snapshot(raw).devices[BREEZER_GUID]

    assert breezer.speed == 3.0
    assert breezer.is_on is True
    payload = breezer.mode_payload(speed_min_set=1)
    assert payload["is_on"] is True
    assert payload["speed"] == 3


def test_missing_is_on_and_zero_speed_is_off() -> None:
    """Нулевая скорость без флага — всё-таки выключенное состояние."""
    raw = copy.deepcopy(RAW_LOCATION)
    data = raw[0]["zones"][0]["devices"][1]["data"]
    del data["is_on"]
    data["speed"] = 0.0

    assert parse_snapshot(raw).devices[BREEZER_GUID].is_on is False


def test_unknown_zone_mode_survives() -> None:
    """Незнакомый режим зоны не подменяется ручным при правке порога CO2."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["mode"]["current"] = "schedule"

    zone = parse_snapshot(raw).devices[BREEZER_GUID].zone
    assert zone.mode_payload(target_co2=750) == {"mode": "schedule", "co2": 750}


def test_explicit_unknown_zone_mode_rejected() -> None:
    """А вот явную установку несуществующего режима надо отвергнуть."""
    with pytest.raises(TionCommandError, match="Неизвестный режим"):
        _breezer().zone.mode_payload(mode="турбо")


# --- поведение сущностей -----------------------------------------------------


async def test_climate_modes_follow_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Списки режимов пересчитываются, а не замораживаются первым снимком.

    Раньше они вычислялись в конструкторе: выпади heater_installed из первого
    же ответа облака, режим нагрева пропал бы до перезапуска Home Assistant.
    """
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    assert HVACMode.HEAT in hass.states.get(CLIMATE).attributes["hvac_modes"]

    raw = copy.deepcopy(RAW_LOCATION)
    data = raw[0]["zones"][0]["devices"][1]["data"]
    data["heater_installed"] = False
    data["heater_enabled"] = False
    data["speed_limit"] = 4.0
    mock_api.async_fetch.return_value = parse_snapshot(raw)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()

    attributes = hass.states.get(CLIMATE).attributes
    assert HVACMode.HEAT not in attributes["hvac_modes"]
    assert attributes["fan_modes"] == ["off", "auto", "1", "2", "3", "4"]


async def test_turn_off_uses_fresh_snapshot(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Выключение не затирает уставку, изменённую из приложения Tion.

    Между сменой режима зоны и отправкой параметров координатор перечитывает
    состояние. Раньше ветка OFF собирала payload из снимка, захваченного до
    этого, и возвращала облаку старый t_set.
    """
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["mode"]["current"] = ZONE_MODE_AUTO
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    async def raise_setpoint(*args: Any, **kwargs: Any) -> None:
        # Пользователь поднял температуру в приложении Tion, и опрос после
        # смены режима зоны это увидел.
        fresh = copy.deepcopy(RAW_LOCATION)
        fresh[0]["zones"][0]["devices"][1]["data"]["t_set"] = 27.0
        mock_api.async_fetch.return_value = parse_snapshot(fresh)

    mock_api.async_send_zone.side_effect = raise_setpoint

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    sent = mock_api.async_send_breezer.await_args
    assert sent.kwargs == {"speed": 0}
    # Команда собрана из свежего объекта, а не из захваченного до смены зоны.
    assert sent.args[0].t_set == 27.0


async def test_commands_are_serialised(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Команды разных платформ не выполняются внахлёст.

    PARALLEL_UPDATES ограничивает платформу, а не устройство, поэтому без общей
    блокировки climate и number собирали payload из одного снимка и затирали
    друг другу поля: облако принимает состояние целиком.
    """
    import asyncio

    from homeassistant.components.number import (
        ATTR_VALUE,
        DOMAIN as NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
    )
    from homeassistant.const import ATTR_TEMPERATURE
    from homeassistant.components.climate import SERVICE_SET_TEMPERATURE

    overlaps = 0
    running = 0

    async def slow(*args: Any, **kwargs: Any) -> None:
        nonlocal overlaps, running
        running += 1
        if running > 1:
            overlaps += 1
        await asyncio.sleep(0)
        running -= 1

    mock_api.async_send_breezer.side_effect = slow

    await asyncio.gather(
        hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 18},
            blocking=True,
        ),
        hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {
                ATTR_ENTITY_ID: "number.gostinaia_brizer_maximum_speed_in_auto",
                ATTR_VALUE: 5,
            },
            blocking=True,
        ),
    )

    assert overlaps == 0
    assert mock_api.async_send_breezer.await_count == 2


def test_zone_without_guid_is_skipped() -> None:
    """Зона без guid пропускается вместе со своими устройствами."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"].insert(0, {"name": "Битая", "devices": [{"guid": "x"}]})
    assert len(parse_snapshot(raw).devices) == 2


@pytest.mark.parametrize(
    "body", [{"text": "<html>отказ</html>"}, {"json": ["не словарь"]}]
)
async def test_command_rejection_without_description(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: dict[str, Any]
) -> None:
    """Отказ без разбираемого тела всё равно остаётся ошибкой команды."""
    aioclient_mock.post(AUTH_URL, json=TOKEN)
    aioclient_mock.get(LOCATION_URL, json=RAW_LOCATION)
    client = _client(hass)
    breezer = (await client.async_fetch()).devices[BREEZER_GUID]

    aioclient_mock.post(
        f"{API_BASE}/device/{BREEZER_GUID}/mode", status=409, **body
    )

    with pytest.raises(TionCommandError, match="409"):
        await client.async_send_breezer(breezer)
