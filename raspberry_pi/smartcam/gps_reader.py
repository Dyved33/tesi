#!/usr/bin/env python3
"""Legge una posizione dal GPS collegato in seriale (frasi NMEA).

``capture_client.py`` e ``sensors.py`` usano :func:`get_gps_fix` per avere le
coordinate. Il parsing delle frasi lo fa la libreria ``pynmea2``, che
verifica anche il checksum e riconosce sia ``$GPGGA`` (solo GPS) sia
``$GNGGA`` (ricevitori multi-costellazione).

Se pyserial o pynmea2 non sono installati la funzione restituisce un record
"dummy" con tutti i campi a ``None``, così si può provare il resto del flusso
anche senza GPS.
"""
# Provenienza:
# - Il ciclo di lettura con scadenza e l'integrazione con il resto del
#   progetto sono scritti da noi; l'apertura della porta usa l'API standard
#   di pySerial (https://pyserial.readthedocs.io/en/latest/shortintro.html).
# - Il parsing delle frasi NMEA è delegato alla libreria pynmea2 (licenza MIT),
#   usata come indicato nel suo README: https://github.com/Knio/pynmea2
#   Prima avevamo un parser fatto a mano (split sulle virgole + conversione
#   gradi/minuti), che non controllava checksum e qualità del fix.
# - Il significato dei campi GGA (in particolare gps_qual = 0 -> nessun fix)
#   viene dalla specifica NMEA 0183, riassunta qui:
#   https://gpsd.gitlab.io/gpsd/NMEA.html#_gga_global_positioning_system_fix_data

import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    import serial
    import pynmea2
    GPS_LIBS_AVAILABLE = True
except ImportError:
    GPS_LIBS_AVAILABLE = False
    logger.warning("pyserial or pynmea2 not available")


def get_gps_fix(
    port: str = "/dev/ttyAMA0",
    baudrate: int = 9600,
    timeout_s: int = 5
) -> Optional[Dict[str, Any]]:
    """Aspetta al massimo ``timeout_s`` secondi una frase GGA con un fix valido.

    Args:
        port: device della porta seriale (sul Pi di solito /dev/ttyAMA0).
        baudrate: velocità della seriale; 9600 è il default di quasi tutti i moduli GPS.
        timeout_s: quanti secondi aspettare al massimo.

    Returns:
        Un dizionario con latitudine e longitudine in gradi decimali, quota,
        numero di satelliti, qualità del fix, HDOP e porta usata. ``None`` se
        scade il tempo o la lettura fallisce. Se mancano le librerie
        restituisce il record dummy (tutti i valori a ``None``).
    """
    if not GPS_LIBS_AVAILABLE:
        logger.error("pyserial or pynmea2 not installed")
        return _get_gps_dummy()

    try:
        # timeout=1 fa sì che readline() non resti bloccata a lungo: così ogni
        # secondo circa si ricontrolla se è scaduto il tempo totale.
        # Il "with" chiude la porta in ogni caso, anche se c'è un'eccezione.
        with serial.Serial(port, baudrate=baudrate, timeout=1) as ser:
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                line = ser.readline().decode("ascii", errors="replace").strip()
                fix = _parse_gga(line)
                if fix:
                    fix["gps_port"] = port
                    return fix
        logger.info(f"No GPS fix within {timeout_s}s on {port}")
        return None
    except Exception as exc:
        logger.error(f"GPS read failed on {port}: {exc}")
        return None


def _parse_gga(line: str) -> Optional[Dict[str, Any]]:
    """Estrae posizione, quota, satelliti e qualità da una frase GGA.

    Restituisce ``None`` se la riga non è una GGA, se il checksum è sbagliato
    o se il ricevitore dice di non avere un fix (gps_qual = 0). Il controllo
    sulla qualità serve davvero: senza fix pynmea2 restituisce 0.0 come
    coordinate, che sembrerebbero valide.
    """
    # Le frasi NMEA sono del tipo "$GPGGA,...": i caratteri 3-5 dicono il tipo
    # di frase, i primi due ("GP", "GN", ...) la costellazione.
    if not line.startswith("$") or line[3:6] != "GGA":
        return None
    try:
        msg = pynmea2.parse(line)
    except pynmea2.ParseError as exc:
        # Comprende anche ChecksumError: riga corrotta, la scartiamo.
        logger.debug(f"GGA parse failed: {exc}")
        return None

    if not msg.gps_qual or not msg.lat or not msg.lon:
        return None

    return {
        # .latitude/.longitude di pynmea2 sono già gradi decimali con segno.
        "latitude": round(msg.latitude, 7),
        "longitude": round(msg.longitude, 7),
        "altitude": msg.altitude,
        "satellites": int(msg.num_sats) if msg.num_sats else None,
        # 1 = GPS, 2 = DGPS, 4/5 = RTK...: utile per filtrare i dati dopo.
        "fix_quality": msg.gps_qual,
        # Horizontal Dilution of Precision: più è basso, più la posizione è precisa.
        "hdop": float(msg.horizontal_dil) if msg.horizontal_dil else None,
    }


def _get_gps_dummy() -> Optional[Dict[str, Any]]:
    """Record GPS vuoto, per usare il flusso senza hardware."""
    return {
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "satellites": None,
        "fix_quality": None,
        "hdop": None,
        "gps_port": "dummy",
    }


if __name__ == "__main__":
    # Prova veloce, da raspberry_pi/: python3 -m smartcam.gps_reader
    logging.basicConfig(level=logging.INFO)
    fix = get_gps_fix()
    print(fix)
