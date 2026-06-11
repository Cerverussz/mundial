"""Intangibles: importancia del partido y rotación esperada (heurísticas documentadas)."""
from __future__ import annotations

FASES_ELIMINACION = {"LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE"}
FASES_FINAL = {"FINAL"}


def factor_fase(fase: str | None, jornada: int | None) -> tuple[float, str | None]:
    """Factor sobre ambas λ (los partidos de eliminación producen menos goles) y razón."""
    if fase in FASES_FINAL:
        return 0.95, "final: partido cerrado esperado"
    if fase in FASES_ELIMINACION:
        return 0.96, "eliminación directa: menos goles esperados"
    if fase == "GROUP_STAGE" and jornada == 3:
        return 0.99, "jornada 3: posible rotación según clasificación"
    return 1.0, None
