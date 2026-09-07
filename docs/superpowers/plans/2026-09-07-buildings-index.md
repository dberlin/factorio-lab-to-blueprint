# Buildings Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repeated linear scans of `buildings` sequences across the
layout pipeline with one `Buildings` domain abstraction that answers the
questions callers actually ask from prebuilt indexes, removing the quadratic
sites the user identified.

**Architecture:** A new `src/flab2bp/layout/buildings.py` holds `Buildings`, an
immutable view over a building sequence with dict-backed indexes on every key
the survey found, and `MutableBuildings`, a `MutableSequence` that keeps those
indexes correct across freeform's tail-append / tail-pop / relink mutation
pattern. Query methods are named for the domain question (`machines_for_recipe`,
`sorters_into`, `belts_carrying`, `at_tile`) and return the positional building
indices callers already use, so conversion is local to each call site. The
index backend is private to that one module.

**Tech Stack:** Python 3.14, stdlib only. No new runtime dependency — see
§ Backend and § Graph for the measurements that rejected `littletable`,
`polars` and `networkx`.

**Spec:** This document. § Spec carries the user's verbatim request and the
brief's requirements; the plan argues from it.

---

## Spec

The user's request, verbatim:

> I was watching the self-loop agent work, and it looks like in its marker code,
> and in lots of other places, we do these O(n) or O(n^2) loops through
> "buildings". Each of these loops walks all of the buildings, for each loop
> seed. In this case, it also should be walking group_machines, which is the
> smaller set anyway. There are tons of loops like this across the codebase.
> Please dispatch a speedup agent to fix all of these. Use littletable (add it)
> and indexes and a proper Buildings abstraction. It looks in this case that you
> want graph nodes and edges. If so, and we are doing something later like
> connected components, add networkx and use it to provide a graph abstraction
> in Buildings.

Two later rulings from the user, relayed mid-survey:

> Another option for both other than littletable is polars. But that only makes
> sense if the data (here and elsewhere) is immutable.

> Whether littletable or polars is used, it should be hidden behind an overall
> abstraction for the type of thing.

The example the user was looking at lives on branch `selfloop`
(`src/flab2bp/layout/markers.py`), which is not on master. This plan converts
master's sites; the marker sites are a named follow-up (§ Follow-ups).

## Global Constraints

Every task's requirements implicitly include this section.

- **Byte-identical output.** Every converted query must return exactly what the
  scan it replaces returned, in the same order wherever the caller's result
  depends on order. Blueprint strings for the deterministic controls must match
  master exactly.
- **Backend containment.** No module outside `src/flab2bp/layout/buildings.py`
  may import or name an index-backend library (`littletable`, `polars`,
  `networkx`, `pandas`), receive a backend object, or write a backend query
  expression. `Buildings`' public methods are typed with the domain's own types
  — building indices (`int`), `PlacedBuilding` records, `tuple[int, ...]`,
  `frozenset[int]` — never a library type. Task 1 Step 9 enforces this with a
  test.
- **No new runtime dependency.** `pyproject.toml`'s `dependencies` list is
  unchanged by this branch.
- **Never a stale index.** A query must never answer from an index that does not
  reflect the current sequence. `MutableBuildings` maintains its indexes on
  every mutation; `Buildings` is built from an immutable sequence. Task 1 and
  Task 2 each prove this with a test.
- **Verification at every task:** `uv run ruff check`, `uv run ruff format
  --check`, `uv run mypy`, and the full `uv run pytest` suite judged by EXIT
  CODE — pytest prints no summary line in this environment, and a 120 s
  pytest-timeout backstop hard-kills any hung test. Two tests are RED on master
  and stay red; they are not your regression:
  `test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
  `test_all_products_sequence_pair_honours_the_exact_layout_deadline`.
- **Worktree hygiene:** work in
  `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/buildings-index`.
  Run `uv sync` and confirm `uv run python -c "import flab2bp;
  print(flab2bp.__file__)"` prints a path **inside the worktree** before any
  test result counts — a worktree without its own venv silently tests master.
- **No interactive git.** `export GIT_EDITOR=true`; always `-m` / `-F` /
  `--no-edit`. Never `git rebase -i` or `git add -i`.
- **Process checks:** `pgrep -f` with an interpreter-anchored pattern, never
  `ps | grep`. Audit slot: `pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'`.
- **CPU pressure** is `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`
  (mean runnable procs; fine below 64). Never load average, never wait for it.
- **One build at a time from this branch.** An item sweep and three other SDD
  controllers also build on this box.
- **Serena for reading only.** It is a shared last-activation-wins server;
  concurrent worktree agents make its writes land in the wrong tree. Edit with
  Read/Edit.
- **Never commit anything under `.superpowers/`.** Evidence goes under
  `docs/superpowers/evidence/2026-09-07-buildings-index/`, any size.
- **One commit per file converted**, so a later rebase conflict stays local.

## Survey

Five parallel surveys classified **155 sites** across the tree. Full per-site
tables, with predicate keys, nesting, traced call frequency and the replacing
query for every row, live in:

- `docs/superpowers/evidence/2026-09-07-buildings-index/survey-freeform.md` (55 sites)
- `docs/superpowers/evidence/2026-09-07-buildings-index/survey-layout-core.md` (54 sites)
- `docs/superpowers/evidence/2026-09-07-buildings-index/survey-hierarchy-dsp-bench-web.md` (46 sites)
- `docs/superpowers/evidence/2026-09-07-buildings-index/graph-survey.md` (13 connectivity sites)

The brief's rough grep found 34 sites on the literal name `buildings`. The real
population is 155, because most scans are comprehension filters, `next(...)`
lookups, `min`/`max` passes and guarded `buildings[i]` lookups.

| file | sites | WORTH | contended by | rank |
|---|---|---|---|---|
| `layout/freeform.py` | 55 | 23 | `coater-placed`, `hierarchical-v4` | 5 |
| `layout/validate.py` | 21 | 6 | `selfloop` | 2 |
| `layout/finalize.py` | 19 | 7 | — | 3 |
| `dsp/colliders.py` + `dsp/planet.py` + `dsp/splitter_ports.py` + `dsp/codec.py` | 28 | 6 | — | 6 |
| `layout/hierarchy/contracts.py` + `compose.py` + `strip_variants.py` | 10 | 6 | `hierarchical-v4` | 4 |
| `bench/metrics.py` | 8 | 0 | — | 6 |
| `layout/slots.py` | 5 | 1 | — | 7 |
| `layout/markers.py` | 5 | 0 | `selfloop` | follow-up |
| `layout/junction.py` | 3 | 0 (dead code) | — | 7 |
| `layout/base.py` | 1 | 1 | `selfloop` | **1** |
| `web/trace.py` | 1 | 0 | — | 6 |

**Files with no building scans at all**, verified: `hierarchy/partition.py`,
`hierarchy/pressure.py`, `hierarchy/strategy.py`, `sequence_solver.py`,
`sequence_pair.py`, `sequence_islands.py`, `sequence_alns.py`,
`compact_seed.py`, `strategy_race.py`, `dsp/provenance.py`, `pipeline.py`,
`spec.py`, `web/payload.py`.

### The rule for HYGIENE sites

A single pass that runs once per build is **not** worth converting unless it
falls out of the abstraction for free. Of the 155 sites, 111 are HYGIENE by
that rule and this plan converts only those that become one-liners against a
`Buildings` the file already holds. Each per-file task says which of its sites
are WORTH and which are HYGIENE; the evidence tables carry the per-site verdict
and the reasoning.

### The highest-value single site

`Placement.bounds` (`layout/base.py:539-540`) recomputes **four full O(N) list
comprehensions over `self.buildings`, uncached, on every call**, and is called
from `freeform.py` (~10 sites, inside the search loop), `finalize.py` (~8 sites,
inside the frame-candidate loop) and `validate.py` (~6 sites) — 24+ traced call
sites, several per placement candidate. One memoised property removes more
redundant scanning than any other change in this plan, in six lines. It is
Task 3.

