#!/usr/bin/env python3
"""Legge una volta tutti i sensori abilitati sul Pi e aggiunge una riga al CSV.

I sensori vengono letti uno dopo l'altro (un "burst"), non nello stesso
istante. Alla fine si aggiunge una riga a ``raspberry_pi/data/sensors.csv`` e
lo script termina. Il timestamp della riga è il momento in cui la riga viene
composta, quindi i singoli sensori possono essere stati letti qualche secondo
prima.

Secondo plan.pdf il BME280 è collegato SOLO all'ESP32 (nella sua custodia
esterna): le colonne BME nel CSV servono per i dati che arriveranno dall'ESP;
leggerlo via I2C dal Pi ha senso solo al banco.

Per adattarlo al proprio cablaggio basta modificare il dizionario SENSORS.
Per ogni sensore c'è una funzione "principale" più alcune alternative
(altra libreria, oppure dummy) selezionabili con la chiave "library".

Si lancia come modulo, dalla cartella raspberry_pi/::

    python3 -m smartcam.sensors
"""
# Provenienza:
# - Il dizionario di configurazione, il meccanismo di scelta delle alternative
#   (read_sensor_with_fallback) e la scrittura del CSV sono scritti da noi.
# - BME280 e GPS sono letti con i moduli bme_reader.py e gps_reader.py di
#   questo package (lì sono indicate le rispettive fonti: Adafruit, RPi.bme280,
#   pynmea2). Prima qui c'erano delle copie semplificate dello stesso codice.
# - read_adc() usa la classe MCP3008 di gpiozero (licenza BSD), preinstallata
#   su Raspberry Pi OS: https://gpiozero.readthedocs.io/en/stable/api_spi.html#mcp3008
#   Sostituisce due versioni precedenti: una adattata dall'esempio Adafruit
#   MCP3xxx (con il chip select sbagliato) e lo snippet spidev "a mano" dei
#   tutorial, che restituiva un tipo diverso e mandava in crash lo script.
# - read_water() e le varianti gpio_digital usano DigitalInputDevice come da
#   documentazione gpiozero: https://gpiozero.readthedocs.io/en/stable/api_input.html
# - Le varianti RPi.GPIO seguono gli esempi base della libreria:
#   https://sourceforge.net/p/raspberry-gpio-python/wiki/Inputs/

import csv
import os
import sys
from datetime import datetime, timezone

from .bme_reader import get_bme280_reading
from .gps_reader import get_gps_fix

# ---------------------------------------------------------------------------
# CONFIGURAZIONE: da adattare al cablaggio e ai modelli di sensore reali.
# "enabled" dice se leggere il sensore, "library" quale implementazione usare.
# I pin qui sotto sono esempi: NON sono il cablaggio di campo verificato.
# ---------------------------------------------------------------------------
SENSORS = {
    # BME280: in campo sta solo sull'ESP (plan.pdf). Abilitarlo qui solo per
    # prove al banco con un BME collegato temporaneamente al Pi. In produzione
    # resta disabilitato e le colonne andranno riempite con i dati dell'ESP.
    "bme280": {
        "enabled": False,
        "bus": 1,
        "address": 0x76,          # 0x76 con SDO a GND (nostro schema), 0x77 con SDO a 3,3 V
        "library": "dummy",       # adafruit | smbus | auto | dummy | (in futuro: esp)
    },
    # GPS: frasi NMEA sulla seriale (UART)
    "gps": {
        "enabled": True,
        "port": "/dev/ttyAMA0",   # oppure /dev/ttyS0, o /dev/ttyUSB0 per i GPS USB
        "baudrate": 9600,
        "timeout_s": 5,           # secondi massimi di attesa per un fix
        "library": "pyserial",    # pyserial | dummy
    },
    # Presenza d'acqua: galleggiante o sonda conduttiva su un ingresso digitale (GPIO)
    "water": {
        "enabled": True,
        "pin": 27,                # numero GPIO (BCM), da adattare al cablaggio
        "pull_up": True,          # True se il contatto chiude verso GND quando è bagnato
        "library": "gpiozero",    # gpiozero | rpigpio | dummy
    },
    # Umidità del suolo: sensore analogico, serve un ADC esterno (MCP3008 su SPI)
    "soil_moisture": {
        "enabled": True,
        "interface": "adc",       # adc | gpio_digital | dummy
        # Impostazioni ADC (MCP3008):
        "adc_chip": 0,            # chip select hardware: 0 = CE0 (GPIO8), 1 = CE1 (GPIO7)
        "adc_channel": 0,         # canale dell'MCP3008, da 0 a 7
        "adc_vref": 3.3,          # tensione su VREF dell'MCP3008
        # Alternativa digitale, se il modulo ha un'uscita DO a soglia:
        "gpio_pin": 22,
        "gpio_wet_level": False,  # livello di DO che significa "bagnato"
        "library": "gpiozero",    # gpiozero | dummy
    },
    # Metano, sensori della serie MQ (es. MQ-4 / MQ-2): analogico via ADC, con uscita digitale DO opzionale
    "methane": {
        "enabled": True,
        "interface": "adc",       # adc | gpio_digital | dummy
        "adc_chip": 0,
        "adc_channel": 1,
        "adc_vref": 3.3,
        "gpio_pin": 23,
        "gpio_alarm_level": True, # livello di DO che significa "allarme"
        "library": "gpiozero",    # gpiozero | dummy
    },
}

