import asyncio
from .state import save_sessions
async def autosave(loop_state_callable=None, interval=30):
    while True:
        await asyncio.sleep(interval); save_sessions()
