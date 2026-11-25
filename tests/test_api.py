"""Layer 3: HTTP API tests (in-process through FastAPI's TestClient, no server needed).

Needs:  pip install pytest httpx
Run from the project root so main.py can find levels/*.json.
Select by size with -k, e.g.  pytest tests/test_api.py -k "not 5x5"
"""
import json
from itertools import product

import pytest
from fastapi.testclient import TestClient

import main
from griductive.model import clue_is_true, describe_clue
from puzzle_helpers import name_of, puzzle_dict

CRIMINAL, INNOCENT, UNKNOWN = "CRIMINAL", "INNOCENT", "UNKNOWN"
FORCED = (CRIMINAL, INNOCENT)

LEVEL_IDS = list(main.LEVELS)
SMALL_IDS = [i for i in LEVEL_IDS if main.LEVELS[i].size <= 4]   # brute force is cheap here


def _ids(ids):
    return [f"{i}-{main.LEVELS[i].size}x{main.LEVELS[i].size}" for i in ids]


# ---------------------------------------------------------------- fixtures / helpers

@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


@pytest.fixture(scope="module")
def lenient():
    """Same app, but server errors come back as HTTP 500 instead of raising in the test."""
    return TestClient(main.app, raise_server_exceptions=False)


def get(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    return r.json()


def post(client, path, **body):
    r = client.post(path, json=body) if body else client.post(path)
    assert r.status_code == 200, r.text
    return r.json()


def load(client, puzzle_id=None, puzzle=None):
    return post(client, "/api/game/load", **({"puzzle": puzzle} if puzzle is not None else {"puzzle_id": puzzle_id}))


def public(state):
    """The part of the state that must not change when a verdict is rejected."""
    return {k: v for k, v in state.items() if k not in ("trace", "analysis")}


def status_of(state, name):
    return next(c["status"] for c in state["characters"] if c["name"] == name)


def sol(criminals, size=3):
    return {name_of(i): (CRIMINAL if name_of(i) in criminals else INNOCENT) for i in range(1, size * size + 1)}


# ---------------------------------------------------------------- hand-made puzzles

ROW1 = {"kind": "row", "row": 1}


def puzzle_basic():
    """After load: N01 is forced CRIMINAL, N09 known INNOCENT, everyone else UNKNOWN.
    N01's own clue (c2) stays hidden until N01 is proved."""
    return puzzle_dict([
        {"id": "c1", "owner": "N09", "type": "FACT", "person": "N01", "status": CRIMINAL},
        {"id": "c2", "owner": "N01", "type": "SAME", "a": "N02", "b": "N03"},
    ], initial=["N09"], solution=sol({"N01"}), pid="T-basic")


def puzzle_hint():
    """Two revealed clues; only c_fact is needed to force N05 (c_same is irrelevant)."""
    return puzzle_dict([
        {"id": "c_fact", "owner": "N09", "type": "FACT", "person": "N05", "status": CRIMINAL},
        {"id": "c_same", "owner": "N08", "type": "SAME", "a": "N02", "b": "N03"},
    ], initial=["N08", "N09"], solution=sol({"N05"}), pid="T-hint")


def puzzle_inconsistent():
    return puzzle_dict([
        {"id": "c1", "owner": "N09", "type": "FACT", "person": "N01", "status": CRIMINAL},
        {"id": "c2", "owner": "N08", "type": "FACT", "person": "N01", "status": INNOCENT},
    ], initial=["N08", "N09"], solution=sol({"N01"}), pid="T-inconsistent")


def puzzle_stuck():
    """The only revealed clue is trivially true, so nothing is ever forced."""
    return puzzle_dict([
        {"id": "c1", "owner": "N09", "type": "AT_MOST", "region": ROW1, "k": 3},
    ], initial=["N09"], solution=sol(set()), pid="T-stuck")


def puzzle_tiny(initial):
    """2x2. Every clue is a FACT, so the full clue set has exactly one solution."""
    return puzzle_dict([
        {"id": "c1", "owner": "N04", "type": "FACT", "person": "N01", "status": CRIMINAL},
        {"id": "c2", "owner": "N03", "type": "FACT", "person": "N02", "status": INNOCENT},
        {"id": "c3", "owner": "N02", "type": "FACT", "person": "N03", "status": CRIMINAL},
        {"id": "c4", "owner": "N01", "type": "FACT", "person": "N04", "status": INNOCENT},
    ], size=2, initial=initial, solution=sol({"N01", "N03"}, size=2), pid="T-tiny")


# ---------------------------------------------------------------- brute-force oracle

def models_of(puzzle, clue_ids, proved):
    clues = [puzzle.clue_by_id[i] for i in clue_ids]
    free = [n for n in puzzle.names if n not in proved]
    for bits in product((False, True), repeat=len(free)):
        assignment = dict(proved)
        assignment.update(zip(free, bits))
        if all(clue_is_true(c, assignment, puzzle) for c in clues):
            yield assignment


def oracle_classification(puzzle, clue_ids, proved):
    models = list(models_of(puzzle, clue_ids, proved))
    if not models:
        return {n: "INCONSISTENT" for n in puzzle.names}
    out = {}
    for n in puzzle.names:
        values = {m[n] for m in models}
        out[n] = UNKNOWN if len(values) == 2 else (CRIMINAL if True in values else INNOCENT)
    return out


def public_kb(state):
    clue_ids = [c["id"] for c in state["clues"]]
    proved = {c["name"]: c["status"] == CRIMINAL for c in state["characters"] if c["status"] is not None}
    return clue_ids, proved


def count_solutions(puzzle):
    initial = {n: puzzle.solution[n] for n in puzzle.initial_revealed}
    found = []
    for bits in product((False, True), repeat=len(puzzle.names)):
        a = dict(zip(puzzle.names, bits))
        if any(a[n] != v for n, v in initial.items()):
            continue
        if all(clue_is_true(c, a, puzzle) for c in puzzle.clues):
            found.append(a)
    return found


def contains_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_key(v, key) for v in obj)
    return False


