"""Support for Tion select entities."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import TionData

GATE_MODES = {
    0: "Street",
    1: "Indoor",
    2: "Mixed",
}
INV_GATE_MODES = {v: k for k, v in GATE_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tion select platform."""
    data: TionData = entry.runtime_data
    coordinator = data.coordinator

    async_add_entities(
        TionGateSelect(coordinator, guid)
        for guid, device in coordinator.data.items()
        if device.type == "breezer"
    )


class TionGateSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Tion gate selection."""

    _attr_options = list(GATE_MODES.values())
    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator, guid):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._guid = guid
        device = coordinator.data[guid]
        self._attr_name = f"{device.name} Air Source"
        self._attr_unique_id = f"{DOMAIN}_{guid}_gate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, guid)},
            "name": device.name,
            "manufacturer": "Tion",
            "model": device.type,
        }

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        device = self.coordinator.data[self._guid]
        return GATE_MODES.get(device.gate)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        device = self.coordinator.data[self._guid]
        if (val := INV_GATE_MODES.get(option)) is not None:
            await self.hass.async_add_executor_job(device.set_state, {"gate": val})
            await self.coordinator.async_request_refresh()
