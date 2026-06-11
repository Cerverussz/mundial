"""Historial directo (H2H) — peso bajo por diseño: muestras chicas engañan."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

ANIOS = 10
MAX_PARTIDOS = 10
POR_GOL = 0.02
TOPE = 0.04


def factor_h2h(
    conexion: sqlite3.Connection, equipo_a: str, equipo_b: str, referencia: date
) -> tuple[float, float]:
    """(factor para A, factor para B) según diferencia de gol promedio en el H2H."""
    desde = (referencia - timedelta(days=365 * ANIOS)).isoformat()
    filas = conexion.execute(
        """SELECT local, goles_local, goles_visitante FROM resultados_historicos
           WHERE ((local = ? AND visitante = ?) OR (local = ? AND visitante = ?))
             AND fecha >= ? ORDER BY fecha DESC LIMIT ?""",
        (equipo_a, equipo_b, equipo_b, equipo_a, desde, MAX_PARTIDOS),
    ).fetchall()
    if not filas:
        return 1.0, 1.0
    diferencia = 0.0
    for fila in filas:
        delta = fila["goles_local"] - fila["goles_visitante"]
        diferencia += delta if fila["local"] == equipo_a else -delta
    promedio = diferencia / len(filas)
    ajuste = min(max(promedio * POR_GOL, -TOPE), TOPE)
    return 1.0 + ajuste, 1.0 - ajuste