def assert_no_leak(puzzle, state):
    """The public state must never expose hidden statuses, unrevealed clue ids or clue text."""
    assert not contains_key(state, "solution")
    chars = {c["name"]: c for c in state["characters"]}
    for name, ch in chars.items():
        if ch["revealed"]:
            assert ch["status"] == (CRIMINAL if puzzle.solution[name] else INNOCENT)
        else:
            assert ch["status"] is None, f"{name} status leaked"
    revealed_owners = {c["owner"] for c in state["clues"]}
    assert revealed_owners == {n for n, ch in chars.items() if ch["revealed"]}
    blob = json.dumps(state)
    shown_texts = {c["text"] for c in state["clues"]}
    for owner, clue in puzzle.clue_by_owner.items():
        if owner in revealed_owners:
            continue
        assert f'"{clue.id}"' not in blob, f"hidden clue id {clue.id} leaked"
        text = describe_clue(clue, puzzle)
        if text not in shown_texts:
            assert text not in blob, f"hidden clue text leaked: {text}"


# =====================================================================
# A. API surface
# =====================================================================

def test_health_lists_puzzles_and_all_clue_types(client):
    data = get(client, "/api/health")
    assert data["ok"] is True
    assert set(data["puzzles"]) == set(LEVEL_IDS)
    assert {"FACT", "SAME", "DIFFERENT", "EXACTLY", "AT_LEAST", "AT_MOST", "PARITY", "COMPARE"} <= set(data["clue_types"])


def test_puzzle_list_shape(client):
    rows = get(client, "/api/puzzles")
    assert {r["id"] for r in rows} == set(LEVEL_IDS)
    for r in rows:
        assert r["characters"] == r["size"] ** 2
        assert r["clues"] >= 1 and r["name"] and r["group"]


def test_load_by_id_and_custom_puzzle(client):
    state = load(client, puzzle=puzzle_basic())
    assert state["puzzle"]["id"] == "T-basic"
    assert state["total"] == 9 and state["steps"] == 0 and state["solved"] is False
    assert [c["cell"] for c in state["characters"]] == ["A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"]
    assert get(client, "/api/game/state")["puzzle"]["id"] == "T-basic"
    if LEVEL_IDS:
        assert load(client, puzzle_id=LEVEL_IDS[0])["puzzle"]["id"] == LEVEL_IDS[0]


