import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or "PUT_YOUR_TOKEN_HERE"

intents = discord.Intents.default()
intents.message_content = True  # needed for prefix/hybrid commands
bot = commands.Bot(command_prefix="!", intents=intents)

INITIAL_EXTENSIONS = [
    "boxing_bot.cogs.roster",
    "boxing_bot.cogs.match",
    "boxing_bot.cogs.admin",
    "boxing_bot.cogs.imports",
]

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} app commands.")
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print("Slash sync error:", e)

async def main():
    async with bot:
        for ext in INITIAL_EXTENSIONS:
            await bot.load_extension(ext)
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
