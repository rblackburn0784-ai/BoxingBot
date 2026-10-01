from __future__ import annotations

import json
import math
import random
from typing import Optional

from ..storage import v2db
from .game import ensure_profile, evaluate_achievements, competitive_legal, unlock_achievement
from .roster import get_boxer


def create_tournament(guild_id: int, name: str, created_by: int, max_entries: int = 16) -> int:
    if max_entries < 2 or max_entries > 64:
        raise ValueError("Tournament size must be between 2 and 64.")
    return v2db.execute(
        "INSERT INTO tournaments(guild_id,name,created_by,max_entries) VALUES(?,?,?,?)",
        (guild_id, name.strip(), created_by, max_entries),
    )


def active_tournament(guild_id: int):
    return v2db.one(
        "SELECT * FROM tournaments WHERE guild_id=? AND status IN ('registration','active') ORDER BY id DESC LIMIT 1",
        (guild_id,),
    )


def tournament(tournament_id: int):
    return v2db.one("SELECT * FROM tournaments WHERE id=?", (tournament_id,))


def list_tournaments(guild_id: int, limit: int = 20):
    return v2db.all_rows("SELECT * FROM tournaments WHERE guild_id=? ORDER BY id DESC LIMIT ?", (guild_id, limit))


def entries(tournament_id: int):
    return v2db.all_rows(
        "SELECT * FROM tournament_entries WHERE tournament_id=? ORDER BY COALESCE(seed,9999), boxer_name",
        (tournament_id,),
    )


def register(tournament_id: int, boxer_name: str) -> None:
    t = tournament(tournament_id)
    if not t or t["status"] != "registration":
        raise ValueError("Tournament registration is not open.")
    boxer = get_boxer(boxer_name)
    if not boxer:
        raise ValueError("Boxer does not exist.")
    legal, reason = competitive_legal(boxer_name)
    if not legal:
        raise ValueError(f"Boxer is not V2 competition-legal: {reason}")
    count = v2db.one("SELECT COUNT(*) AS n FROM tournament_entries WHERE tournament_id=?", (tournament_id,))["n"]
    if count >= t["max_entries"]:
        raise ValueError("Tournament is full.")
    ensure_profile(boxer_name)
    snapshot = {k: getattr(boxer, k) for k in ("power","speed","accuracy","defense","footwork","stamina","chin","body","trait","weight_kg","weight_class")}
    with v2db.transaction() as con:
        con.execute(
            "INSERT INTO tournament_entries(tournament_id,boxer_name,stat_snapshot_json) VALUES(?,?,?)",
            (tournament_id, boxer_name, json.dumps(snapshot)),
        )


def unregister(tournament_id: int, boxer_name: str) -> None:
    t = tournament(tournament_id)
    if not t or t["status"] != "registration":
        raise ValueError("Registration is closed.")
    v2db.execute("DELETE FROM tournament_entries WHERE tournament_id=? AND boxer_name=? COLLATE NOCASE", (tournament_id, boxer_name))


def _next_power_of_two(n: int) -> int:
    return 1 << (n - 1).bit_length()


