from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

from ..models import Boxer
from ..storage import v2db
from .roster import get_boxer, list_boxers

XP_PER_FIGHT = 20
XP_WIN_BONUS = 15
XP_TOURNAMENT_WIN_BONUS = 10


def ensure_profile(boxer_name: str, guild_id: Optional[int] = None, owner_id: Optional[int] = None) -> None:
    with v2db.transaction() as con:
        con.execute(
            "INSERT OR IGNORE INTO boxer_profiles(boxer_name,guild_id,owner_id) VALUES(?,?,?)",
            (boxer_name, guild_id, owner_id),
        )
        if guild_id is not None or owner_id is not None:
            con.execute(
                "UPDATE boxer_profiles SET guild_id=COALESCE(guild_id,?), owner_id=COALESCE(owner_id,?), updated_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE",
                (guild_id, owner_id, boxer_name),
            )
        con.execute("INSERT OR IGNORE INTO career_stats(boxer_name) VALUES(?)", (boxer_name,))


def import_legacy_profiles() -> int:
    count = 0
    for name in list_boxers():
        before = v2db.one("SELECT boxer_name FROM boxer_profiles WHERE boxer_name=? COLLATE NOCASE", (name,))
        ensure_profile(name)
        if not before:
            count += 1
    return count



def competitive_legal(boxer_name: str) -> tuple[bool, str]:
    boxer = get_boxer(boxer_name)
    if not boxer:
        return False, "Boxer does not exist."
    stats = [getattr(boxer, s) for s in ("power","speed","accuracy","defense","footwork","stamina","chin","body")]
    if sum(stats) != 60:
        return False, f"Base stats total {sum(stats)}; V2 requires exactly 60."
    if any(v < 0 or v > 20 for v in stats):
        return False, "Every V2 base stat must be between 0 and 20."
    if boxer.max_hp() != 100:
        return False, "V2 competitive HP must be exactly 100."
    return True, ""

def get_owned_boxer(guild_id: int, owner_id: int) -> Optional[str]:
    row = v2db.one(
        "SELECT boxer_name FROM boxer_profiles WHERE guild_id=? AND owner_id=? AND retired=0",
        (guild_id, owner_id),
    )
    return row["boxer_name"] if row else None


def link_boxer(boxer_name: str, guild_id: int, owner_id: int, *, force: bool = False) -> None:
    ensure_profile(boxer_name)
    with v2db.transaction() as con:
        existing_owner = con.execute(
            "SELECT boxer_name FROM boxer_profiles WHERE guild_id=? AND owner_id=? AND retired=0",
            (guild_id, owner_id),
        ).fetchone()
        if existing_owner and existing_owner["boxer_name"].lower() != boxer_name.lower() and not force:
            raise ValueError("That Discord user already has a linked boxer.")
        target = con.execute(
            "SELECT owner_id FROM boxer_profiles WHERE boxer_name=? COLLATE NOCASE", (boxer_name,)
        ).fetchone()
        if target and target["owner_id"] is not None and int(target["owner_id"]) != owner_id and not force:
            raise ValueError("That boxer is already linked to another Discord user.")
        if force:
            con.execute("UPDATE boxer_profiles SET owner_id=NULL WHERE guild_id=? AND owner_id=?", (guild_id, owner_id))
        con.execute(
            "UPDATE boxer_profiles SET guild_id=?, owner_id=?, updated_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE",
            (guild_id, owner_id, boxer_name),
        )


def unlink_boxer(boxer_name: str) -> None:
    v2db.execute(
        "UPDATE boxer_profiles SET guild_id=NULL, owner_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE",
        (boxer_name,),
    )


def can_edit_boxer(boxer_name: str) -> tuple[bool, str]:
    row = v2db.one(
        """SELECT t.name FROM tournament_entries e
           JOIN tournaments t ON t.id=e.tournament_id
           WHERE e.boxer_name=? COLLATE NOCASE AND e.eliminated=0 AND t.status='active' LIMIT 1""",
        (boxer_name,),
    )
    if row:
        return False, f"Boxer is locked while competing in **{row['name']}**."
    return True, ""


def profile(boxer_name: str) -> dict:
    ensure_profile(boxer_name)
    p = v2db.one("SELECT * FROM boxer_profiles WHERE boxer_name=? COLLATE NOCASE", (boxer_name,))
    s = v2db.one("SELECT * FROM career_stats WHERE boxer_name=? COLLATE NOCASE", (boxer_name,))
    achievements = v2db.all_rows(
        "SELECT code,name,description,tournament_id,unlocked_at FROM achievements WHERE boxer_name=? COLLATE NOCASE ORDER BY unlocked_at DESC",
        (boxer_name,),
    )
    return {"profile": dict(p), "stats": dict(s), "achievements": [dict(a) for a in achievements]}


