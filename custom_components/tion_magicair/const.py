"""Константы интеграции Tion MagicAir."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tion_magicair"

MANUFACTURER: Final = "Tion"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

# Потолок скорости, когда облако не отдало speed_limit конкретной модели.
DEFAULT_MAX_SPEED: Final = 6

# Заслонка бризера: 0 — воздух из помещения, 1 — смешанный, 2 — с улицы.
GATE_INSIDE: Final = 0
GATE_MIXED: Final = 1
GATE_OUTSIDE: Final = 2

GATE_OPTIONS: Final = {
    GATE_INSIDE: "inside",
    GATE_MIXED: "mixed",
    GATE_OUTSIDE: "outside",
}
