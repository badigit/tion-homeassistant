"""Опрос облака Tion MagicAir."""

from __future__ import annotations

from datetime import timedelta
import logging

from tion import Breezer, MagicAir, TionApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type TionDevice = Breezer | MagicAir
type TionConfigEntry = ConfigEntry[TionDataUpdateCoordinator]


class TionDataUpdateCoordinator(DataUpdateCoordinator[dict[str, TionDevice]]):
    """Держит одно подключение к облаку и раздаёт свежие устройства сущностям."""

    config_entry: TionConfigEntry
    api: TionApi

    def __init__(self, hass: HomeAssistant, entry: TionConfigEntry) -> None:
        """Инициализировать координатор."""
        self._scan_interval = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        # Токен переживает перезапуск: без него каждый старт тратит логин.
        self._auth_fname = hass.config.path(
            STORAGE_DIR, f"{DOMAIN}.{entry.entry_id}.token"
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._scan_interval),
        )

    async def _async_setup(self) -> None:
        """Создать клиента библиотеки (сетевой вызов, поэтому в executor)."""
        self.api = await self.hass.async_add_executor_job(self._create_api)

    def _create_api(self) -> TionApi:
        """Залогиниться в облаке Tion."""
        api = TionApi(
            self.config_entry.data[CONF_USERNAME],
            self.config_entry.data[CONF_PASSWORD],
            auth_fname=self._auth_fname,
            # Библиотека кэширует ответ облака на это время. Совпадение с нашим
            # интервалом опроса убирает второй HTTP-запрос внутри get_devices().
            min_update_interval_sec=self._scan_interval,
        )
        if not api.authorization:
            raise ConfigEntryAuthFailed("Облако Tion не выдало токен")
        return api

    async def _async_update_data(self) -> dict[str, TionDevice]:
        """Прочитать состояние всех устройств аккаунта."""
        return await self.hass.async_add_executor_job(self._fetch)

    def _fetch(self) -> dict[str, TionDevice]:
        """Синхронная часть опроса."""
        if not self.api.get_data(force=True):
            if not self.api.authorization:
                raise ConfigEntryAuthFailed("Облако Tion отозвало токен")
            raise UpdateFailed("Облако Tion не отдало данные")

        devices: dict[str, TionDevice] = {
            device.guid: device for device in self.api.get_devices()
        }
        if not devices:
            raise UpdateFailed("Облако Tion не вернуло ни одного устройства")
        return devices
