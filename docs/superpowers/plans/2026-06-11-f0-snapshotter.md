# F0 — Odds Snapshotter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship today a working odds snapshotter (BSD + The Odds API) running on a GitHub Actions cron that commits compressed snapshots to the public repo, so opening→closing odds history starts accumulating from day 0 of the World Cup.

**Architecture:** Python package `mundial` (src layout, uv). Two HTTP clients with injectable transports for testing, a gzip snapshot writer keyed by UTC timestamp, a Typer CLI command `mundial snapshot`, and a scheduled workflow that commits `data/snapshots/`. The Odds API is budget-limited (500 credits/month) so it is only queried when the latest persisted snapshot is older than 5 h — the snapshot directory itself is the budget state, which works identically locally and in CI.

**Tech Stack:** Python 3.12, uv, httpx, typer, rich, python-dotenv, pytest, GitHub Actions.

**Verified facts this plan relies on (probed 2026-06-11):**
- BSD auth header: `Authorization: Token <BSD_TOKEN>`. Base `https://sports.bzzoiro.com/api/v2`.
- BSD World Cup 2026 = `league_id=27`. Events: `GET /events/?league_id=27&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` (paginated, `count/next/results`).
- BSD per-event multi-bookmaker odds in one call: `GET /events/{id}/odds/comparison/` → `{event_id, event_date, league_id, home_team, away_team, bookmakers_count, markets: {"1x2": {HOME/DRAW/AWAY: {bookmakers: {slug: {decimal_odds, movement, updated_at}}}}, ...}}`. Real sample saved at `tests/fixtures/bsd_comparison.json` (event 8287, Mexico vs South Africa, 16 books).
- The Odds API: `GET https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=...` → list of events with `bookmakers[].markets[].outcomes[{name, price}]`. Headers `x-requests-remaining` / `x-requests-used` report credit budget. 1 credit per call (1 market × 1 region). ~5 calls/day ≈ 150/month — inside the 500 free credits.
- `.env` already exists locally (gitignored) with `BSD_TOKEN`, `FOOTBALL_DATA_KEY`, `ODDS_API_KEY`, `API_FOOTBALL_KEY`.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/mundial/__init__.py`
- Create: `src/mundial/config.py`
- Create: `tests/test_config.py`

- [x] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "mundial"
version = "0.1.0"
description = "Sistema de predicción de marcadores — Mundial 2026"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "typer>=0.12",
    "rich>=13",
    "python-dotenv>=1.0",
]

[project.scripts]
mundial = "mundial.cli:app"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.4"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mundial"]

[tool.ruff]
line-length = 100
```

- [x] **Step 2: Write `src/mundial/__init__.py`** (empty file) **and `src/mundial/config.py`**

```python
"""Configuración: claves de API y rutas del proyecto."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
DIR_SNAPSHOTS = RAIZ / "data" / "snapshots"
DIR_LOCAL = RAIZ / "data" / "local"

load_dotenv(RAIZ / ".env")


def clave(nombre: str) -> str:
    """Lee una clave del entorno; falla con mensaje claro si no existe."""
    valor = os.environ.get(nombre, "")
    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre} (revisa .env o los secrets de CI)")
    return valor
```

- [x] **Step 3: Write the test `tests/test_config.py`**

```python
import pytest

from mundial import config


def test_clave_presente(monkeypatch):
    monkeypatch.setenv("PRUEBA_CLAVE", "abc123")
    assert config.clave("PRUEBA_CLAVE") == "abc123"


def test_clave_faltante(monkeypatch):
    monkeypatch.delenv("NO_EXISTE", raising=False)
    with pytest.raises(RuntimeError, match="NO_EXISTE"):
        config.clave("NO_EXISTE")


def test_rutas_apuntan_al_repo():
    assert (config.RAIZ / "pyproject.toml").exists()
    assert config.DIR_SNAPSHOTS == config.RAIZ / "data" / "snapshots"
```

- [x] **Step 4: Install and run tests**

Run: `uv sync && uv run pytest -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "feat: project scaffold with config module"
```

---

### Task 2: Snapshot writer (`snapshots.py`)

**Files:**
- Create: `src/mundial/ingesta/__init__.py` (empty)
- Create: `src/mundial/ingesta/snapshots.py`
- Test: `tests/test_snapshots.py`

- [x] **Step 1: Write the failing tests**

