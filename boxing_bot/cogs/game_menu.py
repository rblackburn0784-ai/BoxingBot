from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from ..models import Boxer, STAT_NAMES, get_weight_class
from ..services.roster import get_boxer, save_boxer, list_boxers
from ..services import game, tournaments
from ..storage import v2db
from ..ui.embeds import boxer_embed

TRAITS = {"", "Granite Chin", "Iron Body", "Gas Tank", "Sharp Eyes", "Quick Feet"}


def _guild_id(interaction: discord.Interaction) -> int:
    if not interaction.guild_id:
        raise ValueError("BoxingBot V2 menus must be used inside a server.")
    return int(interaction.guild_id)


def _is_admin(interaction: discord.Interaction) -> bool:
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


def profile_embed(name: str) -> discord.Embed:
    boxer = get_boxer(name)
    data = game.profile(name)
    s = data["stats"]
    p = data["profile"]
    title = f" • {p['title']}" if p.get("title") else ""
    e = discord.Embed(title=f"🥊 {name}{title}", color=discord.Color.gold())
    if boxer:
        e.description = f"**{boxer.weight_class.title()}** • {boxer.weight_kg:.1f} kg • {boxer.trait or 'No trait'}"
    e.add_field(name="Career", value=f"**{s['wins']}-{s['losses']}-{s['draws']}**  ({s['fights']} fights)", inline=True)
    e.add_field(name="Stoppages", value=f"KO {s['kos']} • TKO {s['tkos']}", inline=True)
    e.add_field(name="Level", value=f"{p['level']}  •  {p['xp']} XP", inline=True)
    e.add_field(name="Knockdowns", value=f"For {s['knockdowns_for']} • Against {s['knockdowns_against']}", inline=True)
    e.add_field(name="Win Streak", value=f"Current {s['current_win_streak']} • Best {s['best_win_streak']}", inline=True)
    e.add_field(name="Tournament Record", value=f"Entries {s['tournament_entries']} • 🏆 {s['tournament_titles']} • 🥈 {s['tournament_runner_ups']}", inline=True)
    e.add_field(name="Achievements", value=str(len(data["achievements"])), inline=True)
    e.set_footer(text="V2 progression is prestige-only: levels and achievements never add combat stats.")
    return e


def tournament_embed(t) -> discord.Embed:
    ent = tournaments.entries(t["id"])
    e = discord.Embed(title=f"🏆 {t['name']}", color=discord.Color.blurple())
    e.description = f"Status: **{t['status'].replace('_',' ').title()}** • Entries: **{len(ent)}/{t['max_entries']}**"
    if t["status"] == "active":
        e.add_field(name="Current Round", value=str(t["current_round"]), inline=True)
        pending = tournaments.pending_matches(t["id"])
        e.add_field(name="Bouts Remaining", value=str(len(pending)), inline=True)
        if pending:
            m = pending[0]
            e.add_field(name="Next Bout", value=f"🔴 **{m['red_name']}** vs 🔵 **{m['blue_name']}**", inline=False)
    elif t["status"] == "complete":
        e.add_field(name="Champion", value=f"🏆 **{t['champion_name'] or '—'}**", inline=False)
        e.add_field(name="Runner-up", value=t["runner_up_name"] or "—", inline=False)
    if ent:
        shown = [f"{r['seed'] or '•'}. {r['boxer_name']}{' ❌' if r['eliminated'] else ''}" for r in ent[:20]]
        e.add_field(name="Field", value="\n".join(shown), inline=False)
    report = tournaments.tournament_report(t["id"])
    if report["bouts"]:
        e.add_field(name="Tournament Stats", value=f"Bouts {report['bouts']} • KO {report['ko']} • TKO {report['tko']} • Points {report['points']}\nKnockdowns {report['knockdowns']} • Total damage {report['damage']}", inline=False)
    return e


class CreateBasicsModal(discord.ui.Modal, title="Create Your Boxer — Identity"):
    name = discord.ui.TextInput(label="Boxer name", min_length=1, max_length=40)
    weight = discord.ui.TextInput(label="Weight (kg)", default="66.7", max_length=8)
    gender = discord.ui.TextInput(label="Gender", default="male", max_length=10)
    trait = discord.ui.TextInput(label="Trait (optional)", required=False, max_length=30, placeholder="Granite Chin / Iron Body / Gas Tank / Sharp Eyes / Quick Feet")
    intro = discord.ui.TextInput(label="Ring intro (optional)", required=False, max_length=300, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = _guild_id(interaction)
        if game.get_owned_boxer(guild_id, interaction.user.id):
            return await interaction.response.send_message("❌ You already have a linked boxer. Open **My Boxer** to edit it.", ephemeral=True)
        name = self.name.value.strip()
        if get_boxer(name):
            return await interaction.response.send_message("❌ That boxer name already exists.", ephemeral=True)
        try:
            weight = float(self.weight.value)
        except ValueError:
            return await interaction.response.send_message("❌ Weight must be a number.", ephemeral=True)
        gender = self.gender.value.strip().lower()
        if gender not in {"male", "female"}:
            return await interaction.response.send_message("❌ Gender must be male or female.", ephemeral=True)
        trait = self.trait.value.strip()
        if trait not in TRAITS:
            return await interaction.response.send_message("❌ Invalid trait.", ephemeral=True)
        basics = {"name": name, "weight_kg": weight, "gender": gender, "trait": trait, "intro": self.intro.value.strip()}
        await interaction.response.send_message(
            "✅ Identity saved. Continue to **Stats 1/2** to build your boxer.",
            view=CreateStats1ContinueView(basics, interaction.user.id),
            ephemeral=True,
        )


class _OwnerOnlyContinueView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This setup belongs to another user.", ephemeral=True)
            return False
        return True


class CreateStats1ContinueView(_OwnerOnlyContinueView):
    def __init__(self, basics: dict, owner_id: int):
        super().__init__(owner_id)
        self.basics = dict(basics)

    @discord.ui.button(label="Continue — Stats 1/2", emoji="📊", style=discord.ButtonStyle.primary)
    async def continue_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateStats1Modal(self.basics))


class CreateStats2ContinueView(_OwnerOnlyContinueView):
    def __init__(self, basics: dict, vals: dict, owner_id: int):
        super().__init__(owner_id)
        self.basics = dict(basics)
        self.vals = dict(vals)

    @discord.ui.button(label="Continue — Stats 2/2", emoji="🥊", style=discord.ButtonStyle.success)
    async def continue_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateStats2Modal(self.basics, self.vals))


