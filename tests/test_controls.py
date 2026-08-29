"""Тесты управляющих сущностей: climate, number, select."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.tion_magicair.api import (
    ZONE_MODE_AUTO,
    ZONE_MODE_MANUAL,
    TionError,
    parse_snapshot,
)

from .conftest import RAW_LOCATION

CLIMATE = "climate.gostinaia_brizer"
SELECT = "select.gostinaia_brizer_air_source"
NUMBER_MIN = "number.gostinaia_brizer_minimum_speed_in_auto"
NUMBER_MAX = "number.gostinaia_brizer_maximum_speed_in_auto"
NUMBER_CO2 = "number.gostinaia_brizer_target_co2"


async def _call(hass: HomeAssistant, domain: str, service: str, **data) -> None:
    """Вызвать службу и дождаться выполнения."""
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()


async def test_climate_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Атрибуты climate собраны из телеметрии бризера."""
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.HEAT
    # Текущая температура — воздух на выходе, целевая — уставка нагрева.
    assert state.attributes["current_temperature"] == 24.0
    assert state.attributes["temperature"] == 22.0
    assert state.attributes["min_temp"] == -20.0
    assert state.attributes["max_temp"] == 25.0
    # Потолок скоростей берётся у модели, а не захардкожен.
    assert state.attributes["fan_modes"] == ["off", "auto", "1", "2", "3", "4", "5", "6"]
    assert state.attributes["fan_mode"] == "2"
    assert state.attributes["zone_mode"] == ZONE_MODE_MANUAL
    assert state.attributes["zone_target_co2"] == 900.0
    assert state.attributes["zone_name"] == "Гостиная"


