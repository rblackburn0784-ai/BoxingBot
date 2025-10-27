import discord
from typing import Optional
from discord.ext import commands
from discord import app_commands

from ..models import Boxer, STAT_NAMES, get_weight_class
from ..services.roster import save_boxer, get_boxer, list_boxers, remove_boxer
from ..services.music import normalize_music_input, display_music_label
from ..services.stats import apply_weight_modifiers
from ..utils.discord_io import respond
from ..ui.components import BoxerSelectionView, MusicSelectionView

# ---------- Modals ----------

class _BasicsModal(discord.ui.Modal, title="Create Boxer — Basics"):
    def __init__(self):
        super().__init__(timeout=300)
        self.name = discord.ui.TextInput(
            label="Boxer Name", placeholder="Unique name", min_length=1, max_length=40
        )
        self.gender = discord.ui.TextInput(
            label="Gender", placeholder="male or female", required=False, max_length=10
        )
        self.weight = discord.ui.TextInput(
            label="Weight (kg)", placeholder="e.g., 66.7", required=False, max_length=10
        )
        self.trait = discord.ui.TextInput(
            label="Trait",
            placeholder="Granite Chin | Iron Body | Gas Tank | Sharp Eyes | Quick Feet",
            required=False, max_length=30
        )
        self.intro = discord.ui.TextInput(
            label="Intro (optional)", style=discord.TextStyle.paragraph, required=False, max_length=300
        )

        self.add_item(self.name)
        self.add_item(self.gender)
        self.add_item(self.weight)
        self.add_item(self.trait)
        self.add_item(self.intro)

        # values captured for next step
        self.data: dict = {}

    async def on_submit(self, interaction: discord.Interaction):
        n = self.name.value.strip()
        if get_boxer(n):
            return await interaction.response.send_message(
                "❌ A boxer with that name already exists. Please choose another name.",
                ephemeral=True
            )

        g = (self.gender.value or "male").strip().lower()
        if g not in {"male", "female"}:
            return await interaction.response.send_message("❌ Gender must be `male` or `female`.", ephemeral=True)

        # weight
        weight_str = (self.weight.value or "66.7").strip()
        try:
            wkg = float(weight_str)
        except ValueError:
            return await interaction.response.send_message("❌ Weight must be a number (kg).", ephemeral=True)

        tr = (self.trait.value or "").strip()
        if tr and tr not in {"Granite Chin","Iron Body","Gas Tank","Sharp Eyes","Quick Feet"}:
            return await interaction.response.send_message("❌ Invalid trait.", ephemeral=True)

        self.data = {
            "name": n,
            "gender": g,
            "weight_kg": wkg,
            "trait": tr,
            "intro": (self.intro.value or "").strip(),
        }

        # go to stats modal
        await interaction.response.send_modal(_StatsModal(self.data))


