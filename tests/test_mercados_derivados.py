import numpy as np
import pytest

from mundial.modelo import mercados, prediccion


@pytest.fixture
def matriz():
    return prediccion.matriz_marcadores(1.5, 1.1, rho=-0.06)


def test_over_under_semientera_suman_uno(matriz):
    over = mercados.prob_over(matriz, 2.5)
    under = mercados.prob_under(matriz, 2.5)
    assert over + under == pytest.approx(1.0)
    assert 0.3 < over < 0.7


def test_total_linea_entera_tiene_push(matriz):
    r = mercados.resultado_total(matriz, 3.0, "over")
    assert r["p_gana"] + r["p_push"] + r["p_pierde"] == pytest.approx(1.0)
    assert r["p_push"] > 0.05  # P(total=3) no es despreciable
    justa = mercados.cuota_justa_total(matriz, 3.0, "over")
    assert justa == pytest.approx(1.0 + r["p_pierde"] / r["p_gana"])


def test_total_linea_cuarto_promedia(matriz):
    r225 = mercados.resultado_total(matriz, 2.25, "over")
    o = 1.9
    assert mercados.ev_total(matriz, 2.25, "over", o) == pytest.approx(
        0.5 * mercados.ev_total(matriz, 2.0, "over", o)
        + 0.5 * mercados.ev_total(matriz, 2.5, "over", o)
    )
    assert r225["p_media_gana"] == pytest.approx(0.0)  # over 2.25: media solo al perder en 2


def test_btts_desde_matriz(matriz):
    p = mercados.prob_btts(matriz)
    assert p == pytest.approx(matriz[1:, 1:].sum())


def test_ah_media_linea_es_prob_simple(matriz):
    r = mercados.resultado_ah(matriz, -0.5)
    indices = np.indices(matriz.shape)
    p_gana_por_1 = matriz[indices[0] > indices[1]].sum()
    assert r["p_gana"] == pytest.approx(p_gana_por_1)
    assert r["p_push"] == 0.0


def test_ah_dnb_es_handicap_cero(matriz):
    r = mercados.resultado_ah(matriz, 0.0)
    assert r["p_push"] == pytest.approx(np.trace(matriz))
    justa_local, justa_visita = mercados.cuotas_justas_dnb(matriz)
    assert justa_local == pytest.approx(1.0 + r["p_pierde"] / r["p_gana"])


def test_ah_cuarto_negativo(matriz):
    # h=-0.25: D>=1 gana todo; D=0 pierde media; D<=-1 pierde todo
    r = mercados.resultado_ah(matriz, -0.25)
    assert r["p_media_pierde"] == pytest.approx(np.trace(matriz))
    assert r["p_gana"] + r["p_media_pierde"] + r["p_pierde"] == pytest.approx(1.0)


def test_liquidar_ah_casos():
    # local -1.5, ganó 2-0 → diferencia 2 → gana completa
    assert mercados.liquidar_ah(2, -1.5, 1.9) == ("ganada", pytest.approx(0.9))
    # local -1.0, ganó 1-0 → push
    assert mercados.liquidar_ah(1, -1.0, 1.9) == ("push", 0.0)
    # local -0.25, empató → media perdida
    estado, retorno = mercados.liquidar_ah(0, -0.25, 1.9)
    assert estado == "media_perdida" and retorno == pytest.approx(-0.5)
    # local +0.25, empató → media ganada
    estado, retorno = mercados.liquidar_ah(0, 0.25, 1.9)
    assert estado == "media_ganada" and retorno == pytest.approx(0.45)
    # visitante: el llamador pasa la diferencia desde la perspectiva apostada
    assert mercados.liquidar_ah(-1, 0.5, 2.0) == ("perdida", -1.0)


def test_liquidar_total():
    assert mercados.liquidar_total(3, 2.5, "over", 1.8) == ("ganada", pytest.approx(0.8))
    assert mercados.liquidar_total(3, 3.0, "over", 1.8) == ("push", 0.0)
    assert mercados.liquidar_total(2, 2.25, "under", 1.8)[0] == "media_ganada"
    assert mercados.liquidar_total(2, 2.25, "over", 1.8)[0] == "media_perdida"


def test_liquidar_2way():
    assert mercados.liquidar_2way(True, 2.1) == ("ganada", pytest.approx(1.1))
    assert mercados.liquidar_2way(False, 2.1) == ("perdida", -1.0)
