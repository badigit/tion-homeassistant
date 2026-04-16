# Tion MagicAir Home Assistant Integration

A modern Home Assistant integration for Tion breezers and MagicAir sensors.

## Features
- **Climate Control**: Full support for Tion Breezer (S3, S4, Lite) including fan speeds (1-6) and heater control.
- **Sensors**: Real-time telemetry for CO2, Temperature, and Humidity from MagicAir and CO2+ stations.
- **Air Source Selection**: Choose between Street, Indoor, and Mixed air intake modes.
- **Filter Status**: Binary sensor for filter replacement alerts.
- **Config Flow**: Easy setup via the Home Assistant UI.
- **Modern Standards**: Uses `DataUpdateCoordinator`, `ConfigFlow`, `EntityDescriptions`, and `Diagnostics`.

## Installation

### Manual Installation
1. Copy the `custom_components/tion_magicair` directory to your Home Assistant `custom_components` folder.
2. Restart Home Assistant.
3. In the Home Assistant UI, go to **Settings** -> **Devices & Services** -> **Add Integration** and search for **Tion MagicAir**.

## Configuration
Setup is handled entirely via the UI. You will need your Tion MagicAir account credentials (email and password).

## Credits
Uses the `tion` Python library.