class _StatsModal(discord.ui.Modal, title="Create Boxer — Stats (max 60 total)"):
    def __init__(self, basics: dict):
        super().__init__(timeout=300)
        self.basics = basics

        # 8 stats as short inputs
        self.power = discord.ui.TextInput(label="Power", placeholder="0-60", max_length=3)
        self.speed = discord.ui.TextInput(label="Speed", placeholder="0-60", max_length=3)
        self.accuracy = discord.ui.TextInput(label="Accuracy", placeholder="0-60", max_length=3)
        self.defense = discord.ui.TextInput(label="Defense", placeholder="0-60", max_length=3)
        self.footwork = discord.ui.TextInput(label="Footwork", placeholder="0-60", max_length=3)
        self.stamina = discord.ui.TextInput(label="Stamina", placeholder="0-60", max_length=3)
        self.chin = discord.ui.TextInput(label="Chin", placeholder="0-60", max_length=3)
        self.body = discord.ui.TextInput(label="Body", placeholder="0-60", max_length=3)

        for i in (
            self.power, self.speed, self.accuracy, self.defense,
            self.footwork, self.stamina, self.chin, self.body
        ):
            self.add_item(i)

    def _parse_stat(self, s: str) -> Optional[int]:
        s = s.strip()
        if not s:
            return None
        try:
            v = int(s)
        except ValueError:
            return None
        return v

    async def on_submit(self, interaction: discord.Interaction):
        vals = {
            "power": self._parse_stat(self.power.value),
            "speed": self._parse_stat(self.speed.value),
            "accuracy": self._parse_stat(self.accuracy.value),
            "defense": self._parse_stat(self.defense.value),
            "footwork": self._parse_stat(self.footwork.value),
            "stamina": self._parse_stat(self.stamina.value),
            "chin": self._parse_stat(self.chin.value),
            "body": self._parse_stat(self.body.value),
        }

        if any(v is None for v in vals.values()):
            return await interaction.response.send_message("❌ All stats must be integers.", ephemeral=True)

        if any(v < 0 or v > 60 for v in vals.values()):  # per-stat sanity
            return await interaction.response.send_message("❌ Each stat must be between 0 and 60.", ephemeral=True)

        total = sum(vals.values())
        if total > 60:
            return await interaction.response.send_message(
                f"❌ Total points **{total}** exceed the 60-point cap. Please try again.",
                ephemeral=True
            )

        # Optional music selection
        await interaction.response.send_message(
            "🎵 (Optional) pick intro music, or close the menu to skip.",
            ephemeral=True
        )
        mv = MusicSelectionView(timeout=60)
        msg = await interaction.followup.send("Select a track (optional):", view=mv, ephemeral=True)
        await mv.wait()
        await msg.edit(view=None)

        chosen_music = mv.selected_music or ""

        b = Boxer(
            name=self.basics["name"],
            power=vals["power"], speed=vals["speed"], accuracy=vals["accuracy"], defense=vals["defense"],
            footwork=vals["footwork"], stamina=vals["stamina"], chin=vals["chin"], body=vals["body"],
            intro=self.basics["intro"], intro_music=chosen_music,
            gender=self.basics["gender"], weight_kg=self.basics["weight_kg"],
            weight_class=get_weight_class(self.basics["weight_kg"]), trait=self.basics["trait"]
        )

        # (Optional) ultra-sanity: re-check total (should already be ≤ 60)
        if (vals["power"] + vals["speed"] + vals["accuracy"] + vals["defense"]
            + vals["footwork"] + vals["stamina"] + vals["chin"] + vals["body"]) > 60:
            return await interaction.followup.send("❌ Stats exceed 60 after assembly. Aborting.", ephemeral=True)

        save_boxer(b)
        await interaction.followup.send(embed=boxer_embed(b))

