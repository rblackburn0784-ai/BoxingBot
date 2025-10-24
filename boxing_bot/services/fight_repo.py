"""Persistence helpers for fight state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, MutableMapping, Optional

from boxing_bot.config import SETTINGS
from boxing_bot.storage import db

FightState = Dict[str, Any]


def _normalise_fight_id(value: Any) -> str:
    """Convert *value* into the canonical fight identifier string."""

    result = str(value)
    if not result:
        raise ValueError("fight id must not be empty")
    return result


def save_fight(state_dict: MutableMapping[str, Any]) -> str:
    """Persist ``state_dict`` into the fight repository.

    Parameters
    ----------
    state_dict:
        Mapping describing the fight state.  It must at minimum provide an
        ``"id"`` key whose value uniquely identifies the fight.

    Returns
    -------
    str
        The canonical identifier assigned to the fight.
    """

    if "id" not in state_dict:
        raise KeyError("fight state must include an 'id' key")

    fight_id = _normalise_fight_id(state_dict["id"])
    data = db.read(SETTINGS.DB_FILE)
    fights = data.setdefault("fights", {})
    fights[fight_id] = deepcopy(dict(state_dict))
    db.write(SETTINGS.DB_FILE, data)
    return fight_id


def load_fight(fid: Any) -> Optional[FightState]:
    """Return the persisted fight state for ``fid`` if it exists."""

    fight_id = _normalise_fight_id(fid)
    data = db.read(SETTINGS.DB_FILE)
    fights = data.get("fights", {})
    fight = fights.get(fight_id)
    if fight is None:
        return None
    return deepcopy(fight)


__all__ = ["load_fight", "save_fight", "FightState"]