"""Generate solvable Griductive puzzles with a provable no-guess reveal chain."""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from griductive.agent import LogicAgent
from griductive.engine import GameEngine
from griductive.model import (
    Character,
    PublicView,
    Puzzle,
    _region_names,
    bool_to_status,
    format_cell,
    parse_cell,
)

NAMES = [
    "Abel", "Bea", "Clara", "Derek", "Eliza", "Franz", "Grant", "Hannah", "Ivy",
    "Jonas", "Karl", "Leo", "Mara", "Noah", "Owen", "Priya", "Quilla", "Roy",
    "Sophia", "Tom", "Uma", "Victor", "Wendy", "Xavier", "Yara", "Zane",
]
JOBS = [
    "Baker", "Chef", "Doctor", "Pilot", "Teacher", "Engineer", "Artist", "Clerk",
    "Farmer", "Guard", "Judge", "Librarian", "Mechanic", "Nurse", "Officer",
    "Painter", "Quarryman", "Ranger", "Sailor", "Tailor", "Usher", "Vet",
    "Writer", "Xenobiologist", "Yoga trainer", "Zoologist",
]


def make_view(size: int, chars: list[Character]) -> PublicView:
    names = [c.name for c in chars]
    return PublicView(
        size,
        names,
        {c.name: c.cell for c in chars},
        {c.cell: c.name for c in chars},
        {c.name: c.job for c in chars},
    )


def random_region(rng: random.Random, size: int, chars: list[Character]) -> dict[str, Any]:
    cells = [c.cell for c in chars]
    kinds = ["row", "col", "neighbors", "cells", "boundary", "corners", "intersection", "common_neighbors", "between"]
    weights = [4, 4, 4, 3, 1, 1, 1, 1, 1]
    kind = rng.choices(kinds, weights)[0]
    if kind == "row":
        return {"kind": "row", "row": rng.randint(1, size)}
    if kind == "col":
        return {"kind": "col", "col": format_cell(1, rng.randrange(size))[0]}
    if kind == "neighbors":
        return {"kind": "neighbors", "cell": rng.choice(cells)}
    if kind == "cells":
        count = rng.randint(2, min(4, size * size))
        picked = rng.sample(cells, count)
        return {"kind": "cells", "cells": picked}
    if kind in ("boundary", "corners"):
        return {"kind": kind}
    if kind == "intersection":
        return {"kind": "intersection", "regions": [
            {"kind": "row", "row": rng.randint(1, size)},
            {"kind": "neighbors", "cell": rng.choice(cells)},
        ]}
    if kind == "common_neighbors":
        a, b = rng.sample(cells, 2)
        return {"kind": "common_neighbors", "a": a, "b": b}
    a, b = rng.sample(cells, 2)
    return {"kind": "between", "a": a, "b": b}


def make_clue(
    rng: random.Random,
    owner: str,
    view: PublicView,
    solution: dict[str, bool],
    clue_id: str,
) -> dict[str, Any] | None:
    names = view.names
    kinds = ["FACT", "SAME", "DIFFERENT", "EXACTLY", "AT_LEAST", "AT_MOST", "PARITY", "COMPARE"]
    weights = [2, 2, 2, 6, 3, 3, 3, 4]
    kind = rng.choices(kinds, weights)[0]
    base = {"id": clue_id, "owner": owner, "type": kind}

    if kind == "FACT":
        return {**base, "person": owner, "status": bool_to_status(solution[owner])}
    if kind == "SAME":
        group = [n for n in names if solution[n] == solution[owner] and n != owner]
        if not group:
            return None
        return {**base, "a": owner, "b": rng.choice(group)}
    if kind == "DIFFERENT":
        group = [n for n in names if solution[n] != solution[owner]]
        if not group:
            return None
        return {**base, "a": owner, "b": rng.choice(group)}

    def count(region: dict[str, Any]) -> int:
        try:
            return sum(solution[n] for n in _region_names(region, view))
        except ValueError:
            return -1

    if kind == "COMPARE":
        for _ in range(12):
            left, right = random_region(rng, view.size, _chars(view)), random_region(rng, view.size, _chars(view))
            a, b = count(left), count(right)
            if a < 0 or b < 0:
                continue
            valid = []
            if a < b:
                valid = ["<", "<=", "!="]
            elif a > b:
                valid = [">", ">=", "!="]
            else:
                valid = ["=", "<=", ">="]
            return {**base, "left": left, "right": right, "op": rng.choice(valid)}
        return None

    for _ in range(12):
        region = random_region(rng, view.size, _chars(view))
        names_in_region = _region_names(region, view) if count(region) >= 0 else []
        if not names_in_region:
            continue
        actual = count(region)
        size = len(names_in_region)
        if kind == "EXACTLY":
            return {**base, "region": region, "k": actual}
        if kind == "AT_LEAST":
            return {**base, "region": region, "k": rng.randint(0, actual)}
        if kind == "AT_MOST":
            return {**base, "region": region, "k": rng.randint(actual, size)}
        if kind == "PARITY":
            return {**base, "region": region, "parity": "even" if actual % 2 == 0 else "odd"}
    return None


def _chars(view: PublicView) -> list[Character]:
    return [Character(view.name_to_cell[n], n, view.name_to_job[n]) for n in view.names]


