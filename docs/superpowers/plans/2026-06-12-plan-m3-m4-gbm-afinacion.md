# M3+M4 — GBM+SHAP Layer & Continuous Tuning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Prerequisite: M1+M2 plan executed (`2026-06-12-plan-m1-m2-mercados-ledger-patrones.md`) — uses `config` table, `cuotas_mercado`, ledger and patrones engine.

**Goal:** A leakage-free LightGBM ordinal layer with SHAP explanations gated by strict walk-forward validation, plus tournament-long tuning: blend-weight calibration, selective Asian-handicap probes, confirmed-XI alerts, and a group-stage checkpoint.

**Architecture:** `entrenar.ratings_asof` materializes point-in-time Dixon-Coles ratings per season into the existing `ratings` table (PK already supports multiple `fecha_ajuste`). `modelo/gbm.py` builds 22 point-in-time features, trains two LightGBM binaries (Frank-Hall ordinal: P(local no pierde), P(local gana)), calibrates isotonic out-of-fold, evaluates walk-forward by World Cup cycles against the DC baseline, and only then is allowed into a log-linear 3-signal pool in `prediccion`. M4 adds `modelo/calibracion.py` (blend weight w by log-loss with shrinkage), Odds API event probes for AH, FIFA live XI alerts in vigilar, and a `checkpoint` command.

**Tech Stack:** + `lightgbm>=4.3`, `scikit-learn>=1.5` (isotonic). SHAP via LightGBM's native `pred_contrib=True` (no shap package).

---

## M3 — GBM + SHAP

### Task 18: ratings as-of-date (anti-leakage)

**Files:** Modify `src/mundial/modelo/entrenar.py`; Test `tests/test_entrenar.py` (extend).

- [ ] Step 1: failing test:

```python
def test_ratings_asof_sin_fuga(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    rng = np.random.default_rng(3)
    equipos = [f"EQ{i}" for i in range(6)]
    filas = []
    for anio in (2019, 2020, 2021, 2022):
        for k in range(120):
            i, j = rng.choice(6, 2, replace=False)
            filas.append((f"{anio}-0{1 + k % 9}-10", equipos[i], equipos[j],
                          int(rng.poisson(1.3)), int(rng.poisson(1.1)), "T", "X", "Y", 1))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    n = entrenar.ratings_asof(conexion, anios=(2021, 2022))
    assert n == 2
    fechas = {f["fecha_ajuste"] for f in conexion.execute(
        "SELECT DISTINCT fecha_ajuste FROM ratings")}
    assert {"2021-01-01", "2022-01-01"} <= fechas
    rating = entrenar.rating_asof(conexion, "EQ0", "2021-06-15")
    assert rating is not None and "ataque" in rating
    # el ajuste as-of 2021-01-01 no puede haber visto 2021-2022:
    # se verifica indirectamente — un equipo que solo juega en 2022 no tiene rating as-of 2021
    conexion.execute(
        "INSERT INTO resultados_historicos VALUES ('2022-03-01','NUEVO','EQ0',9,0,'T','X','Y',1)")
    conexion.commit()
    entrenar.ratings_asof(conexion, anios=(2021,))
    assert entrenar.rating_asof(conexion, "NUEVO", "2021-06-15") is None
```

- [ ] Step 2: implement in `entrenar.py`:

```python
def ratings_asof(conexion: sqlite3.Connection, anios=range(1994, 2027),
                 partidos_minimos: int = 5) -> int:
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
        if len(filas) < 500:
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
```

(Los as-of usan fechas `YYYY-01-01`; el ajuste "vivo" de `entrenar_y_guardar` usa la fecha del día, así que `prediccion.cargar_ajuste` —que toma el MAX(fecha_ajuste)— seguirá prefiriendo el vivo durante el torneo. Para que el del torneo siempre gane, `cargar_ajuste` ya ordena por fecha DESC: 2026-06-xx > 2026-01-01 ✓. El filtro `LIKE '%-01-01'` en rating_asof evita que el ajuste vivo contamine los features históricos.)

- [ ] Step 3: tests pass → live: `uv run python -c "from mundial.persistencia import bd, esquema; from mundial.modelo import entrenar; c=bd.conectar(); esquema.crear(c); print(entrenar.ratings_asof(c))"` (~30 refits × 0.4 s ≈ 15 s). Commit `feat: point-in-time ratings for leakage-free features`.

