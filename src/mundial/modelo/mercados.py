"""Precios justos y liquidación de mercados derivados de la matriz de marcadores."""
from __future__ import annotations

import numpy as np

CUARTO = 0.25


def _es_cuarto(linea: float) -> bool:
    return abs(linea * 4 - round(linea * 4)) < 1e-9 and abs(linea * 2 - round(linea * 2)) > 1e-9


def prob_over(matriz: np.ndarray, linea: float) -> float:
    indices = np.indices(matriz.shape)
    return float(matriz[(indices[0] + indices[1]) > linea].sum())


def prob_under(matriz: np.ndarray, linea: float) -> float:
    indices = np.indices(matriz.shape)
    return float(matriz[(indices[0] + indices[1]) < linea].sum())


def prob_btts(matriz: np.ndarray) -> float:
    return float(matriz[1:, 1:].sum())


def _resultado_simple_total(matriz, linea: float, lado: str) -> dict:
    """Línea entera o semientera: gana/push/pierde."""
    indices = np.indices(matriz.shape)
    total = indices[0] + indices[1]
    p_push = float(matriz[total == linea].sum()) if abs(linea - round(linea)) < 1e-9 else 0.0
    p_over, p_under = prob_over(matriz, linea), prob_under(matriz, linea)
    if lado == "over":
        return {"p_gana": p_over, "p_pierde": p_under, "p_push": p_push,
                "p_media_gana": 0.0, "p_media_pierde": 0.0}
    return {"p_gana": p_under, "p_pierde": p_over, "p_push": p_push,
            "p_media_gana": 0.0, "p_media_pierde": 0.0}


def resultado_total(matriz, linea: float, lado: str) -> dict:
    """Distribución de resultados de la apuesta de totales (maneja líneas de cuarto)."""
    if not _es_cuarto(linea):
        return _resultado_simple_total(matriz, linea, lado)
    baja, alta = linea - CUARTO, linea + CUARTO
    a, b = _resultado_simple_total(matriz, baja, lado), _resultado_simple_total(matriz, alta, lado)
    entera, semi = (a, b) if abs(baja - round(baja)) < 1e-9 else (b, a)
    return {
        "p_gana": min(a["p_gana"], b["p_gana"]),
        "p_pierde": min(a["p_pierde"], b["p_pierde"]),
        "p_push": 0.0,
        "p_media_gana": entera["p_push"] if semi["p_gana"] > entera["p_gana"] else 0.0,
        "p_media_pierde": entera["p_push"] if semi["p_pierde"] > entera["p_pierde"] else 0.0,
    }


def resultado_ah(matriz, handicap: float) -> dict:
    """Distribución de la apuesta AL LOCAL con hándicap h (D = goles_local − goles_visitante)."""
    indices = np.indices(matriz.shape)
    diferencia = indices[0] - indices[1]

    def simple(h: float) -> dict:
        margen = diferencia + h
        return {
            "p_gana": float(matriz[margen > 1e-9].sum()),
            "p_pierde": float(matriz[margen < -1e-9].sum()),
            "p_push": float(matriz[np.abs(margen) < 1e-9].sum()),
            "p_media_gana": 0.0, "p_media_pierde": 0.0,
        }

    if not _es_cuarto(handicap):
        return simple(handicap)
    a, b = simple(handicap - CUARTO), simple(handicap + CUARTO)
    entera = a if a["p_push"] > 0 else b
    semi = b if entera is a else a
    return {
        "p_gana": min(a["p_gana"], b["p_gana"]),
        "p_pierde": min(a["p_pierde"], b["p_pierde"]),
        "p_push": 0.0,
        "p_media_gana": entera["p_push"] if semi["p_gana"] > entera["p_gana"] else 0.0,
        "p_media_pierde": entera["p_push"] if semi["p_pierde"] > entera["p_pierde"] else 0.0,
    }


def _cuota_justa(r: dict) -> float:
    perdida_efectiva = r["p_pierde"] + 0.5 * r["p_media_pierde"]
    ganancia_efectiva = r["p_gana"] + 0.5 * r["p_media_gana"]
    return 1.0 + perdida_efectiva / ganancia_efectiva if ganancia_efectiva > 0 else float("inf")


def cuota_justa_total(matriz, linea: float, lado: str) -> float:
    return _cuota_justa(resultado_total(matriz, linea, lado))


def cuota_justa_ah(matriz, handicap: float) -> float:
    return _cuota_justa(resultado_ah(matriz, handicap))


def cuotas_justas_dnb(matriz) -> tuple[float, float]:
    local = resultado_ah(matriz, 0.0)
    visita = {"p_gana": local["p_pierde"], "p_pierde": local["p_gana"],
              "p_push": local["p_push"], "p_media_gana": 0.0, "p_media_pierde": 0.0}
    return _cuota_justa(local), _cuota_justa(visita)


def ev_total(matriz, linea: float, lado: str, cuota: float) -> float:
    r = resultado_total(matriz, linea, lado)
    return (r["p_gana"] * (cuota - 1) + r["p_media_gana"] * (cuota - 1) / 2
            - r["p_media_pierde"] * 0.5 - r["p_pierde"])


def ev_ah(matriz, handicap: float, cuota: float) -> float:
    r = resultado_ah(matriz, handicap)
    return (r["p_gana"] * (cuota - 1) + r["p_media_gana"] * (cuota - 1) / 2
            - r["p_media_pierde"] * 0.5 - r["p_pierde"])


def liquidar_ah(diferencia: int, handicap: float, cuota: float) -> tuple[str, float]:
    """Liquida la apuesta con la diferencia de goles DESDE LA PERSPECTIVA del lado apostado."""
    if _es_cuarto(handicap):
        e1, r1 = liquidar_ah(diferencia, handicap - CUARTO, cuota)
        e2, r2 = liquidar_ah(diferencia, handicap + CUARTO, cuota)
        retorno = (r1 + r2) / 2.0
        estados = {e1, e2}
        if estados == {"ganada"}:
            return "ganada", retorno
        if estados == {"perdida"}:
            return "perdida", retorno
        if "ganada" in estados:
            return "media_ganada", retorno
        if "perdida" in estados:
            return "media_perdida", retorno
        return "push", 0.0
    margen = diferencia + handicap
    if margen > 1e-9:
        return "ganada", cuota - 1.0
    if margen < -1e-9:
        return "perdida", -1.0
    return "push", 0.0


def liquidar_total(total_goles: int, linea: float, lado: str, cuota: float) -> tuple[str, float]:
    if _es_cuarto(linea):
        e1, r1 = liquidar_total(total_goles, linea - CUARTO, lado, cuota)
        e2, r2 = liquidar_total(total_goles, linea + CUARTO, lado, cuota)
        retorno = (r1 + r2) / 2.0
        estados = {e1, e2}
        if estados == {"ganada"}:
            return "ganada", retorno
        if estados == {"perdida"}:
            return "perdida", retorno
        if "ganada" in estados:
            return "media_ganada", retorno
        if "perdida" in estados:
            return "media_perdida", retorno
        return "push", 0.0
    diferencia = total_goles - linea if lado == "over" else linea - total_goles
    if diferencia > 1e-9:
        return "ganada", cuota - 1.0
    if diferencia < -1e-9:
        return "perdida", -1.0
    return "push", 0.0


def liquidar_2way(gano: bool, cuota: float) -> tuple[str, float]:
    return ("ganada", cuota - 1.0) if gano else ("perdida", -1.0)
