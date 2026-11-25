"""Deterministic DPLL SAT solver with unit propagation and search statistics."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Iterable

from .cnf import CNFFormula


class SolverTimeout(Exception):
    pass


@dataclass
class SolverStats:
    decisions: int = 0
    propagations: int = 0
    backtracks: int = 0
    conflicts: int = 0
    time_ms: float = 0.0

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


class DPLLSolver:
    """Recursive DPLL: unit propagation, conflict detection, deterministic branching."""

    def __init__(
        self,
        formula: CNFFormula,
        pure_literal: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        self.formula = formula
        self.clauses = formula.clauses
        self.n = formula.variable_count
        self.stats = SolverStats()
        self.trace: list[str] = []
        self.pure_literal = pure_literal
        self.timeout_ms = timeout_ms
        self.timed_out = False
        self._deadline: float | None = None
        self._variables = sorted({abs(lit) for clause in self.clauses for lit in clause})

    def solve(self, assumptions: Iterable[int] = ()) -> tuple[bool, dict[int, bool] | None]:
        """Return (SAT, complete model). Assumptions are unit literals (e.g. -3)."""
        self.stats = SolverStats()
        self.trace = []
        self.timed_out = False
        self._deadline = (
            time.perf_counter() + self.timeout_ms / 1000.0
            if self.timeout_ms is not None else None
        )
        started = time.perf_counter()
        assignment: dict[int, bool] = {}
        consistent = True
        for literal in assumptions:
            var, wanted = abs(literal), literal > 0
            if var in assignment and assignment[var] != wanted:
                consistent = False
                break
            assignment[var] = wanted
        model = None
        if consistent:
            try:
                model = self._dpll(assignment)
            except SolverTimeout:
                self.timed_out = True
                model = None
        self.stats.time_ms = (time.perf_counter() - started) * 1000.0
        return (model is not None and not self.timed_out), model

    def _check_timeout(self) -> None:
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            raise SolverTimeout(f"solver exceeded {self.timeout_ms} ms")

    def _propagate(self, assignment: dict[int, bool]) -> bool:
        changed_any = False
        while True:
            self._check_timeout()
            changed = False
            for clause in self.clauses:
                unassigned: list[int] = []
                for literal in clause:
                    value = assignment.get(abs(literal))
                    if value is None:
                        unassigned.append(literal)
                    elif value == (literal > 0):
                        break
                else:
                    if not unassigned:
                        self.stats.conflicts += 1
                        return False
                    literal = unassigned[0]
                    if len(unassigned) == 1:
                        assignment[abs(literal)] = literal > 0
                        self.stats.propagations += 1
                        changed = changed_any = True
                    continue
            if not changed:
                return True

    def _satisfied(self, assignment: dict[int, bool]) -> bool:
        for clause in self.clauses:
            if not any(assignment.get(abs(lit)) == (lit > 0) for lit in clause):
                return False
        return True

    def _pure_literals(self, assignment: dict[int, bool]) -> dict[int, bool]:
        signs: dict[int, set[bool]] = {}
        for clause in self.clauses:
            if any(assignment.get(abs(lit)) == (lit > 0) for lit in clause):
                continue
            for literal in clause:
                var = abs(literal)
                if var not in assignment:
                    signs.setdefault(var, set()).add(literal > 0)
        return {var: next(iter(values)) for var, values in signs.items() if len(values) == 1}

    def _pick_variable(self, assignment: dict[int, bool]) -> int | None:
        for var in self._variables:
            if var not in assignment:
                return var
        return None

    def _complete(self, assignment: dict[int, bool]) -> dict[int, bool]:
        model = dict(assignment)
        for var in range(1, self.n + 1):
            model.setdefault(var, False)
        return model

    def _dpll(self, assignment: dict[int, bool]) -> dict[int, bool] | None:
        self._check_timeout()
        if not self._propagate(assignment):
            return None
        if self._satisfied(assignment):
            return self._complete(assignment)

        if self.pure_literal:
            pure = self._pure_literals(assignment)
            if pure:
                for var, value in pure.items():
                    assignment[var] = value
                return self._dpll(assignment)

        var = self._pick_variable(assignment)
        if var is None:
            return self._complete(assignment)

        self.stats.decisions += 1
        self.trace.append(f"D{self.stats.decisions}: C{var} = True")
        for value in (True, False):
            branch = dict(assignment)
            branch[var] = value
            model = self._dpll(branch)
            if model is not None:
                return model
            self.stats.backtracks += 1
            self.trace.append(f"B{self.stats.backtracks}: backtrack C{var} = {value}")
        return None
