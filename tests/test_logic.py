"""Layer 2: semantic evaluators, regions, clue validation, CNF encoder (direct imports)."""
import random

import pytest

from griductive import DPLLSolver, build_knowledge_base
from griductive.model import clue_cells, clue_is_true, region_cells
from helpers import eval_cnf
from puzzle_helpers import (
    all_assignments, assign, make_puzzle, name_of, puzzle_dict, random_assignment,
)
from griductive import Puzzle

ROW1 = {"kind": "row", "row": 1}
ROW2 = {"kind": "row", "row": 2}
ROW3 = {"kind": "row", "row": 3}
ROW4 = {"kind": "row", "row": 4}
COLB = {"kind": "col", "col": "B"}


def cells(*ids):
    return {"kind": "cells", "cells": list(ids)}


def nb(cell):
    return {"kind": "neighbors", "cell": cell}


def one(spec, size=3):
    puzzle = make_puzzle([spec], size)
    return puzzle, puzzle.clues[0]


# =====================================================================
# 1. Semantic evaluators vs hand-written truth (3x3: A1=N01 ... C3=N09)
# =====================================================================

def fact(p, s): return {"type": "FACT", "person": p, "status": s}
def same(a, b): return {"type": "SAME", "a": a, "b": b}
def diff(a, b): return {"type": "DIFFERENT", "a": a, "b": b}
def count(kind, region, k): return {"type": kind, "region": region, "k": k}


HAND_TRUTH = [
    # FACT / SAME / DIFFERENT
    (fact("N05", "CRIMINAL"), ["N05"], True),
    (fact("N05", "CRIMINAL"), [], False),
    (fact("N05", "INNOCENT"), [], True),
    (fact("N05", "INNOCENT"), ["N05"], False),
    (same("N01", "N09"), [], True),
    (same("N01", "N09"), ["N01", "N09"], True),
    (same("N01", "N09"), ["N01"], False),
    (diff("N01", "N09"), ["N01"], True),
    (diff("N01", "N09"), [], False),
    (diff("N01", "N09"), ["N01", "N09"], False),
    # EXACTLY on row 1 (N01, N02, N03)
    (count("EXACTLY", ROW1, 2), ["N01", "N02"], True),
    (count("EXACTLY", ROW1, 2), ["N01"], False),
    (count("EXACTLY", ROW1, 2), ["N01", "N02", "N03"], False),
    (count("EXACTLY", ROW1, 0), [], True),
    (count("EXACTLY", ROW1, 0), ["N04", "N05"], True),       # outside the region
    (count("EXACTLY", ROW1, 0), ["N01"], False),
    (count("EXACTLY", ROW1, 3), ["N01", "N02", "N03"], True),  # k = |R|
    (count("EXACTLY", ROW1, 3), ["N01", "N02"], False),
    # AT_LEAST / AT_MOST
    (count("AT_LEAST", ROW1, 2), ["N01"], False),
    (count("AT_LEAST", ROW1, 2), ["N01", "N02"], True),
    (count("AT_LEAST", ROW1, 2), ["N01", "N02", "N03"], True),
    (count("AT_LEAST", ROW1, 0), [], True),
    (count("AT_MOST", ROW1, 1), [], True),
    (count("AT_MOST", ROW1, 1), ["N01"], True),
    (count("AT_MOST", ROW1, 1), ["N01", "N02"], False),
    (count("AT_MOST", ROW1, 3), ["N01", "N02", "N03"], True),
    # neighbors: the cell itself is excluded
    (count("EXACTLY", nb("B2"), 0), ["N05"], True),
    (count("EXACTLY", nb("B2"), 0), ["N01"], False),
    # corner A1 has 3 neighbors (N02, N04, N05); self and far cells ignored
    (count("EXACTLY", nb("A1"), 3), ["N02", "N04", "N05"], True),
    (count("EXACTLY", nb("A1"), 3), ["N01", "N02", "N04", "N05", "N09"], True),
    (count("EXACTLY", nb("A1"), 3), ["N02", "N04"], False),
    # edge B1 has 5 neighbors (N01, N03, N04, N05, N06)
    (count("EXACTLY", nb("B1"), 5), ["N01", "N03", "N04", "N05", "N06"], True),
    (count("EXACTLY", nb("B1"), 5), ["N01", "N03", "N04", "N05", "N06", "N02"], True),
    (count("EXACTLY", nb("B1"), 5), ["N01", "N03", "N04", "N05"], False),
    # interior B2 has 8 neighbors
    (count("EXACTLY", nb("B2"), 8), [name_of(i) for i in range(1, 10) if i != 5], True),
    (count("EXACTLY", nb("B2"), 8), [name_of(i) for i in range(1, 10)], True),
    # PARITY on row 1
    ({"type": "PARITY", "region": ROW1, "parity": "odd"}, ["N01"], True),
    ({"type": "PARITY", "region": ROW1, "parity": "odd"}, ["N01", "N02"], False),
    ({"type": "PARITY", "region": ROW1, "parity": "odd"}, [], False),
    ({"type": "PARITY", "region": ROW1, "parity": "even"}, [], True),
    ({"type": "PARITY", "region": ROW1, "parity": "even"}, ["N01", "N02"], True),
    ({"type": "PARITY", "region": ROW1, "parity": "even"}, ["N01"], False),
    ({"type": "PARITY", "region": ROW1, "parity": "even"}, ["N01", "N02", "N03"], False),
]

