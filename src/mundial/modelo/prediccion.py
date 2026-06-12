"""Predicción de un partido: Dixon-Coles por capas + blend con mercado + flags de valor."""
from __future__ import annotations

import json
import math
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
from scipy.stats import poisson

from mundial.config import RAIZ
from mundial.factores import contexto, forma, h2h, intangibles, mercado, plantel
from mundial.modelo import confianza as modulo_confianza
from mundial.modelo import explicacion, inversion, mercados
from mundial.modelo.dixon_coles import Ajuste

MAX_GOLES = 10
PESO_MODELO = 0.4
UMBRAL_VALOR = 0.05
UMBRALES_VALOR = {"1x2": 0.05, "over_under_25": 0.04, "btts": 0.04, "draw_no_bet": 0.04}
HORAS_VALOR_SOSTENIDO = 2.0
ANFITRIONES = {"Mexico": "Mexico", "United States": "United States", "Canada": "Canada"}
RESULTADOS = ("local", "empate", "visitante")


@dataclass
class Prediccion:
    partido_id: int
    creado_en: str
    local: str
    visitante: str
    marcador: tuple[int, int]
    top3: list[tuple[int, int, float]]
    p_modelo: dict
    p_mercado: dict
    p_final: dict
    confianza: str
    razones_confianza: list[str]
    factores: list[dict]
    explicacion: list[str]
    valor_flags: list[dict]
    cambios: list[str] | None
    edad_cuotas_h: float | None
    n_casas: int
    matriz: np.ndarray
    mercados: dict


def matriz_marcadores(lam: float, mu: float, rho: float, max_goles: int = MAX_GOLES):
    goles = np.arange(max_goles + 1)
    matriz = np.outer(poisson.pmf(goles, lam), poisson.pmf(goles, mu))
    matriz[0, 0] *= 1.0 - lam * mu * rho
    matriz[0, 1] *= 1.0 + lam * rho
    matriz[1, 0] *= 1.0 + mu * rho
    matriz[1, 1] *= 1.0 - rho
    matriz = np.clip(matriz, 0.0, None)
    return matriz / matriz.sum()


def prob_1x2(matriz) -> tuple[float, float, float]:
    return (
        float(np.tril(matriz, -1).sum()),
        float(np.trace(matriz)),
        float(np.triu(matriz, 1).sum()),
    )


def reescalar_matriz(matriz, objetivo: dict):
    """Reescala cada región (gana local / empate / gana visitante) a las probabilidades dadas."""
    p_local, p_empate, p_visitante = prob_1x2(matriz)
    nueva = matriz.copy()
    indices = np.indices(matriz.shape)
    regiones = [
        (indices[0] > indices[1], objetivo["local"], p_local),
        (indices[0] == indices[1], objetivo["empate"], p_empate),
        (indices[0] < indices[1], objetivo["visitante"], p_visitante),
    ]
    for mascara, deseado, actual in regiones:
        if actual > 0:
            nueva[mascara] *= deseado / actual
    return nueva / nueva.sum()


def marcadores_top(matriz, n: int = 3) -> list[tuple[int, int, float]]:
    planos = np.argsort(matriz, axis=None)[::-1][:n]
    return [
        (int(i), int(j), float(matriz[i, j]))
        for i, j in (np.unravel_index(k, matriz.shape) for k in planos)
    ]


def cargar_ajuste(conexion: sqlite3.Connection) -> Ajuste | None:
    meta = conexion.execute(
        "SELECT * FROM modelo_meta ORDER BY fecha_ajuste DESC LIMIT 1"
    ).fetchone()
    if meta is None:
        return None
    filas = conexion.execute(
        "SELECT * FROM ratings WHERE fecha_ajuste = ?", (meta["fecha_ajuste"],)
    ).fetchall()
    return Ajuste(
        equipos=[f["equipo"] for f in filas],
        ataque={f["equipo"]: f["ataque"] for f in filas},
        defensa={f["equipo"]: f["defensa"] for f in filas},
        mu=meta["mu"],
        ventaja_local=meta["ventaja_local"],
        rho=meta["rho"],
        n_partidos=meta["n_partidos"],
        log_verosimilitud=meta["log_verosimilitud"],
        version=meta["version"],
    )


