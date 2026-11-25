import pytest
from fastapi.testclient import TestClient

import main
from griductive import (
    DPLLSolver,
    GameEngine,
    GameSession,
    build_knowledge_base,
    check_uniqueness,
)
from griductive.model import Puzzle, clue_is_true, status_to_bool
from puzzle_helpers import make_puzzle, name_of, puzzle_dict

ALL_NAMES = [name_of(i) for i in range(1, 10)]


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def solution_with(*criminals):
    return {name: ("CRIMINAL" if name in criminals else "INNOCENT") for name in ALL_NAMES}


def test_status_to_bool_accepts_mixed_case_and_whitespace():
    assert status_to_bool("criminAL") is True
    assert status_to_bool(" innocent ") is False
    with pytest.raises(ValueError):
        status_to_bool("MAYBE")


def test_lowercase_fact_status_is_evaluated_correctly():
    puzzle = make_puzzle(
        [{"id": "c1", "owner": "N05", "type": "FACT", "person": "N05", "status": "criminal"}],
        solution=solution_with("N05"),
    )
    assert clue_is_true(puzzle.clues[0], puzzle.solution, puzzle) is True


def test_no_clue_card_is_usable_after_reveal():
    data = puzzle_dict(
        [
            {"id": "c1", "owner": "N05", "type": "FACT", "person": "N05", "status": "CRIMINAL"},
            {"id": "c2", "owner": "N01", "type": "AT_MOST", "k": 0,
             "region": {"kind": "cells", "cells": ["A1", "B1"]}},
        ],
        solution=solution_with("N05"),
        initial=["N01"],
        pid="T-no-clue",
    )
    session = GameSession(Puzzle.from_dict(data))
    assert session.engine.proved["N01"] is False

    result = session.verdict("N02", "INNOCENT")
    assert result["result"] == "ACCEPTED"
    assert result["clue_id"] == "no-clue:N02"
    assert any(
        clue["id"] == "no-clue:N02" and clue["text"] == "This card has no clue."
        for clue in result["state"]["clues"]
    )
    knowledge = session.engine.public_knowledge()
    kb = build_knowledge_base(session.engine.puzzle.public_view(), knowledge["revealed_clues"], knowledge["proved"])
    assert kb.clause_count >= 1


def test_engine_reveal_rejects_a_status_that_contradicts_the_solution():
    puzzle = make_puzzle(
        [{"id": "c1", "owner": "N05", "type": "FACT", "person": "N05", "status": "CRIMINAL"}],
        solution=solution_with("N05"),
    )
    with pytest.raises(ValueError, match="contradicts the hidden solution"):
        GameEngine(puzzle).reveal("N05", False)


def test_api_rejects_a_wrong_solution_when_the_clues_are_satisfiable(client):
    data = puzzle_dict(
        [{"id": "c1", "owner": "N01", "type": "FACT", "person": "N01", "status": "CRIMINAL"}],
        pid="T-wrong-solution",
    )
    response = client.post("/api/game/load", json={"puzzle": data})
    assert response.status_code == 422


def test_api_still_allows_an_inconsistent_clue_set(client):
    data = puzzle_dict(
        [
            {"id": "c1", "owner": "N09", "type": "FACT", "person": "N01", "status": "CRIMINAL"},
            {"id": "c2", "owner": "N08", "type": "FACT", "person": "N01", "status": "INNOCENT"},
        ],
        solution=solution_with("N01"),
        pid="T-inconsistent-clues",
    )
    response = client.post("/api/game/load", json={"puzzle": data})
    assert response.status_code == 200


def test_custom_puzzle_is_registered_for_list_reload_and_benchmark(client):
    data = puzzle_dict(
        [{"id": "c1", "owner": "N01", "type": "FACT", "person": "N01", "status": "CRIMINAL"}],
        solution=solution_with("N01"),
        pid="T-registered",
    )
    state = client.post("/api/game/load", json={"puzzle": data})
    assert state.status_code == 200
    assert state.json()["puzzle"]["id"] == "T-registered"
    assert any(p["id"] == "T-registered" for p in client.get("/api/puzzles").json())
    assert client.post("/api/game/load", json={"puzzle_id": "T-registered"}).status_code == 200

    bench = client.post("/api/benchmark", json={"puzzle_ids": ["T-registered"]}).json()
    assert bench["results"][0]["puzzle_id"] == "T-registered"


def test_custom_id_collision_keeps_the_bundled_level_and_renames_the_copy(client):
    data = main.LEVELS["G01"].to_dict()
    data["name"] = "G01 custom copy"
    state = client.post("/api/game/load", json={"puzzle": data}).json()
    assert state["puzzle"]["id"] != "G01"
    assert state["puzzle"]["id"].startswith("G01-")
    assert main.LEVELS["G01"].name != "G01 custom copy"


def test_trace_records_every_agent_sat_query():
    session = GameSession(main.LEVELS["G01"])
    session.auto_solve()
    recorded = [query for entry in session.trace for query in entry.get("queries", [])]
    assert any(entry["action"] == "hint" for entry in session.trace)
    assert recorded == session.agent.queries
    assert len(recorded) == session.agent.sat_calls


def test_relevant_clue_queries_are_counted_and_traced():
    session = GameSession(main.LEVELS["G01"])
    before = session.agent.sat_calls
    hint = session.hint()
    assert hint["available"] is True
    assert session.agent.sat_calls > before
    assert len(hint["state"]["trace"][-1]["queries"]) == session.agent.sat_calls - before


def test_dpll_timeout_and_uniqueness_timeout_are_reported():
    puzzle = main.LEVELS["G01"]
    kb = build_knowledge_base(puzzle.public_view(), puzzle.clues)
    solver = DPLLSolver(kb, timeout_ms=0)
    sat, _ = solver.solve()
    assert sat is False
    assert solver.timed_out is True

    result = check_uniqueness(puzzle, timeout_ms=0)
    assert result["unique"] is False
    assert result["reason"] == "TIMEOUT"
    assert result["timed_out"] is True


def test_benchmark_rows_include_timeout_and_failure_fields(client):
    row = client.post("/api/benchmark", json={"puzzle_ids": ["G01"]}).json()["results"][0]
    assert row["timeout_ms"] == main.BENCHMARK_TIMEOUT_MS
    assert row["timed_out"] is False
    assert row["failure"] is None
