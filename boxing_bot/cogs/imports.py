# boxing_bot/cogs/imports.py
import discord
from discord import app_commands
from discord.ext import commands
from ..services.sheets import upsert_boxers_from_sheet


# Typical boxing classes -> (min_kg, max_kg)  (approx; we’ll use midpoint)
_WEIGHT_CLASS_KG = {
    "strawweight": (0.0, 47.6),
    "light flyweight": (47.6, 49.0),
    "flyweight": (49.0, 50.8),
    "super flyweight": (50.8, 52.2),
    "bantamweight": (52.2, 53.5),
    "super bantamweight": (53.5, 55.3),
    "featherweight": (55.3, 57.2),
    "super featherweight": (57.2, 59.0),
    "lightweight": (59.0, 61.2),
    "super lightweight": (61.2, 63.5),
    "welterweight": (63.5, 66.7),
    "super welterweight": (66.7, 69.9),
    "middleweight": (69.9, 72.6),
    "super middleweight": (72.6, 76.2),
    "light heavyweight": (76.2, 79.4),
    "cruiserweight": (79.4, 90.7),
    "bridgerweight": (90.7, 101.6),
    "heavyweight": (101.6, 200.0),  # open upper bound
}

def _weight_kg_from_class(label: str, default: float = 66.7) -> float:
    if not label:
        return default
    key = str(label).strip().lower()
    # strip anything after first "(" e.g. "Bantamweight (≤53.5 kg / 118 lb)"
    key = key.split("(", 1)[0].strip()
    rng = _WEIGHT_CLASS_KG.get(key)
    if not rng:
        return default
    lo, hi = rng
    return round((lo + hi) / 2.0, 1)


class Imports(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="boxers_import_sheet",
                          description="Import/Update boxers from a Google Sheet (service account must have access).")
    @app_commands.describe(
        sheet_id_or_url="https://docs.google.com/spreadsheets/d/1nhdVrd9f4N-w_3vNAwh_mzGhWRDJrnyF-uccQQbAFPY/edit?usp=sharing",
        tab_or_range="Tab name or A1 range (e.g., Roster!A1:O)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def boxers_import_sheet(self, interaction: discord.Interaction,
                                  sheet_id_or_url: str,
                                  tab_or_range: str = "Sheet1!A1:Z"):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            res = upsert_boxers_from_sheet(sheet_id_or_url, tab_or_range)
            await interaction.followup.send(
                f"✅ Import complete: {res['inserted']} inserted, {res['updated']} updated, {res['skipped']} skipped.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Import failed: `{type(e).__name__}: {e}`", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Imports(bot))
