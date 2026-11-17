#!/usr/bin/env python3
"""Lettura di un BME280 collegato direttamente al Raspberry Pi via I2C.

Serve SOLO per le prove al banco. Secondo plan.pdf, in campo il BME280 è
collegato all'ESP32 e il Pi dovrà ricevere le misure da lì (con il loro
timestamp), tramite un protocollo ESP→Pi che non abbiamo ancora scritto.

Ci sono tre librerie tra cui scegliere:
- ``adafruit``: libreria Adafruit CircuitPython;
- ``smbus``: libreria RPi.bme280 sopra smbus2 (più leggera, niente Blinka);
- ``dummy``: nessun hardware, restituisce un record vuoto.
Entrambe le librerie fanno la compensazione dei valori grezzi descritta nel
datasheet Bosch, quindi restituiscono misure vere.
"""
# Provenienza:
# - La scelta tra i backend e la struttura del modulo sono scritte da noi.
# - _read_bme280_adafruit() segue l'esempio ufficiale Adafruit (licenza MIT):
#   https://github.com/adafruit/Adafruit_CircuitPython_BME280/blob/main/examples/bme280_simpletest.py
#   (import "from adafruit_bme280 import basic", valido dalla versione 2.6.0).
# - _read_bme280_smbus() usa la libreria RPi.bme280 di Richard Hull (licenza MIT),
#   come nell'esempio del suo README: https://github.com/rm-hull/bme280
#   Prima qui c'era un segnaposto che leggeva solo il chip ID senza misure.

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Le librerie hardware potrebbero non essere installate (ad esempio sul PC
# di sviluppo): in quel caso ce lo segnamo e useremo un altro backend.
try:
    import board
    from adafruit_bme280 import basic as adafruit_bme280
    ADAFRUIT_AVAILABLE = True
except ImportError:
    ADAFRUIT_AVAILABLE = False
    logger.debug("adafruit-circuitpython-bme280 not available")

try:
    import smbus2
    import bme280
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False
    logger.debug("smbus2 / RPi.bme280 not available")


def get_bme280_reading(
    bus: int = 1,
    address: int = 0x76,
    library: str = "auto"
) -> Optional[Dict[str, Any]]:
    """Sceglie il backend disponibile e prova a fare una lettura.

    Args:
        bus: numero del bus I2C (sul Raspberry Pi è quasi sempre 1).
        address: indirizzo I2C del sensore: 0x76 con SDO a massa (il nostro
            schema in hardware/sensors/BME280), 0x77 con SDO a 3,3 V.
        library: "adafruit", "smbus", "dummy" oppure "auto" (prova prima
            Adafruit, poi SMBus, altrimenti dummy).

    Returns:
        Un dizionario con temperature (°C), humidity (%), pressure (hPa) e
        bme_address. Con il backend dummy i valori sono tutti ``None``; se la
        lettura hardware fallisce, o il backend chiesto non è installato,
        restituisce ``None``.
    """
    if library == "auto":
        if ADAFRUIT_AVAILABLE:
            library = "adafruit"
        elif SMBUS_AVAILABLE:
            library = "smbus"
        else:
            library = "dummy"

    if library == "adafruit":
        if not ADAFRUIT_AVAILABLE:
            logger.error("BME280: library 'adafruit' requested but not installed")
            return None
        return _read_bme280_adafruit(address)
    if library == "smbus":
        if not SMBUS_AVAILABLE:
            logger.error("BME280: library 'smbus' requested but not installed")
            return None
        return _read_bme280_smbus(bus, address)
    return _read_bme280_dummy()


def _read_bme280_adafruit(address: int) -> Optional[Dict[str, Any]]:
    """Legge il sensore con il driver CircuitPython di Adafruit.

    La libreria usa i pin I2C di default della scheda (bus 1 sul Pi), quindi
    non serve passare il numero del bus.
    """
    try:
        # Fonte: esempio bme280_simpletest.py di Adafruit (vedi intestazione).
        i2c = board.I2C()
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
    """Legge il sensore con RPi.bme280 + smbus2."""
    try:
        # Fonte: README di rm-hull/bme280. Prima si leggono i coefficienti di
        # calibrazione scritti in fabbrica nel chip, poi si fa una misura che
        # la libreria compensa con quei coefficienti.
        with smbus2.SMBus(bus) as i2c:
            calibration = bme280.load_calibration_params(i2c, address)
            data = bme280.sample(i2c, address, calibration)
        return {
            "temperature": data.temperature,
            "humidity": data.humidity,
            "pressure": data.pressure,
            "bme_address": hex(address),
        }
    except Exception as exc:
        logger.error(f"BME280 (SMBus) read failed: {exc}")
        return None


def _read_bme280_dummy() -> Optional[Dict[str, Any]]:
    """Record vuoto con la stessa forma di quello vero, per provare senza sensore."""
    return {
        "temperature": None,
        "humidity": None,
        "pressure": None,
        "bme_address": "dummy",
    }


if __name__ == "__main__":
    # Prova veloce, da raspberry_pi/: python3 -m smartcam.bme_reader
    logging.basicConfig(level=logging.INFO)
    reading = get_bme280_reading()
    print(reading)
