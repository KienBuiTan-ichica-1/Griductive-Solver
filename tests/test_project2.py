"""Unit tests for the Griductive solver (python -m unittest discover -s tests)."""
from __future__ import annotations

import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from griductive import (  # noqa: E402
    CNFFormula,
    DPLLSolver,
    GameSession,
    Puzzle,
    check_uniqueness,
)
from griductive.cnf import CNFEncoder, build_knowledge_base  # noqa: E402
from griductive.model import (  # noqa: E402
    Character,
    Clue,
    _region_names,
    bool_to_status,
    clue_cells,
    clue_is_true,
    format_cell,
    parse_cell,
)

LEVELS = sorted((ROOT / "levels").glob("*.json"))


def toy_puzzle() -> Puzzle:
    return Puzzle.from_dict({
        "id": "TOY", "name": "Toy", "group": "test", "size": 3,
        "characters": [
            {"cell": format_cell(r, c), "name": chr(ord("A") + (r - 1) * 3 + c), "job": "Worker"}
            for r in range(1, 4) for c in range(3)
        ],
        "clues": [], "solution": {chr(ord("A") + i): False for i in range(9)}, "initial_revealed": [],
    })


def with_clues(clues: list[dict], solution: dict[str, bool], initial: list[str] | None = None) -> Puzzle:
    data = toy_puzzle().to_dict()
    data["clues"] = clues
    data["solution"] = {n: bool_to_status(v) for n, v in solution.items()}
    data["initial_revealed"] = initial or []
    return Puzzle.from_dict(data)


class ModelTests(unittest.TestCase):
    def test_cell_roundtrip(self):
        for cell in ("A1", "C2", "I9", "AA10"):
            row, col = parse_cell(cell)
            self.assertEqual(format_cell(row, col), cell)

    def test_regions(self):
        p = toy_puzzle()
        view = p.public_view()
        self.assertEqual(len(_region_names({"kind": "row", "row": 2}, view)), 3)
        self.assertEqual(len(_region_names({"kind": "col", "col": "B"}, view)), 3)
        self.assertEqual(len(_region_names({"kind": "neighbors", "cell": "B2"}, view)), 8)
        self.assertEqual(len(_region_names({"kind": "neighbors", "cell": "A1"}, view)), 3)
        self.assertEqual(len(_region_names({"kind": "boundary"}, view)), 8)
        self.assertEqual(len(_region_names({"kind": "corners"}, view)), 4)
        self.assertEqual(len(_region_names({"kind": "between", "a": "A1", "b": "C1"}, view)), 1)
        self.assertEqual(len(_region_names({
            "kind": "intersection", "regions": [
                {"kind": "row", "row": 1}, {"kind": "col", "col": "A"},
            ]}, view)), 1)
        self.assertEqual(len(_region_names({
            "kind": "common_neighbors", "a": "A1", "b": "C1"}, view)), 2)

    def test_evaluators(self):
        solution = {chr(ord("A") + i): i % 2 == 0 for i in range(9)}
        region = {"kind": "row", "row": 1}
        count = sum(solution[n] for n in _region_names(region, toy_puzzle().public_view()))
        clues = [
            {"id": "c1", "owner": "A", "type": "FACT", "person": "A", "status": "CRIMINAL"},
            {"id": "c2", "owner": "B", "type": "SAME", "a": "A", "b": "C"},
            {"id": "c3", "owner": "C", "type": "DIFFERENT", "a": "A", "b": "B"},
            {"id": "c4", "owner": "D", "type": "EXACTLY", "k": count, "region": region},
            {"id": "c5", "owner": "E", "type": "AT_LEAST", "k": count, "region": region},
            {"id": "c6", "owner": "F", "type": "AT_MOST", "k": count, "region": region},
            {"id": "c7", "owner": "G", "type": "PARITY", "parity": "even" if count % 2 == 0 else "odd", "region": region},
            {"id": "c8", "owner": "H", "type": "COMPARE", "op": "=", "left": region, "right": region},
        ]
        puzzle = with_clues(clues, solution)
        for clue in puzzle.clues:
            self.assertTrue(clue_is_true(clue, solution, puzzle), clue.id)
        self.assertTrue(clue_cells(puzzle.clues[7], puzzle))

    def test_validation(self):
        bad = [
            {"id": "x", "owner": "A", "type": "EXACTLY", "k": 4, "region": {"kind": "row", "row": 1}},
            {"id": "x", "owner": "A", "type": "FACT", "person": "Z", "status": "CRIMINAL"},
            {"id": "x", "owner": "A", "type": "SAME", "a": "A", "b": "A"},
            {"id": "x", "owner": "A", "type": "PARITY", "parity": "maybe", "region": {"kind": "row", "row": 1}},
        ]
        for clue in bad:
            with self.assertRaises(ValueError):
                with_clues([clue], {n: False for n in toy_puzzle().names})


