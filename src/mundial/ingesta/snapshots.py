"""Escritura y lectura de snapshots crudos comprimidos (la bitácora del repo)."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from mundial.config import DIR_SNAPSHOTS


def escribir_snapshot(
    fuente: str,
    payload: dict | list,
    momento: datetime | None = None,
    base: Path | None = None,
) -> Path:
    momento = momento or datetime.now(timezone.utc)
    base = base or DIR_SNAPSHOTS
    carpeta = base / momento.strftime("%Y-%m-%d")
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{momento.strftime('%H%M%SZ')}-{fuente}.json.gz"
    contenido = {"fuente": fuente, "capturado_en": momento.isoformat(), "payload": payload}
    with gzip.open(ruta, "wt", encoding="utf-8") as archivo:
        json.dump(contenido, archivo, ensure_ascii=False, separators=(",", ":"))
    return ruta


def leer_snapshot(ruta: Path) -> dict:
    with gzip.open(ruta, "rt", encoding="utf-8") as archivo:
        return json.load(archivo)


def ultimo_snapshot(fuente: str, base: Path | None = None) -> datetime | None:
    """Momento del snapshot más reciente de una fuente, o None si no hay."""
    base = base or DIR_SNAPSHOTS
    rutas = sorted(base.glob(f"*/*-{fuente}.json.gz"))
    if not rutas:
        return None
    return datetime.fromisoformat(leer_snapshot(rutas[-1])["capturado_en"])
