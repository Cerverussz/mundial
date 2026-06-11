# Sistema de predicción de marcadores — Mundial 2026

**Fecha:** 2026-06-10 · **Estado:** aprobado por el usuario (pendiente revisión final del documento)
**Contexto crítico:** el Mundial arranca el 2026-06-11. El usuario eligió construir el sistema completo (~1 semana) antes de la primera predicción, pero la captura de cuotas (fase 0) debe arrancar el día 0 porque las cuotas de apertura son datos perecederos.

## 1. Objetivo

Sistema de "conocimiento continuo" para predecir marcadores de fútbol: en cada consulta usa los datos más recientes disponibles, recalcula y muestra la predicción junto con qué datos usó, qué cambió desde la última consulta y cómo se compara con el mercado de apuestas.

**Alcance de predicción:** todos los partidos internacionales (Mundial 2026 como objetivo inmediato; amistosos, eliminatorias y Nations League como objetivos consultables con cobertura de datos menor).

**Metas:**
- Marcador exacto más probable + top 3, probabilidades 1X2, confianza (alta/media/baja con motivos) y explicación en español de los factores dominantes.
- Comparación modelo vs. mercado de-vigged con flags de valor (sin recomendación de stake — análisis solamente).
- Historial propio de cuotas opening→closing acumulado desde el día 0 vía snapshots.
- Tracking de precisión (Brier y RPS) contra el benchmark del mercado.
- 100 % fuentes gratis, sin tarjeta; degradación elegante ante cualquier fuente caída.

**No-metas:**
- Stake sizing / Kelly / gestión de bankroll.
- Predicción en vivo (in-play).
- Ligas de clubes (la arquitectura no las impide, pero no se construyen ahora).
- Scraping de FotMob (el proveedor objetó activamente en 2026; riesgo ToS alto).

## 2. Fuentes de datos (verificadas 2026-06-10)

| Fuente | Tier gratis | Aporta | Rol |
|---|---|---|---|
| BSD API (sports.bzzoiro.com) | Sin cuota diaria, throttling 429, sin tarjeta | Cuotas ~15 casas + Polymarket, xG/shotmaps, lesiones, alineaciones, convocatorias WC2026 | Primaria para cuotas/lesiones/xG. **Riesgo:** proyecto de una persona, 1 servidor, 3 caídas la última semana → nunca punto único de falla |
| The Odds API | 500 créditos/mes | Cuotas `soccer_fifa_world_cup` (h2h, totals, outrights), ~100 casas | Respaldo de cuotas (~8 capturas/día) |
| football-data.org | 10 req/min, TIER_ONE | Fixtures, resultados, tablas del Mundial (confirmado). Sin eliminatorias/amistosos gratis | Backbone estable de fixtures/resultados |
| api.fifa.com v3 (no documentada) | Sin auth | 104 partidos con estadios (idCompetition=17, idSeason=285023), convocatorias completas | Respaldo de fixtures + fuente de convocatorias |
| API-Football (api-sports.io) | 100 req/día | Lesiones, alineaciones, cuotas, stats | Relleno de huecos. **Verificar día 1 si season=2026 entra en el tier gratis** |
| eloratings.net | TSV públicos, sin key | Elo de selecciones actualizado a diario (`World.tsv`) | Feature de cordura + regularización |
| martj42/international_results (GitHub) | CC0, CSV crudo | 49 473 partidos internacionales 1872→hoy (+goleadores, penales, nombres históricos) | Bootstrap de ratings. Riesgo casi nulo |
| Open-Meteo | Gratis, sin key | Clima por coordenadas | Capa de contexto |
| dcaribou/transfermarkt-datasets | CSV en GitHub/Kaggle | Valores de mercado de jugadores | Ponderación de bajas (zona gris ToS; snapshot puntual, no scraping en vivo) |
| TheSportsDB (key `123`) | 30 req/min, listas capadas | Escudos y logos | Solo imágenes para el dashboard |
| OpenLigaDB | Sin key | Fixtures WC2026 (comunidad) | Respaldo terciario de fixtures |

**Descartadas:** FotMob (ToS), Understat (solo 6 ligas de clubes), FBref (xG Opta de internacionales pero requiere Selenium por Cloudflare, 10 req/min — opcional futuro), BALLDONTLIE FIFA (pide tarjeta).

**Registros que hace el usuario** (todos sin tarjeta): sports.bzzoiro.com, football-data.org, the-odds-api.com, api-sports.io. Keys en `.env` local y en GitHub Secrets.

## 3. Cobertura honesta por capa del modelo

| Capa | Cobertura | Nota |
|---|---|---|
| L1 Ratings (ataque/defensa dinámicos) | **FUERTE** | martj42 + eloratings.net |
| L2 xG | **MEDIA** | BSD por verificar calidad; sin histórico amplio gratis de xG de selecciones |
| L3 Forma con decaimiento | **FUERTE** | derivada de resultados |
| L4 Contexto (altitud, descanso, viaje, clima) | **FUERTE** | estadios estáticos + fixtures + Open-Meteo |
| L5 Plantel (bajas ponderadas por importancia) | **MEDIA** | depende de BSD/API-Football; valores de Transfermarkt en zona gris |
| L6 H2H | **FUERTE** | martj42 (peso bajo por diseño) |
| L7 Señal de mercado | **FUERTE hacia adelante, DÉBIL hacia atrás** | el historial opening→closing se construye desde el día 0; no existe retroactivo gratis |
| L8 Intangibles | **MEDIA** | heurísticas de importancia/rotación |

