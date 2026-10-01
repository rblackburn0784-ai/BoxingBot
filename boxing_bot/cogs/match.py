# boxing_bot/cogs/match.py

import os
import random
import secrets
import functools
import discord
import asyncio
from typing import Optional, List
from discord import app_commands
from discord.ext import commands
from pathlib import Path
from ..models import FightSession, FighterState
from ..services.roster import get_boxer, list_boxers
from ..services.stats import effective_boxer
from ..services.combat import (
    corner_assignments,
    run_one_round,
    _crowd_round_reset,
    _ensure_crowd_state,
    maybe_post_reaction_and_audio,
    finalize_if_done,
    send_round_card,
    send_points_decision,
    send_finish_announcement,
    compute_scorecards,
    maybe_post_crowd_reaction,
)
from ..services.presentation import momentum_bar

from ..services.state import SESSIONS, save_sessions, get_fight_lock
from ..services.voice import ensure_voice, play_clip
from ..services.music import display_music_label
from ..config import (
    RING_GIF_LOCAL,
    RING_GIF_URL,
    ROUND_GIF_LOCAL,
    ROUND_GIF_URL, PROMO_DIR, PROMO_IMG_EXTS, FFMPEG_PATH,
    CROWD_REACTIONS,        # already there
    COMMENTARY_DIR, PROMO_MUSIC_DIR        # ← add this
)

# ----- Local helpers (presentation) -----

def _hp_blocks(hp: int, max_hp: int = 100) -> str:
    hp = max(0, min(max_hp, int(hp)))
    blocks = hp // 10  # 10 HP per block
    return "█" * blocks + "░" * (10 - blocks)

async def _send_short_status(interaction: discord.Interaction, s: FightSession):
    emb = discord.Embed(
        title=f"Round {s.current_round} — Live",
        description=f"Momentum {momentum_bar(s.momentum, 20)}",
        color=discord.Color.dark_teal()
    )
    emb.add_field(
        name=f"🔴 {s.A.boxer.name} (Red)",
        value=f"`{_hp_blocks(s.A.hp)}`  • Adr {int(s.A.adrenaline)}%",
        inline=False
    )
    emb.add_field(
        name=f"🔵 {s.B.boxer.name} (Blue)",
        value=f"`{_hp_blocks(s.B.hp)}`  • Adr {int(s.B.adrenaline)}%",
        inline=False
    )
    await interaction.followup.send(embed=emb)

# ── Exchange text builder (no momentum/HP here) ────────────────────────────
def _brief_exchange_text(ev: dict) -> str:
    a = ev.get("attacker", "Attacker")
    d = ev.get("defender", "Defender")
    oc = ev.get("outcome", "")
    dmg = ev.get("damage")
    ht  = ev.get("hit_type") or ev.get("type")
    loc = ev.get("location")

    if oc == "hit":
        parts = [f"{a} lands"]
        if ht:  parts.append(f"a *{ht}*")
        if loc: parts.append(f"to **{loc}**")
        if dmg is not None: parts.append(f"for **{int(dmg)}**")
        parts.append(f"on {d}")
        if ev.get("knockdown"): parts.append("— **knockdown!**")
        return " ".join(parts)
    if oc == "miss":
        return f"{a} overreaches and misses {d}"
    if oc == "critical_miss":
        return f"{a} whiffs badly — **critical miss!**"
    if oc == "low_blow":
        return f"{a} strays low — **warning issued**"
    # fallback
    return f"{a} and {d} trade."

# === Commentary clip selection =================================================

# Known, generic clip names you have in the folder (from your screenshot):
# KD.mp3, Low_Blow.mp3, Swing_Miss.mp3, Tidy_Block.mp3, Mind_Belt.mp3
# Red_* and Blue_* variants for: Jab, Cross, hook, Uppercut, Block, Guard, Slip, Pressure, Momentum, OverCommits, Cooking, Felt, Fold, Down, Fely (typo?), etc.

# === Crowd ambience loop state (per channel) ===
CROWD_ACTIVE: dict[int, bool] = {}
CROWD_TASKS: dict[int, asyncio.Task] = {}

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a")  # already present above; ok to reuse

def _find_crowd_ambience_file() -> Optional[str]:
    music_dir = _resolve_music_dir()
    preferred = [music_dir / "crowd_ambience.mp3", music_dir / "crowd_ambience.wav"]
    fallbacks = [
        music_dir / "ambient" / "crowd_ambience.mp3",
        music_dir / "ambient" / "crowd_ambience.wav",
        music_dir / "ambient" / "crowd.mp3",
        music_dir / "ambient" / "crowd.wav",
        music_dir / "crowd.mp3",
        music_dir / "crowd.wav",
    ]
    for p in preferred + fallbacks:
        if p.exists():
            return str(p)
    return None

def _find_fight_crowd_file() -> Optional[str]:
    """Loop during the fight."""
    music_dir = _resolve_music_dir()
    preferred = [music_dir / "crowd.mp3", music_dir / "crowd.wav"]
    fallbacks = [
        music_dir / "ambient" / "crowd.mp3",
        music_dir / "ambient" / "crowd.wav",
    ]
    for p in preferred + fallbacks:
        if p.exists():
            return str(p)
    return None


async def _crowd_music_loop(interaction: discord.Interaction, track_path: str):
    """
    Loop crowd ambience while:
      - CROWD_ACTIVE[channel] is True
      - voice is connected
    If another clip plays (fighter intro, commentary, etc.), we wait until the
    voice client is free, then resume the ambience.
    """
    vc = await _ensure_voice(interaction)
    if not vc:
        return
    ch_id = interaction.channel_id

    while CROWD_ACTIVE.get(ch_id, False):
        try:
            # If something else is playing (intros, commentary), wait and retry
            if vc.is_playing():
                await asyncio.sleep(0.5)
                continue
            # Play full file once (no fade; we want seamless loop)
            audio = discord.FFmpegPCMAudio(
                track_path,
                executable=FFMPEG_PATH,
                before_options="-nostdin",
                options="-vn"
            )
            vc.play(audio)
            # Sleep while it's playing or until we’re told to stop
            while CROWD_ACTIVE.get(ch_id, False) and vc.is_playing():
                await asyncio.sleep(0.5)
        except Exception:
            # Don’t die on transient FFmpeg/voice hiccups
            await asyncio.sleep(1.0)

async def stop_crowd_ambience(interaction: discord.Interaction):
    ch_id = interaction.channel_id
    CROWD_ACTIVE[ch_id] = False
    task = CROWD_TASKS.pop(ch_id, None)
    if task and not task.done():
        task.cancel()
    # If ambience is currently the thing playing, stop it
    vc = interaction.guild.voice_client if interaction.guild else None
    if vc and vc.is_connected() and vc.is_playing():
        vc.stop()

def _commentary_exists(name: str) -> Optional[str]:
    """Return a full path if file exists in COMMENTARY_DIR, else None."""
    path = os.path.join(COMMENTARY_DIR, name)
    return path if os.path.exists(path) else None

def _corner_from_names(session: FightSession, fighter_name: str) -> str:
    return "Red" if session.A.boxer.name == fighter_name else "Blue"

