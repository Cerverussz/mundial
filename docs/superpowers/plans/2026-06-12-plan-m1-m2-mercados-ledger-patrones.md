# M1+M2 — Derived Markets, Paper-Trading Ledger & Pre-Registered Pattern Mining

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Price O/U, BTTS, DNB/AH and double chance from one market-coherent matrix (λ-space blend), open/settle paper bets with CLV tracking, and stand up pre-registered pattern mining with Telegram alerts.

**Architecture:** New pure-math module `modelo/mercados.py` prices and settles every derived market from the score matrix. `modelo/inversion.py` inverts market-implied (λ,μ) from de-vigged DNB+O/U 2.5 so the blend happens in λ-space and ALL markets come from one final matrix. Snapshots already contain 11 markets per book — a second loader pass fills `cuotas_mercado`. `modelo/ledger.py` opens paper bets on sustained flags and settles them in `vigilar` with CLV vs Pinnacle close. M2 adds `analisis/mineria.py` (BH-corrected hypothesis testing over historical data, with 90-minute scores reconstructed from datahub goals.csv) and `notificaciones/patrones.py` (git-pre-registered declarative patterns → priced alerts in vigilar).

**Tech Stack:** existing (numpy/scipy/httpx/typer/pytest). No new deps in M1/M2.

**Probed facts this plan relies on (2026-06-12, live):**
- Snapshot market shape (verified in `data/snapshots/2026-06-11/233034Z-bsd.json.gz`): `markets` keys and selection keys are exactly: `1x2{HOME,DRAW,AWAY}`, `double_chance{1X,X2,12}`, `over_under_15/25/35{over@L,under@L}` (field `line` present), `btts{yes,no}`, `draw_no_bet{HOME,AWAY}`, `total_corners{over@4.5..15.5}`, `corners_1x2{HOME,DRAW,AWAY}`, `red_card{yes,no}`, `total_red_cards{over@0.5,...}`. Each selection: `{line, bookmakers:{slug:{decimal_odds, movement, updated_at}}}`.
- BSD stats fixture captured at `tests/fixtures/bsd_stats.json` (event 8287: `stats.home.expected_goals=1.41`, away `0.07`, 19 shots in `shotmap`, `xg_per_minute`). For not-started events the endpoint returns 200 with nulls.
- datahub: `https://datahub.io/football/worldcup/r/matches.csv` (1,248 matches 1930-2022; cols incl. `match_id, stage_name, group_stage, knockout_stage, match_date, home_team_name, away_team_name, home_team_score, away_team_score, extra_time, penalty_shootout`) and `.../r/goals.csv` (3,637 goals; cols incl. `match_id, team_name, home_team (0/1), minute_regulation, minute_stoppage, match_period ('first half'|'second half'|extra-time periods), own_goal`). 90' score = goals with `match_period` in first/second half, own-goals counted for the opposing team.
- Existing predicciones table lacks `mercados_json` → needs a guarded migration (CREATE TABLE IF NOT EXISTS does not alter existing local DBs).

---

## M1 — Mercados derivados + ledger

### Task 1: Esquema v3 + migración

**Files:** Modify `src/mundial/persistencia/esquema.py`; Test `tests/test_persistencia.py` (extend).

- [x] Step 1: extend tests:

```python
def test_esquema_v3_tablas_y_migracion(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    tablas = {f["name"] for f in conexion.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cuotas_mercado", "archivos_cargados_mercados", "apuestas", "xg", "tiros",
            "resultados_wc", "config"} <= tablas
    columnas = {f["name"] for f in conexion.execute("PRAGMA table_info(predicciones)")}
    assert "mercados_json" in columnas
    esquema.crear(conexion)  # idempotente también con la migración
```

- [x] Step 2: run `uv run pytest tests/test_persistencia.py -v` → FAIL (tablas faltantes).
- [x] Step 3: append to `DDL` in `esquema.py`:

```sql
CREATE TABLE IF NOT EXISTS cuotas_mercado(
  partido_id INTEGER NOT NULL,
  capturado_en TEXT NOT NULL,
  fuente TEXT NOT NULL,
  casa TEXT NOT NULL,
  mercado TEXT NOT NULL,
  seleccion TEXT NOT NULL,
  cuota REAL NOT NULL,
  PRIMARY KEY(partido_id, capturado_en, fuente, casa, mercado, seleccion)
);
CREATE TABLE IF NOT EXISTS archivos_cargados_mercados(
  ruta TEXT PRIMARY KEY,
  cargado_en TEXT
);
CREATE TABLE IF NOT EXISTS apuestas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  partido_id INTEGER NOT NULL,
  creado_en TEXT NOT NULL,
  origen TEXT NOT NULL,
  mercado TEXT NOT NULL,
  seleccion TEXT NOT NULL,
  linea REAL,
  cuota REAL NOT NULL,
  casa TEXT,
  p_modelo REAL, p_mercado REAL, margen REAL,
  estado TEXT NOT NULL DEFAULT 'pendiente',
  retorno_flat REAL,
  stake_kelly REAL, retorno_kelly REAL,
  clv REAL,
  commit_datos TEXT,
  UNIQUE(partido_id, origen, mercado, seleccion, linea)
);
CREATE TABLE IF NOT EXISTS xg(
  partido_id INTEGER PRIMARY KEY,
  xg_local REAL, xg_visitante REAL,
  fuente TEXT, capturado_en TEXT
);
CREATE TABLE IF NOT EXISTS tiros(
  partido_id INTEGER NOT NULL,
  indice INTEGER NOT NULL,
  es_local INTEGER, minuto INTEGER, jugador_id INTEGER,
  xg REAL, xgot REAL, tipo TEXT, x REAL, y REAL,
  PRIMARY KEY(partido_id, indice)
);
CREATE TABLE IF NOT EXISTS resultados_wc(
  match_id TEXT PRIMARY KEY,
  anio INTEGER, fase TEXT, es_grupos INTEGER, es_eliminacion INTEGER,
  fecha TEXT, local TEXT, visitante TEXT,
  goles90_local INTEGER, goles90_visitante INTEGER,
  goles_final_local INTEGER, goles_final_visitante INTEGER,
  prorroga INTEGER, penales INTEGER
);
CREATE TABLE IF NOT EXISTS config(
  clave TEXT PRIMARY KEY,
  valor TEXT
);
```

and after `executescript(DDL)` in `crear()` add the guarded migration:

```python
def _migrar(conexion: sqlite3.Connection) -> None:
    columnas = {f["name"] for f in conexion.execute("PRAGMA table_info(predicciones)")}
    if "mercados_json" not in columnas:
        conexion.execute("ALTER TABLE predicciones ADD COLUMN mercados_json TEXT")


def crear(conexion: sqlite3.Connection) -> None:
    conexion.executescript(DDL)
    _migrar(conexion)
    conexion.commit()
```

(`PRAGMA table_info` rows come through the `sqlite3.Row` factory, so `f["name"]` works.)

- [x] Step 4: `uv run pytest tests/test_persistencia.py -v` → PASS.
- [x] Step 5: `git add -A src tests && git commit -m "feat: schema v3 — market odds, paper bets, xG, WC90, config"`

### Task 2: `modelo/mercados.py` — pricing y liquidación

**Files:** Create `src/mundial/modelo/mercados.py`; Test `tests/test_mercados_derivados.py`.

- [x] Step 1: failing tests (the math core — synthetic matrices with obvious answers):

