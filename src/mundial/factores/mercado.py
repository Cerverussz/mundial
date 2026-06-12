"""De-vigging (proporcional y Shin) y consenso multi-casa del mercado."""
from __future__ import annotations

import math
import sqlite3
from statistics import median

RESULTADOS = ("local", "empate", "visitante")
CASAS_EXCLUIDAS = {"consensus"}


def quitar_margen_proporcional(cuotas: dict[str, float]) -> dict[str, float]:
    inversas = {k: 1.0 / v for k, v in cuotas.items()}
    total = sum(inversas.values())
    return {k: x / total for k, x in inversas.items()}


def quitar_margen_shin(cuotas: dict[str, float]) -> dict[str, float]:
    """Método de Shin: recupera probabilidades asumiendo una proporción z de apostadores
    informados; encoge a los longshots más que la normalización proporcional."""
    q = {k: 1.0 / v for k, v in cuotas.items()}
    s = sum(q.values())
    if s <= 1.0:
        return quitar_margen_proporcional(cuotas)

    def probabilidades(z: float) -> dict[str, float]:
        return {
            k: (math.sqrt(z * z + 4.0 * (1.0 - z) * qi * qi / s) - z) / (2.0 * (1.0 - z))
            for k, qi in q.items()
        }

    bajo, alto = 0.0, 0.4
    for _ in range(60):
        z = (bajo + alto) / 2.0
        if sum(probabilidades(z).values()) > 1.0:
            bajo = z
        else:
            alto = z
    p = probabilidades((bajo + alto) / 2.0)
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}


def consenso(filas: list[tuple]) -> tuple[dict[str, float], int]:
    """Mediana por resultado de las probabilidades Shin de cada casa.

    filas: (casa, cuota_local, cuota_empate, cuota_visitante). Excluye casas sintéticas.
    """
    por_casa = []
    for casa, local, empate, visitante in filas:
        if casa in CASAS_EXCLUIDAS or not all((local, empate, visitante)):
            continue
        por_casa.append(
            quitar_margen_shin({"local": local, "empate": empate, "visitante": visitante})
        )
    if not por_casa:
        return {}, 0
    p = {k: median(c[k] for c in por_casa) for k in RESULTADOS}
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}, len(por_casa)


def cuotas_consenso(
    conexion: sqlite3.Connection, partido_id: int, hasta: str | None = None
) -> tuple[dict[str, float], int, str | None]:
    """Consenso del mercado con la última cuota de cada casa (opcionalmente hasta un momento).

    Devuelve (probabilidades, n_casas, capturado_en más reciente usado).
    """
    condicion = "AND capturado_en <= ?" if hasta else ""
    parametros = [partido_id] + ([hasta] if hasta else [])
    filas = conexion.execute(
        f"""SELECT casa, local, empate, visitante, MAX(capturado_en) AS capturado_en
            FROM cuotas WHERE partido_id = ? AND mercado IN ('1x2', 'h2h') {condicion}
            GROUP BY fuente, casa""",
        parametros,
    ).fetchall()
    if not filas:
        return {}, 0, None
    probabilidades, n_casas = consenso(
        [(f["casa"], f["local"], f["empate"], f["visitante"]) for f in filas]
    )
    mas_reciente = max(f["capturado_en"] for f in filas)
    return probabilidades, n_casas, mas_reciente


def consenso_generico(filas: list[tuple[str, dict[str, float]]]) -> tuple[dict, int]:
    """Mediana de probabilidades Shin por selección. filas: (casa, {seleccion: cuota})."""
    por_casa = []
    selecciones = None
    for casa, cuotas in filas:
        if casa in CASAS_EXCLUIDAS or not cuotas or any(
            v is None or v <= 1.0 for v in cuotas.values()
        ):
            continue
        if selecciones is None:
            selecciones = set(cuotas)
        if set(cuotas) != selecciones:
            continue
        por_casa.append(quitar_margen_shin(cuotas))
    if not por_casa:
        return {}, 0
    p = {k: median(c[k] for c in por_casa) for k in selecciones}
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}, len(por_casa)


def cuotas_consenso_mercado(
    conexion: sqlite3.Connection, partido_id: int, mercado: str, hasta: str | None = None
) -> tuple[dict, int, str | None]:
    condicion = "AND capturado_en <= ?" if hasta else ""
    parametros = [partido_id, mercado] + ([hasta] if hasta else [])
    filas = conexion.execute(
        f"""SELECT casa, seleccion, cuota, MAX(capturado_en) AS capturado_en
            FROM cuotas_mercado WHERE partido_id = ? AND mercado = ? {condicion}
            GROUP BY fuente, casa, seleccion""",
        parametros,
    ).fetchall()
    if not filas:
        return {}, 0, None
    por_casa: dict[str, dict[str, float]] = {}
    for f in filas:
        por_casa.setdefault(f["casa"], {})[f["seleccion"]] = f["cuota"]
    p, n = consenso_generico(list(por_casa.items()))
    return p, n, max(f["capturado_en"] for f in filas)
