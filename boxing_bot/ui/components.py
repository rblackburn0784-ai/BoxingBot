# boxing_bot/ui/components.py
import os
import discord
from typing import List, Optional
from discord.ui import View, Select
from ..services.music import list_music_files, display_music_label

class BoxerSelect(Select):
    def __init__(self, boxers: list[str], placeholder: str):
        options = [discord.SelectOption(label=name.title(), value=name) for name in boxers]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_boxer = self.values[0]
        await interaction.response.defer()
        self.view.stop()

class BoxerSelectionView(View):
    def __init__(self, boxers: list[str], placeholder: str):
        super().__init__(timeout=60)
        self.selected_boxer: str | None = None
        self.add_item(BoxerSelect(boxers, placeholder))
class MusicSelect(Select):
    def __init__(self, options_labels_and_values: List[tuple[str, str]]):
        opts = [discord.SelectOption(label=lbl, value=val) for lbl, val in options_labels_and_values]
        super().__init__(placeholder="Choose intro music (MP3)", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_music = self.values[0]
        await interaction.response.defer()  # ack the selection
        self.view.stop()

class MusicSelectionView(View):
    def __init__(self, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.selected_music: Optional[str] = None

        files = list_music_files()
        # show filename (no extension) as label, full path as value
        pairs = [(display_music_label(p), p) for p in files][:25]  # Discord hard limit is 25 options
        if not pairs:
            pairs = [("No MP3s found in graphics/music", "")]