# COMPARE row1 vs row3. Scenario A: 1 criminal vs 2. Scenario B: 1 vs 1.
for _op, _expected in {"<": True, "<=": True, "=": False, "!=": True, ">": False, ">=": False}.items():
    HAND_TRUTH.append(({"type": "COMPARE", "left": ROW1, "right": ROW3, "op": _op},
                       ["N01", "N07", "N08"], _expected))
for _op, _expected in {"<": False, "<=": True, "=": True, "!=": False, ">": False, ">=": True}.items():
    HAND_TRUTH.append(({"type": "COMPARE", "left": ROW1, "right": ROW3, "op": _op},
                       ["N01", "N07"], _expected))


@pytest.mark.parametrize("spec,criminals,expected", HAND_TRUTH)
def test_evaluator_hand_truth(spec, criminals, expected):
    puzzle, clue = one(spec)
    assert clue_is_true(clue, assign(puzzle, criminals), puzzle) == expected


# =====================================================================
# 2. Region resolution
# =====================================================================

def test_neighbor_counts_3x3():
    puzzle = make_puzzle([count("EXACTLY", ROW1, 0)])
    assert set(region_cells(nb("B2"), puzzle)) == {"A1", "B1", "C1", "A2", "C2", "A3", "B3", "C3"}
    assert region_cells(nb("A1"), puzzle) == ["B1", "A2", "B2"]
    assert region_cells(nb("B1"), puzzle) == ["A1", "C1", "A2", "B2", "C2"]
    assert "B2" not in region_cells(nb("B2"), puzzle)


def test_rows_columns_and_explicit_cells():
    puzzle = make_puzzle([count("EXACTLY", ROW1, 0)])
    assert region_cells(ROW2, puzzle) == ["A2", "B2", "C2"]
    assert region_cells(COLB, puzzle) == ["B1", "B2", "B3"]
    assert region_cells(cells("C3", "A1"), puzzle) == ["A1", "C3"]   # order-insensitive


def test_extension_regions_4x4():
    puzzle = make_puzzle([count("EXACTLY", ROW1, 0)], size=4)
    assert set(region_cells({"kind": "corners"}, puzzle)) == {"A1", "D1", "A4", "D4"}
    boundary = set(region_cells({"kind": "boundary"}, puzzle))
    assert len(boundary) == 12 and not boundary & {"B2", "C2", "B3", "C3"}
    assert region_cells({"kind": "between", "a": "A1", "b": "D1"}, puzzle) == ["B1", "C1"]
    assert region_cells({"kind": "between", "a": "D4", "b": "A1"}, puzzle) == ["B2", "C3"]
    assert set(region_cells({"kind": "common_neighbors", "a": "A1", "b": "C1"}, puzzle)) == {"B1", "B2"}
    inter = {"kind": "intersection", "regions": [ROW1, COLB]}
    assert region_cells(inter, puzzle) == ["B1"]


