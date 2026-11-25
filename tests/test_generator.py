"""Level generator (random_levels) and the /api/generate endpoint.

Generation is the slowest part of the suite. Run only these with:  pytest tests/test_generator.py -v
"""
import json
from itertools import product

import pytest
from fastapi.testclient import TestClient

import main
from griductive import GameSession, Puzzle
from griductive.model import clue_is_true
from random_levels import generate_level, load_config
from random_levels.generator import DEFAULT_CONFIG

CRIMINAL = "CRIMINAL"
CASES = [(3, "easy"), (3, "medium"), (3, "hard"), (4, "easy"), (4, "medium")]


def count_solutions(puzzle):
    """Brute force: assignments that match the face-up statuses and satisfy every clue."""
    initial = {n: puzzle.solution[n] for n in puzzle.initial_revealed}
    found = 0
    for bits in product((False, True), repeat=len(puzzle.names)):
        assignment = dict(zip(puzzle.names, bits))
        if any(assignment[n] != v for n, v in initial.items()):
            continue
        if all(clue_is_true(c, assignment, puzzle) for c in puzzle.clues):
            found += 1
    return found


def write_config(tmp_path, mutate):
    data = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "tiers.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------- generated levels

@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("size,difficulty", CASES)
def test_generated_level_is_valid_true_unique_and_solvable(size, difficulty, seed):
    level = generate_level(seed, size, difficulty)
    puzzle = Puzzle.from_dict(level)
    total = size * size
    assert level["id"] == f"GEN-{size}x{size}-{difficulty}-{seed}"
    assert len(level["characters"]) == total
    assert [c["id"] for c in level["clues"]] == [f"c{i + 1}" for i in range(total)]
    assert sorted(c["owner"] for c in level["clues"]) == sorted(puzzle.names)      # one clue per character
    assert all(clue_is_true(c, puzzle.solution, puzzle) for c in puzzle.clues)      # every clue is true
    assert count_solutions(puzzle) == 1                                              # exactly one solution
    assert GameSession(puzzle).auto_solve()["solved"] is True                        # solvable without guessing


def test_face_up_cards_follow_the_tier():
    expected = {"easy": 3, "medium": 2, "hard": 1}      # 3x3 with the default tiers.json
    for difficulty, count in expected.items():
        assert len(generate_level(3, 3, difficulty)["initial_revealed"]) == count


def test_same_inputs_give_the_same_level():
    assert generate_level(7, 3, "medium") == generate_level(7, 3, "medium")
    assert generate_level("7", 3, "medium") == generate_level(7, 3, "medium")      # int and text seeds agree


def test_different_seeds_give_different_levels():
    first, second = generate_level(1, 3, "easy"), generate_level(2, 3, "easy")
    assert (first["solution"], first["clues"]) != (second["solution"], second["clues"])


def test_meta_block():
    meta = generate_level(3, 3, "hard")["meta"]
    assert meta["seed"] == "3" and meta["difficulty"] == "hard" and meta["attempts"] >= 1
    assert meta["avg_frontier"] >= 1 and meta["score"] > 0
    assert meta["solve"]["steps"] == 8                   # 9 characters, one face-up
    assert sum(meta["clue_types"].values()) == 9


# ---------------------------------------------------------------- name pool and config

def test_names_come_from_the_pool_and_extra_fields_are_kept(tmp_path):
    pool = {f"Person{i}": {"occupation": f"Job{i}", "portrait": f"p{i}.png"} for i in range(9)}
    path = tmp_path / "names.json"
    path.write_text(json.dumps(pool), encoding="utf-8")
    level = generate_level(1, 3, "easy", names_path=path)
    for character in level["characters"]:
        assert character["name"] in pool
        assert character["job"] == pool[character["name"]]["occupation"]
        assert character["portrait"] == pool[character["name"]]["portrait"]
    Puzzle.from_dict(level)                              # the game still loads it


