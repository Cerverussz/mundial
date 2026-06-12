"""Inversión de las λ implícitas del mercado desde DNB y Over 2.5 devigados."""
from __future__ import annotations

import numpy as np

from mundial.modelo import mercados, prediccion

LIMITES = (0.05, 6.0)


def _objetivo(lam: float, mu: float, rho: float, p_dnb: float, p_over: float) -> np.ndarray:
    matriz = prediccion.matriz_marcadores(lam, mu, rho)
    r = mercados.resultado_ah(matriz, 0.0)
    dnb = r["p_gana"] / (r["p_gana"] + r["p_pierde"])
    return np.array([dnb - p_dnb, mercados.prob_over(matriz, 2.5) - p_over])


def invertir_lambdas(
    p_dnb_local: float, p_over25: float, rho: float,
    lam0: float = 1.3, mu0: float = 1.1, iteraciones: int = 40,
) -> tuple[float, float] | None:
    x = np.array([lam0, mu0])
    paso = 1e-5
    for _ in range(iteraciones):
        f = _objetivo(x[0], x[1], rho, p_dnb_local, p_over25)
        if np.max(np.abs(f)) < 1e-9:
            return float(x[0]), float(x[1])
        jacobiano = np.empty((2, 2))
        for j in range(2):
            d = x.copy()
            d[j] += paso
            jacobiano[:, j] = (_objetivo(d[0], d[1], rho, p_dnb_local, p_over25) - f) / paso
        try:
            x = x - np.linalg.solve(jacobiano, f)
        except np.linalg.LinAlgError:
            return None
        x = np.clip(x, LIMITES[0], LIMITES[1])
    f = _objetivo(x[0], x[1], rho, p_dnb_local, p_over25)
    if np.max(np.abs(f)) < 1e-6:
        return float(x[0]), float(x[1])
    return None
