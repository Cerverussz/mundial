"""Dixon-Coles ponderado en el tiempo para selecciones (corrección ρ de marcadores bajos)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import minimize

VIDA_MEDIA_DIAS = 730.0
PENALIZACION_L2 = 1e-3
VERSION = "dc-1.0"


def pesos_decaimiento(fechas, referencia: date, vida_media: float = VIDA_MEDIA_DIAS):
    dias = np.array([(referencia - f).days for f in fechas], dtype=float)
    return np.exp(-np.log(2.0) / vida_media * dias)


@dataclass
class Datos:
    equipos: list[str]
    il: np.ndarray
    iv: np.ndarray
    x: np.ndarray
    y: np.ndarray
    neutral: np.ndarray
    pesos: np.ndarray


@dataclass
class Ajuste:
    equipos: list[str]
    ataque: dict[str, float]
    defensa: dict[str, float]
    mu: float
    ventaja_local: float
    rho: float
    n_partidos: int
    log_verosimilitud: float
    version: str = VERSION


def _preparar(partidos, referencia: date, partidos_minimos: int = 5,
              vida_media: float = VIDA_MEDIA_DIAS) -> Datos:
    """partidos: lista de (fecha, local, visitante, goles_local, goles_visitante, neutral)."""
    conteo: dict[str, int] = {}
    for _, local, visitante, *_ in partidos:
        conteo[local] = conteo.get(local, 0) + 1
        conteo[visitante] = conteo.get(visitante, 0) + 1
    equipos = sorted(e for e, n in conteo.items() if n >= partidos_minimos)
    indice = {e: k for k, e in enumerate(equipos)}
    filas = [p for p in partidos if p[1] in indice and p[2] in indice]
    fechas = np.array([p[0] for p in filas])
    return Datos(
        equipos=equipos,
        il=np.array([indice[p[1]] for p in filas]),
        iv=np.array([indice[p[2]] for p in filas]),
        x=np.array([p[3] for p in filas], dtype=float),
        y=np.array([p[4] for p in filas], dtype=float),
        neutral=np.array([1.0 if p[5] else 0.0 for p in filas]),
        pesos=pesos_decaimiento(fechas, referencia, vida_media),
    )


def _tau(x, y, lam, m, rho):
    """τ de Dixon-Coles y derivadas parciales (∂τ/∂λ, ∂τ/∂m, ∂τ/∂ρ), vectorizado."""
    tau = np.ones_like(lam)
    dl = np.zeros_like(lam)
    dm = np.zeros_like(lam)
    dr = np.zeros_like(lam)
    c00 = (x == 0) & (y == 0)
    c01 = (x == 0) & (y == 1)
    c10 = (x == 1) & (y == 0)
    c11 = (x == 1) & (y == 1)
    tau[c00] = 1.0 - lam[c00] * m[c00] * rho
    dl[c00] = -m[c00] * rho
    dm[c00] = -lam[c00] * rho
    dr[c00] = -lam[c00] * m[c00]
    tau[c01] = 1.0 + lam[c01] * rho
    dl[c01] = rho
    dr[c01] = lam[c01]
    tau[c10] = 1.0 + m[c10] * rho
    dm[c10] = rho
    dr[c10] = m[c10]
    tau[c11] = 1.0 - rho
    dr[c11] = -1.0
    return np.clip(tau, 1e-10, None), dl, dm, dr


def _objetivo(theta, datos: Datos):
    n = len(datos.equipos)
    mu, ventaja, rho = theta[0], theta[1], theta[2]
    ataque = theta[3 : 3 + n]
    defensa = theta[3 + n :]
    loglam = mu + ventaja * (1.0 - datos.neutral) + ataque[datos.il] - defensa[datos.iv]
    logm = mu + ataque[datos.iv] - defensa[datos.il]
    lam, m = np.exp(loglam), np.exp(logm)
    tau, dl, dm, dr = _tau(datos.x, datos.y, lam, m, rho)
    logv = datos.pesos * (np.log(tau) + datos.x * loglam - lam + datos.y * logm - m)
    nll = -logv.sum() + PENALIZACION_L2 * (ataque @ ataque + defensa @ defensa)

    gx = datos.pesos * ((datos.x - lam) + dl * lam / tau)
    gy = datos.pesos * ((datos.y - m) + dm * m / tau)
    gradiente = np.zeros_like(theta)
    gradiente[0] = (gx + gy).sum()
    gradiente[1] = (gx * (1.0 - datos.neutral)).sum()
    gradiente[2] = (datos.pesos * dr / tau).sum()
    ga = np.zeros(n)
    gd = np.zeros(n)
    np.add.at(ga, datos.il, gx)
    np.add.at(ga, datos.iv, gy)
    np.add.at(gd, datos.iv, -gx)
    np.add.at(gd, datos.il, -gy)
    gradiente[3 : 3 + n] = ga - 2.0 * PENALIZACION_L2 * ataque
    gradiente[3 + n :] = gd - 2.0 * PENALIZACION_L2 * defensa
    return nll, -gradiente


def ajustar(partidos, referencia: date, partidos_minimos: int = 5,
            vida_media: float = VIDA_MEDIA_DIAS) -> Ajuste:
    datos = _preparar(partidos, referencia, partidos_minimos, vida_media)
    n = len(datos.equipos)
    theta0 = np.zeros(3 + 2 * n)
    theta0[0] = np.log(max(datos.x.mean(), 0.1))
    limites = [(None, None), (None, None), (-0.5, 0.5)] + [(None, None)] * (2 * n)
    resultado = minimize(
        _objetivo, theta0, args=(datos,), jac=True, method="L-BFGS-B",
        bounds=limites, options={"maxiter": 500},
    )
    mu, ventaja, rho = resultado.x[0], resultado.x[1], resultado.x[2]
    ataque = resultado.x[3 : 3 + n]
    defensa = resultado.x[3 + n :]
    mu += ataque.mean() - defensa.mean()
    ataque -= ataque.mean()
    defensa -= defensa.mean()
    return Ajuste(
        equipos=datos.equipos,
        ataque=dict(zip(datos.equipos, ataque)),
        defensa=dict(zip(datos.equipos, defensa)),
        mu=float(mu),
        ventaja_local=float(ventaja),
        rho=float(rho),
        n_partidos=len(datos.x),
        log_verosimilitud=float(-resultado.fun),
    )
