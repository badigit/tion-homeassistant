"""Константы интеграции Tion MagicAir."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tion_magicair"

MANUFACTURER: Final = "Tion"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

TOKEN_STORE_VERSION: Final = 1

CONFIGURATION_URL: Final = "https://magicair.tion.ru/dashboard/overview"

# Порог CO₂ автоматики зоны: облако принимает и больше, но за этими границами
# режим auto теряет смысл.
MIN_TARGET_CO2: Final = 400
MAX_TARGET_CO2: Final = 2000

# Тип устройства из облака -> человеческое имя модели.
DEVICE_MODELS: Final = {
    "co2mb": "MagicAir",
    "co2plus": "MagicAir 2",
    "tionO2Rf": "Tion O₂ Rf",
    "breezer3": "Tion 3S",
    "breezer4": "Tion 4S",
    "tionLite": "Tion Lite",
}
