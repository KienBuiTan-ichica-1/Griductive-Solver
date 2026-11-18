"""Session façade: enforces the no-guess reveal protocol between engine and agent."""
from __future__ import annotations

from typing import Any

from .agent import INCONSISTENT, LogicAgent, check_uniqueness
from .engine import GameEngine
from .model import Puzzle, status_to_bool

ACCEPTED = "ACCEPTED"
NOT_PROVABLE = "NOT_PROVABLE"
CONTRADICTED = "CONTRADICTED"
ALREADY_KNOWN = "ALREADY_KNOWN"


class GameSession:
    def __init__(self, puzzle: Puzzle) -> None:
        self.trace: list[dict[str, Any]] = []
        self.load(puzzle)

    def load(self, puzzle: Puzzle) -> None:
        self.engine = GameEngine(puzzle)
        knowledge = self.engine.public_knowledge()
        self.agent = LogicAgent(knowledge["view"])
        self.agent.update(knowledge["revealed_clues"], knowledge["proved"])
        self.trace = []

    def restart(self) -> None:
        self.load(self.engine.puzzle)

    def _sync_agent(self) -> None:
        knowledge = self.engine.public_knowledge()
        self.agent.update(knowledge["revealed_clues"], knowledge["proved"])

    def verdict(self, name: str, verdict: str) -> dict[str, Any]:
        if name not in self.engine.puzzle.name_to_cell:
            return {"result": "INVALID", "reason": f"unknown character {name!r}", "state": self.state()}
        wanted = status_to_bool(verdict)
        if name in self.engine.proved:
            return {"result": ALREADY_KNOWN, "state": self.state()}

        queries_before = len(self.agent.queries)
        active_clues = [clue.id for clue in self.agent.revealed_clues]
        classification = self.agent.classify(name, force=True)
        if classification == INCONSISTENT:
            outcome = {"result": INCONSISTENT, "classification": classification}
        elif classification == "UNKNOWN":
            outcome = {"result": NOT_PROVABLE, "classification": classification}
        elif classification != ("CRIMINAL" if wanted else "INNOCENT"):
            outcome = {"result": CONTRADICTED, "classification": classification}
        else:
            reveal = self.engine.reveal(name, wanted)
            self._sync_agent()
            outcome = {
                "result": ACCEPTED,
                "classification": classification,
                "clue_id": reveal["clue_id"],
                "step": reveal["step"],
            }

        entry = {
            "action": "verdict",
            "step": self.engine.step_count,
            "character": name,
            "verdict": verdict,
            **outcome,
            "active_clues": active_clues,
            "sat_queries": len(self.agent.queries) - queries_before,
            "queries": self.agent.queries[queries_before:],
            "revealed_clue": outcome.get("clue_id"),
        }
        self.trace.append(entry)
        return {**outcome, "state": self.state()}

    def hint(self) -> dict[str, Any]:
        name = self.agent.forced_next()
        if name is None:
            classifications = self.agent.classify_all()
            status = "INCONSISTENT" if INCONSISTENT in classifications.values() else (
                "SOLVED" if self.engine.is_solved() else "STUCK"
            )
            return {"available": False, "status": status, "state": self.state()}
        verdict = self.agent.classify(name)
        clue_id = self.agent.relevant_clue(name, verdict)
        return {
            "available": True,
            "name": name,
            "verdict": verdict,
            "clue_id": clue_id,
            "cell": self.engine.puzzle.name_to_cell[name],
            "state": self.state(),
        }

    def auto_step(self) -> dict[str, Any]:
        hint = self.hint()
        if not hint["available"]:
            return {"ok": False, "status": hint["status"], "state": hint["state"]}
        result = self.verdict(hint["name"], hint["verdict"])
        return {**result, "ok": result["result"] == ACCEPTED}

    def auto_solve(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        while not self.engine.is_solved():
            step = self.auto_step()
            steps.append({k: v for k, v in step.items() if k != "state"})
            if not step.get("ok"):
                return {
                    "solved": False,
                    "status": step.get("status", step.get("result")),
                    "steps": steps,
                    "state": self.state(),
                }
        return {
            "solved": True,
            "status": "SOLVED",
            "steps": steps,
            "state": self.state(),
        }

    def classifications(self) -> dict[str, Any]:
        return {
            "characters": self.agent.classify_all(),
            "state": self.state(),
        }

    def uniqueness(self) -> dict[str, Any]:
        return check_uniqueness(self.engine.puzzle)

    def state(self) -> dict[str, Any]:
        return {
            **self.engine.public_state(),
            "analysis": self.agent.summary(),
            "trace": self.trace,
        }
