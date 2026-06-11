# F1 — Data Backbone & Dixon-Coles Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local SQLite populated with static stadium data, all WC2026 fixtures/results (football-data.org → FIFA cascade), 49k historical international results (martj42), and a fitted Dixon-Coles base model with per-team attack/defense ratings stored and sanity-checked.

**Architecture:** `persistencia/` owns the SQLite schema (derived cache, gitignored). `ingesta/` gains three clients (football-data, FIFA, martj42 downloader) and an `actualizar` orchestrator implementing the cascade with declared degradation. `modelo/dixon_coles.py` implements weighted Dixon-Coles (exponential time decay, half-life 730 days; low-score ρ correction; home advantage only for non-neutral) with analytic gradients, fitted via L-BFGS-B; `modelo/entrenar.py` persists ratings. CLI gains `mundial actualizar` and `mundial ratings`.

**Tech Stack:** numpy, scipy (new deps), sqlite3 (stdlib), csv (stdlib), httpx, pytest.

**Verified facts (probed 2026-06-11):**
- football-data.org `GET /v4/competitions/WC/matches` → `matches[]` with `id, utcDate, status (TIMED/FINISHED), matchday, stage, group, homeTeam{name,tla}, awayTeam{...}, score.fullTime{home,away}`. **No venue on free tier.** Knockout matches have null team names until defined → skip those rows. Fixture saved: `tests/fixtures/fd_matches.json`.
- api.fifa.com calendar (`idCompetition=17&idSeason=285023&count=500`) → `Results[]` (104) with `IdMatch, Date, Stadium.Name[0].Description` (16 exact names: "Mexico City Stadium", "BC Place Vancouver", …), `GroupName[0].Description`, `Home/Away.{Abbreviation, TeamName[0].Description}`, `HomeTeamScore/AwayTeamScore`. Trimmed fixture: `tests/fixtures/fifa_calendar.json`.
- martj42 `results.csv`: header `date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`; 49,477 data rows; **future WC fixtures present with score `NA`** — loader must skip score-less rows. Names: "United States", "South Korea", "Iran", "Ivory Coast" (≠ FIFA "USA", "Korea Republic", "IR Iran", "Côte d'Ivoire") → static name mapping + runtime unmapped-team warning.
- Join key between football-data and FIFA: `(utcDate, homeTeam.tla == Home.Abbreviation)`.

---

### Task 1: Dependencies + SQLite schema

**Files:** Modify `pyproject.toml` (add numpy, scipy); Create `src/mundial/persistencia/__init__.py` (empty), `src/mundial/persistencia/bd.py`, `src/mundial/persistencia/esquema.py`; Test `tests/test_persistencia.py`.

- [x] Step 1: add `"numpy>=2.0", "scipy>=1.13",` to `[project] dependencies`; run `uv sync`.
- [x] Step 2: failing tests:

```python
from mundial.persistencia import bd, esquema


def test_conectar_crea_archivo(tmp_path):
    conexion = bd.conectar(tmp_path / "x" / "mundial.db")
    conexion.execute("CREATE TABLE t(a)")
    assert (tmp_path / "x" / "mundial.db").exists()


def test_esquema_idempotente(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    esquema.crear(conexion)
    tablas = {f["name"] for f in conexion.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"equipos", "estadios", "partidos", "resultados_historicos",
            "ratings", "modelo_meta"} <= tablas
```

- [x] Step 3: run `uv run pytest tests/test_persistencia.py -v` → FAIL (module missing).
- [x] Step 4: implement `bd.py`:

```python
"""Conexión SQLite local (caché derivado, nunca commiteado)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from mundial.config import DIR_LOCAL


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or (DIR_LOCAL / "mundial.db")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    return conexion
```

and `esquema.py`:

```python
"""Esquema de la base local. Idempotente."""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS equipos(
  nombre TEXT PRIMARY KEY,
  tla TEXT,
  confederacion TEXT
);
CREATE TABLE IF NOT EXISTS estadios(
  nombre TEXT PRIMARY KEY,
  ciudad TEXT, pais TEXT,
  altitud_m REAL, lat REAL, lon REAL, tz TEXT
);
CREATE TABLE IF NOT EXISTS partidos(
  id INTEGER PRIMARY KEY,
  fecha_utc TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  fase TEXT, grupo TEXT, jornada INTEGER,
  estadio TEXT,
  estado TEXT,
  goles_local INTEGER, goles_visitante INTEGER,
  id_fifa TEXT,
  fuente TEXT
);
CREATE TABLE IF NOT EXISTS resultados_historicos(
  fecha TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  goles_local INTEGER NOT NULL,
  goles_visitante INTEGER NOT NULL,
  torneo TEXT, ciudad TEXT, pais TEXT,
  neutral INTEGER NOT NULL,
  PRIMARY KEY(fecha, local, visitante)
);
CREATE TABLE IF NOT EXISTS ratings(
  equipo TEXT NOT NULL,
  fecha_ajuste TEXT NOT NULL,
  ataque REAL NOT NULL,
  defensa REAL NOT NULL,
  PRIMARY KEY(equipo, fecha_ajuste)
);
CREATE TABLE IF NOT EXISTS modelo_meta(
  fecha_ajuste TEXT PRIMARY KEY,
  mu REAL, ventaja_local REAL, rho REAL,
  n_partidos INTEGER, n_equipos INTEGER,
  log_verosimilitud REAL,
  version TEXT
);
"""


def crear(conexion: sqlite3.Connection) -> None:
    conexion.executescript(DDL)
    conexion.commit()
```