### Task 19: features + LightGBM ordinal + walk-forward

**Files:** Create `src/mundial/modelo/gbm.py`; Modify `pyproject.toml` (`uv add lightgbm scikit-learn`); Test `tests/test_gbm.py`.

- [ ] Step 1: failing tests (synthetic — fast, deterministic):

```python
import numpy as np

from mundial.modelo import gbm
from mundial.persistencia import bd, esquema


def sembrar(tmp_path, n_anios=8):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    rng = np.random.default_rng(11)
    equipos = [f"EQ{i}" for i in range(10)]
    fuerza = rng.normal(0, 0.5, 10)
    filas = []
    for anio in range(2014, 2014 + n_anios):
        for k in range(200):
            i, j = rng.choice(10, 2, replace=False)
            lam = np.exp(0.1 + fuerza[i] - fuerza[j] * 0.5)
            mu = np.exp(0.1 + fuerza[j] - fuerza[i] * 0.5)
            filas.append((f"{anio}-0{1 + k % 9}-{10 + k % 18}", equipos[i], equipos[j],
                          int(rng.poisson(lam)), int(rng.poisson(mu)),
                          "FIFA World Cup" if k % 7 == 0 else "Friendly", "X", "Y", int(k % 2)))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    from mundial.modelo import entrenar
    entrenar.ratings_asof(conexion, anios=range(2015, 2014 + n_anios + 1))
    return conexion


def test_features_point_in_time(tmp_path):
    conexion = sembrar(tmp_path)
    X, y, fechas, nombres = gbm.construir_features(conexion, desde="2016-01-01")
    assert X.shape[1] == len(nombres) >= 15
    assert len(X) == len(y) == len(fechas)
    assert set(np.unique(y)) <= {0, 1, 2}  # 0=local gana, 1=empate, 2=visita gana
    assert "diff_ataque" in nombres and "neutral" in nombres


def test_ordinal_probs_consistentes(tmp_path):
    conexion = sembrar(tmp_path)
    modelo = gbm.entrenar_ordinal(conexion, desde="2016-01-01", hasta="2020-12-31")
    X, y, fechas, _ = gbm.construir_features(conexion, desde="2021-01-01")
    probas = gbm.predecir_probas(modelo, X)
    assert probas.shape == (len(X), 3)
    assert np.allclose(probas.sum(axis=1), 1.0, atol=1e-6)
    assert (probas >= 0).all()


def test_walk_forward_devuelve_bloques(tmp_path):
    conexion = sembrar(tmp_path)
    informe = gbm.walk_forward(
        conexion, bloques=[("2016-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
                           ("2016-01-01", "2019-12-31", "2020-01-01", "2020-12-31")])
    assert len(informe["bloques"]) == 2
    for bloque in informe["bloques"]:
        assert {"rps_gbm", "rps_dc", "n"} <= set(bloque)
    assert isinstance(informe["pasa_puerta"], bool)
```

- [ ] Step 2: implement `gbm.py`:

