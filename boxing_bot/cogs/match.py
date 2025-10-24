from __future__ import annotations

import asyncio
import os
from typing import Optional, List, Tuple
import random
import discord
from discord import app_commands
from discord.ext import commands

from ..models import FightSession, FighterState
from ..services.state import SESSIONS
from ..services.roster import get_boxer, list_boxers
from ..services.stats import effective_boxer
from ..services.presentation import momentum_bar
from ..services.music import display_music_label
from ..services.voice import ensure_voice, play_clip
from ..services.combat import (
    attack_exchange,
    finalize_if_done,
    send_round_card,
    send_points_decision,
    send_finish_announcement,
    corner_assignments,
    CROWD_LINES,
)
from ..config import (
    RING_GIF_LOCAL,
    RING_GIF_URL,
    ROUND_GIF_LOCAL,
    ROUND_GIF_URL,
    PROMO_DIR,
    PROMO_MUSIC_DIR,
    PROMO_IMG_EXTS,
    SETTINGS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Local helpers

def _bar(val: int, width: int = 12, fill: str = "█", empty: str = "—") -> str:
    val = max(0, min(100, int(val)))
    n = round((val / 100) * width)
    return fill * n + empty * (width - n)


def _fighter_line(fs: FighterState, name: str, emoji: str) -> str:
    hp = max(0, min(100, fs.hp))
    return f"{emoji} **{name}**\nHP: {_bar(hp)} {hp}%"


def _safe_gif(map_obj: dict, key: Tuple[str, str, str]) -> Optional[str]:
    # key = (MM/MF/FF, corner 'Red'/'Blue', tag)
    if key in map_obj:
        return map_obj[key]
    # fallback by ignoring color
    k2 = (key[0], "*", key[2])
    return map_obj.get(k2)


def _render_promo_poster(first: str, second: str, img1: Optional[str], img2: Optional[str]) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except Exception:
        return None

    # Background candidates
    bg_candidates = [
        os.path.join(PROMO_DIR, "ring_bg.png"),
        os.path.join(PROMO_DIR, "ring_bg.jpg"),
        os.path.join(PROMO_DIR, "ring_bg.webp"),
    ]
    bg_path = next((p for p in bg_candidates if os.path.exists(p)), None)
    if bg_path:
        bg = Image.open(bg_path).convert("RGBA")
    else:
        bg = Image.new("RGBA", (1280, 720), (8, 12, 16, 255))

    W, H = bg.size
    canvas = bg.copy()
    draw = ImageDraw.Draw(canvas)

    # Try fighter images
    def load_fit(pth):
        if not pth or not os.path.exists(pth):
            return None
        im = Image.open(pth).convert("RGBA")
        return ImageOps.contain(im, (int(W * 0.40), int(H * 0.85)))

    L = load_fit(img1)
    R = load_fit(img2)

    if L:
        canvas.alpha_composite(L, (int(W * 0.08), int((H - L.height) // 2)))
    if R:
        canvas.alpha_composite(R, (int(W - (W * 0.08) - R.width), int((H - R.height) // 2)))

    # Center stripe
    from PIL import Image

    overlay = Image.new("RGBA", (int(W * 0.36), int(H * 0.30)), (0, 0, 0, 140))
    canvas.alpha_composite(overlay, (int(W * 0.32), int(H * 0.35)))

    try:
        font_big = ImageFont.truetype("arial.ttf", size=int(H * 0.12))
        font_med = ImageFont.truetype("arial.ttf", size=int(H * 0.06))
    except Exception:
        font_big = font_med = ImageFont.load_default()

    def centered(txt, y, font):
        bbox = draw.textbbox((0, 0), txt, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((W - tw) // 2, y), txt, fill=(240, 240, 240, 255), font=font, stroke_width=2,
                  stroke_fill=(0, 0, 0, 255))

    centered(first, int(H * 0.37), font_med)
    centered("VS", int(H * 0.44), font_big)
    centered(second, int(H * 0.56), font_med)

    os.makedirs(PROMO_DIR, exist_ok=True)
    out = os.path.join(PROMO_DIR, f"poster_{first}_vs_{second}.png").replace(" ", "_")
    canvas.save(out)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Cog


class MatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Utility to play crowd ambience reliably
    async def _play_crowd(self, interaction: discord.Interaction, seconds: int = 12):
        # Try several crowd files
        candidates = [
            os.path.join(PROMO_MUSIC_DIR, "crowd.mp3"),
            os.path.join(PROMO_MUSIC_DIR, "crowd.wav"),
            os.path.join(PROMO_MUSIC_DIR, "crowd.ogg"),
        ]
        crowd = next((p for p in candidates if os.path.exists(p)), None)
        try:
            vc = await ensure_voice(interaction)
            if crowd:
                await play_clip(vc, crowd, seconds=seconds)
                label = display_music_label(crowd)
                await interaction.followup.send(f"🎵 Crowd ambience: {label} ({seconds}s clip)")
        except Exception:
            pass

    # Start command (select fighters, show ring gif, crowd ambience, intros, then start session)
    @app_commands.command(name="start", description="Start Fight Night: pick fighters and start the show")
    async def start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True)

        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.followup.send("This command must be used from a channel.")
            return

        roster = list_boxers()
        if len(roster) < 2:
            await interaction.followup.send("Not enough fighters in roster.")
            return
        red_key, blue_key = roster[0], roster[1]
        red_raw = get_boxer(red_key)
        blue_raw = get_boxer(blue_key)
        if not red_raw or not blue_raw:
            await interaction.followup.send("Failed to load fighters from the roster.")
            return

        red_eff = effective_boxer(red_raw)
        blue_eff = effective_boxer(blue_raw)

        seed = random.randint(1, 1_000_000)
        rng = random.Random(seed)
        red_state = FighterState(boxer=red_eff, hp=red_eff.max_hp())
        blue_state = FighterState(boxer=blue_eff, hp=blue_eff.max_hp())

        session = FightSession(
            channel_id=channel_id,
            rng_seed=seed,
            rng=rng,
            red_raw=red_raw,
            blue_raw=blue_raw,
            red_eff=red_eff,
            blue_eff=blue_eff,
            A=red_state,
            B=blue_state,
        )

        SESSIONS[channel_id] = session

        matchup = corner_assignments(session.A, session.B)
        gender_key = getattr(matchup, "gender_key", "MM")

        def _select_asset(source: object) -> Optional[str]:
            if isinstance(source, dict):
                return source.get(gender_key)
            if isinstance(source, str):
                return source or None
            return None

        ring_gif = _select_asset(RING_GIF_LOCAL) or _select_asset(RING_GIF_URL)
        red_wc = session.red_raw.weight_class.title()
        blue_wc = session.blue_raw.weight_class.title()
        em = discord.Embed(
            title="🥊 Fight Night!",
            description=(
                f"**In the Red Corner:** {session.red_raw.name} — *{red_wc}*\n\n"
                f"**In the Blue Corner:** {session.blue_raw.name} — *{blue_wc}*"
            ),
        )
        if ring_gif:
            em.set_image(url=ring_gif)
        await interaction.followup.send(embed=em)

        await self._play_crowd(interaction, seconds=12)

        round_gif = _select_asset(ROUND_GIF_LOCAL) or _select_asset(ROUND_GIF_URL)
        intro = discord.Embed(
            title="Round 1 is coming up...",
            description=f"{session.red_raw.name} and {session.blue_raw.name} make their way to center ring.",
        )
        if round_gif:
            intro.set_image(url=round_gif)
        await interaction.followup.send(embed=intro)

        try:
            vc = await ensure_voice(interaction)
            red_theme = getattr(session.red_raw, "intro_music", "") or getattr(session.red_raw, "theme", "")
            blue_theme = getattr(session.blue_raw, "intro_music", "") or getattr(session.blue_raw, "theme", "")
            if red_theme and os.path.exists(red_theme):
                await play_clip(vc, red_theme, seconds=15)
                label = display_music_label(red_theme)
                await interaction.followup.send(f"🎵 {session.red_raw.name} theme: {label} (15s clip)")
            if blue_theme and os.path.exists(blue_theme):
                await play_clip(vc, blue_theme, seconds=15)
                label = display_music_label(blue_theme)
                await interaction.followup.send(f"🎵 {session.blue_raw.name} theme: {label} (15s clip)")
        except Exception:
            pass

        await interaction.followup.send("Type `/fight` to roll Round 1.")

    # Fight command: revert to non-live batch of 6 exchanges (3 per boxer), then show summary + highlight/gif
    @app_commands.command(name="fight", description="Run the next round (6 exchanges in one go).")
    async def fight(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True)
        s = SESSIONS.get(interaction.channel_id)
        if not s:
            await interaction.followup.send("No active fight in this channel. Use `/start` first.")
            return

        total = s.exchanges_per_round if getattr(s, "exchanges_per_round", None) else 6
        lines: List[str] = []
        crowd_lines: List[str] = []
        for i in range(1, total + 1):
            atk = s.A if i % 2 == 1 else s.B
            dfn = s.B if i % 2 == 1 else s.A
            ev = attack_exchange(atk, dfn, s.rng)
            # Build concise line
            if ev.get("summary"):
                lines.append(f"{i}. {ev['summary']}")
            else:
                # Generic fallback
                outcome = ev.get("outcome", "exchange")
                lines.append(f"{i}. ({outcome})")
            # Crowd reaction
            tag = ev.get("crowd_tag")
            if tag and tag in CROWD_LINES:
                crowd_lines.append(CROWD_LINES[tag].format(color="Red" if i % 2 == 1 else "Blue"))

            if finalize_if_done(s):
                break

        if lines:
            s.log.append({"round": s.current_round, "events": lines})
        if crowd_lines:
            s.crowd_log.extend(crowd_lines)

        # Compose single round embed
        title = f"Round {s.current_round}"
        desc = "• " + "\n".join(lines) if lines else "—"
        em = discord.Embed(title=title, description=desc)
        em.add_field(name="Momentum", value=momentum_bar(s.momentum), inline=False)
        em.add_field(
            name=f"{s.A.boxer.name} (Red)  🟥",
            value=_fighter_line(s.A, s.A.boxer.name, "🔴"),
            inline=True,
        )
        em.add_field(
            name=f"{s.B.boxer.name} (Blue) 🟦",
            value=_fighter_line(s.B, s.B.boxer.name, "🔵"),
            inline=True,
        )
        em.add_field(
            name="Adrenaline",
            value=(
                f"🔴 {s.A.boxer.name}: {_bar(s.A.adrenaline)} {s.A.adrenaline}%\n"
                f"🔵 {s.B.boxer.name}: {_bar(s.B.adrenaline)} {s.B.adrenaline}%"
            ),
            inline=False,
        )

        # Crowd reactions (if any)
        if crowd_lines:
            em.add_field(name="Crowd Reactions", value="\n".join(crowd_lines), inline=False)

        await interaction.followup.send(embed=em)

        # End-of-round highlight + GIF
        await send_round_card(interaction, s)

        # Finalize if KO/TKO/Points
        if s.finished:
            if (s.winner_type or "").upper() in {"KO", "TKO"}:
                await send_finish_announcement(interaction, s)
            else:
                await send_points_decision(interaction, s)
        else:
            s.current_round += 1


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCog(bot))
