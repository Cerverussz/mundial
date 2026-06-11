"""Contexto del partido: altitud, descanso entre partidos del torneo, clima."""
from __future__ import annotations

import sqlite3
from datetime import datetime

ACOSTUMBRADOS_ALTITUD = {
    "Mexico", "Bolivia", "Ecuador", "Colombia", "Peru", "Venezuela", "Guatemala", "Honduras",
}
DIAS_DESCANSO_CORTO = 4
DIAS_BUSQUEDA = 10
CALOR_EXTREMO_C = 30


def factor_altitud(equipo: str, altitud_m: float | None) -> float:
    if altitud_m is None or equipo in ACOSTUMBRADOS_ALTITUD:
        return 1.0
    if altitud_m >= 2000:
        return 0.94
    if altitud_m >= 1500:
        return 0.97
    return 1.0


def factor_descanso(conexion: sqlite3.Connection, equipo: str, fecha_utc: str) -> float:
    """Castiga descanso corto desde el último partido jugado del torneo."""
    fila = conexion.execute(
        """SELECT MAX(fecha_utc) AS ultima FROM partidos
           WHERE (local = ? OR visitante = ?) AND fecha_utc < ? AND goles_local IS NOT NULL""",
        (equipo, equipo, fecha_utc),
    ).fetchone()
    if not fila or not fila["ultima"]:
        return 1.0
    ultima = datetime.fromisoformat(fila["ultima"].replace("Z", "+00:00"))
    actual = datetime.fromisoformat(fecha_utc.replace("Z", "+00:00"))
    dias = (actual - ultima).total_seconds() / 86400.0
    if dias > DIAS_BUSQUEDA:
        return 1.0
    return 0.97 if dias < DIAS_DESCANSO_CORTO else 1.0


def factor_clima(temperatura_c: float | None) -> float:
    if temperatura_c is not None and temperatura_c >= CALOR_EXTREMO_C:
        return 0.97
    return 1.0
