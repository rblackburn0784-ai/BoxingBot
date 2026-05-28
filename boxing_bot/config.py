# boxing_bot/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

# ──────────────────────────────
# Project roots
#   ROOT_DIR = project root (one level above the package)
#   GRAPHICS_DIR = where your images/gifs/music live (./graphics)
# ──────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[1]
GRAPHICS_DIR = ROOT_DIR / "graphics"

# ──────────────────────────────
# Media directories (all Path objects)
# ──────────────────────────────


PROMO_DIR = GRAPHICS_DIR / "promo"
COMMENTARY_DIR = PROMO_DIR / "commentary"
PROMO_MUSIC_DIR = PROMO_DIR / "music"

MUSIC_DIR = GRAPHICS_DIR / "music"
CROWD_AMBIENT = MUSIC_DIR / "ambient" / "crowd.mp3"

JUDGES_DIR = GRAPHICS_DIR / "judges"
RING_DIR = GRAPHICS_DIR
ROUNDS_DIR = PROMO_DIR / "rounds"

# Optional legacy alias if older code expects this name:
ASSETS_DIR = GRAPHICS_DIR  # keep for compatibility

# ──────────────────────────────
# File extensions / settings
# Use a tuple for endswith(), e.g. name.lower().endswith(PROMO_IMG_EXTS)
# ──────────────────────────────
PROMO_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# ──────────────────────────────
# GIFs (Paths) – prefer local paths; URLs can be added if you host them
# ──────────────────────────────
RING_GIF_LOCAL = GRAPHICS_DIR / "ring.gif"
RING_GIF_URL = ""  # fill in if hosted

# Round card GIFs by matchup type (MM/MF/FF). If you have per-round art, map it here.
ROUND_GIF_LOCAL = {
    "MM": GRAPHICS_DIR / "round_mm.gif",
    "MF": GRAPHICS_DIR / "round_mf.gif",
    "FF": GRAPHICS_DIR / "round_ff.gif",
}
ROUND_GIF_URL = {"MM": "", "MF": "", "FF": ""}

# Per-event highlight GIFs
from typing import Dict, Tuple
ROUND_HIGHLIGHT_DIR = ROUNDS_DIR

