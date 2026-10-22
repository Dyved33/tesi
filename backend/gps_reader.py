#!/usr/bin/env python3
"""
GPS sensor reader for backend package.

Provides get_gps_fix() compatible with capture_client.py expectations.
Wraps the NMEA parsing logic from sensors.py.
"""

import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.warning("pyserial not available")


def get_gps_fix(
    port: str = "/dev/ttyAMA0",
    baudrate: int = 9600,
    timeout_s: int = 5
) -> Optional[Dict[str, Any]]:
    """
    Get GPS fix from NMEA serial stream.

    Args:
        port: Serial port device path
        baudrate: Baud rate (default 9600 for most GPS modules)
        timeout_s: Maximum seconds to wait for a fix

    Returns:
        Dict with keys: latitude, longitude, altitude, satellites, gps_port
        Returns None if no fix within timeout.
    """
    if not SERIAL_AVAILABLE:
        logger.error("pyserial not installed")
        return _get_gps_dummy()

    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=1)
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            line = ser.readline().decode("ascii", errors="replace").strip()
            if line.startswith("$GPGGA"):
                fix = _parse_gpgga(line)
                if fix:
                    fix["gps_port"] = port
                    ser.close()
                    return fix
        ser.close()
        logger.info(f"No GPS fix within {timeout_s}s on {port}")
        return None
    except Exception as exc:
        logger.error(f"GPS read failed on {port}: {exc}")
        return None


def _parse_gpgga(line: str) -> Optional[Dict[str, Any]]:
    """Parse $GPGGA NMEA sentence."""
    try:
        parts = line.split(",")
        # $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx
        if len(parts) < 10 or not parts[2] or not parts[4]:
            return None

        lat = _parse_nmea_coord(parts[2], parts[3])
        lon = _parse_nmea_coord(parts[4], parts[5])
        alt = float(parts[9]) if parts[9] else None
        sats = int(parts[7]) if parts[7] else None

        if lat is None or lon is None:
            return None

        return {
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "satellites": sats,
        }
    except Exception as exc:
        logger.error(f"GPGGA parse failed: {exc}")
        return None


def _parse_nmea_coord(value: str, direction: str) -> Optional[float]:
    """Convert NMEA DDMM.MMMM to decimal degrees."""
    if not value:
        return None
    try:
        d = float(value)
        deg = int(d / 100)
        minutes = d - deg * 100
        dec = deg + minutes / 60.0
        if direction in ("S", "W"):
            dec = -dec
        return round(dec, 7)
    except ValueError:
        return None


def _get_gps_dummy() -> Optional[Dict[str, Any]]:
    """Dummy GPS reading for testing."""
    return {
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "satellites": None,
        "gps_port": "dummy",
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    fix = get_gps_fix()
    print(fix)