def _title_case_hit(hit: Optional[str]) -> Optional[str]:
    if not hit: return None
    # folder uses 'hook' lower-case in screenshot; we normalize to first upper except hook
    mapping = {"jab": "Jab", "cross": "Cross", "hook": "Hook", "uppercut": "Uppercut", "glancing":"Glancing"}
    return mapping.get(hit.lower())

def _resolve_commentary_file(session: FightSession, ev: dict, tags: list[str]) -> Optional[str]:
    """
    Map crowd tags + event details to best-matching mp3 filename.
    Preference order: KD / Low_Blow / (hit-type by corner) / block / miss / slip / momentum / generic.
    """
    corner = _corner_from_names(session, ev.get("attacker"))
    hit = _title_case_hit(ev.get("hit_type"))
    blocked = bool(ev.get("blocked"))
    block_ok = ev.get("block_success")

    tag_text = " ".join(tags)

    # 1) Knockdown
    if "KD_" in tag_text:
        p = _commentary_exists("KD.mp3")
        if p: return p

    # 2) Low blow
    if "LOWBLOW_" in tag_text or ev.get("outcome") == "low_blow":
        p = _commentary_exists("Low_Blow.mp3")
        if p: return p

    # 3) Big hit → try per-corner + hit-type: Red_Uppercut.mp3 etc.
    if "BIG_" in tag_text or (ev.get("outcome") == "hit" and ev.get("damage",0) >= 14):
        if hit:
            p = _commentary_exists(f"{corner}_{hit}.mp3")
            if p: return p
        # fallbacks if no exact hit-type file
        p = _commentary_exists(f"{corner}_Pressure.mp3")
        if p: return p
        p = _commentary_exists(f"{corner}_Cooking.mp3")
        if p: return p

    # 4) Normal hit → prefer per-corner + hit-type
    if ev.get("outcome") == "hit":
        if hit:
            p = _commentary_exists(f"{corner}_{hit}.mp3")
            if p: return p
        # Block commentary if present
        if blocked:
            if block_ok is True:
                p = _commentary_exists("Tidy_Block.mp3") or _commentary_exists(f"{corner}_Block.mp3")
                if p: return p
            else:
                p = _commentary_exists(f"{corner}_Block.mp3")
                if p: return p
        # generic touch
        p = _commentary_exists(f"{corner}_Felt.mp3") or _commentary_exists(f"{corner}_Guard.mp3")
        if p: return p

    # 5) Miss / Critical miss
    if ev.get("outcome") in ("miss","critical_miss"):

        # Try generic swing miss first
        p = _commentary_exists("Swing_Miss.mp3")
        if p: return p
        # Then a slip flavor (defender makes him miss)
        p = _commentary_exists(f"{_corner_from_names(session, ev.get('defender'))}_Slip.mp3")
        if p: return p

    # 6) Momentum call (if you keep a momentum eruption tag; optional)
    if "MOMENTUM_" in tag_text:
        p = _commentary_exists(f"{corner}_Momentum.mp3")
        if p: return p

    # 7) Down / Fold flavors (if someone “folds” or is “down” by damage—optional heuristics)
    if ev.get("knockdown"):
        p = _commentary_exists(f"{_corner_from_names(session, ev.get('defender'))}_Down.mp3")
        if p: return p

    # 8) Generic last-resort
    return _commentary_exists("Mind_Belt.mp3")  # harmless short filler if present

async def play_commentary_for_event(interaction: discord.Interaction, session: FightSession, ev: dict):
    """Play a short commentary clip if a crowd line was posted."""
    try:
        tags = ev.get("crowd_tags") or []
        if not tags:
            return
        path = _resolve_commentary_file(session, ev, tags)
        if not path:
            return

        vc = await ensure_voice(interaction)
        if not vc:
            return

        # Let commentary finish naturally; if another clip is already playing,
        # skip this bite rather than cutting the current one off mid-sentence.
        await play_clip(vc, path, seconds=None, interrupt=True)
        # tiny gap to avoid stepping on the next exchange by accident
        await asyncio.sleep(0.05)
    except Exception as e:
        print(f"[commentary] failed: {e}")

# ── Crowd selection (same anti-spam logic as earlier) ──────────────────────
_CROWD_FAMILY = {
    "KD_RED": "KD", "KD_BLUE": "KD",
    "BIG_RED": "BIG", "BIG_BLUE": "BIG",
    "CRITMISS_RED": "CRITMISS", "CRITMISS_BLUE": "CRITMISS",
    "LOWBLOW_RED": "LOWBLOW", "LOWBLOW_BLUE": "LOWBLOW",
}
_CROWD_PRIORITY = ["KD_RED", "KD_BLUE", "BIG_RED", "BIG_BLUE",
                   "CRITMISS_RED", "CRITMISS_BLUE", "LOWBLOW_RED", "LOWBLOW_BLUE"]

def _pick_crowd_line_for_event(s: FightSession, ev: dict) -> Optional[str]:
    # make sure per-round state exists
    _ensure_crowd_state(s)

    tags = ev.get("crowd_tags") or []
    if not tags:
        return None

    # sort by our global priority
    tags_sorted = sorted(tags, key=lambda t: _CROWD_PRIORITY.index(t) if t in _CROWD_PRIORITY else 999)

    for t in tags_sorted:
        fam = _CROWD_FAMILY.get(t)
        if fam and fam in getattr(s, "_crowd_seen_families", set()):
            continue

        pool = CROWD_REACTIONS.get(t) or []
        if not pool:
            continue

        # avoid repeating the last exact line if possible
        last = getattr(s, "_crowd_last_line", "")
        if len(pool) > 1:
            choices = [p for p in pool if p != last] or pool
        else:
            choices = pool

        cand = random.choice(choices)
        if fam:
            s._crowd_seen_families.add(fam)
        s._crowd_last_line = cand
        return cand

    return None

def _crowd_round_reset(s: FightSession):
    s._crowd_seen_families = set()
    s._crowd_last_line = ""


async def _send_exchange_note(
    interaction: discord.Interaction,
    s: FightSession,
    ev: dict,
    crowd_line: Optional[str] = None,
):
    body = _brief_exchange_text(ev)
    desc_lines = []
    if crowd_line:
        desc_lines.append(crowd_line)
    desc_lines.append(f"**Exchange:** {body}")

    emb = discord.Embed(
        title=f"Round {s.current_round} — Exchange",
        description="\n".join(desc_lines),
        color=discord.Color.dark_teal()
    )
    await interaction.followup.send(embed=emb)

# ⬇️ helper: map tags to lines and send them immediately
async def _send_crowd_lines_for_event(interaction: discord.Interaction, s: FightSession, ev: dict):
    line = _pick_crowd_line_for_event(s, ev)
    if line:
        await interaction.followup.send(line)


# === Promo state (per channel) ===
PROMO_ACTIVE: dict[int, bool] = {}
PROMO_TASKS: dict[int, asyncio.Task] = {}

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a")

