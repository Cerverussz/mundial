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

    def alineaciones(self, evento_id):
        return {"lineup_status": "predicted", "lineups": {}, "unavailable_players": {}}


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