def leaderboard(limit: int = 20) -> list[dict]:
    rows = v2db.all_rows(
        """SELECT p.boxer_name,p.level,p.xp,p.title,s.*
           FROM boxer_profiles p JOIN career_stats s ON s.boxer_name=p.boxer_name
           WHERE p.retired=0
           ORDER BY s.tournament_titles DESC, s.wins DESC, s.losses ASC, s.fights DESC, p.boxer_name ASC LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def _level_for_xp(xp: int) -> int:
    # Prestige only: deliberately no combat-stat bonuses.
    return 1 + max(0, xp) // 100


def _unlock(con, boxer: str, code: str, name: str, desc: str, tournament_id: Optional[int] = None) -> bool:
    exists = con.execute(
        "SELECT 1 FROM achievements WHERE boxer_name=? COLLATE NOCASE AND code=? AND ((tournament_id IS NULL AND ? IS NULL) OR tournament_id=?) LIMIT 1",
        (boxer, code, tournament_id, tournament_id),
    ).fetchone()
    if exists:
        return False
    con.execute(
        "INSERT INTO achievements(boxer_name,code,name,description,tournament_id) VALUES(?,?,?,?,?)",
        (boxer, code, name, desc, tournament_id),
    )
    return True


def evaluate_achievements(con, boxer_name: str, tournament_id: Optional[int] = None) -> None:
    s = con.execute("SELECT * FROM career_stats WHERE boxer_name=? COLLATE NOCASE", (boxer_name,)).fetchone()
    if not s:
        return
    if s["fights"] >= 1:
        _unlock(con, boxer_name, "FIRST_BELL", "First Bell", "Complete your first recorded bout.")
    if s["wins"] >= 1:
        _unlock(con, boxer_name, "FIRST_WIN", "Hand Raised", "Win your first recorded bout.")
    if s["kos"] + s["tkos"] >= 1:
        _unlock(con, boxer_name, "FIRST_STOPPAGE", "Lights Out", "Earn your first KO/TKO victory.")
    if s["current_win_streak"] >= 3:
        _unlock(con, boxer_name, "STREAK_3", "On a Roll", "Win three consecutive bouts.")
    if s["fights"] >= 10:
        _unlock(con, boxer_name, "VETERAN_10", "Ten-Round Veteran", "Complete ten recorded bouts.")
    if s["tournament_titles"] >= 1 and tournament_id is not None:
        _unlock(con, boxer_name, "CHAMPION", "Tournament Champion", "Win a tournament title.", tournament_id)


def record_completed_fight(session, guild_id: Optional[int] = None, tournament_id: Optional[int] = None) -> Optional[int]:
    """Record a finished FightSession exactly once. Returns fight id or None if already recorded."""
    if not session.finished:
        return None
    red = session.red_raw.name
    blue = session.blue_raw.name
    ensure_profile(red)
    ensure_profile(blue)
    winner = session.winner
    loser = blue if winner and winner.lower() == red.lower() else red if winner else None
    result_type = session.winner_type or "Draw"
    events = []
    for item in session.log:
        if isinstance(item, dict) and isinstance(item.get("events"), list):
            events.extend(item["events"])
        elif isinstance(item, dict):
            events.append(item)
    red_damage = sum(int(e.get("damage", 0) or 0) for e in events if str(e.get("attacker", "")).lower() == red.lower())
    blue_damage = sum(int(e.get("damage", 0) or 0) for e in events if str(e.get("attacker", "")).lower() == blue.lower())
    # V1 FightSession kd_total tracks knockdowns suffered by corner.
    red_kd = int(session.kd_total.get("B", 0))
    blue_kd = int(session.kd_total.get("A", 0))
    fight_key = f"{session.channel_id}:{session.rng_seed}:{red.lower()}:{blue.lower()}"
    metadata = {"winner_corner": session.winner_corner, "log_entries": len(session.log)}

    with v2db.transaction() as con:
        exists = con.execute("SELECT id FROM fights WHERE fight_key=?", (fight_key,)).fetchone()
        if exists:
            return None
        cur = con.execute(
            """INSERT INTO fights(fight_key,guild_id,channel_id,tournament_id,red_name,blue_name,winner_name,loser_name,result_type,rounds,seed,red_damage,blue_damage,red_kd,blue_kd,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fight_key, guild_id, session.channel_id, tournament_id, red, blue, winner, loser, result_type,
             session.current_round, session.rng_seed, red_damage, blue_damage, red_kd, blue_kd, json.dumps(metadata)),
        )
        fight_id = int(cur.lastrowid)
        for name in (red, blue):
            con.execute("INSERT OR IGNORE INTO career_stats(boxer_name) VALUES(?)", (name,))
        draw = not winner
        for name, dmg_for, dmg_against, kd_for, kd_against in (
            (red, red_damage, blue_damage, red_kd, blue_kd),
            (blue, blue_damage, red_damage, blue_kd, red_kd),
        ):
            is_winner = bool(winner and winner.lower() == name.lower())
            is_loser = bool(winner and not is_winner)
            con.execute(
                """UPDATE career_stats SET fights=fights+1,
                   wins=wins+?, losses=losses+?, draws=draws+?,
                   kos=kos+?, tkos=tkos+?, points_wins=points_wins+?,
                   knockdowns_for=knockdowns_for+?, knockdowns_against=knockdowns_against+?,
                   damage_for=damage_for+?, damage_against=damage_against+?,
                   current_win_streak=CASE WHEN ? THEN current_win_streak+1 ELSE 0 END,
                   best_win_streak=CASE WHEN ? THEN MAX(best_win_streak,current_win_streak+1) ELSE best_win_streak END,
                   last_fight_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE""",
                (int(is_winner), int(is_loser), int(draw),
                 int(is_winner and result_type.upper() == "KO"), int(is_winner and result_type.upper() == "TKO"),
                 int(is_winner and result_type.lower() == "points"), kd_for, kd_against, dmg_for, dmg_against,
                 int(is_winner), int(is_winner), name),
            )
            earned = XP_PER_FIGHT + (XP_WIN_BONUS if is_winner else 0) + (XP_TOURNAMENT_WIN_BONUS if is_winner and tournament_id else 0)
            con.execute(
                "UPDATE boxer_profiles SET xp=xp+?, level=?, updated_at=CURRENT_TIMESTAMP WHERE boxer_name=? COLLATE NOCASE",
                (earned, 1, name),
            )
            xp_row = con.execute("SELECT xp FROM boxer_profiles WHERE boxer_name=? COLLATE NOCASE", (name,)).fetchone()
            con.execute("UPDATE boxer_profiles SET level=? WHERE boxer_name=? COLLATE NOCASE", (_level_for_xp(xp_row["xp"]), name))
            evaluate_achievements(con, name, tournament_id)
    return fight_id