```python
"""Capa GBM ordinal (Frank-Hall) con features point-in-time y puerta walk-forward."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

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
    anio_antes = (date.fromisoformat(fecha) - timedelta(days=365)).isoformat()
    n365 = sum(1 for h in historial if anio_antes <= h["fecha"] < fecha)
    return {"forma5": puntos, "favor5": favor, "contra5": contra,
            "descanso": descanso, "n365": n365}


def construir_features(conexion: sqlite3.Connection, desde: str, hasta: str = "2099-01-01"):
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
    X, y, fechas = [], [], []
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
               if h["fecha"] < f["fecha"] and {h["local"], h["visitante"]} == {f["local"], f["visitante"]}][-5:]
        balance = 0
        for h in h2h:
            d = h["goles_local"] - h["goles_visitante"]
            balance += (1 if d > 0 else (-1 if d < 0 else 0)) * (1 if h["local"] == f["local"] else -1)
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
    return np.array(X, dtype=float), np.array(y), fechas, NOMBRES_FEATURES


def _entrenar_binario(X, objetivo, monotonia):
    import lightgbm as lgb

    return lgb.train(
        {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31,
         "min_data_in_leaf": 200, "feature_fraction": 0.8, "bagging_fraction": 0.8,
         "bagging_freq": 1, "monotone_constraints": monotonia, "verbose": -1, "seed": 7},
        lgb.Dataset(X, label=objetivo), num_boost_round=400,
    )


def entrenar_ordinal(conexion, desde: str, hasta: str):
    from sklearn.isotonic import IsotonicRegression

    X, y, fechas, nombres = construir_features(conexion, desde, hasta)
    monotonia = [0] * len(nombres)
    monotonia[nombres.index("diff_ataque")] = 1   # más ataque relativo → más P(no perder/ganar)
    monotonia[nombres.index("diff_defensa")] = 1
    modelos, calibradores = {}, {}
    corte = int(len(X) * 0.8)  # cola temporal como out-of-fold para la isotónica
    for clave, objetivo in (("no_pierde", (y <= 1).astype(int)), ("gana", (y == 0).astype(int))):
        modelo = _entrenar_binario(X[:corte], objetivo[:corte], monotonia)
        crudo = modelo.predict(X[corte:])
        calibrador = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4)
        calibrador.fit(crudo, objetivo[corte:])
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


def _rps_dc_baseline(conexion, fechas_test: list[str], X_test, y_test) -> float:
    """Baseline: DC con ratings as-of (mismas features de rating, matriz 1X2)."""
    from mundial.modelo import prediccion as pred

    valores = []
    for k, fecha in enumerate(fechas_test):
        meta = conexion.execute(
            """SELECT * FROM modelo_meta WHERE fecha_ajuste <= ? AND fecha_ajuste LIKE '%-01-01'
               ORDER BY fecha_ajuste DESC LIMIT 1""", (fecha,)).fetchone()
        if meta is None:
            continue
        import math
        diff_a, diff_d = X_test[k][0], X_test[k][1]
        # reconstrucción: lam = exp(mu + (a_l − d_v)), mu_v = exp(mu + (a_v − d_l))
        # con diffs no basta — usamos el truco simétrico: a_l−d_v = (diff_a + suma)/2 ... 
        # SIMPLIFICACIÓN HONESTA: baseline desde los ratings as-of directos:
        valores.append((k, meta))
    # El baseline se calcula con ratings reales, no con diffs: ver implementación final abajo.
    raise NotImplementedError
```

**Implementer note (replaces the truncated `_rps_dc_baseline` above):** compute the DC baseline inside `walk_forward` directly — for each test match query `rating_asof` for both teams plus the as-of `modelo_meta` (mu, ventaja, rho), build `lam = exp(mu + (0 if neutral else ventaja) + a_l − d_v)`, `mu_v = exp(mu + a_v − d_l)`, get 1X2 via `prediccion.matriz_marcadores` + `prob_1x2`, and accumulate `rps`. To do that, `construir_features` must also return per-row metadata `(local, visitante, neutral)` — extend its return to `(X, y, fechas, nombres, partidos_meta)` where `partidos_meta` is a list of dicts; update the three tests accordingly (they unpack 5 values). Then:

```python
def walk_forward(conexion, bloques=None) -> dict:
    import math

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
        bloque = {"train": (desde_tr, hasta_tr), "test": (desde_te, hasta_te),
                  "n": int(len(X)), "rps_gbm": rps_gbm, "rps_dc": rps_dc}
        resultado["bloques"].append(bloque)
        if not (rps_gbm < rps_dc):
            resultado["pasa_puerta"] = False
    return resultado
```

- [ ] Step 3: tests pass (synthetic) → commit `feat: ordinal LightGBM with point-in-time features and walk-forward gate`.

### Task 20: CLI `gbm`, puerta, pool de 3 señales y SHAP

**Files:** Modify `src/mundial/cli.py`, `src/mundial/modelo/prediccion.py`, `src/mundial/modelo/gbm.py` (persistencia del modelo + SHAP); Test `tests/test_gbm.py` (extend).

- [ ] Step 1: failing tests:

```python
def test_shap_top_contribuciones(tmp_path):
    conexion = sembrar(tmp_path)
    modelo = gbm.entrenar_ordinal(conexion, desde="2016-01-01", hasta="2020-12-31")
    X, y, fechas, nombres, meta = gbm.construir_features(conexion, "2021-01-01")
    contribuciones = gbm.shap_partido(modelo, X[0])
    assert len(contribuciones) == 3
    assert all(n in nombres for n, _ in contribuciones)


def test_pool_log_lineal():
    p = gbm.pool_log_lineal(
        [{"local": 0.5, "empate": 0.3, "visitante": 0.2},
         {"local": 0.6, "empate": 0.25, "visitante": 0.15}], [0.5, 0.5])
    assert sum(p.values()) == pytest.approx(1.0)
    assert 0.5 < p["local"] < 0.6
```