- [x] Step 5: tests pass → commit `feat: SQLite schema and connection module`.

---

### Task 2: Static stadium data

**Files:** Create `data/static/estadios.csv`, `src/mundial/ingesta/estaticos.py`; Test `tests/test_estaticos.py`.

- [x] Step 1: write `data/static/estadios.csv` keyed by exact FIFA names (altitudes approximate, good enough for the altitude adjustment which only materially matters for Mexico City/Guadalajara/Monterrey):

```csv
nombre,ciudad,pais,altitud_m,lat,lon,tz
Mexico City Stadium,Mexico City,Mexico,2240,19.3029,-99.1505,America/Mexico_City
Guadalajara Stadium,Guadalajara,Mexico,1548,20.6817,-103.4626,America/Mexico_City
Monterrey Stadium,Monterrey,Mexico,540,25.6692,-100.2444,America/Monterrey
Atlanta Stadium,Atlanta,United States,290,33.7554,-84.4010,America/New_York
Boston Stadium,Boston,United States,89,42.0909,-71.2643,America/New_York
Dallas Stadium,Dallas,United States,184,32.7473,-97.0945,America/Chicago
Houston Stadium,Houston,United States,15,29.6847,-95.4107,America/Chicago
Kansas City Stadium,Kansas City,United States,265,39.0489,-94.4839,America/Chicago
Los Angeles Stadium,Los Angeles,United States,30,33.9535,-118.3392,America/Los_Angeles
Miami Stadium,Miami,United States,3,25.9580,-80.2389,America/New_York
New York/New Jersey Stadium,New Jersey,United States,3,40.8135,-74.0745,America/New_York
Philadelphia Stadium,Philadelphia,United States,12,39.9008,-75.1675,America/New_York
San Francisco Bay Area Stadium,San Francisco Bay Area,United States,26,37.4033,-121.9694,America/Los_Angeles
Seattle Stadium,Seattle,United States,5,47.5952,-122.3316,America/Los_Angeles
Toronto Stadium,Toronto,Canada,76,43.6332,-79.4186,America/Toronto
BC Place Vancouver,Vancouver,Canada,5,49.2767,-123.1119,America/Vancouver
```

- [x] Step 2: failing test:

```python
from mundial.ingesta import estaticos
from mundial.persistencia import bd, esquema


def test_cargar_estadios(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = estaticos.cargar_estadios(conexion)
    assert n == 16
    azteca = conexion.execute(
        "SELECT * FROM estadios WHERE nombre='Mexico City Stadium'").fetchone()
    assert azteca["altitud_m"] == 2240
    assert azteca["tz"] == "America/Mexico_City"
```

- [x] Step 3: implement `estaticos.py`:

```python
"""Carga de datos estáticos (estadios del Mundial 2026) a la base local."""
from __future__ import annotations

import csv
import sqlite3

from mundial.config import RAIZ

RUTA_ESTADIOS = RAIZ / "data" / "static" / "estadios.csv"


def cargar_estadios(conexion: sqlite3.Connection) -> int:
    with open(RUTA_ESTADIOS, encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    conexion.executemany(
        "INSERT OR REPLACE INTO estadios VALUES (:nombre,:ciudad,:pais,:altitud_m,:lat,:lon,:tz)",
        filas,
    )
    conexion.commit()
    return len(filas)
```

- [x] Step 4: test passes → commit `feat: WC2026 stadium static data (altitude, coords, tz)`.

---

### Task 3: martj42 historical results loader

**Files:** Create `src/mundial/ingesta/martj42.py`; Test `tests/test_martj42.py` (small inline CSV).

- [x] Step 1: failing tests:

```python
import httpx

from mundial.ingesta import martj42
from mundial.persistencia import bd, esquema

CSV_PRUEBA = """date,home_team,away_team,home_score,away_score,tournament,city,country,neutral
2024-07-14,Argentina,Colombia,1,0,Copa América,Miami Gardens,United States,TRUE
2025-03-20,Mexico,Canada,2,0,CONCACAF Nations League,Inglewood,United States,TRUE
2026-06-27,Panama,England,NA,NA,FIFA World Cup,East Rutherford,United States,TRUE
"""


def test_cargar_salta_filas_sin_marcador(tmp_path):
    ruta = tmp_path / "results.csv"
    ruta.write_text(CSV_PRUEBA)
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    n = martj42.cargar(conexion, ruta)
    assert n == 2
    fila = conexion.execute(
        "SELECT * FROM resultados_historicos WHERE local='Argentina'").fetchone()
    assert fila["goles_local"] == 1 and fila["neutral"] == 1


def test_descargar_usa_cache_reciente(tmp_path):
    ruta = tmp_path / "results.csv"
    ruta.write_text(CSV_PRUEBA)

    def responder(solicitud):
        raise AssertionError("No debería tocar la red con caché fresca")

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    assert martj42.descargar(ruta, http=cliente) == ruta


def test_descargar_baja_si_no_existe(tmp_path):
    ruta = tmp_path / "results.csv"

    def responder(solicitud):
        return httpx.Response(200, text=CSV_PRUEBA)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    martj42.descargar(ruta, http=cliente)
    assert "Argentina" in ruta.read_text()
```