ROUND_HIGHLIGHT_GIF_LOCAL: Dict[Tuple[str, str, str], Path] = {
    # (matchup, corner, type) -> file
    ("MM","Red","jab"):       ROUND_HIGHLIGHT_DIR / "mm_red_jab.gif",
    ("MM","Blue","jab"):      ROUND_HIGHLIGHT_DIR / "mm_blue_jab.gif",
    ("MM","Red","hook"):      ROUND_HIGHLIGHT_DIR / "mm_red_hook.gif",
    ("MM","Blue","hook"):     ROUND_HIGHLIGHT_DIR / "mm_blue_hook.gif",
    ("MM","Red","uppercut"):  ROUND_HIGHLIGHT_DIR / "mm_red_uppercut.gif",
    ("MM","Blue","uppercut"): ROUND_HIGHLIGHT_DIR / "mm_blue_uppercut.gif",
    ("MM","Red","cross"):     ROUND_HIGHLIGHT_DIR / "mm_red_cross.gif",
    ("MM","Blue","cross"):    ROUND_HIGHLIGHT_DIR / "mm_blue_cross.gif",
    ("MM","Red","miss"):      ROUND_HIGHLIGHT_DIR / "mm_red_miss.gif",
    ("MM","Blue","miss"):     ROUND_HIGHLIGHT_DIR / "mm_blue_miss.gif",
    ("MM","Red","low_blow"):  ROUND_HIGHLIGHT_DIR / "mm_red_low_blow.gif",
    ("MM","Blue","low_blow"): ROUND_HIGHLIGHT_DIR / "mm_blue_low_blow.gif",
    ("MM","Red","knockdown"): ROUND_HIGHLIGHT_DIR / "mm_red_knockdown.gif",
    ("MM","Blue","knockdown"):ROUND_HIGHLIGHT_DIR / "mm_blue_knockdown.gif",

    ("MF","Red","jab"):       ROUND_HIGHLIGHT_DIR / "mf_red_jab.gif",
    ("MF","Blue","jab"):      ROUND_HIGHLIGHT_DIR / "mf_blue_jab.gif",
    ("MF","Red","hook"):      ROUND_HIGHLIGHT_DIR / "mf_red_hook.gif",
    ("MF","Blue","hook"):     ROUND_HIGHLIGHT_DIR / "mf_blue_hook.gif",
    ("MF","Red","uppercut"):  ROUND_HIGHLIGHT_DIR / "mf_red_uppercut.gif",
    ("MF","Blue","uppercut"): ROUND_HIGHLIGHT_DIR / "mf_blue_uppercut.gif",
    ("MF","Red","cross"):     ROUND_HIGHLIGHT_DIR / "mf_red_cross.gif",
    ("MF","Blue","cross"):    ROUND_HIGHLIGHT_DIR / "mf_blue_cross.gif",
    ("MF","Red","miss"):      ROUND_HIGHLIGHT_DIR / "mf_red_miss.gif",
    ("MF","Blue","miss"):     ROUND_HIGHLIGHT_DIR / "mf_blue_miss.gif",
    ("MF","Red","low_blow"):  ROUND_HIGHLIGHT_DIR / "mf_red_low_blow.gif",
    ("MF","Blue","low_blow"): ROUND_HIGHLIGHT_DIR / "mf_blue_low_blow.gif",
    ("MF","Red","knockdown"): ROUND_HIGHLIGHT_DIR / "mf_red_knockdown.gif",
    ("MF","Blue","knockdown"):ROUND_HIGHLIGHT_DIR / "mf_blue_knockdown.gif",

    ("FF","Red","jab"):       ROUND_HIGHLIGHT_DIR / "ff_red_jab.gif",
    ("FF","Blue","jab"):      ROUND_HIGHLIGHT_DIR / "ff_blue_jab.gif",
    ("FF","Red","hook"):      ROUND_HIGHLIGHT_DIR / "ff_red_hook.gif",
    ("FF","Blue","hook"):     ROUND_HIGHLIGHT_DIR / "ff_blue_hook.gif",
    ("FF","Red","uppercut"):  ROUND_HIGHLIGHT_DIR / "ff_red_uppercut.gif",
    ("FF","Blue","uppercut"): ROUND_HIGHLIGHT_DIR / "ff_blue_uppercut.gif",
    ("FF","Red","cross"):     ROUND_HIGHLIGHT_DIR / "ff_red_cross.gif",
    ("FF","Blue","cross"):    ROUND_HIGHLIGHT_DIR / "ff_blue_cross.gif",
    ("FF","Red","miss"):      ROUND_HIGHLIGHT_DIR / "ff_red_miss.gif",
    ("FF","Blue","miss"):     ROUND_HIGHLIGHT_DIR / "ff_blue_miss.gif",
    ("FF","Red","low_blow"):  ROUND_HIGHLIGHT_DIR / "ff_red_low_blow.gif",
    ("FF","Blue","low_blow"): ROUND_HIGHLIGHT_DIR / "ff_blue_low_blow.gif",
    ("FF","Red","knockdown"): ROUND_HIGHLIGHT_DIR / "ff_red_knockdown.gif",
    ("FF","Blue","knockdown"):ROUND_HIGHLIGHT_DIR / "ff_blue_knockdown.gif",
}
ROUND_HIGHLIGHT_GIF_URL: Dict[Tuple[str, str, str], str] = {}

# Judges
JUDGE_CARD_PNG_LOCAL = {
    "Red": {
        "TheDude": JUDGES_DIR / "thedude_red.png",
        "Walter Sobchak": JUDGES_DIR / "walter_red.png",
        "Donny Kerabatsos": JUDGES_DIR / "donny_red.png",
        "default": JUDGES_DIR / "generic_red.png",
    },
    "Blue": {
        "TheDude": JUDGES_DIR / "thedude_blue.png",
        "Walter Sobchak": JUDGES_DIR / "walter_blue.png",
        "Donny Kerabatsos": JUDGES_DIR / "donny_blue.png",
        "default": JUDGES_DIR / "generic_blue.png",
    },
    "Draw": {
        "TheDude": JUDGES_DIR / "thedude_draw.png",
        "Walter Sobchak": JUDGES_DIR / "walter_draw.png",
        "Donny Kerabatsos": JUDGES_DIR / "donny_draw.png",
        "default": JUDGES_DIR / "generic_draw.png",
    },
}
JUDGE_CARD_PNG_URL = {
    "Red": {"TheDude": "", "Walter Sobchak": "", "Donny Kerabatsos": "", "default": ""},
    "Blue": {"TheDude": "", "Walter Sobchak": "", "Donny Kerabatsos": "", "default": ""},
    "Draw": {"TheDude": "", "Walter Sobchak": "", "Donny Kerabatsos": "", "default": ""},
}

