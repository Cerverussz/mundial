"""Forma reciente: rendimiento real vs esperado por el modelo, con encogimiento."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from mundial.modelo.dixon_coles import Ajuste

N_PARTIDOS = 10
DIAS_VENTANA = 540
MINIMO_PARTIDOS = 5
ENCOGIMIENTO = 2.0
LIMITES = (0.85, 1.15)


@dataclass
class FactorForma:
    ataque: float
    defensa: float
    detalle: str


def _esperados(ajuste: Ajuste, equipo: str, rival: str, es_local: bool, neutral: bool):
    """(goles esperados a favor, en contra) según el modelo para ese partido."""
    ventaja_propia = ajuste.ventaja_local if (es_local and not neutral) else 0.0
    ventaja_rival = ajuste.ventaja_local if (not es_local and not neutral) else 0.0
    favor = math.exp(ajuste.mu + ventaja_propia + ajuste.ataque[equipo] - ajuste.defensa[rival])
    contra = math.exp(ajuste.mu + ventaja_rival + ajuste.ataque[rival] - ajuste.defensa[equipo])
    return favor, contra


def factor_forma(
    conexion: sqlite3.Connection, equipo: str, referencia: date, ajuste: Ajuste
) -> FactorForma:
    desde = (referencia - timedelta(days=DIAS_VENTANA)).isoformat()
    filas = conexion.execute(
        """SELECT fecha, local, visitante, goles_local, goles_visitante, neutral
           FROM resultados_historicos
           WHERE (local = ? OR visitante = ?) AND fecha >= ? AND fecha < ?
           ORDER BY fecha DESC LIMIT ?""",
        (equipo, equipo, desde, referencia.isoformat(), N_PARTIDOS),
    ).fetchall()
    favor = contra = esperado_favor = esperado_contra = 0.0
    usados = 0
    for fila in filas:
        es_local = fila["local"] == equipo
        rival = fila["visitante"] if es_local else fila["local"]
        if rival not in ajuste.ataque:
            continue
        ef, ec = _esperados(ajuste, equipo, rival, es_local, bool(fila["neutral"]))
        favor += fila["goles_local"] if es_local else fila["goles_visitante"]
        contra += fila["goles_visitante"] if es_local else fila["goles_local"]
        esperado_favor += ef
        esperado_contra += ec
        usados += 1
    if usados < MINIMO_PARTIDOS:
        return FactorForma(1.0, 1.0, f"forma: datos insuficientes ({usados} partidos)")
    ataque = math.sqrt((favor + ENCOGIMIENTO) / (esperado_favor + ENCOGIMIENTO))
    defensa = math.sqrt((esperado_contra + ENCOGIMIENTO) / (contra + ENCOGIMIENTO))
    ataque = min(max(ataque, LIMITES[0]), LIMITES[1])
    defensa = min(max(defensa, LIMITES[0]), LIMITES[1])
    detalle = (
        f"forma ({usados} partidos): {favor:.0f} goles vs {esperado_favor:.1f} esperados; "
        f"{contra:.0f} en contra vs {esperado_contra:.1f}"
    )
    return FactorForma(ataque, defensa, detalle)