def has_chain(puzzle: Puzzle) -> bool:
    """Cheap reveal-chain test without computing hint relevance."""
    engine = GameEngine(puzzle)
    knowledge = engine.public_knowledge()
    agent = LogicAgent(knowledge["view"])
    agent.update(knowledge["revealed_clues"], knowledge["proved"])
    order = sorted(puzzle.names, key=lambda n: parse_cell(puzzle.name_to_cell[n]))
    while not engine.is_solved():
        advanced = False
        for name in order:
            if name in engine.proved:
                continue
            verdict = agent.classify(name)
            if verdict in ("CRIMINAL", "INNOCENT"):
                engine.reveal(name, verdict == "CRIMINAL")
                knowledge = engine.public_knowledge()
                agent.update(knowledge["revealed_clues"], knowledge["proved"])
                advanced = True
                break
        if not advanced:
            return False
    return True


def chain_clue(
    rng: random.Random,
    owner: str,
    target: str,
    proved_names: list[str],
    view: PublicView,
    solution: dict[str, bool],
    clue_id: str,
) -> dict[str, Any]:
    """A clue owned by an already-proved character that forces exactly one new target."""
    base = {"id": clue_id, "owner": owner}
    style = rng.choice(["FACT", "SAME", "DIFFERENT", "EXACTLY", "EXACTLY", "PARITY", "COMPARE"])
    anchor = rng.choice(proved_names)
    if style == "FACT":
        return {**base, "type": "FACT", "person": target, "status": bool_to_status(solution[target])}
    if style in ("SAME", "DIFFERENT"):
        relation = "SAME" if solution[target] == solution[anchor] else "DIFFERENT"
        return {**base, "type": relation, "a": target, "b": anchor}
    if style in ("EXACTLY", "PARITY"):
        extra = rng.sample(proved_names, rng.randint(1, min(3, len(proved_names))))
        region = {"kind": "cells", "cells": [view.name_to_cell[n] for n in [target, *extra]]}
        count = sum(solution[n] for n in [target, *extra])
        if style == "EXACTLY":
            return {**base, "type": "EXACTLY", "region": region, "k": count}
        return {**base, "type": "PARITY", "region": region,
                "parity": "even" if count % 2 == 0 else "odd"}
    left = {"kind": "cells", "cells": [view.name_to_cell[target]]}
    right = {"kind": "cells", "cells": [view.name_to_cell[anchor]]}
    op = "=" if solution[target] == solution[anchor] else "!="
    return {**base, "type": "COMPARE", "left": left, "right": right, "op": op}


def generate(size: int, seed: int, label: str) -> dict[str, Any]:
    rng = random.Random(seed)
    for attempt in range(1, 201):
        chars = [
            Character(format_cell(r, c), NAMES[(r - 1) * size + c], JOBS[(seed + (r - 1) * size + c) % len(JOBS)])
            for r in range(1, size + 1)
            for c in range(size)
        ]
        view = make_view(size, chars)
        solution = {c.name: rng.random() < 0.5 for c in chars}
        if len(set(solution.values())) < 2:
            continue
        order = sorted((c.name for c in chars), key=lambda n: parse_cell(view.name_to_cell[n]))
        initial = order[:2]
        clues_by_owner: dict[str, dict[str, Any]] = {}
        filler = make_clue(rng, order[0], view, solution, "c1")
        if filler is None:
            continue
        clues_by_owner[order[0]] = filler
        for index in range(1, len(order) - 1):
            clues_by_owner[order[index]] = chain_clue(
                rng, order[index], order[index + 1], order[: index + 1],
                view, solution, f"c{index + 1}",
            )
        last = make_clue(rng, order[-1], view, solution, f"c{len(order)}")
        if last is None:
            continue
        clues_by_owner[order[-1]] = last
        clues = [clues_by_owner[c.name] for c in chars]
        data: dict[str, Any] = {
            "id": label,
            "name": f"Puzzle {label}",
            "group": f"{size}x{size}",
            "size": size,
            "desc": f"{size} x {size} Griductive puzzle, no guessing required.",
            "characters": [{"cell": c.cell, "name": c.name, "job": c.job} for c in chars],
            "clues": clues,
            "solution": {n: bool_to_status(v) for n, v in solution.items()},
            "initial_revealed": initial,
        }
        try:
            puzzle = Puzzle.from_dict(data)
            if not GameEngine(puzzle).verify_hidden_solution():
                continue
            if not has_chain(puzzle):
                continue
        except (ValueError, KeyError, IndexError):
            continue
        data["attempts"] = attempt
        return data
    raise RuntimeError(f"could not generate a {size}x{size} puzzle after 500 attempts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "levels")
    parser.add_argument("--seed", type=int, default=14003)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plan = [(3, "G01"), (3, "G02"), (3, "G03"), (4, "G04"), (4, "G05"), (4, "G06"), (5, "G07")]
    for index, (size, label) in enumerate(plan):
        puzzle = generate(size, args.seed + index * 97, label)
        attempts = puzzle.pop("attempts")
        path = args.out / f"{label}.json"
        path.write_text(json.dumps(puzzle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{label}: {size}x{size}, attempts={attempts}, initial={puzzle['initial_revealed']} -> {path}")


if __name__ == "__main__":
    main()
