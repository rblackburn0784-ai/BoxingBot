import os
import asyncio
import random
import discord
from typing import Tuple, List, Dict, Optional
from ..models import FightSession, Boxer, FighterState, gender_badge
from ..config import (
    ROUND_GIF_LOCAL, ROUND_GIF_URL,
    ROUND_HIGHLIGHT_GIF_LOCAL, ROUND_HIGHLIGHT_GIF_URL,
    FINISH_GIF_LOCAL, FINISH_GIF_URL,
    JUDGE_CARD_PNG_LOCAL, JUDGE_CARD_PNG_URL,
    MOMENTUM_MAX, MOMENTUM_HIT_GAIN, MOMENTUM_BIG_HIT_BONUS, MOMENTUM_KD_BONUS,
    MOMENTUM_BLOCKED_PENALTY, MOMENTUM_CRITMISS_SWING, MOMENTUM_LOW_BLOW_SWING,
    CROWD_REACTIONS, COMMENTARY_DIR, MUSIC_DIR, PROMO_MUSIC_DIR
)
from ..services.voice import ensure_voice, play_clip
from .presentation import momentum_bar

# === helpers from your code (mods, hit tables, etc.) ===

def _pick_commentary_line():
    # example: pick a random .txt file from commentary lines folder
    files = [f for f in os.listdir(COMMENTARY_DIR) if f.lower().endswith(".txt")]
    if not files:
        return None
    chosen = random.choice(files)
    with open(os.path.join(COMMENTARY_DIR, chosen), "r", encoding="utf-8") as fh:
        return fh.read().strip()

def _ensure_crowd_state(session: FightSession, *_, **__):
    """Per-fight/round crowd state (tolerates extra args from older callers)."""
    if not hasattr(session, "_crowd_seen_keys"):
        session._crowd_seen_keys = set()
    if not hasattr(session, "_crowd_last_line"):
        session._crowd_last_line = ""
    if not hasattr(session, "momentum"):
        session.momentum = 0
    if not hasattr(session, "crowd_hype"):
        session.crowd_hype = 0

def _crowd_round_reset(session: FightSession):
    _ensure_crowd_state(session)
    session._crowd_seen_keys = set()
    session._crowd_last_line = ""

def _find_cheer_clip() -> Optional[str]:
    """
    Prefer COMMENTARY_DIR/cheer.mp3, else look in promo music folders.
    """
    try_candidates = []
    if os.path.isdir(COMMENTARY_DIR):
        try_candidates.append(os.path.join(COMMENTARY_DIR, "cheer.mp3"))
        try_candidates.append(os.path.join(COMMENTARY_DIR, "cheer.wav"))

    # Soft fallback to graphics/promo/music if you use that layout
    promo_roots = [
        os.path.join(os.getcwd(), "graphics", "promo", "music"),
        os.path.join(os.getcwd(), "graphics", "promo")
    ]
    for root in promo_roots:
        try_candidates.append(os.path.join(root, "cheer.mp3"))
        try_candidates.append(os.path.join(root, "cheer.wav"))

    for p in try_candidates:
        if os.path.exists(p):
            return p
    return None

# ⬇️ helper: which corner is this fighter in?
def _corner_of(session: FightSession, name: str) -> str:
    return "Red" if session.A.boxer.name == name else "Blue"

__all__ = ["FighterState", "run_one_round", "finalize_if_done",
    "send_round_card", "send_points_decision", "send_finish_announcement",
    "compute_scorecards", "update_adrenaline"]

HIT_TYPES = [("glancing",4,7),("jab",5,9),("cross",7,12),("hook",7,12),("uppercut",10,16)]
LOCATIONS = ["head","body","stomach","low_blow"]
def mod_acc(accuracy: int) -> int: return accuracy // 5
def mod_spd(speed: int) -> int: return speed // 10
def mod_def(defense: int) -> int: return defense // 5
def mod_ftw(footwork: int) -> int: return footwork // 10

def pick_hit_type(margin: int, nat20: bool) -> str:
    if nat20: return "uppercut"
    if margin <= 2: return random.choices(["glancing","jab"], [3,2])[0]
    elif margin <= 5: return random.choices(["jab","cross","hook"], [2,3,3])[0]
    else: return random.choices(["cross","hook","uppercut"], [3,3,2])[0]

def pick_location() -> str:
    return random.choices(LOCATIONS, weights=[50,35,12,3])[0]

def base_damage_for(hit_type: str) -> Tuple[int,int]:
    for name, lo, hi in HIT_TYPES:
        if name == hit_type: return (lo,hi)
    return (4,7)

def location_modifiers(location: str) -> float:
    if location == "head": return 1.0
    if location == "body": return 0.9
    if location == "stomach": return 1.1
    if location == "low_blow": return 0.0
    return 1.0

def reduction_by_resistance(location: str, chin: int, body: int) -> float:
    if location == "head": return max(0.6, 1.0 - (chin * 0.006))
    if location in ("body","stomach"): return max(0.6, 1.0 - (body * 0.006))
    return 1.0

# ======== Trait trade-offs (example small effects) ========
def trait_attack_bonus(trait: str, hit_type: Optional[str] = None) -> int:
    t = (trait or "").lower()
    if t == "sharp eyes" and hit_type in ("jab", "cross"):
        return 1
    return 0

def trait_defense_bonus(trait: str) -> int:
    if (trait or "").lower() == "quick feet":
        return 1
    return 0

def trait_block_bonus(trait: str) -> int:
    t = (trait or "").lower()
    if t == "quick feet":
        return 1
    if t == "granite chin":
        return -1
    return 0

# ⬇️ momentum updater
def update_momentum(session: FightSession, ev: dict):
    """
    Positive momentum favors Red; negative favors Blue. Small snowball bonus if you already have momentum.
    """
    if not ev:
        return

    prev = session.momentum
    delta = 0

    if ev["outcome"] == "hit":
        delta += MOMENTUM_HIT_GAIN
        if ev.get("damage", 0) >= 14:
            delta += MOMENTUM_BIG_HIT_BONUS
        if ev.get("knockdown"):
            delta += MOMENTUM_KD_BONUS
        if ev.get("blocked"):
            # If fully blocked, momentum shouldn’t jump as much.
            if ev.get("block_success"):
                delta += MOMENTUM_BLOCKED_PENALTY
    elif ev["outcome"] == "miss":
        # miss swings momentum to the defender
        delta -= MOMENTUM_HIT_GAIN // 2
    elif ev["outcome"] == "critical_miss":
        delta -= MOMENTUM_CRITMISS_SWING
    elif ev["outcome"] == "low_blow":
        delta -= MOMENTUM_LOW_BLOW_SWING

    # apply to the attacker's sign (Red → +, Blue → −)
    attacker_corner = "Red" if ev["attacker"] == session.A.boxer.name else "Blue"
    sign = +1 if attacker_corner == "Red" else -1

    # small "snowball" if momentum is already on your side
    if (sign == 1 and session.momentum > 0) or (sign == -1 and session.momentum < 0):
        delta += sign * 1  # slight accelerator

    session.momentum = max(-MOMENTUM_MAX, min(MOMENTUM_MAX, session.momentum + sign * delta))

    # flag a momentum reaction when we cross the erupt threshold in attacker’s direction
    if abs(session.momentum) >= MOMENTUM_ERUPT_THRESH and abs(prev) < MOMENTUM_ERUPT_THRESH:
        if (session.momentum > 0 and sign == +1) or (session.momentum < 0 and sign == -1):
            ev["momentum_reaction"] = True