def test_load_errors(client):
    load(client, puzzle=puzzle_basic())
    assert client.post("/api/game/load", json={"puzzle_id": "does-not-exist"}).status_code == 404
    assert client.post("/api/game/load", json={}).status_code == 404
    bad_clue = puzzle_dict([{"owner": "N09", "type": "EXACTLY", "k": 1}])      # missing region
    for bad in ({}, bad_clue, "not an object"):
        assert client.post("/api/game/load", json={"puzzle": bad}).status_code == 422
    # a failed load must not replace the running session
    assert get(client, "/api/game/state")["puzzle"]["id"] == "T-basic"


def test_initially_revealed_characters_are_public(client):
    state = load(client, puzzle=puzzle_basic())
    assert status_of(state, "N09") == INNOCENT
    assert status_of(state, "N01") is None
    assert [c["id"] for c in state["clues"]] == ["c1"]


def test_load_and_restart_populate_kb_stats(client):
    loaded = load(client, puzzle=puzzle_basic())
    for st in (loaded, post(client, "/api/game/restart")):
        kb = st["analysis"]["kb"]
        assert kb["primary_variables"] == 9
        assert kb["auxiliary_variables"] == 0
        assert kb["variables"] == 9
        assert kb["clauses"] > 0
        assert st["analysis"]["sat_calls"] == 0


def test_already_solved_puzzle_populates_kb_stats(client):
    state = load(client, puzzle=puzzle_tiny(initial=["N01", "N02", "N03", "N04"]))
    assert state["solved"] is True
    auto = post(client, "/api/game/auto")
    assert auto["solved"] is True and auto["steps"] == []
    kb = auto["state"]["analysis"]["kb"]
    assert kb["primary_variables"] == 4
    assert kb["clauses"] > 0


# =====================================================================
# B. Verdict contract (hand-made puzzle with a known answer)
# =====================================================================

def test_classify_basic_puzzle(client):
    load(client, puzzle=puzzle_basic())
    data = get(client, "/api/game/classify")["characters"]
    assert data["N01"] == CRIMINAL
    assert data["N09"] == INNOCENT
    assert all(data[name_of(i)] == UNKNOWN for i in range(2, 9))
    kb = get(client, "/api/game/classify")["state"]["analysis"]["kb"]
    assert kb["primary_variables"] == 9 and kb["clauses"] > 0


def test_not_provable_leaves_state_unchanged(client):
    before = load(client, puzzle=puzzle_basic())
    r = post(client, "/api/game/verdict", name="N02", verdict="CRIMINAL")
    assert r["result"] == "NOT_PROVABLE"
    assert public(r["state"]) == public(before)
    assert status_of(r["state"], "N02") is None


def test_contradicted_leaves_state_unchanged_and_hides_clue(client):
    before = load(client, puzzle=puzzle_basic())
    r = post(client, "/api/game/verdict", name="N01", verdict="INNOCENT")
    assert r["result"] == "CONTRADICTED" and r["classification"] == CRIMINAL
    assert public(r["state"]) == public(before)
    assert [c["id"] for c in r["state"]["clues"]] == ["c1"]       # N01's clue c2 still hidden


def test_accepted_verdict_flips_card_and_reveals_clue(client):
    load(client, puzzle=puzzle_basic())
    r = post(client, "/api/game/verdict", name="N01", verdict="CRIMINAL")
    assert r["result"] == "ACCEPTED" and r["clue_id"] == "c2" and r["step"] == 1
    state = r["state"]
    assert status_of(state, "N01") == CRIMINAL and state["steps"] == 1
    assert [c["id"] for c in state["clues"]] == ["c2", "c1"]
    assert state["history"] == [{"step": 1, "name": "N01", "verdict": CRIMINAL, "clue_id": "c2"}]
    # already proved
    assert post(client, "/api/game/verdict", name="N01", verdict="CRIMINAL")["result"] == "ALREADY_KNOWN"


def test_verdict_is_case_insensitive_and_unknown_name_is_reported(client):
    load(client, puzzle=puzzle_basic())
    assert post(client, "/api/game/verdict", name="N01", verdict="criminal")["result"] == "ACCEPTED"
    r = post(client, "/api/game/verdict", name="Nobody", verdict="CRIMINAL")
    assert r["result"] == "INVALID"


