#!/usr/bin/env python3
"""Legge una posizione dal GPS collegato in seriale (frasi NMEA).

``sensors.py`` usa :func:`get_gps_fix` a ogni lettura dei sensori. Il parsing
delle frasi lo fa la libreria ``pynmea2``, che verifica anche il checksum e
riconosce sia ``$GPGGA`` (solo GPS) sia ``$GNGGA`` (più costellazioni).

Si può provare da solo, dalla cartella raspberry_pi/::

    python3 -m smartcam.gps_reader
"""
# Provenienza:
# - Il ciclo di lettura con scadenza è scritto da noi; l'apertura della porta
#   usa l'API standard di pySerial
#   (https://pyserial.readthedocs.io/en/latest/shortintro.html).
# - Il parsing delle frasi NMEA è delegato a pynmea2 (licenza MIT), usata come
#   indicato nel suo README: https://github.com/Knio/pynmea2
# - Il significato dei campi GGA (in particolare gps_qual = 0 -> nessun fix)
#   viene dalla specifica NMEA 0183, riassunta qui:
#   https://gpsd.gitlab.io/gpsd/NMEA.html#_gga_global_positioning_system_fix_data

import importlib.util
import logging
import time

from . import config
from .storage import iso, utc_now

logger = logging.getLogger(__name__)


def get_gps_fix(port: str = config.GPS_PORT, baudrate: int = config.GPS_BAUD,
                timeout_s: float = 5) -> dict | None:
    """Aspetta al massimo ``timeout_s`` secondi una frase GGA con un fix valido.

    Returns:
        Un dizionario con ora di ricezione, latitudine e longitudine in gradi
        decimali, quota, satelliti, qualità del fix e HDOP; ``None`` se entro
        il tempo non arriva nessun fix (non è un errore: il cielo può essere
        coperto).

    Raises:
        ImportError se mancano pyserial o pynmea2, ``serial.SerialException``
        se la porta non si apre. Chi chiama li registra come errore del GPS.
    """
    import serial

    # parse_gga importa pynmea2 solo quando arriva una riga: controlliamo
    # subito che ci sia, così l'errore non resta nascosto se il GPS tace.
    if importlib.util.find_spec("pynmea2") is None:
        raise ImportError("pynmea2 non installato")

    # timeout=1: readline() non resta bloccata più di un secondo, così si
    # ricontrolla spesso se è scaduto il tempo totale.
    with serial.Serial(port, baudrate=baudrate, timeout=1) as ser:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = ser.readline().decode("ascii", errors="replace").strip()
            fix = parse_gga(line)
            if fix:
                fix["measured_at_utc"] = iso(utc_now())
                return fix
    logger.info("Nessun fix GPS entro %ss su %s", timeout_s, port)
    return None


def parse_gga(line: str) -> dict | None:
    """Estrae posizione, quota, satelliti e qualità da una frase GGA.

    Restituisce ``None`` se la riga non è una GGA, se il checksum è sbagliato
    o se il ricevitore dice di non avere un fix (gps_qual = 0). Il controllo
    sulla qualità serve davvero: senza fix pynmea2 restituisce 0.0 come
    coordinate, che sembrerebbero valide.
    """
    import pynmea2

    # Le frasi NMEA sono del tipo "$GPGGA,...": i caratteri 3-5 dicono il tipo
    # di frase, i primi due ("GP", "GN", ...) la costellazione.
    if not line.startswith("$") or line[3:6] != "GGA":
        return None
    try:
        msg = pynmea2.parse(line)
    except pynmea2.ParseError as exc:
        # Comprende anche ChecksumError: riga corrotta, la scartiamo.
        logger.debug("GGA non valida: %s", exc)
        return None

    if not msg.gps_qual or not msg.lat or not msg.lon:
        return None

    return {
        # .latitude/.longitude di pynmea2 sono già gradi decimali con segno.
        "latitude": round(msg.latitude, 7),
        "longitude": round(msg.longitude, 7),
        "altitude_m": msg.altitude,
        "satellites": int(msg.num_sats) if msg.num_sats else None,
        # 1 = GPS, 2 = DGPS, 4/5 = RTK...: utile per filtrare i dati dopo.
        "fix_quality": msg.gps_qual,
        # Horizontal Dilution of Precision: più è basso, più la posizione è precisa.
        "hdop": float(msg.horizontal_dil) if msg.horizontal_dil else None,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_gps_fix())