def _resolve_music_dir() -> Path:
    """
    Return the best guess music directory, without double-joining segments.
    Prefers an existing directory among several sensible candidates.
    """
    pkg_root = Path(__file__).resolve().parents[2]  # project root
    raw = Path(PROMO_MUSIC_DIR)

    candidates: list[Path] = []

    # 1) If PROMO_MUSIC_DIR is absolute, try it as-is.
    if raw.is_absolute():
        candidates.append(raw)
    else:
        # 2) Try relative to the package root (project root)
        candidates.append((pkg_root / raw).resolve())
        # 3) Try relative to current working dir (just in case you run from a different cwd)
        candidates.append((Path.cwd() / raw).resolve())

    # 4) Also try common defaults if the above don’t exist
    candidates.append((pkg_root / "graphics" / "promo" / "music").resolve())
    candidates.append((pkg_root / "graphics" / "promo").resolve())

    # Pick the first existing directory
    for c in candidates:
        if c.exists() and c.is_dir():
            return c

    # Fallback: return the first candidate even if it doesn’t exist (so we can show it in the error)
    return candidates[0]

async def stop_all_voice(interaction: discord.Interaction):
    """
    Fully stop all voice playback, cancel any promo or crowd loops,
    and disconnect from the voice channel if connected.
    """
    ch_id = interaction.channel_id

    # stop promo and crowd loops if active
    global PROMO_ACTIVE, PROMO_TASKS, CROWD_ACTIVE, CROWD_TASKS

    # promo
    try:
        PROMO_ACTIVE[ch_id] = False
        task = PROMO_TASKS.pop(ch_id, None)
        if task and not task.done():
            task.cancel()
    except Exception:
        pass

    # crowd ambience
    try:
        CROWD_ACTIVE[ch_id] = False
        task = CROWD_TASKS.pop(ch_id, None)
        if task and not task.done():
            task.cancel()
    except Exception:
        pass

    # stop any current voice playback
    vc = interaction.guild.voice_client if interaction.guild else None
    if vc:
        try:
            if vc.is_playing():
                vc.stop()
            if vc.is_connected():
                await vc.disconnect(force=True)
        except Exception as e:
            print(f"[voice stop] {type(e).__name__}: {e}")

def _find_first_audio(music_dir: Path) -> Optional[Path]:
    """
    Prefer hype.mp3/hype.wav first, otherwise return the first valid audio file found.
    """
    if not music_dir.exists():
        return None

    # 1️⃣ Prefer hype.*
    for fn in ("hype.mp3", "hype.wav", "promo.mp3"):
        p = music_dir / fn
        if p.exists():
            return p

    # 2️⃣ Fallback: first available audio file
    for root, _, files in os.walk(music_dir):
        for fn in sorted(files):
            if fn.lower().endswith(AUDIO_EXTS):
                return Path(root) / fn

    return None


