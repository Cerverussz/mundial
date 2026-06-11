"""Carga incremental de snapshots de cuotas (y bajas) del repo hacia SQLite."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mundial.config import DIR_SNAPSHOTS
from mundial.ingesta import snapshots
from mundial.ingesta.actualizar import canonico

RESULTADO_BSD = {"HOME": "local", "DRAW": "empate", "AWAY": "visitante"}


def _indice_partidos(conexion: sqlite3.Connection) -> dict:
    filas = conexion.execute("SELECT id, fecha_utc, local, visitante FROM partidos").fetchall()
    return {
        (f["fecha_utc"][:10], frozenset((f["local"], f["visitante"]))): f["id"] for f in filas
    }


def _filas_bsd(payload: dict, capturado_en: str, indice: dict) -> tuple[list, list, list]:
    cuotas, vinculos, bajas = [], [], []
    for evento_id, comparacion in (payload.get("comparaciones") or {}).items():
        llave = (
            comparacion["event_date"][:10],
            frozenset(
                (canonico(comparacion["home_team"]), canonico(comparacion["away_team"]))
            ),
        )
        partido_id = indice.get(llave)
        if partido_id is None:
            continue
        vinculos.append((partido_id, int(evento_id)))
        mercado_1x2 = (comparacion.get("markets") or {}).get("1x2") or {}
        por_casa: dict[str, dict[str, float]] = {}
        for resultado_bsd, detalle in mercado_1x2.items():
            resultado = RESULTADO_BSD.get(resultado_bsd)
            if resultado is None:
                continue
            for casa, datos in (detalle.get("bookmakers") or {}).items():
                por_casa.setdefault(casa, {})[resultado] = datos.get("decimal_odds")
        for casa, valores in por_casa.items():
            if len(valores) == 3 and all(valores.values()):
                cuotas.append(
                    (partido_id, capturado_en, "bsd", casa, "1x2",
                     valores["local"], valores["empate"], valores["visitante"])
                )
        equipos = {
            "home": canonico(comparacion["home_team"]),
            "away": canonico(comparacion["away_team"]),
        }
        alineacion = (payload.get("alineaciones") or {}).get(str(evento_id)) or {}
        xi = {
            lado: {j["name"]: j.get("ai_score") for j in (datos or {}).get("players", [])}
            for lado, datos in (alineacion.get("lineups") or {}).items()
        }
        for lado, jugadores in (alineacion.get("unavailable_players") or {}).items():
            for jugador in jugadores or []:
                bajas.append(
                    (partido_id, equipos.get(lado), jugador.get("name"),
                     jugador.get("status"), jugador.get("reason"),
                     xi.get(lado, {}).get(jugador.get("name")), capturado_en)
                )
    return cuotas, vinculos, bajas


def _filas_odds_api(payload, capturado_en: str, indice: dict) -> list:
    eventos = payload.get("eventos") if isinstance(payload, dict) else payload
    cuotas = []
    for evento in eventos or []:
        local, visitante = canonico(evento["home_team"]), canonico(evento["away_team"])
        partido_id = indice.get((evento["commence_time"][:10], frozenset((local, visitante))))
        if partido_id is None:
            continue
        for casa in evento.get("bookmakers", []):
            for mercado in casa.get("markets", []):
                if mercado["key"] != "h2h":
                    continue
                precios = {o["name"]: o["price"] for o in mercado["outcomes"]}
                valores = {
                    "local": precios.get(evento["home_team"]),
                    "empate": precios.get("Draw"),
                    "visitante": precios.get(evento["away_team"]),
                }
                if all(valores.values()):
                    cuotas.append(
                        (partido_id, capturado_en, "odds-api", casa["key"], "h2h",
                         valores["local"], valores["empate"], valores["visitante"])
                    )
    return cuotas


def cargar_nuevos(conexion: sqlite3.Connection, base: Path | None = None) -> int:
    """Carga snapshots aún no procesados. Devuelve filas de cuotas insertadas."""
    base = base or DIR_SNAPSHOTS
    cargados = {
        f["ruta"] for f in conexion.execute("SELECT ruta FROM archivos_cargados")
    }
    indice = _indice_partidos(conexion)
    total = 0
    for ruta in sorted(base.glob("*/*.json.gz")):
        rel = str(ruta.relative_to(base))
        if rel in cargados:
            continue
        contenido = snapshots.leer_snapshot(ruta)
        fuente, capturado_en = contenido["fuente"], contenido["capturado_en"]
        payload = contenido["payload"]
        cuotas, vinculos, bajas = [], [], []
        if fuente == "bsd":
            cuotas, vinculos, bajas = _filas_bsd(payload, capturado_en, indice)
        elif fuente == "odds-api":
            cuotas = _filas_odds_api(payload, capturado_en, indice)
        conexion.executemany(
            "INSERT OR REPLACE INTO cuotas VALUES (?,?,?,?,?,?,?,?)", cuotas
        )
        conexion.executemany(
            "INSERT OR REPLACE INTO eventos_bsd VALUES (?,?)", vinculos
        )
        conexion.executemany(
            "INSERT OR REPLACE INTO bajas VALUES (?,?,?,?,?,?,?)", bajas
        )
        conexion.execute(
            "INSERT OR REPLACE INTO archivos_cargados VALUES (?,?)",
            (rel, datetime.now(timezone.utc).isoformat()),
        )
        total += len(cuotas)
    conexion.commit()
    return total
