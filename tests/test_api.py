"""Тесты клиента облака Tion.

Клиент не зависит от Home Assistant, поэтому проверяется обычными юнит-тестами.
Здесь закрыты модели, которых у автора нет физически: 3S, 4S, Lite, — и те
грабли, на которые годами жаловались в issues заброшенного апстрима
airens/tion_home_assistant.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.tion_magicair.api import (
    ZONE_MODE_AUTO,
    ZONE_MODE_MANUAL,
    TionCommandError,
    TionBreezer,
    TionMagicAir,
    parse_snapshot,
)


def _location(*devices: dict[str, Any], zone_mode: str = ZONE_MODE_MANUAL) -> list[dict]:
    """Ответ /location с одной зоной и перечисленными устройствами."""
    return [
        {
            "guid": "loc-1",
            "name": "Дом",
            "mac": "00:11:22:33:44:55",
            "connection": {"is_online": True},
            "zones": [
                {
                    "guid": "zone-1",
                    "name": "Гостиная",
                    "mode": {"current": zone_mode, "auto_set": {"co2": 800.0}},
                    "devices": list(devices),
                }
            ],
        }
    ]


def _device(device_type: str, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Устройство в формате облака."""
    return {
        "guid": f"guid-{device_type}",
        "name": f"Устройство {device_type}",
        "type": device_type,
        "is_online": True,
        "data": data,
        **extra,
    }


BREEZER_DATA = {
    "is_on": True,
    "data_valid": True,
    "speed": 2.0,
    "speed_m3h": 75.0,
    "speed_limit": 6.0,
    "speed_min_set": 0,
    "speed_max_set": 6,
    "t_in": 5.0,
    "t_out": 20.0,
    "t_set": 20.0,
    "gate": 2,
    "heater_installed": True,
    "heater_enabled": True,
    "run_seconds": 3600,
    "filter_time_seconds": 86400,
    "filter_need_replace": False,
    "errors": {"code": "0x00000000"},
}


def test_magicair_nan_becomes_none() -> None:
    """Отсутствующий датчик приходит строкой NaN и не должен стать нулём."""
    snapshot = parse_snapshot(
        _location(
            _device(
                "co2mb",
                {
                    "co2": 700.0,
                    "temperature": 24.0,
                    "humidity": 45.0,
                    "pm25": "NaN",
                    "pm10": "NaN",
                    "pm1": "NaN",
                },
            )
        )
    )
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionMagicAir)
    assert device.co2 == 700.0
    # Апстрим отдавал NaN наружу, и у людей срабатывали автоматизации.
    assert (device.pm1, device.pm25, device.pm10) == (None, None, None)


@pytest.mark.parametrize("device_type", ["tionO2Rf", "breezer3", "breezer4", "tionLite"])
def test_known_breezer_types(device_type: str) -> None:
    """Все известные модели бризеров опознаются по имени типа."""
    snapshot = parse_snapshot(_location(_device(device_type, dict(BREEZER_DATA))))
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionBreezer)
    assert device.speed == 2.0
    assert device.max_speed == 6


def test_unknown_type_recognised_by_payload() -> None:
    """Новая модель опознаётся по составу телеметрии, а не по списку имён."""
    snapshot = parse_snapshot(
        _location(_device("tionSuperNova2030", dict(BREEZER_DATA)))
    )
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionBreezer)


def test_unknown_device_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """Совсем чужое устройство пропускается, но громко."""
    snapshot = parse_snapshot(
        _location(_device("danfossEco", {"battery": 80, "opening": 50}))
    )
    assert not snapshot.devices
    assert "не опознано" in caplog.text
    assert "danfossEco" in caplog.text


def test_4s_heater_without_flag() -> None:
    """4S не отдаёт heater_installed — иначе у него пропадал бы режим нагрева."""
    data = dict(BREEZER_DATA)
    del data["heater_installed"]
    del data["heater_enabled"]
    data["heater_mode"] = "heat"

    snapshot = parse_snapshot(_location(_device("breezer4", data)))
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionBreezer)
    assert device.heater_installed is True
    assert device.heater_enabled is True


