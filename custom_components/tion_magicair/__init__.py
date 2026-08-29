"""Интеграция Tion MagicAir."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import TionApiClient
from .const import CONFIGURATION_URL, DOMAIN, MANUFACTURER, TOKEN_STORE_VERSION
from .coordinator import TionConfigEntry, TionDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]


def _token_store(hass: HomeAssistant, entry: TionConfigEntry) -> Store[dict[str, Any]]:
    """Хранилище токена доступа для записи конфигурации."""
    return Store(hass, TOKEN_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_setup_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Поднять запись конфигурации."""
    await _async_drop_legacy_token(hass, entry)

    store = _token_store(hass, entry)
    stored = await store.async_load() or {}

    async def _async_save_token(token: str) -> None:
        await store.async_save({"token": token})

    client = TionApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        token=stored.get("token"),
        token_callback=_async_save_token,
    )

    coordinator = TionDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    _async_register_hubs(hass, entry, coordinator)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_register_hubs(
    hass: HomeAssistant, entry: TionConfigEntry, coordinator: TionDataUpdateCoordinator
) -> None:
    """Завести устройство-локацию, чтобы бризеры висели под ним.

    MAC локации намеренно не пишем: облако отдаёт там MAC самой станции
    MagicAir, и хаб отобрал бы его у настоящего устройства — HA отвергает
    второе устройство с тем же адресом и выбрасывает все его сущности.
    """
    registry = dr.async_get(hass)
    for location in coordinator.data.locations.values():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, location.guid)},
            name=location.name,
            manufacturer=MANUFACTURER,
            configuration_url=CONFIGURATION_URL,
        )


async def _async_drop_legacy_token(
    hass: HomeAssistant, entry: TionConfigEntry
) -> None:
    """Убрать файл токена, который писала прежняя версия на библиотеке tion."""
    path = hass.config.path(".storage", f"{DOMAIN}.{entry.entry_id}.token")

    def _remove() -> None:
        with contextlib.suppress(OSError):
            os.remove(path)

    await hass.async_add_executor_job(_remove)


async def async_reload_entry(hass: HomeAssistant, entry: TionConfigEntry) -> None:
    """Перечитать запись после смены опций."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Выгрузить запись конфигурации."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TionConfigEntry) -> None:
    """Убрать сохранённый токен вместе с записью конфигурации."""
    await _token_store(hass, entry).async_remove()