- [x] Step 2: run → FAIL. Step 3: implement:

```python
"""Histórico de partidos internacionales 1872→hoy (martj42, CC0)."""
from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

import httpx

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE_HORAS = 24.0


def descargar(destino: Path, http: httpx.Client | None = None) -> Path:
    if destino.exists() and (time.time() - destino.stat().st_mtime) < CACHE_HORAS * 3600:
        return destino
    cliente = http or httpx.Client(timeout=60, follow_redirects=True)
    respuesta = cliente.get(URL)
    respuesta.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(respuesta.content)
    return destino


def cargar(conexion: sqlite3.Connection, ruta: Path) -> int:
    """Inserta resultados con marcador (salta fixtures futuros con NA)."""
    filas = []
    with open(ruta, encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            if not fila["home_score"].isdigit() or not fila["away_score"].isdigit():
                continue
            filas.append(
                (
                    fila["date"], fila["home_team"], fila["away_team"],
                    int(fila["home_score"]), int(fila["away_score"]),
                    fila["tournament"], fila["city"], fila["country"],
                    1 if fila["neutral"].upper() == "TRUE" else 0,
                )
            )
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas
    )
    conexion.commit()
    return len(filas)
```

- [x] Step 4: tests pass → commit `feat: martj42 historical results downloader and loader`.

---

### Task 4: football-data + FIFA clients

**Files:** Create `src/mundial/ingesta/football_data.py`, `src/mundial/ingesta/fifa.py`; copy probes `/tmp/fd_matches.json` → `tests/fixtures/fd_matches.json` and trimmed `/tmp/fifa_cal.json` (first 6 Results) → `tests/fixtures/fifa_calendar.json`; Test `tests/test_clientes_fixtures.py`.

- [x] Step 1: save fixtures (trim FIFA to 6 matches with `python3 -c "..."`).
- [x] Step 2: failing tests:

```python
import json
from pathlib import Path

import httpx

from mundial.ingesta.fifa import ClienteFifa
from mundial.ingesta.football_data import ClienteFootballData

FIXTURES = Path(__file__).parent / "fixtures"


def test_football_data_partidos():
    pagina = json.loads((FIXTURES / "fd_matches.json").read_text())

    def responder(solicitud):
        assert solicitud.headers["X-Auth-Token"] == "clave-prueba"
        return httpx.Response(200, json=pagina)

    cliente = ClienteFootballData("clave-prueba", transporte=httpx.MockTransport(responder))
    partidos = cliente.partidos_mundial()
    assert partidos[0]["homeTeam"]["tla"] == "MEX"


def test_fifa_calendario_simplificado():
    crudo = json.loads((FIXTURES / "fifa_calendar.json").read_text())

    def responder(solicitud):
        return httpx.Response(200, json=crudo)

    cliente = ClienteFifa(transporte=httpx.MockTransport(responder))
    calendario = cliente.calendario()
    primero = calendario[0]
    assert primero["local_tla"] == "MEX"
    assert primero["estadio"] == "Mexico City Stadium"
    assert primero["grupo"] == "Group A"
    assert primero["id_fifa"] == "400021443"
```

- [x] Step 3: implement `football_data.py`:

```python
"""Cliente de football-data.org v4 — backbone de fixtures/resultados (10 req/min)."""
from __future__ import annotations

import httpx

BASE = "https://api.football-data.org/v4"


class ClienteFootballData:
    def __init__(self, clave: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=BASE, headers={"X-Auth-Token": clave}, timeout=30, transport=transporte
        )

    def partidos_mundial(self) -> list[dict]:
        respuesta = self._http.get("/competitions/WC/matches")
        respuesta.raise_for_status()
        return respuesta.json()["matches"]
```

and `fifa.py`:

