"""Disponibilidad de plantel: bajas ponderadas por importancia (ai_score del XI predicho)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

PESO_TITULAR = 0.04
PESO_DESCONOCIDO = 0.025
FACTOR_DUDA = 0.5
TOPE_INFERIOR = 0.88


@dataclass
class FactorPlantel:
    propio: float
    detalle: str | None


def factor_plantel(conexion: sqlite3.Connection, partido_id: int, equipo: str) -> FactorPlantel:
    """Factor sobre la λ propia según las bajas más recientes conocidas del partido."""
    filas = conexion.execute(
        """SELECT jugador, estado, razon, ai_score FROM bajas
           WHERE partido_id = ? AND equipo = ?
             AND capturado_en = (SELECT MAX(capturado_en) FROM bajas
                                 WHERE partido_id = ? AND equipo = ?)""",
        (partido_id, equipo, partido_id, equipo),
    ).fetchall()
    if not filas:
        return FactorPlantel(1.0, None)
    penalizacion = 0.0
    nombres = []
    for fila in filas:
        peso = PESO_TITULAR * fila["ai_score"] if fila["ai_score"] else PESO_DESCONOCIDO
        if fila["estado"] == "doubtful":
            peso *= FACTOR_DUDA
        penalizacion += peso
        nombres.append(f"{fila['jugador']} ({fila['estado']})")
    factor = max(1.0 - penalizacion, TOPE_INFERIOR)
    return FactorPlantel(factor, f"bajas de {equipo}: " + ", ".join(nombres))
