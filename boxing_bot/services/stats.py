# boxing_bot/services/stats.py
from ..models import Boxer, WEIGHT_CLASS_MODIFIERS
from ..config import SETTINGS

def normalize_modifiers(mods: dict) -> dict:
    m = dict(mods)
    if "defence" in m and "defense" not in m: m["defense"] = m.pop("defence")
    def pos_sum(d): return sum(v for v in d.values() if v > 0)
    while pos_sum(m) > SETTINGS.MAX_TOTAL_BONUS:
        biggest = max((k for k in m if m[k] > 0), key=lambda k: m[k], default=None)
        if biggest is None: break
        m[biggest] -= 1
    return m

def apply_weight_modifiers(base_stats: dict, weight_class: str) -> dict:
    raw = WEIGHT_CLASS_MODIFIERS.get(weight_class, {})
    mods = normalize_modifiers(raw)
    out = base_stats.copy()
    for stat, change in mods.items():
        if stat in out:
            out[stat] = max(SETTINGS.MIN_PER_STAT, min(SETTINGS.MAX_PER_STAT, out.get(stat, 0) + change))
    return out

def effective_boxer(b: Boxer) -> Boxer:
    base = {k: getattr(b, k) for k in ("power","speed","accuracy","defense","footwork","stamina","chin","body")}
    mods = apply_weight_modifiers(base, b.weight_class)
    return Boxer(
        name=b.name, intro=b.intro, intro_music=b.intro_music, gender=b.gender,
        weight_kg=b.weight_kg, weight_class=b.weight_class, trait=b.trait,
        power=mods["power"], speed=mods["speed"], accuracy=mods["accuracy"], defense=mods["defense"],
        footwork=mods["footwork"], stamina=mods["stamina"], chin=mods["chin"], body=mods["body"],
    )