```python
"""Cliente de api.fifa.com v3 (no documentada) — respaldo de fixtures + estadios."""
from __future__ import annotations

import httpx

BASE = "https://api.fifa.com/api/v3"
ID_COMPETICION = 17
ID_TEMPORADA = 285023


def _descripcion(lista) -> str | None:
    return lista[0].get("Description") if lista else None


def _equipo(crudo: dict | None) -> dict:
    crudo = crudo or {}
    return {
        "tla": crudo.get("Abbreviation"),
        "nombre": _descripcion(crudo.get("TeamName") or []),
    }


class ClienteFifa:
    def __init__(self, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=BASE, timeout=30, transport=transporte)

    def calendario(self) -> list[dict]:
        respuesta = self._http.get(
            "/calendar/matches",
            params={
                "idCompetition": ID_COMPETICION,
                "idSeason": ID_TEMPORADA,
                "language": "en",
                "count": 500,
            },
        )
        respuesta.raise_for_status()
        simplificados = []
        for m in respuesta.json().get("Results", []):
            local, visitante = _equipo(m.get("Home")), _equipo(m.get("Away"))
            simplificados.append(
                {
                    "id_fifa": m.get("IdMatch"),
                    "fecha_utc": m.get("Date"),
                    "estadio": _descripcion((m.get("Stadium") or {}).get("Name") or []),
                    "grupo": _descripcion(m.get("GroupName") or []),
                    "local_tla": local["tla"],
                    "local_nombre": local["nombre"],
                    "visitante_tla": visitante["tla"],
                    "visitante_nombre": visitante["nombre"],
                    "goles_local": m.get("HomeTeamScore"),
                    "goles_visitante": m.get("AwayTeamScore"),
                }
            )
        return simplificados
```

- [x] Step 4: tests pass → commit `feat: football-data and FIFA calendar clients`.

---

### Task 5: Name mapping + `actualizar` orchestrator

**Files:** Create `data/static/mapeo_nombres.csv`, `src/mundial/ingesta/actualizar.py`; Test `tests/test_actualizar.py`. Modify `src/mundial/cli.py` (add command).

- [x] Step 1: starter mapping (extend at runtime check; canonical = martj42 names):

```csv
nombre_fuente,nombre_canonico
USA,United States
Korea Republic,South Korea
IR Iran,Iran
Côte d'Ivoire,Ivory Coast
Cabo Verde,Cape Verde
China PR,China
Czechia,Czech Republic
```

- [x] Step 2: failing tests (fake clients from fixtures; degraded-cascade case):

```python
import json
from pathlib import Path

from mundial.ingesta import actualizar
from mundial.persistencia import bd, esquema

FIXTURES = Path(__file__).parent / "fixtures"


class FdFalso:
    def partidos_mundial(self):
        return json.loads((FIXTURES / "fd_matches.json").read_text())["matches"]


class FdCaido:
    def partidos_mundial(self):
        raise RuntimeError("503")


class FifaFalso:
    def calendario(self):
        from mundial.ingesta.fifa import ClienteFifa
        import httpx

        crudo = json.loads((FIXTURES / "fifa_calendar.json").read_text())
        transporte = httpx.MockTransport(lambda s: httpx.Response(200, json=crudo))
        return ClienteFifa(transporte=transporte).calendario()


def preparar_bd(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    return conexion


def test_sincroniza_partidos_y_enriquece_estadio(tmp_path):
    conexion = preparar_bd(tmp_path)
    mensajes = actualizar.sincronizar(
        conexion, cliente_fd=FdFalso(), cliente_fifa=FifaFalso(), cargar_historico=False
    )
    fila = conexion.execute("SELECT * FROM partidos WHERE id=537327").fetchone()
    assert fila["local"] == "Mexico"
    assert fila["estadio"] == "Mexico City Stadium"
    assert fila["fuente"] == "football-data"
    assert any("partidos" in m for m in mensajes)


def test_cascada_degrada_a_fifa(tmp_path):
    conexion = preparar_bd(tmp_path)
    mensajes = actualizar.sincronizar(
        conexion, cliente_fd=FdCaido(), cliente_fifa=FifaFalso(), cargar_historico=False
    )
    filas = conexion.execute("SELECT * FROM partidos").fetchall()
    assert len(filas) >= 1
    assert filas[0]["fuente"] == "fifa"
    assert any("ADVERTENCIA" in m for m in mensajes)


def test_canonico_aplica_mapeo():
    assert actualizar.canonico("Korea Republic") == "South Korea"
    assert actualizar.canonico("Mexico") == "Mexico"
```

- [x] Step 3: implement `actualizar.py`:

```python
"""Orquestación de sincronización: estáticos → histórico → fixtures (cascada fd → FIFA)."""
from __future__ import annotations

import csv
import sqlite3
from functools import lru_cache

from mundial.config import DIR_LOCAL, RAIZ, clave
from mundial.ingesta import estaticos, martj42
from mundial.ingesta.fifa import ClienteFifa
from mundial.ingesta.football_data import ClienteFootballData

RUTA_MAPEO = RAIZ / "data" / "static" / "mapeo_nombres.csv"


@lru_cache(maxsize=1)
def _mapeo() -> dict[str, str]:
    with open(RUTA_MAPEO, encoding="utf-8") as archivo:
        return {f["nombre_fuente"]: f["nombre_canonico"] for f in csv.DictReader(archivo)}


def canonico(nombre: str) -> str:
    """Nombre canónico de equipo (convención martj42)."""
    return _mapeo().get(nombre, nombre)


def _desde_fd(m: dict) -> dict | None:
    if not m["homeTeam"].get("name") or not m["awayTeam"].get("name"):
        return None  # llaves de eliminatoria sin definir
    marcador = m["score"]["fullTime"]
    return {
        "id": m["id"],
        "fecha_utc": m["utcDate"],
        "local": canonico(m["homeTeam"]["name"]),
        "visitante": canonico(m["awayTeam"]["name"]),
        "local_tla": m["homeTeam"].get("tla"),
        "fase": m.get("stage"),
        "grupo": m.get("group"),
        "jornada": m.get("matchday"),
        "estado": m.get("status"),
        "goles_local": marcador.get("home"),
        "goles_visitante": marcador.get("away"),
        "fuente": "football-data",
    }


def _desde_fifa(c: dict) -> dict | None:
    if not c.get("local_nombre") or not c.get("visitante_nombre"):
        return None
    return {
        "id": int(c["id_fifa"]),
        "fecha_utc": c["fecha_utc"],
        "local": canonico(c["local_nombre"]),
        "visitante": canonico(c["visitante_nombre"]),
        "local_tla": c.get("local_tla"),
        "fase": None,
        "grupo": c.get("grupo"),
        "jornada": None,
        "estado": None,
        "goles_local": c.get("goles_local"),
        "goles_visitante": c.get("goles_visitante"),
        "fuente": "fifa",
    }


def sincronizar(
    conexion: sqlite3.Connection,
    cliente_fd: object | None = None,
    cliente_fifa: object | None = None,
    cargar_historico: bool = True,
) -> list[str]:
    """Sincroniza la base local. Nunca falla duro: degrada y lo declara."""
    mensajes: list[str] = []
    n_estadios = estaticos.cargar_estadios(conexion)
    mensajes.append(f"estadios: {n_estadios}")

    if cargar_historico:
        try:
            ruta = martj42.descargar(DIR_LOCAL / "martj42.csv")
            n = martj42.cargar(conexion, ruta)
            mensajes.append(f"histórico martj42: {n} resultados")
        except Exception as error:
            mensajes.append(f"[ADVERTENCIA] martj42 no disponible: {error}")

    partidos: list[dict] = []
    try:
        fd = cliente_fd or ClienteFootballData(clave("FOOTBALL_DATA_KEY"))
        partidos = [p for m in fd.partidos_mundial() if (p := _desde_fd(m))]
    except Exception as error:
        mensajes.append(f"[ADVERTENCIA] football-data caído: {error}; intento FIFA")

    calendario: list[dict] = []
    try:
        calendario = (cliente_fifa or ClienteFifa()).calendario()
    except Exception as error:
        mensajes.append(f"[ADVERTENCIA] calendario FIFA no disponible: {error}")

    if not partidos and calendario:
        partidos = [p for c in calendario if (p := _desde_fifa(c))]

    estadio_por_llave = {
        (c["fecha_utc"], c["local_tla"]): (c["estadio"], c["id_fifa"]) for c in calendario
    }
    for p in partidos:
        p["estadio"], p["id_fifa"] = estadio_por_llave.get(
            (p["fecha_utc"], p.pop("local_tla")), (None, None)
        )
    conexion.executemany(
        """INSERT OR REPLACE INTO partidos
           (id, fecha_utc, local, visitante, fase, grupo, jornada, estadio, estado,
            goles_local, goles_visitante, id_fifa, fuente)
           VALUES (:id,:fecha_utc,:local,:visitante,:fase,:grupo,:jornada,:estadio,:estado,
                   :goles_local,:goles_visitante,:id_fifa,:fuente)""",
        partidos,
    )
    equipos = sorted({p["local"] for p in partidos} | {p["visitante"] for p in partidos})
    conexion.executemany(
        "INSERT OR IGNORE INTO equipos(nombre) VALUES (?)", [(e,) for e in equipos]
    )
    conexion.commit()
    mensajes.append(f"partidos: {len(partidos)} (fuente: {partidos[0]['fuente'] if partidos else '—'})")

    historicos = {
        f["local"] for f in conexion.execute("SELECT DISTINCT local FROM resultados_historicos")
    }
    sin_mapear = [e for e in equipos if historicos and e not in historicos]
    if sin_mapear:
        mensajes.append(f"[ADVERTENCIA] equipos sin mapear al histórico: {sin_mapear}")
    return mensajes
```

- [x] Step 4: add CLI command to `cli.py`:

```python
@app.command()
def actualizar() -> None:
    """Sincroniza estáticos, histórico y fixtures/resultados a la base local."""
    from mundial.ingesta import actualizar as modulo
    from mundial.persistencia import bd, esquema

    conexion = bd.conectar()
    esquema.crear(conexion)
    for mensaje in modulo.sincronizar(conexion):
        consola.print(mensaje)
```

- [x] Step 5: tests pass → live run `uv run mundial actualizar` → expect 16 estadios, ~49.5k históricos, ≥72 partidos, **0 equipos sin mapear** (extend `mapeo_nombres.csv` if the warning lists any). Commit `feat: actualizar command with source cascade and name mapping`.

