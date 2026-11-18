"""Run experiments on every bundled puzzle and write results/benchmark.*."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from griductive import GameSession, Puzzle, check_uniqueness  # noqa: E402

FIELDS = [
    "puzzle_id", "size", "solved", "status", "steps", "primary_variables",
    "auxiliary_variables", "clauses", "sat_calls", "decisions", "propagations",
    "backtracks", "runtime_ms", "unique", "uniqueness_ms",
]


def load_puzzles() -> dict[str, Puzzle]:
    puzzles: dict[str, Puzzle] = {}
    for path in sorted((ROOT / "levels").glob("*.json")):
        puzzle = Puzzle.from_dict(json.loads(path.read_text(encoding="utf-8")))
        puzzles[puzzle.id] = puzzle
    return puzzles


def run_one(puzzle: Puzzle) -> dict:
    session = GameSession(puzzle)
    result = session.auto_solve()
    analysis = session.state()["analysis"]
    uniqueness = check_uniqueness(puzzle)
    return {
        "puzzle_id": puzzle.id,
        "size": puzzle.size,
        "solved": result["solved"],
        "status": result["status"],
        "steps": len(result["steps"]),
        "primary_variables": analysis["kb"]["primary_variables"],
        "auxiliary_variables": analysis["kb"]["auxiliary_variables"],
        "clauses": analysis["kb"]["clauses"],
        "sat_calls": analysis["sat_calls"],
        "decisions": analysis["decisions"],
        "propagations": analysis["propagations"],
        "backtracks": analysis["backtracks"],
        "runtime_ms": analysis["runtime_ms"],
        "unique": uniqueness["unique"],
        "uniqueness_ms": uniqueness["time_ms"],
    }


def main() -> None:
    results = [run_one(puzzle) for puzzle in load_puzzles().values()]
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "benchmark.json").write_text(
        json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8"
    )
    with (out / "benchmark.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    for row in results:
        print(f"{row['puzzle_id']} {row['size']}x{row['size']}: "
              f"solved={row['solved']} steps={row['steps']} "
              f"vars={row['primary_variables']}+{row['auxiliary_variables']} "
              f"clauses={row['clauses']} sat_calls={row['sat_calls']} "
              f"ms={row['runtime_ms']:.2f} unique={row['unique']}")


if __name__ == "__main__":
    main()
