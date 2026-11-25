"""Gaps found when comparing against test_project2.py (so that file can be deleted)."""
import json
from pathlib import Path

import pytest

import main
from griductive import DPLLSolver, CNFFormula, GameEngine, Puzzle, build_knowledge_base
from griductive.model import clue_cells, col_letter, format_cell, parse_cell, region_cells
from puzzle_helpers import make_puzzle, puzzle_dict

ROOT = Path(__file__).resolve().parents[1]
ROW1 = {"kind": "row", "row": 1}
ROW3 = {"kind": "row", "row": 3}


# ---------- cell helpers (multi-letter columns were never tested) ----------

@pytest.mark.parametrize("cell", ["A1", "C2", "I9", "Z1", "AA10", "AB3"])
def test_cell_roundtrip(cell):
    row, col = parse_cell(cell)
    assert format_cell(row, col) == cell


def test_col_letter_boundaries():
    assert [col_letter(i) for i in (0, 25, 26, 27, 51, 52)] == ["A", "Z", "AA", "AB", "AZ", "BA"]
    with pytest.raises(ValueError):
        col_letter(-1)


def test_parse_cell_is_lenient_about_case_and_spaces_but_rejects_garbage():
    assert parse_cell(" b2 ") == (2, 1)
    for bad in ("", "A", "1", "A0", "11A", "A-1"):
        with pytest.raises(ValueError):
            parse_cell(bad)


# ---------- level files: main.py silently SKIPS files that fail to load ----------

def test_every_level_file_loads_and_is_registered():
    files = sorted((ROOT / "levels").glob("*.json"))
    assert files, "no level files found"
    ids = []
    for path in files:
        puzzle = Puzzle.from_dict(json.loads(path.read_text(encoding="utf-8")))   # raises if broken
        ids.append(puzzle.id)
    assert len(set(ids)) == len(ids), "two level files share an id"
    assert set(ids).issubset(set(main.LEVELS)), "main.py skipped or overwrote some level file"


@pytest.mark.parametrize("level_id", list(main.LEVELS))
def test_engine_verify_hidden_solution_on_levels(level_id):
    assert GameEngine(main.LEVELS[level_id]).verify_hidden_solution() is True


def test_engine_verify_hidden_solution_detects_a_false_clue():
    puzzle = make_puzzle([{"type": "FACT", "person": "N01", "status": "CRIMINAL"}])   # solution: all innocent
    assert GameEngine(puzzle).verify_hidden_solution() is False


# ---------- the agent uses a PublicView, not a Puzzle ----------

def test_regions_and_clue_cells_work_on_public_view():
    puzzle = make_puzzle([{"type": "COMPARE", "left": ROW1, "right": ROW3, "op": "<"}])
    view = puzzle.public_view()
    assert len(region_cells({"kind": "neighbors", "cell": "B2"}, view)) == 8
    assert len(region_cells({"kind": "neighbors", "cell": "A1"}, view)) == 3
    expected = ["A1", "B1", "C1", "A3", "B3", "C3"]       # left AND right regions are highlighted
    assert clue_cells(puzzle.clues[0], puzzle) == expected
    assert clue_cells(puzzle.clues[0], view) == expected


def test_encoding_with_public_view_equals_encoding_with_puzzle():
    puzzle = make_puzzle([
        {"type": "PARITY", "region": ROW1, "parity": "odd"},
        {"owner": "N01", "type": "EXACTLY", "region": ROW3, "k": 2},
    ])
    from_puzzle = build_knowledge_base(puzzle, puzzle.clues, {"N05": True})
    from_view = build_knowledge_base(puzzle.public_view(), puzzle.clues, {"N05": True})
    assert from_puzzle.clauses == from_view.clauses
    assert from_puzzle.stats() == from_view.stats()


# ---------- DPLL statistics on a conflict found by propagation alone ----------

def test_unsat_by_propagation_counts_conflict_and_propagations():
    solver = DPLLSolver(CNFFormula([[1], [-1, 2], [-2]], 2, 0, {}))
    sat, model = solver.solve()
    assert sat is False and model is None
    assert solver.stats.propagations > 0
    assert solver.stats.conflicts > 0
    assert solver.stats.decisions == 0