## Backend: why no library

The brief asked for `littletable`; the user offered `polars` for immutable
holders. Both were benchmarked against real blueprints decoded from
`tests/fixtures/` before this plan chose. Full numbers and the reproducible
script: `docs/superpowers/evidence/2026-09-07-buildings-index/backend-choice.md`.

| fixture | N | scan | littletable | polars | dict |
|---|---|---|---|---|---|
| factory-quick-start-step-3-red-cube | 287 | 8.4 us | 23.7 us | 189.1 us | **0.100 us** |
| factory-heretical-smelter-block | 591 | 21.7 us | 155.9 us | 206.5 us | **0.100 us** |
| factory-endgame-distribution-hub | 1969 | 141.0 us | 3245.9 us | 342.6 us | **0.208 us** |

At every size this project produces (roughly 500 to 6000 buildings) both
libraries are **slower than the linear scan they would replace**, because each
answers a lookup by materialising a new container. A plain
`dict[key, tuple[int, ...]]` built in one O(n) pass is 200x to 1600x faster than
the scan, with a build cost in the same order as theirs.

**Ruling:** `Buildings` ships the abstraction and the named indexed queries the
user asked for, backed by dict indexes. Neither library is added. Because the
backend is confined to `buildings.py` behind the public interface, swapping a
dict for a `littletable.Table` later is a single-file change with no call-site
churn. *Cost if wrong:* the user wanted a named library in the tree.

## Graph: why no networkx

Thirteen sites walk building connectivity for reachability, cycle detection and
one hand-rolled Tarjan SCC. Full survey: `graph-survey.md`.

Not one is a cheap, exact `nx.*` swap. The two heaviest — freeform's
`_committed_path_closes_cycle` (Tarjan over only the *reachable slice*) and
`_leads_back` (DFS with early exit) — are tighter than the networkx primitive
and sit on the commit hot path, where each call would additionally pay a fresh
`DiGraph` build against a canvas that mutates between commits. `belt.acyclic`
cannot be converted at all without changing Finding output. Every walk in
`dsp/colliders.py` is hard-capped at 1-3 hops to replay a decompiled game rule.

**Ruling:** networkx is not added. What the survey shows is worth doing instead
is what `Buildings` provides: build the successor / predecessor edge index once
and share it, fixing the four real algorithmic defects the survey found —
`contracts._belt_run`'s O(n^2) adjacency build, `validate._belt_reaches_any`'s
rescan inside the pop loop, `validate._close_over_junctions`' fixpoint, and
`freeform._leads_back`'s per-call index rebuild — none of which networkx would
have fixed. *Cost if wrong:* if a later feature needs `nx.maximum_flow`, adding
networkx then is a one-line `uv add`; nothing here forecloses it.

## Mutability, per holder

| holder | shape | verdict |
|---|---|---|
| `Placement.buildings` (`base.py:517`) | `tuple[...]`, frozen slots dataclass | **immutable** — index once |
| `_Canvas.buildings` (`freeform.py:5771`) | `list`, mutated throughout a build | **live** — maintained indexes |
| `compose.py` composed list | `list`, `extend`ed then frozen into a `Placement` | grows, then frozen |
| `dsp` / `bench` / `web` holders | read a finished `Placement` or decoded `Blueprint` | **immutable** |

The freeform survey established the live canvas's exact mutation grammar:

- **All growth is tail-append** — `_Canvas.add` (freeform.py:5889) plus four raw
  `canvas.buildings.append(...)` at **6960, 7321, 18302, 19267** that bypass
  `add`.
- **All removal is tail-pop** — `_commit_paths.roll_back_prefix` (12444), which
  already asserts the popped index is the tail.
- **Every in-place write is a `_relink` / `replace` touching only `input_obj` /
  `output_obj`** (and `z`, at 13503 and 13315). Geometry — `x`, `y`, `width`,
  `height`, `item_id`, `model_index`, `owner_strip` — is **never** rewritten
  after insertion.

So geometry / tile / item / kind indexes need only append and truncate; only the
link indexes need per-relink maintenance, which `_commit_paths.refresh_predecessor`
(12504) already hand-rolls. Because four appends and the pop bypass
`_Canvas.add`, an index hooked into `add` would silently miss them — so
`MutableBuildings` wraps **the list itself**, which no call site can bypass.

## File Structure

| file | responsibility |
|---|---|
| `src/flab2bp/layout/buildings.py` (new) | `Kind`, `Buildings` (immutable view + indexes), `MutableBuildings` (live list with maintained indexes). The only module that knows how an index is stored. |
| `tests/layout/test_buildings.py` (new) | Index correctness against brute-force scans on generated and real fixtures; staleness; mutation grammar. |
| `tests/test_backend_containment.py` (new) | Greps the tree for backend-library imports outside `buildings.py`. |
| converted call sites | one commit per file, in the rank order above. |

---

## Task 1: The `Buildings` abstraction

**Files:**
- Create: `src/flab2bp/layout/buildings.py`
- Create: `tests/layout/test_buildings.py`
- Create: `tests/test_backend_containment.py`

**Interfaces:**
- Consumes: `flab2bp.layout.base.PlacedBuilding`, `flab2bp.dsp.catalog.is_belt`,
  `is_sorter`, `SPLITTER_ID`, `PILER_ID`, `SPRAY_COATER_ID`.
- Produces: everything later tasks call. Exact public surface:

```python
class Kind(Enum):
    MACHINE = "machine"
    BELT = "belt"
    SORTER = "sorter"
    OTHER = "other"

class Buildings:
    def __init__(self, records: Sequence[PlacedBuilding]) -> None: ...
    @classmethod
    def of(cls, placement: Placement) -> Buildings: ...

    # identity / access
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[PlacedBuilding]: ...
    def all(self) -> tuple[PlacedBuilding, ...]: ...
    def by_index(self, index: int | None) -> PlacedBuilding | None: ...
    def kind_of(self, index: int) -> Kind: ...

    # attribute indexes -> positional indices, ascending
    def by_kind(self, kind: Kind) -> tuple[int, ...]: ...
    def machines(self) -> tuple[int, ...]: ...
    def belts(self) -> tuple[int, ...]: ...
    def sorters(self) -> tuple[int, ...]: ...
    def by_item(self, item_id: int) -> tuple[int, ...]: ...
    def splitters(self) -> tuple[int, ...]: ...
    def machines_for_recipe(self, recipe_id: int) -> tuple[int, ...]: ...
    def by_owner_strip(self, owner_strip: int | None) -> tuple[int, ...]: ...
    def machines_for_strip(self, owner_strip: int) -> tuple[int, ...]: ...
    def carrying(self, item_id: str) -> tuple[int, ...]: ...
    def belts_carrying(self, item_id: str) -> tuple[int, ...]: ...
    def sorters_carrying(self, item_id: str) -> tuple[int, ...]: ...

    # link indexes (the edge source; see Graph ruling)
    def by_output_obj(self, index: int) -> tuple[int, ...]: ...
    def by_input_obj(self, index: int) -> tuple[int, ...]: ...
    def attached_to(self, index: int) -> tuple[int, ...]: ...
    def belts_into(self, index: int) -> tuple[int, ...]: ...
    def sorters_into(self, index: int) -> tuple[int, ...]: ...
    def sorters_out_of(self, index: int) -> tuple[int, ...]: ...
    def sorters_between(
        self, sources: Container[int], sinks: Container[int]
    ) -> tuple[int, ...]: ...

    # spatial
    def at_tile(self, x: int, y: int, z: Fraction | int | None = None) -> tuple[int, ...]: ...
    def in_box(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, ...]: ...
    def bounds(self) -> tuple[int, int, int, int]: ...

    # counts (so callers stop scanning to count)
    def count_by_kind(self, kind: Kind) -> int: ...
    def count_by_item(self, item_id: int) -> int: ...
```

