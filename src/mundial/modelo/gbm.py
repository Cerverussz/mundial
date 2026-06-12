"""Capa GBM ordinal (Frank-Hall) con features point-in-time y puerta walk-forward."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np

from mundial.modelo import entrenar
from mundial.modelo.precision import rps

TORNEOS_MAYORES = ("FIFA World Cup", "Copa América", "UEFA Euro", "African Cup of Nations",
                   "AFC Asian Cup", "CONCACAF Championship")

NOMBRES_FEATURES = [
    "diff_ataque", "diff_defensa", "suma_fuerza", "neutral",
    "es_torneo_mayor", "es_clasificatoria", "es_amistoso",
    "descanso_local", "descanso_visitante", "diff_descanso",
    "forma5_local", "forma5_visitante", "diff_forma",
    "goles_favor5_local", "goles_favor5_visitante",
    "goles_contra5_local", "goles_contra5_visitante",
    "partidos365_local", "partidos365_visitante",
    "h2h5_balance", "era_post2018", "mes",
]


def _forma_y_descanso(historial: list, equipo: str, fecha: str) -> dict:
    previos = [h for h in historial if h["fecha"] < fecha][-5:]
    puntos = favor = contra = 0
    for h in previos:
        es_local = h["local"] == equipo
        gf = h["goles_local"] if es_local else h["goles_visitante"]
        gc = h["goles_visitante"] if es_local else h["goles_local"]
        favor += gf
        contra += gc
        puntos += 3 if gf > gc else (1 if gf == gc else 0)
    ultimo = previos[-1]["fecha"] if previos else None
    descanso = (
        min((date.fromisoformat(fecha) - date.fromisoformat(ultimo)).days, 60)
        if ultimo else 60
    )
    from datetime import timedelta
    anio_antes = (date.fromisoformat(fecha) - timedelta(days=365)).isoformat()
    n365 = sum(1 for h in historial if anio_antes <= h["fecha"] < fecha)
    return {"forma5": puntos, "favor5": favor, "contra5": contra,
            "descanso": descanso, "n365": n365}


def construir_features(conexion, desde: str, hasta: str = "2099-01-01"):
    filas = conexion.execute(
        """SELECT fecha, local, visitante, goles_local, goles_visitante, torneo, neutral
           FROM resultados_historicos WHERE fecha >= date(?, '-2 years') AND fecha < ?
           ORDER BY fecha""",
        (desde, hasta),
    ).fetchall()
    por_equipo: dict[str, list] = {}
    for f in filas:
        por_equipo.setdefault(f["local"], []).append(f)
        por_equipo.setdefault(f["visitante"], []).append(f)
    X, y, fechas, meta = [], [], [], []
    for f in filas:
        if f["fecha"] < desde:
            continue
        rl = entrenar.rating_asof(conexion, f["local"], f["fecha"])
        rv = entrenar.rating_asof(conexion, f["visitante"], f["fecha"])
        if rl is None or rv is None:
            continue
        sl = _forma_y_descanso(por_equipo[f["local"]], f["local"], f["fecha"])
        sv = _forma_y_descanso(por_equipo[f["visitante"]], f["visitante"], f["fecha"])
        h2h = [h for h in por_equipo[f["local"]]
               if h["fecha"] < f["fecha"]
               and {h["local"], h["visitante"]} == {f["local"], f["visitante"]}][-5:]
        balance = 0
        for h in h2h:
            d = h["goles_local"] - h["goles_visitante"]
            balance += (1 if d > 0 else (-1 if d < 0 else 0)) * (
                1 if h["local"] == f["local"] else -1)
        torneo = f["torneo"] or ""
        X.append([
            rl["ataque"] - rv["ataque"], rl["defensa"] - rv["defensa"],
            rl["ataque"] + rl["defensa"] + rv["ataque"] + rv["defensa"],
            f["neutral"],
            int(any(t in torneo for t in TORNEOS_MAYORES)),
            int("qualification" in torneo.lower()),
            int(torneo == "Friendly"),
            sl["descanso"], sv["descanso"], sl["descanso"] - sv["descanso"],
            sl["forma5"], sv["forma5"], sl["forma5"] - sv["forma5"],
            sl["favor5"], sv["favor5"], sl["contra5"], sv["contra5"],
            sl["n365"], sv["n365"],
            balance, int(f["fecha"] >= "2018-01-01"), int(f["fecha"][5:7]),
        ])
        d = f["goles_local"] - f["goles_visitante"]
        y.append(0 if d > 0 else (1 if d == 0 else 2))
        fechas.append(f["fecha"])
        meta.append({"local": f["local"], "visitante": f["visitante"], "neutral": f["neutral"]})
    return np.array(X, dtype=float), np.array(y), fechas, NOMBRES_FEATURES, meta


def _entrenar_binario(X, objetivo, monotonia):
    import lightgbm as lgb

    return lgb.train(
        {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31,
         "min_data_in_leaf": 50, "feature_fraction": 0.8, "bagging_fraction": 0.8,
         "bagging_freq": 1, "monotone_constraints": monotonia, "verbose": -1, "seed": 7},
        lgb.Dataset(X, label=objetivo), num_boost_round=200,
    )


def entrenar_ordinal(conexion, desde: str, hasta: str):
    from sklearn.isotonic import IsotonicRegression

    X, y, fechas, nombres, _ = construir_features(conexion, desde, hasta)
    monotonia = [0] * len(nombres)
    monotonia[nombres.index("diff_ataque")] = 1   # más ataque relativo → más P(no perder/ganar)
    monotonia[nombres.index("diff_defensa")] = 1
    modelos, calibradores = {}, {}
    corte = max(int(len(X) * 0.8), 1)  # cola temporal como out-of-fold para la isotónica
    for clave, objetivo in (("no_pierde", (y <= 1).astype(int)), ("gana", (y == 0).astype(int))):
        modelo = _entrenar_binario(X[:corte], objetivo[:corte], monotonia)
        crudo = modelo.predict(X[corte:]) if corte < len(X) else modelo.predict(X)
        objetivo_cal = objetivo[corte:] if corte < len(X) else objetivo
        calibrador = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4)
        calibrador.fit(crudo, objetivo_cal)
        modelos[clave], calibradores[clave] = modelo, calibrador
    return {"modelos": modelos, "calibradores": calibradores, "nombres": nombres}


def predecir_probas(modelo, X) -> np.ndarray:
    p_no_pierde = modelo["calibradores"]["no_pierde"].predict(
        modelo["modelos"]["no_pierde"].predict(X))
    p_gana = modelo["calibradores"]["gana"].predict(modelo["modelos"]["gana"].predict(X))
    p_gana = np.minimum(p_gana, p_no_pierde - 1e-6)  # consistencia ordinal
    probas = np.stack([p_gana, p_no_pierde - p_gana, 1.0 - p_no_pierde], axis=1)
    probas = np.clip(probas, 1e-6, None)
    return probas / probas.sum(axis=1, keepdims=True)


def walk_forward(conexion, bloques=None) -> dict:
    from mundial.modelo import prediccion as pred

    bloques = bloques or [
        ("1996-01-01", "2013-12-31", "2014-01-01", "2015-12-31"),
        ("1996-01-01", "2017-12-31", "2018-01-01", "2019-12-31"),
        ("1996-01-01", "2021-12-31", "2022-01-01", "2023-12-31"),
        ("1996-01-01", "2023-12-31", "2024-01-01", "2026-06-10"),
    ]
    resultado = {"bloques": [], "pasa_puerta": True}
    for desde_tr, hasta_tr, desde_te, hasta_te in bloques:
        modelo = entrenar_ordinal(conexion, desde_tr, hasta_tr)
        X, y, fechas, _, meta = construir_features(conexion, desde_te, hasta_te)
        if not len(X):
            continue
        probas = predecir_probas(modelo, X)
        rps_gbm = float(np.mean([rps(tuple(p), int(o)) for p, o in zip(probas, y)]))
        valores_dc = []
        for k in range(len(X)):
            m = conexion.execute(
                """SELECT * FROM modelo_meta WHERE fecha_ajuste <= ?
                   AND fecha_ajuste LIKE '%-01-01' ORDER BY fecha_ajuste DESC LIMIT 1""",
                (fechas[k],)).fetchone()
            rl = entrenar.rating_asof(conexion, meta[k]["local"], fechas[k])
            rv = entrenar.rating_asof(conexion, meta[k]["visitante"], fechas[k])
            if not (m and rl and rv):
                continue
            ventaja = 0.0 if meta[k]["neutral"] else m["ventaja_local"]
            lam = math.exp(m["mu"] + ventaja + rl["ataque"] - rv["defensa"])
            mu_v = math.exp(m["mu"] + rv["ataque"] - rl["defensa"])
            p = pred.prob_1x2(pred.matriz_marcadores(lam, mu_v, m["rho"]))
            valores_dc.append(rps(p, int(y[k])))
        rps_dc = float(np.mean(valores_dc)) if valores_dc else float("nan")
        resultado["bloques"].append(
            {"train": (desde_tr, hasta_tr), "test": (desde_te, hasta_te),
             "n": int(len(X)), "rps_gbm": rps_gbm, "rps_dc": rps_dc})
        if not (rps_gbm < rps_dc):
            resultado["pasa_puerta"] = False
    return resultado


def shap_partido(modelo, x_fila, n_top: int = 3) -> list[tuple[str, float]]:
    contribs = modelo["modelos"]["gana"].predict(
        x_fila.reshape(1, -1), pred_contrib=True)[0][:-1]  # último = bias
    orden = np.argsort(np.abs(contribs))[::-1][:n_top]
    return [(modelo["nombres"][i], float(contribs[i])) for i in orden]


def pool_log_lineal(distribuciones: list[dict], pesos: list[float]) -> dict:
    claves = distribuciones[0].keys()
    log_p = {k: sum(w * np.log(max(d[k], 1e-12)) for d, w in zip(distribuciones, pesos))
             for k in claves}
    maximo = max(log_p.values())
    exp_p = {k: np.exp(v - maximo) for k, v in log_p.items()}
    total = sum(exp_p.values())
    return {k: v / total for k, v in exp_p.items()}


def guardar(modelo, directorio: Path) -> None:
    import pickle

    directorio.mkdir(parents=True, exist_ok=True)
    for clave, m in modelo["modelos"].items():
        m.save_model(str(directorio / f"{clave}.txt"))
    with open(directorio / "calibradores.pkl", "wb") as f:
        pickle.dump({"calibradores": modelo["calibradores"], "nombres": modelo["nombres"]}, f)


def cargar(directorio: Path):
    import pickle

    import lightgbm as lgb

    if not (directorio / "gana.txt").exists():
        return None
    with open(directorio / "calibradores.pkl", "rb") as f:
        extra = pickle.load(f)
    return {"modelos": {c: lgb.Booster(model_file=str(directorio / f"{c}.txt"))
                        for c in ("no_pierde", "gana")},
            "calibradores": extra["calibradores"], "nombres": extra["nombres"]}
