"""Layer 1: DPLL solver on raw CNF, no puzzle involved."""
import random

import pytest

from griductive import CNFFormula, DPLLSolver
from helpers import brute_force_sat, eval_cnf, random_cnf


@pytest.fixture(params=[False, True], ids=["plain", "pure_literal"])
def pure(request):
    return request.param


def make(clauses, n):
    return CNFFormula([list(c) for c in clauses], n, 0, {})


def solve(clauses, n, pure=False, assumptions=()):
    solver = DPLLSolver(make(clauses, n), pure_literal=pure)
    sat, model = solver.solve(assumptions)
    return solver, sat, model


def pigeonhole_3_in_2():
    """3 pigeons, 2 holes: UNSAT and needs real search. var(i, j) = 2*i + j + 1."""
    v = lambda i, j: 2 * i + j + 1
    clauses = [[v(i, 0), v(i, 1)] for i in range(3)]
    for j in range(2):
        for i in range(3):
            for k in range(i + 1, 3):
                clauses.append([-v(i, j), -v(k, j)])
    return clauses, 6


# ---------- basic cases ----------

def test_empty_formula_is_sat(pure):
    _, sat, model = solve([], 0, pure)
    assert sat is True and model == {}


def test_empty_clause_is_unsat(pure):
    _, sat, model = solve([[]], 1, pure)
    assert sat is False and model is None


def test_spec_example(pure):
    """KB = (A or B) and (not A or B): SAT, B forced True, A undetermined."""
    kb = [[1, 2], [-1, 2]]
    _, sat, model = solve(kb, 2, pure)
    assert sat and model[2] is True and eval_cnf(kb, model)
    assert solve(kb, 2, pure, [-2])[1] is False   # KB and not B -> UNSAT
    assert solve(kb, 2, pure, [1])[1] is True     # A can be True
    assert solve(kb, 2, pure, [-1])[1] is True    # A can be False


def test_contradictory_assumptions_are_unsat(pure):
    assert solve([[1, 2]], 2, pure, [1, -1])[1] is False


def test_model_is_complete_and_valid(pure):
    clauses = [[1, -2], [2, 3], [-3, 4, 5], [-1, -5]]
    _, sat, model = solve(clauses, 5, pure)
    assert sat
    assert set(model) == {1, 2, 3, 4, 5}
    assert eval_cnf(clauses, model)


# ---------- statistics ----------

def test_unit_propagation_alone_solves_implication_chain():
    clauses = [[1], [-1, 2], [-2, 3], [-3, 4]]
    solver, sat, model = solve(clauses, 4)
    assert sat and all(model[v] for v in (1, 2, 3, 4))
    assert solver.stats.decisions == 0
    assert solver.stats.backtracks == 0
    assert solver.stats.propagations == 4


def test_pigeonhole_is_unsat_and_needs_search(pure):
    clauses, n = pigeonhole_3_in_2()
    solver, sat, model = solve(clauses, n, pure)
    assert sat is False and model is None
    assert solver.stats.decisions > 0
    assert solver.stats.backtracks > 0


def test_stats_are_non_negative_and_reset_between_calls():
    clauses, n = pigeonhole_3_in_2()
    solver = DPLLSolver(make(clauses, n))
    solver.solve()
    first = solver.stats.to_dict()
    solver.solve()
    second = solver.stats.to_dict()
    for key in ("decisions", "propagations", "backtracks", "conflicts", "time_ms"):
        assert first[key] >= 0 and second[key] >= 0
    for key in ("decisions", "propagations", "backtracks", "conflicts"):
        assert first[key] == second[key]   # reset, not accumulated


def test_deterministic_runs():
    rng = random.Random(7)
    for _ in range(50):
        n = rng.randint(2, 8)
        clauses = random_cnf(rng, n, rng.randint(1, 25))
        a, sat_a, model_a = solve(clauses, n)
        b, sat_b, model_b = solve(clauses, n)
        assert (sat_a, model_a) == (sat_b, model_b)
        assert a.trace == b.trace
        assert a.stats.decisions == b.stats.decisions


# ---------- the key test: DPLL vs brute force ----------

def test_agrees_with_brute_force_on_random_cnf(pure):
    rng = random.Random(1234)
    for _ in range(300):
        n = rng.randint(1, 8)
        clauses = random_cnf(rng, n, rng.randint(1, 30))
        _, sat, model = solve(clauses, n, pure)
        assert sat == brute_force_sat(clauses, n), clauses
        if sat:
            assert eval_cnf(clauses, model), (clauses, model)


def test_agrees_with_brute_force_with_assumptions(pure):
    rng = random.Random(99)
    for _ in range(300):
        n = rng.randint(1, 8)
        clauses = random_cnf(rng, n, rng.randint(1, 25))
        assumptions = [rng.choice((-1, 1)) * rng.randint(1, n) for _ in range(rng.randint(1, 2))]
        _, sat, model = solve(clauses, n, pure, assumptions)
        expected = brute_force_sat(clauses + [[lit] for lit in assumptions], n)
        assert sat == expected, (clauses, assumptions)
        if sat:
            assert eval_cnf(clauses, model)
            assert all(model[abs(l)] == (l > 0) for l in assumptions)