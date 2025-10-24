"""Project-wide configuration helpers and constants for BoxingBot.

This module centralises filesystem paths for assets, configurable
settings and assorted lookup tables used by the application.  The values
mirror the structure described in the original project notes while
adding a small amount of robustness around path discovery so that assets
can be located regardless of where the package is imported from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

_GRAPHICS_DIR_NAME = "graphics"
_BOXINGBOT_ROOT_ENV = "BOXINGBOT_ROOT"


def _discover_root(start: Path) -> Path:
    """Return the best-guess project root directory.

    The optional ``BOXINGBOT_ROOT`` environment variable can be supplied
    to override the discovery mechanism.  Otherwise we walk up the
    directory tree looking for a folder that contains the expected
    ``graphics`` asset directory.  If nothing matches we fall back to the
    directory that contains ``config.py`` so that relative paths remain
    stable even when the full asset set is unavailable (e.g. in tests).
    """

    override = os.getenv(_BOXINGBOT_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()

    for candidate in (start, *start.parents):
        if (candidate / _GRAPHICS_DIR_NAME).exists():
            return candidate

    return start


# Base directories -------------------------------------------------------

_MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = _discover_root(_MODULE_DIR)
ASSETS_DIR = ROOT_DIR / _GRAPHICS_DIR_NAME
MUSIC_DIR = ASSETS_DIR / "music"
IMAGES_DIR = ASSETS_DIR / "images"
GRAPHICS_DIR = _GRAPHICS_DIR_NAME

MUSIC_DIR_STR = str(MUSIC_DIR)
IMAGES_DIR_STR = str(IMAGES_DIR)


# Settings ---------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    DB_FILE: str = str(ROOT_DIR / "boxing_db.json")
    MAX_TOTAL_BONUS: int = 5
    MIN_PER_STAT: int = 0
    MAX_PER_STAT: int = 100
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    EXCHANGES_PER_BOXER: int = 3


SETTINGS = Settings()


# Asset locations --------------------------------------------------------

COMMENTARY_DIR = os.path.join(GRAPHICS_DIR, "commentary")
PROMO_DIR = os.path.join(GRAPHICS_DIR, "promo")
PROMO_MUSIC_DIR = os.path.join(PROMO_DIR, "music")
PROMO_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
CROWD_AMBIENT = os.path.join(PROMO_MUSIC_DIR, "ambient", "crowd.mp3")
FFMPEG_PATH = SETTINGS.FFMPEG_PATH

valid_types = {"glancing", "jab", "cross", "hook", "uppercut", "miss", "low_blow"}


# Generic round GIFs by matchup (MM, MF, FF)
ROUND_GIF_LOCAL = {
    "MM": "graphics/round_mm.gif",
    "MF": "graphics/round_mf.gif",
    "FF": "graphics/round_ff.gif",
}
ROUND_GIF_URL = {
    "MM": "",
    "MF": "",
    "FF": "",
}

# Ring GIF on pre-fight intro
RING_GIF_LOCAL = "graphics/ring.gif"
RING_GIF_URL = ""

# Round highlight GIFs (optional; leave missing keys to fall back)
# Keys: (matchup, corner, hit_type)
ROUND_HIGHLIGHT_GIF_LOCAL: Dict[Tuple[str, str, str], str] = {}

ROUND_HIGHLIGHT_GIF_URL: Dict[Tuple[str, str, str], str] = {}

# --- Judge decision thumbnails (per-judge) ---

# Put your PNGs under graphics/judges/
# Suggested names:
#   graphics/judges/thedude_red.png
#   graphics/judges/thedude_blue.png
#   graphics/judges/thedude_draw.png
#   graphics/judges/walter_red.png ... etc.
#   graphics/judges/generic_red.png (fallbacks)
#   graphics/judges/generic_blue.png
#   graphics/judges/generic_draw.png

JUDGE_CARD_PNG_LOCAL = {
    "Red": {
        "TheDude": "graphics/judges/thedude_red.png",
        "Walter Sobchak": "graphics/judges/walter_red.png",
        "Donny Kerabatsos": "graphics/judges/donny_red.png",
        "default": "graphics/judges/generic_red.png",
    },
    "Blue": {
        "TheDude": "graphics/judges/thedude_blue.png",
        "Walter Sobchak": "graphics/judges/walter_blue.png",
        "Donny Kerabatsos": "graphics/judges/donny_blue.png",
        "default": "graphics/judges/generic_blue.png",
    },
    "Draw": {
        "TheDude": "graphics/judges/thedude_draw.png",
        "Walter Sobchak": "graphics/judges/walter_draw.png",
        "Donny Kerabatsos": "graphics/judges/donny_draw.png",
        "default": "graphics/judges/generic_draw.png",
    },
}

# Optional URL fallbacks (only used if the local file isn’t found)
JUDGE_CARD_PNG_URL = {
    "Red": {
        "TheDude": "",
        "Walter Sobchak": "",
        "Donny Kerabatsos": "",
        "default": "",  # e.g. "https://…/generic_red.png"
    },
    "Blue": {
        "TheDude": "",
        "Walter Sobchak": "",
        "Donny Kerabatsos": "",
        "default": "",
    },
    "Draw": {
        "TheDude": "",
        "Walter Sobchak": "",
        "Donny Kerabatsos": "",
        "default": "",
    },
}


# Finish announcement GIFs: (matchup, winner corner, result)
FINISH_GIF_LOCAL: Dict[Tuple[str, str, str], str] = {}
FINISH_GIF_URL: Dict[Tuple[str, str, str], str] = {}

# ===================== Crowd & Momentum =====================
# Momentum runs from -100 (Blue surging) to +100 (Red surging).
MOMENTUM_MAX = 100
MOMENTUM_HIT_GAIN = 6  # base gain for a clean hit
MOMENTUM_BIG_HIT_BONUS = 4  # extra when damage >= 14
MOMENTUM_KD_BONUS = 12  # extra on knockdown
MOMENTUM_BLOCKED_PENALTY = -3  # small loss when a shot is fully blocked
MOMENTUM_CRITMISS_SWING = 6  # swings against attacker on crit miss
MOMENTUM_LOW_BLOW_SWING = 5  # swings against the fouler


def clamp(value: int, minimum: int, maximum: int) -> int:
    """Clamp ``value`` to be within the inclusive range ``[minimum, maximum]``."""

    return minimum if value < minimum else maximum if value > maximum else value


# Flavor lines keyed by 'event' + optional 'tier'
# ===================== Crowd Reactions =====================
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


__all__ = [
    "ROOT_DIR",
    "ASSETS_DIR",
    "MUSIC_DIR",
    "IMAGES_DIR",
    "GRAPHICS_DIR",
    "MUSIC_DIR_STR",
    "IMAGES_DIR_STR",
    "Settings",
    "SETTINGS",
    "COMMENTARY_DIR",
    "PROMO_DIR",
    "PROMO_MUSIC_DIR",
    "PROMO_IMG_EXTS",
    "CROWD_AMBIENT",
    "FFMPEG_PATH",
    "valid_types",
    "ROUND_GIF_LOCAL",
    "ROUND_GIF_URL",
    "RING_GIF_LOCAL",
    "RING_GIF_URL",
    "ROUND_HIGHLIGHT_GIF_LOCAL",
    "ROUND_HIGHLIGHT_GIF_URL",
    "JUDGE_CARD_PNG_LOCAL",
    "JUDGE_CARD_PNG_URL",
    "FINISH_GIF_LOCAL",
    "FINISH_GIF_URL",
    "MOMENTUM_MAX",
    "MOMENTUM_HIT_GAIN",
    "MOMENTUM_BIG_HIT_BONUS",
    "MOMENTUM_KD_BONUS",
    "MOMENTUM_BLOCKED_PENALTY",
    "MOMENTUM_CRITMISS_SWING",
    "MOMENTUM_LOW_BLOW_SWING",
    "clamp",
    "CROWD_REACTIONS",
]