def test_clue_cells_for_gui_highlight():
    puzzle = make_puzzle([count("EXACTLY", ROW2, 1), fact("N05", "CRIMINAL"), same("N01", "N09")])
    by_type = {c.type: c for c in puzzle.clues}
    assert clue_cells(by_type["EXACTLY"], puzzle) == ["A2", "B2", "C2"]
    assert clue_cells(by_type["FACT"], puzzle) == ["B2"]
    assert clue_cells(by_type["SAME"], puzzle) == ["A1", "C3"]


# =====================================================================
# 3. Clue / puzzle validation
# =====================================================================

BAD_SPECS = [
    count("EXACTLY", ROW1, 4),
    count("EXACTLY", ROW1, -1),
    count("AT_LEAST", ROW1, 4),
    count("AT_MOST", ROW1, 99),
    count("EXACTLY", cells("A1", "Z9"), 1),          # unknown cell
    count("EXACTLY", cells("A1", "A1"), 1),          # repeated cell
    count("EXACTLY", cells(), 0),                    # empty region
    fact("Nobody", "CRIMINAL"),
    fact("N01", "MAYBE"),
    same("N01", "N01"),
    diff("N01", "Nobody"),
    {"type": "PARITY", "region": ROW1, "parity": "weird"},
    {"type": "COMPARE", "left": ROW1, "right": ROW3, "op": "=>"},
    {"type": "TELEPORT", "region": ROW1, "k": 1},    # unknown clue type
    count("EXACTLY", {"kind": "row", "row": 4}, 1),  # outside a 3x3 grid
    count("EXACTLY", {"kind": "col", "col": "D"}, 1),
    count("EXACTLY", {"kind": "spiral"}, 1),
    count("EXACTLY", {"kind": "intersection", "regions": [ROW1, ROW2]}, 0),   # empty
    count("EXACTLY", {"kind": "between", "a": "A1", "b": "B3"}, 0),           # not aligned
    count("EXACTLY", {"kind": "between", "a": "A1", "b": "B1"}, 0),           # nothing between
    count("EXACTLY", {"kind": "between", "a": "A1", "b": "A1"}, 0),           # same endpoint
    {"type": "EXACTLY", "k": 1},                                              # missing region
]


@pytest.mark.parametrize("spec", BAD_SPECS, ids=[f"{i}-{s['type']}" for i, s in enumerate(BAD_SPECS)])
def test_invalid_clue_is_rejected(spec):
    with pytest.raises((ValueError, KeyError, TypeError)):
        make_puzzle([spec])


def test_structural_validation_errors():
    good = [fact("N05", "CRIMINAL")]
    Puzzle.from_dict(puzzle_dict(good))   # sanity: the base dict is valid

    d = puzzle_dict([fact("N05", "CRIMINAL"), same("N01", "N02")])
    d["clues"][1]["owner"] = d["clues"][0]["owner"]            # two clues, one owner
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)

    d = puzzle_dict([fact("N05", "CRIMINAL"), same("N01", "N02")])
    d["clues"][1]["id"] = d["clues"][0]["id"]                  # duplicate clue id
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)

    no_clue = Puzzle.from_dict(puzzle_dict(good, initial=["N01"]))
    assert "N01" in no_clue.initial_revealed

    d = puzzle_dict(good)
    d["characters"].pop()                                      # a cell has no character
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)

    d = puzzle_dict(good)
    d["solution"].pop("N01")                                   # solution misses a character
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)

    d = puzzle_dict(good)
    d["clues"][0]["owner"] = "Nobody"                          # unknown owner
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)

    d = puzzle_dict(good)
    d["size"] = 1
    with pytest.raises(ValueError):
        Puzzle.from_dict(d)


