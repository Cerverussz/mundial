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


@app.callback()
def principal() -> None:
    """Sistema de predicción de marcadores — Mundial 2026."""


@app.command()
def actualizar() -> None:
    """Sincroniza estáticos, histórico y fixtures/resultados a la base local."""
    from mundial.ingesta import actualizar as modulo
    from mundial.persistencia import bd, esquema

    conexion = bd.conectar()
    esquema.crear(conexion)
    for mensaje in modulo.sincronizar(conexion):
        consola.print(mensaje)


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
        "bsd",
        {"eventos": eventos, "comparaciones": comparaciones},
        momento=ahora,
        base=DIR_SNAPSHOTS,
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