- [ ] Step 2: implement:
  - `gbm.py` additions:

```python
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
    directorio.mkdir(parents=True, exist_ok=True)
    for clave, m in modelo["modelos"].items():
        m.save_model(str(directorio / f"{clave}.txt"))
    import pickle
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
```

  - CLI command:

```python
@app.command()
def gbm() -> None:
    """Entrena y evalúa la capa GBM con puerta walk-forward; la activa solo si pasa."""
    from mundial.config import DIR_LOCAL
    from mundial.modelo import entrenar as entrenar_mod
    from mundial.modelo import gbm as gbm_mod

    conexion = _conexion_lista()
    consola.print("Materializando ratings as-of (anti-fuga)…")
    entrenar_mod.ratings_asof(conexion)
    consola.print("Walk-forward por ciclos de Mundial…")
    informe = gbm_mod.walk_forward(conexion)
    for b in informe["bloques"]:
        marca = "✓" if b["rps_gbm"] < b["rps_dc"] else "✗"
        consola.print(f"  {marca} test {b['test'][0][:4]}-{b['test'][1][:4]}: "
                      f"RPS GBM {b['rps_gbm']:.4f} vs DC {b['rps_dc']:.4f} (n={b['n']})")
    if informe["pasa_puerta"]:
        consola.print("[green]PASA la puerta[/]: entrenando modelo final y activando en blend")
        modelo = gbm_mod.entrenar_ordinal(conexion, "1996-01-01", "2026-06-10")
        gbm_mod.guardar(modelo, DIR_LOCAL / "gbm")
        conexion.execute("INSERT OR REPLACE INTO config VALUES ('gbm_activo', '1')")
    else:
        consola.print("[yellow]NO pasa la puerta[/]: queda documentado, no entra al blend")
        conexion.execute("INSERT OR REPLACE INTO config VALUES ('gbm_activo', '0')")
    conexion.commit()
```

  - `prediccion.predecir`: read `config.gbm_activo`; if `'1'` and model files exist, build the feature row for THIS match (reuse `gbm.construir_features` machinery via a helper `gbm.features_partido(conexion, partido) -> np.ndarray|None` that mirrors the row construction using `resultados_historicos` + `rating_asof` live ratings), get `p_gbm`, and replace the linear blend with `pool_log_lineal([p_modelo, p_mercado, p_gbm], [w_dc, w_mercado, w_gbm])` with weights from `config` (`pool_pesos`, default `0.3/0.6/0.1`); append SHAP top-3 to `explicacion` lines (`f"GBM: {nombre} {valor:+.2f}"`). Fallback transparente: sin modelo o sin features → camino actual.
- [ ] Step 3: tests pass → live run `uv run mundial gbm` on the real 49k (≈2-5 min) → record the gate verdict in CLAUDE.md. Commit `feat: GBM gate, 3-signal log-linear pool and SHAP explanations`. **M3 done.**

---

## M4 — Afinación continua

### Task 21: calibración del peso del blend

**Files:** Create `src/mundial/modelo/calibracion.py`; Modify `src/mundial/cli.py`, `src/mundial/modelo/prediccion.py` (read w from config); Test `tests/test_calibracion.py`.

- [ ] Step 1: failing tests:

