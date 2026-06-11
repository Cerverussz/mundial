# F2–F5 — Full Engine, Squad/Intangibles, Accuracy, Dashboard

> Consolidated plan. Build order: F2 → F4 → F5 → F3 (dashboard last, it displays everything).
> Executed inline with TDD; this doc records interfaces, critical math, and decisions.

**Probed facts (2026-06-11):**
- BSD `GET /events/{id}/lineups/?full=true` → `{lineup_status: "predicted"|..., lineups{home/away: {formation, confidence, players[{name, position, ai_score}]}}, unavailable_players{home/away: [{name, status: injured|suspended|doubtful, reason}]}}`. **ai_score = free player-importance proxy → Transfermarkt not needed (ToS gray zone avoided).**
- BSD `GET /events/{id}/?full=true` → includes `weather{temperature_c, wind_speed, code}`, `is_neutral_ground`, `travel_distance_km` (often null) → Open-Meteo client not needed.
- BSD post-match xG endpoint shape unverifiable today (no finished WC match) → **xG deferred**: documented TODO, not in this build.
- No finished WC matches yet → precision module ships now, produces output as results arrive.

## Schema additions (esquema.py, all IF NOT EXISTS)

`cuotas(partido_id, capturado_en, fuente, casa, mercado, local, empate, visitante, PK(partido_id,capturado_en,fuente,casa,mercado))` ·
`archivos_cargados(ruta PK, cargado_en)` ·
`eventos_bsd(partido_id PK, evento_id)` ·
`bajas(partido_id, equipo, jugador, estado, razon, ai_score, capturado_en, PK(partido_id,equipo,jugador,capturado_en))` ·
`predicciones(id PK AUTOINCREMENT, partido_id, creado_en, commit_datos, version_modelo, marcador, p_local/p_empate/p_visitante [blend], p_*_modelo, p_*_mercado, matriz_json, confianza, razones_confianza, factores_json, valor_flags)`

## F2 — engine