class CreateStats1Modal(discord.ui.Modal, title="Create Your Boxer — Stats 1/2"):
    def __init__(self, basics: dict):
        super().__init__(timeout=300)
        self.basics = basics
        self.fields = {}
        for key in ("power", "speed", "accuracy", "defense"):
            x = discord.ui.TextInput(label=key.title(), default="7", max_length=2)
            self.fields[key] = x
            self.add_item(x)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            vals = {k: int(v.value) for k, v in self.fields.items()}
        except ValueError:
            return await interaction.response.send_message("❌ Stats must be whole numbers.", ephemeral=True)
        await interaction.response.send_message(
            "✅ First four stats saved. Continue to **Stats 2/2**.",
            view=CreateStats2ContinueView(self.basics, vals, interaction.user.id),
            ephemeral=True,
        )


class CreateStats2Modal(discord.ui.Modal, title="Create Your Boxer — Stats 2/2"):
    def __init__(self, basics: dict, vals: dict):
        super().__init__(timeout=300)
        self.basics, self.vals = basics, vals
        self.fields = {}
        for key in ("footwork", "stamina", "chin", "body"):
            x = discord.ui.TextInput(label=key.title(), default="7", max_length=2)
            self.fields[key] = x
            self.add_item(x)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            vals = {**self.vals, **{k: int(v.value) for k, v in self.fields.items()}}
        except ValueError:
            return await interaction.response.send_message("❌ Stats must be whole numbers.", ephemeral=True)
        if any(v < 0 or v > 20 for v in vals.values()):
            return await interaction.response.send_message("❌ V2 base stats must be between 0 and 20.", ephemeral=True)
        total = sum(vals.values())
        if total != 60:
            return await interaction.response.send_message(f"❌ V2 boxers use **exactly 60 base points**. Your total is **{total}**.", ephemeral=True)
        guild_id = _guild_id(interaction)
        if game.get_owned_boxer(guild_id, interaction.user.id):
            return await interaction.response.send_message("❌ You already have a linked boxer.", ephemeral=True)
        b = Boxer(weight_class=get_weight_class(self.basics["weight_kg"]), intro_music="", **self.basics, **vals)
        save_boxer(b)
        game.ensure_profile(b.name, guild_id, interaction.user.id)
        game.link_boxer(b.name, guild_id, interaction.user.id)
        v2db.audit(guild_id, interaction.user.id, "player_boxer_created", b.name, {"points": total})
        await interaction.response.send_message("✅ **Your boxer is ready.**", embed=profile_embed(b.name), ephemeral=True)


class EditIdentityModal(discord.ui.Modal, title="Edit Boxer Profile"):
    def __init__(self, boxer: Boxer):
        super().__init__(timeout=300)
        self.boxer_name = boxer.name
        self.weight = discord.ui.TextInput(label="Weight (kg)", default=str(boxer.weight_kg), max_length=8)
        self.gender = discord.ui.TextInput(label="Gender", default=boxer.gender, max_length=10)
        self.trait = discord.ui.TextInput(label="Trait", default=boxer.trait or "", required=False, max_length=30)
        self.intro = discord.ui.TextInput(label="Ring intro", default=boxer.intro or "", required=False, max_length=300, style=discord.TextStyle.paragraph)
        for x in (self.weight, self.gender, self.trait, self.intro): self.add_item(x)

    async def on_submit(self, interaction: discord.Interaction):
        b = get_boxer(self.boxer_name)
        if not b:
            return await interaction.response.send_message("❌ Boxer no longer exists.", ephemeral=True)
        allowed, reason = game.can_edit_boxer(b.name)
        if not allowed:
            return await interaction.response.send_message(f"🔒 {reason}", ephemeral=True)
        try: b.weight_kg = float(self.weight.value)
        except ValueError: return await interaction.response.send_message("❌ Weight must be numeric.", ephemeral=True)
        gender = self.gender.value.strip().lower()
        trait = self.trait.value.strip()
        if gender not in {"male", "female"} or trait not in TRAITS:
            return await interaction.response.send_message("❌ Invalid gender or trait.", ephemeral=True)
        b.gender, b.trait, b.intro = gender, trait, self.intro.value.strip()
        save_boxer(b)
        v2db.audit(interaction.guild_id, interaction.user.id, "player_boxer_profile_edit", b.name)
        await interaction.response.send_message("✅ Boxer profile updated.", embed=profile_embed(b.name), ephemeral=True)


class EditStats1Modal(discord.ui.Modal, title="Reallocate Stats — 1/2"):
    def __init__(self, boxer: Boxer):
        super().__init__(timeout=300); self.boxer_name=boxer.name; self.vals={}
        self.fields={}
        for key in ("power","speed","accuracy","defense"):
            x=discord.ui.TextInput(label=key.title(), default=str(getattr(boxer,key)), max_length=2); self.fields[key]=x; self.add_item(x)
    async def on_submit(self, interaction):
        try: vals={k:int(v.value) for k,v in self.fields.items()}
        except ValueError: return await interaction.response.send_message("❌ Stats must be whole numbers.",ephemeral=True)
        b=get_boxer(self.boxer_name)
        if not b: return await interaction.response.send_message("❌ Boxer missing.",ephemeral=True)
        await interaction.response.send_message(
            "✅ First four stats saved. Continue to **Stats 2/2**.",
            view=EditStats2ContinueView(b.name, vals, interaction.user.id),
            ephemeral=True,
        )


class EditStats2ContinueView(_OwnerOnlyContinueView):
    def __init__(self, boxer_name: str, vals: dict, owner_id: int):
        super().__init__(owner_id)
        self.boxer_name = boxer_name
        self.vals = dict(vals)

    @discord.ui.button(label="Continue — Stats 2/2", emoji="📊", style=discord.ButtonStyle.primary)
    async def continue_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        boxer = get_boxer(self.boxer_name)
        if not boxer:
            return await interaction.response.send_message("❌ Boxer missing.", ephemeral=True)
        allowed, reason = game.can_edit_boxer(boxer.name)
        if not allowed:
            return await interaction.response.send_message(f"🔒 {reason}", ephemeral=True)
        await interaction.response.send_modal(EditStats2Modal(boxer, self.vals))


