import asyncio
from boxing_bot.storage import db
from boxing_bot.config import SETTINGS

async def autosave(loop_state_callable, interval=30):
    while True:
        await asyncio.sleep(interval)
        data = loop_state_callable()
        db.write(SETTINGS.DB_FILE, data)