- `factores/mercado.py`: `quitar_margen_proporcional`, `quitar_margen_shin` (bisection on z∈[0,0.4] of p_i(z)=(√(z²+4(1−z)q_i²/s)−z)/(2(1−z)), Σp=1, fallback proportional when s≤1), `consenso(filas)` = per-book Shin de-vig → per-outcome **median** across books (excluding BSD's synthetic `consensus` book) → renormalize. `cuotas_consenso(conexion, partido_id, hasta=None)` reads latest row per (fuente,casa).
  - Tests: fair odds → identity; margin case sums to 1; **Shin shrinks longshots more than proportional**; consensus median robust to one crazy book.
- `ingesta/cargar_cuotas.py`: incremental loader of `data/snapshots/**` (tracked in `archivos_cargados`) → `cuotas` rows + `eventos_bsd` linkage. Match resolution: `(fecha[:10], frozenset{canonico(home), canonico(away)})` → partidos. Handles BSD payload (`comparaciones.*.markets.1x2.{HOME,DRAW,AWAY}.bookmakers`) and Odds API payload (list or `{eventos,presupuesto}`); h2h outcomes mapped by name == event's home/away.
- `modelo/prediccion.py`:
  - `matriz_marcadores(lam, mu, rho, max_goles=8)`: outer Poisson product, τ applied to the 2×2 low-score cells, renormalized.
  - `prob_1x2(matriz)`, `marcadores_top(matriz, n=3)`.
  - Factor pipeline, each returning `(nombre, mult_local, mult_visitante, detalle)`:
    - forma (10 matches/18 months, shrinkage +2 goals, √ damping, clip [0.85, 1.15]; needs ≥5 matches else neutral)
    - altitud (≥2000 m: ×0.94 attack for non-accustomed; 1500–2000: ×0.97; accustomed set: MEX/BOL/ECU/COL/PER/VEN/GUA/HON)
    - descanso (<4 days since last tournament match: ×0.97)
    - clima (BSD weather ≥30 °C: ×0.97 both; missing → neutral + razón)
    - h2h (avg goal diff last 10 H2H/10 years, ±2%/goal, clip ±4%)
  - `predecir(conexion, partido_id, ...)`: λs from latest ratings ⇒ factors ⇒ model matrix/probs ⇒ market consensus (Shin) ⇒ blend `w·modelo + (1−w)·mercado` (w=0.4) ⇒ **matrix rescaled to blended 1X2** (per-region scaling, renormalize) ⇒ score + top-3 ⇒ value flags (|p_mod−p_mer|>0.05, "sostenida" if also >0.05 against consensus ≥2 h older) ⇒ confianza ⇒ persist + diff vs previous prediction (cambios).
- `modelo/confianza.py`: score 100 − penalties (no odds −25; odds older than 6 h −10; <8 books −5; form data missing −10; team <10 matches in window −15 each; model-market divergence >15 pts −15; no lineup/bajas info −5). Alta ≥75 / Media ≥50 / Baja, with razones list. Pure function.
- `modelo/explicacion.py`: factor log → ordered Spanish lines (largest effects first), plus market summary. Pure.
- CLI: `predecir <ref>` (ref = `mex-rsa` TLAs or name substrings), `hoy`, `jornada N`. Output: timestamp, data freshness, **qué cambió desde la última consulta**, marcador + top-3, 1X2 (modelo/mercado/blend), confianza + razones, explicación, value flags. `actualizar` now also stores TLA in equipos and runs cargar_cuotas.

## F4 — squad & intangibles (xG deferred)

- `mundial snapshot` BSD payload gains `alineaciones[evento_id]` = lineups/?full=true for upcoming events (≤3 days). Cron then archives injury history in git.
- `ingesta/cargar_cuotas.py` also extracts `unavailable_players` + predicted-XI ai_scores → `bajas`.
- `factores/plantel.py`: per missing player weight = 0.04·ai_score (if in predicted XI) else 0.025; doubtful ×0.5; team factor f = clip(1−Σ, 0.88, 1) → own λ ×f, opponent λ ×(2−f).
- `factores/intangibles.py`: jornada 3 → ×0.99 both + confianza razón "posible rotación"; knockout → ×0.96 both; final/3er puesto → ×0.95 (knockouts produce fewer goals empirically). Documented heuristics.

## F5 — accuracy + sources

- `modelo/precision.py`: `brier(p, idx)` = Σ(p−y)²; `rps(p, idx)` = ½Σ_{k≤2}(cumP−cumY)²; `evaluar(conexion)`: last pre-kickoff prediction per finished match → per-prediction and aggregate Brier/RPS for modelo, mercado, blend. Hand-computed test vectors: uniform p vs home win → Brier 0.6667, RPS 0.2778.
- CLI `precision` (table) and `fuentes` (per-source last snapshot age + count today, Odds API credits from latest snapshot meta, DB row counts, last fit date). Snapshot meta: odds-api snapshot payload becomes `{eventos, presupuesto}` (loader handles both shapes).

## F3 — dashboard (Streamlit)

- Deps: streamlit, pandas, plotly. `src/mundial/dashboard/app.py` with `st.navigation` over 5 pages; pure data helpers in `dashboard/datos.py` (tested); pages thin.
  1. **Hoy/Jornada** — upcoming matches + latest stored prediction summary, button to recompute.
  2. **Partido** — score-matrix heatmap (plotly), 1X2 modelo/mercado/blend bars, factores, odds-evolution line (consensus over time from cuotas), bajas list.
  3. **Modelo vs mercado** — divergence table + value flags.
  4. **Precisión** — cumulative Brier/RPS vs market benchmark.
  5. **Sistema** — fuentes status (same data as CLI `fuentes`).
- Run: `uv run streamlit run src/mundial/dashboard/app.py`. Tests cover `datos.py` only; app smoke-checked by import/run.

## Close

- CLAUDE.md: phases F2–F5 done, new commands, factor caps table, xG TODO, decisions (ai_score over Transfermarkt, BSD weather over Open-Meteo). README usage update. Push + CI green.
