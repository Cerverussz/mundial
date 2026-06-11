import json
from pathlib import Path

import httpx

from mundial.ingesta.odds_api import ClienteOddsApi

FIXTURES = Path(__file__).parent / "fixtures"


def test_cuotas_h2h_devuelve_eventos_y_presupuesto():
    eventos = json.loads((FIXTURES / "odds_api_h2h.json").read_text())

    def responder(solicitud: httpx.Request) -> httpx.Response:
        assert solicitud.url.params["apiKey"] == "clave-prueba"
        assert solicitud.url.params["markets"] == "h2h"
        return httpx.Response(
            200, json=eventos, headers={"x-requests-remaining": "499", "x-requests-used": "1"}
        )

    cliente = ClienteOddsApi("clave-prueba", transporte=httpx.MockTransport(responder))
    datos, presupuesto = cliente.cuotas_h2h()
    assert isinstance(datos, list)
    assert presupuesto == {"restantes": "499", "usadas": "1"}
