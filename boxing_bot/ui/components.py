from __future__ import annotations

"""Discord UI components used throughout the bot."""

from typing import Iterable, List, Optional, Sequence

import discord
from discord.ui import Select, View

from ..services.music import display_music_label, list_music_files

__all__ = [
    "BoxerSelect",
    "BoxerSelectionView",
    "MusicSelect",
    "MusicSelectionView",
]


class BoxerSelect(Select):
    """A single-select drop-down listing available boxers."""

    def __init__(self, boxers: Sequence[str], placeholder: str) -> None:
        options = [
            discord.SelectOption(label=name.title(), value=name)
            for name in boxers
        ]
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:  # pragma: no cover - discord runtime
        view = self.view
        if view is None:  # Defensive guard; discord.py guarantees this at runtime.
            return

        view.selected_boxer = self.values[0]
        await interaction.response.defer()
        view.stop()


class BoxerSelectionView(View):
    """View wrapper that exposes the :class:`BoxerSelect` dropdown."""

    def __init__(self, boxers: Sequence[str], placeholder: str, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.selected_boxer: Optional[str] = None
        self.add_item(BoxerSelect(boxers, placeholder))


class MusicSelect(Select):
    """A drop-down allowing the user to choose intro music for a boxer."""

    def __init__(self, options_labels_and_values: Iterable[tuple[str, str]]) -> None:
        options = [
            discord.SelectOption(label=label, value=value, default=not value)
            for label, value in options_labels_and_values
        ]
        # If the only option has an empty value, disable the select entirely so the
        # user cannot submit an invalid choice.
        disabled = len(options) == 1 and not options[0].value

        super().__init__(
            placeholder="Choose intro music (MP3)",
            min_values=1,
            max_values=1,
            options=options,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:  # pragma: no cover - discord runtime
        view = self.view
        if view is None:
            return

        view.selected_music = self.values[0]
        await interaction.response.defer()
        view.stop()


class MusicSelectionView(View):
    """View wrapper for selecting intro music files."""

    def __init__(self, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.selected_music: Optional[str] = None

        files = list_music_files()
        pairs: List[tuple[str, str]] = [
            (display_music_label(path), path) for path in files
        ][:25]  # Discord hard limit is 25 options.

        if not pairs:
            pairs = [("No MP3s found in graphics/music", "")]

        self.add_item(MusicSelect(pairs))