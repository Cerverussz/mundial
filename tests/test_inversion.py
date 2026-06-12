import pytest

from mundial.modelo import inversion, mercados, prediccion


def test_inversion_recupera_lambdas():
    lam, mu, rho = 1.7, 0.9, -0.06
    matriz = prediccion.matriz_marcadores(lam, mu, rho)
    r = mercados.resultado_ah(matriz, 0.0)
    p_dnb_local = r["p_gana"] / (r["p_gana"] + r["p_pierde"])
    p_over25 = mercados.prob_over(matriz, 2.5)
    lam_inv, mu_inv = inversion.invertir_lambdas(p_dnb_local, p_over25, rho)
    assert lam_inv == pytest.approx(lam, abs=1e-3)
    assert mu_inv == pytest.approx(mu, abs=1e-3)


def test_inversion_sin_convergencia_devuelve_none():
    assert inversion.invertir_lambdas(0.999, 0.001, -0.06) is None
