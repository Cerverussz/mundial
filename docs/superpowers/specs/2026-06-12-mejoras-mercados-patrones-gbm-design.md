# Mejoras v2: mercados derivados, paper trading, minería de patrones y GBM

**Fecha:** 2026-06-12 · **Estado:** aprobado (Enfoque A) · **Horizonte:** las 5 semanas del Mundial 2026
**Base:** sistema v1 completo (spec 2026-06-10). Investigación multi-agente 2026-06-12: 61 hallazgos, 5 áreas; los 2 hallazgos estructurales clave verificados adversarialmente; 10 verificaciones de patrones de literatura no corrieron (límite de sesión) → esos entran como *candidatos* y se re-validan sobre datos propios antes de activarse (ver M2).

## 1. Objetivo (de la entrevista)

Apostar con ventaja **empezando 100% simulado** (paper trading con CLV como métrica norte) + aprender construyendo (GBM+SHAP ahora). Mercados nuevos: over/under, BTTS, hándicap asiático. Patrones: de juego, de mercado, históricos de Mundiales y descubrimiento automático — consumidos como informe + alertas pre-partido en Telegram. Sin polla. Todo debe rendir dentro del torneo.

**No-metas:** dinero real (decisión del usuario tras ver evidencia simulada); stake sizing para dinero real; live betting; steam/RLM (inviable con cadencia 30 min); cambiar Dixon-Coles por bivariate Poisson a mitad de torneo (sin beneficio que justifique el riesgo).

## 2. Hechos medidos en vivo que habilitan el diseño

