# CLAUDE.md — Mundial (World Cup 2026 prediction system)

## What this is

Continuous-knowledge score prediction system for international football (2026 World Cup first). Every query pulls the freshest data, recalculates, and returns: most likely exact score + top 3, 1X2 probabilities, confidence with reasons, factor explanation (in Spanish), and model-vs-market comparison with value flags. No stake sizing. Free data sources only — no paid tiers, no cards.

Full spec: `docs/superpowers/specs/2026-06-10-mundial-prediccion-design.md`. Plans live in `docs/superpowers/plans/`.

## Architecture (approved decisions)

- **Snapshots-in-git:** GitHub Actions cron captures raw odds/injury data as `data/snapshots/YYYY-MM-DD/HHMMSSZ-<fuente>.json.gz`, committed to this public repo. Git history IS the versioned, auditable data log.
- **SQLite is derived, never committed:** `data/local/` (gitignored) is rebuilt from snapshots. Predictions reference the data commit hash + model version for auditability.
- **Source cascade, never hard-fail:** every data type has primary → backup; missing data degrades confidence and is declared in the output.
- **Model:** Dixon-Coles with temporal decay (half-life ≈ 730 days) bootstrapped from martj42 CC0 historical results; multiplicative per-layer λ adjustments (form, altitude/rest/travel/weather, weighted absences, match importance), each logged for the explanation. Market: proportional + Shin de-vig, multi-book median consensus; official 1X2 = configurable blend (default w=0.4 model); value flag at >5 pt sustained divergence. Home advantage only for MEX/USA/CAN (rest is neutral venue).

## Data sources — verified facts (2026-06-11)

| Source | Free limits | Use | Verified facts |
|---|---|---|---|
| BSD `sports.bzzoiro.com/api/v2` | no quota, 429 burst throttle | PRIMARY odds/injuries/xG/lineups | Auth `Authorization: Token $BSD_TOKEN`. World Cup 2026 = `league_id=27`. `GET /events/{id}/odds/comparison/` = all ~16 books in 1 call. Events paginated (`count/next/results`), filters `date_from/date_to/league_id/team_name`. **Solo-dev project, 1 server, outage-prone → never single point of failure** |
| The Odds API v4 | **500 credits/month** | backup odds | `soccer_fifa_world_cup`, h2h+eu = 1 credit/call. Budget headers `x-requests-remaining/used`. CLI spaces calls ≥5 h apart (~150 credits/month) |
| football-data.org v4 | 10 req/min | fixtures/results backbone | WC 2026 confirmed on free TIER_ONE (`competitions/WC`, season id 2398). No qualifiers/friendlies/odds/xG on free |
| api.fifa.com v3 | none (undocumented) | fixtures + full squads | `idCompetition=17, idSeason=285023`; squads at `/teams/squads/all/17/285023` |
| eloratings.net | none | national-team Elo | plain TSV: `/World.tsv`, positional columns, updated daily |
| martj42/international_results | CC0 | ratings bootstrap | 49k matches 1872→today, cols: date,home_team,away_team,home_score,away_score,tournament,city,country,neutral |
| Open-Meteo | free, no key | weather layer | — |
| API-Football | 100 req/day | (nearly useless) | **Free tier = seasons 2022–2024 only — NO World Cup 2026** (verified by live call) |
| TheSportsDB key `123` | 30 req/min, capped lists | badges/logos only | free key returns only 15/104 WC events |

Discarded: FotMob (vendor actively objects to scraping), Understat (club leagues only), FBref (xG exists but Cloudflare → Selenium; optional future), BALLDONTLIE (requires card).

Layer coverage honesty: STRONG = ratings, form, context, H2H, forward odds history. MEDIUM = xG (BSD quality unverified), squad availability (BSD single-source), intangibles. WEAK = historical odds (we only have what we snapshot, starting 2026-06-11) and broad historical international xG.

## Conventions

