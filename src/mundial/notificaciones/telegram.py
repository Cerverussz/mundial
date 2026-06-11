"""Notificaciones por Telegram: resumen diario de pronósticos y resultados."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import httpx

BASE = "https://api.telegram.org"
LIMITE_MENSAJE = 4000


class ClienteTelegram:
    def __init__(self, token: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=f"{BASE}/bot{token}", timeout=30, transport=transporte
        )

    def enviar(self, chat_id: str, texto: str) -> int:
        """Envía texto HTML, troceado al límite de Telegram. Devuelve nº de mensajes."""
        enviados = 0
        for trozo in _trocear(texto, LIMITE_MENSAJE):
            respuesta = self._http.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": trozo,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            respuesta.raise_for_status()
            enviados += 1
        return enviados

    def obtener_chat_id(self) -> str | None:
        """Chat del mensaje más reciente recibido por el bot (para --configurar)."""
        respuesta = self._http.get("/getUpdates")
        respuesta.raise_for_status()
        for actualizacion in reversed(respuesta.json().get("result", [])):
            mensaje = actualizacion.get("message") or actualizacion.get("edited_message")
            if mensaje and mensaje.get("chat", {}).get("id") is not None:
                return str(mensaje["chat"]["id"])
        return None


def _trocear(texto: str, limite: int) -> list[str]:
    if len(texto) <= limite:
        return [texto]
    trozos: list[str] = []
    actual = ""
    for linea in texto.split("\n"):
        if actual and len(actual) + len(linea) + 1 > limite:
            trozos.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        trozos.append(actual)
    return trozos


def _bloque_prediccion(resultado) -> str:
    lineas = [f"⚽ <b>{resultado.local} vs {resultado.visitante}</b>"]
    top = " · ".join(f"{i}-{j} ({p * 100:.0f}%)" for i, j, p in resultado.top3)
    lineas.append(
        f"Marcador más probable: <b>{resultado.marcador[0]}-{resultado.marcador[1]}</b> ({top})"
    )
    p = resultado.p_final
    linea_1x2 = (
        f"1X2: <b>{p['local'] * 100:.0f}/{p['empate'] * 100:.0f}/{p['visitante'] * 100:.0f}</b>"
    )
    if resultado.p_mercado:
        m = resultado.p_mercado
        linea_1x2 += (
            f" (mercado {m['local'] * 100:.0f}/{m['empate'] * 100:.0f}/"
            f"{m['visitante'] * 100:.0f}, {resultado.n_casas} casas)"
        )
    lineas.append(linea_1x2)
    lineas.append(f"Confianza: {resultado.confianza}")
    for flag in resultado.valor_flags:
        etiqueta = "sostenida" if flag["sostenida"] else "reciente"
        lineas.append(
            f"💎 Valor: {flag['resultado']} {flag['margen'] * 100:+.1f} pts ({etiqueta})"
        )
    return "\n".join(lineas)


def armar_resumen(
    conexion: sqlite3.Connection,
    fecha: str | None = None,
    cliente_bsd=None,
) -> str | None:
    """Resumen del día: pronósticos de hoy + resultados de ayer + precisión acumulada."""
    from mundial.modelo import precision, prediccion

    fecha = fecha or datetime.now(timezone.utc).date().isoformat()
    ayer = (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()
    secciones: list[str] = []

    # La "jornada" en horario de las Américas se extiende hasta la madrugada UTC siguiente.
    manana = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
    partidos_hoy = conexion.execute(
        """SELECT id, fecha_utc, estadio FROM partidos
           WHERE fecha_utc >= ? AND fecha_utc < ? AND goles_local IS NULL
           ORDER BY fecha_utc""",
        (f"{fecha}T00:00", f"{manana}T05:00"),
    ).fetchall()
    if partidos_hoy:
        bloques = [f"🏆 <b>Pronósticos del {fecha}</b>"]
        for partido in partidos_hoy:
            encabezado = partido["fecha_utc"][11:16] + " UTC"
            if partido["estadio"]:
                encabezado += f" · {partido['estadio']}"
            try:
                resultado = prediccion.predecir(conexion, partido["id"], cliente_bsd=cliente_bsd)
                bloques.append(f"{_bloque_prediccion(resultado)}\n🕒 {encabezado}")
            except Exception as error:
                fila = conexion.execute(
                    "SELECT local, visitante FROM partidos WHERE id = ?", (partido["id"],)
                ).fetchone()
                bloques.append(
                    f"⚽ <b>{fila['local']} vs {fila['visitante']}</b>\n"
                    f"(sin predicción: {error})"
                )
        secciones.append("\n\n".join(bloques))

    informe = precision.evaluar(conexion)
    de_ayer = [p for p in informe["partidos"] if p["fecha"][:10] == ayer]
    if de_ayer:
        lineas = [f"📊 <b>Resultados del {ayer}</b>"]
        for p in de_ayer:
            marca_1x2 = "✅" if p["acerto_1x2"] else "❌"
            marca_marcador = "✅" if p["acerto_marcador"] else "❌"
            lineas.append(
                f"{marca_1x2} {p['partido']} — predicho {p['marcador_predicho']} "
                f"(marcador exacto {marca_marcador})"
            )
        if informe["blend"]["rps"] is not None:
            lineas.append(
                f"Acumulado ({informe['n']} partidos): RPS blend "
                f"{informe['blend']['rps']:.4f}"
                + (
                    f" vs mercado {informe['mercado']['rps']:.4f}"
                    if informe["mercado"]["rps"] is not None else ""
                )
            )
        secciones.append("\n".join(lineas))

    if not secciones:
        return None
    return "\n\n".join(secciones)
