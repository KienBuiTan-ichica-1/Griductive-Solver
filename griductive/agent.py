"""Deductive agent: entailment classification, hints and uniqueness checking."""
from __future__ import annotations

import time
from typing import Iterable

from .cnf import CNFFormula, build_knowledge_base
from .dpll import DPLLSolver
from .model import (
    Clue,
    PublicView,
    Puzzle,
    bool_to_status,
    parse_cell,
)

UNKNOWN = "UNKNOWN"
INCONSISTENT = "INCONSISTENT"


class LogicAgent:
    """Operates only on revealed clues and proved verdicts; never reads hidden data."""

    def __init__(self, view: PublicView) -> None:
        self.view = view
        self.revealed_clues: list[Clue] = []
        self.proved: dict[str, bool] = {}
        self.queries: list[dict] = []
        self.sat_calls = 0
        self.decisions = 0
        self.propagation_count = 0
        self.backtracks = 0
        self.runtime_ms = 0.0
        self.last_kb_stats: dict[str, int] = {}
        self._kb: CNFFormula | None = None
        self._consistent: bool | None = None
        self._cache: dict[str, str] = {}

    def update(self, revealed_clues: Iterable[Clue], proved: dict[str, bool]) -> None:
        self.revealed_clues = list(revealed_clues)
        self.proved = dict(proved)
        self._kb = None
        self._consistent = None
        self._cache.clear()

    def knowledge(self) -> dict:
        return {"clue_ids": [clue.id for clue in self.revealed_clues]}

    def _knowledge_base(self) -> CNFFormula:
        if self._kb is None:
            self._kb = build_knowledge_base(self.view, self.revealed_clues, self.proved)
            self.last_kb_stats = self._kb.stats()
        return self._kb

    def _solve(self, kb: CNFFormula, assumptions: list[int]) -> bool:
        solver = DPLLSolver(kb)
        sat, _ = solver.solve(assumptions)
        stats = solver.stats.to_dict()
        self.sat_calls += 1
        self.decisions += int(stats["decisions"])
        self.propagation_count += int(stats["propagations"])
        self.backtracks += int(stats["backtracks"])
        self.runtime_ms += float(stats["time_ms"])
        self.queries.append({
            "assumption": assumptions,
            "sat": sat,
            "decisions": stats["decisions"],
            "propagations": stats["propagations"],
            "backtracks": stats["backtracks"],
            "time_ms": round(float(stats["time_ms"]), 4),
            "clue_ids": [clue.id for clue in self.revealed_clues],
        })
        return sat

    def classify(self, name: str, force: bool = False) -> str:
        """CRIMINAL / INNOCENT / UNKNOWN / INCONSISTENT for one character."""
        if not force and name in self._cache:
            return self._cache[name]
        kb = self._knowledge_base()
        if self._consistent is None:
            self._consistent = self._solve(kb, [])
        if not self._consistent:
            return INCONSISTENT
        if name in self.proved:
            result = bool_to_status(self.proved[name])
        else:
            variable = kb.name_to_var[name]
            if not self._solve(kb, [-variable]):
                result = "CRIMINAL"
            elif not self._solve(kb, [variable]):
                result = "INNOCENT"
            else:
                result = UNKNOWN
        self._cache[name] = result
        return result

    def classify_all(self) -> dict[str, str]:
        return {name: self.classify(name) for name in self.view.names}

    def forced_next(self) -> str | None:
        """First forced, still unsolved character in row-major order."""
        order = sorted(self.view.names, key=lambda n: parse_cell(self.view.name_to_cell[n]))
        for name in order:
            if name not in self.proved and self.classify(name) in ("CRIMINAL", "INNOCENT"):
                return name
        return None

    def relevant_clue(self, name: str, verdict: str) -> str | None:
        """Leave-one-out test: which revealed clue is needed to force this verdict?"""
        for clue in self.revealed_clues:
            remaining = [c for c in self.revealed_clues if c.id != clue.id]
            kb = build_knowledge_base(self.view, remaining, self.proved)
            variable = kb.name_to_var[name]
            opposite = -variable if verdict == "CRIMINAL" else variable
            sat, _ = DPLLSolver(kb).solve([opposite])
            if sat:   # without this clue the verdict is no longer forced, so the clue is needed
                return clue.id
        return self.revealed_clues[0].id if self.revealed_clues else None

    def summary(self) -> dict:
        return {
            "kb": self.last_kb_stats,
            "sat_calls": self.sat_calls,
            "decisions": self.decisions,
            "propagations": self.propagation_count,
            "backtracks": self.backtracks,
            "runtime_ms": round(self.runtime_ms, 3),
            "revealed_clues": len(self.revealed_clues),
            "proved": len(self.proved),
            "last_queries": self.queries[-6:],
        }


def check_uniqueness(puzzle: Puzzle) -> dict:
    """Verify that all clues plus the initially revealed statuses admit one assignment."""
    started = time.perf_counter()
    initial_statuses = {
        name: puzzle.solution[name] for name in puzzle.initial_revealed
    }
    kb = build_knowledge_base(puzzle.public_view(), puzzle.clues, initial_statuses)
    solver = DPLLSolver(kb)
    sat, _ = solver.solve()
    if not sat:
        return {"unique": False, "reason": "INCONSISTENT", "sat_calls": 1,
                "time_ms": round((time.perf_counter() - started) * 1000, 3)}
    forced = 0
    calls = 1
    for name in puzzle.names:
        variable = kb.name_to_var[name]
        for assumption in (variable, -variable):
            calls += 1
            solver = DPLLSolver(kb)
            model_sat, _ = solver.solve([assumption])
            if not model_sat:
                forced += 1
                break
    unique = forced == len(puzzle.names)
    return {
        "unique": unique,
        "forced_characters": forced,
        "characters": len(puzzle.names),
        "sat_calls": calls,
        "kb": kb.stats(),
        "time_ms": round((time.perf_counter() - started) * 1000, 3),
    }