- Python 3.12, **uv** (`uv sync`, `uv run`). Typer CLI + Rich. pytest with TDD (write failing test first). Ruff, line length 100.
- **Spanish domain names** in code (`ingesta`, `factores`, `modelo`, `persistencia`, `cuotas`, `escribir_snapshot`), Spanish CLI/dashboard output, English commits/README. Deliberate choice — do not "fix" to English.
- HTTP clients take a `transporte: httpx.BaseTransport` kwarg so tests inject `httpx.MockTransport` — no network in tests. Real captured API responses live in `tests/fixtures/`.
- Secrets via `.env` (gitignored, never commit) and GitHub Secrets (`BSD_TOKEN`, `ODDS_API_KEY`) for Actions. `config.clave("NAME")` raises with a clear message if missing.
- Typer app uses an `@app.callback()` no-op so `mundial snapshot` stays a subcommand.

## How to run

```bash
uv sync
uv run mundial snapshot    # capture odds + lineups/absences → data/snapshots/
uv run mundial actualizar  # sync stadiums, 49k historical results, WC fixtures, odds → SQLite
uv run mundial ratings     # fit Dixon-Coles on last 10y, store ratings, print top 10
uv run mundial predecir mex-rsa   # predict a match (TLA pair or name substrings)
uv run mundial hoy / jornada 1    # predict today's matches / a group-stage matchday
uv run mundial ledger      # paper-trading: PnL flat, yield, CLV medio
uv run mundial minar       # mine WC patterns (BH q=0.10) → data/candidatos.json (no activa)
uv run mundial gbm         # train+gate the GBM layer (activates only if it beats DC in ALL blocks)
uv run mundial calibrar [--aplicar]  # tune blend weight w by log-loss with shrinkage
uv run mundial sondear mex-rsa       # probe real AH/totals via The Odds API (~5 credits)
uv run mundial checkpoint  # tournament dashboard: accuracy, ledger/CLV, w, GBM, patterns
uv run mundial precision   # Brier/RPS/log-loss: modelo vs mercado vs blend (needs finished matches)
uv run mundial fuentes     # source freshness, Odds API credits, DB counts
uv run streamlit run src/mundial/dashboard/app.py   # 5-page dashboard
uv run mundial telegram    # send today's digest to Telegram (--configurar to detect chat_id)
uv run pytest              # 68 tests, all offline
```

## Telegram notifications

**Per-match watcher (`mundial vigilar` + `vigilar.yml`, cron */30 during 13:00-04:30 UTC):** sends the analysis ~2.5 h before each kickoff and the result right after each match finishes (final score, predicted score, ✅/❌ 1X2 with the probability given to the actual outcome, ✅/❌ exact score, cumulative hit rates + RPS vs market verdict). Idempotence across stateless CI runners via `data/notificaciones.json` (committed). Predictions persist across runs as JSONL in `data/predicciones/` (exported by predict commands and vigilar, imported by `actualizar` via INSERT OR IGNORE on unique (partido_id, creado_en)).

**Hard-won fact (2026-06-11):** football-data.org free tier can report `FINISHED` with NULL scores for hours; `actualizar` merges scores per-field from the FIFA calendar (cascade applies per-field, not per-source). Also: late-night kickoffs (01-02 UT C) belong to the next UTC date — never filter "today's matches" by `date(fecha_utc)`; the digest window runs [00:00, next-day 05:00) and per-match timing lives in vigilar.

`notificaciones/telegram.py` + `.github/workflows/telegram.yml` (cron 13:00 UTC pre-match digest, 04:30 UTC results digest). The CI job rebuilds the DB (actualizar → ratings) and sends fresh predictions — it is a *notification* layer; audit-grade prediction history accumulates where the CLI runs persistently. Secrets needed: `TELEGRAM_BOT_TOKEN` (from @BotFather), `TELEGRAM_CHAT_ID` (via `mundial telegram --configurar`), plus `FOOTBALL_DATA_KEY`. Messages are HTML, chunked at 4,000 chars; a match whose prediction fails degrades to one line, never kills the digest.

## Engine facts (F2-F5, 2026-06-11)

