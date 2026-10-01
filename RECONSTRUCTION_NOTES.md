# Boxing Bot — reconstructed latest build

Reconstructed on 2026-09-30 from the uploaded `Boxing_Bot_Final - Copy.zip`, using the later Boxing Bot project decisions and bug reports as the source of truth where they were recoverable.

## Confirmed later fixes restored

- **Points decisions no longer run backwards.** `_round_stats()` now credits damage and knockdowns to the attacker who dealt/scored them rather than the defender who received them.
- **10-point-must KD handling updated for the corrected KD meaning.** A KD scored by the round winner now reduces the opponent's score (one KD -> 10-8; two or more -> 10-7), while the existing dominant-damage 10-8 rule remains.
- **Judge direction fix.** `_score_round()` uses `diff = dmgA - dmgB` and the corrected judge-bias direction recovered from the 2025-12-23 fix.
- **`/resolve_test Points` NameError fixed.** `compute_scorecards` is imported by `cogs/match.py`.
- **`/resolve_test KO/TKO` runtime call fixed.** The `FightSession` argument is now supplied to `send_finish_announcement()`.
- **Commentary cutoff fix.** `play_clip()` supports natural-length playback (`seconds=None`); commentary/murmur bites use it and do not interrupt an already-playing voice clip.
- **Low-blow point deductions made round-specific.** The event already records `point_deduction=True` from warning #3 onward; scoring now applies that deduction only to the round containing that event rather than every round once cumulative warnings reach 3.
- **Google Sheet importer runtime fix.** `services/sheets.py` now imports `_weight_kg_from_class`, which it called but did not define/import in the uploaded snapshot.
- **Dependencies completed.** Added packages required by the source's existing Discord voice, Pillow promo composition, HTTP, and Google Sheets features.

## Rules deliberately retained

- Knockdown detection: damage >= 14, or an unblocked natural 20.
- Damage TKO: `(HP <= 10 and round damage >= 20) or HP <= 5`.
- Default 3-KD rule remains `per_round`, limit 3.
- Three judges remain TheDude, Walter Sobchak and Donny Kerabatsos.
- Near-even rounds retain the small seeded/random judge-bias behaviour already in the project.
- Boxer database and media from the uploaded package are retained unchanged except for generated/cache/IDE/private environment files and font binaries.

## Distribution cleanup

The reconstructed ZIP intentionally omits `.venv`, IDE folders, `__pycache__`, and the uploaded `.env`. Use `.env.example` to create a fresh local `.env` and insert your Discord token locally.

## Verification performed

- `python -m compileall` succeeds for the reconstructed source.
- Static unresolved-global scan reports no unresolved globals in project Python files.
- All `send_finish_announcement()` calls in `match.py` match its 8-argument signature.
- Both JSON database files parse successfully.
- `tests/regression_core.py` passes checks covering scoring direction, KD 10-point-must scoring, round-specific foul deductions, and TKO thresholds.

## Limits of reconstruction

This is a best-evidence reconstruction of the latest Boxing Bot code from the uploaded snapshot plus recoverable project history. Later poster artwork and manual scorecard images were content outputs, not code patches, so they are not synthesised into the bot source. Where a later conversation discussed an idea without a confirmed implementation, the behaviour was not silently invented.
