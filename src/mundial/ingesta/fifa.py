"""Cliente de api.fifa.com v3 (no documentada) — respaldo de fixtures + estadios."""
from __future__ import annotations

import httpx

BASE = "https://api.fifa.com/api/v3"
ID_COMPETICION = 17
ID_TEMPORADA = 285023


def _descripcion(lista) -> str | None:
    return lista[0].get("Description") if lista else None


def _equipo(crudo: dict | None) -> dict:
    crudo = crudo or {}
    return {
        "tla": crudo.get("Abbreviation"),
        "nombre": _descripcion(crudo.get("TeamName") or []),
    }


class ClienteFifa:
    def __init__(self, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=BASE, timeout=30, transport=transporte)

    def calendario(self) -> list[dict]:
        respuesta = self._http.get(
            "/calendar/matches",
            params={
                "idCompetition": ID_COMPETICION,
                "idSeason": ID_TEMPORADA,
                "language": "en",
                "count": 500,
            },
        )
        respuesta.raise_for_status()
        simplificados = []
        for m in respuesta.json().get("Results", []):
            local, visitante = _equipo(m.get("Home")), _equipo(m.get("Away"))
            simplificados.append(
                {
                    "id_fifa": m.get("IdMatch"),
                    "fecha_utc": m.get("Date"),
                    "estadio": _descripcion((m.get("Stadium") or {}).get("Name") or []),
                    "grupo": _descripcion(m.get("GroupName") or []),
                    "local_tla": local["tla"],
                    "local_nombre": local["nombre"],
                    "visitante_tla": visitante["tla"],
                    "visitante_nombre": visitante["nombre"],
                    "goles_local": m.get("HomeTeamScore"),
                    "goles_visitante": m.get("AwayTeamScore"),
                }
            )
        return simplificados
