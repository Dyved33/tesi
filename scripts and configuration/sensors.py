#!/usr/bin/env python3
"""Read enabled Raspberry Pi sensors once and append one CSV record.

Each enabled device is read in sequence, so this is a burst, not a synchronized
sample. It appends a row to ``data/sensors.csv`` and exits. The row timestamp is
the time the script builds the record; each sensor may have been read earlier.

Per plan.pdf the BME280 is wired ONLY to the ESP32 (external 3D case). CSV columns
for BME exist for data forwarded from the ESP; local I2C BME is bench-only.

Edit the SENSORS dict to match actual wiring. See pyexplanation.md.
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CONFIGURATION — edit these to match your actual wiring / sensor models.
# ``enabled`` controls invocation; ``library`` selects an implementation or
# fallback. These example pins are not verified field wiring or calibration.
# ---------------------------------------------------------------------------
SENSORS = {
    # BME280: in the field this sensor lives on the ESP only (plan.pdf).
    # Keep enabled+I2C only for bench tests with a temporary BME on the Pi.
    # Production: set enabled False (or library dummy) and fill CSV from ESP feed.
    "bme280": {
        "enabled": False,
        "bus": 1,
        "address": 0x77,          # try 0x76 if 0x77 is not detected
        "library": "dummy",       # adafruit | smbus | dummy | (future: esp)
    },
    # GPS: NMEA over serial UART
    "gps": {
        "enabled": True,
        "port": "/dev/ttyAMA0",   # or /dev/ttyS0, /dev/ttyUSB0
        "baudrate": 9600,
        "timeout_s": 5,           # max seconds to wait for a fix
        "library": "pyserial",    # pyserial | dummy
    },
    # Water presence: digital float switch / conductive probe (GPIO)
    "water": {
        "enabled": True,
        "pin": 27,                # GPIO number (BCM), adjust to your wiring
        "pull_up": True,          # True if switch pulls to GND when wet
        "library": "gpiozero",    # gpiozero | RPi.GPIO | dummy
    },
    # Soil moisture: analog (needs external ADC, e.g. MCP3008 via SPI)
    "soil_moisture": {
        "enabled": True,
        "interface": "adc",       # adc | gpio_digital | dummy
        # ADC (MCP3008) settings:
        "adc_chip": 0,            # MCP3008 CE0/CE1 -> 0/1
        "adc_channel": 0,         # MCP3008 channel 0-7
        "adc_vref": 3.3,
        # Digital fallback (if sensor has a DO / threshold pin):
        "gpio_pin": 22,
        "gpio_wet_level": False,  # True if DO goes high when wet/dry
        "library": "mcp3008",     # mcp3008 | spidev_raw | dummy
    },
    # Methane MQ-x (e.g. MQ-4 / MQ-2): analog via ADC, optional digital DO
    "methane": {
        "enabled": True,
        "interface": "adc",       # adc | gpio_digital | dummy
        "adc_chip": 0,
        "adc_channel": 1,
        "adc_vref": 3.3,
        "gpio_pin": 23,
        "gpio_alarm_level": True, # True if DO goes high on alarm
        "library": "mcp3008",
    },
}

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sensors.csv")
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
# Utility helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    """Return the CSV row timestamp in UTC ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def ensure_csv() -> None:
    """Create the output directory and header only when the CSV is absent."""
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)


def append_row(row: dict) -> None:
    """Append declared columns, leaving values unavailable in this run blank."""
    ensure_csv()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writerow({k: row.get(k, "") for k in CSV_HEADER})


# ---------------------------------------------------------------------------
# Sensor readers — PRIMARY implementations
# ---------------------------------------------------------------------------

def read_bme280() -> dict:
    """Read compensated BME values using Adafruit (bench use on the Pi only)."""
    import board
    import busio
    import adafruit_bme280

    i2c = busio.I2C(board.SCL, board.SDA)
    bme = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=SENSORS["bme280"]["address"])
    return {
        "temperature": bme.temperature,
        "humidity": bme.relative_humidity,
        "pressure": bme.pressure,
    }


# ============================================================
# ALTERNATIVE BME280: raw SMBus read (no Adafruit library).
# Use this if adafruit-circuitpython-bme280 cannot be installed.
# ============================================================

def read_bme280_smbus() -> dict:
    """Placeholder SMBus path: verify the chip responds, but return no values."""
    import smbus2

    bus = smbus2.SMBus(SENSORS["bme280"]["bus"])
    addr = SENSORS["bme280"]["address"]

    # BME280 calibration and compensation is complex; this is a minimal
    # placeholder that reads raw registers. For a thesis, prefer the Adafruit
    # library above, or implement full compensation from the BME280 datasheet.
    try:
        # Read chip ID (register 0xD0) just to verify presence
        bus.read_byte_data(addr, 0xD0)
        return {"temperature": None, "humidity": None, "pressure": None}
    except OSError:
        return {"temperature": None, "humidity": None, "pressure": None}


