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


def _conexion_lista():
    from mundial.persistencia import bd, esquema

    conexion = bd.conectar()
    esquema.crear(conexion)
    return conexion


def _cliente_bsd_opcional():
    try:
        return _cliente_bsd()
    except Exception:
        return None


def _resolver_partido(conexion, referencia: str) -> int:
    partes = [p.strip().lower() for p in referencia.split("-", 1)]
    if len(partes) != 2:
        raise typer.BadParameter("Formato esperado: equipo1-equipo2 (ej. mex-rsa)")
    nombres = []
    for parte in partes:
        fila = None
        if len(parte) == 3:
            fila = conexion.execute(
                "SELECT nombre FROM equipos WHERE lower(tla) = ?", (parte,)
            ).fetchone()
        if fila is None:
            fila = conexion.execute(
                "SELECT nombre FROM equipos WHERE lower(nombre) LIKE ? ORDER BY nombre LIMIT 1",
                (f"%{parte}%",),
            ).fetchone()
        if fila is None:
            raise typer.BadParameter(f"No encuentro al equipo '{parte}'")
        nombres.append(fila["nombre"])
    fila = conexion.execute(
        """SELECT id FROM partidos
           WHERE (local = ? AND visitante = ?) OR (local = ? AND visitante = ?)
           ORDER BY (goles_local IS NOT NULL), fecha_utc LIMIT 1""",
        (nombres[0], nombres[1], nombres[1], nombres[0]),
    ).fetchone()
    if fila is None:
        raise typer.BadParameter(f"No hay partido {nombres[0]} vs {nombres[1]} en la base")
    return fila["id"]


def _imprimir_prediccion(resultado) -> None:
    from rich.panel import Panel
    from rich.table import Table

    lineas = [f"[bold]{resultado.local} vs {resultado.visitante}[/]"]
    lineas.append(f"Consulta: {resultado.creado_en}")
    if resultado.edad_cuotas_h is not None:
        lineas.append(
            f"Cuotas: consenso de {resultado.n_casas} casas, "
            f"capturadas hace {resultado.edad_cuotas_h:.1f} h"
        )
    else:
        lineas.append("Cuotas: [yellow]sin datos de mercado[/]")
    if resultado.cambios:
        lineas.append("Desde la última consulta: " + "; ".join(resultado.cambios))
    consola.print(Panel("\n".join(lineas)))

    top = " · ".join(f"{i}-{j} ({p * 100:.1f}%)" for i, j, p in resultado.top3)
    consola.print(
        f"[bold green]Marcador más probable: "
        f"{resultado.marcador[0]}-{resultado.marcador[1]}[/]  (top 3: {top})"
    )
    tabla = Table(title="Probabilidades 1X2")
    tabla.add_column("")
    tabla.add_column(f"Gana {resultado.local}", justify="right")
    tabla.add_column("Empate", justify="right")
    tabla.add_column(f"Gana {resultado.visitante}", justify="right")
    filas = [("Modelo", resultado.p_modelo)]
    if resultado.p_mercado:
        filas.append(("Mercado (de-vig)", resultado.p_mercado))
    filas.append(("Final (blend)", resultado.p_final))
    for nombre, p in filas:
        tabla.add_row(
            nombre, f"{p['local'] * 100:.1f}%", f"{p['empate'] * 100:.1f}%",
            f"{p['visitante'] * 100:.1f}%",
        )
    consola.print(tabla)
    color = {"Alta": "green", "Media": "yellow", "Baja": "red"}[resultado.confianza]
    razones = ("; ".join(resultado.razones_confianza)) or "datos completos y frescos"
    consola.print(f"Confianza: [{color}]{resultado.confianza}[/] — {razones}")
    if resultado.explicacion:
        consola.print("[bold]Factores:[/]")
        for linea in resultado.explicacion:
            consola.print(f"  • {linea}")
    for flag in resultado.valor_flags:
        etiqueta = "sostenida" if flag["sostenida"] else "reciente, aún no sostenida"
        consola.print(
            f"[bold magenta]VALOR[/]: el modelo da {flag['margen'] * 100:+.1f} pts más que el "
            f"mercado a '{flag['resultado']}' ({etiqueta})"
        )
    consola.print()


@app.command()
def predecir(
    partido: str = typer.Argument(..., help="Partido como tla-tla o nombres (ej. mex-rsa)"),
) -> None:
    """Predice un partido con los datos más recientes disponibles."""
    from mundial.modelo import prediccion

    conexion = _conexion_lista()
    partido_id = _resolver_partido(conexion, partido)
    resultado = prediccion.predecir(conexion, partido_id, cliente_bsd=_cliente_bsd_opcional())
    _imprimir_prediccion(resultado)


@app.command()
def hoy() -> None:
    """Predice todos los partidos de hoy (UTC)."""
    from mundial.modelo import prediccion

    conexion = _conexion_lista()
    filas = conexion.execute(
        "SELECT id FROM partidos WHERE date(fecha_utc) = date('now') ORDER BY fecha_utc"
    ).fetchall()
    if not filas:
        consola.print("No hay partidos hoy.")
        return
    cliente = _cliente_bsd_opcional()
    for fila in filas:
        _imprimir_prediccion(prediccion.predecir(conexion, fila["id"], cliente_bsd=cliente))


@app.command()
def jornada(numero: int = typer.Argument(..., help="Jornada de fase de grupos (1-3)")) -> None:
    """Predice todos los partidos de una jornada de la fase de grupos."""
    from mundial.modelo import prediccion

    conexion = _conexion_lista()
    filas = conexion.execute(
        "SELECT id FROM partidos WHERE jornada = ? ORDER BY fecha_utc", (numero,)
    ).fetchall()
    if not filas:
        consola.print(f"No hay partidos para la jornada {numero}.")
        return
    cliente = _cliente_bsd_opcional()
    for fila in filas:
        _imprimir_prediccion(prediccion.predecir(conexion, fila["id"], cliente_bsd=cliente))


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