## 4. Arquitectura (enfoque aprobado: A)

Monorepo Python local-first. GitHub Actions (repo público ⇒ Actions gratis ilimitado) corre un cron que captura snapshots y los commitea: **git es la bitácora versionada y auditable**. El Mac del usuario hace `git pull` antes de cada query y reconstruye un SQLite local derivado (gitignored). Streamlit lee el mismo SQLite.

```
mundial/
├── CLAUDE.md                  # decisiones, APIs+límites, capas FUERTE/DÉBIL, convenciones, cómo correr
├── README.md                  # setup paso a paso
├── pyproject.toml             # uv; Python 3.12
├── .env.example
├── .github/workflows/
│   ├── snapshot.yml           # cron cada 2 h (30–60 min en ventanas de partido): cuotas + lesiones
│   └── resultados.yml         # post-partido: resultados finales + refit de ratings
├── data/
│   ├── snapshots/             # commiteados: 2026-06-11/1430-bsd.json.gz (append-only)
│   ├── static/                # estadios.csv (altitud/coords/tz), equipos.csv, mapeo_nombres.csv
│   └── local/                 # mundial.db + caché HTTP — gitignored
├── src/mundial/
│   ├── ingesta/               # base.py (interfaz), bsd.py, odds_api.py, football_data.py,
│   │                          # fifa.py, eloratings.py, martj42.py, open_meteo.py,
│   │                          # cascada.py, presupuesto.py (límites por fuente)
│   ├── factores/              # elo.py, forma.py, contexto.py, plantel.py, mercado.py (de-vig)
│   ├── modelo/                # dixon_coles.py, blend.py, confianza.py, explicacion.py
│   ├── persistencia/          # esquema.py, repos.py, auditoria.py
│   ├── cli.py                 # Typer: hoy | predecir | jornada | snapshot | precision | fuentes
│   └── dashboard/             # app.py + pages/
└── tests/
```

Convenciones: código e identificadores en inglés es lo estándar, pero aquí el dominio se nombra en español (decisión consciente: usuario hispanohablante, proyecto personal); salidas de CLI/dashboard en español; commits y README en inglés.

## 5. Modelo de datos (SQLite, derivado de snapshots)

- `equipos(id, codigo_fifa, nombre, confederacion)`
- `estadios(id, nombre, ciudad, pais, altitud_m, lat, lon, tz)` — los 16 del Mundial, estático
- `partidos(id, fecha_utc, local, visitante, fase, estadio_id, estado, goles_local, goles_visitante, fuente)`
- `cuotas(id, partido_id, capturado_en, fuente, casa, mercado, local, empate, visitante)` — cada fila un snapshot
- `lesiones(partido_id/equipo, jugador, estado, capturado_en)`
- `valores_plantel(equipo, jugador, valor_eur, fecha_corte)`
- `ratings(equipo, fecha, ataque, defensa, elo_externo)`
- `predicciones(id, partido_id, creado_en, commit_datos, version_modelo, marcador, p_local, p_empate, p_visita, matriz_json, confianza, factores_json)`
- `log_requests(fuente, fecha, conteo)` — aviso al 80 % del límite

La regla de auditoría: una predicción referencia el hash del commit de datos + versión del modelo ⇒ reproducible y explicable.

## 6. Ingesta: cascada, caché, presupuesto

- Interfaz por tipo de dato; orden de cascada: **cuotas** BSD → The Odds API · **fixtures/resultados** football-data.org → api.fifa.com → OpenLigaDB · **lesiones** BSD → API-Football · **clima** Open-Meteo · **ratings** eloratings.net → Elo propio.
- Caché con TTL por "¿pudo cambiar?": resultado final = inmutable; cuotas TTL 30 min (5 min en las 2 h previas al kickoff); fixtures TTL 12 h; convocatorias TTL 24 h; estáticos = para siempre.
- `presupuesto.py` persiste conteos por fuente/día y bloquea con aviso antes de exceder un límite; el dashboard lo muestra.
- Si todas las fuentes de un dato fallan: la predicción sale igual, con confianza degradada y lista explícita de datos faltantes. Nunca hard-fail.

## 7. Motor de predicción

