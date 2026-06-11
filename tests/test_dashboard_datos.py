import json

from mundial.dashboard import datos
from mundial.persistencia import bd, esquema


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.execute(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, fase, grupo, jornada, estadio)
           VALUES (1, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa',
                   'GROUP_STAGE', 'GROUP_A', 1, 'Mexico City Stadium')"""
    )
    for momento, cuota_local in [("2026-06-11T06:00:00+00:00", 1.50),
                                 ("2026-06-11T09:00:00+00:00", 1.45)]:
        for casa in ("pinnacle", "bet365"):
            conexion.execute(
                "INSERT INTO cuotas VALUES (1, ?, 'bsd', ?, '1x2', ?, 4.3, 7.6)",
                (momento, casa, cuota_local),
            )
    conexion.execute(
        """INSERT INTO predicciones
           (partido_id, creado_en, marcador, p_local, p_empate, p_visitante,
            p_local_modelo, p_empate_modelo, p_visitante_modelo,
            p_local_mercado, p_empate_mercado, p_visitante_mercado,
            matriz_json, confianza, razones_confianza, factores_json, valor_flags)
           VALUES (1, '2026-06-11T10:00:00+00:00', '2-0', 0.72, 0.18, 0.10,
                   0.80, 0.14, 0.06, 0.68, 0.21, 0.11,
                   ?, 'Alta', '[]', '[]', '[]')""",
        (json.dumps([[0.1] * 3] * 3),),
    )
    conexion.commit()
    return conexion


def test_partidos_proximos(tmp_path):
    conexion = preparar_bd(tmp_path)
    filas = datos.partidos_proximos(conexion, desde="2026-06-11", dias=3)
    assert len(filas) == 1
    assert filas[0]["local"] == "Mexico"


def test_ultima_prediccion_parsea_json(tmp_path):
    conexion = preparar_bd(tmp_path)
    p = datos.ultima_prediccion(conexion, 1)
    assert p["marcador"] == "2-0"
    assert isinstance(p["matriz"], list)
    assert p["p_local"] == 0.72


def test_evolucion_consenso_ordenada(tmp_path):
    conexion = preparar_bd(tmp_path)
    serie = datos.evolucion_consenso(conexion, 1)
    assert len(serie) == 2
    assert serie[0]["capturado_en"] < serie[1]["capturado_en"]
    assert serie[1]["local"] > serie[0]["local"]  # la cuota bajó ⇒ probabilidad subió


def test_divergencias(tmp_path):
    conexion = preparar_bd(tmp_path)
    filas = datos.divergencias(conexion)
    assert len(filas) == 1
    assert filas[0]["divergencia"] > 0.1
