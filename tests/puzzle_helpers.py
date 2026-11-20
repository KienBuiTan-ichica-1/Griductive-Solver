"""Tiny-puzzle builders for tests (reused by the API tests later).

Naming trick: characters are N01..N{n} in ROW-MAJOR order, so on a 3x3 grid
A1=N01, B1=N02, C1=N03, A2=N04, B2=N05, ... and the CNF variable of N0k is k.
"""
from __future__ import annotations

import random
from itertools import product

from griductive import Puzzle

COLS = "ABCDEFG"


def name_of(index: int) -> str:
    """1-based row-major index -> character name."""
    return f"N{index:02d}"


def puzzle_dict(clues, size=3, initial=(), solution=None, pid="T") -> dict:
    """Raw puzzle dict. `clues` are specs without id/owner; owners are assigned from
    the LAST cell backwards (N09, N08, ...) unless the spec gives its own."""
    n = size * size
    characters = []
    for i in range(n):
        row, col = divmod(i, size)
        characters.append({"cell": f"{COLS[col]}{row + 1}", "name": name_of(i + 1), "job": "Tester"})
    built = []
    for i, spec in enumerate(clues):
        clue = dict(spec)
        clue.setdefault("id", f"c{i + 1}")
        clue.setdefault("owner", name_of(n - i))
        built.append(clue)
    if solution is None:
        solution = {name_of(i + 1): "INNOCENT" for i in range(n)}
    return {
        "id": pid, "name": f"Test {pid}", "group": "test", "size": size, "desc": "",
        "characters": characters, "clues": built,
        "solution": solution, "initial_revealed": list(initial),
    }


def make_puzzle(clues, size=3, initial=(), solution=None, pid="T") -> Puzzle:
    return Puzzle.from_dict(puzzle_dict(clues, size, initial, solution, pid))


def assign(puzzle: Puzzle, criminals) -> dict[str, bool]:
    """Complete assignment: exactly the listed names are criminals."""
    criminals = set(criminals)
    return {name: name in criminals for name in puzzle.names}


def all_assignments(puzzle: Puzzle):
    """All 2^n complete assignments, name -> bool."""
    names = puzzle.names
    for bits in product((False, True), repeat=len(names)):
        yield dict(zip(names, bits))


def random_assignment(rng: random.Random, puzzle: Puzzle) -> dict[str, bool]:
    density = rng.choice((0.2, 0.5, 0.8))
    return {name: rng.random() < density for name in puzzle.names}