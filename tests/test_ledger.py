import pytest

from mundial.modelo import ledger
from mundial.persistencia import bd, esquema


def preparar(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.executescript("""
        INSERT INTO partidos(id, fecha_utc, local, visitante, estado)
        VALUES (1, '2026-06-13T19:00:00Z', 'Mexico', 'South Africa', 'TIMED');
        INSERT INTO cuotas_mercado VALUES
          (1,'2026-06-13T17:00:00+00:00','bsd','pinnacle','over_under_25','over@2.5',2.10),
          (1,'2026-06-13T17:00:00+00:00','bsd','pinnacle','over_under_25','under@2.5',1.80),
          (1,'2026-06-13T17:00:00+00:00','bsd','bet365','over_under_25','over@2.5',2.15),
          (1,'2026-06-13T17:00:00+00:00','bsd','bet365','over_under_25','under@2.5',1.78),
          (1,'2026-06-13T18:50:00+00:00','bsd','pinnacle','over_under_25','over@2.5',1.95),
          (1,'2026-06-13T18:50:00+00:00','bsd','pinnacle','over_under_25','under@2.5',1.92);
    """)
    conexion.commit()
    return conexion


def test_abrir_apuesta_de_flag_y_no_duplicar(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "over_under_25", "seleccion": "over@2.5", "margen": 0.07, "sostenida": True}
    n = ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:30:00+00:00")
    assert n == 1
    assert ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:40:00+00:00") == 0
    fila = conexion.execute("SELECT * FROM apuestas").fetchone()
    assert fila["cuota"] == pytest.approx(2.15)  # mejor cuota real disponible
    assert fila["stake_kelly"] > 0


def test_liquidar_y_clv(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "over_under_25", "seleccion": "over@2.5", "margen": 0.07, "sostenida": True}
    ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:30:00+00:00")
    conexion.execute("UPDATE partidos SET goles_local=2, goles_visitante=1, estado='FINISHED'")
    conexion.commit()
    n = ledger.liquidar_pendientes(conexion)
    assert n == 1
    fila = conexion.execute("SELECT * FROM apuestas").fetchone()
    assert fila["estado"] == "ganada"
    assert fila["retorno_flat"] == pytest.approx(1.15)
    assert fila["clv"] is not None and fila["clv"] > 0  # tomamos 2.15, cierre justo ~1.935
    resumen = ledger.resumen(conexion)
    assert resumen["n"] == 1 and resumen["pnl_flat"] == pytest.approx(1.15)


def test_no_abre_sin_cuota_real(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "btts", "seleccion": "yes", "margen": 0.08, "sostenida": True}
    assert ledger.abrir_apuestas(conexion, 1, [flag], {"yes": 0.6}, "2026-06-13T17:30:00+00:00") == 0
