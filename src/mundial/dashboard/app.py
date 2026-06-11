"""Dashboard del sistema de predicción — `uv run streamlit run src/mundial/dashboard/app.py`."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from mundial.dashboard import datos
from mundial.modelo import precision as modulo_precision
from mundial.persistencia import bd, esquema

st.set_page_config(page_title="Mundial 2026 — predicciones", page_icon="⚽", layout="wide")


@st.cache_resource
def conexion():
    con = bd.conectar()
    esquema.crear(con)
    return con


def _tarjeta_prediccion(partido: dict, prediccion: dict | None) -> None:
    encabezado = f"**{partido['local']} vs {partido['visitante']}**"
    detalle = f"{partido['fecha_utc']} · {partido.get('estadio') or 'estadio por confirmar'}"
    if prediccion is None:
        st.markdown(f"{encabezado}  \n{detalle}  \n_(sin predicción aún — corre "
                    f"`mundial predecir` o usa el botón en la página Partido)_")
        return
    columnas = st.columns([2, 1, 1, 1, 1])
    columnas[0].markdown(f"{encabezado}  \n{detalle}")
    columnas[1].metric("Marcador", prediccion["marcador"])
    columnas[2].metric(f"Gana {partido['local']}", f"{prediccion['p_local'] * 100:.0f}%")
    columnas[3].metric("Empate", f"{prediccion['p_empate'] * 100:.0f}%")
    columnas[4].metric(f"Gana {partido['visitante']}", f"{prediccion['p_visitante'] * 100:.0f}%")
    flags = prediccion.get("flags") or []
    if flags:
        st.markdown(
            " · ".join(
                f":violet[VALOR {f['resultado']} {f['margen'] * 100:+.1f} pts"
                f"{' (sostenida)' if f['sostenida'] else ''}]" for f in flags
            )
        )
    st.caption(f"Confianza: {prediccion['confianza']} · calculada {prediccion['creado_en']}")


def pagina_hoy() -> None:
    st.title("Partidos próximos")
    con = conexion()
    partidos = datos.partidos_proximos(con, dias=int(st.sidebar.slider("Días", 1, 14, 3)))
    if not partidos:
        st.info("No hay partidos en la ventana elegida. Corre `mundial actualizar`.")
        return
    for partido in partidos:
        _tarjeta_prediccion(partido, datos.ultima_prediccion(con, partido["id"]))
        st.divider()


def pagina_partido() -> None:
    st.title("Detalle de partido")
    con = conexion()
    partidos = datos.partidos_proximos(con, dias=40)
    if not partidos:
        st.info("Sin partidos cargados.")
        return
    opciones = {f"{p['fecha_utc'][:10]} · {p['local']} vs {p['visitante']}": p for p in partidos}
    elegido = opciones[st.selectbox("Partido", list(opciones))]
    if st.button("Recalcular predicción ahora"):
        from mundial.modelo import prediccion as modulo

        with st.spinner("Recalculando con los datos más recientes…"):
            modulo.predecir(con, elegido["id"])
        st.rerun()
    pred = datos.ultima_prediccion(con, elegido["id"])
    if pred is None:
        st.warning("Este partido aún no tiene predicción — usa el botón de arriba.")
        return
    _tarjeta_prediccion(elegido, pred)

    izquierda, derecha = st.columns(2)
    with izquierda:
        st.subheader("Matriz de marcadores")
        matriz = pd.DataFrame(pred["matriz"])
        figura = px.imshow(
            matriz.values,
            labels={"x": f"Goles {elegido['visitante']}", "y": f"Goles {elegido['local']}",
                    "color": "P"},
            color_continuous_scale="Greens", text_auto=".1%",
        )
        figura.update_layout(height=420, coloraxis_showscale=False)
        st.plotly_chart(figura, use_container_width=True)
    with derecha:
        st.subheader("Evolución del consenso del mercado")
        serie = datos.evolucion_consenso(con, elegido["id"])
        if serie:
            df = pd.DataFrame(serie).rename(columns={
                "local": f"Gana {elegido['local']}",
                "empate": "Empate",
                "visitante": f"Gana {elegido['visitante']}",
            })
            figura = px.line(
                df, x="capturado_en",
                y=[f"Gana {elegido['local']}", "Empate", f"Gana {elegido['visitante']}"],
            )
            figura.update_layout(height=420, yaxis_tickformat=".0%",
                                 legend_title=None, xaxis_title=None)
            st.plotly_chart(figura, use_container_width=True)
        else:
            st.caption("Aún no hay historial de cuotas para este partido.")

    st.subheader("Factores")
    relevantes = [
        f for f in pred["factores"]
        if abs(f.get("local", 1) - 1) > 0.005 or abs(f.get("visitante", 1) - 1) > 0.005
    ]
    if relevantes:
        st.dataframe(
            pd.DataFrame(relevantes).rename(columns={
                "nombre": "factor", "local": "× λ local", "visitante": "× λ visitante",
                "detalle": "detalle",
            }),
            use_container_width=True, hide_index=True,
        )
    if pred["razones"]:
        st.caption("Confianza: " + "; ".join(pred["razones"]))

    bajas = con.execute(
        """SELECT equipo, jugador, estado, razon FROM bajas WHERE partido_id = ?
           AND capturado_en = (SELECT MAX(capturado_en) FROM bajas WHERE partido_id = ?)""",
        (elegido["id"], elegido["id"]),
    ).fetchall()
    if bajas:
        st.subheader("Bajas conocidas")
        st.dataframe(pd.DataFrame([dict(b) for b in bajas]), hide_index=True)


def pagina_mercado() -> None:
    st.title("Modelo vs mercado")
    filas = datos.divergencias(conexion())
    if not filas:
        st.info("Sin predicciones registradas todavía.")
        return
    df = pd.DataFrame([
        {
            "partido": f"{f['local']} vs {f['visitante']}",
            "fecha": f["fecha_utc"][:16],
            "marcador": f["marcador"],
            "P(local) modelo": f["p_local_modelo"],
            "P(local) mercado": f["p_local_mercado"],
            "divergencia máx": f["divergencia"],
            "flags de valor": ", ".join(
                f"{x['resultado']} {x['margen'] * 100:+.1f}" for x in f["flags"]
            ) or "—",
            "confianza": f["confianza"],
        }
        for f in filas
    ])
    st.dataframe(
        df.style.format({
            "P(local) modelo": "{:.0%}", "P(local) mercado": "{:.0%}",
            "divergencia máx": "{:.0%}",
        }),
        use_container_width=True, hide_index=True,
    )


def pagina_precision() -> None:
    st.title("Precisión del modelo")
    informe = modulo_precision.evaluar(conexion())
    if informe["n"] == 0:
        st.info("Aún no hay partidos terminados con predicción previa al kickoff. "
                "Esta página cobra vida cuando terminen los primeros partidos.")
        return
    columnas = st.columns(3)
    for columna, nombre in zip(columnas, ("modelo", "mercado", "blend")):
        datos_variante = informe[nombre]
        if datos_variante["n"]:
            columna.metric(
                f"{nombre} — RPS medio", f"{datos_variante['rps']:.4f}",
                help="Menor es mejor. El mercado es el benchmark a batir.",
            )
            columna.caption(f"Brier: {datos_variante['brier']:.4f} · n={datos_variante['n']}")
    aciertos = pd.DataFrame([
        {
            "partido": p["partido"], "fecha": p["fecha"][:16],
            "predicho": p["marcador_predicho"], "1X2": "✓" if p["acerto_1x2"] else "✗",
            "marcador exacto": "✓" if p["acerto_marcador"] else "✗",
            "RPS blend": p["metricas"].get("blend", {}).get("rps"),
        }
        for p in informe["partidos"]
    ])
    st.dataframe(aciertos, use_container_width=True, hide_index=True)


def pagina_sistema() -> None:
    st.title("Estado del sistema")
    from datetime import datetime, timezone

    from mundial.config import DIR_SNAPSHOTS
    from mundial.ingesta import snapshots

    con = conexion()
    ahora = datetime.now(timezone.utc)
    columnas = st.columns(2)
    for columna, fuente in zip(columnas, ("bsd", "odds-api")):
        ultimo = snapshots.ultimo_snapshot(fuente, base=DIR_SNAPSHOTS)
        edad = f"hace {(ahora - ultimo).total_seconds() / 3600:.1f} h" if ultimo else "nunca"
        columna.metric(f"Último snapshot {fuente}", edad)
    rutas = sorted(DIR_SNAPSHOTS.glob("*/*-odds-api.json.gz"))
    if rutas:
        carga = snapshots.leer_snapshot(rutas[-1])["payload"]
        if isinstance(carga, dict) and carga.get("presupuesto"):
            st.metric("Créditos restantes The Odds API (mes)", carga["presupuesto"]["restantes"])
    conteos = {
        "Partidos": "partidos", "Resultados históricos": "resultados_historicos",
        "Filas de cuotas": "cuotas", "Bajas": "bajas", "Predicciones": "predicciones",
    }
    df = pd.DataFrame([
        {"tabla": nombre, "filas": con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]}
        for nombre, tabla in conteos.items()
    ])
    st.dataframe(df, hide_index=True)
    meta = con.execute(
        "SELECT * FROM modelo_meta ORDER BY fecha_ajuste DESC LIMIT 1"
    ).fetchone()
    if meta:
        st.caption(
            f"Ratings ajustados el {meta['fecha_ajuste']} con {meta['n_partidos']} partidos y "
            f"{meta['n_equipos']} equipos · ventaja local {meta['ventaja_local']:.3f} · "
            f"ρ {meta['rho']:.3f} · {meta['version']}"
        )


st.navigation(
    [
        st.Page(pagina_hoy, title="Próximos partidos", icon="📅", default=True),
        st.Page(pagina_partido, title="Partido", icon="🎯"),
        st.Page(pagina_mercado, title="Modelo vs mercado", icon="📈"),
        st.Page(pagina_precision, title="Precisión", icon="📊"),
        st.Page(pagina_sistema, title="Sistema", icon="🩺"),
    ]
).run()
