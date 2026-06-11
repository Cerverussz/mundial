"""Orquestación de sincronización: estáticos → histórico → fixtures (cascada fd → FIFA)."""
from __future__ import annotations

import csv
import sqlite3
from functools import lru_cache

from mundial.config import DIR_LOCAL, RAIZ, clave
from mundial.ingesta import estaticos, martj42
from mundial.ingesta.fifa import ClienteFifa
from mundial.ingesta.football_data import ClienteFootballData

RUTA_MAPEO = RAIZ / "data" / "static" / "mapeo_nombres.csv"


@lru_cache(maxsize=1)
def _mapeo() -> dict[str, str]:
    with open(RUTA_MAPEO, encoding="utf-8") as archivo:
        return {f["nombre_fuente"]: f["nombre_canonico"] for f in csv.DictReader(archivo)}


def canonico(nombre: str) -> str:
    """Nombre canónico de equipo (convención martj42)."""
    return _mapeo().get(nombre, nombre)


def _desde_fd(m: dict) -> dict | None:
    if not m["homeTeam"].get("name") or not m["awayTeam"].get("name"):
        return None  # llaves de eliminatoria sin definir
    marcador = m["score"]["fullTime"]
    return {
        "id": m["id"],
        "fecha_utc": m["utcDate"],
        "local": canonico(m["homeTeam"]["name"]),
        "visitante": canonico(m["awayTeam"]["name"]),
        "local_tla": m["homeTeam"].get("tla"),
        "fase": m.get("stage"),
        "grupo": m.get("group"),
        "jornada": m.get("matchday"),
        "estado": m.get("status"),
        "goles_local": marcador.get("home"),
        "goles_visitante": marcador.get("away"),
        "fuente": "football-data",
    }


def _desde_fifa(c: dict) -> dict | None:
    if not c.get("local_nombre") or not c.get("visitante_nombre"):
        return None
    return {
        "id": int(c["id_fifa"]),
        "fecha_utc": c["fecha_utc"],
        "local": canonico(c["local_nombre"]),
        "visitante": canonico(c["visitante_nombre"]),
        "local_tla": c.get("local_tla"),
        "fase": None,
        "grupo": c.get("grupo"),
        "jornada": None,
        "estado": None,
        "goles_local": c.get("goles_local"),
        "goles_visitante": c.get("goles_visitante"),
        "fuente": "fifa",
    }


def sincronizar(
    conexion: sqlite3.Connection,
    cliente_fd: object | None = None,
    cliente_fifa: object | None = None,
    cargar_historico: bool = True,
) -> list[str]:
    """Sincroniza la base local. Nunca falla duro: degrada y lo declara."""
    mensajes: list[str] = []
    n_estadios = estaticos.cargar_estadios(conexion)
    mensajes.append(f"estadios: {n_estadios}")

    if cargar_historico:
        try:
            ruta = martj42.descargar(DIR_LOCAL / "martj42.csv")
            n = martj42.cargar(conexion, ruta)
            mensajes.append(f"histórico martj42: {n} resultados")
        except Exception as error:
            mensajes.append(f"[ADVERTENCIA] martj42 no disponible: {error}")

    partidos: list[dict] = []
    try:
        fd = cliente_fd or ClienteFootballData(clave("FOOTBALL_DATA_KEY"))
        partidos = [p for m in fd.partidos_mundial() if (p := _desde_fd(m))]
    except Exception as error:
        mensajes.append(f"[ADVERTENCIA] football-data caído: {error}; intento FIFA")

    calendario: list[dict] = []
    try:
        calendario = (cliente_fifa or ClienteFifa()).calendario()
    except Exception as error:
        mensajes.append(f"[ADVERTENCIA] calendario FIFA no disponible: {error}")

    if not partidos and calendario:
        partidos = [p for c in calendario if (p := _desde_fifa(c))]

    estadio_por_llave = {
        (c["fecha_utc"], c["local_tla"]): (c["estadio"], c["id_fifa"]) for c in calendario
    }
    for p in partidos:
        p["estadio"], p["id_fifa"] = estadio_por_llave.get(
            (p["fecha_utc"], p.pop("local_tla")), (None, None)
        )
    conexion.executemany(
        """INSERT OR REPLACE INTO partidos
           (id, fecha_utc, local, visitante, fase, grupo, jornada, estadio, estado,
            goles_local, goles_visitante, id_fifa, fuente)
           VALUES (:id,:fecha_utc,:local,:visitante,:fase,:grupo,:jornada,:estadio,:estado,
                   :goles_local,:goles_visitante,:id_fifa,:fuente)""",
        partidos,
    )
    equipos = sorted({p["local"] for p in partidos} | {p["visitante"] for p in partidos})
    conexion.executemany(
        "INSERT OR IGNORE INTO equipos(nombre) VALUES (?)", [(e,) for e in equipos]
    )
    conexion.commit()
    mensajes.append(
        f"partidos: {len(partidos)} (fuente: {partidos[0]['fuente'] if partidos else '—'})"
    )

    historicos = {
        f["local"] for f in conexion.execute("SELECT DISTINCT local FROM resultados_historicos")
    }
    sin_mapear = [e for e in equipos if historicos and e not in historicos]
    if sin_mapear:
        mensajes.append(f"[ADVERTENCIA] equipos sin mapear al histórico: {sin_mapear}")
    return mensajes
