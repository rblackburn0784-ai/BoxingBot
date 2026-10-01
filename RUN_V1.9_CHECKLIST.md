# First local run checklist

1. Create a fresh virtual environment using Python 3.13 (or your established supported Python version).
2. `pip install -r Requirements.txt`
3. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
4. Ensure FFmpeg is on PATH, or set `FFMPEG_PATH` in `.env`.
5. Start with `python -m boxing_bot.bot` from the project root.
6. Confirm `/check_ffmpeg` reports the same FFmpeg executable used by playback.
7. In a private Discord test channel, run: `/start` -> `/fight` -> `/next_round`.
8. Restart the bot mid-fight and confirm the same fight resumes from `fight_sessions.json`.
9. Test a points fight and call/display the decision twice; judge cards should remain identical.
10. Test boxer creation wizard and a roster larger than 25 entries to verify pagination.
