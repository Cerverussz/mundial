"""Cliente de The Odds API — respaldo de cuotas, presupuesto de 500 créditos/mes."""
from __future__ import annotations

import httpx

BASE = "https://api.the-odds-api.com/v4"
DEPORTE_MUNDIAL = "soccer_fifa_world_cup"


class ClienteOddsApi:
    def __init__(self, clave: str, transporte: httpx.BaseTransport | None = None):
        self._clave = clave
        self._http = httpx.Client(base_url=BASE, timeout=30, transport=transporte)

    def cuotas_h2h(self) -> tuple[list, dict]:
        """Cuotas 1X2 del Mundial (región eu). Devuelve (eventos, presupuesto)."""
        respuesta = self._http.get(
            f"/sports/{DEPORTE_MUNDIAL}/odds/",
            params={
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "apiKey": self._clave,
            },
        )
        respuesta.raise_for_status()
        presupuesto = {
            "restantes": respuesta.headers.get("x-requests-remaining"),
            "usadas": respuesta.headers.get("x-requests-used"),
        }
        return respuesta.json(), presupuesto
