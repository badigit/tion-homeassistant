"""Base entity for Tion MagicAir."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TionDataUpdateCoordinator


class TionEntity(CoordinatorEntity[TionDataUpdateCoordinator]):
    """Base class for Tion entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TionDataUpdateCoordinator, guid: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._guid = guid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, guid)},
            name=self.device.name,
            manufacturer="Tion",
            model=self.device.type.capitalize(),
        )

    @property
    def device(self):
        """Return the device from coordinator."""
        return self.coordinator.data[self._guid]
