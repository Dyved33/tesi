#!/usr/bin/env python3
"""Scatta le foto e salva accanto a ognuna un CSV con tutti i suoi metadati.

Due modalità, come nel piano:

- ``--oneshot`` (acquisizione selettiva): il Pi è stato appena acceso
  dall'ESP. Fa una foto, scarica dall'ESP misure del BME280 ed eventi della
  camera, legge i sensori del Pi, scrive il CSV della foto ed esce. Lo
  spegnimento lo chiede l'unità systemd.
- senza ``--oneshot`` (monitoraggio continuativo): dentro la fascia oraria
  legge sensori ed ESP ogni ``--sensor-interval`` secondi e fa una foto ogni
  ``--interval`` secondi. Le due cadenze sono indipendenti.

Per ogni foto ``AAAAMMGGTHHMMSS_mmmZ_camN.jpg`` viene scritto
``AAAAMMGGTHHMMSS_mmmZ_camN.csv`` con impostazioni di scatto, hash del file,
evento della camera che ha acceso il Pi, posizione GPS, ultima misura del
BME280 e ultima lettura dei sensori del Pi.
Le colonne sono descritte in ``docs/dati-csv.md``.

Si lancia come modulo, dalla cartella raspberry_pi/ (lo fa capture_rpi.sh)::

    python3 -m smartcam.capture_client --oneshot
"""
# Provenienza:
# - Il flusso, il ciclo con due cadenze e il parser degli argomenti sono
#   scritti da noi.
# - Le opzioni passate a rpicam-still (-n, -t, -o, --camera, --width,
#   --height, --quality, --autofocus-*, --shutter, --denoise, --sharpness,
#   --contrast, --roi) vengono dalla documentazione ufficiale Raspberry Pi:
#   https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still
#   https://www.raspberrypi.com/documentation/computers/camera_software.html#camera-control-options
# - I valori di default 4608x2592 sono la risoluzione piena del sensore IMX708
#   della Camera Module 3 (dalla stessa documentazione).
# - Lo zoom digitale tramite --roi centrato (build_center_roi) è un calcolo
#   nostro basato sulla descrizione dell'opzione --roi.
# - Valutata ma non adottata: Picamera2 (https://github.com/raspberrypi/picamera2).
#   Terrebbe la camera aperta nel ciclo continuo e darebbe i metadati di
#   scatto, ma va riscritto lo scatto e provato sulla camera vera: per ora
#   restiamo su rpicam-still (vedi docs/guida-codice.md).

import argparse
import hashlib
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from shutil import which

from . import config, esp_link, sensors
from .storage import clock_synced, iso, utc_now, write_sidecar

logger = logging.getLogger(__name__)

SIDECAR_HEADER = [
    # foto
    "image_file", "captured_at_utc", "pi_clock_synced", "mode", "pi_boot_id", "camera_index",
    "size_bytes", "sha256",
    # impostazioni di scatto
    "width", "height", "quality", "zoom", "roi", "timeout_ms",
    "af_mode", "af_range", "af_speed", "af_window", "af_on_capture",
    "shutter_us", "denoise", "sharpness", "contrast",
    # ultima misura del BME280 (dall'ESP32)
    "bme_esp_boot_id", "bme_seq", "bme_measured_at_utc", "bme_received_at_utc",
    "bme_status", "bme_temperature_c", "bme_humidity_pct", "bme_pressure_hpa",
    # ultimo evento della camera dell'ESP che ha acceso il Pi
    "wake_esp_boot_id", "wake_seq", "wake_measured_at_utc", "wake_changed_pct",
    # esito dell'ultimo scambio con l'ESP
    "esp_sync_at_utc", "esp_received", "esp_lost", "esp_error",
    # ultima lettura dei sensori del Pi (stesse colonne di sensors.csv)
    *sensors.SENSORS_HEADER,
    # errori dello scatto o del salvataggio
    "errors",
]


