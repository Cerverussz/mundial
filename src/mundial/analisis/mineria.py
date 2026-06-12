"""Minería de patrones con control de multiplicidad (BH) sobre datos históricos propios."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass


@dataclass
class Candidato:
    id: str
    familia: str
    hipotesis: str
    filtro: dict
    mercado_objetivo: str
    lado: str
    exitos: int
    n: int
    baseline: float
    p_cruda: float = 1.0
    p_adj: float = 1.0
    reportable: bool = False
    ic95: tuple = (0.0, 1.0)

    def tasa(self) -> float:
        return self.exitos / self.n if self.n else 0.0


def _p_binomial_dos_colas(exitos: int, n: int, p0: float) -> float:
    """Test binomial exacto a dos colas (método de verosimilitud)."""
    from scipy.stats import binom

    p_obs = binom.pmf(exitos, n, p0)
    total = sum(binom.pmf(k, n, p0) for k in range(n + 1) if binom.pmf(k, n, p0) <= p_obs + 1e-12)
    return min(1.0, total)


def _wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = exitos / n
    denominador = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / denominador
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominador
    return max(0.0, centro - margen), min(1.0, centro + margen)


def ajustar_bh(candidatos: list[Candidato], q: float = 0.10, n_minimo: int = 30) -> list[Candidato]:
    validos = [c for c in candidatos if c.n >= n_minimo]
    for c in validos:
        c.p_cruda = _p_binomial_dos_colas(c.exitos, c.n, c.baseline)
        c.ic95 = _wilson(c.exitos, c.n)
    ordenados = sorted(validos, key=lambda c: c.p_cruda)
    m = len(ordenados)
    umbral_k = 0
    for k, c in enumerate(ordenados, start=1):
        if c.p_cruda <= q * k / m:
            umbral_k = k
    for k, c in enumerate(ordenados, start=1):
        c.p_adj = min(1.0, c.p_cruda * m / k)
        c.reportable = k <= umbral_k
    return candidatos


def _tasa_mercado(filas, umbral_goles: float = 2.5) -> tuple[int, int, int, int]:
    """(overs, btts_si, empates_90, n) sobre filas de resultados_wc."""
    overs = sum(1 for f in filas if f["goles90_local"] + f["goles90_visitante"] > umbral_goles)
    btts = sum(1 for f in filas if f["goles90_local"] > 0 and f["goles90_visitante"] > 0)
    empates = sum(1 for f in filas if f["goles90_local"] == f["goles90_visitante"])
    return overs, btts, empates, len(filas)


def minar(conexion: sqlite3.Connection, anio_desde: int = 1994) -> list[Candidato]:
    """Familias parametrizadas → candidatos. Baselines = tasa global de la era."""
    base = conexion.execute(
        "SELECT * FROM resultados_wc WHERE anio >= ?", (anio_desde,)).fetchall()
    if not base:
        return []
    over_b, btts_b, empate_b, n_b = _tasa_mercado(base)
    baselines = {"over@2.5": over_b / n_b, "yes": btts_b / n_b, "empate": empate_b / n_b}
    candidatos: list[Candidato] = []

    def agregar(id_, familia, hipotesis, filtro, filas):
        overs, btts, empates, n = _tasa_mercado(filas)
        for lado, exitos, mercado in (
            ("over@2.5", overs, "over_under_25"), ("yes", btts, "btts"),
            ("empate", empates, "1x2"),
        ):
            candidatos.append(Candidato(
                id=f"{id_}_{lado}", familia=familia, hipotesis=hipotesis, filtro=filtro,
                mercado_objetivo=mercado, lado=lado, exitos=exitos, n=n,
                baseline=baselines[lado]))

    # Familia 1: goles/empates por fase (90 minutos — válido también en KO gracias a score90)
    for fase, etiqueta in ((1, "grupos"), (0, "eliminacion")):
        filas = [f for f in base if f["es_grupos"] == fase]
        agregar(f"fase_{etiqueta}", "goles_por_fase",
                f"tasas de mercado en {etiqueta} vs baseline de la era", {"es_grupos": fase}, filas)
    # Familia 2: tercer puesto
    filas = [f for f in base if "third" in (f["fase"] or "").lower()]
    agregar("tercer_puesto", "goles_por_fase", "el tercer puesto golea",
            {"fase": "third place"}, filas)
    # Familia 3: era con mejores terceros (análogo del formato 2026): 1986-1994
    filas = conexion.execute(
        "SELECT * FROM resultados_wc WHERE anio BETWEEN 1986 AND 1994 AND es_grupos=1").fetchall()
    agregar("grupos_86_94", "formato_terceros",
            "grupos con repechaje de terceros (análogo 2026)", {"es_grupos": 1}, filas)
    # Familia 4: jornada 3 (aprox.: tercer partido del grupo por fecha dentro de cada grupo+año)
    filas = conexion.execute("""
        SELECT * FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY anio, local ORDER BY fecha) AS k
          FROM resultados_wc WHERE es_grupos = 1) WHERE k = 3""").fetchall()
    agregar("jornada3", "dead_rubber", "tercer partido de grupo", {"jornada": 3}, filas)
    return ajustar_bh(candidatos)
