"""Core combat routines for BoxingBot."""
from __future__ import annotations

import importlib
import random
from types import SimpleNamespace
from typing import Any, Dict

# ``discord`` is an optional dependency during testing. When the real library
# is unavailable we substitute a very small stub that exposes the handful of
# attributes the service uses. This keeps the combat logic importable in a
# minimal environment.
if (spec := importlib.util.find_spec("discord")) is not None:  # pragma: no cover - exercised when discord is installed
    discord = importlib.import_module("discord")
else:  # pragma: no cover - simple compatibility shim
    class _FollowupStub:
        async def send(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401 - simple stub
            """Pretend to send a message."""

    class _InteractionStub:
        followup = _FollowupStub()

    class _EmbedStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class _ColorStub:
        @staticmethod
        def red() -> int:
            return 0xFF0000

    discord = SimpleNamespace(Interaction=_InteractionStub, Embed=_EmbedStub, Color=_ColorStub)  # type: ignore[assignment]


from ..config import SETTINGS
from ..models import FightSession, FighterState

CROWD_LINES = SETTINGS.get(
    "crowd_lines",
    {
        "heavy": "🔥 {color} lands a bomb — oohs from the crowd!",
        "ooh": "👏 Huge shot from {color}!",
        "miss": "😬 Whiff from {color}.",
    },
)


def corner_assignments(A: FighterState, B: FighterState) -> Any:
    """Determine the matchup key for selecting presentation assets."""

    genders = (getattr(A, "gender", "M"), getattr(B, "gender", "M"))
    if genders == ("M", "M"):
        key = "MM"
    elif set(genders) == {"M", "F"}:
        key = "MF"
    else:
        key = "FF"
    return type("Matchup", (), {"gender_key": key})


def attack_exchange(attacker: FighterState, defender: FighterState, rng: random.Random) -> Dict[str, Any]:
    """Resolve a single attack exchange between fighters."""

    roll = rng.randint(1, 100)
    event: Dict[str, Any] = {}

    if roll >= 80:
        dmg = rng.randint(10, 18)
        defender.hp = max(0, defender.hp - dmg)
        event["outcome"] = "hit"
        event["crowd_tag"] = "heavy"
        event["summary"] = f"{attacker.name} lands heavy leather ({dmg})."
    elif roll >= 55:
        dmg = rng.randint(4, 9)
        defender.hp = max(0, defender.hp - dmg)
        event["outcome"] = "hit"
        event["crowd_tag"] = "ooh"
        event["summary"] = f"{attacker.name} scores with a clean shot ({dmg})."
    elif roll <= 10:
        event["outcome"] = "miss"
        event["crowd_tag"] = "miss"
        event["summary"] = f"{attacker.name} whiffs."
    else:
        event["outcome"] = "exchange"
        event["summary"] = f"{attacker.name} and {defender.name} trade but nothing big."

    attacker.adr = min(100, getattr(attacker, "adr", 0) + 3)
    defender.adr = min(100, getattr(defender, "adr", 0) + 2)

    sess = getattr(attacker, "session", None)
    if defender.hp <= 0 and sess:
        sess.is_over = True
        sess.result = "KO"
        sess.winner = attacker.name

    return event


async def send_round_card(interaction: "discord.Interaction", session: FightSession) -> None:
    """Send an embed summarising the current round."""

    highlight = f"{session.A.name if session.A.adr >= session.B.adr else session.B.name} had the edge that round."
    embed = discord.Embed(title=f"Round {session.round_no} — Highlight", description=highlight)
    await interaction.followup.send(embed=embed)


async def send_finish_announcement(interaction: "discord.Interaction", session: FightSession) -> None:
    """Send an embed announcing the winner when the fight concludes."""

    title = f"{session.result}!"
    desc = f"Winner: **{session.winner}**"
    embed = discord.Embed(title=title, description=desc, color=discord.Color.red())
    await interaction.followup.send(embed=embed)


async def send_points_decision(interaction: "discord.Interaction", session: FightSession) -> None:
    """Send an embed summarising the judges' decision when the fight reaches the scorecards."""

    embed = discord.Embed(title="Decision", description="Fight goes to the cards. (Stub)")
    await interaction.followup.send(embed=embed)


def finalize_if_done(session: FightSession) -> bool:
    """Mark the fight finished if either fighter's HP has been depleted."""

    if session.A.hp <= 0:
        session.is_over = True
        session.result = "KO"
        session.winner = session.B.name
    elif session.B.hp <= 0:
        session.is_over = True
        session.result = "KO"
        session.winner = session.A.name
    return getattr(session, "is_over", False)


__all__ = [
    "CROWD_LINES",
    "corner_assignments",
    "attack_exchange",
    "send_round_card",
    "send_finish_announcement",
    "send_points_decision",
    "finalize_if_done",
]