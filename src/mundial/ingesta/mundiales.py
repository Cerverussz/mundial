"""Mundiales 1930-2022 con marcador a 90' (datahub matches.csv + goals.csv)."""
from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

import httpx

URL_MATCHES = "https://datahub.io/football/worldcup/r/matches.csv"
URL_GOALS = "https://datahub.io/football/worldcup/r/goals.csv"
PERIODOS_90 = {"first half", "second half"}


def descargar(directorio: Path, http: httpx.Client | None = None) -> tuple[Path, Path]:
    cliente = http or httpx.Client(timeout=60, follow_redirects=True)
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = []
    for url, nombre in ((URL_MATCHES, "wc_matches.csv"), (URL_GOALS, "wc_goals.csv")):
        destino = directorio / nombre
        if not destino.exists():
            respuesta = cliente.get(url)
            respuesta.raise_for_status()
            destino.write_bytes(respuesta.content)
        rutas.append(destino)
    return rutas[0], rutas[1]


def _goles_90(ruta_goals: Path) -> dict[str, list[int]]:
    """{match_id: [goles90_local, goles90_visitante]} contando solo 1ª/2ª parte."""
    conteo: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with open(ruta_goals, encoding="utf-8") as archivo:
        for gol in csv.DictReader(archivo):
            if gol["match_period"] not in PERIODOS_90:
                continue
            es_local = gol["home_team"] == "1"
            if gol.get("own_goal") == "1":
                es_local = not es_local
            conteo[gol["match_id"]][0 if es_local else 1] += 1
    return conteo


def cargar(conexion: sqlite3.Connection, ruta_matches: Path, ruta_goals: Path) -> int:
    goles90 = _goles_90(ruta_goals)
    filas = []
    with open(ruta_matches, encoding="utf-8") as archivo:
        for m in csv.DictReader(archivo):
            final = (int(m["home_team_score"]), int(m["away_team_score"]))
            con_prorroga = m["extra_time"] == "1"
            score90 = goles90.get(m["match_id"], list(final)) if con_prorroga else list(final)
            filas.append((
                m["match_id"], int(m["tournament_id"].split("-")[1]), m["stage_name"],
                int(m["group_stage"]), int(m["knockout_stage"]), m["match_date"],
                m["home_team_name"], m["away_team_name"],
                score90[0], score90[1], final[0], final[1],
                int(con_prorroga), int(m["penalty_shootout"] == "1"),
            ))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_wc VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    return len(filas)
