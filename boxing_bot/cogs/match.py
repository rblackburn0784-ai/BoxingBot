from __future__ import annotations

import asyncio
import os
from typing import Optional, List, Tuple

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
        draw.text(((W - tw) // 2, y), txt, fill=(240, 240, 240, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))

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
                await play_clip(vc, crowd, max_seconds=seconds)
                await display_music_label(interaction, "Crowd ambience", seconds)
        except Exception:
            pass

    # Start command (select fighters, show ring gif, crowd ambience, intros, then start session)
    @app_commands.command(name="start", description="Start Fight Night: pick fighters and start the show")
    async def start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True)

        # Pick fighters (simple: first two in roster for this demo)
        roster = list_boxers()
        if len(roster) < 2:
            await interaction.followup.send("Not enough fighters in roster.")
            return
        a, b = roster[0], roster[1]
        A = effective_boxer(a)
        B = effective_boxer(b)

        # Create session
        s = FightSession(A=A, B=B)

        # Store session by channel
        SESSIONS[interaction.channel_id] = s

        # Fight Night embed with ring.gif
        matchup = corner_assignments(A, B)  # returns (div, gender_key "MM/MF/FF", red_name, blue_name, art paths?)
        gender_key = matchup.gender_key if hasattr(matchup, "gender_key") else "MM"

        ring_gif = RING_GIF_LOCAL.get(gender_key) or RING_GIF_URL.get(gender_key)
        em = discord.Embed(title="🥊 Fight Night!", description=f"**In the Red Corner:** {A.name} — *{A.division}*\n\n**In the Blue Corner:** {B.name} — *{B.division}*")
        if ring_gif:
            em.set_image(url=ring_gif)
        await interaction.followup.send(embed=em)

        # Ensure crowd ambience plays during this panel
        await self._play_crowd(interaction, seconds=12)

        # Fighter intros with round.gif + themes
        round_gif = ROUND_GIF_LOCAL.get(gender_key) or ROUND_GIF_URL.get(gender_key)
        intro = discord.Embed(title="Round 1 is coming up...", description=f"{A.name} and {B.name} make their way to center ring.")
        if round_gif:
            intro.set_image(url=round_gif)
        await interaction.followup.send(embed=intro)

        # Play short intro themes if available (15s each, ignore errors)
        try:
            vc = await ensure_voice(interaction)
            if getattr(A, "theme", None) and os.path.exists(A.theme):
                await play_clip(vc, A.theme, max_seconds=15)
                await display_music_label(interaction, f"{A.name} theme", 15)
            if getattr(B, "theme", None) and os.path.exists(B.theme):
                await play_clip(vc, B.theme, max_seconds=15)
                await display_music_label(interaction, f"{B.name} theme", 15)
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

        # Exactly 6 exchanges, alternating A/B
        total = 6
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

            if getattr(s, "is_over", False):
                break

        # Compose single round embed
        title = f"Round {s.round_no}"
        desc = "• " + "\n".join(lines) if lines else "—"
        em = discord.Embed(title=title, description=desc)
        em.add_field(name=" ", value="**Momentum**", inline=False)
        em.add_field(
            name=f"{s.A.name} (Red)  🟥",
            value=_fighter_line(s.A_state, s.A.name, "🔴"),
            inline=True,
        )
        em.add_field(
            name=f"{s.B.name} (Blue) 🟦",
            value=_fighter_line(s.B_state, s.B.name, "🔵"),
            inline=True,
        )
        em.add_field(
            name="Adrenaline",
            value=f"🔴 {s.A.name}: {_bar(s.A_state.adr)} {s.A_state.adr}%\n🔵 {s.B.name}: {_bar(s.B_state.adr)} {s.B_state.adr}%",
            inline=False,
        )

        # Crowd reactions (if any)
        if crowd_lines:
            em.add_field(name="Crowd Reactions", value="\n".join(crowd_lines), inline=False)

        await interaction.followup.send(embed=em)

        # End-of-round highlight + GIF
        await send_round_card(interaction, s)

        # Finalize if KO/TKO/Points
        if getattr(s, "is_over", False):
            if getattr(s, "result", None) in ("KO", "TKO"):
                await send_finish_announcement(interaction, s)
            else:
                await send_points_decision(interaction, s)
        else:
            s.round_no += 1


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCog(bot))