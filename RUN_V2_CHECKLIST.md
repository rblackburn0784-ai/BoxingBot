# BoxingBot V2.0 — First Live Run Checklist

1. Install Python 3.13 (or the same supported Python used by your bot host).
2. Create a fresh virtual environment; do not reuse the old archived `.venv`.
3. Install `Requirements.txt`.
4. Copy `.env.example` to `.env` and set the Discord token.
5. Confirm FFmpeg resolves (`FFMPEG_PATH` can override autodetection).
6. Start with `python run_bot.py`.
7. Confirm startup reports the V2 SQLite database ready and imported legacy boxer profiles.
8. In Discord run `/menu` as a normal user and create/link a test boxer.
9. As admin open `/menu` → Admin Centre → Bot Settings → Diagnostics; SQLite should report `ok`.
10. Run a test grudge fight and verify `/career` increments exactly once.
11. Create a two-boxer tournament, start it, run the bout, and verify the tournament completes with a champion.
12. Restart the bot and confirm career/tournament data remains present.

Note: missing optional GIF/judge fallback assets from the recovered V1 source continue to degrade gracefully; they do not affect career/tournament persistence.
