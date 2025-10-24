"""Utilities for presenting BoxingBot momentum values."""

from __future__ import annotations

from ..config import MOMENTUM_MAX


def _clamp(value: int, minimum: int, maximum: int) -> int:
    """Return *value* constrained to the inclusive range ``[minimum, maximum]``."""

    if minimum > maximum:
        raise ValueError("minimum cannot be greater than maximum")
    return max(minimum, min(maximum, value))


def momentum_bar(mom: int, width: int = 20) -> str:
    """Return a textual bar that visualises the current momentum.

    The bar is split into a *red* left half and a *blue* right half separated by a
    vertical divider. The amount of filled blocks for each side is derived from the
    ``mom`` value which is clamped to ``[-MOMENTUM_MAX, MOMENTUM_MAX]`` before being
    scaled to the requested ``width``.

    Parameters
    ----------
    mom:
        The momentum value to display. Positive values favour the red corner while
        negative ones favour the blue corner.
    width:
        The number of character slots available for each side of the bar. The total
        width of the returned string is therefore ``2 * width + 5`` (the brackets,
        the divider, and a space on either side of the divider).

    Returns
    -------
    str
        A string representation of the momentum bar, e.g. ``"[██████      |      ████]"``.
    """

    if width <= 0:
        raise ValueError("width must be a positive integer")

    if MOMENTUM_MAX <= 0:
        raise ValueError("MOMENTUM_MAX must be a positive integer")

    mom = _clamp(mom, -MOMENTUM_MAX, MOMENTUM_MAX)

    total_slots = width
    scaled = (mom + MOMENTUM_MAX) * total_slots / (2 * MOMENTUM_MAX)
    red_slots = int(round(scaled))
    red_slots = _clamp(red_slots, 0, total_slots)
    blue_slots = total_slots - red_slots

    red_bar = "█" * red_slots + " " * (total_slots - red_slots)
    blue_bar = " " * (total_slots - blue_slots) + "█" * blue_slots

    return f"[{red_bar} | {blue_bar}]"


__all__ = ["momentum_bar"]