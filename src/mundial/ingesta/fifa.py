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
                    "id_stage": m.get("IdStage"),
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

    def alineacion_live(self, id_stage: str, id_match: str) -> dict:
        """XI oficial desde el endpoint live (Status==1 = titular; FIFA lo publica T-60/75min)."""
        respuesta = self._http.get(
            f"/live/football/{ID_COMPETICION}/{ID_TEMPORADA}/{id_stage}/{id_match}",
            params={"language": "en"})
        respuesta.raise_for_status()
        crudo = respuesta.json()

        def titulares(lado: dict | None) -> list[str]:
            return [_descripcion(j.get("PlayerName") or [])
                    for j in (lado or {}).get("Players", []) if j.get("Status") == 1]

        return {"local": titulares(crudo.get("HomeTeam")),
                "visitante": titulares(crudo.get("AwayTeam"))}
