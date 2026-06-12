"""CLI del sistema de predicción del Mundial 2026."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import typer
from rich.console import Console

from mundial.config import DIR_PREDICCIONES, DIR_SNAPSHOTS, clave
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
        mercado_etq = flag.get("mercado", "1x2")
        consola.print(
            f"[bold magenta]VALOR[/]: el modelo da {flag['margen'] * 100:+.1f} pts más que el "
            f"mercado a '{flag['resultado']}' [{mercado_etq}] ({etiqueta})"
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
    resultado = prediccion.predecir(
        conexion, partido_id, cliente_bsd=_cliente_bsd_opcional(),
        dir_exportacion=DIR_PREDICCIONES,
    )
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
        _imprimir_prediccion(
            prediccion.predecir(
                conexion, fila["id"], cliente_bsd=cliente, dir_exportacion=DIR_PREDICCIONES
            )
        )


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
        _imprimir_prediccion(
            prediccion.predecir(
                conexion, fila["id"], cliente_bsd=cliente, dir_exportacion=DIR_PREDICCIONES
            )
        )


@app.command()
def vigilar() -> None:
    """Envía análisis pre-partido y resultados post-partido pendientes a Telegram."""
    from mundial.notificaciones import vigilar as modulo
    from mundial.notificaciones.telegram import ClienteTelegram

    from mundial.ingesta.fifa import ClienteFifa

    cliente = ClienteTelegram(clave("TELEGRAM_BOT_TOKEN"))
    registro = modulo.vigilar(
        _conexion_lista(), cliente, clave("TELEGRAM_CHAT_ID"),
        cliente_bsd=_cliente_bsd_opcional(), dir_exportacion=DIR_PREDICCIONES,
        cliente_fifa=ClienteFifa(),
    )
    for linea in registro:
        consola.print(linea)


@app.command()
def sondear(partido: str = typer.Argument(..., help="tla-tla, igual que predecir")) -> None:
    """Sondea AH/totales reales en The Odds API (≈5 créditos) y compara con el modelo."""
    import json as json_lib
    from datetime import datetime, timezone

    from mundial.ingesta.actualizar import canonico
    from mundial.ingesta.odds_api import ClienteOddsApi

    conexion = _conexion_lista()
    partido_id = _resolver_partido(conexion, partido)
    fila = conexion.execute("SELECT * FROM partidos WHERE id=?", (partido_id,)).fetchone()
    cliente = _cliente_odds_api()
    eventos = cliente.eventos()
    objetivo = next(
        (e for e in eventos
         if {canonico(e["home_team"]), canonico(e["away_team"])}
         == {fila["local"], fila["visitante"]}), None)
    if objetivo is None:
        consola.print("[yellow]El partido no está en The Odds API todavía.[/]")
        return
    datos, presupuesto = cliente.cuotas_evento(objetivo["id"])
    if int(presupuesto["restantes"] or 0) < 100:
        consola.print("[red]Presupuesto bajo[/] — quedan menos de 100 créditos.")
    filas = ClienteOddsApi.filas_mercados(
        datos, partido_id, datetime.now(timezone.utc).isoformat())
    conexion.executemany("INSERT OR REPLACE INTO cuotas_mercado VALUES (?,?,?,?,?,?,?)", filas)
    conexion.commit()
    consola.print(f"{len(filas)} cuotas AH/totales guardadas "
                  f"(créditos restantes: {presupuesto['restantes']})")
    ultima = conexion.execute(
        """SELECT mercados_json FROM predicciones WHERE partido_id=?
           ORDER BY creado_en DESC LIMIT 1""", (partido_id,)).fetchone()
    if ultima and ultima["mercados_json"]:
        justas = json_lib.loads(ultima["mercados_json"]).get("ah", {})
        for f in filas:
            if f[4] == "ah":
                clave = f"{float(f[5].split('@')[1]):+.2f}"
                consola.print(f"  {f[5]} @{f[6]:.2f} ({f[3]}) — justa modelo: "
                              f"{justas.get(clave, '—')}")


@app.command()
def calibrar(
    aplicar: bool = typer.Option(False, "--aplicar", help="Guarda el w recomendado en config.")
) -> None:
    """Calibra el peso modelo/mercado por log-loss con shrinkage al prior 0.4."""
    from mundial.modelo import calibracion

    conexion = _conexion_lista()
    r = calibracion.optimizar_w(conexion)
    if r.get("n", 0) < 5:
        consola.print(f"Muestra insuficiente ({r['n']} partidos); se mantiene w=0.4.")
        return
    consola.print(
        f"n={r['n']} · w crudo {r['w_crudo']:.2f} · w recomendado [bold]{r['w_recomendado']:.3f}[/]\n"
        f"log-loss lineal {r['logloss_lineal']:.4f} · geométrico {r['logloss_geometrico']:.4f} · "
        f"mercado puro {r['logloss_mercado']:.4f}"
    )
    if aplicar:
        conexion.execute("INSERT OR REPLACE INTO config VALUES ('peso_modelo', ?)",
                         (str(r["w_recomendado"]),))
        conexion.commit()
        consola.print(f"[green]Aplicado[/]: config.peso_modelo = {r['w_recomendado']:.3f}")


@app.command()
def gbm() -> None:
    """Entrena y evalúa la capa GBM con puerta walk-forward; la activa solo si pasa."""
    from mundial.config import DIR_LOCAL
    from mundial.modelo import entrenar as entrenar_mod
    from mundial.modelo import gbm as gbm_mod

    conexion = _conexion_lista()
    consola.print("Materializando ratings as-of (anti-fuga)…")
    entrenar_mod.ratings_asof(conexion)
    consola.print("Walk-forward por ciclos de Mundial…")
    informe = gbm_mod.walk_forward(conexion)
    for b in informe["bloques"]:
        marca = "✓" if b["rps_gbm"] < b["rps_dc"] else "✗"
        consola.print(f"  {marca} test {b['test'][0][:4]}-{b['test'][1][:4]}: "
                      f"RPS GBM {b['rps_gbm']:.4f} vs DC {b['rps_dc']:.4f} (n={b['n']})")
    if informe["pasa_puerta"]:
        consola.print("[green]PASA la puerta[/]: entrenando modelo final y activando en blend")
        modelo = gbm_mod.entrenar_ordinal(conexion, "1996-01-01", "2026-06-10")
        gbm_mod.guardar(modelo, DIR_LOCAL / "gbm")
        conexion.execute("INSERT OR REPLACE INTO config VALUES ('gbm_activo', '1')")
    else:
        consola.print("[yellow]NO pasa la puerta[/]: queda documentado, no entra al blend")
        conexion.execute("INSERT OR REPLACE INTO config VALUES ('gbm_activo', '0')")
    conexion.commit()


@app.command()
def minar(anio_desde: int = typer.Option(1994, help="Inicio de la era a minar")) -> None:
    """Mina patrones históricos y escribe los candidatos (NO los activa)."""
    import json as json_lib

    from rich.table import Table

    from mundial.analisis import mineria
    from mundial.config import RAIZ

    conexion = _conexion_lista()
    candidatos = mineria.minar(conexion, anio_desde=anio_desde)
    reportables = [c for c in candidatos if c.reportable]
    tabla = Table(
        title=f"Candidatos reportables (BH q=0.10): {len(reportables)}/{len(candidatos)}")
    for col in ("id", "tasa", "baseline", "n", "p_adj", "IC95"):
        tabla.add_column(col)
    for c in sorted(reportables, key=lambda c: c.p_adj):
        tabla.add_row(c.id, f"{c.tasa():.3f}", f"{c.baseline:.3f}", str(c.n),
                      f"{c.p_adj:.4f}", f"[{c.ic95[0]:.2f},{c.ic95[1]:.2f}]")
    consola.print(tabla)
    ruta = RAIZ / "data" / "candidatos.json"
    ruta.write_text(json_lib.dumps([c.__dict__ for c in candidatos], indent=1, default=str,
                                   ensure_ascii=False))
    consola.print(f"Candidatos completos → {ruta}. Revisión humana antes de promover a "
                  f"data/patrones.json.")


@app.command()
def ledger() -> None:
    """Resumen del paper trading: PnL, yield y CLV."""
    from mundial.modelo import ledger as modulo

    conexion = _conexion_lista()
    modulo.liquidar_pendientes(conexion)
    r = modulo.resumen(conexion)
    if not r["n"] and not r["pendientes"]:
        consola.print("Sin apuestas simuladas todavía.")
        return
    if r["n"] and r.get("clv_medio") is not None:
        consola.print(
            f"Apuestas: {r['n']} liquidadas, {r['pendientes']} pendientes · "
            f"PnL flat: {r.get('pnl_flat', 0):+.2f}u · yield: {r.get('yield_flat', 0) * 100:+.1f}% · "
            f"CLV medio: {r['clv_medio'] * 100:+.2f}% (n={r['clv_n']})"
        )
    else:
        consola.print(
            f"Apuestas: {r['n']} liquidadas, {r['pendientes']} pendientes · "
            f"PnL flat: {r.get('pnl_flat', 0):+.2f}u · CLV aún sin datos"
        )
    for f in conexion.execute(
        "SELECT a.*, p.local, p.visitante FROM apuestas a JOIN partidos p ON p.id=a.partido_id "
        "ORDER BY a.creado_en DESC LIMIT 15"
    ):
        clv = f" CLV {f['clv'] * 100:+.1f}%" if f["clv"] is not None else ""
        consola.print(
            f"  {f['estado']:>14} {f['local']} vs {f['visitante']} — "
            f"{f['mercado']}/{f['seleccion']} @{f['cuota']:.2f} ({f['origen']}){clv}"
        )


@app.command()
def telegram(
    configurar: bool = typer.Option(
        False, "--configurar", help="Detecta tu chat_id tras escribirle al bot."
    ),
) -> None:
    """Envía por Telegram los pronósticos de hoy y los resultados de ayer."""
    from mundial.notificaciones.telegram import ClienteTelegram, armar_resumen

    cliente = ClienteTelegram(clave("TELEGRAM_BOT_TOKEN"))
    if configurar:
        chat_id = cliente.obtener_chat_id()
        if chat_id:
            consola.print(f"Tu chat_id es [bold]{chat_id}[/] — guárdalo en .env como "
                          f"TELEGRAM_CHAT_ID={chat_id}")
        else:
            consola.print("[yellow]No veo mensajes:[/] escríbele cualquier cosa al bot en "
                          "Telegram y vuelve a correr este comando.")
        return
    resumen = armar_resumen(_conexion_lista(), cliente_bsd=_cliente_bsd_opcional())
    if resumen is None:
        consola.print("Nada que enviar: no hay partidos hoy ni resultados de ayer.")
        return
    enviados = cliente.enviar(clave("TELEGRAM_CHAT_ID"), resumen)
    consola.print(f"[green]Enviado a Telegram[/] ({enviados} mensaje(s)).")


@app.command()
def precision() -> None:
    """Precisión acumulada (Brier/RPS): modelo vs mercado vs blend."""
    from rich.table import Table

    from mundial.modelo import precision as modulo

    informe = modulo.evaluar(_conexion_lista())
    if informe["n"] == 0:
        consola.print("Aún no hay partidos terminados con predicción previa al kickoff.")
        return
    aciertos_1x2 = sum(1 for p in informe["partidos"] if p["acerto_1x2"])
    aciertos_marcador = sum(1 for p in informe["partidos"] if p["acerto_marcador"])
    consola.print(
        f"{informe['n']} partidos evaluados — 1X2 acertado: {aciertos_1x2}/{informe['n']}, "
        f"marcador exacto: {aciertos_marcador}/{informe['n']}"
    )
    tabla = Table(title="Brier / RPS promedio (menor es mejor)")
    tabla.add_column("Variante")
    tabla.add_column("Brier", justify="right")
    tabla.add_column("RPS", justify="right")
    tabla.add_column("n", justify="right")
    for nombre in ("modelo", "mercado", "blend"):
        datos = informe[nombre]
        if datos["n"]:
            tabla.add_row(
                nombre, f"{datos['brier']:.4f}", f"{datos['rps']:.4f}", str(datos["n"])
            )
    consola.print(tabla)
    for p in informe["partidos"][-10:]:
        marca = "✓" if p["acerto_1x2"] else "✗"
        consola.print(
            f"  {marca} {p['partido']} — predicho {p['marcador_predicho']}, "
            f"P({p['resultado']}) dada: {p['metricas'].get('blend', {}).get('brier', 0):.3f} Brier"
        )


@app.command()
def fuentes() -> None:
    """Estado de las fuentes de datos, presupuesto y frescura."""
    from rich.table import Table

    conexion = _conexion_lista()
    ahora = datetime.now(timezone.utc)
    tabla = Table(title="Fuentes")
    tabla.add_column("Fuente")
    tabla.add_column("Último snapshot", justify="right")
    tabla.add_column("Hoy", justify="right")
    for fuente in ("bsd", "odds-api"):
        ultimo = snapshots.ultimo_snapshot(fuente, base=DIR_SNAPSHOTS)
        edad = f"hace {(ahora - ultimo).total_seconds() / 3600:.1f} h" if ultimo else "nunca"
        hoy_n = len(list(DIR_SNAPSHOTS.glob(f"{ahora.strftime('%Y-%m-%d')}/*-{fuente}.json.gz")))
        tabla.add_row(fuente, edad, str(hoy_n))
    consola.print(tabla)
    rutas_odds = sorted(DIR_SNAPSHOTS.glob("*/*-odds-api.json.gz"))
    if rutas_odds:
        contenido = snapshots.leer_snapshot(rutas_odds[-1])
        presupuesto = (
            contenido["payload"].get("presupuesto")
            if isinstance(contenido["payload"], dict) else None
        )
        if presupuesto:
            consola.print(
                f"The Odds API: {presupuesto['restantes']} créditos restantes este mes"
            )
    estadisticas = {
        "partidos": "SELECT COUNT(*) FROM partidos",
        "resultados históricos": "SELECT COUNT(*) FROM resultados_historicos",
        "filas de cuotas": "SELECT COUNT(*) FROM cuotas",
        "bajas registradas": "SELECT COUNT(*) FROM bajas",
        "predicciones": "SELECT COUNT(*) FROM predicciones",
    }
    for nombre, consulta in estadisticas.items():
        consola.print(f"  {nombre}: {conexion.execute(consulta).fetchone()[0]}")
    meta = conexion.execute(
        "SELECT fecha_ajuste, n_partidos, n_equipos FROM modelo_meta "
        "ORDER BY fecha_ajuste DESC LIMIT 1"
    ).fetchone()
    if meta:
        consola.print(
            f"  ratings: ajustados el {meta['fecha_ajuste']} "
            f"({meta['n_partidos']} partidos, {meta['n_equipos']} equipos)"
        )


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
    alineaciones: dict[str, dict] = {}
    for evento in eventos:
        if evento.get("status") == "finished":
            continue
        comparaciones[str(evento["id"])] = bsd.comparacion_cuotas(evento["id"])
        time.sleep(PAUSA_ENTRE_LLAMADAS_S)
        try:
            alineaciones[str(evento["id"])] = bsd.alineaciones(evento["id"])
            time.sleep(PAUSA_ENTRE_LLAMADAS_S)
        except Exception:
            pass  # las alineaciones pueden no existir aún; las cuotas no se pierden
    ruta_bsd = snapshots.escribir_snapshot(
        "bsd",
        {"eventos": eventos, "comparaciones": comparaciones, "alineaciones": alineaciones},
        momento=ahora,
        base=DIR_SNAPSHOTS,
    )
    consola.print(
        f"[green]BSD[/]: {len(eventos)} eventos, {len(comparaciones)} comparaciones, "
        f"{len(alineaciones)} alineaciones → {ruta_bsd}"
    )

    ultimo = snapshots.ultimo_snapshot("odds-api", base=DIR_SNAPSHOTS)
    if ultimo and (ahora - ultimo) < timedelta(hours=horas_min_odds_api):
        consola.print(
            f"[yellow]The Odds API omitido[/]: último snapshot hace "
            f"{(ahora - ultimo).total_seconds() / 3600:.1f} h (< {horas_min_odds_api} h)"
        )
        return
    datos, presupuesto = _cliente_odds_api().cuotas_h2h()
    ruta_odds = snapshots.escribir_snapshot(
        "odds-api", {"eventos": datos, "presupuesto": presupuesto},
        momento=ahora, base=DIR_SNAPSHOTS,
    )
    consola.print(
        f"[green]The Odds API[/]: {len(datos)} eventos → {ruta_odds} "
        f"(créditos restantes: {presupuesto['restantes']})"
    )