def _temperatura(conexion, partido_id, cliente_bsd) -> float | None:
    if cliente_bsd is None:
        return None
    vinculo = conexion.execute(
        "SELECT evento_id FROM eventos_bsd WHERE partido_id = ?", (partido_id,)
    ).fetchone()
    if not vinculo:
        return None
    try:
        clima = (cliente_bsd.detalle(vinculo["evento_id"]) or {}).get("weather") or {}
        return clima.get("temperature_c")
    except Exception:
        return None


def _partidos_en_ventana(conexion, equipo: str, referencia: date) -> int:
    desde = (referencia - timedelta(days=3650)).isoformat()
    fila = conexion.execute(
        """SELECT COUNT(*) AS n FROM resultados_historicos
           WHERE (local = ? OR visitante = ?) AND fecha >= ?""",
        (equipo, equipo, desde),
    ).fetchone()
    return fila["n"]


def _commit_datos() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return None


COLUMNAS_PREDICCION = (
    "partido_id", "creado_en", "commit_datos", "version_modelo", "marcador",
    "p_local", "p_empate", "p_visitante",
    "p_local_modelo", "p_empate_modelo", "p_visitante_modelo",
    "p_local_mercado", "p_empate_mercado", "p_visitante_mercado",
    "matriz_json", "confianza", "razones_confianza", "factores_json", "valor_flags",
    "mercados_json",
)


def cargar_exportadas(conexion: sqlite3.Connection, directorio=None) -> int:
    """Importa predicciones exportadas al repo (JSONL); idempotente por (partido, momento)."""
    from mundial.config import DIR_PREDICCIONES

    directorio = directorio or DIR_PREDICCIONES
    if not directorio.exists():
        return 0
    columnas = ", ".join(COLUMNAS_PREDICCION)
    marcadores = ", ".join(f":{c}" for c in COLUMNAS_PREDICCION)
    insertadas = 0
    for ruta in sorted(directorio.glob("*.jsonl")):
        with open(ruta, encoding="utf-8") as archivo:
            for linea in archivo:
                if not linea.strip():
                    continue
                datos = json.loads(linea)
                datos.setdefault("mercados_json", None)  # JSONL antiguo sin la clave
                cursor = conexion.execute(
                    f"INSERT OR IGNORE INTO predicciones ({columnas}) VALUES ({marcadores})",
                    datos,
                )
                insertadas += cursor.rowcount
    conexion.commit()
    return insertadas


def _flags_mercado(conexion, partido_id, mercado_clave, p_propias, ahora):
    p_mkt, _, _ = mercado.cuotas_consenso_mercado(conexion, partido_id, mercado_clave)
    if not p_mkt:
        return []
    previas, _, _ = mercado.cuotas_consenso_mercado(
        conexion, partido_id, mercado_clave,
        hasta=(ahora - timedelta(hours=HORAS_VALOR_SOSTENIDO)).isoformat())
    flags = []
    for seleccion, p in p_propias.items():
        margen = p - p_mkt.get(seleccion, 1.0)
        if margen > UMBRALES_VALOR[mercado_clave]:
            sostenida = bool(
                previas and (p - previas.get(seleccion, 1.0)) > UMBRALES_VALOR[mercado_clave]
            )
            flags.append({"mercado": mercado_clave, "seleccion": seleccion,
                          "resultado": seleccion, "margen": round(margen, 4),
                          "sostenida": sostenida})
    return flags