`sorters_between` is the query the user asked for by name: it iterates the
**smaller** of the two endpoint sets and looks up incident sorters, rather than
walking all buildings once per group member.

- [ ] **Step 1: Write the failing test for the attribute indexes**

Create `tests/layout/test_buildings.py`:

```python
"""``Buildings`` answers from an index exactly what a brute-force scan answers."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.buildings import Buildings, Kind


def _fixture() -> tuple[PlacedBuilding, ...]:
    """A spread with every kind, repeated keys, ``None`` links and shared tiles."""
    belt = catalog.BELT_IDS[0] if isinstance(catalog.BELT_IDS, tuple) else next(iter(catalog.BELT_IDS))
    sorter = next(iter(catalog.SORTER_IDS))
    records: list[PlacedBuilding] = []
    for i in range(60):
        if i % 3 == 0:
            records.append(
                PlacedBuilding(
                    item_id=2303, model_index=0, x=i, y=0, width=3, height=3,
                    recipe_id=i % 4, owner_strip=i % 5,
                )
            )
        elif i % 3 == 1:
            records.append(
                PlacedBuilding(
                    item_id=belt, model_index=0, x=i, y=1,
                    output_obj=i + 2 if i + 2 < 60 else None,
                    carries_item=f"item-{i % 7}",
                )
            )
        else:
            records.append(
                PlacedBuilding(
                    item_id=sorter, model_index=0, x=i, y=2,
                    input_obj=i - 1, output_obj=(i + 1) % 60,
                    carries_item=f"item-{i % 7}",
                )
            )
    return tuple(records)


def test_by_item_matches_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for item_id in {b.item_id for b in records}:
        expected = tuple(i for i, b in enumerate(records) if b.item_id == item_id)
        assert index.by_item(item_id) == expected


def test_machines_for_recipe_matches_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for recipe_id in {b.recipe_id for b in records}:
        expected = tuple(
            i
            for i, b in enumerate(records)
            if b.recipe_id == recipe_id
            and not catalog.is_belt(b.item_id)
            and not catalog.is_sorter(b.item_id)
        )
        assert index.machines_for_recipe(recipe_id) == expected


def test_link_indexes_match_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for target in range(len(records)):
        assert index.by_output_obj(target) == tuple(
            i for i, b in enumerate(records) if b.output_obj == target
        )
        assert index.by_input_obj(target) == tuple(
            i for i, b in enumerate(records) if b.input_obj == target
        )
        assert index.sorters_into(target) == tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.output_obj == target
        )
        assert index.sorters_out_of(target) == tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.input_obj == target
        )


def test_missing_keys_answer_empty_not_raise() -> None:
    index = Buildings(_fixture())
    assert index.by_item(999_999) == ()
    assert index.machines_for_recipe(999_999) == ()
    assert index.by_output_obj(999_999) == ()
    assert index.by_index(999_999) is None
    assert index.by_index(None) is None
    assert index.by_index(-1) is None


def test_empty_sequence_is_answerable() -> None:
    index = Buildings(())
    assert len(index) == 0
    assert index.belts() == ()
    assert index.bounds() == (0, 0, 0, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_buildings.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'flab2bp.layout.buildings'`.

- [ ] **Step 3: Write `buildings.py`**

Create `src/flab2bp/layout/buildings.py`. The docstring must explain the backend
ruling, because the next reader will wonder where littletable went:

```python
"""One indexed view over a sequence of :class:`PlacedBuilding` records.

The layout pipeline asks the same few questions about a building sequence over
and over -- which machines run this recipe, which sorters feed that machine,
what sits on this tile -- and before this module every one of those questions
was a fresh linear scan, often inside a loop that already scaled with the
building count.

WHY A DICT AND NOT A TABLE LIBRARY

`littletable` and `polars` were both measured against real blueprints before
this module was written (see
``docs/superpowers/evidence/2026-09-07-buildings-index/backend-choice.md``).
Both LOSE to the linear scan they would replace at the sizes this project
produces -- 500 to 6000 buildings -- because each answers a lookup by
materialising a new container: on a 1969-building blueprint, one indexed
lookup costs 3246 us through littletable and 343 us through polars against a
141 us scan, while a plain dict answers in 0.2 us.  So the indexes here are
dicts built in one pass.

The backend is deliberately private to this module.  No caller imports a table
library, receives a backend object, or writes a query expression; every public
method is typed with this project's own types and returns positional building
indices.  Swapping the dicts for something else is a change to this file alone,
and ``tests/test_backend_containment.py`` fails if that boundary is breached.
"""

from __future__ import annotations

from collections.abc import Container, Iterator, Sequence
from enum import Enum
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding


class Kind(Enum):
    """What a building is, for the questions callers actually ask.

    Derived once per record from the catalog, so a call site never pays a
    ``catalog.is_belt`` lookup inside a loop again.
    """

    MACHINE = "machine"
    BELT = "belt"
    SORTER = "sorter"
    OTHER = "other"


def kind_for(item_id: int) -> Kind:
    if catalog.is_belt(item_id):
        return Kind.BELT
    if catalog.is_sorter(item_id):
        return Kind.SORTER
    if item_id in (catalog.SPLITTER_ID, catalog.PILER_ID):
        return Kind.OTHER
    return Kind.MACHINE


#: Every attribute the survey found a call site filtering on, and the accessor
#: that reads it.  Adding a key here adds an index; nothing else changes.
_EMPTY: tuple[int, ...] = ()


class Buildings:
    """An immutable indexed view over a building sequence."""

    __slots__ = (
        "_records",
        "_kinds",
        "_by_kind",
        "_by_item",
        "_by_recipe",
        "_by_owner_strip",
        "_by_carries",
        "_by_output_obj",
        "_by_input_obj",
        "_by_tile",
        "_bounds",
    )

    def __init__(self, records: Sequence[PlacedBuilding]) -> None:
        self._records: tuple[PlacedBuilding, ...] = tuple(records)
        kinds: list[Kind] = []
        by_kind: dict[Kind, list[int]] = {k: [] for k in Kind}
        by_item: dict[int, list[int]] = {}
        by_recipe: dict[int, list[int]] = {}
        by_owner_strip: dict[int | None, list[int]] = {}
        by_carries: dict[str, list[int]] = {}
        by_output_obj: dict[int, list[int]] = {}
        by_input_obj: dict[int, list[int]] = {}
        by_tile: dict[tuple[int, int], list[int]] = {}
        for i, b in enumerate(self._records):
            kind = kind_for(b.item_id)
            kinds.append(kind)
            by_kind[kind].append(i)
            by_item.setdefault(b.item_id, []).append(i)
            if kind is Kind.MACHINE:
                by_recipe.setdefault(b.recipe_id, []).append(i)
            by_owner_strip.setdefault(b.owner_strip, []).append(i)
            if b.carries_item is not None:
                by_carries.setdefault(b.carries_item, []).append(i)
            if b.output_obj is not None:
                by_output_obj.setdefault(b.output_obj, []).append(i)
            if b.input_obj is not None:
                by_input_obj.setdefault(b.input_obj, []).append(i)
            for dx in range(b.width):
                for dy in range(b.height):
                    by_tile.setdefault((b.x + dx, b.y + dy), []).append(i)
        self._kinds: tuple[Kind, ...] = tuple(kinds)
        self._by_kind = {k: tuple(v) for k, v in by_kind.items()}
        self._by_item = {k: tuple(v) for k, v in by_item.items()}
        self._by_recipe = {k: tuple(v) for k, v in by_recipe.items()}
        self._by_owner_strip = {k: tuple(v) for k, v in by_owner_strip.items()}
        self._by_carries = {k: tuple(v) for k, v in by_carries.items()}
        self._by_output_obj = {k: tuple(v) for k, v in by_output_obj.items()}
        self._by_input_obj = {k: tuple(v) for k, v in by_input_obj.items()}
        self._by_tile = {k: tuple(v) for k, v in by_tile.items()}
        self._bounds = self._compute_bounds()

    # NOTE: ``Buildings.of(placement)`` is deliberately NOT in this task.  It
    # needs the ``Placement.buildings_index`` field, which Task 3 adds; writing
    # it here would not type-check.  Task 3 Step 4 adds it.

    # --- identity / access -------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[PlacedBuilding]:
        return iter(self._records)

    def all(self) -> tuple[PlacedBuilding, ...]:
        return self._records

    def by_index(self, index: int | None) -> PlacedBuilding | None:
        """The record at ``index``, or ``None`` when it does not name one.

        Callers previously wrote ``0 <= i < len(buildings)`` guards at a dozen
        sites; this collapses all of them.  A NEGATIVE index is ``None``, not a
        Python tail lookup -- ``-1`` in this codebase means "no link".
        """
        if index is None or index < 0 or index >= len(self._records):
            return None
        return self._records[index]

    def kind_of(self, index: int) -> Kind:
        return self._kinds[index]

    # --- attribute indexes -------------------------------------------------

    def by_kind(self, kind: Kind) -> tuple[int, ...]:
        return self._by_kind.get(kind, _EMPTY)

    def machines(self) -> tuple[int, ...]:
        return self._by_kind[Kind.MACHINE]

    def belts(self) -> tuple[int, ...]:
        return self._by_kind[Kind.BELT]

    def sorters(self) -> tuple[int, ...]:
        return self._by_kind[Kind.SORTER]

    def by_item(self, item_id: int) -> tuple[int, ...]:
        return self._by_item.get(item_id, _EMPTY)

    def splitters(self) -> tuple[int, ...]:
        return self._by_item.get(catalog.SPLITTER_ID, _EMPTY)

    def machines_for_recipe(self, recipe_id: int) -> tuple[int, ...]:
        return self._by_recipe.get(recipe_id, _EMPTY)

    def by_owner_strip(self, owner_strip: int | None) -> tuple[int, ...]:
        return self._by_owner_strip.get(owner_strip, _EMPTY)

    def machines_for_strip(self, owner_strip: int) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_owner_strip.get(owner_strip, _EMPTY)
            if self._kinds[i] is Kind.MACHINE
        )

    def carrying(self, item_id: str) -> tuple[int, ...]:
        return self._by_carries.get(item_id, _EMPTY)

    def belts_carrying(self, item_id: str) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_carries.get(item_id, _EMPTY)
            if self._kinds[i] is Kind.BELT
        )

    def sorters_carrying(self, item_id: str) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_carries.get(item_id, _EMPTY)
            if self._kinds[i] is Kind.SORTER
        )

    # --- link indexes ------------------------------------------------------

    def by_output_obj(self, index: int) -> tuple[int, ...]:
        """Every building whose ``output_obj`` names ``index``."""
        return self._by_output_obj.get(index, _EMPTY)

    def by_input_obj(self, index: int) -> tuple[int, ...]:
        """Every building whose ``input_obj`` names ``index``."""
        return self._by_input_obj.get(index, _EMPTY)

    def attached_to(self, index: int) -> tuple[int, ...]:
        """Every building linked to ``index`` from either end, ascending."""
        return tuple(sorted(set(self.by_output_obj(index)) | set(self.by_input_obj(index))))

    def belts_into(self, index: int) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_output_obj.get(index, _EMPTY)
            if self._kinds[i] is Kind.BELT
        )

    def sorters_into(self, index: int) -> tuple[int, ...]:
        """Sorters that PUT DOWN at ``index`` (``output_obj == index``)."""
        return tuple(
            i for i in self._by_output_obj.get(index, _EMPTY)
            if self._kinds[i] is Kind.SORTER
        )

    def sorters_out_of(self, index: int) -> tuple[int, ...]:
        """Sorters that PICK UP at ``index`` (``input_obj == index``)."""
        return tuple(
            i for i in self._by_input_obj.get(index, _EMPTY)
            if self._kinds[i] is Kind.SORTER
        )

    def sorters_between(
        self, sources: Container[int], sinks: Container[int]
    ) -> tuple[int, ...]:
        """Sorters picking up in ``sources`` and putting down in ``sinks``.

        Drives off the sorter index rather than off the building list, which is
        the whole point: the old shape walked every building once per group
        member, and the group is always the smaller set.
        """
        return tuple(
            i
            for i in self._by_kind[Kind.SORTER]
            if self._records[i].input_obj in sources
            and self._records[i].output_obj in sinks
        )

    # --- spatial -----------------------------------------------------------

    def at_tile(
        self, x: int, y: int, z: Fraction | int | None = None
    ) -> tuple[int, ...]:
        """Buildings whose footprint covers ``(x, y)``, optionally at ``z``."""
        hits = self._by_tile.get((x, y), _EMPTY)
        if z is None:
            return hits
        return tuple(i for i in hits if self._records[i].z == z)

    def in_box(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, ...]:
        """Buildings whose footprint intersects the inclusive box."""
        seen: set[int] = set()
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                seen.update(self._by_tile.get((x, y), _EMPTY))
        return tuple(sorted(seen))

    def _compute_bounds(self) -> tuple[int, int, int, int]:
        if not self._records:
            return (0, 0, 0, 0)
        min_x = min(b.x for b in self._records)
        min_y = min(b.y for b in self._records)
        max_x = max(b.x + b.width - 1 for b in self._records)
        max_y = max(b.y + b.height - 1 for b in self._records)
        return (min_x, min_y, max_x, max_y)

    def bounds(self) -> tuple[int, int, int, int]:
        """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile."""
        return self._bounds

    # --- counts ------------------------------------------------------------

    def count_by_kind(self, kind: Kind) -> int:
        return len(self._by_kind.get(kind, _EMPTY))

    def count_by_item(self, item_id: int) -> int:
        return len(self._by_item.get(item_id, _EMPTY))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_buildings.py -x`
Expected: PASS.

`Buildings` in this task takes a plain `Sequence[PlacedBuilding]`; there is no
`of` classmethod and no import of `Placement` yet. Task 3 adds both, together
with the field `of` needs. Keeping them apart means this task's mypy run is
clean without a forward reference to a field that does not exist.

- [ ] **Step 5: Add the bounds test against a real blueprint**

Append to `tests/layout/test_buildings.py`:

```python
def test_bounds_matches_a_brute_force_scan_on_a_real_blueprint() -> None:
    from pathlib import Path

    from flab2bp.dsp.codec import decode

    fixture = (
        Path(__file__).parent.parent / "fixtures" / "factory-heretical-smelter-block.txt"
    )
    decoded = decode(fixture.read_text())
    records = tuple(
        PlacedBuilding(
            item_id=b.item_id,
            model_index=b.model_index,
            x=int(b.x),
            y=int(b.y),
            recipe_id=b.recipe_id,
            output_obj=b.output_obj_idx if b.output_obj_idx >= 0 else None,
            input_obj=b.input_obj_idx if b.input_obj_idx >= 0 else None,
        )
        for b in decoded.buildings
    )
    index = Buildings(records)
    xs = [b.x for b in records] + [b.x + b.width - 1 for b in records]
    ys = [b.y for b in records] + [b.y + b.height - 1 for b in records]
    assert index.bounds() == (min(xs), min(ys), max(xs), max(ys))
    for item_id in {b.item_id for b in records}:
        assert index.by_item(item_id) == tuple(
            i for i, b in enumerate(records) if b.item_id == item_id
        )
```

- [ ] **Step 6: Add the tile-index test**

Append to `tests/layout/test_buildings.py`:

```python
def test_at_tile_and_in_box_match_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)

    def covers(b: PlacedBuilding, x: int, y: int) -> bool:
        return b.x <= x < b.x + b.width and b.y <= y < b.y + b.height

    for x in range(-2, 64):
        for y in range(-2, 5):
            assert index.at_tile(x, y) == tuple(
                i for i, b in enumerate(records) if covers(b, x, y)
            )
    assert index.in_box(0, 0, 10, 3) == tuple(
        i
        for i, b in enumerate(records)
        if any(
            covers(b, x, y) for x in range(0, 11) for y in range(0, 4)
        )
    )


def test_sorters_between_drives_off_the_smaller_set() -> None:
    records = _fixture()
    index = Buildings(records)
    sources = {i for i in range(0, 60, 3)}
    sinks = {i for i in range(1, 60, 3)}
    assert index.sorters_between(sources, sinks) == tuple(
        i
        for i, b in enumerate(records)
        if catalog.is_sorter(b.item_id)
        and b.input_obj in sources
        and b.output_obj in sinks
    )
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/layout/test_buildings.py -x`
Expected: PASS.

- [ ] **Step 8: Run the full verification set**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest; echo "EXIT=$?"
```
Expected: ruff/format/mypy clean; pytest EXIT=1 with exactly the two known-red
tests failing (they fail on master too — confirm by name in the output).

- [ ] **Step 9: Write the backend-containment test**

Create `tests/test_backend_containment.py`:

```python
"""The index backend never leaks past ``layout/buildings.py``.

The user's ruling: whichever library backs the index, it is hidden behind the
domain abstraction.  Today the backend is plain dicts; if someone swaps in
``littletable`` or ``polars`` later, this test is what keeps the swap confined
to one file instead of spreading query expressions across the call sites.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "flab2bp"
BACKENDS = ("littletable", "polars", "networkx", "pandas")
OWNER = SRC / "layout" / "buildings.py"

_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(BACKENDS) + r")\b", re.MULTILINE
)


def test_no_module_outside_buildings_imports_an_index_backend() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{match.group(1)}"
        for path in SRC.rglob("*.py")
        if path != OWNER
        for match in _IMPORT.finditer(path.read_text())
    ]
    assert offenders == [], (
        "index-backend imports must stay inside layout/buildings.py; found: "
        + ", ".join(offenders)
    )


def test_buildings_public_methods_return_domain_types() -> None:
    """No public method may be annotated with a backend library's type."""
    source = OWNER.read_text()
    for backend in BACKENDS:
        assert f"{backend}." not in source or backend == "networkx", (
            f"{backend} type names must not appear in buildings.py's public surface"
        )
```

- [ ] **Step 10: Run it and commit**

```bash
uv run pytest tests/test_backend_containment.py tests/layout/test_buildings.py -x
export GIT_EDITOR=true
git add src/flab2bp/layout/buildings.py tests/layout/test_buildings.py tests/test_backend_containment.py
git commit -m "feat(layout): add an indexed Buildings abstraction

Replaces the repeated linear scans of building sequences with one domain
type whose queries are named for what callers ask.  Backed by dict indexes:
littletable and polars were both measured against real blueprints and both
lose to the scan they would replace at this project's sizes (evidence under
docs/superpowers/evidence/2026-09-07-buildings-index/)."
```

---

## Task 2: `MutableBuildings` for the live canvas

**Files:**
- Modify: `src/flab2bp/layout/buildings.py`
- Modify: `tests/layout/test_buildings.py`

**Interfaces:**
- Consumes: Task 1's `Buildings`, `Kind`, `kind_for`.
- Produces: `MutableBuildings`, a `MutableSequence[PlacedBuilding]` with the
  same query surface as `Buildings` plus the mutation grammar freeform needs.
  Task 10 substitutes it for `_Canvas.buildings`.

The mutation grammar it must support, and nothing more (§ Mutability):
tail-`append`, tail-`pop()`, and `__setitem__` at an existing index where only
`input_obj` / `output_obj` / `z` changed. Any other mutation raises, so a future
edit that breaks the assumption fails loudly instead of answering from a stale
index.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_buildings.py`:

```python
from flab2bp.layout.buildings import MutableBuildings


def test_append_keeps_every_index_correct() -> None:
    live = MutableBuildings(_fixture())
    extra = PlacedBuilding(item_id=2303, model_index=0, x=200, y=7, recipe_id=1)
    live.append(extra)
    records = tuple(live)
    assert live.by_item(2303) == tuple(
        i for i, b in enumerate(records) if b.item_id == 2303
    )
    assert live.machines_for_recipe(1) == tuple(
        i
        for i, b in enumerate(records)
        if b.recipe_id == 1 and kind_for(b.item_id) is Kind.MACHINE
    )
    assert live.at_tile(200, 7) == (len(records) - 1,)
    assert live.bounds() == Buildings(records).bounds()


def test_pop_truncates_every_index() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    live.append(PlacedBuilding(item_id=2303, model_index=0, x=200, y=7))
    live.pop()
    assert tuple(live) == records
    assert live.at_tile(200, 7) == ()
    for item_id in {b.item_id for b in records}:
        assert live.by_item(item_id) == Buildings(records).by_item(item_id)


def test_relink_updates_the_link_indexes_and_nothing_else() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    old = records[1]
    live[1] = replace(old, output_obj=42)
    assert 1 not in live.by_output_obj(old.output_obj or -1)
    assert 1 in live.by_output_obj(42)
    assert live.by_item(old.item_id) == Buildings(records).by_item(old.item_id)


def test_a_geometry_rewrite_raises_rather_than_answering_stale() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError, match="geometry"):
        live[0] = replace(live[0], x=999)


def test_a_non_tail_pop_raises() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError, match="tail"):
        live.pop(0)


def test_queries_match_a_rebuilt_index_after_a_mutation_sequence() -> None:
    """The staleness guard: after arbitrary legal mutation, every query agrees
    with a freshly built index over the same records."""
    live = MutableBuildings(_fixture())
    for n in range(20):
        live.append(
            PlacedBuilding(
                item_id=2303 if n % 2 else next(iter(catalog.SORTER_IDS)),
                model_index=0, x=100 + n, y=9, recipe_id=n % 3,
                input_obj=n, output_obj=n + 1, carries_item=f"item-{n % 7}",
            )
        )
    for _ in range(5):
        live.pop()
    live[3] = replace(live[3], output_obj=11)

    records = tuple(live)
    fresh = Buildings(records)
    assert live.bounds() == fresh.bounds()
    assert live.machines() == fresh.machines()
    assert live.belts() == fresh.belts()
    assert live.sorters() == fresh.sorters()
    for i in range(len(records)):
        assert live.by_output_obj(i) == fresh.by_output_obj(i)
        assert live.by_input_obj(i) == fresh.by_input_obj(i)
    for item_id in {b.item_id for b in records}:
        assert live.by_item(item_id) == fresh.by_item(item_id)
    for carried in {b.carries_item for b in records if b.carries_item}:
        assert live.carrying(carried) == fresh.carrying(carried)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_buildings.py -x -k Mutable or relink or pop or append`
Expected: FAIL with `ImportError: cannot import name 'MutableBuildings'`.

- [ ] **Step 3: Implement `MutableBuildings`**

Add to `src/flab2bp/layout/buildings.py`. Keep the indexes as `dict[key,
list[int]]` here (rather than tuples) so append is O(1); the public methods
return tuples, matching `Buildings`.

Required behaviour:

- `append(b)` — assigns index `len(self)`, adds it to every index bucket, and
  widens the cached bounds. O(footprint), not O(n).
- `pop(index=-1)` — only the tail; raise `ValueError("... tail ...")` otherwise.
  Removes the index from every bucket it is in, and **recomputes bounds** (a
  pop can shrink them and there is no cheap incremental answer; a pop happens
  once per rolled-back path prefix, not per query).