```python
import numpy as np
import pytest

from mundial.modelo import mercados, prediccion


@pytest.fixture
def matriz():
    return prediccion.matriz_marcadores(1.5, 1.1, rho=-0.06)


def test_over_under_semientera_suman_uno(matriz):
    over = mercados.prob_over(matriz, 2.5)
    under = mercados.prob_under(matriz, 2.5)
    assert over + under == pytest.approx(1.0)
    assert 0.3 < over < 0.7


def test_total_linea_entera_tiene_push(matriz):
    r = mercados.resultado_total(matriz, 3.0, "over")
    assert r["p_gana"] + r["p_push"] + r["p_pierde"] == pytest.approx(1.0)
    assert r["p_push"] > 0.05  # P(total=3) no es despreciable
    justa = mercados.cuota_justa_total(matriz, 3.0, "over")
    assert justa == pytest.approx(1.0 + r["p_pierde"] / r["p_gana"])


def test_total_linea_cuarto_promedia(matriz):
    r225 = mercados.resultado_total(matriz, 2.25, "over")
    r20 = mercados.resultado_total(matriz, 2.0, "over")
    r25 = mercados.resultado_total(matriz, 2.5, "over")
    # EV por unidad a cuota o debe ser el promedio de las dos patas
    o = 1.9
    assert mercados.ev_total(matriz, 2.25, "over", o) == pytest.approx(
        0.5 * mercados.ev_total(matriz, 2.0, "over", o)
        + 0.5 * mercados.ev_total(matriz, 2.5, "over", o)
    )
    assert r225["p_media_gana"] == pytest.approx(0.0)  # over 2.25: media solo al perder en 2


def test_btts_desde_matriz(matriz):
    p = mercados.prob_btts(matriz)
    assert p == pytest.approx(matriz[1:, 1:].sum())


def test_ah_media_linea_es_prob_simple(matriz):
    r = mercados.resultado_ah(matriz, -0.5)
    indices = np.indices(matriz.shape)
    p_gana_por_1 = matriz[indices[0] > indices[1]].sum()
    assert r["p_gana"] == pytest.approx(p_gana_por_1)
    assert r["p_push"] == 0.0


def test_ah_dnb_es_handicap_cero(matriz):
    r = mercados.resultado_ah(matriz, 0.0)
    assert r["p_push"] == pytest.approx(np.trace(matriz))
    justa_local, justa_visita = mercados.cuotas_justas_dnb(matriz)
    assert justa_local == pytest.approx(1.0 + r["p_pierde"] / r["p_gana"])


def test_ah_cuarto_negativo(matriz):
    # h=-0.25: D>=1 gana todo; D=0 pierde media; D<=-1 pierde todo
    r = mercados.resultado_ah(matriz, -0.25)
    assert r["p_media_pierde"] == pytest.approx(np.trace(matriz))
    assert r["p_gana"] + r["p_media_pierde"] + r["p_pierde"] == pytest.approx(1.0)


def test_liquidar_ah_casos():
    # local -1.5, ganó 2-0 → diferencia 2 → gana completa
    assert mercados.liquidar_ah(2, -1.5, 1.9) == ("ganada", pytest.approx(0.9))
    # local -1.0, ganó 1-0 → push
    assert mercados.liquidar_ah(1, -1.0, 1.9) == ("push", 0.0)
    # local -0.25, empató → media perdida
    estado, retorno = mercados.liquidar_ah(0, -0.25, 1.9)
    assert estado == "media_perdida" and retorno == pytest.approx(-0.5)
    # local +0.25, empató → media ganada
    estado, retorno = mercados.liquidar_ah(0, 0.25, 1.9)
    assert estado == "media_ganada" and retorno == pytest.approx(0.45)
    # visitante: el llamador pasa la diferencia desde la perspectiva apostada
    assert mercados.liquidar_ah(-1, 0.5, 2.0) == ("perdida", -1.0)


def test_liquidar_total():
    assert mercados.liquidar_total(3, 2.5, "over", 1.8) == ("ganada", pytest.approx(0.8))
    assert mercados.liquidar_total(3, 3.0, "over", 1.8) == ("push", 0.0)
    assert mercados.liquidar_total(2, 2.25, "under", 1.8)[0] == "media_ganada"
    assert mercados.liquidar_total(2, 2.25, "over", 1.8)[0] == "media_perdida"


def test_liquidar_2way():
    assert mercados.liquidar_2way(True, 2.1) == ("ganada", pytest.approx(1.1))
    assert mercados.liquidar_2way(False, 2.1) == ("perdida", -1.0)
```

- [x] Step 2: run → FAIL (módulo no existe).
- [x] Step 3: implement `src/mundial/modelo/mercados.py`:

```python
"""Precios justos y liquidación de mercados derivados de la matriz de marcadores."""
from __future__ import annotations

import numpy as np

CUARTO = 0.25


def _es_cuarto(linea: float) -> bool:
    return abs(linea * 4 - round(linea * 4)) < 1e-9 and abs(linea * 2 - round(linea * 2)) > 1e-9


def prob_over(matriz: np.ndarray, linea: float) -> float:
    indices = np.indices(matriz.shape)
    return float(matriz[(indices[0] + indices[1]) > linea].sum())


def prob_under(matriz: np.ndarray, linea: float) -> float:
    indices = np.indices(matriz.shape)
    return float(matriz[(indices[0] + indices[1]) < linea].sum())


def prob_btts(matriz: np.ndarray) -> float:
    return float(matriz[1:, 1:].sum())


def _resultado_simple_total(matriz, linea: float, lado: str) -> dict:
    """Línea entera o semientera: gana/push/pierde."""
    indices = np.indices(matriz.shape)
    total = indices[0] + indices[1]
    p_push = float(matriz[total == linea].sum()) if abs(linea - round(linea)) < 1e-9 else 0.0
    p_over, p_under = prob_over(matriz, linea), prob_under(matriz, linea)
    if lado == "over":
        return {"p_gana": p_over, "p_pierde": p_under, "p_push": p_push,
                "p_media_gana": 0.0, "p_media_pierde": 0.0}
    return {"p_gana": p_under, "p_pierde": p_over, "p_push": p_push,
            "p_media_gana": 0.0, "p_media_pierde": 0.0}


def resultado_total(matriz, linea: float, lado: str) -> dict:
    """Distribución de resultados de la apuesta de totales (maneja líneas de cuarto)."""
    if not _es_cuarto(linea):
        return _resultado_simple_total(matriz, linea, lado)
    baja, alta = linea - CUARTO, linea + CUARTO
    a, b = _resultado_simple_total(matriz, baja, lado), _resultado_simple_total(matriz, alta, lado)
    # una pata entera (con push) y una semientera; el push de la entera = media-X del cuarto
    entera, semi = (a, b) if abs(baja - round(baja)) < 1e-9 else (b, a)
    return {
        "p_gana": min(a["p_gana"], b["p_gana"]),
        "p_pierde": min(a["p_pierde"], b["p_pierde"]),
        "p_push": 0.0,
        "p_media_gana": entera["p_push"] if semi["p_gana"] > entera["p_gana"] else 0.0,
        "p_media_pierde": entera["p_push"] if semi["p_pierde"] > entera["p_pierde"] else 0.0,
    }


def resultado_ah(matriz, handicap: float) -> dict:
    """Distribución de la apuesta AL LOCAL con hándicap h (D = goles_local − goles_visitante)."""
    indices = np.indices(matriz.shape)
    diferencia = indices[0] - indices[1]

    def simple(h: float) -> dict:
        margen = diferencia + h
        return {
            "p_gana": float(matriz[margen > 1e-9].sum()),
            "p_pierde": float(matriz[margen < -1e-9].sum()),
            "p_push": float(matriz[np.abs(margen) < 1e-9].sum()),
            "p_media_gana": 0.0, "p_media_pierde": 0.0,
        }

    if not _es_cuarto(handicap):
        return simple(handicap)
    a, b = simple(handicap - CUARTO), simple(handicap + CUARTO)
    entera = a if abs((handicap - CUARTO) * 2 - round((handicap - CUARTO) * 2)) < 1e-9 else b
    if entera is a:  # entera abajo: ej. -0.25 → patas -0.5 y 0.0... (la entera es la de push>0)
        pass
    entera = a if a["p_push"] > 0 else b
    semi = b if entera is a else a
    return {
        "p_gana": min(a["p_gana"], b["p_gana"]),
        "p_pierde": min(a["p_pierde"], b["p_pierde"]),
        "p_push": 0.0,
        "p_media_gana": entera["p_push"] if semi["p_gana"] > entera["p_gana"] else 0.0,
        "p_media_pierde": entera["p_push"] if semi["p_pierde"] > entera["p_pierde"] else 0.0,
    }


def _cuota_justa(r: dict) -> float:
    perdida_efectiva = r["p_pierde"] + 0.5 * r["p_media_pierde"]
    ganancia_efectiva = r["p_gana"] + 0.5 * r["p_media_gana"]
    return 1.0 + perdida_efectiva / ganancia_efectiva if ganancia_efectiva > 0 else float("inf")


def cuota_justa_total(matriz, linea: float, lado: str) -> float:
    return _cuota_justa(resultado_total(matriz, linea, lado))


def cuota_justa_ah(matriz, handicap: float) -> float:
    return _cuota_justa(resultado_ah(matriz, handicap))


def cuotas_justas_dnb(matriz) -> tuple[float, float]:
    local = resultado_ah(matriz, 0.0)
    visita = {"p_gana": local["p_pierde"], "p_pierde": local["p_gana"],
              "p_push": local["p_push"], "p_media_gana": 0.0, "p_media_pierde": 0.0}
    return _cuota_justa(local), _cuota_justa(visita)


def ev_total(matriz, linea: float, lado: str, cuota: float) -> float:
    r = resultado_total(matriz, linea, lado)
    return (r["p_gana"] * (cuota - 1) + r["p_media_gana"] * (cuota - 1) / 2
            - r["p_media_pierde"] * 0.5 - r["p_pierde"])


def ev_ah(matriz, handicap: float, cuota: float) -> float:
    r = resultado_ah(matriz, handicap)
    return (r["p_gana"] * (cuota - 1) + r["p_media_gana"] * (cuota - 1) / 2
            - r["p_media_pierde"] * 0.5 - r["p_pierde"])


def liquidar_ah(diferencia: int, handicap: float, cuota: float) -> tuple[str, float]:
    """Liquida la apuesta con la diferencia de goles DESDE LA PERSPECTIVA del lado apostado."""
    if _es_cuarto(handicap):
        e1, r1 = liquidar_ah(diferencia, handicap - CUARTO, cuota)
        e2, r2 = liquidar_ah(diferencia, handicap + CUARTO, cuota)
        retorno = (r1 + r2) / 2.0
        estados = {e1, e2}
        if estados == {"ganada"}:
            return "ganada", retorno
        if estados == {"perdida"}:
            return "perdida", retorno
        if "ganada" in estados:
            return "media_ganada", retorno
        if "perdida" in estados:
            return "media_perdida", retorno
        return "push", 0.0
    margen = diferencia + handicap
    if margen > 1e-9:
        return "ganada", cuota - 1.0
    if margen < -1e-9:
        return "perdida", -1.0
    return "push", 0.0


def liquidar_total(total_goles: int, linea: float, lado: str, cuota: float) -> tuple[str, float]:
    diferencia = total_goles - linea if lado == "over" else linea - total_goles
    # reusar la lógica de AH tratando 'diferencia' como margen con h=0 (admite cuartos vía linea)
    if _es_cuarto(linea):
        e1, r1 = liquidar_total(total_goles, linea - CUARTO, lado, cuota)
        e2, r2 = liquidar_total(total_goles, linea + CUARTO, lado, cuota)
        retorno = (r1 + r2) / 2.0
        estados = {e1, e2}
        if estados == {"ganada"}:
            return "ganada", retorno
        if estados == {"perdida"}:
            return "perdida", retorno
        if "ganada" in estados:
            return "media_ganada", retorno
        if "perdida" in estados:
            return "media_perdida", retorno
        return "push", 0.0
    if diferencia > 1e-9:
        return "ganada", cuota - 1.0
    if diferencia < -1e-9:
        return "perdida", -1.0
    return "push", 0.0


def liquidar_2way(gano: bool, cuota: float) -> tuple[str, float]:
    return ("ganada", cuota - 1.0) if gano else ("perdida", -1.0)
```