def predecir(
    conexion: sqlite3.Connection,
    partido_id: int,
    ahora: datetime | None = None,
    peso_modelo: float = PESO_MODELO,
    cliente_bsd=None,
    dir_exportacion=None,
) -> Prediccion:
    ahora = ahora or datetime.now(timezone.utc)
    referencia = ahora.date()
    partido = conexion.execute(
        "SELECT * FROM partidos WHERE id = ?", (partido_id,)
    ).fetchone()
    if partido is None:
        raise ValueError(f"Partido {partido_id} no existe en la base local")
    ajuste = cargar_ajuste(conexion)
    if ajuste is None:
        raise RuntimeError("No hay ratings ajustados: corre `mundial ratings` primero")
    local, visitante = partido["local"], partido["visitante"]
    for equipo in (local, visitante):
        if equipo not in ajuste.ataque:
            raise RuntimeError(f"{equipo} no tiene rating (¿mapeo de nombres?)")

    estadio = conexion.execute(
        "SELECT * FROM estadios WHERE nombre = ?", (partido["estadio"],)
    ).fetchone()
    pais = estadio["pais"] if estadio else None
    altitud = estadio["altitud_m"] if estadio else None
    ventaja = ajuste.ventaja_local if (pais and ANFITRIONES.get(local) == pais) else 0.0

    lam = math.exp(ajuste.mu + ventaja + ajuste.ataque[local] - ajuste.defensa[visitante])
    mu_v = math.exp(ajuste.mu + ajuste.ataque[visitante] - ajuste.defensa[local])

    factores: list[dict] = []
    if ventaja:
        factores.append({"nombre": "localía real", "local": math.exp(ventaja),
                         "visitante": 1.0, "detalle": f"{local} juega en casa"})
    forma_local = forma.factor_forma(conexion, local, referencia, ajuste)
    forma_visitante = forma.factor_forma(conexion, visitante, referencia, ajuste)
    factores.append({"nombre": f"forma {local}", "local": forma_local.ataque,
                     "visitante": round(1.0 / forma_local.defensa, 4),
                     "detalle": forma_local.detalle})
    factores.append({"nombre": f"forma {visitante}", "visitante": forma_visitante.ataque,
                     "local": round(1.0 / forma_visitante.defensa, 4),
                     "detalle": forma_visitante.detalle})
    factores.append({"nombre": "altitud",
                     "local": contexto.factor_altitud(local, altitud),
                     "visitante": contexto.factor_altitud(visitante, altitud),
                     "detalle": f"{altitud:.0f} m" if altitud else "sin dato de estadio"})
    factores.append({"nombre": "descanso",
                     "local": contexto.factor_descanso(conexion, local, partido["fecha_utc"]),
                     "visitante": contexto.factor_descanso(conexion, visitante, partido["fecha_utc"]),
                     "detalle": None})
    temperatura = _temperatura(conexion, partido_id, cliente_bsd)
    factor_clima = contexto.factor_clima(temperatura)
    factores.append({"nombre": "clima", "local": factor_clima, "visitante": factor_clima,
                     "detalle": f"{temperatura:.0f} °C" if temperatura is not None
                     else "sin dato de clima"})
    factor_h2h_local, factor_h2h_visitante = h2h.factor_h2h(conexion, local, visitante, referencia)
    factores.append({"nombre": "historial directo", "local": factor_h2h_local,
                     "visitante": factor_h2h_visitante, "detalle": "peso bajo por diseño"})
    plantel_local = plantel.factor_plantel(conexion, partido_id, local)
    plantel_visitante = plantel.factor_plantel(conexion, partido_id, visitante)
    factores.append({"nombre": f"bajas {local}", "local": plantel_local.propio,
                     "visitante": round(2.0 - plantel_local.propio, 4),
                     "detalle": plantel_local.detalle})
    factores.append({"nombre": f"bajas {visitante}", "visitante": plantel_visitante.propio,
                     "local": round(2.0 - plantel_visitante.propio, 4),
                     "detalle": plantel_visitante.detalle})
    factor_fase, razon_fase = intangibles.factor_fase(partido["fase"], partido["jornada"])
    factores.append({"nombre": "fase del torneo", "local": factor_fase,
                     "visitante": factor_fase, "detalle": razon_fase})

    for f in factores:
        lam *= f.get("local", 1.0)
        mu_v *= f.get("visitante", 1.0)

    matriz = matriz_marcadores(lam, mu_v, ajuste.rho)
    p_local, p_empate, p_visitante = prob_1x2(matriz)
    p_modelo = {"local": p_local, "empate": p_empate, "visitante": p_visitante}

    p_mercado, n_casas, capturado_en = mercado.cuotas_consenso(conexion, partido_id)
    edad_cuotas_h = None
    if capturado_en:
        edad_cuotas_h = (
            ahora - datetime.fromisoformat(capturado_en.replace("Z", "+00:00"))
        ).total_seconds() / 3600.0

    # Blend en espacio lambda cuando el mercado da DNB y O/U 2.5; si no, fallback 1X2.
    origen_matriz = "reescalado_1x2"
    matriz_final = matriz
    if p_mercado:
        p_final = {
            k: peso_modelo * p_modelo[k] + (1.0 - peso_modelo) * p_mercado[k]
            for k in RESULTADOS
        }
        p_dnb, _, _ = mercado.cuotas_consenso_mercado(conexion, partido_id, "draw_no_bet")
        p_ou, _, _ = mercado.cuotas_consenso_mercado(conexion, partido_id, "over_under_25")
        invertido = None
        if p_dnb and p_ou:
            invertido = inversion.invertir_lambdas(
                p_dnb.get("HOME", 0.5), p_ou.get("over@2.5", 0.5), ajuste.rho
            )
        if invertido:
            lam_b = peso_modelo * lam + (1.0 - peso_modelo) * invertido[0]
            mu_b = peso_modelo * mu_v + (1.0 - peso_modelo) * invertido[1]
            matriz_final = matriz_marcadores(lam_b, mu_b, ajuste.rho)
            origen_matriz = "blend_lambda"
        matriz_final = reescalar_matriz(matriz_final, p_final)  # contrato 1X2 intacto
    else:
        p_final = dict(p_modelo)

    precios = {
        "origen_matriz": origen_matriz,
        "over_under_25": {
            "p_over": mercados.prob_over(matriz_final, 2.5),
            "p_under": mercados.prob_under(matriz_final, 2.5),
            "justa_over": mercados.cuota_justa_total(matriz_final, 2.5, "over"),
            "justa_under": mercados.cuota_justa_total(matriz_final, 2.5, "under"),
        },
        "btts": {"p_si": mercados.prob_btts(matriz_final)},
        "dnb": dict(zip(("justa_local", "justa_visitante"),
                        mercados.cuotas_justas_dnb(matriz_final))),
        "ah": {f"{h:+.2f}": mercados.cuota_justa_ah(matriz_final, h)
               for h in (-2.0, -1.5, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 1.5, 2.0)},
    }

    valor_flags = []
    if p_mercado:
        anterior_mercado, _, _ = mercado.cuotas_consenso(
            conexion, partido_id,
            hasta=(ahora - timedelta(hours=HORAS_VALOR_SOSTENIDO)).isoformat(),
        )
        for k in RESULTADOS:
            margen = p_modelo[k] - p_mercado[k]
            if margen > UMBRAL_VALOR:
                sostenida = bool(
                    anterior_mercado and (p_modelo[k] - anterior_mercado[k]) > UMBRAL_VALOR
                )
                valor_flags.append(
                    {"mercado": "1x2", "seleccion": k, "resultado": k,
                     "margen": round(margen, 4), "sostenida": sostenida}
                )
        valor_flags += _flags_mercado(
            conexion, partido_id, "over_under_25",
            {"over@2.5": precios["over_under_25"]["p_over"],
             "under@2.5": precios["over_under_25"]["p_under"]}, ahora)
        valor_flags += _flags_mercado(
            conexion, partido_id, "btts",
            {"yes": precios["btts"]["p_si"], "no": 1.0 - precios["btts"]["p_si"]}, ahora)
        dnb_local = mercados.resultado_ah(matriz_final, 0.0)
        p_dnb_propia = dnb_local["p_gana"] / (dnb_local["p_gana"] + dnb_local["p_pierde"])
        valor_flags += _flags_mercado(
            conexion, partido_id, "draw_no_bet",
            {"HOME": p_dnb_propia, "AWAY": 1.0 - p_dnb_propia}, ahora)

    divergencia = max(abs(p_modelo[k] - p_mercado[k]) for k in RESULTADOS) if p_mercado else 0.0
    bajas_info = conexion.execute(
        "SELECT 1 FROM eventos_bsd WHERE partido_id = ?", (partido_id,)
    ).fetchone() is not None
    nivel, razones = modulo_confianza.calcular(
        divergencia=divergencia,
        edad_cuotas_h=edad_cuotas_h,
        n_casas=n_casas,
        forma_ok_local="insuficiente" not in forma_local.detalle,
        forma_ok_visitante="insuficiente" not in forma_visitante.detalle,
        partidos_local=_partidos_en_ventana(conexion, local, referencia),
        partidos_visitante=_partidos_en_ventana(conexion, visitante, referencia),
        bajas_info=bajas_info,
    )
    if razon_fase:
        razones = razones + [razon_fase]

    top3 = marcadores_top(matriz_final, 3)
    marcador = (top3[0][0], top3[0][1])
    lineas = explicacion.generar(factores, p_modelo, p_mercado, n_casas)

    anterior = conexion.execute(
        """SELECT * FROM predicciones WHERE partido_id = ?
           ORDER BY creado_en DESC, id DESC LIMIT 1""",
        (partido_id,),
    ).fetchone()
    cambios = None
    if anterior:
        cambios = []
        delta = (p_final["local"] - anterior["p_local"]) * 100
        if abs(delta) >= 0.5:
            cambios.append(f"P(gana {local}) {delta:+.1f} pts desde la última consulta")
        marcador_previo = anterior["marcador"]
        if marcador_previo != f"{marcador[0]}-{marcador[1]}":
            cambios.append(f"marcador más probable cambió: {marcador_previo} → "
                           f"{marcador[0]}-{marcador[1]}")
        if anterior["p_local_mercado"] and p_mercado:
            delta_mercado = (p_mercado["local"] - anterior["p_local_mercado"]) * 100
            if abs(delta_mercado) >= 0.5:
                cambios.append(f"el mercado movió P(gana {local}) {delta_mercado:+.1f} pts")
        if not cambios:
            cambios.append("sin cambios relevantes")

    resultado = Prediccion(
        partido_id=partido_id,
        creado_en=ahora.isoformat(),
        local=local,
        visitante=visitante,
        marcador=marcador,
        top3=top3,
        p_modelo=p_modelo,
        p_mercado=p_mercado,
        p_final=p_final,
        confianza=nivel,
        razones_confianza=razones,
        factores=factores,
        explicacion=lineas,
        valor_flags=valor_flags,
        cambios=cambios,
        edad_cuotas_h=edad_cuotas_h,
        n_casas=n_casas,
        matriz=matriz_final,
        mercados=precios,
    )
    fila = dict(
        zip(
            COLUMNAS_PREDICCION,
            (
                partido_id, resultado.creado_en, _commit_datos(), ajuste.version,
                f"{marcador[0]}-{marcador[1]}",
                p_final["local"], p_final["empate"], p_final["visitante"],
                p_modelo["local"], p_modelo["empate"], p_modelo["visitante"],
                p_mercado.get("local"), p_mercado.get("empate"), p_mercado.get("visitante"),
                json.dumps(matriz_final.tolist()), nivel,
                json.dumps(razones, ensure_ascii=False),
                json.dumps(factores, ensure_ascii=False),
                json.dumps(valor_flags, ensure_ascii=False),
                json.dumps(precios, ensure_ascii=False),
            ),
        )
    )
    columnas = ", ".join(COLUMNAS_PREDICCION)
    marcadores_sql = ", ".join(f":{c}" for c in COLUMNAS_PREDICCION)
    conexion.execute(
        f"INSERT OR IGNORE INTO predicciones ({columnas}) VALUES ({marcadores_sql})", fila
    )
    conexion.commit()
    if dir_exportacion is not None:
        dir_exportacion.mkdir(parents=True, exist_ok=True)
        ruta = dir_exportacion / f"{resultado.creado_en[:10]}.jsonl"
        with open(ruta, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return resultado
