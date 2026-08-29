"""Тесты сенсоров, бинарных сенсоров и диагностики."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.tion_magicair.api import TionBreezer, parse_snapshot

from .conftest import BREEZER_GUID, RAW_LOCATION

BREEZER = "gostinaia_brizer"
STATION = "gostinaia_magicair"


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.gostinaia_magicair_co2", "810.0"),
        ("sensor.gostinaia_magicair_temperature", "25.32"),
        ("sensor.gostinaia_magicair_humidity", "52.66"),
        ("sensor.gostinaia_magicair_pm1", "3.0"),
        ("sensor.gostinaia_magicair_pm2_5", "5.0"),
        ("sensor.gostinaia_magicair_pm10", "9.0"),
        ("sensor.gostinaia_magicair_wi_fi_signal", "120.0"),
        ("sensor.gostinaia_brizer_temperature_in", "23.0"),
        ("sensor.gostinaia_brizer_temperature_out", "24.0"),
        ("sensor.gostinaia_brizer_speed", "2.0"),
        ("sensor.gostinaia_brizer_airflow", "75.0"),
        ("sensor.gostinaia_brizer_signal_level", "157.0"),
        ("sensor.gostinaia_brizer_error_code", "0x00000000"),
    ],
)
async def test_sensor_states(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_id: str,
    expected: str,
) -> None:
    """Каждая величина доезжает до своей сущности."""
    state = hass.states.get(entity_id)
    assert state is not None, f"нет сущности {entity_id}"
    assert state.state == expected


async def test_derived_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Секунды из облака пересчитываются в дни и часы."""
    # 13023770 секунд ресурса фильтра — это 150.7 суток.
    filter_left = hass.states.get("sensor.gostinaia_brizer_filter_life_left")
    assert float(filter_left.state) == pytest.approx(150.7, abs=0.1)

    # 91836600 секунд наработки — это 25510 часов.
    run_time = hass.states.get("sensor.gostinaia_brizer_run_time")
    assert float(run_time.state) == pytest.approx(25510, abs=1)


async def test_binary_sensor_states(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Вентилятор, фильтр и связь."""
    assert hass.states.get("binary_sensor.gostinaia_brizer_fan_state").state == STATE_ON
    assert (
        hass.states.get(
            "binary_sensor.gostinaia_brizer_filter_replacement_required"
        ).state
        == STATE_OFF
    )
    assert (
        hass.states.get("binary_sensor.gostinaia_brizer_connection").state == STATE_ON
    )
    assert (
        hass.states.get("binary_sensor.gostinaia_magicair_connection").state == STATE_ON
    )


async def test_diagnostic_entities_categorised(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Служебные сущности не засоряют карточку устройства."""
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.gostinaia_brizer_run_time",
        "sensor.gostinaia_brizer_signal_level",
        "sensor.gostinaia_brizer_error_code",
        "binary_sensor.gostinaia_brizer_connection",
    ):
        assert registry.async_get(entity_id).entity_category is EntityCategory.DIAGNOSTIC


async def test_sensor_skipped_without_data(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Датчика нет в модели — сущности тоже нет."""
    import copy

    raw = copy.deepcopy(RAW_LOCATION)
    station = raw[0]["zones"][0]["devices"][0]
    for field in ("pm1", "pm25", "pm10"):
        station["data"][field] = "NaN"
    mock_api.async_fetch.return_value = parse_snapshot(raw)

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.gostinaia_magicair_pm1") is None
    assert hass.states.get("sensor.gostinaia_magicair_co2") is not None


async def test_entities_unavailable_when_device_offline(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Пропавший бризер уводит свои сущности в unavailable, кроме связи."""
    import copy
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    raw = copy.deepcopy(RAW_LOCATION)
    raw[0]["zones"][0]["devices"][1]["is_online"] = False
    mock_api.async_fetch.return_value = parse_snapshot(raw)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.gostinaia_brizer_speed").state == STATE_UNAVAILABLE
    # Сенсор связи обязан пережить пропажу — иначе он не сможет о ней сообщить.
    assert (
        hass.states.get("binary_sensor.gostinaia_brizer_connection").state == STATE_OFF
    )


async def test_entities_unavailable_when_poll_fails(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: AsyncMock
) -> None:
    """Провал опроса тоже уводит сущности в unavailable."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util

    from custom_components.tion_magicair.api import TionError

    mock_api.async_fetch.side_effect = TionError("облако молчит")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.gostinaia_magicair_co2").state == STATE_UNAVAILABLE
    assert (
        hass.states.get("binary_sensor.gostinaia_brizer_connection").state
        == STATE_UNAVAILABLE
    )


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Диагностика отдаёт состояние и прячет то, что указывает на владельца."""
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    assert result["last_update_success"] is True
    assert result["config_entry"]["data"]["username"] == "**REDACTED**"
    assert result["config_entry"]["data"]["password"] == "**REDACTED**"

    devices = {d["type"]: d for d in result["devices"]}
    breezer, station = devices["breezer3"], devices["co2plus"]

    assert breezer["t_in"] == 23.0
    assert breezer["zone"]["mode"] == "manual"
    assert breezer["guid"] == "**REDACTED**"
    assert breezer["mac"] == "**REDACTED**"
    assert breezer["serial_number"] == "**REDACTED**"
    assert station["co2"] == 810.0


async def test_snapshot_has_expected_devices(snapshot) -> None:
    """Фикстура снимка описывает ровно то, что ждут тесты."""
    assert len(snapshot.devices) == 2
    breezer = snapshot.devices[BREEZER_GUID]
    assert isinstance(breezer, TionBreezer)
    assert breezer.gate == 2
