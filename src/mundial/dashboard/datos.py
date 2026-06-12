"""Consultas puras para el dashboard (testeables sin Streamlit)."""
from __future__ import annotations

import json
import sqlite3

from mundial.factores import mercado


def partidos_proximos(
    conexion: sqlite3.Connection, desde: str | None = None, dias: int = 7
) -> list[dict]:
    filas = conexion.execute(
        """SELECT * FROM partidos
           WHERE date(fecha_utc) >= date(coalesce(?, 'now'))
             AND date(fecha_utc) < date(coalesce(?, 'now'), '+' || ? || ' days')
           ORDER BY fecha_utc""",
        (desde, desde, dias),
    ).fetchall()
    return [dict(f) for f in filas]


def ultima_prediccion(conexion: sqlite3.Connection, partido_id: int) -> dict | None:
    fila = conexion.execute(
        """SELECT * FROM predicciones WHERE partido_id = ?
           ORDER BY creado_en DESC, id DESC LIMIT 1""",
        (partido_id,),
    ).fetchone()
    if fila is None:
        return None
    prediccion = dict(fila)
    prediccion["matriz"] = json.loads(prediccion.pop("matriz_json") or "[]")
    prediccion["factores"] = json.loads(prediccion.pop("factores_json") or "[]")
    prediccion["razones"] = json.loads(prediccion.pop("razones_confianza") or "[]")
    prediccion["flags"] = json.loads(prediccion.pop("valor_flags") or "[]")
    return prediccion


def evolucion_consenso(conexion: sqlite3.Connection, partido_id: int) -> list[dict]:
    """Probabilidades de consenso del mercado en cada momento de captura."""
    momentos = [
        f["capturado_en"] for f in conexion.execute(
            "SELECT DISTINCT capturado_en FROM cuotas WHERE partido_id = ? ORDER BY 1",
            (partido_id,),
        )
    ]
    serie = []
    for momento in momentos:
        filas = conexion.execute(
            """SELECT casa, local, empate, visitante FROM cuotas
               WHERE partido_id = ? AND capturado_en = ?""",
            (partido_id, momento),
        ).fetchall()
        p, n_casas = mercado.consenso(
            [(f["casa"], f["local"], f["empate"], f["visitante"]) for f in filas]
        )
        if p:
            serie.append({"capturado_en": momento, "n_casas": n_casas, **p})
    return serie


def divergencias(conexion: sqlite3.Connection) -> list[dict]:
    """Última predicción por partido no terminado, con divergencia modelo-mercado."""
    filas = conexion.execute(
        """SELECT m.id, m.fecha_utc, m.local, m.visitante, p.marcador, p.confianza,
                  p.p_local, p.p_empate, p.p_visitante,
                  p.p_local_modelo, p.p_empate_modelo, p.p_visitante_modelo,
                  p.p_local_mercado, p.p_empate_mercado, p.p_visitante_mercado,
                  p.valor_flags
           FROM partidos m
           JOIN predicciones p ON p.id = (
               SELECT p2.id FROM predicciones p2 WHERE p2.partido_id = m.id
               ORDER BY p2.creado_en DESC, p2.id DESC LIMIT 1
           )
           WHERE m.goles_local IS NULL
           ORDER BY m.fecha_utc""",
    ).fetchall()
    resultado = []
    for fila in filas:
        d = dict(fila)
        if d["p_local_mercado"] is not None:
            d["divergencia"] = max(
                abs(d[f"p_{k}_modelo"] - d[f"p_{k}_mercado"])
                for k in ("local", "empate", "visitante")
            )
        else:
            d["divergencia"] = 0.0
        d["flags"] = json.loads(d.pop("valor_flags") or "[]")
        resultado.append(d)
    resultado.sort(key=lambda d: d["divergencia"], reverse=True)
    return resultado


def patrones_registrados() -> list[dict]:
    """Patrones de data/patrones.json (vacío si no existe)."""
    from mundial.config import RAIZ
    ruta = RAIZ / "data" / "patrones.json"
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text(encoding="utf-8"))


def apuestas_recientes(conexion: sqlite3.Connection, limite: int = 20) -> list[dict]:
    filas = conexion.execute(
        """SELECT a.estado, a.mercado, a.seleccion, a.cuota, a.origen, a.clv,
                  a.retorno_flat, p.local, p.visitante
           FROM apuestas a JOIN partidos p ON p.id = a.partido_id
           ORDER BY a.creado_en DESC LIMIT ?""", (limite,)).fetchall()
    return [dict(f) for f in filas]
