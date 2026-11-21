# random_levels: seeded level generator

Generates a Griductive level from a seed. Every level is guaranteed to be **valid, unique and solvable by the no-guess agent**.

```
random_levels/
├── __init__.py     exports generate_level, load_config, load_pool, GenerationError
├── __main__.py     makes `python -m random_levels` work
├── generator.py    the generator
├── tiers.json      difficulty settings (weights, caps, ...): see "Configuration"
└── names.json      the character pool (names + occupations): see "Character pool"
```

## 1. Quick start

Run from the **project root** (the folder that contains `main.py`, `griductive/` and `random_levels/`):

```bash
python -m random_levels --seed 42 --size 4 --difficulty hard
```

The level JSON is printed to stdout and a one-line summary goes to stderr:

```
GEN-4x4-hard-42  attempts=1  score=7.31  avg_frontier=1.0  steps=15
```

Save it to a file:

```bash
python -m random_levels --seed 42 --size 4 --difficulty hard -o levels/GEN-42.json
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `--seed` | random (printed to stderr) | any integer or text. Same inputs give the same level |
| `--size` | `3` | grid size: `3`, `4` or `5` |
| `--difficulty` | `easy` | a tier name from the config (`easy`, `medium`, `hard`, or your own) |
| `--initial N` | from the tier | number of face-up cards at the start |
| `--names FILE` | `names.json` | character pool JSON |
| `--config FILE` | `tiers.json` | tier settings JSON |
| `--max-attempts N` | `50` | tries before giving up |
| `-o`, `--output FILE` | stdout | write the level to a file |

### From Python

```python
from random_levels import generate_level

