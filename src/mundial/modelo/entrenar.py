"""Ajuste del modelo base sobre el histórico y persistencia de ratings."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from mundial.modelo import dixon_coles

VENTANA_DIAS = 3650


def entrenar_y_guardar(
    conexion: sqlite3.Connection, referencia: date | None = None
) -> dixon_coles.Ajuste:
    referencia = referencia or date.today()
    desde = (referencia - timedelta(days=VENTANA_DIAS)).isoformat()
    filas = conexion.execute(
        """SELECT fecha, local, visitante, goles_local, goles_visitante, neutral
           FROM resultados_historicos WHERE fecha >= ? ORDER BY fecha""",
        (desde,),
    ).fetchall()
    partidos = [
        (date.fromisoformat(f["fecha"]), f["local"], f["visitante"],
         f["goles_local"], f["goles_visitante"], bool(f["neutral"]))
        for f in filas
    ]
    ajuste = dixon_coles.ajustar(partidos, referencia)
    marca = referencia.isoformat()
    conexion.executemany(
        "INSERT OR REPLACE INTO ratings VALUES (?,?,?,?)",
        [(e, marca, ajuste.ataque[e], ajuste.defensa[e]) for e in ajuste.equipos],
    )
    conexion.execute(
        "INSERT OR REPLACE INTO modelo_meta VALUES (?,?,?,?,?,?,?,?)",
        (marca, ajuste.mu, ajuste.ventaja_local, ajuste.rho,
         ajuste.n_partidos, len(ajuste.equipos), ajuste.log_verosimilitud, ajuste.version),
    )
    conexion.commit()
    return ajuste


def ratings_asof(conexion: sqlite3.Connection, anios=range(1994, 2027),
                 partidos_minimos: int = 5, minimo_ajuste: int = 500) -> int:
    """Materializa ratings point-in-time: ajuste con datos ESTRICTAMENTE anteriores al 1 de
    enero de cada año (ventana de 10 años). Para features históricas sin fuga."""
    hechos = 0
    for anio in anios:
        corte = date(anio, 1, 1)
        desde = (corte - timedelta(days=VENTANA_DIAS)).isoformat()
        filas = conexion.execute(
            """SELECT fecha, local, visitante, goles_local, goles_visitante, neutral
               FROM resultados_historicos WHERE fecha >= ? AND fecha < ? ORDER BY fecha""",
            (desde, corte.isoformat()),
        ).fetchall()
        if len(filas) < minimo_ajuste:
            continue
        partidos = [
            (date.fromisoformat(f["fecha"]), f["local"], f["visitante"],
             f["goles_local"], f["goles_visitante"], bool(f["neutral"])) for f in filas
        ]
        ajuste = dixon_coles.ajustar(partidos, corte, partidos_minimos=partidos_minimos)
        marca = corte.isoformat()
        conexion.executemany(
            "INSERT OR REPLACE INTO ratings VALUES (?,?,?,?)",
            [(e, marca, ajuste.ataque[e], ajuste.defensa[e]) for e in ajuste.equipos])
        conexion.execute(
            "INSERT OR REPLACE INTO modelo_meta VALUES (?,?,?,?,?,?,?,?)",
            (marca, ajuste.mu, ajuste.ventaja_local, ajuste.rho, ajuste.n_partidos,
             len(ajuste.equipos), ajuste.log_verosimilitud, ajuste.version))
        hechos += 1
    conexion.commit()
    return hechos


def rating_asof(conexion: sqlite3.Connection, equipo: str, fecha: str) -> dict | None:
    fila = conexion.execute(
        """SELECT * FROM ratings WHERE equipo = ? AND fecha_ajuste <= ?
           AND fecha_ajuste LIKE '%-01-01'
           ORDER BY fecha_ajuste DESC LIMIT 1""",
        (equipo, fecha),
    ).fetchone()
    return dict(fila) if fila else None
