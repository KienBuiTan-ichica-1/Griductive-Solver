"""FastAPI backend for the Griductive solver. Chay: python main.py (hoac uvicorn main:app --reload)."""
import json
import threading
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from griductive import GameSession, Puzzle, check_uniqueness

ROOT = Path(__file__).parent
LEVELS: dict[str, Puzzle] = {}
for path in sorted((ROOT / "levels").glob("*.json")):
    try:
        puzzle = Puzzle.from_dict(json.loads(path.read_text(encoding="utf-8")))
        LEVELS[puzzle.id] = puzzle
    except (ValueError, KeyError, TypeError) as error:
        print(f"Skipping {path.name}: {error}")

LOCK = threading.Lock()
SESSION = GameSession(LEVELS[next(iter(LEVELS))]) if LEVELS else None

app = FastAPI(title="Griductive Solver API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class LoadRequest(BaseModel):
    puzzle_id: Optional[str] = None
    puzzle: Optional[dict] = None


class VerdictRequest(BaseModel):
    name: str
    verdict: str


class BenchmarkRequest(BaseModel):
    puzzle_ids: Optional[List[str]] = None


def _session() -> GameSession:
    if SESSION is None:
        raise HTTPException(503, "No puzzle is available")
    return SESSION


def _puzzle(puzzle_id: Optional[str]) -> Puzzle:
    if puzzle_id in LEVELS:
        return LEVELS[puzzle_id]
    raise HTTPException(404, f"Khong tim thay puzzle: {puzzle_id}")


@app.get("/api/health")
def health():
    return {"ok": True, "puzzles": list(LEVELS), "clue_types": [
        "FACT", "SAME", "DIFFERENT", "EXACTLY", "AT_LEAST", "AT_MOST", "PARITY", "COMPARE",
    ]}


@app.get("/api/puzzles")
def list_puzzles():
    return [
        {
            "id": p.id, "name": p.name, "group": p.group, "size": p.size,
            "desc": p.desc, "characters": len(p.names), "clues": len(p.clues),
        }
        for p in LEVELS.values()
    ]


@app.post("/api/game/load")
def api_load(req: LoadRequest):
    if req.puzzle is not None:
        try:
            puzzle = Puzzle.from_dict(req.puzzle)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            raise HTTPException(422, f"Puzzle khong hop le: {error}")
    else:
        puzzle = _puzzle(req.puzzle_id)
    with LOCK:
        global SESSION
        SESSION = GameSession(puzzle)
        return SESSION.state()


@app.get("/api/game/state")
def api_state():
    with LOCK:
        return _session().state()


@app.post("/api/game/restart")
def api_restart():
    with LOCK:
        session = _session()
        session.restart()
        return session.state()


@app.post("/api/game/verdict")
def api_verdict(req: VerdictRequest):
    verdict = req.verdict.upper()
    if verdict not in ("CRIMINAL", "INNOCENT"):
        raise HTTPException(422, "verdict must be CRIMINAL or INNOCENT")
    with LOCK:
        return _session().verdict(req.name, verdict)


@app.get("/api/game/hint")
def api_hint():
    with LOCK:
        return _session().hint()


@app.get("/api/game/classify")
def api_classify():
    with LOCK:
        return _session().classifications()


@app.post("/api/game/step")
def api_step():
    with LOCK:
        return _session().auto_step()


@app.post("/api/game/auto")
def api_auto():
    with LOCK:
        return _session().auto_solve()


@app.get("/api/uniqueness")
def api_uniqueness(puzzle_id: Optional[str] = None):
    with LOCK:
        session = _session()
        puzzle = _puzzle(puzzle_id) if puzzle_id else session.engine.puzzle
        return check_uniqueness(puzzle)


@app.post("/api/benchmark")
def api_benchmark(req: BenchmarkRequest):
    ids = req.puzzle_ids or list(LEVELS)
    with LOCK:
        results = []
        for puzzle_id in ids:
            puzzle = _puzzle(puzzle_id)
            session = GameSession(puzzle)
            uniqueness = check_uniqueness(puzzle)
            result = session.auto_solve()
            analysis = session.state()["analysis"]
            results.append({
                "puzzle_id": puzzle_id,
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
            })
        return {"results": results}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")

if __name__ == "__main__":
    import uvicorn

    defaultPort = 8000
    setPort = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else defaultPort

    uvicorn.run(app, host="127.0.0.1", port=setPort)
