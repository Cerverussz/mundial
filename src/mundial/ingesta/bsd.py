"""Cliente de Bzzoiro Sports Data (BSD) — cuotas multi-casa, eventos del Mundial."""
from __future__ import annotations

import httpx

BASE = "https://sports.bzzoiro.com/api/v2"
LIGA_MUNDIAL = 27


class ClienteBsd:
    def __init__(self, token: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=BASE,
            headers={"Authorization": f"Token {token}"},
            timeout=30,
            transport=transporte,
        )

    def eventos(
        self,
        liga: int = LIGA_MUNDIAL,
        desde: str | None = None,
        hasta: str | None = None,
    ) -> list[dict]:
        """Eventos de una liga, siguiendo la paginación completa."""
        parametros = {"league_id": liga, "limit": 200}
        if desde:
            parametros["date_from"] = desde
        if hasta:
            parametros["date_to"] = hasta
        resultados: list[dict] = []
        respuesta = self._http.get("/events/", params=parametros)
        respuesta.raise_for_status()
        pagina = respuesta.json()
        resultados.extend(pagina["results"])
        while pagina.get("next"):
            respuesta = self._http.get(pagina["next"])
            respuesta.raise_for_status()
            pagina = respuesta.json()
            resultados.extend(pagina["results"])
        return resultados

    def comparacion_cuotas(self, evento_id: int) -> dict:
        """Cuotas de todas las casas para un evento, en una sola llamada."""
        respuesta = self._http.get(f"/events/{evento_id}/odds/comparison/")
        respuesta.raise_for_status()
        return respuesta.json()

    def detalle(self, evento_id: int) -> dict:
        """Detalle del evento (incluye clima precalculado y terreno neutral)."""
        respuesta = self._http.get(f"/events/{evento_id}/", params={"full": "true"})
        respuesta.raise_for_status()
        return respuesta.json()

    def alineaciones(self, evento_id: int) -> dict:
        """Alineaciones (predichas o confirmadas) y jugadores no disponibles."""
        respuesta = self._http.get(f"/events/{evento_id}/lineups/", params={"full": "true"})
        respuesta.raise_for_status()
        return respuesta.json()

    def estadisticas(self, evento_id: int) -> dict:
        """Estadísticas post-partido: xG por equipo, shotmap por tiro, xG por minuto."""
        respuesta = self._http.get(f"/events/{evento_id}/stats/")
        respuesta.raise_for_status()
        return respuesta.json()
