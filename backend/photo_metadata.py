#!/usr/bin/env python3
"""
Photo metadata handling for backend package.

Provides DEFAULT_METADATA, load_metadata_for_image_path, save_metadata_for_image_path
compatible with capture_client.py expectations.

Stores metadata as JSON sidecar files (same name as image, .json extension).
This is simpler and more robust than EXIF manipulation.
"""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Default metadata structure
DEFAULT_METADATA = {
    "latitude": None,
    "longitude": None,
    "altitude": None,
    "temperature": None,
    "humidity": None,
    "pressure": None,
    "capture_timestamp": None,
    "camera_settings": {},
    "sensor_readings": {},
}


def _get_metadata_path(image_path: str) -> str:
    """Get the sidecar JSON path for an image."""
    base, _ = os.path.splitext(image_path)
    return base + ".json"


def load_metadata_for_image_path(image_path: str) -> Optional[Dict[str, Any]]:
    """
    Load metadata from sidecar JSON file.

    Args:
        image_path: Path to the image file

    Returns:
        Metadata dict or None if not found/invalid
    """
    meta_path = _get_metadata_path(image_path)
    if not os.path.exists(meta_path):
        return None

    try:
        with open(meta_path, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Failed to load metadata from {meta_path}: {exc}")
        return None


def save_metadata_for_image_path(image_path: str, metadata: Dict[str, Any]) -> bool:
    """
    Save metadata to sidecar JSON file.

    Args:
        image_path: Path to the image file
        metadata: Metadata dict to save

    Returns:
        True on success, False on failure
    """
    meta_path = _get_metadata_path(image_path)
    try:
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        logger.debug(f"Saved metadata to {meta_path}")
        return True
    except Exception as exc:
        logger.error(f"Failed to save metadata to {meta_path}: {exc}")
        return False


def create_metadata_for_capture(
    image_path: str,
    gps_fix: Optional[Dict[str, Any]] = None,
    bme_reading: Optional[Dict[str, Any]] = None,
    camera_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a complete metadata dict for a new capture.

    Args:
        image_path: Path where image will be saved
        gps_fix: Dict from get_gps_fix()
        bme_reading: Dict from get_bme280_reading()
        camera_settings: Dict of camera parameters used

    Returns:
        Complete metadata dict
    """
    from datetime import datetime, timezone

    metadata = dict(DEFAULT_METADATA)
    metadata["capture_timestamp"] = datetime.now(timezone.utc).isoformat()

    if camera_settings:
        metadata["camera_settings"] = camera_settings

    if gps_fix:
        metadata["latitude"] = gps_fix.get("latitude")
        metadata["longitude"] = gps_fix.get("longitude")
        metadata["altitude"] = gps_fix.get("altitude")
        metadata["sensor_readings"]["gps_satellites"] = gps_fix.get("satellites")

    if bme_reading:
        metadata["temperature"] = bme_reading.get("temperature")
        metadata["humidity"] = bme_reading.get("humidity")
        metadata["pressure"] = bme_reading.get("pressure")
        metadata["sensor_readings"]["bme_address"] = bme_reading.get("bme_address")

    return metadata


if __name__ == "__main__":
    # Quick test
    import tempfile
    logging.basicConfig(level=logging.DEBUG)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        test_img = f.name

    # Test save/load
    meta = create_metadata_for_capture(test_img, camera_settings={"width": 4608, "height": 2592})
    save_metadata_for_image_path(test_img, meta)

    loaded = load_metadata_for_image_path(test_img)
    print(f"Loaded: {loaded}")

    # Cleanup
    os.unlink(test_img)
    os.unlink(_get_metadata_path(test_img))