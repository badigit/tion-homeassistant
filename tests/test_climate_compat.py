from homeassistant.components.climate import ClimateEntity
from homeassistant.const import UnitOfTemperature

from custom_components.tion_magicair.climate import TionClimate


def test_native_temperature_properties_have_legacy_fallback():
    assert isinstance(TionClimate.__dict__["native_current_temperature"], property)
    assert isinstance(TionClimate.__dict__["native_target_temperature"], property)

    # С HA 2026.11 метакласс CachedProperties оборачивает _attr_native_* в
    # property и уносит значение в закрытый __attr_native_*; на старом ядре
    # это обычный атрибут класса.
    unit = TionClimate.__dict__.get("_attr_native_temperature_unit")
    if isinstance(unit, property):
        unit = TionClimate.__dict__["__attr_native_temperature_unit"]
    assert unit == UnitOfTemperature.CELSIUS

    if not hasattr(ClimateEntity, "native_current_temperature"):
        assert TionClimate.current_temperature is TionClimate.native_current_temperature
        assert TionClimate.target_temperature is TionClimate.native_target_temperature
    else:
        assert "current_temperature" not in TionClimate.__dict__
        assert "target_temperature" not in TionClimate.__dict__
        assert "_attr_temperature_unit" not in TionClimate.__dict__