# ============================================================
# ALTERNATIVE BME280: dummy / disabled.
# Returns None for all fields; useful for bench testing without hardware.
# ============================================================

def read_bme280_dummy() -> dict:
    return {"temperature": None, "humidity": None, "pressure": None}


def read_gps() -> dict:
    """Read the first coordinate-bearing GPGGA sentence before timeout.

    This parser does not accept GNGGA and does not check GGA fix quality.
    """
    import serial

    port = SENSORS["gps"]["port"]
    baud = SENSORS["gps"]["baudrate"]
    timeout = SENSORS["gps"]["timeout_s"]

    ser = serial.Serial(port, baudrate=baud, timeout=1)
    deadline = time.time() + timeout

    while time.time() < deadline:
        line = ser.readline().decode("ascii", errors="replace").strip()
        if line.startswith("$GPGGA"):
            parts = line.split(",")
            # $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx
            if len(parts) >= 10 and parts[2] and parts[4]:
                lat = parse_nmea_coord(parts[2], parts[3])
                lon = parse_nmea_coord(parts[4], parts[5])
                alt = float(parts[9]) if parts[9] else None
                sats = int(parts[7]) if parts[7] else None
                ser.close()
                return {
                    "latitude": lat,
                    "longitude": lon,
                    "altitude": alt,
                    "satellites": sats,
                }
    ser.close()
    return {"latitude": None, "longitude": None, "altitude": None, "satellites": None}


def parse_nmea_coord(value: str, direction: str):
    """Convert NMEA degrees/minutes to signed decimal degrees."""
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


# ============================================================
# ALTERNATIVE GPS: dummy / no fix.
# ============================================================

def read_gps_dummy() -> dict:
    return {"latitude": None, "longitude": None, "altitude": None, "satellites": None}


def read_water() -> dict:
    """Read active-low digital input; a low level is interpreted as wet."""
    from gpiozero import DigitalInputDevice

    pin = SENSORS["water"]["pin"]
    pull_up = SENSORS["water"]["pull_up"]
    sensor = DigitalInputDevice(pin, pull_up=pull_up)
    # True = high = dry (if switch closes to GND when wet)
    wet = not sensor.value
    sensor.close()
    return {"present": wet}


# ============================================================
# ALTERNATIVE water: RPi.GPIO raw.
# ============================================================

