# pyexplanation — sensors.py walkthrough

This document explains `sensors.py`, the one-shot environmental reader for the
Raspberry Pi 5 thesis. Read it before deploying, and update it if you change
sensor models or wiring.

---

## Purpose

The Pi is normally in **halt** (~0.01 W) and is woken by the ESP32-CAM only when
an insect event is detected. While the Pi is awake, this script must:

1. Read **every available sensor** in one fast burst.
2. Append one row to a **CSV** file (`data/sensors.csv`).
3. Exit cleanly so `capture_rpi.sh --oneshot` can proceed to `poweroff`.

It is **not** a daemon and does **not** loop continuously.

---

## File structure

| Section | What it does |
|---------|--------------|
| `SENSORS` dict | Configuration: enabled flags, GPIO pins, I2C addresses, UART port, ADC channels. Edit this to match your actual wiring. |
| `CSV_PATH` / `CSV_HEADER` | Where and how results are stored (one row per wake cycle). |
| `now_iso()`, `ensure_csv()`, `append_row()` | Helpers: timestamp in ISO 8601 UTC, create CSV with header if missing, append a row. |
| `read_bme280()` ... `read_methane()` | PRIMARY reader functions, one per sensor type, using the recommended libraries. |
| `read_*_dummy()`, `read_*_rpigpio()`, `read_adc_spidev()` ... | ALTERNATIVE reader functions, delimited by `////////////////////` blocks. Use these if the primary library is unavailable or your hardware differs. |
| `read_sensor_with_fallback()` | Tries the primary reader, then an alternative chosen by `SENSORS[...]["library"]`; falls back to dummy if everything fails. |
| `main()` | Reads all enabled sensors, builds a CSV row, writes it, prints a summary, exits 0/1. |

---

## The `////////////////////` alternative blocks

Each sensor has **one or more alternative implementations** wrapped between two lines of `////////////////////`. Example:

```python
////////////////////

# ALTERNATIVE BME280: raw SMBus read ...
def read_bme280_smbus() -> dict:
    ...

////////////////////
```

**Why:** You do not yet know the exact sensor models or pinout. The script
therefore supports the most common options for each sensor type:

| Sensor | Primary | Alternatives |
|--------|---------|--------------|
| BME280 | Adafruit CircuitPython (I2C) | `smbus2` raw read, dummy |
| GPS | `pyserial` NMEA `$GPGGA` parsing | dummy |
| Water | `gpiozero` digital input | `RPi.GPIO`, dummy |
| Soil moisture | MCP3008 ADC via Adafruit lib | `spidev` raw, GPIO digital, dummy |
| Methane | MCP3008 ADC via Adafruit lib | `spidev` raw, GPIO digital DO, dummy |

To switch to an alternative, change the `"library"` field in `SENSORS`, e.g.:

```python
"library": "smbus"        # BME280 via smbus2 instead of Adafruit
"library": "spidev_raw"   # Soil moisture via raw spidev instead of Adafruit MCP3xxx
```

If nothing is wired yet or a sensor is missing, the **dummy** alternative
returns `None` so the script still runs and produces a CSV row with empty fields.

---

## CSV output

One row per wake cycle in `data/sensors.csv`:

| Column | Meaning |
|--------|---------|
| `timestamp_iso` | UTC ISO 8601 timestamp of the reading burst |
| `bme280_temperature_c` / `_humidity_pct` / `_pressure_hpa` | BME280 environmental data |
| `gps_latitude` / `gps_longitude` / `gps_altitude_m` / `gps_satellites` | GPS fix (NMEA `$GPGGA`) |
| `water_present_bool` | Digital water detection (True/False) |
| `soil_moisture_voltage` / `_percent` | ADC voltage and rough % (0–100) |
| `methane_voltage` / `_ppm_approx` | ADC voltage; ppm left `None` until calibrated |
| `sensors_ok` | Comma-separated list of sensors that returned data |
| `sensors_failed` | Comma-separated list of sensors that failed |

Missing sensors produce empty cells, not errors.

---

## How to run

```bash
cd ~/tesi
python3 sensors.py
```

If using a venv:

```bash
source ~/venv/bin/activate
python3 sensors.py
```

Expected output:

```
[sensors] Wrote row to /home/rpi5-03/tesi/data/sensors.csv
[sensors] OK: ['bme280', 'gps', 'water', 'soil_moisture', 'methane'] | FAILED: []
```

Exit code: `0` if all enabled sensors succeeded, `1` if any failed (still writes the row with what it could read).

---

## Integration with `capture_rpi.sh` and photo metadata

The existing `capture_rpi.sh --oneshot` launches `python -m backend.capture_client`, which snaps a photo and already attempts to attach BME280 and GPS readings to the image metadata via `backend.photo_metadata`.

**What "embedding in photo metadata" means:** your capture pipeline can store the same sensor values alongside each photo — either in a sidecar JSON file (same timestamp, e.g. `rpi_20261019-124900.json`) or inside the image EXIF — so every insect photo carries its environmental context (temperature, humidity, GPS, etc.). The CSV from `sensors.py` and the photo metadata can be linked by timestamp. You do not have to do this now; it is a "yes, later" item.

---

## Calibration notes (thesis-relevant)

- **MQ methane sensor:** raw voltage is not ppm. You must calibrate `R0` in clean air and apply the sensor's curve (see datasheet). The script returns voltage only; add ppm conversion once you have calibration data.
- **Soil moisture:** the percent conversion is linear (voltage / Vref × 100). Calibrate against dry and saturated soil for meaningful numbers.
- **BME280:** the Adafruit library handles compensation automatically; the SMBus alternative does **not** and returns raw/uncompensated values unless you implement the full compensation algorithm from the BME280 datasheet.

---

## What to verify before first field run

1. `piconf.md` steps 1–7 completed (interfaces enabled, permissions, dependencies).
2. `i2cdetect -y 1` shows the BME280 address (`0x76` or `0x77`).
3. `ls /dev/tty*` shows the GPS serial device.
4. `SENSORS` dict pins/addresses match your actual wiring.
5. Run `python3 sensors.py` manually once and confirm `data/sensors.csv` gets a row.
6. Test the full cycle: wake impulse → boot → `capture_rpi.sh --oneshot` → photo + sensor CSV → `poweroff`.