def test_breezer_without_heater() -> None:
    """У модели без нагревателя он не должен появиться из ниоткуда."""
    data = dict(BREEZER_DATA)
    del data["heater_installed"]
    data["heater_enabled"] = False

    snapshot = parse_snapshot(_location(_device("tionLite", data)))
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionBreezer)
    assert device.heater_installed is False


def test_speed_zero_when_off() -> None:
    """Облако отдаёт speed 1 у выключенного бризера — наружу должен идти 0."""
    data = dict(BREEZER_DATA, is_on=False, speed=1.0)
    snapshot = parse_snapshot(_location(_device("breezer3", data)))
    device = next(iter(snapshot.devices.values()))
    assert device.speed == 0


def _breezer(zone_mode: str = ZONE_MODE_MANUAL, **overrides: Any) -> TionBreezer:
    """Разобранный бризер с подменёнными полями телеметрии."""
    snapshot = parse_snapshot(
        _location(
            _device("breezer3", dict(BREEZER_DATA, **overrides)), zone_mode=zone_mode
        )
    )
    device = next(iter(snapshot.devices.values()))
    assert isinstance(device, TionBreezer)
    return device


def test_payload_turn_off_uses_is_on() -> None:
    """Скорости 0 в протоколе нет: выключение задаётся флагом is_on."""
    payload = _breezer().mode_payload(speed=0)
    assert payload["is_on"] is False
    assert payload["speed"] == 1


def test_payload_keeps_untouched_fields() -> None:
    """Меняем скорость — остальное состояние уходит без изменений."""
    payload = _breezer().mode_payload(speed=4)
    assert payload["speed"] == 4
    assert payload["is_on"] is True
    assert payload["t_set"] == 20
    assert payload["speed_max_set"] == 6
    assert payload["heater_mode"] == "heat"


def test_payload_gate_only_in_manual_zone() -> None:
    """В автоматическом режиме зоны заслонка в запрос не попадает."""
    assert "gate" not in _breezer(zone_mode=ZONE_MODE_AUTO).mode_payload()
    assert _breezer(zone_mode=ZONE_MODE_MANUAL).mode_payload()["gate"] == 2


def test_payload_explicit_gate_survives_stale_zone() -> None:
    """Заслонка, заданная явно, уходит даже если снимок зоны ещё «auto».

    Вызывающий переводит зону в ручной режим и сразу шлёт заслонку, а его
    снимок об этом ещё не знает. Без этого выбор источника воздуха молча не
    применялся бы — самая частая жалоба в issues апстрима.
    """
    payload = _breezer(zone_mode=ZONE_MODE_AUTO).mode_payload(gate=0)
    assert payload["gate"] == 0


def test_zone_payload_keeps_target_co2() -> None:
    """Смена режима зоны не должна сбрасывать порог CO2 на 900."""
    breezer = _breezer()
    payload = breezer.zone.mode_payload(mode=ZONE_MODE_AUTO)
    assert payload == {"mode": ZONE_MODE_AUTO, "co2": 800}


def test_zone_payload_defaults_when_cloud_silent() -> None:
    """Если порога в облаке нет, команда не отправляется.

    Раньше подставлялось 900, и смена режима зоны затирала настройку
    пользователя в облаке.
    """
    snapshot = parse_snapshot(
        [
            {
                "guid": "loc-1",
                "name": "Дом",
                "zones": [
                    {
                        "guid": "zone-1",
                        "name": "Гостиная",
                        "mode": {"current": ZONE_MODE_MANUAL},
                        "devices": [_device("breezer3", dict(BREEZER_DATA))],
                    }
                ],
            }
        ]
    )
    zone = next(iter(snapshot.devices.values())).zone
    with pytest.raises(TionCommandError, match="порог CO2"):
        zone.mode_payload()


def test_offline_device_is_not_valid() -> None:
    """Пропавший из сети бризер помечается недостоверным."""
    snapshot = parse_snapshot(
        _location(_device("breezer3", dict(BREEZER_DATA), is_online=False))
    )
    assert next(iter(snapshot.devices.values())).valid is False


def test_stale_data_is_not_valid() -> None:
    """Облако само сообщает, что телеметрия протухла."""
    snapshot = parse_snapshot(
        _location(_device("breezer3", dict(BREEZER_DATA, data_valid=False)))
    )
    assert next(iter(snapshot.devices.values())).valid is False