# ---------------------------------------------------------------------------
# Argomenti
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scatto foto e raccolta dati della smart camera.")
    p.add_argument("--oneshot", action="store_true",
                   help="una foto con sensori ed ESP, poi esce (app selettiva)")
    p.add_argument("--interval", type=int, default=config.CAPTURE_INTERVAL,
                   help="secondi tra due foto in modalità continuativa (default: %(default)s)")
    p.add_argument("--sensor-interval", type=int, default=config.SENSOR_INTERVAL,
                   help="secondi tra due letture dei sensori (default: %(default)s)")
    p.add_argument("--no-esp", action="store_true",
                   help="non parlare con l'ESP (prove al banco senza ESP collegato)")
    p.add_argument("--camera", type=int, default=0,
                   help="indice della camera per rpicam-still (default: 0)")
    p.add_argument("--timeout-ms", type=int, default=3000,
                   help="ms di accensione della camera prima dello scatto, per AE/AWB/AF (default: 3000)")
    p.add_argument("--width", type=int, default=4608)
    p.add_argument("--height", type=int, default=2592)
    p.add_argument("--quality", type=int, default=95, help="qualità JPEG 1-100 (default: 95)")
    p.add_argument("--zoom", type=float, default=1.0,
                   help="zoom digitale: 1.0 = nessuno, 2.0 = ritaglio centrale di metà lato")
    p.add_argument("--profile", choices=["standard", "macro"], default="standard",
                   help="valori predefiniti dell'autofocus")
    p.add_argument("--af-mode", choices=["manual", "auto", "continuous"])
    p.add_argument("--af-range", choices=["normal", "macro", "full"])
    p.add_argument("--af-speed", choices=["normal", "fast"])
    p.add_argument("--af-window", help="finestra AF x,y,w,h normalizzata, es. 0.3,0.3,0.4,0.4")
    p.add_argument("--af-on-capture", action="store_true")
    p.add_argument("--shutter", type=int, default=0, help="esposizione in µs, 0 = automatica")
    p.add_argument("--denoise", choices=["auto", "off", "cdn_off", "cdn_fast", "cdn_hq"])
    p.add_argument("--sharpness", type=float, default=1.0)
    p.add_argument("--contrast", type=float, default=1.0)
    return p


def resolve_af_settings(args: argparse.Namespace) -> dict:
    """Parte dal profilo e applica le opzioni --af-* passate esplicitamente."""
    if args.profile == "macro":
        af = {"mode": "continuous", "range": "macro", "speed": "normal",
              "window": "0.30,0.30,0.40,0.40", "on_capture": False}
    else:
        af = {"mode": "continuous", "range": "full", "speed": "normal",
              "window": "0.35,0.35,0.30,0.30", "on_capture": False}
    for key in ("mode", "range", "speed", "window"):
        value = getattr(args, f"af_{key}")
        if value is not None:
            af[key] = value
    if args.af_on_capture:
        af["on_capture"] = True
    return af


def build_center_roi(zoom: float) -> str | None:
    """Ritaglio centrale per lo zoom digitale (``None`` se zoom <= 1).

    --roi vuole x,y,larghezza,altezza come frazioni dell'immagine intera.
    È solo un ritaglio: non aumenta il dettaglio come uno zoom ottico.
    """
    if zoom <= 1.0:
        return None
    size = max(0.05, min(1.0, 1.0 / zoom))  # oltre 20x non ha senso
    offset = (1.0 - size) / 2.0
    return f"{offset:.6f},{offset:.6f},{size:.6f},{size:.6f}"


def camera_settings(args: argparse.Namespace) -> dict:
    """Impostazioni effettive dello scatto, già riportate in intervalli validi.

    Le chiavi sono le stesse colonne del CSV della foto.
    """
    af = resolve_af_settings(args)
    zoom = max(1.0, args.zoom)
    return {
        "camera_index": args.camera,
        "width": max(320, args.width),
        "height": max(240, args.height),
        "quality": max(1, min(100, args.quality)),
        "zoom": zoom,
        "roi": build_center_roi(zoom),
        "timeout_ms": max(100, args.timeout_ms),
        "af_mode": af["mode"],
        "af_range": af["range"],
        "af_speed": af["speed"],
        "af_window": af["window"],
        "af_on_capture": af["on_capture"],
        "shutter_us": max(0, args.shutter),
        "denoise": args.denoise,
        "sharpness": max(0.0, args.sharpness),
        "contrast": max(0.0, args.contrast),
    }


