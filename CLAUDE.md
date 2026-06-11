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
uv run mundial precision   # Brier/RPS: modelo vs mercado vs blend (needs finished matches)
uv run mundial fuentes     # source freshness, Odds API credits, DB counts
uv run streamlit run src/mundial/dashboard/app.py   # 5-page dashboard
uv run mundial telegram    # send today's digest to Telegram (--configurar to detect chat_id)
uv run pytest              # 68 tests, all offline
```

## Telegram notifications

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

**Maintenance loop during the tournament:** after each matchday run `mundial actualizar && mundial ratings` (results refresh the fit), then `mundial precision` to watch whether the model beats the market benchmark. Open TODOs: xG loader once a finished-match stats response can be inspected; player-importance via caps; optional GBM/SHAP layer; optional Streamlit Community Cloud publish.
