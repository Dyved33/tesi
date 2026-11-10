#!/usr/bin/env python3
"""Scatta foto con la camera del Raspberry Pi e, se possibile, aggiunge il GPS.

Lo scatto vero e proprio lo fa il comando ``rpicam-still`` (o il vecchio
``libcamera-still``): questo script costruisce la riga di comando, la lancia
e poi prova a leggere il GPS per salvare le coordinate nel JSON della foto.

- con ``--oneshot`` fa una foto ed esce (è il caso dell'app selettiva);
- senza, scatta in ciclo ogni ``--interval`` secondi.

Si lancia come modulo, dalla cartella raspberry_pi/ (lo fa capture_rpi.sh)::

    python3 -m smartcam.capture_client --oneshot

Il BME280 di campo NON viene letto qui: è collegato all'ESP32 e il protocollo
per farne arrivare i dati al Pi non esiste ancora.
"""
# Provenienza:
# - Il flusso (scatto -> GPS -> JSON) e il parser degli argomenti sono scritti da noi.
# - Le opzioni passate a rpicam-still (-n, -t, -o, --width, --height, --quality,
#   --autofocus-mode/range/speed/window, --autofocus-on-capture, --shutter,
#   --denoise, --sharpness, --contrast, --roi) vengono dalla documentazione
#   ufficiale Raspberry Pi:
#   https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still
#   https://www.raspberrypi.com/documentation/computers/camera_software.html#camera-control-options
# - I valori di default 4608x2592 sono la risoluzione piena del sensore IMX708
#   della Camera Module 3 (dalla stessa documentazione).
# - Lo zoom digitale tramite --roi centrato (build_center_roi) è un calcolo
#   nostro basato sulla descrizione dell'opzione --roi nella documentazione.
# - Valutata ma non adottata: la libreria ufficiale Picamera2
#   (https://github.com/raspberrypi/picamera2) potrebbe sostituire la chiamata
#   a rpicam-still, ma richiede di riscrivere tutto lo scatto e provarlo
#   sulla camera vera (vedi issues.md).
import argparse
import logging
import os
import subprocess
import time
from datetime import datetime
from shutil import which

from .gps_reader import get_gps_fix
from .photo_metadata import (
    DEFAULT_METADATA,
    load_metadata_for_image_path,
    save_metadata_for_image_path,
)

# Cartella delle foto, relativa alla directory da cui si lancia lo script
# (capture_rpi.sh fa prima cd nella root del progetto).
IMAGE_DIR = "static/uploads/images"


