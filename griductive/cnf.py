"""Automatic translation of structured clues and proved verdicts into CNF."""
from __future__ import annotations

from itertools import combinations
from typing import Iterable

from .model import NO_CLUE, Clue, Puzzle, _region_names, status_to_bool


class CNFFormula:
    """A CNF knowledge base with deterministic primary/auxiliary variable numbering."""

    def __init__(
        self,
        clauses: list[list[int]],
        primary_count: int,
        aux_count: int,
        name_to_var: dict[str, int],
    ) -> None:
        self.clauses = clauses
        self.primary_count = primary_count
        self.aux_count = aux_count
        self.name_to_var = name_to_var
        self.var_to_name = {v: k for k, v in name_to_var.items()}

    @property
    def variable_count(self) -> int:
        return self.primary_count + self.aux_count

    @property
    def clause_count(self) -> int:
        return len(self.clauses)

    def stats(self) -> dict[str, int]:
        return {
            "primary_variables": self.primary_count,
            "auxiliary_variables": self.aux_count,
            "variables": self.variable_count,
            "clauses": self.clause_count,
        }

    def dimacs(self) -> str:
        lines = [f"p cnf {self.variable_count} {self.clause_count}"]
        lines += [" ".join(map(str, clause)) + " 0" for clause in self.clauses]
        return "\n".join(lines) + "\n"


class CNFEncoder:
    """Builds a fresh CNF knowledge base for one deduction step."""

    def __init__(self, puzzle: Puzzle) -> None:
        self.puzzle = puzzle
        self.name_to_var = {name: i + 1 for i, name in enumerate(puzzle.names)}
        self.primary_count = len(puzzle.names)
        self._next_var = self.primary_count + 1
        self.clauses: list[list[int]] = []
        self.used_aux: set[int] = set()

    def _new_var(self) -> int:
        var = self._next_var
        self._next_var += 1
        self.used_aux.add(var)
        return var

    def _add(self, clause: Iterable[int]) -> None:
        self.clauses.append(list(clause))

    def _at_most(self, variables: list[int], k: int, guard: int | None = None) -> None:
        if k < 0:
            self._add([guard] if guard is not None else [])
            return
        if k >= len(variables):
            return
        for subset in combinations(variables, k + 1):
            clause = [-v for v in subset]
            if guard is not None:
                clause.append(-guard)
            self._add(clause)

    def _at_least(self, variables: list[int], k: int, guard: int | None = None) -> None:
        if k <= 0:
            return
        if k > len(variables):
            self._add([guard] if guard is not None else [])
            return
        for subset in combinations(variables, len(variables) - k + 1):
            clause = list(subset)
            if guard is not None:
                clause.append(-guard)
            self._add(clause)

    def _xor(self, variables: list[int]) -> int:
        result = variables[0]
        for variable in variables[1:]:
            out = self._new_var()
            self._add([-result, -variable, -out])
            self._add([result, variable, -out])
            self._add([result, -variable, out])
            self._add([-result, variable, out])
            result = out
        return result

    def _count_indicators(self, variables: list[int]) -> dict[int, int]:
        """indicator[j] is true iff exactly j of `variables` are true."""
        size = len(variables)
        indicators = {j: self._new_var() for j in range(size + 1)}
        self._add(indicators.values())
        for i, j in combinations(range(size + 1), 2):
            self._add([-indicators[i], -indicators[j]])
        for j, guard in indicators.items():
            self._at_most(variables, j, guard)
            self._at_least(variables, j, guard)
        return indicators

    def encode_clue(self, clue: Clue) -> None:
        params = clue.params
        kind = clue.type
        var = self.name_to_var

        if kind == NO_CLUE:
            return
        if kind == "FACT":
            literal = var[str(params["person"])]
            self._add([literal if status_to_bool(params["status"]) else -literal])
            return
        if kind == "SAME":
            a, b = var[str(params["a"])], var[str(params["b"])]
            self._add([-a, b])
            self._add([a, -b])
            return
        if kind == "DIFFERENT":
            a, b = var[str(params["a"])], var[str(params["b"])]
            self._add([a, b])
            self._add([-a, -b])
            return

        if kind in ("EXACTLY", "AT_LEAST", "AT_MOST"):
            variables = [var[n] for n in _region_names(params["region"], self.puzzle)]
            k = int(params["k"])
            if kind == "EXACTLY":
                self._at_most(variables, k)
                self._at_least(variables, k)
            elif kind == "AT_LEAST":
                self._at_least(variables, k)
            else:
                self._at_most(variables, k)
            return

        if kind == "PARITY":
            variables = [var[n] for n in _region_names(params["region"], self.puzzle)]
            result = self._xor(variables)
            self._add([result if str(params["parity"]).lower() == "odd" else -result])
            return

        if kind == "COMPARE":
            left = [var[n] for n in _region_names(params["left"], self.puzzle)]
            right = [var[n] for n in _region_names(params["right"], self.puzzle)]
            left_counts = self._count_indicators(left)
            right_counts = self._count_indicators(right)
            op = str(params["op"])
            for i, left_var in left_counts.items():
                for j, right_var in right_counts.items():
                    holds = {
                        "<": i < j, "<=": i <= j, "=": i == j,
                        "!=": i != j, ">": i > j, ">=": i >= j,
                    }[op]
                    if not holds:
                        self._add([-left_var, -right_var])
            return

        raise ValueError(f"cannot encode clue type {kind!r}")

    def encode_proved(self, proved: dict[str, bool]) -> None:
        for name, is_criminal in proved.items():
            if name not in self.name_to_var:
                raise ValueError(f"unknown proved character {name!r}")
            literal = self.name_to_var[name]
            self._add([literal if is_criminal else -literal])

    def build(
        self,
        revealed_clues: Iterable[Clue],
        proved: dict[str, bool] | None = None,
    ) -> CNFFormula:
        for clue in revealed_clues:
            self.encode_clue(clue)
        if proved:
            self.encode_proved(proved)
        return CNFFormula(
            self.clauses,
            self.primary_count,
            self._next_var - 1 - self.primary_count,
            self.name_to_var,
        )


def build_knowledge_base(
    puzzle: Puzzle,
    revealed_clues: Iterable[Clue],
    proved: dict[str, bool] | None = None,
) -> CNFFormula:
    """KB_t = CNF(revealed clues) AND unit clauses for proved verdicts."""
    return CNFEncoder(puzzle).build(revealed_clues, proved)
