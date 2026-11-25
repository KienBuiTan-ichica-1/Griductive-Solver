"""Puzzle model, region resolution and direct semantic evaluators for Griductive."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CRIMINAL = "CRIMINAL"
INNOCENT = "INNOCENT"
STATUS_VALUES = (CRIMINAL, INNOCENT)

CORE_TYPES = ("FACT", "SAME", "DIFFERENT", "EXACTLY", "AT_LEAST", "AT_MOST")
EXTENSION_TYPES = ("PARITY", "COMPARE")
NO_CLUE = "NO_CLUE"
CLUE_TYPES = CORE_TYPES + EXTENSION_TYPES + (NO_CLUE,)
REGION_KINDS = (
    "row", "col", "column", "neighbors", "cells",
    "intersection", "common_neighbors", "boundary", "corners", "between",
)
COMPARE_OPS = ("<", "<=", "=", "!=", ">", ">=")


def col_letter(index: int) -> str:
    """0-based column index -> spreadsheet-style letter."""
    if index < 0:
        raise ValueError("column index must be non-negative")
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def parse_cell(cell: str) -> tuple[int, int]:
    """'C2' -> (row 2, column index 2); row is 1-based, column is 0-based."""
    text = str(cell).strip().upper()
    split = 0
    while split < len(text) and text[split].isalpha():
        split += 1
    letters, digits = text[:split], text[split:]
    if not letters or not digits.isdigit() or int(digits) < 1:
        raise ValueError(f"invalid cell identifier: {cell!r}")
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(digits), col - 1


def format_cell(row: int, col: int) -> str:
    return f"{col_letter(col)}{row}"


def status_to_bool(status: str) -> bool:
    if isinstance(status, str):
        normalized = status.strip().upper()
        if normalized == CRIMINAL:
            return True
        if normalized == INNOCENT:
            return False
    elif status in (True, 1):
        return True
    elif status in (False, 0):
        return False
    raise ValueError(f"invalid status: {status!r}")


def bool_to_status(value: bool) -> str:
    return CRIMINAL if value else INNOCENT


@dataclass(frozen=True)
class Character:
    cell: str
    name: str
    job: str = ""


@dataclass
class PublicView:
    """The part of a puzzle visible to the LogicAgent: no solution, no hidden clues."""

    size: int
    names: list[str]
    name_to_cell: dict[str, str]
    cell_to_name: dict[str, str]
    name_to_job: dict[str, str]


@dataclass
class Clue:
    id: str
    owner: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in CLUE_TYPES:
            raise ValueError(f"unknown clue type {self.type!r}; expected one of {CLUE_TYPES}")
        if not self.owner:
            raise ValueError("a clue must have an owner")
        if not isinstance(self.params, dict):
            raise ValueError("clue params must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "owner": self.owner, "type": self.type, **self.params}


class Puzzle:
    """A complete puzzle definition, including hidden data owned by the GameEngine."""

    def __init__(
        self,
        puzzle_id: str,
        name: str,
        group: str,
        size: int,
        characters: list[Character],
        clues: list[Clue],
        solution: dict[str, bool],
        initial_revealed: list[str],
        desc: str = "",
    ) -> None:
        self.id = str(puzzle_id)
        self.name = str(name)
        self.group = str(group)
        self.size = int(size)
        self.characters = list(characters)
        self.clues = list(clues)
        self.solution = dict(solution)
        self.initial_revealed = list(initial_revealed)
        self.desc = desc

        self.names: list[str] = sorted((c.name for c in self.characters))
        self.name_to_cell: dict[str, str] = {c.name: c.cell for c in self.characters}
        self.cell_to_name: dict[str, str] = {c.cell: c.name for c in self.characters}
        self.name_to_job: dict[str, str] = {c.name: c.job for c in self.characters}
        self.validate()

        self.clue_by_owner: dict[str, Clue] = {}
        self.clue_by_id: dict[str, Clue] = {}
        for clue in self.clues:
            if clue.owner in self.clue_by_owner:
                raise ValueError(f"character {clue.owner!r} has more than one clue")
            self.clue_by_owner[clue.owner] = clue
            self.clue_by_id[clue.id] = clue

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Puzzle":
        if not isinstance(data, dict):
            raise TypeError("puzzle must be a JSON object")
        size = int(data.get("size", 0))
        if size < 2 or size > 7:
            raise ValueError("size must be between 2 and 7")
        characters: list[Character] = []
        for raw in data.get("characters", []):
            job = raw.get("job", raw.get("profession", ""))
            characters.append(Character(str(raw["cell"]), str(raw["name"]), str(job or "")))
        clues: list[Clue] = []
        for index, raw in enumerate(data.get("clues", [])):
            params = {k: v for k, v in raw.items() if k not in ("id", "owner", "type")}
            clue_id = str(raw.get("id", f"c{index + 1}"))
            clues.append(Clue(clue_id, str(raw.get("owner", "")), str(raw.get("type", "")), params))
        solution = {
            str(name): status_to_bool(status)
            for name, status in (data.get("solution") or {}).items()
        }
        initial = [str(name) for name in data.get("initial_revealed", [])]
        return cls(
            str(data.get("id", "custom")),
            str(data.get("name", "Custom puzzle")),
            str(data.get("group", "custom")),
            size,
            characters,
            clues,
            solution,
            initial,
            str(data.get("desc", "")),
        )

    def public_view(self) -> PublicView:
        return PublicView(
            self.size,
            list(self.names),
            dict(self.name_to_cell),
            dict(self.cell_to_name),
            dict(self.name_to_job),
        )

    def to_dict(self, include_hidden: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "size": self.size,
            "desc": self.desc,
            "characters": [
                {"cell": c.cell, "name": c.name, "job": c.job} for c in self.characters
            ],
            "clues": [clue.to_dict() for clue in self.clues],
            "initial_revealed": self.initial_revealed,
        }
        if include_hidden:
            data["solution"] = {
                name: bool_to_status(value) for name, value in self.solution.items()
            }
        return data

    def validate(self) -> None:
        if self.size < 2:
            raise ValueError("grid size must be at least 2")
        if not self.characters:
            raise ValueError("a puzzle needs at least one character")
        seen_cells: set[str] = set()
        seen_names: set[str] = set()
        for char in self.characters:
            row, col = parse_cell(char.cell)
            if not (1 <= row <= self.size and 0 <= col < self.size):
                raise ValueError(f"cell {char.cell!r} is outside a {self.size}x{self.size} grid")
            if char.cell in seen_cells or char.name in seen_names:
                raise ValueError("duplicate cell or character name")
            seen_cells.add(char.cell)
            seen_names.add(char.name)
        if len(seen_cells) != self.size * self.size:
            raise ValueError("every cell of the grid must contain a character")
        names = set(seen_names)
        if set(self.solution) != names:
            raise ValueError("solution must assign a status to every character")
        if len({clue.id for clue in self.clues}) != len(self.clues):
            raise ValueError("clue ids must be unique")
        for clue in self.clues:
            if clue.owner not in names:
                raise ValueError(f"clue {clue.id!r} references unknown owner {clue.owner!r}")
            validate_clue(clue, self)
        for name in self.initial_revealed:
            if name not in names:
                raise ValueError(f"unknown initially revealed character {name!r}")


def _region_names(spec: Any, puzzle: Puzzle) -> list[str]:
    """Resolve a region expression to a deterministic list of character names."""
    if isinstance(spec, str):
        if spec in puzzle.name_to_cell:
            spec = {"kind": "cells", "cells": [spec]}
        elif spec.upper().startswith("ROW"):
            spec = {"kind": "row", "row": int(spec[3:])}
        elif len(spec) >= 2 and spec[0].isalpha() and spec[1:].isdigit():
            row, _ = parse_cell(spec)
            spec = {"kind": "row", "row": row}
        else:
            raise ValueError(f"invalid region expression: {spec!r}")
    if not isinstance(spec, dict):
        raise ValueError("region must be an object")
    kind = str(spec.get("kind", "")).lower()

    def in_grid(row: int, col: int) -> bool:
        return 1 <= row <= puzzle.size and 0 <= col < puzzle.size

    def names_from_cells(cells: list[str]) -> list[str]:
        result: list[str] = []
        for cell in cells:
            name = puzzle.cell_to_name.get(format_cell(*parse_cell(cell)))
            if name is None or name in result:
                raise ValueError(f"region references an invalid or repeated cell: {cell!r}")
            result.append(name)
        return sorted(result)

    if kind == "row":
        row = int(spec["row"])
        if not 1 <= row <= puzzle.size:
            raise ValueError(f"row {row} is outside the grid")
        return names_from_cells([format_cell(row, c) for c in range(puzzle.size)])
    if kind in ("col", "column"):
        raw = spec.get("col", spec.get("column"))
        if isinstance(raw, int):
            col = raw
        else:
            _, col = parse_cell(f"{raw}1")
        if not 0 <= col < puzzle.size:
            raise ValueError(f"column {raw} is outside the grid")
        return names_from_cells([format_cell(r, col) for r in range(1, puzzle.size + 1)])
    if kind == "neighbors":
        row, col = parse_cell(str(spec["cell"]))
        cells = [
            format_cell(r, c)
            for r in range(row - 1, row + 2)
            for c in range(col - 1, col + 2)
            if in_grid(r, c) and (r, c) != (row, col)
        ]
        return names_from_cells(cells)
    if kind == "cells":
        return names_from_cells([str(cell) for cell in spec.get("cells", [])])
    if kind == "intersection":
        sets = [set(_region_names(part, puzzle)) for part in spec.get("regions", [])]
        if not sets:
            raise ValueError("intersection needs at least one region")
        result = set.intersection(*sets)
        if not result:
            raise ValueError("intersection is empty")
        return sorted(result)
    if kind == "common_neighbors":
        a = set(_region_names({"kind": "neighbors", "cell": spec["a"]}, puzzle))
        b = set(_region_names({"kind": "neighbors", "cell": spec["b"]}, puzzle))
        result = a & b
        if not result:
            raise ValueError("common neighbors region is empty")
        return sorted(result)
    if kind == "boundary":
        cells = [
            format_cell(r, c)
            for r in range(1, puzzle.size + 1)
            for c in range(puzzle.size)
            if r in (1, puzzle.size) or c in (0, puzzle.size - 1)
        ]
        return names_from_cells(cells)
    if kind == "corners":
        return names_from_cells([
            format_cell(1, 0), format_cell(1, puzzle.size - 1),
            format_cell(puzzle.size, 0), format_cell(puzzle.size, puzzle.size - 1),
        ])
    if kind == "between":
        r1, c1 = parse_cell(str(spec["a"]))
        r2, c2 = parse_cell(str(spec["b"]))
        dr = (r2 > r1) - (r2 < r1)
        dc = (c2 > c1) - (c2 < c1)
        if dr and dc and abs(r2 - r1) != abs(c2 - c1):
            raise ValueError("'between' cells must share a row, column or diagonal")
        if not dr and not dc:
            raise ValueError("'between' endpoints must be different")
        r, c = r1 + dr, c1 + dc
        cells: list[str] = []
        while (r, c) != (r2, c2):
            if not in_grid(r, c):
                raise ValueError("'between' segment leaves the grid")
            cells.append(format_cell(r, c))
            r += dr
            c += dc
        if not cells:
            raise ValueError("'between' region is empty")
        return names_from_cells(cells)
    raise ValueError(f"unknown region kind: {kind!r}")


def region_cells(spec: Any, puzzle: Puzzle) -> list[str]:
    """Cell ids referenced by a region, in row-major order (for GUI highlighting)."""
    names = _region_names(spec, puzzle)
    return sorted(
        (puzzle.name_to_cell[name] for name in names),
        key=parse_cell,
    )


def clue_cells(clue: Clue, puzzle_like: Puzzle | PublicView) -> list[str]:
    """All cells highlighted when this clue is selected in the GUI."""
    cells: set[str] = set()
    name_to_cell = puzzle_like.name_to_cell
    for key in ("person", "a", "b"):
        raw = clue.params.get(key)
        if isinstance(raw, str) and raw in name_to_cell:
            cells.add(name_to_cell[raw])
    for key in ("region", "left", "right"):
        raw = clue.params.get(key)
        if raw is not None:
            cells.update(region_cells(raw, puzzle_like))
    return sorted(cells, key=parse_cell)


def validate_clue(clue: Clue, puzzle: Puzzle) -> None:
    """Validate clue parameters and every referenced cell before encoding."""
    params = clue.params
    kind = clue.type

    def person(raw: Any) -> str:
        name = str(raw)
        if name not in puzzle.name_to_cell:
            raise ValueError(f"clue {clue.id!r} references unknown character {name!r}")
        return name

    if kind == NO_CLUE:
        return
    if kind == "FACT":
        if str(params.get("status", "")).upper() not in STATUS_VALUES:
            raise ValueError(f"clue {clue.id!r} has an invalid status")
        person(params["person"])
    elif kind in ("SAME", "DIFFERENT"):
        a, b = person(params["a"]), person(params["b"])
        if a == b:
            raise ValueError(f"clue {clue.id!r} compares a character with itself")
    elif kind in ("EXACTLY", "AT_LEAST", "AT_MOST"):
        names = _region_names(params["region"], puzzle)
        if not names:
            raise ValueError(f"clue {clue.id!r} has an empty region")
        k = int(params.get("k", -1))
        if not 0 <= k <= len(names):
            raise ValueError(f"clue {clue.id!r} has k={k} outside 0..{len(names)}")
    elif kind == "PARITY":
        if not _region_names(params["region"], puzzle):
            raise ValueError(f"clue {clue.id!r} has an empty region")
        if str(params.get("parity", "")).lower() not in ("even", "odd"):
            raise ValueError(f"clue {clue.id!r} has invalid parity")
    elif kind == "COMPARE":
        left = _region_names(params["left"], puzzle)
        right = _region_names(params["right"], puzzle)
        if str(params.get("op", "")) not in COMPARE_OPS:
            raise ValueError(f"clue {clue.id!r} has invalid comparison operator")
        if not left or not right:
            raise ValueError(f"clue {clue.id!r} has an empty comparison region")
    else:
        raise ValueError(f"unsupported clue type: {kind!r}")


def clue_is_true(clue: Clue, assignment: dict[str, bool], puzzle: Puzzle) -> bool:
    """Direct semantic evaluator: no CNF encoder and no SAT solver involved."""
    params = clue.params
    kind = clue.type
    if kind == NO_CLUE:
        return True
    if kind == "FACT":
        return assignment[str(params["person"])] == status_to_bool(params["status"])
    if kind == "SAME":
        return assignment[str(params["a"])] == assignment[str(params["b"])]
    if kind == "DIFFERENT":
        return assignment[str(params["a"])] != assignment[str(params["b"])]
    if kind == "COMPARE":
        left = sum(assignment[n] for n in _region_names(params["left"], puzzle))
        right = sum(assignment[n] for n in _region_names(params["right"], puzzle))
        op = str(params["op"])
        return {
            "<": left < right, "<=": left <= right, "=": left == right,
            "!=": left != right, ">": left > right, ">=": left >= right,
        }[op]
    count = sum(assignment[name] for name in _region_names(params["region"], puzzle))
    if kind == "EXACTLY":
        return count == int(params["k"])
    if kind == "AT_LEAST":
        return count >= int(params["k"])
    if kind == "AT_MOST":
        return count <= int(params["k"])
    if kind == "PARITY":
        return (count % 2 == 0) == (str(params["parity"]).lower() == "even")
    raise ValueError(f"unsupported clue type: {kind!r}")


def _describe_region(spec: Any, puzzle: Puzzle) -> str:
    if isinstance(spec, dict):
        kind = str(spec.get("kind", "")).lower()
        if kind == "row":
            return f"row {spec['row']}"
        if kind in ("col", "column"):
            return f"column {spec.get('col', spec.get('column'))}"
        if kind == "neighbors":
            return f"the neighbours of {spec['cell']}"
        if kind == "cells":
            return ", ".join(str(c) for c in spec.get("cells", []))
        if kind == "intersection":
            return "the intersection of " + " and ".join(
                _describe_region(r, puzzle) for r in spec.get("regions", [])
            )
        if kind == "common_neighbors":
            return f"the common neighbours of {spec['a']} and {spec['b']}"
        if kind == "boundary":
            return "the boundary cells"
        if kind == "corners":
            return "the four corners"
        if kind == "between":
            return f"the cells between {spec['a']} and {spec['b']}"
    return str(spec)


def describe_clue(clue: Clue, puzzle: Puzzle) -> str:
    """Natural-language rendering of a structured clue for the GUI."""
    p = clue.params
    t = clue.type
    if t == NO_CLUE:
        return "This card has no clue."
    if t == "FACT":
        return f"{p['person']} is {str(p['status']).lower()}."
    if t == "SAME":
        return f"{p['a']} and {p['b']} have the same status."
    if t == "DIFFERENT":
        return f"{p['a']} and {p['b']} have different statuses."
    if t == "EXACTLY":
        return f"Exactly {p['k']} of the people in {_describe_region(p['region'], puzzle)} are criminals."
    if t == "AT_LEAST":
        return f"At least {p['k']} of the people in {_describe_region(p['region'], puzzle)} are criminals."
    if t == "AT_MOST":
        return f"At most {p['k']} of the people in {_describe_region(p['region'], puzzle)} are criminals."
    if t == "PARITY":
        return f"The number of criminals in {_describe_region(p['region'], puzzle)} is {p['parity']}."
    if t == "COMPARE":
        return (
            f"The number of criminals in {_describe_region(p['left'], puzzle)} "
            f"is {p['op']} the number in {_describe_region(p['right'], puzzle)}."
        )
    return str(clue.to_dict())
