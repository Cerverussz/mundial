from mundial.ingesta import estaticos
from mundial.persistencia import bd, esquema


def test_cargar_estadios(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = estaticos.cargar_estadios(conexion)
    assert n == 16
    azteca = conexion.execute(
        "SELECT * FROM estadios WHERE nombre='Mexico City Stadium'").fetchone()
    assert azteca["altitud_m"] == 2240
    assert azteca["tz"] == "America/Mexico_City"


def test_cargar_confederaciones(tmp_path):
    from mundial.ingesta.actualizar import canonico  # noqa: F401

    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = estaticos.cargar_confederaciones(conexion)
    assert n >= 130
    fila = conexion.execute(
        "SELECT confederacion FROM equipos WHERE nombre='Mexico'").fetchone()
    assert fila["confederacion"] == "CONCACAF"
    fila = conexion.execute(
        "SELECT confederacion FROM equipos WHERE nombre='Brazil'").fetchone()
    assert fila["confederacion"] == "CONMEBOL"