```python
from datetime import datetime, timezone

from mundial.ingesta import snapshots


def test_escribir_y_leer_roundtrip(tmp_path):
    momento = datetime(2026, 6, 11, 14, 30, 5, tzinfo=timezone.utc)
    payload = {"hola": "mundo", "n": [1, 2, 3]}
    ruta = snapshots.escribir_snapshot("bsd", payload, momento=momento, base=tmp_path)
    assert ruta == tmp_path / "2026-06-11" / "143005Z-bsd.json.gz"
    contenido = snapshots.leer_snapshot(ruta)
    assert contenido["fuente"] == "bsd"
    assert contenido["capturado_en"] == "2026-06-11T14:30:05+00:00"
    assert contenido["payload"] == payload


def test_ultimo_snapshot_vacio(tmp_path):
    assert snapshots.ultimo_snapshot("bsd", base=tmp_path) is None


def test_ultimo_snapshot_encuentra_el_mas_reciente(tmp_path):
    t1 = datetime(2026, 6, 11, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 11, 14, 0, 0, tzinfo=timezone.utc)
    snapshots.escribir_snapshot("odds-api", {}, momento=t1, base=tmp_path)
    snapshots.escribir_snapshot("odds-api", {}, momento=t2, base=tmp_path)
    snapshots.escribir_snapshot("bsd", {}, momento=datetime(2026, 6, 12, 9, 0, 0, tzinfo=timezone.utc), base=tmp_path)
    assert snapshots.ultimo_snapshot("odds-api", base=tmp_path) == t2
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_snapshots.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError`.

- [x] **Step 3: Implement `src/mundial/ingesta/snapshots.py`**

```python
"""Escritura y lectura de snapshots crudos comprimidos (la bitácora del repo)."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from mundial.config import DIR_SNAPSHOTS


def escribir_snapshot(
    fuente: str,
    payload: dict | list,
    momento: datetime | None = None,
    base: Path | None = None,
) -> Path:
    momento = momento or datetime.now(timezone.utc)
    base = base or DIR_SNAPSHOTS
    carpeta = base / momento.strftime("%Y-%m-%d")
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{momento.strftime('%H%M%SZ')}-{fuente}.json.gz"
    contenido = {"fuente": fuente, "capturado_en": momento.isoformat(), "payload": payload}
    with gzip.open(ruta, "wt", encoding="utf-8") as archivo:
        json.dump(contenido, archivo, ensure_ascii=False, separators=(",", ":"))
    return ruta


def leer_snapshot(ruta: Path) -> dict:
    with gzip.open(ruta, "rt", encoding="utf-8") as archivo:
        return json.load(archivo)


def ultimo_snapshot(fuente: str, base: Path | None = None) -> datetime | None:
    """Momento del snapshot más reciente de una fuente, o None si no hay."""
    base = base or DIR_SNAPSHOTS
    rutas = sorted(base.glob(f"*/*-{fuente}.json.gz"))
    if not rutas:
        return None
    return datetime.fromisoformat(leer_snapshot(rutas[-1])["capturado_en"])
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_snapshots.py -v`
Expected: 3 passed. (Note `ultimo_snapshot` relies on lexicographic path order == chronological order, which the `YYYY-MM-DD/HHMMSSZ` naming guarantees.)

- [x] **Step 5: Commit**

```bash
git add src/mundial/ingesta tests/test_snapshots.py
git commit -m "feat: gzip snapshot writer with latest-snapshot lookup"
```

---

### Task 3: BSD client

**Files:**
- Create: `src/mundial/ingesta/bsd.py`
- Test: `tests/test_bsd.py` (uses real captured fixtures `tests/fixtures/bsd_eventos.json`, `tests/fixtures/bsd_comparison.json`)

- [x] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path

import httpx

from mundial.ingesta.bsd import LIGA_MUNDIAL, ClienteBsd

FIXTURES = Path(__file__).parent / "fixtures"


def cliente_con_respuestas(respuestas: dict[str, dict]) -> ClienteBsd:
    """ClienteBsd cuyo transporte responde según el path solicitado."""

    def responder(solicitud: httpx.Request) -> httpx.Response:
        assert solicitud.headers["Authorization"] == "Token token-prueba"
        return httpx.Response(200, json=respuestas[solicitud.url.path])

    return ClienteBsd("token-prueba", transporte=httpx.MockTransport(responder))


