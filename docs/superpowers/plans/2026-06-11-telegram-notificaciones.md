# Telegram — Notification Layer

**Goal:** A Telegram bot DMs the user the day's predictions and yesterday's results/accuracy, automatically via GitHub Actions (works with the Mac off) and on demand via `mundial telegram`.

**Design:**
- `notificaciones/telegram.py`: `ClienteTelegram(token, transporte)` with `enviar(chat_id, texto)` (HTML, chunked at 4,000 chars on line boundaries — Telegram hard limit is 4,096) and `obtener_chat_id()` (reads `getUpdates`, returns the most recent chat). `armar_resumen(conexion, fecha=None, cliente_bsd=None)`: today's matches each freshly predicted (predecir wrapped in try/except — a failing match degrades to a line, never kills the digest), yesterday's finished matches with ✅/❌ vs the last pre-kickoff prediction, and the aggregate Brier/RPS table when available. Returns None when there is nothing to send.
- CLI `mundial telegram [--configurar]`: `--configurar` auto-detects the chat_id after the user messages the bot; default mode builds + sends the digest.
- `.github/workflows/telegram.yml`: cron `0 13 * * *` (pre-match digest; earliest WC kickoffs ~15-16 UTC) and `30 4 * * *` (post-matchday results; last matches end ~03 UTC). Steps: actualizar → ratings → telegram. Needs secrets: `FOOTBALL_DATA_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (BSD/Odds keys already set).
- Scope note: CI predictions live only in the runner's DB — the Telegram workflow is a *notification* layer; audit-grade prediction history accumulates wherever the CLI runs persistently (the Mac). Documented TODO: export CI predictions as committed JSON if needed later.

**User actions required (no card, 2 min):** create bot via @BotFather → token to `.env` as `TELEGRAM_BOT_TOKEN`; send any message to the bot; run `uv run mundial telegram --configurar` → chat_id to `.env` as `TELEGRAM_CHAT_ID`; then `gh secret set` both.

**Tests:** chunking respects limit and line boundaries; `enviar` posts correct payload/parse_mode and chunks long texts; `obtener_chat_id` parses getUpdates; `armar_resumen` with seeded DB contains match header, 1X2 line and yesterday's ✅/❌; returns None on empty day.
