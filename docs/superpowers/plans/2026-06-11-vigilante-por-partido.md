# Vigilante por partido — pre-match analysis + post-match result via Telegram

**Root causes found (2026-06-11 ~21:50 UTC):**
1. football-data free tier returned `FINISHED` with null `fullTime` scores for Mexico-South Africa while FIFA calendar and BSD both had 2-0 → `actualizar` must merge scores from the FIFA calendar when fd lacks them (cascade applies per-field, not only per-source).
2. South Korea-Czech Republic kicks off 02:00 UTC June 12 → next-day UTC date, so the daily 13:00 digest (filtering `date(fecha_utc)=today`) can never announce it in time. Per-match timing is needed, not date buckets.
3. CI runners are stateless → post-match messages can't know what was predicted unless predictions persist in the repo.

**Design:**
- `actualizar`: merge `goles_*` (+ estado=FINISHED) from FIFA calendar rows when fd has none.
- Prediction persistence: `predecir(..., dir_exportacion)` appends a JSONL line per prediction to `data/predicciones/YYYY-MM-DD.jsonl` (committed by CI); `prediccion.cargar_exportadas()` imports them with `INSERT OR IGNORE` (new unique index on `predicciones(partido_id, creado_en)`); `actualizar` imports on every run. CLI predict commands and vigilar export; the daily digest does not.
- `notificaciones/vigilar.py` — `vigilar(conexion, cliente, chat_id, ...)`:
  - PRE: unfinished matches with kickoff within 2.5 h and id not in state → fresh prediction → send analysis block.
  - POST: finished matches with id not in state → result message: final score, predicted score, ✅/❌ 1X2 (with the probability we gave the actual outcome) and exact score, cumulative hit rates and RPS blend-vs-market verdict. Matches without prior prediction degrade to result-only.
  - State `data/notificaciones.json` (`{"pre": [...], "post": [...]}`) committed by CI → idempotent across runs.
- `mundial vigilar` CLI command.
- `.github/workflows/vigilar.yml`: cron `*/30 13-23,0-4 * * *`; actualizar → ratings → vigilar; commits `data/predicciones` + `data/notificaciones.json` with pull-rebase (same pattern as snapshot.yml).
- `telegram.yml`: drop the 04:30 results cron (superseded by per-match messages); keep the 13:00 digest, whose window widens to [00:00, next-day 05:00 UTC) so late-night kickoffs appear in the morning digest too.
- `precision.evaluar` gains `partido_id` and `p_resultado` per match (additive).

**Tests:** score-merge from FIFA when fd is null · export/import JSONL idempotent · vigilar sends pre once (no resend on second run), post once with ✅/❌ and cumulative line, result-only when no prior prediction · digest window includes next-day 02:00 match.
