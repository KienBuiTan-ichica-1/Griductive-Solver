"""Game engine: sole owner of the hidden solution and unrevealed clues."""
from __future__ import annotations

from typing import Any

from .model import (
    NO_CLUE,
    Clue,
    PublicView,
    Puzzle,
    bool_to_status,
    clue_cells,
    clue_is_true,
    describe_clue,
    parse_cell,
)


class GameEngine:
    """Owns complete puzzle data. Only public_knowledge()/public_state() leave this class."""

    def __init__(self, puzzle: Puzzle) -> None:
        self.puzzle = puzzle
        self.reset()

    def reset(self) -> None:
        self.proved: dict[str, bool] = {
            name: self.puzzle.solution[name] for name in self.puzzle.initial_revealed
        }
        self.revealed: set[str] = set(self.puzzle.initial_revealed)
        self.history: list[dict[str, Any]] = []
        self.step_count = 0

    def public_view(self) -> PublicView:
        return self.puzzle.public_view()

    def _clue_for(self, name: str) -> Clue:
        clue = self.puzzle.clue_by_owner.get(name)
        if clue is not None:
            return clue
        return Clue(f"no-clue:{name}", name, NO_CLUE)

    def public_knowledge(self) -> dict[str, Any]:
        """Data passed to the LogicAgent: revealed clues and proved verdicts only."""
        view = self.puzzle.public_view()
        clues = [
            self._clue_for(name)
            for name in sorted(self.revealed, key=lambda n: parse_cell(view.name_to_cell[n]))
        ]
        return {"view": view, "revealed_clues": clues, "proved": dict(self.proved)}

    def reveal(self, name: str, status: bool) -> dict[str, Any]:
        """Flip a proved card and add its clue to public knowledge."""
        if name not in self.puzzle.name_to_cell:
            raise ValueError(f"unknown character {name!r}")
        if status != self.puzzle.solution[name]:
            raise ValueError(f"verdict for {name!r} contradicts the hidden solution")
        self.proved[name] = status
        self.revealed.add(name)
        self.step_count += 1
        clue = self._clue_for(name)
        entry = {
            "step": self.step_count,
            "name": name,
            "verdict": bool_to_status(status),
            "clue_id": clue.id,
        }
        self.history.append(entry)
        return entry

    def is_solved(self) -> bool:
        return len(self.proved) == len(self.puzzle.names)

    def public_state(self) -> dict[str, Any]:
        """GUI state: hidden statuses and unrevealed clue text are never included."""
        view = self.puzzle.public_view()
        characters = []
        for name in sorted(view.names, key=lambda n: parse_cell(view.name_to_cell[n])):
            characters.append({
                "cell": view.name_to_cell[name],
                "name": name,
                "job": view.name_to_job[name],
                "status": bool_to_status(self.proved[name]) if name in self.proved else None,
                "revealed": name in self.revealed,
            })
        clues = []
        for character_name in sorted(
            self.revealed, key=lambda n: parse_cell(view.name_to_cell[n])
        ):
            clue = self._clue_for(character_name)
            clues.append({
                "id": clue.id,
                "owner": clue.owner,
                "type": clue.type,
                "text": describe_clue(clue, view),
                "cells": clue_cells(clue, view),
            })
        return {
            "puzzle": {
                "id": self.puzzle.id,
                "name": self.puzzle.name,
                "group": self.puzzle.group,
                "size": self.puzzle.size,
                "desc": self.puzzle.desc,
            },
            "characters": characters,
            "clues": clues,
            "steps": self.step_count,
            "solved": self.is_solved(),
            "history": self.history,
            "total": len(view.names),
        }

    def verify_hidden_solution(self) -> bool:
        """Sanity check used by the puzzle loader and generator, never by the agent."""
        return all(
            clue_is_true(clue, self.puzzle.solution, self.puzzle)
            for clue in self.puzzle.clues
        )