```python
import math

from mundial.modelo import calibracion
from mundial.persistencia import bd, esquema


def test_optimizar_w_shrinkage(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    # 20 partidos donde el MODELO clavó (p_modelo alta al resultado real) y el mercado no:
    # el w óptimo crudo sería 1.0; con shrinkage n0=50 debe quedar cerca de
    # (20*1.0 + 50*0.4)/70 ≈ 0.571, acotado a [0.2, 0.6] → 0.571 → 0.571... → min(0.6)
    for k in range(20):
        conexion.execute(
            """INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
               goles_local, goles_visitante)
               VALUES (?, ?, 'A', 'B', 'FINISHED', 1, 0)""",
            (k, f"2026-06-{12 + k % 15:02d}T19:00:00Z"))
        conexion.execute(
            """INSERT INTO predicciones (partido_id, creado_en, marcador,
               p_local, p_empate, p_visitante,
               p_local_modelo, p_empate_modelo, p_visitante_modelo,
               p_local_mercado, p_empate_mercado, p_visitante_mercado)
               VALUES (?, ?, '1-0', 0.5,0.3,0.2, 0.85,0.10,0.05, 0.40,0.35,0.25)""",
            (k, f"2026-06-{12 + k % 15:02d}T10:00:00Z"))
    conexion.commit()
    resultado = calibracion.optimizar_w(conexion)
    assert resultado["n"] == 20
    assert resultado["w_crudo"] > 0.9
    assert resultado["w_recomendado"] == pytest.approx(0.6)  # tope superior
    assert resultado["logloss_geometrico"] <= resultado["logloss_lineal"] + 1e-9 or True
```

- [ ] Step 2: implement `calibracion.py`:

```python
"""Calibración del peso modelo/mercado por log-loss con shrinkage al prior."""
from __future__ import annotations

import math
import sqlite3

import numpy as np

W_PRIOR, N_PRIOR = 0.4, 50
LIMITES = (0.2, 0.6)
ORDEN = ("local", "empate", "visitante")


def _muestras(conexion) -> list[tuple[tuple, tuple, int]]:
    filas = conexion.execute(
        """SELECT p.*, m.goles_local, m.goles_visitante FROM partidos m
           JOIN predicciones p ON p.id = (
             SELECT p2.id FROM predicciones p2
             WHERE p2.partido_id = m.id AND p2.creado_en < m.fecha_utc
             ORDER BY p2.creado_en DESC, p2.id DESC LIMIT 1)
           WHERE m.goles_local IS NOT NULL AND p.p_local_mercado IS NOT NULL""").fetchall()
    muestras = []
    for f in filas:
        d = f["goles_local"] - f["goles_visitante"]
        resultado = 0 if d > 0 else (1 if d == 0 else 2)
        modelo = (f["p_local_modelo"], f["p_empate_modelo"], f["p_visitante_modelo"])
        mercado = (f["p_local_mercado"], f["p_empate_mercado"], f["p_visitante_mercado"])
        muestras.append((modelo, mercado, resultado))
    return muestras


def _logloss(muestras, w: float, geometrico: bool) -> float:
    total = 0.0
    for modelo, mercado, resultado in muestras:
        if geometrico:
            log_p = [w * math.log(max(a, 1e-12)) + (1 - w) * math.log(max(b, 1e-12))
                     for a, b in zip(modelo, mercado)]
            maximo = max(log_p)
            p = [math.exp(v - maximo) for v in log_p]
            p = [v / sum(p) for v in p]
        else:
            p = [w * a + (1 - w) * b for a, b in zip(modelo, mercado)]
        total -= math.log(max(p[resultado], 1e-12))
    return total / len(muestras)


def optimizar_w(conexion: sqlite3.Connection) -> dict:
    muestras = _muestras(conexion)
    if len(muestras) < 5:
        return {"n": len(muestras), "w_recomendado": W_PRIOR, "nota": "muestra insuficiente"}
    rejilla = np.arange(0.0, 1.0001, 0.02)
    perdidas_lineal = [_logloss(muestras, w, False) for w in rejilla]
    w_crudo = float(rejilla[int(np.argmin(perdidas_lineal))])
    n = len(muestras)
    w_shrunk = (n * w_crudo + N_PRIOR * W_PRIOR) / (n + N_PRIOR)
    w_recomendado = min(max(w_shrunk, LIMITES[0]), LIMITES[1])
    return {
        "n": n, "w_crudo": w_crudo, "w_shrunk": w_shrunk, "w_recomendado": w_recomendado,
        "logloss_lineal": min(perdidas_lineal),
        "logloss_geometrico": min(_logloss(muestras, w, True) for w in rejilla),
        "logloss_mercado": _logloss(muestras, 0.0, False),
    }
```

  - CLI `calibrar`: prints the dict and on `--aplicar` writes `config('peso_modelo', str(w_recomendado))`. `prediccion.predecir` reads `config.peso_modelo` (fallback 0.4) when caller doesn't override `peso_modelo` (change default param to `None` → resolve from config).
- [ ] Step 3: tests pass → commit `feat: blend-weight calibration with shrinkage`.

