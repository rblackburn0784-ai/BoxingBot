from __future__ import annotations
import asyncio, json, random, os, time
from dataclasses import asdict
from typing import Dict
from ..models import Boxer, FighterState, FightSession
from ..config import SETTINGS

SESSIONS: Dict[int, FightSession] = {}
_LOCKS: Dict[int, asyncio.Lock] = {}

def get_fight_lock(channel_id: int) -> asyncio.Lock:
    return _LOCKS.setdefault(int(channel_id), asyncio.Lock())

def _boxer(d: dict) -> Boxer:
    return Boxer(**d)

def session_to_dict(s: FightSession) -> dict:
    return {
        "channel_id": s.channel_id, "rng_seed": s.rng_seed,
        "rng_state": repr(s.rng.getstate()),
        "red_raw": asdict(s.red_raw), "blue_raw": asdict(s.blue_raw),
        "red_eff": asdict(s.red_eff), "blue_eff": asdict(s.blue_eff),
        "A": asdict(s.A), "B": asdict(s.B),
        "kd_rule": s.kd_rule, "kd_limit": s.kd_limit, "kd_round": s.kd_round, "kd_total": s.kd_total,
        "current_round": s.current_round, "exchanges_per_round": s.exchanges_per_round,
        "finished": s.finished, "winner": s.winner, "winner_corner": s.winner_corner, "winner_type": s.winner_type,
        "log": s.log, "crowd_log": s.crowd_log, "momentum": s.momentum, "crowd_hype": s.crowd_hype,
        "judge_cards": getattr(s, "judge_cards", None),
    }

def session_from_dict(d: dict) -> FightSession:
    seed=d.get("rng_seed")
    rng=random.Random(seed)
    state=d.get("rng_state")
    if state:
        try:
            import ast; rng.setstate(ast.literal_eval(state))
        except Exception: pass
    red_raw=_boxer(d["red_raw"]); blue_raw=_boxer(d["blue_raw"]); red_eff=_boxer(d["red_eff"]); blue_eff=_boxer(d["blue_eff"])
    def fighter(fd, boxer):
        x=dict(fd); x.pop("boxer", None); return FighterState(boxer=boxer, **x)
    s=FightSession(channel_id=int(d["channel_id"]), rng_seed=seed, rng=rng, red_raw=red_raw, blue_raw=blue_raw, red_eff=red_eff, blue_eff=blue_eff, A=fighter(d["A"],red_eff), B=fighter(d["B"],blue_eff), kd_rule=d.get("kd_rule","per_round"), kd_limit=int(d.get("kd_limit",3)))
    for k in ("kd_round","kd_total","log","crowd_log"):
        if k in d: setattr(s,k,d[k])
    for k in ("current_round","exchanges_per_round","momentum","crowd_hype"):
        if k in d: setattr(s,k,int(d[k]))
    for k in ("finished","winner","winner_corner","winner_type"):
        if k in d: setattr(s,k,d.get(k))
    if d.get("judge_cards") is not None: s.judge_cards=d["judge_cards"]
    return s

def save_sessions() -> None:
    path=SETTINGS.FIGHT_STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp=f"{path}.tmp.{os.getpid()}.{time.time_ns()}"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump({str(k):session_to_dict(v) for k,v in SESSIONS.items()},f,indent=2,ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def load_sessions() -> int:
    path=SETTINGS.FIGHT_STATE_FILE
    if not os.path.exists(path): return 0
    try:
        with open(path,"r",encoding="utf-8") as f: raw=json.load(f)
        SESSIONS.clear()
        for k,v in raw.items(): SESSIONS[int(k)]=session_from_dict(v)
        return len(SESSIONS)
    except Exception as exc:
        stamp=time.strftime("%Y%m%d-%H%M%S")
        try: os.replace(path, f"{path}.corrupt-{stamp}.bak")
        except OSError: pass
        print(f"[state] Could not restore fight sessions: {exc}")
        return 0

def delete_session(channel_id: int) -> None:
    SESSIONS.pop(int(channel_id), None); save_sessions()

def debug_sessions(): return {k: str(v) for k,v in SESSIONS.items()}