# ⬇️ crowd tagger for instant commentary
def _crowd_tags_for_event(session: FightSession, ev: dict) -> list[str]:
    tags = []
    attacker = ev.get("attacker")
    corner = "Red" if attacker == session.A.boxer.name else "Blue"

    # High-priority first
    if ev.get("knockdown"):
        tags.append("KD_RED" if corner == "Red" else "KD_BLUE")
        return tags
    if ev["outcome"] == "hit" and ev.get("damage", 0) >= 14:
        tags.append("BIG_RED" if corner == "Red" else "BIG_BLUE")
        return tags
    if ev["outcome"] == "critical_miss":
        tags.append("CRITMISS_RED" if corner == "Red" else "CRITMISS_BLUE")
        return tags
    if ev["outcome"] == "low_blow":
        tags.append("LOWBLOW_RED" if corner == "Red" else "LOWBLOW_BLUE")
        return tags

    # Baseline tags so we always have a crowd option
    if ev["outcome"] == "hit":
        tags.append("HIT_RED" if corner == "Red" else "HIT_BLUE")
        if ev.get("blocked") is True:
            tags.append("BLOCKED")  # mild line
    elif ev["outcome"] == "miss":
        tags.append("MISS_RED" if corner == "Red" else "MISS_BLUE")

    return tags

# ===== Reaction selection + audio ============================================

BIG_HIT_THRESHOLD = 14          # same threshold you use for KD/big shots
MOMENTUM_ERUPT_THRESH = 8       # when abs(momentum) crosses/passes this, we can cheer

def _corner_from(session: FightSession, fighter_name: str) -> str:
    return "Red" if session.A.boxer.name == fighter_name else "Blue"

def _title_hit(ht: Optional[str]) -> str:
    if not ht: return "shot"
    m = {"jab":"jab", "cross":"cross", "hook":"hook", "uppercut":"uppercut", "glancing":"jab"}
    return m.get(ht.lower(), ht)

def detect_reaction_key(session: FightSession, ev: dict) -> Optional[str]:
    """Return one of: kd | big_hit | low_blow | crit_miss | big_block | momentum | None."""
    if ev.get("knockdown"):
        return "kd"
    oc = ev.get("outcome")
    if oc == "low_blow":
        return "low_blow"
    if oc == "critical_miss":
        return "crit_miss"
    if oc == "hit":
        if ev.get("blocked") and ev.get("block_success") is True:
            return "big_block"
        if ev.get("damage", 0) >= BIG_HIT_THRESHOLD:
            return "big_hit"
    # momentum cheer tagged by update_momentum (see patch below)
    if ev.get("momentum_reaction"):
        return "momentum"
    return None

def format_reaction_line(key: str, session: FightSession, ev: dict) -> str:
    """Fill {attacker}/{defender}/{hit_type}/{corner} placeholders."""
    attacker = ev.get("attacker", "Attacker")
    defender = ev.get("defender", "Defender")
    hit_type = _title_hit(ev.get("hit_type"))
    corner   = _corner_from(session, attacker)
    tpl = random.choice(CROWD_REACTIONS.get(key, [""]))
    return tpl.format(attacker=attacker, defender=defender, hit_type=hit_type, corner=corner)

def _exists(name: str) -> Optional[str]:
    p = os.path.join(COMMENTARY_DIR, name)
    return p if os.path.exists(p) else None

def resolve_commentary_mp3(key: str, session: FightSession, ev: dict) -> Optional[str]:
    """
    Map reaction key + event info to one of your files (per screenshot).
    Priority: KD/Low_Blow/Swing_Miss/Tidy_Block/Red|Blue_{Hit}/Pressure/Momentum...
    """
    attacker = ev.get("attacker")
    defender = ev.get("defender")
    a_corner = _corner_from(session, attacker) if attacker else "Red"
    d_corner = _corner_from(session, defender) if defender else "Blue"
    ht = ev.get("hit_type")
    # standardize to your filenames
    # replace the old map with this:
    hit_map = {"jab": "Jab", "cross": "Cross", "hook": "Hook", "uppercut": "Uppercut", "glancing": "Jab"}
    Hit = hit_map.get((ht or "").lower())

    if key == "kd":
        return _exists("KD.mp3") or _exists(f"{d_corner}_Down.mp3")
    if key == "low_blow":
        return _exists("Low_Blow.mp3")
    if key == "crit_miss":
        return _exists("Swing_Miss.mp3") or _exists(f"{d_corner}_Slip.mp3")
    if key == "big_block":
        return _exists("Tidy_Block.mp3") or _exists(f"{d_corner}_Block.mp3") or _exists(f"{d_corner}_Guard.mp3")
    if key == "big_hit":
        if Hit and _exists(f"{a_corner}_{Hit}.mp3"):
            return _exists(f"{a_corner}_{Hit}.mp3")
        return _exists(f"{a_corner}_Pressure.mp3") or _exists(f"{a_corner}_Cooking.mp3")
    if key == "momentum":
        return _exists(f"{a_corner}_Momentum.mp3") or _exists(f"{a_corner}_Pressure.mp3")
    return None

async def maybe_post_reaction_and_audio(
    interaction: discord.Interaction,
    session: FightSession,
    ev: dict
) -> Optional[str]:
    key = detect_reaction_key(session, ev)

    # ── New: “two whiffs then dull event” crowd line ─────────────────────
    if not key:
        # Did the previous TWO exchanges both miss?
        recent = getattr(session, "_last_two_outcomes", [])
        oc = ev.get("outcome")

        had_two_misses = (
            len(recent) == 2
            and all(o in ("miss", "critical_miss") for o in recent)
        )

        # What counts as the follow-up “dull” event?
        is_another_miss = oc in ("miss", "critical_miss")
        is_small_hit = (
            oc == "hit"
            and (ev.get("hit_type") or "").lower() in ("jab", "hook", "glancing")
            and ev.get("damage", 0) <= 8
        )

        # Only fire once per round
        seen = getattr(session, "_crowd_seen_keys", set())
        if had_two_misses and (is_another_miss or is_small_hit) and "miss_streak" not in seen:
            line = random.choice([
                "🎙️ **Crowd**: Lot of air in there — someone needs to find the target.",
                "🎙️ **Crowd**: They’re fencing with shadows… arena wants leather on chin.",
                "🎙️ **Crowd**: After all those whiffs, even a jab gets a little cheer."
            ])
            await interaction.followup.send(line)
            seen.add("miss_streak")
            session._crowd_seen_keys = seen
        return None
    # ── End new block ─────────────────────────────────────────────────────


    line = format_reaction_line(key, session, ev)
    # avoid immediate repeat
    if line == getattr(session, "_crowd_last_line", ""):
        # pick another line if available
        opts = CROWD_REACTIONS.get(key, [])
        alt = [x for x in opts if x != line]
        if alt:
            line = random.choice(alt)

    if line:
        await interaction.followup.send(line)
        session._crowd_seen_keys.add(key)
        session._crowd_last_line = line

        # voice
        mp3 = resolve_commentary_mp3(key, session, ev)
        if mp3:
            try:
                vc = await ensure_voice(interaction)
                if vc:
                    if vc.is_playing(): vc.stop()
                    # short + snappy
                    await play_clip(vc, mp3, seconds=5)
                    await asyncio.sleep(0.05)
            except Exception as e:
                print(f"[commentary] {type(e).__name__}: {e}")

    return line