def start(tournament_id: int, seed: Optional[int] = None) -> None:
    t = tournament(tournament_id)
    if not t or t["status"] != "registration":
        raise ValueError("Tournament is not awaiting a start.")
    ent = [dict(r) for r in entries(tournament_id)]
    if len(ent) < 2:
        raise ValueError("At least two boxers are required.")
    rng = random.Random(seed if seed is not None else tournament_id)
    rng.shuffle(ent)
    with v2db.transaction() as con:
        for i, e in enumerate(ent, 1):
            con.execute("UPDATE tournament_entries SET seed=? WHERE tournament_id=? AND boxer_name=? COLLATE NOCASE", (i, tournament_id, e["boxer_name"]))
            con.execute("UPDATE career_stats SET tournament_entries=tournament_entries+1 WHERE boxer_name=? COLLATE NOCASE", (e["boxer_name"],))
        con.execute("UPDATE tournaments SET status='active',current_round=1,started_at=CURRENT_TIMESTAMP WHERE id=?", (tournament_id,))
        # Pair sequentially. Odd entrant receives a bye and is automatically advanced when the round closes.
        slot = 1
        for i in range(0, len(ent), 2):
            red = ent[i]["boxer_name"]
            blue = ent[i+1]["boxer_name"] if i+1 < len(ent) else None
            con.execute(
                "INSERT INTO tournament_matches(tournament_id,round_no,slot_no,red_name,blue_name,status,winner_name) VALUES(?,?,?,?,?,?,?)",
                (tournament_id, 1, slot, red, blue, "complete" if blue is None else "pending", red if blue is None else None),
            )
            slot += 1
    for e in ent:
        unlock_achievement(e["boxer_name"], "TOURNAMENT_ENTRY", "Tournament Contender", f"Enter {t['name']}.", tournament_id)
    _advance_if_round_complete(tournament_id)


def pending_matches(tournament_id: int):
    return v2db.all_rows(
        "SELECT * FROM tournament_matches WHERE tournament_id=? AND status='pending' ORDER BY round_no,slot_no",
        (tournament_id,),
    )


def current_round_matches(tournament_id: int):
    t = tournament(tournament_id)
    if not t:
        return []
    return v2db.all_rows(
        "SELECT * FROM tournament_matches WHERE tournament_id=? AND round_no=? ORDER BY slot_no",
        (tournament_id, t["current_round"]),
    )


def match_for_pair(tournament_id: int, a: str, b: str):
    return v2db.one(
        """SELECT * FROM tournament_matches WHERE tournament_id=? AND status='pending' AND
           ((red_name=? COLLATE NOCASE AND blue_name=? COLLATE NOCASE) OR (red_name=? COLLATE NOCASE AND blue_name=? COLLATE NOCASE))
           ORDER BY round_no,slot_no LIMIT 1""",
        (tournament_id, a, b, b, a),
    )


def record_result(tournament_id: int, red: str, blue: str, winner: str, fight_id: int) -> bool:
    m = match_for_pair(tournament_id, red, blue)
    if not m:
        return False
    loser = blue if winner.lower() == red.lower() else red
    with v2db.transaction() as con:
        con.execute(
            "UPDATE tournament_matches SET status='complete',winner_name=?,fight_id=? WHERE id=?",
            (winner, fight_id, m["id"]),
        )
        con.execute(
            "UPDATE tournament_entries SET eliminated=1 WHERE tournament_id=? AND boxer_name=? COLLATE NOCASE",
            (tournament_id, loser),
        )
    _advance_if_round_complete(tournament_id)
    return True