1. **Bootstrap:** Dixon-Coles con decaimiento exponencial (half-life ≈ 730 días, ξ ajustable) sobre martj42 (~10 años efectivos), parámetros de ataque/defensa por selección, corrección ρ de marcadores bajos, ventaja de local solo si no es cancha neutral (Mundial: MEX/USA/CAN locales reales, resto neutral). Refit tras cada jornada (scipy, minutos).
2. **Ajustes multiplicativos sobre λ** (cada uno acotado y registrado para la explicación): forma reciente ponderada por recencia y fuerza del rival · altitud (p. ej. Azteca 2 240 m) · días de descanso · distancia de viaje y cambio horario · clima · bajas ponderadas por share de valor de mercado del plantel · importancia del partido/rotación esperada. H2H entra con peso bajo fijo.
3. **Mercado:** de-vig proporcional + método de Shin (ambos, con tests); consenso multi-casa por mediana; sesgo favorito-longshot corregido con prior de literatura (no tenemos histórico propio aún).
4. **Salidas:** matriz de marcadores (0–6+ × 0–6+) ⇒ marcador más probable + top 3; 1X2 oficial = blend configurable `w·modelo + (1−w)·mercado` (default w=0.4); value flag cuando |p_modelo − p_mercado| > umbral (default 5 pts) sostenido en ≥2 snapshots; confianza por frescura/completitud de datos + acuerdo modelo-mercado + incertidumbre de parámetros.
5. **Elo externo** (eloratings.net) como verificación de cordura y regularizador para selecciones con pocos partidos recientes.
6. **Fase posterior opcional:** capa XGBoost/CatBoost sobre los features con SHAP para explicabilidad; xG (BSD) como sustituto de goles observados en el refit si la calidad lo justifica.

## 8. Flujo de query (CLI)

`mundial predecir mex-rsa` (también `mundial hoy`, `mundial jornada 1`):
1. `git pull` (trae snapshots nuevos de Actions).
2. Detecta cambios desde la última query del usuario: resultados nuevos, movimiento de cuotas, lesiones nuevas.
3. Refresca en vivo solo lo que pudo cambiar y el presupuesto permita.
4. Recalcula y persiste la predicción.
5. Muestra: timestamp de la query · datos usados con frescura por fuente · **qué cambió desde la última consulta** · predicción (marcador, top 3, 1X2, confianza) · explicación de factores · modelo vs. mercado con value flags.

## 9. Dashboard (Streamlit, 5 páginas)

1. **Hoy/Jornada:** partidos con predicción resumida.
2. **Partido:** matriz de marcadores (heatmap), factores, evolución de cuotas desde nuestro historial, bajas.
3. **Modelo vs. mercado:** divergencias y value flags activos.
4. **Precisión:** Brier/RPS acumulado del modelo vs. benchmark mercado-solo.
5. **Sistema:** salud de fuentes, presupuesto de requests, frescura de datos.

## 10. GitHub Actions

- `snapshot.yml`: dos crons estáticos — `0 */2 * * *` (base) y `*/30 15-23,0-3 * * *` (horario diario de partidos del torneo, UTC); corre `mundial snapshot`; commitea `data/snapshots/` con mensaje `snapshot: 2026-06-11T14:30Z (bsd, odds-api)`. Keys via Secrets. Nota: el cron de Actions puede retrasarse minutos — aceptable.
- `resultados.yml`: tras cada bloque de partidos, captura resultados y commitea; el refit de ratings ocurre localmente en la siguiente query (no en CI) para mantener Actions simple.
- El Mac nunca depende de Actions para funcionar: sin red, predice con el último snapshot local y lo declara.

## 11. Testing

pytest: de-vig proporcional y Shin (márgenes conocidos, ida y vuelta) · Dixon-Coles recupera parámetros sintéticos · pesos de decaimiento · matriz suma 1 y simetrías · ajustes acotados · cascada con mocks (fuente caída ⇒ respaldo ⇒ degradación declarada) · presupuesto bloquea en el límite · esquema y auditoría (predicción referencia commit existente).

## 12. Fases

- **F0 (hoy):** repo público + adaptadores de cuotas (BSD, The Odds API) + `mundial snapshot` + `snapshot.yml` corriendo. El historial de cuotas empieza a acumularse antes que todo lo demás.
- **F1:** estáticos + fixtures/resultados + bootstrap martj42 → Elo/DC base.
- **F2:** motor completo (L1, L3, L4, L6, L7) + de-vig + blend + CLI completo.
- **F3:** dashboard.
- **F4:** L5 (lesiones + valores) y L8; xG si BSD da calidad.
- **F5:** precisión Brier/RPS + comparación vs. mercado + capa GBM opcional.

## 13. Riesgos y verificaciones pendientes

- **BSD puede caerse o desaparecer** (3 caídas en 7 días): mitigado por cascada + snapshots persistidos; nada depende solo de él.
- **API-Football season 2026 en tier gratis:** sin confirmar; se prueba el día 1 con la key del usuario y se ajusta la cascada si no entra.
- **api.fifa.com podría añadir auth/geoblock durante el torneo:** respaldo OpenLigaDB + openfootball/worldcup.json.
- **Cuotas de cierre ≠ apertura para partidos tempranos:** los primeros partidos tendrán historial corto de cuotas; la calibración opening→closing mejora con el torneo.
- **Valores de Transfermarkt:** zona gris de ToS; se usa snapshot puntual del dataset comunitario, no scraping en vivo, y la capa L5 funciona sin él (bajas sin ponderar) si se decide retirarlo.