- Pipeline per prediction: λs from latest ratings → multiplicative factors (each logged for the Spanish explanation) → DC score matrix (τ on 0-0/0-1/1-0/1-1) → model 1X2 → market consensus (per-book **Shin de-vig**, median across books excl. synthetic `consensus`) → blend `0.4·model + 0.6·market` → **matrix rescaled to blended 1X2** → score + top-3.
- Factor caps: forma ±15% (≥5 matches, shrinkage +2, √ damping) · altitud −6%/−3% (≥2000/≥1500 m, accustomed list exempt) · descanso −3% (<4 days) · clima −3% (≥30 °C, from BSD event detail) · H2H ±4% (±2%/avg goal) · bajas down to −12% (0.04·ai_score per starter, 0.025 unknown, doubtful ×0.5) · fase: knockout ×0.96, final ×0.95, matchday 3 ×0.99.
- Value flags: model−market > 5 pts; "sostenida" if also >5 pts vs consensus ≥2 h older. Confianza Alta/Media/Baja from penalties (no odds −25, stale odds −10, few books −5, weak form data −10, <10 matches/team −15, divergence>15pts −15, no lineup info −5).
- Real home advantage only when host nation plays in its own country (ANFITRIONES map in prediccion.py); all other WC matches are neutral.
- `cuotas` accumulates every snapshot (opening→closing history); `predicciones` stores blend+model+market probs, matrix JSON, factors JSON, git data-commit hash. `precision.evaluar` uses the LAST pre-kickoff prediction per finished match.
- Decisions: player importance via BSD predicted-XI `ai_score` (injured players aren't in the XI, so they usually weigh 0.025 — refine later with caps from /worldcup/squads/); BSD `weather` instead of Open-Meteo; **xG deferred** — no finished WC match existed to verify the stats endpoint shape (revisit after matchday 1); optional GBM/SHAP layer documented as future work, not built.

CI: `.github/workflows/snapshot.yml`, dual cron (`0 4-14/2 * * *` + `*/30 0-3,15-23 * * *` UTC), commits snapshots to main, `concurrency: snapshot`.

## Model facts (F1 fit, 2026-06-11)

- `modelo/dixon_coles.py`: weighted NLL with analytic gradients (gradient-checked vs finite differences), L-BFGS-B, ρ bounded ±0.5, L2 1e-3 for identifiability, attack/defense centered post-fit (μ compensated). Real fit: 9,476 matches / 263 teams in 0.4 s; home advantage 0.231, ρ −0.061; top-10 sanity = Argentina/Spain/England/Brazil… ✓.
- Known quirk: non-FIFA teams (e.g. Basque Country) can rank high on few friendly wins — harmless for WC predictions; consider FIFA-member filter or higher `partidos_minimos` if it bothers downstream features.
- Name canonicalization: `actualizar.canonico()` via `data/static/mapeo_nombres.csv` (canonical = martj42 names). `mundial actualizar` warns about unmapped teams — keep that at 0.
- football-data free tier has NO venue → stadiums joined from FIFA calendar on `(utcDate, home tla)`; knockout TBD matches skipped until teams defined.

## Phase status

- **F0 DONE (2026-06-11):** snapshotter live (BSD 16-book comparisons + Odds API h2h), first real snapshot committed, CI cron active.
- **F1 DONE (2026-06-11):** SQLite schema; 16 stadiums static; martj42 loader (skips NA-score future fixtures); football-data→FIFA cascade with degradation messages; `mundial actualizar` + `mundial ratings`; Dixon-Coles fit stored in `ratings`/`modelo_meta`.
- **F2 DONE (2026-06-11):** full engine + de-vig + blend + value flags + `predecir/hoy/jornada`. First real prediction: Mexico 2-0 South Africa (model 80/14/6 vs market 68/21/11, 39 books).
- **F4 DONE (2026-06-11):** snapshot captures lineups+absences (cron archives injury history in git); plantel + intangibles factors live. xG deferred (see Engine facts).
- **F5 DONE (2026-06-11):** Brier/RPS evaluation (modelo vs mercado vs blend) + `precision` + `fuentes`.
- **F3 DONE (2026-06-11):** Streamlit dashboard, 5 pages, helpers tested in `dashboard/datos.py`.
- **M1 DONE (2026-06-12):** derived markets (O/U, BTTS, DNB/AH) priced+settled from one matrix (`modelo/mercados.py`); λ-space blend via market inversion (`modelo/inversion.py`) so every market is coherent in result AND total; 11 markets loaded from snapshots into `cuotas_mercado` (62k rows reprocessed); generic Shin consensus; multi-market value flags; paper-trading ledger with CLV vs pre-kickoff close (`modelo/ledger.py`, `mundial ledger`); log-loss added to precision.
- **M2 DONE (2026-06-12):** WC 1930-2022 with reconstructed 90-min scores (`resultados_wc`, datahub — fixes the ET-inflated KO draw rate); confederations static; BH-corrected mining engine (`analisis/mineria.py`, `mundial minar`); pre-registered pattern engine with git-commit validation + declarative filter + price condition (`notificaciones/patrones.py`, `data/patrones.json`); pattern alerts + pattern paper-bets in vigilar; post-match xG/shots loader (BSD `/stats/`) into `xg`/`tiros` + dashboard xG metric. **Mining finding: 0 patterns survive BH q=0.10 on WC-only data** — third-place over-2.5 (73%, n=15) looks real but n<30; "matchday-3 goals" and "KO low-scoring" do NOT beat same-era baseline. `data/patrones.json` stays empty until a pattern passes our own gate; market-bias patterns (KO-draw underpricing) await odds-history for backtest.

## Engine facts (M1-M2)

- `mercados.py`: AH/totals from the score matrix with push + quarter-line half-win/half-loss; settlement returns `(estado, retorno_por_unidad)`; DNB = AH 0; `MAX_GOLES` raised 8→10. Tests pin obvious cases (h=-0.5 ≡ P(D≥1)).
- λ-blend: invert (λ_mkt, μ_mkt) by 2D Newton from de-vigged DNB + Over 2.5; blend in λ-space; matrix still rescaled to blended 1X2 (contract intact). Fallback to 1X2 rescale when those 2-way markets are absent (`origen_matriz` declares which). BSD always ships 1X2 with the 2-way markets, so multi-market flags live inside the `if p_mercado:` block.
- Ledger: flat 1u (primary) + ¼-Kelly (learning); opens only on SUSTAINED flags in markets with real odds (AH excluded — no free odds); CLV = taken_odds × close_devig_prob − 1; yield needs n huge for significance, CLV is the tournament metric. `liquidar_pendientes` settles in vigilar post-match.
- Patterns: `data/patrones.json` entries need `registrado_en_commit` to predate the match (git `%cI` check) or they're rejected; alert fires only if filter matches AND best de-vigged price ≤ `umbral_prob_implicita`; pattern bets get `origen=patron:<id>` (separate ledger stream). `minar` writes `data/candidatos.json` (gitignored, regenerated).

- **M3 DONE (2026-06-12):** point-in-time `ratings_asof` (anti-leakage, `entrenar.py`); LightGBM ordinal (Frank-Hall 2 binaries, isotonic, monotone constraints) on 22 t<match features (`gbm.py`); strict all-blocks walk-forward gate + 3-signal log-linear pool + SHAP. **Gate verdict on real 49k: GBM LOSES to Dixon-Coles in 3/4 blocks (RPS Δ~0.002) → NOT activated** (`config.gbm_activo='0'`), exactly as the no-odds-features literature predicts. Infra kept for learning/SHAP. Needs `libomp` on macOS (`brew install libomp`); Ubuntu CI has libgomp1; the `lightgbm` import is lazy so the core pipeline never requires it.
- **M4 DONE (2026-06-12):** blend-weight calibration by log-loss + shrinkage to w₀=0.4 (`calibracion.py`, `mundial calibrar`); selective AH/totals probes via The Odds API event endpoint (`mundial sondear`, ~5 cr); confirmed-XI alert from FIFA live (`/live/football/...`, **Status==1 = starter, verified against a real lineup**) in vigilar; `mundial checkpoint`; dashboard "Patrones y ledger" page (6 pages now).

**Maintenance loop during the tournament:** after each matchday run `mundial actualizar && mundial ratings`, then `mundial checkpoint` (accuracy, ledger/CLV, w, GBM, patterns in one view). Re-run `mundial minar` after group stage with 2026 out-of-sample; `mundial calibrar --aplicar` once enough finished matches accumulate; `mundial gbm` to re-test the gate as the sample grows. The pipeline is feature-complete per both plans — open future work: promote a pattern to `data/patrones.json` only when it passes its own gate; optional Streamlit Cloud publish.