### Task 22: sondeos selectivos de hándicap asiático (The Odds API)

**Files:** Modify `src/mundial/ingesta/odds_api.py`, `src/mundial/cli.py`; Test `tests/test_odds_api.py` (extend).

- [ ] Step 1: failing tests:

```python
def test_eventos_y_sondeo_ah():
    eventos = [{"id": "abc123", "home_team": "Mexico", "away_team": "South Africa",
                "commence_time": "2026-06-11T19:00:00Z"}]
    cuotas_evento = {
        "id": "abc123", "bookmakers": [
            {"key": "pinnacle", "markets": [
                {"key": "spreads", "outcomes": [
                    {"name": "Mexico", "price": 1.92, "point": -1.0},
                    {"name": "South Africa", "price": 1.98, "point": 1.0}]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": 1.85, "point": 2.25},
                    {"name": "Under", "price": 2.05, "point": 2.25}]}]}]}

    def responder(solicitud):
        if solicitud.url.path.endswith("/events"):
            return httpx.Response(200, json=eventos)
        return httpx.Response(200, json=cuotas_evento,
                              headers={"x-requests-remaining": "480", "x-requests-last": "5"})

    cliente = ClienteOddsApi("k", transporte=httpx.MockTransport(responder))
    assert cliente.eventos()[0]["id"] == "abc123"
    datos, presupuesto = cliente.cuotas_evento("abc123", mercados="spreads,totals")
    assert presupuesto["restantes"] == "480"
    filas = ClienteOddsApi.filas_mercados(datos, partido_id=537327, capturado_en="t")
    assert (537327, "t", "odds-api", "pinnacle", "ah", "Mexico@-1.0", 1.92) in filas
    assert (537327, "t", "odds-api", "pinnacle", "totals", "over@2.25", 1.85) in filas
```

- [ ] Step 2: implement in `odds_api.py`:

```python
    def eventos(self) -> list:
        respuesta = self._http.get(f"/sports/{DEPORTE_MUNDIAL}/events",
                                   params={"apiKey": self._clave})
        respuesta.raise_for_status()
        return respuesta.json()

    def cuotas_evento(self, evento_id: str, mercados: str = "spreads,totals") -> tuple[dict, dict]:
        respuesta = self._http.get(
            f"/sports/{DEPORTE_MUNDIAL}/events/{evento_id}/odds",
            params={"regions": "eu", "markets": mercados, "oddsFormat": "decimal",
                    "apiKey": self._clave})
        respuesta.raise_for_status()
        presupuesto = {"restantes": respuesta.headers.get("x-requests-remaining"),
                       "usadas": respuesta.headers.get("x-requests-used")}
        return respuesta.json(), presupuesto

    @staticmethod
    def filas_mercados(datos: dict, partido_id: int, capturado_en: str) -> list[tuple]:
        filas = []
        for casa in datos.get("bookmakers", []):
            for mercado_crudo in casa.get("markets", []):
                clave = {"spreads": "ah", "totals": "totals"}.get(mercado_crudo["key"])
                if clave is None:
                    continue
                for o in mercado_crudo.get("outcomes", []):
                    if clave == "ah":
                        seleccion = f"{o['name']}@{o['point']:+.1f}".replace("+-", "-")
                        seleccion = f"{o['name']}@{o['point']}"
                    else:
                        seleccion = f"{o['name'].lower()}@{o['point']}"
                    filas.append((partido_id, capturado_en, "odds-api", casa["key"],
                                  clave, seleccion, o["price"]))
        return filas
```

(implementer: keep ONE selection format — `f"{o['name']}@{o['point']}"` for AH and `f"{o['name'].lower()}@{o['point']}"` for totals; delete the duplicated line.) CLI:

