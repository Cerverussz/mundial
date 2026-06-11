import json
from pathlib import Path

import httpx

from mundial.ingesta.fifa import ClienteFifa
from mundial.ingesta.football_data import ClienteFootballData

FIXTURES = Path(__file__).parent / "fixtures"


def test_football_data_partidos():
    pagina = json.loads((FIXTURES / "fd_matches.json").read_text())

    def responder(solicitud):
        assert solicitud.headers["X-Auth-Token"] == "clave-prueba"
        return httpx.Response(200, json=pagina)

    cliente = ClienteFootballData("clave-prueba", transporte=httpx.MockTransport(responder))
    partidos = cliente.partidos_mundial()
    assert partidos[0]["homeTeam"]["tla"] == "MEX"


def test_fifa_calendario_simplificado():
    crudo = json.loads((FIXTURES / "fifa_calendar.json").read_text())

    def responder(solicitud):
        return httpx.Response(200, json=crudo)

    cliente = ClienteFifa(transporte=httpx.MockTransport(responder))
    calendario = cliente.calendario()
    primero = calendario[0]
    assert primero["local_tla"] == "MEX"
    assert primero["estadio"] == "Mexico City Stadium"
    assert primero["grupo"] == "Group A"
    assert primero["id_fifa"] == "400021443"
