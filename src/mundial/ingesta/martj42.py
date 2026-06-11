"""Histórico de partidos internacionales 1872→hoy (martj42, CC0)."""
from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

import httpx

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE_HORAS = 24.0


def descargar(destino: Path, http: httpx.Client | None = None) -> Path:
    if destino.exists() and (time.time() - destino.stat().st_mtime) < CACHE_HORAS * 3600:
        return destino
    cliente = http or httpx.Client(timeout=60, follow_redirects=True)
    respuesta = cliente.get(URL)
    respuesta.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(respuesta.content)
    return destino


def cargar(conexion: sqlite3.Connection, ruta: Path) -> int:
    """Inserta resultados con marcador (salta fixtures futuros con NA)."""
    filas = []
    with open(ruta, encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            if not fila["home_score"].isdigit() or not fila["away_score"].isdigit():
                continue
            filas.append(
                (
                    fila["date"], fila["home_team"], fila["away_team"],
                    int(fila["home_score"]), int(fila["away_score"]),
                    fila["tournament"], fila["city"], fila["country"],
                    1 if fila["neutral"].upper() == "TRUE" else 0,
                )
            )
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas
    )
    conexion.commit()
    return len(filas)
