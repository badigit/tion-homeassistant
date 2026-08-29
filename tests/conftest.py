"""Общие фикстуры тестов Tion MagicAir."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
import copy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from custom_components.tion_magicair.api import TionSnapshot, parse_snapshot
from custom_components.tion_magicair.const import DOMAIN

ACCOUNT = {
    CONF_USERNAME: "Owner@Example.COM",
    CONF_PASSWORD: "пароль-от-облака",
}

BREEZER_GUID = "1b7e2c41-0000-4000-9000-b2ee5e000001"
MAGICAIR_GUID = "9d4f6a02-0000-4000-9000-a1cc4d000002"
LOCATION_GUID = "5e8c1f30-0000-4000-9000-c3dd7e000003"

# Ответ /location, снятый с живого аккаунта и дополненный полями, которых у
# конкретного железа нет: заслонка у бризера и датчики пыли у станции. Так
# одним снимком покрываются обе ветки создания сущностей.
RAW_LOCATION: list[dict[str, Any]] = [
    {
        "guid": LOCATION_GUID,
        "name": "Дом",
        "mac": "02:00:00:AB:CD:00",
        "connection": {"is_online": True},
        "zones": [
            {
                "guid": "09e577af-f0c8-4e14-addb-fd2e38239566",
                "name": "Гостиная",
                "mode": {"current": "manual", "auto_set": {"co2": 900.0}},
                "devices": [
                    {
                        "guid": MAGICAIR_GUID,
                        "name": "MagicAir",
                        "type": "co2plus",
                        "mac": "02:00:00:AB:CD:01",
                        "is_online": True,
                        "firmware": "0760",
                        "hardware": "0001",
                        "serial_number": "",
                        "data": {
                            "co2": 810.0,
                            "temperature": 25.32,
                            "humidity": 52.66,
                            "pm1": 3.0,
                            "pm25": 5.0,
                            "pm10": 9.0,
                            "wi-fi": 120,
                            "signal_level": 0,
                            "backlight": 1,
                        },
                    },
                    {
                        "guid": BREEZER_GUID,
                        "name": "Бризер",
                        "type": "breezer3",
                        "mac": "02:00:00:AB:CD:02",
                        "is_online": True,
                        "firmware": "018F",
                        "hardware": "0001",
                        "serial_number": "SN-1",
                        "t_min": -20.0,
                        "t_max": 25.0,
                        "data": {
                            "is_on": True,
                            "data_valid": True,
                            "heater_installed": True,
                            "heater_enabled": True,
                            "speed": 2.0,
                            "speed_m3h": 75.0,
                            "speed_limit": 6.0,
                            "speed_min_set": 0,
                            "speed_max_set": 3,
                            "t_in": 23.0,
                            "t_set": 22.0,
                            "t_out": 24.0,
                            "gate": 2,
                            "run_seconds": 91836600,
                            "filter_time_seconds": 13023770,
                            "filter_need_replace": False,
                            "signal_level": 157,
                            "errors": {"code": "0x00000000"},
                        },
                    },
                ],
            }
        ],
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Разрешить загрузку кастомной интеграции во всех тестах."""


@pytest.fixture
def snapshot() -> TionSnapshot:
    """Состояние аккаунта, разобранное настоящим парсером."""
    return parse_snapshot(copy.deepcopy(RAW_LOCATION))


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Не поднимать интеграцию целиком: проверяется только диалог настройки."""
    with patch(
        "custom_components.tion_magicair.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Подменить клиента облака, который создаёт config flow."""
    with patch(
        "custom_components.tion_magicair.config_flow.TionApiClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.async_validate = AsyncMock(return_value=None)
        yield client


@pytest.fixture
def mock_api(snapshot: TionSnapshot) -> Generator[AsyncMock]:
    """Подменить транспорт: сеть не трогаем, разбор ответа настоящий."""
    with patch(
        "custom_components.tion_magicair.TionApiClient", autospec=True
    ) as mock_class:
        client = mock_class.return_value
        client.async_fetch = AsyncMock(return_value=snapshot)
        client.async_send_breezer = AsyncMock(return_value=None)
        client.async_send_zone = AsyncMock(return_value=None)
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Запись конфигурации интеграции."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=ACCOUNT[CONF_USERNAME].lower(),
        title=ACCOUNT[CONF_USERNAME],
        data=dict(ACCOUNT),
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> AsyncGenerator[MockConfigEntry]:
    """Поднятая интеграция с подменённым транспортом."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
