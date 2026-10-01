# boxing_bot/services/voice.py
import os, asyncio, shutil
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

async def play_clip(
    vc: discord.VoiceClient,
    source: str,
    seconds: Optional[float] = None,
    *,
    interrupt: bool = True,
):
    """Play a local/remote clip.

    ``seconds=None`` plays the file to natural completion.  This fixes the
    commentary cutoff caused by forcing every clip through FFmpeg ``-t``.
    When ``interrupt`` is False, an already-playing clip is left alone and the
    new clip is skipped instead of chopping the current audio mid-sentence.
    """
    if not source:
        return
    try:
        is_url = _is_url(source)
        if not is_url:
            src = os.path.abspath(source)
            if not os.path.exists(src):
                ensure_music_dir()
                alt = os.path.abspath(os.path.join(str(SETTINGS.MUSIC_DIR), os.path.basename(source)))
                if os.path.exists(alt):
                    src = alt
                else:
                    return
        else:
            src = source

        if vc.is_playing():
            if not interrupt:
                return
            vc.stop()

        options = "-vn"
        if seconds is not None:
            options += f" -t {float(seconds):.2f}"

        audio = discord.FFmpegPCMAudio(
            src,
            executable=(shutil.which("ffmpeg") or SETTINGS.FFMPEG_PATH),
            before_options="-nostdin",
            options=options,
        )
        vc.play(audio)
        while vc.is_playing():
            await asyncio.sleep(0.25)
    except Exception as e:
        print(f"[audio] FFmpeg play error: {e}")
