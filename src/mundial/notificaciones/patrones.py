"""Patrones pre-registrados: carga validada por git, filtro declarativo, condición de precio."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mundial.config import RAIZ

RUTA_PATRONES = RAIZ / "data" / "patrones.json"
CLAVES_FILTRO = {
    "fase_eliminacion": lambda ctx, v: ctx.get("fase_eliminacion") == v,
    "jornada": lambda ctx, v: ctx.get("jornada") == v,
    "diff_rating_max": lambda ctx, v: ctx.get("diff_rating") is not None and ctx["diff_rating"] <= v,
    "diff_rating_min": lambda ctx, v: ctx.get("diff_rating") is not None and ctx["diff_rating"] >= v,
    "confederacion_local": lambda ctx, v: ctx.get("confederacion_local") == v,
    "confederacion_visitante": lambda ctx, v: ctx.get("confederacion_visitante") == v,
    "dead_rubber_alguno": lambda ctx, v: (
        ctx.get("dead_rubber_local") or ctx.get("dead_rubber_visitante")) == v,
    "es_anfitrion_local": lambda ctx, v: ctx.get("es_anfitrion_local") == v,
}


def satisface(filtro: dict, contexto: dict) -> bool:
    return all(
        clave in CLAVES_FILTRO and CLAVES_FILTRO[clave](contexto, valor)
        for clave, valor in filtro.items()
    )


def precio_cumple(patron: dict, p_implicitas: dict) -> bool:
    p = p_implicitas.get(patron["lado"])
    return p is not None and p <= patron["umbral_prob_implicita"]


def _commit_valido(commit: str, fecha_partido: str, repo: Path | None) -> bool:
    try:
        salida = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit],
            cwd=repo or RAIZ, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return bool(salida) and salida < fecha_partido
    except Exception:
        return False


def cargar_validados(ruta: Path | None = None, fecha_partido: str = "",
                     repo: Path | None = None) -> list[dict]:
    ruta = ruta or RUTA_PATRONES
    if not ruta.exists():
        return []
    cargados = json.loads(ruta.read_text(encoding="utf-8"))
    validos = []
    for patron in cargados:
        if patron.get("estado") not in ("activo", "en_papel"):
            continue
        ventana = patron.get("ventana_validez", ["", "9999"])
        if not (ventana[0] <= fecha_partido[:10] <= ventana[1]):
            continue
        if not _commit_valido(patron.get("registrado_en_commit", ""), fecha_partido, repo):
            continue
        validos.append(patron)
    return validos


def construir_contexto(conexion, partido_id: int) -> dict:
    partido = conexion.execute("SELECT * FROM partidos WHERE id=?", (partido_id,)).fetchone()
    ratings = {
        f["equipo"]: f["ataque"] + f["defensa"] for f in conexion.execute(
            """SELECT * FROM ratings WHERE fecha_ajuste =
               (SELECT MAX(fecha_ajuste) FROM ratings)""")
    }
    confederaciones = {
        f["nombre"]: f["confederacion"] for f in conexion.execute("SELECT * FROM equipos")
    }
    diff = None
    if partido["local"] in ratings and partido["visitante"] in ratings:
        diff = abs(ratings[partido["local"]] - ratings[partido["visitante"]])
    return {
        "fase_eliminacion": (partido["fase"] or "") not in ("GROUP_STAGE", "", None),
        "jornada": partido["jornada"],
        "diff_rating": diff,
        "confederacion_local": confederaciones.get(partido["local"]),
        "confederacion_visitante": confederaciones.get(partido["visitante"]),
        "dead_rubber_local": _dead_rubber(conexion, partido, partido["local"]),
        "dead_rubber_visitante": _dead_rubber(conexion, partido, partido["visitante"]),
        "es_anfitrion_local": partido["local"] in ("Mexico", "United States", "Canada"),
        "fecha": partido["fecha_utc"],
    }


def _dead_rubber(conexion, partido, equipo: str) -> bool:
    """Jornada 3: clasificación directa ya decidida ignorando la lotería de terceros
    (aproximación documentada: enumera los 3^k resultados restantes del grupo)."""
    if partido["jornada"] != 3 or not partido["grupo"]:
        return False
    filas = conexion.execute(
        "SELECT * FROM partidos WHERE grupo = ?", (partido["grupo"],)).fetchall()
    equipos = sorted({f["local"] for f in filas} | {f["visitante"] for f in filas})
    puntos = {e: 0 for e in equipos}
    pendientes = []
    for f in filas:
        if f["goles_local"] is not None:
            if f["goles_local"] > f["goles_visitante"]:
                puntos[f["local"]] += 3
            elif f["goles_local"] < f["goles_visitante"]:
                puntos[f["visitante"]] += 3
            else:
                puntos[f["local"]] += 1
                puntos[f["visitante"]] += 1
        else:
            pendientes.append((f["local"], f["visitante"]))
    posiciones = set()
    for combo in range(3 ** len(pendientes)):
        escenario = dict(puntos)
        c = combo
        for local, visitante in pendientes:
            r = c % 3
            c //= 3
            if r == 0:
                escenario[local] += 3
            elif r == 1:
                escenario[visitante] += 3
            else:
                escenario[local] += 1
                escenario[visitante] += 1
        orden = sorted(escenario, key=escenario.get, reverse=True)
        posiciones.add(orden.index(equipo) < 2)  # ¿termina top-2?
    return len(posiciones) == 1  # mismo destino en TODOS los escenarios
