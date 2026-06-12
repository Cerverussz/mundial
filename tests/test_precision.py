import pytest

from mundial.modelo import precision
from mundial.persistencia import bd, esquema


def test_brier_y_rps_casos_conocidos():
    # Predicción perfecta del triunfo local
    assert precision.brier((1.0, 0.0, 0.0), 0) == pytest.approx(0.0)
    assert precision.rps((1.0, 0.0, 0.0), 0) == pytest.approx(0.0)
    # Uniforme contra triunfo local: valores clásicos
    uniforme = (1 / 3, 1 / 3, 1 / 3)
    assert precision.brier(uniforme, 0) == pytest.approx(2 / 3)
    assert precision.rps(uniforme, 0) == pytest.approx(5 / 18)
    # RPS castiga menos el error "cercano": empate predicho, ganó local
    p_empate = (0.1, 0.8, 0.1)
    p_visita = (0.1, 0.1, 0.8)
    assert precision.rps(p_empate, 0) < precision.rps(p_visita, 0)


def test_evaluar_usa_ultima_prediccion_antes_del_kickoff(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.execute(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
           goles_local, goles_visitante)
           VALUES (1, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa', 'FINISHED', 2, 0)"""
    )
    base = dict(
        p_local_modelo=0.8, p_empate_modelo=0.14, p_visitante_modelo=0.06,
        p_local_mercado=0.68, p_empate_mercado=0.21, p_visitante_mercado=0.11,
    )
    for creado_en, p_local in [
        ("2026-06-11T09:00:00+00:00", 0.70),
        ("2026-06-11T18:00:00+00:00", 0.73),   # esta es la última antes del kickoff
        ("2026-06-11T22:00:00+00:00", 0.99),   # posterior al partido: debe ignorarse
    ]:
        conexion.execute(
            """INSERT INTO predicciones
               (partido_id, creado_en, marcador, p_local, p_empate, p_visitante,
                p_local_modelo, p_empate_modelo, p_visitante_modelo,
                p_local_mercado, p_empate_mercado, p_visitante_mercado)
               VALUES (1, ?, '2-0', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (creado_en, p_local, (1 - p_local) * 0.6, (1 - p_local) * 0.4,
             base["p_local_modelo"], base["p_empate_modelo"], base["p_visitante_modelo"],
             base["p_local_mercado"], base["p_empate_mercado"], base["p_visitante_mercado"]),
        )
    conexion.commit()
    informe = precision.evaluar(conexion)
    assert informe["n"] == 1
    fila = informe["partidos"][0]
    assert fila["p_local"] == pytest.approx(0.73)
    assert fila["resultado"] == "local"
    assert fila["acerto_marcador"] is True
    assert informe["blend"]["brier"] == pytest.approx(precision.brier(
        (0.73, 0.27 * 0.6, 0.27 * 0.4), 0))
    assert informe["modelo"]["rps"] < informe["mercado"]["rps"]  # modelo estaba más seguro


def test_logloss_en_evaluar(tmp_path):
    import math

    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.execute(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
           goles_local, goles_visitante)
           VALUES (1, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa', 'FINISHED', 2, 0)"""
    )
    conexion.execute(
        """INSERT INTO predicciones (partido_id, creado_en, marcador,
           p_local, p_empate, p_visitante,
           p_local_modelo, p_empate_modelo, p_visitante_modelo,
           p_local_mercado, p_empate_mercado, p_visitante_mercado)
           VALUES (1, '2026-06-11T18:00:00+00:00', '2-0', 0.73, 0.18, 0.09,
                   0.8, 0.14, 0.06, 0.68, 0.21, 0.11)"""
    )
    conexion.commit()
    informe = precision.evaluar(conexion)
    assert informe["blend"]["logloss"] == pytest.approx(-math.log(0.73), rel=1e-6)


def test_evaluar_sin_partidos_terminados(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    informe = precision.evaluar(conexion)
    assert informe["n"] == 0
