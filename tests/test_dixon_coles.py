from datetime import date, timedelta

import numpy as np
from scipy.optimize import approx_fprime

from mundial.modelo import dixon_coles as dc


def test_pesos_decaimiento_vida_media():
    hoy = date(2026, 6, 11)
    fechas = np.array([hoy, hoy - timedelta(days=730), hoy - timedelta(days=1460)])
    pesos = dc.pesos_decaimiento(fechas, hoy)
    assert pesos[0] == 1.0
    assert abs(pesos[1] - 0.5) < 1e-9
    assert abs(pesos[2] - 0.25) < 1e-9


def _partidos_sinteticos(n_equipos=8, n_partidos=600, semilla=42):
    rng = np.random.default_rng(semilla)
    equipos = [f"EQ{i}" for i in range(n_equipos)]
    ataque = rng.normal(0, 0.3, n_equipos)
    defensa = rng.normal(0, 0.3, n_equipos)
    mu, ventaja = 0.15, 0.25
    hoy = date(2026, 6, 11)
    partidos = []
    for _ in range(n_partidos):
        i, j = rng.choice(n_equipos, 2, replace=False)
        neutral = bool(rng.random() < 0.5)
        lam = np.exp(mu + (0 if neutral else ventaja) + ataque[i] - defensa[j])
        m = np.exp(mu + ataque[j] - defensa[i])
        fecha = hoy - timedelta(days=int(rng.integers(0, 720)))
        partidos.append(
            (fecha, equipos[i], equipos[j], rng.poisson(lam), rng.poisson(m), neutral)
        )
    return partidos, equipos, ataque, mu, ventaja


def test_gradiente_coincide_con_diferencias_finitas():
    partidos, *_ = _partidos_sinteticos(n_equipos=4, n_partidos=40)
    datos = dc._preparar(partidos, date(2026, 6, 11), partidos_minimos=1)
    theta = np.concatenate([[0.1, 0.2, 0.05], np.linspace(-0.2, 0.2, 2 * len(datos.equipos))])
    _, gradiente = dc._objetivo(theta, datos)
    numerico = approx_fprime(theta, lambda t: dc._objetivo(t, datos)[0], 1e-6)
    assert np.allclose(gradiente, numerico, rtol=1e-3, atol=1e-4)


def test_recupera_parametros_sinteticos():
    partidos, equipos, ataque_real, mu_real, ventaja_real = _partidos_sinteticos()
    ajuste = dc.ajustar(partidos, date(2026, 6, 11))
    ajustado = np.array([ajuste.ataque[e] for e in equipos])
    correlacion = np.corrcoef(ataque_real - ataque_real.mean(), ajustado)[0, 1]
    assert correlacion > 0.85
    assert abs(ajuste.ventaja_local - ventaja_real) < 0.15
    assert abs(ajuste.rho) < 0.1