def build_parser() -> argparse.ArgumentParser:
    """Definisce le opzioni da riga di comando: tempi, formato immagine e controlli camera."""
    parser = argparse.ArgumentParser(
        description="Camera capture client for Raspberry Pi (camera only)."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Seconds between captures in continuous mode (default: 30).",
    )
    parser.add_argument(
        "--warmup-ms",
        type=int,
        default=2000,
        help="Camera warmup in milliseconds passed to libcamera-still (default: 2000).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=3000,
        help="Capture timeout in milliseconds passed to libcamera-still (default: 3000).",
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Capture one image and exit.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=4608,
        help="Output width in pixels (default: 4608).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=2592,
        help="Output height in pixels (default: 2592).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=100,
        help="JPEG quality from 1 to 100 (default: 100).",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=1.0,
        help=(
            "Digital zoom factor. 1.0 = no zoom, 2.0 = 2x zoom, 4.0 = 4x zoom "
            "(default: 1.0)."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=["standard", "macro"],
        default="standard",
        help="Capture profile preset (default: standard).",
    )
    parser.add_argument(
        "--af-mode",
        choices=["manual", "auto", "continuous"],
        default=None,
        help="Autofocus mode override.",
    )
    parser.add_argument(
        "--af-range",
        choices=["normal", "macro", "full"],
        default=None,
        help="Autofocus range override.",
    )
    parser.add_argument(
        "--af-speed",
        choices=["normal", "fast"],
        default=None,
        help="Autofocus speed override.",
    )
    parser.add_argument(
        "--af-window",
        type=str,
        default=None,
        help="Autofocus window x,y,w,h (normalized, e.g. 0.3,0.3,0.4,0.4).",
    )
    parser.add_argument(
        "--af-on-capture",
        action="store_true",
        help="Trigger autofocus scan just before capture.",
    )
    parser.add_argument(
        "--shutter",
        type=int,
        default=0,
        help="Fixed shutter in microseconds (0 = auto). Example: 8000.",
    )
    parser.add_argument(
        "--denoise",
        choices=["auto", "off", "cdn_off", "cdn_fast", "cdn_hq"],
        default=None,
        help="Denoise mode override.",
    )
    parser.add_argument(
        "--sharpness",
        type=float,
        default=1.0,
        help="Image sharpness (default: 1.0).",
    )
    parser.add_argument(
        "--contrast",
        type=float,
        default=1.0,
        help="Image contrast (default: 1.0).",
    )
    return parser


def resolve_af_settings(args: argparse.Namespace) -> dict[str, str | bool | None]:
    """Calcola le impostazioni dell'autofocus.

    Si parte dal profilo scelto ("standard" o "macro") e poi si sovrascrive
    con le opzioni --af-* passate esplicitamente, che hanno la precedenza.
    """
    if args.profile == "macro":
        af = {
            "mode": "continuous",
            "range": "macro",
            "speed": "normal",
            "window": "0.30,0.30,0.40,0.40",
            "on_capture": False,
        }
    else:
        af = {
            "mode": "continuous",
            "range": "full",
            "speed": "normal",
            "window": "0.35,0.35,0.30,0.30",
            "on_capture": False,
        }

    if args.af_mode is not None:
        af["mode"] = args.af_mode
    if args.af_range is not None:
        af["range"] = args.af_range
    if args.af_speed is not None:
        af["speed"] = args.af_speed
    if args.af_window is not None:
        af["window"] = args.af_window
    if args.af_on_capture:
        af["on_capture"] = True
    return af


def build_center_roi(zoom_factor: float) -> str | None:
    """Calcola il ritaglio centrale per lo zoom digitale (``None`` se zoom = 1x).

    --roi vuole x,y,larghezza,altezza come frazioni (da 0 a 1) dell'immagine
    intera. Con zoom 2x prendiamo un quadrato largo metà, centrato. È solo un
    ritaglio: non aumenta il dettaglio come farebbe uno zoom ottico.
    """
    if zoom_factor <= 1.0:
        return None

    box_size = 1.0 / zoom_factor
    # Limitiamo il ritaglio al 5% per evitare zoom assurdi (oltre 20x).
    box_size = max(0.05, min(1.0, box_size))
    x = (1.0 - box_size) / 2.0
    y = (1.0 - box_size) / 2.0
    return f"{x:.6f},{y:.6f},{box_size:.6f},{box_size:.6f}"


def capture_photo(
    warmup_ms: int,
    timeout_ms: int,
    width: int,
    height: int,
    quality: int,
    zoom: float,
    af_settings: dict[str, str | bool | None],
    shutter: int,
    denoise: str | None,
    sharpness: float,
    contrast: float,
) -> str | None:
    """Fa uno scatto, salva il JPG e, se c'è un fix GPS, il JSON con le coordinate.

    Restituisce il percorso dell'immagine se tutto va bene, ``None`` se il
    comando della camera non esiste o fallisce. Il GPS viene letto DOPO lo
    scatto, quindi la posizione si riferisce a qualche secondo più tardi.
    """
    # Nome file con data e ora locali, al secondo (es. rpi_20261022-093524.jpg).
    os.makedirs(IMAGE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file_path = os.path.join(IMAGE_DIR, f"rpi_{timestamp}.jpg")

    # Su Bookworm il comando si chiama rpicam-still; su sistemi più vecchi
    # esiste solo libcamera-still, che accetta le stesse opzioni.
    camera_cmd = which("rpicam-still") or which("libcamera-still")
    if not camera_cmd:
        logging.error(
            "No camera CLI found. Install rpicam-still or libcamera-still on Raspberry Pi."
        )
        return None

    # Riportiamo i parametri in intervalli sensati prima di passarli alla camera.
    quality = max(1, min(100, quality))
    width = max(320, width)
    height = max(240, height)
    zoom = max(1.0, zoom)
    shutter = max(0, shutter)
    sharpness = max(0.0, sharpness)
    contrast = max(0.0, contrast)

    # -n = nessuna finestra di anteprima; -t = per quanti ms tenere accesa la
    # camera prima di scattare (warmup + timeout sommati); -o = file di uscita.
    cmd = [
        camera_cmd,
        "-n",
        "--autofocus-mode",
        str(af_settings["mode"]),
        "--autofocus-range",
        str(af_settings["range"]),
        "--autofocus-speed",
        str(af_settings["speed"]),
        "--width",
        str(width),
        "--height",
        str(height),
        "--quality",
        str(quality),
        "--sharpness",
        str(sharpness),
        "--contrast",
        str(contrast),
        "-t",
        str(timeout_ms + warmup_ms),
        "-o",
        file_path,
    ]
    # Le opzioni facoltative si aggiungono solo se impostate, così negli altri
    # casi valgono i default della camera.
    if shutter > 0:
        cmd.extend(["--shutter", str(shutter)])
    if denoise:
        cmd.extend(["--denoise", denoise])
    if af_settings.get("window"):
        cmd.extend(["--autofocus-window", str(af_settings["window"])])
    if af_settings.get("on_capture"):
        cmd.append("--autofocus-on-capture")
    roi = build_center_roi(zoom)
    if roi:
        cmd.extend(["--roi", roi])

    logging.info("Capturing image: %s", file_path)
    logging.info(
        "Capture params: %sx%s quality=%s zoom=%.2fx",
        width,
        height,
        quality,
        zoom,
    )
    logging.info(
        "AF params: mode=%s range=%s speed=%s window=%s on_capture=%s",
        af_settings["mode"],
        af_settings["range"],
        af_settings["speed"],
        af_settings["window"],
        af_settings["on_capture"],
    )
    logging.info(
        "Image params: shutter=%sus denoise=%s sharpness=%.2f contrast=%.2f",
        shutter,
        denoise or "default",
        sharpness,
        contrast,
    )
    try:
        # check=True: se la camera esce con errore parte CalledProcessError.
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        logging.error("Capture failed: %s", exc)
        return None

    # Da qui in poi la foto è già salvata: un problema con GPS o metadati non
    # deve far risultare fallito lo scatto, quindi lo registriamo e basta.
    try:
        _attach_gps_metadata(file_path)
    except Exception:
        logging.exception("Metadata update failed for %s", file_path)

    logging.info("Saved image: %s", file_path)
    return file_path


def _attach_gps_metadata(file_path: str) -> None:
    """Legge il GPS e, se c'è un fix, salva le coordinate nel JSON della foto."""
    # Se esiste già un JSON per questa foto lo aggiorniamo, altrimenti
    # partiamo dalla struttura vuota di default.
    metadata = load_metadata_for_image_path(file_path)
    if not metadata:
        metadata = dict(DEFAULT_METADATA)

    # Il record "dummy" (librerie GPS mancanti) è un dizionario non vuoto ma
    # con latitudine None: va trattato come "nessun fix".
    # Nota: per ora copiamo solo latitudine e longitudine (vedi issues.md).
    fix = get_gps_fix()
    if not fix or fix.get("latitude") is None or fix.get("longitude") is None:
        logging.info("No GPS fix available for %s", os.path.basename(file_path))
        return

    metadata["latitude"] = fix["latitude"]
    metadata["longitude"] = fix["longitude"]
    logging.info(
        "GPS fix saved for %s: lat=%.7f lon=%.7f (%s)",
        os.path.basename(file_path),
        float(fix["latitude"]),
        float(fix["longitude"]),
        fix.get("gps_port", "unknown-port"),
    )

    # Qui andranno le misure del BME280 ricevute dall'ESP32, quando ci sarà
    # il protocollo ESP→Pi. Il sensore di campo non va letto via I2C dal Pi.

    # Il JSON viene scritto solo se abbiamo aggiunto qualcosa (oggi: solo col GPS).
    save_metadata_for_image_path(file_path, metadata)


def main() -> int:
    """Legge le opzioni, poi fa uno scatto singolo oppure parte con il ciclo continuo."""
    args = build_parser().parse_args()
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )
    af_settings = resolve_af_settings(args)

    # Modalità singola: exit code 0 se lo scatto è riuscito, 1 altrimenti
    # (systemd lo usa per decidere se spegnere il Pi).
    if args.oneshot:
        return 0 if capture_photo(
            args.warmup_ms,
            args.timeout_ms,
            args.width,
            args.height,
            args.quality,
            args.zoom,
            af_settings,
            args.shutter,
            args.denoise,
            args.sharpness,
            args.contrast,
        ) else 1

    if args.interval < 1:
        logging.error("--interval must be >= 1")
        return 1

    logging.info(
        "Starting continuous capture. interval=%ss warmup=%sms timeout=%sms",
        args.interval,
        args.warmup_ms,
        args.timeout_ms,
    )

    # Ciclo infinito: un errore di scatto viene solo registrato nel log e si
    # riprova al giro dopo. La pausa parte DOPO lo scatto, quindi il periodo
    # reale è un po' più lungo di --interval.
    while True:
        capture_photo(
            args.warmup_ms,
            args.timeout_ms,
            args.width,
            args.height,
            args.quality,
            args.zoom,
            af_settings,
            args.shutter,
            args.denoise,
            args.sharpness,
            args.contrast,
        )
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
