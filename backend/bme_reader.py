#!/usr/bin/env python3
"""
BME280 reading helper for the backend package.

Per plan.pdf the field BME280 is attached only to the ESP32; the Pi should
consume forwarded samples (with measurement timestamp). This module still
supports direct I2C on the Pi for bench tests and for capture_client.py until
the ESP→Pi protocol is in place.

Provides get_bme280_reading() compatible with capture_client.py.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Try to import the Adafruit library
try:
    import board
    import busio
    import adafruit_bme280
    ADAFRUIT_AVAILABLE = True
except ImportError:
    ADAFRUIT_AVAILABLE = False
    logger.warning("adafruit-circuitpython-bme280 not available")

# Try to import smbus2 as fallback
try:
    import smbus2
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False
    logger.warning("smbus2 not available")


def get_bme280_reading(
    bus: int = 1,
    address: int = 0x77,
    library: str = "auto"
) -> Optional[Dict[str, Any]]:
    """
    Read BME280 sensor data.

    Args:
        bus: I2C bus number (default 1 on Raspberry Pi)
        address: I2C address (0x76 or 0x77)
        library: "adafruit", "smbus", "auto", or "dummy"

    Returns:
        Dict with keys: temperature (C), humidity (%), pressure (hPa), bme_address
        Returns None if reading fails.
    """
    if library == "auto":
        if ADAFRUIT_AVAILABLE:
            library = "adafruit"
        elif SMBUS_AVAILABLE:
            library = "smbus"
        else:
            library = "dummy"

    if library == "adafruit" and ADAFRUIT_AVAILABLE:
        return _read_bme280_adafruit(bus, address)
    elif library == "smbus" and SMBUS_AVAILABLE:
        return _read_bme280_smbus(bus, address)
    else:
        return _read_bme280_dummy()


def _read_bme280_adafruit(bus: int, address: int) -> Optional[Dict[str, Any]]:
    """Read BME280 via Adafruit CircuitPython library."""
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        bme = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
        return {
            "temperature": bme.temperature,
            "humidity": bme.relative_humidity,
            "pressure": bme.pressure,
            "bme_address": hex(address),
        }
    except Exception as exc:
        logger.error(f"BME280 (Adafruit) read failed: {exc}")
        return None


def _read_bme280_smbus(bus: int, address: int) -> Optional[Dict[str, Any]]:
    """Read BME280 via raw SMBus (no compensation - returns raw values)."""
    try:
        smbus = smbus2.SMBus(bus)
        # Read chip ID to verify presence
        chip_id = smbus.read_byte_data(address, 0xD0)
        if chip_id != 0x60:
            logger.error(f"BME280 not found at {hex(address)} (chip ID: {hex(chip_id)})")
            return None

        # NOTE: This returns RAW uncompensated values!
        # For proper readings, use the Adafruit library which handles compensation.
        # This is a minimal placeholder.
        logger.warning("BME280 SMBus read returns raw values without compensation")
        return {
            "temperature": None,
            "humidity": None,
            "pressure": None,
            "bme_address": hex(address),
        }
    except Exception as exc:
        logger.error(f"BME280 (SMBus) read failed: {exc}")
        return None


def _read_bme280_dummy() -> Optional[Dict[str, Any]]:
    """Dummy reading for testing without hardware."""
    return {
        "temperature": None,
        "humidity": None,
        "pressure": None,
        "bme_address": "dummy",
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    reading = get_bme280_reading()
    print(reading)