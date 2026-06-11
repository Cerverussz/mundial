from mundial.persistencia import bd, esquema


def test_conectar_crea_archivo(tmp_path):
    conexion = bd.conectar(tmp_path / "x" / "mundial.db")
    conexion.execute("CREATE TABLE t(a)")
    assert (tmp_path / "x" / "mundial.db").exists()


def test_esquema_idempotente(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    esquema.crear(conexion)
    tablas = {f["name"] for f in conexion.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"equipos", "estadios", "partidos", "resultados_historicos",
            "ratings", "modelo_meta"} <= tablas