- `__setitem__(i, b)` — compares the new record against the old. If any of
  `item_id`, `model_index`, `x`, `y`, `width`, `height`, `owner_strip`,
  `recipe_id`, `carries_item` differs, raise
  `ValueError("MutableBuildings: geometry is immutable after insertion; ...")`.
  Otherwise update only the `by_output_obj` / `by_input_obj` buckets for the
  changed links and store the record.
- `insert(i, b)` — required by `MutableSequence`; raise `ValueError` unless
  `i == len(self)` (in which case delegate to `append`), because a mid-sequence
  insert would renumber every positional index in the tree.
- `__delitem__(i)` — same tail-only rule as `pop`.
- `snapshot() -> Buildings` — a frozen `Buildings` over the current records, for
  the places that want to hand an immutable view onward.

Every query method from Task 1's list must be present with identical
semantics. Share them by having both classes inherit a `_BuildingsQueries` mixin
that reads `self._by_*`, so the two cannot drift — a drift between the live and
frozen answers is exactly the class of bug that breaks byte-identical output.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/layout/test_buildings.py -x`
Expected: PASS.

- [ ] **Step 5: Full verification and commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest; echo "EXIT=$?"
export GIT_EDITOR=true
git add src/flab2bp/layout/buildings.py tests/layout/test_buildings.py
git commit -m "feat(layout): add MutableBuildings for the live routing canvas

Maintains the same indexes across the canvas's actual mutation grammar --
tail append, tail pop, and relinks that touch only input_obj/output_obj --
and raises on anything else rather than answering from a stale index."
```

---

## Task 3: Memoise `Placement.bounds` (highest-value single site)

**Files:**
- Modify: `src/flab2bp/layout/base.py:513-541`
- Modify: `src/flab2bp/layout/buildings.py` (add `Buildings.of`)
- Test: `tests/layout/test_base.py`

**Interfaces:**
- Consumes: Task 1's `Buildings`.
- Produces: `Placement.buildings_index: Buildings | None` (a lazily populated,
  `init=False`, `compare=False`, `repr=False` slot) and a `Placement.bounds`
  that answers from it. Later tasks call `Buildings.of(placement)` to get the
  shared index for any frozen placement.

**Why this task exists and why it is early:** `bounds` runs four full O(N) list
comprehensions per call, uncached, and the survey traced 24+ call sites across
`freeform.py`'s search loop, `finalize.py`'s frame-candidate loop and
`validate.py`. It is the largest single source of redundant scanning in the tree
and the change is six lines.

**Ruling carried into this task:** `base.py` is touched by the in-flight
`selfloop` branch, and the brief says to land contended files last. This one
lands early anyway: it is the highest-value site in the survey, and the change
is confined to one property plus one field, so a rebase conflict is a
three-line resolution. *Cost if wrong:* one small manual conflict resolution
when `selfloop` merges.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/test_base.py`:

```python
def test_bounds_is_memoised_and_matches_the_scan() -> None:
    from flab2bp.layout.base import PlacedBuilding, Placement

    records = tuple(
        PlacedBuilding(item_id=2303, model_index=0, x=i * 4, y=i, width=3, height=3)
        for i in range(20)
    )
    placement = Placement(buildings=records)
    xs = [b.x for b in records] + [b.x + b.width - 1 for b in records]
    ys = [b.y for b in records] + [b.y + b.height - 1 for b in records]
    assert placement.bounds == (min(xs), min(ys), max(xs), max(ys))
    # Second call answers from the memo, and answers the same.
    assert placement.bounds == (min(xs), min(ys), max(xs), max(ys))
    assert placement.buildings_index is not None


def test_replace_does_not_carry_a_stale_index() -> None:
    from dataclasses import replace as dc_replace

    from flab2bp.layout.base import PlacedBuilding, Placement

    first = Placement(
        buildings=(PlacedBuilding(item_id=2303, model_index=0, x=0, y=0),)
    )
    assert first.bounds == (0, 0, 0, 0)
    second = dc_replace(
        first,
        buildings=(PlacedBuilding(item_id=2303, model_index=0, x=10, y=10),),
    )
    assert second.buildings_index is None or len(second.buildings_index) == 1
    assert second.bounds == (10, 10, 10, 10)