Note for the implementer: in `resultado_ah` delete the dead `if entera is a: pass` block — keep only the `p_push`-based selection of the whole line (the leg with `p_push > 0` is the integer one; if both have push 0 — impossible for a true quarter line — fall back to `a`).

- [x] Step 4: run → PASS. Step 5: commit `feat: derived-market pricing and settlement from score matrix`.

### Task 3: `MAX_GOLES` 8 → 10

**Files:** Modify `src/mundial/modelo/prediccion.py` (line `MAX_GOLES = 8`); Test `tests/test_prediccion.py`.

- [x] Step 1: change `MAX_GOLES = 8` → `MAX_GOLES = 10`. Add test:

```python
def test_matriz_11x11_normalizada():
    matriz = prediccion.matriz_marcadores(3.4, 2.8, rho=-0.06)
    assert matriz.shape == (11, 11)
    assert matriz.sum() == pytest.approx(1.0)
```

- [x] Step 2: `uv run pytest -q` → all pass (existing tests don't pin the shape). Commit `feat: extend score matrix to 10 goals`.

### Task 4: cargar mercados desde snapshots

**Files:** Modify `src/mundial/ingesta/cargar_cuotas.py`; Test `tests/test_cargar_cuotas.py` (extend).

- [x] Step 1: failing tests:

```python
def test_carga_mercados_desde_snapshot(tmp_path):
    conexion = preparar_bd(tmp_path)
    escribir_snapshot_bsd(tmp_path / "snaps")
    cargar_cuotas.cargar_nuevos(conexion, base=tmp_path / "snaps")
    n = cargar_cuotas.cargar_mercados(conexion, base=tmp_path / "snaps")
    assert n > 50
    fila = conexion.execute(
        """SELECT * FROM cuotas_mercado WHERE partido_id=537327 AND mercado='over_under_25'
           AND casa='pinnacle' AND seleccion='over@2.5'"""
    ).fetchone()
    assert fila is not None and fila["cuota"] > 1.0
    selecciones_btts = {f["seleccion"] for f in conexion.execute(
        "SELECT DISTINCT seleccion FROM cuotas_mercado WHERE mercado='btts'")}
    assert selecciones_btts == {"yes", "no"}
    # segunda corrida: idempotente
    assert cargar_cuotas.cargar_mercados(conexion, base=tmp_path / "snaps") == 0
```

(If `tests/fixtures/bsd_comparison.json` lacks non-1x2 markets — it was captured day 1 — refresh it once: `set -a; source .env; set +a && curl -sS "https://sports.bzzoiro.com/api/v2/events/8297/odds/comparison/" -H "Authorization: Token $BSD_TOKEN" -o tests/fixtures/bsd_comparison.json` using any upcoming event id from `data/local`, then fix the team/date literals in `tests/test_cargar_cuotas.py::preparar_bd` and `tests/test_bsd.py::test_comparacion_cuotas` to match the refreshed fixture.)

- [x] Step 2: implement in `cargar_cuotas.py`:

```python
MERCADOS_CAPTURADOS = (
    "over_under_15", "over_under_25", "over_under_35", "btts", "draw_no_bet",
    "double_chance", "total_corners", "corners_1x2",
)


def _filas_mercados_bsd(payload: dict, capturado_en: str, indice: dict) -> list:
    filas = []
    for comparacion in (payload.get("comparaciones") or {}).values():
        llave = (
            comparacion["event_date"][:10],
            frozenset((canonico(comparacion["home_team"]), canonico(comparacion["away_team"]))),
        )
        partido_id = indice.get(llave)
        if partido_id is None:
            continue
        for mercado, contenido in (comparacion.get("markets") or {}).items():
            if mercado not in MERCADOS_CAPTURADOS:
                continue
            for seleccion, detalle in contenido.items():
                for casa, datos in (detalle.get("bookmakers") or {}).items():
                    cuota = datos.get("decimal_odds")
                    if cuota and cuota > 1.0:
                        filas.append(
                            (partido_id, capturado_en, "bsd", casa, mercado, seleccion, cuota)
                        )
    return filas


def cargar_mercados(conexion: sqlite3.Connection, base: Path | None = None) -> int:
    """Segunda pasada sobre los snapshots: mercados más allá del 1X2 (registro propio)."""
    base = base or DIR_SNAPSHOTS
    cargados = {
        f["ruta"] for f in conexion.execute("SELECT ruta FROM archivos_cargados_mercados")
    }
    indice = _indice_partidos(conexion)
    total = 0
    for ruta in sorted(base.glob("*/*-bsd.json.gz")):
        rel = str(ruta.relative_to(base))
        if rel in cargados:
            continue
        contenido = snapshots.leer_snapshot(ruta)
        filas = _filas_mercados_bsd(contenido["payload"], contenido["capturado_en"], indice)
        conexion.executemany(
            "INSERT OR REPLACE INTO cuotas_mercado VALUES (?,?,?,?,?,?,?)", filas
        )
        conexion.execute(
            "INSERT OR REPLACE INTO archivos_cargados_mercados VALUES (?,?)",
            (rel, datetime.now(timezone.utc).isoformat()),
        )
        total += len(filas)
    conexion.commit()
    return total
```

and call it from `actualizar.sincronizar` right after `cargar_nuevos` (message `f"cuotas de mercados nuevas: {n}"`).

- [x] Step 3: tests pass → live run `uv run mundial actualizar` (expect tens of thousands of rows from the ~40 accumulated snapshots — they reprocess once). Commit `feat: multi-market odds loader from snapshots`.

### Task 5: consenso por mercado

**Files:** Modify `src/mundial/factores/mercado.py`; Test `tests/test_mercado.py` (extend).

- [x] Step 1: failing tests:

```python
def test_consenso_generico_dos_salidas():
    filas = [("pinnacle", {"over@2.5": 1.85, "under@2.5": 2.05}),
             ("bet365", {"over@2.5": 1.83, "under@2.5": 2.03})]
    p, n = mercado.consenso_generico(filas)
    assert n == 2
    assert sum(p.values()) == pytest.approx(1.0)
    assert p["over@2.5"] > 0.5


def test_cuotas_consenso_mercado(tmp_path):
    from mundial.persistencia import bd, esquema
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    for casa, over, under in [("pinnacle", 1.85, 2.05), ("bet365", 1.83, 2.03)]:
        for seleccion, cuota in [("over@2.5", over), ("under@2.5", under)]:
            conexion.execute(
                "INSERT INTO cuotas_mercado VALUES (1, '2026-06-12T10:00:00+00:00', 'bsd', ?, 'over_under_25', ?, ?)",
                (casa, seleccion, cuota))
    conexion.commit()
    p, n, capturado = mercado.cuotas_consenso_mercado(conexion, 1, "over_under_25")
    assert n == 2 and capturado.startswith("2026-06-12")
    assert p["over@2.5"] + p["under@2.5"] == pytest.approx(1.0)
```

- [x] Step 2: implement in `factores/mercado.py` (reuses `quitar_margen_shin`, which is generic over dict keys):

```python
def consenso_generico(filas: list[tuple[str, dict[str, float]]]) -> tuple[dict, int]:
    """Mediana de probabilidades Shin por selección. filas: (casa, {seleccion: cuota})."""
    por_casa = []
    selecciones = None
    for casa, cuotas in filas:
        if casa in CASAS_EXCLUIDAS or not cuotas or any(v is None or v <= 1.0 for v in cuotas.values()):
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
```

- [x] Step 3: tests pass → commit `feat: generic Shin consensus for 2-way and n-way markets`.

### Task 6: inversión de λ del mercado

**Files:** Create `src/mundial/modelo/inversion.py`; Test `tests/test_inversion.py`.

- [x] Step 1: failing round-trip test:

```python
import pytest

from mundial.modelo import inversion, mercados, prediccion


def test_inversion_recupera_lambdas():
    lam, mu, rho = 1.7, 0.9, -0.06
    matriz = prediccion.matriz_marcadores(lam, mu, rho)
    r = mercados.resultado_ah(matriz, 0.0)
    p_dnb_local = r["p_gana"] / (r["p_gana"] + r["p_pierde"])
    p_over25 = mercados.prob_over(matriz, 2.5)
    lam_inv, mu_inv = inversion.invertir_lambdas(p_dnb_local, p_over25, rho)
    assert lam_inv == pytest.approx(lam, abs=1e-3)
    assert mu_inv == pytest.approx(mu, abs=1e-3)


def test_inversion_sin_convergencia_devuelve_none():
    assert inversion.invertir_lambdas(0.999, 0.001, -0.06) is None
```

- [x] Step 2: implement `inversion.py` (Newton 2D con jacobiano numérico, acotado):

```python
"""Inversión de las λ implícitas del mercado desde DNB y Over 2.5 devigados."""
from __future__ import annotations

import numpy as np

from mundial.modelo import mercados, prediccion

LIMITES = (0.05, 6.0)


def _objetivo(lam: float, mu: float, rho: float, p_dnb: float, p_over: float) -> np.ndarray:
    matriz = prediccion.matriz_marcadores(lam, mu, rho)
    r = mercados.resultado_ah(matriz, 0.0)
    dnb = r["p_gana"] / (r["p_gana"] + r["p_pierde"])
    return np.array([dnb - p_dnb, mercados.prob_over(matriz, 2.5) - p_over])


def invertir_lambdas(
    p_dnb_local: float, p_over25: float, rho: float,
    lam0: float = 1.3, mu0: float = 1.1, iteraciones: int = 40,
) -> tuple[float, float] | None:
    x = np.array([lam0, mu0])
    paso = 1e-5
    for _ in range(iteraciones):
        f = _objetivo(x[0], x[1], rho, p_dnb_local, p_over25)
        if np.max(np.abs(f)) < 1e-9:
            return float(x[0]), float(x[1])
        jacobiano = np.empty((2, 2))
        for j in range(2):
            d = x.copy()
            d[j] += paso
            jacobiano[:, j] = (_objetivo(d[0], d[1], rho, p_dnb_local, p_over25) - f) / paso
        try:
            x = x - np.linalg.solve(jacobiano, f)
        except np.linalg.LinAlgError:
            return None
        x = np.clip(x, LIMITES[0], LIMITES[1])
    f = _objetivo(x[0], x[1], rho, p_dnb_local, p_over25)
    if np.max(np.abs(f)) < 1e-6:
        return float(x[0]), float(x[1])
    return None
```

- [x] Step 3: tests pass → commit `feat: market lambda inversion via 2D Newton`.

### Task 7: blend en espacio λ + precios de mercados en la predicción

**Files:** Modify `src/mundial/modelo/prediccion.py`; Test `tests/test_prediccion.py` (extend).

- [x] Step 1: failing test (seed `cuotas_mercado` in `preparar_bd_completa` with DNB + O/U 2.5 + BTTS rows for two books — same pattern as Task 5's test — then):

```python
def test_predecir_blend_lambda_y_mercados(tmp_path):
    conexion = preparar_bd_completa(tmp_path)  # ahora también siembra cuotas_mercado
    resultado = prediccion.predecir(conexion, 537327)
    assert resultado.mercados  # dict con precios derivados
    ou = resultado.mercados["over_under_25"]
    assert 1.0 < ou["justa_over"] < 10.0
    assert ou["p_over"] + ou["p_under"] == pytest.approx(1.0)
    assert "btts" in resultado.mercados and "dnb" in resultado.mercados
    assert resultado.mercados["origen_matriz"] == "blend_lambda"
    fila = conexion.execute(
        "SELECT mercados_json FROM predicciones WHERE partido_id=537327").fetchone()
    assert fila["mercados_json"] is not None


def test_predecir_sin_mercados_2way_usa_fallback(tmp_path):
    conexion = preparar_bd_completa(tmp_path)
    conexion.execute("DELETE FROM cuotas_mercado")
    conexion.commit()
    resultado = prediccion.predecir(conexion, 537327)
    assert resultado.mercados["origen_matriz"] == "reescalado_1x2"
```

- [x] Step 2: implement in `predecir` (after `p_mercado` is computed, replacing the current single `reescalar_matriz` block):

```python
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
```

with imports `from mundial.modelo import inversion, mercados` at top, `mercados=precios` added to the `Prediccion` dataclass (field `mercados: dict`), and `mercados_json` persisted (add `"mercados_json"` to `COLUMNAS_PREDICCION` and `json.dumps(precios)` to the values tuple — `cargar_exportadas` inherits it automatically; old JSONL lines without the key fail the named-param insert, so in `cargar_exportadas` add `fila.setdefault("mercados_json", None)` after `json.loads(linea)`).

- [x] Step 3: all tests pass (existing prediction tests unaffected: no 2-way rows seeded → fallback path). Commit `feat: lambda-space market blend and derived market prices in predictions`.

### Task 8: value flags multi-mercado

**Files:** Modify `src/mundial/modelo/prediccion.py`; Test `tests/test_prediccion.py` (extend).

- [x] Step 1: failing test:

```python
def test_flags_incluyen_mercados_2way(tmp_path):
    conexion = preparar_bd_completa(tmp_path)  # cuotas 2way sembradas con over barato
    resultado = prediccion.predecir(conexion, 537327)
    assert all({"mercado", "seleccion", "margen", "sostenida"} <= set(f) for f in resultado.valor_flags)
```

- [x] Step 2: implement — generalize the flag loop:

```python
UMBRALES_VALOR = {"1x2": 0.05, "over_under_25": 0.04, "btts": 0.04, "draw_no_bet": 0.04}

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
            sostenida = bool(previas and (p - previas.get(seleccion, 1.0)) > UMBRALES_VALOR[mercado_clave])
            flags.append({"mercado": mercado_clave, "seleccion": seleccion, "resultado": seleccion,
                          "margen": round(margen, 4), "sostenida": sostenida})
    return flags
```

1X2 flags keep their loop but gain `"mercado": "1x2", "seleccion": k`. Then in `predecir`:

```python
    valor_flags += _flags_mercado(conexion, partido_id, "over_under_25",
        {"over@2.5": precios["over_under_25"]["p_over"], "under@2.5": precios["over_under_25"]["p_under"]}, ahora)
    valor_flags += _flags_mercado(conexion, partido_id, "btts",
        {"yes": precios["btts"]["p_si"], "no": 1.0 - precios["btts"]["p_si"]}, ahora)
    dnb_local = mercados.resultado_ah(matriz_final, 0.0)
    p_dnb_propia = dnb_local["p_gana"] / (dnb_local["p_gana"] + dnb_local["p_pierde"])
    valor_flags += _flags_mercado(conexion, partido_id, "draw_no_bet",
        {"HOME": p_dnb_propia, "AWAY": 1.0 - p_dnb_propia}, ahora)
```

(CLI/Telegram printers read `flag["resultado"]` — kept populated — so they keep working; extend the printed label with `flag.get("mercado")`.)

- [x] Step 3: tests pass → commit `feat: value flags across derived markets`.

### Task 9: ledger de apuestas simuladas con CLV

**Files:** Create `src/mundial/modelo/ledger.py`; Test `tests/test_ledger.py`.

- [x] Step 1: failing tests:

```python
import pytest

from mundial.modelo import ledger
from mundial.persistencia import bd, esquema


def preparar(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    conexion.executescript("""
        INSERT INTO partidos(id, fecha_utc, local, visitante, estado)
        VALUES (1, '2026-06-13T19:00:00Z', 'Mexico', 'South Africa', 'TIMED');
        INSERT INTO cuotas_mercado VALUES
          (1,'2026-06-13T17:00:00+00:00','bsd','pinnacle','over_under_25','over@2.5',2.10),
          (1,'2026-06-13T17:00:00+00:00','bsd','pinnacle','over_under_25','under@2.5',1.80),
          (1,'2026-06-13T17:00:00+00:00','bsd','bet365','over_under_25','over@2.5',2.15),
          (1,'2026-06-13T17:00:00+00:00','bsd','bet365','over_under_25','under@2.5',1.78),
          (1,'2026-06-13T18:50:00+00:00','bsd','pinnacle','over_under_25','over@2.5',1.95),
          (1,'2026-06-13T18:50:00+00:00','bsd','pinnacle','over_under_25','under@2.5',1.92);
    """)
    conexion.commit()
    return conexion


def test_abrir_apuesta_de_flag_y_no_duplicar(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "over_under_25", "seleccion": "over@2.5", "margen": 0.07, "sostenida": True}
    n = ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:30:00+00:00")
    assert n == 1
    assert ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:40:00+00:00") == 0
    fila = conexion.execute("SELECT * FROM apuestas").fetchone()
    assert fila["cuota"] == pytest.approx(2.15)  # mejor cuota real disponible
    assert fila["stake_kelly"] > 0


def test_liquidar_y_clv(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "over_under_25", "seleccion": "over@2.5", "margen": 0.07, "sostenida": True}
    ledger.abrir_apuestas(conexion, 1, [flag], {"over@2.5": 0.55}, "2026-06-13T17:30:00+00:00")
    conexion.execute("UPDATE partidos SET goles_local=2, goles_visitante=1, estado='FINISHED'")
    conexion.commit()
    n = ledger.liquidar_pendientes(conexion)
    assert n == 1
    fila = conexion.execute("SELECT * FROM apuestas").fetchone()
    assert fila["estado"] == "ganada"
    assert fila["retorno_flat"] == pytest.approx(1.15)
    assert fila["clv"] is not None and fila["clv"] > 0  # tomamos 2.15, cierre justo ~1.935
    resumen = ledger.resumen(conexion)
    assert resumen["n"] == 1 and resumen["pnl_flat"] == pytest.approx(1.15)


def test_no_abre_sin_cuota_real(tmp_path):
    conexion = preparar(tmp_path)
    flag = {"mercado": "btts", "seleccion": "yes", "margen": 0.08, "sostenida": True}
    assert ledger.abrir_apuestas(conexion, 1, [flag], {"yes": 0.6}, "2026-06-13T17:30:00+00:00") == 0
```

- [x] Step 2: implement `ledger.py`:

```python
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
        gano = {"local": diferencia > 0, "empate": diferencia == 0, "visitante": diferencia < 0}[s]
        return mercados.liquidar_2way(gano, cuota)
    if m.startswith("over_under"):
        lado = "over" if s.startswith("over") else "under"
        return mercados.liquidar_total(total, fila["linea"], lado, cuota)
    if m == "btts":
        return mercados.liquidar_2way((goles_local > 0 and goles_visitante > 0) == (s == "yes"), cuota)
    if m == "draw_no_bet":
        if diferencia == 0:
            return "push", 0.0
        return mercados.liquidar_2way((diferencia > 0) == (s == "HOME"), cuota)
    if m == "double_chance":
        gano = {"1X": diferencia >= 0, "X2": diferencia <= 0, "12": diferencia != 0}[s]
        return mercados.liquidar_2way(gano, cuota)
    return "push", 0.0


def _clv(conexion, fila, fecha_kickoff: str) -> float | None:
    """CLV = cuota tomada / cuota justa de cierre − 1 (cierre: Pinnacle devig, fallback consenso)."""
    if fila["mercado"] == "1x2":
        p_cierre, _, _ = modulo_mercado.cuotas_consenso(conexion, fila["partido_id"], hasta=fecha_kickoff)
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
```

(Nota CLV: el `hasta=fecha_kickoff` reutiliza el GROUP BY con MAX(capturado_en) — el cierre es el último snapshot pre-kickoff; Pinnacle queda dentro de la mediana de consenso. Si se quiere Pinnacle-only, la mediana ya degrada bien cuando falta.)

- [x] Step 3: tests pass → commit `feat: paper-trading ledger with CLV vs pre-kickoff close`.

### Task 10: cableado — vigilar, CLI `ledger`, log-loss en precision

**Files:** Modify `src/mundial/notificaciones/vigilar.py`, `src/mundial/cli.py`, `src/mundial/modelo/precision.py`; Tests `tests/test_vigilar.py`, `tests/test_precision.py` (extend).

- [x] Step 1: failing tests:

```python
# test_vigilar.py — el pre-partido abre apuestas papel si hay flags sostenidos,
# y el post-partido liquida e incluye la línea del ledger
def test_vigilar_abre_y_liquida_apuestas(tmp_path):
    conexion = preparar_bd(tmp_path)  # extender: sembrar cuotas_mercado con over barato sostenido
    ...
    registro = vigilar.vigilar(conexion, TelegramFalso(), "42", ahora=AHORA, ruta_estado=tmp_path / "n.json")
    n_apuestas = conexion.execute("SELECT COUNT(*) c FROM apuestas").fetchone()["c"]
    assert n_apuestas >= 1

# test_precision.py
def test_logloss_en_evaluar(tmp_path):
    ...  # mismo seeding existente
    informe = precision.evaluar(conexion)
    assert informe["blend"]["logloss"] == pytest.approx(-math.log(0.73), rel=1e-6)
```

- [x] Step 2: implement:
  - `precision.py`: in the variant loop add `"logloss": -math.log(max(p[resultado], 1e-12))` per match and aggregate mean alongside brier/rps (`import math`).
  - `vigilar.py` PRE block: after `prediccion.predecir(...)` succeeds, build `p_propias` from the result (`{"local":..., "empate":..., "visitante":...}` plus the 2-way dicts used in Task 8) and call `ledger.abrir_apuestas(conexion, partido["id"], resultado.valor_flags, p_propias, ahora.isoformat())`; append count to registro. POST block: call `ledger.liquidar_pendientes(conexion)` once before the loop; in `_mensaje_resultado` append a ledger line when `resumen["n"] > 0`: `f"💰 Papel: {r['n']} apuestas, PnL flat {r['pnl_flat']:+.2f}u, CLV medio {r['clv_medio']*100:+.1f}%"` (omit CLV when None).
  - `cli.py`: new command `ledger`:

```python
@app.command()
def ledger() -> None:
    """Resumen del paper trading: PnL, yield y CLV."""
    from mundial.modelo import ledger as modulo

    conexion = _conexion_lista()
    modulo.liquidar_pendientes(conexion)
    r = modulo.resumen(conexion)
    if not r["n"] and not r["pendientes"]:
        consola.print("Sin apuestas simuladas todavía.")
        return
    consola.print(
        f"Apuestas: {r['n']} liquidadas, {r['pendientes']} pendientes · "
        f"PnL flat: {r.get('pnl_flat', 0):+.2f}u · yield: {r.get('yield_flat', 0) * 100:+.1f}% · "
        f"CLV medio: {r['clv_medio'] * 100:+.2f}% (n={r['clv_n']})"
        if r.get("clv_medio") is not None else "CLV aún sin datos"
    )
    for f in conexion.execute(
        "SELECT a.*, p.local, p.visitante FROM apuestas a JOIN partidos p ON p.id=a.partido_id ORDER BY a.creado_en DESC LIMIT 15"):
        consola.print(
            f"  {f['estado']:>14} {f['local']} vs {f['visitante']} — {f['mercado']}/{f['seleccion']}"
            f" @{f['cuota']:.2f} ({f['origen']})" + (f" CLV {f['clv']*100:+.1f}%" if f["clv"] is not None else "")
        )
```

- [x] Step 3: full suite passes → live: `uv run mundial actualizar && uv run mundial hoy && uv run mundial ledger`. Commit `feat: paper bets wired into watcher; ledger CLI; log-loss metric`. **M1 done.**

---

## M2 — Minería de patrones pre-registrada

### Task 11: histórico de Mundiales con marcador a 90'

**Files:** Create `src/mundial/ingesta/mundiales.py`; Test `tests/test_mundiales.py`.

- [x] Step 1: failing tests (tiny inline CSVs mirroring the probed datahub columns):

```python
from mundial.ingesta import mundiales
from mundial.persistencia import bd, esquema

MATCHES_CSV = """key_id,tournament_id,tournament_name,match_id,match_name,stage_name,group_name,group_stage,knockout_stage,replayed,replay,match_date,match_time,stadium_id,stadium_name,city_name,country_name,home_team_id,home_team_name,home_team_code,away_team_id,away_team_name,away_team_code,score,home_team_score,away_team_score,home_team_score_margin,away_team_score_margin,extra_time,penalty_shootout,score_penalties,home_team_score_penalties,away_team_score_penalties,result,home_team_win,away_team_win,draw
1,WC-2014,x,M-2014-60,a,round of sixteen,,0,1,0,0,2014-06-28,17:00,S-1,s,c,p,T-1,Brazil,BRA,T-2,Chile,CHI,1–1,1,1,0,0,1,1,3-2,3,2,home team win,1,0,0
2,WC-2014,x,M-2014-01,b,group stage,Group A,1,0,0,0,2014-06-12,17:00,S-1,s,c,p,T-1,Brazil,BRA,T-3,Croatia,CRO,3–1,3,1,2,-2,0,0,0-0,0,0,home team win,1,0,0
"""

GOALS_CSV = """key_id,goal_id,tournament_id,tournament_name,match_id,match_name,match_date,stage_name,group_name,team_id,team_name,team_code,home_team,away_team,player_id,family_name,given_name,shirt_number,player_team_id,player_team_name,player_team_code,minute_label,minute_regulation,minute_stoppage,match_period,own_goal,penalty
1,G-1,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-1,Brazil,BRA,1,0,P-1,A,B,10,T-1,Brazil,BRA,18',18,0,first half,0,0
2,G-2,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-2,Chile,CHI,0,1,P-2,C,D,9,T-2,Chile,CHI,32',32,0,first half,0,0
3,G-3,WC-2014,x,M-2014-60,a,2014-06-28,r16,,T-1,Brazil,BRA,1,0,P-3,E,F,7,T-1,Brazil,BRA,108',108,0,extra time second half,0,0
4,G-4,WC-2014,x,M-2014-01,b,2014-06-12,g,Group A,T-3,Croatia,CRO,0,1,P-4,G,H,5,T-3,Croatia,CRO,11',11,0,first half,1,0
"""


def test_carga_reconstruye_score_90(tmp_path):
    (tmp_path / "matches.csv").write_text(MATCHES_CSV)
    (tmp_path / "goals.csv").write_text(GOALS_CSV)
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = mundiales.cargar(conexion, tmp_path / "matches.csv", tmp_path / "goals.csv")
    assert n == 2
    ko = conexion.execute("SELECT * FROM resultados_wc WHERE match_id='M-2014-60'").fetchone()
    # final con prórroga 1-1... el gol 108' NO cuenta para 90': score90 = 1-1
    assert (ko["goles90_local"], ko["goles90_visitante"]) == (1, 1)
    assert ko["prorroga"] == 1 and ko["penales"] == 1 and ko["es_eliminacion"] == 1
    grupo = conexion.execute("SELECT * FROM resultados_wc WHERE match_id='M-2014-01'").fetchone()
    # gol en contra de Croacia (own_goal=1, anotado por jugador de CRO) cuenta para Brasil:
    # el CSV de goles está incompleto a propósito — para grupos sin prórroga el marcador 90'
    # es el final del matches.csv (3-1), NO la suma de goles
    assert (grupo["goles90_local"], grupo["goles90_visitante"]) == (3, 1)
    assert grupo["es_grupos"] == 1
```

- [x] Step 2: implement `mundiales.py`:

```python
"""Mundiales 1930-2022 con marcador a 90' (datahub matches.csv + goals.csv)."""
from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

import httpx

URL_MATCHES = "https://datahub.io/football/worldcup/r/matches.csv"
URL_GOALS = "https://datahub.io/football/worldcup/r/goals.csv"
PERIODOS_90 = {"first half", "second half"}


def descargar(directorio: Path, http: httpx.Client | None = None) -> tuple[Path, Path]:
    cliente = http or httpx.Client(timeout=60, follow_redirects=True)
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = []
    for url, nombre in ((URL_MATCHES, "wc_matches.csv"), (URL_GOALS, "wc_goals.csv")):
        destino = directorio / nombre
        if not destino.exists():
            respuesta = cliente.get(url)
            respuesta.raise_for_status()
            destino.write_bytes(respuesta.content)
        rutas.append(destino)
    return rutas[0], rutas[1]


def _goles_90(ruta_goals: Path) -> dict[str, list[int]]:
    """{match_id: [goles90_local, goles90_visitante]} solo para partidos con prórroga."""
    conteo: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with open(ruta_goals, encoding="utf-8") as archivo:
        for gol in csv.DictReader(archivo):
            if gol["match_period"] not in PERIODOS_90:
                continue
            es_local = gol["home_team"] == "1"
            if gol.get("own_goal") == "1":
                es_local = not es_local
            conteo[gol["match_id"]][0 if es_local else 1] += 1
    return conteo


def cargar(conexion: sqlite3.Connection, ruta_matches: Path, ruta_goals: Path) -> int:
    goles90 = _goles_90(ruta_goals)
    filas = []
    with open(ruta_matches, encoding="utf-8") as archivo:
        for m in csv.DictReader(archivo):
            final = (int(m["home_team_score"]), int(m["away_team_score"]))
            con_prorroga = m["extra_time"] == "1"
            score90 = goles90.get(m["match_id"], list(final)) if con_prorroga else list(final)
            filas.append((
                m["match_id"], int(m["tournament_id"].split("-")[1]), m["stage_name"],
                int(m["group_stage"]), int(m["knockout_stage"]), m["match_date"],
                m["home_team_name"], m["away_team_name"],
                score90[0], score90[1], final[0], final[1],
                int(con_prorroga), int(m["penalty_shootout"] == "1"),
            ))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_wc VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    return len(filas)
```

- [x] Step 3: tests pass → wire into `actualizar.sincronizar` (try/except with ADVERTENCIA, download to `DIR_LOCAL`) → live run expects 1,248 filas → commit `feat: World Cup 90-minute results from datahub`.

### Task 12: confederaciones

**Files:** Create `data/static/confederaciones.csv` + `scripts/generar_confederaciones.py` is NOT needed — write the CSV directly; Modify `src/mundial/ingesta/estaticos.py`; Test `tests/test_estaticos.py` (extend).

- [x] Step 1: write `data/static/confederaciones.csv` with header `equipo,confederacion` and one row per team, canonical martj42 names. Content (132 teams):

```csv
equipo,confederacion
Argentina,CONMEBOL
Bolivia,CONMEBOL
Brazil,CONMEBOL
Chile,CONMEBOL
Colombia,CONMEBOL
Ecuador,CONMEBOL
Paraguay,CONMEBOL
Peru,CONMEBOL
Uruguay,CONMEBOL
Venezuela,CONMEBOL
Canada,CONCACAF
Costa Rica,CONCACAF
Cuba,CONCACAF
Curaçao,CONCACAF
El Salvador,CONCACAF
Guatemala,CONCACAF
Haiti,CONCACAF
Honduras,CONCACAF
Jamaica,CONCACAF
Mexico,CONCACAF
Nicaragua,CONCACAF
Panama,CONCACAF
Suriname,CONCACAF
Trinidad and Tobago,CONCACAF
United States,CONCACAF
Albania,UEFA
Armenia,UEFA
Austria,UEFA
Azerbaijan,UEFA
Belarus,UEFA
Belgium,UEFA
Bosnia and Herzegovina,UEFA
Bulgaria,UEFA
Croatia,UEFA
Cyprus,UEFA
Czech Republic,UEFA
Denmark,UEFA
England,UEFA
Estonia,UEFA
Finland,UEFA
France,UEFA
Georgia,UEFA
Germany,UEFA
Greece,UEFA
Hungary,UEFA
Iceland,UEFA
Israel,UEFA
Italy,UEFA
Kosovo,UEFA
Latvia,UEFA
Lithuania,UEFA
Luxembourg,UEFA
Malta,UEFA
Moldova,UEFA
Montenegro,UEFA
Netherlands,UEFA
North Macedonia,UEFA
Northern Ireland,UEFA
Norway,UEFA
Poland,UEFA
Portugal,UEFA
Republic of Ireland,UEFA
Romania,UEFA
Russia,UEFA
Scotland,UEFA
Serbia,UEFA
Slovakia,UEFA
Slovenia,UEFA
Spain,UEFA
Sweden,UEFA
Switzerland,UEFA
Turkey,UEFA
Ukraine,UEFA
Wales,UEFA
Algeria,CAF
Angola,CAF
Benin,CAF
Burkina Faso,CAF
Cameroon,CAF
Cape Verde,CAF
DR Congo,CAF
Egypt,CAF
Equatorial Guinea,CAF
Gabon,CAF
Gambia,CAF
Ghana,CAF
Guinea,CAF
Guinea-Bissau,CAF
Ivory Coast,CAF
Kenya,CAF
Libya,CAF
Madagascar,CAF
Mali,CAF
Mauritania,CAF
Morocco,CAF
Mozambique,CAF
Namibia,CAF
Niger,CAF
Nigeria,CAF
Senegal,CAF
Sierra Leone,CAF
South Africa,CAF
Sudan,CAF
Tanzania,CAF
Togo,CAF
Tunisia,CAF
Uganda,CAF
Zambia,CAF
Zimbabwe,CAF
Australia,AFC
Bahrain,AFC
China,AFC
India,AFC
Indonesia,AFC
Iran,AFC
Iraq,AFC
Japan,AFC
Jordan,AFC
Kuwait,AFC
Lebanon,AFC
Malaysia,AFC
North Korea,AFC
Oman,AFC
Qatar,AFC
Saudi Arabia,AFC
South Korea,AFC
Syria,AFC
Thailand,AFC
United Arab Emirates,AFC
Uzbekistan,AFC
Vietnam,AFC
Fiji,OFC
New Caledonia,OFC
New Zealand,OFC
Papua New Guinea,OFC
Solomon Islands,OFC
Tahiti,OFC
```

- [x] Step 2: failing test + loader `estaticos.cargar_confederaciones(conexion) -> int` (UPDATE equipos SET confederacion + INSERT OR IGNORE for teams not yet in equipos), called from `sincronizar`; live check: `mundial actualizar` then `SELECT COUNT(*) FROM equipos WHERE confederacion IS NULL AND nombre IN (SELECT local FROM partidos)` → 0 (the 48 WC teams all covered).
- [x] Step 3: commit `feat: confederations static data`.

### Task 13: motor de minería con BH

**Files:** Create `src/mundial/analisis/__init__.py` (empty), `src/mundial/analisis/mineria.py`; Test `tests/test_mineria.py`.

- [x] Step 1: failing tests:

```python
import numpy as np

from mundial.analisis import mineria


def test_bh_controla_nulos():
    rng = np.random.default_rng(7)
    candidatos = []
    for i in range(200):  # 200 hipótesis nulas: tasa real = baseline
        exitos = int(rng.binomial(80, 0.5))
        candidatos.append(mineria.Candidato(
            id=f"nulo_{i}", familia="nulos", hipotesis="x", filtro={},
            mercado_objetivo="over_under_25", lado="over@2.5",
            exitos=exitos, n=80, baseline=0.5))
    reportables = mineria.ajustar_bh(candidatos, q=0.10)
    assert sum(1 for c in reportables if c.reportable) <= 4  # FDR controlado


def test_detecta_efecto_plantado():
    candidatos = [mineria.Candidato(
        id="real", familia="f", hipotesis="x", filtro={}, mercado_objetivo="btts",
        lado="yes", exitos=70, n=100, baseline=0.5)]
    for i in range(50):
        candidatos.append(mineria.Candidato(
            id=f"n{i}", familia="f", hipotesis="x", filtro={}, mercado_objetivo="btts",
            lado="yes", exitos=50, n=100, baseline=0.5))
    resultado = mineria.ajustar_bh(candidatos, q=0.10)
    real = next(c for c in resultado if c.id == "real")
    assert real.reportable and real.p_adj < 0.05
    assert real.ic95[0] > 0.5  # IC de Wilson por encima del baseline


def test_familia_goles_por_fase(tmp_path):
    from mundial.persistencia import bd, esquema
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    filas = []
    for i in range(60):  # grupos: pocos goles; KO: muchos (efecto plantado)
        filas.append((f"g{i}", 2018, "group stage", 1, 0, "2018-06-14", "A", "B", 1, 0, 1, 0, 0, 0))
        filas.append((f"k{i}", 2018, "final", 0, 1, "2018-07-14", "A", "B", 3, 2, 3, 2, 0, 0))
    conexion.executemany("INSERT OR REPLACE INTO resultados_wc VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    candidatos = mineria.minar(conexion, anio_desde=1994)
    sobre_ko = [c for c in candidatos if c.familia == "goles_por_fase" and "eliminacion" in c.id and c.lado == "over@2.5"]
    assert sobre_ko and sobre_ko[0].exitos == 60 and sobre_ko[0].n == 60
```

- [x] Step 2: implement `mineria.py`:

```python
"""Minería de patrones con control de multiplicidad (BH) sobre datos históricos propios."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field


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
            ("over@2.5", overs, "over_under_25"), ("yes", btts, "btts"), ("empate", empates, "1x2"),
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
    agregar("tercer_puesto", "goles_por_fase", "el tercer puesto golea", {"fase": "third place"}, filas)
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
```

(El test de la Familia 1 usa la fase plantada; la Familia 4 usa una aproximación por orden — documentada — porque resultados_wc no trae jornada explícita.)

- [x] Step 3: tests pass → commit `feat: pattern mining engine with Benjamini-Hochberg control`.

### Task 14: CLI `minar`

**Files:** Modify `src/mundial/cli.py`; Test: covered by Task 13 (CLI is a thin printer).

- [x] Step 1: add command:

```python
@app.command()
def minar(anio_desde: int = typer.Option(1994, help="Inicio de la era a minar")) -> None:
    """Mina patrones históricos y escribe los candidatos (NO los activa)."""
    import json as json_lib

    from rich.table import Table

    from mundial.analisis import mineria
    from mundial.config import RAIZ

    conexion = _conexion_lista()
    candidatos = mineria.minar(conexion, anio_desde=anio_desde)
    reportables = [c for c in candidatos if c.reportable]
    tabla = Table(title=f"Candidatos reportables (BH q=0.10): {len(reportables)}/{len(candidatos)}")
    for col in ("id", "tasa", "baseline", "n", "p_adj", "IC95"):
        tabla.add_column(col)
    for c in sorted(reportables, key=lambda c: c.p_adj):
        tabla.add_row(c.id, f"{c.tasa():.3f}", f"{c.baseline:.3f}", str(c.n),
                      f"{c.p_adj:.4f}", f"[{c.ic95[0]:.2f},{c.ic95[1]:.2f}]")
    consola.print(tabla)
    ruta = RAIZ / "data" / "candidatos.json"
    ruta.write_text(json_lib.dumps([c.__dict__ for c in candidatos], indent=1, default=str,
                                   ensure_ascii=False))
    consola.print(f"Candidatos completos → {ruta}. Revisión humana antes de promover a "
                  f"data/patrones.json (Task 15).")
```

- [x] Step 2: live run `uv run mundial minar` → inspect table sanity (e.g. eliminacion empates ~0.30 with score90, NOT 0.21). Commit `feat: minar command writing pattern candidates`.

### Task 15: motor de patrones pre-registrados

**Files:** Create `src/mundial/notificaciones/patrones.py`, `data/patrones.json` (empty list `[]` initially); Test `tests/test_patrones.py`.

- [x] Step 1: failing tests:

```python
import json
import subprocess

from mundial.notificaciones import patrones
from mundial.persistencia import bd, esquema

PATRON = {
    "id": "empate_ko_parejo",
    "familia": "empates_ko",
    "hipotesis": "En eliminatorias parejas el empate a 90' está subvalorado",
    "filtro": {"fase_eliminacion": True, "diff_rating_max": 0.35},
    "mercado_objetivo": "1x2",
    "lado": "empate",
    "efecto": {"tasa": 0.41, "baseline": 0.31, "lift": 0.10},
    "n": 73, "p_adj_bh": 0.03, "ic95": [0.33, 0.49],
    "registrado_en_commit": "PENDIENTE",
    "ventana_validez": ["2026-06-11", "2026-07-19"],
    "umbral_prob_implicita": 0.32,
    "estado": "en_papel",
}


def contexto_prueba(**extra):
    base = {"fase_eliminacion": True, "jornada": None, "diff_rating": 0.2,
            "confederacion_local": "UEFA", "confederacion_visitante": "CONMEBOL",
            "dead_rubber_local": False, "dead_rubber_visitante": False, "fecha": "2026-06-29"}
    base.update(extra)
    return base


def test_filtro_declarativo():
    assert patrones.satisface(PATRON["filtro"], contexto_prueba())
    assert not patrones.satisface(PATRON["filtro"], contexto_prueba(diff_rating=0.9))
    assert not patrones.satisface(PATRON["filtro"], contexto_prueba(fase_eliminacion=False))


def test_condicion_de_precio():
    # prob implícita devig del empate 0.30 <= umbral 0.32 → dispara
    assert patrones.precio_cumple(PATRON, {"empate": 0.30})
    assert not patrones.precio_cumple(PATRON, {"empate": 0.35})


def test_validacion_preregistro_rechaza_no_commiteado(tmp_path):
    ruta = tmp_path / "patrones.json"
    ruta.write_text(json.dumps([PATRON]))
    activos = patrones.cargar_validados(ruta, fecha_partido="2026-06-29T19:00:00Z", repo=None)
    assert activos == []  # commit 'PENDIENTE' no existe → rechazado
```

- [x] Step 2: implement `patrones.py`:

```python
"""Patrones pre-registrados: carga validada por git, filtro declarativo, condición de precio."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mundial.config import RAIZ

RUTA_PATRONES = RAIZ / "data" / "patrones.json"
CLAVES_FILTRO = {
    "fase_eliminacion": lambda ctx, v: ctx.get("fase_eliminacion") == v,
    "jornada": lambda ctx, v: ctx.get("jornada") == v,
    "diff_rating_max": lambda ctx, v: ctx.get("diff_rating") is not None and ctx["diff_rating"] <= v,
    "diff_rating_min": lambda ctx, v: ctx.get("diff_rating") is not None and ctx["diff_rating"] >= v,
    "confederacion_local": lambda ctx, v: ctx.get("confederacion_local") == v,
    "confederacion_visitante": lambda ctx, v: ctx.get("confederacion_visitante") == v,
    "dead_rubber_alguno": lambda ctx, v: (ctx.get("dead_rubber_local") or ctx.get("dead_rubber_visitante")) == v,
    "es_anfitrion_local": lambda ctx, v: ctx.get("es_anfitrion_local") == v,
}


def satisface(filtro: dict, contexto: dict) -> bool:
    return all(
        clave in CLAVES_FILTRO and CLAVES_FILTRO[clave](contexto, valor)
        for clave, valor in filtro.items()
    )


def precio_cumple(patron: dict, p_implicitas: dict) -> bool:
    p = p_implicitas.get(patron["lado"])
    return p is not None and p <= patron["umbral_prob_implicita"]


def _commit_valido(commit: str, fecha_partido: str, repo: Path | None) -> bool:
    try:
        salida = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit],
            cwd=repo or RAIZ, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return bool(salida) and salida < fecha_partido
    except Exception:
        return False


def cargar_validados(ruta: Path | None = None, fecha_partido: str = "",
                     repo: Path | None = None) -> list[dict]:
    ruta = ruta or RUTA_PATRONES
    if not ruta.exists():
        return []
    cargados = json.loads(ruta.read_text(encoding="utf-8"))
    validos = []
    for patron in cargados:
        if patron.get("estado") not in ("activo", "en_papel"):
            continue
        ventana = patron.get("ventana_validez", ["", "9999"])
        if not (ventana[0] <= fecha_partido[:10] <= ventana[1]):
            continue
        if not _commit_valido(patron.get("registrado_en_commit", ""), fecha_partido, repo):
            continue
        validos.append(patron)
    return validos


def construir_contexto(conexion, partido_id: int) -> dict:
    partido = conexion.execute("SELECT * FROM partidos WHERE id=?", (partido_id,)).fetchone()
    ratings = {
        f["equipo"]: f["ataque"] + f["defensa"] for f in conexion.execute(
            """SELECT * FROM ratings WHERE fecha_ajuste =
               (SELECT MAX(fecha_ajuste) FROM ratings)""")
    }
    confederaciones = {
        f["nombre"]: f["confederacion"] for f in conexion.execute("SELECT * FROM equipos")
    }
    diff = None
    if partido["local"] in ratings and partido["visitante"] in ratings:
        diff = abs(ratings[partido["local"]] - ratings[partido["visitante"]])
    return {
        "fase_eliminacion": (partido["fase"] or "") not in ("GROUP_STAGE", "", None),
        "jornada": partido["jornada"],
        "diff_rating": diff,
        "confederacion_local": confederaciones.get(partido["local"]),
        "confederacion_visitante": confederaciones.get(partido["visitante"]),
        "dead_rubber_local": _dead_rubber(conexion, partido, partido["local"]),
        "dead_rubber_visitante": _dead_rubber(conexion, partido, partido["visitante"]),
        "es_anfitrion_local": partido["local"] in ("Mexico", "United States", "Canada"),
        "fecha": partido["fecha_utc"],
    }


def _dead_rubber(conexion, partido, equipo: str) -> bool:
    """Jornada 3: clasificación directa ya decidida ignorando la lotería de terceros
    (aproximación documentada: enumera los 3^k resultados restantes del grupo)."""
    if partido["jornada"] != 3 or not partido["grupo"]:
        return False
    filas = conexion.execute(
        "SELECT * FROM partidos WHERE grupo = ?", (partido["grupo"],)).fetchall()
    equipos = sorted({f["local"] for f in filas} | {f["visitante"] for f in filas})
    puntos = {e: 0 for e in equipos}
    pendientes = []
    for f in filas:
        if f["goles_local"] is not None:
            if f["goles_local"] > f["goles_visitante"]:
                puntos[f["local"]] += 3
            elif f["goles_local"] < f["goles_visitante"]:
                puntos[f["visitante"]] += 3
            else:
                puntos[f["local"]] += 1
                puntos[f["visitante"]] += 1
        else:
            pendientes.append((f["local"], f["visitante"]))
    posiciones = set()
    for combo in range(3 ** len(pendientes)):
        escenario = dict(puntos)
        c = combo
        for local, visitante in pendientes:
            r = c % 3
            c //= 3
            if r == 0:
                escenario[local] += 3
            elif r == 1:
                escenario[visitante] += 3
            else:
                escenario[local] += 1
                escenario[visitante] += 1
        orden = sorted(escenario, key=escenario.get, reverse=True)
        posiciones.add(orden.index(equipo) < 2)  # ¿termina top-2?
    return len(posiciones) == 1  # mismo destino en TODOS los escenarios
```

- [x] Step 3: tests pass → commit `feat: pre-registered pattern engine with git validation`.

### Task 16: alertas de patrones en vigilar + apuestas papel por patrón

**Files:** Modify `src/mundial/notificaciones/vigilar.py`; Test `tests/test_vigilar.py` (extend).

- [x] Step 1: failing test (seed `data/patrones.json` path param with a committed-hash patron — in the test use `repo=None` bypass: add `patrones_validados` injectable param to `vigilar()` so tests pass a list directly):

```python
def test_vigilar_alerta_patron(tmp_path):
    conexion = preparar_bd(tmp_path)
    # cuota de empate barata sembrada en `cuotas` para el partido 10 + patrón inyectado
    telegram = TelegramFalso()
    patron = {**PATRON_PRUEBA, "estado": "en_papel"}
    vigilar.vigilar(conexion, telegram, "42", ahora=AHORA, ruta_estado=tmp_path / "n.json",
                    patrones_validados=[patron])
    pre = next(m for m in telegram.mensajes if "Arranca" in m)
    assert "patrón pre-registrado" in pre
    apuesta = conexion.execute("SELECT * FROM apuestas WHERE origen LIKE 'patron:%'").fetchone()
    assert apuesta is not None
```

- [x] Step 2: implement in `vigilar.py` PRE block (after the prediction message is built):

```python
        patrones_activos = (
            patrones_validados if patrones_validados is not None
            else patrones_mod.cargar_validados(fecha_partido=partido["fecha_utc"])
        )
        if patrones_activos:
            contexto = patrones_mod.construir_contexto(conexion, partido["id"])
            for patron in patrones_activos:
                if not patrones_mod.satisface(patron["filtro"], contexto):
                    continue
                if patron["mercado_objetivo"] == "1x2":
                    p_imp, _, _ = mercado.cuotas_consenso(conexion, partido["id"])
                else:
                    p_imp, _, _ = mercado.cuotas_consenso_mercado(
                        conexion, partido["id"], patron["mercado_objetivo"])
                if not patrones_mod.precio_cumple(patron, p_imp):
                    continue
                texto += (
                    f"\n\n⚠️ <b>Patrón pre-registrado</b>: {patron['hipotesis']} — "
                    f"hist. {patron['efecto']['tasa']*100:.0f}% vs base "
                    f"{patron['efecto']['baseline']*100:.0f}% (n={patron['n']}, "
                    f"p_adj={patron['p_adj_bh']:.3f}). Apuesta de papel."
                )
                ledger.abrir_apuestas(
                    conexion, partido["id"],
                    [{"mercado": patron["mercado_objetivo"], "seleccion": patron["lado"],
                      "margen": patron["efecto"]["lift"], "sostenida": True}],
                    {patron["lado"]: patron["efecto"]["tasa"]},
                    ahora.isoformat(), origen=f"patron:{patron['id']}")
```

(imports: `from mundial.factores import mercado`, `from mundial.modelo import ledger`, `from mundial.notificaciones import patrones as patrones_mod`; `vigilar()` signature gains `patrones_validados: list | None = None`. Nota: para 1x2 el `lado` 'empate' coincide con las claves de `cuotas_consenso`.)

- [x] Step 3: tests pass → commit `feat: pattern alerts with price condition and pattern paper bets`.

### Task 17: xG post-partido + primera tanda de patrones

**Files:** Modify `src/mundial/ingesta/bsd.py`, `src/mundial/notificaciones/vigilar.py`, `src/mundial/dashboard/app.py`; Test `tests/test_bsd.py`, `tests/test_vigilar.py` (extend).

- [x] Step 1: failing tests:

```python
# test_bsd.py
def test_estadisticas():
    crudo = json.loads((FIXTURES / "bsd_stats.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/8287/stats/": crudo})
    datos = cliente.estadisticas(8287)
    assert datos["stats"]["home"]["expected_goals"] == 1.41

# test_vigilar.py — post-partido guarda xG si hay cliente BSD y vínculo
def test_vigilar_guarda_xg(tmp_path):
    conexion = preparar_bd(tmp_path)
    conexion.execute("INSERT INTO eventos_bsd VALUES (11, 8287)")
    conexion.commit()
    class BsdConStats:
        def estadisticas(self, evento_id):
            return json.loads((FIXTURES / "bsd_stats.json").read_text())
    vigilar.vigilar(conexion, TelegramFalso(), "42", ahora=AHORA,
                    ruta_estado=tmp_path / "n.json", cliente_bsd=BsdConStats())
    fila = conexion.execute("SELECT * FROM xg WHERE partido_id=11").fetchone()
    assert fila["xg_local"] == 1.41
    assert conexion.execute("SELECT COUNT(*) c FROM tiros WHERE partido_id=11").fetchone()["c"] == 19
```

- [x] Step 2: implement:
  - `bsd.py`: `def estadisticas(self, evento_id)` → GET `/events/{evento_id}/stats/`.
  - `vigilar.py` POST block, before sending the result message:

```python
        if cliente_bsd is not None:
            vinculo = conexion.execute(
                "SELECT evento_id FROM eventos_bsd WHERE partido_id=?", (partido["id"],)).fetchone()
            ya = conexion.execute("SELECT 1 FROM xg WHERE partido_id=?", (partido["id"],)).fetchone()
            if vinculo and not ya:
                try:
                    stats = cliente_bsd.estadisticas(vinculo["evento_id"])
                    xg_l = (stats.get("stats", {}).get("home") or {}).get("expected_goals")
                    xg_v = (stats.get("stats", {}).get("away") or {}).get("expected_goals")
                    if xg_l is not None:
                        conexion.execute("INSERT OR REPLACE INTO xg VALUES (?,?,?,?,?)",
                                         (partido["id"], xg_l, xg_v, "bsd", ahora.isoformat()))
                        conexion.executemany(
                            "INSERT OR REPLACE INTO tiros VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [(partido["id"], i, int(t.get("home") or 0), t.get("min"),
                              t.get("player_id"), t.get("xg"), t.get("xgot"), t.get("type"),
                              (t.get("pos") or {}).get("x"), (t.get("pos") or {}).get("y"))
                             for i, t in enumerate(stats.get("shotmap") or [])])
                        conexion.commit()
                except Exception:
                    pass
```

  and append xG line to `_mensaje_resultado` when available (`f"xG: {xg_l:.2f} - {xg_v:.2f}"` — pass via informe lookup or re-query inside).
  - dashboard `pagina_partido`: query xg table and show `st.metric("xG", ...)` when present.
- [x] Step 3: tests pass → live: run `uv run mundial minar`, review `data/candidatos.json` WITH THE USER, hand-write the first `data/patrones.json` entries (the KO-draw rule from the spec uses our own mined numbers; commit, capture the commit hash, edit `registrado_en_commit`, commit again) → `git push`. **M2 done.** Update CLAUDE.md (commands `minar`, `ledger`; pattern workflow; xG tables) and mark this plan's checkboxes.

## Self-review notes

- Spec coverage M1: pricing ✓(T2), λ-blend ✓(T6-7), multi-market loader ✓(T4), Shin 2-way ✓(T5), flags ✓(T8), ledger flat+¼Kelly+CLV ✓(T9), log-loss ✓(T10), MAX_GOLES ✓(T3). M2: dataset 90' ✓(T11), confederaciones ✓(T12), BH mining ✓(T13-14), pre-registro git + alertas + precio ✓(T15-16), xG ✓(T17), dashboard page Patrones queda como sección en T17 (página de partido) + el informe es candidatos.json/tabla CLI — si se quiere página dedicada, va en M3-M4 plan Task 24.
- Consistency: `Candidato` fields match between T13/T14; `cuotas_consenso_mercado` signature consistent T5/T8/T9/T16; `liquidar_*` return `(estado, retorno_flat_por_unidad)` everywhere; `vigilar(patrones_validados=None)` added once.
- AH sin cuota gratis continua: el ledger solo abre en `MERCADOS_APOSTABLES` con cuota real — AH queda en precios publicados (T7) y sondeos selectivos (plan M3-M4).
