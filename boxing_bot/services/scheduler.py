"""Async helpers for periodically saving the bot state."""

from __future__ import annotations

import asyncio
from typing import Callable, Mapping, Any

from boxing_bot.config import SETTINGS
from boxing_bot.storage.db import save_db


LoopStateCallable = Callable[[], Mapping[str, Any]]


async def autosave(loop_state_callable: LoopStateCallable, interval: float = 30) -> None:
    """Periodically persist the current loop state to disk.

    Parameters
    ----------
    loop_state_callable:
        Callable returning the serializable loop state that should be saved.
    interval:
        Number of seconds to wait between saves.
    """

    while True:
        await asyncio.sleep(interval)
        data = loop_state_callable()
        save_db(SETTINGS.DB_FILE, data)