def finalize_session(session, guild_id: Optional[int] = None) -> Optional[int]:
    """Persist a V1.9 fight into the V2 career layer and advance any matching tournament/challenge."""
    from . import tournaments
    tournament_id = None
    if guild_id is not None:
        t = tournaments.active_tournament(guild_id)
        if t and t["status"] == "active" and tournaments.match_for_pair(t["id"], session.red_raw.name, session.blue_raw.name):
            tournament_id = int(t["id"])
    fight_id = record_completed_fight(session, guild_id=guild_id, tournament_id=tournament_id)
    if fight_id is None:
        return None
    if tournament_id and session.winner:
        tournaments.record_result(tournament_id, session.red_raw.name, session.blue_raw.name, session.winner, fight_id)
    if guild_id is not None:
        # Complete an accepted grudge challenge if this pair matches one.
        ch = v2db.one(
            """SELECT id FROM challenges WHERE guild_id=? AND status='accepted' AND
               ((challenger_name=? COLLATE NOCASE AND challenged_name=? COLLATE NOCASE) OR
                (challenger_name=? COLLATE NOCASE AND challenged_name=? COLLATE NOCASE))
               ORDER BY id LIMIT 1""",
            (guild_id, session.red_raw.name, session.blue_raw.name, session.blue_raw.name, session.red_raw.name),
        )
        if ch:
            v2db.execute("UPDATE challenges SET status='complete',completed_at=CURRENT_TIMESTAMP WHERE id=?", (ch["id"],))
    return fight_id


def head_to_head(a: str, b: str) -> dict:
    rows = v2db.all_rows(
        """SELECT * FROM fights WHERE
           (red_name=? COLLATE NOCASE AND blue_name=? COLLATE NOCASE) OR
           (red_name=? COLLATE NOCASE AND blue_name=? COLLATE NOCASE)
           ORDER BY id""",
        (a,b,b,a),
    )
    out = {"fights": len(rows), "a_wins": 0, "b_wins": 0, "draws": 0, "last": None}
    for r in rows:
        if not r["winner_name"]: out["draws"] += 1
        elif r["winner_name"].lower() == a.lower(): out["a_wins"] += 1
        elif r["winner_name"].lower() == b.lower(): out["b_wins"] += 1
        out["last"] = dict(r)
    return out


def competition_boxer(guild_id: Optional[int], boxer_name: str) -> Optional[Boxer]:
    """Return the tournament-locked build when applicable, otherwise the live roster boxer."""
    boxer = get_boxer(boxer_name)
    if not boxer or guild_id is None:
        return boxer
    row = v2db.one(
        """SELECT e.stat_snapshot_json FROM tournament_entries e
           JOIN tournaments t ON t.id=e.tournament_id
           WHERE t.guild_id=? AND t.status='active' AND e.boxer_name=? COLLATE NOCASE AND e.eliminated=0
           ORDER BY t.id DESC LIMIT 1""",
        (guild_id, boxer_name),
    )
    if not row:
        return boxer
    try:
        snap = json.loads(row["stat_snapshot_json"] or "{}")
    except Exception:
        return boxer
    values = {field: getattr(boxer, field) for field in Boxer.__dataclass_fields__}
    for key in ("power","speed","accuracy","defense","footwork","stamina","chin","body","trait","weight_kg","weight_class"):
        if key in snap:
            values[key] = snap[key]
    return Boxer(**values)


def unlock_achievement(boxer_name: str, code: str, name: str, description: str, tournament_id: Optional[int] = None) -> bool:
    ensure_profile(boxer_name)
    with v2db.transaction() as con:
        return _unlock(con, boxer_name, code, name, description, tournament_id)
