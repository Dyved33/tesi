#!/usr/bin/env python3
"""Legge una volta tutti i sensori collegati al Pi e aggiunge una riga a data/sensors.csv.

I sensori vengono letti uno dopo l'altro (un "burst"), non nello stesso
istante: per questo la riga ha l'ora di inizio e di fine del burst, più l'ora
del fix GPS. Il BME280 non è qui: è collegato all'ESP32 e le sue misure
arrivano con ``esp_link`` in un file a parte.

Per adattare lo script al cablaggio basta modificare il dizionario SENSORS.
Con ``"dummy": True`` un sensore non viene letto (serve per provare il resto
senza hardware) e finisce nella colonna ``sensors_dummy``; uno che va in
errore finisce in ``sensors_failed``. Solo i sensori letti davvero finiscono
in ``sensors_ok``.

Si lancia come modulo, dalla cartella raspberry_pi/::

    python3 -m smartcam.sensors                  # una lettura, una riga nel CSV
    python3 -m smartcam.sensors --calibra-suolo  # tensione media della sonda del suolo
"""
# Provenienza:
# - Il dizionario di configurazione, il ciclo di lettura e il formato del CSV
#   sono scritti da noi.
# - read_adc() usa la classe MCP3008 di gpiozero (licenza BSD), preinstallata
#   su Raspberry Pi OS: https://gpiozero.readthedocs.io/en/stable/api_spi.html#mcp3008
# - Gli ingressi digitali usano DigitalInputDevice come da documentazione
#   gpiozero: https://gpiozero.readthedocs.io/en/stable/api_input.html
# - Le vecchie varianti con RPi.GPIO sono state tolte: RPi.GPIO non funziona
#   sul Pi 5 (il GPIO passa dal chip RP1), gpiozero invece sì.

import logging
import sys
import time

from . import config
from .gps_reader import get_gps_fix
from .storage import append_rows, clock_synced, iso, utc_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURAZIONE: da adattare ai modelli di sensore che compreremo.
# I pin sono quelli di docs/pinout.md (numerazione BCM).
# ---------------------------------------------------------------------------
SENSORS = {
    # GPS su UART2 (GPIO4/GPIO5)
    "gps": {
        "dummy": False,
        "port": config.GPS_PORT,
        "baudrate": config.GPS_BAUD,
        "timeout_s": 5,
    },
    # Presenza d'acqua: galleggiante o sonda conduttiva su un ingresso digitale
    "water": {
        "dummy": False,
        "pin": 27,
        "pull_up": True,          # True se il contatto chiude verso GND quando è bagnato
    },
    # Umidità del suolo: sonda analogica sul canale 0 dell'MCP3008
    "soil_moisture": {
        "dummy": False,
        "interface": "adc",       # adc | digital (uscita DO a soglia del modulo)
        "adc_device": 0,          # chip select: 0 = CE0 (GPIO8), 1 = CE1 (GPIO7)
        "adc_channel": 0,
        "adc_vref": 3.3,          # tensione collegata a VREF dell'MCP3008
        # Tensioni misurate con la sonda in aria e in acqua: servono a
        # calcolare la percentuale. Finché non le misuriamo restano None e la
        # percentuale non viene scritta.
        "volt_dry": None,
        "volt_wet": None,
        "digital_pin": 22,
        "digital_wet_level": False,  # livello di DO che significa "bagnato"
    },
    # Metano, serie MQ (MQ-4): analogico sul canale 1 dell'MCP3008
    "methane": {
        "dummy": False,
        "interface": "adc",       # adc | digital
        "adc_device": 0,
        "adc_channel": 1,
        "adc_vref": 3.3,
        # Il modulo MQ-4 va alimentato a 5 V e la sua uscita arriva a 5 V,
        # mentre l'MCP3008 con VREF a 3,3 V legge al massimo 3,3 V. Tra AO e
        # CH1 c'è un partitore: R_top in serie, R_bottom verso GND.
        # Con 10 kΩ e 18 kΩ i 5 V diventano 5 * 18 / 28 = 3,21 V.
        # Il codice moltiplica per (R_top + R_bottom) / R_bottom per salvare
        # la tensione vera del sensore. Senza partitore: divider_r_top = 0.
        "divider_r_top": 10_000,
        "divider_r_bottom": 18_000,
        "digital_pin": 23,             # anche DO è a 5 V: stesso partitore
        "digital_alarm_level": True,   # livello di DO che significa "allarme"
    },
}

SENSORS_HEADER = [
    "sensors_clock_synced",
    "sensors_started_at_utc",
    "sensors_finished_at_utc",
    "gps_measured_at_utc",
    "gps_latitude",
    "gps_longitude",
    "gps_altitude_m",
    "gps_satellites",
    "gps_fix_quality",
    "gps_hdop",
    "water_present",
    "soil_moisture_voltage",
    "soil_moisture_percent",
    "soil_wet",
    "methane_voltage",
    "methane_alarm",
    "sensors_ok",
    "sensors_dummy",
    "sensors_failed",
    "sensors_errors",
]


# ---------------------------------------------------------------------------
# Letture. Ogni funzione restituisce le colonne del CSV che le competono.
# ---------------------------------------------------------------------------

def read_gps() -> dict:
    cfg = SENSORS["gps"]
    fix = get_gps_fix(cfg["port"], cfg["baudrate"], cfg["timeout_s"])
    if not fix:
        return {}  # nessun fix: colonne vuote, ma il sensore ha funzionato
    return {
        "gps_measured_at_utc": fix["measured_at_utc"],
        "gps_latitude": fix["latitude"],
        "gps_longitude": fix["longitude"],
        "gps_altitude_m": fix["altitude_m"],
        "gps_satellites": fix["satellites"],
        "gps_fix_quality": fix["fix_quality"],
        "gps_hdop": fix["hdop"],
    }


