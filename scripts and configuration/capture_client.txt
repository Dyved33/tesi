#!/usr/bin/env python3
import argparse
import logging
import os
import subprocess
import time
from datetime import datetime
from shutil import which

from backend.bme_reader import get_bme280_reading
from backend.gps_reader import get_gps_fix
from backend.photo_metadata import (
    DEFAULT_METADATA,
    load_metadata_for_image_path,
    save_metadata_for_image_path,
)

IMAGE_DIR = "static/uploads/images"


def build_parser() -> argparse.ArgumentParser:
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
    """
    Resolve autofocus settings from profile, then apply explicit overrides.
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
    """
    Build centered ROI for rpicam/libcamera in normalized coords x,y,w,h.
    """
    if zoom_factor <= 1.0:
        return None

    box_size = 1.0 / zoom_factor
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
    os.makedirs(IMAGE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file_path = os.path.join(IMAGE_DIR, f"rpi_{timestamp}.jpg")

    camera_cmd = which("rpicam-still") or which("libcamera-still")
    if not camera_cmd:
        logging.error(
            "No camera CLI found. Install rpicam-still or libcamera-still on Raspberry Pi."
        )
        return None

    quality = max(1, min(100, quality))
    width = max(320, width)
    height = max(240, height)
    zoom = max(1.0, zoom)
    shutter = max(0, shutter)
    sharpness = max(0.0, sharpness)
    contrast = max(0.0, contrast)

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
        subprocess.run(cmd, check=True)
        metadata = load_metadata_for_image_path(file_path)
        if not metadata:
            metadata = dict(DEFAULT_METADATA)
        metadata_updated = False

        fix = get_gps_fix()
        if fix:
            metadata["latitude"] = fix["latitude"]
            metadata["longitude"] = fix["longitude"]
            metadata_updated = True
            logging.info(
                "GPS fix saved for %s: lat=%.7f lon=%.7f (%s)",
                os.path.basename(file_path),
                float(fix["latitude"]),
                float(fix["longitude"]),
                fix.get("gps_port", "unknown-port"),
            )
        else:
            logging.info("No GPS fix available for %s", os.path.basename(file_path))

        bme = get_bme280_reading()
        if bme:
            metadata["temperature"] = bme.get("temperature")
            metadata["humidity"] = bme.get("humidity")
            metadata["pressure"] = bme.get("pressure")
            metadata_updated = True
            logging.info(
                "BME280 reading saved for %s: T=%.2fC H=%.2f%% P=%.2fhPa (%s)",
                os.path.basename(file_path),
                float(metadata["temperature"]),
                float(metadata["humidity"]),
                float(metadata["pressure"]),
                bme.get("bme_address", "unknown-addr"),
            )
        else:
            logging.info("No BME280 reading available for %s", os.path.basename(file_path))

        if metadata_updated:
            save_metadata_for_image_path(file_path, metadata)

        logging.info("Saved image: %s", file_path)
        return file_path
    except subprocess.CalledProcessError as exc:
        logging.error("Capture failed: %s", exc)
        return None


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )
    af_settings = resolve_af_settings(args)

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