# Il CSV sta in raspberry_pi/data/ (la cartella sopra questo package).
# L'ordine delle colonne è fisso: le righe vecchie restano leggibili anche se
# un sensore viene disabilitato.
CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sensors.csv"
)
CSV_HEADER = [
    "timestamp_iso",
    "bme280_temperature_c",
    "bme280_humidity_pct",
    "bme280_pressure_hpa",
    "gps_latitude",
    "gps_longitude",
    "gps_altitude_m",
    "gps_satellites",
    "water_present_bool",
    "soil_moisture_voltage",
    "soil_moisture_percent",
    "methane_voltage",
    "methane_ppm_approx",
    "sensors_ok",
    "sensors_failed",
]


# ---------------------------------------------------------------------------
# Funzioni di utilità
# ---------------------------------------------------------------------------
def now_iso() -> str:
    """Timestamp della riga in UTC, formato ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def ensure_csv() -> None:
    """Crea cartella e intestazione del CSV, ma solo se il file non esiste ancora."""
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)


def append_row(row: dict) -> None:
    """Aggiunge una riga; le colonne senza valore in questo giro restano vuote.

    Le chiavi che non sono nell'intestazione vengono ignorate.
    """
    ensure_csv()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writerow({k: row.get(k, "") for k in CSV_HEADER})


# ---------------------------------------------------------------------------
# Lettura dei sensori: per ognuno la versione principale e le alternative
# ---------------------------------------------------------------------------

def read_bme280() -> dict:
    """Legge il BME280 tramite bme_reader (solo prove al banco sul Pi).

    Solleva un'eccezione se la lettura fallisce, così il dispatcher la
    registra come errore.
    """
    cfg = SENSORS["bme280"]
    reading = get_bme280_reading(cfg["bus"], cfg["address"], cfg["library"])
    if reading is None:
        raise RuntimeError("BME280 read failed (see log)")
    return reading


def read_bme280_dummy() -> dict:
    """Dummy del BME280: tutti i campi a None, per provare senza hardware."""
    return {"temperature": None, "humidity": None, "pressure": None}


def read_gps() -> dict:
    """Legge una posizione tramite gps_reader.

    Nessun fix entro il timeout non è un errore: si restituiscono campi vuoti.
    """
    cfg = SENSORS["gps"]
    fix = get_gps_fix(cfg["port"], cfg["baudrate"], cfg["timeout_s"])
    return fix or read_gps_dummy()


def read_gps_dummy() -> dict:
    """Dummy del GPS: nessun fix."""
    return {"latitude": None, "longitude": None, "altitude": None, "satellites": None}


def read_water() -> dict:
    """Legge il sensore d'acqua; l'idea è che livello basso = bagnato.

    ATTENZIONE: con pull_up=True gpiozero inverte già il valore (value = 1
    quando il pin è basso), quindi il "not" qui sotto inverte una seconda
    volta e il risultato esce al contrario. Vedi issues.md.
    """
    from gpiozero import DigitalInputDevice

    pin = SENSORS["water"]["pin"]
    pull_up = SENSORS["water"]["pull_up"]
    sensor = DigitalInputDevice(pin, pull_up=pull_up)
    wet = not sensor.value
    sensor.close()
    return {"present": wet}


# ============================================================
# ALTERNATIVA acqua: RPi.GPIO, legge il livello "grezzo" del pin.
# Qui il "not" è corretto: GPIO.input restituisce 0 quando il pin è basso.
# ============================================================

def read_water_rpigpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["water"]["pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP if SENSORS["water"]["pull_up"] else GPIO.PUD_DOWN)
    wet = not GPIO.input(pin)
    GPIO.cleanup()
    return {"present": wet}


def read_water_dummy() -> dict:
    """Dummy del sensore d'acqua."""
    return {"present": None}