class EditStats2Modal(discord.ui.Modal, title="Reallocate Stats — 2/2"):
    def __init__(self, boxer: Boxer, vals: dict):
        super().__init__(timeout=300); self.boxer_name=boxer.name; self.vals=vals; self.fields={}
        for key in ("footwork","stamina","chin","body"):
            x=discord.ui.TextInput(label=key.title(), default=str(getattr(boxer,key)), max_length=2); self.fields[key]=x; self.add_item(x)
    async def on_submit(self, interaction):
        try: vals={**self.vals, **{k:int(v.value) for k,v in self.fields.items()}}
        except ValueError: return await interaction.response.send_message("❌ Stats must be whole numbers.",ephemeral=True)
        if any(v<0 or v>20 for v in vals.values()) or sum(vals.values()) != 60:
            return await interaction.response.send_message(f"❌ Each stat must be 0–20 and the total must be exactly **60** (currently {sum(vals.values())}).",ephemeral=True)
        b=get_boxer(self.boxer_name)
        if not b: return await interaction.response.send_message("❌ Boxer missing.",ephemeral=True)
        allowed,reason=game.can_edit_boxer(b.name)
        if not allowed: return await interaction.response.send_message(f"🔒 {reason}",ephemeral=True)
        for k,v in vals.items(): setattr(b,k,v)
        save_boxer(b); v2db.audit(interaction.guild_id, interaction.user.id, "player_boxer_stats_reallocated", b.name, vals)
        await interaction.response.send_message("✅ Stats reallocated. No progression bonuses were added.",embed=boxer_embed(b),ephemeral=True)


class TournamentEntryModal(discord.ui.Modal, title="Add Tournament Boxer"):
    boxer=discord.ui.TextInput(label="Boxer name",min_length=1,max_length=40)
    def __init__(self,tid:int): super().__init__(timeout=180); self.tid=tid
    async def on_submit(self,interaction):
        b=get_boxer(self.boxer.value.strip())
        if not b: return await interaction.response.send_message("❌ Boxer not found.",ephemeral=True)
        try: tournaments.register(self.tid,b.name)
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(interaction.guild_id,interaction.user.id,"tournament_entry_added",b.name,{"tournament_id":self.tid})
        await interaction.response.send_message("✅ Boxer entered.",embed=tournament_embed(tournaments.tournament(self.tid)),ephemeral=True)


class TournamentRemoveEntryModal(discord.ui.Modal, title="Remove Tournament Boxer"):
    boxer=discord.ui.TextInput(label="Boxer name",min_length=1,max_length=40)
    def __init__(self,tid:int): super().__init__(timeout=180); self.tid=tid
    async def on_submit(self,interaction):
        b=get_boxer(self.boxer.value.strip())
        if not b: return await interaction.response.send_message("❌ Boxer not found.",ephemeral=True)
        try: tournaments.unregister(self.tid,b.name)
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(interaction.guild_id,interaction.user.id,"tournament_entry_removed",b.name,{"tournament_id":self.tid})
        await interaction.response.send_message("✅ Entry removed.",ephemeral=True)


class TournamentCreateModal(discord.ui.Modal, title="Create Tournament"):
    name=discord.ui.TextInput(label="Tournament name",min_length=2,max_length=60)
    size=discord.ui.TextInput(label="Maximum entrants (2-64)",default="16",max_length=2)
    async def on_submit(self,interaction):
        if not _is_admin(interaction): return await interaction.response.send_message("Admins only.",ephemeral=True)
        try: size=int(self.size.value)
        except ValueError: return await interaction.response.send_message("Size must be a number.",ephemeral=True)
        try: tid=tournaments.create_tournament(_guild_id(interaction),self.name.value,interaction.user.id,size)
        except ValueError as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(interaction.guild_id,interaction.user.id,"tournament_created",str(tid),{"name":self.name.value})
        await interaction.response.send_message("✅ Tournament created and registration is open.",embed=tournament_embed(tournaments.tournament(tid)),ephemeral=True)


