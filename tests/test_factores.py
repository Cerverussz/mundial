from datetime import date

from mundial.factores import contexto, forma, h2h
from mundial.modelo.dixon_coles import Ajuste
from mundial.persistencia import bd, esquema


def ajuste_prueba():
    equipos = ["AA", "BB"]
    return Ajuste(
        equipos=equipos,
        ataque={"AA": 0.3, "BB": -0.2},
        defensa={"AA": 0.2, "BB": -0.1},
        mu=0.15,
        ventaja_local=0.25,
        rho=-0.05,
        n_partidos=100,
        log_verosimilitud=-1.0,
    )


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    return conexion


def insertar_resultados(conexion, filas):
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas
    )
    conexion.commit()


def test_forma_neutral_con_pocos_datos(tmp_path):
    conexion = preparar_bd(tmp_path)
    factor = forma.factor_forma(conexion, "AA", date(2026, 6, 11), ajuste_prueba())
    assert factor.ataque == 1.0 and factor.defensa == 1.0
    assert "insuficiente" in factor.detalle.lower()


def test_forma_buena_racha_sube_ataque(tmp_path):
    conexion = preparar_bd(tmp_path)
    filas = [
        (f"2026-0{m}-01", "AA", "BB", 4, 0, "Amistoso", "X", "Y", 1) for m in range(1, 6)
    ] + [(f"2025-1{m}-01", "BB", "AA", 0, 3, "Amistoso", "X", "Y", 1) for m in range(0, 3)]
    insertar_resultados(conexion, filas)
    factor = forma.factor_forma(conexion, "AA", date(2026, 6, 11), ajuste_prueba())
    assert 1.0 < factor.ataque <= 1.15
    assert 1.0 < factor.defensa <= 1.15  # no recibió goles


def test_forma_acotada(tmp_path):
    conexion = preparar_bd(tmp_path)
    filas = [
        (f"2026-0{m}-01", "AA", "BB", 9, 9, "Amistoso", "X", "Y", 1) for m in range(1, 6)
    ]
    insertar_resultados(conexion, filas)
    factor = forma.factor_forma(conexion, "AA", date(2026, 6, 11), ajuste_prueba())
    assert factor.ataque == 1.15
    assert factor.defensa == 0.85


def test_altitud_castiga_no_acostumbrados():
    assert contexto.factor_altitud("South Africa", 2240) == 0.94
    assert contexto.factor_altitud("Mexico", 2240) == 1.0
    assert contexto.factor_altitud("South Africa", 1700) == 0.97
    assert contexto.factor_altitud("South Africa", 100) == 1.0
    assert contexto.factor_altitud("South Africa", None) == 1.0


def test_descanso_corto_castiga(tmp_path):
    conexion = preparar_bd(tmp_path)
    conexion.executemany(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, estado, goles_local, goles_visitante)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (1, "2026-06-09T19:00:00Z", "AA", "CC", "FINISHED", 1, 0),
            (2, "2026-06-20T19:00:00Z", "BB", "CC", "FINISHED", 1, 0),
        ],
    )
    conexion.commit()
    assert contexto.factor_descanso(conexion, "AA", "2026-06-11T19:00:00Z") == 0.97
    assert contexto.factor_descanso(conexion, "BB", "2026-06-11T19:00:00Z") == 1.0


def test_clima_calor():
    assert contexto.factor_clima(34) == 0.97
    assert contexto.factor_clima(21) == 1.0
    assert contexto.factor_clima(None) == 1.0


def test_h2h_acotado(tmp_path):
    conexion = preparar_bd(tmp_path)
    filas = [
        (f"202{a}-03-01", "AA", "BB", 5, 0, "Amistoso", "X", "Y", 1) for a in range(0, 6)
    ]
    insertar_resultados(conexion, filas)
    factor_local, factor_visitante = h2h.factor_h2h(conexion, "AA", "BB", date(2026, 6, 11))
    assert factor_local == 1.04
    assert factor_visitante == 0.96


def test_h2h_sin_historia(tmp_path):
    conexion = preparar_bd(tmp_path)
    factor_local, factor_visitante = h2h.factor_h2h(conexion, "AA", "BB", date(2026, 6, 11))
    assert factor_local == 1.0 and factor_visitante == 1.0