- **[VERIFICADO ✓]** Los snapshots BSD ya capturan 11 mercados con ~15 casas (Pinnacle incl.): `1x2, double_chance, over_under_15/25/35, btts, draw_no_bet, total_corners, corners_1x2, red_card, total_red_cards` — historial apertura→cierre acumulándose desde 2026-06-11 en el repo.
- **[VERIFICADO ✓]** BSD `GET /events/{id}/stats/` responde para partidos terminados: `stats.home/away` (~54 campos, `expected_goals`), `shotmap[]` (xG/xGOT por tiro, coords, player_id), `xg_per_minute[]`. Para no iniciados devuelve 200 con nulls (loader seguro). Ojo: `xg.actual` es null a FT — usar `expected_goals`; por mitades sí viene.
- The Odds API: AH (`spreads`) y `totals` con líneas de cuarto, 7 casas (Pinnacle, Matchbook) vía `/events/{id}/odds`; coste medido 5 créditos/sondeo (= mercados devueltos × regiones). Quedan ~490 créditos → ~30 sondeos selectivos.
- Alineaciones BSD confirman tarde (T+54 min, medido en 14 snapshots; al confirmar pierde `ai_score`). FIFA live (`/api/v3/live/football/17/285023/{IdStage}/{IdMatch}`) publica el XI oficial ~60-75 min antes, con `Players[26]`, suplencias, árbitros.
- StatsBomb open-data: eventos con xG por tiro de WC 2018 (43/3) y 2022 (43/106), gratis con atribución.
- **Trampa martj42:** marcadores de eliminatorias incluyen prórroga (empate KO medido 21.4% vs ~30% real a 90') → minería de mercados sobre KO requiere dataset con score a 90' (datahub.io/football/worldcup, 1930-2022, FT/ET/penales separados).

## 3. M1 — Mercados derivados + paper trading (días 1-2)

**Precios desde la matriz.** `modelo/mercados.py`: con `M[i,j]` (matriz final), `D = i−j`:
- Over L (L semientero) = Σ M[i,j] : i+j > L; líneas enteras con push: o_justo = 1 + P(T<L)/P(T>L); líneas de cuarto = mitad de stake en las dos adyacentes.
- BTTS sí = M[1:,1:].sum() (usar la matriz, NO Poisson independiente: τ ya infla 0-0/1-1 con ρ<0).
- AH general: P_fw/P_hw/P_hl/P_fl (gana/media/pierde-media/pierde) → o_justo = 1 + (P_fl + ½P_hl)/(P_fw + ½P_hw); retornos por unidad: o−1 / (o−1)/2 / 0 / −0.5 / −1. DNB = AH 0. Tests con casos sintéticos obvios (h=−0.5 ≡ P(D≥1)).
- `MAX_GOLES` 8 → 10 (elimina sesgo residual en over 3.5 con λ altas).

**Blend en espacio λ** (`modelo/inversion.py`): invertir (λ_mkt, μ_mkt) resolviendo por Newton/bisección 2D sobre la propia matriz DC (ρ fijo) las ecuaciones p_DNB_local y p_Over2.5 devigadas del consenso; λ_b = w·λ_modelo + (1−w)·λ_mkt; **una sola matriz final coherente** para 1X2, marcador, O/U, BTTS y AH (estructura de Egidi et al. 2018, arXiv:1802.08848). Si el partido no tiene DNB/O-U en el consenso, fallback al reescalado 1X2 actual (degradación declarada).

**Cuotas multi-mercado.** Nueva tabla `cuotas_mercado(partido_id, capturado_en, fuente, casa, mercado, seleccion, cuota, PK(todas menos cuota))`; `cargar_cuotas` extrae los 11 mercados de los snapshots, con registro de carga propio (`archivos_cargados_mercados`) para reprocesar una sola vez todos los snapshots existentes sin tocar la carga 1X2 ya hecha. De-vig: Shin vale para 2 salidas; mediana multi-casa excluyendo sintéticas (reuso del módulo).

**Ledger simulado** (`modelo/ledger.py` + tabla `apuestas`): cuando un value flag es sostenido (>5 pts, ≥2 h) en un mercado con cuota real → registrar apuesta de papel a la mejor cuota devig disponible: flat 1u (medición primaria) y ¼-Kelly sobre bankroll virtual 100u (aprendizaje). Liquidación en `vigilar` post-partido (incluye half-win/push de AH). **CLV** por apuesta: cuota tomada vs cierre devigado de Pinnacle (fallback: mediana) del último snapshot pre-kickoff. El yield no alcanza significancia en 5 semanas (t = y·√n/√(o̅−1)); el CLV sí discrimina — métrica norte. `mundial ledger` (CLI) + línea en mensajes de Telegram + página en dashboard.

**Precision**: añadir log-loss (ignorance score; mejor discriminador que RPS/Brier según Wheatcroft 2021) y calibración por mercado.

## 4. M2 — Minería de patrones pre-registrada (días 3-5)

**Datos:** datahub worldcup (score 90'/ET/penales + etiquetas oficiales de fase) → tabla `resultados_wc`; `data/static/confederaciones.csv`; xG post-partido del BSD → tablas `xg` y `tiros` (loader en `vigilar` post-partido); StatsBomb 2018+2022 queda como ampliación opcional (solo si una familia de hipótesis de la minería necesita xG histórico — las familias iniciales usan marcadores).

**Metodología** (`analisis/mineria.py`): catálogo de familias de hipótesis (goles por fase, dead rubbers, confederaciones, descanso, era) parametrizado → ~100-300 tests; estratificación por era obligatoria (cortes 1992/1994/1995/2018/2020; análogo correcto de 2026 = 1986-1994 por formato de clasificación 67%); Benjamini-Hochberg q=0.10 por familia + IC bootstrap + n mínimo; mercados sobre KO solo con score 90'.

**Pre-registro vía git:** `data/patrones.json` con esquema declarativo: `{id, familia, hipotesis, filtro (claves cerradas: fase, jornada, confederacion_*, dead_rubber_*, dias_descanso_min, es_anfitrion, es_debut, diff_rating_abs), mercado_objetivo, lado, efecto{tasa, baseline, lift}, n, p_adj_bh, ic95, holdout, registrado_en_commit, ventana_validez, umbral_prob_implicita, estado: activo|en_papel|retirado}`. El motor de alertas **rechaza** patrones cuyo commit no preceda al partido. Alerta en `vigilar` pre-partido sii: estado activo ∧ contexto del partido satisface el filtro ∧ mejor cuota devig ≤ umbral (tasa − semiancho IC − 1 pt seguridad). Mensaje con n, lift±IC, p_adj y disclaimer "patrón pre-registrado — apuesta de papel". Las apuestas por patrón van a un ledger separado del de modelo.

**Candidatos iniciales** (de la investigación; NINGUNO se activa sin pasar la validación propia): empate <3.20 en KO parejos (+22.7% ROI documentado, base estructural), under jornada 1 vs ancla histórica (formato 2026), dead rubbers MD3 etiquetados con la tabla en vivo, overreacción post-upset de MD1, sesgo patriótico USA en libros US (sin estudio previo — lo medimos nosotros con snapshots multi-casa), tercer puesto over (3.80 goles/partido histórico).

**Informe:** página "Patrones" en el dashboard + sección en el README de datos.

## 5. M3 — GBM + SHAP (semana 2)

- **Anti-leakage:** `ratings_asof` — refits Dixon-Coles expanding-window por año (~50 refits × 0.4 s), materializados en `ratings` (la PK ya soporta fechas múltiples); toda feature estrictamente t<partido.
- **Modelo:** LightGBM, descomposición ordinal Frank-Hall (2 binarios: P(local no pierde), P(local gana)) — no softmax 3-clases; ~22 features (diffs de rating as-of, forma decaída, descanso, neutral, tipo de torneo, pares de confederación, dummies de era, contexto de clasificación); restricciones monótonas donde el signo es conocido; calibración isotónica out-of-fold.
- **Validación:** walk-forward por ciclos de Mundial (entrenar ≤2013→test 2014, ≤2017→2018, ≤2021→2022, holdout 2024-2026); métrica RPS/log-loss vs DC puro walk-forward. **Puerta de entrada: el GBM entra al blend solo si gana en TODOS los bloques de test**, no en promedio. Integración: pool log-lineal de 3 señales con pesos ajustados en histórico, nunca sobre partidos del torneo.
- **SHAP:** por partido (se suma a la explicación en español) y global (alimenta nuevas hipótesis de M2 — nunca se promueve directo a alertas). Solo sobre folds de test.
- **Expectativa honesta** (literatura: Hubáček et al.): sin cuotas históricas, GBM ≈ modelos de rating (ΔRPS ~0.001-0.005). Valor real: aprendizaje, explicabilidad, descubrimiento.

## 6. M4 — Afinación continua (resto del torneo)

- Peso w del blend: minimizar log-loss walk-forward con shrinkage al prior w₀=0.4 (n₀=50, w∈[0.2,0.6]); probar pooling geométrico en paralelo.
- Sondeos AH selectivos en The Odds API (5 cr) solo cuando el modelo señale valor AH; Pinnacle+Matchbook como cierre sharp para CLV de AH.
- Alerta "XI confirmado" desde FIFA live en `vigilar` (T-90 min): difiere/coincide con el XI predicho usado por la predicción.
- Checkpoint tras fase de grupos: revisar patrones (BH sobre resultados 2026), recalibrar, decidir si el GBM pasó la puerta.

## 7. Métricas de éxito del torneo

1. **CLV medio > 0** con IC bootstrap en el ledger de modelo (la evidencia de ventaja real que pediste antes de poner dinero).
2. Log-loss del blend ≤ log-loss del mercado puro en los ~104 partidos.
3. ≥3 patrones pre-registrados que sobrevivan su holdout 2026.
4. Resultado documentado de la puerta GBM (entra o no entra, con números) + informe SHAP global.

## 8. Riesgos

- Mercados secundarios con menos casas (BTTS 4 en Odds API; medianas más ruidosas) → umbral de edge por mercado = margen medido + seguridad.
- Patrones de literatura no verificados adversarialmente (límite de sesión) → mitigado por diseño: nada alerta sin re-validación propia + pre-registro.
- BSD sigue siendo único proveedor de O/U-BTTS multi-casa → sondeos Odds API como respaldo puntual; degradación declarada como siempre.
- Sobreajuste del GBM a Mundiales viejos → puerta estricta por bloques + holdout intocado.
