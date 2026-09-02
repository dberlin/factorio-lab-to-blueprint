# Phase B Last-Mile Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the one or two nets that stay unrouted after rip-up-and-reroute on the largest corpus cells into either a routed pack or a proved no-good, so that freeform `quantum-chip/all-products` and freeform `universe-matrix/output-products` become CLEAN at a 30-second budget with no cell regressing.

**Architecture:** After the last rip-up round and its repair passes, `_route_all` builds a conflict cluster of at most eight nets (the stranded nets plus the nets their blame walls and blocker lists name), releases their committed paths, and runs conflict-based search over them: the existing Cython-backed `_astar` at the low level with per-net forbidden cells, a Python best-first tree at the high level splitting on the first shared cell. A solution is staked and committed through the round's own preflight; a closed tree is a proof that becomes an `ExactPackNoGood` through machinery that already exists but has never had a producer, and — when a second run over an environment stripped of every other belt also closes — a new `ClusterRelationNoGood` that forbids the cluster strips' relative placement in both packers.

**Tech Stack:** Python 3.14, `uv run`, pytest (serial), Ruff, strict MyPy, OR-Tools CP-SAT 9.15.6755, the Phase A Cython routing kernel (used, not modified).

**Spec:** `docs/superpowers/specs/2026-09-02-phase-b-last-mile-router-design.md`

## Global Constraints

- Every `file:line` below was taken at commit `b3c990a` and is a hint only: resolve each target by symbol name (Serena `find_symbol`) before editing, and enumerate call sites with Serena `find_referencing_symbols`, never with grep alone (grep misses sites; it is for strings, comments, and config). When a step says "grep for X" and X is a Python symbol, use Serena; grep only cross-checks `getattr`-style dynamic dispatch.
- **Symbol-tool activation (every implementer and reviewer, first thing):** the tools are deferred, so load them explicitly: `ToolSearch("select:mcp__serena__activate_project,mcp__serena__initial_instructions,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,LSP")`, then call `mcp__serena__activate_project` with the absolute path of the checkout you are editing (the worktree, not the main repository), then `mcp__serena__initial_instructions`. The repository tracks `.serena/project.yml`, so every worktree is its own Serena project once activated at its own path. If `find_symbol` errors or returns nothing for a symbol that exists, use the `LSP` tool (goToDefinition / findReferences) instead. If both fail, stop and report NEEDS_CONTEXT; never substitute grep.
- No change to strip planning, variant generation, or band policy.
- No ALNS, no new destroy/repair operators, no scheduling change (Phase C).
- No deadline-overshoot fix, no racing, no cross-process sharing (Phase D).
- No learned component, and no retuning of `RRR_MAX = 8`, `_SINGLE_ROUND_NETS = 64`, `_RRR_STALE_ROUNDS = 3`, `_REPAIR_PASSES = 4`, `_REPAIR_MAX_VICTIMS = 16`, `_MAX_EXPANSIONS = 200_000`, `_ROUTING_BUDGET = 2_000_000`, `LEVELS = 4`, or any congestion weight.
- No Cython in this phase. The CBS high level is Python over the already compiled low-level `_astar`.
- No change to CLI, web, or pipeline interfaces. `scripts/route_bench.py` and `scripts/last_mile_bench.py` are developer tools.
- No fallback corridor tier and no relaxation of validator rules: a cluster solution is committed through `_commit_paths` or it is not committed.
- Budget and deadline failures never create a no-good. Only a closed CBS tree with no `BUDGET`-kind failure among the remainder does.
- **Any low-level search returning `RouteFailureKind.BUDGET` forces the whole cluster run to `BOUNDED`.** A tree that closes only because a search was cut short is not a complete search. This holds for the private `B_LOW_LEVEL_EXPANSIONS = 50_000` allowance, for the shared expansion floor, and for the deadline.
- Run 1 and run 2 share **one** expansion allowance: the floor is computed once at pass entry as `budget["left"] - int(B_CBS_EXPANSION_SHARE * budget["left"])` and the same value is passed to both.
- Every low-level search runs against a private budget dict capped at `B_LOW_LEVEL_EXPANSIONS = 50_000`, with the spend written back to the shared `budget["left"]` afterwards. This bounds how far past a bound check one search can run; `_MAX_EXPANSIONS = 200_000` is four times too coarse for a pass that makes hundreds of searches.
- The last-mile pass never raises to signal a restore failure. A mismatch between the recorded and restored round degrades the outcome to `BOUNDED` and increments `last_mile_restore_mismatch`. An `AssertionError` inside `_route_all` becomes a CRASH row in `scripts/audit.py` and fails the gate on the wrong condition; the exact-equality assertion belongs in the test suite only.
- No on-disk or cross-process cache of geometry (carried over from Phase A).
- Cython is the one compiled toolchain (carried over from Phase A).
- Each task is a separate commit that leaves the tree green: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` (no new diagnostic against the locked baseline of 176 pre-existing errors).
- Run the full test suite from the repo root with `uv run pytest -q` (serial; never `-n auto`, CP-SAT already saturates the box).
- Build the extensions before any test that touches routing: `uv run python setup.py build_ext --inplace`.
- Evidence files are tracked under `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/`. The `.superpowers/sdd/` workspace is git-ignored.
- Timing measurements only on an idle box. `git diff` needs `--no-ext-diff`.
- Corpus gate: `scripts/audit.py --budget 30 --jobs 16`, both strategies, three rounds against this plan's Task 1 baselines; freeform `quantum-chip/all-products` and freeform `universe-matrix/output-products` CLEAN in every round; no cell CLEAN in the baseline non-CLEAN in a candidate round; INVALID 0; CRASH 0; paired area ratio at most `1 + 0.013`; wall p95 per cell at or under **31 s**. Target 67/72 or better; record whatever it is.
- Wall p95 is Phase D's problem, not this phase's. The Phase A round files already sit above 30 s (p95 30.53 s, 30.67 s, 30.37 s), so the threshold is the worst of those rounded up: `--p95-seconds 31`. The gate record carries the line "wall p95 inherited from Phase A, owned by Phase D".
- `scripts/audit.py` rows carry no `stats` object. The `last_mile_*` counters reach the gate record only through `scripts/route_profile.py --json` on the two target cells. Never read `row["stats"]` from an audit JSONL: it yields zeros and reads as "the pass never ran".
- Known test facts carried over from Phase A: the two wall-clock tests `TestDirectInsertion::test_the_sweep_prefers_area_over_direct_insertion` (0.5 s) and `TestTheTimeBudgetIsAWall::test_magnetic_ring_repeated_one_second_calls_complete` (1.0 s) in `tests/layout/test_freeform.py` were removed from the tree during Phase B (Ruling S) because they flake under load and cost every implementer reruns; restoring them with a deterministic or scaled budget is a follow-up. `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` runs at a 1.5 s budget and trips DID NOT RAISE when preparation gets faster.
- Commit messages: imperative, sentence case, no trailing period, e.g. `feat(layout): add a bounded conflict-based last-mile router`.
- A step whose measurement misses its stated goal is not committed as if it passed: record the numbers and report.
- **Task ordering notes.** (a) The brief suggested the stranded-state capture in Task 1. Its only sound hook is `last_mile.CAPTURE`, which does not exist until Task 2, so Task 1 delivers the baselines, the `--policy` flag and the pre-change replay digests, and Task 9 delivers `--stranded`. (b) Integration and the commit path are one task (Task 4): the `offers` capability and the staking code have no reader until the commit path exists, so splitting them would ship dead code in a green commit. (c) The relation no-good is two tasks (6 and 7): the CP-SAT modelling is independently reviewable and testable without the relaxed run that produces its input.

---

### Task 1: Baseline evidence, capture policies, and pre-change replay digests

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/baseline-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/route-cases-universe-matrix-output-products.pkl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/route-cases-quantum-chip-all-products.pkl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/digests-before.txt`
- Modify: `scripts/route_bench.py:93-179` (`capture`), `:260-277` (`main`)
- Test: `tests/scripts/test_route_bench_policy.py`

**Interfaces:**
- Consumes: `scripts/audit.py --budget --jobs --json`, `scripts/audit_compare.py` CLI, `flab2bp.rates.CandidatePolicy` (`NO_PROLIFERATOR`, `ALL_PRODUCTS`, `OUTPUT_PRODUCTS`), `flab2bp.bench.corpus.URL_CORPUS`.
- Produces: `scripts/route_bench.py::capture(url_id: str, budget: float, every: int, cap: int, out: Path, policy: CandidatePolicy) -> None` and the CLI flag `--policy`. Every later task uses `--policy` to reach the two Phase B target cells.