async def maybe_post_lull(interaction: discord.Interaction, session: FightSession):
    """When exchanges are dull, nudge the crowd once per round."""
    _ensure_crowd_state(session)
    key = f"r{session.current_round}_lull_mid"
    if key in session._crowd_seen_keys:
        return
    # only if hype is low
    if getattr(session, "crowd_hype", 0) < 40 and getattr(session, "_quiet_streak", 0) >= 3:
        line = random.choice([
            "Crowd getting a bit restless — someone needs to let the hands go.",
            "It’s a chess match out there… the arena wants action.",
            "Muted buzz in the seats — both corners waiting for a mistake."
        ])
        session._crowd_seen_keys.add(key)
        await interaction.followup.send(f"🎙️ **Crowd**: {line}")
        # optional soft murmur SFX if present
        try:
            murmur = _exists("Crowd_Murmur.mp3") or _exists("Crowd_Murmur.wav")
            if murmur:
                vc = await ensure_voice(interaction)
                if vc:
                    await play_clip(vc, murmur, seconds=5)
        except Exception:
            pass

async def maybe_post_crowd_reaction(
    interaction: discord.Interaction,
    session: FightSession,
    round_idx: int,
    events: list[dict]
):
    _ensure_crowd_state(session)

    # Signals
    had_kd      = any(e.get("knockdown") for e in events if e.get("outcome") == "hit")
    big_shot    = max((e.get("damage", 0) for e in events if e.get("outcome") == "hit"), default=0) >= 14
    low_blow    = any(e.get("outcome") == "low_blow" for e in events)
    wild_misses = sum(1 for e in events if e.get("outcome") in ("miss", "critical_miss")) >= 4

    # Momentum nudge
    if had_kd or big_shot:
        # momentum toward the attacker who landed the biggest shot
        best = max((e for e in events if e.get("outcome") == "hit"), key=lambda x: x.get("damage", 0), default=None)
        if best:
            if best["attacker"] == session.A.boxer.name:
                session.momentum = min(10, session.momentum + 2)
            else:
                session.momentum = max(-10, session.momentum - 2)

    # Hype meter
    delta = (3 if had_kd else 0) + (2 if big_shot else 0) + (-1 if wild_misses else 0) + (1 if low_blow else 0)
    session.crowd_hype = max(0, min(100, session.crowd_hype + delta))

    # Choose one flavour line, de-duped per round-type
    key = None
    line = None
    if had_kd:
        key = f"r{round_idx}_kd"
        if key not in session._crowd_seen_keys:
            who = "🔴 Red corner" if session.momentum > 0 else ("🔵 Blue corner" if session.momentum < 0 else "The crowd")
            line = random.choice([
                f"{who} fans are on their feet after that knockdown!",
                "WHAT A SHOT! The arena just exploded!"
            ])
    elif low_blow:
        key = f"r{round_idx}_foul"
        if key not in session._crowd_seen_keys:
            line = random.choice([
                "Boos rain down after that low blow…",
                "The ref steps in — that’s low!"
            ])
    elif big_shot:
        key = f"r{round_idx}_bomb"
        if key not in session._crowd_seen_keys:
            line = random.choice([
                "Huge shot! You could feel that in the cheap seats!",
                "Ooooh! That one echoed around the arena!"
            ])
    elif wild_misses and session.crowd_hype < 40:
        key = f"r{round_idx}_lull"
        if key not in session._crowd_seen_keys:
            line = random.choice([
                "Crowd getting restless — they want exchanges!",
                "A chess match out there. Tension building…"
            ])

    if line:
        session._crowd_seen_keys.add(key)
        # Add a tiny “meter” for fun
        meter = "▮" * (session.crowd_hype // 10) + "▯" * (10 - session.crowd_hype // 10)
        await interaction.followup.send(f"🎙️ **Crowd**: {line}\nHype: `{meter}` ({session.crowd_hype}/100)")

# ===================== Fight engine =====================

def attack_exchange(attacker: FighterState, defender: FighterState, rng: random.Random) -> dict:
    fatigue_step = max(2, 6 + attacker.boxer.stamina // 20)
    fatigue_pen  = min(5, attacker.fatigue // fatigue_step)

    pre_notes = []
    # Auto-activate when you hit 100, up to 2 times per match, and only if no special is currently running
    if attacker.adrenaline >= 100 and attacker.adrenaline_uses < attacker.adrenaline_max_uses and attacker.special_turns == 0:
        move = activate_special(attacker)  # sets special_name & duration and zeros adrenaline
        attacker.adrenaline_uses += 1
        pre_notes.append(f"⭐ SPECIAL ACTIVATED: {move}! ({attacker.adrenaline_uses}/{attacker.adrenaline_max_uses})")

    d20 = rng.randint(1, 20)
    atk_mod = (mod_acc(attacker.boxer.accuracy) + mod_spd(attacker.boxer.speed)
               + attacker.off_balance_penalty - fatigue_pen)
    def_dc  = 10 + mod_def(defender.boxer.defense) + mod_ftw(defender.boxer.footwork) + trait_defense_bonus(defender.boxer.trait)

    result = {
        "attacker": attacker.boxer.name, "defender": defender.boxer.name,
        "d20": d20, "roll_total": 0, "atk_mod": 0, "def_dc": 0,
        "outcome": "", "hit_type": None, "location": None, "damage": 0,
        "blocked": False, "block_success": None, "notes": []
    }
    if pre_notes:
        result["notes"].extend(pre_notes)

    attacker.off_balance_penalty = 0

    # Natural 1
    if d20 == 1:
        result["roll_total"] = d20 + atk_mod
        result["atk_mod"] = atk_mod
        result["def_dc"] = def_dc
        result["outcome"] = "critical_miss"
        result["notes"].append("Off-balance! -2 next roll.")
        attacker.off_balance_penalty -= 2
        attacker.exchanges += 1
        attacker.fatigue += max(1, 3 - attacker.boxer.stamina // 40)
        # Decay specials at end of exchange
        decay_special(attacker); decay_special(defender)
        return result

    # First pass to beat DC
    roll_total = d20 + atk_mod
    margin = roll_total - def_dc
    if roll_total < def_dc:
        result["roll_total"] = roll_total
        result["atk_mod"] = atk_mod
        result["def_dc"] = def_dc
        result["outcome"] = "miss"
        attacker.exchanges += 1
        attacker.fatigue += max(1, 3 - attacker.boxer.stamina // 40)
        decay_special(attacker); decay_special(defender)
        return result

    # Determine location + low blow check
    location = pick_location()
    if location == "low_blow":
        result["roll_total"] = roll_total
        result["atk_mod"] = atk_mod
        result["def_dc"] = def_dc
        result["outcome"] = "low_blow"
        result["location"] = "low_blow"
        attacker.warnings += 1
        result["notes"].append(f"Ref warning #{attacker.warnings} for low blow!")
        attacker.off_balance_penalty -= 1
        if attacker.warnings >= 3:
            result["notes"].append("Point deducted for repeated fouls!")
            result["point_deduction"] = True
        else:
            result["point_deduction"] = False
        attacker.exchanges += 1
        attacker.fatigue += max(1, 3 - attacker.boxer.stamina // 40)
        decay_special(attacker); decay_special(defender)
        return result

    # Hit type
    nat20 = (d20 == 20)
    hit_type = pick_hit_type(margin, nat20)
    result["hit_type"] = hit_type
    result["location"] = location

    # Trait adjustments (to-hit/DC)
    ctx_bonus = trait_attack_bonus(attacker.boxer.trait, hit_type)
    if (attacker.boxer.trait or "").lower() == "iron body" and hit_type in ("hook", "uppercut"):
        atk_mod -= 1
        result["notes"].append("Iron Body (drawback): heavy shot a bit slower (−1 to-hit).")
    if ctx_bonus:
        atk_mod += ctx_bonus
        result["notes"].append("Sharp Eyes: clean line on straight (+1 to-hit).")
    if (defender.boxer.trait or "").lower() == "sharp eyes" and hit_type in ("jab","cross"):
        def_dc -= 1
        result["notes"].append("Sharp Eyes (drawback): easier to tag with straights (−1 DC).")

    # SPECIAL to-hit/DC (apply BEFORE final hit check)
    if attacker.special_name == "Lightning Combo":
        atk_mod += 2
        result["notes"].append("Lightning Combo: +2 to-hit.")
    elif attacker.special_name == "Unleashed Fury":
        atk_mod -= 1
        result["notes"].append("Unleashed Fury: -1 to-hit, huge power.")
    if defender.special_name == "Iron Guard":
        def_dc += 2
        result["notes"].append("Iron Guard: +2 defense DC.")

    # Final check with all mods
    roll_total = d20 + atk_mod
    result["roll_total"] = roll_total
    result["atk_mod"] = atk_mod
    result["def_dc"] = def_dc
    margin = roll_total - def_dc
    if roll_total < def_dc:
        result["outcome"] = "miss"
        attacker.exchanges += 1
        attacker.fatigue += max(1, 3 - attacker.boxer.stamina // 40)
        decay_special(attacker); decay_special(defender)
        return result

    # Block attempt
    blocked = False
    block_success = None
    if margin <= 2:
        difficulty = 12 if hit_type in ("glancing","jab") else (14 if hit_type in ("cross","hook") else 16)
        block_roll = (rng.randint(1,20)
                      + mod_def(defender.boxer.defense)
                      + mod_ftw(defender.boxer.footwork)
                      + trait_block_bonus(defender.boxer.trait))
        blocked = True
        block_success = block_roll >= difficulty

    # Base damage
    lo, hi = base_damage_for(hit_type)
    raw = rng.randint(lo, hi)
    raw = int(round(raw * (1.0 + attacker.boxer.power / 50.0)))
    raw = int(round(raw * location_modifiers(location)))
    raw = int(round(raw * reduction_by_resistance(location, defender.boxer.chin, defender.boxer.body)))

    if blocked and block_success is not None:
        if block_success:
            raw = int(round(raw * 0.3))
            result["notes"].append("Block absorbed most of the shot.")
        else:
            raw = int(round(raw * 0.7))
            result["notes"].append("Block partially failed.")

    if margin >= 8:
        raw = int(round(raw * (1.0 + attacker.boxer.speed / 100.0)))

    fatigue_scale = max(0.8, 1.0 - (fatigue_pen * 0.04))
    raw = int(round(raw * fatigue_scale))
    damage = max(0, raw)

    # Trait damage tweaks
    if (attacker.boxer.trait or "").lower() == "quick feet":
        damage = int(round(damage * 0.95))
        if damage > 0:
            result["notes"].append("Quick Feet (drawback): not fully planted (−5% dmg).")
    if (attacker.boxer.trait or "").lower() == "gas tank" and margin >= 8:
        damage = int(round(damage * 0.93))
        if damage > 0:
            result["notes"].append("Gas Tank (drawback): conserving energy on big swing (−7% dmg).")

    # SPECIAL damage tweaks (apply BEFORE subtracting HP and before setting result)
    if attacker.special_name == "Lightning Combo":
        damage = int(round(damage * 1.15))
        if damage > 0: result["notes"].append("Lightning Combo: +15% damage.")
    elif attacker.special_name == "Unleashed Fury":
        damage = int(round(damage * 1.30))
        if damage > 0: result["notes"].append("Unleashed Fury: +30% damage!")
    if defender.special_name == "Iron Guard":
        damage = int(round(damage * 0.65))
        if damage > 0: result["notes"].append("Iron Guard: -35% damage taken.")

    # Apply damage
    defender.hp -= damage
    result["outcome"] = "hit"
    result["damage"] = damage
    result["blocked"] = blocked
    result["block_success"] = block_success

    # KD detection
    KD_DAMAGE_THRESHOLD = 14
    KD_FROM_NAT20 = True
    result["knockdown"] = False
    if damage >= KD_DAMAGE_THRESHOLD:
        result["knockdown"] = True
    elif KD_FROM_NAT20 and d20 == 20 and not (blocked and block_success):
        result["knockdown"] = True

    if damage >= 14 and rng.random() < 0.25:
        result["notes"].append("Staggered! −1 next roll.")
        defender.off_balance_penalty -= 1

    attacker.exchanges += 1
    attacker.fatigue += max(1, 3 - attacker.boxer.stamina // 40)
    if blocked:
        defender.fatigue += 1 if defender.boxer.stamina >= 40 else 2

    # Decay specials at end of exchange
    decay_special(attacker)
    decay_special(defender)

    return result

# ⬇️ make adrenaline build slower + fairer and support fouls
def update_adrenaline(attacker: FighterState, defender: FighterState, ev: dict):
    """
    Slower, steadier adrenaline. Typical clean hit +4 / defender +1; KDs give a small surge.
    """
    if ev["outcome"] == "hit":
        attacker.adrenaline += 4
        defender.adrenaline += 1
        if ev.get("knockdown"):
            attacker.adrenaline += 6
            defender.adrenaline = max(0, defender.adrenaline - 6)
    elif ev["outcome"] == "miss":
        defender.adrenaline += 2
    elif ev["outcome"] == "critical_miss":
        defender.adrenaline += 3
    elif ev["outcome"] == "low_blow":
        attacker.adrenaline = max(0, attacker.adrenaline - 15)

    attacker.adrenaline = max(0, min(100, attacker.adrenaline))
    defender.adrenaline = max(0, min(100, defender.adrenaline))


# ===================== Special Moves =====================
SPECIAL_MOVES = {
    "Lightning Combo": {"duration": 2, "kind": "offense"},
    "Iron Guard": {"duration": 3, "kind": "defense"},
    "Unleashed Fury": {"duration": 2, "kind": "offense_heavy"},
}

TRAIT_SPECIAL_DEFAULT = {
    "quick feet": "Lightning Combo",
    "sharp eyes": "Lightning Combo",
    "granite chin": "Iron Guard",
    "iron body": "Iron Guard",
    "gas tank": "Unleashed Fury",
}

def choose_special_for(boxer) -> str:
    t = (boxer.trait or "").lower()
    return TRAIT_SPECIAL_DEFAULT.get(t, "Lightning Combo")

def activate_special(f: FighterState) -> str:
    move = choose_special_for(f.boxer)
    spec = SPECIAL_MOVES[move]
    f.special_name = move
    f.special_turns = spec["duration"]
    f.special_used = True
    f.adrenaline = 0
    return move

def decay_special(f: FighterState):
    if f.special_turns > 0:
        f.special_turns -= 1
        if f.special_turns <= 0:
            f.special_turns = 0
            f.special_name = None

def round_damage(events: List[dict], target_name: str) -> int:
    return sum(e["damage"] for e in events if e.get("outcome") == "hit" and e.get("defender") == target_name)

def tko_stoppage(hp_after_round: int, dmg_this_round: int) -> bool:
    return (hp_after_round <= 10 and dmg_this_round >= 20) or (hp_after_round <= 5)

def matchup_key(red: Boxer, blue: Boxer) -> str:
    r, b = red.gender, blue.gender
    if r == "male" and b == "male": return "MM"
    if r == "female" and b == "female": return "FF"
    return "MF"

def corner_assignments(a: Boxer, b: Boxer, rng: random.Random):
    return (("Red", a), ("Blue", b)) if rng.randint(0,1)==0 else (("Red", b), ("Blue", a))

def _highlight_gif_for_event(session: FightSession, ev: dict):
    from pathlib import Path
    mkey = matchup_key(session.red_raw, session.blue_raw)  # "MM","FF","MF"
    attacker = ev.get("attacker")
    corner = "Red" if attacker == session.A.boxer.name else "Blue"

    # Normalize type
    alias = {
        "glancing": "glancing",
        "jab": "jab",
        "cross": "cross",
        "straight": "cross",   # straight -> cross
        "hook": "hook",
        "uppercut": "uppercut",
        "miss": "miss",
        "critical_miss": "miss",
        "low_blow": "low_blow",
        "knockdown": "knockdown",
    }
    raw_type = (ev.get("gif_type") or ev.get("hit_type") or ev.get("outcome") or "glancing").lower()
    gif_type = alias.get(raw_type, "glancing")

    # 1) Try filename convention directly (works even if config maps are empty)
    #    e.g. graphics/promo/rounds/mm_red_hook.gif
    rounds_dir = Path(os.getcwd()) / "graphics" / "promo" / "rounds"
    fname = f"{mkey.lower()}_{corner.lower()}_{gif_type}.gif"
    fpath = rounds_dir / fname
    if fpath.exists():
        return discord.File(str(fpath), filename=fpath.name), None

    # 2) Your configured maps (keys must be EXACT: ("MM","Red","hook"))
    key = (mkey, corner, gif_type)
    local = ROUND_HIGHLIGHT_GIF_LOCAL.get(key)
    if local and os.path.exists(local):
        return discord.File(local, filename=os.path.basename(local)), None
    url = ROUND_HIGHLIGHT_GIF_URL.get(key)
    if url:
        return None, url

    # 3) Corner-only fallback within rounds_dir (any type for same matchup/corner)
    if rounds_dir.exists():
        for alt in rounds_dir.glob(f"{mkey.lower()}_{corner.lower()}_*.gif"):
            return discord.File(str(alt), filename=alt.name), None

    # 4) Map fallbacks for same matchup/corner
    for k, p in ROUND_HIGHLIGHT_GIF_LOCAL.items():
        if k[0] == mkey and k[1] == corner and os.path.exists(p):
            return discord.File(p, filename=os.path.basename(p)), None
    for k, u in ROUND_HIGHLIGHT_GIF_URL.items():
        if k[0] == mkey and k[1] == corner:
            return None, u

    # 5) Generic round art
    local_generic = ROUND_GIF_LOCAL.get(mkey)
    if local_generic and os.path.exists(local_generic):
        return discord.File(local_generic, filename=os.path.basename(local_generic)), None
    url_generic = ROUND_GIF_URL.get(mkey)
    if url_generic:
        return None, url_generic
    return None, None


def _finish_gif_for_result(red: Boxer, blue: Boxer, winner_corner: str, win_type: str):
    """
    Pick the correct finish GIF file based on matchup, corner, and result.
    Looks in graphics/promo/finish/ for files like:
        mm_red_ko.gif
        mm_blue_tko.gif
        mm_red_points.gif
    Returns (discord.File | None, url | None)
    """
    from pathlib import Path
    import os
    mkey = matchup_key(red, blue)  # e.g., "MM", "FF", "MF"
    base_dir = Path(os.getcwd()) / "graphics" / "promo" / "finish"
    file_to_send = None
    url = None

    if not base_dir.exists():
        return None, None

    fn = f"{mkey.lower()}_{winner_corner.lower()}_{win_type.lower()}.gif"
    p = base_dir / fn
    if p.exists():
        return discord.File(str(p), filename=p.name), None

    # fallback: look for partial matches (e.g., mm_red_ko*.gif)
    for alt in base_dir.glob(f"{mkey.lower()}_{winner_corner.lower()}_{win_type.lower()}*.gif"):
        return discord.File(str(alt), filename=alt.name), None

    # final fallback: generic
    for alt in base_dir.glob(f"{mkey.lower()}_*_{win_type.lower()}*.gif"):
        return discord.File(str(alt), filename=alt.name), None

    return None, None


def run_one_round(session: FightSession) -> Tuple[List[dict], Optional[str], Optional[str]]:
    # stamina recovery at start of round
    recovA = 2 + (session.A.boxer.stamina // 20)
    recovB = 2 + (session.B.boxer.stamina // 20)
    session.A.fatigue = max(0, session.A.fatigue - recovA)
    session.B.fatigue = max(0, session.B.fatigue - recovB)

    # round KD counters
    session.kd_round = {"A": 0, "B": 0}

    events: List[dict] = []
    loser: Optional[str] = None
    winner_type: Optional[str] = None

    if not hasattr(session, "kd_total"):
        session.kd_total = {"A": 0, "B": 0}

    order = [("A","B"),("B","A"),("A","B"),("B","A"),("A","B"),("B","A")]
    for attacker, defender in order:
        if attacker == "A":
            ev = attack_exchange(session.A, session.B, session.rng)
            events.append(ev)
            update_adrenaline(session.A, session.B, ev)
            update_momentum(session, ev)
            ev["crowd_tags"] = _crowd_tags_for_event(session, ev)

            # quiet streak for later lull logic (used by maybe_post_lull in your cog)
            if ev.get("outcome") in ("miss", "critical_miss"):
                session._quiet_streak = getattr(session, "_quiet_streak", 0) + 1
            else:
                session._quiet_streak = 0
            # track last two outcomes for “double-miss then dull event” commentary
            recent = getattr(session, "_last_two_outcomes", [])
            recent.append(ev.get("outcome"))
            if len(recent) > 2:
                recent = recent[-2:]
            session._last_two_outcomes = recent


            if ev.get("knockdown"):
                session.kd_round["B"] += 1
                session.kd_total["B"] += 1
                session.B.off_balance_penalty -= 1

            if session.B.hp <= 0:
                winner_type, loser = "KO", session.B.boxer.name
                break
        else:
            ev = attack_exchange(session.B, session.A, session.rng)
            events.append(ev)
            update_adrenaline(session.B, session.A, ev)
            update_momentum(session, ev)
            ev["crowd_tags"] = _crowd_tags_for_event(session, ev)

            if ev.get("outcome") in ("miss", "critical_miss"):
                session._quiet_streak = getattr(session, "_quiet_streak", 0) + 1
            else:
                session._quiet_streak = 0
            # ✅ track last two outcomes for “double-miss then dull event” commentary
            recent = getattr(session, "_last_two_outcomes", [])
            recent.append(ev.get("outcome"))
            if len(recent) > 2:
                recent = recent[-2:]
            session._last_two_outcomes = recent

            if ev.get("knockdown"):
                session.kd_round["A"] += 1
                session.kd_total["A"] += 1
                session.A.off_balance_penalty -= 1

            if session.A.hp <= 0:
                winner_type, loser = "KO", session.A.boxer.name
                break

    # 3KD rule
    if winner_type is None and session.kd_rule != "off":
        kdr_A = session.kd_round["A"] if session.kd_rule == "per_round" else session.kd_total["A"]
        kdr_B = session.kd_round["B"] if session.kd_rule == "per_round" else session.kd_total["B"]
        if kdr_A >= session.kd_limit and kdr_B >= session.kd_limit:
            dmgA = round_damage(events, session.A.boxer.name)
            dmgB = round_damage(events, session.B.boxer.name)
            if dmgA > dmgB:
                winner_type, loser = "TKO", session.A.boxer.name
            elif dmgB > dmgA:
                winner_type, loser = "TKO", session.B.boxer.name
            else:
                if session.A.hp < session.B.hp:
                    winner_type, loser = "TKO", session.A.boxer.name
                else:
                    winner_type, loser = "TKO", session.B.boxer.name
        elif kdr_A >= session.kd_limit:
            winner_type, loser = "TKO", session.A.boxer.name
        elif kdr_B >= session.kd_limit:
            winner_type, loser = "TKO", session.B.boxer.name

    # damage-based TKO check
    if not winner_type:
        dmgA = round_damage(events, session.A.boxer.name)
        dmgB = round_damage(events, session.B.boxer.name)
        if tko_stoppage(session.A.hp, dmgA):
            winner_type, loser = "TKO", session.A.boxer.name
        elif tko_stoppage(session.B.hp, dmgB):
            winner_type, loser = "TKO", session.B.boxer.name

    return events, winner_type, loser


def finalize_if_done(session: FightSession):
    if session.finished: return

    if session.A.hp <= 0 and session.B.hp <= 0:
        session.finished, session.winner, session.winner_type, session.winner_corner = True, None, "KO", None
        return
    if session.A.hp <= 0:
        session.finished, session.winner, session.winner_type, session.winner_corner = True, session.B.boxer.name, "KO", "Blue"; return
    if session.B.hp <= 0:
        session.finished, session.winner, session.winner_type, session.winner_corner = True, session.A.boxer.name, "KO", "Red"; return

    if session.current_round > 12:
        cards = compute_scorecards(session)
        votesA = sum(1 for c in cards if c["for"] == "A")
        votesB = sum(1 for c in cards if c["for"] == "B")
        if votesA > votesB:
            session.finished = True
            session.winner = session.A.boxer.name
            session.winner_type = "Points"
            session.winner_corner = "Red"
        elif votesB > votesA:
            session.finished = True
            session.winner = session.B.boxer.name
            session.winner_type = "Points"
            session.winner_corner = "Blue"
        else:
            session.finished = True
            session.winner = None
            session.winner_type = None
            session.winner_corner = None
        session.judge_cards = cards

# ===================== Judges / Scorecards =====================
JUDGES = ["TheDude", "Walter Sobchak", "Donny Kerabatsos"]

def _round_stats(events: List[dict], nameA: str, nameB: str) -> tuple[int,int,int,int]:
    dmgA = sum(e["damage"] for e in events if e.get("outcome")=="hit" and e.get("defender")==nameA)
    dmgB = sum(e["damage"] for e in events if e.get("outcome")=="hit" and e.get("defender")==nameB)
    kdA  = sum(1 for e in events if e.get("outcome")=="hit" and e.get("knockdown") and e.get("defender")==nameA)
    kdB  = sum(1 for e in events if e.get("outcome")=="hit" and e.get("knockdown") and e.get("defender")==nameB)
    return dmgA, dmgB, kdA, kdB

def _score_round(dmgA: int, dmgB: int, kdA: int, kdB: int, bias: float, rng: random.Random) -> tuple[int,int,str]:
    diff = dmgB - dmgA
    eff = diff - bias
    if abs(eff) < 2:
        winner = "A" if rng.random() + (bias*0.25) > 0.5 else "B"
    else:
        winner = "A" if eff < 0 else "B"

    scoreA, scoreB = 10, 10
    if winner == "A":
        scoreB -= 1
        if kdB >= 2: scoreB = 7
        elif kdB == 1: scoreB = 8
    else:
        scoreA -= 1
        if kdA >= 2: scoreA = 7
        elif kdA == 1: scoreA = 8

    if winner == "A" and kdB == 0 and (dmgA - dmgB) >= 10 and scoreB == 9:
        scoreB = 8
    if winner == "B" and kdA == 0 and (dmgB - dmgA) >= 10 and scoreA == 9:
        scoreA = 8

    note = f"{scoreA}-{scoreB} (dmg A/B {dmgA}/{dmgB}, KD A/B {kdA}/{kdB})"
    return scoreA, scoreB, note

def compute_scorecards(session: FightSession) -> list[dict]:
    rng = session.rng
    nameA, nameB = session.A.boxer.name, session.B.boxer.name
    cards = []
    judge_biases = {JUDGES[0]: +0.15, JUDGES[1]: 0.0, JUDGES[2]: -0.15}

    for j in JUDGES:
        bias = judge_biases.get(j, 0.0)
        totalA = totalB = 0
        per_round = []
        for r in session.log:
            dmgA, dmgB, kdA, kdB = _round_stats(r["events"], nameA, nameB)
            sA, sB, note = _score_round(dmgA, dmgB, kdA, kdB, bias, rng)

            # deduct 1 point for each fighter with 3+ low-blow warnings
            warnsA = session.A.warnings
            warnsB = session.B.warnings
            if warnsA >= 3:
                sA -= 1
                note += f"  (-1 for fouls by {nameA})"
            if warnsB >= 3:
                sB -= 1
                note += f"  (-1 for fouls by {nameB})"
            totalA += sA
            totalB += sB
            per_round.append((sA, sB, note))
        verdict = "A" if totalA > totalB else ("B" if totalB > totalA else "Draw")
        cards.append({"judge": j, "totalA": totalA, "totalB": totalB, "rounds": per_round, "for": verdict})
    return cards

async def send_finish_announcement(
    interaction: discord.Interaction,
    session: FightSession,
    red: Boxer,
    blue: Boxer,
    winner_name: Optional[str],
    winner_corner: Optional[str],
    loser_name: Optional[str],
    win_type: Optional[str]
):
    if not win_type:
        emb = discord.Embed(
            title="🏁 Result: Draw",
            description="No winner after the final bell.",
            color=discord.Color.dark_grey()
        )
        await interaction.followup.send(embed=emb)
        # optional: mild crowd murmur instead of cheer
        return

    title = f"🏁 Result: {winner_name} wins by {win_type}!"
    color = discord.Color.red() if winner_corner == "Red" else discord.Color.blue()
    emb = discord.Embed(
        title=title,
        description=f"{winner_name} ({winner_corner}) defeats {loser_name}.",
        color=color
    )

    # 👇 NEW: add stat lines under the title
    totals = _fight_totals(session) if hasattr(interaction, "client") and hasattr(interaction, "channel") else None
    try:
        if totals:
            rname, bname = red.name, blue.name
            rt = totals.get(rname, {})
            bt = totals.get(bname, {})
            r_txt = (
                f"**Landed/Thrown:** {rt.get('landed', 0)}/{rt.get('thrown', 0)} "
                f"({rt.get('accuracy', 0):.0f}%)\n"
                f"**Damage:** {rt.get('damage', 0)}  •  **KD For/Against:** {rt.get('kd_for', 0)}/{rt.get('kd_against', 0)}\n"
                f"**Blocks Forced:** {rt.get('blocks_forced', 0)}  •  **Fouls (warnings):** {rt.get('fouls', 0)}"
            )
            b_txt = (
                f"**Landed/Thrown:** {bt.get('landed', 0)}/{bt.get('thrown', 0)} "
                f"({bt.get('accuracy', 0):.0f}%)\n"
                f"**Damage:** {bt.get('damage', 0)}  •  **KD For/Against:** {bt.get('kd_for', 0)}/{bt.get('kd_against', 0)}\n"
                f"**Blocks Forced:** {bt.get('blocks_forced', 0)}  •  **Fouls (warnings):** {bt.get('fouls', 0)}"
            )
            emb.add_field(name=f"🔴 {red.name}", value=r_txt, inline=False)
            emb.add_field(name=f"🔵 {blue.name}", value=b_txt, inline=False)
    except Exception:
        # don’t block the result if anything goes weird
        pass

    mkey = matchup_key(red, blue)
    key = (mkey, winner_corner, win_type)
    file_to_send = None
    local_path = FINISH_GIF_LOCAL.get(key)
    url = FINISH_GIF_URL.get(key)

    # 🎞️ finish GIF
    file_to_send, url = _finish_gif_for_result(red, blue, winner_corner, win_type)

    if file_to_send:
        emb.set_image(url=f"attachment://{file_to_send.filename}")
        await interaction.followup.send(embed=emb, file=file_to_send)
    elif url:
        emb.set_image(url=url)
        await interaction.followup.send(embed=emb)
    else:
        # fallback to no image
        await interaction.followup.send(embed=emb)

    # 🔔 Bell + 🎉 Cheer sequence on finish
    try:
        bell = _find_bell_clip()
        if bell:
            vc = await ensure_voice(interaction)
            if vc:
                if vc.is_playing():
                    vc.stop()
                # 1) Bell rings cleanly
                await play_clip(vc, bell, seconds=3)
                # short pause before cheer (optional)
                await asyncio.sleep(0.3)

        clip = _find_cheer_clip()
        if clip:
            vc = await ensure_voice(interaction)
            if vc:
                if vc.is_playing():
                    vc.stop()
                # 2) Play cheer afterwards
                await play_clip(vc, clip, seconds=5)
                await asyncio.sleep(0.05)
    except Exception as _e:
        print(f"[bell/cheer] {type(_e).__name__}: {_e}")
        pass

def _fight_totals(session: FightSession) -> dict[str, dict]:
    """Return {name: {landed, thrown, accuracy, damage, kd_for, kd_against, blocks_forced, fouls}}."""
    nameA, nameB = session.A.boxer.name, session.B.boxer.name
    out = {
        nameA: {"landed":0,"thrown":0,"damage":0,"kd_for":0,"kd_against":0,"blocks_forced":0,"fouls":session.A.warnings},
        nameB: {"landed":0,"thrown":0,"damage":0,"kd_for":0,"kd_against":0,"blocks_forced":0,"fouls":session.B.warnings},
    }
    for rnd in session.log:
        for e in rnd.get("events", []):
            oc = e.get("outcome")
            atk, dfn = e.get("attacker"), e.get("defender")
            # attempts
            if oc in ("hit","miss","critical_miss","low_blow"):
                out[atk]["thrown"] += 1
            # landed
            if oc == "hit":
                out[atk]["landed"] += 1
                out[atk]["damage"] += int(e.get("damage",0))
                if e.get("knockdown"):
                    out[atk]["kd_for"] += 1
                    out[dfn]["kd_against"] += 1
                if e.get("blocked") and e.get("block_success") is True:
                    out[atk]["blocks_forced"] += 1
            elif oc == "low_blow":
                # we still count as an attempt; fouls already tracked via warnings
                pass
    for name, d in out.items():
        d["accuracy"] = (100.0 * d["landed"] / d["thrown"]) if d["thrown"] else 0.0
    return out


def _find_bell_clip() -> Optional[str]:
    """
    Prefer Bell.mp3 / Bell.wav in COMMENTARY_DIR, fallback to promo music folder.
    """
    try_candidates = []
    if os.path.isdir(COMMENTARY_DIR):
        try_candidates += [
            os.path.join(COMMENTARY_DIR, "Bell.mp3"),
            os.path.join(COMMENTARY_DIR, "Bell.wav"),
        ]

    promo_roots = [
        os.path.join(os.getcwd(), "graphics", "promo", "music"),
        os.path.join(os.getcwd(), "graphics", "promo"),
    ]
    for root in promo_roots:
        try_candidates += [
            os.path.join(root, "Bell.mp3"),
            os.path.join(root, "Bell.wav"),
        ]

    for p in try_candidates:
        if os.path.exists(p):
            return p
    return None


def _resolve_judge_card_asset(badge_key: str, judge_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (local_path, url_fallback) for the judge's decision card.
    badge_key: 'Red' | 'Blue' | 'Draw'
    judge_name: e.g. 'TheDude'
    """
    local_map = JUDGE_CARD_PNG_LOCAL.get(badge_key, {})
    url_map = JUDGE_CARD_PNG_URL.get(badge_key, {})

    # prefer per-judge asset, then default
    local_path = local_map.get(judge_name) or local_map.get("default")
    url_path = url_map.get(judge_name) or url_map.get("default")

    # If local path is missing or file not found, caller will use url_path if set
    return local_path, url_path


async def send_points_decision(interaction: discord.Interaction, session: FightSession):
    cards = getattr(session, "judge_cards", None) or compute_scorecards(session)
    nameA, nameB = session.A.boxer.name, session.B.boxer.name

    for c in cards:
        j = c["judge"]
        totA, totB = c["totalA"], c["totalB"]
        verdict_for = c["for"]  # "A" | "B" | "Draw"

        if verdict_for == "A":
            verdict_line = f"{j} scores it **{totA}–{totB}** for **{nameA} (Red)**."
            badge_key = "Red"
        elif verdict_for == "B":
            verdict_line = f"{j} scores it **{totB}–{totA}** for **{nameB} (Blue)**."
            badge_key = "Blue"
        else:
            verdict_line = f"{j} scores it **{totA}–{totB}**, a **Draw**."
            badge_key = "Draw"

        rr = []
        for i, (sA, sB, _note) in enumerate(c["rounds"], start=1):
            rr.append(f"R{i:02d}: {sA}-{sB}")
        breakdown = " • ".join(rr)

        emb = discord.Embed(
            title=f"🧾 Judge {j}",
            description=verdict_line,
            color=discord.Color.dark_teal()
        )
        emb.add_field(name="Round-by-round", value=breakdown[:1024], inline=False)

        # 👇 per-judge thumbnail
        local_path, url_path = _resolve_judge_card_asset(badge_key, j)
        file_to_send = None
        if local_path and os.path.exists(local_path):
            file_to_send = discord.File(local_path, filename=os.path.basename(local_path))
            emb.set_thumbnail(url=f"attachment://{os.path.basename(local_path)}")
        elif url_path:
            emb.set_thumbnail(url=url_path)

        if file_to_send:
            await interaction.followup.send(embed=emb, file=file_to_send)
        else:
            await interaction.followup.send(embed=emb)

        await asyncio.sleep(1.2)

    # send result banner after judges
    loser_name = session.B.boxer.name if session.winner_corner == "Red" else (session.A.boxer.name if session.winner_corner == "Blue" else None)
    await send_finish_announcement(
        interaction,
        session,
        session.red_raw, session.blue_raw,
        session.winner, session.winner_corner,
        loser_name,
        "Points"
    )

# ===================== Round card + finish announcement =====================
def _bar(val: int, width: int = 12, fill: str = "█", empty: str = "—") -> str:
    val = max(0, min(100, int(val)))
    n = round((val / 100) * width)
    return fill * n + empty * (width - n)

# ⬇️ tweak the HP display in send_round_card to include 10-HP blocks + momentum bar
# (find send_round_card in services/combat.py; we’ll only change the embed fields here in match.py call)
# Instead, we’ll keep services/combat.py embed as-is and just enrich it here by re-sending a short status
# after the instant commentary. If you prefer a single embed, you can move this into send_round_card.

def _hp_blocks(hp: int) -> str:
    """10-block fixed HP bar, regardless of a boxer’s absolute max HP."""
    # Convert to a 0..100 scale then 10 blocks.
    # If your boxers’ max HP != 100, normalize here:
    try:
        # If FighterState exposes a true max, use it; else assume 100.
        max_hp = 100
        if isinstance(hp, (int, float)):
            pass
    except Exception:
        max_hp = 100
    # Clamp to 0..100 and draw 10 blocks.
    pct = max(0, min(100, int(hp if hp <= 100 else (hp / max_hp) * 100)))
    blocks = pct // 10
    return "█" * blocks + "░" * (10 - blocks)


async def _send_short_status(interaction: discord.Interaction, s: FightSession):
    emb = discord.Embed(
        title=f"Round {s.current_round} — Live",
        description=f"Momentum {momentum_bar(s.momentum, 20)}",
        color=discord.Color.dark_teal()
    )
    emb.add_field(
        name=f"🔴 {s.A.boxer.name}",
        value=f"HP `{_hp_blocks(s.A.hp)}`  **{max(0, s.A.hp)}**  • Adr {int(s.A.adrenaline)}%",
        inline=False
    )
    emb.add_field(
        name=f"🔵 {s.B.boxer.name}",
        value=f"HP `{_hp_blocks(s.B.hp)}`  **{max(0, s.B.hp)}**  • Adr {int(s.B.adrenaline)}%",
        inline=False
    )
    await interaction.followup.send(embed=emb)

async def send_round_card(interaction: discord.Interaction, session: FightSession, round_events: List[dict]):
    # ---- Build narration ----
    lines = []
    for i, ev in enumerate(round_events, start=1):
        if ev["outcome"] == "hit":
            kd  = " **[KNOCKDOWN]**" if ev.get("knockdown") else ""
            blk = ""
            if ev.get("blocked"):
                blk = " [BLOCK✔]" if ev.get("block_success") else " [BLOCK~]"
            lines.append(f"{i:02d}. **{ev['attacker']}** hits a *{ev['hit_type']}* to **{ev['location']}** for **{ev['damage']}**{blk}{kd}")
        elif ev["outcome"] == "miss":
            lines.append(f"{i:02d}. **{ev['attacker']}** misses")
        elif ev["outcome"] == "critical_miss":
            lines.append(f"{i:02d}. **{ev['attacker']}** **CRITICAL MISS** (off-balance next)")
        elif ev["outcome"] == "low_blow":
            lines.append(f"{i:02d}. **{ev['attacker']}** **LOW BLOW** (warning)")
        if ev.get("notes"):
            for n in ev["notes"]:
                lines.append(f"  • {n}")

    text = "\n".join(lines) if lines else "_Quiet round._"

    emb = discord.Embed(
        title=f"Round {session.current_round}",
        # keep description shorter to ensure other fields survive
        description=text[:2500],  # ⬅️ tighter cap
        color=discord.Color.orange()
    )

    emb.add_field(
        name=f"🔴 {session.A.boxer.name} {gender_badge(session.A.boxer.gender)}",
        value=f"`{_hp_blocks(session.A.hp)}`",
        inline=True
    )
    emb.add_field(
        name=f"🔵 {session.B.boxer.name} {gender_badge(session.B.boxer.gender)}",
        value=f"`{_hp_blocks(session.B.hp)}`",
        inline=True
    )
    emb.add_field(
        name="Momentum",
        value=momentum_bar(session.momentum, 20),
        inline=False
    )
    emb.add_field(
        name="Adrenaline",
        value=(
            f"🔴 {session.A.boxer.name}:  `[{_bar(session.A.adrenaline)}]`  {int(session.A.adrenaline)}%\n"
            f"🔵 {session.B.boxer.name}:  `[{_bar(session.B.adrenaline)}]`  {int(session.B.adrenaline)}%"
        ),
        inline=False
    )

    # ---- Highlight image selection (safe defaults) ----
    file_to_send: Optional[discord.File] = None
    url: Optional[str] = None

    active_specs = []
    if session.A.special_name:
        active_specs.append(f"🔴 {session.A.boxer.name}: {session.A.special_name} ({session.A.special_turns})")
    if session.B.special_name:
        active_specs.append(f"🔵 {session.B.boxer.name}: {session.B.special_name} ({session.B.special_turns})")
    emb.add_field(name="Specials", value=(" • ".join(active_specs) if active_specs else "—"), inline=False)

    emb.add_field(
        name="Warnings",
        value=f"🔴 {session.A.boxer.name}: {session.A.warnings} • "
              f"🔵 {session.B.boxer.name}: {session.B.warnings}",
        inline=False
    )
    emb.add_field(
        name="Knockdowns",
        value=f"🔴 {session.A.boxer.name}: R{session.kd_round['A']}/F{session.kd_total['A']}  •  "
              f"🔵 {session.B.boxer.name}: R{session.kd_round['B']}/F{session.kd_total['B']}",
        inline=False
    )

    # ---- Highlight selection ----
    highlight_ev = None
    hits = [e for e in round_events if e.get("outcome") == "hit"]
    low_blows = [e for e in round_events if e.get("outcome") == "low_blow"]
    misses = [e for e in round_events if e.get("outcome") == "miss"]
    cmiss = [e for e in round_events if e.get("outcome") == "critical_miss"]

    if hits:
        highlight_ev = max(hits, key=lambda e: e.get("damage", 0))
        # If it produced a KD, force KD art
        if highlight_ev.get("knockdown"):
            highlight_ev = dict(highlight_ev)
            highlight_ev["gif_type"] = "knockdown"
        title = f"{highlight_ev['attacker']} lands a {highlight_ev.get('hit_type', 'shot')}!"
        desc = f"→ {highlight_ev['defender']} for **{highlight_ev.get('damage', 0)}** to {highlight_ev.get('location', 'head')}"
        emb.insert_field_at(0, name="Round Highlight", value=f"{title}\n{desc}", inline=False)
    elif low_blows:
        highlight_ev = dict(low_blows[0], gif_type="low_blow", hit_type="low_blow")
        emb.insert_field_at(0, name="Round Highlight", value=f"{highlight_ev['attacker']} goes LOW — warning!",
                            inline=False)
    elif misses:
        highlight_ev = dict(misses[0], hit_type="miss")
        emb.insert_field_at(0, name="Round Highlight", value=f"{highlight_ev['attacker']} whiffs — clean miss.",
                            inline=False)
    elif cmiss:
        highlight_ev = dict(cmiss[0], hit_type="miss")
        emb.insert_field_at(0, name="Round Highlight", value=f"{highlight_ev['attacker']} slips badly — critical miss!",
                            inline=False)
    else:
        emb.insert_field_at(0, name="Round Highlight", value="Cagey exchanges.", inline=False)

    # Route to a GIF (jab/cross/straight/hook/uppercut/miss/low_blow/knockdown supported)
    file_to_send = None
    url = None
    if highlight_ev:
        file_to_send, url = _highlight_gif_for_event(session, highlight_ev)

    if not file_to_send and not url:
        mkey = matchup_key(session.red_raw, session.blue_raw)
        local_path = ROUND_GIF_LOCAL.get(mkey)
        if local_path and os.path.exists(local_path):
            file_to_send = discord.File(local_path, filename=os.path.basename(local_path))
        else:
            url = ROUND_GIF_URL.get(mkey)

        # ---- Send embed + image ----
    if file_to_send is not None:
        # Use the provided filename property (no .fp access needed)
        emb.set_image(url=f"attachment://{file_to_send.filename}")
        await interaction.followup.send(embed=emb, file=file_to_send)
    else:
        if url:
            emb.set_image(url=url)
        await interaction.followup.send(embed=emb)
        await maybe_post_crowd_reaction(interaction, session, session.current_round, round_events)
