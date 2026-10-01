from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from ..config import ROOT_DIR

DB_PATH = ROOT_DIR / "boxing_v2.sqlite3"
_LOCK = threading.RLock()

SCHEMA = r'''
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS boxer_profiles (
    boxer_name TEXT PRIMARY KEY COLLATE NOCASE,
    guild_id INTEGER,
    owner_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    prestige INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    retired INTEGER NOT NULL DEFAULT 0,
    UNIQUE(guild_id, owner_id)
);

CREATE TABLE IF NOT EXISTS career_stats (
    boxer_name TEXT PRIMARY KEY COLLATE NOCASE REFERENCES boxer_profiles(boxer_name) ON DELETE CASCADE,
    fights INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    kos INTEGER NOT NULL DEFAULT 0,
    tkos INTEGER NOT NULL DEFAULT 0,
    points_wins INTEGER NOT NULL DEFAULT 0,
    knockdowns_for INTEGER NOT NULL DEFAULT 0,
    knockdowns_against INTEGER NOT NULL DEFAULT 0,
    damage_for INTEGER NOT NULL DEFAULT 0,
    damage_against INTEGER NOT NULL DEFAULT 0,
    current_win_streak INTEGER NOT NULL DEFAULT 0,
    best_win_streak INTEGER NOT NULL DEFAULT 0,
    tournament_entries INTEGER NOT NULL DEFAULT 0,
    tournament_titles INTEGER NOT NULL DEFAULT 0,
    tournament_runner_ups INTEGER NOT NULL DEFAULT 0,
    last_fight_at TEXT
);

CREATE TABLE IF NOT EXISTS fights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_key TEXT NOT NULL UNIQUE,
    guild_id INTEGER,
    channel_id INTEGER,
    tournament_id INTEGER,
    red_name TEXT NOT NULL,
    blue_name TEXT NOT NULL,
    winner_name TEXT,
    loser_name TEXT,
    result_type TEXT NOT NULL,
    rounds INTEGER NOT NULL DEFAULT 0,
    seed INTEGER,
    red_damage INTEGER NOT NULL DEFAULT 0,
    blue_damage INTEGER NOT NULL DEFAULT 0,
    red_kd INTEGER NOT NULL DEFAULT 0,
    blue_kd INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    fought_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fights_red ON fights(red_name);
CREATE INDEX IF NOT EXISTS idx_fights_blue ON fights(blue_name);
CREATE INDEX IF NOT EXISTS idx_fights_tournament ON fights(tournament_id);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boxer_name TEXT NOT NULL COLLATE NOCASE REFERENCES boxer_profiles(boxer_name) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    tournament_id INTEGER,
    unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(boxer_name, code, tournament_id)
);

CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    name TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'single_elimination',
    status TEXT NOT NULL DEFAULT 'registration',
    created_by INTEGER,
    max_entries INTEGER NOT NULL DEFAULT 16,
    current_round INTEGER NOT NULL DEFAULT 0,
    champion_name TEXT,
    runner_up_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tournament_entries (
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    boxer_name TEXT NOT NULL COLLATE NOCASE REFERENCES boxer_profiles(boxer_name) ON DELETE CASCADE,
    seed INTEGER,
    eliminated INTEGER NOT NULL DEFAULT 0,
    final_place INTEGER,
    entered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stat_snapshot_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(tournament_id, boxer_name)
);

CREATE TABLE IF NOT EXISTS tournament_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL,
    slot_no INTEGER NOT NULL,
    red_name TEXT COLLATE NOCASE,
    blue_name TEXT COLLATE NOCASE,
    winner_name TEXT COLLATE NOCASE,
    fight_id INTEGER REFERENCES fights(id),
    status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(tournament_id, round_no, slot_no)
);

CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    challenger_name TEXT NOT NULL COLLATE NOCASE REFERENCES boxer_profiles(boxer_name) ON DELETE CASCADE,
    challenged_name TEXT NOT NULL COLLATE NOCASE REFERENCES boxer_profiles(boxer_name) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    accepted_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def init_db() -> None:
    with _LOCK, connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','2.0')")


@contextmanager
def transaction():
    with _LOCK:
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    with _LOCK, connect() as con:
        return con.execute(sql, tuple(params)).fetchone()


def all_rows(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _LOCK, connect() as con:
        return list(con.execute(sql, tuple(params)).fetchall())


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with _LOCK, connect() as con:
        cur = con.execute(sql, tuple(params))
        return cur.lastrowid


def audit(guild_id: Optional[int], actor_id: Optional[int], action: str, target: str = "", details: Optional[dict] = None) -> None:
    execute(
        "INSERT INTO audit_log(guild_id,actor_id,action,target,details_json) VALUES(?,?,?,?,?)",
        (guild_id, actor_id, action, target, json.dumps(details or {}, ensure_ascii=False)),
    )


def backup_database(retain: int = 20) -> Optional[Path]:
    """Create a consistent SQLite backup. Safe while WAL mode is active."""
    if not DB_PATH.exists():
        return None
    import datetime
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = backup_dir / f"boxing_v2-{stamp}.sqlite3"
    with _LOCK:
        src = connect()
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
    backups = sorted(backup_dir.glob("boxing_v2-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, retain):]:
        try: old.unlink()
        except OSError: pass
    return out
