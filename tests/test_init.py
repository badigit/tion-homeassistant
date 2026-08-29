"""Тесты жизненного цикла записи конфигурации."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.tion_magicair.api import TionAuthError, TionError
from custom_components.tion_magicair.const import DOMAIN

from .conftest import BREEZER_GUID, LOCATION_GUID, MAGICAIR_GUID


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Запись поднимается и выгружается без остатка."""
    assert init_integration.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_devices_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Локация становится хабом, устройства висят под ней."""
    registry = dr.async_get(hass)

    hub = registry.async_get_device(identifiers={(DOMAIN, LOCATION_GUID)})
    assert hub is not None
    assert hub.name == "Дом"
    # MAC локации — это адрес самой станции; отдать его хабу значило бы
    # отобрать устройство у станции, и HA выбросил бы её сущности.
    assert not hub.connections

    breezer = registry.async_get_device(identifiers={(DOMAIN, BREEZER_GUID)})
    assert breezer is not None
    assert breezer.model == "Tion 3S"
    assert breezer.model_id == "breezer3"
    assert breezer.sw_version == "018F"
    assert breezer.hw_version == "0001"
    assert breezer.serial_number == "SN-1"
    assert breezer.via_device_id == hub.id

    station = registry.async_get_device(identifiers={(DOMAIN, MAGICAIR_GUID)})
    assert station is not None
    assert station.model == "MagicAir 2"
    # Пустая строка серийника из облака не должна превращаться в пустой номер.
    assert station.serial_number is None


async def test_area_suggested_from_zone(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Комната берётся из имени зоны в облаке."""
    registry = dr.async_get(hass)
    breezer = registry.async_get_device(identifiers={(DOMAIN, BREEZER_GUID)})
    assert breezer.area_id is not None


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Облако отвергло данные — запись просит повторный вход, а не падает."""
    mock_api.async_fetch.side_effect = TionAuthError("пароль не тот")
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_connection_error_retries(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Сетевая ошибка — это повтор позже, а не запрос пароля."""
    mock_api.async_fetch.side_effect = TionError("облако молчит")
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_options_reload_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Смена интервала опроса перечитывает запись."""
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.update_interval.total_seconds() == 30


async def test_legacy_token_file_removed(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Файл токена от версии на библиотеке tion удаляется при первом старте."""
    config_entry.add_to_hass(hass)
    legacy = Path(
        hass.config.path(".storage", f"{DOMAIN}.{config_entry.entry_id}.token")
    )
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("Bearer старый-токен", encoding="utf-8")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert not legacy.exists()


async def test_token_saved_and_reused(
    hass: HomeAssistant, mock_api: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Токен переживает перезапуск: второй старт получает его из хранилища."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    from custom_components.tion_magicair import _token_store

    await _token_store(hass, config_entry).async_save({"token": "Bearer сохранённый"})

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    # Главное: сохранённый токен доехал до клиента, а не был прочитан впустую.
    assert (
        mock_api._mock_new_parent.call_args.kwargs["token"] == "Bearer сохранённый"
    )


async def test_remove_entry_drops_token(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Удаление записи уносит с собой сохранённый токен."""
    from custom_components.tion_magicair import _token_store

    store = _token_store(hass, init_integration)
    await store.async_save({"token": "Bearer test"})

    await hass.config_entries.async_remove(init_integration.entry_id)
    await hass.async_block_till_done()

    assert await store.async_load() is None