def boxer_embed(b: Boxer) -> discord.Embed:
    corner_color = discord.Color.red() if b.gender == "male" else discord.Color.magenta()
    e = discord.Embed(title=f"🥊 {b.name}", color=corner_color)
    e.add_field(name="Gender", value=("Male ♂️" if b.gender == "male" else "Female ♀️"), inline=True)
    e.add_field(name="Weight", value=f"{b.weight_kg:.1f} kg • {b.weight_class.title()}", inline=True)
    e.add_field(name="Trait", value=b.trait or "—", inline=True)
    e.add_field(name="HP", value=str(b.max_hp()), inline=True)

    eff = apply_weight_modifiers(
        {
            "power": b.power, "speed": b.speed, "accuracy": b.accuracy,
            "defense": b.defense, "footwork": b.footwork, "stamina": b.stamina,
            "chin": b.chin, "body": b.body
        },
        b.weight_class
    )
    for s in STAT_NAMES:
        e.add_field(name=s.capitalize(), value=str(eff[s]))
    if b.intro_music:
        e.add_field(name="Intro Music", value=display_music_label(b.intro_music), inline=False)
    if b.intro:
        e.add_field(name="Intro", value=b.intro[:1024], inline=False)
    e.set_footer(text=f"Total base points: {b.total_points()} / 100 • Stats shown include weight-class modifiers")
    return e


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="boxer_create", description="Create a boxer (100 base points max).")
    @app_commands.describe(
        name="Unique boxer name",
        power="0-100", speed="0-100", accuracy="0-100", defense="0-100",
        footwork="0-100", stamina="0-100", chin="0-100", body="0-100",
        weight_kg="Weight in kg (e.g., 66.7)", gender="male or female",
        intro="Optional intro line",
        trait="Granite Chin | Iron Body | Gas Tank | Sharp Eyes | Quick Feet",
        intro_music="Filename like music.mp3 (stored in graphics/music)"
    )
    async def boxer_create(
        self,
        interaction: discord.Interaction,
        name: str,
        power: int, speed: int, accuracy: int, defense: int,
        footwork: int, stamina: int, chin: int, body: int,
        weight_kg: float = 66.7,
        gender: str = "male",
        intro: Optional[str] = None,
        trait: Optional[str] = None,
        intro_music: Optional[str] = None,
    ):
        await interaction.response.defer(thinking=False)

        stats = [power, speed, accuracy, defense, footwork, stamina, chin, body]
        if any(s < 0 or s > 100 for s in stats):
            return await respond(interaction, "Each stat must be between 0 and 100.", ephemeral=True)

        tr = (trait or "").strip()
        if tr and tr not in {"Granite Chin", "Iron Body", "Gas Tank", "Sharp Eyes", "Quick Feet"}:
            return await respond(interaction, "Invalid trait.", ephemeral=True)

        if get_boxer(name.strip()):
            return await respond(interaction, "A boxer with that name already exists.", ephemeral=True)

        # Optionally ask for music if not provided
        chosen_music: Optional[str] = None
        if not intro_music:
            await interaction.followup.send("🎵 (Optional) pick an intro track:", ephemeral=True)
            view = MusicSelectionView(timeout=60)
            msg = await interaction.followup.send("Select a track:", view=view, ephemeral=True)
            await view.wait()
            await msg.edit(view=None)
            chosen_music = view.selected_music
        else:
            chosen_music = normalize_music_input(intro_music or "")

        b = Boxer(
            name=name.strip(),
            power=power, speed=speed, accuracy=accuracy, defense=defense,
            footwork=footwork, stamina=stamina, chin=chin, body=body,
            intro=(intro or ""), intro_music=(chosen_music or ""),
            gender=gender, weight_kg=weight_kg,
            weight_class=get_weight_class(weight_kg), trait=tr
        )

        if b.total_points() > 100:
            return await respond(interaction, f"Total base points {b.total_points()} exceed 100.", ephemeral=True)

        save_boxer(b)
        await respond(interaction, embed=boxer_embed(b))

    @app_commands.command(
        name="boxer_set_music",
        description="Set/clear a boxer's intro music (filename in graphics/music)."
    )
    @app_commands.describe(
        name="(Optional) Pick from menu if omitted",
        intro_music="Filename like music.mp3 (stored in graphics/music; leave blank to open a menu)"
    )
    async def boxer_set_music(
        self,
        interaction: discord.Interaction,
        name: Optional[str] = None,
        intro_music: Optional[str] = None,
    ):
        names = list_boxers()
        if not names:
            return await interaction.response.send_message(
                "❌ No boxers exist yet. Use `/boxer_create` first.",
                ephemeral=True,
            )

        # Choose boxer if not provided
        if not name:
            await interaction.response.send_message("🎯 Select the boxer to update:", ephemeral=True)
            view = BoxerSelectionView(names, "Choose a boxer")
            await interaction.edit_original_response(view=view)
            await view.wait()
            if not view.selected_boxer:
                return await interaction.edit_original_response(
                    content="❌ No selection made. Command cancelled.",
                    view=None,
                )
            name = view.selected_boxer
            await interaction.edit_original_response(
                content=f"Selected **{name}**. Processing…",
                view=None,
            )
        else:
            await interaction.response.defer(ephemeral=True, thinking=False)

        b = get_boxer(name)
        if not b:
            return await interaction.followup.send(f"❌ Boxer **{name}** not found.", ephemeral=True)

        # If no music provided, open music picker
        if not intro_music:
            mv = MusicSelectionView(timeout=60)
            msg = await interaction.followup.send("🎵 Select intro music (or close to clear):", view=mv, ephemeral=True)
            await mv.wait()
            await msg.edit(view=None)
            chosen = mv.selected_music  # may be None if closed → clears music
        else:
            chosen = normalize_music_input(intro_music or "")

        b.intro_music = chosen or ""  # clear if None
        save_boxer(b)

        label = display_music_label(b.intro_music) if b.intro_music else "— (cleared)"
        await interaction.followup.send(
            f"🎵 Intro music for **{b.name}** set to **{label}**.",
            ephemeral=True,
        )

    @app_commands.command(name="boxer_set_intro", description="Set a boxer's intro line.")
    async def boxer_set_intro(self, interaction: discord.Interaction, name: str, intro: str):
        b = get_boxer(name)
        if not b:
            return await interaction.response.send_message("No such boxer.", ephemeral=True)
        b.intro = intro
        save_boxer(b)
        await interaction.response.send_message(f"Updated intro for **{b.name}**.", ephemeral=True)

    @app_commands.command(name="boxer_set_gender", description="Set a boxer's gender.")
    async def boxer_set_gender(self, interaction: discord.Interaction, name: str, gender: str):
        b = get_boxer(name)
        if not b:
            return await interaction.response.send_message("No such boxer.", ephemeral=True)
        b.gender = gender
        save_boxer(b)
        await interaction.response.send_message(f"Updated gender for **{b.name}** to **{b.gender}**.", ephemeral=True)

    @app_commands.command(name="boxer_set_weight", description="Set a boxer's weight (kg).")
    async def boxer_set_weight(self, interaction: discord.Interaction, name: str, weight_kg: float):
        b = get_boxer(name)
        if not b:
            return await interaction.response.send_message("No such boxer.", ephemeral=True)
        b.weight_kg = float(weight_kg)
        b.weight_class = get_weight_class(b.weight_kg)
        save_boxer(b)
        await interaction.response.send_message(
            f"Updated **{b.name}** to {b.weight_kg:.1f} kg — {b.weight_class.title()}.",
            ephemeral=True
        )

    @app_commands.command(name="boxer_show", description="Show a boxer.")
    @app_commands.describe(name="(Optional) Boxer name; leave blank to pick from a list")
    async def boxer_show(self, interaction: discord.Interaction, name: Optional[str] = None):
        names = list_boxers()
        if not names:
            return await interaction.response.send_message(
                "No boxers yet. Use /boxer_create to add one.", ephemeral=True
            )

        if name:
            b = get_boxer(name)
            if b:
                return await interaction.response.send_message(embed=boxer_embed(b))
            else:
                await interaction.response.send_message(
                    f"'{name}' not found — pick from the list below.", ephemeral=True
                )
        else:
            await interaction.response.send_message("👀 Select a boxer to show:", ephemeral=True)

        view = BoxerSelectionView(names, "Choose a boxer to view")
        await interaction.edit_original_response(view=view)
        await view.wait()

        if not view.selected_boxer:
            return await interaction.edit_original_response(
                content="❌ No selection made. Command cancelled.", view=None
            )

        await interaction.edit_original_response(
            content=f"Showing **{view.selected_boxer}**…", view=None
        )
        b = get_boxer(view.selected_boxer)
        if not b:
            return await interaction.followup.send("Could not load that boxer.")
        await interaction.followup.send(embed=boxer_embed(b))

    @app_commands.command(name="boxer_list", description="List saved boxers.")
    async def boxer_list(self, interaction: discord.Interaction):
        names = list_boxers()
        if not names:
            return await interaction.response.send_message("No boxers yet. Use /boxer_create.", ephemeral=True)
        await interaction.response.send_message(f"**Saved boxers:** {', '.join(names)}")

    @app_commands.command(name="boxer_remove", description="Remove a boxer (with dropdown).")
    async def boxer_remove(self, interaction: discord.Interaction):
        names = list_boxers()
        if not names:
            return await interaction.response.send_message("❌ No boxers exist.", ephemeral=True)
        await interaction.response.send_message("🗑️ Select the boxer to remove:", ephemeral=True)
        view = BoxerSelectionView(names, "Choose a boxer to delete")
        await interaction.edit_original_response(view=view)
        await view.wait()
        if not view.selected_boxer:
            return await interaction.edit_original_response(content="❌ No selection made.", view=None)
        ok = remove_boxer(view.selected_boxer)
        msg = "removed" if ok else "not found"
        await interaction.edit_original_response(content=f"🗑️ Boxer **{view.selected_boxer}** {msg}.", view=None)

    @app_commands.command(name="boxer_create_wizard", description="UI wizard to create a boxer (max 60 stat points).")
    async def boxer_create_wizard(self, interaction: discord.Interaction):
        # Open the first modal
        await interaction.response.send_modal(_BasicsModal())

async def setup(bot: commands.Bot):
    await bot.add_cog(Roster(bot))