level = generate_level(42, size=4, difficulty="hard")
# optional: initial=2, names_path="my_names.json", config_path="my_tiers.json", max_attempts=100
```

## 2. Using a generated level

- **Load it into the running game:** send the JSON as the `puzzle` field of `POST /api/game/load`:
  ```json
  { "puzzle": { ...the generated level... } }
  ```
- **Add it to the level list:** save it into `levels/` (for example with `-o levels/GEN-42.json`) and restart the server. It appears in `/api/puzzles`.
- **Level id:** `GEN-<size>x<size>-<difficulty>-<seed>`, for example `GEN-4x4-hard-42`. Two files in `levels/` must not share an id.

### The `meta` block

Every level has an extra `meta` object. The game ignores it. It records how the level was made:

| Field | Meaning |
|---|---|
| `seed`, `difficulty` | the inputs |
| `attempts` | which attempt succeeded (usually 1) |
| `score` | a rough difficulty score, higher is harder (see below) |
| `avg_frontier` | average number of characters that could be proved at the same time. `1.0` means one deduction at a time |
| `clue_types` | how many clues of each type the level really has |
| `solve` | steps, SAT calls, decisions, propagations, backtracks when the agent solves it |
| `tier` | the exact tier settings used, so the level can be reproduced |

`score = average clue-type score + 2 / avg_frontier + decisions per step`. The clue-type scores come from `type_score` in `tiers.json`. Use it only to compare levels with each other.

## 3. How it works

1. Pick a random hidden solution and the face-up characters.
2. Play the reveal protocol forward. Each time a character is proved, give that character a **true** clue that, together with all public information, forces at least one more unsolved character. Forcedness is tested with the real CNF encoder and DPLL solver.
3. Every character ends up forced at its own reveal time, so the full clue set has exactly one solution, and the agent can always make progress.
4. Before returning, the level is checked again with the real `check_uniqueness` and `auto_solve`. If a check fails, it retries with the next attempt number (still deterministic).

## 4. Configuration: `tiers.json`

All tuning lives in this file. No code changes are needed.

```json
{
  "density": [0.35, 0.55],
  "tries_per_clue": 300,
  "relax_after": 100,
  "type_score": { "FACT": 1.0, "...": "..." },
  "tiers": {
    "easy":   { "types": {...}, "regions": {...}, "frontier_cap": null, "initial_share": 0.34 },
    "medium": { "..." : "..." },
    "hard":   { "..." : "..." }
  }
}
```

### Rules for the file

- **Weights are relative**, not percentages. `{"FACT": 4, "EXACTLY": 4}` is the same as `{"FACT": 1, "EXACTLY": 1}`.
- **`0` or a missing key means "never used"** for `types` and `regions`.
- A tier needs at least one positive weight in `types` and in `regions`.
- Names are checked. An unknown clue type, region kind or key, a negative weight, or a bad value stops the run with a clear `error:` message instead of being ignored.
- Keys that start with `_` (for example `"_help"` or `"_note"`) are ignored, so you can leave notes in the file.
- The weight is the chance a type is *tried*. A candidate can be rejected (for example it forces nobody), so the real mix differs a little. See `meta.clue_types`.

### Global keys

| Key | Default | Meaning |
|---|---|---|
| `density` | `[0.35, 0.55]` | range for the share of criminals in the hidden solution |
| `tries_per_clue` | `300` | candidate clues tried for one character before the attempt is abandoned |
| `relax_after` | `100` | after this many failed candidates for one clue, `frontier_cap` is ignored for that clue |
| `type_score` | built-in | score per clue type, used only for `meta.score` |
| `tiers` | required | the difficulty tiers |

### Keys inside a tier

| Key | Default | Meaning |
|---|---|---|
| `types` | required | weights of clue types (table below) |
| `regions` | required | weights of region kinds (table below) |
| `frontier_cap` | `null` | the most characters that may be provable at once after each reveal. `1` = one deduction at a time, `null` = no limit |
| `initial_share` | `0.2` | share of cards face-up at the start: `max(1, round(cells × share))`, never all cards. `--initial` overrides it |

### `types`: clue types

| Type | The clue says | Example |
|---|---|---|
| `FACT` | one person's status | "Derek is innocent." |
| `SAME` | two people have the same status | "Eliza and Abel have the same status." |
| `DIFFERENT` | two people have different statuses | "Abel and Bea have different statuses." |
| `EXACTLY` | an exact criminal count in a region | "Exactly 2 criminals in row 1." |
| `AT_LEAST` | a lower bound on the count (with slack, so it is vague) | "At least 1 criminal in column B." |
| `AT_MOST` | an upper bound on the count (with slack) | "At most 3 criminals in the neighbours of B2." |
| `PARITY` | the count is even or odd | "The number of criminals in row 3 is odd." |
| `COMPARE` | count in one region compared with another | "Row 1 has fewer criminals than column C." |

How they behave when generated:
- `FACT` is the easiest (it hands over a verdict). It always names someone who is not yet proved.
- `SAME` / `DIFFERENT` need at least one unsolved person. A pair with one proved person is the easy kind.
- `EXACTLY` gives the real count. `AT_LEAST` / `AT_MOST` are deliberately vague.
- `PARITY` and `COMPARE` give little information alone and are mainly useful in combination, so they make levels harder.

### `regions`: which cells a counting clue looks at

Regions are only used by the counting types (`EXACTLY`, `AT_LEAST`, `AT_MOST`, `PARITY`, `COMPARE`). `FACT`, `SAME` and `DIFFERENT` never use them. Examples are for a 3×3 grid:

| Region | Cells |
|---|---|
| `row` | a whole row, e.g. A1 B1 C1 |
| `col` | a whole column, e.g. B1 B2 B3 |
| `neighbors` | the cells touching one cell, not itself (B2 has 8, A1 has 3, B1 has 5) |
| `cells` | a random list of 2 to 5 cells |
| `boundary` | the outer ring (8 cells on 3×3, 12 on 4×4, 16 on 5×5) |
| `corners` | the four corner cells |
| `between` | the cells strictly between two aligned cells (A1 and C1 give B1) |
| `common_neighbors` | cells touching both of two cells (A1 and C1 give B1 and B2) |
| `intersection` | cells in two regions at once (row 1 and column B give B1) |

Small regions give strong, easy clues. Large ones (`boundary`, `neighbors`) give weak clues. `between`, `common_neighbors` and `intersection` often produce nothing usable (especially on 3×3) and are discarded, so they are used less than their weight suggests. `intersection` often yields a single cell, which makes the clue behave like a `FACT`.

### Recipes

| Goal | Change |
|---|---|
| remove direct hints | set `"FACT": 0` (and lower `SAME` / `DIFFERENT`) in that tier |
| make clues vaguer | raise `AT_LEAST` / `AT_MOST` |
| make clues combine more | raise `PARITY` and `COMPARE` |
| force one deduction at a time | `"frontier_cap": 1` |
| allow several deductions at once | `"frontier_cap": null` or a larger number |
| start with fewer face-up cards | lower `initial_share` (or use `--initial 1`) |
| avoid tiny regions | set `"cells": 0`, and favour `boundary` / `neighbors` |
| a custom difficulty | add a new name under `tiers`, then use `--difficulty myname` |

To try settings without touching the original, copy the file and pass `--config my_tiers.json`.

## 5. Character pool: `names.json`

Each name is a key. Its object holds that character's occupation, and any other fields you want to add later:

```json
{
  "Abel":  { "occupation": "Painter" },
  "Bea":   { "occupation": "Quarryman", "portrait": "bea.png" }
}
```

- The occupation key may be `occupation`, `job` or `profession`. A character without one gets "Worker".
- **Extra fields are copied unchanged** into each generated character. The game loader ignores fields it does not know, so levels still load.
- A list of `{"name": ..., "occupation": ...}` objects, or a plain list of names, also works.
- The pool needs at least as many characters as cells: 9, 16 or 25. The default file has 40.
- Duplicate names are rejected. Note that two identical keys inside the same JSON object silently merge into one. That is how JSON parsing works.
- Names are drawn with the seeded random generator, and each keeps its own occupation.

## 6. Reproducibility

The same **seed + size + difficulty + initial + `tiers.json` + `names.json`** always gives the identical level. Changing the config, the name pool, or the generator code changes the level for the same seed. When you want to keep a level, save the file (`-o`), and `meta.tier` records the settings it was made with.

## 7. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `No module named griductive` or `random_levels` | run from the project root |
| `'random_levels' is a package and cannot be directly executed` | `__main__.py` is missing from the folder |
| `error: no valid level after N attempts` | try another seed, an easier tier, a higher `--max-attempts`, or a higher `tries_per_clue` |
| `error: ... unknown 'X'` / `unknown key` | a typo in `tiers.json`; the message names the exact key |
| `error: names list needs at least N names` | the pool has fewer characters than cells |
| very slow on 5×5 | each candidate clue costs one SAT call per unsolved character. Try 3×3 or 4×4, or lower `tries_per_clue` |
| level looks too easy | lower `FACT` / `SAME` / `DIFFERENT` weights, use `frontier_cap: 1`, and favour `PARITY` / `COMPARE` / `AT_LEAST` / `AT_MOST` |