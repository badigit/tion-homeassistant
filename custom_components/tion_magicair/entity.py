"""Базовая сущность Tion MagicAir."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import TionDataUpdateCoordinator, TionDevice


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
        self._guid: str = device.guid
        self._attr_unique_id = f"{device.guid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.guid)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=type(device).__name__,
        )

    @property
    def device(self) -> TionDevice | None:
        """Свежий объект устройства из последнего опроса."""
        return self.coordinator.data.get(self._guid)

    @property
    def available(self) -> bool:
        """Устройство пропало из аккаунта или облако отдало битые данные."""
        device = self.device
        return super().available and device is not None and device.valid


class TionDescribedEntity(TionEntity):
    """Сущность, у которой ключ берётся из EntityDescription."""

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
