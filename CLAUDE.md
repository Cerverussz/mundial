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
uv run mundial snapshot   # capture odds → data/snapshots/
uv run pytest             # 13 tests, all offline
```

CI: `.github/workflows/snapshot.yml`, dual cron (`0 4-14/2 * * *` + `*/30 0-3,15-23 * * *` UTC), commits snapshots to main, `concurrency: snapshot`.

## Phase status

- **F0 DONE (2026-06-11):** snapshotter live (BSD 16-book comparisons + Odds API h2h), first real snapshot committed, CI cron active.
- **F1 next:** static stadium data (16 venues: altitude/coords/tz), fixtures/results ingestion (football-data.org → fifa → OpenLigaDB cascade), martj42 bootstrap, SQLite schema, Dixon-Coles base fit.
- **F2:** full engine (layers 1,3,4,6,7) + de-vig + blend + `mundial predecir/hoy/jornada`.
- **F3:** Streamlit dashboard (5 pages). **F4:** injuries/squad values/xG. **F5:** Brier/RPS tracking + optional GBM layer.

Update this file at the end of every phase.
