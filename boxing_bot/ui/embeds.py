import discord
from ..models import Boxer, STAT_NAMES, gender_badge
from ..services.stats import apply_weight_modifiers
from ..services.music import display_music_label

def _bar(val: int, width: int = 10, fill: str = "█", empty: str = "—") -> str:
    val = max(0, min(100, val))
    n = round((val/100) * width)
    return fill*n + empty*(width-n)


def boxer_embed(b: Boxer) -> discord.Embed:
    corner_color = discord.Color.red() if b.gender == "male" else discord.Color.magenta()
    e = discord.Embed(title=f"🥊 {b.name}", color=corner_color)

    e.add_field(name="Gender", value=("Male ♂️" if b.gender == "male" else "Female ♀️"), inline=True)
    e.add_field(name="Weight", value=f"{b.weight_kg:.1f} kg • {b.weight_class.title()}", inline=True)
    e.add_field(name="Trait", value=b.trait or "—", inline=True)
    e.add_field(name="HP", value=str(b.max_hp()), inline=True)

    eff = apply_weight_modifiers(
        {
            "power": b.power, "speed": b.speed, "accuracy": b.accuracy, "defense": b.defense,
            "footwork": b.footwork, "stamina": b.stamina, "chin": b.chin, "body": b.body
        },
        b.weight_class
    )
    for s in STAT_NAMES:
        e.add_field(name=s.capitalize(), value=str(eff[s]))

    if b.intro_music:
        e.add_field(name="Intro Music", value=display_music_label(b.intro_music), inline=False)
    if b.intro:
        e.add_field(name="Intro", value=b.intro[:1024], inline=False)

    e.set_footer(text=f"Total base points: {b.total_points()} / 60 • Stats shown include weight-class modifiers")
    return e