def read_digital(pin: int, pull_up: bool | None = None) -> bool:
    """True se il pin è "attivo".

    Con pull_up=True gpiozero considera attivo il livello basso, con
    pull_up=False il livello alto: non serve invertire a mano il valore.
    pull_up=None lascia il pin senza resistenza interna (il modulo ne ha una
    sua) e allora attivo = alto.
    """
    from gpiozero import DigitalInputDevice

    if pull_up is None:
        dev = DigitalInputDevice(pin, pull_up=None, active_state=True)
    else:
        dev = DigitalInputDevice(pin, pull_up=pull_up)
    try:
        return dev.is_active
    finally:
        dev.close()


def read_adc(channel: int, device: int = 0, vref: float = 3.3) -> float:
    """Tensione di un canale dell'MCP3008, in volt.

    gpiozero usa lo SPI hardware se è abilitato (raspi-config -> Interface
    Options -> SPI), altrimenti uno SPI software più lento.
    """
    from gpiozero import MCP3008

    adc = MCP3008(channel=channel, device=device, max_voltage=vref)
    try:
        return round(adc.voltage, 4)
    finally:
        adc.close()


def read_water() -> dict:
    cfg = SENSORS["water"]
    return {"water_present": read_digital(cfg["pin"], cfg["pull_up"])}


def read_soil_moisture() -> dict:
    cfg = SENSORS["soil_moisture"]
    if cfg["interface"] == "digital":
        level = read_digital(cfg["digital_pin"], None)
        return {"soil_wet": level == cfg["digital_wet_level"]}

    voltage = read_adc(cfg["adc_channel"], cfg["adc_device"], cfg["adc_vref"])
    percent = None
    dry, wet = cfg["volt_dry"], cfg["volt_wet"]
    if dry is not None and wet is not None and dry != wet:
        # Retta per i due punti di calibrazione. Funziona sia per le sonde in
        # cui la tensione sale con l'acqua sia per quelle in cui scende.
        percent = round(max(0.0, min(100.0, (voltage - dry) / (wet - dry) * 100.0)), 1)
    return {"soil_moisture_voltage": voltage, "soil_moisture_percent": percent}


def read_methane() -> dict:
    cfg = SENSORS["methane"]
    if cfg["interface"] == "digital":
        level = read_digital(cfg["digital_pin"], None)
        return {"methane_alarm": level == cfg["digital_alarm_level"]}
    # I ppm si ricavano dal rapporto Rs/R0, con R0 misurata in aria pulita:
    # finché non calibriamo il sensore salviamo solo la tensione.
    adc_voltage = read_adc(cfg["adc_channel"], cfg["adc_device"], cfg["adc_vref"])
    factor = (cfg["divider_r_top"] + cfg["divider_r_bottom"]) / cfg["divider_r_bottom"]
    return {"methane_voltage": round(adc_voltage * factor, 4)}


READERS = {
    "gps": read_gps,
    "water": read_water,
    "soil_moisture": read_soil_moisture,
    "methane": read_methane,
}


def read_all() -> dict:
    """Legge tutti i sensori e restituisce una riga con le colonne di SENSORS_HEADER."""
    row = {"sensors_clock_synced": clock_synced(), "sensors_started_at_utc": iso(utc_now())}
    ok, dummy, failed, errors = [], [], [], []

    for name, reader in READERS.items():
        if SENSORS[name]["dummy"]:
            dummy.append(name)
            continue
        try:
            row.update(reader())
            ok.append(name)
        except Exception as exc:
            failed.append(name)
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            logger.warning("Lettura di %s fallita: %s", name, exc)

    row["sensors_finished_at_utc"] = iso(utc_now())
    row["sensors_ok"] = ",".join(ok)
    row["sensors_dummy"] = ",".join(dummy)
    row["sensors_failed"] = ",".join(failed)
    row["sensors_errors"] = " | ".join(errors)
    return row


def read_and_save() -> dict:
    """Legge i sensori, aggiunge la riga a sensors.csv e la restituisce."""
    row = read_all()
    append_rows(config.SENSORS_CSV, SENSORS_HEADER, [row])
    return row


def calibrate_soil(samples: int = 10) -> float:
    """Media di ``samples`` letture della sonda del suolo, una ogni mezzo secondo.

    Si usa due volte: con la sonda all'aria (il valore va in ``volt_dry``) e
    con la sonda in un bicchiere d'acqua fino alla linea indicata sulla
    scheda (il valore va in ``volt_wet``).
    """
    cfg = SENSORS["soil_moisture"]
    values = []
    for _ in range(samples):
        values.append(read_adc(cfg["adc_channel"], cfg["adc_device"], cfg["adc_vref"]))
        time.sleep(0.5)
    mean = sum(values) / len(values)
    print(f"min {min(values):.4f} V, max {max(values):.4f} V, media {mean:.4f} V")
    return mean


def main() -> int:
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    if "--calibra-suolo" in sys.argv:
        calibrate_soil()
        return 0
    row = read_and_save()
    print(f"Riga scritta in {config.SENSORS_CSV}")
    print(f"ok: {row['sensors_ok']} | dummy: {row['sensors_dummy']} | falliti: {row['sensors_failed']}")
    return 1 if row["sensors_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
