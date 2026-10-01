import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # needed for prefix/hybrid commands
bot = commands.Bot(command_prefix="!", intents=intents)
_synced_once = False

INITIAL_EXTENSIONS = [
    "boxing_bot.cogs.roster",
    "boxing_bot.cogs.match",
    "boxing_bot.cogs.admin",
    "boxing_bot.cogs.imports",
    "boxing_bot.cogs.game_menu",
]

@bot.event
async def on_ready():
    global _synced_once
    try:
        if _synced_once:
            print(f"Reconnected as {bot.user}.")
            return
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} app commands.")
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        _synced_once = True
    except Exception as e:
        print("Slash sync error:", e)

async def main():
    from boxing_bot.storage.v2db import init_db, backup_database
    from boxing_bot.services.game import import_legacy_profiles
    init_db()
    backup = backup_database()
    if backup:
        print(f"V2 database backup: {backup.name}")
    migrated = import_legacy_profiles()
    print(f"BoxingBot V2 database ready; imported {migrated} legacy boxer profile(s).")
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not configured. Copy .env.example to .env and set a valid token.")
    from boxing_bot.services.state import load_sessions
    restored = load_sessions()
    print(f"Restored {restored} persisted fight session(s).")
    async with bot:
        for ext in INITIAL_EXTENSIONS:
            await bot.load_extension(ext)
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