def test_pool_smaller_than_the_grid_is_rejected(tmp_path):
    path = tmp_path / "names.json"
    path.write_text(json.dumps({"A": {"occupation": "x"}, "B": {"occupation": "y"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        generate_level(1, 3, "easy", names_path=path)


def test_weights_decide_which_clue_types_are_used(tmp_path):
    path = write_config(tmp_path, lambda d: d["tiers"]["easy"].update({"types": {"FACT": 1, "EXACTLY": 3}}))
    for seed in (1, 2, 3):
        level = generate_level(seed, 3, "easy", config_path=path)
        assert {c["type"] for c in level["clues"]} <= {"FACT", "EXACTLY"}
        assert level["meta"]["tier"]["types"] == {"FACT": 1, "EXACTLY": 3}


BAD_CONFIGS = [
    lambda d: d["tiers"]["easy"]["types"].update({"NOPE": 1}),                               # unknown clue type
    lambda d: d["tiers"]["easy"]["types"].update({"FACT": -1}),                              # negative weight
    lambda d: d["tiers"]["easy"]["types"].update({k: 0 for k in d["tiers"]["easy"]["types"]}),   # all zero
    lambda d: d["tiers"]["easy"]["regions"].update({"spiral": 1}),                           # unknown region
    lambda d: d["tiers"]["easy"].update({"frontier_capp": 1}),                               # typo in a key
    lambda d: d["tiers"]["easy"].update({"frontier_cap": 0}),
    lambda d: d["tiers"]["easy"].update({"initial_share": 2}),
    lambda d: d.update({"density": [0.9, 0.1]}),
    lambda d: d.update({"surprise": 1}),                                                     # unknown top-level key
    lambda d: d.update({"tiers": {}}),
]


@pytest.mark.parametrize("mutate", BAD_CONFIGS, ids=[str(i) for i in range(len(BAD_CONFIGS))])
def test_invalid_config_is_rejected(tmp_path, mutate):
    with pytest.raises(ValueError):
        load_config(write_config(tmp_path, mutate))


def test_default_config_loads():
    config = load_config()
    assert {"easy", "medium", "hard"} <= set(config["tiers"])


def test_bad_arguments_are_rejected():
    with pytest.raises(ValueError):
        generate_level(1, 6, "easy")
    with pytest.raises(ValueError):
        generate_level(1, 3, "does-not-exist")


# ---------------------------------------------------------------- HTTP endpoint

@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def test_generate_endpoint_returns_a_loadable_level(client):
    response = client.post("/api/generate", json={"seed": 5, "size": 3, "difficulty": "easy"})
    assert response.status_code == 200
    level = response.json()["level"]
    assert level == generate_level(5, 3, "easy")                    # same level as calling the generator directly
    loaded = client.post("/api/game/load", json={"puzzle": level})
    assert loaded.status_code == 200 and loaded.json()["puzzle"]["id"] == "GEN-3x3-easy-5"
    assert client.post("/api/game/auto").json()["solved"] is True


def test_generate_endpoint_picks_a_seed_when_none_is_given(client):
    for body in ({"size": 3, "difficulty": "easy"}, {"seed": "", "size": 3, "difficulty": "easy"}):
        response = client.post("/api/generate", json=body)
        assert response.status_code == 200
        level = response.json()["level"]
        assert level["meta"]["seed"] and level["id"].endswith(level["meta"]["seed"])


def test_generate_endpoint_rejects_bad_input(client):
    assert client.post("/api/generate", json={"seed": 1, "size": 9, "difficulty": "easy"}).status_code == 422
    assert client.post("/api/generate", json={"seed": 1, "size": 3, "difficulty": "nope"}).status_code == 422


def test_generate_options_lists_sizes_and_difficulties(client):
    data = client.get("/api/generate/options").json()
    assert data["sizes"] == [3, 4, 5]
    assert {"easy", "medium", "hard"} <= set(data["difficulties"])