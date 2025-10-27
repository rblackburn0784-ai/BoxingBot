# boxing_bot/services/voice.py
import os, asyncio
import discord
from typing import Optional
from ..config import SETTINGS
from .music import ensure_music_dir


def _is_url(s: str) -> bool: return s.startswith(("http://","https://"))

async def ensure_voice(interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works in a server (not DMs).", ephemeral=True); return None
    vc: discord.VoiceClient | None = guild.voice_client
    if vc and vc.is_connected():
        if interaction.user and getattr(interaction.user, "voice", None):
            user_channel = interaction.user.voice.channel
            if vc.channel != user_channel:
                await vc.move_to(user_channel)
        return vc
    if not interaction.user or not getattr(interaction.user, "voice", None):
        await interaction.followup.send("Join a **voice channel** first so I can play intro music.", ephemeral=True); return None
    try:
        vc = await interaction.user.voice.channel.connect(reconnect=True)
        return vc
    except Exception as e:
        await interaction.followup.send(f"Couldn’t join your voice channel: `{e}`", ephemeral=True); return None

async def play_clip(vc: discord.VoiceClient, source: str, seconds: int = 15):
    if not source: return
    try:
        is_url = _is_url(source)
        if not is_url:
            src = os.path.abspath(source)
            if not os.path.exists(src):
                ensure_music_dir()
                alt = os.path.join(SETTINGS.MUSIC_DIR, os.path.basename(source))
                alt = os.path.abspath(alt)
                if os.path.exists(alt): src = alt
                else: return
            before_opts = "-nostdin"
        else:
            src = source; before_opts = "-nostdin"
        if vc.is_playing(): vc.stop()
        audio = discord.FFmpegPCMAudio(
            src, executable=SETTINGS.FFMPEG_PATH, before_options=before_opts, options=f"-vn -t {int(seconds)}"
        )
        vc.play(audio)
        waited = 0.0
        while vc.is_playing() and waited < seconds + 2:
            await asyncio.sleep(0.5); waited += 0.5
        vc.stop()
    except Exception as e:
        print(f"[audio] FFmpeg play error: {e}")