# Finish announcement GIFs (optional, keep empty until you add files)
FINISH_GIF_LOCAL: Dict[Tuple[str,str,str], Path] = {}
FINISH_GIF_URL: Dict[Tuple[str,str,str], str] = {}

# ──────────────────────────────
# Audio / ffmpeg
# ──────────────────────────────
FFMPEG_PATH = os.getenv("FFMPEG_PATH", r"C:\ffmpeg\bin\ffmpeg.exe")

# ──────────────────────────────
# Game settings
# ──────────────────────────────
@dataclass(frozen=True)
class Settings:
    DB_FILE: str = str(ROOT_DIR / "boxing_db.json")
    MAX_TOTAL_BONUS: int = 5
    MIN_PER_STAT: int = 0
    MAX_PER_STAT: int = 100
    FFMPEG_PATH: str = FFMPEG_PATH
    EXCHANGES_PER_BOXER: int = 3

SETTINGS = Settings()

# ──────────────────────────────
# Momentum / crowd (constants only)
# ──────────────────────────────
MOMENTUM_MAX = 100
MOMENTUM_HIT_GAIN = 6
MOMENTUM_BIG_HIT_BONUS = 4
MOMENTUM_KD_BONUS = 12
MOMENTUM_BLOCKED_PENALTY = -3
MOMENTUM_CRITMISS_SWING = 6
MOMENTUM_LOW_BLOW_SWING = 5

valid_types = {"glancing","jab","cross","hook","uppercut","miss","low_blow","knockdown"}

CROWD_REACTIONS = {
    "kd": [
        "💥 The crowd ERUPTS after that knockdown!",
        "💫 Down goes {defender}! You could hear that from the cheap seats!",
        "😱 {attacker} just folded {defender} like a lawn chair!",
    ],
    "big_hit": [
        "🔥 Thunderous {hit_type} from {attacker} — the arena loved that!",
        "🥵 {defender} felt that one — crowd’s on their feet!",
        "⚡ Cracking shot by {attacker}!",
    ],
    "low_blow": [
        "🚫 Oooo, that looked low… the crowd’s not happy!",
        "🙈 Ref steps in after the low blow — chorus of boos!",
        "🛑 Mind the belt line! Tension rising!",
    ],
    "crit_miss": [
        "😬 Whoops — {attacker} slipped! A few gasps from the stands.",
        "🤦 A swing and a miss! Crowd groans.",
        "😵 {attacker} overcommits and stumbles — oohs from ringside!",
    ],
    "big_block": [
        "🧱 Great defense! Nice block by {defender}.",
        "🙅 Textbook guard — {defender} shuts it down.",
        "🛡️ Crowd applauds that tidy block!",
    ],
    "momentum": [
        "⏫ Momentum shifting to the {corner} corner!",
        "📈 {attacker} is cooking — crowd sensing a swing!",
        "🌪️ Pressure building from {attacker}!",
    ],
}

# ──────────────────────────────
# Ensure folders exist (safe no-ops)
# ──────────────────────────────
def _ensure_dirs() -> None:
    dirs = {
        GRAPHICS_DIR, PROMO_DIR, COMMENTARY_DIR, MUSIC_DIR, JUDGES_DIR, ROUNDS_DIR,
        RING_DIR, ROUND_HIGHLIGHT_DIR,
    }
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

_ensure_dirs()

# ──────────────────────────────
# Optional: quick validator for highlight assets
# ──────────────────────────────
def debug_check_highlight_files() -> None:
    missing = [(k, p) for k, p in ROUND_HIGHLIGHT_GIF_LOCAL.items() if not p.exists()]
    print(f"[round_gif] base={ROUND_HIGHLIGHT_DIR}")
    if missing:
        for k, p in missing:
            print(f"[round_gif] MISSING {k} -> {p}")
    else:
        print("[round_gif] all mapped highlight GIFs found")
