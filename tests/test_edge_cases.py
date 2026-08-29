"""Тесты редких веток: отказы облака, пропажа устройства, мусор в ответе."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.tion_magicair import _token_store
from custom_components.tion_magicair.api import (
    TionApiClient,
    TionAuthError,
    TionConnectionError,
    TionSnapshot,
    _number,
    parse_snapshot,
)
from custom_components.tion_magicair.const import DOMAIN

from .conftest import RAW_LOCATION

CLIMATE = "climate.gostinaia_brizer"
SELECT = "select.gostinaia_brizer_air_source"


@pytest.mark.parametrize(
    "value", ["не число", object(), "NaN", float("nan"), None, True]
)
def test_number_helper_rejects_garbage(value: object) -> None:
    """Всё, что не является настоящим числом, превращается в None."""
    assert _number(value) is None


def test_number_helper_accepts_numbers() -> None:
    """Числа и числовые строки проходят."""
    assert _number("12.5") == 12.5
    assert _number(7) == 7.0


def test_station_recognised_by_co2_field() -> None:
    """Незнакомый тип с CO2 в телеметрии — это станция, а не бризер."""
    snapshot = parse_snapshot(
        [
            {
                "guid": "loc",
                "name": "Дом",
                "zones": [
                    {
                        "guid": "zone",
                        "name": "Комната",
                        "mode": {"current": "manual", "auto_set": {"co2": 900}},
                        "devices": [
                            {
                                "guid": "dev",
                                "name": "Датчик",
                                "type": "airStationX",
                                "data": {"co2": 500.0, "temperature": 22.0},
                            }
                        ],
                    }
                ],
            }
        ]
    )
    device = next(iter(snapshot.devices.values()))
    assert device.co2 == 500.0


async def test_client_wraps_aiohttp_errors() -> None:
    """Любая ошибка aiohttp наружу уходит как проблема связи."""

    class _BrokenSession:
        def request(self, *args: object, **kwargs: object) -> None:
            raise aiohttp.ClientError("соединение оборвано")

        def post(self, *args: object, **kwargs: object) -> None:
            raise aiohttp.ClientError("соединение оборвано")

    client = TionApiClient(_BrokenSession(), "owner@example.com", "секрет")
    with pytest.raises(TionConnectionError):
        await client.async_authenticate()

    client_with_token = TionApiClient(
        _BrokenSession(), "owner@example.com", "секрет", token="Bearer x"
    )
    with pytest.raises(TionConnectionError):
        await client_with_token.async_fetch()


async def test_token_is_persisted(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Интеграция сохраняет токен, о котором сообщил клиент."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Клиент создаётся интеграцией — забираем переданный ему обработчик.
    token_callback = mock_api._mock_new_parent.call_args.kwargs["token_callback"]
    await token_callback("Bearer свежий")

    assert await _token_store(hass, config_entry).async_load() == {
        "token": "Bearer свежий"
    }


async def test_unknown_device_creates_no_sensors(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Устройство неизвестного класса не порождает сущностей."""
    snapshot = parse_snapshot(copy.deepcopy(RAW_LOCATION))
    # Подсовываем объект, который не является ни бризером, ни станцией.
    snapshot.devices["чужак"] = object()
    mock_api.async_fetch.return_value = snapshot

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.gostinaia_magicair_co2") is not None
    # Раньше чужой объект ронял платформу binary_sensor целиком, а проверка
    # только sensor.* этого не замечала.
    assert hass.states.get("binary_sensor.gostinaia_magicair_connection") is not None
    assert hass.states.get("binary_sensor.gostinaia_brizer_fan_state") is not None


async def test_values_are_none_without_device(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Пропало устройство — сущности не выдумывают значения."""
    init_integration.runtime_data.data = TionSnapshot(locations={}, devices={})

    sensor = hass.data["entity_components"]["sensor"].get_entity(
        "sensor.gostinaia_brizer_speed"
    )
    binary = hass.data["entity_components"]["binary_sensor"].get_entity(
        "binary_sensor.gostinaia_brizer_fan_state"
    )
    assert sensor.native_value is None
    assert binary.is_on is None


@pytest.mark.parametrize("method", ["async_send_breezer", "async_send_zone"])
async def test_auth_error_during_command_asks_for_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AsyncMock,
    method: str,
) -> None:
    """Отвергнутый при команде токен ведёт в повторный вход."""
    getattr(mock_api, method).side_effect = TionAuthError("токен отозван")

    service, data = (
        (SERVICE_SET_TEMPERATURE, {ATTR_TEMPERATURE: 19})
        if method == "async_send_breezer"
        else (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.OFF})
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            service,
            {ATTR_ENTITY_ID: CLIMATE, **data},
            blocking=True,
        )

    # Раньше проверялось лишь то, что исключение всплыло. Но повторный вход
    # Home Assistant сам запускает только на путях настройки и планового
    # опроса, поэтому диалог обязан открыть координатор.
    await hass.async_block_till_done()
    assert [
        flow["context"]["source"] for flow in hass.config_entries.flow.async_progress()
    ] == ["reauth"]


async def test_select_raises_if_device_vanishes_midway(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Устройство пропало между сменой режима зоны и отправкой заслонки."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["mode"]["current"] = "auto"
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    async def vanish(*args: object, **kwargs: object) -> None:
        # Обнуляем и снимок, и источник: после смены режима зоны координатор
        # перечитывает состояние, иначе устройство тут же вернулось бы.
        empty = TionSnapshot(locations={}, devices={})
        mock_api.async_fetch.return_value = empty
        config_entry.runtime_data.data = empty

    mock_api.async_send_zone.side_effect = vanish

    entity = hass.data["entity_components"][SELECT_DOMAIN].get_entity(SELECT)
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("inside")


async def test_number_entity_registered_for_domain(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Числовые настройки принадлежат интеграции, а не другому домену."""
    entity = hass.data["entity_components"][NUMBER_DOMAIN].get_entity(
        "number.gostinaia_brizer_target_co2"
    )
    assert entity.unique_id.endswith("_target_co2")
    assert entity.device_info["identifiers"] == {
        (DOMAIN, "1b7e2c41-0000-4000-9000-b2ee5e000001")
    }
