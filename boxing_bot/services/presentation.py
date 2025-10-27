from ..config import MOMENTUM_MAX

def momentum_bar(mom: int, width: int = 20) -> str:
    """
    mom ∈ [-MOMENTUM_MAX, +MOMENTUM_MAX]
    returns: "[██████      |      ████]"
    Left side is Red; right side is Blue.
    """
    total_slots = width
    # map momentum to [0..total_slots]
    red_slots = int(round((mom + MOMENTUM_MAX) * total_slots / (2 * MOMENTUM_MAX)))
    red_slots = max(0, min(total_slots, red_slots))
    blue_slots = total_slots - red_slots
    red_bar = "█" * red_slots + " " * (total_slots - red_slots)
    blue_bar = " " * (total_slots - blue_slots) + "█" * blue_slots
    return f"[{red_bar} | {blue_bar}]"