# === new/updated poster renderer ===
def _render_promo_poster(name_left: str, name_right: str,
                         img_left: Optional[str], img_right: Optional[str],
                         out_w: int = 1280, out_h: int = 720) -> Optional[str]:
    """Promo poster with stacked title centered, fighter images flanking the title, and transparent flames."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageStat
    except Exception:
        return None

    # ---------- Tunables ----------
    NAME_SIZE = 170         # left/right names
    VS_SIZE   = 130         # VS
    TAGLINE_SIZE = 40
    TITLE_BAND_RATIO = 0.42   # how much vertical space top band uses
    SIDE_MARGIN = 36
    BETWEEN_TITLE_AND_IMAGE = 22   # horizontal breathing room between title column & each image
    IMG_MAX_W = 360               # cap fighter width (they’ll scale down to fit)
    IMG_MAX_H_RATIO = 0.56        # fraction of canvas height available for fighter images inside band
    FLAME_SCALE = 1.10            # flame height relative to VS font size
    TAGLINE_TEXT = "A night of glory, grit, and guts — live in TheDude Boxing Federation."

    # ---------- assets ----------
    try:
        from ..config import PROMO_DIR
    except Exception:
        PROMO_DIR = "./graphics/promo"
    bg_path = os.path.join(PROMO_DIR, "background.png")
    flame_path = os.path.join(PROMO_DIR, "icons", "flame.png")

    font_candidates = [
        os.path.join(PROMO_DIR, "fonts", "BebasNeue-Regular.ttf"),
        os.path.join(PROMO_DIR, "fonts", "Anton-Regular.ttf"),
        os.path.join(PROMO_DIR, "fonts", "Impact.ttf"),
    ]
    def _load_font(size: int):
        for fp in font_candidates:
            if os.path.exists(fp):
                try: return ImageFont.truetype(fp, size=size)
                except Exception: pass
        return ImageFont.load_default()

    # ---------- canvas ----------
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 255))
    if os.path.exists(bg_path):
        bg = Image.open(bg_path).convert("RGBA")
        r = max(out_w / bg.width, out_h / bg.height)
        bg = bg.resize((int(bg.width * r), int(bg.height * r)), Image.LANCZOS)
        x = (bg.width - out_w) // 2
        y = (bg.height - out_h) // 2
        canvas.paste(bg.crop((x, y, x + out_w, y + out_h)), (0, 0))
    else:
        grad = Image.new("RGBA", (1, out_h), 0)
        g = ImageDraw.Draw(grad)
        for i in range(out_h):
            c = (int(30 + 8*i/out_h), int(10 + 18*i/out_h), int(45 + 40*i/out_h), 255)
            g.point((0, i), fill=c)
        canvas = grad.resize((out_w, out_h), Image.BILINEAR)

    # readability overlays
    overlay = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    o = ImageDraw.Draw(overlay)
    title_band_h = int(out_h * TITLE_BAND_RATIO)
    o.rectangle([0, 0, out_w, title_band_h], fill=(0, 0, 0, 120))
    o.rectangle([0, title_band_h, out_w, out_h], fill=(0, 0, 0, 60))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    # ---------- title text (center column) ----------
    font_left  = _load_font(NAME_SIZE)
    font_vs    = _load_font(VS_SIZE)
    font_right = _load_font(NAME_SIZE)
    font_tag   = _load_font(TAGLINE_SIZE)

    def size(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
        """Width/height across Pillow versions (textlength or textbbox)."""
        try:
            w = draw.textlength(text, font=font)        # newer Pillow
        except Exception:
            # fallback: textbbox
            bbox = draw.textbbox((0, 0), text, font=font)  # (l, t, r, b)
            w = bbox[2] - bbox[0]
        # height: use bbox for accuracy
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            h = (bbox[3] - bbox[1]) + 8
        except Exception:
            h = font.size + 8
        return int(w), int(h)

    l_text, vs_text, r_text = name_left, "VS", name_right
    l_w, l_h = size(l_text, font_left)
    v_w, v_h = size(vs_text, font_vs)
    r_w, r_h = size(r_text, font_right)

    # column width = max of the three lines
    col_w = max(l_w, v_w, r_w)
    col_x = (out_w - col_w) // 2
    # vertically center block within title band
    total_h = l_h + v_h + r_h + 8
    start_y = max(16, (title_band_h - total_h) // 2)

    # glow writer
    def glow(x, y, text, font, fill, radii=(8, 3)):
        for r in radii:
            tmp = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            td.text((x, y), text, font=font, fill=(255, 255, 255, 255))
            tmp = tmp.filter(ImageFilter.GaussianBlur(radius=r))
            canvas.alpha_composite(tmp)
        draw.text((x, y), text, font=font, fill=fill)

    colL, colVS, colR = (255, 95, 95, 255), (255, 230, 90, 255), (95, 160, 255, 255)

    y = start_y
    glow(col_x + (col_w - l_w)//2, y, l_text, font_left,  colL); y += l_h
    vs_x = col_x + (col_w - v_w)//2
    vs_y = y
    glow(vs_x, vs_y, vs_text, font_vs, colVS); y += v_h
    glow(col_x + (col_w - r_w)//2, y, r_text, font_right, colR); y += r_h

    # tagline (directly under title block)
    tag_y = y + 10
    tag_w = draw.textlength(TAGLINE_TEXT, font=font_tag)
    tag_x = (out_w - tag_w) // 2
    for dx, dy in ((2,2),(3,3)):
        draw.text((tag_x+dx, tag_y+dy), TAGLINE_TEXT, font=font_tag, fill=(0,0,0,180))
    draw.text((tag_x, tag_y), TAGLINE_TEXT, font=font_tag, fill=(240,240,240,240))

    # --- replace your _load_flame with this version ---
    def _load_flame(path: str, target_h: int) -> Optional[Image.Image]:
        """
        Load a flame PNG and synthesize a clean alpha if the file has a baked gray/ checkerboard BG.
        We keep high-saturation, bright pixels (flame) and drop low-sat gray (background).
        """
        from PIL import Image, ImageChops, ImageFilter, ImageStat

        if not os.path.exists(path):
            return None

        im = Image.open(path).convert("RGBA")
        w, h = im.size

        # If the png already has a sensible alpha, use it.
        try:
            A = im.getchannel("A")
            s = int(ImageStat.Stat(A).sum[0])
            if 0 < s < 255 * w * h:  # already has mixed transparency
                pass  # keep
            else:
                # Build an alpha from chroma (HSV saturation * value) and de-gray it.
                RGB = im.convert("RGB")
                HSV = RGB.convert("HSV")
                H, S, V = HSV.split()  # 0..255 each

                # Emphasize saturation (colorfulness) and brightness together.
                SV = ImageChops.multiply(S, V)  # 0..255
                # Boost a bit so mid oranges become solid.
                SV = SV.point(lambda p: min(255, int(p * 1.4)))

                # Remove neutral grays explicitly: |R-G| and |R-B| small ⇒ background
                R, G, B = RGB.split()
                RG = ImageChops.difference(R, G)
                RB = ImageChops.difference(R, B)
                chroma = ImageChops.lighter(RG, RB)  # bigger ⇒ more colorful

                # Combine: strong alpha where (SV high) AND (chroma high)
                # thresholds tuned empirically; tweak if needed
                keep = ImageChops.multiply(
                    SV.point(lambda p: 255 if p > 110 else 0),
                    chroma.point(lambda p: 255 if p > 22 else 0),
                )

                # Slight feather so edges aren’t jaggy
                keep = keep.filter(ImageFilter.GaussianBlur(1.2))
                im.putalpha(keep)
        except Exception:
            # If anything above fails, just keep the original and hope it had alpha.
            pass

        # Scale to target height
        scale = target_h / im.height
        new_size = (max(1, int(im.width * scale)), max(1, int(target_h)))
        return im.resize(new_size, Image.LANCZOS)

    flame_h = int(font_vs.size * FLAME_SCALE)
    flame = _load_flame(flame_path, flame_h)
    if flame:
        left_fx = max(SIDE_MARGIN, vs_x - flame.width - 20)
        right_fx = min(out_w - SIDE_MARGIN - flame.width, vs_x + v_w + 20)

        # paste ON TOP of everything with flame’s alpha
        canvas.paste(flame, (left_fx, vs_y - 6), mask=flame)
        flame_mirror = flame.transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(flame_mirror, (right_fx, vs_y - 6), mask=flame_mirror)

    # ---------- fighter images FLANKING the title column ----------
    content_top = int(out_h * 0.10)  # top edge of title band
    img_zone_h  = int(out_h * IMG_MAX_H_RATIO)
    img_max_h   = min(img_zone_h, title_band_h - 20)

    def load_fit(path):
        if not path: return None
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return None
        return ImageOps.contain(im, (IMG_MAX_W, img_max_h), method=Image.LANCZOS)

    L = load_fit(img_left)
    R = load_fit(img_right)

    def shadow_paste(base, im, x, y):
        if im is None: return
        sh = Image.new("RGBA", (im.width+32, im.height+32), (0,0,0,0))
        sd = ImageDraw.Draw(sh)
        sd.rectangle([16,16,16+im.width,16+im.height], fill=(0,0,0,160))
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        base.alpha_composite(sh, (x-16, y-16))
        base.alpha_composite(im, (x, y))

    # place left image to the left of the title column, vertically centered within band
    if L:
        Lx = max(SIDE_MARGIN, col_x - BETWEEN_TITLE_AND_IMAGE - L.width)
        Ly = content_top + (title_band_h - L.height)//2
        shadow_paste(canvas, L, Lx, Ly)

    # place right image to the right of the title column
    if R:
        Rx = min(out_w - SIDE_MARGIN - R.width, col_x + col_w + BETWEEN_TITLE_AND_IMAGE)
        Ry = content_top + (title_band_h - R.height)//2
        shadow_paste(canvas, R, Rx, Ry)

    # ---------- save ----------
    out_name = f"_poster_{int(asyncio.get_running_loop().time() * 1000)}.png"
    out_path = os.path.join(PROMO_DIR, out_name)
    try:
        canvas.save(out_path)
        return out_path
    except Exception:
        return None



def _fancy(text: str) -> str:
    # simple fancy (Mathematical Bold) where possible; fallback regular chars
    bold_map = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
        "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    )
    return text.translate(bold_map)


def _promo_image_for_name(name: str) -> Optional[str]:
    base = os.path.join(PROMO_DIR, name)
    # try exact with known exts
    for ext in PROMO_IMG_EXTS:
        p = base + ext
        if os.path.exists(p):
            return p
    # try lowercased
    base = os.path.join(PROMO_DIR, name.lower())
    for ext in PROMO_IMG_EXTS:
        p = base + ext
        if os.path.exists(p):
            return p
    return None


async def _ensure_voice(interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works in a server (not DMs).", ephemeral=True)
        return None
    vc = guild.voice_client
    if vc and vc.is_connected():
        if interaction.user and getattr(interaction.user, "voice", None):
            ch = interaction.user.voice.channel
            if vc.channel != ch:
                await vc.move_to(ch)
        return vc
    if not interaction.user or not getattr(interaction.user, "voice", None):
        await interaction.followup.send("Join a **voice channel** first so I can play the promo music.",
                                        ephemeral=True)
        return None
    try:
        return await interaction.user.voice.channel.connect(reconnect=True)
    except Exception as e:
        await interaction.followup.send(f"Couldn’t join your voice channel: `{e}`", ephemeral=True)
        return None


async def _play_once(
    vc: discord.VoiceClient,
    path: str,
    seconds: Optional[float] = None,
    fade_out: float = 0.0
):
    if not os.path.exists(path):
        return
    if vc.is_playing():
        vc.stop()

    before_opts = "-nostdin"
    # IMPORTANT: on Windows quoting can be touchy; avoid shell quotes and pass raw -af args.
    opts = "-vn"
    if seconds:
        opts += f" -t {float(seconds):.2f}"
        if fade_out and fade_out > 0:
            st = max(0.0, float(seconds) - float(fade_out))
            # No quotes around the filter expression => FFmpegPCMAudio will pass args properly cross-platform
            opts += f" -af afade=t=out:st={st:.2f}:d={float(fade_out):.2f}"

    audio = discord.FFmpegPCMAudio(
        path,
        executable=FFMPEG_PATH,
        before_options=before_opts,
        options=opts
    )
    vc.play(audio)
    while vc.is_playing():
        await asyncio.sleep(0.3)


async def _promo_music_loop(interaction: discord.Interaction, track_path: str):
    """Loop until PROMO_ACTIVE[channel_id] becomes False."""
    vc = await _ensure_voice(interaction)
    if not vc:
        return
    ch_id = interaction.channel_id
    while PROMO_ACTIVE.get(ch_id, False):
        try:
            await _play_once(vc, track_path, seconds=None)  # full track
        except Exception:
            await asyncio.sleep(2.0)


async def stop_promo_music(interaction: discord.Interaction):
    ch_id = interaction.channel_id
    PROMO_ACTIVE[ch_id] = False
    task = PROMO_TASKS.pop(ch_id, None)
    if task and not task.done():
        task.cancel()
    # also stop current voice playback if any
    vc = interaction.guild.voice_client if interaction.guild else None
    if vc and vc.is_connected() and vc.is_playing():
        vc.stop()


def _compose_side_by_side(path_left: str, path_right: str) -> Optional[str]:
    """
    Try to compose /graphics/promo/_composite_<timestamp>.png using Pillow.
    Fallback: return None if Pillow not available or error.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None

    try:
        left = Image.open(path_left).convert("RGBA")
        right = Image.open(path_right).convert("RGBA")
        # make same height
        h = max(left.height, right.height)

        def fit_h(im):
            return ImageOps.contain(im, (im.width * 10, h))  # keep width, limit height to h

        left = fit_h(left)
        right = fit_h(right)

        # pad to same height exactly
        def pad_to_h(im):
            if im.height == h: return im
            new = Image.new("RGBA", (im.width, h), (0, 0, 0, 0))
            y = (h - im.height) // 2
            new.paste(im, (0, y))
            return new

        left = pad_to_h(left)
        right = pad_to_h(right)

        # combine
        gap = 24
        w = left.width + gap + right.width
        combo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        combo.paste(left, (0, 0))
        combo.paste(right, (left.width + gap, 0))
        out_path = os.path.join(PROMO_DIR, f"_composite_{int(asyncio.get_running_loop().time() * 1000)}.png")
        combo.save(out_path)
        return out_path
    except Exception:
        return None


