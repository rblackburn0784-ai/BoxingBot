import os
import shutil
import subprocess
from discord.ext import commands
from ..config import SETTINGS
from ..storage.db import DB, save_db


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(description="Show simple DB info.")
    async def db_info(self, ctx: commands.Context):
        path = SETTINGS.DB_FILE
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        count = len(DB.get("boxers", {}))
        await ctx.reply(
            f"**DB path:** `{path}`\n"
            f"**Exists:** {exists}\n"
            f"**Size:** {size} bytes\n"
            f"**Boxers loaded:** {count}\n"
            f"**Names:** {', '.join(sorted(DB.get('boxers', {}).keys())) or '—'}"
        )

    @commands.hybrid_command(description="Save the DB to disk now.")
    @commands.has_permissions(administrator=True)
    async def save(self, ctx: commands.Context):
        save_db(DB)
        await ctx.reply("✅ Saved.")

    @commands.hybrid_command(description="Check if ffmpeg is available.")
    async def check_ffmpeg(self, ctx: commands.Context):
        path = shutil.which("ffmpeg") or SETTINGS.FFMPEG_PATH
        if path and os.path.exists(path):
            try:
                out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=3)
                ver = out.stdout.splitlines()[0] if out.stdout else "ffmpeg found"
                msg = f"✅ {ver}\nPath: `{path}`"
            except Exception:
                msg = f"✅ ffmpeg found at `{path}` (version check failed)"
        else:
            msg = "❌ FFmpeg not found. Install it and set FFMPEG_PATH or add to PATH."
        await ctx.reply(msg)


async def setup(bot):
    await bot.add_cog(Admin(bot))