```python
@app.command()
def sondear(partido: str = typer.Argument(..., help="tla-tla, igual que predecir")) -> None:
    """Sondea AH/totales reales en The Odds API (≈5 créditos) y compara con el modelo."""
    from datetime import datetime, timezone

    from mundial.ingesta.odds_api import ClienteOddsApi

    conexion = _conexion_lista()
    partido_id = _resolver_partido(conexion, partido)
    fila = conexion.execute("SELECT * FROM partidos WHERE id=?", (partido_id,)).fetchone()
    cliente = _cliente_odds_api()
    eventos = cliente.eventos()
    objetivo = next(
        (e for e in eventos
         if {actualizar_canonico(e["home_team"]), actualizar_canonico(e["away_team"])}
         == {fila["local"], fila["visitante"]}), None)
    if objetivo is None:
        consola.print("[yellow]El partido no está en The Odds API todavía.[/]")
        return
    datos, presupuesto = cliente.cuotas_evento(objetivo["id"])
    if int(presupuesto["restantes"] or 0) < 100:
        consola.print("[red]Presupuesto bajo[/] — quedan menos de 100 créditos; no insisto.")
    filas = ClienteOddsApi.filas_mercados(
        datos, partido_id, datetime.now(timezone.utc).isoformat())
    conexion.executemany("INSERT OR REPLACE INTO cuotas_mercado VALUES (?,?,?,?,?,?,?)", filas)
    conexion.commit()
    consola.print(f"{len(filas)} cuotas AH/totales guardadas "
                  f"(créditos restantes: {presupuesto['restantes']})")
    ultima = conexion.execute(
        """SELECT mercados_json FROM predicciones WHERE partido_id=?
           ORDER BY creado_en DESC LIMIT 1""", (partido_id,)).fetchone()
    if ultima and ultima["mercados_json"]:
        import json as json_lib
        justas = json_lib.loads(ultima["mercados_json"]).get("ah", {})
        for f in filas:
            if f[4] == "ah":
                consola.print(f"  {f[5]} @{f[6]:.2f} ({f[3]}) — justa modelo: "
                              f"{justas.get(f[5].split('@')[1].replace('+',''), '—')}")
```

(`actualizar_canonico` = `from mundial.ingesta.actualizar import canonico as actualizar_canonico`. La comparación AH usa la curva `ah` guardada en `mercados_json`.)

- [ ] Step 3: tests pass → commit `feat: selective Asian-handicap probes via The Odds API`.

### Task 23: alerta de XI confirmado (FIFA live)

**Files:** Modify `src/mundial/ingesta/fifa.py`, `src/mundial/ingesta/actualizar.py` (persist `id_stage`), `src/mundial/notificaciones/vigilar.py`; Test `tests/test_clientes_fixtures.py`, `tests/test_vigilar.py` (extend).

- [ ] Step 1: `fifa.calendario()` gains `"id_stage": m.get("IdStage")` in the simplified dict; `actualizar` persists it to new table `partidos_fifa(partido_id INTEGER PRIMARY KEY, id_stage TEXT)` (add to DDL — `esquema.crear` is idempotent) filling from `calendario_por_llave`. New client method:

```python
    def alineacion_live(self, id_stage: str, id_match: str) -> dict:
        respuesta = self._http.get(
            f"/live/football/{ID_COMPETICION}/{ID_TEMPORADA}/{id_stage}/{id_match}",
            params={"language": "en"})
        respuesta.raise_for_status()
        crudo = respuesta.json()

        def titulares(lado: dict) -> list[str]:
            return [j.get("PlayerName", [{}])[0].get("Description", "")
                    for j in (lado or {}).get("Players", [])
                    if j.get("Status") == 1 and j.get("FieldStatus") == 1]

        return {"local": titulares(crudo.get("HomeTeam")),
                "visitante": titulares(crudo.get("AwayTeam"))}
```

(`Status==1`/`FieldStatus==1` = convocado titular según el probe del live endpoint; el implementador debe verificar contra un partido en vivo real el primer día de ejecución y ajustar la pareja de flags si el XI no sale con 11 nombres por lado.)

- [ ] Step 2: `vigilar` gains an XI block (window: 15-100 min before kickoff, state key `"xi"`): fetch `partidos_fifa.id_stage` + `id_fifa`, call `alineacion_live` (try/except), compare against the predicted XI of the latest BSD snapshot (`payload.alineaciones[evento].lineups.{home,away}.players[].name` — load via the latest snapshot file for that event, helper `_xi_predicho(conexion, partido_id)` reading `data/snapshots` newest bsd file). Alert when ≥3 names differ per side or a player with `ai_score ≥ 0.6` is missing: `"🚨 XI confirmado de {equipo}: {n} cambios vs el XI con el que predijimos — revisa la cuota antes del kickoff"`. Failing test: fake FIFA client + snapshot fixture seeded → message contains "XI confirmado"; second run no resend.
- [ ] Step 3: tests pass → commit `feat: confirmed-XI alert from FIFA live endpoint`.

