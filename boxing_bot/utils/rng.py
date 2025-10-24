"""Utilities for deterministic random number generation."""

from __future__ import annotations

import random
from typing import Sequence, Tuple, TypeVar

T = TypeVar("T")


def seeded(seed: int) -> random.Random:
    """Return a :class:`random.Random` instance seeded with ``seed``."""

    return random.Random(seed)


def weighted_choice(rng: random.Random, items: Sequence[Tuple[T, float]]) -> T:
    """Choose an item based on weights using ``rng``.

    Args:
        rng: The :class:`random.Random` instance used for deterministic sampling.
        items: A sequence of ``(value, weight)`` tuples.

    Returns:
        The selected value according to the provided weights.
    """

    total = sum(weight for _, weight in items)
    pick = rng.uniform(0, total)
    cumulative = 0.0

    for value, weight in items:
        cumulative += weight
        if pick <= cumulative:
            return value

    # Fallback in case of floating point rounding errors: return last value.
    return items[-1][0]