def read_adc(channel: int, chip: int = 0, vref: float = 3.3) -> float:
    """Legge la tensione di un canale dell'MCP3008 con gpiozero.

    ``chip`` è il chip select hardware (0 = CE0, 1 = CE1). gpiozero usa lo SPI
    hardware se è abilitato (raspi-config -> Interface -> SPI), altrimenti
    ripiega su uno SPI software più lento.
    Fonte: documentazione gpiozero, classe MCP3008 (vedi intestazione).
    """
    from gpiozero import MCP3008

    # .value è la lettura normalizzata tra 0 e 1; .voltage la moltiplica per
    # max_voltage, che deve essere la tensione collegata a VREF.
    adc = MCP3008(channel=channel, device=chip, max_voltage=vref)
    try:
        return round(adc.voltage, 4)
    finally:
        adc.close()


def read_soil_moisture() -> dict:
    """Restituisce la tensione del sensore di suolo e una percentuale "a occhio".

    La percentuale è una semplice proporzione lineare sulla tensione, NON
    calibrata: va presa solo come indicazione.
    """
    cfg = SENSORS["soil_moisture"]
    if cfg["interface"] == "adc":
        voltage = read_adc(cfg["adc_channel"], cfg["adc_chip"], cfg["adc_vref"])
        # Ipotesi: 0 V = secco, 3,3 V = saturo. Molti sensori capacitivi fanno
        # il contrario (tensione alta = secco): va verificato sulla sonda reale.
        percent = None
        if voltage is not None:
            percent = max(0.0, min(100.0, (voltage / cfg["adc_vref"]) * 100.0))
        return {"voltage": voltage, "percent": percent}
    elif cfg["interface"] == "gpio_digital":
        from gpiozero import DigitalInputDevice
        pin = DigitalInputDevice(cfg["gpio_pin"], pull_up=False)
        wet = pin.value == SENSORS["soil_moisture"]["gpio_wet_level"]
        pin.close()
        return {"voltage": None, "percent": None, "wet_bool": wet}
    return {"voltage": None, "percent": None}


# ============================================================
# ALTERNATIVA suolo: solo soglia digitale (uscita DO del modulo) con RPi.GPIO.
# Al momento il dispatcher non la richiama mai.
# ============================================================

