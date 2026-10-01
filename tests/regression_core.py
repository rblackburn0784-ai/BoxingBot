"""Lightweight regression checks for reconstructed Boxing Bot core rules.

The pure combat functions are extracted from combat.py so these checks can run
before discord.py and voice dependencies are installed.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path
from types import SimpleNamespace
from typing import List

ROOT = Path(__file__).resolve().parents[1]
COMBAT = ROOT / "boxing_bot" / "services" / "combat.py"
FUNCTIONS = {"round_damage", "tko_stoppage", "_round_stats", "_score_round", "compute_scorecards"}

module = ast.parse(COMBAT.read_text(encoding="utf-8"))
selected = []
for node in module.body:
    if isinstance(node, ast.Assign):
        if any(isinstance(t, ast.Name) and t.id == "JUDGES" for t in node.targets):
            selected.append(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
        selected.append(node)

ns = {"List": List, "random": random}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(COMBAT), "exec"), ns)

round_damage = ns["round_damage"]
tko_stoppage = ns["tko_stoppage"]
_round_stats = ns["_round_stats"]
_score_round = ns["_score_round"]
compute_scorecards = ns["compute_scorecards"]


def test_scoring_direction() -> None:
    events = [
        {"outcome": "hit", "attacker": "Red", "defender": "Blue", "damage": 12, "knockdown": False},
        {"outcome": "hit", "attacker": "Red", "defender": "Blue", "damage": 8, "knockdown": True},
        {"outcome": "hit", "attacker": "Blue", "defender": "Red", "damage": 7, "knockdown": False},
    ]
    assert _round_stats(events, "Red", "Blue") == (20, 7, 1, 0)
    assert round_damage(events, "Red") == 7
    assert round_damage(events, "Blue") == 20


def test_ten_point_must_and_kd() -> None:
    a, b, _ = _score_round(20, 7, 1, 0, 0.0, random.Random(1))
    assert (a, b) == (10, 8), (a, b)
    a, b, _ = _score_round(5, 20, 0, 2, 0.0, random.Random(1))
    assert (a, b) == (7, 10), (a, b)
    a, b, _ = _score_round(20, 5, 0, 0, 0.0, random.Random(1))
    assert (a, b) == (10, 8), (a, b)


def test_round_specific_foul_deduction() -> None:
    boxer_a = SimpleNamespace(name="Red")
    boxer_b = SimpleNamespace(name="Blue")
    session = SimpleNamespace(
        rng_seed=4,
        rng=random.Random(4),
        A=SimpleNamespace(boxer=boxer_a, warnings=3),
        B=SimpleNamespace(boxer=boxer_b, warnings=0),
        log=[
            {"events": [
                {"outcome": "hit", "attacker": "Red", "defender": "Blue", "damage": 12, "knockdown": False},
                {"outcome": "low_blow", "attacker": "Red", "defender": "Blue", "damage": 0, "point_deduction": True},
            ]},
            {"events": [
                {"outcome": "hit", "attacker": "Red", "defender": "Blue", "damage": 12, "knockdown": False},
            ]},
        ],
    )
    cards = compute_scorecards(session)
    for card in cards:
        r1a, r1b, _ = card["rounds"][0]
        r2a, r2b, _ = card["rounds"][1]
        # Same dominant round twice; only the round carrying point_deduction
        # should reduce Red's score by one.
        assert r1a == r2a - 1, (card["judge"], card["rounds"])
        assert r1b == r2b, (card["judge"], card["rounds"])



def test_knockdown_influences_round_even_if_damage_trails() -> None:
    # Red trails raw damage 12-18 but scores a KD; the KD must be part of
    # deciding the round rather than ignored because damage alone favoured Blue.
    a, b, _ = _score_round(12, 18, 1, 0, 0.0, random.Random(2))
    assert (a, b) == (10, 8), (a, b)

def test_scorecards_are_immutable() -> None:
    boxer_a = SimpleNamespace(name="Red")
    boxer_b = SimpleNamespace(name="Blue")
    session = SimpleNamespace(
        rng_seed=99, rng=random.Random(99), A=SimpleNamespace(boxer=boxer_a), B=SimpleNamespace(boxer=boxer_b),
        log=[{"events":[{"outcome":"hit","attacker":"Red","defender":"Blue","damage":9,"knockdown":False}]}],
    )
    first = compute_scorecards(session)
    # Mutating the fight RNG after the decision must not alter the official cards.
    for _ in range(50): session.rng.random()
    second = compute_scorecards(session)
    assert first == second
    assert first is second

def test_tko_rule() -> None:
    assert tko_stoppage(10, 20)
    assert tko_stoppage(5, 0)
    assert not tko_stoppage(11, 30)
    assert not tko_stoppage(10, 19)


if __name__ == "__main__":
    tests = [
        test_scoring_direction,
        test_ten_point_must_and_kd,
        test_round_specific_foul_deduction,
        test_knockdown_influences_round_even_if_damage_trails,
        test_scorecards_are_immutable,
        test_tko_rule,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} core regression checks passed")
