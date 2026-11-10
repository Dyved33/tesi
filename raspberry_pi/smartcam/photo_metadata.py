#!/usr/bin/env python3
"""Metadati delle foto salvati in un file JSON accanto all'immagine.

Per ogni foto ``foto.jpg`` scriviamo ``foto.json`` (il cosiddetto "sidecar")
con posizione, misure ambientali e impostazioni della camera. Abbiamo scelto
il JSON separato invece dei tag EXIF perché è più semplice da leggere e da
estendere, e non tocca il file immagine. I valori mancanti sono ``None``.

``capture_client.py`` usa le funzioni di lettura/scrittura e
``DEFAULT_METADATA``; ``create_metadata_for_capture`` è un helper pronto ma
per ora il client non lo chiama.
"""
# Provenienza: formato del JSON e funzioni scritte da noi, usando solo la
# libreria standard di Python (json, os). Nessuna fonte esterna.

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Struttura "fissa" del sidecar: chi legge il JSON trova sempre queste chiavi,
# anche quando il sensore corrispondente non è collegato (valore None).
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
    """Dal percorso della foto ricava quello del JSON (stesso nome, estensione .json)."""
    base, _ = os.path.splitext(image_path)
    return base + ".json"


def load_metadata_for_image_path(image_path: str) -> Optional[Dict[str, Any]]:
    """Legge il JSON associato a una foto.

    Args:
        image_path: percorso dell'immagine.

    Returns:
        Il dizionario dei metadati, oppure None se il file non c'è o non è
        un JSON valido.
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
    """Scrive (o sovrascrive) il JSON associato a una foto.

    Args:
        image_path: percorso dell'immagine.
        metadata: dizionario da salvare.

    Returns:
        True se il salvataggio è andato bene, False altrimenti.
    """
    meta_path = _get_metadata_path(image_path)
    try:
        with open(meta_path, "w") as f:
            # default=str evita errori con tipi non serializzabili (es. datetime).
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
    """Costruisce il record standard a partire dalle letture disponibili.

    Args:
        image_path: per ora non usato (la funzione non scrive file).
        gps_fix: risultato di get_gps_fix().
        bme_reading: risultato di get_bme280_reading().
        camera_settings: parametri usati per lo scatto.

    Returns:
        Il dizionario dei metadati; i campi GPS/BME assenti restano None.
        Il timestamp (UTC) è il momento in cui gira questa funzione, non
        quello della misura dei sensori.
    """
    from datetime import datetime, timezone

    # ATTENZIONE: dict() fa una copia superficiale, quindi "camera_settings" e
    # "sensor_readings" restano gli stessi oggetti di DEFAULT_METADATA e le
    # modifiche qui sotto si propagano alle chiamate successive (vedi issues.md).
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
    # Prova veloce: crea una finta immagine, salva e rilegge il JSON, poi pulisce.
    import tempfile
    logging.basicConfig(level=logging.DEBUG)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        test_img = f.name

    meta = create_metadata_for_capture(test_img, camera_settings={"width": 4608, "height": 2592})
    save_metadata_for_image_path(test_img, meta)

    loaded = load_metadata_for_image_path(test_img)
    print(f"Loaded: {loaded}")

    os.unlink(test_img)
    os.unlink(_get_metadata_path(test_img))
