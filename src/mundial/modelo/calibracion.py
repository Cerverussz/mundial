"""Calibración del peso modelo/mercado por log-loss con shrinkage al prior."""
from __future__ import annotations

import math
import sqlite3

import numpy as np

W_PRIOR, N_PRIOR = 0.4, 50
LIMITES = (0.2, 0.6)
ORDEN = ("local", "empate", "visitante")


def _muestras(conexion) -> list[tuple[tuple, tuple, int]]:
    filas = conexion.execute(
        """SELECT p.*, m.goles_local, m.goles_visitante FROM partidos m
           JOIN predicciones p ON p.id = (
             SELECT p2.id FROM predicciones p2
             WHERE p2.partido_id = m.id AND p2.creado_en < m.fecha_utc
             ORDER BY p2.creado_en DESC, p2.id DESC LIMIT 1)
           WHERE m.goles_local IS NOT NULL AND p.p_local_mercado IS NOT NULL""").fetchall()
    muestras = []
    for f in filas:
        d = f["goles_local"] - f["goles_visitante"]
        resultado = 0 if d > 0 else (1 if d == 0 else 2)
        modelo = (f["p_local_modelo"], f["p_empate_modelo"], f["p_visitante_modelo"])
        mercado = (f["p_local_mercado"], f["p_empate_mercado"], f["p_visitante_mercado"])
        muestras.append((modelo, mercado, resultado))
    return muestras


def _logloss(muestras, w: float, geometrico: bool) -> float:
    total = 0.0
    for modelo, mercado, resultado in muestras:
        if geometrico:
            log_p = [w * math.log(max(a, 1e-12)) + (1 - w) * math.log(max(b, 1e-12))
                     for a, b in zip(modelo, mercado)]
            maximo = max(log_p)
            p = [math.exp(v - maximo) for v in log_p]
            p = [v / sum(p) for v in p]
        else:
            p = [w * a + (1 - w) * b for a, b in zip(modelo, mercado)]
        total -= math.log(max(p[resultado], 1e-12))
    return total / len(muestras)


def optimizar_w(conexion: sqlite3.Connection) -> dict:
    muestras = _muestras(conexion)
    if len(muestras) < 5:
        return {"n": len(muestras), "w_recomendado": W_PRIOR, "nota": "muestra insuficiente"}
    rejilla = np.arange(0.0, 1.0001, 0.02)
    perdidas_lineal = [_logloss(muestras, w, False) for w in rejilla]
    w_crudo = float(rejilla[int(np.argmin(perdidas_lineal))])
    n = len(muestras)
    w_shrunk = (n * w_crudo + N_PRIOR * W_PRIOR) / (n + N_PRIOR)
    w_recomendado = min(max(w_shrunk, LIMITES[0]), LIMITES[1])
    return {
        "n": n, "w_crudo": w_crudo, "w_shrunk": w_shrunk, "w_recomendado": w_recomendado,
        "logloss_lineal": min(perdidas_lineal),
        "logloss_geometrico": min(_logloss(muestras, w, True) for w in rejilla),
        "logloss_mercado": _logloss(muestras, 0.0, False),
    }
