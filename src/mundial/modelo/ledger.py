"""Ledger de apuestas simuladas: apertura por flags sostenidos, liquidación y CLV."""
from __future__ import annotations

import sqlite3

from mundial.factores import mercado as modulo_mercado
from mundial.modelo import mercados

KELLY_FRACCION = 0.25
MERCADOS_APOSTABLES = {"1x2", "over_under_25", "over_under_15", "over_under_35",
                       "btts", "draw_no_bet", "double_chance"}
LINEAS = {"over_under_15": 1.5, "over_under_25": 2.5, "over_under_35": 3.5}


def _mejor_cuota(conexion, partido_id: int, mercado_clave: str, seleccion: str):
    if mercado_clave == "1x2":
        columna = {"local": "local", "empate": "empate", "visitante": "visitante"}[seleccion]
        fila = conexion.execute(
            f"""SELECT casa, {columna} AS cuota, MAX(capturado_en) FROM cuotas
                WHERE partido_id=? AND casa NOT IN ('consensus') GROUP BY casa
                ORDER BY cuota DESC LIMIT 1""", (partido_id,)).fetchone()
    else:
        fila = conexion.execute(
            """SELECT casa, cuota, MAX(capturado_en) FROM cuotas_mercado
               WHERE partido_id=? AND mercado=? AND seleccion=? AND casa NOT IN ('consensus')
               GROUP BY casa ORDER BY cuota DESC LIMIT 1""",
            (partido_id, mercado_clave, seleccion)).fetchone()
    return (fila["casa"], fila["cuota"]) if fila and fila["cuota"] else (None, None)


def abrir_apuestas(conexion, partido_id: int, flags: list[dict], p_propias: dict,
                   ahora: str, origen: str = "modelo") -> int:
    abiertas = 0
    for flag in flags:
        if not flag.get("sostenida") or flag.get("mercado") not in MERCADOS_APOSTABLES:
            continue
        casa, cuota = _mejor_cuota(conexion, partido_id, flag["mercado"], flag["seleccion"])
        if not cuota or cuota <= 1.0:
            continue
        p = p_propias.get(flag["seleccion"])
        if p is None:
            continue
        kelly = max(0.0, (p * cuota - 1.0) / (cuota - 1.0)) * KELLY_FRACCION
        cursor = conexion.execute(
            """INSERT OR IGNORE INTO apuestas
               (partido_id, creado_en, origen, mercado, seleccion, linea, cuota, casa,
                p_modelo, p_mercado, margen, stake_kelly)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (partido_id, ahora, origen, flag["mercado"], flag["seleccion"],
             LINEAS.get(flag["mercado"]), cuota, casa, p,
             p - flag["margen"], flag["margen"], round(kelly, 4)))
        abiertas += cursor.rowcount
    conexion.commit()
    return abiertas


def _liquidar_una(fila, goles_local: int, goles_visitante: int) -> tuple[str, float]:
    total, diferencia = goles_local + goles_visitante, goles_local - goles_visitante
    m, s, cuota = fila["mercado"], fila["seleccion"], fila["cuota"]
    if m == "1x2":
        gano = {"local": diferencia > 0, "empate": diferencia == 0,
                "visitante": diferencia < 0}[s]
        return mercados.liquidar_2way(gano, cuota)
    if m.startswith("over_under"):
        lado = "over" if s.startswith("over") else "under"
        return mercados.liquidar_total(total, fila["linea"], lado, cuota)
    if m == "btts":
        return mercados.liquidar_2way(
            (goles_local > 0 and goles_visitante > 0) == (s == "yes"), cuota)
    if m == "draw_no_bet":
        if diferencia == 0:
            return "push", 0.0
        return mercados.liquidar_2way((diferencia > 0) == (s == "HOME"), cuota)
    if m == "double_chance":
        gano = {"1X": diferencia >= 0, "X2": diferencia <= 0, "12": diferencia != 0}[s]
        return mercados.liquidar_2way(gano, cuota)
    return "push", 0.0


def _clv(conexion, fila, fecha_kickoff: str) -> float | None:
    """CLV = cuota tomada / cuota justa de cierre − 1 (cierre: consenso devig pre-kickoff)."""
    if fila["mercado"] == "1x2":
        p_cierre, _, _ = modulo_mercado.cuotas_consenso(
            conexion, fila["partido_id"], hasta=fecha_kickoff)
        clave = fila["seleccion"]
    else:
        p_cierre, _, _ = modulo_mercado.cuotas_consenso_mercado(
            conexion, fila["partido_id"], fila["mercado"], hasta=fecha_kickoff)
        clave = fila["seleccion"]
    if not p_cierre or clave not in p_cierre or p_cierre[clave] <= 0:
        return None
    return fila["cuota"] * p_cierre[clave] - 1.0


def liquidar_pendientes(conexion) -> int:
    filas = conexion.execute(
        """SELECT a.*, p.goles_local, p.goles_visitante, p.fecha_utc FROM apuestas a
           JOIN partidos p ON p.id = a.partido_id
           WHERE a.estado = 'pendiente' AND p.goles_local IS NOT NULL""").fetchall()
    for fila in filas:
        estado, retorno = _liquidar_una(fila, fila["goles_local"], fila["goles_visitante"])
        clv = _clv(conexion, fila, fila["fecha_utc"])
        conexion.execute(
            """UPDATE apuestas SET estado=?, retorno_flat=?, retorno_kelly=?, clv=? WHERE id=?""",
            (estado, retorno, retorno * fila["stake_kelly"] if fila["stake_kelly"] else 0.0,
             clv, fila["id"]))
    conexion.commit()
    return len(filas)


def resumen(conexion) -> dict:
    filas = conexion.execute("SELECT * FROM apuestas WHERE estado != 'pendiente'").fetchall()
    pendientes = conexion.execute(
        "SELECT COUNT(*) c FROM apuestas WHERE estado='pendiente'").fetchone()["c"]
    if not filas:
        return {"n": 0, "pendientes": pendientes}
    pnl = sum(f["retorno_flat"] for f in filas)
    clvs = [f["clv"] for f in filas if f["clv"] is not None]
    return {
        "n": len(filas), "pendientes": pendientes,
        "ganadas": sum(1 for f in filas if f["estado"].startswith(("ganada", "media_ganada"))),
        "pnl_flat": pnl, "yield_flat": pnl / len(filas),
        "pnl_kelly": sum(f["retorno_kelly"] or 0.0 for f in filas),
        "clv_medio": sum(clvs) / len(clvs) if clvs else None,
        "clv_n": len(clvs),
    }
