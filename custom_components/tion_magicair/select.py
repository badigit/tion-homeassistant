"""Support for Tion select entities."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TionEntity
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


class TionGateSelect(TionEntity, SelectEntity):
    """Representation of a Tion gate selection."""

    _attr_options = list(GATE_MODES.values())
    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator, guid):
        """Initialize the select entity."""
        super().__init__(coordinator, guid)
        self._attr_name = "Air Source"
        self._attr_unique_id = f"{DOMAIN}_{guid}_gate"

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return GATE_MODES.get(self.device.gate)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if (val := INV_GATE_MODES.get(option)) is not None:
            await self.hass.async_add_executor_job(self.device.set_state, {"gate": val})
            await self.coordinator.async_request_refresh()