def read_soil_moisture_gpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["soil_moisture"]["gpio_pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN)
    wet = GPIO.input(pin) == SENSORS["soil_moisture"]["gpio_wet_level"]
    GPIO.cleanup()
    return {"voltage": None, "percent": None, "wet_bool": wet}


def read_soil_moisture_dummy() -> dict:
    """Dummy del sensore di suolo."""
    return {"voltage": None, "percent": None}


def read_methane() -> dict:
    """Restituisce la tensione del sensore di metano (o l'allarme digitale).

    I ppm non vengono calcolati: servirebbe la calibrazione del sensore.
    """
    cfg = SENSORS["methane"]
    if cfg["interface"] == "adc":
        voltage = read_adc(cfg["adc_channel"], cfg["adc_chip"], cfg["adc_vref"])
        # Per i sensori MQ i ppm si ottengono dal rapporto Rs/R0, dove R0 si
        # misura in aria pulita durante la calibrazione. Finché non la facciamo
        # restituiamo solo la tensione.
        return {"voltage": voltage, "ppm": None}
    elif cfg["interface"] == "gpio_digital":
        from gpiozero import DigitalInputDevice
        pin = DigitalInputDevice(cfg["gpio_pin"], pull_up=False)
        alarm = pin.value == SENSORS["methane"]["gpio_alarm_level"]
        pin.close()
        return {"voltage": None, "ppm": None, "alarm_bool": alarm}
    return {"voltage": None, "ppm": None}


# ============================================================
# ALTERNATIVA metano: uscita digitale DO con RPi.GPIO.
# Al momento il dispatcher non la richiama mai.
# ============================================================

def read_methane_gpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["methane"]["gpio_pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN)
    alarm = GPIO.input(pin) == SENSORS["methane"]["gpio_alarm_level"]
    GPIO.cleanup()
    return {"voltage": None, "ppm": None, "alarm_bool": alarm}


def read_methane_dummy() -> dict:
    """Dummy del sensore di metano."""
    return {"voltage": None, "ppm": None}


# ---------------------------------------------------------------------------
# Scelta dell'implementazione in base a SENSORS[...]["library"]
# ---------------------------------------------------------------------------

def read_sensor_with_fallback(name: str, primary, alternatives: dict) -> tuple:
    """Esegue l'implementazione scelta; se va in errore ripiega sul dummy.

    Se "library" non è tra le alternative si usa la funzione principale.
    ATTENZIONE: quando si ripiega sul dummy il sensore viene comunque contato
    come "ok", anche se non ha misurato niente (vedi issues.md).
    """
    lib = SENSORS[name].get("library", "primary")
    try:
        if lib in alternatives:
            return alternatives[lib](), True
        return primary(), True
    except Exception as exc:
        # Ultima spiaggia: il dummy, se esiste per questo sensore.
        if "dummy" in alternatives:
            try:
                return alternatives["dummy"](), True
            except Exception:
                pass
        print(f"[WARN] {name} read failed: {exc}", file=sys.stderr)
        return {"error": str(exc)}, False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Legge i sensori abilitati, scrive la riga nel CSV e segnala quelli falliti.

    Exit code 0 se nessun sensore è fallito, 1 altrimenti.
    """
    results = {}
    ok_list = []
    fail_list = []

    # Ogni voce: nome del sensore, funzione principale, alternative.
    readers = [
        ("bme280", read_bme280, {"dummy": read_bme280_dummy}),
        ("gps", read_gps, {"dummy": read_gps_dummy}),
        ("water", read_water, {"rpigpio": read_water_rpigpio, "dummy": read_water_dummy}),
        ("soil_moisture", read_soil_moisture, {"dummy": read_soil_moisture_dummy}),
        ("methane", read_methane, {"dummy": read_methane_dummy}),
    ]
    for name, primary, alternatives in readers:
        if not SENSORS[name]["enabled"]:
            continue
        data, ok = read_sensor_with_fallback(name, primary, alternatives)
        results[name] = data
        (ok_list if ok else fail_list).append(name)

    # Compone la riga con lo schema fisso del CSV. I sensori non letti restano
    # vuoti; il timestamp è quello della riga, non delle singole misure.
    row = {"timestamp_iso": now_iso(), "sensors_ok": ",".join(ok_list), "sensors_failed": ",".join(fail_list)}

    b = results.get("bme280", {})
    row["bme280_temperature_c"] = b.get("temperature")
    row["bme280_humidity_pct"] = b.get("humidity")
    row["bme280_pressure_hpa"] = b.get("pressure")

    g = results.get("gps", {})
    row["gps_latitude"] = g.get("latitude")
    row["gps_longitude"] = g.get("longitude")
    row["gps_altitude_m"] = g.get("altitude")
    row["gps_satellites"] = g.get("satellites")

    w = results.get("water", {})
    row["water_present_bool"] = w.get("present")

    s = results.get("soil_moisture", {})
    row["soil_moisture_voltage"] = s.get("voltage")
    row["soil_moisture_percent"] = s.get("percent")

    m = results.get("methane", {})
    row["methane_voltage"] = m.get("voltage")
    row["methane_ppm_approx"] = m.get("ppm")

    append_row(row)

    print(f"[sensors] Wrote row to {CSV_PATH}")
    print(f"[sensors] OK: {ok_list} | FAILED: {fail_list}")
    return 0 if not fail_list else 1


if __name__ == "__main__":
    raise SystemExit(main())