- [ ] **Step 1: Generate the Phase B baselines on the starting master**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint
git log --oneline -1
mkdir -p docs/superpowers/evidence/2026-09-02-phase-b-last-mile
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
for r in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 --json "$d/baseline-budget30-round$r.jsonl" | tail -4
done
wc -l $d/*.jsonl
```

Expected: 72 lines in each file, about 3 minutes each, and the same seven REFUSED cells the Phase A round files hold. Record each round's clean count in the commit message. If a round differs from 65/72 by more than one cell, say so in the commit message and continue: this file, not the Phase A file, is the gate's baseline.

- [ ] **Step 2: Write the failing test for the capture policy flag**

```python
# tests/scripts/test_route_bench_policy.py
from __future__ import annotations

import inspect

from flab2bp.rates import CandidatePolicy

from scripts import route_bench


def test_capture_accepts_a_candidate_policy() -> None:
    signature = inspect.signature(route_bench.capture)
    assert "policy" in signature.parameters
    assert signature.parameters["policy"].default is CandidatePolicy.NO_PROLIFERATOR


def test_cli_parses_every_candidate_policy() -> None:
    parser = route_bench.build_parser()
    for policy in CandidatePolicy:
        parsed = parser.parse_args(["--capture", "graphene", "--policy", policy.value])
        assert parsed.policy is policy
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/scripts/test_route_bench_policy.py -v`
Expected: FAIL with `AssertionError: assert 'policy' in ...` on the first test and `AttributeError: module 'scripts.route_bench' has no attribute 'build_parser'` on the second.

- [ ] **Step 4: Add the policy parameter and factor the parser out**

In `scripts/route_bench.py`, change `capture`'s signature and its candidate construction:

```python
def capture(
    url_id: str,
    budget: float,
    every: int,
    cap: int,
    out: Path,
    policy: CandidatePolicy = CandidatePolicy.NO_PROLIFERATOR,
) -> None:
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]
```

Replace the body of `main` with a factored parser plus a call:

```python
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture")
    ap.add_argument("--budget", type=float, default=4.0)
    ap.add_argument("--every", type=int, default=8)
    ap.add_argument("--cap", type=int, default=64)
    ap.add_argument("--cases", type=Path)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--landmarks", type=int)
    ap.add_argument(
        "--policy",
        type=CandidatePolicy,
        choices=tuple(CandidatePolicy),
        default=CandidatePolicy.NO_PROLIFERATOR,
    )
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.capture:
        out = args.cases or Path(f"/tmp/route-cases-{args.capture}-{args.policy.value}.pkl")
        capture(args.capture, args.budget, args.every, args.cap, out, args.policy)
        return 0
    if not args.cases:
        ap.error("--cases or --capture required")
    return bench(args.cases, args.rounds, args.check, args.landmarks)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/scripts/test_route_bench_policy.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 6: Capture the two target cells and record their digests**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python setup.py build_ext --inplace
uv run python scripts/route_bench.py --capture universe-matrix --policy output-products \
  --budget 30 --every 8 --cap 64 --cases "$d/route-cases-universe-matrix-output-products.pkl"
uv run python scripts/route_bench.py --capture quantum-chip --policy all-products \
  --budget 30 --every 8 --cap 64 --cases "$d/route-cases-quantum-chip-all-products.pkl"
{
  uv run python scripts/route_bench.py --cases "$d/route-cases-universe-matrix-output-products.pkl" --rounds 3 --check
  uv run python scripts/route_bench.py --cases "$d/route-cases-quantum-chip-all-products.pkl" --rounds 3 --check
} | tee "$d/digests-before.txt"
```

Expected: each capture prints `captured 64 of N searches -> …` and each check prints a `BEST …` line followed by `captured digest X   replay digest X   MATCH`. Both exit 0. These two digests are the parity oracle for Tasks 4 and 11.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check scripts/route_bench.py tests/scripts/test_route_bench_policy.py
uv run mypy scripts/route_bench.py
uv run pytest -q
git add scripts/route_bench.py tests/scripts/test_route_bench_policy.py docs/superpowers/evidence/2026-09-02-phase-b-last-mile
git commit -m "bench: record phase B baselines and capture per candidate policy"
```

---

### Task 2: Cluster construction in `last_mile.py`

**Files:**
- Create: `src/flab2bp/layout/last_mile.py`
- Test: `tests/layout/test_last_mile.py`

**Interfaces:**
- Consumes: nothing at runtime. `_Canvas`, `_Grid`, `_Net` and `_PathSearchResult` appear only under `if TYPE_CHECKING:` so `freeform` can import this module without a cycle.
- Produces:

```python
Cell = tuple[int, int, int]
B_MAX_STRANDED: int = 3
B_MAX_CLUSTER: int = 8
B_MAX_CBS_NODES: int = 512
B_MAX_CONSTRAINTS: int = 64
B_CBS_EXPANSION_SHARE: float = 0.25
B_LOW_LEVEL_EXPANSIONS: int = 50_000
B_MIN_SECONDS: float = 0.35
B_UNROUTED_COST: int = 1_000_000

class ClusterOutcome(StrEnum): SOLVED, PROVED, BOUNDED

@dataclass(frozen=True, slots=True)
class ClusterProblem:
    nets: tuple[int, ...]
    stranded: tuple[int, ...]
    truncated: bool
    sibling_closed: bool

def build_cluster(
    stranded: Sequence[int],
    *,
    walls: Mapping[int, tuple[Cell, ...]],
    blockers: Mapping[int, tuple[int, ...]],
    owner: Mapping[Cell, int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
    src_group: Mapping[int, tuple[int, ...]],
    dst_group: Mapping[int, tuple[int, ...]],
    max_cluster: int = B_MAX_CLUSTER,
) -> ClusterProblem: ...

def cluster_strips(
    problem: ClusterProblem,
    net_strips: Mapping[int, tuple[int | None, int | None]],
) -> tuple[int, ...]: ...
```

There is no `strip_count` bound: `_route_all` does not know how many strips the pack holds, and `relation_no_good` (Task 6) already drops any index outside `range(len(origins))`, so a bound here would be inert or wrong.

- [ ] **Step 1: Write the failing tests**

Import only what this task uses. Task 3 adds the rest at the top of the file as its own step: importing them here would leave five unused names and fail `uv run ruff check .` (F401) at this task's commit.

```python
# tests/layout/test_last_mile.py
from __future__ import annotations

from flab2bp.layout import last_mile

Cell = tuple[int, int, int]


def _endpoints(count: int) -> dict[int, tuple[Cell | None, Cell]]:
    return {index: ((index, 0, 0), (index, 9, 0)) for index in range(count)}


def test_a_wall_names_its_owners_as_cluster_members() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ((5, 5, 0), (5, 6, 0))},
        blockers={0: ()},
        owner={(5, 5, 0): 2, (5, 6, 0): 3},
        paths={2: ((5, 5, 0),), 3: ((5, 6, 0),)},
        endpoints=_endpoints(4),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (0, 2, 3)
    assert problem.stranded == (0,)
    assert problem.truncated is False


def test_blockers_are_added_even_when_the_wall_is_empty() -> None:
    problem = last_mile.build_cluster(
        [1],
        walls={1: ()},
        blockers={1: (4,)},
        owner={},
        paths={},
        endpoints=_endpoints(5),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (1, 4)


def test_a_stranded_net_with_no_evidence_clusters_alone() -> None:
    problem = last_mile.build_cluster(
        [2],
        walls={2: ()},
        blockers={2: ()},
        owner={},
        paths={},
        endpoints=_endpoints(3),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (2,)
    assert problem.truncated is False


def test_growth_is_transitive_until_the_cap_then_truncates_by_distance() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0), (2, 0, 0), (3, 0, 0))},
        blockers={0: ()},
        owner={(1, 0, 0): 1, (2, 0, 0): 2, (3, 0, 0): 3},
        paths={1: ((1, 0, 0),), 2: ((2, 0, 0),), 3: ((3, 0, 0),)},
        endpoints=_endpoints(4),
        src_group={},
        dst_group={},
        max_cluster=3,
    )

    # Net 0's endpoints are (0, 0, 0) and (0, 9, 0); the two nearest owners win.
    assert problem.nets == (0, 1, 2)
    assert problem.truncated is True


def test_a_sibling_outside_the_cluster_makes_it_not_sibling_closed() -> None:
    closed = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0),)},
        blockers={0: ()},
        owner={(1, 0, 0): 1},
        paths={1: ((1, 0, 0),)},
        endpoints=_endpoints(3),
        src_group={0: (1,), 1: (0,)},
        dst_group={},
    )
    leaking = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0),)},
        blockers={0: ()},
        owner={(1, 0, 0): 1},
        paths={1: ((1, 0, 0),)},
        endpoints=_endpoints(3),
        src_group={0: (2,)},
        dst_group={},
    )

    assert closed.sibling_closed is True
    assert leaking.sibling_closed is False


def test_cluster_strips_are_ascending_and_drop_missing_owners() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ()},
        blockers={0: (1,)},
        owner={},
        paths={},
        endpoints=_endpoints(2),
        src_group={},
        dst_group={},
    )

    strips = last_mile.cluster_strips(problem, {0: (3, None), 1: (1, 3)})

    assert strips == (1, 3)


def test_an_empty_stranded_list_is_refused() -> None:
    try:
        last_mile.build_cluster(
            [],
            walls={},
            blockers={},
            owner={},
            paths={},
            endpoints={},
            src_group={},
            dst_group={},
        )
    except ValueError as exc:
        assert "stranded" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("an empty cluster must be refused")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_last_mile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flab2bp.layout.last_mile'` (collection error).

- [ ] **Step 3: Create the module with its constants, types and cluster construction**

```python
# src/flab2bp/layout/last_mile.py
"""A bounded, complete last-mile search over a small conflict cluster.

The rip-up-and-reroute loop in :func:`flab2bp.layout.freeform._route_all` is
greedy sequential routing with a displacement repair.  When it finishes with a
net or two still unrouted it has proved nothing: the pack is discarded and the
only thing that survives is decaying feedback.  This module is the missing
proof.  Given the handful of nets that failed and the nets their blame walls
accuse, it searches JOINTLY over all of them -- conflict-based search, with the
router's own A* at the low level -- and returns one of exactly three answers:
a disjoint routing for every cluster net, a closed tree that proves there is
none, or "a bound fired and nothing is claimed".

NOTHING HERE IMPORTS ``freeform`` AT RUNTIME.  Every canvas, grid and net type
is behind ``TYPE_CHECKING`` (added in the next task, with the search) and every
capability the search needs arrives as a callable on
:class:`ClusterEnvironment`, because ``_route_all``'s ends, stake, unstake and
blocker machinery are closures over one routing pass and cannot be imported.
That also makes the whole module testable on hand-built grids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

Cell = tuple[int, int, int]

#: The largest stranded set a cluster search is offered.  Both Phase B target
#: cells refuse with ONE net unrouted on their best pack; three leaves room for
#: the worst observed pack without inviting a cluster nobody can close.
B_MAX_STRANDED = 3

#: The largest cluster.  Packs on these cells hold 100-150 nets, and the
#: measurement in ``_repair``'s docstring is that a stranded net crosses between
#: 1 and 11 already-placed paths, so eight is a real neighbourhood rather than
#: a token one.
B_MAX_CLUSTER = 8

#: High-level CBS nodes per run.
B_MAX_CBS_NODES = 512

#: Constraints on one CBS node.  Reaching it ends the run as BOUNDED rather
#: than pruning the branch: a pruned branch would make a closed tree a lie.
B_MAX_CONSTRAINTS = 64

#: Share of the routing pass's remaining expansion budget one run may spend.
B_CBS_EXPANSION_SHARE = 0.25

#: Remaining wall seconds below which the pass declines to start.
B_MIN_SECONDS = 0.35

#: Cost charged for a cluster net with no path, so nodes that lost a net sort
#: after nodes that kept one without special-casing the heap.
B_UNROUTED_COST = 1_000_000

_FAR = 1 << 30


class ClusterOutcome(StrEnum):
    """What one cluster search established."""

    SOLVED = "solved"
    PROVED = "proved"
    BOUNDED = "bounded"


@dataclass(frozen=True, slots=True)
class ClusterProblem:
    """The nets one cluster search may move, and what is known about them."""

    nets: tuple[int, ...]
    stranded: tuple[int, ...]
    truncated: bool
    sibling_closed: bool

    def __post_init__(self) -> None:
        if not self.nets:
            raise ValueError("a cluster problem needs at least one net")
        if tuple(sorted(self.nets)) != self.nets:
            raise ValueError("cluster nets must be ascending")
        if not set(self.stranded) <= set(self.nets):
            raise ValueError("every stranded net must be a cluster member")


def _anchor_cells(
    index: int,
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
) -> tuple[Cell, ...]:
    path = paths.get(index)
    if path:
        return path
    ends = endpoints.get(index)
    if ends is None:
        return ()
    source, destination = ends
    return tuple(cell for cell in (source, destination) if cell is not None)


def _distance_to_stranded(
    candidate: int,
    stranded: Sequence[int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
) -> int:
    """Manhattan distance from a candidate's cells to any stranded endpoint."""
    cells = _anchor_cells(candidate, paths, endpoints)
    best = _FAR
    for seed in stranded:
        ends = endpoints.get(seed)
        if ends is None:
            continue
        for target in ends:
            if target is None:
                continue
            for cell in cells:
                value = abs(cell[0] - target[0]) + abs(cell[1] - target[1])
                if value < best:
                    best = value
    return best


def build_cluster(
    stranded: Sequence[int],
    *,
    walls: Mapping[int, tuple[Cell, ...]],
    blockers: Mapping[int, tuple[int, ...]],
    owner: Mapping[Cell, int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
    src_group: Mapping[int, tuple[int, ...]],
    dst_group: Mapping[int, tuple[int, ...]],
    max_cluster: int = B_MAX_CLUSTER,
) -> ClusterProblem:
    """Close the stranded nets over their accusers, bounded by ``max_cluster``."""
    seeds = tuple(sorted(dict.fromkeys(stranded)))
    if not seeds:
        raise ValueError("a cluster needs at least one stranded net")
    members = set(seeds)
    cluster = list(seeds)
    truncated = False
    frontier: list[int] = list(seeds)
    while frontier:
        candidates: set[int] = set()
        for index in frontier:
            for cell in walls.get(index, ()):
                holder = owner.get(cell)
                if holder is not None and holder not in members:
                    candidates.add(holder)
            for holder in blockers.get(index, ()):
                if holder not in members:
                    candidates.add(holder)
        if not candidates:
            break
        room = max_cluster - len(cluster)
        if room <= 0:
            truncated = True
            break
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                _distance_to_stranded(candidate, seeds, paths, endpoints),
                candidate,
            ),
        )
        if len(ordered) > room:
            truncated = True
            ordered = ordered[:room]
        cluster.extend(ordered)
        members.update(ordered)
        frontier = ordered
    cluster.sort()
    sibling_closed = all(
        sibling in members
        for index in cluster
        for sibling in (*src_group.get(index, ()), *dst_group.get(index, ()))
    )
    return ClusterProblem(
        nets=tuple(cluster),
        stranded=seeds,
        truncated=truncated,
        sibling_closed=sibling_closed,
    )


def cluster_strips(
    problem: ClusterProblem,
    net_strips: Mapping[int, tuple[int | None, int | None]],
) -> tuple[int, ...]:
    """Ascending strip instances the cluster's nets attach to."""
    instances: set[int] = set()
    for index in problem.nets:
        ends = net_strips.get(index)
        if ends is None:
            continue
        for strip in ends:
            if strip is not None and strip >= 0:
                instances.add(strip)
    return tuple(sorted(instances))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_last_mile.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/last_mile.py tests/layout/test_last_mile.py
uv run mypy src/flab2bp/layout/last_mile.py
git add src/flab2bp/layout/last_mile.py tests/layout/test_last_mile.py
git commit -m "feat(layout): build a bounded conflict cluster from stranded nets"
```

---

### Task 3: The CBS core on hand-built grids

**Files:**
- Modify: `src/flab2bp/layout/last_mile.py` (append `ClusterResult`, `ClusterEnvironment`, `solve_cluster`)
- Test: `tests/layout/test_last_mile.py`

**Interfaces:**
- Consumes: `ClusterProblem`, `B_MAX_CBS_NODES`, `B_MAX_CONSTRAINTS`, `B_UNROUTED_COST` from Task 2; `flab2bp.layout.freeform._astar` and `_Canvas` in the tests only.
- Produces:

```python
class ClusterBound(StrEnum):
    NONE = ""                  # the run reached a decision on its own
    NODES = "nodes"
    CONSTRAINTS = "constraints"
    BUDGET = "budget"          # the shared floor, or a cut low-level search
    WALL = "wall"

@dataclass(frozen=True, slots=True)
class ClusterResult:
    outcome: ClusterOutcome
    paths: Mapping[int, tuple[Cell, ...]]
    nodes: int
    expansions: int
    seconds: float
    bound: ClusterBound = ClusterBound.NONE

@dataclass(frozen=True, slots=True)
class ClusterEnvironment:
    search: Callable[[int, frozenset[Cell]], _PathSearchResult]
    offers: Callable[[int], _Offers]
    budget_left: Callable[[], int]
    budget_floor: int
    expired: Callable[[], bool]
    max_nodes: int = B_MAX_CBS_NODES
    max_constraints: int = B_MAX_CONSTRAINTS

_Offers = tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]]

def solve_cluster(
    problem: ClusterProblem,
    environment: ClusterEnvironment,
) -> ClusterResult: ...
```

`offers` is not read by `solve_cluster`; it is the capability the caller uses to re-query `_ends` at stake time (Task 4). It lives on the environment because it is the same object the caller already builds and because a side-table of offers collected during the search would be stale by the time staking starts.

- [ ] **Step 1: Extend the test module's imports and write the failing tests**

First add the imports this task needs to the **top** of `tests/layout/test_last_mile.py`, beside the `from flab2bp.layout import last_mile` line Task 2 wrote — never mid-file, which is `E402`:

```python
import flab2bp.layout.freeform as freeform_module
from flab2bp.layout.freeform import _astar, _Canvas, _PathSearchResult
from flab2bp.layout.route_feedback import RouteFailureKind
```

Then append:

```python
def _offers_stub(_index: int) -> last_mile._Offers:
    return ({}, {}, {})


def _grid_environment(
    canvas: _Canvas,
    bounds: tuple[int, int, int, int],
    ends: dict[int, tuple[list[Cell], set[Cell]]],
    *,
    budget: dict[str, int] | None = None,
    max_nodes: int = last_mile.B_MAX_CBS_NODES,
) -> last_mile.ClusterEnvironment:
    """A CBS environment whose low level is the real router's A*."""
    left = {"left": 1 << 30} if budget is None else budget

    def search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        starts, goals = ends[index]
        return _astar(
            canvas,
            list(starts),
            set(goals),
            {},
            1.0,
            bounds,
            left,
            None,
            None,
            None,
            (),
            (),
            constraints,
            None,
        )

    return last_mile.ClusterEnvironment(
        search=search,
        offers=_offers_stub,
        budget_left=lambda: left["left"],
        budget_floor=0,
        expired=lambda: False,
        max_nodes=max_nodes,
    )


def _crossing_canvas() -> tuple[_Canvas, tuple[int, int, int, int]]:
    """An empty 5x5 box, so the two nets' shortest paths cross at (2, 2, 0)."""
    bounds = (0, 0, 4, 4)
    return _Canvas(limit=bounds), bounds


#: The two nets of `_crossing_canvas`: one along row 2, one down column 2.
_CROSSING_ENDS: dict[int, tuple[list[Cell], set[Cell]]] = {
    0: ([(0, 2, 0)], {(4, 2, 0)}),
    1: ([(2, 0, 0)], {(2, 4, 0)}),
}


def test_two_crossing_nets_are_solved_jointly() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem, _grid_environment(canvas, bounds, _CROSSING_ENDS)
    )

    assert result.outcome is last_mile.ClusterOutcome.SOLVED
    assert set(result.paths) == {0, 1}
    assert not set(result.paths[0]) & set(result.paths[1])
    assert result.nodes <= last_mile.B_MAX_CBS_NODES


def test_a_gap_that_cannot_hold_two_nets_is_proved_infeasible() -> None:
    """Both nets must cross x=2, and the only opening is one cell on level 0."""
    bounds = (0, 0, 4, 2)
    canvas = _Canvas(limit=bounds)
    for y in range(3):
        for level in range(freeform_module.LEVELS):
            if (y, level) == (1, 0):
                continue
            canvas.blocked[2, y, level] = 0
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    ends = {
        0: ([(0, 0, 0)], {(4, 0, 0)}),
        1: ([(0, 2, 0)], {(4, 2, 0)}),
    }

    result = last_mile.solve_cluster(problem, _grid_environment(canvas, bounds, ends))

    assert result.outcome is last_mile.ClusterOutcome.PROVED
    assert result.paths == {}
    assert result.nodes < last_mile.B_MAX_CBS_NODES


def test_a_node_bound_reports_bounded_and_never_proved() -> None:
    bounds = (0, 0, 4, 2)
    canvas = _Canvas(limit=bounds)
    for y in range(3):
        for level in range(freeform_module.LEVELS):
            if (y, level) == (1, 0):
                continue
            canvas.blocked[2, y, level] = 0
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    ends = {
        0: ([(0, 0, 0)], {(4, 0, 0)}),
        1: ([(0, 2, 0)], {(4, 2, 0)}),
    }

    result = last_mile.solve_cluster(
        problem,
        _grid_environment(canvas, bounds, ends, max_nodes=1),
    )

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.paths == {}
    assert result.bound is last_mile.ClusterBound.NODES


def test_a_cut_low_level_search_is_never_a_proof() -> None:
    """H1: a tree that empties only because a search was capped proves nothing."""
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    cut = _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)

    def search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        return cut

    environment = last_mile.ClusterEnvironment(
        search=search,
        offers=_offers_stub,
        budget_left=lambda: 1 << 30,
        budget_floor=0,
        expired=lambda: False,
    )

    result = last_mile.solve_cluster(problem, environment)

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET
    assert result.paths == {}


def test_an_exhausted_expansion_floor_reports_bounded() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    environment = _grid_environment(
        canvas, bounds, _CROSSING_ENDS, budget={"left": 0}
    )

    result = last_mile.solve_cluster(problem, environment)

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET


def test_constraints_keep_a_net_off_the_cell_it_was_split_on() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem, _grid_environment(canvas, bounds, _CROSSING_ENDS)
    )

    assert result.outcome is last_mile.ClusterOutcome.SOLVED
    crossing = (2, 2, 0)
    assert sum(crossing in path for path in result.paths.values()) <= 1


def test_the_same_cluster_solves_identically_twice() -> None:
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    first_canvas, bounds = _crossing_canvas()
    second_canvas, _bounds = _crossing_canvas()

    first = last_mile.solve_cluster(
        problem, _grid_environment(first_canvas, bounds, _CROSSING_ENDS)
    )
    second = last_mile.solve_cluster(
        problem, _grid_environment(second_canvas, bounds, _CROSSING_ENDS)
    )

    assert first.paths == second.paths
    assert first.nodes == second.nodes
    assert first.expansions == second.expansions


def test_paths_on_different_levels_over_one_column_do_not_conflict() -> None:
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    conflict = last_mile._first_conflict(
        problem,
        {0: ((1, 0, 0), (2, 0, 0)), 1: ((1, 0, 2), (2, 0, 2))},
    )
    shared = last_mile._first_conflict(
        problem,
        {0: ((1, 0, 0), (2, 0, 0)), 1: ((2, 0, 0), (3, 0, 0))},
    )

    assert conflict is None
    assert shared == (0, 1, (2, 0, 0))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_last_mile.py -v -k "solve or conflict or bounded or proved or constraints or identically or cut_low_level"`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.last_mile' has no attribute 'ClusterEnvironment'`.

- [ ] **Step 3: Append the search to `last_mile.py`**

At the top of the module add `import heapq`, `import time`, extend the
`collections.abc` import with `Callable`, and add the typing block the search
needs (Task 2 deliberately left it out, because an unused `TYPE_CHECKING`
import fails `uv run ruff check .`):

```python
from typing import TYPE_CHECKING

from flab2bp.layout.route_feedback import RouteFailureKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.layout.freeform import _PathSearchResult

_Offers = tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]]
```

`RouteFailureKind` is a real runtime import: the `BUDGET` rule compares against
it. `route_feedback` imports nothing from `last_mile`, so there is no cycle.
Then append:

```python
class ClusterBound(StrEnum):
    """Which bound ended a run, so a replay can tell a wall cut from a cap."""

    NONE = ""
    NODES = "nodes"
    CONSTRAINTS = "constraints"
    BUDGET = "budget"
    WALL = "wall"


@dataclass(frozen=True, slots=True)
class ClusterResult:
    """What one cluster search established, and what it cost."""

    outcome: ClusterOutcome
    paths: Mapping[int, tuple[Cell, ...]]
    nodes: int
    expansions: int
    seconds: float
    bound: ClusterBound = ClusterBound.NONE

    def __post_init__(self) -> None:
        if self.outcome is not ClusterOutcome.SOLVED and self.paths:
            raise ValueError("only a solved cluster carries paths")
        if (self.bound is ClusterBound.NONE) is (
            self.outcome is ClusterOutcome.BOUNDED
        ):
            raise ValueError("a bounded run names its bound and no other does")


@dataclass(frozen=True, slots=True)
class ClusterEnvironment:
    """Everything the search may do, as callables owned by the caller.

    ``search(index, forbidden)`` must run the caller's own A* for one net with
    the caller's own ends, its own rejected-commit cells UNIONED with
    ``forbidden``, and the cluster's paths absent from the grid.  The search
    never touches a canvas itself; the caller owns every mutation.

    ``offers`` re-queries one net's ``_ends`` offer maps.  :func:`solve_cluster`
    never calls it; it is here because the caller needs it at STAKE time and
    the environment is the object that already knows how to reach ``_ends``.
    Offers collected during the search are stale by then -- staking happens one
    net at a time and each stake takes cells the next net's offers were
    computed against.
    """

    search: Callable[[int, frozenset[Cell]], _PathSearchResult]
    offers: Callable[[int], _Offers]
    budget_left: Callable[[], int]
    budget_floor: int
    expired: Callable[[], bool]
    max_nodes: int = B_MAX_CBS_NODES
    max_constraints: int = B_MAX_CONSTRAINTS


_Constraints = tuple[tuple[int, Cell], ...]
_Node = tuple[tuple[int, int, int], _Constraints, dict[int, tuple[Cell, ...]]]


def _cost(problem: ClusterProblem, paths: Mapping[int, tuple[Cell, ...]]) -> int:
    return sum(
        len(paths[index]) if index in paths else B_UNROUTED_COST
        for index in problem.nets
    )


def _first_conflict(
    problem: ClusterProblem,
    paths: Mapping[int, tuple[Cell, ...]],
) -> tuple[int, int, Cell] | None:
    """The first cell two cluster paths share, scanning nets in index order.

    A cell is ``(x, y, level)``, which is the whole resource: a ramp's ``via``
    cell is already spliced into the path by ``_astar`` and de-duplicated by
    ``_cut_loops``, so ramps need no separate model, and two paths crossing one
    column at different levels are correctly not a conflict.
    """
    seen: dict[Cell, int] = {}
    for index in problem.nets:
        path = paths.get(index)
        if path is None:
            continue
        for cell in path:
            holder = seen.get(cell)
            if holder is not None and holder != index:
                return (holder, index, cell)
            seen[cell] = index
    return None


def _forbidden_for(constraints: _Constraints, net: int) -> frozenset[Cell]:
    return frozenset(cell for index, cell in constraints if index == net)


def solve_cluster(
    problem: ClusterProblem,
    environment: ClusterEnvironment,
) -> ClusterResult:
    """Conflict-based search over ``problem``, bounded by ``environment``.

    High level: best-first over the sum of path lengths, splitting the first
    shared cell into the two one-net constraints.  A branch that loses a net
    is kept and priced, never dropped, because a dropped branch would make a
    closed tree a lie.  Reaching any bound ends the run as BOUNDED for the same
    reason: only a heap that empties on its own, with every search in it having
    reached a real conclusion, is a proof.

    A low-level result carrying :attr:`RouteFailureKind.BUDGET` is the subtle
    version of that: the search did not decide whether a path exists, so the
    node built on it does not stand for the subspace it claims, and an empty
    heap afterwards is an artifact of the cap rather than a fact about the
    grid.  Every such result ends the run.
    """
    started = time.perf_counter()
    entry_budget = environment.budget_left()

    def done(
        outcome: ClusterOutcome,
        paths: Mapping[int, tuple[Cell, ...]],
        nodes: int,
        bound: ClusterBound = ClusterBound.NONE,
    ) -> ClusterResult:
        return ClusterResult(
            outcome=outcome,
            paths=dict(paths) if outcome is ClusterOutcome.SOLVED else {},
            nodes=nodes,
            expansions=entry_budget - environment.budget_left(),
            seconds=time.perf_counter() - started,
            bound=bound,
        )

    def hit_bound() -> ClusterBound:
        if environment.expired():
            return ClusterBound.WALL
        if environment.budget_left() <= environment.budget_floor:
            return ClusterBound.BUDGET
        return ClusterBound.NONE

    def cut(found: _PathSearchResult) -> bool:
        return found.kind is RouteFailureKind.BUDGET

    if (bound := hit_bound()) is not ClusterBound.NONE:
        return done(ClusterOutcome.BOUNDED, {}, 0, bound)

    root: dict[int, tuple[Cell, ...]] = {}
    for index in problem.nets:
        if (bound := hit_bound()) is not ClusterBound.NONE:
            return done(ClusterOutcome.BOUNDED, {}, 0, bound)
        found = environment.search(index, frozenset())
        if cut(found):
            return done(ClusterOutcome.BOUNDED, {}, 0, ClusterBound.BUDGET)
        if found.path is not None:
            root[index] = found.path

    ordinal = 0
    heap: list[_Node] = [((_cost(problem, root), 0, ordinal), (), root)]
    nodes = 0
    while heap:
        if nodes >= environment.max_nodes:
            return done(ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.NODES)
        if (bound := hit_bound()) is not ClusterBound.NONE:
            return done(ClusterOutcome.BOUNDED, {}, nodes, bound)
        _key, constraints, paths = heapq.heappop(heap)
        nodes += 1
        conflict = _first_conflict(problem, paths)
        if conflict is None:
            if len(paths) == len(problem.nets):
                return done(ClusterOutcome.SOLVED, paths, nodes)
            # Conflict-free but incomplete: no split can add a path, so the
            # branch is exhausted rather than bounded.
            continue
        left, right, cell = conflict
        for chosen in (left, right):
            child_constraints: _Constraints = (*constraints, (chosen, cell))
            if len(child_constraints) > environment.max_constraints:
                return done(
                    ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.CONSTRAINTS
                )
            if (bound := hit_bound()) is not ClusterBound.NONE:
                return done(ClusterOutcome.BOUNDED, {}, nodes, bound)
            found = environment.search(chosen, _forbidden_for(child_constraints, chosen))
            if cut(found):
                return done(ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.BUDGET)
            child = dict(paths)
            if found.path is None:
                child.pop(chosen, None)
            else:
                child[chosen] = found.path
            ordinal += 1
            heapq.heappush(
                heap,
                (
                    (_cost(problem, child), len(child_constraints), ordinal),
                    child_constraints,
                    child,
                ),
            )
    return done(ClusterOutcome.PROVED, {}, nodes)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_last_mile.py -v`
Expected: PASS, 15 passed.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/last_mile.py tests/layout/test_last_mile.py
uv run mypy src/flab2bp/layout/last_mile.py
uv run pytest -q
git add src/flab2bp/layout/last_mile.py tests/layout/test_last_mile.py
git commit -m "feat(layout): add a bounded conflict-based search over a cluster"
```

---

### Task 4: Run the cluster search inside `_route_all` and commit its solutions

**Files:**
- Modify: `src/flab2bp/layout/route_feedback.py:119-146` (`DetailedRouteResult`)
- Modify: `src/flab2bp/layout/freeform.py:7082-8832` (`_route_all`), `:13994-14017` (`_build_prepared`'s combined result)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `last_mile.build_cluster`, `last_mile.solve_cluster`, `last_mile.ClusterEnvironment`, `last_mile.ClusterProblem`, `last_mile.ClusterOutcome`, `last_mile.ClusterBound`, `last_mile.B_MAX_STRANDED`, `last_mile.B_MIN_SECONDS`, `last_mile.B_CBS_EXPANSION_SHARE`, `last_mile.B_LOW_LEVEL_EXPANSIONS`; `_ends`, `_stake`, `_unstake`, `_selected_hints`, `commit_once`, `_finish` inside `_route_all`.
- Produces:

```python
# flab2bp.layout.route_feedback
@dataclass(frozen=True, slots=True)
class LastMileReport:
    invocations: int
    solved: int
    proved: int
    bounded: int
    commit_rejected: int
    restore_mismatch: int
    relation_skipped_siblings: int
    nodes: int
    expansions: int
    seconds: float
    relation_strips: tuple[int, ...] = ()
    relation_evidence: str = ""

@dataclass(frozen=True, slots=True)
class DetailedRouteResult:
    ...
    last_mile: LastMileReport | None = None
```

Integration and the commit path are one task on purpose: `ClusterEnvironment.offers` and the staking code have no reader until the commit path exists, so splitting them would ship dead code in a green commit. The no-good is Task 5.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pack_with_no_stranded_net_never_runs_the_cluster_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import last_mile as last_mile_module

    calls: list[object] = []
    original = last_mile_module.solve_cluster

    def counting(problem: object, environment: object) -> object:
        calls.append(problem)
        return original(problem, environment)  # type: ignore[arg-type]

    monkeypatch.setattr(last_mile_module, "solve_cluster", counting)
    FreeformLayout(band_policy=BandPolicy("portable"), workers=1).lay_out(
        plastic_spec(), time_budget_s=8.0
    )

    assert calls == []


def _bounded_result() -> object:
    from flab2bp.layout import last_mile as last_mile_module

    return last_mile_module.ClusterResult(
        outcome=last_mile_module.ClusterOutcome.BOUNDED,
        paths={},
        nodes=0,
        expansions=0,
        seconds=0.0,
        bound=last_mile_module.ClusterBound.NODES,
    )


def test_a_bounded_cluster_search_restores_the_round_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BOUNDED outcome must leave every piece of round state byte-equal."""
    from flab2bp.layout import last_mile as last_mile_module

    def always_bounded(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> object:
        return _bounded_result()

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_bounded)
    canvas, nets, bounds = _one_stranded_net_fixture()
    result = freeform_module._route_all(
        canvas,
        nets,
        catalog.item_id("conveyor-belt-mk-i"),
        catalog.building(catalog.item_id("conveyor-belt-mk-i")).model_index,
        bounds,
    )

    assert result.status is DetailedRouteStatus.STRANDED
    assert result.exhaustive is False
    assert result.last_mile is not None
    assert result.last_mile.invocations == 1
    assert result.last_mile.bounded == 1
    assert result.last_mile.restore_mismatch == 0


def test_a_hostile_cluster_solution_never_raises_and_never_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass absorbs a bad solution: no exception, no ROUTED, a counter moves.

    A CRASH row fails the corpus gate, so the restore check must degrade rather
    than assert.  This drives the two ways a solution can go wrong at once --
    the committer refuses it, or the rollback does not reproduce the round --
    and requires only that exactly one of the two counters records it.
    """
    from flab2bp.layout import last_mile as last_mile_module

    def hostile(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> object:
        # Claim every cluster net lands on the same single cell: disjointness
        # is violated, the committer cannot link it, and the rollback has to
        # put the round back from a state CBS would never have produced.
        cell = (0, 0, 0)
        return last_mile_module.ClusterResult(
            outcome=last_mile_module.ClusterOutcome.SOLVED,
            paths={index: (cell,) for index in problem.nets},
            nodes=1,
            expansions=0,
            seconds=0.0,
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", hostile)
    canvas, nets, bounds = _one_stranded_net_fixture()
    result = freeform_module._route_all(
        canvas,
        nets,
        catalog.item_id("conveyor-belt-mk-i"),
        catalog.building(catalog.item_id("conveyor-belt-mk-i")).model_index,
        bounds,
    )

    assert result.status is not DetailedRouteStatus.ROUTED
    assert result.exhaustive is False
    assert result.last_mile is not None
    assert result.last_mile.solved == 0
    # The committer refuses the overlapping paths, so this is exact.  The
    # rollback that follows may or may not reproduce the round from a state CBS
    # would never have produced; either way it must not raise, and at most one
    # mismatch can be recorded because the pass runs once.
    assert result.last_mile.commit_rejected == 1
    assert result.last_mile.restore_mismatch <= 1


def test_too_many_stranded_nets_never_reach_the_cluster_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import last_mile as last_mile_module

    seen: list[object] = []

    def counting(problem: object, environment: object) -> object:
        seen.append(problem)
        return _bounded_result()

    monkeypatch.setattr(last_mile_module, "solve_cluster", counting)
    monkeypatch.setattr(last_mile_module, "B_MAX_STRANDED", 0)
    canvas, nets, bounds = _one_stranded_net_fixture()
    freeform_module._route_all(
        canvas,
        nets,
        catalog.item_id("conveyor-belt-mk-i"),
        catalog.building(catalog.item_id("conveyor-belt-mk-i")).model_index,
        bounds,
    )

    assert seen == []


def test_the_cluster_search_runs_at_most_once_per_routing_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import last_mile as last_mile_module

    seen: list[last_mile_module.ClusterProblem] = []

    def always_bounded(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        seen.append(problem)
        return _bounded_result()

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_bounded)
    canvas, nets, bounds = _one_stranded_net_fixture()
    freeform_module._route_all(
        canvas,
        nets,
        catalog.item_id("conveyor-belt-mk-i"),
        catalog.building(catalog.item_id("conveyor-belt-mk-i")).model_index,
        bounds,
    )

    assert len(seen) == 1


def test_a_cluster_solution_is_staked_and_routes_the_pack() -> None:
    """A joint solution the greedy round could not find finishes the pack."""
    canvas, nets, bounds = _joint_only_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert result.status is DetailedRouteStatus.ROUTED
    assert result.failures == ()
    assert result.last_mile is not None
    assert result.last_mile.solved == 1
    assert result.last_mile.commit_rejected == 0


def test_a_cluster_solution_rejected_at_commit_is_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit-link rejection is not a proof and must not keep the paths.

    The ROUND's own `commit_once()` (`freeform.py:8637`) runs BEFORE the
    last-mile pass, so a stub that refuses "the first call" would refuse the
    wrong one.  Refuse instead on the call whose `paths` argument contains the
    net that only a cluster solution can wire -- index 1 in this fixture.
    """
    canvas, nets, bounds = _joint_only_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")
    original = freeform_module._commit_paths

    def refusing(
        commit_canvas: object,
        commit_nets: object,
        commit_paths: dict[int, object],
        *args: object,
        **kwargs: object,
    ) -> tuple[int, ...]:
        if 1 in commit_paths:
            return (1,)
        return original(  # type: ignore[arg-type]
            commit_canvas, commit_nets, commit_paths, *args, **kwargs
        )

    monkeypatch.setattr(freeform_module, "_commit_paths", refusing)
    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert result.status is not DetailedRouteStatus.ROUTED
    assert result.exhaustive is False
    assert result.last_mile is not None
    assert result.last_mile.solved == 0
    assert result.last_mile.commit_rejected == 1
    assert result.last_mile.bounded == 1
```

`_one_stranded_net_fixture()` is a helper added beside the existing routing fixtures in `tests/layout/test_freeform.py`: it builds a `_Canvas` with a walled pocket, two `_Net`s with stable `NetId`s where one destination is unreachable, and returns `(canvas, nets, bounds)`. Reuse the construction in `TestRepair`'s `_block` helper for the wall.

`_joint_only_fixture()` is its sibling: two nets whose greedy sequential routing strands the second (the first takes the only cell the second needs) but for which a disjoint pair exists. Build it as a 5x5 canvas with a wall at `x = 2` open at `y = 1` and `y = 2` on every level, endpoints `(0, 1, 0) -> (4, 2, 0)` for net 0 and `(0, 2, 0) -> (4, 1, 0)` for net 1, so the shortest paths cross and the joint solution swaps which gap each net takes.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -v -k "cluster_search"`
Expected: FAIL with `AttributeError: 'DetailedRouteResult' object has no attribute 'last_mile'`.

- [ ] **Step 3: Add the report type and the result field**

In `src/flab2bp/layout/route_feedback.py`, above `DetailedRouteResult`:

```python
@dataclass(frozen=True, slots=True)
class LastMileReport:
    """What the bounded last-mile cluster search did in one routing pass."""

    invocations: int
    solved: int
    proved: int
    bounded: int
    #: A CBS solution the commit preflight refused, or whose rollback ran.
    commit_rejected: int
    #: Run 1 closed but a cluster net had a sibling, so run 2 was not run.
    #: See the spec's 5.2: unstaking a sibling can DISCONNECT a net, and a
    #: closed tree over a disconnected net is a false proof.
    relation_skipped_siblings: int
    #: Times the round could not be restored exactly.  Never an exception: an
    #: `AssertionError` here becomes a CRASH row and fails the corpus gate on a
    #: condition the gate exists to measure.
    restore_mismatch: int
    nodes: int
    expansions: int
    seconds: float
    #: Ascending strip instances of a cluster proved unroutable in the relaxed
    #: environment, empty when no relation proof was established.
    relation_strips: tuple[int, ...] = ()
    relation_evidence: str = ""

    def __post_init__(self) -> None:
        if self.relation_strips and len(self.relation_strips) < 2:
            raise ValueError("a relation proof needs at least two strip instances")
        if tuple(sorted(self.relation_strips)) != self.relation_strips:
            raise ValueError("relation strips must be ascending")
```

and add the field to `DetailedRouteResult` after `exhaustive`:

```python
    last_mile: LastMileReport | None = None
```

- [ ] **Step 4: Add the last-mile machinery to `_route_all`**

Add `from flab2bp.layout import last_mile` to `freeform.py`'s imports. Immediately after the `_repair` closure's definition (`freeform.py:7965`-`8130`), add:

```python
    last_mile_counts = {
        "invocations": 0,
        "solved": 0,
        "proved": 0,
        "bounded": 0,
        "commit_rejected": 0,
        "restore_mismatch": 0,
        "relation_skipped_siblings": 0,
        "nodes": 0,
        "expansions": 0,
    }
    last_mile_seconds = 0.0
    last_mile_done = False
    #: One expansion allowance for the whole pass, shared by both runs.  Set
    #: once at pass entry so run 2 cannot re-derive a fresh quarter of whatever
    #: run 1 left behind.
    last_mile_floor = 0
    proved_stranded: set[int] = set()
    proved_round = -1
    relation_strips: tuple[int, ...] = ()
    relation_evidence = ""

    def _last_mile_report() -> LastMileReport:
        return LastMileReport(
            invocations=last_mile_counts["invocations"],
            solved=last_mile_counts["solved"],
            proved=last_mile_counts["proved"],
            bounded=last_mile_counts["bounded"],
            commit_rejected=last_mile_counts["commit_rejected"],
            restore_mismatch=last_mile_counts["restore_mismatch"],
            relation_skipped_siblings=last_mile_counts["relation_skipped_siblings"],
            nodes=last_mile_counts["nodes"],
            expansions=last_mile_counts["expansions"],
            seconds=last_mile_seconds,
            relation_strips=relation_strips,
            relation_evidence=relation_evidence,
        )

    def _cluster_offers(index: int) -> tuple[
        dict[Cell, Cell], dict[Cell, Cell], dict[Cell, Cell]
    ]:
        """This net's `_ends` offer maps, as of right now."""
        _starts, _goals, offers = _ends(index)
        canvas.routing_ports = frozenset()
        return offers

    def _cluster_search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        """One cluster net's search: the round's own call, capped and constrained.

        The private budget is the deadline discipline.  `_MAX_EXPANSIONS` lets
        one search run for a large fraction of a second, and this pass makes
        hundreds of them at the end of an attempt that is already near its
        budget, so a quarter of that cap bounds how far past the last bound
        check the pass can travel.  Exhausting it returns
        `RouteFailureKind.BUDGET`, which `solve_cluster` turns into BOUNDED --
        which is correct: a capped search decided nothing.
        """
        starts, goals, _offers = _ends(index)
        allowance = min(
            last_mile.B_LOW_LEVEL_EXPANSIONS,
            max(0, budget["left"] - last_mile_floor),
        )
        private = {"left": allowance}
        found = _astar(
            canvas,
            starts,
            goals,
            history,
            pressure,
            bounds,
            private,
            deadline,
            {},
            grid,
            owned_starts=owned_source_starts.get(index, ()),
            forbidden=frozenset(rejected_path_cells.get(index, ())) | constraints,
            blocking_owners=owner,
        )
        canvas.routing_ports = frozenset()
        budget["left"] -= allowance - private["left"]
        return found

    def _cluster_environment() -> last_mile.ClusterEnvironment:
        return last_mile.ClusterEnvironment(
            search=_cluster_search,
            offers=_cluster_offers,
            budget_left=lambda: budget["left"],
            budget_floor=last_mile_floor,
            expired=lambda: _expired(deadline),
        )

    def _round_state() -> tuple[object, ...]:
        """Everything the pass borrows, in a form two snapshots can compare.

        `grid.reserved` is in here because it is NOT constant across a pass:
        `_retire_served_roles` filters it (`freeform.py:7606`-`7610`) and
        `_restore_unserved_roles` rebuilds it (`:7624`-`7632`).  A role that
        came back in the wrong order, or not at all, is precisely the silent
        corruption this comparison exists to catch.
        """
        return (
            dict(paths),
            dict(owner),
            bytes(grid.occ),
            tuple(grid.reserved),
            set(canvas.guard),
            {cell for cell, holder in canvas.blocked.items() if holder == _TENTATIVE},
            dict(path_tap),
            {index: set(cells) for index, cells in path_guards.items()},
            {cell: set(claims) for cell, claims in guard_claims.items()},
            dict(canvas.reserved),
            dict(canvas.port_corridors),
        )

    def _restore_staked(
        order: Sequence[int],
        staked: Mapping[int, tuple[Cell, ...]],
        held: Mapping[int, tuple[Cell | None, Cell | None, Cell | None]],
        before: tuple[object, ...],
    ) -> bool:
        """Re-stake in the original order and report whether it worked.

        Used by BOTH releases -- the cluster release in `_last_mile` and the
        whole-pack sweep in `_relaxed_cluster_result` -- so run 2 cannot skip
        the check that run 1 must pass.  The order matters because
        `_claim_junction_guard` computes its `excused` set from the sibling
        paths already down (`freeform.py:7563`-`7568`).

        It DEGRADES rather than asserts: an `AssertionError` inside
        `_route_all` becomes a CRASH row in `scripts/audit.py` and fails the
        corpus gate on the very condition the gate is measuring.
        """
        for index in order:
            if index not in paths:
                _stake(index, staked[index], hints=held[index])
        if before == _round_state():
            return True
        last_mile_counts["restore_mismatch"] += 1
        return False

    def _tally(result: last_mile.ClusterResult) -> None:
        nonlocal last_mile_seconds
        last_mile_counts["nodes"] += result.nodes
        last_mile_counts["expansions"] += result.expansions
        last_mile_seconds += result.seconds

    def _last_mile(round_stranded: list[int], round_index: int) -> list[int]:
        """Search the conflict cluster once per pass; see the Phase B spec 5.6."""
        nonlocal last_mile_done, last_mile_floor, proved_round
        if (
            last_mile_done
            or not round_stranded
            or len(round_stranded) > last_mile.B_MAX_STRANDED
            or budget["left"] <= 0
            or _expired(deadline)
            or (
                deadline is not None
                and deadline - time.monotonic() < last_mile.B_MIN_SECONDS
            )
        ):
            return round_stranded
        last_mile_done = True
        last_mile_counts["invocations"] += 1
        last_mile_floor = budget["left"] - int(
            last_mile.B_CBS_EXPANSION_SHARE * budget["left"]
        )
        index_by_id = {_net_id(index): index for index in range(len(nets))}
        problem = last_mile.build_cluster(
            sorted(round_stranded),
            walls={
                index: search_failures[index].wall
                for index in round_stranded
                if index in search_failures
            },
            blockers={
                index: tuple(
                    index_by_id[blocker]
                    for blocker in search_blockers.get(index, ())
                    if blocker in index_by_id
                )
                for index in round_stranded
            },
            owner=owner,
            paths=paths,
            endpoints={index: _endpoint_cells(nets[index]) for index in range(len(nets))},
            src_group=src_group,
            dst_group=dst_group,
        )
        # `paths` is insertion-ordered and only `_stake` writes it, so
        # `list(paths)` IS the stake order -- which the restore has to replay,
        # because `_claim_junction_guard` computes its `excused` set from the
        # sibling paths already down.
        order = [index for index in paths if index in set(problem.nets)]
        released = {index: paths[index] for index in order}
        held = {
            index: (
                source_hint.get(index),
                sink_hint.get(index),
                path_tap.get(index),
            )
            for index in order
        }
        before = _round_state()
        environment = _cluster_environment()

        for index in order:
            _unstake(index)
        _capture(1, problem)
        result = last_mile.solve_cluster(problem, environment)
        _tally(result)

        if result.outcome is last_mile.ClusterOutcome.SOLVED:
            # Stake in ascending index order, re-querying each net's offers
            # THROUGH THE ENVIRONMENT as we go: the offers CBS saw were
            # collected with NO cluster net staked, and every stake takes cells
            # the next net's offers were computed against.  A stale hint is
            # exactly the defect `_ends`' own docstring names.  Going through
            # `environment.offers` rather than the closure keeps the field a
            # live part of the contract the bench's stub also implements.
            for index in problem.nets:
                path = result.paths[index]
                _stake(
                    index,
                    path,
                    hints=_selected_hints(path, environment.offers(index)),
                )
            unlinked_now, _details_now = commit_once()
            if not unlinked_now:
                last_mile_counts["solved"] += 1
                return []
            # A commit-link rejection is exact static evidence about buildings,
            # not a routing proof.  Put the round back and report a bound.
            for index in problem.nets:
                if index in paths:
                    _unstake(index)
            _restore_staked(order, released, held, before)
            last_mile_counts["commit_rejected"] += 1
            last_mile_counts["bounded"] += 1
            return round_stranded

        restored = _restore_staked(order, released, held, before)
        if result.outcome is last_mile.ClusterOutcome.PROVED and restored:
            last_mile_counts["proved"] += 1
            proved_round = round_index
            proved_stranded.clear()
            proved_stranded.update(round_stranded)
        else:
            last_mile_counts["bounded"] += 1
        return round_stranded
```

Add the capture hook once, at `_route_all` scope beside `_cluster_environment`, so **both** runs can reach it (Task 9 fills in its body; a `pass` stub keeps this task green):

```python
    def _capture(run: int, problem: last_mile.ClusterProblem) -> None:
        """Hand a developer-tool hook everything needed to replay this run.

        Called AFTER the unstake that builds each run's environment, so what
        the bench snapshots is the grid the search will actually see.
        """
        return None
```

`commit_once` is a local of `_route_all` defined inside the round loop
(`freeform.py:8580`); the closure resolves it at call time, which is always
after that definition. `time` is already imported in `freeform.py`; `Callable`
is already imported from `collections.abc`; add `Sequence` to the
`collections.abc` import if it is not there. Import `LastMileReport` alongside
the other `route_feedback` names.

- [ ] **Step 5: Call it at the insertion point and track the incumbent round**

Beside `fewest_failed` (`freeform.py:7159`) add `best_round = -1`. In the incumbent update (`freeform.py:8801`-`8806`) add `best_round = it` to the assignment line's block:

```python
        if failed < fewest_failed:
            fewest_failed, stale, best_paths = failed, 0, dict(paths)
            best_round = it
```

At the insertion point — immediately before `for path in paths.values():` (`freeform.py:8758`) — insert:

```python
        if failed:
            stranded = _last_mile(stranded, it)
            failed = len(stranded)
            round_failures = {
                index: round_failures[index]
                for index in stranded
                if index in round_failures
            }
            if failed == 0:
                return _finish(
                    paths,
                    {},
                    source_hint,
                    sink_hint,
                    path_tap,
                    budget_exhausted=False,
                )
```

That `_finish` is the identical return the round already takes at `freeform.py:8640` and `8750` when a round wires everything.

Thread the report and the claim through the three exits. In `_budget_result`'s and `_finish`'s `DetailedRouteResult(...)` constructions add `last_mile=_last_mile_report()`. Give `_finish` a keyword and use it:

```python
    def _finish(
        selected_paths: dict[int, tuple[Cell, ...]],
        selected_failures: dict[int, NetFailure],
        selected_source_hints: Mapping[int, Cell],
        selected_sink_hints: Mapping[int, Cell],
        selected_taps: Mapping[int, Cell],
        *,
        budget_exhausted: bool,
        exhaustive_claim: bool = False,
    ) -> DetailedRouteResult:
```

and, just before its `return DetailedRouteResult(...)`:

```python
        exhaustive = (
            exhaustive_claim
            and status is DetailedRouteStatus.STRANDED
            and set(failures) == proved_stranded
            and not any(
                failure.kind is RouteFailureKind.BUDGET for failure in ordered_failures
            )
        )
```

with `exhaustive=exhaustive` and `last_mile=_last_mile_report()` added to the constructor call. Leave `exhaustive_claim` false at every call site in this task; Task 5 supplies it.

- [ ] **Step 6: Carry the report through `_build_prepared`**

In the combined `DetailedRouteResult(...)` at `freeform.py:13994`, add:

```python
        last_mile=internal_routing.last_mile,
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run python setup.py build_ext --inplace
uv run pytest tests/layout/test_freeform.py -v -k "cluster_search or cluster_solution or hostile_cluster"
uv run pytest tests/layout/test_route_feedback.py -q
```

Expected: the six new tests PASS and `test_route_feedback.py` is unchanged and green. Note that the `B_MAX_STRANDED` test monkeypatches the module attribute, so `_last_mile` must read `last_mile.B_MAX_STRANDED` through the module rather than importing the constant by name.

- [ ] **Step 8: Prove the replay digests did not move**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python scripts/route_bench.py --cases "$d/route-cases-universe-matrix-output-products.pkl" --rounds 3 --check
uv run python scripts/route_bench.py --cases "$d/route-cases-quantum-chip-all-products.pkl" --rounds 3 --check
```

Expected: both print `MATCH` against the digests recorded in `digests-before.txt` and exit 0. A `DIFFER` here means the last-mile pass changed a search on a pack it should never have touched: stop, do not commit, and find which `_astar` call moved.

- [ ] **Step 9: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py
git commit -m "feat(layout): run and commit a bounded cluster search in the router"
```

---

### Task 5: Environment-scoped no-good from a closed tree

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:10264-10499` (`_route_boundary_nets`), `:7281-7364` (`_finish`), `:8825-8832` (the final `_finish` call)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `proved_stranded`, `proved_round`, `best_round` from Task 4; `DetailedRouteResult.exhaustive` (`route_feedback.py:125`).
- Produces: a `DetailedRouteResult` with `exhaustive=True`, which `_proof_scoped_no_goods` (`freeform.py:13682`) already turns into an `ExactPackNoGood` and `_ExactPackNoGoodState.remember` (`freeform.py:2765`, `:2773`) already deduplicates into `_pack`'s `exact_pack_no_goods` tuple (`:16375`). No new packer code is needed for level one.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_clean_boundary_routing_is_marked_exhaustive() -> None:
    canvas, nets, core = _boundary_input_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_external_inputs(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        core,
    )

    assert result.status is DetailedRouteStatus.ROUTED
    assert result.exhaustive is True


def test_a_boundary_routing_with_failures_is_not_exhaustive() -> None:
    canvas, nets, core = _boundary_input_fixture(sealed=True)
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_external_inputs(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        core,
    )

    assert result.failures
    assert result.exhaustive is False


def test_a_proved_cluster_marks_the_routing_exhaustive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import last_mile as last_mile_module

    def always_proved(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        return last_mile_module.ClusterResult(
            last_mile_module.ClusterOutcome.PROVED, {}, 3, 10, 0.0
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_proved)
    canvas, nets, bounds = _one_stranded_net_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert result.status is DetailedRouteStatus.STRANDED
    assert result.exhaustive is True
    assert result.last_mile is not None
    assert result.last_mile.proved == 1


def test_a_budget_failure_never_becomes_a_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PROVED cluster plus a BUDGET-kind failure is still not exhaustive.

    The pass must actually RUN for this to mean anything: a budget so small
    that `_last_mile` returns at its `budget["left"] <= 0` guard would make the
    test pass without ever reaching `always_proved`.  `calls` is the assertion
    that it did.
    """
    from flab2bp.layout import last_mile as last_mile_module

    calls: list[object] = []

    def always_proved(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        calls.append(problem)
        return last_mile_module.ClusterResult(
            last_mile_module.ClusterOutcome.PROVED, {}, 1, 0, 0.0
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_proved)
    canvas, nets, bounds = _one_stranded_net_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
        budget={"left": 20_000},
    )

    assert calls, "the last-mile pass never ran; raise the budget"
    assert any(
        failure.kind is RouteFailureKind.BUDGET for failure in result.failures
    ) or result.status is DetailedRouteStatus.BUDGET
    assert result.exhaustive is False
```

**Decision rule for the budget in that test.** `20_000` is chosen so `_route_all`'s own searches on a two-net fixture cannot exhaust it before the pass runs, while `_finish` still reports a `BUDGET`-kind failure for the net that never routed. If `assert calls` fails, the round consumed the budget first: raise it by a factor of ten, re-run, and record the value that works in the test's docstring. If the second assertion fails, the fixture routed everything and there is no budget failure to test against — extend `_one_stranded_net_fixture` with a third net whose goal is outside `bounds` so it is refused before any expansion, and say so.

`_boundary_input_fixture(sealed: bool = False)` builds a canvas with one external input net reaching the core from the entry ring, and, when `sealed`, walls the last approach cell so the net fails.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -v -k "exhaustive"`
Expected: FAIL with `assert False is True` on the first and third tests.

- [ ] **Step 3: Make a clean boundary routing vacuously exhaustive**

In `_route_boundary_nets`, at its `return DetailedRouteResult(...)` (`freeform.py:10492`-`10499`), add:

```python
    return DetailedRouteResult(
        status=status,
        routed=tuple(routed),
        failures=tuple(failures),
        iterations=0,
        expansions=expansions,
        # A result with no failure has nothing left unproved.  This is the same
        # vacuous claim `_build_prepared` already makes for `empty_routing`, and
        # `_build_prepared` conjoins all four sub-routings, so without it an
        # internal proof could never reach `_proof_scoped_no_goods`.
        exhaustive=not failures,
    )
```

- [ ] **Step 4: Supply the claim at the final `_finish`**

Replace the tail of `_route_all` (`freeform.py:8825`-`8832`):

```python
    return _finish(
        best_paths,
        best_failures,
        best_source_hints,
        best_sink_hints,
        best_path_taps,
        budget_exhausted=budget["left"] <= 0,
        exhaustive_claim=proved_round >= 0 and proved_round == best_round,
    )
```

The four guards inside `_finish` (Task 4 Step 5) do the rest: the claim survives only when the status is `STRANDED`, the failure set is exactly the proved set, and no failure is `BUDGET`-kind. `DetailedRouteResult.__post_init__` (`route_feedback.py:127`-`137`) rejects the combination independently, so a mistake raises rather than cutting.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/layout/test_freeform.py -v -k "exhaustive"
uv run pytest tests/layout/test_freeform.py -q -k "no_good or budget_failures"
```

Expected: the four new tests PASS, and the pre-existing `test_exhaustive_non_budget_failure_creates_full_assignment_no_good` (`tests/layout/test_freeform.py:3382`) and `test_unproved_and_budget_failures_do_not_exclude_geometry` (`:3418`) still pass unchanged.

- [ ] **Step 6: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): mark a proved stranded routing exhaustive"
```

---

### Task 6: `ClusterRelationNoGood` and its `_pack` modelling

**Files:**
- Modify: `src/flab2bp/layout/route_feedback.py` (add `ClusterRelationNoGood`)
- Modify: `src/flab2bp/layout/last_mile.py` (add `relation_no_good`)
- Modify: `src/flab2bp/layout/freeform.py:3038-3087` (add `_add_cluster_relation_no_good`), `:3179-3266` (`_pack`)
- Test: `tests/layout/test_last_mile.py`, `tests/layout/test_freeform.py`

This task delivers the type and its CP-SAT modelling. Nothing produces one yet; Task 7 adds the relaxed run that does. The split is deliberate: the modelling is independently reviewable, and a reviewer can reject the `add_forbidden_assignments` encoding without rejecting the relaxed run.

**Interfaces:**
- Consumes: `_add_exact_pack_no_good`'s modelling idiom (`freeform.py:3038`), the `_DirectRelationNoGood` relative-offset idiom (`freeform.py:3427`-`3446`).
- Produces:

```python
# flab2bp.layout.route_feedback
@dataclass(frozen=True, slots=True)
class ClusterRelationNoGood:
    height: int
    outline: tuple[tuple[int, int], ...]
    strips: tuple[int, ...]
    deltas: tuple[tuple[int, int], ...]
    evidence: tuple[str, ...]

# flab2bp.layout.last_mile
def relation_no_good(
    *,
    strips: Sequence[int],
    origins: Sequence[tuple[int, int]],
    outline: tuple[tuple[int, int], ...],
    height: int,
    evidence: str,
) -> ClusterRelationNoGood | None: ...

# flab2bp.layout.freeform
def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    height: int,
    width_bound: int,
    index: int,
    no_good: ClusterRelationNoGood,
) -> None: ...

def _pack(..., cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = ()) -> _Pack | None: ...
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_last_mile.py`:

```python
def test_relation_no_good_records_offsets_from_the_anchor() -> None:
    no_good = last_mile.relation_no_good(
        strips=(1, 3),
        origins=((0, 0), (10, 4), (0, 0), (22, 9)),
        outline=((2, 2), (3, 3), (2, 2), (4, 4)),
        height=20,
        evidence="cluster: nets=(4, 7)",
    )

    assert no_good is not None
    assert no_good.strips == (1, 3)
    assert no_good.deltas == ((0, 0), (12, 5))
    assert no_good.height == 20
    assert no_good.evidence == ("cluster: nets=(4, 7)",)


def test_relation_no_good_needs_two_strip_instances() -> None:
    assert (
        last_mile.relation_no_good(
            strips=(2,),
            origins=((0, 0), (1, 1), (2, 2)),
            outline=((1, 1), (1, 1), (1, 1)),
            height=4,
            evidence="x",
        )
        is None
    )


def test_relation_no_good_drops_a_strip_outside_the_pack() -> None:
    no_good = last_mile.relation_no_good(
        strips=(0, 1, 99),
        origins=((0, 0), (5, 0)),
        outline=((1, 1), (1, 1)),
        height=3,
        evidence="x",
    )

    assert no_good is not None
    assert no_good.strips == (0, 1)
```

Append to `tests/layout/test_freeform.py`:

```python
def test_a_cluster_relation_no_good_forbids_only_that_relative_placement() -> None:
    """Every translation of the recorded relation is out; a shift is back in."""
    strips = _three_unit_strips()
    height = 6
    no_good = ClusterRelationNoGood(
        height=height,
        outline=tuple(freeform_module._box(strip) for strip in strips),
        strips=(0, 2),
        deltas=((0, 0), (2, 0)),
        evidence=("route.exhaustive",),
    )

    forbidden = freeform_module._pack(
        strips,
        height=height,
        width_bound=4,
        time_budget_s=1.0,
        direct_candidates={},
        workers=1,
        deterministic=True,
        cluster_relation_no_goods=(no_good,),
    )

    assert forbidden is not None
    origins = [forbidden.at[index] for index in range(len(strips))]
    assert (origins[2][0] - origins[0][0], origins[2][1] - origins[0][1]) != (2, 0)


def test_a_cluster_relation_no_good_for_another_outline_is_ignored() -> None:
    strips = _three_unit_strips()
    no_good = ClusterRelationNoGood(
        height=6,
        outline=((99, 99),),
        strips=(0, 2),
        deltas=((0, 0), (2, 0)),
        evidence=("route.exhaustive",),
    )

    packed = freeform_module._pack(
        strips,
        height=6,
        width_bound=4,
        time_budget_s=1.0,
        direct_candidates={},
        workers=1,
        deterministic=True,
        cluster_relation_no_goods=(no_good,),
    )

    assert packed is not None


def test_a_translated_cluster_relation_is_still_forbidden() -> None:
    """The constraint is over relative offsets, so sliding the pair cannot escape it."""
    strips = _three_unit_strips()
    outline = tuple(freeform_module._box(strip) for strip in strips)
    no_good = ClusterRelationNoGood(
        height=6,
        outline=outline,
        strips=(0, 2),
        deltas=((0, 0), (2, 0)),
        evidence=("route.exhaustive",),
    )

    packed = freeform_module._pack(
        strips,
        height=6,
        width_bound=8,
        time_budget_s=1.0,
        direct_candidates={},
        workers=1,
        deterministic=True,
        cluster_relation_no_goods=(no_good,),
    )

    assert packed is not None
    origins = [packed.at[index] for index in range(len(strips))]
    delta = (origins[2][0] - origins[0][0], origins[2][1] - origins[0][1])
    assert delta != (2, 0)
```

`_three_unit_strips()` returns three minimal `Strip` objects with `west_channel = 0`, built the way the existing packing tests build them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_last_mile.py tests/layout/test_freeform.py -v -k "relation"`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.last_mile' has no attribute 'relation_no_good'` and `ImportError: cannot import name 'ClusterRelationNoGood'`.

- [ ] **Step 3: Add the no-good type**

In `src/flab2bp/layout/route_feedback.py`, beside `LastMileReport`:

```python
@dataclass(frozen=True, slots=True)
class ClusterRelationNoGood:
    """One relative placement of strip instances proved unroutable.

    The proof behind it is a CBS tree that closed with every OTHER belt in the
    pack unstaked and the cluster's routing-derived rejection sets emptied, so
    it is a statement about the strips and not about one routing: any packing
    that repeats these relative offsets refuses again.  ``outline`` and
    ``height`` scope it to the strip plan that produced it, the same guard
    :class:`ExactPackNoGood` carries.

    ``evidence`` is one blob rather than one string per net: what a reader
    needs is which cluster this was and that both runs closed, and a per-net
    tuple only makes the equality key noisier.
    """

    height: int
    outline: tuple[tuple[int, int], ...]
    strips: tuple[int, ...]
    deltas: tuple[tuple[int, int], ...]
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.height <= 0:
            raise ValueError("cluster relation height must be positive")
        if len(self.strips) < 2:
            raise ValueError("a cluster relation needs at least two strips")
        if tuple(sorted(self.strips)) != self.strips:
            raise ValueError("cluster relation strips must be ascending")
        if len(self.deltas) != len(self.strips):
            raise ValueError("a cluster relation needs one delta per strip")
        if self.deltas[0] != (0, 0):
            raise ValueError("the anchor strip's delta must be the origin")
        if not self.evidence:
            raise ValueError("a cluster relation no-good requires evidence")
```

- [ ] **Step 4: Add the builder to `last_mile.py`**

```python
def relation_no_good(
    *,
    strips: Sequence[int],
    origins: Sequence[tuple[int, int]],
    outline: tuple[tuple[int, int], ...],
    height: int,
    evidence: str,
) -> ClusterRelationNoGood | None:
    """Record the cluster strips' relative placement, or nothing to record."""
    chosen = tuple(sorted({strip for strip in strips if 0 <= strip < len(origins)}))
    if len(chosen) < 2:
        return None
    anchor = origins[chosen[0]]
    deltas = tuple(
        (origins[strip][0] - anchor[0], origins[strip][1] - anchor[1])
        for strip in chosen
    )
    return ClusterRelationNoGood(
        height=height,
        outline=tuple(outline),
        strips=chosen,
        deltas=deltas,
        evidence=(evidence,),
    )
```

Import `ClusterRelationNoGood` from `flab2bp.layout.route_feedback` at the top of `last_mile.py`. `route_feedback` imports nothing from `last_mile`, so there is no cycle.

- [ ] **Step 5: Model it in `_pack`**

Beside `_add_projection_no_good` (`freeform.py:3062`):

```python
def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    height: int,
    width_bound: int,
    index: int,
    no_good: ClusterRelationNoGood,
) -> None:
    """Forbid one RELATIVE placement: at least one cluster strip must move.

    Unlike :func:`_add_exact_pack_no_good`, which removes a single point, this
    removes every translation of the proved relation -- which is exactly what
    the proof supports, because the CBS run behind it removed every other belt
    and so said nothing about where the cluster sits, only how its strips sit
    relative to one another.
    """
    anchor = no_good.strips[0]
    if any(strip >= len(strips) for strip in no_good.strips):
        return
    variables: list[cp_model.IntVar] = []
    values: list[int] = []
    for position, strip_index in enumerate(no_good.strips[1:], start=1):
        relation_x = model.new_int_var(
            -width_bound,
            width_bound,
            f"cluster_ng{index}_dx{position}",
        )
        relation_y = model.new_int_var(-height, height, f"cluster_ng{index}_dy{position}")
        model.add(
            relation_x
            == (xs[strip_index] + strips[strip_index].west_channel)
            - (xs[anchor] + strips[anchor].west_channel)
        )
        model.add(relation_y == ys[strip_index] - ys[anchor])
        variables.extend((relation_x, relation_y))
        values.extend(no_good.deltas[position])
    model.add_forbidden_assignments(variables, [tuple(values)])
```

Add the parameter to `_pack` after `direct_relation_no_goods` (`freeform.py:3192`):

```python
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
```

and, immediately after the `exact_pack_no_goods` loop (`freeform.py:3252`-`3255`):

```python
    for cluster_index, cluster_no_good in enumerate(cluster_relation_no_goods):
        if cluster_no_good.height != height or cluster_no_good.outline != tuple(sizes):
            continue
        _add_cluster_relation_no_good(
            model,
            xs,
            ys,
            strips,
            height,
            width_bound,
            cluster_index,
            cluster_no_good,
        )
```

`xs` and `ys` exist by that point (`freeform.py:3240`-`3248`) and `model.add_no_overlap_2d` runs at `:3250`, so the new loop sits between the `exact_pack_no_goods` loop (`:3252`-`3255`) and the `projection_no_goods` loop (`:3257`-`3266`). Do not move either existing loop.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/layout/test_last_mile.py -v -k "relation"
uv run pytest tests/layout/test_freeform.py -v -k "cluster_relation"
```

Expected: PASS, 6 passed (3 in `test_last_mile.py`, 3 in `test_freeform.py`).

- [ ] **Step 7: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/last_mile.py src/flab2bp/layout/route_feedback.py tests/layout
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/last_mile.py src/flab2bp/layout/route_feedback.py
git add src/flab2bp/layout tests/layout
git commit -m "feat(layout): model a cluster relation no-good in the CP-SAT packer"
```

---

### Task 7: The relaxed run that produces a cluster relation

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_route_all`'s `_last_mile` closure), `:13682-13753` (`_proof_scoped_no_goods`), `:16082-16083` and `:16671-16690` (`lay_out`'s no-good accumulation), `:16361-16380` (the `_pack` call)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `last_mile.cluster_strips` (Task 2), `last_mile.relation_no_good` and `ClusterRelationNoGood` (Task 6), `_unstake`/`_stake`/`_restore_round`/`_cluster_environment` (Task 4), `PackAttempt.origins`/`.outline`/`.height` (`freeform.py:13610`-`13613`).
- Produces:

```python
def _proof_scoped_no_goods(
    attempt: PackAttempt, strips: list[Strip]
) -> tuple[
    tuple[_DirectRelationNoGood, ...],
    ExactPackNoGood | None,
    tuple[ClusterRelationNoGood, ...],
]: ...
```

- [ ] **Step 1: Write the failing tests**

```python
def test_a_relaxed_run_that_closes_records_the_cluster_strips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both runs close, so the report names the cluster's strip instances."""
    from flab2bp.layout import last_mile as last_mile_module

    def always_proved(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        return last_mile_module.ClusterResult(
            last_mile_module.ClusterOutcome.PROVED, {}, 1, 0, 0.0
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_proved)
    canvas, nets, bounds = _two_strip_stranded_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert result.last_mile is not None
    assert result.last_mile.proved == 1
    assert result.last_mile.relation_skipped_siblings == 0
    assert len(result.last_mile.relation_strips) >= 2
    assert result.last_mile.relation_evidence


def test_a_cluster_with_a_sibling_never_runs_the_relaxed_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The soundness gate: unstaking a sibling can DISCONNECT a net.

    `_ends` offers merge points onto sibling paths and, for a walled-in lane,
    that is the only way in (`freeform.py:6834`-`6843`, `:7405`-`7411`).  So a
    cluster holding any net with a sibling must never reach run 2, or run 2
    would prove a net unroutable that it had itself cut off.
    """
    from flab2bp.layout import last_mile as last_mile_module

    calls: list[object] = []

    def always_proved(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        calls.append(problem)
        return last_mile_module.ClusterResult(
            last_mile_module.ClusterOutcome.PROVED, {}, 1, 0, 0.0
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_proved)
    canvas, nets, bounds = _sibling_stranded_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert len(calls) == 1, "run 2 must not start for a cluster with a sibling"
    assert result.last_mile is not None
    assert result.last_mile.proved == 1
    assert result.last_mile.relation_skipped_siblings == 1
    assert result.last_mile.relation_strips == ()
    assert result.exhaustive is True


def test_a_bounded_relaxed_run_records_no_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run 1 proves, run 2 does not close, so there is no relation to forbid."""
    from flab2bp.layout import last_mile as last_mile_module

    outcomes = [
        last_mile_module.ClusterOutcome.PROVED,
        last_mile_module.ClusterOutcome.BOUNDED,
    ]

    def scripted(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        outcome = outcomes.pop(0)
        return last_mile_module.ClusterResult(
            outcome,
            {},
            1,
            0,
            0.0,
            bound=(
                last_mile_module.ClusterBound.NONE
                if outcome is last_mile_module.ClusterOutcome.PROVED
                else last_mile_module.ClusterBound.NODES
            ),
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", scripted)
    canvas, nets, bounds = _two_strip_stranded_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")

    result = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    assert outcomes == []
    assert result.last_mile is not None
    assert result.last_mile.proved == 1
    assert result.last_mile.relation_strips == ()


def test_proof_scoped_no_goods_forwards_a_cluster_relation() -> None:
    attempt = _stranded_attempt_with_relation(strips=(0, 2))

    _relations, exact, clusters = freeform_module._proof_scoped_no_goods(
        attempt, _three_unit_strips()
    )

    assert exact is not None
    assert len(clusters) == 1
    assert clusters[0].strips == (0, 2)


def test_proof_scoped_no_goods_returns_no_relation_without_one() -> None:
    attempt = _stranded_attempt_with_relation(strips=())

    _relations, exact, clusters = freeform_module._proof_scoped_no_goods(
        attempt, _three_unit_strips()
    )

    assert exact is not None
    assert clusters == ()
```

`_two_strip_stranded_fixture()` is `_one_stranded_net_fixture()` with `NetId`s whose `source_strip` and `destination_strip` name two distinct strips, so `cluster_strips` returns at least two instances, **and with no two nets sharing a source lane or a destination lane** — `src_group` and `dst_group` are built from `(item, cargo_domain, source.y, source.x0, source.z)` and `(item, cargo_domain, dst.x, dst.y, dst.z)` (`freeform.py:7412`-`7415`, `:7394`-`7397`), so giving the nets different items is the simplest way to keep every group empty.

`_sibling_stranded_fixture()` is the same fixture with two nets sharing one source lane — the same `item`, `cargo_domain`, `source.y`, `source.x0` and `source.z` — so `src_group` is non-empty for both and the cluster is not sibling-free.

`_stranded_attempt_with_relation(strips=...)` builds a `PackAttempt` whose `routing` is an exhaustive `STRANDED` `DetailedRouteResult` carrying a `LastMileReport` with `relation_strips=strips` and `relation_evidence="cluster"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -v -k "relaxed_run or sibling or proof_scoped"`
Expected: FAIL — the relaxed-run tests with `assert () != ()` / `assert 0 >= 2` because nothing runs a second time, the sibling test with `AssertionError` on `relation_skipped_siblings` (the attribute does not exist yet), and the two `proof_scoped` tests with `ValueError: too many values to unpack (expected 2)`.

- [ ] **Step 3: Run CBS a second time on an emptied round, behind a sibling-free gate**

The relaxed environment is not a copy of the canvas: it is the round with **every** net unstaked, which is exactly the state `_route_all` enters at the top of each round (`freeform.py:8342`-`8343`), plus the cluster's five routing-derived rejection sets emptied.

**The gate is load-bearing and must be written first.** `_ends` builds part of its starts and goals from `_merge_frontier(canvas, paths, siblings, …)` (`freeform.py:7886`-`7895`, `:7934`-`7939`), and for a net whose lane is walled in by buildings that is *the only way in* — `_merge_frontier`'s docstring (`:6834`-`6843`) and the `src_group` comment (`:7405`-`7411`) both say so. Unstake the sibling and that net's `starts` come back empty, `_astar` reports `DYNAMIC_ACCESS` at zero expansions, CBS prices the net unrouted, the tree closes, and run 2 reports `PROVED` for a net it disconnected itself. So run 2 runs **only** for a cluster in which every net has empty `src_group` and `dst_group`; otherwise it is skipped and counted.

```python
    def _cluster_is_sibling_free(problem: last_mile.ClusterProblem) -> bool:
        """Whether unstaking the pack can take nothing away from this cluster.

        `_ends` offers merge points onto SIBLING paths, and for a walled-in
        lane that is the only way in.  A net with no siblings had no merge
        frontier to lose, so for such a cluster -- and only such a cluster --
        "every other net removed" is a relaxation rather than a mutilation.
        """
        return not any(
            src_group.get(index, ()) or dst_group.get(index, ())
            for index in problem.nets
        )

    def _relaxed_cluster_result(
        problem: last_mile.ClusterProblem,
    ) -> last_mile.ClusterResult | None:
        """Re-run CBS with the whole pack unstaked; see the Phase B spec 5.2.

        Callers MUST have checked `_cluster_is_sibling_free` first.

        The relaxation argument needs every routing-derived constraint gone
        too: four of the five per-net rejection sets are read inside `_ends`
        and the fifth, `rejected_path_cells`, is the search's `forbidden`
        argument (`freeform.py:7534`-`7538`).  All five are saved, emptied for
        the cluster's nets, and put back afterwards.

        `grid.reserved` needs no separate handling, and not because it is
        constant -- `_retire_served_roles` filters it and
        `_restore_unserved_roles` rebuilds it (`:7606`-`7610`, `:7624`-`7632`).
        The FULL sweep is what makes it right: `_restore_unserved_roles` skips
        a role only while another member of it is still in `paths` (`:7618`),
        and once every net is unstaked no member remains.
        """
        if budget["left"] <= 0 or _expired(deadline):
            return None
        rejections = (
            rejected_starts,
            rejected_goals,
            rejected_path_cells,
            rejected_source_hints,
            rejected_sink_hints,
        )
        saved = [
            {index: set(table[index]) for index in problem.nets if index in table}
            for table in rejections
        ]
        every = list(paths)
        held_all = {
            index: (
                source_hint.get(index),
                sink_hint.get(index),
                path_tap.get(index),
            )
            for index in every
        }
        staked = {index: paths[index] for index in every}
        before_all = _round_state()
        try:
            for table in rejections:
                for index in problem.nets:
                    table[index].clear()
            for index in every:
                _unstake(index)
            _capture(2, problem)
            return last_mile.solve_cluster(problem, _cluster_environment())
        finally:
            # The SAME verified restore run 1 uses, so run 2 cannot skip the
            # check that run 1 must pass.  Its return value is read by the
            # caller through `restore_mismatch`.
            _restore_staked(every, staked, held_all, before_all)
            for table, snapshot in zip(rejections, saved, strict=True):
                for index, cells in snapshot.items():
                    table[index].clear()
                    table[index].update(cells)
```

Then, in `_last_mile`'s `PROVED` branch (after `proved_stranded.update(round_stranded)`):

```python
            if not _cluster_is_sibling_free(problem):
                last_mile_counts["relation_skipped_siblings"] += 1
            else:
                mismatches = last_mile_counts["restore_mismatch"]
                relaxed = _relaxed_cluster_result(problem)
                if relaxed is not None:
                    _tally(relaxed)
                    if last_mile_counts["restore_mismatch"] != mismatches:
                        # Run 2 did not put the round back.  The incumbent the
                        # run-1 claim describes is no longer known to be the
                        # incumbent that was proved, so BOTH claims go.
                        last_mile_counts["proved"] -= 1
                        last_mile_counts["bounded"] += 1
                        proved_round = -1
                        proved_stranded.clear()
                    elif relaxed.outcome is last_mile.ClusterOutcome.PROVED:
                        relation_strips = last_mile.cluster_strips(
                            problem,
                            {
                                index: (
                                    _net_id(index).source_strip,
                                    _net_id(index).destination_strip,
                                )
                                for index in problem.nets
                            },
                        )
                        relation_evidence = (
                            f"cluster: nets={tuple(problem.nets)!r} "
                            f"truncated={problem.truncated} "
                            f"sibling_closed={problem.sibling_closed}"
                        )
```

Declare `nonlocal relation_strips, relation_evidence` at the top of `_last_mile` beside the existing `nonlocal`.

`ClusterProblem.sibling_closed` (every sibling *inside* the cluster) is **not** the gate — sibling-free is strictly stronger — and stays in the evidence blob as telemetry. Two stronger alternatives are recorded in the spec's §5.2 as follow-ups gated on the measured `last_mile_relation_skipped_siblings` count: passing the CBS node's own cluster paths to `_merge_frontier`, or unstaking only non-cluster non-sibling nets. **Neither is in this phase's scope**; do not implement either here, whatever the skip count turns out to be.

- [ ] **Step 4: Forward the relation through `_proof_scoped_no_goods` and into `_pack`**

Change `_proof_scoped_no_goods`'s return type to the 3-tuple and its two early `return` statements:

```python
    if local:
        return tuple(local), None, ()

    routing = attempt.routing
    if (
        not routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or not routing.failures
        or any(failure.kind is RouteFailureKind.BUDGET for failure in routing.failures)
    ):
        return (), None, ()
```

and, at its tail, after the `evidence` tuple is built:

```python
    report = routing.last_mile
    cluster_no_good = (
        None
        if report is None or not report.relation_strips
        else last_mile.relation_no_good(
            strips=report.relation_strips,
            origins=attempt.origins,
            outline=attempt.outline,
            height=attempt.height,
            evidence=report.relation_evidence,
        )
    )
    return (
        (),
        ExactPackNoGood(
            height=attempt.height,
            outline=attempt.outline,
            width=attempt.compact_width,
            origins=attempt.origins,
            evidence=evidence,
        ),
        () if cluster_no_good is None else (cluster_no_good,),
    )
```

In `lay_out`, beside `direct_relation_no_goods` (`freeform.py:16082`-`16083`) add:

```python
        cluster_relation_no_goods: list[ClusterRelationNoGood] = []
        cluster_relation_no_good_keys: set[ClusterRelationNoGood] = set()
```

clear both wherever `direct_relation_no_goods.clear()` runs (`freeform.py:16181`), unpack the third element at the call site (`freeform.py:16671`):

```python
                local_no_goods, exact_no_good, cluster_no_goods = _proof_scoped_no_goods(
                    attempt,
                    strips,
                )
                ...
                for cluster_no_good in cluster_no_goods:
                    if cluster_no_good in cluster_relation_no_good_keys:
                        continue
                    cluster_relation_no_good_keys.add(cluster_no_good)
                    cluster_relation_no_goods.append(cluster_no_good)
                    learned = True
```

and pass them to `_pack` (`freeform.py:16375`-`16376`):

```python
                cluster_relation_no_goods=tuple(cluster_relation_no_goods),
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/layout/test_freeform.py -v -k "relaxed_run or sibling or proof_scoped"
uv run pytest tests/layout/test_freeform.py -q -k "no_good or exhaustive"
```

Expected: the five new tests PASS, and the pre-existing no-good tests at `tests/layout/test_freeform.py:3382` and `:3418` still pass.

- [ ] **Step 6: Prove the replay digests still have not moved**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python scripts/route_bench.py --cases "$d/route-cases-universe-matrix-output-products.pkl" --rounds 3 --check
uv run python scripts/route_bench.py --cases "$d/route-cases-quantum-chip-all-products.pkl" --rounds 3 --check
```

Expected: both `MATCH`. The relaxed run unstakes and re-stakes the whole pack, so this is the step that catches a restore that silently moved a belt.

- [ ] **Step 7: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/last_mile.py tests/layout
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/last_mile.py
git add src/flab2bp/layout tests/layout
git commit -m "feat(layout): prove a cluster relation on an emptied round"
```

---

### Task 8: Sequence-pair consumption of the cluster relation

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py:2726` (`_ProjectionPackNoGood`), `:2729-2761` (`_projection_feedback_matches`), `:2767-2859` (`_projection_feedback_stage_update`), `:4700-4767` (the stage-boundary feedback selection)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `ClusterRelationNoGood` (Task 6), `DetailedRouteResult.last_mile` (Task 4), `last_mile.relation_no_good` (Task 6), `_decoded_pack`, `decode_state`, `problem.selected_sizes`, `StageBoundaryUpdate`.
- Produces: `type _ProjectionPackNoGood = finalize.ProjectionNoGood | ExactPackNoGood | ClusterRelationNoGood` and the matching branches. No other signature changes.

The compact-seed model has no no-good input — `solve_compact_seed` (`compact_seed.py:567`) takes a problem, seeds, a config, direct-eligibility targets, a deadline and a cancellation callback, and `PairwiseRelationSignature` (`compact_seed.py:147`) is a diagnostic of a solved packing, not a constraint surface. The existing relation-repair path is a hard state exclusion and is used instead; no energy penalty is introduced.

**Precondition for the wiring.** The branch this task extends is `elif detailed.placement is not None:` inside `transform_stage`, and `transform_stage` reaches it only when its `select_feedback_variant` parameter is true (`sequence_solver.py:4655`). Every test of the wiring must therefore pass `select_feedback_variant=True` and a `DetailedStageResult` whose `placement` is not `None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_cluster_relation_matches_a_state_that_repeats_it() -> None:
    problem, state, pack, signatures, channels = _two_strip_stage()
    origins = tuple(pack.at[index] for index in range(problem.size))
    no_good = ClusterRelationNoGood(
        height=pack.height,
        outline=problem.selected_sizes(state.variant_indices),
        strips=(0, 1),
        deltas=((0, 0), (origins[1][0] - origins[0][0], origins[1][1] - origins[0][1])),
        evidence=("cluster",),
    )

    assert sequence_solver._projection_feedback_matches(
        problem, state, pack, no_good, signatures
    )


def test_a_cluster_relation_stops_matching_once_a_strip_moves() -> None:
    problem, state, pack, signatures, channels = _two_strip_stage()
    no_good = ClusterRelationNoGood(
        height=pack.height,
        outline=problem.selected_sizes(state.variant_indices),
        strips=(0, 1),
        deltas=((0, 0), (999, 999)),
        evidence=("cluster",),
    )

    assert not sequence_solver._projection_feedback_matches(
        problem, state, pack, no_good, signatures
    )


def test_the_stage_boundary_moves_off_a_matching_cluster_relation() -> None:
    problem, state, pack, signatures, channels = _two_strip_stage()
    origins = tuple(pack.at[index] for index in range(problem.size))
    no_good = ClusterRelationNoGood(
        height=pack.height,
        outline=problem.selected_sizes(state.variant_indices),
        strips=(0, 1),
        deltas=((0, 0), (origins[1][0] - origins[0][0], origins[1][1] - origins[0][1])),
        evidence=("cluster",),
    )

    update = sequence_solver._projection_feedback_stage_update(
        problem,
        state,
        no_good,
        west_channels=channels,
        geometry_signatures=signatures,
        deadline=None,
        try_relation_update=True,
    )

    assert update is not None
    assert update.state != state


def _last_mile_relation_report() -> LastMileReport:
    return LastMileReport(
        invocations=1,
        solved=0,
        proved=1,
        bounded=0,
        commit_rejected=0,
        restore_mismatch=0,
        relation_skipped_siblings=0,
        nodes=3,
        expansions=10,
        seconds=0.01,
        relation_strips=(0, 1),
        relation_evidence="cluster: nets=(0, 1)",
    )


def _recorded_stage_update(
    monkeypatch: pytest.MonkeyPatch,
) -> list[object]:
    """Record which no-good the stage boundary was handed."""
    seen: list[object] = []
    original = sequence_solver._projection_feedback_stage_update

    def recording(
        problem: object,
        state: object,
        no_good: object,
        **kwargs: object,
    ) -> object:
        seen.append(no_good)
        return original(problem, state, no_good, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        sequence_solver, "_projection_feedback_stage_update", recording
    )
    return seen


def test_transform_stage_turns_a_routing_relation_into_stage_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring, with a projection failure present so precedence is exercised.

    `transform_stage` only reaches the branch this task extends when
    `select_feedback_variant` is true (`sequence_solver.py:4655`) and
    `detailed.placement` is not None, so both are supplied here.  The
    projection failure is one that does NOT map to a strip pair, so the
    `for failure in projection_failures:` loop leaves
    `projection_relation_feedback` as `None` and the cluster relation is what
    reaches the repairer.  Before this task's ordering fix, an assignment made
    BEFORE that loop would have been discarded by it.
    """
    harness = _stage_harness_with_two_strips()
    seen = _recorded_stage_update(monkeypatch)
    unmapped = finalize.ProjectionFailure(
        check="geom.band", buildings=(), detail="not a collide pair", band=0
    )

    update = harness.transform_stage(
        harness.height,
        harness.problem,
        harness.state,
        harness.feedback,
        harness.detailed_with(last_mile=_last_mile_relation_report()),
        0,
        (unmapped,),
        True,
    )

    assert update is not None
    assert seen and isinstance(seen[0], ClusterRelationNoGood)


def test_a_projection_failure_takes_precedence_over_a_cluster_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A geom.collide pair is a static refusal and outranks a routing relation."""
    harness = _stage_harness_with_two_strips()
    seen = _recorded_stage_update(monkeypatch)

    update = harness.transform_stage(
        harness.height,
        harness.problem,
        harness.state,
        harness.feedback,
        harness.detailed_with(last_mile=_last_mile_relation_report()),
        0,
        (harness.collide_failure,),
        True,
    )

    assert update is not None
    assert seen and not isinstance(seen[0], ClusterRelationNoGood)
```

`_two_strip_stage()` builds a two-strip `PlacementProblem`, an `AnnealState`, its decoded `_Pack`, the geometry signatures and the west channels, in the style of the existing `test_sequence_solver.py` stage fixtures. `_stage_harness_with_two_strips()` exposes the `transform_stage` closure that `_production_run` builds, together with the `height`, `problem`, `state`, `feedback`, a `detailed_with(**overrides)` factory returning a `DetailedStageResult` whose `placement` is not `None` and whose `routing` carries the given `last_mile` report, and a `collide_failure` — a `finalize.ProjectionFailure` with `check="geom.collide"` and two valid building indices, which is what `_projection_strip_pair` (`freeform.py:2854`) requires to map to a strip pair. Build the harness by extracting the existing `test_sequence_solver.py` production-run fixture rather than by re-implementing `_production_run`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -v -k "cluster_relation or transform_stage or precedence"`
Expected: FAIL with `AttributeError: 'ClusterRelationNoGood' object has no attribute 'projection_pair'` raised inside `_projection_feedback_matches` for the first three, and `assert seen and ...` (empty list) for the two wiring tests.

- [ ] **Step 3: Extend the union and the matcher**

```python
type _ProjectionPackNoGood = (
    finalize.ProjectionNoGood | ExactPackNoGood | ClusterRelationNoGood
)
```

At the top of `_projection_feedback_matches`, before the `ProjectionNoGood` branch:

```python
    if isinstance(no_good, ClusterRelationNoGood):
        if (
            pack.height != no_good.height
            or problem.selected_sizes(state.variant_indices) != no_good.outline
            or any(strip >= problem.size for strip in no_good.strips)
        ):
            return False
        anchor = pack.at[no_good.strips[0]]
        return all(
            (
                pack.at[strip][0] - anchor[0],
                pack.at[strip][1] - anchor[1],
            )
            == delta
            for strip, delta in zip(no_good.strips, no_good.deltas, strict=True)
        )
```

- [ ] **Step 4: Extend the pair iterator**

In `_projection_feedback_stage_update`, replace the pair selection block (`sequence_solver.py:2799`-`2812`) so the cluster case comes first:

```python
    if isinstance(no_good, ClusterRelationNoGood):
        anchor = no_good.strips[0]
        pairs = iter(tuple((anchor, strip) for strip in no_good.strips[1:]))
    elif isinstance(no_good, finalize.ProjectionNoGood):
        pairs = iter(((no_good.left_strip, no_good.right_strip),))
    elif no_good.projection_pair is not None:
        pair = no_good.projection_pair
        pairs = iter(((pair.left_strip, pair.right_strip),))
    else:
        pairs = islice(
            (
                (left, right)
                for left in range(problem.size)
                for right in range(left + 1, problem.size)
            ),
            _EXACT_PROJECTION_FALLBACK_PAIR_TRIALS,
        )
```

- [ ] **Step 5: Feed a routing-proved relation into the stage boundary**

In `transform_stage`, in the `elif detailed.placement is not None:` branch (`sequence_solver.py:4692`), **after** the `for failure in projection_failures:` loop, not before it.

Placing it before would be a silent bug: the loop assigns `projection_relation_feedback` itself (`sequence_solver.py:4730`) and would overwrite the cluster entry the moment any projection failure maps to a strip pair. Placing it after, guarded on `is None`, states the precedence explicitly — **a projection failure wins over a cluster relation**, because a `geom.collide` between two buildings is a static-geometry refusal that recurs whatever the router does, while the cluster relation is about routing:

```python
                if projection_relation_feedback is None:
                    report = detailed.routing.last_mile
                    if report is not None and report.relation_strips:
                        cluster_no_good = last_mile.relation_no_good(
                            strips=report.relation_strips,
                            origins=tuple(
                                pack.at[index] for index in range(len(selected))
                            ),
                            outline=problem.selected_sizes(state.variant_indices),
                            height=pack.height,
                            evidence=report.relation_evidence,
                        )
                        if cluster_no_good is not None:
                            projection_relation_feedback = (
                                problem,
                                projection_failures,
                                cluster_no_good,
                            )
```

Import `ClusterRelationNoGood` and `LastMileReport` from `flab2bp.layout.route_feedback` and `last_mile` from `flab2bp.layout` at the top of `sequence_solver.py`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_solver.py -v -k "cluster_relation or transform_stage or precedence"`
Expected: PASS, 5 passed.

- [ ] **Step 7: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "feat(layout): exclude a proved cluster relation in sequence-pair states"
```

---

### Task 9: Cluster capture, the replay bench, and the wall floor measurement

**Files:**
- Create: `scripts/last_mile_bench.py`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/cluster-cases-universe-matrix-output-products.pkl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/cluster-cases-quantum-chip-all-products.pkl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/cluster-bench.txt`
- Modify: `scripts/route_bench.py` (`capture_clusters`, `--stranded`)
- Test: `tests/scripts/test_last_mile_bench.py`

**Interfaces:**
- Consumes: `scripts.route_bench._snapshot`, `flab2bp.layout.last_mile.{solve_cluster, ClusterEnvironment, ClusterProblem, ClusterResult, ClusterOutcome}`, `flab2bp.layout.freeform._astar`.
- Produces: `scripts/route_bench.py::capture_clusters(url_id, budget, cap, out, policy) -> None`, the `--stranded` flag, and `scripts/last_mile_bench.py::{digest(results) -> str, bench(path, rounds, check) -> int}`.

- [ ] **Step 1: Add the explicit capture hook to `last_mile.py`**

Frame inspection is forbidden here: a bench that reads `_route_all`'s locals through `sys._getframe` breaks silently the first time a local is renamed, and it cannot be type-checked. `_route_all` hands the capture everything, through a declared type.

Append to `src/flab2bp/layout/last_mile.py`:

```python
@dataclass(frozen=True, slots=True)
class ClusterCapture:
    """Everything a replay needs to re-run one live cluster search."""

    run: int                       # 1 environment run, 2 relaxed run
    canvas: object                 # freeform._Canvas, opaque here
    grid: object                   # freeform._Grid, opaque here
    history: Mapping[Cell, float]
    pressure: float
    bounds: tuple[int, int, int, int]
    problem: ClusterProblem
    ends: Mapping[int, tuple[list[Cell], set[Cell], frozenset[Cell]]]
    budget_left: int
    budget_floor: int
    deadline_remaining: float | None


#: Developer-tool hook.  ``None`` in production; ``scripts/route_bench.py``
#: sets it for the length of one capture run.  A module-level callback rather
#: than a parameter because the alternative is threading a bench-only argument
#: through ``lay_out``, ``_sweep``, ``_build`` and ``_build_prepared``.
CAPTURE: Callable[[ClusterCapture], None] | None = None
```

`canvas` and `grid` are typed `object` because `last_mile` must not import `freeform` at runtime; the bench casts them back.

- [ ] **Step 2: Complete `_capture` at `_route_all` scope**

Task 4 added `_capture(run, problem)` as a `return None` stub at `_route_all` scope, beside `_cluster_environment`. It lives there — not inside `_last_mile` — because **both** runs call it: `_capture(1, problem)` in `_last_mile` and `_capture(2, problem)` inside `_relaxed_cluster_result` (Task 7), and a closure defined inside `_last_mile` would not be in scope for the second. Replace the stub body:

```python
    def _capture(run: int, problem: last_mile.ClusterProblem) -> None:
        """Hand a developer-tool hook everything needed to replay this run.

        Called AFTER the unstake that builds each run's environment -- the
        cluster release for run 1, the whole-pack sweep for run 2 -- so what
        the bench snapshots is the grid the search will actually see.
        """
        hook = last_mile.CAPTURE
        if hook is None:
            return
        ends: dict[int, tuple[list[Cell], set[Cell], frozenset[Cell]]] = {}
        for index in problem.nets:
            starts, goals, _offers = _ends(index)
            ends[index] = (list(starts), set(goals), canvas.routing_ports)
            canvas.routing_ports = frozenset()
        hook(
            last_mile.ClusterCapture(
                run=run,
                canvas=canvas,
                grid=grid,
                history=history,
                pressure=pressure,
                bounds=bounds,
                problem=problem,
                ends=ends,
                budget_left=budget["left"],
                budget_floor=last_mile_floor,
                deadline_remaining=(
                    None if deadline is None else deadline - time.monotonic()
                ),
            )
        )
```

The `ends` mapping is keyed by **net index**, not by cell. `_ends`' only side effect is `canvas.routing_ports`, which is cleared after each call, so the capture is invisible to the search that follows.

- [ ] **Step 3: Add the cluster capture to `route_bench.py`**

```python
def capture_clusters(
    url_id: str,
    budget: float,
    cap: int,
    out: Path,
    policy: CandidatePolicy = CandidatePolicy.NO_PROLIFERATOR,
) -> None:
    """Snapshot every last-mile invocation of one real cell run.

    The hook is `last_mile.CAPTURE` rather than `_astar`, because the stranded
    state Phase B cares about only exists at the moment `_route_all` would give
    up, and that is the one call that sees it.
    """
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]

    cases: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def sink(shot: last_mile.ClusterCapture) -> None:
        if len(cases) + len(pending) >= cap:
            return
        canvas = cast(freeform._Canvas, shot.canvas)
        grid = cast(freeform._Grid, shot.grid)
        shot_canvas, shot_grid, shot_hist = _snapshot(canvas, grid, dict(shot.history))
        pending.append(
            {
                "kind": "cluster",
                "run": shot.run,
                "canvas": shot_canvas,
                "grid": shot_grid,
                "history": shot_hist,
                "problem": shot.problem,
                "ends": {
                    index: (list(starts), set(goals), ports)
                    for index, (starts, goals, ports) in shot.ends.items()
                },
                "pressure": shot.pressure,
                "bounds": shot.bounds,
                "budget_left": shot.budget_left,
                "budget_floor": shot.budget_floor,
                "deadline_remaining": shot.deadline_remaining,
            }
        )

    orig_solve = last_mile.solve_cluster

    def spy(
        problem: last_mile.ClusterProblem,
        environment: last_mile.ClusterEnvironment,
    ) -> last_mile.ClusterResult:
        result = orig_solve(problem, environment)
        # `CAPTURE` fires before the solve, so the pending shot is this one's.
        while pending:
            shot = pending.pop(0)
            shot["result"] = result
            cases.append(shot)
        return result

    last_mile.CAPTURE = sink
    last_mile.solve_cluster = spy
    try:
        freeform.FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=1,
        ).lay_out(spec, time_budget_s=budget)
    except NoValidLayout:
        pass
    finally:
        last_mile.CAPTURE = None
        last_mile.solve_cluster = orig_solve
    out.write_bytes(pickle.dumps(cases, protocol=5))
    outcomes = [case["result"].outcome.value for case in cases]
    bounds_hit = [case["result"].bound.value for case in cases]
    print(
        f"captured {len(cases)} cluster searches -> {out} "
        f"({out.stat().st_size / 1e6:.1f} MB); "
        + ", ".join(f"{value}={outcomes.count(value)}" for value in sorted(set(outcomes)))
        + "; bounds "
        + ", ".join(
            f"{value or 'none'}={bounds_hit.count(value)}"
            for value in sorted(set(bounds_hit))
        )
    )
```

Add `from typing import Any, cast`, `from flab2bp.layout import last_mile`, `--stranded` to `build_parser`, and route it in `main`:

```python
    ap.add_argument("--stranded", action="store_true")
```

```python
    if args.capture:
        out = args.cases or Path(f"/tmp/route-cases-{args.capture}-{args.policy.value}.pkl")
        if args.stranded:
            capture_clusters(args.capture, args.budget, args.cap, out, args.policy)
        else:
            capture(args.capture, args.budget, args.every, args.cap, out, args.policy)
        return 0
```

`solve_cluster` is still wrapped, but only to attach the result to the shot the hook already produced — no frame is read.

- [ ] **Step 4: Write the failing tests**

Write these before `scripts/last_mile_bench.py` exists; step 6 creates it.

```python
# tests/scripts/test_last_mile_bench.py
from __future__ import annotations

from flab2bp.layout import last_mile

from scripts import last_mile_bench


def test_the_digest_separates_outcomes_and_paths() -> None:
    solved = last_mile.ClusterResult(
        last_mile.ClusterOutcome.SOLVED, {0: ((0, 0, 0),)}, 1, 1, 0.0
    )
    other = last_mile.ClusterResult(
        last_mile.ClusterOutcome.SOLVED, {0: ((1, 0, 0),)}, 1, 1, 0.0
    )
    proved = last_mile.ClusterResult(last_mile.ClusterOutcome.PROVED, {}, 1, 1, 0.0)

    assert last_mile_bench.digest([solved]) != last_mile_bench.digest([other])
    assert last_mile_bench.digest([solved]) != last_mile_bench.digest([proved])
    assert last_mile_bench.digest([proved]) == last_mile_bench.digest([proved])


def test_a_wall_bounded_case_is_not_replayable() -> None:
    """A clock cannot be replayed, so those cases are skipped, not diffed."""
    wall = {
        "result": last_mile.ClusterResult(
            last_mile.ClusterOutcome.BOUNDED,
            {},
            1,
            1,
            0.0,
            bound=last_mile.ClusterBound.WALL,
        )
    }
    nodes = {
        "result": last_mile.ClusterResult(
            last_mile.ClusterOutcome.BOUNDED,
            {},
            1,
            1,
            0.0,
            bound=last_mile.ClusterBound.NODES,
        )
    }

    assert last_mile_bench._replayable(wall) is False
    assert last_mile_bench._replayable(nodes) is True
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run pytest tests/scripts/test_last_mile_bench.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.last_mile_bench'`.

- [ ] **Step 6: Write the replay bench**

```python
# scripts/last_mile_bench.py
"""Replay captured last-mile cluster searches outside a whole cell run.

    uv run python scripts/route_bench.py --capture universe-matrix \
        --policy output-products --stranded --budget 30 \
        --cases /tmp/cluster-cases.pkl
    uv run python scripts/last_mile_bench.py --cases /tmp/cluster-cases.pkl --check

WHY A REPLAY.  A cluster search only happens on a pack that stranded, which on
the cells that matter is one pack in five of a thirty-second run.  Capturing
the search's real environment and replaying it turns a thirty-second
nondeterministic experiment into a millisecond deterministic one, and
``--check`` proves a candidate changed the SPEED and not the ANSWER.
"""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flab2bp.layout import last_mile  # noqa: E402
from flab2bp.layout.freeform import _astar  # noqa: E402


def _environment(case: dict[str, Any], budget: dict[str, int]) -> last_mile.ClusterEnvironment:
    canvas = case["canvas"]
    grid = case["grid"]

    floor = case["budget_floor"]

    def search(index: int, constraints: frozenset[tuple[int, int, int]]) -> Any:
        starts, goals, routing_ports = case["ends"][index]
        # The live search ran with this net's own ports readable; without that
        # the replay refuses starts the capture admitted and the digest differs
        # for a reason that has nothing to do with the search.
        canvas.routing_ports = routing_ports
        # CAP EACH SEARCH THE WAY THE LIVE PASS DOES.  A capture that ended
        # `bound is BUDGET` because one search hit its private allowance would
        # otherwise replay with no per-search cap, take a different branch, and
        # report DIFFER for something that is not a regression.  Same private
        # dict, same write-back.
        allowance = min(
            last_mile.B_LOW_LEVEL_EXPANSIONS,
            max(0, budget["left"] - floor),
        )
        private = {"left": allowance}
        found = _astar(
            canvas,
            list(starts),
            set(goals),
            case["history"],
            case["pressure"],
            case["bounds"],
            private,
            None,
            {},
            grid,
            (),
            (),
            constraints,
            None,
        )
        budget["left"] -= allowance - private["left"]
        return found

    return last_mile.ClusterEnvironment(
        search=search,
        offers=lambda _index: ({}, {}, {}),
        budget_left=lambda: budget["left"],
        # REPLAY THE CAPTURED BOUNDS, not an unbounded run.  A case that ended
        # BOUNDED because the shared floor was reached would otherwise replay
        # under an infinite budget, reach PROVED, and report DIFFER for a
        # reason that is not a regression.
        budget_floor=floor,
        expired=lambda: False,
    )


def digest(results: list[last_mile.ClusterResult]) -> str:
    hasher = hashlib.sha256()
    for result in results:
        hasher.update(result.outcome.value.encode())
        for index in sorted(result.paths):
            hasher.update(repr((index, result.paths[index])).encode())
    return hasher.hexdigest()[:16]


def _replayable(case: dict[str, Any]) -> bool:
    """Whether the captured run's bound can be reproduced without a clock."""
    return case["result"].bound is not last_mile.ClusterBound.WALL


def bench(path: Path, rounds: int, check: bool) -> int:
    cases: list[dict[str, Any]] = pickle.loads(path.read_bytes())
    if not cases:
        print("no cluster cases in this capture")
        return 1
    replayable = [case for case in cases if _replayable(case)]
    skipped = len(cases) - len(replayable)
    if not replayable:
        print(f"every one of {len(cases)} captured searches was wall-bounded")
        return 1
    best: tuple[float, list[last_mile.ClusterResult]] | None = None
    for r in range(rounds):
        got: list[last_mile.ClusterResult] = []
        t0 = time.perf_counter()
        for case in replayable:
            budget = {"left": case["budget_left"]}
            got.append(last_mile.solve_cluster(case["problem"], _environment(case, budget)))
        dt = time.perf_counter() - t0
        if best is None or dt < best[0]:
            best = (dt, got)
        nodes = sum(result.nodes for result in got)
        print(f"  round {r + 1}: {dt:.3f}s  {nodes} nodes")
    assert best is not None
    dt, got = best
    counts = {outcome.value: 0 for outcome in last_mile.ClusterOutcome}
    for result in got:
        counts[result.outcome.value] += 1
    sizes = [len(case["problem"].nets) for case in replayable]
    truncated = sum(1 for case in replayable if case["problem"].truncated)
    runs = {run: sum(1 for case in replayable if case["run"] == run) for run in (1, 2)}
    print(
        f"BEST {dt:.3f}s  {len(replayable)} clusters  "
        f"(run1={runs[1]} run2={runs[2]}, skipped {skipped} wall-bounded)  "
        f"sizes {min(sizes)}-{max(sizes)}  truncated {truncated}  "
        + "  ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        + f"  digest {digest(got)}"
    )
    if check:
        want = digest([case["result"] for case in replayable])
        same = digest(got)
        print(f"captured digest {want}   replay digest {same}   "
              f"{'MATCH' if want == same else 'DIFFER'}")
        return 0 if want == same else 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return bench(args.cases, args.rounds, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/scripts/test_last_mile_bench.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 8: Capture and replay the two target cells**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python scripts/route_bench.py --capture universe-matrix --policy output-products \
  --stranded --budget 30 --cap 32 \
  --cases "$d/cluster-cases-universe-matrix-output-products.pkl"
uv run python scripts/route_bench.py --capture quantum-chip --policy all-products \
  --stranded --budget 30 --cap 32 \
  --cases "$d/cluster-cases-quantum-chip-all-products.pkl"
{
  uv run python scripts/last_mile_bench.py --cases "$d/cluster-cases-universe-matrix-output-products.pkl" --rounds 3 --check
  uv run python scripts/last_mile_bench.py --cases "$d/cluster-cases-quantum-chip-all-products.pkl" --rounds 3 --check
} | tee "$d/cluster-bench.txt"
```

Expected: each capture reports at least one cluster search, and each replay prints `MATCH` and exits 0.

**Decision rule on the outcome distribution.** Read the two `BEST` lines:
- If `solved` is non-zero on both cells, continue to Task 10; the phase's premise holds.
- If `solved` is zero and `proved` dominates with `sizes 1-1` on both cells, the surviving stranded nets are stranded by static geometry, not contention. Stop at Task 11, run the gate anyway, and write that finding into `gate.md` as a coverage failure with these numbers. The no-goods still ship: they are correct and Phase C consumes them.
- If `bounded` dominates, record `nodes` per cluster from the round lines. If it is at `B_MAX_CBS_NODES`, the finding is "CBS does not close on these clusters at 512 nodes"; record it in `gate.md` and do not raise the cap in this phase.

- [ ] **Step 9: Measure the wall floor `B_MIN_SECONDS`**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python - <<'EOF' | tee -a "$d/cluster-bench.txt"
import pickle, statistics, sys
sys.path.insert(0, "src")
d = "docs/superpowers/evidence/2026-09-02-phase-b-last-mile/"
for name in (
    "cluster-cases-universe-matrix-output-products.pkl",
    "cluster-cases-quantum-chip-all-products.pkl",
):
    cases = pickle.loads(open(d + name, "rb").read())
    seconds = [c["result"].seconds for c in cases]
    if not seconds:
        print(f"{name}: no cluster searches")
        continue
    print(f"{name}: n={len(seconds)} max={max(seconds):.3f}s "
          f"mean={statistics.fmean(seconds):.3f}s")
EOF
```

Decision rule: set `B_MIN_SECONDS` to the larger of `0.35` and `2 x` the maximum observed `seconds` across both files, rounded up to two decimals. If the measurement exceeds `0.35`, edit `src/flab2bp/layout/last_mile.py`'s `B_MIN_SECONDS` to the measured value in this task and say so in the commit message. If it is at or under `0.35`, leave the default and record the measurement.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check scripts/route_bench.py scripts/last_mile_bench.py tests/scripts src/flab2bp/layout/last_mile.py
uv run mypy scripts/last_mile_bench.py src/flab2bp/layout/last_mile.py
git add scripts/route_bench.py scripts/last_mile_bench.py tests/scripts/test_last_mile_bench.py src/flab2bp/layout/last_mile.py docs/superpowers/evidence/2026-09-02-phase-b-last-mile
git commit -m "bench: capture and replay last-mile cluster searches"
```

---

### Task 10: Telemetry in `placement.stats` and the profiler

**Files:**
- Modify: `src/flab2bp/layout/base.py:198-336` (`PlacementStats`)
- Modify: `src/flab2bp/layout/freeform.py:14059-14071` (the `Placement` stats dict in `_build_prepared`)
- Modify: `scripts/route_profile.py:103-106` (`PHASES`), `:132-…` (`install`)
- Test: `tests/layout/test_freeform.py`, `tests/scripts/test_route_profile.py`

**Interfaces:**
- Consumes: `DetailedRouteResult.last_mile` (Task 4).
- Produces: eleven `float` keys on `PlacementStats` — `last_mile_invocations`, `last_mile_solved`, `last_mile_proved`, `last_mile_bounded`, `last_mile_commit_rejected`, `last_mile_restore_mismatch`, `last_mile_relation_skipped_siblings`, `last_mile_nodes`, `last_mile_expansions`, `last_mile_seconds`, `last_mile_relation_strips` — a `"last_mile"` entry in the profiler's `phases` object, and a `"last_mile_stats"` object in the profiler's JSON row. Sequence-pair inherits the stats keys for free: its stats start from `placement.stats.copy()` (`sequence_solver.py:5348`) and that placement came from the same `_build_prepared`.

**Why the profiler row matters.** `scripts/audit.py` rows carry no `stats` object, so the gate record cannot read these counters out of the audit JSONL — it would get zeros for every cell and conclude the pass never ran. The profiler is the only path, which is why this task adds the JSON field and not only the phase timer.

- [ ] **Step 1: Write the failing tests**

```python
def test_placement_stats_count_the_last_mile_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not merely that the key exists: that the monkeypatched outcome is counted."""
    from flab2bp.layout import last_mile as last_mile_module

    def always_bounded(
        problem: last_mile_module.ClusterProblem,
        environment: last_mile_module.ClusterEnvironment,
    ) -> last_mile_module.ClusterResult:
        return last_mile_module.ClusterResult(
            last_mile_module.ClusterOutcome.BOUNDED,
            {},
            7,
            11,
            0.25,
            bound=last_mile_module.ClusterBound.NODES,
        )

    monkeypatch.setattr(last_mile_module, "solve_cluster", always_bounded)
    canvas, nets, bounds = _one_stranded_net_fixture()
    belt_id = catalog.item_id("conveyor-belt-mk-i")
    routing = freeform_module._route_all(
        canvas,
        nets,
        belt_id,
        catalog.building(belt_id).model_index,
        bounds,
    )

    stats = freeform_module._last_mile_stats(routing.last_mile)

    assert stats["last_mile_invocations"] == 1.0
    assert stats["last_mile_bounded"] == 1.0
    assert stats["last_mile_solved"] == 0.0
    assert stats["last_mile_nodes"] == 7.0
    assert stats["last_mile_expansions"] == 11.0


def test_placement_stats_default_to_zero_without_a_report() -> None:
    stats = freeform_module._last_mile_stats(None)

    assert stats["last_mile_invocations"] == 0.0
    assert set(stats) == {
        "last_mile_invocations",
        "last_mile_solved",
        "last_mile_proved",
        "last_mile_bounded",
        "last_mile_commit_rejected",
        "last_mile_restore_mismatch",
        "last_mile_relation_skipped_siblings",
        "last_mile_nodes",
        "last_mile_expansions",
        "last_mile_seconds",
        "last_mile_relation_strips",
    }
```

```python
# tests/scripts/test_route_profile.py
def test_last_mile_is_a_profiled_phase() -> None:
    from scripts import route_profile

    assert "last_mile" in route_profile.PHASES


def test_the_profiler_row_carries_the_last_mile_counters() -> None:
    """The audit has no stats object, so this row is the only telemetry path."""
    from scripts import route_profile

    row = route_profile._last_mile_row({"last_mile_invocations": 2.0})

    assert row == {"last_mile_invocations": 2.0}
    assert route_profile._last_mile_row({}) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -v -k "last_mile_stats or last_mile_outcome" tests/scripts/test_route_profile.py -v`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.freeform' has no attribute '_last_mile_stats'` and `assert 'last_mile' in (...)`.

- [ ] **Step 3: Add the keys to `PlacementStats`**

In `src/flab2bp/layout/base.py`, inside `class PlacementStats(TypedDict, total=False)`, in the file's existing alphabetical position:

```python
    last_mile_bounded: float
    last_mile_commit_rejected: float
    last_mile_expansions: float
    last_mile_invocations: float
    last_mile_nodes: float
    last_mile_proved: float
    last_mile_relation_skipped_siblings: float
    last_mile_relation_strips: float
    last_mile_restore_mismatch: float
    last_mile_seconds: float
    last_mile_solved: float
```

- [ ] **Step 4: Write them once, in `_build_prepared`**

In the `stats={...}` literal (`freeform.py:14059`-`14071`), after `"direct_inserts"`:

```python
            **_last_mile_stats(internal_routing.last_mile),
```

and add the helper beside `_build_prepared`:

```python
def _last_mile_stats(report: LastMileReport | None) -> dict[str, float]:
    """Flatten the last-mile report so both strategies report it identically."""
    if report is None:
        return {
            "last_mile_invocations": 0.0,
            "last_mile_solved": 0.0,
            "last_mile_proved": 0.0,
            "last_mile_bounded": 0.0,
            "last_mile_commit_rejected": 0.0,
            "last_mile_restore_mismatch": 0.0,
            "last_mile_relation_skipped_siblings": 0.0,
            "last_mile_nodes": 0.0,
            "last_mile_expansions": 0.0,
            "last_mile_seconds": 0.0,
            "last_mile_relation_strips": 0.0,
        }
    return {
        "last_mile_invocations": float(report.invocations),
        "last_mile_solved": float(report.solved),
        "last_mile_proved": float(report.proved),
        "last_mile_bounded": float(report.bounded),
        "last_mile_commit_rejected": float(report.commit_rejected),
        "last_mile_restore_mismatch": float(report.restore_mismatch),
        "last_mile_relation_skipped_siblings": float(report.relation_skipped_siblings),
        "last_mile_nodes": float(report.nodes),
        "last_mile_expansions": float(report.expansions),
        "last_mile_seconds": report.seconds,
        "last_mile_relation_strips": float(len(report.relation_strips)),
    }
```

- [ ] **Step 5: Add the profiler phase**

In `scripts/route_profile.py`, extend `PHASES`:

```python
PHASES = (
    "plan_strips", "strip_families", "prepare", "place_coaters", "coater_frame_bans",
    "junction_ban", "power_plan", "static_risks", "relaxed_search", "last_mile",
    "finalize", "validate",
)
```

and in `install`, beside the other shims:

```python
    orig_last_mile = last_mile.solve_cluster

    def timed_last_mile(
        problem: last_mile.ClusterProblem,
        environment: last_mile.ClusterEnvironment,
    ) -> last_mile.ClusterResult:
        t0 = time.perf_counter()
        try:
            return orig_last_mile(problem, environment)
        finally:
            tally.add("last_mile", time.perf_counter() - t0)

    last_mile.solve_cluster = timed_last_mile
```

restoring it in the `restore()` closure the same way every other shim is restored, and add `from flab2bp.layout import last_mile` to the script's imports.

- [ ] **Step 6: Put the counters in the profiler's JSON row**

`main` currently throws the returned `Placement` away (`scripts/route_profile.py:514`-`516`). Keep it, and add the extractor beside `PHASES`:

```python
_LAST_MILE_KEYS = (
    "last_mile_invocations",
    "last_mile_solved",
    "last_mile_proved",
    "last_mile_bounded",
    "last_mile_commit_rejected",
    "last_mile_restore_mismatch",
    "last_mile_relation_skipped_siblings",
    "last_mile_nodes",
    "last_mile_expansions",
    "last_mile_seconds",
    "last_mile_relation_strips",
)


def _last_mile_row(stats: Mapping[str, object]) -> dict[str, float]:
    """The last-mile counters, if this run produced any.

    `scripts/audit.py` rows carry no `stats` object, so this is the ONLY path
    by which these numbers reach a gate record.  An empty dict here means the
    run never entered the pass, which is a fact worth printing rather than a
    zero worth inventing.
    """
    return {
        key: float(str(stats[key])) for key in _LAST_MILE_KEYS if key in stats
    }
```

In `main`, capture the placement and add the field:

```python
        placement = None
        try:
            if prof is not None:
                prof.enable()
            placement = _strategy(args.strategy)(workers=args.workers).lay_out(
                spec, time_budget_s=args.budget
            )
        except NoValidLayout as exc:
            verdict = f"REFUSED: {exc.reason[:90]}"
```

and, in the `json.dumps({...})` literal, beside `"route_backend"`:

```python
                "last_mile_stats": (
                    {} if placement is None else _last_mile_row(placement.stats)
                ),
```

Add `Mapping` to the script's `collections.abc` import if it is not there.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/layout/test_freeform.py -v -k "last_mile_stats or last_mile_outcome"
uv run pytest tests/scripts/test_route_profile.py -q
```

Expected: PASS, 4 passed.

- [ ] **Step 8: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check src/flab2bp/layout/base.py src/flab2bp/layout/freeform.py scripts/route_profile.py tests
uv run mypy src/flab2bp/layout/base.py src/flab2bp/layout/freeform.py scripts/route_profile.py
git add src/flab2bp/layout/base.py src/flab2bp/layout/freeform.py scripts/route_profile.py tests
git commit -m "feat(layout): report the last-mile pass in placement stats and the profiler"
```

---

### Task 11: The regression-aware gate and the three-round corpus audit

**Files:**
- Modify: `scripts/audit_compare.py:62-116` (`compare`), `:127-156` (`main`)
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/candidate-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/digests-after.txt`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/last-mile-profile.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/gate.md`
- Test: `tests/scripts/test_audit_compare.py`

**Interfaces:**
- Consumes: `scripts/audit.py --json` JSONL rows with keys `strategy`, `url_id`, `spec_index`, `spec_label`, `power`, `budget`, `status`, `area`, `seconds`, `detail` — **and no `stats` object**; `scripts/route_profile.py --json`'s `last_mile_stats` field (Task 10); the Task 1 baselines; the Task 1 and Task 9 digests.
- Produces:

```python
def compare(
    baseline: Iterable[Mapping[str, object]],
    candidate: Iterable[Mapping[str, object]],
    *,
    noise_area: float,
    p95_seconds: float,
    expect_cells: int | None = None,
    regressions_only: bool = False,
    require_clean: frozenset[str] = frozenset(),
) -> Verdict: ...
```

and the CLI flags `--regressions-only` and `--require-clean STRATEGY/URL_ID/SPEC_LABEL` (repeatable).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_carried_over_refusal_does_not_fail_a_regression_only_run() -> None:
    baseline = [
        _row("freeform", "graphene", 0, "graphene/a", "CLEAN", 100.0, 1.0),
        _row("freeform", "quantum-chip", 1, "quantum-chip/all-products", "REFUSED", 0.0, 30.0),
    ]
    candidate = [
        _row("freeform", "graphene", 0, "graphene/a", "CLEAN", 100.0, 1.0),
        _row("freeform", "quantum-chip", 1, "quantum-chip/all-products", "REFUSED", 0.0, 30.0),
    ]

    verdict = audit_compare.compare(
        baseline,
        candidate,
        noise_area=0.013,
        p95_seconds=30.0,
        expect_cells=2,
        regressions_only=True,
    )

    assert verdict.passed is True
    assert any(reason.startswith("CARRIED:") for reason in verdict.notes)


def test_a_new_refusal_fails_a_regression_only_run() -> None:
    baseline = [_row("freeform", "graphene", 0, "graphene/a", "CLEAN", 100.0, 1.0)]
    candidate = [_row("freeform", "graphene", 0, "graphene/a", "REFUSED", 0.0, 4.0)]

    verdict = audit_compare.compare(
        baseline,
        candidate,
        noise_area=0.013,
        p95_seconds=30.0,
        expect_cells=1,
        regressions_only=True,
    )

    assert verdict.passed is False
    assert any(reason.startswith("REGRESSION:") for reason in verdict.reasons)


def test_a_required_cell_that_stays_refused_fails() -> None:
    baseline = [
        _row("freeform", "quantum-chip", 1, "quantum-chip/all-products", "REFUSED", 0.0, 30.0)
    ]
    candidate = [
        _row("freeform", "quantum-chip", 1, "quantum-chip/all-products", "REFUSED", 0.0, 30.0)
    ]

    verdict = audit_compare.compare(
        baseline,
        candidate,
        noise_area=0.013,
        p95_seconds=30.0,
        expect_cells=1,
        regressions_only=True,
        require_clean=frozenset({"freeform/quantum-chip/quantum-chip/all-products"}),
    )

    assert verdict.passed is False
    assert any(reason.startswith("NOT CLEAN:") for reason in verdict.reasons)


def test_the_default_mode_is_unchanged() -> None:
    baseline = [_row("freeform", "graphene", 0, "graphene/a", "CLEAN", 100.0, 1.0)]
    candidate = [_row("freeform", "graphene", 0, "graphene/a", "REFUSED", 0.0, 4.0)]

    verdict = audit_compare.compare(
        baseline, candidate, noise_area=0.013, p95_seconds=30.0, expect_cells=1
    )

    assert verdict.passed is False
    assert verdict.reasons[0].startswith("REFUSED:")


def test_regressions_only_never_carries_an_invalid_or_crash_row() -> None:
    """Goal 1 requires INVALID 0 and CRASH 0 outright, baseline or not.

    The restore-mismatch hazard is a way this phase could manufacture CRASH
    rows, so the mode that relaxes refusals must not relax these.
    """
    for status in ("INVALID", "CRASH"):
        baseline = [_row("freeform", "graphene", 0, "graphene/a", status, 0.0, 4.0)]
        candidate = [_row("freeform", "graphene", 0, "graphene/a", status, 0.0, 4.0)]

        verdict = audit_compare.compare(
            baseline,
            candidate,
            noise_area=0.013,
            p95_seconds=31.0,
            expect_cells=1,
            regressions_only=True,
        )

        assert verdict.passed is False, status
        assert any(reason.startswith(f"{status}:") for reason in verdict.reasons)
```

`_row(strategy, url_id, spec_index, spec_label, status, area, seconds)` returns the dict shape `audit_compare` reads — `{"strategy", "url_id", "spec_index", "spec_label", "power", "budget", "status", "area", "seconds", "detail"}` with `detail` set to `""` for CLEAN rows and `"refused"` otherwise. Add it beside the existing helpers in `tests/scripts/test_audit_compare.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/scripts/test_audit_compare.py -v`
Expected: FAIL with `TypeError: compare() got an unexpected keyword argument 'regressions_only'`.

- [ ] **Step 3: Add the regression mode**

Add `notes: tuple[str, ...] = field(default_factory=tuple)` to `Verdict`, then replace `compare`'s non-CLEAN branch:

```python
def compare(
    baseline: Iterable[Mapping[str, object]],
    candidate: Iterable[Mapping[str, object]],
    *,
    noise_area: float,
    p95_seconds: float,
    expect_cells: int | None = None,
    regressions_only: bool = False,
    require_clean: frozenset[str] = frozenset(),
) -> Verdict:
    base_by_key = {_key(row): row for row in baseline}
    candidate_rows = list(candidate)
    candidate_keys = {_key(row) for row in candidate_rows}
    counts: dict[str, int] = {}
    reasons: list[str] = []
    notes: list[str] = []
    log_ratios: list[float] = []
    seconds: list[float] = []
    for row in candidate_rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
        seconds.append(float(str(row["seconds"])))
        label = f"{row['strategy']} {row['url_id']}/{row['spec_label']}: {row['detail']}"
        name = f"{row['strategy']}/{row['url_id']}/{row['spec_label']}"
        base = base_by_key.get(_key(row))
        if status != "CLEAN":
            if name in require_clean:
                reasons.append(f"NOT CLEAN: {label}")
            elif not regressions_only or status in {"INVALID", "CRASH"}:
                # INVALID and CRASH are never "carried over": the gate demands
                # zero of each outright, and a phase that corrupts a round
                # would show up here first.
                reasons.append(f"{status}: {label}")
            elif base is not None and str(base["status"]) == "CLEAN":
                reasons.append(f"REGRESSION: {label}")
            else:
                notes.append(f"CARRIED: {label}")
            continue
        if base is None or str(base["status"]) != "CLEAN":
            continue
        base_area = float(str(base["area"]))
        cand_area = float(str(row["area"]))
        if base_area > 0 and cand_area > 0:
            log_ratios.append(math.log(cand_area / base_area))
```

Leave the remainder of the function unchanged except for `notes=tuple(notes)` in the returned `Verdict`. In `main`, add the flags and print the notes:

```python
    ap.add_argument("--regressions-only", action="store_true")
    ap.add_argument("--require-clean", action="append", default=[])
```

```python
    verdict = compare(
        _read(args.baseline),
        _read(args.candidate),
        noise_area=args.noise_area,
        p95_seconds=args.p95_seconds,
        expect_cells=args.expect_cells or None,
        regressions_only=args.regressions_only,
        require_clean=frozenset(args.require_clean),
    )
```

```python
    for note in verdict.notes:
        print(f"  note {note}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/scripts/test_audit_compare.py -v`
Expected: PASS, including the pre-existing tests unchanged.

- [ ] **Step 5: Re-check every digest**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python setup.py build_ext --inplace
{
  uv run python scripts/route_bench.py --cases "$d/route-cases-universe-matrix-output-products.pkl" --rounds 3 --check
  uv run python scripts/route_bench.py --cases "$d/route-cases-quantum-chip-all-products.pkl" --rounds 3 --check
  uv run python scripts/last_mile_bench.py --cases "$d/cluster-cases-universe-matrix-output-products.pkl" --rounds 3 --check
  uv run python scripts/last_mile_bench.py --cases "$d/cluster-cases-quantum-chip-all-products.pkl" --rounds 3 --check
} | tee "$d/digests-after.txt"
```

Expected: four `MATCH` lines. The two `route_bench` digests must equal the ones in `digests-before.txt`.

- [ ] **Step 6: Run the three-round corpus audit**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
for r in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 --json "$d/candidate-budget30-round$r.jsonl" | tail -5
done
for r in 1 2 3; do
  uv run python scripts/audit_compare.py "$d/baseline-budget30-round1.jsonl" "$d/candidate-budget30-round$r.jsonl" \
    --p95-seconds 31 --expect-cells 72 --regressions-only \
    --require-clean "freeform/quantum-chip/quantum-chip/all-products" \
    --require-clean "freeform/universe-matrix/universe-matrix/output-products"
done
```

Expected: every round prints `clean 67  refused 5  invalid 0  crashed 0  paired …  area ratio …  p95 …s`, five `note CARRIED: …` lines naming the Phase C and Phase D cells, and `PASS`. Any `REGRESSION:`, `NOT CLEAN:`, `MISSING:`, `INVALID:` or `CRASH:` line fails the gate.

`--p95-seconds 31`, not 30: wall p95 is Phase D's problem and the Phase A round files already sit at 30.53 s, 30.67 s and 30.37 s. The threshold is the worst of those rounded up. Do not lower it to 30 to "be strict" — that fails Phase B for an inherited defect — and do not raise it above 31 without a measurement.

The exact `--require-clean` names must match the `spec_label` values in the JSONL. Confirm them once before running the loop:

```bash
uv run python - <<'EOF'
import json
d = "docs/superpowers/evidence/2026-09-02-phase-b-last-mile/"
rows = [json.loads(line) for line in open(d + "baseline-budget30-round1.jsonl")]
for row in rows:
    if row["status"] != "CLEAN":
        print(f'{row["strategy"]}/{row["url_id"]}/{row["spec_label"]}')
EOF
```

- [ ] **Step 7: Collect the `last_mile_*` counters from the profiler**

`scripts/audit.py` rows carry no `stats` object, so the counters come from `scripts/route_profile.py --json` (Task 10 Step 6), one run per target cell:

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
{
  uv run python scripts/route_profile.py universe-matrix --strategy freeform \
    --candidate-policy output-products --budget 30 --workers 8 --json
  uv run python scripts/route_profile.py quantum-chip --strategy freeform \
    --candidate-policy all-products --budget 30 --workers 8 --json
} | tee "$d/last-mile-profile.jsonl"
uv run python - <<'EOF'
import json
d = "docs/superpowers/evidence/2026-09-02-phase-b-last-mile/"
for line in open(d + "last-mile-profile.jsonl"):
    row = json.loads(line)
    stats = row.get("last_mile_stats", {})
    print(row["url_id"], row["verdict"][:40], stats or "NO LAST-MILE STATS")
EOF
```

Expected: two rows whose `last_mile_stats` is non-empty with `last_mile_invocations` greater than zero. **If either row prints `NO LAST-MILE STATS`, the phase's observational claims are unsupported**: write that into `gate.md` verbatim rather than reporting the counters as zero, because zero and unmeasured are different findings and only one of them is evidence.

Record `last_mile_relation_skipped_siblings` against `last_mile_proved` explicitly in `gate.md`: it is the measurement the spec's §5.2 follow-ups are gated on, and a run where the skip count swamps the proof count is the finding that says sibling-free clusters are too rare for the relation no-good to matter on this corpus. Do **not** act on it in this phase.

Add `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/last-mile-profile.jsonl` to the task's created files.

- [ ] **Step 8: Write the gate record**

`docs/superpowers/evidence/2026-09-02-phase-b-last-mile/gate.md` contains, and nothing else:

- the commit hash under test and the baseline commit hash from Task 1;
- the three `audit_compare` output lines verbatim, including their `note CARRIED:` lines;
- the four digest lines from `digests-after.txt`;
- the two `BEST` lines from `cluster-bench.txt` and the `B_MIN_SECONDS` measurement from Task 9 Step 9;
- the two `last_mile_stats` profiler rows from Step 7;
- the line `wall p95 inherited from Phase A, owned by Phase D` beside the measured p95 values;
- one line per gate condition from the Global Constraints stating pass or fail.

No prose beyond that.

- [ ] **Step 9: Full suite, lint, type-check, commit**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy
git add scripts/audit_compare.py tests/scripts/test_audit_compare.py docs/superpowers/evidence/2026-09-02-phase-b-last-mile
git commit -m "bench: record the 30s corpus gate for the phase B last-mile router"
```

`uv run ruff check .` must be clean here and at the end of every task, not only this one.

If any round fails the gate, commit the same evidence under the message
`bench: record a failed 30s corpus gate for the phase B last-mile router`
with `gate.md` naming the failing cells and their `detail` strings, and report.
