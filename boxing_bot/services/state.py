"""Session state management for BoxingBot."""
from typing import Dict, TYPE_CHECKING

# Avoid circular imports by only importing FightSession for type checking
if TYPE_CHECKING:  # pragma: no cover - import guard
    from ..models import FightSession

# Channel ID -> FightSession
SESSIONS: Dict[int, "FightSession"] = {}


def debug_sessions() -> Dict[int, str]:
    """Return a debug-friendly mapping of session IDs to their string form."""
    return {channel_id: str(session) for channel_id, session in SESSIONS.items()}