# =====================================================================
# 4. CNF encoder vs semantic evaluator (the most valuable test)
# =====================================================================

def accepts(formula, assignment):
    """Is there an auxiliary setting that makes the CNF true under this primary assignment?"""
    if formula.aux_count == 0:
        model = {formula.name_to_var[n]: v for n, v in assignment.items()}
        return eval_cnf(formula.clauses, model)
    literals = [formula.name_to_var[n] if v else -formula.name_to_var[n] for n, v in assignment.items()]
    sat, _ = DPLLSolver(formula).solve(literals)
    return sat


EXHAUSTIVE_SPECS = [
    fact("N05", "CRIMINAL"), fact("N05", "INNOCENT"),
    same("N01", "N09"), diff("N02", "N08"),
]
_regions = [
    ROW2, COLB, nb("A1"), nb("B1"), nb("B2"), cells("A1", "C3", "B2", "A3"),
]
_sizes = [3, 3, 3, 5, 8, 4]
for _kind in ("EXACTLY", "AT_LEAST", "AT_MOST"):
    for _region, _size in zip(_regions, _sizes):
        for _k in range(_size + 1):
            EXHAUSTIVE_SPECS.append(count(_kind, _region, _k))
# extension region expressions
for _region in (
    {"kind": "corners"}, {"kind": "boundary"},
    {"kind": "intersection", "regions": [ROW1, COLB]},
    {"kind": "common_neighbors", "a": "A1", "b": "C1"},
    {"kind": "between", "a": "A1", "b": "C1"},
    {"kind": "between", "a": "A1", "b": "C3"},
):
    EXHAUSTIVE_SPECS.append(count("EXACTLY", _region, 1))
EXHAUSTIVE_SPECS.append(count("EXACTLY", {"kind": "corners"}, 0))
# extension clue types (these use auxiliary variables)
for _parity in ("even", "odd"):
    for _region in (ROW1, nb("B2"), nb("A1"), {"kind": "boundary"}):
        EXHAUSTIVE_SPECS.append({"type": "PARITY", "region": _region, "parity": _parity})
for _op in ("<", "<=", "=", "!=", ">", ">="):
    EXHAUSTIVE_SPECS.append({"type": "COMPARE", "left": ROW1, "right": ROW3, "op": _op})
for _op in ("<", "=", ">=", "!="):
    EXHAUSTIVE_SPECS.append({"type": "COMPARE", "left": cells("A1", "C3"), "right": nb("B1"), "op": _op})


@pytest.mark.parametrize(
    "spec", EXHAUSTIVE_SPECS, ids=[f"{i}-{s['type']}" for i, s in enumerate(EXHAUSTIVE_SPECS)]
)
def test_encoder_matches_evaluator_exhaustive_3x3(spec):
    """All 2^9 assignments: CNF accepts it  <=>  evaluator says the clue is true."""
    puzzle, clue = one(spec)
    formula = build_knowledge_base(puzzle, [clue])
    for assignment in all_assignments(puzzle):
        assert accepts(formula, assignment) == clue_is_true(clue, assignment, puzzle), (
            spec, [n for n, v in assignment.items() if v]
        )


SAMPLED_SPECS_4X4 = [
    count("EXACTLY", {"kind": "boundary"}, 5),
    count("AT_LEAST", {"kind": "corners"}, 2),
    count("AT_MOST", nb("B2"), 3),
    {"type": "PARITY", "region": {"kind": "boundary"}, "parity": "odd"},
    {"type": "COMPARE", "left": ROW1, "right": ROW4, "op": ">="},
    {"type": "COMPARE", "left": {"kind": "corners"}, "right": nb("B2"), "op": "<"},
]


@pytest.mark.parametrize(
    "spec", SAMPLED_SPECS_4X4, ids=[f"{i}-{s['type']}" for i, s in enumerate(SAMPLED_SPECS_4X4)]
)
def test_encoder_matches_evaluator_sampled_4x4(spec):
    rng = random.Random(2024)
    puzzle, clue = one(spec, size=4)
    formula = build_knowledge_base(puzzle, [clue])
    for _ in range(150):
        assignment = random_assignment(rng, puzzle)
        assert accepts(formula, assignment) == clue_is_true(clue, assignment, puzzle)


