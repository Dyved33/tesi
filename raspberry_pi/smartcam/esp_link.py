#!/usr/bin/env python3
"""Scarica dall'ESP32 misure del BME280 ed eventi della camera.

L'ESP32 misura il BME280 ogni minuto e controlla la camera per vedere se c'è
movimento, anche quando il Pi è spento. Misure ed eventi restano in un buffer
dell'ESP finché il Pi non li scarica. Quando il Pi è acceso, :func:`sync`:

1. manda ``HELLO`` e riceve ``INFO`` (stato dell'ESP, del sensore e della camera);
2. manda ``TIME`` con l'ora del Pi, che l'ESP userà per forecaster e decider;
3. manda ``GET`` e riceve tutti i record del buffer (``M`` misure, ``E``
   eventi), poi ``END``;
4. salva su disco i record nuovi: misure in ``data/bme280.csv``, eventi in
   ``data/camera_events.csv``;
5. solo dopo il salvataggio manda ``ACK`` con l'ultimo record ricevuto bene,
   e l'ESP lo toglie dal buffer insieme a quelli prima.

Se qualcosa va storto prima dell'ACK l'ESP tiene i record e li rimanda la
volta dopo; i doppioni si riconoscono dalla coppia (boot dell'ESP, numero
progressivo). Il protocollo completo è in ``docs/protocollo-uart.md``.

Si lancia come modulo, dalla cartella raspberry_pi/::

    python3 -m smartcam.esp_link
"""
# Provenienza: scritto da noi. L'apertura della porta usa pySerial
# (https://pyserial.readthedocs.io/en/latest/shortintro.html); il checksum
# è lo stesso delle frasi NMEA 0183 (XOR dei caratteri prima di '*').

import logging
import time
from datetime import timedelta

from . import config
from .storage import append_rows, clock_synced, iso, read_tail, utc_now

logger = logging.getLogger(__name__)

# Significato del campo <esito> delle misure (enum EsitoMisura nel firmware).
STATUS = {
    0: "ok",
    1: "sensore_assente",
    2: "timeout",
    3: "fuori_scala",
    4: "senza_umidita",
}

# Colonne comuni: identificano il record e dicono quando è successo.
_COMMON = [
    "esp_boot_id",       # numero casuale scelto dall'ESP a ogni avvio
    "seq",               # numero progressivo del record, riparte a ogni avvio dell'ESP
    "measured_at_utc",   # quando è successo sull'ESP (ricevuto - age_ms)
    "received_at_utc",   # quando il Pi ha ricevuto la riga
    "age_ms",            # età del record al momento dell'invio
    "pi_clock_synced",   # 1 se l'orologio del Pi era sincronizzato con NTP
]
BME280_HEADER = _COMMON + ["status", "temperature_c", "humidity_pct", "pressure_hpa"]
EVENTS_HEADER = _COMMON + [
    "woke_pi",           # 1 se l'evento ha mandato l'impulso WAKE
    "changed_pct",       # percentuale di blocchi dell'immagine cambiati
    "mean_diff",         # differenza media di luminosità rispetto allo sfondo (0-255)
]

# Un'ora prima di questa vuol dire che l'orologio del Pi non è sincronizzato
# (né rete né batteria dell'RTC): in quel caso non la mandiamo all'ESP.
MIN_VALID_EPOCH = 1767225600  # 2026-01-01


class EspError(Exception):
    """L'ESP non risponde o risponde in modo inatteso."""


def _checksum(text: str) -> int:
    cs = 0
    for c in text:
        cs ^= ord(c)
    return cs


def parse_line(raw: str) -> list[str] | None:
    """Controlla il checksum e divide la riga nei campi.

    Restituisce ``None`` se la riga è vuota, senza checksum o corrotta.
    """
    line = raw.strip()
    if "*" not in line:
        return None
    text, cs = line.rsplit("*", 1)
    try:
        if int(cs, 16) != _checksum(text):
            return None
    except ValueError:
        return None
    return text.split(",")


def _float_or_none(s: str) -> float | None:
    return float(s) if s else None


def parse_record(fields: list[str], received_at) -> dict | None:
    """Trasforma una riga M o E in un dizionario con le colonne del CSV.

    Il campo ``kind`` ("M" o "E") dice in quale file va. ``None`` se la riga
    non ha il numero giusto di campi.
    """
    kind = fields[0]
    if (kind, len(fields)) not in (("M", 8), ("E", 7)):
        return None
    boot, seq, age_ms = fields[1], int(fields[2]), int(fields[3])
    record = {
        "kind": kind,
        "esp_boot_id": boot,
        "seq": seq,
        "measured_at_utc": iso(received_at - timedelta(milliseconds=age_ms)),
        "received_at_utc": iso(received_at),
        "age_ms": age_ms,
        "pi_clock_synced": clock_synced(),
    }
    if kind == "M":
        status = int(fields[4])
        record.update({
            "status": STATUS.get(status, f"sconosciuto_{status}"),
            "temperature_c": _float_or_none(fields[5]),
            "humidity_pct": _float_or_none(fields[6]),
            "pressure_hpa": _float_or_none(fields[7]),
        })
    else:
        record.update({
            "woke_pi": fields[4] == "1",
            "changed_pct": _float_or_none(fields[5]),
            "mean_diff": _float_or_none(fields[6]),
        })
    return record