def read_water_rpigpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["water"]["pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP if SENSORS["water"]["pull_up"] else GPIO.PUD_DOWN)
    wet = not GPIO.input(pin)
    GPIO.cleanup()
    return {"present": wet}


# ============================================================
# ALTERNATIVE water: dummy.
# ============================================================

def read_water_dummy() -> dict:
    return {"present": None}


def read_adc(channel: int, chip: int = 0, vref: float = 3.3) -> float:
    """Read MCP3008 channel voltage; ``vref`` is unused by this backend."""
    import board
    import busio
    import adafruit_mcp3xxx.mcp3008 as MCP
    from adafruit_mcp3xxx.analog_in import AnalogIn

    spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
    cs = board.D5 if chip == 0 else board.D6  # adjust CE pins if needed
    mcp = MCP.MCP3008(spi, cs)
    chan = AnalogIn(mcp, getattr(MCP, f"P{channel}"))
    return chan.voltage


# ============================================================
# ALTERNATIVE ADC: raw spidev read from MCP3008.
# No Adafruit library required; returns voltage on the selected channel.
# ============================================================

def read_adc_spidev(channel: int, chip: int = 0, vref: float = 3.3) -> float:
    """Read one raw MCP3008 channel over SPI and convert counts to voltage."""
    import spidev

    spi = spidev.SpiDev()
    spi.open(0, chip)          # bus 0, CE0/CE1
    spi.max_speed_hz = 1350000

    # MCP3008 single-ended read: start bit, single-ended + channel, null
    buf = spi.xfer2([1, (8 + channel) << 4, 0])
    adc = ((buf[1] & 3) << 8) + buf[2]
    spi.close()

    voltage = (adc / 1023.0) * vref
    return round(voltage, 4)


# ============================================================
# ALTERNATIVE ADC: dummy.
# ============================================================

def read_adc_dummy(channel: int, **kwargs) -> float:
    return None


def read_soil_moisture() -> dict:
    """Return soil voltage and an uncalibrated linear percentage estimate."""
    cfg = SENSORS["soil_moisture"]
    if cfg["interface"] == "adc":
        voltage = read_adc(cfg["adc_channel"], cfg["adc_chip"], cfg["adc_vref"])
        # Rough percent: 0 V = dry, 3.3 V = saturated (calibrate for your probe)
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
# ALTERNATIVE soil moisture: digital threshold only (if sensor has DO pin),
# using RPi.GPIO instead of gpiozero.
# ============================================================

def read_soil_moisture_gpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["soil_moisture"]["gpio_pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN)
    wet = GPIO.input(pin) == SENSORS["soil_moisture"]["gpio_wet_level"]
    GPIO.cleanup()
    return {"voltage": None, "percent": None, "wet_bool": wet}


# ============================================================
# ALTERNATIVE soil moisture: dummy.
# ============================================================

def read_soil_moisture_dummy() -> dict:
    return {"voltage": None, "percent": None}


def read_methane() -> dict:
    """Return analog voltage (or digital alarm); calibrated ppm is not implemented."""
    cfg = SENSORS["methane"]
    if cfg["interface"] == "adc":
        voltage = read_adc(cfg["adc_channel"], cfg["adc_chip"], cfg["adc_vref"])
        # MQ sensors need calibration (R0 in clean air) for real ppm.
        # Here we return voltage only; ppm is left as None until calibrated.
        return {"voltage": voltage, "ppm": None}
    elif cfg["interface"] == "gpio_digital":
        from gpiozero import DigitalInputDevice
        pin = DigitalInputDevice(cfg["gpio_pin"], pull_up=False)
        alarm = pin.value == SENSORS["methane"]["gpio_alarm_level"]
        pin.close()
        return {"voltage": None, "ppm": None, "alarm_bool": alarm}
    return {"voltage": None, "ppm": None}


# ============================================================
# ALTERNATIVE methane: digital DO pin via RPi.GPIO.
# ============================================================

def read_methane_gpio() -> dict:
    import RPi.GPIO as GPIO

    pin = SENSORS["methane"]["gpio_pin"]
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.IN)
    alarm = GPIO.input(pin) == SENSORS["methane"]["gpio_alarm_level"]
    GPIO.cleanup()
    return {"voltage": None, "ppm": None, "alarm_bool": alarm}


# ============================================================
# ALTERNATIVE methane: dummy.
# ============================================================

def read_methane_dummy() -> dict:
    return {"voltage": None, "ppm": None}


# ---------------------------------------------------------------------------
# Dispatchers — pick primary or alternative based on SENSORS["library"]
# ---------------------------------------------------------------------------

def read_sensor_with_fallback(name: str, primary, alternatives: dict) -> tuple:
    """Run the configured backend, falling back to dummy only after an exception.

    A dummy result counts as an operational success, not as a real measurement.
    """
    lib = SENSORS[name].get("library", "primary")
    try:
        if lib in alternatives:
            return alternatives[lib](), True
        return primary(), True
    except Exception as exc:
        # Try dummy as last resort if configured
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
    """Read enabled devices, append their fields, and report failed readers."""
    results = {}
    ok_list = []
    fail_list = []

    # BME280
    if SENSORS["bme280"]["enabled"]:
        alts = {"dummy": read_bme280_dummy}
        if SENSORS["bme280"].get("library") == "smbus":
            data, ok = read_sensor_with_fallback("bme280", read_bme280_smbus, alts)
        else:
            data, ok = read_sensor_with_fallback("bme280", read_bme280, alts)
        results["bme280"] = data
        (ok_list if ok else fail_list).append("bme280")

    # GPS
    if SENSORS["gps"]["enabled"]:
        alts = {"dummy": read_gps_dummy}
        data, ok = read_sensor_with_fallback("gps", read_gps, alts)
        results["gps"] = data
        (ok_list if ok else fail_list).append("gps")

    # Water
    if SENSORS["water"]["enabled"]:
        alts = {"rpigpio": read_water_rpigpio, "dummy": read_water_dummy}
        data, ok = read_sensor_with_fallback("water", read_water, alts)
        results["water"] = data
        (ok_list if ok else fail_list).append("water")

    # Soil moisture
    if SENSORS["soil_moisture"]["enabled"]:
        alts = {"dummy": read_soil_moisture_dummy}
        lib = SENSORS["soil_moisture"].get("library", "mcp3008")
        if lib == "spidev_raw":
            data, ok = read_sensor_with_fallback(
                "soil_moisture",
                lambda: read_adc_spidev(
                    SENSORS["soil_moisture"]["adc_channel"],
                    SENSORS["soil_moisture"]["adc_chip"],
                    SENSORS["soil_moisture"]["adc_vref"],
                ),
                alts,
            )
        else:
            data, ok = read_sensor_with_fallback("soil_moisture", read_soil_moisture, alts)
        results["soil_moisture"] = data
        (ok_list if ok else fail_list).append("soil_moisture")

    # Methane
    if SENSORS["methane"]["enabled"]:
        alts = {"dummy": read_methane_dummy}
        lib = SENSORS["methane"].get("library", "mcp3008")
        if lib == "spidev_raw":
            data, ok = read_sensor_with_fallback(
                "methane",
                lambda: read_adc_spidev(
                    SENSORS["methane"]["adc_channel"],
                    SENSORS["methane"]["adc_chip"],
                    SENSORS["methane"]["adc_vref"],
                ),
                alts,
            )
        else:
            data, ok = read_sensor_with_fallback("methane", read_methane, alts)
        results["methane"] = data
        (ok_list if ok else fail_list).append("methane")

    # Build one row using the stable CSV schema. Sensors absent from this run
    # remain blank; the row timestamp is not an individual sample time.
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
