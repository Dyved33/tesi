"""Percorsi, porte seriali e cadenze usati da tutto il package.

I valori si possono cambiare con le variabili d'ambiente, di solito messe in
``.env.systemd`` (vedi ``raspberry_pi/systemd/.env.systemd.example``).
La mappa dei pin fisici è in ``docs/pinout.md``.
"""
# Provenienza: file scritto da noi.

import os
from pathlib import Path

# Cartella raspberry_pi/ (quella sopra questo package).
RPI_DIR = Path(__file__).resolve().parent.parent

# Tutti i dati raccolti stanno sotto DATA_DIR:
#   images/          foto JPG e, accanto a ognuna, il CSV con i suoi metadati
#   bme280.csv       tutte le misure del BME280 arrivate dall'ESP32
#   camera_events.csv  tutti i movimenti visti dalla camera dell'ESP32
#   sensors.csv      tutte le letture dei sensori collegati al Pi
DATA_DIR = Path(os.environ.get("SMARTCAM_DATA_DIR", RPI_DIR / "data"))
IMAGE_DIR = DATA_DIR / "images"
BME280_CSV = DATA_DIR / "bme280.csv"
EVENTS_CSV = DATA_DIR / "camera_events.csv"
SENSORS_CSV = DATA_DIR / "sensors.csv"

# UART verso l'ESP32: GPIO14 (TXD) e GPIO15 (RXD), pin fisici 8 e 10.
ESP_PORT = os.environ.get("ESP_PORT", "/dev/ttyAMA0")
ESP_BAUD = 115200

# GPS sulla UART2 del Pi 5: GPIO4 (TXD2) e GPIO5 (RXD2), pin fisici 7 e 29.
# Serve dtoverlay=uart2-pi5 in config.txt. Non può stare su ttyAMA0 perché
# quella UART è già usata dall'ESP32.
GPS_PORT = os.environ.get("GPS_PORT", "/dev/ttyAMA2")
GPS_BAUD = 9600

# Cadenze della modalità continuativa, in secondi (il piano propone una
# misura al minuto e una foto ogni cinque minuti).
CAPTURE_INTERVAL = int(os.environ.get("CAPTURE_INTERVAL", "300"))
SENSOR_INTERVAL = int(os.environ.get("SENSOR_INTERVAL", "60"))

# Fascia oraria della modalità continuativa, ora locale "HH:MM".
# Se una delle due manca il Pi lavora tutto il giorno.
DAILY_WINDOW_START = os.environ.get("DAILY_WINDOW_START", "")
DAILY_WINDOW_END = os.environ.get("DAILY_WINDOW_END", "")
