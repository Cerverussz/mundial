import numpy as np
import pytest

from mundial.modelo import confianza, prediccion
from mundial.persistencia import bd, esquema


def test_matriz_suma_uno_y_rho_mueve_marcadores_bajos():
    matriz_sin = prediccion.matriz_marcadores(1.4, 1.1, rho=0.0)
    matriz_con = prediccion.matriz_marcadores(1.4, 1.1, rho=-0.1)
    assert matriz_sin.sum() == pytest.approx(1.0)
    assert matriz_con.sum() == pytest.approx(1.0)
    assert matriz_con[0, 0] > matriz_sin[0, 0]  # rho negativo infla 0-0
    assert matriz_con[1, 1] > matriz_sin[1, 1]


def test_matriz_11x11_normalizada():
    matriz = prediccion.matriz_marcadores(3.4, 2.8, rho=-0.06)
    assert matriz.shape == (11, 11)
    assert matriz.sum() == pytest.approx(1.0)


def test_prob_1x2_consistente():
    matriz = prediccion.matriz_marcadores(2.0, 0.8, rho=-0.05)
    p_local, p_empate, p_visitante = prediccion.prob_1x2(matriz)
    assert p_local + p_empate + p_visitante == pytest.approx(1.0)
    assert p_local > p_visitante  # lambda local mucho mayor


def test_reescalar_matriz_a_blend():
    matriz = prediccion.matriz_marcadores(1.5, 1.0, rho=-0.05)
    objetivo = {"local": 0.6, "empate": 0.25, "visitante": 0.15}
    nueva = prediccion.reescalar_matriz(matriz, objetivo)
    p_local, p_empate, p_visitante = prediccion.prob_1x2(nueva)
    assert p_local == pytest.approx(0.6, abs=1e-9)
    assert p_empate == pytest.approx(0.25, abs=1e-9)


def test_marcadores_top():
    matriz = prediccion.matriz_marcadores(1.4, 1.1, rho=-0.05)
    top = prediccion.marcadores_top(matriz, 3)
    assert len(top) == 3
    assert top[0][2] >= top[1][2] >= top[2][2]


def test_confianza_niveles():
    nivel, razones = confianza.calcular(
        divergencia=0.02, edad_cuotas_h=0.5, n_casas=14,
        forma_ok_local=True, forma_ok_visitante=True,
        partidos_local=30, partidos_visitante=30, bajas_info=True,
    )
    assert nivel == "Alta" and razones == []
    nivel, razones = confianza.calcular(
        divergencia=0.20, edad_cuotas_h=None, n_casas=0,
        forma_ok_local=False, forma_ok_visitante=True,
        partidos_local=4, partidos_visitante=30, bajas_info=False,
    )
    assert nivel == "Baja" and len(razones) >= 3


def preparar_bd_completa(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.execute(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, fase, grupo, jornada, estadio, estado)
           VALUES (537327, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa',
                   'GROUP_STAGE', 'GROUP_A', 1, 'Mexico City Stadium', 'TIMED')"""
    )
    conexion.execute(
        """INSERT INTO estadios VALUES ('Mexico City Stadium','Mexico City','Mexico',
           2240, 19.3, -99.15, 'America/Mexico_City')"""
    )
    for equipo, ataque, defensa in [("Mexico", 0.5, 0.3), ("South Africa", -0.1, -0.2)]:
        conexion.execute(
            "INSERT INTO ratings VALUES (?, '2026-06-11', ?, ?)", (equipo, ataque, defensa)
        )
    conexion.execute(
        """INSERT INTO modelo_meta VALUES ('2026-06-11', 0.1, 0.23, -0.06, 9000, 200,
           -100.0, 'dc-1.0')"""
    )
    for casa, cl, ce, cv in [("pinnacle", 1.45, 4.3, 7.6), ("bet365", 1.47, 4.2, 7.5)]:
        conexion.execute(
            """INSERT INTO cuotas VALUES (537327, '2026-06-11T09:00:00+00:00', 'bsd', ?,
               '1x2', ?, ?, ?)""",
            (casa, cl, ce, cv),
        )
    conexion.commit()
    return conexion


def test_predecir_integra_todo(tmp_path):
    conexion = preparar_bd_completa(tmp_path)
    resultado = prediccion.predecir(conexion, 537327)
    assert resultado.p_final["local"] + resultado.p_final["empate"] + resultado.p_final[
        "visitante"
    ] == pytest.approx(1.0, abs=1e-6)
    assert resultado.p_final["local"] > 0.5  # favorito claro modelo + mercado
    assert resultado.marcador[0] >= 1  # México anota
    assert resultado.confianza in ("Alta", "Media", "Baja")
    assert any("altitud" in f["nombre"] for f in resultado.factores)
    fila = conexion.execute("SELECT * FROM predicciones WHERE partido_id=537327").fetchone()
    assert fila is not None
    assert resultado.cambios is None  # primera predicción

    segundo = prediccion.predecir(conexion, 537327)
    assert segundo.cambios is not None  # ahora hay una anterior para comparar


def test_exportar_e_importar_predicciones(tmp_path):
    conexion = preparar_bd_completa(tmp_path)
    directorio = tmp_path / "exportadas"
    prediccion.predecir(conexion, 537327, dir_exportacion=directorio)
    assert len(list(directorio.glob("*.jsonl"))) == 1

    otra = bd.conectar(tmp_path / "otra.db")
    esquema.crear(otra)
    assert prediccion.cargar_exportadas(otra, directorio) == 1
    assert prediccion.cargar_exportadas(otra, directorio) == 0  # idempotente
    fila = otra.execute("SELECT * FROM predicciones").fetchone()
    assert fila["partido_id"] == 537327 and fila["confianza"] in ("Alta", "Media", "Baja")