# ---------------------------------------------------------------------------
# Scatto
# ---------------------------------------------------------------------------

def build_command(camera_cmd: str, s: dict, output: Path) -> list[str]:
    # -n = niente anteprima; -t = per quanti ms tenere accesa la camera prima
    # di scattare (serve a esposizione, bilanciamento del bianco e fuoco).
    cmd = [
        camera_cmd, "-n",
        "--camera", str(s["camera_index"]),
        "--width", str(s["width"]), "--height", str(s["height"]),
        "--quality", str(s["quality"]),
        "--sharpness", str(s["sharpness"]), "--contrast", str(s["contrast"]),
        "--autofocus-mode", s["af_mode"],
        "--autofocus-range", s["af_range"],
        "--autofocus-speed", s["af_speed"],
        "-t", str(s["timeout_ms"]),
        "-o", str(output),
    ]
    # Le opzioni facoltative si aggiungono solo se impostate, così negli altri
    # casi valgono i default della camera.
    if s["af_window"]:
        cmd += ["--autofocus-window", s["af_window"]]
    if s["af_on_capture"]:
        cmd.append("--autofocus-on-capture")
    if s["shutter_us"] > 0:
        cmd += ["--shutter", str(s["shutter_us"])]
    if s["denoise"]:
        cmd += ["--denoise", s["denoise"]]
    if s["roi"]:
        cmd += ["--roi", s["roi"]]
    return cmd