---

### Task 6: Dixon-Coles model

**Files:** Create `src/mundial/modelo/__init__.py` (empty), `src/mundial/modelo/dixon_coles.py`; Test `tests/test_dixon_coles.py`.

- [x] Step 1: failing tests (decay weights; analytic gradient vs finite differences; synthetic recovery incl. neutral home advantage):

```python
from datetime import date, timedelta

import numpy as np
from scipy.optimize import approx_fprime

from mundial.modelo import dixon_coles as dc


def test_pesos_decaimiento_vida_media():
    hoy = date(2026, 6, 11)
    fechas = np.array([hoy, hoy - timedelta(days=730), hoy - timedelta(days=1460)])
    pesos = dc.pesos_decaimiento(fechas, hoy)
    assert pesos[0] == 1.0
    assert abs(pesos[1] - 0.5) < 1e-9
    assert abs(pesos[2] - 0.25) < 1e-9


def _partidos_sinteticos(n_equipos=8, n_partidos=600, rho=0.0, semilla=42):
    rng = np.random.default_rng(semilla)
    equipos = [f"EQ{i}" for i in range(n_equipos)]
    ataque = rng.normal(0, 0.3, n_equipos)
    defensa = rng.normal(0, 0.3, n_equipos)
    mu, ventaja = 0.15, 0.25
    hoy = date(2026, 6, 11)
    partidos = []
    for _ in range(n_partidos):
        i, j = rng.choice(n_equipos, 2, replace=False)
        neutral = bool(rng.random() < 0.5)
        lam = np.exp(mu + (0 if neutral else ventaja) + ataque[i] - defensa[j])
        m = np.exp(mu + ataque[j] - defensa[i])
        fecha = hoy - timedelta(days=int(rng.integers(0, 720)))
        partidos.append(
            (fecha, equipos[i], equipos[j], rng.poisson(lam), rng.poisson(m), neutral)
        )
    return partidos, equipos, ataque, mu, ventaja


def test_gradiente_coincide_con_diferencias_finitas():
    partidos, equipos, *_ = _partidos_sinteticos(n_equipos=4, n_partidos=40)
    datos = dc._preparar(partidos, date(2026, 6, 11), partidos_minimos=1)
    theta = np.concatenate([[0.1, 0.2, 0.05], np.linspace(-0.2, 0.2, 2 * len(datos.equipos))])
    _, gradiente = dc._objetivo(theta, datos)
    numerico = approx_fprime(theta, lambda t: dc._objetivo(t, datos)[0], 1e-6)
    assert np.allclose(gradiente, numerico, rtol=1e-3, atol=1e-4)


def test_recupera_parametros_sinteticos():
    partidos, equipos, ataque_real, mu_real, ventaja_real = _partidos_sinteticos()
    ajuste = dc.ajustar(partidos, date(2026, 6, 11))
    ajustado = np.array([ajuste.ataque[e] for e in equipos])
    correlacion = np.corrcoef(ataque_real - ataque_real.mean(), ajustado)[0, 1]
    assert correlacion > 0.85
    assert abs(ajuste.ventaja_local - ventaja_real) < 0.15
    assert abs(ajuste.rho) < 0.1
```

- [x] Step 2: run → FAIL. Step 3: implement `dixon_coles.py`:

```python
"""Dixon-Coles ponderado en el tiempo para selecciones (corrección ρ de marcadores bajos)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import minimize

VIDA_MEDIA_DIAS = 730.0
PENALIZACION_L2 = 1e-3
VERSION = "dc-1.0"


def pesos_decaimiento(fechas, referencia: date, vida_media: float = VIDA_MEDIA_DIAS):
    dias = np.array([(referencia - f).days for f in fechas], dtype=float)
    return np.exp(-np.log(2.0) / vida_media * dias)


@dataclass
class Datos:
    equipos: list[str]
    il: np.ndarray
    iv: np.ndarray
    x: np.ndarray
    y: np.ndarray
    neutral: np.ndarray
    pesos: np.ndarray


@dataclass
class Ajuste:
    equipos: list[str]
    ataque: dict[str, float]
    defensa: dict[str, float]
    mu: float
    ventaja_local: float
    rho: float
    n_partidos: int
    log_verosimilitud: float
    version: str = VERSION


def _preparar(partidos, referencia: date, partidos_minimos: int = 5,
              vida_media: float = VIDA_MEDIA_DIAS) -> Datos:
    """partidos: lista de (fecha, local, visitante, goles_local, goles_visitante, neutral)."""
    conteo: dict[str, int] = {}
    for _, local, visitante, *_ in partidos:
        conteo[local] = conteo.get(local, 0) + 1
        conteo[visitante] = conteo.get(visitante, 0) + 1
    equipos = sorted(e for e, n in conteo.items() if n >= partidos_minimos)
    indice = {e: k for k, e in enumerate(equipos)}
    filas = [p for p in partidos if p[1] in indice and p[2] in indice]
    fechas = np.array([p[0] for p in filas])
    return Datos(
        equipos=equipos,
        il=np.array([indice[p[1]] for p in filas]),
        iv=np.array([indice[p[2]] for p in filas]),
        x=np.array([p[3] for p in filas], dtype=float),
        y=np.array([p[4] for p in filas], dtype=float),
        neutral=np.array([1.0 if p[5] else 0.0 for p in filas]),
        pesos=pesos_decaimiento(fechas, referencia, vida_media),
    )


def _tau(x, y, lam, m, rho):
    """τ de Dixon-Coles y derivadas parciales (∂τ/∂λ, ∂τ/∂m, ∂τ/∂ρ), vectorizado."""
    tau = np.ones_like(lam)
    dl = np.zeros_like(lam)
    dm = np.zeros_like(lam)
    dr = np.zeros_like(lam)
    c00 = (x == 0) & (y == 0)
    c01 = (x == 0) & (y == 1)
    c10 = (x == 1) & (y == 0)
    c11 = (x == 1) & (y == 1)
    tau[c00] = 1.0 - lam[c00] * m[c00] * rho
    dl[c00] = -m[c00] * rho
    dm[c00] = -lam[c00] * rho
    dr[c00] = -lam[c00] * m[c00]
    tau[c01] = 1.0 + lam[c01] * rho
    dl[c01] = rho
    dr[c01] = lam[c01]
    tau[c10] = 1.0 + m[c10] * rho
    dm[c10] = rho
    dr[c10] = m[c10]
    tau[c11] = 1.0 - rho
    dr[c11] = -1.0
    return np.clip(tau, 1e-10, None), dl, dm, dr


def _objetivo(theta, datos: Datos):
    n = len(datos.equipos)
    mu, ventaja, rho = theta[0], theta[1], theta[2]
    ataque = theta[3 : 3 + n]
    defensa = theta[3 + n :]
    loglam = mu + ventaja * (1.0 - datos.neutral) + ataque[datos.il] - defensa[datos.iv]
    logm = mu + ataque[datos.iv] - defensa[datos.il]
    lam, m = np.exp(loglam), np.exp(logm)
    tau, dl, dm, dr = _tau(datos.x, datos.y, lam, m, rho)
    logv = datos.pesos * (
        np.log(tau) + datos.x * loglam - lam + datos.y * logm - m
    )
    nll = -logv.sum() + PENALIZACION_L2 * (ataque @ ataque + defensa @ defensa)

    gx = datos.pesos * ((datos.x - lam) + dl * lam / tau)
    gy = datos.pesos * ((datos.y - m) + dm * m / tau)
    gradiente = np.zeros_like(theta)
    gradiente[0] = (gx + gy).sum()
    gradiente[1] = (gx * (1.0 - datos.neutral)).sum()
    gradiente[2] = (datos.pesos * dr / tau).sum()
    ga = np.zeros(n)
    gd = np.zeros(n)
    np.add.at(ga, datos.il, gx)
    np.add.at(ga, datos.iv, gy)
    np.add.at(gd, datos.iv, -gx)
    np.add.at(gd, datos.il, -gy)
    gradiente[3 : 3 + n] = ga - 2.0 * PENALIZACION_L2 * ataque
    gradiente[3 + n :] = gd - 2.0 * PENALIZACION_L2 * defensa
    return nll, -gradiente


def ajustar(partidos, referencia: date, partidos_minimos: int = 5,
            vida_media: float = VIDA_MEDIA_DIAS) -> Ajuste:
    datos = _preparar(partidos, referencia, partidos_minimos, vida_media)
    n = len(datos.equipos)
    theta0 = np.zeros(3 + 2 * n)
    theta0[0] = np.log(max(datos.x.mean(), 0.1))
    limites = [(None, None), (None, None), (-0.5, 0.5)] + [(None, None)] * (2 * n)
    resultado = minimize(
        _objetivo, theta0, args=(datos,), jac=True, method="L-BFGS-B",
        bounds=limites, options={"maxiter": 500},
    )
    mu, ventaja, rho = resultado.x[0], resultado.x[1], resultado.x[2]
    ataque = resultado.x[3 : 3 + n]
    defensa = resultado.x[3 + n :]
    mu += ataque.mean() - defensa.mean()
    ataque -= ataque.mean()
    defensa -= defensa.mean()
    return Ajuste(
        equipos=datos.equipos,
        ataque=dict(zip(datos.equipos, ataque)),
        defensa=dict(zip(datos.equipos, defensa)),
        mu=float(mu),
        ventaja_local=float(ventaja),
        rho=float(rho),
        n_partidos=len(datos.x),
        log_verosimilitud=float(-resultado.fun),
    )
```

- [x] Step 4: tests pass (gradient check is the critical one) → commit `feat: weighted Dixon-Coles with analytic gradients`.

---

### Task 7: Train-and-store + `mundial ratings`

**Files:** Create `src/mundial/modelo/entrenar.py`; Test `tests/test_entrenar.py`. Modify `src/mundial/cli.py`.

- [x] Step 1: failing test:

