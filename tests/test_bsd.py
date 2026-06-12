import json
from pathlib import Path

import httpx

from mundial.ingesta.bsd import ClienteBsd

FIXTURES = Path(__file__).parent / "fixtures"


def cliente_con_respuestas(respuestas: dict[str, dict]) -> ClienteBsd:
    """ClienteBsd cuyo transporte responde según el path solicitado."""

    def responder(solicitud: httpx.Request) -> httpx.Response:
        assert solicitud.headers["Authorization"] == "Token token-prueba"
        return httpx.Response(200, json=respuestas[solicitud.url.path])

    return ClienteBsd("token-prueba", transporte=httpx.MockTransport(responder))


def test_eventos_devuelve_resultados():
    pagina = json.loads((FIXTURES / "bsd_eventos.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/": pagina})
    eventos = cliente.eventos(desde="2026-06-11", hasta="2026-06-12")
    assert len(eventos) == 1
    assert eventos[0]["home_team"] == "Mexico"
    assert eventos[0]["id"] == 8287


def test_eventos_sigue_paginacion():
    paginas = iter(
        [
            {"count": 2, "next": "https://x/api/v2/events/?offset=1", "results": [{"id": 1}]},
            {"count": 2, "next": None, "results": [{"id": 2}]},
        ]
    )

    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(paginas))

    cliente = ClienteBsd("t", transporte=httpx.MockTransport(responder))
    assert [e["id"] for e in cliente.eventos()] == [1, 2]


def test_comparacion_cuotas():
    comparacion = json.loads((FIXTURES / "bsd_comparison.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/8287/odds/comparison/": comparacion})
    datos = cliente.comparacion_cuotas(8287)
    assert datos["home_team"] == "Mexico"
    assert datos["bookmakers_count"] == 16
    assert "1x2" in datos["markets"]


def test_estadisticas():
    crudo = json.loads((FIXTURES / "bsd_stats.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/8287/stats/": crudo})
    datos = cliente.estadisticas(8287)
    assert datos["stats"]["home"]["expected_goals"] == 1.41