def test_trace_records_every_verdict(client):
    load(client, puzzle=puzzle_basic())
    post(client, "/api/game/verdict", name="N02", verdict="CRIMINAL")
    state = post(client, "/api/game/verdict", name="N01", verdict="CRIMINAL")["state"]
    first, second = state["trace"]
    assert (first["character"], first["result"], first["revealed_clue"]) == ("N02", "NOT_PROVABLE", None)
    assert (second["character"], second["result"], second["revealed_clue"]) == ("N01", "ACCEPTED", "c2")
    assert second["step"] == 1 and second["active_clues"] == ["c1"]
    for entry in (first, second):
        assert entry["sat_queries"] >= 1 and len(entry["queries"]) == entry["sat_queries"]
        assert {"assumption", "sat", "decisions", "propagations", "backtracks"} <= set(entry["queries"][0])


def test_restart_equals_fresh_load(client):
    fresh = load(client, puzzle=puzzle_basic())
    post(client, "/api/game/verdict", name="N01", verdict="CRIMINAL")
    restarted = post(client, "/api/game/restart")
    assert public(restarted) == public(fresh)
    assert restarted["trace"] == []


# =====================================================================
# C. Hint / step / auto on special puzzles
# =====================================================================

def test_hint_points_to_forced_character(client):
    load(client, puzzle=puzzle_basic())
    hint = get(client, "/api/game/hint")
    assert hint["available"] and hint["name"] == "N01" and hint["verdict"] == CRIMINAL
    assert hint["cell"] == "A1" and hint["clue_id"] == "c1"
    assert status_of(hint["state"], "N01") is None        # a hint must not reveal anything


def test_step_advances_exactly_one_reveal_then_gets_stuck(client):
    load(client, puzzle=puzzle_basic())
    step = post(client, "/api/game/step")
    assert step["ok"] is True and step["result"] == "ACCEPTED" and step["state"]["steps"] == 1
    again = post(client, "/api/game/step")
    assert again["ok"] is False and again["status"] == "STUCK"
    assert again["state"]["steps"] == 1


def test_stuck_puzzle(client):
    load(client, puzzle=puzzle_stuck())
    hint = get(client, "/api/game/hint")
    assert hint["available"] is False and hint["status"] == "STUCK"
    auto = post(client, "/api/game/auto")
    assert auto["solved"] is False and auto["status"] == "STUCK"
    uniq = get(client, "/api/uniqueness")                  # no id -> the loaded puzzle
    assert uniq["unique"] is False


def test_inconsistent_puzzle(client):
    load(client, puzzle=puzzle_inconsistent())
    classes = get(client, "/api/game/classify")["characters"]
    assert set(classes.values()) == {"INCONSISTENT"}
    assert post(client, "/api/game/verdict", name="N01", verdict="CRIMINAL")["result"] == "INCONSISTENT"
    hint = get(client, "/api/game/hint")
    assert hint["available"] is False and hint["status"] == "INCONSISTENT"
    auto = post(client, "/api/game/auto")
    assert auto["solved"] is False and auto["status"] == "INCONSISTENT"
    uniq = get(client, "/api/uniqueness")
    assert uniq["unique"] is False and uniq["reason"] == "INCONSISTENT"


def test_tiny_puzzle_solves_in_row_major_order(client):
    load(client, puzzle=puzzle_tiny(initial=["N04", "N03"]))
    auto = post(client, "/api/game/auto")
    assert auto["solved"] is True and auto["status"] == "SOLVED" and len(auto["steps"]) == 2
    history = auto["state"]["history"]
    assert [(h["name"], h["verdict"]) for h in history] == [("N01", CRIMINAL), ("N02", INNOCENT)]
    # after solving: nothing left to do
    assert get(client, "/api/game/hint")["status"] == "SOLVED"
    assert post(client, "/api/game/step")["ok"] is False
    assert post(client, "/api/game/auto")["steps"] == []