class MyBoxerView(discord.ui.View):
    def __init__(self, owner_id:int, guild_id:int): super().__init__(timeout=180); self.owner_id=owner_id; self.guild_id=guild_id
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id: await interaction.response.send_message("This menu belongs to another user.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Edit Profile",emoji="✏️",style=discord.ButtonStyle.secondary)
    async def edit_profile(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id); b=get_boxer(name) if name else None
        if not b: return await interaction.response.send_message("Create a boxer first.",ephemeral=True)
        await interaction.response.send_modal(EditIdentityModal(b))
    @discord.ui.button(label="Reallocate Stats",emoji="📊",style=discord.ButtonStyle.secondary)
    async def edit_stats(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id); b=get_boxer(name) if name else None
        if not b: return await interaction.response.send_message("Create a boxer first.",ephemeral=True)
        allowed,reason=game.can_edit_boxer(b.name)
        if not allowed: return await interaction.response.send_message(f"🔒 {reason}",ephemeral=True)
        await interaction.response.send_modal(EditStats1Modal(b))
    @discord.ui.button(label="Achievements",emoji="🏅",style=discord.ButtonStyle.primary)
    async def achievements(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not name: return await interaction.response.send_message("Create a boxer first.",ephemeral=True)
        ach=game.profile(name)["achievements"]
        e=discord.Embed(title=f"🏅 {name} — Achievements",color=discord.Color.gold())
        e.description="\n".join(f"**{a['name']}** — {a['description']}" for a in ach[:25]) or "No achievements yet. Get in the ring."
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Fight History",emoji="📜",style=discord.ButtonStyle.secondary)
    async def history(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not name: return await interaction.response.send_message("Create a boxer first.",ephemeral=True)
        rows=v2db.all_rows("SELECT * FROM fights WHERE red_name=? COLLATE NOCASE OR blue_name=? COLLATE NOCASE ORDER BY id DESC LIMIT 10",(name,name))
        e=discord.Embed(title=f"📜 {name} — Last 10 Fights",color=discord.Color.dark_gold())
        e.description="\n".join(f"#{r['id']} • {r['red_name']} vs {r['blue_name']} — **{r['winner_name'] or 'Draw'} {r['result_type']}**" for r in rows) or "No recorded fights yet."
        await interaction.response.send_message(embed=e,ephemeral=True)


class MainMenuView(discord.ui.View):
    def __init__(self, owner_id:int, guild_id:int, is_admin:bool):
        super().__init__(timeout=300); self.owner_id=owner_id; self.guild_id=guild_id; self.is_admin=is_admin
        if not is_admin:
            self.remove_item(self.admin_center)
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id: await interaction.response.send_message("Use `/menu` to open your own BoxingBot menu.",ephemeral=True); return False
        return True
    @discord.ui.button(label="My Boxer",emoji="🥊",style=discord.ButtonStyle.primary,row=0)
    async def my_boxer(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not name:
            return await interaction.response.send_message("You don't have a linked boxer yet.",view=CreateBoxerView(self.owner_id,self.guild_id),ephemeral=True)
        await interaction.response.send_message(embed=profile_embed(name),view=MyBoxerView(self.owner_id,self.guild_id),ephemeral=True)
    @discord.ui.button(label="Fight Centre",emoji="🥋",style=discord.ButtonStyle.secondary,row=0)
    async def fight_center(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        e=discord.Embed(title="🥋 Fight Centre",color=discord.Color.red())
        e.description="Career fights are permanent. **Grudge matches** count toward career records; tournament bouts also update tournament progress automatically.\n\nAdmins stage live bouts with `/start`, `/fight` and `/next_round`."
        if name: e.add_field(name="Your Boxer",value=name,inline=True)
        accepted=v2db.all_rows("SELECT * FROM challenges WHERE guild_id=? AND status='accepted' ORDER BY id",(self.guild_id,))
        e.add_field(name="Accepted Grudge Matches",value="\n".join(f"#{r['id']} {r['challenger_name']} vs {r['challenged_name']}" for r in accepted[:10]) or "None",inline=False)
        await interaction.response.send_message(embed=e,view=FightCentreView(self.owner_id,self.guild_id),ephemeral=True)
    @discord.ui.button(label="Tournaments",emoji="🏆",style=discord.ButtonStyle.secondary,row=0)
    async def tourneys(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t: return await interaction.response.send_message("🏆 No tournament is currently open or active.",ephemeral=True)
        await interaction.response.send_message(embed=tournament_embed(t),view=TournamentPlayerView(self.owner_id,self.guild_id,t["id"]),ephemeral=True)
    @discord.ui.button(label="Leaderboard",emoji="📈",style=discord.ButtonStyle.secondary,row=1)
    async def leaderboard(self,interaction,button):
        rows=game.leaderboard(20); e=discord.Embed(title="📈 BoxingBot Career Leaderboard",color=discord.Color.gold())
        e.description="\n".join(f"**{i}. {r['boxer_name']}** — {r['wins']}-{r['losses']}-{r['draws']} • 🏆 {r['tournament_titles']} • L{r['level']}" for i,r in enumerate(rows,1)) or "No recorded careers yet."
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Tournament Archive",emoji="📚",style=discord.ButtonStyle.secondary,row=1)
    async def archive(self,interaction,button):
        rows=tournaments.list_tournaments(self.guild_id,10); e=discord.Embed(title="📚 Tournament Archive",color=discord.Color.blurple())
        e.description="\n".join(f"**#{r['id']} {r['name']}** — {r['status'].title()}" + (f" • 🏆 {r['champion_name']}" if r['champion_name'] else "") for r in rows) or "No tournaments yet."
        e.set_footer(text="Use /tournament_show <id> for the full persisted tournament card.")
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Help",emoji="❓",style=discord.ButtonStyle.secondary,row=2)
    async def help(self,interaction,button):
        e=discord.Embed(title="🥊 BoxingBot V2",description="**Create → Compete → Build a Career → Win Championships**",color=discord.Color.blurple())
        e.add_field(name="Fair play",value="Every boxer uses exactly **60 base stat points**, max **20 per stat**, and **100 HP**. XP, levels, titles and achievements never increase combat power.",inline=False)
        e.add_field(name="Career",value="Every completed bout is stored permanently with result, damage, knockdowns, seed and tournament context.",inline=False)
        e.add_field(name="Tournaments",value="Join during registration. Your build locks when the tournament starts, results advance the bracket automatically.",inline=False)
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Admin Centre",emoji="🛠️",style=discord.ButtonStyle.danger,row=2)
    async def admin_center(self,interaction,button):
        if not _is_admin(interaction): return await interaction.response.send_message("Admins only.",ephemeral=True)
        await interaction.response.send_message(embed=admin_dashboard_embed(self.guild_id),view=AdminCentreView(self.owner_id,self.guild_id),ephemeral=True)


class CreateBoxerView(discord.ui.View):
    def __init__(self,owner_id,guild_id): super().__init__(timeout=180); self.owner_id=owner_id; self.guild_id=guild_id
    @discord.ui.button(label="Create My Boxer",emoji="🥊",style=discord.ButtonStyle.success)
    async def create(self,interaction,button):
        if interaction.user.id!=self.owner_id: return await interaction.response.send_message("Open your own `/menu`.",ephemeral=True)
        await interaction.response.send_modal(CreateBasicsModal())


class ChallengeSelect(discord.ui.Select):
    def __init__(self, owner_id:int, guild_id:int, own_name:str):
        options=[]
        linked=v2db.all_rows("SELECT boxer_name FROM boxer_profiles WHERE guild_id=? AND owner_id IS NOT NULL AND retired=0 ORDER BY boxer_name",(guild_id,))
        for row in linked:
            n=row["boxer_name"]; b=get_boxer(n)
            if b and b.name.lower()!=own_name.lower(): options.append(discord.SelectOption(label=b.name,value=b.name))
        super().__init__(placeholder="Choose an opponent",options=options[:25],min_values=1,max_values=1)
        self.owner_id,self.guild_id,self.own_name=owner_id,guild_id,own_name
    async def callback(self,interaction):
        opponent=self.values[0]; game.ensure_profile(opponent)
        exists=v2db.one("SELECT id FROM challenges WHERE guild_id=? AND status IN ('pending','accepted') AND ((challenger_name=? AND challenged_name=?) OR (challenger_name=? AND challenged_name=?))",(self.guild_id,self.own_name,opponent,opponent,self.own_name))
        if exists: return await interaction.response.send_message("A pending/accepted challenge already exists between these boxers.",ephemeral=True)
        cid=v2db.execute("INSERT INTO challenges(guild_id,challenger_name,challenged_name) VALUES(?,?,?)",(self.guild_id,self.own_name,opponent))
        await interaction.response.send_message(f"🥊 Challenge **#{cid}** issued: **{self.own_name} vs {opponent}**.",ephemeral=True)


class ChallengeView(discord.ui.View):
    def __init__(self,owner_id,guild_id,own_name): super().__init__(timeout=120); self.add_item(ChallengeSelect(owner_id,guild_id,own_name))


class ChallengeOpponentModal(discord.ui.Modal, title="Issue Grudge Challenge"):
    opponent=discord.ui.TextInput(label="Opponent boxer name",min_length=1,max_length=40)
    def __init__(self,owner_id:int,guild_id:int,own_name:str): super().__init__(timeout=180); self.owner_id=owner_id; self.guild_id=guild_id; self.own_name=own_name
    async def on_submit(self,interaction):
        opp=get_boxer(self.opponent.value.strip())
        if not opp: return await interaction.response.send_message("❌ Boxer not found.",ephemeral=True)
        if opp.name.lower()==self.own_name.lower(): return await interaction.response.send_message("❌ You cannot challenge yourself.",ephemeral=True)
        linked=v2db.one("SELECT owner_id FROM boxer_profiles WHERE guild_id=? AND boxer_name=? COLLATE NOCASE AND owner_id IS NOT NULL",(self.guild_id,opp.name))
        if not linked: return await interaction.response.send_message("❌ Grudge challenges can only be issued to another linked player boxer.",ephemeral=True)
        exists=v2db.one("SELECT id FROM challenges WHERE guild_id=? AND status IN ('pending','accepted') AND ((challenger_name=? COLLATE NOCASE AND challenged_name=? COLLATE NOCASE) OR (challenger_name=? COLLATE NOCASE AND challenged_name=? COLLATE NOCASE))",(self.guild_id,self.own_name,opp.name,opp.name,self.own_name))
        if exists: return await interaction.response.send_message("A pending/accepted challenge already exists between these boxers.",ephemeral=True)
        cid=v2db.execute("INSERT INTO challenges(guild_id,challenger_name,challenged_name) VALUES(?,?,?)",(self.guild_id,self.own_name,opp.name))
        await interaction.response.send_message(f"🥊 Challenge **#{cid}** issued: **{self.own_name} vs {opp.name}**.",ephemeral=True)


class AcceptChallengeModal(discord.ui.Modal, title="Accept Grudge Challenge"):
    challenge_id=discord.ui.TextInput(label="Challenge ID",placeholder="e.g. 12",max_length=8)
    def __init__(self,guild_id:int,own_name:str): super().__init__(timeout=180); self.guild_id=guild_id; self.own_name=own_name
    async def on_submit(self,interaction):
        try: cid=int(self.challenge_id.value)
        except ValueError: return await interaction.response.send_message("❌ Challenge ID must be a number.",ephemeral=True)
        row=v2db.one("SELECT * FROM challenges WHERE id=? AND guild_id=? AND challenged_name=? COLLATE NOCASE AND status='pending'",(cid,self.guild_id,self.own_name))
        if not row: return await interaction.response.send_message("❌ That pending challenge is not addressed to your boxer.",ephemeral=True)
        v2db.execute("UPDATE challenges SET status='accepted',accepted_at=CURRENT_TIMESTAMP WHERE id=?",(cid,))
        await interaction.response.send_message(f"✅ Challenge #{cid} accepted. It is now in the admin Fight Centre queue.",ephemeral=True)


class FightCentreView(discord.ui.View):
    def __init__(self,owner_id,guild_id): super().__init__(timeout=180); self.owner_id=owner_id; self.guild_id=guild_id
    @discord.ui.button(label="Issue Grudge Challenge",emoji="🔥",style=discord.ButtonStyle.danger)
    async def challenge(self,interaction,button):
        own=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not own: return await interaction.response.send_message("Create your boxer first.",ephemeral=True)
        await interaction.response.send_modal(ChallengeOpponentModal(self.owner_id,self.guild_id,own))
    @discord.ui.button(label="My Pending Challenges",emoji="📨",style=discord.ButtonStyle.secondary)
    async def pending(self,interaction,button):
        own=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not own: return await interaction.response.send_message("Create your boxer first.",ephemeral=True)
        rows=v2db.all_rows("SELECT * FROM challenges WHERE guild_id=? AND challenged_name=? COLLATE NOCASE AND status='pending' ORDER BY id",(self.guild_id,own))
        if not rows: return await interaction.response.send_message("No incoming challenges.",ephemeral=True)
        listing="\n".join(f"**#{r['id']}** from {r['challenger_name']}" for r in rows[:25])
        await interaction.response.send_message(f"📨 **Incoming challenges**\n{listing}\n\nClick below and enter the challenge ID you want to accept.",view=AcceptChallengeView(self.guild_id,own),ephemeral=True)


class AcceptChallengeView(discord.ui.View):
    def __init__(self,guild_id,own_name): super().__init__(timeout=120); self.guild_id=guild_id; self.own_name=own_name
    @discord.ui.button(label="Accept by ID",emoji="✅",style=discord.ButtonStyle.success)
    async def accept(self,interaction,button): await interaction.response.send_modal(AcceptChallengeModal(self.guild_id,self.own_name))


class IncomingChallengeSelect(discord.ui.Select):
    def __init__(self,rows):
        self.rows={str(r['id']):r for r in rows}; super().__init__(placeholder="Choose a challenge to accept",options=[discord.SelectOption(label=f"#{r['id']} vs {r['challenger_name']}",value=str(r['id'])) for r in rows[:25]])
    async def callback(self,interaction):
        cid=int(self.values[0]); v2db.execute("UPDATE challenges SET status='accepted',accepted_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(cid,)); await interaction.response.send_message(f"✅ Challenge #{cid} accepted. An admin can stage the grudge match.",ephemeral=True)
class IncomingChallengeView(discord.ui.View):
    def __init__(self,owner_id,guild_id,own,rows): super().__init__(timeout=120); self.add_item(IncomingChallengeSelect(rows))


class TournamentPlayerView(discord.ui.View):
    def __init__(self,owner_id,guild_id,tid): super().__init__(timeout=180); self.owner_id=owner_id; self.guild_id=guild_id; self.tid=tid
    @discord.ui.button(label="Join",emoji="✅",style=discord.ButtonStyle.success)
    async def join(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not name: return await interaction.response.send_message("Create your boxer first.",ephemeral=True)
        try: tournaments.register(self.tid,name)
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        await interaction.response.send_message("✅ Entered.",embed=tournament_embed(tournaments.tournament(self.tid)),ephemeral=True)
    @discord.ui.button(label="Leave Registration",emoji="↩️",style=discord.ButtonStyle.secondary)
    async def leave(self,interaction,button):
        name=game.get_owned_boxer(self.guild_id,self.owner_id)
        if not name: return await interaction.response.send_message("No linked boxer.",ephemeral=True)
        try: tournaments.unregister(self.tid,name)
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        await interaction.response.send_message("✅ Entry removed.",ephemeral=True)
    @discord.ui.button(label="Bracket / Current Round",emoji="🧾",style=discord.ButtonStyle.primary)
    async def bracket(self,interaction,button):
        ms=tournaments.current_round_matches(self.tid); e=discord.Embed(title="🧾 Current Tournament Round",color=discord.Color.blurple())
        e.description="\n".join(f"**Bout {m['slot_no']}** • {m['red_name']} vs {m['blue_name'] or 'BYE'} — {m['winner_name'] or m['status']}" for m in ms) or "Bracket not drawn yet."
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Tournament Awards",emoji="🏅",style=discord.ButtonStyle.secondary)
    async def awards(self,interaction,button):
        awards=tournaments.tournament_awards(self.tid); e=discord.Embed(title="🏅 Tournament Leaders",color=discord.Color.gold())
        e.description="\n".join(f"**{label}:** {names} ({value})" for label,names,value in awards) or "Awards populate as bouts are completed."
        await interaction.response.send_message(embed=e,ephemeral=True)


def admin_dashboard_embed(guild_id:int)->discord.Embed:
    t=tournaments.active_tournament(guild_id); e=discord.Embed(title="🛠️ BoxingBot V2 — Admin Centre",color=discord.Color.red())
    if not t: e.description="No open/active tournament. Create one below."
    else:
        e.description=f"**{t['name']}** • {t['status'].title()} • Round {t['current_round']}"
        pending=tournaments.pending_matches(t['id'])
        if pending: e.add_field(name="Next Bout",value=f"{pending[0]['red_name']} vs {pending[0]['blue_name']}",inline=False)
    accepted=v2db.all_rows("SELECT * FROM challenges WHERE guild_id=? AND status='accepted' ORDER BY id LIMIT 10",(guild_id,))
    e.add_field(name="Accepted Grudge Matches",value="\n".join(f"#{r['id']} {r['challenger_name']} vs {r['challenged_name']}" for r in accepted) or "None",inline=False)
    return e


class AdminCentreView(discord.ui.View):
    def __init__(self,owner_id,guild_id): super().__init__(timeout=300); self.owner_id=owner_id; self.guild_id=guild_id
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id or not _is_admin(interaction): await interaction.response.send_message("Admins only.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Create Tournament",emoji="🏆",style=discord.ButtonStyle.success,row=0)
    async def create_t(self,interaction,button): await interaction.response.send_modal(TournamentCreateModal())
    @discord.ui.button(label="Add Boxer",emoji="🥊",style=discord.ButtonStyle.secondary,row=0)
    async def add_boxer(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t or t['status']!='registration': return await interaction.response.send_message("Registration is not open.",ephemeral=True)
        await interaction.response.send_modal(TournamentEntryModal(t['id']))
    @discord.ui.button(label="Remove Boxer",emoji="➖",style=discord.ButtonStyle.secondary,row=1)
    async def remove_boxer(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t or t['status']!='registration': return await interaction.response.send_message("Registration is not open.",ephemeral=True)
        await interaction.response.send_modal(TournamentRemoveEntryModal(t['id']))
    @discord.ui.button(label="Start Tournament",emoji="▶️",style=discord.ButtonStyle.primary,row=0)
    async def start_t(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t or t['status']!='registration': return await interaction.response.send_message("No tournament awaiting a start.",ephemeral=True)
        try: tournaments.start(t['id'])
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(self.guild_id,interaction.user.id,"tournament_started",str(t['id']))
        await interaction.response.send_message("🥊 Tournament started.",embed=tournament_embed(tournaments.tournament(t['id'])),ephemeral=True)
    @discord.ui.button(label="Tournament Director",emoji="🎛️",style=discord.ButtonStyle.secondary,row=0)
    async def director(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t: return await interaction.response.send_message("No active/open tournament.",ephemeral=True)
        await interaction.response.send_message(embed=tournament_embed(t),ephemeral=True)
    @discord.ui.button(label="Career Leaderboard",emoji="📈",style=discord.ButtonStyle.secondary,row=1)
    async def board(self,interaction,button):
        rows=game.leaderboard(25); e=discord.Embed(title="📈 Career Leaderboard",color=discord.Color.gold()); e.description="\n".join(f"{i}. **{r['boxer_name']}** {r['wins']}-{r['losses']}-{r['draws']} • 🏆{r['tournament_titles']}" for i,r in enumerate(rows,1)) or "No results yet."; await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Audit Summary",emoji="🧾",style=discord.ButtonStyle.secondary,row=1)
    async def audit(self,interaction,button):
        rows=v2db.all_rows("SELECT * FROM audit_log WHERE guild_id=? ORDER BY id DESC LIMIT 15",(self.guild_id,)); e=discord.Embed(title="🧾 Recent Admin/Game Audit",color=discord.Color.dark_grey()); e.description="\n".join(f"#{r['id']} <@{r['actor_id']}> • **{r['action']}** • {r['target'] or '—'}" for r in rows) or "No audit events."; await interaction.response.send_message(embed=e,ephemeral=True)


class _AdminSubView(discord.ui.View):
    def __init__(self, owner_id:int, guild_id:int):
        super().__init__(timeout=300); self.owner_id=owner_id; self.guild_id=guild_id
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id or not _is_admin(interaction):
            await interaction.response.send_message("Admins only.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Admin Home",emoji="🏠",style=discord.ButtonStyle.secondary,row=4)
    async def home(self,interaction,button):
        await interaction.response.edit_message(embed=admin_dashboard_embed(self.guild_id),view=AdminCentreView(self.owner_id,self.guild_id))


class BoxerManagementView(_AdminSubView):
    @discord.ui.button(label="Roster Overview",emoji="📋",style=discord.ButtonStyle.primary,row=0)
    async def roster(self,interaction,button):
        rows=v2db.all_rows("SELECT boxer_name,owner_id FROM boxer_profiles WHERE retired=0 ORDER BY boxer_name")
        linked=[r for r in rows if r['owner_id'] is not None]; offline=[r for r in rows if r['owner_id'] is None]
        e=discord.Embed(title="🥊 Boxer Management",color=discord.Color.red())
        e.add_field(name=f"Linked Players ({len(linked)})",value="\n".join(f"**{r['boxer_name']}** → <@{r['owner_id']}>" for r in linked[:20]) or "None",inline=False)
        e.add_field(name=f"Offline/Admin Boxers ({len(offline)})",value=", ".join(r['boxer_name'] for r in offline[:30]) or "None",inline=False)
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Competition Audit",emoji="⚖️",style=discord.ButtonStyle.secondary,row=0)
    async def audit_builds(self,interaction,button):
        bad=[]
        for n in list_boxers():
            ok,reason=game.competitive_legal(n)
            if not ok: bad.append(f"**{n}** — {reason}")
        e=discord.Embed(title="⚖️ Competition Build Audit",color=discord.Color.green() if not bad else discord.Color.orange())
        e.description="✅ Every saved boxer is V2 competition-legal." if not bad else "\n".join(bad[:25])
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Ownership Tools",emoji="🔗",style=discord.ButtonStyle.secondary,row=1)
    async def ownership(self,interaction,button):
        await interaction.response.send_message("Use **`/v2_link_boxer boxer user`** to link/relink an existing offline boxer. Player-created boxers link automatically. Admin/offline boxer creation remains available through `/boxer_create_wizard`.",ephemeral=True)


class TournamentControlView(_AdminSubView):
    @discord.ui.button(label="Create Tournament",emoji="➕",style=discord.ButtonStyle.success,row=0)
    async def create_t(self,interaction,button): await interaction.response.send_modal(TournamentCreateModal())
    @discord.ui.button(label="Start Tournament",emoji="▶️",style=discord.ButtonStyle.primary,row=0)
    async def start_t(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t or t['status']!='registration': return await interaction.response.send_message("No tournament is waiting to start.",ephemeral=True)
        try: tournaments.start(t['id'])
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(self.guild_id,interaction.user.id,"tournament_started",str(t['id']))
        await interaction.response.send_message("🥊 Tournament started.",embed=tournament_embed(tournaments.tournament(t['id'])),ephemeral=True)
    @discord.ui.button(label="Director Dashboard",emoji="🎛️",style=discord.ButtonStyle.secondary,row=0)
    async def director(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t: return await interaction.response.send_message("No open/active tournament.",ephemeral=True)
        await interaction.response.send_message(embed=tournament_embed(t),ephemeral=True)
    @discord.ui.button(label="Tournament Archive",emoji="📚",style=discord.ButtonStyle.secondary,row=1)
    async def archive(self,interaction,button):
        rows=tournaments.list_tournaments(self.guild_id,20); e=discord.Embed(title="📚 Tournament Archive",color=discord.Color.blurple())
        e.description="\n".join(f"**#{r['id']} {r['name']}** — {r['status'].title()}"+(f" • 🏆 {r['champion_name']}" if r['champion_name'] else "") for r in rows) or "No tournaments."
        await interaction.response.send_message(embed=e,ephemeral=True)


class MatchControlView(_AdminSubView):
    @discord.ui.button(label="Live Fight Status",emoji="🥊",style=discord.ButtonStyle.primary,row=0)
    async def live(self,interaction,button):
        try:
            from .match import SESSIONS
            s=SESSIONS.get(interaction.channel_id)
        except Exception: s=None
        if not s: return await interaction.response.send_message("No active fight in this channel. Stage one with `/start`.",ephemeral=True)
        e=discord.Embed(title="🥊 Live Fight",description=f"🔴 **{s.A.boxer.name}** vs 🔵 **{s.B.boxer.name}**",color=discord.Color.red())
        e.add_field(name="Round",value=str(s.current_round),inline=True); e.add_field(name="HP",value=f"{s.A.hp} / {s.B.hp}",inline=True); e.add_field(name="Seed",value=str(s.rng_seed),inline=True)
        e.add_field(name="Recovery",value="Fight state is persisted after meaningful transitions and restores on bot restart.",inline=False)
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Accepted Grudges",emoji="🔥",style=discord.ButtonStyle.secondary,row=0)
    async def grudges(self,interaction,button):
        rows=v2db.all_rows("SELECT * FROM challenges WHERE guild_id=? AND status='accepted' ORDER BY id",(self.guild_id,)); e=discord.Embed(title="🔥 Accepted Grudge Matches",color=discord.Color.orange())
        e.description="\n".join(f"**#{r['id']}** {r['challenger_name']} vs {r['challenged_name']}" for r in rows[:25]) or "None awaiting a fight."
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Fight Controls",emoji="🎮",style=discord.ButtonStyle.secondary,row=1)
    async def controls(self,interaction,button):
        await interaction.response.send_message("**Live controls**\n`/start` — stage fighters + entrances\n`/fight` — Round 1\n`/next_round` — advance\n`/resolve_test` — emergency/admin resolve\n\nV2 career/tournament recording happens automatically when the fight finishes.",ephemeral=True)


class RecordsAwardsView(_AdminSubView):
    @discord.ui.button(label="Career Leaders",emoji="📈",style=discord.ButtonStyle.primary,row=0)
    async def leaders(self,interaction,button):
        rows=game.leaderboard(25); e=discord.Embed(title="📈 Career Leaders",color=discord.Color.gold())
        e.description="\n".join(f"{i}. **{r['boxer_name']}** — {r['wins']}-{r['losses']}-{r['draws']} • 🏆 {r['tournament_titles']} • L{r['level']}" for i,r in enumerate(rows,1)) or "No results."
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Current Tournament Awards",emoji="🏅",style=discord.ButtonStyle.secondary,row=0)
    async def awards(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id)
        if not t:
            rows=tournaments.list_tournaments(self.guild_id,1); t=rows[0] if rows else None
        if not t: return await interaction.response.send_message("No tournament data yet.",ephemeral=True)
        awards=tournaments.tournament_awards(t['id']); e=discord.Embed(title=f"🏅 {t['name']} — Leaders",color=discord.Color.gold())
        e.description="\n".join(f"**{label}:** {names} ({value})" for label,names,value in awards) or "No bout data yet."
        await interaction.response.send_message(embed=e,ephemeral=True)


class SettingsView(_AdminSubView):
    @discord.ui.button(label="Diagnostics",emoji="🩺",style=discord.ButtonStyle.primary,row=0)
    async def diagnostics(self,interaction,button):
        import sqlite3
        con=v2db.connect(); integrity=con.execute("PRAGMA integrity_check").fetchone()[0]; con.close()
        profiles=v2db.one("SELECT COUNT(*) n FROM boxer_profiles")['n']; fights=v2db.one("SELECT COUNT(*) n FROM fights")['n']; tours=v2db.one("SELECT COUNT(*) n FROM tournaments")['n']
        e=discord.Embed(title="🩺 BoxingBot V2 Diagnostics",color=discord.Color.green() if integrity=='ok' else discord.Color.red())
        e.add_field(name="SQLite",value=integrity,inline=True); e.add_field(name="Profiles",value=str(profiles),inline=True); e.add_field(name="Recorded Fights",value=str(fights),inline=True); e.add_field(name="Tournaments",value=str(tours),inline=True)
        e.set_footer(text="Schema v2.0 • WAL mode • foreign keys • transactional writes")
        await interaction.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="Backup Database Now",emoji="💾",style=discord.ButtonStyle.secondary,row=0)
    async def backup(self,interaction,button):
        path=v2db.backup_database(); await interaction.response.send_message(f"✅ Backup created: `{path.name if path else 'no database yet'}`",ephemeral=True)
    @discord.ui.button(label="Audit Log",emoji="🧾",style=discord.ButtonStyle.secondary,row=1)
    async def audit(self,interaction,button):
        rows=v2db.all_rows("SELECT * FROM audit_log WHERE guild_id=? ORDER BY id DESC LIMIT 20",(self.guild_id,)); e=discord.Embed(title="🧾 Audit Log",color=discord.Color.dark_grey())
        e.description="\n".join(f"#{r['id']} <@{r['actor_id']}> • **{r['action']}** • {r['target'] or '—'}" for r in rows) or "No audit events."
        await interaction.response.send_message(embed=e,ephemeral=True)


# V2 hierarchy replaces the earlier flat compatibility view above.
class AdminCentreView(discord.ui.View):
    def __init__(self,owner_id,guild_id): super().__init__(timeout=300); self.owner_id=owner_id; self.guild_id=guild_id
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id or not _is_admin(interaction): await interaction.response.send_message("Admins only.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Boxer Management",emoji="🥊",style=discord.ButtonStyle.primary,row=0)
    async def boxers(self,interaction,button):
        e=discord.Embed(title="🥊 Boxer Management",description="Player ownership, offline/admin boxers and competition-build validation.",color=discord.Color.red()); await interaction.response.edit_message(embed=e,view=BoxerManagementView(self.owner_id,self.guild_id))
    @discord.ui.button(label="Tournament Control",emoji="🏆",style=discord.ButtonStyle.primary,row=0)
    async def tourneys(self,interaction,button):
        t=tournaments.active_tournament(self.guild_id); e=tournament_embed(t) if t else discord.Embed(title="🏆 Tournament Control",description="No tournament is currently open.",color=discord.Color.blurple()); await interaction.response.edit_message(embed=e,view=TournamentControlView(self.owner_id,self.guild_id))
    @discord.ui.button(label="Match Control",emoji="🎮",style=discord.ButtonStyle.primary,row=1)
    async def matches(self,interaction,button):
        e=discord.Embed(title="🎮 Match Control",description="Stage grudge matches or tournament bouts and monitor persisted fight state.",color=discord.Color.orange()); await interaction.response.edit_message(embed=e,view=MatchControlView(self.owner_id,self.guild_id))
    @discord.ui.button(label="Records & Awards",emoji="🏅",style=discord.ButtonStyle.secondary,row=1)
    async def records(self,interaction,button):
        e=discord.Embed(title="🏅 Records & Awards",description="Career leaderboards, tournament leaders and permanent records.",color=discord.Color.gold()); await interaction.response.edit_message(embed=e,view=RecordsAwardsView(self.owner_id,self.guild_id))
    @discord.ui.button(label="Bot Settings",emoji="⚙️",style=discord.ButtonStyle.secondary,row=2)
    async def settings(self,interaction,button):
        e=discord.Embed(title="⚙️ Bot Settings & Integrity",description="Database diagnostics, backups and audit history.",color=discord.Color.dark_grey()); await interaction.response.edit_message(embed=e,view=SettingsView(self.owner_id,self.guild_id))


class GameMenu(commands.Cog):
    def __init__(self,bot): self.bot=bot

    @app_commands.command(name="menu",description="Open the BoxingBot V2 game menu.")
    async def menu(self,interaction:discord.Interaction):
        guild_id=_guild_id(interaction); name=game.get_owned_boxer(guild_id,interaction.user.id)
        e=discord.Embed(title="🥊 BOXINGBOT V2",description="**Your boxing career lives here.**\nCreate a fighter, build a record, earn achievements, settle grudges and chase tournament championships.",color=discord.Color.red())
        e.add_field(name="Your Boxer",value=name or "Not created yet",inline=True)
        t=tournaments.active_tournament(guild_id); e.add_field(name="Tournament",value=t['name'] if t else "None active",inline=True)
        e.set_footer(text="Fair competition • Persistent careers • Tournament Director")
        await interaction.response.send_message(embed=e,view=MainMenuView(interaction.user.id,guild_id,_is_admin(interaction)),ephemeral=True)

    @app_commands.command(name="career",description="View a persistent boxer career profile.")
    async def career(self,interaction:discord.Interaction,boxer:Optional[str]=None):
        name=boxer or game.get_owned_boxer(_guild_id(interaction),interaction.user.id)
        if not name or not get_boxer(name): return await interaction.response.send_message("Boxer not found.",ephemeral=True)
        await interaction.response.send_message(embed=profile_embed(name))

    @app_commands.command(name="v2_link_boxer",description="Admin: link an existing boxer to a Discord user.")
    @app_commands.checks.has_permissions(administrator=True)
    async def link_boxer(self,interaction:discord.Interaction,boxer:str,user:discord.Member):
        if not get_boxer(boxer): return await interaction.response.send_message("Boxer not found.",ephemeral=True)
        try: game.link_boxer(get_boxer(boxer).name,_guild_id(interaction),user.id,force=True)
        except Exception as e: return await interaction.response.send_message(f"❌ {e}",ephemeral=True)
        v2db.audit(interaction.guild_id,interaction.user.id,"admin_boxer_link",boxer,{"user_id":user.id}); await interaction.response.send_message(f"✅ **{boxer}** linked to {user.mention}.",ephemeral=True)

    @app_commands.command(name="tournament_show",description="View a persisted tournament and its stats.")
    async def tournament_show(self,interaction:discord.Interaction,tournament_id:int):
        t=tournaments.tournament(tournament_id)
        if not t or (interaction.guild_id and t["guild_id"]!=interaction.guild_id): return await interaction.response.send_message("Tournament not found.",ephemeral=True)
        e=tournament_embed(t); awards=tournaments.tournament_awards(tournament_id)
        if awards: e.add_field(name="Awards / Leaders",value="\n".join(f"{label}: **{names}** ({value})" for label,names,value in awards),inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="fight_preview",description="Compare two boxers before a bout.")
    async def fight_preview(self,interaction:discord.Interaction,red:str,blue:str):
        a=get_boxer(red); b=get_boxer(blue)
        if not a or not b: return await interaction.response.send_message("Both boxers must exist.",ephemeral=True)
        h=game.head_to_head(a.name,b.name); pa=game.profile(a.name)["stats"]; pb=game.profile(b.name)["stats"]
        e=discord.Embed(title=f"🥊 {a.name} vs {b.name}",description="Pre-fight career card",color=discord.Color.red())
        e.add_field(name=a.name,value=f"{pa['wins']}-{pa['losses']}-{pa['draws']} • KO/TKO {pa['kos']+pa['tkos']}\n{a.weight_class.title()} • {a.trait or 'No trait'}",inline=True)
        e.add_field(name=b.name,value=f"{pb['wins']}-{pb['losses']}-{pb['draws']} • KO/TKO {pb['kos']+pb['tkos']}\n{b.weight_class.title()} • {b.trait or 'No trait'}",inline=True)
        e.add_field(name="Head-to-Head",value=f"{a.name} {h['a_wins']} • Draws {h['draws']} • {b.name} {h['b_wins']}",inline=False)
        if h['last']: e.add_field(name="Last Meeting",value=f"Winner: **{h['last']['winner_name'] or 'Draw'}** • {h['last']['result_type']}",inline=False)
        await interaction.response.send_message(embed=e)

async def setup(bot:commands.Bot):
    await bot.add_cog(GameMenu(bot))
