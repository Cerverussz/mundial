import json
from pathlib import Path

import httpx

from mundial.ingesta import actualizar
from mundial.ingesta.fifa import ClienteFifa
from mundial.persistencia import bd, esquema

FIXTURES = Path(__file__).parent / "fixtures"


class FdFalso:
    def partidos_mundial(self):
        return json.loads((FIXTURES / "fd_matches.json").read_text())["matches"]


class FdCaido:
    def partidos_mundial(self):
        raise RuntimeError("503")


class FifaFalso:
    def calendario(self):
        crudo = json.loads((FIXTURES / "fifa_calendar.json").read_text())
        transporte = httpx.MockTransport(lambda s: httpx.Response(200, json=crudo))
        return ClienteFifa(transporte=transporte).calendario()


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    return conexion


def test_sincroniza_partidos_y_enriquece_estadio(tmp_path):
    conexion = preparar_bd(tmp_path)
    mensajes = actualizar.sincronizar(
        conexion, cliente_fd=FdFalso(), cliente_fifa=FifaFalso(), cargar_historico=False
    )
    fila = conexion.execute("SELECT * FROM partidos WHERE id=537327").fetchone()
    assert fila["local"] == "Mexico"
    assert fila["estadio"] == "Mexico City Stadium"
    assert fila["fuente"] == "football-data"
    assert any("partidos" in m for m in mensajes)


def test_cascada_degrada_a_fifa(tmp_path):
    conexion = preparar_bd(tmp_path)
    mensajes = actualizar.sincronizar(
        conexion, cliente_fd=FdCaido(), cliente_fifa=FifaFalso(), cargar_historico=False
    )
    filas = conexion.execute("SELECT * FROM partidos").fetchall()
    assert len(filas) >= 1
    assert filas[0]["fuente"] == "fifa"
    assert any("ADVERTENCIA" in m for m in mensajes)


def test_completa_marcador_desde_fifa(tmp_path):
    """football-data puede traer FINISHED sin marcador; el calendario FIFA lo completa."""

    class FifaConMarcador(FifaFalso):
        def calendario(self):
            calendario = super().calendario()
            for c in calendario:
                if c["id_fifa"] == "400021443":
                    c["goles_local"], c["goles_visitante"] = 2, 0
            return calendario

    conexion = preparar_bd(tmp_path)
    actualizar.sincronizar(
        conexion, cliente_fd=FdFalso(), cliente_fifa=FifaConMarcador(), cargar_historico=False
    )
    fila = conexion.execute("SELECT * FROM partidos WHERE id=537327").fetchone()
    assert fila["goles_local"] == 2 and fila["goles_visitante"] == 0
    assert fila["estado"] == "FINISHED"


def test_canonico_aplica_mapeo():
    assert actualizar.canonico("Korea Republic") == "South Korea"
    assert actualizar.canonico("Mexico") == "Mexico"
