"""Carga de datos estáticos (estadios del Mundial 2026) a la base local."""
from __future__ import annotations

import csv
import sqlite3

from mundial.config import RAIZ

RUTA_ESTADIOS = RAIZ / "data" / "static" / "estadios.csv"
RUTA_CONFEDERACIONES = RAIZ / "data" / "static" / "confederaciones.csv"


def cargar_estadios(conexion: sqlite3.Connection) -> int:
    with open(RUTA_ESTADIOS, encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    conexion.executemany(
        "INSERT OR REPLACE INTO estadios VALUES (:nombre,:ciudad,:pais,:altitud_m,:lat,:lon,:tz)",
        filas,
    )
    conexion.commit()
    return len(filas)


def cargar_confederaciones(conexion: sqlite3.Connection) -> int:
    with open(RUTA_CONFEDERACIONES, encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    conexion.executemany(
        """INSERT INTO equipos(nombre, confederacion) VALUES (:equipo, :confederacion)
           ON CONFLICT(nombre) DO UPDATE SET confederacion = excluded.confederacion""",
        filas,
    )
    conexion.commit()
    return len(filas)
