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


def test_esquema_v3_tablas_y_migracion(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    tablas = {f["name"] for f in conexion.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cuotas_mercado", "archivos_cargados_mercados", "apuestas", "xg", "tiros",
            "resultados_wc", "config"} <= tablas
    columnas = {f["name"] for f in conexion.execute("PRAGMA table_info(predicciones)")}
    assert "mercados_json" in columnas
    esquema.crear(conexion)  # idempotente también con la migración
