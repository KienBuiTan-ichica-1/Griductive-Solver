"""Deductive agent: entailment classification, hints and uniqueness checking."""
from __future__ import annotations

import time
from typing import Iterable

from .cnf import CNFFormula, build_knowledge_base
from .dpll import DPLLSolver, SolverTimeout
from .model import (
    NO_CLUE,
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

    def __init__(self, view: PublicView, timeout_ms: float | None = None) -> None:
        self.view = view
        self.timeout_ms = timeout_ms
        self.revealed_clues: list[Clue] = []
        self.proved: dict[str, bool] = {}
        self.queries: list[dict] = []
        self.sat_calls = 0
        self.entail_sat_calls = 0
        self.hint_sat_calls = 0
        self.decisions = 0
        self.propagation_count = 0
        self.backtracks = 0
        self.runtime_ms = 0.0
        self.timeouts = 0
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

    def _solve(
        self,
        kb: CNFFormula,
        assumptions: list[int],
        clue_ids: list[str] | None = None,
        purpose: str = "entail",
    ) -> bool:
        solver = DPLLSolver(kb, timeout_ms=self.timeout_ms)
        try:
            sat, _ = solver.solve(assumptions)
        except SolverTimeout:
            sat = False
        stats = solver.stats.to_dict()
        self.sat_calls += 1
        if purpose == "hint":
            self.hint_sat_calls += 1
        else:
            self.entail_sat_calls += 1
        self.decisions += int(stats["decisions"])
        self.propagation_count += int(stats["propagations"])
        self.backtracks += int(stats["backtracks"])
        self.runtime_ms += float(stats["time_ms"])
        if solver.timed_out:
            self.timeouts += 1
        self.queries.append({
            "purpose": purpose,
            "assumption": assumptions,
            "sat": sat,
            "decisions": stats["decisions"],
            "propagations": stats["propagations"],
            "backtracks": stats["backtracks"],
            "time_ms": round(float(stats["time_ms"]), 4),
            "clue_ids": list(clue_ids) if clue_ids is not None else [
                clue.id for clue in self.revealed_clues
            ],
            "timeout": solver.timed_out,
        })
        if solver.timed_out:
            raise SolverTimeout(f"agent query exceeded {self.timeout_ms} ms")
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
        """Find a minimal clue set still forcing the verdict, then name one of its clues."""
        candidates = [clue for clue in self.revealed_clues if clue.type != NO_CLUE]
        if not candidates:
            return None
        variable = self._knowledge_base().name_to_var[name]
        opposite = -variable if verdict == "CRIMINAL" else variable

        def still_forced(clues: list[Clue]) -> bool:
            kb = build_knowledge_base(self.view, clues, self.proved)
            return not self._solve(kb, [opposite], [c.id for c in clues], purpose="hint")

        needed = list(candidates)
        if still_forced(needed):
            for clue in list(needed):
                trial = [c for c in needed if c.id != clue.id]
                if still_forced(trial):
                    needed = trial
        return needed[0].id if needed else None

    def summary(self) -> dict:
        return {
            "kb": self.last_kb_stats,
            "sat_calls": self.entail_sat_calls,
            "hint_sat_calls": self.hint_sat_calls,
            "total_sat_calls": self.sat_calls,
            "decisions": self.decisions,
            "propagations": self.propagation_count,
            "backtracks": self.backtracks,
            "timeouts": self.timeouts,
            "runtime_ms": round(self.runtime_ms, 3),
            "revealed_clues": len(self.revealed_clues),
            "proved": len(self.proved),
            "last_queries": self.queries[-6:],
        }


def check_uniqueness(puzzle: Puzzle, timeout_ms: float | None = None) -> dict:
    """Verify that all clues plus the initially revealed statuses admit one assignment."""
    started = time.perf_counter()

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    initial_statuses = {
        name: puzzle.solution[name] for name in puzzle.initial_revealed
    }
    kb = build_knowledge_base(puzzle.public_view(), puzzle.clues, initial_statuses)
    solver = DPLLSolver(kb, timeout_ms=timeout_ms)
    try:
        sat, _ = solver.solve()
    except SolverTimeout:
        return {"unique": False, "reason": "TIMEOUT", "timed_out": True,
                "timeout_ms": timeout_ms, "sat_calls": 1, "time_ms": elapsed()}
    if not sat:
        return {"unique": False, "reason": "INCONSISTENT", "timed_out": False,
                "timeout_ms": timeout_ms, "sat_calls": 1, "time_ms": elapsed()}
    forced = 0
    calls = 1
    for name in puzzle.names:
        variable = kb.name_to_var[name]
        for assumption in (variable, -variable):
            calls += 1
            solver = DPLLSolver(kb, timeout_ms=timeout_ms)
            try:
                model_sat, _ = solver.solve([assumption])
            except SolverTimeout:
                return {"unique": False, "reason": "TIMEOUT", "timed_out": True,
                        "timeout_ms": timeout_ms, "sat_calls": calls, "time_ms": elapsed()}
            if not model_sat:
                forced += 1
                break
    unique = forced == len(puzzle.names)
    return {
        "unique": unique,
        "timed_out": False,
        "timeout_ms": timeout_ms,
        "forced_characters": forced,
        "characters": len(puzzle.names),
        "sat_calls": calls,
        "kb": kb.stats(),
        "time_ms": elapsed(),
    }
