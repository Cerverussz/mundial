"""Vigilante por partido: análisis previo al kickoff y resultado con acierto al final."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mundial.config import RAIZ
from mundial.notificaciones.telegram import ClienteTelegram, _bloque_prediccion

RUTA_ESTADO = RAIZ / "data" / "notificaciones.json"
VENTANA_PRE_HORAS = 2.5


def _leer_estado(ruta: Path) -> dict:
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"pre": [], "post": []}


def _guardar_estado(ruta: Path, estado: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(estado, indent=1) + "\n", encoding="utf-8")


def _mensaje_resultado(partido, evaluado, informe, resumen_ledger=None) -> str:
    encabezado = (
        f"🏁 <b>Final: {partido['local']} {partido['goles_local']}-"
        f"{partido['goles_visitante']} {partido['visitante']}</b>"
    )
    if evaluado is None:
        return f"{encabezado}\n(sin pronóstico previo al partido)"
    marca_1x2 = "✅" if evaluado["acerto_1x2"] else "❌"
    marca_exacto = "✅" if evaluado["acerto_marcador"] else "❌"
    lineas = [
        encabezado,
        f"Pronóstico: <b>{evaluado['marcador_predicho']}</b>",
        f"{marca_1x2} 1X2 — dimos {evaluado['p_resultado'] * 100:.0f}% a "
        f"'{evaluado['resultado']}' · {marca_exacto} marcador exacto",
    ]
    n = informe["n"]
    aciertos_1x2 = sum(1 for p in informe["partidos"] if p["acerto_1x2"])
    aciertos_exacto = sum(1 for p in informe["partidos"] if p["acerto_marcador"])
    acumulado = (
        f"📊 Acumulado: 1X2 {aciertos_1x2}/{n} ({aciertos_1x2 / n * 100:.0f}%) · "
        f"exacto {aciertos_exacto}/{n} ({aciertos_exacto / n * 100:.0f}%)"
    )
    if informe["blend"]["rps"] is not None:
        acumulado += f" · RPS {informe['blend']['rps']:.3f}"
        if informe["mercado"]["rps"] is not None:
            veredicto = (
                "✅ vamos mejor que el mercado"
                if informe["blend"]["rps"] <= informe["mercado"]["rps"]
                else "❌ vamos peor que el mercado"
            )
            acumulado += f" ({veredicto}: {informe['mercado']['rps']:.3f})"
    lineas.append(acumulado)
    if resumen_ledger and resumen_ledger.get("n"):
        linea = (
            f"💰 Papel: {resumen_ledger['n']} apuestas, "
            f"PnL flat {resumen_ledger['pnl_flat']:+.2f}u"
        )
        if resumen_ledger.get("clv_medio") is not None:
            linea += f", CLV medio {resumen_ledger['clv_medio'] * 100:+.1f}%"
        lineas.append(linea)
    return "\n".join(lineas)


def vigilar(
    conexion: sqlite3.Connection,
    cliente: ClienteTelegram,
    chat_id: str,
    ahora: datetime | None = None,
    ruta_estado: Path | None = None,
    cliente_bsd=None,
    dir_exportacion=None,
    patrones_validados=None,
) -> list[str]:
    """Envía análisis pre-partido (≤2.5 h antes) y resultados post-partido, sin duplicar."""
    from mundial.factores import mercado
    from mundial.modelo import ledger, precision, prediccion
    from mundial.notificaciones import patrones as patrones_mod

    ahora = ahora or datetime.now(timezone.utc)
    ruta_estado = ruta_estado or RUTA_ESTADO
    estado = _leer_estado(ruta_estado)
    registro: list[str] = []

    proximos = conexion.execute(
        """SELECT id, fecha_utc, local, visitante FROM partidos
           WHERE goles_local IS NULL ORDER BY fecha_utc"""
    ).fetchall()
    for partido in proximos:
        if partido["id"] in estado["pre"]:
            continue
        kickoff = datetime.fromisoformat(partido["fecha_utc"].replace("Z", "+00:00"))
        horas = (kickoff - ahora).total_seconds() / 3600.0
        if not 0 <= horas <= VENTANA_PRE_HORAS:
            continue
        try:
            resultado = prediccion.predecir(
                conexion, partido["id"], cliente_bsd=cliente_bsd,
                dir_exportacion=dir_exportacion,
            )
            texto = (
                f"🔜 <b>Arranca en {horas:.1f} h</b> — {partido['fecha_utc'][11:16]} UTC\n\n"
                + _bloque_prediccion(resultado)
            )
            patrones_activos = (
                patrones_validados if patrones_validados is not None
                else patrones_mod.cargar_validados(fecha_partido=partido["fecha_utc"])
            )
            if patrones_activos:
                contexto = patrones_mod.construir_contexto(conexion, partido["id"])
                for patron in patrones_activos:
                    if not patrones_mod.satisface(patron["filtro"], contexto):
                        continue
                    if patron["mercado_objetivo"] == "1x2":
                        p_imp, _, _ = mercado.cuotas_consenso(conexion, partido["id"])
                    else:
                        p_imp, _, _ = mercado.cuotas_consenso_mercado(
                            conexion, partido["id"], patron["mercado_objetivo"])
                    if not patrones_mod.precio_cumple(patron, p_imp):
                        continue
                    texto += (
                        f"\n\n⚠️ <b>Patrón pre-registrado</b>: {patron['hipotesis']} — "
                        f"hist. {patron['efecto']['tasa'] * 100:.0f}% vs base "
                        f"{patron['efecto']['baseline'] * 100:.0f}% (n={patron['n']}, "
                        f"p_adj={patron['p_adj_bh']:.3f}). Apuesta de papel."
                    )
                    ledger.abrir_apuestas(
                        conexion, partido["id"],
                        [{"mercado": patron["mercado_objetivo"], "seleccion": patron["lado"],
                          "margen": patron["efecto"]["lift"], "sostenida": True}],
                        {patron["lado"]: patron["efecto"]["tasa"]},
                        ahora.isoformat(), origen=f"patron:{patron['id']}")
            cliente.enviar(chat_id, texto)
            estado["pre"].append(partido["id"])
            registro.append(f"análisis enviado: {partido['local']} vs {partido['visitante']}")
            p_propias = dict(resultado.p_final)
            p_propias["over@2.5"] = resultado.mercados["over_under_25"]["p_over"]
            p_propias["under@2.5"] = resultado.mercados["over_under_25"]["p_under"]
            p_propias["yes"] = resultado.mercados["btts"]["p_si"]
            p_propias["no"] = 1.0 - resultado.mercados["btts"]["p_si"]
            n_apuestas = ledger.abrir_apuestas(
                conexion, partido["id"], resultado.valor_flags, p_propias, ahora.isoformat())
            if n_apuestas:
                registro.append(f"apuestas papel abiertas: {n_apuestas}")
        except Exception as error:
            registro.append(
                f"[ADVERTENCIA] sin análisis para {partido['local']} vs "
                f"{partido['visitante']}: {error}"
            )

    ledger.liquidar_pendientes(conexion)
    resumen_ledger = ledger.resumen(conexion)
    informe = precision.evaluar(conexion)
    evaluados = {p["partido_id"]: p for p in informe["partidos"]}
    terminados = conexion.execute(
        """SELECT id, local, visitante, goles_local, goles_visitante FROM partidos
           WHERE goles_local IS NOT NULL ORDER BY fecha_utc"""
    ).fetchall()

    if cliente_bsd is not None:
        for partido in terminados:
            vinculo = conexion.execute(
                "SELECT evento_id FROM eventos_bsd WHERE partido_id=?", (partido["id"],)
            ).fetchone()
            ya = conexion.execute(
                "SELECT 1 FROM xg WHERE partido_id=?", (partido["id"],)).fetchone()
            if not vinculo or ya:
                continue
            try:
                stats = cliente_bsd.estadisticas(vinculo["evento_id"])
                xg_l = (stats.get("stats", {}).get("home") or {}).get("expected_goals")
                xg_v = (stats.get("stats", {}).get("away") or {}).get("expected_goals")
                if xg_l is not None:
                    conexion.execute("INSERT OR REPLACE INTO xg VALUES (?,?,?,?,?)",
                                     (partido["id"], xg_l, xg_v, "bsd", ahora.isoformat()))
                    conexion.executemany(
                        "INSERT OR REPLACE INTO tiros VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(partido["id"], i, int(t.get("home") or 0), t.get("min"),
                          t.get("player_id"), t.get("xg"), t.get("xgot"), t.get("type"),
                          (t.get("pos") or {}).get("x"), (t.get("pos") or {}).get("y"))
                         for i, t in enumerate(stats.get("shotmap") or [])])
                    conexion.commit()
                    registro.append(f"xG guardado: {partido['local']} vs {partido['visitante']}")
            except Exception:
                pass
    for partido in terminados:
        if partido["id"] in estado["post"]:
            continue
        cliente.enviar(
            chat_id,
            _mensaje_resultado(partido, evaluados.get(partido["id"]), informe, resumen_ledger),
        )
        estado["post"].append(partido["id"])
        registro.append(
            f"resultado enviado: {partido['local']} {partido['goles_local']}-"
            f"{partido['goles_visitante']} {partido['visitante']}"
        )

    _guardar_estado(ruta_estado, estado)
    return registro or ["sin novedades"]
