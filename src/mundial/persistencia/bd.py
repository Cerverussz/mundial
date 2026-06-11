"""Conexión SQLite local (caché derivado, nunca commiteado)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from mundial.config import DIR_LOCAL


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or (DIR_LOCAL / "mundial.db")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    return conexion
