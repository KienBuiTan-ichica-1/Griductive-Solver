"""Seeded Griductive level generator.

Idea: simulate the reveal protocol forward. Pick a hidden solution, then for every
character that gets proved, give it a TRUE clue that (together with everything already
public) forces at least one more unsolved character. Every character is therefore forced
at its reveal time, so the full clue set has exactly one solution and the no-guess agent
can always make progress. Output is a level dict in the same format as levels/G01.json.

All tuning (clue/region weights, frontier cap, face-up share, ...) lives in tiers.json.

Run directly:   python -m random_levels --seed 42 --size 4 --difficulty hard
"""
from __future__ import annotations

import argparse
import json
import operator
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from griductive import Clue, DPLLSolver, GameSession, Puzzle, build_knowledge_base, check_uniqueness  # noqa: E402
from griductive.model import (  # noqa: E402
    _region_names, bool_to_status, clue_is_true, col_letter, format_cell, parse_cell, validate_clue,
)

DEFAULT_NAMES = Path(__file__).with_name("names.json")
DEFAULT_CONFIG = Path(__file__).with_name("tiers.json")

COMPARE_FNS = {
    "<": operator.lt, "<=": operator.le, "=": operator.eq,
    "!=": operator.ne, ">": operator.gt, ">=": operator.ge,
}
CLUE_TYPES = ("FACT", "SAME", "DIFFERENT", "EXACTLY", "AT_LEAST", "AT_MOST", "PARITY", "COMPARE")
REGION_KINDS = ("row", "col", "neighbors", "cells", "boundary", "corners",
                "between", "common_neighbors", "intersection")
DEFAULT_TYPE_SCORE = {"FACT": 1.0, "SAME": 1.5, "DIFFERENT": 1.5, "EXACTLY": 2.0,
                      "AT_LEAST": 2.5, "AT_MOST": 2.5, "PARITY": 3.5, "COMPARE": 4.0}
TOP_KEYS = {"density", "tries_per_clue", "relax_after", "type_score", "tiers"}
TIER_KEYS = {"types", "regions", "frontier_cap", "initial_share"}


class GenerationError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- config

def _check_keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: expected an object")
    for key in obj:
        if key not in allowed and not key.startswith("_"):
            raise ValueError(f"{where}: unknown key '{key}' (allowed: {', '.join(sorted(allowed))})")