def _advance_if_round_complete(tournament_id: int) -> None:
    t = tournament(tournament_id)
    if not t or t["status"] != "active":
        return
    rnd = int(t["current_round"])
    matches = v2db.all_rows(
        "SELECT * FROM tournament_matches WHERE tournament_id=? AND round_no=? ORDER BY slot_no",
        (tournament_id, rnd),
    )
    if not matches or any(m["status"] != "complete" for m in matches):
        return
    winners = [m["winner_name"] for m in matches if m["winner_name"]]
    if len(winners) == 1:
        champion = winners[0]
        runner = None
        if len(matches) == 1:
            m = matches[0]
            runner = m["blue_name"] if champion.lower() == (m["red_name"] or "").lower() else m["red_name"]
        with v2db.transaction() as con:
            con.execute(
                "UPDATE tournaments SET status='complete',champion_name=?,runner_up_name=?,completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (champion, runner, tournament_id),
            )
            con.execute("UPDATE tournament_entries SET final_place=1 WHERE tournament_id=? AND boxer_name=? COLLATE NOCASE", (tournament_id, champion))
            con.execute("UPDATE career_stats SET tournament_titles=tournament_titles+1 WHERE boxer_name=? COLLATE NOCASE", (champion,))
            con.execute("UPDATE boxer_profiles SET title=?, prestige=prestige+1, updated_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE", (f"Champion of {t['name']}", champion))
            if runner:
                con.execute("UPDATE tournament_entries SET final_place=2 WHERE tournament_id=? AND boxer_name=? COLLATE NOCASE", (tournament_id, runner))
                con.execute("UPDATE career_stats SET tournament_runner_ups=tournament_runner_ups+1 WHERE boxer_name=? COLLATE NOCASE", (runner,))
            evaluate_achievements(con, champion, tournament_id)
        unlock_achievement(champion, "TOURNAMENT_FINALIST", "Tournament Finalist", f"Reach the final of {t['name']}.", tournament_id)
        if runner:
            unlock_achievement(runner, "TOURNAMENT_FINALIST", "Tournament Finalist", f"Reach the final of {t['name']}.", tournament_id)
        return
    next_round = rnd + 1
    with v2db.transaction() as con:
        con.execute("UPDATE tournaments SET current_round=? WHERE id=?", (next_round, tournament_id))
        slot = 1
        for i in range(0, len(winners), 2):
            red = winners[i]
            blue = winners[i+1] if i+1 < len(winners) else None
            con.execute(
                "INSERT OR IGNORE INTO tournament_matches(tournament_id,round_no,slot_no,red_name,blue_name,status,winner_name) VALUES(?,?,?,?,?,?,?)",
                (tournament_id, next_round, slot, red, blue, "complete" if blue is None else "pending", red if blue is None else None),
            )
            slot += 1
    _advance_if_round_complete(tournament_id)


def standings(tournament_id: int):
    return v2db.all_rows(
        """SELECT e.*,s.wins,s.losses,s.draws,s.kos,s.tkos FROM tournament_entries e
           LEFT JOIN career_stats s ON s.boxer_name=e.boxer_name
           WHERE e.tournament_id=? ORDER BY e.eliminated ASC, COALESCE(e.final_place,999), e.seed""",
        (tournament_id,),
    )


def tournament_report(tournament_id: int) -> dict:
    fights = v2db.all_rows("SELECT * FROM fights WHERE tournament_id=? ORDER BY id", (tournament_id,))
    report = {
        "bouts": len(fights), "ko": 0, "tko": 0, "points": 0, "draws": 0,
        "knockdowns": 0, "damage": 0, "fighters": {},
    }
    for f in fights:
        rt = (f["result_type"] or "").lower()
        if rt == "ko": report["ko"] += 1
        elif rt == "tko": report["tko"] += 1
        elif rt == "points": report["points"] += 1
        if not f["winner_name"]: report["draws"] += 1
        report["knockdowns"] += int(f["red_kd"] or 0) + int(f["blue_kd"] or 0)
        report["damage"] += int(f["red_damage"] or 0) + int(f["blue_damage"] or 0)
        for name, dmg, kd in ((f["red_name"], f["red_damage"], f["red_kd"]), (f["blue_name"], f["blue_damage"], f["blue_kd"])):
            d = report["fighters"].setdefault(name, {"fights":0,"wins":0,"losses":0,"draws":0,"damage":0,"kd":0,"stoppages":0})
            d["fights"] += 1; d["damage"] += int(dmg or 0); d["kd"] += int(kd or 0)
            if not f["winner_name"]: d["draws"] += 1
            elif f["winner_name"].lower() == name.lower():
                d["wins"] += 1
                if rt in {"ko","tko"}: d["stoppages"] += 1
            else: d["losses"] += 1
    return report


def tournament_awards(tournament_id: int) -> list[tuple[str, str, int]]:
    report = tournament_report(tournament_id)
    fighters = report["fighters"]
    if not fighters:
        return []
    awards = []
    for label, key in (("💥 Most Knockdowns","kd"),("🔥 Most Damage","damage"),("🛑 Most Stoppages","stoppages")):
        top = max(v[key] for v in fighters.values())
        if top <= 0:
            continue
        winners = ", ".join(sorted(n for n,v in fighters.items() if v[key] == top))
        awards.append((label, winners, top))
    return awards
