"""Nivel de confianza de una predicción, con razones explícitas."""
from __future__ import annotations


def calcular(
    *,
    divergencia: float,
    edad_cuotas_h: float | None,
    n_casas: int,
    forma_ok_local: bool,
    forma_ok_visitante: bool,
    partidos_local: int,
    partidos_visitante: int,
    bajas_info: bool,
) -> tuple[str, list[str]]:
    puntaje = 100
    razones: list[str] = []
    if edad_cuotas_h is None or n_casas == 0:
        puntaje -= 25
        razones.append("sin cuotas de mercado disponibles")
    else:
        if edad_cuotas_h > 6:
            puntaje -= 10
            razones.append(f"cuotas con {edad_cuotas_h:.0f} h de antigüedad")
        if n_casas < 8:
            puntaje -= 5
            razones.append(f"solo {n_casas} casas en el consenso")
    if not forma_ok_local or not forma_ok_visitante:
        puntaje -= 10
        razones.append("datos de forma insuficientes")
    for nombre, n in (("local", partidos_local), ("visitante", partidos_visitante)):
        if n < 10:
            puntaje -= 15
            razones.append(f"equipo {nombre} con solo {n} partidos en la ventana del modelo")
    if divergencia > 0.15:
        puntaje -= 15
        razones.append(f"modelo y mercado divergen {divergencia * 100:.0f} pts")
    if not bajas_info:
        puntaje -= 5
        razones.append("sin información de alineaciones/bajas")
    if puntaje >= 75:
        return "Alta", razones
    if puntaje >= 50:
        return "Media", razones
    return "Baja", razones