# =====================================================================
# 5. Encoder structure: variable map, counts, unit clauses, KB contents
# =====================================================================

def test_variable_map_is_deterministic_and_alphabetical():
    puzzle, clue = one({"type": "PARITY", "region": ROW1, "parity": "odd"})
    first = build_knowledge_base(puzzle, [clue])
    second = build_knowledge_base(puzzle, [clue])
    assert first.name_to_var == {name: i + 1 for i, name in enumerate(sorted(puzzle.names))}
    assert first.name_to_var == second.name_to_var
    assert first.clauses == second.clauses


def test_auxiliary_variables_are_separate_from_primary():
    puzzle, clue = one({"type": "PARITY", "region": ROW1, "parity": "odd"})
    formula = build_knowledge_base(puzzle, [clue])
    assert formula.primary_count == 9
    assert formula.aux_count == 2                      # XOR of 3 variables -> 2 gates
    assert formula.variable_count == 11
    assert max(abs(lit) for clause in formula.clauses for lit in clause) <= formula.variable_count
    assert set(formula.name_to_var.values()) == set(range(1, 10))   # aux never mapped to a name


def test_counts_are_reported_correctly():
    puzzle, clue = one(fact("N05", "CRIMINAL"))
    formula = build_knowledge_base(puzzle, [clue])
    stats = formula.stats()
    assert stats["primary_variables"] == 9 and stats["auxiliary_variables"] == 0
    assert stats["variables"] == 9
    assert stats["clauses"] == len(formula.clauses) == 1
    assert formula.clauses == [[5]]

    puzzle, clue = one(count("EXACTLY", ROW1, 1))
    formula = build_knowledge_base(puzzle, [clue])
    assert formula.stats()["clauses"] == len(formula.clauses)
    assert formula.aux_count == 0                       # direct encoding, no aux


def test_dimacs_export():
    puzzle, clue = one(same("N01", "N02"))
    formula = build_knowledge_base(puzzle, [clue])
    lines = formula.dimacs().splitlines()
    assert lines[0] == f"p cnf {formula.variable_count} {formula.clause_count}"
    assert len(lines) == 1 + formula.clause_count
    assert all(line.endswith(" 0") for line in lines[1:])


def test_proved_verdicts_become_unit_clauses():
    puzzle, _ = one(fact("N05", "CRIMINAL"))
    formula = build_knowledge_base(puzzle, [], {"N01": True, "N02": False})
    assert sorted(formula.clauses) == [[-2], [1]]


def test_unknown_proved_character_is_rejected():
    puzzle, _ = one(fact("N05", "CRIMINAL"))
    with pytest.raises(ValueError):
        build_knowledge_base(puzzle, [], {"Nobody": True})


def test_empty_kb_contains_nothing():
    puzzle, _ = one(fact("N05", "CRIMINAL"))
    formula = build_knowledge_base(puzzle, [])
    assert formula.clauses == [] and formula.variable_count == 9


def test_kb_contains_only_the_clues_it_is_given():
    """Unrevealed clues must not leak into KB_t."""
    puzzle = make_puzzle([fact("N05", "CRIMINAL"), count("EXACTLY", ROW1, 2)])
    first, second = puzzle.clues
    only_first = build_knowledge_base(puzzle, [first])
    both = build_knowledge_base(puzzle, [first, second])
    assert only_first.clauses == [[5]]
    assert len(both.clauses) > len(only_first.clauses)
    assert both.clauses[: len(only_first.clauses)] == only_first.clauses


def test_contradictory_kb_is_unsat():
    puzzle, clue = one(fact("N05", "CRIMINAL"))
    formula = build_knowledge_base(puzzle, [clue], {"N05": False})
    sat, _ = DPLLSolver(formula).solve()
    assert sat is False