def _weights(table, allowed, where):
    if not isinstance(table, dict) or not table:
        raise ValueError(f"{where}: expected a non-empty object of weights")
    out = {}
    for key, value in table.items():
        if key.startswith("_"):
            continue
        if key not in allowed:
            raise ValueError(f"{where}: unknown '{key}' (allowed: {', '.join(allowed)})")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{where}.{key}: weight must be a number >= 0")
        out[key] = value
    if not any(out.values()):
        raise ValueError(f"{where}: at least one weight must be above 0")
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Read and validate tiers.json (or another file with the same structure)."""
    data = json.loads(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8"))
    _check_keys(data, TOP_KEYS, "config")

    density = data.get("density", [0.35, 0.55])
    if not (isinstance(density, list) and len(density) == 2 and 0 < density[0] <= density[1] < 1):
        raise ValueError("density must be [low, high] with 0 < low <= high < 1")
    type_score = dict(DEFAULT_TYPE_SCORE)
    type_score.update(_weights(data.get("type_score", DEFAULT_TYPE_SCORE), CLUE_TYPES, "type_score"))

    config = {
        "density": [float(density[0]), float(density[1])],
        "tries_per_clue": int(data.get("tries_per_clue", 300)),
        "relax_after": int(data.get("relax_after", 100)),
        "type_score": type_score,
        "tiers": {},
    }
    if config["tries_per_clue"] < 1 or config["relax_after"] < 0:
        raise ValueError("tries_per_clue must be >= 1 and relax_after >= 0")

    tiers = data.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise ValueError("config needs a non-empty 'tiers' object")
    for name, spec in tiers.items():
        if name.startswith("_"):
            continue
        where = f"tiers.{name}"
        _check_keys(spec, TIER_KEYS, where)
        cap = spec.get("frontier_cap")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
            raise ValueError(f"{where}.frontier_cap must be null or an integer >= 1")
        share = spec.get("initial_share", 0.2)
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 1:
            raise ValueError(f"{where}.initial_share must be a number between 0 and 1")
        config["tiers"][name] = {
            "types": _weights(spec.get("types"), CLUE_TYPES, f"{where}.types"),
            "regions": _weights(spec.get("regions"), REGION_KINDS, f"{where}.regions"),
            "frontier_cap": cap,
            "initial_share": float(share),
        }
    if not config["tiers"]:
        raise ValueError("config defines no tiers")
    return config


# ----------------------------------------------------------------------------- names

def load_pool(path: str | Path | None = None) -> list[dict]:
    """Read the character pool. Format: {"Abel": {"occupation": "Painter", ...extra fields}, ...}.
    A list of {"name": ..., "occupation": ...} objects (or plain strings) also works. Each entry
    becomes {"name", "job", **extras}; extra fields are copied into the generated level as-is."""
    data = json.loads(Path(path or DEFAULT_NAMES).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = [{**(info if isinstance(info, dict) else {}), "name": name} for name, info in data.items()]
    elif isinstance(data, list):
        items = [{"name": x} if isinstance(x, str) else dict(x) for x in data]
    else:
        raise ValueError("names file must be an object or a list")
    pool: list[dict] = []
    for item in items:
        if "name" not in item:
            raise ValueError(f"character without a name: {item!r}")
        name = str(item.pop("name"))
        job = ""
        for key in ("occupation", "job", "profession"):
            value = item.pop(key, None)
            job = job or (str(value) if value else "")
        pool.append({"name": name, "job": job or "Worker", **item})
    if len({p["name"] for p in pool}) != len(pool):
        raise ValueError("names list contains duplicates")
    return pool


# ----------------------------------------------------------------------------- regions

def sample_region(rng: random.Random, n: int, weights: dict[str, float]) -> dict | None:
    kinds = list(weights)
    kind = rng.choices(kinds, [weights[k] for k in kinds])[0]
    cells = [format_cell(r, c) for r in range(1, n + 1) for c in range(n)]
    if kind == "row":
        return {"kind": "row", "row": rng.randint(1, n)}
    if kind == "col":
        return {"kind": "col", "col": col_letter(rng.randrange(n))}
    if kind == "neighbors":
        return {"kind": "neighbors", "cell": rng.choice(cells)}
    if kind == "cells":
        picked = rng.sample(cells, rng.randint(2, min(5, len(cells))))
        return {"kind": "cells", "cells": sorted(picked, key=parse_cell)}
    if kind == "boundary":
        return {"kind": "boundary"}
    if kind == "corners":
        return {"kind": "corners"}
    if kind == "between":
        if n < 3:
            return None
        row, col = rng.randint(1, n), rng.randrange(n)
        d_row, d_col = rng.choice([(0, 1), (1, 0), (1, 1), (1, -1), (0, -1), (-1, 0), (-1, -1), (-1, 1)])
        gap = rng.randint(2, n - 1)
        row2, col2 = row + d_row * gap, col + d_col * gap
        if not (1 <= row2 <= n and 0 <= col2 < n):
            return None
        return {"kind": "between", "a": format_cell(row, col), "b": format_cell(row2, col2)}
    if kind == "common_neighbors":
        a, b = rng.sample(cells, 2)
        return {"kind": "common_neighbors", "a": a, "b": b}
    if kind == "intersection":
        first = rng.choice([{"kind": "row", "row": rng.randint(1, n)},
                            {"kind": "neighbors", "cell": rng.choice(cells)}])
        second = rng.choice([{"kind": "col", "col": col_letter(rng.randrange(n))},
                             {"kind": "neighbors", "cell": rng.choice(cells)}])
        return {"kind": "intersection", "regions": [first, second]}
    return None


# ----------------------------------------------------------------------------- clues

def candidate(rng, tier, base, truth, proved, need_unsolved):
    """One random clue spec (dict with 'type') that is TRUE under `truth`, or None."""
    kinds = list(tier["types"])
    kind = rng.choices(kinds, [tier["types"][k] for k in kinds])[0]
    names = base.names
    unsolved = [n for n in names if n not in proved]

    if kind == "FACT":
        person = rng.choice(unsolved if (need_unsolved and unsolved) else names)
        return {"type": "FACT", "person": person, "status": bool_to_status(truth[person])}

    if kind in ("SAME", "DIFFERENT"):
        for _ in range(8):
            a, b = rng.sample(names, 2)
            if need_unsolved and a in proved and b in proved:
                continue
            if (truth[a] == truth[b]) == (kind == "SAME"):
                return {"type": kind, "a": a, "b": b}
        return None

    def region():
        for _ in range(10):
            spec = sample_region(rng, base.size, tier["regions"])
            if spec is None:
                continue
            try:
                members = _region_names(spec, base)
            except (ValueError, KeyError):
                continue
            if not need_unsolved or any(m not in proved for m in members):
                return spec, members
        return None, None

    spec, members = region()
    if spec is None:
        return None
    count = sum(truth[m] for m in members)
    size = len(members)
    if kind == "EXACTLY":
        return {"type": kind, "region": spec, "k": count}
    if kind == "AT_LEAST":
        if count < 1:
            return None
        return {"type": kind, "region": spec, "k": count - rng.randint(0, count - 1)}
    if kind == "AT_MOST":
        if count >= size:
            return None
        return {"type": kind, "region": spec, "k": count + rng.randint(0, size - count - 1)}
    if kind == "PARITY":
        return {"type": kind, "region": spec, "parity": "even" if count % 2 == 0 else "odd"}

    # COMPARE
    spec2, members2 = region()
    if spec2 is None or spec2 == spec or set(members) == set(members2):
        return None
    right = sum(truth[m] for m in members2)
    true_ops = [op for op, fn in COMPARE_FNS.items() if fn(count, right)]
    strict = [op for op in true_ops if op in ("<", ">", "=")]
    return {"type": "COMPARE", "left": spec, "right": spec2, "op": rng.choice(strict or true_ops)}


def forced_unsolved(base, clues, proved, truth, cap=None):
    """Unsolved characters forced by the public KB. The hidden solution is a model of the KB,
    so a character is forced iff 'KB and (value != its true value)' is UNSAT: one SAT call each."""
    kb = build_knowledge_base(base, clues, proved)
    forced: list[str] = []
    for name in base.names:
        if name in proved:
            continue
        var = kb.name_to_var[name]
        sat, _ = DPLLSolver(kb).solve([-var if truth[name] else var])
        if not sat:
            forced.append(name)
            if cap is not None and len(forced) > cap:
                break
    return forced


def pick_clue(rng, tier, base, owner, clues, proved, truth, seen, frontier, need_unsolved=True, floor=0):
    """Find a true clue for `owner`. With frontier=True the clue must leave at least one (and, per
    the tier, at most `cap`) unsolved character forced. Returns (clue, forced_list) or (None, [])."""
    cap = tier["frontier_cap"]
    if cap is not None:
        cap = max(cap, floor)       # characters already forced before this clue do not count against it
    for attempt in range(tier["tries_per_clue"]):
        spec = candidate(rng, tier, base, truth, proved, need_unsolved)
        if spec is None:
            continue
        key = json.dumps(spec, sort_keys=True)
        if key in seen:
            continue
        clue = Clue("tmp", owner, spec["type"], {k: v for k, v in spec.items() if k != "type"})
        try:
            validate_clue(clue, base)
        except (ValueError, KeyError):
            continue
        if not clue_is_true(clue, truth, base):
            continue
        if not frontier:
            seen.add(key)
            return clue, []
        active_cap = cap if attempt < tier["relax_after"] else None
        forced = forced_unsolved(base, clues + [clue], proved, truth, active_cap)
        if forced and (active_cap is None or len(forced) <= active_cap):
            seen.add(key)
            return clue, forced
    return None, []


# ----------------------------------------------------------------------------- one attempt

def _attempt(rng, tier, n, pool, initial_count):
    total = n * n
    cells = [format_cell(r, c) for r in range(1, n + 1) for c in range(n)]
    picked = rng.sample(pool, total)             # every pool entry carries its own occupation (+ extras)
    chosen = [p["name"] for p in picked]
    characters = [{"cell": cells[i], **picked[i]} for i in range(total)]

    low = max(1, round(total * tier["density"][0]))
    high = min(total - 1, round(total * tier["density"][1]))
    criminals = rng.randint(low, max(low, high))
    flags = [True] * criminals + [False] * (total - criminals)
    rng.shuffle(flags)
    truth = {chosen[i]: flags[i] for i in range(total)}

    base = Puzzle.from_dict({
        "id": "base", "size": n, "characters": characters, "clues": [],
        "solution": {k: bool_to_status(v) for k, v in truth.items()}, "initial_revealed": [],
    })

    def row_major(names):
        return sorted(names, key=lambda x: parse_cell(base.name_to_cell[x]))

    initial = row_major(rng.sample(base.names, initial_count))
    proved = {name: truth[name] for name in initial}
    clues: list[Clue] = []
    seen: set[str] = set()
    frontier: list[str] = []

    for index, owner in enumerate(initial):
        last = index == len(initial) - 1
        clue, forced = pick_clue(rng, tier, base, owner, clues, proved, truth, seen, frontier=last)
        if clue is None:
            return None
        clues.append(clue)
        frontier = forced
    frontier_sizes = [len(frontier)]

    while True:
        nxt = row_major(frontier)[0]                 # same tie-break as the LogicAgent
        floor = len(frontier) - 1
        proved[nxt] = truth[nxt]
        done = len(proved) == total
        clue, forced = pick_clue(rng, tier, base, nxt, clues, proved, truth, seen,
                                 frontier=not done, need_unsolved=not done, floor=floor)
        if clue is None:
            return None
        clues.append(clue)
        if done:
            break
        frontier = forced
        frontier_sizes.append(len(frontier))

    ordered = sorted(clues, key=lambda c: parse_cell(base.name_to_cell[c.owner]))
    clue_dicts = [Clue(f"c{i + 1}", c.owner, c.type, c.params).to_dict() for i, c in enumerate(ordered)]
    level = {
        "characters": characters,
        "clues": clue_dicts,
        "solution": {c["name"]: bool_to_status(truth[c["name"]]) for c in characters},
        "initial_revealed": initial,
    }
    return level, frontier_sizes


# ----------------------------------------------------------------------------- public API

def generate_level(seed, size: int = 3, difficulty: str = "easy", initial: int | None = None,
                   names_path: str | Path | None = None, max_attempts: int = 50,
                   config_path: str | Path | None = None) -> dict:
    """Deterministic: same arguments (and same tiers.json) -> same level. `seed` may be an int or
    any string."""
    if size not in (3, 4, 5):
        raise ValueError("size must be 3, 4 or 5")
    config = load_config(config_path)
    if difficulty not in config["tiers"]:
        raise ValueError(f"difficulty must be one of {list(config['tiers'])}")
    tier_config = config["tiers"][difficulty]
    tier = {**tier_config, "density": config["density"],
            "tries_per_clue": config["tries_per_clue"], "relax_after": config["relax_after"]}
    pool = load_pool(names_path)
    total = size * size
    if len(pool) < total:
        raise ValueError(f"names list needs at least {total} names, found {len(pool)}")
    count = initial if initial is not None else max(1, round(total * tier["initial_share"]))
    count = max(1, min(count, total - 1))

    for attempt in range(1, max_attempts + 1):
        rng = random.Random(f"griductive|{seed}|{size}|{difficulty}|{count}|{attempt}")
        built = _attempt(rng, tier, size, pool, count)
        if built is None:
            continue
        body, frontier_sizes = built
        level = {
            "id": f"GEN-{size}x{size}-{difficulty}-{seed}",
            "name": f"Generated {size}x{size} {difficulty} #{seed}",
            "group": f"{size}x{size}",
            "size": size,
            "desc": f"{size} x {size} generated Griductive puzzle ({difficulty}), seed {seed}.",
            **body,
        }
        stats = _verify(level)
        if stats is None:
            continue
        types: dict[str, int] = {}
        for clue in level["clues"]:
            types[clue["type"]] = types.get(clue["type"], 0) + 1
        avg_weight = sum(config["type_score"][t] * k for t, k in types.items()) / len(level["clues"])
        avg_frontier = sum(frontier_sizes) / len(frontier_sizes)
        level["meta"] = {
            "seed": str(seed), "difficulty": difficulty, "attempts": attempt,
            "score": round(avg_weight + 2 / avg_frontier + stats["decisions"] / max(1, stats["steps"]), 2),
            "avg_frontier": round(avg_frontier, 2),
            "clue_types": dict(sorted(types.items())),
            "solve": stats,
            "tier": tier_config,          # the settings used, so the level can be reproduced
        }
        return level
    raise GenerationError(f"no valid level after {max_attempts} attempts "
                          f"(seed={seed}, size={size}, difficulty={difficulty})")


def _verify(level: dict) -> dict | None:
    """Independent check with the real engine: valid, unique, and solvable by the no-guess agent."""
    try:
        puzzle = Puzzle.from_dict(level)
    except (ValueError, KeyError, TypeError):
        return None
    if not check_uniqueness(puzzle)["unique"]:
        return None
    session = GameSession(puzzle)
    result = session.auto_solve()
    if not result["solved"]:
        return None
    analysis = session.state()["analysis"]
    return {
        "steps": len(result["steps"]), "sat_calls": analysis["sat_calls"],
        "decisions": analysis["decisions"], "propagations": analysis["propagations"],
        "backtracks": analysis["backtracks"],
    }


# ----------------------------------------------------------------------------- command line

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m random_levels",
                                     description="Generate a solvable, unique Griductive level from a seed.")
    parser.add_argument("--seed", help="any integer or string (default: random, printed to stderr)")
    parser.add_argument("--size", type=int, default=3, choices=[3, 4, 5])
    parser.add_argument("--difficulty", default="easy", help="a tier name from the config (default: easy)")
    parser.add_argument("--initial", type=int, help="number of face-up cards at the start")
    parser.add_argument("--names", help="JSON file with the character pool (default: names.json)")
    parser.add_argument("--config", help="JSON file with tier settings (default: tiers.json)")
    parser.add_argument("--max-attempts", type=int, default=50)
    parser.add_argument("-o", "--output", help="write the level to this file instead of stdout")
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else str(random.SystemRandom().randrange(10 ** 6))
    try:
        level = generate_level(seed, args.size, args.difficulty, args.initial, args.names,
                               args.max_attempts, args.config)
    except (GenerationError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    text = json.dumps(level, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    meta = level["meta"]
    print(f"{level['id']}  attempts={meta['attempts']}  score={meta['score']}  "
          f"avg_frontier={meta['avg_frontier']}  steps={meta['solve']['steps']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())