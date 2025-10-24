"""Voice channel utilities built around ``discord.py``."""
from __future__ import annotations

import asyncio
import os
from typing import Optional

try:  # pragma: no cover - exercised only when discord.py is unavailable.
    import discord  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback used only in CI without discord.py.
    class _DiscordStub:  # pragma: no cover - used purely as a lightweight shim.
        """Very small subset of the :mod:`discord` API used in the tests."""

        class _Followup:
            async def send(self, *args, **kwargs):  # noqa: D401 - simple stub
                """Do nothing."""
                return None

        class Interaction:  # type: ignore[override]
            guild = None
            user = None
            followup = _Followup()

        class VoiceClient:  # pragma: no cover - behaviour is provided by tests.
            def __init__(self):
                self.channel = None
                self._is_playing = False

            def is_connected(self) -> bool:
                return self.channel is not None

            async def move_to(self, channel) -> None:  # noqa: ANN001 - third-party signature
                self.channel = channel

            def is_playing(self) -> bool:
                return self._is_playing

            def play(self, source) -> None:  # noqa: ANN001 - third-party signature
                self._is_playing = True
                self._source = source  # noqa: SLF001 - debug aid for tests

            def stop(self) -> None:
                self._is_playing = False
                self._source = None

        class VoiceChannel:  # pragma: no cover - debug helper
            async def connect(self, reconnect: bool = True) -> "_DiscordStub.VoiceClient":
                _ = reconnect
                return _DiscordStub.VoiceClient()

        class MemberVoiceState:
            def __init__(self, channel: "_DiscordStub.VoiceChannel" | None = None):
                self.channel = channel

        class Member:
            def __init__(self, voice: "_DiscordStub.MemberVoiceState" | None = None):
                self.voice = voice

        class FFmpegPCMAudio:  # noqa: D401 - thin placeholder
            """Placeholder that mimics :class:`discord.FFmpegPCMAudio`."""

            def __init__(self, source, executable=None, before_options=None, options=None):
                self.source = source
                self.executable = executable
                self.before_options = before_options
                self.options = options

    discord = _DiscordStub()  # type: ignore

from ..config import SETTINGS
from .music import ensure_music_dir


def _is_url(candidate: str) -> bool:
    """Return ``True`` if *candidate* appears to be an HTTP(S) URL."""

    return candidate.startswith(("http://", "https://"))


def _resolve_source(source: str) -> tuple[str, bool]:
    """Resolve the playable source path and whether it's a remote URL."""

    if not source:
        return "", False

    is_url = _is_url(source)
    if is_url:
        return source, True

    candidate = os.path.abspath(source)
    if os.path.exists(candidate):
        return candidate, False

    ensure_music_dir()
    fallback = os.path.abspath(os.path.join(SETTINGS.MUSIC_DIR, os.path.basename(source)))
    if os.path.exists(fallback):
        return fallback, False

    return "", False


async def ensure_voice(interaction: "discord.Interaction") -> Optional["discord.VoiceClient"]:
    """Ensure that the bot is connected to the user's current voice channel."""

    guild = getattr(interaction, "guild", None)
    if guild is None:
        await interaction.followup.send("This only works in a server (not DMs).", ephemeral=True)
        return None

    vc: "discord.VoiceClient | None" = getattr(guild, "voice_client", None)
    if vc and vc.is_connected():
        user = getattr(interaction, "user", None)
        user_voice = getattr(user, "voice", None)
        user_channel = getattr(user_voice, "channel", None)
        if user_channel and getattr(vc, "channel", None) != user_channel:
            await vc.move_to(user_channel)
        return vc

    user = getattr(interaction, "user", None)
    user_voice = getattr(user, "voice", None)
    if not user_voice or not getattr(user_voice, "channel", None):
        await interaction.followup.send(
            "Join a **voice channel** first so I can play intro music.", ephemeral=True
        )
        return None

    try:
        vc = await user_voice.channel.connect(reconnect=True)
        return vc
    except Exception as exc:  # pragma: no cover - defensive logging
        await interaction.followup.send(
            f"Couldn’t join your voice channel: `{exc}`", ephemeral=True
        )
        return None


async def play_clip(vc: "discord.VoiceClient", source: str, seconds: int = 15) -> None:
    """Play a short audio clip through an existing voice client."""

    if not source:
        return

    resolved, _ = _resolve_source(source)
    if not resolved:
        return

    before_opts = "-nostdin"
    if vc.is_playing():
        vc.stop()

    audio = discord.FFmpegPCMAudio(
        resolved,
        executable=SETTINGS.FFMPEG_PATH,
        before_options=before_opts,
        options=f"-vn -t {int(seconds)}",
    )

    try:
        vc.play(audio)
        waited = 0.0
        while vc.is_playing() and waited < seconds + 2:
            await asyncio.sleep(0.5)
            waited += 0.5
    finally:
        vc.stop()


__all__ = ["ensure_voice", "play_clip"]