"""Регрессии приватности выгружаемой диагностики."""

from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.core import HomeAssistant

from custom_components.tion_magicair.api import parse_snapshot

from .conftest import ACCOUNT, RAW_LOCATION


async def test_diagnostics_redacts_email_and_nested_personal_names(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_api: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """Email и личные названия скрыты, показания и исходные данные сохранены."""
    location_name = "Москва, улица Примерная, дом 42, квартира 7"
    zone_name = "Спальня Анны Ивановой"
    device_names = ["Станция Петра Петрова", "Бризер Марии Сидоровой"]
    raw = deepcopy(RAW_LOCATION)
    raw[0]["name"] = location_name
    zone = raw[0]["zones"][0]
    zone["name"] = zone_name
    for device, name in zip(zone["devices"], device_names, strict=True):
        device["name"] = name
    zone["devices"][0]["serial_number"] = "PRIVATE-STATION-SERIAL"
    snapshot = parse_snapshot(raw)
    original_snapshot = deepcopy(snapshot)
    mock_api.async_fetch.return_value = snapshot
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    original_entry = deepcopy(config_entry.as_dict())

    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    redacted = "**REDACTED**"
    assert result["config_entry"]["title"] == redacted
    assert result["config_entry"]["unique_id"] == redacted
    assert result["config_entry"]["data"]["username"] == redacted
    assert result["config_entry"]["data"]["password"] == redacted
    assert result["locations"][0]["name"] == redacted
    assert len(result["devices"]) == 2
    for device in result["devices"]:
        assert device["name"] == redacted
        assert device["zone"]["name"] == redacted
        for key in ("guid", "mac", "serial_number", "location_guid"):
            assert device[key] == redacted
        assert device["zone"]["guid"] == redacted

    serialized = json.dumps(result, ensure_ascii=False).casefold()
    for private_value in (
        *ACCOUNT.values(),
        location_name,
        zone_name,
        *device_names,
        "PRIVATE-STATION-SERIAL",
    ):
        assert private_value.casefold() not in serialized

    devices = {device["type"]: device for device in result["devices"]}
    assert result["last_update_success"] is True
    assert result["locations"][0]["is_online"] is True
    assert devices["co2plus"]["co2"] == 810.0
    assert devices["breezer3"]["t_in"] == 23.0
    assert devices["breezer3"]["zone"]["mode"] == "manual"
    assert devices["breezer3"]["zone"]["target_co2"] == 900.0
    assert snapshot == original_snapshot
    assert config_entry.as_dict() == original_entry
