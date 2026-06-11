"""Configuración: claves de API y rutas del proyecto."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
DIR_SNAPSHOTS = RAIZ / "data" / "snapshots"
DIR_LOCAL = RAIZ / "data" / "local"

load_dotenv(RAIZ / ".env")


def clave(nombre: str) -> str:
    """Lee una clave del entorno; falla con mensaje claro si no existe."""
    valor = os.environ.get(nombre, "")
    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre} (revisa .env o los secrets de CI)")
    return valor