class SolverTests(unittest.TestCase):
    def test_dpll_entailment_from_spec(self):
        kb = CNFFormula([[1, 2], [-1, 2]], 2, 0, {"A": 1, "B": 2})
        solver = DPLLSolver(kb)
        sat, model = solver.solve([-2])
        self.assertFalse(sat)
        self.assertIsNone(model)
        self.assertTrue(DPLLSolver(kb).solve([2])[0])
        self.assertTrue(DPLLSolver(kb).solve([-1])[0])
        self.assertTrue(DPLLSolver(kb).solve([1])[0])
        self.assertGreater(solver.stats.conflicts, 0)
        self.assertIn("decisions", solver.stats.to_dict())

    def test_unit_propagation_and_unsat(self):
        kb = CNFFormula([[1], [-1, 2], [-2]], 2, 0, {"A": 1, "B": 2})
        solver = DPLLSolver(kb)
        sat, _ = solver.solve()
        self.assertFalse(sat)
        self.assertGreater(solver.stats.propagations, 0)

    def test_encoder_matches_semantics(self):
        rng = random.Random(7)
        p = toy_puzzle()
        view = p.public_view()
        solution = {n: rng.random() < 0.5 for n in p.names}
        region = {"kind": "neighbors", "cell": "B2"}
        count = sum(solution[n] for n in _region_names(region, view))
        cases = [
            ("FACT", {"person": "A", "status": bool_to_status(solution["A"])}),
            ("SAME", {"a": "A", "b": "B"}),
            ("DIFFERENT", {"a": "C", "b": "D"}),
            ("EXACTLY", {"k": count, "region": region}),
            ("AT_LEAST", {"k": max(0, count - 1), "region": region}),
            ("AT_MOST", {"k": min(8, count + 1), "region": region}),
            ("PARITY", {"parity": "even" if count % 2 == 0 else "odd", "region": region}),
            ("COMPARE", {"op": "=", "left": region, "right": region}),
        ]
        for index, (kind, params) in enumerate(cases):
            clue = Clue(f"t{index}", "A", kind, params)
            kb = CNFEncoder(p).build([clue])
            self.assertGreater(kb.clause_count, 0)
            for _ in range(4):
                assignment = {n: rng.random() < 0.5 for n in p.names}
                assumptions = [kb.name_to_var[n] if assignment[n] else -kb.name_to_var[n] for n in p.names]
                sat, _ = DPLLSolver(kb).solve(assumptions)
                self.assertEqual(sat, clue_is_true(clue, assignment, view))

    def test_stats_and_dimacs(self):
        kb = build_knowledge_base(toy_puzzle(), [])
        self.assertIn("p cnf", kb.dimacs())
        self.assertEqual(kb.stats()["primary_variables"], 9)
        self.assertEqual(kb.stats()["clauses"], 0)


class GameTests(unittest.TestCase):
    def test_no_guess_protocol(self):
        path = next(p for p in LEVELS if p.stem == "G01")
        puzzle = Puzzle.from_dict(json.loads(path.read_text(encoding="utf-8")))
        session = GameSession(puzzle)
        classifications = session.agent.classify_all()
        unsolved = next(n for n in puzzle.names if classifications[n] == "UNKNOWN")
        result = session.verdict(unsolved, "CRIMINAL")
        self.assertEqual(result["result"], "NOT_PROVABLE")
        forced = session.hint()
        self.assertTrue(forced["available"])
        wrong = "INNOCENT" if forced["verdict"] == "CRIMINAL" else "CRIMINAL"
        result = session.verdict(forced["name"], wrong)
        self.assertEqual(result["result"], "CONTRADICTED")
        before = len(session.state()["clues"])
        result = session.verdict(forced["name"], forced["verdict"])
        self.assertEqual(result["result"], "ACCEPTED")
        self.assertEqual(len(session.state()["clues"]), before + 1)
        last = session.state()["trace"][-1]
        for key in ("step", "active_clues", "sat_queries", "queries", "verdict", "revealed_clue"):
            self.assertIn(key, last)
        self.assertTrue(last["queries"])
        public = session.state()
        for character in public["characters"]:
            if character["name"] not in session.engine.proved:
                self.assertIsNone(character["status"])

    def test_all_levels_solve_and_are_unique(self):
        for path in LEVELS:
            with self.subTest(level=path.stem):
                puzzle = Puzzle.from_dict(json.loads(path.read_text(encoding="utf-8")))
                session = GameSession(puzzle)
                self.assertTrue(session.engine.verify_hidden_solution())
                self.assertTrue(check_uniqueness(puzzle)["unique"])
                result = GameSession(puzzle).auto_solve()
                self.assertTrue(result["solved"])
                state = result["state"]
                self.assertTrue(state["solved"])
                self.assertTrue(all(c["status"] for c in state["characters"]))

    def test_restart(self):
        puzzle = Puzzle.from_dict(json.loads(LEVELS[0].read_text(encoding="utf-8")))
        session = GameSession(puzzle)
        hint = session.hint()
        session.verdict(hint["name"], hint["verdict"])
        session.restart()
        self.assertEqual(session.state()["steps"], 0)
        self.assertEqual(len(session.state()["clues"]), len(puzzle.initial_revealed))


if __name__ == "__main__":
    unittest.main()