def test_unique_puzzle_can_still_get_stuck_by_the_reveal_protocol(client):
    """Uniqueness is about the FULL clue set; progressive reveal can still stall."""
    load(client, puzzle=puzzle_tiny(initial=["N04"]))
    uniq = get(client, "/api/uniqueness")
    assert uniq["unique"] is True and uniq["forced_characters"] == 4
    auto = post(client, "/api/game/auto")
    assert auto["solved"] is False and auto["status"] == "STUCK"
    assert [h["name"] for h in auto["state"]["history"]] == ["N01"]


# =====================================================================
# D. Every shipped level
# =====================================================================

@pytest.mark.parametrize("level_id", LEVEL_IDS, ids=_ids(LEVEL_IDS))
def test_level_hidden_solution_satisfies_all_clues(level_id):
    puzzle = main.LEVELS[level_id]
    assert all(clue_is_true(c, puzzle.solution, puzzle) for c in puzzle.clues)


@pytest.mark.parametrize("level_id", SMALL_IDS, ids=_ids(SMALL_IDS))
def test_level_has_exactly_one_solution_by_brute_force(level_id):
    puzzle = main.LEVELS[level_id]
    found = count_solutions(puzzle)
    assert len(found) == 1
    assert found[0] == puzzle.solution


@pytest.mark.parametrize("level_id", LEVEL_IDS, ids=_ids(LEVEL_IDS))
def test_uniqueness_endpoint_accepts_level(client, level_id):
    data = get(client, f"/api/uniqueness?puzzle_id={level_id}")
    assert data["unique"] is True
    assert data["forced_characters"] == data["characters"] == main.LEVELS[level_id].size ** 2


@pytest.mark.parametrize("level_id", LEVEL_IDS, ids=_ids(LEVEL_IDS))
def test_auto_solve_reaches_hidden_solution(client, level_id):
    puzzle = main.LEVELS[level_id]
    load(client, puzzle_id=level_id)
    result = post(client, "/api/game/auto")
    assert result["solved"] is True and result["status"] == "SOLVED"
    assert all(s["ok"] and s["result"] == "ACCEPTED" for s in result["steps"])
    state = result["state"]
    for ch in state["characters"]:
        assert ch["status"] == (CRIMINAL if puzzle.solution[ch["name"]] else INNOCENT)
    history = state["history"]
    assert [h["step"] for h in history] == list(range(1, len(history) + 1))
    assert all(h["verdict"] == (CRIMINAL if puzzle.solution[h["name"]] else INNOCENT) for h in history)
    assert len(history) == state["total"] - len(puzzle.initial_revealed)


@pytest.mark.parametrize("level_id", SMALL_IDS, ids=_ids(SMALL_IDS))
def test_auto_solve_is_deterministic(client, level_id):
    load(client, puzzle_id=level_id)
    first = post(client, "/api/game/auto")["state"]["history"]
    load(client, puzzle_id=level_id)
    second = post(client, "/api/game/auto")["state"]["history"]
    assert first == second


@pytest.mark.parametrize("level_id", SMALL_IDS, ids=_ids(SMALL_IDS))
def test_agent_matches_brute_force_entailment_at_every_step(client, level_id):
    """The key test: at every step, CRIMINAL/INNOCENT/UNKNOWN == what all models of KB_t say."""
    puzzle = main.LEVELS[level_id]
    state = load(client, puzzle_id=level_id)
    for _ in range(puzzle.size ** 2 + 1):
        clue_ids, proved = public_kb(state)
        expected = oracle_classification(puzzle, clue_ids, proved)
        got = get(client, "/api/game/classify")["characters"]
        assert got == expected, f"step {state['steps']}"
        for name, verdict in got.items():                    # never contradicts the hidden truth
            if verdict in FORCED:
                assert (verdict == CRIMINAL) == puzzle.solution[name]
        forced = [c["name"] for c in state["characters"] if c["status"] is None and got[c["name"]] in FORCED]
        hint = get(client, "/api/game/hint")
        if not forced:
            assert hint["available"] is False
            break
        assert hint["available"] and hint["name"] == forced[0]           # row-major tie-break
        assert hint["verdict"] == got[forced[0]]
        assert hint["clue_id"] in clue_ids
        step = post(client, "/api/game/step")
        assert step["ok"] and step["result"] == "ACCEPTED"
        state = step["state"]
    assert state["solved"]