async def test_climate_set_temperature(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Целевая температура уходит целым числом."""
    await _call(
        hass, CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE,
        **{ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 18},
    )
    assert mock_api.async_send_breezer.await_args.kwargs == {"t_set": 18}


async def test_climate_set_temperature_without_value(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Вызов без температуры ничего не отправляет."""
    entity = hass.data["entity_components"][CLIMATE_DOMAIN].get_entity(CLIMATE)
    await entity.async_set_temperature()
    assert not mock_api.async_send_breezer.await_count


@pytest.mark.parametrize(
    ("hvac_mode", "expected"),
    [
        (HVACMode.HEAT, {"speed": 2, "heater_enabled": True}),
        (HVACMode.FAN_ONLY, {"speed": 2, "heater_enabled": False}),
    ],
)
async def test_climate_set_hvac_mode(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AsyncMock,
    hvac_mode: HVACMode,
    expected: dict,
) -> None:
    """Нагрев включается и выключается, скорость сохраняется."""
    await _call(
        hass, CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE,
        **{ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: hvac_mode},
    )
    assert mock_api.async_send_breezer.await_args.kwargs == expected


async def test_climate_turn_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Выключение переводит зону в ручной режим и обнуляет скорость."""
    await _call(hass, CLIMATE_DOMAIN, SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: CLIMATE})

    assert mock_api.async_send_zone.await_args.kwargs["mode"] == ZONE_MODE_MANUAL
    assert mock_api.async_send_breezer.await_args.kwargs == {"speed": 0}


async def test_climate_turn_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Включение выбирает нагрев, раз он у модели есть."""
    await _call(hass, CLIMATE_DOMAIN, SERVICE_TURN_ON, **{ATTR_ENTITY_ID: CLIMATE})
    assert mock_api.async_send_breezer.await_args.kwargs["heater_enabled"] is True


async def test_climate_fan_auto(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Скорость auto отдаёт зону под автоматику облака."""
    await _call(
        hass, CLIMATE_DOMAIN, SERVICE_SET_FAN_MODE,
        **{ATTR_ENTITY_ID: CLIMATE, ATTR_FAN_MODE: "auto"},
    )
    assert mock_api.async_send_zone.await_args.kwargs["mode"] == ZONE_MODE_AUTO
    assert not mock_api.async_send_breezer.await_count


@pytest.mark.parametrize(
    ("fan_mode", "expected_speed"), [("4", 4), ("off", 0)]
)
async def test_climate_fan_manual(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AsyncMock,
    fan_mode: str,
    expected_speed: int,
) -> None:
    """Конкретная скорость и выключение идут в ручном режиме зоны."""
    await _call(
        hass, CLIMATE_DOMAIN, SERVICE_SET_FAN_MODE,
        **{ATTR_ENTITY_ID: CLIMATE, ATTR_FAN_MODE: fan_mode},
    )
    assert mock_api.async_send_breezer.await_args.kwargs == {"speed": expected_speed}


async def test_climate_fan_switches_zone_to_manual(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Зона в auto — перед заданием скорости её переводят в ручной режим."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["mode"]["current"] = ZONE_MODE_AUTO
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CLIMATE).attributes["fan_mode"] == "auto"

    await _call(
        hass, CLIMATE_DOMAIN, SERVICE_SET_FAN_MODE,
        **{ATTR_ENTITY_ID: CLIMATE, ATTR_FAN_MODE: "3"},
    )
    assert mock_api.async_send_zone.await_args.kwargs["mode"] == ZONE_MODE_MANUAL
    assert mock_api.async_send_breezer.await_args.kwargs == {"speed": 3}


async def test_climate_off_when_device_off(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Выключенный бризер показывается как off, а не как продув."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["devices"][1]["data"]["is_on"] = False
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.OFF
    assert state.attributes["fan_mode"] == "off"


async def test_climate_without_heater(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """У модели без нагревателя режима HEAT в списке нет."""
    raw = copy.deepcopy(RAW_LOCATION)
    data = raw[0]["zones"][0]["devices"][1]["data"]
    data["heater_installed"] = False
    data["heater_enabled"] = False
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(CLIMATE)
    assert HVACMode.HEAT not in state.attributes["hvac_modes"]
    assert state.state == HVACMode.FAN_ONLY

    # turn_on тогда обязан выбрать продув, а не несуществующий нагрев.
    await _call(hass, CLIMATE_DOMAIN, SERVICE_TURN_ON, **{ATTR_ENTITY_ID: CLIMATE})


async def test_cloud_refusal_surfaces(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Отказ облака доходит до пользователя ошибкой, а не молчанием."""
    mock_api.async_send_breezer.side_effect = TionError("облако отклонило команду")

    with pytest.raises(HomeAssistantError, match="отклонило"):
        await _call(
            hass, CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE,
            **{ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 18},
        )


async def test_zone_refusal_surfaces(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Отказ на смене режима зоны тоже виден."""
    mock_api.async_send_zone.side_effect = TionError("зона занята")

    with pytest.raises(HomeAssistantError, match="зона занята"):
        await _call(
            hass, CLIMATE_DOMAIN, SERVICE_SET_FAN_MODE,
            **{ATTR_ENTITY_ID: CLIMATE, ATTR_FAN_MODE: "auto"},
        )


async def test_select_state_and_change(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Заслонка показывается и переключается."""
    assert hass.states.get(SELECT).state == "outside"

    await _call(
        hass, SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: SELECT, ATTR_OPTION: "inside"},
    )
    assert mock_api.async_send_breezer.await_args.kwargs == {"gate": 0}


async def test_select_switches_zone_to_manual(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Заслонку облако принимает только в ручном режиме зоны."""
    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["mode"]["current"] = ZONE_MODE_AUTO
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await _call(
        hass, SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: SELECT, ATTR_OPTION: "mixed"},
    )
    assert mock_api.async_send_zone.await_args.kwargs["mode"] == ZONE_MODE_MANUAL
    assert mock_api.async_send_breezer.await_args.kwargs == {"gate": 1}


async def test_select_absent_without_gate(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """У модели без заслонки сущности выбора нет."""
    raw = copy.deepcopy(RAW_LOCATION)
    del raw[0]["zones"][0]["devices"][1]["data"]["gate"]
    mock_api.async_fetch.return_value = parse_snapshot(raw)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(SELECT) is None


async def test_number_states(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Границы автоматики и порог CO2 читаются из облака."""
    assert hass.states.get(NUMBER_MIN).state == "0.0"
    assert hass.states.get(NUMBER_MAX).state == "3.0"
    assert hass.states.get(NUMBER_CO2).state == "900.0"
    # Потолок ползунка — предел модели, а не фиксированные шесть скоростей.
    assert hass.states.get(NUMBER_MAX).attributes["max"] == 6


@pytest.mark.parametrize(
    ("entity_id", "value", "expected"),
    [
        (NUMBER_MIN, 1, {"speed_min_set": 1.0}),
        (NUMBER_MAX, 5, {"speed_max_set": 5.0}),
    ],
)
async def test_number_set_speed_limits(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_id: str,
    value: int,
    expected: dict,
) -> None:
    """Границы скорости уходят бризеру."""
    await _call(
        hass, NUMBER_DOMAIN, SERVICE_SET_VALUE,
        **{ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
    )
    assert mock_api.async_send_breezer.await_args.kwargs == expected


async def test_number_set_target_co2(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Порог CO2 — свойство зоны, а не бризера."""
    await _call(
        hass, NUMBER_DOMAIN, SERVICE_SET_VALUE,
        **{ATTR_ENTITY_ID: NUMBER_CO2, ATTR_VALUE: 750},
    )
    assert mock_api.async_send_zone.await_args.kwargs == {
        "mode": None,
        "target_co2": 750.0,
    }
    assert not mock_api.async_send_breezer.await_count


async def test_controls_raise_when_device_gone(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Пропавшее устройство — ошибка, а не тихо применённая настройка."""
    from custom_components.tion_magicair.api import TionSnapshot

    empty = TionSnapshot(locations={}, devices={})
    init_integration.runtime_data.data = empty

    climate = hass.data["entity_components"][CLIMATE_DOMAIN].get_entity(CLIMATE)
    number = hass.data["entity_components"][NUMBER_DOMAIN].get_entity(NUMBER_CO2)
    select = hass.data["entity_components"][SELECT_DOMAIN].get_entity(SELECT)

    with pytest.raises(HomeAssistantError):
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 20})
    with pytest.raises(HomeAssistantError):
        await number.async_set_native_value(700)
    with pytest.raises(HomeAssistantError):
        await select.async_select_option("inside")

    # Пока устройства нет, значения не выдумываются.
    assert climate.hvac_mode is None
    assert climate.current_temperature is None
    assert climate.target_temperature is None
    assert climate.fan_mode is None
    assert climate.extra_state_attributes is None
    assert number.native_value is None
    assert select.current_option is None
