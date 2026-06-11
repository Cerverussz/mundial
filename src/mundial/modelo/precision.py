"""Precisión de las predicciones: Brier y RPS, modelo vs mercado vs blend."""
from __future__ import annotations

import sqlite3

ORDEN = ("local", "empate", "visitante")


def brier(p: tuple[float, float, float], resultado: int) -> float:
    """Brier multiclase: Σ(p_i − y_i)² sobre los 3 resultados."""
    return sum((pi - (1.0 if i == resultado else 0.0)) ** 2 for i, pi in enumerate(p))


def rps(p: tuple[float, float, float], resultado: int) -> float:
    """Ranked Probability Score: castiga menos los errores 'ordinalmente cercanos'."""
    acumulado_p = acumulado_y = total = 0.0
    for i in range(2):
        acumulado_p += p[i]
        acumulado_y += 1.0 if i == resultado else 0.0
        total += (acumulado_p - acumulado_y) ** 2
    return total / 2.0


def _resultado(goles_local: int, goles_visitante: int) -> int:
    if goles_local > goles_visitante:
        return 0
    if goles_local == goles_visitante:
        return 1
    return 2


def evaluar(conexion: sqlite3.Connection) -> dict:
    """Evalúa la última predicción pre-kickoff de cada partido terminado."""
    filas = conexion.execute(
        """SELECT p.*, m.fecha_utc, m.local AS equipo_local, m.visitante AS equipo_visitante,
                  m.goles_local, m.goles_visitante
           FROM partidos m
           JOIN predicciones p ON p.id = (
               SELECT p2.id FROM predicciones p2
               WHERE p2.partido_id = m.id AND p2.creado_en < m.fecha_utc
               ORDER BY p2.creado_en DESC, p2.id DESC LIMIT 1
           )
           WHERE m.goles_local IS NOT NULL AND m.goles_visitante IS NOT NULL
           ORDER BY m.fecha_utc""",
    ).fetchall()
    partidos = []
    agregados = {"blend": [], "modelo": [], "mercado": []}
    for fila in filas:
        resultado = _resultado(fila["goles_local"], fila["goles_visitante"])
        variantes = {
            "blend": (fila["p_local"], fila["p_empate"], fila["p_visitante"]),
            "modelo": (fila["p_local_modelo"], fila["p_empate_modelo"],
                       fila["p_visitante_modelo"]),
            "mercado": (fila["p_local_mercado"], fila["p_empate_mercado"],
                        fila["p_visitante_mercado"]),
        }
        metricas = {}
        for nombre, p in variantes.items():
            if None in p:
                continue
            metricas[nombre] = {"brier": brier(p, resultado), "rps": rps(p, resultado)}
            agregados[nombre].append(metricas[nombre])
        partidos.append(
            {
                "partido": f"{fila['equipo_local']} {fila['goles_local']}-"
                           f"{fila['goles_visitante']} {fila['equipo_visitante']}",
                "fecha": fila["fecha_utc"],
                "resultado": ORDEN[resultado],
                "p_local": fila["p_local"],
                "marcador_predicho": fila["marcador"],
                "acerto_marcador": fila["marcador"]
                == f"{fila['goles_local']}-{fila['goles_visitante']}",
                "acerto_1x2": max(ORDEN, key=lambda k, f=fila: f[f"p_{k}"]) == ORDEN[resultado],
                "metricas": metricas,
            }
        )
    informe = {"n": len(partidos), "partidos": partidos}
    for nombre, valores in agregados.items():
        informe[nombre] = {
            "brier": sum(v["brier"] for v in valores) / len(valores) if valores else None,
            "rps": sum(v["rps"] for v in valores) / len(valores) if valores else None,
            "n": len(valores),
        }
    return informe
