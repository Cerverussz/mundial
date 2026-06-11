import pytest

from mundial.factores import mercado


def test_proporcional_sin_margen_es_identidad():
    cuotas = {"local": 2.0, "empate": 4.0, "visitante": 4.0}
    p = mercado.quitar_margen_proporcional(cuotas)
    assert p["local"] == pytest.approx(0.5)
    assert p["empate"] == pytest.approx(0.25)
    assert sum(p.values()) == pytest.approx(1.0)


def test_proporcional_normaliza_margen():
    cuotas = {"local": 1.8, "empate": 3.6, "visitante": 7.2}
    p = mercado.quitar_margen_proporcional(cuotas)
    assert sum(p.values()) == pytest.approx(1.0)
    assert p["local"] == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 3.6 + 1 / 7.2))


def test_shin_suma_uno_y_encoge_longshots():
    cuotas = {"local": 1.5, "empate": 4.2, "visitante": 8.0}
    proporcional = mercado.quitar_margen_proporcional(cuotas)
    shin = mercado.quitar_margen_shin(cuotas)
    assert sum(shin.values()) == pytest.approx(1.0, abs=1e-6)
    assert shin["visitante"] < proporcional["visitante"]
    assert shin["local"] > proporcional["local"]


def test_shin_sin_margen_devuelve_justas():
    cuotas = {"local": 2.0, "empate": 4.0, "visitante": 4.0}
    shin = mercado.quitar_margen_shin(cuotas)
    assert shin["local"] == pytest.approx(0.5, abs=1e-4)


def test_consenso_mediana_resiste_casa_loca():
    filas = [
        ("pinnacle", 1.5, 4.2, 8.0),
        ("bet365", 1.52, 4.1, 7.8),
        ("rara", 3.0, 3.0, 3.0),
        ("consensus", 1.5, 4.2, 8.0),
    ]
    p, n_casas = mercado.consenso(filas)
    assert n_casas == 3  # excluye la casa sintética "consensus"
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-6)
    assert p["local"] > 0.55  # la mediana ignora a la casa rara