class PromoSelection(discord.ui.Select):
    def __init__(self, options: List[str], placeholder: str):
        items=[discord.SelectOption(label=n[:100],value=n) for n in options[:25]]
        super().__init__(placeholder=placeholder[:150],min_values=1,max_values=1,options=items)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected=self.values[0]; await interaction.response.defer(); self.view.stop()

class PromoView(discord.ui.View):
    PAGE_SIZE=23
    def __init__(self,names:List[str],placeholder:str):
        super().__init__(timeout=60); self.selected=None; self.names=list(names); self.placeholder=placeholder; self.page=0; self._render()
    def _render(self):
        self.clear_items(); start=self.page*self.PAGE_SIZE; chunk=self.names[start:start+self.PAGE_SIZE]
        pages=max(1,(len(self.names)+self.PAGE_SIZE-1)//self.PAGE_SIZE)
        self.add_item(PromoSelection(chunk,f"{self.placeholder} ({self.page+1}/{pages})"))
        if len(self.names)>self.PAGE_SIZE:
            prev=discord.ui.Button(label="◀ Previous",style=discord.ButtonStyle.secondary,disabled=self.page==0)
            nxt=discord.ui.Button(label="Next ▶",style=discord.ButtonStyle.secondary,disabled=start+self.PAGE_SIZE>=len(self.names))
            async def pc(i): self.page-=1; self._render(); await i.response.edit_message(view=self)
            async def nc(i): self.page+=1; self._render(); await i.response.edit_message(view=self)
            prev.callback=pc; nxt.callback=nc; self.add_item(prev); self.add_item(nxt)

def _find_crowd_track() -> Optional[str]:
    """Find a crowd ambience file in resolved music dir or common names."""
    # explicit override if you have it in config
    try:
        from ..config import CROWD_AMBIENT
        if CROWD_AMBIENT and os.path.exists(CROWD_AMBIENT):
            return CROWD_AMBIENT
    except Exception:
        pass

    music_dir = _resolve_music_dir()
    candidates = [
        music_dir / "ambient" / "crowd.mp3",
        music_dir / "crowd.mp3",
        music_dir / "crowd_ambience.mp3",
        music_dir / "crowd.wav",
        music_dir / "ambient" / "crowd.wav",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

async def _send_intro_with_ring(interaction: discord.Interaction, red, blue):
    """Single Fight Night embed + short crowd ambience with fade-out."""
    title = "🥊 Fight Night!"
    desc = (
        f"**In the Red Corner:** {red.name} — *{red.weight_class.title()}*\n"
        f"_{red.intro or 'Ready to rumble.'}_\n\n"
        f"**In the Blue Corner:** {blue.name} — *{blue.weight_class.title()}*\n"
        f"_{blue.intro or 'No step backs.'}_"
    )

    emb = discord.Embed(title=title, description=desc, color=discord.Color.dark_gold())

    # choose file or URL once
    file_to_send = None
    if os.path.exists(RING_GIF_LOCAL):
        file_to_send = discord.File(RING_GIF_LOCAL, filename=os.path.basename(RING_GIF_LOCAL))
        emb.set_image(url=f"attachment://{os.path.basename(RING_GIF_LOCAL)}")
    else:
        emb.set_image(url=RING_GIF_URL)

    # ✅ send exactly once (NO second embed below)
    if file_to_send:
        await interaction.followup.send(embed=emb, file=file_to_send)
    else:
        await interaction.followup.send(embed=emb)
    # crowd ambience (LOOPS until /fight)
    try:
        await stop_promo_music(interaction)
        crowd = _find_crowd_ambience_file()
        if crowd and os.path.exists(crowd):
            await stop_crowd_ambience(interaction)  # ensure clean state
            ch_id = interaction.channel_id
            CROWD_ACTIVE[ch_id] = True
            CROWD_TASKS[ch_id] = asyncio.create_task(_crowd_music_loop(interaction, crowd))
        else:
            print("[crowd] crowd_ambience file not found")
    except Exception as e:
        print(f"[crowd] failed to start ambience loop: {e}")


async def _send_matchup_gif_and_music(interaction: discord.Interaction, red, blue):
    """Matchup GIF + optional voice intro clips."""
    # GIF
    mkey = ("MM" if red.gender == "male" and blue.gender == "male"
            else "FF" if red.gender == "female" and blue.gender == "female"
    else "MF")

    emb = discord.Embed(
        title="🎵 Fighter Intros",
        description=f"{red.name} vs {blue.name}",
        color=discord.Color.blurple(),
    )

    tracks = []
    if getattr(red, "intro_music", None):
        tracks.append(f"🔴 {red.name} — *{display_music_label(red.intro_music)}*")
    if getattr(blue, "intro_music", None):
        tracks.append(f"🔵 {blue.name} — *{display_music_label(blue.intro_music)}*")
    if tracks:
        emb.add_field(name="Tracks", value="\n".join(tracks), inline=False)

    file_to_send = None
    local_path = ROUND_GIF_LOCAL.get(mkey)
    url = ROUND_GIF_URL.get(mkey)
    if local_path and os.path.exists(local_path):
        file_to_send = discord.File(local_path, filename=os.path.basename(local_path))
        emb.set_image(url=f"attachment://{os.path.basename(local_path)}")
    elif url:
        emb.set_image(url=url)

    if file_to_send:
        await interaction.followup.send(embed=emb, file=file_to_send)
    else:
        await interaction.followup.send(embed=emb)

    # Music
    vc = await ensure_voice(interaction)
    if vc:
        if vc.is_playing():
            vc.stop()
        if getattr(red, "intro_music", None):
            await play_clip(vc, red.intro_music, seconds=10)
        if getattr(blue, "intro_music", None):
            await play_clip(vc, blue.intro_music, seconds=10)


# ----- Cog -----

def _serial_fight_action(func):
    @functools.wraps(func)
    async def wrapped(self, interaction: discord.Interaction, *args, **kwargs):
        async with get_fight_lock(interaction.channel_id):
            return await func(self, interaction, *args, **kwargs)
    return wrapped


class Match(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _summary_embed(self, s: FightSession) -> discord.Embed:
        result = "Draw" if not s.winner else f"{s.winner} — {s.winner_type or 'Result'}"
        emb = discord.Embed(title="🥊 Fight Summary", description=f"**{result}**", color=discord.Color.gold())
        emb.add_field(name=f"🔴 {s.A.boxer.name}", value=f"HP {max(0,s.A.hp)} • KDs scored {s.kd_total.get('B',0)} • Warnings {s.A.warnings}", inline=False)
        emb.add_field(name=f"🔵 {s.B.boxer.name}", value=f"HP {max(0,s.B.hp)} • KDs scored {s.kd_total.get('A',0)} • Warnings {s.B.warnings}", inline=False)
        emb.set_footer(text=f"Rounds logged: {len(s.log)} • Seed: {s.rng_seed}")
        return emb

    def _record_v2_result(self, interaction: discord.Interaction, s: FightSession) -> None:
        try:
            from ..services.game import finalize_session
            finalize_session(s, guild_id=interaction.guild_id)
        except Exception as exc:
            # Career persistence must never prevent the fight presentation from finishing.
            print(f"[V2 career] result persistence failed: {type(exc).__name__}: {exc}")

    @app_commands.command(
        name="promo",
        description="Set up a looping promo: pick fighters, show poster, and play promo music until /start."
    )
    async def promo(self, interaction: discord.Interaction):
        from ..services.roster import list_boxers  # lazy import to avoid circulars

        from ..services.game import competitive_legal
        names = [n for n in list_boxers() if competitive_legal(n)[0]]
        if not names:
            await interaction.response.send_message("No boxers yet. Use /boxer_create first.", ephemeral=True)
            return

        # Step 1: select fighter 1
        await interaction.response.send_message("🎬 Choose the **first fighter** for the promo:", ephemeral=True)
        v1 = PromoView(names, "Select fighter 1")
        await interaction.edit_original_response(view=v1)
        await v1.wait()
        if not v1.selected:
            await interaction.edit_original_response(content="❌ No selection made.", view=None)
            return
        first = v1.selected

        # Step 2: select fighter 2
        await interaction.edit_original_response(content="🎬 Choose the **second fighter** for the promo:", view=None)
        v2 = PromoView([n for n in names if n != first], "Select fighter 2")
        await interaction.edit_original_response(view=v2)
        await v2.wait()
        if not v2.selected:
            await interaction.edit_original_response(content="❌ No selection made.", view=None)
            return
        second = v2.selected

        # Build / choose art (centered text poster preferred)
        img1 = _promo_image_for_name(first) or _promo_image_for_name(first.title())
        img2 = _promo_image_for_name(second) or _promo_image_for_name(second.title())

        poster = None
        try:
            poster = _render_promo_poster(first, second, img1, img2)
        except Exception as e:
            # log to console so you can see the real cause
            print(f"[promo poster] render failed: {type(e).__name__}: {e}")

        if not poster:
            # graceful fallbacks – never crash the interaction
            if img1 and img2:
                try:
                    poster = _compose_side_by_side(img1, img2)
                except Exception as e:
                    print(f"[promo poster] composite failed: {type(e).__name__}: {e}")
            if not poster:
                poster = img1 or img2

        await interaction.edit_original_response(content="Building promo…", view=None)

        emb = discord.Embed(color=discord.Color.gold())
        if poster and os.path.exists(poster):
            file_to_send = discord.File(poster, filename=os.path.basename(poster))
            emb.set_image(url=f"attachment://{os.path.basename(poster)}")
            await interaction.followup.send(embed=emb, file=file_to_send)
        else:
            emb.title = f"{first} VS {second}"
            emb.add_field(name="Poster", value="No images found in `/graphics/promo/`.", inline=False)
            await interaction.followup.send(embed=emb)

        if poster and Path(poster).name.startswith(("_poster_", "_composite_")):
            try:
                Path(poster).unlink(missing_ok=True)
            except OSError:
                pass

        # === MUSIC LOOP (inside the function!) ===
        music_dir = _resolve_music_dir()
        track_path = _find_first_audio(music_dir)

        if track_path:
            vc = await _ensure_voice(interaction)
            if not vc:
                await interaction.followup.send(
                    "🎵 Found music but I couldn't join voice. Check channel perms & FFMPEG_PATH.",
                    ephemeral=True
                )
            else:
                PROMO_ACTIVE[interaction.channel_id] = True
                task = asyncio.create_task(_promo_music_loop(interaction, str(track_path)))
                PROMO_TASKS[interaction.channel_id] = task
                await interaction.followup.send(
                    f"🎵 Looping `{Path(track_path).name}` from `{music_dir}`.",
                    ephemeral=True
                )
        else:
            listed = []
            if music_dir.exists():
                try:
                    listed = sorted(os.listdir(music_dir))[:12]
                except Exception:
                    listed = ["<error listing directory>"]
            await interaction.followup.send(
                "🎵 No audio found.\n"
                f"• PROMO_MUSIC_DIR (from config): `{PROMO_MUSIC_DIR}`\n"
                f"• Resolved folder checked: `{music_dir}`\n"
                f"• Looking for: {', '.join(ext.upper() for ext in AUDIO_EXTS)}\n"
                f"• Top-level files found: {listed or '[none]'}\n"
                "Tip: drop `hype.mp3` here to loop it.",
                ephemeral=True
            )

    @app_commands.command(name="voice_stop_all", description="Stop all audio and disconnect the bot from voice.")
    @app_commands.checks.has_permissions(administrator=True)
    async def voice_stop_all(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await stop_all_voice(interaction)
        await interaction.followup.send("🛑 All voice playback stopped and bot disconnected.", ephemeral=True)

    @app_commands.command(name="promo_music_test", description="Play first promo track once.")
    async def promo_music_test(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)
        music_dir = _resolve_music_dir()
        track = _find_first_audio(music_dir)
        if not track:
            return await interaction.followup.send(f"No audio in `{music_dir}`.", ephemeral=True)
        vc = await _ensure_voice(interaction)
        if not vc:
            return await interaction.followup.send("Could not join voice.", ephemeral=True)
        await _play_once(vc, str(track), seconds=4.0, fade_out=0.8)
        from pathlib import Path as _P
        await interaction.followup.send(f"Played: `{_P(track).name}`", ephemeral=True)

    @app_commands.command(name="promo_stop", description="Stop any active promo loop & music in this channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def promo_stop(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=False, ephemeral=True)
        await stop_promo_music(interaction)
        await interaction.followup.send("🛑 Promo stopped in this channel.", ephemeral=True)

    @app_commands.command(name="start", description="Pick two boxers, show ring + intros.")
    @app_commands.checks.has_permissions(administrator=True)
    @_serial_fight_action
    async def start(self, interaction: discord.Interaction):
        from ..services.game import competitive_legal
        names = [n for n in list_boxers() if competitive_legal(n)[0]]
        if not names:
            await interaction.response.send_message("No boxers available. Use `/boxer_create` first.", ephemeral=True)
            return

        # stop promo loop if running in this channel
        await stop_promo_music(interaction)

        # Select fighters
        await interaction.response.send_message("🎯 Choose the **first fighter**:", ephemeral=True)
        from boxing_bot.ui.components import BoxerSelectionView  # lazy import to avoid cycles
        view1 = BoxerSelectionView(names, "Select fighter 1")
        await interaction.edit_original_response(view=view1)
        await view1.wait()
        if not view1.selected_boxer:
            await interaction.edit_original_response(content="❌ No selection made.", view=None)
            return
        first_name = view1.selected_boxer

        await interaction.edit_original_response(content="🎯 Choose the **second fighter**:", view=None)
        view2 = BoxerSelectionView([n for n in names if n != first_name], "Select fighter 2")
        await interaction.edit_original_response(view=view2)
        await view2.wait()
        if not view2.selected_boxer:
            await interaction.edit_original_response(content="❌ No selection made.", view=None)
            return
        second_name = view2.selected_boxer

        try:
            from ..services.game import competition_boxer
            A = competition_boxer(interaction.guild_id, first_name)
            B = competition_boxer(interaction.guild_id, second_name)
            if not A or not B:
                await interaction.edit_original_response(content="❌ Could not load both fighters.", view=None)
                return

            await interaction.edit_original_response(
                content=f"✅ Fighters selected: **{first_name}** and **{second_name}**.\nSetting up the match...",
                view=None,
            )

            # Corner assignment + session build
            seed = secrets.randbits(64)
            rng = random.Random(seed)
            (red_info, blue_info) = corner_assignments(A, B, rng)
            red_raw, blue_raw = red_info[1], blue_info[1]
            red_eff, blue_eff = effective_boxer(red_raw), effective_boxer(blue_raw)

            session = FightSession(
                channel_id=interaction.channel_id,
                rng_seed=seed,
                rng=rng,
                red_raw=red_raw,
                blue_raw=blue_raw,
                red_eff=red_eff,
                blue_eff=blue_eff,
                A=FighterState(red_eff, red_eff.max_hp()),
                B=FighterState(blue_eff, blue_eff.max_hp()),
                kd_rule="per_round",
                kd_limit=3,
            )
            SESSIONS[interaction.channel_id] = session
            save_sessions()

            # Public confirmation
            await interaction.followup.send(
                f"Match set: **{red_raw.name} (Red)** vs **{blue_raw.name} (Blue)**.\nUse `/fight` to begin Round 1."
            )

            # Present intros — add a short cinematic delay
            await _send_intro_with_ring(interaction, red_raw, blue_raw)

            # Pause between the two cards
            await asyncio.sleep(3.0)

            # Stop ambience before intros begin (so they don’t overlap)


            await _send_matchup_gif_and_music(interaction, red_raw, blue_raw)


        except discord.Forbidden as e:
            await interaction.followup.send(
                f"❌ I don’t have permission to send messages/embeds here: `{e}`.\n"
                f"Please grant **Send Messages**, **Embed Links**, and **Attach Files**.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Error while creating the match: `{type(e).__name__}: {e}`",
                ephemeral=True,
            )
            raise

    @app_commands.command(name="fight", description="Begin Round 1 (then use /next_round).")
    @app_commands.checks.has_permissions(administrator=True)
    @_serial_fight_action
    async def fight(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            # stop pre-fight ambience and start in-fight crowd loop
            await stop_crowd_ambience(interaction)
            fight_crowd = _find_fight_crowd_file()
            if fight_crowd and os.path.exists(fight_crowd):
                ch_id = interaction.channel_id
                CROWD_ACTIVE[ch_id] = True
                CROWD_TASKS[ch_id] = asyncio.create_task(_crowd_music_loop(interaction, fight_crowd))

            s = SESSIONS.get(interaction.channel_id)
            if not s:
                await interaction.followup.send("No active match. Use `/start` first.")
                return
            if s.finished:
                await interaction.followup.send(embed=self._summary_embed(s))
                return
            if s.current_round > 1 and s.log:
                await interaction.followup.send("Fight already underway. Use `/next_round`.")
                return

            # per-round state
            _ensure_crowd_state(s)
            _crowd_round_reset(s)

            # play the round once
            events, winner_type, loser = run_one_round(s)

            # log first
            s.log.append({
                "round": s.current_round,
                "events": events,
                "hp": {s.A.boxer.name: s.A.hp, s.B.boxer.name: s.B.hp},
            })
            save_sessions()

            # stream exchanges (crowd bite + audio + short exchange embed per event)
            for ev in events:
                crowd_line = await maybe_post_reaction_and_audio(interaction, s, ev)
                await _send_exchange_note(interaction, s, ev, crowd_line=crowd_line)
                await asyncio.sleep(2.0)

            # decide end-of-round state
            if winner_type:
                s.winner_type = winner_type
                if loser == s.A.boxer.name:
                    s.winner, s.winner_corner = s.B.boxer.name, "Blue"
                else:
                    s.winner, s.winner_corner = s.A.boxer.name, "Red"
                s.finished = True
                save_sessions()

            # round summary
            await send_round_card(interaction, s, events)

            # reset momentum for next round
            s.momentum = 0

            # finish or advance
            if s.finished:
                self._record_v2_result(interaction, s)
                if s.winner_type == "Points":
                    await send_points_decision(interaction, s)
                else:
                    loser_name = s.B.boxer.name if s.winner_corner == "Red" else s.A.boxer.name
                    await send_finish_announcement(
                        interaction, s, s.red_raw, s.blue_raw, s.winner, s.winner_corner, loser_name, s.winner_type
                    )
            else:
                s.current_round += 1
                save_sessions()
                await interaction.followup.send("Use `/next_round` to play the next round.")

        except Exception as e:
            await interaction.followup.send(f"⚠️ `/fight` crashed: `{type(e).__name__}: {e}`")
            raise

    @app_commands.command(name="next_round", description="Advance to the next round.")
    @app_commands.checks.has_permissions(administrator=True)
    @_serial_fight_action
    async def next_round(self, interaction: discord.Interaction):
        s = SESSIONS.get(interaction.channel_id)
        if not s:
            await interaction.response.send_message("No active fight. Use `/start` then `/fight`.", ephemeral=True)
            return
        if s.finished:
            await interaction.response.send_message(embed=self._summary_embed(s))
            return

        # end-of-fight gate (if we already played 12)
        if s.current_round > 12:
            finalize_if_done(s)
            save_sessions()
            if s.finished:
                self._record_v2_result(interaction, s)
            if s.finished and s.winner_type == "Points":
                await send_points_decision(interaction, s)
            else:
                loser_name = s.B.boxer.name if s.winner_corner == "Red" else (
                    s.A.boxer.name if s.winner_corner == "Blue" else None
                )
                # RIGHT
                await send_finish_announcement(
                    interaction, s, s.red_raw, s.blue_raw, s.winner, s.winner_corner, loser_name, s.winner_type
                )
            return

        await interaction.response.defer(thinking=True)

        # per-round crowd state
        _ensure_crowd_state(s)
        _crowd_round_reset(s)

        # play the round
        events, winner_type, loser = run_one_round(s)

        # log it immediately
        s.log.append({
            "round": s.current_round,
            "events": events,
            "hp": {s.A.boxer.name: s.A.hp, s.B.boxer.name: s.B.hp},
        })
        save_sessions()

        # instant per-exchange notes + (optional) audio bites
        for ev in events:
            crowd_line = await maybe_post_reaction_and_audio(interaction, s, ev)
            await _send_exchange_note(interaction, s, ev, crowd_line=crowd_line)
            await asyncio.sleep(2.0)

        # resolve end state for this round
        if winner_type:
            s.winner_type = winner_type
            if loser == s.A.boxer.name:
                s.winner, s.winner_corner = s.B.boxer.name, "Blue"
            else:
                s.winner, s.winner_corner = s.A.boxer.name, "Red"
            s.finished = True
            save_sessions()

        # single round summary card (it will internally post ONE crowd/hype line after)
        await send_round_card(interaction, s, events)

        # reset momentum for next round
        s.momentum = 0

        # finish or advance
        if s.finished:
            self._record_v2_result(interaction, s)
            if s.winner_type == "Points":
                await send_points_decision(interaction, s)
            else:
                loser_name = s.B.boxer.name if s.winner_corner == "Red" else s.A.boxer.name
                await send_finish_announcement(
                    interaction, s, s.red_raw, s.blue_raw, s.winner, s.winner_corner, loser_name, s.winner_type
                )
            await interaction.followup.send(embed=self._summary_embed(s))
            return

        # still going — move to next round (and handle 12→cards path)
        s.current_round += 1
        save_sessions()
        if s.current_round > 12:
            finalize_if_done(s)
            save_sessions()
            if s.finished:
                self._record_v2_result(interaction, s)
            if s.finished and s.winner_type == "Points":
                await send_points_decision(interaction, s)
            else:
                loser_name = s.B.boxer.name if s.winner_corner == "Red" else (
                    s.A.boxer.name if s.winner_corner == "Blue" else None
                )
                await send_finish_announcement(
                    interaction, s, s.red_raw, s.blue_raw, s.winner, s.winner_corner, loser_name, s.winner_type
                )
            await interaction.followup.send(embed=self._summary_embed(s))
        else:
            await interaction.followup.send(
                f"Round {s.current_round - 1} complete. Use `/next_round` for Round {s.current_round}."
            )

    @app_commands.command(name="resolve_test", description="(TEST) Force-resolve the current fight.")
    @app_commands.describe(method="KO | TKO | Points", winner="Red | Blue")
    @app_commands.choices(
        method=[
            app_commands.Choice(name="KO", value="KO"),
            app_commands.Choice(name="TKO", value="TKO"),
            app_commands.Choice(name="Points", value="Points"),
        ],
        winner=[
            app_commands.Choice(name="Red", value="Red"),
            app_commands.Choice(name="Blue", value="Blue"),
        ],
    )
    @app_commands.checks.has_permissions(administrator=True)
    @_serial_fight_action
    async def resolve_test(
            self,
            interaction: discord.Interaction,
            method: app_commands.Choice[str],
            winner: app_commands.Choice[str],
    ):
        # 1) ACK immediately so Discord stops showing "thinking…"
        await interaction.response.defer(thinking=False)

        try:
            s = SESSIONS.get(interaction.channel_id)
            if not s:
                await interaction.followup.send("No active match.", ephemeral=True)
                return
            if s.finished:
                await interaction.followup.send("This fight is already finished.", ephemeral=True)
                return

            # 2) Decide winner/loser + mark finished
            if winner.value == "Red":
                s.winner, s.winner_corner, loser_name = s.A.boxer.name, "Red", s.B.boxer.name
            else:
                s.winner, s.winner_corner, loser_name = s.B.boxer.name, "Blue", s.A.boxer.name

            s.winner_type = method.value
            s.finished = True
            save_sessions()
            self._record_v2_result(interaction, s)

            # Small immediate follow-up so users see movement
            await interaction.followup.send(
                f"Resolving as **{s.winner} ({s.winner_corner}) – {s.winner_type}**…"
            )

            # 3) Show outcome
            if s.winner_type == "Points":
                # ensure judge cards exist (safe even if log is empty)
                if not getattr(s, "judge_cards", None):
                    s.judge_cards = compute_scorecards(s)
                await send_points_decision(interaction, s)
            else:
                await send_finish_announcement(
                    interaction,
                    s,
                    s.red_raw,
                    s.blue_raw,
                    s.winner,
                    s.winner_corner,
                    loser_name,
                    s.winner_type
                )

        except Exception as e:
            # 4) Never leave the interaction hanging
            await interaction.followup.send(f"⚠️ resolve_test error: `{type(e).__name__}: {e}`", ephemeral=True)
            raise

async def setup(bot: commands.Bot):
    await bot.add_cog(Match(bot))