def image_path(captured_at: datetime, camera_index: int) -> Path:
    """Nome file in UTC con i millisecondi: due scatti non si sovrascrivono."""
    stamp = captured_at.strftime("%Y%m%dT%H%M%S_") + f"{captured_at.microsecond // 1000:03d}Z"
    return config.IMAGE_DIR / f"{stamp}_cam{camera_index}.jpg"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def take_photo(settings: dict) -> dict:
    """Fa uno scatto. Restituisce le colonne del CSV relative alla foto.

    Se lo scatto fallisce ``image_file`` resta vuoto e il motivo è in ``errors``.
    """
    captured_at = utc_now()
    row = {"captured_at_utc": iso(captured_at), "pi_clock_synced": clock_synced(), **settings}

    # Su Bookworm il comando si chiama rpicam-still; sui sistemi più vecchi
    # esiste solo libcamera-still, che accetta le stesse opzioni.
    camera_cmd = which("rpicam-still") or which("libcamera-still")
    if not camera_cmd:
        row["errors"] = "rpicam-still non trovato"
        logger.error(row["errors"])
        return row

    output = image_path(captured_at, settings["camera_index"])
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(camera_cmd, settings, output)
    logger.info("Scatto: %s", " ".join(cmd))
    try:
        # Il timeout evita che una camera bloccata blocchi tutto il ciclo.
        subprocess.run(cmd, check=True, timeout=settings["timeout_ms"] / 1000 + 30,
                       capture_output=True, text=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        row["errors"] = f"scatto fallito: {exc} {stderr.strip()[-200:]}"
        logger.error(row["errors"])
        return row

    row["image_file"] = output.name
    row["size_bytes"] = output.stat().st_size
    row["sha256"] = sha256_of(output)
    logger.info("Foto salvata: %s", output)
    return row


# ---------------------------------------------------------------------------
# Raccolta dati
# ---------------------------------------------------------------------------

def pi_boot_id() -> str:
    """Identificativo dell'avvio corrente di Linux: raggruppa i dati di un ciclo di wake."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def esp_columns(sync_result: dict | None) -> dict:
    """Colonne del CSV della foto che riguardano l'ESP: ultima misura del BME280,
    ultimo evento che ha acceso il Pi ed esito dello scambio."""
    cols = {}
    if sync_result is not None:
        info = sync_result.get("info") or {}
        cols.update({
            "esp_sync_at_utc": sync_result.get("at"),
            "esp_received": sync_result.get("received"),
            "esp_lost": info.get("lost"),
            "esp_error": sync_result.get("error"),
        })
    last = esp_link.latest_measurement()
    if last:
        for key in ("esp_boot_id", "seq", "measured_at_utc", "received_at_utc", "status",
                    "temperature_c", "humidity_pct", "pressure_hpa"):
            cols[f"bme_{key}"] = last.get(key)
    wake = esp_link.latest_wake_event()
    if wake:
        for key in ("esp_boot_id", "seq", "measured_at_utc", "changed_pct"):
            cols[f"wake_{key}"] = wake.get(key)
    return cols


def sync_esp(enabled: bool) -> dict | None:
    if not enabled:
        return None
    result = esp_link.sync()
    result["at"] = iso(utc_now())
    return result


def save_sidecar(photo: dict, esp: dict | None, sensor_row: dict | None, mode: str) -> None:
    if not photo.get("image_file"):
        return  # niente foto, niente CSV: l'errore è già nel log
    row = {"mode": mode, "pi_boot_id": pi_boot_id(), **photo, **esp_columns(esp)}
    if sensor_row:
        row.update(sensor_row)
    path = write_sidecar(config.IMAGE_DIR / photo["image_file"], SIDECAR_HEADER, row)
    logger.info("Metadati salvati: %s", path)


def run_oneshot(args: argparse.Namespace) -> int:
    """Ciclo dell'app selettiva. Exit code 0 solo se foto, ESP e sensori sono andati bene."""
    settings = camera_settings(args)
    # Prima la foto: è il motivo per cui il Pi è stato acceso, e prima la
    # facciamo meno il soggetto ha tempo di spostarsi.
    photo = take_photo(settings)
    esp = sync_esp(not args.no_esp)
    sensor_row = sensors.read_and_save()
    try:
        save_sidecar(photo, esp, sensor_row, mode="selective")
    except OSError as exc:
        logger.error("CSV della foto non salvato: %s", exc)
        return 1

    failed = bool(photo.get("errors")) or bool(sensor_row["sensors_failed"])
    failed |= esp is not None and esp["error"] is not None
    return 1 if failed else 0


def _parse_hhmm(text: str):
    return datetime.strptime(text, "%H:%M").time() if text else None


def in_daily_window(now: datetime, start, end) -> bool:
    """True se ``now`` (ora locale) è nella fascia oraria. Gestisce anche le fasce a cavallo della mezzanotte."""
    if start is None or end is None:
        return True
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def run_continuous(args: argparse.Namespace) -> int:
    """Ciclo del monitoraggio continuativo, con due cadenze indipendenti."""
    if args.interval < 1 or args.sensor_interval < 1:
        logger.error("--interval e --sensor-interval devono essere almeno 1")
        return 1
    start = _parse_hhmm(config.DAILY_WINDOW_START)
    end = _parse_hhmm(config.DAILY_WINDOW_END)
    settings = camera_settings(args)
    logger.info("Modalità continuativa: foto ogni %ss, sensori ogni %ss, fascia %s-%s",
                args.interval, args.sensor_interval, start or "-", end or "-")

    # Le scadenze sono calcolate sul tempo monotono e avanzano di un periodo
    # fisso: la durata dello scatto non fa "scivolare" la cadenza.
    next_sensors = next_photo = time.monotonic()
    last_esp, last_sensors = None, None
    while True:
        now = time.monotonic()
        if not in_daily_window(datetime.now(), start, end):
            time.sleep(30)
            next_sensors = next_photo = time.monotonic()
            continue
        if now >= next_sensors:
            last_esp = sync_esp(not args.no_esp)
            last_sensors = sensors.read_and_save()
            next_sensors += args.sensor_interval
        if now >= next_photo:
            photo = take_photo(settings)
            try:
                save_sidecar(photo, last_esp, last_sensors, mode="continuous")
            except OSError as exc:
                logger.error("CSV della foto non salvato: %s", exc)
            next_photo += args.interval
        # Se una scadenza è già passata da più di un periodo (Pi rallentato)
        # ripartiamo da adesso invece di recuperare a raffica.
        now = time.monotonic()
        next_sensors = max(next_sensors, now - args.sensor_interval)
        next_photo = max(next_photo, now - args.interval)
        time.sleep(max(0.1, min(next_sensors, next_photo) - now))


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        level=logging.INFO)
    return run_oneshot(args) if args.oneshot else run_continuous(args)


if __name__ == "__main__":
    raise SystemExit(main())
