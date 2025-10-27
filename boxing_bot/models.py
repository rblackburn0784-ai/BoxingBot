from dataclasses import dataclass, field
from typing import Optional, Dict, List

STAT_NAMES = ["power","speed","accuracy","defense","footwork","stamina","chin","body"]

# boxing_bot/models.py
def _weight_kg_from_class(weight_class: str) -> float:
    """
    Rough mapping from boxing weight classes to an approximate midpoint kg value.
    """
    mapping = {
        "flyweight": 50.8,
        "bantamweight": 53.5,
        "featherweight": 57.2,
        "lightweight": 61.2,
        "welterweight": 66.7,
        "middleweight": 72.6,
        "light heavyweight": 79.4,
        "cruiserweight": 90.7,
        "heavyweight": 100.0,
    }
    if not weight_class:
        return 66.7  # default middle
    key = weight_class.lower()
    for k, v in mapping.items():
        if k in key:
            return v
    return 66.7


def _norm_gender(g: Optional[str]) -> str:
    if not g: return "male"
    g = g.strip().lower()
    if g in ("m","male","man"): return "male"
    if g in ("f","female","woman"): return "female"
    return "male"

def gender_badge(g: str) -> str:
    return "♂️" if g == "male" else "♀️"

@dataclass
class Boxer:
    name: str
    power: int; speed: int; accuracy: int; defense: int
    footwork: int; stamina: int; chin: int; body: int
    intro: str = ""; intro_music: str = ""; gender: str = "male"
    weight_kg: float = 66.7; weight_class: str = "welterweight"; trait: str = ""
    def total_points(self) -> int:
        return sum(getattr(self, s) for s in STAT_NAMES)
    def max_hp(self) -> int: return 100

def get_weight_class(weight_kg: float) -> str:
    if weight_kg <= 51.0:  return "flyweight"
    if weight_kg <= 53.5:  return "bantamweight"
    if weight_kg <= 57.2:  return "featherweight"
    if weight_kg <= 66.7:  return "welterweight"
    if weight_kg <= 72.6:  return "middleweight"
    return "heavyweight"

WEIGHT_CLASS_MODIFIERS: Dict[str, Dict[str, int]] = {
    "flyweight":   {"speed": +3, "stamina": +2, "power": -2, "defence": +1, "footwork": +3, "body": -2},
    "bantamweight":{"speed": +2, "stamina": +1, "power": -1, "accuracy": +1, "footwork": +2, "body": -1},
    "featherweight":{"speed": +1, "power": 0, "stamina": +1, "defence": 0, "footwork": +1, "body": 0},
    "welterweight":{"speed": 0, "stamina": 0, "power": 0, "defence": 0, "footwork": 0, "body": 0},
    "middleweight":{"speed": -1, "stamina": -1, "power": +2, "defence": +1, "footwork": -1, "body": +2},
    "heavyweight":{"speed": -2, "stamina": 0, "power": +4, "defence": +2, "footwork": -3, "body": +4},
}

@dataclass
class FighterState:
    boxer: Boxer
    hp: int
    off_balance_penalty: int = 0
    warnings: int = 0
    fatigue: int = 0
    exchanges: int = 0

    # ⭐ Adrenaline & Specials
    adrenaline: int = 0
    # used to be a bool; now count uses so we can trigger up to 2x per match
    adrenaline_uses: int = 0
    adrenaline_max_uses: int = 2
    special_name: Optional[str] = None
    special_turns: int = 0
    special_meter: int = 0

@dataclass
class FightSession:
    channel_id: int
    rng_seed: Optional[int]; rng: "random.Random"
    red_raw: Boxer; blue_raw: Boxer; red_eff: Boxer; blue_eff: Boxer
    A: FighterState; B: FighterState
    kd_rule: str = "per_round"; kd_limit: int = 3
    kd_round: Dict[str,int] = field(default_factory=lambda: {"A":0,"B":0})
    kd_total: Dict[str,int] = field(default_factory=lambda: {"A":0,"B":0})
    current_round: int = 1; exchanges_per_round: int = 6
    finished: bool = False; winner: Optional[str] = None
    winner_corner: Optional[str] = None; winner_type: Optional[str] = None
    log: List[dict] = field(default_factory=list)
    crowd_log: List[str] = field(default_factory=list)  # lines to show for this round only
    momentum: int = 0  # negative favors Blue, positive favors Red
    crowd_hype: int = 0  # 0..100 for fun
    _crowd_seen_keys: set[str] = field(default_factory=set)  # de-dupe one-offs per fight