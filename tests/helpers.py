"""Shared test helpers: brute-force oracle for CNF (reused by later test files)."""
from __future__ import annotations

import random
from itertools import product
from typing import Iterator


def eval_cnf(clauses: list[list[int]], assignment: dict[int, bool]) -> bool:
    """True iff every clause has at least one true literal under a COMPLETE assignment."""
    return all(any(assignment[abs(lit)] == (lit > 0) for lit in clause) for clause in clauses)


def all_models(clauses: list[list[int]], n_vars: int) -> Iterator[dict[int, bool]]:
    """Every satisfying assignment over variables 1..n_vars (2^n enumeration)."""
    for bits in product((False, True), repeat=n_vars):
        assignment = {i + 1: bit for i, bit in enumerate(bits)}
        if eval_cnf(clauses, assignment):
            yield assignment


def brute_force_sat(clauses: list[list[int]], n_vars: int) -> bool:
    return next(all_models(clauses, n_vars), None) is not None


def random_cnf(rng: random.Random, n_vars: int, n_clauses: int, max_len: int = 3) -> list[list[int]]:
    """Random CNF; each clause uses distinct variables with random signs."""
    clauses = []
    for _ in range(n_clauses):
        length = rng.randint(1, min(max_len, n_vars))
        variables = rng.sample(range(1, n_vars + 1), length)
        clauses.append([v if rng.random() < 0.5 else -v for v in variables])
    return clauses