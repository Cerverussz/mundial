import json
from datetime import datetime, timezone
from pathlib import Path

from mundial.ingesta import cargar_cuotas, snapshots
from mundial.persistencia import bd, esquema

FIXTURES = Path(__file__).parent / "fixtures"
MOMENTO = datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc)


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.execute(
        """INSERT INTO partidos(id, fecha_utc, local, visitante, fuente)
           VALUES (537327, '2026-06-11T19:00:00Z', 'Mexico', 'South Africa', 'football-data')"""
    )
    conexion.commit()
    return conexion


def escribir_snapshot_bsd(base):
    comparacion = json.loads((FIXTURES / "bsd_comparison.json").read_text())
    payload = {"eventos": [], "comparaciones": {"8287": comparacion}}
    snapshots.escribir_snapshot("bsd", payload, momento=MOMENTO, base=base)


def test_carga_bsd_y_vincula_evento(tmp_path):
    conexion = preparar_bd(tmp_path)
    escribir_snapshot_bsd(tmp_path / "snaps")
    n = cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps")
    assert n > 10
    filas = conexion.execute(
        "SELECT DISTINCT casa FROM cuotas WHERE partido_id=537327").fetchall()
    casas = {f["casa"] for f in filas}
    assert "pinnacle" in casas
    vinculo = conexion.execute("SELECT * FROM eventos_bsd WHERE partido_id=537327").fetchone()
    assert vinculo["evento_id"] == 8287


def test_carga_es_incremental(tmp_path):
    conexion = preparar_bd(tmp_path)
    escribir_snapshot_bsd(tmp_path / "snaps")
    cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps")
    assert cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps") == 0


def test_carga_mercados_desde_snapshot(tmp_path):
    conexion = preparar_bd(tmp_path)
    escribir_snapshot_bsd(tmp_path / "snaps")
    cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps")
    n = cargar_cuotas.cargar_mercados(conexion, base=tmp_path / "snaps")
    assert n > 50
    fila = conexion.execute(
        """SELECT * FROM cuotas_mercado WHERE partido_id=537327 AND mercado='over_under_25'
           AND casa='pinnacle' AND seleccion='over@2.5'"""
    ).fetchone()
    assert fila is not None and fila["cuota"] > 1.0
    selecciones_btts = {f["seleccion"] for f in conexion.execute(
        "SELECT DISTINCT seleccion FROM cuotas_mercado WHERE mercado='btts'")}
    assert selecciones_btts == {"yes", "no"}
    # segunda corrida: idempotente
    assert cargar_cuotas.cargar_mercados(conexion, base=tmp_path / "snaps") == 0


def test_carga_odds_api(tmp_path):
    conexion = preparar_bd(tmp_path)
    eventos = json.loads((FIXTURES / "odds_api_h2h.json").read_text())
    snapshots.escribir_snapshot("odds-api", eventos, momento=MOMENTO, base=tmp_path / "snaps")
    cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps")
    fila = conexion.execute(
        """SELECT * FROM cuotas WHERE partido_id=537327 AND fuente='odds-api'
           AND casa='pinnacle'"""
    ).fetchone()
    assert fila is not None
    assert fila["local"] > 1.0 and fila["empate"] > 1.0 and fila["visitante"] > 1.0
