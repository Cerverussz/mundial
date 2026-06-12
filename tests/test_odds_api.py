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


def test_eventos_y_sondeo_ah():
    eventos = [{"id": "abc123", "home_team": "Mexico", "away_team": "South Africa",
                "commence_time": "2026-06-11T19:00:00Z"}]
    cuotas_evento = {
        "id": "abc123", "bookmakers": [
            {"key": "pinnacle", "markets": [
                {"key": "spreads", "outcomes": [
                    {"name": "Mexico", "price": 1.92, "point": -1.0},
                    {"name": "South Africa", "price": 1.98, "point": 1.0}]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": 1.85, "point": 2.25},
                    {"name": "Under", "price": 2.05, "point": 2.25}]}]}]}

    def responder(solicitud):
        if solicitud.url.path.endswith("/events"):
            return httpx.Response(200, json=eventos)
        return httpx.Response(200, json=cuotas_evento,
                              headers={"x-requests-remaining": "480", "x-requests-last": "5"})

    cliente = ClienteOddsApi("k", transporte=httpx.MockTransport(responder))
    assert cliente.eventos()[0]["id"] == "abc123"
    datos, presupuesto = cliente.cuotas_evento("abc123", mercados="spreads,totals")
    assert presupuesto["restantes"] == "480"
    filas = ClienteOddsApi.filas_mercados(datos, partido_id=537327, capturado_en="t")
    assert (537327, "t", "odds-api", "pinnacle", "ah", "Mexico@-1.0", 1.92) in filas
    assert (537327, "t", "odds-api", "pinnacle", "totals", "over@2.25", 1.85) in filas