def test_empty_placement_bounds_is_the_origin() -> None:
    from flab2bp.layout.base import Placement

    assert Placement(buildings=()).bounds == (0, 0, 0, 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/layout/test_base.py -x -k bounds`
Expected: FAIL — `Placement` has no attribute `buildings_index`.

- [ ] **Step 3: Add the field and rewrite the property**

In `src/flab2bp/layout/base.py`, add to `Placement` (after `completion`):

```python
    #: Lazily built index over :attr:`buildings`, shared by every caller that
    #: asks a question about this placement.  ``init=False`` so
    #: :func:`dataclasses.replace` never carries one placement's index onto
    #: another's records -- a stale index here would answer confidently and
    #: wrongly, which is worse than being slow.
    buildings_index: Buildings | None = field(
        default=None, init=False, compare=False, repr=False
    )
```

with `from flab2bp.layout.buildings import Buildings` imported under
`TYPE_CHECKING` and quoted in the annotation if a circular import appears
(`buildings.py` imports `PlacedBuilding` from `base.py`; use
`if TYPE_CHECKING:` plus `from __future__ import annotations`, which `base.py`
already has).

Replace the `bounds` property body:

```python
    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile.

        Answers from the placement's index.  This used to run four full list
        comprehensions over ``buildings`` on every call, and it is called from
        inside the freeform search loop and finalize's frame-candidate loop --
        24+ traced call sites, several of them per placement candidate.
        """
        from flab2bp.layout.buildings import Buildings

        return Buildings.of(self).bounds()
```

- [ ] **Step 4: Move `Buildings.of` into `buildings.py`**

Add the `of` classmethod exactly as written in Task 1 Step 3 (it was deferred
from that task because `Placement.buildings_index` did not exist yet).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/layout/test_base.py tests/layout/test_buildings.py -x`
Expected: PASS.

- [ ] **Step 6: Full verification — this one touches everything**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest; echo "EXIT=$?"
```
Expected: EXIT=1 with **only** the two known-red tests failing. `bounds` is on
so many paths that any other failure here means the memo is wrong — treat it as
a correctness bug, not a flake.

- [ ] **Step 7: Prove byte-identical output on a deterministic control**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "CPU:", sum/5}'
uv run python - <<'PY' > /tmp/bounds-after.txt
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout.base import DETERMINISTIC_WORKERS
print(len(URL_CORPUS))
PY
```
Then run the project's deterministic control for one small cell and diff the
blueprint string against master's. Record both in
`docs/superpowers/evidence/2026-09-07-buildings-index/task-3-control.md`.
If the strings differ, STOP — the memo has changed behaviour.

- [ ] **Step 8: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/layout/base.py src/flab2bp/layout/buildings.py tests/layout/test_base.py docs/superpowers/evidence/2026-09-07-buildings-index/task-3-control.md
git commit -m "perf(layout): memoise Placement.bounds behind the Buildings index

bounds ran four full O(N) comprehensions per call, uncached, from 24+ traced
call sites including freeform's search loop and finalize's frame-candidate
loop.  It now answers from the placement's lazily built index."
```

---

## Tasks 4-10: the per-file conversions

Each of these tasks converts **every site in one file** (or one batched group),
in the rank order established by the survey. They share one recipe, stated once
here; each task below names only its file, its site count, its WORTH rows and
its fixture.

### The conversion recipe (applies to Tasks 4-10)

1. Read your file's rows in the evidence table named in your task. It gives you
   `file:line`, the enclosing function, the holder scanned, the predicate keys,
   the nesting, the traced call frequency, the WORTH/HYGIENE verdict and the
   replacing query for **every** site.
2. Obtain the index once, at the widest scope where the sequence is stable —
   for a frozen placement that is `Buildings.of(placement)`; for a local
   sequence it is `Buildings(records)` hoisted out of the enclosing loop. **The
   whole point is to build once and query many.** Building a `Buildings` inside
   the loop you were trying to speed up is the one way to make this slower;
   the review will check for it.
3. Replace each scan with its named query. Preserve **order**: every query
   returns positional indices ascending, which matches `enumerate` order. Where
   the old code built a `dict` or `set` from the scan, keep the same container
   type at the call site.
4. Convert HYGIENE sites only where they become a one-liner against the index
   the function already holds. Leave the rest; say which in your report.
5. Add one test per converted site group asserting the converted query equals
   the brute-force predicate **on a real layout fixture**, not a synthetic one.
   Use the session-scoped placement fixtures in `tests/conftest.py` where the
   file already has them, or decode a blueprint from `tests/fixtures/`.
6. Verify: `uv run ruff check && uv run ruff format --check && uv run mypy`,
   then `uv run pytest; echo "EXIT=$?"` — EXIT=1 with only the two known reds.
7. Commit that file alone, with a message naming the site count and which
   quadratic sites went away.

### Task 4: `layout/finalize.py` — 19 sites, 7 WORTH

**Files:** Modify `src/flab2bp/layout/finalize.py`; Test `tests/layout/test_finalize.py`.
**Evidence rows:** `survey-layout-core.md`, `finalize.py` rows.

The WORTH rows are the frame-candidate certification path — `_power_nodes`
(:515, scan by power item_id), `_planet_sorters` (:556, scan by kind), and
`_projection_invariants` (:1818, which scans by kind for belt/sorter/addon and
internally triggers the two above, so one call costs five full passes). These
are cached per placement across the frame-candidate loop but still cost one real
scan per distinct placement candidate. Build one `Buildings.of(placement)` in
`_projection_invariants` and pass it down; `_power_nodes` becomes
`sum((index.by_item(i) for i in POWER_ITEM_IDS), ())` and `_planet_sorters`
becomes `index.sorters()`.

`first_projected_static_failure` (:883, :932) does a per-placement-candidate
scan plus a linear index search — convert with `by_index`.

Leave `_CleanupSurvivorGraph` alone: the survey found it is already an optimal
hand-rolled incremental index, and replacing it buys nothing.

### Task 5: `layout/slots.py` + `layout/junction.py` — 8 sites, 1 WORTH (batched)

**Files:** Modify `src/flab2bp/layout/slots.py`, `src/flab2bp/layout/junction.py`;
Test `tests/layout/test_slots_ports.py`, `tests/layout/test_junction.py`.

Small, same-shape, un-contended: one dispatch, one review.

`slots.py`: `sorter_seat_boxes` (:745) and `assign_belt_slots` (:1189, :1203,
:1209) each scan once per slot-assignment pass; `_assign_sorter_slots_only`
(:1273) once. Build one index at the top of each public entry point and use
`belts()` / `sorters()` / `by_item()`.

`junction.py`: `site_is_clear` (:133) and `check_ports` (:303, :307).

**Ruling on junction.py:** two independent survey passes — a caller-side grep
and an AST scan — agree that `junction.site_is_clear` and `junction.check_ports`
have **no production caller**. `freeform.py` has its own differently-shaped local
`_junction_site_is_clear` (freeform.py:5483) which is what it actually calls;
`hierarchy/compose.py` imports the module only for `keepout_cells`. Do **not**
delete them in this branch and do **not** invest in converting them: leave both
functions exactly as they are, and record them in the report as a deletion
candidate for the user. *Why:* deleting public API on a speedup branch is scope
the user did not ask for, and converting dead code is wasted effort that still
has to be reviewed. *Cost if wrong:* they stay as they are, which is the status
quo.

So Task 5 converts `slots.py` only, and its commit message says why
`junction.py` was left.

### Task 6: `dsp/*` + `bench/metrics.py` + `web/trace.py` — 37 sites, 6 WORTH (batched)

**Files:** Modify `src/flab2bp/dsp/colliders.py`, `src/flab2bp/dsp/splitter_ports.py`,
`src/flab2bp/dsp/codec.py`, `src/flab2bp/bench/metrics.py`.
**Evidence rows:** `survey-hierarchy-dsp-bench-web.md`, Part 2.

Mostly HYGIENE — several of these files already build their own spatial indexes
(`colliders.collisions`' 32-unit cell hash, `planet.candidate_pairs`' column
buckets) and those stay exactly as they are. Convert only:

- `colliders.paste_input_links` (:1630) and `_reverse_input_choices` (:1810),
  which hand-roll a reverse `output_obj -> predecessor` index per call.
- `splitter_ports._NodeIndex.build` (:112) — the survey calls this "a hand-rolled
  Buildings index already" and the direct precedent for the abstraction. Rebuild
  it on `Buildings`' link indexes.
- `splitter_ports._issues` (:460) — `splitters()`.
- `codec.placement_to_blueprint`'s splitter-anchor fixup (:285) — `belts()`.
- `bench/metrics.measure` (:56-76) — eight separate passes over the same
  sequence collapse to one `Buildings` and its `count_by_kind` /
  `count_by_item` / `sorters_between` calls. Offline code, but it is eight
  passes and they become one line each.

**Do not touch** `dsp/planet.py`. Its `collisions_at` fallback (:1104) is a
literal O(n^2) all-pairs generator, but the survey confirmed every caller
supplies pre-filtered `pairs`, so it is unreachable; and `candidate_pairs`'
incremental broad-phase (:1008) is deliberate. Record both in the report as
latent traps for the follow-up list. Likewise leave
`colliders.belt_crossings` (:1543): it is quadratic in shape but every caller
passes singleton lists after doing its own tile-bucketing.

Also record `splitter_ports.expected_placement_port` (:606) — it rebuilds the
full index on every call and has **zero callers repo-wide**. Report it; do not
convert or delete it.

### Task 7: `layout/hierarchy/contracts.py` + `compose.py` + `strip_variants.py` — 10 sites, 6 WORTH

**Files:** Modify those three; Test `tests/layout/hierarchy/` and
`tests/layout/test_strip_variants.py`.
**Evidence rows:** `survey-hierarchy-dsp-bench-web.md`, Part 1.

The three real wins:

- `contracts._belt_run` (:77-88) — an **O(n^2)** adjacency build: the inner scan
  rediscovers belts drawn off each splitter/piler junction. Replace the whole
  `onward`/`backward` construction with `Buildings`' `by_output_obj` /
  `by_input_obj`, built once per block. The BFS that follows stays as it is.
- `compose._lane` (:476) — builds a full reverse `output_obj` map **on every
  call**, and `_port` calls it twice per `LaneFlow` inside `_pack_at`'s net
  loop. Hoist one index per pack attempt.
- `strip_variants.projection_pitch_requirements` (:607) — the hottest call site
  in the whole survey by frequency: it runs unconditionally per candidate state
  in the sequence-pair anneal search. Build the index once per placement.

`contracts._machines_behind` (:64) and `compose._machines_behind` (:551) both
become `machines_for_strip`.

This file group is contended by `hierarchical-v4`; keep the diff tight.

### Task 8: `layout/validate.py` — 21 sites, 6 WORTH

**Files:** Modify `src/flab2bp/layout/validate.py`; Test `tests/layout/test_validate.py`.
**Evidence rows:** `survey-layout-core.md`, `validate.py` rows.

Highest total scan volume in the tree: one confirmed quadratic (`_addon_rides`,
called 3x uncached per `validate()` pass) plus ~25 single-pass `@check` scans
that each run once per build but compound to roughly 40N work per `validate()`.

`_context()` (:761-779) is where `Buildings` belongs: it already builds `kinds`,
`succ` and `pred` by hand. Build one `Buildings` there, hang it on `Context`,
and let the checks query it — that collapses about six of validate's own manual
index constructions into one.

Two algorithmic defects the survey found, both fixable here without any new
dependency, both worth doing while you are in the file:

- `_belt_reaches_any` (:4609) rescans **every sorter inside the pop loop**,
  making it O(V·S). Precompute the sorter edge index once from
  `Buildings.sorters_out_of` / `sorters_into`.
- `_close_over_junctions` (:4126) is a naive fixpoint that re-scans all
  junctions until nothing changes. Replace with a plain BFS over the `ctx.succ`
  that already exists.

**Leave alone**, with the graph survey as the reason: `_acyclic` (:3511, its
Finding output depends on first-found path order), `_build_runs` (:620),
`_unsprayed_belts` (:4920), `_run_components` (:4095), `_max_flow` (:5198),
`_propagate` (:6035), `_reachable_from_outside` (:4411).

Contended by `selfloop`.

### Task 9: `layout/freeform.py` part A — the frozen-side sites

**Files:** Modify `src/flab2bp/layout/freeform.py`; Test `tests/layout/test_freeform.py`.
**Evidence rows:** `survey-freeform.md`, every row whose holder is NOT
`canvas.buildings`.

Sites over prepared templates, placement records and pre-narrowed peer lists —
they read a sequence that does not mutate while they read it, so plain
`Buildings` applies:

- `_staged_static_projection_peers` (:1738) and `_coater_keepout_hits` (:5369) —
  both **quadratic-or-worse**, called per coater seat inside a per-strip x
  per-item loop. `peers_excluding_strip` via `by_owner_strip`, and `in_box`.
- `_building_collider_hits` (:5300) — quadratic, per router step. `at_tile` /
  `in_box`.
- `_protected_template_belt_indices` (:8883, :8886) and
  `_prepared_candidate_area_lower_bound` (:8904, :8911-8914) — two passes plus
  four min/max passes per prepared candidate; `belts()` and `bounds()`.
- `_core_bounds` (:6041-6044) — four separate full passes, four call sites;
  `bounds()`.
- `FreeformLayout._sweep` (:22195) — builds `dict(enumerate(placement.buildings))`
  inside the per-failure learning loop purely to serve `by_index`.

Split from Task 10 because 55 sites in one commit is not a reviewable diff.

### Task 10: `layout/freeform.py` part B — the live canvas

**Files:** Modify `src/flab2bp/layout/freeform.py`; Test `tests/layout/test_freeform.py`.
**Evidence rows:** `survey-freeform.md`, every row whose holder IS
`canvas.buildings`, plus the mutation table.

Make `_Canvas.buildings` a `MutableBuildings` (Task 2). Because it implements
`MutableSequence`, `list(canvas.buildings)`, `tuple(...)`, `len(...)`,
iteration, slicing, `canvas.buildings[i] = ...`, `.append(...)` and `.pop()` all
keep working unchanged — including the **four raw appends at 6960, 7321, 18302,
19267 and the tail-pop at 12444** that bypass `_Canvas.add`. That is exactly why
the wrapper goes on the list rather than in `add`.

Then convert:

- `_splitter_successors` (:12825) — a full scan recomputed at **four** call
  sites (12660, 12846, 12940, 12976). This becomes `by_input_obj`, and fixes
  the survey's finding that `_leads_back`'s three call sites all omit
  `splitter_successors` and so rebuild the index per call.
- `_tap_source` (:13294, :13319, :13353) — three quadratic scans per net per
  commit. `belts_into`, `attached_to`.
- `_commit_paths` (:12500, :12581, :12602) — the hand-rolled `into` reverse map
  and its incremental `refresh_predecessor` are subsumed by the maintained link
  indexes.
- `_route_all` (:9758) — `building_predecessors` **is** `belts_into`.
- `_Canvas.junction_is_clear` (:5935), `_place_coaters` (:18703, :18719),
  `_prepare_routing_problem` (:17445), `_prepared_junction_ban` (:5622, :5671),
  `_power_plan` (:15508) — `by_item`, `at_tile`, `machines`.
- `_bridge` (:18219, :18228) — quadratic per direct-insert candidate;
  `sorters_between`.
- The twelve guarded `canvas.buildings[i]` lookups (9791, 12760, 12799, 12948,
  12978, 13127, 13156, 13204, 13237, 13440, 13474, 9281) all become `by_index`.

**Leave the graph algorithms themselves alone** — `_committed_path_closes_cycle`'s
Tarjan SCC, `_leads_back`'s early-exit DFS, `_run_cells`' bounded BFS and
`_output_tail_nets`' DFS keep their algorithms; only the **adjacency they walk**
comes from the maintained index instead of a fresh scan. The graph survey
explains why converting the algorithms to a library would be slower.

This file is contended by both `coater-placed` and `hierarchical-v4`, so it
lands last.

---

## Task 11: Measurement and the paired corpus guard

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-buildings-index/profile.md`
- Create: `docs/superpowers/evidence/2026-09-07-buildings-index/corpus-guard.md`

Run at the branch's final HEAD. `git diff --stat -- src tests` against this
task's own commit must be empty when the evidence is written — the numbers must
describe the code that shipped.

- [ ] **Step 1: cProfile, before and after, on three cells**

One small, one mid, and `universe-matrix` at 60 (or the largest mall if that
cell refuses). Profile master at `2e861af0` and this branch's HEAD with the same
budget and `DETERMINISTIC_WORKERS`. Report cumulative time in each converted
function plus total wall. Record CPU pressure the vmstat way beside every
timing.

- [ ] **Step 2: Rule-W wall ratio on the eight largest cells**

Report the wall ratio (after / before) per cell and the aggregate. State plainly
which sites moved the numbers and which were hygiene — the brief requires that
distinction, and a conversion that removes a quadratic is worth landing even if
the profile does not move.

- [ ] **Step 3: Deterministic controls, 12 cells**

Run 12 corpus cells at `DETERMINISTIC_WORKERS` on both master and HEAD and
compare the exact blueprint strings. Any difference is a FAIL — report it as a
FAIL, do not explain it away.

- [ ] **Step 4: The paired corpus audit**

```bash
pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'   # must be 0 before you start
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "CPU:", sum/5}'
uv run python scripts/audit.py --budget 30 --json /tmp/audit-head.json
uv run python scripts/audit_compare.py /tmp/audit-master.json /tmp/audit-head.json
```

`audit.py` prints NOT CLEAN on any refusal, so the gate is **the compared counts
and the named differing cells**, not the CLEAN line. Master's baseline must be
captured from `2e861af0` with the same budget.

- [ ] **Step 5: Write the evidence and commit**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-buildings-index/
git commit -m "docs: profile and corpus guard for the buildings index"
```

---

## Follow-ups (not this branch)

- **`selfloop`'s marker sites.** The example the user was actually looking at —
  three list comprehensions over `enumerate(buildings)` inside a per-seed loop
  in `src/flab2bp/layout/markers.py`, filtering on `recipe_id`,
  `catalog.is_belt`, `catalog.is_sorter`, `carries_item`, `input_obj in
  group_machines`, `output_obj in group_machines`. That is exactly
  `machines_for_recipe` + `sorters_between(group_machines, group_machines)`,
  driving off the group rather than the buildings. Master's `markers.py` has 5
  sites, all HYGIENE; the quadratic ones arrive with `selfloop`. Convert after
  it merges.
- **`layout/junction.py` dead code.** `site_is_clear` and `check_ports` have no
  production caller (two independent passes agree). Ask the user whether to
  delete them or wire them back in place of `freeform.py`'s local duplicate
  `_junction_site_is_clear`.
- **`dsp/splitter_ports.expected_placement_port`** — zero callers repo-wide, and
  it rebuilds the full node index on every call. Delete or wire up.
- **`dsp/planet.collisions_at`'s `pairs=None` fallback** — a literal O(n^2)
  all-pairs generator, currently unreachable because every caller pre-filters.
  A latent trap if a future caller omits `pairs`.
- **`dsp/colliders.belt_crossings`** — quadratic in shape, safe only because
  every caller passes singleton lists after its own tile-bucketing. Worth an
  assertion that the inputs are singletons.
