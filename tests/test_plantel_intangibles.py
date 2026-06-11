from mundial.factores import intangibles, plantel
from mundial.persistencia import bd, esquema


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    return conexion


def insertar_bajas(conexion, filas):
    conexion.executemany("INSERT OR REPLACE INTO bajas VALUES (?,?,?,?,?,?,?)", filas)
    conexion.commit()


def test_plantel_sin_bajas(tmp_path):
    conexion = preparar_bd(tmp_path)
    factor = plantel.factor_plantel(conexion, 1, "Mexico")
    assert factor.propio == 1.0
    assert factor.detalle is None


def test_plantel_titular_pesa_mas_que_suplente(tmp_path):
    conexion = preparar_bd(tmp_path)
    insertar_bajas(conexion, [
        (1, "Mexico", "Estrella", "injured", "Muscle", 0.65, "2026-06-11T09:00:00+00:00"),
        (2, "Mexico", "Suplente", "injured", "Knock", None, "2026-06-11T09:00:00+00:00"),
    ])
    con_estrella = plantel.factor_plantel(conexion, 1, "Mexico")
    con_suplente = plantel.factor_plantel(conexion, 2, "Mexico")
    assert con_estrella.propio < con_suplente.propio < 1.0
    assert "Estrella" in con_estrella.detalle


def test_plantel_duda_pesa_menos_y_esta_acotado(tmp_path):
    conexion = preparar_bd(tmp_path)
    insertar_bajas(conexion, [
        (1, "Mexico", "Duda", "doubtful", None, 0.6, "2026-06-11T09:00:00+00:00"),
    ] + [
        (1, "Mexico", f"Baja{i}", "injured", None, 0.9, "2026-06-11T09:00:00+00:00")
        for i in range(8)
    ])
    factor = plantel.factor_plantel(conexion, 1, "Mexico")
    assert factor.propio == 0.88  # tope inferior


def test_plantel_usa_solo_captura_mas_reciente(tmp_path):
    conexion = preparar_bd(tmp_path)
    insertar_bajas(conexion, [
        (1, "Mexico", "Recuperado", "injured", None, 0.6, "2026-06-10T09:00:00+00:00"),
    ])
    insertar_bajas(conexion, [
        (1, "Mexico", "Nuevo", "injured", None, 0.6, "2026-06-11T09:00:00+00:00"),
    ])
    factor = plantel.factor_plantel(conexion, 1, "Mexico")
    assert "Nuevo" in factor.detalle and "Recuperado" not in factor.detalle


def test_intangibles_fases():
    assert intangibles.factor_fase("GROUP_STAGE", jornada=1) == (1.0, None)
    factor, razon = intangibles.factor_fase("GROUP_STAGE", jornada=3)
    assert factor == 0.99 and "rotación" in razon
    assert intangibles.factor_fase("LAST_16", jornada=None)[0] == 0.96
    assert intangibles.factor_fase("FINAL", jornada=None)[0] == 0.95