```python
from datetime import date

from mundial.modelo import entrenar
from mundial.persistencia import bd, esquema


def test_entrenar_y_guardar(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    filas = []
    import numpy as np

    rng = np.random.default_rng(7)
    equipos = [f"EQ{i}" for i in range(6)]
    for k in range(300):
        i, j = rng.choice(6, 2, replace=False)
        filas.append(
            (f"2025-0{1 + k % 9}-15", equipos[i], equipos[j],
             int(rng.poisson(1.3)), int(rng.poisson(1.1)), "Amistoso", "X", "Y", 1)
        )
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas
    )
    ajuste = entrenar.entrenar_y_guardar(conexion, referencia=date(2026, 6, 11))
    assert len(ajuste.equipos) == 6
    n_ratings = conexion.execute("SELECT COUNT(*) c FROM ratings").fetchone()["c"]
    assert n_ratings == 6
    meta = conexion.execute("SELECT * FROM modelo_meta").fetchone()
    assert meta["version"] == "dc-1.0"
```

- [x] Step 2: implement `entrenar.py`:

```python
"""Ajuste del modelo base sobre el histórico y persistencia de ratings."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from mundial.modelo import dixon_coles

VENTANA_DIAS = 3650


def entrenar_y_guardar(
    conexion: sqlite3.Connection, referencia: date | None = None
) -> dixon_coles.Ajuste:
    referencia = referencia or date.today()
    desde = (referencia - timedelta(days=VENTANA_DIAS)).isoformat()
    filas = conexion.execute(
        """SELECT fecha, local, visitante, goles_local, goles_visitante, neutral
           FROM resultados_historicos WHERE fecha >= ? ORDER BY fecha""",
        (desde,),
    ).fetchall()
    partidos = [
        (date.fromisoformat(f["fecha"]), f["local"], f["visitante"],
         f["goles_local"], f["goles_visitante"], bool(f["neutral"]))
        for f in filas
    ]
    ajuste = dixon_coles.ajustar(partidos, referencia)
    marca = referencia.isoformat()
    conexion.executemany(
        "INSERT OR REPLACE INTO ratings VALUES (?,?,?,?)",
        [(e, marca, ajuste.ataque[e], ajuste.defensa[e]) for e in ajuste.equipos],
    )
    conexion.execute(
        "INSERT OR REPLACE INTO modelo_meta VALUES (?,?,?,?,?,?,?,?)",
        (marca, ajuste.mu, ajuste.ventaja_local, ajuste.rho,
         ajuste.n_partidos, len(ajuste.equipos), ajuste.log_verosimilitud, ajuste.version),
    )
    conexion.commit()
    return ajuste
```

- [x] Step 3: CLI command:

```python
@app.command()
def ratings() -> None:
    """Ajusta Dixon-Coles sobre el histórico y guarda los ratings."""
    from rich.table import Table

    from mundial.modelo import entrenar
    from mundial.persistencia import bd, esquema

    conexion = bd.conectar()
    esquema.crear(conexion)
    ajuste = entrenar.entrenar_y_guardar(conexion)
    consola.print(
        f"Ajustado con {ajuste.n_partidos} partidos, {len(ajuste.equipos)} equipos "
        f"(ventaja local: {ajuste.ventaja_local:.3f}, rho: {ajuste.rho:.3f})"
    )
    tabla = Table(title="Top 10 fuerza neta (ataque + defensa)")
    tabla.add_column("Equipo")
    tabla.add_column("Ataque", justify="right")
    tabla.add_column("Defensa", justify="right")
    fuertes = sorted(
        ajuste.equipos, key=lambda e: ajuste.ataque[e] + ajuste.defensa[e], reverse=True
    )[:10]
    for e in fuertes:
        tabla.add_row(e, f"{ajuste.ataque[e]:+.3f}", f"{ajuste.defensa[e]:+.3f}")
    consola.print(tabla)
```

- [x] Step 4: all tests pass → live run: `uv run mundial actualizar && uv run mundial ratings` → sanity check: top 10 should be plausible (Spain/Argentina/France/England-tier teams). Commit `feat: ratings training command storing Dixon-Coles fit`.

---

### Task 8: Close phase

- [x] Update `CLAUDE.md` (F1 done; document `actualizar`/`ratings` commands, schema, DC params), mark this plan's checkboxes, push, verify CI still green.

## Self-review notes

- Spec coverage: F1 = spec §12 F1 (estáticos ✓ T2, fixtures/resultados con cascada ✓ T4-T5, bootstrap martj42 ✓ T3, esquema ✓ T1, DC base ✓ T6-T7). Elo externo (eloratings.net) belongs to F2's feature layer, not F1.
- Type consistency: `Datos`/`_objetivo` shared between gradient test and `ajustar`; `sincronizar(conexion, cliente_fd, cliente_fifa, cargar_historico)` matches tests; schema column order matches all `INSERT` statements.
- Placeholder scan: clean; runtime unknowns (unmapped names) handled by an explicit warning + live verification step, not left vague.
