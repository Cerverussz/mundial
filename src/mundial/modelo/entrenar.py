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
