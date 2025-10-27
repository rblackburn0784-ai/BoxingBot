# boxing_bot/services/roster.py
from typing import Optional
import dataclasses
from typing import Optional, List
from ..storage.db import DB, save_db      # <-- relative
from ..models import Boxer, _norm_gender, get_weight_class

def save_boxer(b: Boxer):
    b.gender = _norm_gender(b.gender)
    b.weight_class = get_weight_class(b.weight_kg)
    DB["boxers"][b.name.lower()] = dataclasses.asdict(b)
    save_db(DB)

def get_boxer(name: str) -> Optional[Boxer]:
    b = DB["boxers"].get(name.lower())
    if not b: return None
    b.setdefault("intro",""); b.setdefault("intro_music",""); b.setdefault("trait","")
    b["gender"] = _norm_gender(b.get("gender","male"))
    b.setdefault("weight_kg", 66.7)
    b["weight_class"] = get_weight_class(b["weight_kg"])
    known = {f.name for f in dataclasses.fields(Boxer)}
    b = {k:v for k,v in b.items() if k in known}
    return Boxer(**b)

def list_boxers() -> List[str]:
    return sorted(DB["boxers"].keys())

def remove_boxer(name: str) -> bool:
    key = name.lower()
    if key in DB["boxers"]:
        del DB["boxers"][key]
        save_db(DB)
        return True
    return False