def test_eventos_devuelve_resultados():
    pagina = json.loads((FIXTURES / "bsd_eventos.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/": pagina})
    eventos = cliente.eventos(desde="2026-06-11", hasta="2026-06-12")
    assert len(eventos) == 1
    assert eventos[0]["home_team"] == "Mexico"
    assert eventos[0]["id"] == 8287


def test_eventos_sigue_paginacion():
    primera = {"count": 2, "next": "https://x/api/v2/events/?offset=1", "results": [{"id": 1}]}
    # El cliente debe pedir la URL de `next` hasta agotarla; ambas páginas comparten path.
    paginas = iter([primera, {"count": 2, "next": None, "results": [{"id": 2}]}])

    def responder(solicitud: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(paginas))

    cliente = ClienteBsd("t", transporte=httpx.MockTransport(responder))
    assert [e["id"] for e in cliente.eventos()] == [1, 2]


def test_comparacion_cuotas():
    comparacion = json.loads((FIXTURES / "bsd_comparison.json").read_text())
    cliente = cliente_con_respuestas({"/api/v2/events/8287/odds/comparison/": comparacion})
    datos = cliente.comparacion_cuotas(8287)
    assert datos["home_team"] == "Mexico"
    assert datos["bookmakers_count"] == 16
    assert "1x2" in datos["markets"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bsd.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mundial.ingesta.bsd'`.

- [x] **Step 3: Implement `src/mundial/ingesta/bsd.py`**

```python
"""Cliente de Bzzoiro Sports Data (BSD) — cuotas multi-casa, eventos del Mundial."""
from __future__ import annotations

import httpx

BASE = "https://sports.bzzoiro.com/api/v2"
LIGA_MUNDIAL = 27


class ClienteBsd:
    def __init__(self, token: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=BASE,
            headers={"Authorization": f"Token {token}"},
            timeout=30,
            transport=transporte,
        )

    def eventos(
        self,
        liga: int = LIGA_MUNDIAL,
        desde: str | None = None,
        hasta: str | None = None,
    ) -> list[dict]:
        """Eventos de una liga, siguiendo la paginación completa."""
        parametros = {"league_id": liga, "limit": 200}
        if desde:
            parametros["date_from"] = desde
        if hasta:
            parametros["date_to"] = hasta
        resultados: list[dict] = []
        respuesta = self._http.get("/events/", params=parametros)
        respuesta.raise_for_status()
        pagina = respuesta.json()
        resultados.extend(pagina["results"])
        while pagina.get("next"):
            respuesta = self._http.get(pagina["next"])
            respuesta.raise_for_status()
            pagina = respuesta.json()
            resultados.extend(pagina["results"])
        return resultados

    def comparacion_cuotas(self, evento_id: int) -> dict:
        """Cuotas de todas las casas para un evento, en una sola llamada."""
        respuesta = self._http.get(f"/events/{evento_id}/odds/comparison/")
        respuesta.raise_for_status()
        return respuesta.json()
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bsd.py -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add src/mundial/ingesta/bsd.py tests/test_bsd.py tests/fixtures
git commit -m "feat: BSD client with paginated events and odds comparison"
```

---

### Task 4: The Odds API client

**Files:**
- Create: `src/mundial/ingesta/odds_api.py`
- Create: `tests/fixtures/odds_api_h2h.json` (captured in Step 1)
- Test: `tests/test_odds_api.py`

- [x] **Step 1: Capture a real fixture (costs 1 of 500 monthly credits)**

```bash
set -a; source .env; set +a
curl -sS "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey=$ODDS_API_KEY" -o tests/fixtures/odds_api_h2h.json
python3 -m json.tool tests/fixtures/odds_api_h2h.json | head -5
```

Expected: JSON array of events with `bookmakers`.

- [x] **Step 2: Write the failing tests**

```python
import json
from pathlib import Path

import httpx

from mundial.ingesta.odds_api import ClienteOddsApi

FIXTURES = Path(__file__).parent / "fixtures"


def test_cuotas_h2h_devuelve_eventos_y_presupuesto():
    eventos = json.loads((FIXTURES / "odds_api_h2h.json").read_text())

    def responder(solicitud: httpx.Request) -> httpx.Response:
        assert solicitud.url.params["apiKey"] == "clave-prueba"
        assert solicitud.url.params["markets"] == "h2h"
        return httpx.Response(
            200, json=eventos, headers={"x-requests-remaining": "499", "x-requests-used": "1"}
        )

    cliente = ClienteOddsApi("clave-prueba", transporte=httpx.MockTransport(responder))
    datos, presupuesto = cliente.cuotas_h2h()
    assert isinstance(datos, list)
    assert presupuesto == {"restantes": "499", "usadas": "1"}
```

- [x] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_odds_api.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 4: Implement `src/mundial/ingesta/odds_api.py`**

```python
"""Cliente de The Odds API — respaldo de cuotas, presupuesto de 500 créditos/mes."""
from __future__ import annotations

import httpx

BASE = "https://api.the-odds-api.com/v4"
DEPORTE_MUNDIAL = "soccer_fifa_world_cup"


class ClienteOddsApi:
    def __init__(self, clave: str, transporte: httpx.BaseTransport | None = None):
        self._clave = clave
        self._http = httpx.Client(base_url=BASE, timeout=30, transport=transporte)

    def cuotas_h2h(self) -> tuple[list, dict]:
        """Cuotas 1X2 del Mundial (región eu). Devuelve (eventos, presupuesto)."""
        respuesta = self._http.get(
            f"/sports/{DEPORTE_MUNDIAL}/odds/",
            params={
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "apiKey": self._clave,
            },
        )
        respuesta.raise_for_status()
        presupuesto = {
            "restantes": respuesta.headers.get("x-requests-remaining"),
            "usadas": respuesta.headers.get("x-requests-used"),
        }
        return respuesta.json(), presupuesto
```

- [x] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_odds_api.py -v`
Expected: 1 passed.

- [x] **Step 6: Commit**

```bash
git add src/mundial/ingesta/odds_api.py tests/test_odds_api.py tests/fixtures/odds_api_h2h.json
git commit -m "feat: The Odds API client reporting credit budget headers"
```

---

### Task 5: CLI `mundial snapshot`

**Files:**
- Create: `src/mundial/cli.py`
- Test: `tests/test_cli.py`

Behavior: always snapshot BSD (events for the next 3 days + per-event odds comparison, with a 0.4 s pause between calls to respect throttling); snapshot The Odds API only if its latest snapshot is older than `--horas-min-odds-api` (default 5 h, so ~5 calls/day ≈ 150 credits/month). Print a Spanish summary including the Odds API credits remaining.

- [x] **Step 1: Write the failing tests**

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from mundial import cli
from mundial.ingesta import snapshots

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


class BsdFalso:
    def eventos(self, liga=27, desde=None, hasta=None):
        return json.loads((FIXTURES / "bsd_eventos.json").read_text())["results"]

    def comparacion_cuotas(self, evento_id):
        return json.loads((FIXTURES / "bsd_comparison.json").read_text())


class OddsApiFalso:
    llamadas = 0

    def cuotas_h2h(self):
        OddsApiFalso.llamadas += 1
        return [], {"restantes": "499", "usadas": "1"}


def preparar(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_cliente_bsd", lambda: BsdFalso())
    monkeypatch.setattr(cli, "_cliente_odds_api", lambda: OddsApiFalso())
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", tmp_path)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    OddsApiFalso.llamadas = 0


def test_snapshot_escribe_ambas_fuentes(monkeypatch, tmp_path):
    preparar(monkeypatch, tmp_path)
    resultado = runner.invoke(cli.app, ["snapshot"])
    assert resultado.exit_code == 0, resultado.output
    rutas = sorted(p.name for p in tmp_path.glob("*/*.json.gz"))
    assert any("-bsd" in r for r in rutas)
    assert any("-odds-api" in r for r in rutas)
    assert "499" in resultado.output


def test_snapshot_respeta_presupuesto_odds_api(monkeypatch, tmp_path):
    preparar(monkeypatch, tmp_path)
    reciente = datetime.now(timezone.utc) - timedelta(hours=1)
    snapshots.escribir_snapshot("odds-api", [], momento=reciente, base=tmp_path)
    resultado = runner.invoke(cli.app, ["snapshot"])
    assert resultado.exit_code == 0, resultado.output
    assert OddsApiFalso.llamadas == 0
    assert "omitido" in resultado.output.lower()


def test_snapshot_bsd_incluye_comparaciones(monkeypatch, tmp_path):
    preparar(monkeypatch, tmp_path)
    runner.invoke(cli.app, ["snapshot"])
    ruta_bsd = next(tmp_path.glob("*/*-bsd.json.gz"))
    contenido = snapshots.leer_snapshot(ruta_bsd)
    assert contenido["payload"]["eventos"][0]["id"] == 8287
    assert contenido["payload"]["comparaciones"]["8287"]["home_team"] == "Mexico"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mundial.cli'`.

- [x] **Step 3: Implement `src/mundial/cli.py`**

```python
"""CLI del sistema de predicción del Mundial 2026."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import typer
from rich.console import Console

from mundial.config import DIR_SNAPSHOTS, clave
from mundial.ingesta import snapshots
from mundial.ingesta.bsd import ClienteBsd
from mundial.ingesta.odds_api import ClienteOddsApi

app = typer.Typer(help="Sistema de predicción de marcadores — Mundial 2026")
consola = Console()

DIAS_VENTANA = 3
PAUSA_ENTRE_LLAMADAS_S = 0.4


def _cliente_bsd() -> ClienteBsd:
    return ClienteBsd(clave("BSD_TOKEN"))


def _cliente_odds_api() -> ClienteOddsApi:
    return ClienteOddsApi(clave("ODDS_API_KEY"))


@app.command()
def snapshot(
    horas_min_odds_api: float = typer.Option(
        5.0, help="No consultar The Odds API si su último snapshot es más reciente que esto."
    ),
) -> None:
    """Captura cuotas y las persiste en data/snapshots/ (la bitácora del repo)."""
    ahora = datetime.now(timezone.utc)
    hoy = date.today()

    bsd = _cliente_bsd()
    eventos = bsd.eventos(
        desde=hoy.isoformat(), hasta=(hoy + timedelta(days=DIAS_VENTANA)).isoformat()
    )
    comparaciones: dict[str, dict] = {}
    for evento in eventos:
        if evento.get("status") == "finished":
            continue
        comparaciones[str(evento["id"])] = bsd.comparacion_cuotas(evento["id"])
        time.sleep(PAUSA_ENTRE_LLAMADAS_S)
    ruta_bsd = snapshots.escribir_snapshot(
        "bsd", {"eventos": eventos, "comparaciones": comparaciones},
        momento=ahora, base=DIR_SNAPSHOTS,
    )
    consola.print(
        f"[green]BSD[/]: {len(eventos)} eventos, {len(comparaciones)} comparaciones → {ruta_bsd}"
    )

    ultimo = snapshots.ultimo_snapshot("odds-api", base=DIR_SNAPSHOTS)
    if ultimo and (ahora - ultimo) < timedelta(hours=horas_min_odds_api):
        consola.print(
            f"[yellow]The Odds API omitido[/]: último snapshot hace "
            f"{(ahora - ultimo).total_seconds() / 3600:.1f} h (< {horas_min_odds_api} h)"
        )
        return
    datos, presupuesto = _cliente_odds_api().cuotas_h2h()
    ruta_odds = snapshots.escribir_snapshot("odds-api", datos, momento=ahora, base=DIR_SNAPSHOTS)
    consola.print(
        f"[green]The Odds API[/]: {len(datos)} eventos → {ruta_odds} "
        f"(créditos restantes: {presupuesto['restantes']})"
    )
```

Note for the implementer: the tests monkeypatch `cli.DIR_SNAPSHOTS`, so `snapshot()` must reference the module-level name (as shown) rather than importing it inside the function.

- [x] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: all pass (3 config + 3 snapshots + 3 bsd + 1 odds-api + 3 cli = 13).

- [x] **Step 5: First real snapshot (live run)**

Run: `uv run mundial snapshot`
Expected: green lines for BSD (≥3 events — today has Mexico–South Africa 19:00Z plus 2 more matches through Jun 12-14 window) and The Odds API with remaining credits ≈ 497. Verify: `ls data/snapshots/$(date -u +%Y-%m-%d)/`.

- [x] **Step 6: Commit (code + first snapshot)**

```bash
git add src/mundial/cli.py tests/test_cli.py data/snapshots
git commit -m "feat: mundial snapshot CLI command; first live snapshot"
```

---

### Task 6: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/snapshot.yml`

- [x] **Step 1: Write the workflow**

```yaml
name: snapshot

on:
  schedule:
    - cron: "0 4-14/2 * * *"        # base: cada 2 h fuera del horario de partidos
    - cron: "*/30 0-3,15-23 * * *"  # cada 30 min en horario diario de partidos (UTC)
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: snapshot
  cancel-in-progress: false

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run mundial snapshot
        env:
          BSD_TOKEN: ${{ secrets.BSD_TOKEN }}
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
      - name: Commit snapshots
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/snapshots
          if git diff --cached --quiet; then
            echo "Sin snapshots nuevos"
          else
            git commit -m "snapshot: $(date -u +%Y-%m-%dT%H:%MZ)"
            git pull --rebase origin main
            git push
          fi
```

- [x] **Step 2: Commit**

```bash
git add .github/workflows/snapshot.yml
git commit -m "ci: scheduled odds snapshot workflow"
```

---

### Task 7: README, CLAUDE.md, publish repo, verify workflow

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`
- Create: `.env.example`

- [x] **Step 1: Write `.env.example`**

```bash
# Claves de API — regístrate gratis (sin tarjeta) y copia este archivo a .env
BSD_TOKEN=            # https://sports.bzzoiro.com/register/
FOOTBALL_DATA_KEY=    # https://www.football-data.org/client/register
ODDS_API_KEY=         # https://the-odds-api.com/
API_FOOTBALL_KEY=     # https://api-sports.io/ (solo histórico 2022-2024 en tier gratis)
```

- [x] **Step 2: Write `README.md`** — setup in English: prerequisites (uv), `uv sync`, copy `.env.example` → `.env`, run `uv run mundial snapshot`, run `uv run pytest`. Link to the spec at `docs/superpowers/specs/` and note that `data/snapshots/` is committed by CI on a schedule. Include the GitHub Secrets needed (`BSD_TOKEN`, `ODDS_API_KEY`).

- [x] **Step 3: Write `CLAUDE.md`** covering: project goal (one paragraph); architecture summary (snapshots-in-git, SQLite derived, cascade); the source table with limits and verified facts (BSD league_id=27, comparison endpoint, auth header; The Odds API 500 credits/month and the 5 h snapshot spacing rule; football-data.org TIER_ONE WC only; API-Football free tier useless for 2026 — verified); layer coverage STRONG/MEDIUM/WEAK table; conventions (Spanish domain names in code, Spanish CLI/dashboard output, English commits/README, TDD with pytest, uv); how to run (snapshot command, tests); phase status (F0 done, F1-F5 pending per spec). Keep it under ~120 lines; update it at the end of every phase.

- [x] **Step 4: Commit docs**

```bash
git add README.md CLAUDE.md .env.example
git commit -m "docs: README, CLAUDE.md and .env.example"
```

- [x] **Step 5: Create the public repo and push**

```bash
gh auth status   # verify auth first; if missing, ask the user to run `gh auth login`
gh repo create mundial --public --source=. --remote=origin --push
```

Expected: repo created at `<user>/mundial`, main branch pushed. If the name is taken, use `mundial-2026`.

- [x] **Step 6: Set Actions secrets**

```bash
set -a; source .env; set +a
gh secret set BSD_TOKEN --body "$BSD_TOKEN"
gh secret set ODDS_API_KEY --body "$ODDS_API_KEY"
```

- [x] **Step 7: Trigger and verify the workflow**

```bash
gh workflow run snapshot.yml
sleep 90
gh run list --workflow=snapshot.yml --limit 1
```

Expected: status `completed success`, and a new commit `snapshot: ...` on main (`git pull` to confirm locally). If it fails, `gh run view --log-failed`.

---

## Self-review notes

- Spec coverage: this plan implements F0 only (spec §12); F1-F5 get their own plans.
- The Odds API spacing (5 h) is enforced via snapshot-directory state, which CI inherits through checkout — no separate budget store needed in F0; the full `presupuesto` module arrives in F1 when football-data.org's 10 req/min enters.
- Type consistency: `escribir_snapshot(fuente, payload, momento, base)` used identically in Tasks 2, 5; clients take `transporte` kwarg in Tasks 3, 4, 5.
- Known follow-up for F1 (not F0): BSD `status` enum for finished matches must be verified (`finished` assumed from schema enum) — only used as a skip-filter here, harmless if wrong.
