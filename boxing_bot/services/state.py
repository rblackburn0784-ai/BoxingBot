# boxing_bot/services/state.py
from typing import Dict, TYPE_CHECKING

# Avoid circular imports by only importing FightSession for type checking
if TYPE_CHECKING:
    from ..models import FightSession

# Channel ID -> FightSession
SESSIONS: Dict[int, 'FightSession'] = {}

def debug_sessions():
    return {k: str(v) for k, v in SESSIONS.items()}