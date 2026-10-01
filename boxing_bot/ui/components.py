import discord
from typing import List, Optional
from discord.ui import View, Select
from ..services.music import list_music_files, display_music_label

class BoxerSelect(Select):
    def __init__(self, boxers: list[str], placeholder: str):
        options=[discord.SelectOption(label=name[:100], value=name) for name in boxers[:25]]
        super().__init__(placeholder=placeholder[:150], min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_boxer=self.values[0]; await interaction.response.defer(); self.view.stop()

class BoxerSelectionView(View):
    PAGE_SIZE=23
    def __init__(self, boxers: list[str], placeholder: str):
        super().__init__(timeout=60); self.selected_boxer=None; self.boxers=list(boxers); self.placeholder=placeholder; self.page=0; self._render()
    def _render(self):
        self.clear_items(); start=self.page*self.PAGE_SIZE; chunk=self.boxers[start:start+self.PAGE_SIZE]
        self.add_item(BoxerSelect(chunk, f"{self.placeholder} ({self.page+1}/{max(1,(len(self.boxers)+self.PAGE_SIZE-1)//self.PAGE_SIZE)})"))
        if len(self.boxers)>self.PAGE_SIZE:
            prev=discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=self.page==0)
            nxt=discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(start+self.PAGE_SIZE)>=len(self.boxers))
            async def p(i): self.page-=1; self._render(); await i.response.edit_message(view=self)
            async def n(i): self.page+=1; self._render(); await i.response.edit_message(view=self)
            prev.callback=p; nxt.callback=n; self.add_item(prev); self.add_item(nxt)

class MusicSelect(Select):
    def __init__(self, pairs):
        opts=[discord.SelectOption(label=lbl[:100],value=val) for lbl,val in pairs[:25]]
        super().__init__(placeholder="Choose intro music (MP3)", min_values=1,max_values=1,options=opts)
    async def callback(self, interaction): self.view.selected_music=self.values[0]; await interaction.response.defer(); self.view.stop()
class MusicSelectionView(View):
    def __init__(self, timeout=60):
        super().__init__(timeout=timeout); self.selected_music=None
        files=list_music_files(); pairs=[(display_music_label(p),p) for p in files][:25]
        if pairs: self.add_item(MusicSelect(pairs))