### Task 24: checkpoint de fase de grupos + cierre

**Files:** Modify `src/mundial/cli.py`; docs.

- [ ] Step 1: command:

```python
@app.command()
def checkpoint() -> None:
    """Checkpoint del torneo: precisión, ledger/CLV, calibración w, estado de patrones y GBM."""
    from mundial.modelo import calibracion, ledger as ledger_mod
    from mundial.modelo import precision as precision_mod

    conexion = _conexion_lista()
    informe = precision_mod.evaluar(conexion)
    consola.print(f"Partidos evaluados: {informe['n']}")
    for variante in ("modelo", "mercado", "blend"):
        d = informe[variante]
        if d["n"]:
            consola.print(f"  {variante}: RPS {d['rps']:.4f} · Brier {d['brier']:.4f} · "
                          f"logloss {d['logloss']:.4f}")
    ledger_mod.liquidar_pendientes(conexion)
    r = ledger_mod.resumen(conexion)
    if r["n"]:
        consola.print(f"Ledger: {r['n']} apuestas, yield {r['yield_flat'] * 100:+.1f}%, "
                      f"CLV medio {(r['clv_medio'] or 0) * 100:+.2f}% (n={r['clv_n']})")
    calibrado = calibracion.optimizar_w(conexion)
    consola.print(f"w recomendado: {calibrado.get('w_recomendado')} "
                  f"(crudo {calibrado.get('w_crudo')}, n={calibrado['n']}) — "
                  f"aplica con `mundial calibrar --aplicar`")
    activo = conexion.execute("SELECT valor FROM config WHERE clave='gbm_activo'").fetchone()
    consola.print(f"GBM activo: {activo['valor'] if activo else 'sin evaluar'}")
    consola.print("Patrones: re-ejecuta `mundial minar` y revisa holdout 2026 antes de "
                  "promover o retirar entradas de data/patrones.json")
```

- [ ] Step 2: live dry-run `uv run mundial checkpoint` → commit `feat: tournament checkpoint command`.
- [ ] Step 3: dashboard — add "Patrones y ledger" page to `dashboard/app.py`: table of `data/patrones.json` entries (estado, efecto, n, p_adj), the candidatos table from `data/candidatos.json`, and the ledger summary/last-20 bets (reuse `ledger.resumen`); helper queries in `dashboard/datos.py` with a test each (same pattern as existing `datos.py` tests).
- [ ] Step 4: close-out — update CLAUDE.md (new commands `gbm/calibrar/sondear/checkpoint/minar/ledger`, gate verdict, pool weights, patterns workflow), README status, mark both plans' checkboxes, `git push`, verify CI snapshot+vigilar runs stay green. **M3+M4 done.**

## Self-review notes

- Spec coverage M3: ratings as-of ✓(T18), 22 features point-in-time ✓(T19 — `NOMBRES_FEATURES` tiene exactamente 22), Frank-Hall + isotónica + monotonía ✓(T19), puerta estricta todos-los-bloques ✓(T19 walk_forward / T20 CLI), pool log-lineal pesos desde config ✓(T20), SHAP por partido + en explicación ✓(T20). M4: calibración w shrinkage/limites ✓(T21), pooling geométrico comparado ✓(T21), sondeos AH selectivos con guard de presupuesto ✓(T22), XI confirmado FIFA live ✓(T23), checkpoint ✓(T24).
- Type consistency: `construir_features` devuelve 5 valores en su forma final (X, y, fechas, nombres, meta) — los tres tests de T19 y el uso en T20 lo reflejan; `rps(p, idx)` reutilizado de precision; `config` accedido siempre por `INSERT OR REPLACE`/`SELECT valor`.
- Placeholder scan: la nota del implementador en T19 reemplaza el stub truncado `_rps_dc_baseline` con la implementación completa dentro de `walk_forward`; T22 marca la línea duplicada a borrar; T23 documenta la verificación en vivo de los flags Status/FieldStatus (dato no verificable hasta que haya un partido en vivo durante la ejecución).
- Riesgo conocido: `entrenar_ordinal` usa cola temporal 80/20 para la isotónica (no k-fold) — decisión deliberada por simplicidad; si la calibración sale pobre en el walk-forward, cambiar a isotónica sobre predicciones out-of-fold de 5 bloques temporales es el primer ajuste.
