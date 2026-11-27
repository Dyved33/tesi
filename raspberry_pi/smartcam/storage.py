"""Scrittura dei CSV: serie temporali in data/ e CSV accanto a ogni foto.

Abbiamo scelto il CSV perché si apre con qualsiasi programma (pandas, R,
LibreOffice) e si può copiare sul server insieme alle foto senza dover
esportare niente. Ogni file ha un'intestazione fissa: le colonne sono
definite nei moduli che scrivono (``esp_link``, ``sensors``,
``capture_client``) e documentate in ``docs/dati-csv.md``.
"""
# Provenienza: scritto da noi con la libreria standard (csv, os, subprocess).
# Il controllo dell'orologio usa `timedatectl show`, vedi `man timedatectl`.

import csv
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_clock_cache: tuple[float, bool | None] = (0.0, None)


def clock_synced() -> bool | None:
    """True se l'orologio del Pi è stato sincronizzato con NTP da quando è acceso.

    Tutti gli orari dei CSV vengono dall'orologio del Pi: questa informazione
    finisce nelle colonne ``*clock_synced`` per sapere, dopo, se ci si può
    fidare. False non vuol dire per forza ora sbagliata: con la batteria
    dell'RTC l'ora resta giusta anche senza rete, ma non è stata verificata.
    None se ``timedatectl`` non c'è (per esempio sul PC).
    Il risultato viene tenuto per 60 s per non lanciare un processo a ogni riga.
    """
    global _clock_cache
    checked_at, value = _clock_cache
    if time.monotonic() - checked_at < 60 and checked_at:
        return value
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
        value = {"yes": True, "no": False}.get(out)
    except (OSError, subprocess.SubprocessError):
        value = None
    _clock_cache = (time.monotonic(), value)
    return value


def iso(dt: datetime | None) -> str:
    """Data e ora in formato ISO-8601 con i millisecondi, oppure stringa vuota."""
    return dt.isoformat(timespec="milliseconds") if dt else ""


def _clean(value):
    """Rende un valore adatto al CSV: None -> vuoto, bool -> 1/0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _read_header(path: Path) -> list[str] | None:
    try:
        with open(path, newline="") as f:
            return next(csv.reader(f), None)
    except FileNotFoundError:
        return None


def append_rows(path: Path, header: list[str], rows: Iterable[dict]) -> int:
    """Aggiunge righe a un CSV, creando file e intestazione se mancano.

    Se il file esiste ma ha un'intestazione diversa (perché abbiamo cambiato le
    colonne) non lo modifichiamo: lo rinominiamo in ``<nome>.<data>.csv`` e ne
    iniziamo uno nuovo. Così una riga non finisce mai sotto le colonne sbagliate.

    Il file viene sincronizzato su disco prima di tornare: chi chiama può
    considerare le righe salvate (``esp_link`` lo usa prima di mandare l'ACK).
    """
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)

    old_header = _read_header(path)
    if old_header is not None and old_header != header:
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path.rename(path.with_name(f"{path.stem}.{stamp}{path.suffix}"))
        old_header = None

    with open(path, "a", newline="") as f:
        # extrasaction="raise": una chiave che non è nell'intestazione è un
        # errore di programmazione e vogliamo accorgercene subito.
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="raise")
        if old_header is None:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: _clean(row.get(k)) for k in header})
        f.flush()
        os.fsync(f.fileno())
    return len(rows)


def write_sidecar(image_path: Path, header: list[str], row: dict) -> Path:
    """Scrive il CSV dei metadati accanto alla foto (foto.jpg -> foto.csv)."""
    path = image_path.with_suffix(".csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="raise")
        writer.writeheader()
        writer.writerow({k: _clean(row.get(k)) for k in header})
        f.flush()
        os.fsync(f.fileno())
    return path


def read_tail(path: Path, max_bytes: int = 512 * 1024) -> list[dict]:
    """Legge le ultime righe di un CSV (circa gli ultimi ``max_bytes``).

    Serve a ``esp_link`` per controllare i doppioni e per prendere l'ultima
    misura, senza rileggere ogni volta un file che cresce per mesi.
    """
    header = _read_header(path)
    if header is None:
        return []
    size = path.stat().st_size
    with open(path, newline="") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()  # la prima riga è quasi sicuramente tagliata a metà
        else:
            f.readline()  # salta l'intestazione
        return list(csv.DictReader(f, fieldnames=header))
