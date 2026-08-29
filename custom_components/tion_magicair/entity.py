"""Базовая сущность Tion MagicAir."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TionBreezer, TionDevice
from .const import CONFIGURATION_URL, DEVICE_MODELS, DOMAIN, MANUFACTURER
from .coordinator import TionDataUpdateCoordinator


class TionEntity(CoordinatorEntity[TionDataUpdateCoordinator]):
    """Общий предок: держит guid устройства и достаёт его из координатора."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TionDataUpdateCoordinator,
        device: TionDevice,
        key: str,
    ) -> None:
        """Инициализировать сущность."""
        super().__init__(coordinator)
        self._guid = device.guid
        self._attr_unique_id = f"{device.guid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.guid)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=DEVICE_MODELS.get(device.type, device.type),
            model_id=device.type or None,
            sw_version=device.firmware,
            hw_version=device.hardware,
            serial_number=device.serial_number,
            configuration_url=CONFIGURATION_URL,
            via_device=(DOMAIN, device.location_guid),
        )
        # Имя зоны в облаке — это комната, поэтому оно же подсказка для HA.
        if device.zone.name:
            self._attr_device_info["suggested_area"] = device.zone.name
        if device.mac:
            self._attr_device_info["connections"] = {
                (CONNECTION_NETWORK_MAC, device.mac)
            }

    @property
    def device(self) -> TionDevice | None:
        """Свежий объект устройства из последнего опроса."""
        return self.coordinator.data.devices.get(self._guid)

    @property
    def available(self) -> bool:
        """Устройство пропало из аккаунта или облако отдало битые данные."""
        device = self.device
        return super().available and device is not None and device.valid


class TionBreezerEntity(TionEntity):
    """Сущность бризера с уточнённым типом."""

    @property
    def device(self) -> TionBreezer | None:
        """Свежий объект бризера."""
        device = self.coordinator.data.devices.get(self._guid)
        return device if isinstance(device, TionBreezer) else None


class TionDescribedEntity(TionEntity):
    """Сущность, у которой ключ и имя берутся из EntityDescription."""

    def __init__(
        self,
        coordinator: TionDataUpdateCoordinator,
        device: TionDevice,
        description: EntityDescription,
    ) -> None:
        """Инициализировать сущность по её описанию."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key


@callback
def async_add_entities_dynamically(
    coordinator: TionDataUpdateCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[TionDataUpdateCoordinator], list[Entity]],
) -> None:
    """Заводить сущности по мере появления, а не только по первому опросу.

    Бризер, который был offline в момент запуска, отдаёт неполную телеметрию:
    производительность, ресурс фильтра и заслонка тогда не создавались вовсе и
    не появлялись до перезагрузки Home Assistant. То же с устройством, которое
    добавили в аккаунт позже. Слушатель координатора доводит состав сущностей
    до фактического сам.
    """
    known: set[str] = set()

    @callback
    def _discover() -> None:
        fresh = [entity for entity in build(coordinator) if entity.unique_id not in known]
        if not fresh:
            return
        known.update(entity.unique_id for entity in fresh)
        async_add_entities(fresh)

    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_discover))
    _discover()
