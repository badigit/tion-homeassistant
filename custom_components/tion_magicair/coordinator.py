"""Опрос облака Tion MagicAir."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TionApiClient,
    TionAuthError,
    TionBreezer,
    TionError,
    TionSnapshot,
    TionZone,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type TionConfigEntry = ConfigEntry[TionDataUpdateCoordinator]


class TionDataUpdateCoordinator(DataUpdateCoordinator[TionSnapshot]):
    """Держит один снимок аккаунта и раздаёт его сущностям."""

    config_entry: TionConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TionConfigEntry,
        client: TionApiClient,
    ) -> None:
        """Инициализировать координатор."""
        self.client = client
        # PARALLEL_UPDATES ограничивает платформу, а не устройство, поэтому
        # команда climate и команда number могут собрать payload из одного
        # снимка и затереть друг другу поля: облако принимает состояние
        # целиком. Одна блокировка на запись по всему аккаунту это исключает.
        self._command_lock = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )

    async def _async_update_data(self) -> TionSnapshot:
        """Прочитать состояние всех устройств аккаунта."""
        try:
            return await self.client.async_fetch()
        except TionAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TionError as err:
            raise UpdateFailed(str(err)) from err

    async def async_send_breezer(self, breezer: TionBreezer, **changes: Any) -> None:
        """Отправить бризеру новые параметры и перечитать состояние."""
        async with self._command_lock:
            await self._async_command(self.client.async_send_breezer(breezer, **changes))

    async def async_send_zone(
        self,
        zone: TionZone,
        *,
        mode: str | None = None,
        target_co2: float | None = None,
    ) -> None:
        """Отправить зоне новый режим или порог CO₂ и перечитать состояние."""
        async with self._command_lock:
            await self._async_command(
                self.client.async_send_zone(zone, mode=mode, target_co2=target_co2)
            )

    async def _async_command(self, coro: Awaitable[None]) -> None:
        """Выполнить команду, разобрать отказ и перечитать состояние."""
        try:
            await coro
        except TionAuthError as err:
            # Из обработчика службы ConfigEntryAuthFailed повторный вход НЕ
            # запускает: Home Assistant делает это только на путях настройки и
            # планового опроса. Просим диалог явно, иначе пользователь узнал бы
            # о смене пароля лишь на следующем тике — до часа при своём
            # интервале опроса.
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except TionError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
