"""Cliente de football-data.org v4 — backbone de fixtures/resultados (10 req/min)."""
from __future__ import annotations

import httpx

BASE = "https://api.football-data.org/v4"


class ClienteFootballData:
    def __init__(self, clave: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=BASE, headers={"X-Auth-Token": clave}, timeout=30, transport=transporte
        )

    def partidos_mundial(self) -> list[dict]:
        respuesta = self._http.get("/competitions/WC/matches")
        respuesta.raise_for_status()
        return respuesta.json()["matches"]
