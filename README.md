# Mundial — World Cup 2026 score prediction system

A "continuous knowledge" football prediction system: every query pulls the freshest data available, recalculates, and returns the most likely exact score, 1X2 probabilities, a confidence level, and an explanation of the driving factors — plus a model-vs-market comparison built on de-vigged bookmaker odds.

Built exclusively on **free data sources** (no paid tiers, no credit card). A scheduled GitHub Actions workflow snapshots multi-bookmaker odds into [`data/snapshots/`](data/snapshots/) every 30–120 minutes, so the repo's git history doubles as an auditable opening→closing odds archive — the dataset paid APIs charge for, accumulated at zero cost.

## Status

All phases live (built June 11, 2026 — tournament day 1):

- **Snapshotter** (CI cron): multi-book odds + lineups/absences archived to git every 30–120 min.
- **Data backbone:** 16 stadiums (altitude/coords/tz), 49k historical internationals (CC0), WC fixtures with source cascade (football-data.org → api.fifa.com).
- **Engine:** time-weighted Dixon-Coles (analytic gradients) + layered factors (form, altitude, rest, weather, H2H, absences, match importance) + Shin de-vigged market consensus + configurable blend + value flags + confidence with reasons.
- **CLI:** `predecir`, `hoy`, `jornada`, `actualizar`, `ratings`, `snapshot`, `precision`, `fuentes` — Spanish output.
- **Dashboard:** 5-page Streamlit app (matches, match detail with score-matrix heatmap and odds evolution, model-vs-market, accuracy, system health).
- **Accuracy tracking:** Brier + RPS per prediction, model vs market benchmark vs blend.

See the full design in [docs/superpowers/specs/](docs/superpowers/specs/2026-06-10-mundial-prediccion-design.md) and the architecture notes in [CLAUDE.md](CLAUDE.md).

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/Cerverussz/mundial.git
cd mundial
uv sync
cp .env.example .env   # then fill in your API keys
```

Register (free, no card) and put the keys in `.env`:

| Key | Where to register | Free limits |
|---|---|---|
| `BSD_TOKEN` | [sports.bzzoiro.com](https://sports.bzzoiro.com/register/) | no quota (burst throttling) |
| `ODDS_API_KEY` | [the-odds-api.com](https://the-odds-api.com/) | 500 credits/month |
| `FOOTBALL_DATA_KEY` | [football-data.org](https://www.football-data.org/client/register) | 10 req/min |
| `API_FOOTBALL_KEY` | [api-sports.io](https://api-sports.io/) | 100 req/day (seasons 2022–2024 only) |

## Usage

```bash
uv run mundial snapshot   # capture current odds into data/snapshots/
uv run pytest             # run the test suite
```

The CLI output is in Spanish (project convention; code identifiers use Spanish domain names, commits and this README are in English).

## CI snapshots

`.github/workflows/snapshot.yml` runs on a dual cron (every 2 h off-peak, every 30 min during daily match windows) and commits new snapshots to `main`. It needs two repository secrets: `BSD_TOKEN` and `ODDS_API_KEY`. The Odds API is only queried when its latest snapshot is older than 5 h, keeping usage at ~150 of the 500 monthly free credits.