@pytest.mark.parametrize("level_id", SMALL_IDS, ids=_ids(SMALL_IDS))
def test_state_never_leaks_hidden_data(client, level_id):
    puzzle = main.LEVELS[level_id]
    state = load(client, puzzle_id=level_id)
    assert_no_leak(puzzle, state)
    # rejected verdicts must not leak either
    classes = get(client, "/api/game/classify")["characters"]
    tried = set()
    for ch in state["characters"]:
        name, kind = ch["name"], classes[ch["name"]]
        if ch["status"] is not None or kind in tried:
            continue
        tried.add(kind)
        if kind == UNKNOWN:
            r = post(client, "/api/game/verdict", name=name, verdict=CRIMINAL)
            assert r["result"] == "NOT_PROVABLE"
        else:
            r = post(client, "/api/game/verdict", name=name, verdict=INNOCENT if kind == CRIMINAL else CRIMINAL)
            assert r["result"] == "CONTRADICTED"
        assert public(r["state"]) == public(state)
        assert_no_leak(puzzle, r["state"])
    while True:
        step = post(client, "/api/game/step")
        if not step["ok"]:
            break
        assert_no_leak(puzzle, step["state"])


@pytest.mark.skipif(not LEVEL_IDS, reason="no levels")
def test_restart_after_play_matches_fresh_level(client):
    fresh = load(client, puzzle_id=LEVEL_IDS[0])
    post(client, "/api/game/step")
    post(client, "/api/game/step")
    restarted = post(client, "/api/game/restart")
    assert public(restarted) == public(fresh)
    assert restarted["trace"] == []


# =====================================================================
# E. Benchmark
# =====================================================================

BENCH_IDS = SMALL_IDS[:2]


@pytest.mark.skipif(not BENCH_IDS, reason="no small levels")
def test_benchmark_rows(client):
    data = post(client, "/api/benchmark", puzzle_ids=BENCH_IDS)["results"]
    assert [r["puzzle_id"] for r in data] == BENCH_IDS
    for row in data:
        puzzle = main.LEVELS[row["puzzle_id"]]
        assert row["size"] == puzzle.size and row["solved"] is True and row["status"] == "SOLVED"
        assert row["unique"] is True
        assert row["primary_variables"] == puzzle.size ** 2
        assert row["auxiliary_variables"] >= 0 and row["clauses"] > 0
        for key in ("sat_calls", "decisions", "propagations", "backtracks", "runtime_ms", "uniqueness_ms"):
            assert row[key] >= 0, key
        assert row["sat_calls"] >= 1
        load(client, puzzle_id=row["puzzle_id"])
        assert row["steps"] == len(post(client, "/api/game/auto")["steps"])


@pytest.mark.skipif(not BENCH_IDS, reason="no small levels")
def test_benchmark_does_not_touch_the_current_session(client):
    load(client, puzzle=puzzle_basic())
    post(client, "/api/game/verdict", name="N01", verdict=CRIMINAL)
    before = public(get(client, "/api/game/state"))
    post(client, "/api/benchmark", puzzle_ids=BENCH_IDS)
    assert public(get(client, "/api/game/state")) == before


def test_benchmark_unknown_id_is_404(client):
    assert client.post("/api/benchmark", json={"puzzle_ids": ["does-not-exist"]}).status_code == 404


# =====================================================================
# F. Known defects (expected to fail until the code is fixed; strict -> tells you when fixed)
# =====================================================================

@pytest.mark.xfail(strict=True, reason="agent.relevant_clue: wrong literal (-wanted) and inverted SAT check")
def test_hint_clue_id_is_a_clue_that_is_actually_needed(client):
    load(client, puzzle=puzzle_hint())
    hint = get(client, "/api/game/hint")
    assert hint["available"] and hint["name"] == "N05" and hint["verdict"] == CRIMINAL
    assert hint["cell"] == "B2"
    assert hint["clue_id"] == "c_fact"          # c_same is irrelevant to N05


@pytest.mark.xfail(strict=True, reason="invalid verdict string raises ValueError -> HTTP 500")
def test_invalid_verdict_string_is_a_client_error(client, lenient):
    load(client, puzzle=puzzle_basic())
    r = lenient.post("/api/game/verdict", json={"name": "N01", "verdict": "MAYBE"})
    assert 400 <= r.status_code < 500