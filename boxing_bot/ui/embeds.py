"""Domain models for BoxingBot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

STAT_NAMES: tuple[str, ...] = (
    "power",
    "speed",
    "accuracy",
    "defense",
    "footwork",
    "stamina",
    "chin",
    "body",
)


def gender_badge(gender: str) -> str:
    """Return an emoji badge for a gender string."""
    normalized = (gender or "").strip().lower()
    if normalized == "male":
        return "♂️"
    if normalized == "female":
        return "♀️"
    return "⚪"


@dataclass(slots=True)
class Boxer:
    """A simple representation of a boxer profile."""

    name: str
    gender: str
    weight_kg: float
    weight_class: str
    trait: Optional[str] = None
    intro_music: Optional[str] = None
    intro: Optional[str] = None

    power: int = 0
    speed: int = 0
    accuracy: int = 0
    defense: int = 0
    footwork: int = 0
    stamina: int = 0
    chin: int = 0
    body: int = 0

    _hp_bonus: int = field(default=0, repr=False)

    def base_stats(self) -> Dict[str, int]:
        """Return a dictionary of the boxer's raw stats."""
        return {name: getattr(self, name) for name in STAT_NAMES}

    def total_points(self) -> int:
        """Total of the raw stat points."""
        return sum(self.base_stats().values())

    def max_hp(self) -> int:
        """Compute a simple hit point value for display purposes."""
        stamina_component = max(0, self.stamina)
        return 50 + stamina_component + self._hp_bonus

    def as_stat_iter(self) -> Iterable[tuple[str, int]]:
        """Iterate over stat name/value pairs."""
        for name in STAT_NAMES:
            yield name, getattr(self, name)