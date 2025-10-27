import os
from typing import List
from ..config import MUSIC_DIR  # you already have this constant
# if not, set: MUSIC_DIR = os.path.join("graphics", "music")

def list_music_files() -> List[str]:
    """Return mp3 files in graphics/music as absolute paths."""
    if not os.path.isdir(MUSIC_DIR):
        return []
    out = []
    for fname in os.listdir(MUSIC_DIR):
        if fname.lower().endswith(".mp3"):
            out.append(os.path.join(MUSIC_DIR, fname))
    return sorted(out, key=str.casefold)

def ensure_music_dir():
    os.makedirs(MUSIC_DIR, exist_ok=True)

def normalize_music_input(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    base = os.path.basename(s)
    if not base.lower().endswith(".mp3"): base += ".mp3"
    ensure_music_dir()
    return os.path.join(MUSIC_DIR, base)

def display_music_label(path: str) -> str:
    base = os.path.basename(path or "")
    name, _ = os.path.splitext(base)
    return name or "—"