def _read_reply(ser, expected: str) -> list[str]:
    """Legge righe finché ne arriva una valida che inizia con ``expected``."""
    deadline = time.monotonic() + ser.timeout * 2
    while time.monotonic() < deadline:
        raw = ser.readline().decode("ascii", errors="replace")
        if not raw:
            continue
        fields = parse_line(raw)
        if fields is None:
            logger.warning("Riga dall'ESP scartata: %r", raw)
            continue
        if fields[0] == expected:
            return fields
        if fields[0] == "ERR":
            raise EspError(f"l'ESP ha risposto ERR: {fields}")
    raise EspError(f"nessuna risposta {expected} dall'ESP")


def _send(ser, command: str) -> None:
    ser.write((command + "\n").encode("ascii"))


def _saved_keys() -> set[tuple[str, int]]:
    """Coppie (boot dell'ESP, seq) già presenti nei due CSV.

    Non basta il seq più alto: se una riga arriva corrotta l'ESP la rimanda
    al giro dopo, quando le successive sono già salvate.
    """
    keys = set()
    for path in (config.BME280_CSV, config.EVENTS_CSV):
        for row in read_tail(path):
            try:
                keys.add((row["esp_boot_id"], int(row["seq"])))
            except (KeyError, TypeError, ValueError):
                continue
    return keys


def sync(port: str = config.ESP_PORT, baudrate: int = config.ESP_BAUD,
         timeout_s: float = 2.0) -> dict:
    """Scarica i record dall'ESP, li salva e conferma la ricezione.

    Returns:
        Un dizionario con ``info`` (risposta a HELLO), ``received`` (righe
        valide), ``saved`` (righe nuove scritte nei CSV), ``acked`` (seq
        confermato, o None) e ``error`` (testo, o None se è andato tutto bene).
    """
    import serial  # import qui: il resto del modulo si usa anche senza pyserial

    result = {"info": None, "received": 0, "saved": 0, "acked": None, "error": None}
    try:
        with serial.Serial(port, baudrate=baudrate, timeout=timeout_s) as ser:
            ser.reset_input_buffer()

            _send(ser, "HELLO")
            info = _read_reply(ser, "INFO")
            # INFO,<boot>,<uptime_ms>,<chip_id>,<indirizzo>,<in_buffer>,<persi>,<camera>
            result["info"] = dict(zip(
                ["esp_boot_id", "uptime_ms", "chip_id", "i2c_address", "buffered", "lost",
                 "camera_ok"],
                info[1:],
            ))
            logger.info("ESP: %s", result["info"])
            if result["info"].get("lost", "0") != "0":
                logger.warning("L'ESP ha perso %s record per buffer pieno", result["info"]["lost"])

            now = time.time()
            if now >= MIN_VALID_EPOCH:
                _send(ser, f"TIME,{int(now)}")
                _read_reply(ser, "OK")
            else:
                logger.warning("Orologio del Pi non sincronizzato: TIME non inviato")

            _send(ser, "GET")
            records, ack_seq, broken = [], None, False
            while True:
                raw = ser.readline().decode("ascii", errors="replace")
                if not raw:
                    raise EspError("timeout durante GET")
                received_at = utc_now()
                fields = parse_line(raw)
                if fields is not None and fields[0] == "END":
                    break
                try:
                    record = parse_record(fields, received_at) if fields else None
                except ValueError:  # checksum giusto ma numeri malformati
                    record = None
                if record is None:
                    # Da qui in poi non confermiamo niente: la riga persa resta
                    # nell'ESP e arriverà al prossimo sync.
                    logger.warning("Riga corrotta durante GET: %r", raw)
                    broken = True
                    continue
                records.append(record)
                if not broken:
                    ack_seq = record["seq"]
            result["received"] = len(records)

            saved = _saved_keys()
            new = [r for r in records if (r["esp_boot_id"], r["seq"]) not in saved]
            result["saved"] = (
                append_rows(config.BME280_CSV, BME280_HEADER,
                            [_without_kind(r) for r in new if r["kind"] == "M"])
                + append_rows(config.EVENTS_CSV, EVENTS_HEADER,
                              [_without_kind(r) for r in new if r["kind"] == "E"])
            )

            if ack_seq is not None:
                _send(ser, f"ACK,{ack_seq}")
                _read_reply(ser, "OK")
                result["acked"] = ack_seq
    except Exception as exc:  # porta assente, ESP muta, errore di scrittura...
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.error("Sync con l'ESP fallito: %s", result["error"])
    return result


def _without_kind(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "kind"}


def latest_measurement() -> dict | None:
    """L'ultima misura del BME280 salvata, o None se non ce ne sono."""
    rows = read_tail(config.BME280_CSV, max_bytes=16 * 1024)
    return rows[-1] if rows else None


def latest_wake_event() -> dict | None:
    """L'ultimo evento della camera che ha acceso il Pi, o None."""
    rows = [r for r in read_tail(config.EVENTS_CSV, max_bytes=64 * 1024) if r.get("woke_pi") == "1"]
    return rows[-1] if rows else None


def main() -> int:
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    result = sync()
    print(result)
    return 0 if result["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
