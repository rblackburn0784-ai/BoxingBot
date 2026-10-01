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
from ..ui.embeds import boxer_embed

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

        # Discord does not allow a modal submit to directly open another modal.
        # Hand off through a user-locked ephemeral button instead.
        await interaction.response.send_message(
            "✅ Basics saved. Continue to **Stats 1/2**.",
            view=_Stats1ContinueView(self.data, interaction.user.id),
            ephemeral=True,
        )


class _WizardContinueView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This wizard belongs to another user.", ephemeral=True)
            return False
        return True


class _Stats1ContinueView(_WizardContinueView):
    def __init__(self, basics: dict, owner_id: int):
        super().__init__(owner_id)
        self.basics = dict(basics)

    @discord.ui.button(label="Continue — Stats 1/2", emoji="📊", style=discord.ButtonStyle.primary)
    async def continue_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_StatsModal(self.basics))


class _Stats2ContinueView(_WizardContinueView):
    def __init__(self, basics: dict, vals: dict, owner_id: int):
        super().__init__(owner_id)
        self.basics = dict(basics)
        self.vals = dict(vals)

    @discord.ui.button(label="Continue — Stats 2/2", emoji="🥊", style=discord.ButtonStyle.success)
    async def continue_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_StatsModal2(self.basics, self.vals))


class _StatsModal(discord.ui.Modal, title="Create Boxer — Stats 1/2"):
    def __init__(self, basics):
        super().__init__(timeout=300); self.basics=basics
        self.inputs={k:discord.ui.TextInput(label=k.title(),placeholder="0-20",max_length=2) for k in ("power","speed","accuracy","defense")}
        for x in self.inputs.values(): self.add_item(x)
    async def on_submit(self, interaction):
        vals={}
        try: vals={k:int(v.value.strip()) for k,v in self.inputs.items()}
        except ValueError: return await interaction.response.send_message("❌ All stats must be integers.",ephemeral=True)
        if any(v<0 or v>20 for v in vals.values()): return await interaction.response.send_message("❌ Each stat must be 0-20 in V2.",ephemeral=True)
        await interaction.response.send_message(
            "✅ First four stats saved. Continue to **Stats 2/2**.",
            view=_Stats2ContinueView(self.basics, vals, interaction.user.id),
            ephemeral=True,
        )

class _StatsModal2(discord.ui.Modal, title="Create Boxer — Stats 2/2"):
    def __init__(self, basics, vals):
        super().__init__(timeout=300); self.basics=basics; self.vals=vals
        self.inputs={k:discord.ui.TextInput(label=k.title(),placeholder="0-20",max_length=2) for k in ("footwork","stamina","chin","body")}
        for x in self.inputs.values(): self.add_item(x)
    async def on_submit(self, interaction):
        try: vals={**self.vals, **{k:int(v.value.strip()) for k,v in self.inputs.items()}}
        except ValueError: return await interaction.response.send_message("❌ All stats must be integers.",ephemeral=True)
        if any(v<0 or v>20 for v in vals.values()): return await interaction.response.send_message("❌ Each stat must be 0-20 in V2.",ephemeral=True)
        total=sum(vals.values())
        if total != 60: return await interaction.response.send_message(f"❌ V2 boxers must use exactly **60 base points**; this build uses **{total}**.",ephemeral=True)
        b=Boxer(name=self.basics["name"], intro=self.basics["intro"], intro_music="", gender=self.basics["gender"], weight_kg=self.basics["weight_kg"], weight_class=get_weight_class(self.basics["weight_kg"]), trait=self.basics["trait"], **vals)
        save_boxer(b)
        await interaction.response.send_message("✅ Boxer created. Use `/boxer_set_music` to choose intro music.",embed=boxer_embed(b),ephemeral=True)


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="boxer_create", description="Create a boxer (60 base points max).")
    @app_commands.describe(
        name="Unique boxer name",
        power="0-20", speed="0-20", accuracy="0-20", defense="0-20",
        footwork="0-20", stamina="0-20", chin="0-20", body="0-20",
        weight_kg="Weight in kg (e.g., 66.7)", gender="male or female",
        intro="Optional intro line",
        trait="Granite Chin | Iron Body | Gas Tank | Sharp Eyes | Quick Feet",
        intro_music="Filename like music.mp3 (stored in graphics/music)"
    )
    @app_commands.checks.has_permissions(administrator=True)
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
        if any(s < 0 or s > 20 for s in stats):
            return await respond(interaction, "Each V2 base stat must be between 0 and 20.", ephemeral=True)

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

        if b.total_points() != 60:
            return await respond(interaction, f"V2 boxers must use exactly 60 base points; this build uses {b.total_points()}.", ephemeral=True)

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
    @app_commands.checks.has_permissions(administrator=True)
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
            chosen = normalize_music_input(mv.selected_music or "") if mv.selected_music else None
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
    @app_commands.checks.has_permissions(administrator=True)
    async def boxer_set_intro(self, interaction: discord.Interaction, name: str, intro: str):
        b = get_boxer(name)
        if not b:
            return await interaction.response.send_message("No such boxer.", ephemeral=True)
        b.intro = intro
        save_boxer(b)
        await interaction.response.send_message(f"Updated intro for **{b.name}**.", ephemeral=True)

    @app_commands.command(name="boxer_set_gender", description="Set a boxer's gender.")
    @app_commands.checks.has_permissions(administrator=True)
    async def boxer_set_gender(self, interaction: discord.Interaction, name: str, gender: str):
        b = get_boxer(name)
        if not b:
            return await interaction.response.send_message("No such boxer.", ephemeral=True)
        b.gender = gender
        save_boxer(b)
        await interaction.response.send_message(f"Updated gender for **{b.name}** to **{b.gender}**.", ephemeral=True)

    @app_commands.command(name="boxer_set_weight", description="Set a boxer's weight (kg).")
    @app_commands.checks.has_permissions(administrator=True)
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
    @app_commands.checks.has_permissions(administrator=True)
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

    @app_commands.command(name="boxer_create_wizard", description="UI wizard to create a boxer (max 60 base points).")
    @app_commands.checks.has_permissions(administrator=True)
    async def boxer_create_wizard(self, interaction: discord.Interaction):
        # Open the first modal
        await interaction.response.send_modal(_BasicsModal())

async def setup(bot: commands.Bot):
    await bot.add_cog(Roster(bot))
