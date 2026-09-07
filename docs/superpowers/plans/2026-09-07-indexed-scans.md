# Replace repeated scans and hand-rolled graphs with indexed domain types

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ranked repeated-scan and hand-rolled-graph sites in `src/flab2bp/` and
`scripts/` with indexes and graphs that are built once and queried, each hidden behind a domain
type whose backend (`littletable`, `networkx`, or a plain dict/counter) is chosen per collection
from its mutability and proven by measurement — with byte-identical blueprint output to master.

**Architecture:** A new package `src/flab2bp/indexed/` holds one module per domain type
(`Stages`, `Sorters`, `Nets`, `Cells`, `StripPositions`, `StakedPaths`, `ReferenceGraph`,
`BlockGraph`, `BeltOverlap`, `UnionFind`). Those modules are the **only** places in the tree
allowed to import `littletable`, `networkx`, `polars`, `rustworkx` or `scipy`; a guard test
greps for that and fails on any other import. Every caller receives the domain's own types
(`int` building indices, `PlacedBuilding`, `CellResult`, `_Net`), never a `Table`, a `DataFrame`,
a `nx.DiGraph`, or a query expression. Conversion proceeds file by file in the order that lands
uncontended files before files held by branches in flight, one commit per file, with a
measurement task after each hot-path conversion so a regression is caught at the task rather
than at the gate.

**Tech Stack:** Python 3.14, `uv`, pytest, pytest-timeout, OR-Tools CP-SAT, Cython
(`_sequence_kernel`, `_route_kernel`), numpy, ruff, mypy. New runtime dependencies added by this
plan: `littletable` (pure Python, no transitive deps) and `networkx` (pure Python).

**Spec:** two documents, both binding, cited throughout:

1. `/home/dannyb/.claude/jobs/02fee873/tmp/scan-scout-findings.md` — the scout's catalogue of 49
   sites in 28 files (39 repeated scans, 10 hand-rolled graphs), ranked by nesting depth times
   call frequency, with a mutability column per row, plus the duplicate-adjacency groups, the
   existing indexes, and the not-worth-converting list. Site numbers below (`#1` … `#49`) are
   that file's row numbers.
2. **The user's rulings**, reproduced verbatim in Global Constraints below.

Where this plan's own reading of the code at `master@2e861af0` contradicts the scout, §"Where
this plan disagrees with the scout" says so and the plan follows this reading, not the scout's.

---

## Requests to `buildings-index`

The concurrent `buildings-index` branch owns every scan over a *buildings sequence* and lands
before this plan executes. Its `Buildings` domain type is specified as offering
`machines_for_recipe`, `sorters_into`, `sorters_out_of`, `at_tile`, `graph()`. The scout rows
below are buildings scans and are therefore **not** re-implemented here; each becomes a
"convert to `Buildings.<method>`" task step once that branch merges. Three of them need a method
that interface does not yet name:

1. **`Buildings.splitter_successors(index) -> tuple[int, ...]`**, or an equivalent guarantee on
   `Buildings.graph()`, that stays valid **while `canvas.add()` appends**.
   Needed by: scout #6 — `freeform.py:12822` `_splitter_successors`, rebuilt from scratch inside
   `_leads_back` (`freeform.py:12940`) and `_committed_path_closes_cycle`
   (`freeform.py:12976`) on every call that is not handed a cached copy, which is every
   `_sink_for` call at `freeform.py:13121`, `:13140`, `:13165`, once per net in `_commit_paths`'s
   `laid.items()` loop. The index must be *incrementally maintained*, not memoized: `canvas.add()`
   at `freeform.py:12628` grows `canvas.buildings` inside the same commit pass that queries it,
   so a snapshot goes stale mid-pass. `freeform.py:12496` `into` /
   `refresh_predecessor` (`:12504-12513`) is the model this should copy.

2. **`Buildings.predecessor_of(index) -> int | None`** — the reverse `output_obj → index` link.
   Needed by: scout #12 — `layout/hierarchy/compose.py:476`, which rebuilds
   `prev = {b.output_obj: i for i, b in enumerate(buildings) if b.output_obj is not None}` on
   every `_lane` call, and `_lane` is reached twice per `LaneFlow` from `_port`
   (`compose.py:516`) inside `_pack_at`'s per-flow loop (`compose.py:722-723`).

3. **`Buildings.belt_run(index, *, forward: bool) -> frozenset[int]`** — the belt run through an
   index, crossing splitters and pilers.
   Needed by: scout #13 — `layout/hierarchy/contracts.py:67-103` `_belt_run`, whose inner
   `for j, other in enumerate(buildings)` at `contracts.py:86-88` makes construction **O(B²)**,
   rebuilt per call from `_machines_on_lane` (`contracts.py:115`), `_apportion`
   (`contracts.py:158`) and `boundary_lanes` (`contracts.py:228`, `:237`).

4. **A statement of whether `Buildings` wraps `Placement.buildings`** (validate's source via
   `Context.placement`) as well as `_Canvas.buildings`. If it does, this plan's `Sorters`
   (Task 4) delegates its `input_obj`/`output_obj` link keys to `Buildings.sorters_into` /
   `Buildings.sorters_out_of` and keeps only the *item* index, which is a validate-domain fact
   (`ctx.cache.sorter_items`) that `Buildings` cannot know. See Ruling I-7.

If any of these lands under a different name, the executing agent renames at the call site; the
plan's own modules do not re-implement them.

---

## Global Constraints

Copy these into every task dispatch. They bind every task.

### The user's rulings (verbatim, binding)

1. "Places where we enumerate larger lists and should be using an index or are hacking up graph
   abstractions out of them in O(N) or O(N^2) repeatedly" get fixed with an index or a graph
   library.
2. "Use littletable and indexes and a proper abstraction." Then: "Another option for both other
   than littletable is polars. But that only makes sense if the data (here and elsewhere) is
   immutable." So choose per collection from its mutability column: a frozen collection queried
   column-style many times may be a polars frame built once; a collection that grows during a
   phase or is rewritten between scans, or that needs incremental appends and stable positional
   indices, is a littletable indexed table; a plain dict keyed once at construction is also a
   valid index when the query is a single key and the collection is small; never two backends
   for one collection. Say which and why per collection, and require the profile to show the
   build cost is below the scans it replaces at the measured call frequency (polars has per-call
   overhead that loses on tiny collections queried once).
3. "Whether littletable or polars is used, it should be hidden behind an overall abstraction for
   the type of thing." One domain type per kind of collection (for example `Strips`, `Nets`,
   `Sorters`, `Stages`, `ReferenceGraph`), with methods named for what callers ask; no caller
   imports the library, receives a Table or DataFrame, or writes a query expression; the backend
   lives in one module per type; a test greps the tree outside those modules for
   `littletable`/`polars`/`networkx` imports and fails on any. Public methods are typed with the
   domain's own types.
4. Graphs: the 10 hand-rolled sites (adjacency rebuilt per call, inline BFS/DFS reachability,
   closure recomputed inside loops, successor walks by scanning) move to a graph library behind a
   domain graph abstraction. Default networkx for correctness and breadth of algorithms; it is
   pure Python, so for a site on a hot path (the sequence-pair kernel, the router's per-net loop)
   the plan may pick scipy.sparse.csgraph or rustworkx behind the same abstraction, chosen by a
   measurement task, never by assertion. One earlier session already chose scipy over networkx
   for bipartite matching for exactly this reason; check whether that code still exists and reuse
   its pattern. Duplicate-adjacency groups in the scout's file become ONE graph built once per
   source and shared.
5. Byte-identical outputs to master: deterministic controls on 12 corpus cells at
   `DETERMINISTIC_WORKERS` compared with master's exact blueprint strings; the full 72-cell
   corpus at `--budget 30` paired against master with `scripts/audit_compare.py`
   (`scripts/audit.py --json <path>`; NOT CLEAN on any refusal, compare counts and named cells);
   full pytest suite exit code (no summary line here; 120 s pytest-timeout; known reds
   `test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
   `test_all_products_sequence_pair_honours_the_exact_layout_deadline`); ruff,
   ruff format --check, mypy (narrowest `[[tool.mypy.overrides]]` per untyped library, no blanket
   ignores). Sequence-pair changes additionally need the `route_bench` digest MATCH line and a
   sequence-pair multi-run audit compare, because the kernel's tie-breaking must not move.
6. Measurement: `cProfile` before/after on three corpus cells spanning small / mid / largest, per
   converted function and total wall, plus wall ratios on the eight largest cells, CPU pressure
   recorded the vmstat way beside every timing. The report must separate sites that moved the
   numbers from hygiene conversions. Evidence under
   `docs/superpowers/evidence/2026-09-07-indexed-scans/`, any size.

### Process constraints

- **Branch/worktree.** All work happens on branch `indexed-scans` in the worktree
  `.claude/worktrees/indexed-scans`, cut from `master@2e861af0`. Never merge, never push, never
  delete the branch.
- **Environment check before any test result counts.** Run `uv sync` in the worktree, then
  `uv run python -c "import flab2bp; print(flab2bp.__file__)"` and confirm the printed path is
  inside `.claude/worktrees/indexed-scans`. A worktree without `uv sync` runs the tests against
  MASTER through the main checkout's venv, and the result is not evidence.
- **Never a git command that opens an editor.** `export GIT_EDITOR=true`; use `-m` / `-F` /
  `--no-edit` on every commit, merge and rebase.
- **Never `ps | grep`.** `pgrep` excludes its own PID; use an interpreter-anchored pattern, e.g.
  `pgrep -f 'python.*audit\.py'`.
- **Never `uptime` / load average for CPU pressure.** This box has 128 cores and its load is disk
  I/O wait. Measure only as `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` (the
  five-second mean of runnable processes). Under 64 is not busy. Record it beside every timing;
  never wait for it to drop.
- **Serena is for READING only.** The Serena MCP server is shared across worktrees and its last
  `activate_project` wins, so a Serena write from here can land in another agent's worktree. Use
  `Read`/`Edit`/`Write` and the LSP tools for every modification.
- **ONE corpus build at a time.** Other agents build on this box. Never run two `audit.py` runs
  concurrently and never raise `--jobs` above what the task text says.
- **`pytest` prints no summary line in this environment.** Judge every run by its **exit code**,
  and remember the 120 s `pytest-timeout` backstop hard-kills a hung run.
- **Evidence size is never a concern.** Anything under gigabytes is fine. Never shrink, prune or
  omit committed evidence.
- **One commit per file converted.** A task that converts `foo.py` commits exactly `foo.py`, its
  test file, and nothing else. Domain-type tasks commit their own module plus its test.
- **File-landing order is fixed by contention, not by rank.** Branches in flight:
  `selfloop` (validate.py, markers.py, base.py, pipeline.py), `coater-placed` (freeform.py,
  coater_mode.py), `hierarchical-v4` (freeform.py, hierarchy/*, sequence_solver.py),
  `buildings-index` (a new module plus call sites across layout/, dsp/, bench/). Uncontended
  files (dsp/, global_router.py, bench/, web/, scripts/, lab/, last_mile.py, route_feedback.py)
  land first; `sequence_solver.py`, `sequence_pair.py`, `freeform.py`, `validate.py`,
  `pipeline.py` and `hierarchy/*` land last.
- **Out of scope.** The web TypeScript under `web/`. Everything on the scout's "Not worth
  converting" list, unless a conversion falls out of a domain type built for a ranked site
  anyway — where that happens the task says so explicitly on the row.

### Verification commands (the gate)

Run from the worktree root. `$W` is `.claude/worktrees/indexed-scans`.

```bash
export GIT_EDITOR=true
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/indexed-scans
uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"   # must print a path inside $W

uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts
uv run pytest ; echo "pytest exit=$?"                        # judge by exit code only

# full corpus, paired against master
uv run python scripts/audit.py --budget 30 --strategy both --json /tmp/indexed-scans.jsonl
uv run python scripts/audit_compare.py /tmp/master-baseline.jsonl /tmp/indexed-scans.jsonl

# sequence-pair tie-breaking (only for tasks touching sequence_pair.py / sequence_solver.py)
uv run python scripts/route_bench.py --cases <committed capture> --check   # expect "MATCH"
```

---

## Where this plan disagrees with the scout

The scout worked from grep and caller tracing, not profiles. Every row below was re-read at
`master@2e861af0`. Seven readings differ; the plan follows this column, not the scout's.

| Scout row | Scout's claim | This plan's reading (verified) | Consequence |
|---|---|---|---|
| **#1** | "a running int counter incremented at the same site as `.append()`" | **Incomplete and would change behaviour.** `_counts_as_scheduled_stage` (`sequence_solver.py:865-871`) is false when `global_skip_reason` is `"shared-pack"`, `"topology-beam"` or `"projection-feedback"`. `sequence_solver.py:2106-2107` rewrites `self._stage_stats[-1]` with `replace(observation, global_skip_reason="projection-feedback")` **after** it was appended, flipping an already-counted stage to uncounted. An append-only counter would over-count and change `stage_limit` comparisons at `:1280` and `:2036`. | The `Stages` type must own **both** mutations (`append` and `replace_last`) and recompute the predicate on each. Task 8, with an explicit staleness test. |
| **#3** | `decode_sequence_pair`'s O(N²) adjacency runs "on every candidate move inside `anneal_stage`'s per-move loop" | **False on the production path.** `anneal_stage` scores through `kernel.score_state` (`sequence_pair.py:1640`, `:1667`); `build_sequence_kernel` (`sequence_kernel.py:273-280`) returns `CompiledSequenceKernel` whenever `compiled_backend_available()` and the inputs are safe, and `layout/_sequence_kernel.cpython-314-*.so` is present in the tree. The Python `decode_sequence_pair` is reached only from `decode_state` (`sequence_pair.py:907`) and `encode_placement` (`:1048`). | **Site #3 is dropped from the conversion set** and demoted to "not worth converting". Converting the authoritative reference decoder to incremental maintenance buys nothing on the production path and puts the kernel's tie-breaking at risk for no measured gain. Recorded as Ruling I-1. |
| **#4** | position index instead of two `.index()` scans in `apply_move` SWAP_BOTH | **Confirmed and it IS hot** — `apply_move` at `sequence_pair.py:1656` is Python and runs per candidate move regardless of which kernel scores. `negative.index(...)` at `:1479-1480`. | Site #4 is the *highest-value* sequence-pair site, above #3. Task 15. |
| **#5** | "a running 'fully shared' boolean maintained by `occupy()`" | **Wrong.** `present_cost(index, compatible)` (`global_router.py:79-84`) computes `shares` against the **caller's** `compatible` frozenset, which differs per net; `occupy` cannot know a future querier's set. A cached boolean would be answering a different question. | The real win is cheaper membership: store each unit's owners as a `frozenset[NetId]` so the test is `owners <= compatible` (one C-level subset test) instead of `all(owner in compatible for owner in unit)` (a Python generator per unit). Task 11, gated on measurement. |
| **#9** | build the item-independent belt topology once and share it | **Half right.** `validate.py:5299-5313` (belts) is genuinely item-independent; `:5315-5348` (sorters) and `:5350-5372` (docks) are item-filtered. But `_add_flow_link` writes mutable residual capacities into `graph: list[list[_FlowEdge]]` that `_max_flow` consumes, so a shared skeleton **must be deep-copied per item**. The saving is the scan and the legality tests, not the allocation. | Convert to "precompute an item-independent edge list once, rebuild the flow graph from that list per item". Medium confidence, explicitly gated on the measurement task. Task 21. |
| **#15** | "`functools.cached_property` on `by_item`/`by_recipe`" | **Would raise at runtime.** `FlowSelection` is `@dataclass(frozen=True, slots=True)` (`lab/flow.py:442-443`); `functools.cached_property` needs a `__dict__` and raises `TypeError: No '__dict__' attribute on 'FlowSelection'`. | Use an `init=False` field populated in `__post_init__` through `object.__setattr__`, which works with `frozen=True, slots=True`. Task 13. |
| **Ruling 4** | "One earlier session already chose scipy over networkx for bipartite matching … check whether that code still exists and reuse its pattern." | **That code does not exist.** `grep -rn -i 'scipy'` over `src/`, `tests/`, `scripts/` returns nothing, and `uv pip list` shows no scipy in the environment. The bipartite matching from `bb6ed841` ("Freeform: access cells are a matching") is implemented in `_reserve_port_access` (`freeform.py:12041`) as an **OR-Tools CP-SAT model** (`solve_model` at `freeform.py:11911`), not scipy. | The reusable precedent is "state the combinatorial problem to a solver already in the dependency set", not "reach for scipy". This plan therefore adds **no** scipy dependency; the compiled-library escape hatch in Ruling 4 is exercised, if at all, only by the measurement tasks (Tasks 16, 20, 22), and only against `rustworkx`. Recorded as Ruling I-2. |

Two further readings the scout did not make, both load-bearing:

- **`_stage_stats` is scanned a third time** at `sequence_solver.py:1228`
  (`for stage in reversed(self._stage_stats)`), inside the same driver, and again at `:1618`,
  `:1625`, `:1647`. `Stages` therefore needs a reverse-iteration accessor, not only a count.
- **`_sorter_item` is already memoized.** `ctx.cache.sorter_items` (`validate.py:5860`
  `_sorter_items`) resolves the item per sorter once. Site #8's per-BFS-step cost is the
  `ctx.of_kind(Kind.SORTER)` scan alone (`validate.py:4620-4628`), not the item resolution.

---

## Per-collection backend table (Ruling 2)

Every row states the collection, its mutability with the evidence, the chosen backend, and why —
including why the two backends it is not.

| Domain type | Collection (source) | Mutability (evidence) | Backend | Why this and not the others |
|---|---|---|---|---|
| `Stages` | `SequenceSolver._stage_stats` (`sequence_solver.py:1119`) | **append-during-phase and rewritten** — `.append()` at `:3119`, `self._stage_stats[-1] = replace(...)` at `:2106-2107` | plain `list` + a maintained `int` counter | The only repeated query is a **count under a predicate**, plus ordered iteration. littletable would pay a row insert on the hottest write in the solver to answer a question a single `int` answers in O(1); polars is excluded outright by the mutability. Ruling 2's "a plain dict keyed once … is also a valid index when the query is a single key and the collection is small" extends to a single running aggregate. |
| `Sorters` | validate `Context`'s `of_kind(Kind.SORTER)` plus `ctx.cache.sorter_items` (`validate.py:392-404`, `:5860`) | **frozen** — `of_kind` is a memoized tuple on a frozen `Context`; the docstring at `validate.py:234-257` states nothing here changes a verdict | **littletable** | Three distinct query keys (`input_obj`, `output_obj`, resolved `item`) and at least four consumers (`_belt_reaches_any` `:4620`, `_unsprayed_belts` `:4977`, `_sprayed_cargo_reaches_machines` `:5048`, `_lane_balance` `:5315`) — exactly the multi-key, multi-consumer shape littletable exists for, and the shape a hand-rolled dict has already been written four times for. **Not polars**: every consumer needs the `PlacedBuilding` object and its index, so a frame would force a per-query materialisation back to objects — the per-call overhead Ruling 2 warns about — and thousands of rows is not enough to pay it back. **Not a plain dict**: three keys means three dicts kept in step by hand, which is the duplication being removed. |
| `Nets` | freeform's `all_prepared_nets` (`freeform.py:17317-17321`), consolidating `net_by_id` (`:9425`) and `role_members` (`:9372`) | **frozen for the query phase** — built by `_prepare_routing_problem` before the pack attempt that scans it; not appended during `_route_all` | **littletable** | Queried on `(item, kind, cell)` composite and on `id` and on role — three key shapes, three separately hand-built dicts today. **Not polars**: `_Net` carries nested tuples (`src`/`dst` endpoints) that do not flatten into columns without loss, and the collection is hundreds of rows. **Not a plain dict**: the composite-key query at `freeform.py:12111-12129` and the id query at `:9425` are different keys over one collection, and Ruling 2 forbids two backends for one collection — one table with two indexes is the single backend. |
| `Cells` | `bench` `Sequence[CellResult]` (`bench/scoring.py:70`, `bench/report.py:44`, `:145`, `bench/regression.py:65`) | **frozen** — built once from a completed run, four independent readers | **littletable** | Four byte-identical-in-intent re-implementations of "best `CellResult` per url, smallest area" over one frozen collection; one table with an index on `url_id` and a rank accessor collapses all four. **Not polars**: ≤72 rows read once per report — Ruling 2's own cost test rules it out, and the measurement task in Task 12 records the number. **Not a plain dict**: the four readers use *different* rank keys (`bench/regression.py:62` ranks `(0 if valid else 1, area)`), so the shared thing is the index, not the reduction. |
| `StripPositions` | `SequencePair.positive` / `.negative` tuples (`sequence_pair.py:1465-1466`) | **frozen** — tuple fields of a frozen `SequencePair`; every move builds a wholly new pair at `:1504-1510` | **plain dict** (`{strip: position}`) | The query is a single key on a collection of tens, in the hottest Python loop in the solver. Ruling 2 names this case exactly. littletable's per-row insert would cost more than the two `.index()` scans it replaces at N≈30; polars is not in the conversation at this size. `decode_sequence_pair` already builds this exact index at `sequence_pair.py:849-851` — the type is a promotion of an existing local pattern, not a new idea. |
| `StakedPaths` | freeform `_repair`'s `paths` (`freeform.py:9931`, `:9962`) plus `path_tap` (`:9942`) | **rewritten during the phase** — `paths[index] = path` in `_stake`, `paths.pop(index)` in `_unstake`, both inside the very round `_leaning` scans | **plain dict multimap**, maintained by `_stake`/`_unstake` | Ruling 2 sends "grows during a phase" to littletable, and this row is the one place the plan overrides that default with a measurement: the write path (`_stake`/`_unstake`) runs far more often than the read path (`_leaning`, once per stranded net), so a table insert per stake would move cost onto the hotter side. Task 20 measures both and the plan is **committed to switching this row to littletable if the measurement does not show the dict winning** — see Ruling I-4. |
| `ReferenceGraph` | `dsp/provenance.Graph` (`dsp/provenance.py:136-177`) | **frozen** — `build_graph()` is `@lru_cache(maxsize=1)`; `edges`/`owner`/`kind`/`calls` are `Mapping` fields never mutated | **networkx** `DiGraph` | Ruling 4's default. The queries are reachability closures (`closure()` at `:158-174`, called inside the entry loop at `:527`) and a reverse-reach inversion (`:507`) — `nx.descendants` and one precomputed inversion answer both. Cold path (provenance/lint, not per build), so the pure-Python cost is irrelevant and correctness/breadth wins. |
| `BlockGraph` | `hierarchy/partition.py` `edges` built per `derive_cuts` call (`partition.py:200-226`) | **rewritten per round by design** — the block graph genuinely changes each round of `HierarchicalLayout.lay_out` (`hierarchy/strategy.py:607`) | **networkx** `DiGraph`, rebuilt per round | Ruling 4's default, and the only site where a per-round rebuild is *correct* rather than wasteful. The defect is the internals: `ready = sorted(set(ready) - seen)` re-sorts on every dequeue, O(n² log n). `nx.lexicographical_topological_sort` gives the same deterministic order in O(n log n). Byte-identical order is proven by an equality test against the inline walk before the inline walk is deleted. |
| `BeltOverlap` | `dsp/colliders.py` `grid`/`boxes` from `previews` (`dsp/colliders.py:1742`) | `previews` **frozen** (`Preview` is `@dataclass(frozen=True)`, a tuple, unchanged between the two calls); `grid`/`boxes` **rewritten** fresh per call and discarded | **plain dict** spatial hash, memoized on `id(previews)` inside the module | Single-key spatial lookup, built twice per validation pass by `belt_collisions` (`:1798-1800`) and `stable_belt_collisions` (`:1901-1904`) from the same source. Ruling 2's plain-dict clause; littletable adds nothing to a bucket grid and polars cannot express one. |
| `UnionFind` | three independent closures in `freeform.py` (`:16008-16115`, `:16115-16236`, `:8959-9020`) | local, rebuilt per call | **plain arrays** (path-compressed, union by rank) | Not a scan defect at all — a code-duplication defect the scout rated `low (perf) / medium (duplication)`. `networkx.utils.UnionFind` exists but is slower than a 25-line array implementation and would drag a library import into a hot file for no query benefit. Included because Ruling 3's "one domain type per kind of collection" applies, and because it removes three re-implementations. |

**polars is adopted nowhere, and the reason is Ruling 2's own cost test.** Every frozen
collection in the ranked set is either small (≤ a few hundred rows: `flow.rows`, `bench` cells,
`planet.bands()`, `Nets`) or read back as objects rather than columns (validate's sorters and
belts, whose consumers need `PlacedBuilding` attributes and building indices). In both shapes the
per-call materialisation overhead exceeds the scan it would replace at the measured call
frequency. Tasks 12 and 21 record the numbers that support this; if either shows a frozen
collection large enough and column-shaped enough to pay for a frame, the follow-up is a separate
plan, not an unmeasured switch here. See Ruling I-3.

### Graph-site backends (Ruling 4)

Ten hand-rolled graph sites. Six convert, three defer to `buildings-index`, one is dropped.

| Site | What it is | Backend | Decided by |
|---|---|---|---|
| #10 `provenance.py:505-509` | reverse-reach inversion recomputed inside the rules loop | **networkx**, via `ReferenceGraph` | assertion is fine: cold path, Ruling 4 default |
| #11 `provenance.py:521-529` | `g.closure(g.nodes_in(m))` recomputed inside the entry loop | **networkx**, via `ReferenceGraph` | as above |
| #35 `partition.py:200-226` | hand-rolled Kahn with a re-sort per dequeue | **networkx**, via `BlockGraph` | **measurement task (Task 22)** — n is the block count; if networkx's per-round build loses, the fallback inside the same abstraction is `heapq`-backed Kahn, and the task records which won |
| #23 `sequence_pair.py:1057-1088` | hand-rolled Kahn, `ready.pop(0)` + full re-sort | **`heapq` behind `StripPrecedence`, pending measurement** | **measurement task (Task 16)** — this is `encode_placement`, on the sequence-pair path whose tie-breaking must not move. The task benchmarks `heapq` vs `networkx` vs `rustworkx` at the real strip counts and takes the winner; Ruling 4 forbids choosing by assertion, and at N≈tens the networkx build cost plausibly exceeds the whole pass |
| #21 `validate.py:4182/4358/4396` | one `while changed:` fixpoint over `ctx.junction_out`, computed three times | **plain memo on `ctx.cache`**, not a library | the fixpoint is already a correct O(V+E) closure; the defect is that it runs three times. Ruling 4's "duplicate-adjacency groups become ONE graph built once per source and shared" is satisfied by caching, and importing a graph library to re-express a correct closure would add a dependency to `validate.py` for no algorithmic change |
| #8 `validate.py:4609-4629` | BFS with an O(sorters) scan at every step | **`Sorters` index; the BFS stays hand-rolled** | the edge set is **parameterised by `item`** (`:4627`), so a shared graph would need one graph per item or a networkx filtered view (slow). The win is the index at the step, not the walk. Explicit disagreement with a blanket "move to a graph library" |
| #9 `validate.py:5299-5372` | flow graph rebuilt from scratch per item | **plain edge list + per-item rebuild**, not a library | `_max_flow` (`validate.py:5198-5235`) is a correct hand-rolled Edmonds-Karp the scout's own "not worth converting" list defends, and networkx's max-flow would change the residual exploration order and therefore the verdict on ties. Only the *inputs* convert |
| #3 `sequence_pair.py:853-860` | O(N²) precedence adjacency | **dropped** | see the disagreement table: not on the production path (`CompiledSequenceKernel`), and it is the authoritative reference decoder |
| #6, #12, #13 | splitter successors, `_lane` reverse links, `_belt_run` | **deferred to `buildings-index`** | brief's scope boundary; see "Requests to `buildings-index`" |

### Rulings this plan makes for itself

- **Ruling I-1.** Scout site #3 (`decode_sequence_pair`'s O(N²) adjacency) is **not converted**.
  The compiled kernel owns the per-move path; the Python decoder is the reference. Recorded in
  the scout's terms so a later reader does not re-open it.
- **Ruling I-2.** No `scipy` dependency is added. The precedent Ruling 4 points at is CP-SAT, not
  scipy (`freeform.py:11911`). The only compiled graph library any measurement task may adopt is
  `rustworkx`, and only if it wins a recorded benchmark.
- **Ruling I-3.** `polars` is adopted nowhere in this plan, on Ruling 2's own cost test. Revisiting
  it needs a separate plan and a measurement, not an edit here.
- **Ruling I-4.** `StakedPaths` ships with a dict backend but the decision is *provisional*: Task
  20's measurement must show the dict's total (writes + reads) beating a littletable table on the
  same fixture. If it does not, the executing agent switches the backend inside
  `indexed/staked_paths.py` — no caller changes, which is the point of the abstraction.
- **Ruling I-5.** Any conversion whose measurement task shows **no** improvement outside noise is
  still kept **only if** it removes a duplicated re-implementation (a hygiene conversion). A
  conversion that is neither faster nor de-duplicating is **reverted** in its own task, and the
  final report names it. This is what makes Ruling 6's "separate sites that moved the numbers from
  hygiene conversions" a decision rather than a label.
- **Ruling I-6.** Byte-identity beats speed everywhere. If a conversion is faster and the paired
  audit compare names a differing cell, the conversion is reverted, not defended.
- **Ruling I-7.** `Sorters` indexes validate's `Context` sorters **together with their resolved
  item** (`ctx.cache.sorter_items`), which is a validate-domain fact `Buildings` cannot supply. If
  `buildings-index` lands `Buildings` over `Placement.buildings`, `Sorters` delegates its
  `input_obj`/`output_obj` accessors to it and keeps only the item index — one backend per
  collection, composed, not duplicated.

---

## File structure

**Created — the only modules allowed to import a table or graph library:**

| File | Responsibility |
|---|---|
| `src/flab2bp/indexed/__init__.py` | Re-exports every domain type. Imports no library itself. |
| `src/flab2bp/indexed/_record.py` | `IndexRecord` base — a **non-slots** dataclass wrapper, because littletable sets attributes on inserted rows and every payload in this codebase (`PlacedBuilding`, `CellResult`, `_Net`) is `slots=True`. |
| `src/flab2bp/indexed/stages.py` | `Stages` — solver stage ledger, list + counter. |
| `src/flab2bp/indexed/sorters.py` | `Sorters` — littletable, keys `input_obj` / `output_obj` / `item`. |
| `src/flab2bp/indexed/nets.py` | `Nets` — littletable, keys `net_id` / `(item, kind, cell)` / `role`. |
| `src/flab2bp/indexed/cells.py` | `Cells` — littletable over `CellResult`, key `url_id`, rank-aware accessors. |
| `src/flab2bp/indexed/strip_positions.py` | `StripPositions` — `{strip: position}` over one permutation. |
| `src/flab2bp/indexed/staked_paths.py` | `StakedPaths` — cell→nets multimap maintained by stake/unstake. |
| `src/flab2bp/indexed/reference_graph.py` | `ReferenceGraph` — networkx over `dsp.provenance.Graph`. |
| `src/flab2bp/indexed/block_graph.py` | `BlockGraph` — networkx over hierarchy block edges. |
| `src/flab2bp/indexed/belt_overlap.py` | `BeltOverlap` — bucket grid over `previews`, memoized per source. |
| `src/flab2bp/indexed/union_find.py` | `UnionFind` — path-compressed, union by rank. |

**Modified (one commit each, in this order):**

`dsp/provenance.py` → `dsp/colliders.py` → `dsp/codec.py` + `dsp/splitter_ports.py` +
`dsp/planet.py` → `layout/global_router.py` → `lab/flow.py` + `lab/data.py` + `lab/techs.py` →
`bench/scoring.py` + `bench/report.py` + `bench/regression.py` + `bench/ab.py` +
`bench/promotion.py` + `bench/runner.py` → `web/trace.py` → `scripts/*` →
`layout/last_mile.py` → `layout/route_feedback.py` → `layout/hierarchy/partition.py` +
`layout/hierarchy/pressure.py` → `pipeline.py` → `layout/sequence_pair.py` →
`layout/sequence_solver.py` → `layout/freeform.py` → `layout/validate.py`.

**Tests created:** one `tests/indexed/test_<type>.py` per domain type, plus
`tests/indexed/test_backend_containment.py`, plus one equality test per conversion, added to the
existing test file for the module being converted where one exists.

---

## Task 1: Dependencies, the `indexed` package, and the backend-containment guard

**Files:**
- Modify: `pyproject.toml`
- Create: `src/flab2bp/indexed/__init__.py`
- Create: `src/flab2bp/indexed/_record.py`
- Test: `tests/indexed/test_backend_containment.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the package `flab2bp.indexed`; `IndexRecord` (a base class for littletable rows);
  the guard test that every later task must keep green.

- [ ] **Step 1: Write the failing guard test**

Create `tests/indexed/test_backend_containment.py`:

```python
"""The table and graph backends live in `flab2bp.indexed` and nowhere else.

Ruling 3: "no caller imports the library, receives a Table or DataFrame, or
writes a query expression; the backend lives in one module per type; a test
greps the tree outside those modules for littletable/polars/networkx imports and
fails on any."
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED = _ROOT / "src" / "flab2bp" / "indexed"
_SEARCHED = (_ROOT / "src", _ROOT / "scripts", _ROOT / "tests")
_BANNED = re.compile(
    r"^\s*(?:import|from)\s+(littletable|polars|networkx|rustworkx|scipy)\b",
    re.MULTILINE,
)


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in _SEARCHED:
        out.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return out


def test_no_backend_import_outside_the_indexed_package() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if _ALLOWED in path.parents or path == _ALLOWED:
            continue
        if path.name == "test_backend_containment.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in _BANNED.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(_ROOT)}:{line}: {match.group(1)}")
    assert not offenders, "backend imports outside flab2bp.indexed:\n" + "\n".join(offenders)


def test_the_indexed_package_exists_and_exports_nothing_library_shaped() -> None:
    from flab2bp import indexed

    for name in indexed.__all__:
        exported = getattr(indexed, name)
        module = getattr(exported, "__module__", "")
        assert module.startswith("flab2bp.indexed"), f"{name} leaks {module}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/indexed/test_backend_containment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'flab2bp.indexed'`.

- [ ] **Step 3: Add the dependencies and the mypy overrides**

In `pyproject.toml`, extend `dependencies` (keep the existing `ortools` comment block intact):

```toml
dependencies = [
    # ortools provides BOTH the CP-SAT solver (layout) and, via its SCIP/HiGHS
    # backends, the MILP solver (rates).
    #
    # Do NOT add `highspy`. ortools bundles its own HiGHS inside libortools, and
    # the two cannot share a process: import highspy first and ortools resolves
    # HiGHS symbols into the incompatible library (`ImportError: Symbol not
    # found: setLocalOptionValue`); import it second and it segfaults mid-solve,
    # which showed up as the whole suite exiting 139.
    "ortools>=9.15.6755",
    "httpx>=0.27",
    "pydantic>=2.13.4",
    "sympy>=1.14.0",
    "nodriver==0.47.0",
    # Indexed domain types (`flab2bp.indexed`). Both are PURE PYTHON with no
    # transitive dependencies, so neither can conflict with the ortools/HiGHS
    # symbol problem above. They are importable ONLY from `flab2bp.indexed`;
    # `tests/indexed/test_backend_containment.py` fails on any other import.
    "littletable>=3.0",
    "networkx>=3.4",
]
```

Append to `pyproject.toml`, after the existing mypy configuration (narrowest possible scope, per
Ruling 5 — no blanket ignore):

```toml
[[tool.mypy.overrides]]
module = ["littletable"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["networkx", "networkx.*"]
ignore_missing_imports = true
```

- [ ] **Step 4: Create the package and the record base**

`src/flab2bp/indexed/_record.py`:

```python
"""The row wrapper every littletable-backed domain type inserts.

littletable assigns attributes to the rows it holds (it stamps an id on inserted
objects and rebinds fields on `Table.insert`), and every payload this codebase
would otherwise insert -- `PlacedBuilding`, `CellResult`, `_Net` -- is declared
`@dataclass(frozen=True, slots=True)`. A slotted frozen object cannot take a new
attribute, so inserting one raises rather than indexing it.

So the tables hold a wrapper: an ORDINARY dataclass (no `slots`, not frozen)
carrying the key fields flat, plus `payload`, the caller's own object handed
back unchanged. Callers never see this type; it is an implementation detail of
`flab2bp.indexed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IndexRecord:
    """Base for a littletable row: flat key fields plus an untouched payload."""

    payload: Any
```

`src/flab2bp/indexed/__init__.py`:

```python
"""Indexed domain types: one module per kind of collection.

This package is the ONLY place in the tree allowed to import `littletable`,
`networkx`, `polars`, `rustworkx` or `scipy`. Callers import a domain type from
here, call methods named for what they are asking, and receive the domain's own
types back -- never a `Table`, a `DataFrame`, a graph object, or a query
expression. See `docs/superpowers/plans/2026-09-07-indexed-scans.md` for the
per-collection backend table and why each backend was chosen.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
```

- [ ] **Step 5: Sync and run the guard**

```bash
uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"
uv run pytest tests/indexed/test_backend_containment.py -v
```
Expected: the printed path is inside `.claude/worktrees/indexed-scans`, and both tests PASS.

- [ ] **Step 6: Confirm the new dependencies did not disturb the solver**

Run: `uv run pytest tests/ -k "sequence or freeform" ; echo "exit=$?"`
Expected: exit 1 with only the two known reds
(`test_two_stage_alignment_retains_cp_sat_direct_opportunity`,
`test_all_products_sequence_pair_honours_the_exact_layout_deadline`), or exit 0 if neither is
selected. Any *other* failure means the dependency addition broke something — stop and report.

- [ ] **Step 7: Commit**

```bash
export GIT_EDITOR=true
git add pyproject.toml uv.lock src/flab2bp/indexed tests/indexed
git commit -m "feat(indexed): add the indexed package and its backend-containment guard"
```

---

## Task 2: `ReferenceGraph` — networkx behind the provenance graph

**Files:**
- Create: `src/flab2bp/indexed/reference_graph.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_reference_graph.py`

**Interfaces:**
- Consumes: `flab2bp.dsp.provenance.Graph` (fields `edges: Mapping[str, frozenset[str]]`,
  `owner: Mapping[str, str]`, `kind: Mapping[str, str]`, `calls: Mapping[str, frozenset[str]]`;
  methods `closure(roots, *, block=())`, `nodes_in(module)`).
- Produces:
  - `ReferenceGraph.of(graph: Graph) -> ReferenceGraph`
  - `ReferenceGraph.reachable_from(roots: Iterable[str], *, block: Iterable[str] = ()) -> frozenset[str]`
  - `ReferenceGraph.nodes_in(module: str) -> frozenset[str]`
  - `ReferenceGraph.module_reach(modules: Iterable[str]) -> dict[str, frozenset[str]]`
  - `ReferenceGraph.import_time_captures() -> dict[str, frozenset[str]]`
  - `ReferenceGraph.holders_of(node: str) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_reference_graph.py`:

```python
"""`ReferenceGraph` answers exactly what the inline walk answered.

The graph it replaces is `dsp.provenance.Graph.closure`, a hand-rolled stack
DFS. Equality against that walk on the REAL graph -- not a toy -- is the whole
proof, because the thing being protected is a lint verdict.
"""

from __future__ import annotations

import types

from flab2bp.dsp import provenance
from flab2bp.indexed import ReferenceGraph


def _toy() -> provenance.Graph:
    return provenance.Graph(
        edges=types.MappingProxyType(
            {
                "m.a": frozenset({"m.b"}),
                "m.b": frozenset({"n.c"}),
                "n.c": frozenset(),
                "n.d": frozenset({"m.a"}),
            }
        ),
        owner=types.MappingProxyType({"m.a": "m", "m.b": "m", "n.c": "n", "n.d": "n"}),
        kind=types.MappingProxyType(
            {"m.a": "const", "m.b": "func", "n.c": "default", "n.d": "func"}
        ),
        calls=types.MappingProxyType({"m.a": frozenset({"m.b"}), "n.c": frozenset()}),
    )


def test_reachable_from_equals_the_inline_closure_on_a_toy_graph() -> None:
    g = _toy()
    index = ReferenceGraph.of(g)
    for root in g.edges:
        assert index.reachable_from([root]) == g.closure([root])


def test_reachable_from_honours_a_blocked_module_exactly_as_the_walk_does() -> None:
    g = _toy()
    index = ReferenceGraph.of(g)
    assert index.reachable_from(["m.a"], block=["n"]) == g.closure(["m.a"], block=["n"])


def test_reachable_from_equals_the_inline_closure_on_the_real_graph() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    for root in g.edges:
        assert index.reachable_from([root]) == g.closure([root]), root


def test_module_reach_equals_a_closure_per_module() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    modules = sorted({m for m in g.owner.values()})[:6]
    assert index.module_reach(modules) == {m: g.closure(g.nodes_in(m)) for m in modules}


def test_holders_of_equals_a_brute_force_scan_of_the_captures() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    captured = index.import_time_captures()
    for node in sorted(g.edges):
        brute = tuple(sorted(n for n, reach in captured.items() if n != node and node in reach))
        assert index.holders_of(node) == brute, node
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_reference_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'ReferenceGraph' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/reference_graph.py`:

```python
"""The import-reference graph, built once, queried many times.

`dsp.provenance` asks three reachability questions and hand-rolls a stack DFS
for each: `frozen_captures` inverts a reach map by rescanning it once per
registry rule (provenance.py:505-509, ~126 rules x every import-time node), and
`hardcoding_readers` recomputes `g.closure(g.nodes_in(m))` INSIDE its entry loop
(provenance.py:521-529) -- the very hoist `consultation()` already does
correctly two functions earlier (provenance.py:429-430).

networkx is the backend (Ruling 4's default). This is a lint/provenance path,
not a per-build path, so a pure-Python library costs nothing that matters and
buys correct, tested reachability. The blocked-module walk is expressed as a
subgraph view rather than a filtered traversal so the result is a plain set.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import cached_property

import networkx as nx

from flab2bp.dsp.provenance import Graph

_IMPORT_TIME_KINDS = frozenset({"const", "default"})


class ReferenceGraph:
    """Reachability over dotted definition names, with the walks precomputed."""

    def __init__(self, graph: Graph) -> None:
        self._graph = graph
        digraph: nx.DiGraph = nx.DiGraph()
        digraph.add_nodes_from(graph.edges)
        for node, targets in graph.edges.items():
            for target in targets:
                digraph.add_edge(node, target)
        self._digraph = digraph
        self._owner: Mapping[str, str] = graph.owner

    @classmethod
    def of(cls, graph: Graph) -> ReferenceGraph:
        """Index one provenance graph."""
        return cls(graph)

    def reachable_from(
        self,
        roots: Iterable[str],
        *,
        block: Iterable[str] = (),
    ) -> frozenset[str]:
        """Everything reachable from ``roots``, never entering a blocked module.

        Matches `Graph.closure` exactly, INCLUDING its two quirks: a root not in
        ``edges`` is dropped rather than seeded, and a blocked node is refused at
        the EDGE rather than removed, so a blocked root is still in the result.
        """
        blocked = tuple(block)
        seeds = [r for r in roots if r in self._graph.edges]
        if not seeds:
            return frozenset()
        if not blocked:
            seen: set[str] = set()
            for seed in seeds:
                if seed in seen:
                    continue
                seen.add(seed)
                seen |= nx.descendants(self._digraph, seed)
            return frozenset(seen)
        banned = frozenset(blocked)
        allowed = self._digraph.edge_subgraph(
            [
                (u, v)
                for u, v in self._digraph.edges
                if self._owner.get(v, "") not in banned
            ]
        )
        seen = set(seeds)
        for seed in seeds:
            if seed in allowed:
                seen |= nx.descendants(allowed, seed)
        return frozenset(seen)

    def nodes_in(self, module: str) -> frozenset[str]:
        """Every node defined in one module."""
        return self._nodes_by_module.get(module, frozenset())

    @cached_property
    def _nodes_by_module(self) -> dict[str, frozenset[str]]:
        buckets: dict[str, set[str]] = {}
        for node, module in self._owner.items():
            buckets.setdefault(module, set()).add(node)
        return {module: frozenset(nodes) for module, nodes in buckets.items()}

    def module_reach(self, modules: Iterable[str]) -> dict[str, frozenset[str]]:
        """One closure per module, computed once for the whole caller loop."""
        return {module: self.reachable_from(self.nodes_in(module)) for module in modules}

    @cached_property
    def _captures(self) -> dict[str, frozenset[str]]:
        out: dict[str, frozenset[str]] = {}
        for node, node_kind in self._graph.kind.items():
            if node_kind not in _IMPORT_TIME_KINDS:
                continue
            direct = self._graph.edges.get(node, frozenset())
            run = self.reachable_from(self._graph.calls.get(node, frozenset()))
            out[node] = direct | run
        return out

    def import_time_captures(self) -> dict[str, frozenset[str]]:
        """Node -> what it freezes at import, for every import-time node."""
        return dict(self._captures)

    @cached_property
    def _holders(self) -> dict[str, tuple[str, ...]]:
        inverted: dict[str, list[str]] = {}
        for holder, reach in self._captures.items():
            for node in reach:
                if node == holder:
                    continue
                inverted.setdefault(node, []).append(holder)
        return {node: tuple(sorted(holders)) for node, holders in inverted.items()}

    def holders_of(self, node: str) -> tuple[str, ...]:
        """Import-time nodes that froze ``node``, sorted; empty when none did."""
        return self._holders.get(node, ())
```

Add to `src/flab2bp/indexed/__init__.py`:

```python
from flab2bp.indexed.reference_graph import ReferenceGraph

__all__ = ("ReferenceGraph",)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_reference_graph.py -v`
Expected: PASS, all five tests.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run ruff format --check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
```
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/indexed/reference_graph.py src/flab2bp/indexed/__init__.py tests/indexed/test_reference_graph.py
git commit -m "feat(indexed): add ReferenceGraph over the provenance reference graph"
```

---

## Task 3: `Sorters` — the littletable index over validate's sorters

**Files:**
- Create: `src/flab2bp/indexed/sorters.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_sorters.py`

**Interfaces:**
- Consumes: nothing from `flab2bp` at construction time — the type is built from an iterable of
  `(index: int, building: PlacedBuilding, item: str | None)` triples so it does not import
  `validate` (which would be a cycle). `PlacedBuilding` is imported for typing only.
- Produces:
  - `Sorters.of(rows: Iterable[tuple[int, PlacedBuilding, str | None]]) -> Sorters`
  - `Sorters.drawing_from(source: int) -> tuple[int, ...]` — sorter indices whose `input_obj` is
    `source`, in placement order
  - `Sorters.feeding(destination: int) -> tuple[int, ...]` — sorter indices whose `output_obj` is
    `destination`, in placement order
  - `Sorters.drawing_from_carrying(source: int, item: str) -> tuple[int, ...]`
  - `Sorters.feeding_carrying(destination: int, item: str) -> tuple[int, ...]`
  - `Sorters.carrying(item: str) -> tuple[int, ...]`
  - `Sorters.building(index: int) -> PlacedBuilding`
  - `Sorters.item(index: int) -> str | None`
  - `Sorters.indices() -> tuple[int, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_sorters.py`:

```python
"""Every `Sorters` answer equals the brute-force scan it replaces.

The scan being replaced is validate.py:4620-4628 --
`for sorter_index, sorter in ctx.of_kind(Kind.SORTER) if sorter.input_obj == index`
-- run once per BFS step inside `_belt_reaches_any`. The proof obligation is
equality with that filter, including order, because the caller extends a BFS
frontier with the result and a different order is a different traversal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from flab2bp.indexed import Sorters


@dataclass(frozen=True, slots=True)
class _FakeBuilding:
    """Stands in for `PlacedBuilding`: slotted and frozen, exactly as it is."""

    input_obj: int | None
    output_obj: int | None


def _fixture(seed: int, count: int) -> list[tuple[int, _FakeBuilding, str | None]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "copper-ingot", "gear", None)
    return [
        (
            i,
            _FakeBuilding(
                input_obj=rng.choice([None, *range(count)]),
                output_obj=rng.choice([None, *range(count)]),
            ),
            rng.choice(items),
        )
        for i in range(count)
    ]


def test_drawing_from_equals_the_brute_force_filter_in_placement_order() -> None:
    rows = _fixture(seed=11, count=200)
    index = Sorters.of(rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.input_obj == probe)
        assert index.drawing_from(probe) == brute, probe


def test_feeding_equals_the_brute_force_filter_in_placement_order() -> None:
    rows = _fixture(seed=12, count=200)
    index = Sorters.of(rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.output_obj == probe)
        assert index.feeding(probe) == brute, probe


def test_drawing_from_carrying_equals_the_two_predicate_filter() -> None:
    rows = _fixture(seed=13, count=200)
    index = Sorters.of(rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.input_obj == probe and it == item)
            assert index.drawing_from_carrying(probe, item) == brute, (probe, item)


def test_feeding_carrying_equals_the_two_predicate_filter() -> None:
    rows = _fixture(seed=14, count=200)
    index = Sorters.of(rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.output_obj == probe and it == item)
            assert index.feeding_carrying(probe, item) == brute, (probe, item)


def test_carrying_equals_the_item_filter() -> None:
    rows = _fixture(seed=15, count=200)
    index = Sorters.of(rows)
    for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
        brute = tuple(i for i, _b, it in rows if it == item)
        assert index.carrying(item) == brute, item


def test_a_none_item_is_never_returned_by_carrying() -> None:
    rows = _fixture(seed=16, count=80)
    index = Sorters.of(rows)
    assert all(index.item(i) is not None for i in index.carrying("gear"))


def test_building_and_item_hand_back_the_payload_unchanged() -> None:
    rows = _fixture(seed=17, count=40)
    index = Sorters.of(rows)
    for i, building, item in rows:
        assert index.building(i) is building
        assert index.item(i) == item


def test_an_empty_collection_answers_empty_rather_than_raising() -> None:
    index = Sorters.of(())
    assert index.indices() == ()
    assert index.drawing_from(0) == ()
    assert index.carrying("gear") == ()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_sorters.py -v`
Expected: FAIL — `ImportError: cannot import name 'Sorters' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/sorters.py`:

```python
"""Sorters, indexed by what they draw from, feed, and carry.

Four separate places rebuild this same map ad hoc from `ctx.of_kind(SORTER)`:
`_run_sorter_sources` (validate.py:4322-4342, the one that IS cached),
`_belt_reaches_any`'s inline filter (validate.py:4620-4628, run once per BFS
step -- the whole of scout site #8), `_unsprayed_belts`'s `hops`
(validate.py:4977-4988) and `_sprayed_cargo_reaches_machines`'s `feeds`
(validate.py:5048-5057).

Backend: littletable. The collection is frozen (`Context.of_kind` is a memoized
tuple on a frozen `Context`) but it is queried on THREE keys -- `input_obj`,
`output_obj`, and the resolved item -- by at least four consumers. Three
hand-kept dicts is the duplication being removed; one table with three indexes
is one backend for one collection, which is what Ruling 2 requires. polars is
refused here because every consumer wants the `PlacedBuilding` object and its
placement index back, so a frame would materialise objects per query.

Rows are wrapped in `_SorterRecord` rather than inserted directly: littletable
rebinds attributes on the objects it holds and `PlacedBuilding` is
`@dataclass(frozen=True, slots=True)`, which cannot take one.

ORDER IS PART OF THE CONTRACT. Callers extend a BFS frontier with these results,
so every accessor returns placement order, which is what the scan it replaces
produced.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import littletable

from flab2bp.indexed._record import IndexRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.dsp.catalog import PlacedBuilding


@dataclass
class _SorterRecord(IndexRecord):
    index: int = -1
    input_obj: int | None = None
    output_obj: int | None = None
    item: str | None = None


class Sorters:
    """One placement's sorters, answered by key instead of by scan."""

    def __init__(self, rows: Iterable[tuple[int, PlacedBuilding, str | None]]) -> None:
        table: littletable.Table = littletable.Table("sorters")
        table.create_index("input_obj")
        table.create_index("output_obj")
        table.create_index("item")
        order: list[int] = []
        payloads: dict[int, PlacedBuilding] = {}
        items: dict[int, str | None] = {}
        for index, building, item in rows:
            table.insert(
                _SorterRecord(
                    payload=building,
                    index=index,
                    input_obj=building.input_obj,
                    output_obj=building.output_obj,
                    item=item,
                )
            )
            order.append(index)
            payloads[index] = building
            items[index] = item
        self._table = table
        self._order = tuple(order)
        self._payloads = payloads
        self._items = items
        self._rank = {index: rank for rank, index in enumerate(order)}

    @classmethod
    def of(cls, rows: Iterable[tuple[int, PlacedBuilding, str | None]]) -> Sorters:
        """Index the sorters of one placement."""
        return cls(rows)

    def _ordered(self, records: Iterable[_SorterRecord]) -> tuple[int, ...]:
        return tuple(sorted((r.index for r in records), key=self._rank.__getitem__))

    def drawing_from(self, source: int) -> tuple[int, ...]:
        """Sorters whose ``input_obj`` is ``source``, in placement order."""
        return self._ordered(self._table.by.input_obj[source])

    def feeding(self, destination: int) -> tuple[int, ...]:
        """Sorters whose ``output_obj`` is ``destination``, in placement order."""
        return self._ordered(self._table.by.output_obj[destination])

    def carrying(self, item: str) -> tuple[int, ...]:
        """Sorters resolved to ``item``, in placement order."""
        return self._ordered(self._table.by.item[item])

    def drawing_from_carrying(self, source: int, item: str) -> tuple[int, ...]:
        """Sorters drawing from ``source`` that carry ``item``."""
        return tuple(i for i in self.drawing_from(source) if self._items[i] == item)

    def feeding_carrying(self, destination: int, item: str) -> tuple[int, ...]:
        """Sorters feeding ``destination`` that carry ``item``."""
        return tuple(i for i in self.feeding(destination) if self._items[i] == item)

    def building(self, index: int) -> PlacedBuilding:
        """The placed sorter at ``index``, handed back unchanged."""
        return self._payloads[index]

    def item(self, index: int) -> str | None:
        """The resolved item for the sorter at ``index``."""
        return self._items[index]

    def indices(self) -> tuple[int, ...]:
        """Every sorter index, in placement order."""
        return self._order
```

Extend `src/flab2bp/indexed/__init__.py`:

```python
from flab2bp.indexed.reference_graph import ReferenceGraph
from flab2bp.indexed.sorters import Sorters

__all__ = ("ReferenceGraph", "Sorters")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_sorters.py -v`
Expected: PASS, all eight tests.

If `table.insert(...)` raises, littletable is stamping an attribute the record does not accept —
add the field it names to `_SorterRecord` (it must stay a non-slots dataclass) rather than
switching to `slots=True`.

- [ ] **Step 5: Lint, type-check, and re-run the containment guard**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
uv run pytest tests/indexed/test_backend_containment.py -v
```
Expected: clean, and the guard still passes (the `littletable` import is inside the package).

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/indexed/sorters.py src/flab2bp/indexed/__init__.py tests/indexed/test_sorters.py
git commit -m "feat(indexed): add the Sorters littletable index"
```

---

## Task 4: `Cells` — the littletable index over bench `CellResult`s

**Files:**
- Create: `src/flab2bp/indexed/cells.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_cells.py`

**Interfaces:**
- Consumes: `flab2bp.bench.scoring.CellResult` (fields used: `url_id: str`, `strategy: str`,
  `candidate: str`, `valid: bool`, `area: int`). Imported for typing only.
- Produces:
  - `Cells.of(cells: Sequence[CellResult]) -> Cells`
  - `Cells.best_per_url(*, strategy: str | None = None, valid_only: bool = True, rank: Callable[[CellResult], tuple[int, ...]] | None = None) -> dict[str, CellResult]`
  - `Cells.for_url(url_id: str) -> tuple[CellResult, ...]`
  - `Cells.url_ids() -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_cells.py`:

```python
"""`Cells.best_per_url` equals each of the four scans it replaces.

Four independent re-implementations of "best CellResult per url, smallest area"
exist today, all touched inside one `render_markdown()` pass:
bench/scoring.py:70-79 `_best_per_url`, bench/report.py:44-52 `_best` (identical
logic), bench/report.py:145-152 (inline), bench/regression.py:65-72
`_best_per_url` (a DIFFERENT rank key: `(0 if valid else 1, area)`). The
different key is why this type takes `rank` rather than hard-coding area.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from flab2bp.indexed import Cells


@dataclass(frozen=True, slots=True)
class _FakeCell:
    url_id: str
    strategy: str
    candidate: str
    valid: bool
    area: int


def _fixture(seed: int, count: int) -> list[_FakeCell]:
    rng = random.Random(seed)
    urls = [f"url-{i}" for i in range(12)]
    return [
        _FakeCell(
            url_id=rng.choice(urls),
            strategy=rng.choice(("freeform", "sequence-pair")),
            candidate=rng.choice(("default", "no-proliferator")),
            valid=rng.random() > 0.25,
            area=rng.randrange(100, 10_000),
        )
        for _ in range(count)
    ]


def _brute_best_valid(cells: list[_FakeCell], strategy: str) -> dict[str, _FakeCell]:
    best: dict[str, _FakeCell] = {}
    for cell in cells:
        if cell.strategy != strategy or not cell.valid:
            continue
        current = best.get(cell.url_id)
        if current is None or cell.area < current.area:
            best[cell.url_id] = cell
    return best


def _brute_best_ranked(cells: list[_FakeCell]) -> dict[str, _FakeCell]:
    def rank(cell: _FakeCell) -> tuple[int, int]:
        return (0 if cell.valid else 1, cell.area)

    best: dict[str, _FakeCell] = {}
    for cell in cells:
        current = best.get(cell.url_id)
        if current is None or rank(cell) < rank(current):
            best[cell.url_id] = cell
    return best


def test_best_per_url_equals_the_scoring_and_report_scan() -> None:
    cells = _fixture(seed=21, count=400)
    index = Cells.of(cells)
    for strategy in ("freeform", "sequence-pair"):
        assert index.best_per_url(strategy=strategy) == _brute_best_valid(cells, strategy)


def test_best_per_url_equals_the_regression_scan_with_its_own_rank_key() -> None:
    cells = _fixture(seed=22, count=400)
    index = Cells.of(cells)
    got = index.best_per_url(
        valid_only=False,
        rank=lambda c: (0 if c.valid else 1, c.area),
    )
    assert got == _brute_best_ranked(cells)


def test_ties_keep_the_first_cell_seen_exactly_as_the_scan_does() -> None:
    a = _FakeCell("u", "freeform", "default", True, 100)
    b = _FakeCell("u", "freeform", "no-proliferator", True, 100)
    index = Cells.of([a, b])
    assert index.best_per_url(strategy="freeform")["u"] is a


def test_for_url_returns_every_cell_for_that_url_in_input_order() -> None:
    cells = _fixture(seed=23, count=200)
    index = Cells.of(cells)
    for url_id in index.url_ids():
        assert index.for_url(url_id) == tuple(c for c in cells if c.url_id == url_id)


def test_an_empty_collection_answers_empty() -> None:
    index = Cells.of([])
    assert index.best_per_url(strategy="freeform") == {}
    assert index.url_ids() == ()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_cells.py -v`
Expected: FAIL — `ImportError: cannot import name 'Cells' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/cells.py`:

```python
"""Benchmark cells, indexed by url, with the "best per url" reduction shared.

Four independent implementations of the same reduction exist today
(bench/scoring.py:70-79, bench/report.py:44-52, bench/report.py:145-152,
bench/regression.py:65-72), three with an identical body and one with a
different rank key. This is a HYGIENE conversion: at <=72 rows read once per
report there is no measurable time in it, and the plan keeps it under Ruling I-5
because it removes three re-implementations.

Backend: littletable, indexed on `url_id`. polars is refused by Ruling 2's cost
test at this size and the measurement in the bench conversion task records the
number.

TIE-BREAKING IS PART OF THE CONTRACT. The scans keep the FIRST cell seen on an
equal rank (`if current is None or cell.area < current.area`), so this does too;
a `<=` here would change which candidate a report names.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import littletable

from flab2bp.indexed._record import IndexRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.bench.scoring import CellResult


@dataclass
class _CellRecord(IndexRecord):
    url_id: str = ""
    strategy: str = ""
    position: int = -1


def _area_rank(cell: Any) -> tuple[int, ...]:
    return (cell.area,)


class Cells:
    """One benchmark run's cells, reduced by key instead of by rescan."""

    def __init__(self, cells: Sequence[CellResult]) -> None:
        table: littletable.Table = littletable.Table("cells")
        table.create_index("url_id")
        table.create_index("strategy")
        for position, cell in enumerate(cells):
            table.insert(
                _CellRecord(
                    payload=cell,
                    url_id=cell.url_id,
                    strategy=cell.strategy,
                    position=position,
                )
            )
        self._table = table
        self._cells = tuple(cells)
        self._url_ids = tuple(dict.fromkeys(cell.url_id for cell in cells))

    @classmethod
    def of(cls, cells: Sequence[CellResult]) -> Cells:
        """Index one benchmark run's cells."""
        return cls(cells)

    def url_ids(self) -> tuple[str, ...]:
        """Every url id, first-seen order."""
        return self._url_ids

    def for_url(self, url_id: str) -> tuple[CellResult, ...]:
        """Every cell for one url, in input order."""
        records = sorted(self._table.by.url_id[url_id], key=lambda r: r.position)
        return tuple(record.payload for record in records)

    def best_per_url(
        self,
        *,
        strategy: str | None = None,
        valid_only: bool = True,
        rank: Callable[[CellResult], tuple[int, ...]] | None = None,
    ) -> dict[str, CellResult]:
        """The cell the pipeline would ship for each url.

        ``rank`` defaults to smallest area. Ties keep the first cell in input
        order, exactly as the scans this replaces did.
        """
        key = _area_rank if rank is None else rank
        best: dict[str, CellResult] = {}
        for cell in self._cells:
            if strategy is not None and cell.strategy != strategy:
                continue
            if valid_only and not cell.valid:
                continue
            current = best.get(cell.url_id)
            if current is None or key(cell) < key(current):
                best[cell.url_id] = cell
        return best
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_cells.py -v`
Expected: PASS, all five tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/cells.py src/flab2bp/indexed/__init__.py tests/indexed/test_cells.py
git commit -m "feat(indexed): add the Cells index for bench reductions"
```

Note for Step 3: `src/flab2bp/indexed/__init__.py` becomes

```python
from flab2bp.indexed.cells import Cells
from flab2bp.indexed.reference_graph import ReferenceGraph
from flab2bp.indexed.sorters import Sorters

__all__ = ("Cells", "ReferenceGraph", "Sorters")
```

Every later domain-type task adds its own import and name to this tuple, alphabetically.

---

## Task 5: `Stages` — the solver's stage ledger with a maintained count

**Files:**
- Create: `src/flab2bp/indexed/stages.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_stages.py`

**Interfaces:**
- Consumes: nothing. The predicate is injected at construction so the type does not import
  `sequence_solver` (which would be a cycle).
- Produces:
  - `Stages(counts: Callable[[T], bool])` — construct empty
  - `Stages.append(stage: T) -> None`
  - `Stages.replace_last(stage: T) -> None`
  - `Stages.last() -> T`
  - `Stages.scheduled_count() -> int`
  - `Stages.__len__`, `Stages.__iter__`, `Stages.__reversed__`, `Stages.__getitem__`
  - `Stages.as_tuple() -> tuple[T, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_stages.py`:

```python
"""The maintained count must survive a REWRITE, not only an append.

`sequence_solver.py:2106-2107` does
`self._stage_stats[-1] = replace(observation, global_skip_reason="projection-feedback")`
AFTER the stage was appended, and `_counts_as_scheduled_stage`
(sequence_solver.py:865-871) is False for that reason. So a counter incremented
only at the append site over-counts, and `stage_limit` at :1280 and :2036 then
stops the search early. That is the staleness test this file exists for.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from flab2bp.indexed import Stages


@dataclass(frozen=True, slots=True)
class _FakeStage:
    stage_index: int
    global_skip_reason: str | None = None


_UNSCHEDULED = ("shared-pack", "topology-beam", "projection-feedback")


def _counts(stage: _FakeStage) -> bool:
    return stage.global_skip_reason not in _UNSCHEDULED


def test_scheduled_count_equals_the_brute_force_sum_after_every_append() -> None:
    rng = random.Random(31)
    ledger: Stages[_FakeStage] = Stages(_counts)
    seen: list[_FakeStage] = []
    for i in range(500):
        stage = _FakeStage(i, rng.choice([None, None, None, *_UNSCHEDULED]))
        ledger.append(stage)
        seen.append(stage)
        assert ledger.scheduled_count() == sum(_counts(s) for s in seen), i


def test_replace_last_updates_the_count_when_the_predicate_flips_off() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0))
    assert ledger.scheduled_count() == 1
    ledger.replace_last(replace(ledger.last(), global_skip_reason="projection-feedback"))
    assert ledger.scheduled_count() == 0


def test_replace_last_updates_the_count_when_the_predicate_flips_on() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0, "shared-pack"))
    assert ledger.scheduled_count() == 0
    ledger.replace_last(replace(ledger.last(), global_skip_reason=None))
    assert ledger.scheduled_count() == 1


def test_replace_last_leaves_the_count_alone_when_the_predicate_does_not_move() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0))
    ledger.append(_FakeStage(1))
    ledger.replace_last(_FakeStage(99))
    assert ledger.scheduled_count() == 2
    assert ledger.last().stage_index == 99


def test_the_count_matches_a_brute_force_sum_under_interleaved_appends_and_rewrites() -> None:
    rng = random.Random(32)
    ledger: Stages[_FakeStage] = Stages(_counts)
    seen: list[_FakeStage] = []
    for i in range(1000):
        if seen and rng.random() < 0.3:
            stage = _FakeStage(i, rng.choice([None, *_UNSCHEDULED]))
            ledger.replace_last(stage)
            seen[-1] = stage
        else:
            stage = _FakeStage(i, rng.choice([None, None, *_UNSCHEDULED]))
            ledger.append(stage)
            seen.append(stage)
        assert ledger.scheduled_count() == sum(_counts(s) for s in seen), i


def test_iteration_reverse_iteration_and_indexing_match_the_list_it_replaces() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    made = [_FakeStage(i) for i in range(10)]
    for stage in made:
        ledger.append(stage)
    assert list(ledger) == made
    assert list(reversed(ledger)) == list(reversed(made))
    assert ledger[-1] is made[-1]
    assert ledger.as_tuple() == tuple(made)
    assert len(ledger) == 10


def test_replace_last_on_an_empty_ledger_raises_rather_than_corrupting_the_count() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    try:
        ledger.replace_last(_FakeStage(0))
    except IndexError:
        return
    raise AssertionError("replace_last on an empty ledger must raise IndexError")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_stages.py -v`
Expected: FAIL — `ImportError: cannot import name 'Stages' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/stages.py`:

```python
"""An append-and-rewrite ledger that keeps its own predicate count.

`SequenceSolver` sums `_counts_as_scheduled_stage` over `self._stage_stats` on
EVERY iteration of its top-level `while True:` driver (sequence_solver.py:1280)
and again inside `_run_pending_projection_feedback` (:2030), which that same
loop reaches from three sites. The list grows one entry per stage, so the sum is
O(S) per iteration and O(S^2) over a solve.

The list is also REWRITTEN in place: sequence_solver.py:2106-2107 replaces
`[-1]` with a copy whose `global_skip_reason` is "projection-feedback", and the
predicate is False for that reason. That is why this type owns BOTH mutations
and re-evaluates the predicate on each; a counter bumped only on append reports
a number the scan never would.

Backend: a plain list plus an int. The only repeated query is a count under one
predicate, on the hottest write path in the solver -- Ruling 2's plain-index
clause, and a littletable insert per stage would move cost onto that write for a
question one integer answers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class Stages(Generic[T]):
    """Ordered stage observations with a maintained "counts as scheduled" total."""

    __slots__ = ("_counts", "_scheduled", "_stages")

    def __init__(self, counts: Callable[[T], bool]) -> None:
        self._counts = counts
        self._stages: list[T] = []
        self._scheduled = 0

    def append(self, stage: T) -> None:
        """Record one observation."""
        self._stages.append(stage)
        if self._counts(stage):
            self._scheduled += 1

    def replace_last(self, stage: T) -> None:
        """Rewrite the most recent observation, re-deciding whether it counts."""
        if not self._stages:
            raise IndexError("replace_last on an empty stage ledger")
        if self._counts(self._stages[-1]):
            self._scheduled -= 1
        self._stages[-1] = stage
        if self._counts(stage):
            self._scheduled += 1

    def last(self) -> T:
        """The most recent observation."""
        return self._stages[-1]

    def scheduled_count(self) -> int:
        """How many observations consume a scheduled search stage."""
        return self._scheduled

    def as_tuple(self) -> tuple[T, ...]:
        """Every observation, in order, as an immutable snapshot."""
        return tuple(self._stages)

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[T]:
        return iter(self._stages)

    def __reversed__(self) -> Iterator[T]:
        return reversed(self._stages)

    def __getitem__(self, index: int) -> T:
        return self._stages[index]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_stages.py -v`
Expected: PASS, all seven tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/stages.py src/flab2bp/indexed/__init__.py tests/indexed/test_stages.py
git commit -m "feat(indexed): add the Stages ledger with a rewrite-safe scheduled count"
```

---

## Task 6: `StripPositions` — the permutation position index

**Files:**
- Create: `src/flab2bp/indexed/strip_positions.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_strip_positions.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `StripPositions.of(permutation: Sequence[int]) -> StripPositions`
  - `StripPositions.position_of(strip: int) -> int`
  - `StripPositions.positions_of(first: int, second: int) -> tuple[int, int]`
  - `StripPositions.strip_at(position: int) -> int`
  - `StripPositions.__len__`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_strip_positions.py`:

```python
"""Position lookups equal `tuple.index`, which is the scan being replaced.

`apply_move`'s SWAP_BOTH does `negative.index(first_strip)` and
`negative.index(second_strip)` (sequence_pair.py:1479-1480) once per move inside
`anneal_stage`'s per-move loop (sequence_pair.py:1656) -- two O(N) scans on the
hottest Python loop in the solver. `swapped()` in
`_projection_feedback_stage_update` (sequence_solver.py:3489-3491) does the same
thing up to 32 times per call, and `merge_stage_boundary`
(sequence_pair.py:1902-1905) and `transform_stage` (sequence_solver.py:5646) do
it once each.
"""

from __future__ import annotations

import random

import pytest

from flab2bp.indexed import StripPositions


def test_position_of_equals_tuple_index_for_every_strip() -> None:
    rng = random.Random(41)
    for size in (1, 2, 5, 30, 200):
        permutation = list(range(size))
        rng.shuffle(permutation)
        as_tuple = tuple(permutation)
        index = StripPositions.of(as_tuple)
        for strip in as_tuple:
            assert index.position_of(strip) == as_tuple.index(strip), (size, strip)


def test_positions_of_equals_two_tuple_index_calls() -> None:
    rng = random.Random(42)
    permutation = list(range(64))
    rng.shuffle(permutation)
    as_tuple = tuple(permutation)
    index = StripPositions.of(as_tuple)
    for _ in range(200):
        first, second = rng.sample(as_tuple, 2)
        assert index.positions_of(first, second) == (
            as_tuple.index(first),
            as_tuple.index(second),
        )


def test_strip_at_is_the_inverse_of_position_of() -> None:
    index = StripPositions.of((3, 0, 2, 1))
    for position in range(4):
        assert index.position_of(index.strip_at(position)) == position


def test_an_absent_strip_raises_the_same_shape_of_error_as_index() -> None:
    index = StripPositions.of((0, 1, 2))
    with pytest.raises(KeyError):
        index.position_of(9)


def test_an_empty_permutation_is_legal_and_empty() -> None:
    index = StripPositions.of(())
    assert len(index) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_strip_positions.py -v`
Expected: FAIL — `ImportError: cannot import name 'StripPositions' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/strip_positions.py`:

```python
"""Where each strip sits in one sequence-pair permutation.

Backend: a plain dict. The query is a single key over tens of strips on the
hottest Python loop in the solver, which is exactly the case Ruling 2 hands to a
plain dict; a littletable insert per move would cost more than the two
`tuple.index` scans it replaces.

`decode_sequence_pair` already builds this index inline
(sequence_pair.py:849-851) and then throws it away. This type is that pattern
promoted, not a new idea.
"""

from __future__ import annotations

from collections.abc import Sequence


class StripPositions:
    """A strip -> position map over one permutation, built once."""

    __slots__ = ("_permutation", "_position")

    def __init__(self, permutation: Sequence[int]) -> None:
        self._permutation = tuple(permutation)
        self._position = {strip: position for position, strip in enumerate(self._permutation)}

    @classmethod
    def of(cls, permutation: Sequence[int]) -> StripPositions:
        """Index one permutation."""
        return cls(permutation)

    def position_of(self, strip: int) -> int:
        """Where ``strip`` sits. Raises ``KeyError`` when it is not present."""
        return self._position[strip]

    def positions_of(self, first: int, second: int) -> tuple[int, int]:
        """Both positions in one call, for the swap that always wants two."""
        position = self._position
        return position[first], position[second]

    def strip_at(self, position: int) -> int:
        """The strip at ``position``."""
        return self._permutation[position]

    def __len__(self) -> int:
        return len(self._permutation)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_strip_positions.py -v`
Expected: PASS, all five tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/strip_positions.py src/flab2bp/indexed/__init__.py tests/indexed/test_strip_positions.py
git commit -m "feat(indexed): add StripPositions for permutation position lookups"
```

---

## Task 7: `StakedPaths` — the incrementally maintained path-endpoint index

**Files:**
- Create: `src/flab2bp/indexed/staked_paths.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_staked_paths.py`

**Interfaces:**
- Consumes: nothing. `Cell` is `tuple[int, int, int]`; the type is generic over it.
- Produces:
  - `StakedPaths(steps: Sequence[tuple[int, int]])` — `steps` is freeform's `_STEPS`
  - `StakedPaths.stake(net: int, path: Sequence[Cell]) -> None`
  - `StakedPaths.unstake(net: int) -> None`
  - `StakedPaths.path(net: int) -> tuple[Cell, ...]`
  - `StakedPaths.nets() -> tuple[int, ...]`
  - `StakedPaths.beside(cell: Cell) -> frozenset[int]` — nets with an endpoint adjacent to `cell`
  - `StakedPaths.sole_neighbours(net: int, owner: Mapping[Cell, int]) -> frozenset[int]`
  - `StakedPaths.position_in(net: int, cell: Cell) -> int | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_staked_paths.py`:

```python
"""The maintained index equals `_leaning`'s from-scratch rebuild, always.

`_leaning` (freeform.py:10331-10344) rebuilds `touch` and `sole` from every
staked path's endpoints on EVERY call, once per stranded net inside `_repair`'s
loop, which itself runs per routing round per candidate pack per candidate
height. `paths` is rewritten under it the whole time -- `paths[index] = path` in
`_stake` (freeform.py:9931) and `paths.pop(index)` in `_unstake` (:9962) -- so
the staleness test is the point of this file, not a formality.
"""

from __future__ import annotations

import random

from flab2bp.indexed import StakedPaths

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int, int]


def _brute_touch(paths: dict[int, tuple[Cell, ...]]) -> dict[Cell, set[int]]:
    touch: dict[Cell, set[int]] = {}
    for other, path in paths.items():
        for end in (path[0], path[-1]):
            for dx, dy in _STEPS:
                beside = (end[0] + dx, end[1] + dy, end[2])
                touch.setdefault(beside, set()).add(other)
    return touch


def _brute_sole(
    paths: dict[int, tuple[Cell, ...]],
    owner: dict[Cell, int],
) -> dict[int, set[int]]:
    sole: dict[int, set[int]] = {}
    for other, path in paths.items():
        for end in (path[0], path[-1]):
            near: set[int] = set()
            for dx, dy in _STEPS:
                beside = (end[0] + dx, end[1] + dy, end[2])
                held = owner.get(beside)
                if held is not None and held != other:
                    near.add(held)
            if len(near) == 1:
                sole.setdefault(other, set()).update(near)
    return sole


def _random_path(rng: random.Random) -> tuple[Cell, ...]:
    x, y, z = rng.randrange(20), rng.randrange(20), rng.randrange(2)
    out = [(x, y, z)]
    for _ in range(rng.randrange(1, 6)):
        dx, dy = rng.choice(_STEPS)
        x, y = x + dx, y + dy
        out.append((x, y, z))
    return tuple(out)


def test_beside_equals_the_from_scratch_touch_map_after_every_mutation() -> None:
    rng = random.Random(51)
    index = StakedPaths(_STEPS)
    live: dict[int, tuple[Cell, ...]] = {}
    for step in range(400):
        if live and rng.random() < 0.35:
            victim = rng.choice(sorted(live))
            index.unstake(victim)
            del live[victim]
        else:
            net = step
            path = _random_path(rng)
            index.stake(net, path)
            live[net] = path
        brute = _brute_touch(live)
        for cell, expected in brute.items():
            assert index.beside(cell) == frozenset(expected), (step, cell)
        assert index.nets() == tuple(sorted(live)), step


def test_beside_forgets_a_cell_entirely_once_its_last_net_is_unstaked() -> None:
    index = StakedPaths(_STEPS)
    index.stake(1, ((5, 5, 0), (6, 5, 0)))
    assert index.beside((4, 5, 0)) == frozenset({1})
    index.unstake(1)
    assert index.beside((4, 5, 0)) == frozenset()


def test_restaking_the_same_net_replaces_rather_than_accumulates() -> None:
    index = StakedPaths(_STEPS)
    index.stake(1, ((5, 5, 0), (6, 5, 0)))
    index.stake(1, ((9, 9, 0), (10, 9, 0)))
    assert index.beside((4, 5, 0)) == frozenset()
    assert index.beside((8, 9, 0)) == frozenset({1})
    assert index.path(1) == ((9, 9, 0), (10, 9, 0))


def test_sole_neighbours_equals_the_from_scratch_sole_map() -> None:
    rng = random.Random(52)
    index = StakedPaths(_STEPS)
    live: dict[int, tuple[Cell, ...]] = {}
    for net in range(60):
        path = _random_path(rng)
        index.stake(net, path)
        live[net] = path
    owner: dict[Cell, int] = {}
    for net, path in live.items():
        for cell in path:
            owner[cell] = net
    brute = _brute_sole(live, owner)
    for net in live:
        assert index.sole_neighbours(net, owner) == frozenset(brute.get(net, set())), net


def test_position_in_equals_tuple_index_and_answers_none_when_absent() -> None:
    index = StakedPaths(_STEPS)
    path = ((1, 1, 0), (2, 1, 0), (3, 1, 0))
    index.stake(7, path)
    for position, cell in enumerate(path):
        assert index.position_in(7, cell) == position
    assert index.position_in(7, (9, 9, 9)) is None
    assert index.position_in(999, (1, 1, 0)) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_staked_paths.py -v`
Expected: FAIL — `ImportError: cannot import name 'StakedPaths' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/staked_paths.py`:

```python
"""Staked router paths, with the endpoint-adjacency index kept in step.

`_leaning` (freeform.py:10290-10360) rebuilds `touch` and `sole` from every
staked path on every call, once per stranded net inside `_repair`. The paths
themselves are rewritten under it by `_stake` (freeform.py:9931) and `_unstake`
(:9962) in the same phase, which is precisely why the index has to be
MAINTAINED rather than memoized. `into`/`refresh_predecessor`
(freeform.py:12496-12513) is the model.

Backend: plain dicts of sets, maintained on stake/unstake. Ruling 2 sends
"grows during a phase" to littletable, and Ruling I-4 overrides that here on one
condition: the write path runs far more often than the read path, so a table
insert per stake would move cost onto the hotter side. The measurement task for
freeform settles it -- and if the dict does not win, the backend changes INSIDE
this module and no caller moves, which is the whole point of the abstraction.

`sole_neighbours` deliberately takes `owner` per call rather than holding it:
`owner` is the router's own cell->net map, rewritten by rip-up outside this
type's knowledge, and a stale copy of it would be a wrong answer rather than a
slow one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

Cell = tuple[int, int, int]


class StakedPaths:
    """Nets currently staked, indexed by the cells beside their endpoints."""

    __slots__ = ("_beside", "_paths", "_positions", "_steps")

    def __init__(self, steps: Sequence[tuple[int, int]]) -> None:
        self._steps = tuple(steps)
        self._paths: dict[int, tuple[Cell, ...]] = {}
        self._positions: dict[int, dict[Cell, int]] = {}
        self._beside: dict[Cell, set[int]] = {}

    def _endpoint_neighbours(self, path: tuple[Cell, ...]) -> list[Cell]:
        out: list[Cell] = []
        for end in (path[0], path[-1]):
            for dx, dy in self._steps:
                out.append((end[0] + dx, end[1] + dy, end[2]))
        return out

    def stake(self, net: int, path: Sequence[Cell]) -> None:
        """Record ``net`` on ``path``, replacing any path it already held."""
        if net in self._paths:
            self.unstake(net)
        frozen = tuple(path)
        if not frozen:
            raise ValueError("a staked path cannot be empty")
        self._paths[net] = frozen
        self._positions[net] = {cell: position for position, cell in enumerate(frozen)}
        for cell in self._endpoint_neighbours(frozen):
            self._beside.setdefault(cell, set()).add(net)

    def unstake(self, net: int) -> None:
        """Forget ``net`` entirely. A net that is not staked is not an error."""
        path = self._paths.pop(net, None)
        if path is None:
            return
        self._positions.pop(net, None)
        for cell in self._endpoint_neighbours(path):
            holders = self._beside.get(cell)
            if holders is None:
                continue
            holders.discard(net)
            if not holders:
                del self._beside[cell]

    def path(self, net: int) -> tuple[Cell, ...]:
        """The path ``net`` currently holds; empty when it holds none."""
        return self._paths.get(net, ())

    def nets(self) -> tuple[int, ...]:
        """Every staked net, ascending."""
        return tuple(sorted(self._paths))

    def beside(self, cell: Cell) -> frozenset[int]:
        """Nets with an endpoint adjacent to ``cell``."""
        return frozenset(self._beside.get(cell, ()))

    def sole_neighbours(self, net: int, owner: Mapping[Cell, int]) -> frozenset[int]:
        """Nets that are ``net``'s ONLY neighbour at one of its ends.

        Matches freeform.py:10336-10344 exactly: an end whose four steps reach
        exactly one OTHER owner contributes that owner; an end reaching zero or
        two or more contributes nothing.
        """
        path = self._paths.get(net)
        if path is None:
            return frozenset()
        out: set[int] = set()
        for end in (path[0], path[-1]):
            near: set[int] = set()
            for dx, dy in self._steps:
                held = owner.get((end[0] + dx, end[1] + dy, end[2]))
                if held is not None and held != net:
                    near.add(held)
            if len(near) == 1:
                out |= near
        return frozenset(out)

    def position_in(self, net: int, cell: Cell) -> int | None:
        """Where ``cell`` sits on ``net``'s path, or ``None``.

        Replaces the "membership test then `.index()`" double scan at
        freeform.py:10442-10456, which walked the same tuple twice.
        """
        positions = self._positions.get(net)
        if positions is None:
            return None
        return positions.get(cell)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_staked_paths.py -v`
Expected: PASS, all five tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/staked_paths.py src/flab2bp/indexed/__init__.py tests/indexed/test_staked_paths.py
git commit -m "feat(indexed): add StakedPaths with a maintained endpoint index"
```

---

## Task 8: `BlockGraph` — networkx behind the hierarchy block topological order

**Files:**
- Create: `src/flab2bp/indexed/block_graph.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_block_graph.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BlockGraph.of(node_count: int, edges: Iterable[tuple[int, int]]) -> BlockGraph`
  - `BlockGraph.topological_order() -> tuple[int, ...]` — lexicographic Kahn, ties by node id
  - `BlockGraph.has_cycle() -> bool`
  - `BlockGraph.successors(node: int) -> tuple[int, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_block_graph.py`:

```python
"""`BlockGraph.topological_order` equals the inline Kahn walk it replaces.

`partition.py:200-226` `_topo_order` re-sorts its ready frontier on EVERY
dequeue (`ready = sorted(set(ready) - seen)`), which is O(n^2 log n). It is
re-derived every round of `HierarchicalLayout.lay_out` (hierarchy/strategy.py:607),
by design, because the block graph genuinely changes each round.

The order is BYTE-VISIBLE -- it decides which cut a round takes -- so equality
with the inline walk on random DAGs is the whole proof.
"""

from __future__ import annotations

import random

from flab2bp.indexed import BlockGraph


def _inline_topo_order(node_count: int, edges: list[tuple[int, int]]) -> tuple[int, ...]:
    """The exact algorithm at partition.py:200-226, transcribed."""
    indegree = dict.fromkeys(range(node_count), 0)
    successors: dict[int, list[int]] = {n: [] for n in range(node_count)}
    for src, dst in edges:
        successors[src].append(dst)
        indegree[dst] += 1
    ready = sorted(n for n in range(node_count) if indegree[n] == 0)
    seen: set[int] = set()
    out: list[int] = []
    while ready:
        node = ready.pop(0)
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready = sorted(set(ready) - seen)
    return tuple(out)


def _random_dag(rng: random.Random, node_count: int) -> list[tuple[int, int]]:
    order = list(range(node_count))
    rng.shuffle(order)
    edges: list[tuple[int, int]] = []
    for i, src in enumerate(order):
        for dst in order[i + 1 :]:
            if rng.random() < 0.12:
                edges.append((src, dst))
    return edges


def test_topological_order_equals_the_inline_kahn_walk_on_random_dags() -> None:
    rng = random.Random(61)
    for node_count in (1, 2, 5, 12, 40, 120):
        for _ in range(20):
            edges = _random_dag(rng, node_count)
            got = BlockGraph.of(node_count, edges).topological_order()
            assert got == _inline_topo_order(node_count, edges), (node_count, edges)


def test_a_graph_with_no_edges_orders_by_node_id() -> None:
    assert BlockGraph.of(5, []).topological_order() == (0, 1, 2, 3, 4)


def test_has_cycle_is_true_for_a_cycle_and_false_for_a_dag() -> None:
    assert BlockGraph.of(3, [(0, 1), (1, 2), (2, 0)]).has_cycle()
    assert not BlockGraph.of(3, [(0, 1), (1, 2)]).has_cycle()


def test_a_cyclic_graph_orders_only_the_acyclic_prefix_as_the_inline_walk_does() -> None:
    edges = [(0, 1), (1, 2), (2, 1), (0, 3)]
    got = BlockGraph.of(4, edges).topological_order()
    assert got == _inline_topo_order(4, edges)


def test_successors_are_ascending_and_deduplicated() -> None:
    graph = BlockGraph.of(4, [(0, 2), (0, 1), (0, 2)])
    assert graph.successors(0) == (1, 2)
    assert graph.successors(3) == ()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_block_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'BlockGraph' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/block_graph.py`:

```python
"""The hierarchy block graph, ordered without re-sorting the frontier.

`partition.py:200-226` `_topo_order` does `ready = sorted(set(ready) - seen)`
after EVERY dequeue: O(n) set-difference and O(n log n) sort per node, so
O(n^2 log n) for a walk that is O(n log n). The re-derivation per round is
correct and stays -- the block graph really does change each round -- and only
the internals move.

Backend: networkx (Ruling 4's default). `lexicographical_topological_sort`
produces the SAME order as the inline walk, because that walk always dequeues
the smallest ready node. A cyclic graph is handled the way the inline walk
handled it -- emit the acyclic prefix and stop -- rather than raising, because
`derive_cuts` relies on a short answer meaning "not all blocks are ordered".

The measurement task for the hierarchy conversion decides whether networkx's
per-round build pays for itself at the real block counts; if it does not, the
`heapq` frontier in `_heap_order` below replaces the networkx call INSIDE this
module and no caller moves.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable

import networkx as nx


class BlockGraph:
    """A block precedence graph with a deterministic topological order."""

    __slots__ = ("_digraph", "_node_count")

    def __init__(self, node_count: int, edges: Iterable[tuple[int, int]]) -> None:
        digraph: nx.DiGraph = nx.DiGraph()
        digraph.add_nodes_from(range(node_count))
        digraph.add_edges_from(edges)
        self._digraph = digraph
        self._node_count = node_count

    @classmethod
    def of(cls, node_count: int, edges: Iterable[tuple[int, int]]) -> BlockGraph:
        """Build one round's block graph."""
        return cls(node_count, edges)

    def successors(self, node: int) -> tuple[int, ...]:
        """Blocks that must follow ``node``, ascending."""
        return tuple(sorted(self._digraph.successors(node)))

    def has_cycle(self) -> bool:
        """Whether any block precedence cycle exists."""
        return not nx.is_directed_acyclic_graph(self._digraph)

    def topological_order(self) -> tuple[int, ...]:
        """Blocks in dependency order, ties broken by ascending block id.

        On a cyclic graph this returns the acyclic prefix, which is what the
        inline walk returned and what `derive_cuts` reads as "incomplete".
        """
        if self.has_cycle():
            return self._heap_order()
        return tuple(nx.lexicographical_topological_sort(self._digraph))

    def _heap_order(self) -> tuple[int, ...]:
        indegree = {node: self._digraph.in_degree(node) for node in self._digraph}
        frontier = [node for node, degree in indegree.items() if degree == 0]
        heapq.heapify(frontier)
        out: list[int] = []
        while frontier:
            node = heapq.heappop(frontier)
            out.append(node)
            for nxt in self._digraph.successors(node):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    heapq.heappush(frontier, nxt)
        return tuple(out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_block_graph.py -v`
Expected: PASS, all five tests. If
`test_a_cyclic_graph_orders_only_the_acyclic_prefix_as_the_inline_walk_does` fails, the inline
walk's cyclic behaviour differs from `_heap_order` — transcribe `partition.py:200-226` again and
match it exactly; the inline walk is authoritative, not this module.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/block_graph.py src/flab2bp/indexed/__init__.py tests/indexed/test_block_graph.py
git commit -m "feat(indexed): add BlockGraph over the hierarchy block precedence graph"
```

---

## Task 9: `UnionFind` — one implementation instead of three

**Files:**
- Create: `src/flab2bp/indexed/union_find.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_union_find.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `UnionFind()` — construct empty; nodes are created on first use
  - `UnionFind.find(node: Hashable) -> Hashable`
  - `UnionFind.union(left: Hashable, right: Hashable) -> bool` — True when a merge happened
  - `UnionFind.connected(left: Hashable, right: Hashable) -> bool`
  - `UnionFind.groups() -> tuple[tuple[Hashable, ...], ...]` — each group sorted by insertion order,
    groups in first-insertion order

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_union_find.py`:

```python
"""One path-compressed union-find, replacing three hand-rolled ones.

freeform.py writes the same structure from scratch at :16008-16115
(`_connect_short_cuts`), :16115-16236 (`_join_shard_islands`) and :8959-9020
(net-role grouping). This is a duplication defect, not a complexity defect, and
it is kept under Ruling I-5 for exactly that reason.
"""

from __future__ import annotations

import random

from flab2bp.indexed import UnionFind


def _brute_groups(nodes: list[int], pairs: list[tuple[int, int]]) -> set[frozenset[int]]:
    groups = [{n} for n in nodes]
    for left, right in pairs:
        hit = [g for g in groups if left in g or right in g]
        merged: set[int] = {left, right}
        for g in hit:
            merged |= g
            groups.remove(g)
        groups.append(merged)
    return {frozenset(g) for g in groups}


def test_groups_equal_a_brute_force_merge_on_random_pairs() -> None:
    rng = random.Random(71)
    for _ in range(50):
        nodes = list(range(30))
        pairs = [(rng.randrange(30), rng.randrange(30)) for _ in range(25)]
        uf = UnionFind()
        for node in nodes:
            uf.find(node)
        for left, right in pairs:
            uf.union(left, right)
        got = {frozenset(g) for g in uf.groups()}
        assert got == _brute_groups(nodes, pairs)


def test_union_reports_whether_it_actually_merged() -> None:
    uf = UnionFind()
    assert uf.union("a", "b")
    assert not uf.union("a", "b")
    assert not uf.union("b", "a")


def test_connected_is_reflexive_symmetric_and_transitive() -> None:
    uf = UnionFind()
    uf.union(1, 2)
    uf.union(2, 3)
    assert uf.connected(1, 1)
    assert uf.connected(1, 3) and uf.connected(3, 1)
    assert not uf.connected(1, 9)


def test_groups_are_in_first_insertion_order_and_sorted_within() -> None:
    uf = UnionFind()
    for node in (5, 3, 9, 1):
        uf.find(node)
    uf.union(9, 3)
    assert uf.groups() == ((5,), (3, 9), (1,))


def test_an_untouched_node_is_its_own_group() -> None:
    uf = UnionFind()
    assert uf.find("x") == "x"
    assert uf.groups() == (("x",),)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_union_find.py -v`
Expected: FAIL — `ImportError: cannot import name 'UnionFind' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/union_find.py`:

```python
"""Disjoint sets with path compression and union by rank.

Backend: plain dicts. `networkx.utils.UnionFind` exists but is slower than this
and would drag a graph library into freeform's hot path for a structure with no
query to index. Ruling 3's "one domain type per kind of collection" is what puts
it here rather than in freeform.

`groups()` is ordered -- first-insertion order between groups, insertion order
within one -- because two of the three call sites feed their result straight
into a routing decision, and an arbitrary set order would make those decisions
non-reproducible.
"""

from __future__ import annotations

from collections.abc import Hashable


class UnionFind:
    """Merge-and-query disjoint sets over arbitrary hashable nodes."""

    __slots__ = ("_order", "_parent", "_rank")

    def __init__(self) -> None:
        self._parent: dict[Hashable, Hashable] = {}
        self._rank: dict[Hashable, int] = {}
        self._order: list[Hashable] = []

    def find(self, node: Hashable) -> Hashable:
        """The representative of ``node``'s set, creating the node if new."""
        parent = self._parent
        if node not in parent:
            parent[node] = node
            self._rank[node] = 0
            self._order.append(node)
            return node
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(self, left: Hashable, right: Hashable) -> bool:
        """Merge two sets. Returns whether they were distinct."""
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        if self._rank[left_root] < self._rank[right_root]:
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root
        if self._rank[left_root] == self._rank[right_root]:
            self._rank[left_root] += 1
        return True

    def connected(self, left: Hashable, right: Hashable) -> bool:
        """Whether two nodes share a set."""
        return self.find(left) == self.find(right)

    def groups(self) -> tuple[tuple[Hashable, ...], ...]:
        """Every set, in first-insertion order, members in insertion order."""
        buckets: dict[Hashable, list[Hashable]] = {}
        for node in self._order:
            buckets.setdefault(self.find(node), []).append(node)
        seen: set[Hashable] = set()
        out: list[tuple[Hashable, ...]] = []
        for node in self._order:
            root = self.find(node)
            if root in seen:
                continue
            seen.add(root)
            out.append(tuple(buckets[root]))
        return tuple(out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_union_find.py -v`
Expected: PASS, all five tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
export GIT_EDITOR=true
git add src/flab2bp/indexed/union_find.py src/flab2bp/indexed/__init__.py tests/indexed/test_union_find.py
git commit -m "feat(indexed): add UnionFind, replacing three hand-rolled copies"
```

---

## Task 10: `Nets` — the littletable index over prepared routing nets

**Files:**
- Create: `src/flab2bp/indexed/nets.py`
- Modify: `src/flab2bp/indexed/__init__.py`
- Test: `tests/indexed/test_nets.py`

**Interfaces:**
- Consumes: nothing at runtime — built from `(net_id, item, kind, cell, role, payload)` tuples so
  it does not import `freeform`.
- Produces:
  - `Nets.of(rows: Iterable[tuple[int, str, str, Cell, str, object]]) -> Nets`
  - `Nets.by_id(net_id: int) -> object | None`
  - `Nets.matching_demand(item: str, kind: str, cell: Cell) -> tuple[object, ...]`
  - `Nets.in_role(role: str) -> tuple[int, ...]`
  - `Nets.ids() -> tuple[int, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_nets.py`:

```python
"""Composite-key demand matching equals the `next()`-inside-a-comprehension scan.

freeform.py:12111-12129 / :17317-17321 asks `matches_demand(candidate, demand)`
-- item, kind and cell equality -- with a `next()` over EVERY prepared net,
inside a comprehension over every missing demand: O(missing x all_prepared_nets).
The same collection is separately keyed by id at freeform.py:9425 (`net_by_id`)
and by role at :9372 (`role_members`), which is why one table with three indexes
replaces three hand-built dicts rather than adding a fourth.
"""

from __future__ import annotations

import random

from flab2bp.indexed import Nets


def _fixture(seed: int, count: int) -> list[tuple[int, str, str, tuple[int, int, int], str, str]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "gear", "circuit")
    kinds = ("input", "output")
    roles = ("producer", "consumer", "external")
    return [
        (
            i,
            rng.choice(items),
            rng.choice(kinds),
            (rng.randrange(8), rng.randrange(8), 0),
            rng.choice(roles),
            f"net-{i}",
        )
        for i in range(count)
    ]


def test_matching_demand_equals_the_brute_force_triple_predicate() -> None:
    rows = _fixture(seed=81, count=300)
    index = Nets.of(rows)
    for item in ("iron-ingot", "gear", "circuit", "absent"):
        for kind in ("input", "output"):
            for cell in ((0, 0, 0), (3, 4, 0), (7, 7, 0)):
                brute = tuple(
                    payload
                    for _i, it, kd, cl, _role, payload in rows
                    if it == item and kd == kind and cl == cell
                )
                assert index.matching_demand(item, kind, cell) == brute, (item, kind, cell)


def test_by_id_equals_the_net_by_id_dict_and_answers_none_when_absent() -> None:
    rows = _fixture(seed=82, count=100)
    index = Nets.of(rows)
    for net_id, _it, _kd, _cl, _role, payload in rows:
        assert index.by_id(net_id) == payload
    assert index.by_id(9999) is None


def test_in_role_equals_the_role_members_grouping_in_input_order() -> None:
    rows = _fixture(seed=83, count=200)
    index = Nets.of(rows)
    for role in ("producer", "consumer", "external", "absent"):
        brute = tuple(i for i, _it, _kd, _cl, r, _payload in rows if r == role)
        assert index.in_role(role) == brute, role


def test_an_empty_collection_answers_empty() -> None:
    index = Nets.of(())
    assert index.ids() == ()
    assert index.matching_demand("gear", "input", (0, 0, 0)) == ()
    assert index.in_role("producer") == ()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/indexed/test_nets.py -v`
Expected: FAIL — `ImportError: cannot import name 'Nets' from 'flab2bp.indexed'`.

- [ ] **Step 3: Write the implementation**

`src/flab2bp/indexed/nets.py`:

```python
"""Prepared routing nets, keyed by id, by role, and by demand signature.

Backend: littletable. Three key shapes over one collection -- `net_id`
(freeform.py:9425), `role` (:9372), and the `(item, kind, cell)` demand
signature (:12111-12129, :17317-17321) -- with three separately hand-built dicts
today. Ruling 2 forbids two backends for one collection, so one table with three
indexes is the answer rather than a fourth dict.

polars is refused because `_Net` carries nested endpoint tuples that do not
flatten into columns without losing what the callers read.

Order is input order in every accessor, matching the comprehensions replaced.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import littletable

from flab2bp.indexed._record import IndexRecord

Cell = tuple[int, int, int]


@dataclass
class _NetRecord(IndexRecord):
    net_id: int = -1
    role: str = ""
    signature: tuple[str, str, Cell] = ("", "", (0, 0, 0))
    position: int = -1


class Nets:
    """One pack attempt's prepared nets, answered by key instead of by scan."""

    def __init__(self, rows: Iterable[tuple[int, str, str, Cell, str, Any]]) -> None:
        table: littletable.Table = littletable.Table("nets")
        table.create_index("net_id", unique=True)
        table.create_index("role")
        table.create_index("signature")
        ids: list[int] = []
        for position, (net_id, item, kind, cell, role, payload) in enumerate(rows):
            table.insert(
                _NetRecord(
                    payload=payload,
                    net_id=net_id,
                    role=role,
                    signature=(item, kind, cell),
                    position=position,
                )
            )
            ids.append(net_id)
        self._table = table
        self._ids = tuple(ids)

    @classmethod
    def of(cls, rows: Iterable[tuple[int, str, str, Cell, str, Any]]) -> Nets:
        """Index one pack attempt's prepared nets."""
        return cls(rows)

    def ids(self) -> tuple[int, ...]:
        """Every net id, in preparation order."""
        return self._ids

    def by_id(self, net_id: int) -> Any | None:
        """The net with that id, or ``None``."""
        records = self._table.by.net_id[net_id]
        record = next(iter(records), None)
        return None if record is None else record.payload

    def matching_demand(self, item: str, kind: str, cell: Cell) -> tuple[Any, ...]:
        """Nets whose demand signature is exactly ``(item, kind, cell)``."""
        records = sorted(self._table.by.signature[(item, kind, cell)], key=lambda r: r.position)
        return tuple(record.payload for record in records)

    def in_role(self, role: str) -> tuple[int, ...]:
        """Net ids in one role, in preparation order."""
        records = sorted(self._table.by.role[role], key=lambda r: r.position)
        return tuple(record.net_id for record in records)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/indexed/test_nets.py -v`
Expected: PASS, all four tests.

If `create_index("net_id", unique=True)` raises on a duplicate id, the collection is not
id-unique — drop `unique=True`, keep `by_id` returning the first record in preparation order, and
note the finding in the final report.

- [ ] **Step 5: Lint, type-check, run the whole domain-type suite, commit**

```bash
uv run ruff check src/flab2bp/indexed tests/indexed
uv run mypy src/flab2bp/indexed
uv run pytest tests/indexed -v ; echo "exit=$?"
export GIT_EDITOR=true
git add src/flab2bp/indexed/nets.py src/flab2bp/indexed/__init__.py tests/indexed/test_nets.py
git commit -m "feat(indexed): add the Nets littletable index"
```

Expected: `tests/indexed` exits 0. That is the end of Phase 1 — every domain type exists and is
proven against a brute-force scan, with nothing in `src/flab2bp/` outside `indexed/` changed yet.

`BeltOverlap` is the one domain type without a Phase 1 task: it is created inside Task 12,
because its only sensible test fixture is the `previews` tuple that task's call sites already
build, and inventing a synthetic one first would prove less.

---

# Phase 2 — conversions, uncontended files first

## Task 11: `dsp/provenance.py` — sites #10, #11, #38

**Files:**
- Modify: `src/flab2bp/dsp/provenance.py:496-510` (`frozen_captures`),
  `:519-530` (`hardcoding_readers`), `:637-653` (`scan_source`)
- Test: `tests/dsp/test_provenance.py` (existing; add three tests)

**Interfaces:**
- Consumes: `ReferenceGraph.of`, `.reachable_from`, `.module_reach`, `.import_time_captures`,
  `.holders_of` (Task 2).
- Produces: no new public names. `frozen_captures()` and `hardcoding_readers()` keep their exact
  signatures and return types (`dict[str, tuple[str, ...]]`).

- [ ] **Step 1: Write the failing characterisation tests**

Append to `tests/dsp/test_provenance.py`:

```python
def test_frozen_captures_is_unchanged_by_the_index(monkeypatch) -> None:
    """The converted body answers exactly what the scan answered.

    provenance.py:507 rescanned every import-time node's reach ONCE PER
    REGISTRY RULE (~126 of them). The captured map is the same for every rule,
    so inverting it once is the same answer with one pass instead of 126.
    """
    from flab2bp.dsp import provenance

    g = provenance.build_graph()
    captured: dict[str, frozenset[str]] = {}
    for node, node_kind in g.kind.items():
        if node_kind not in {"const", "default"}:
            continue
        captured[node] = g.edges.get(node, frozenset()) | g.closure(
            g.calls.get(node, frozenset())
        )
    expected: dict[str, tuple[str, ...]] = {}
    for entry in provenance.registry.rules():
        node = entry.dotted
        holders = [n for n, reach in captured.items() if n != node and node in reach]
        if holders:
            expected[entry.symbol] = tuple(sorted(holders))
    assert provenance.frozen_captures(g) == expected


def test_hardcoding_readers_is_unchanged_by_the_hoist() -> None:
    """provenance.py:527 recomputed `closure(nodes_in(m))` inside the entry loop."""
    from flab2bp.dsp import provenance

    g = provenance.build_graph()
    modules = (*provenance.STRATEGY_MODULES, provenance.VALIDATE_MODULE)
    expected: dict[str, tuple[str, ...]] = {}
    for entry in provenance.registry.ENTRIES:
        if not entry.hardcodes:
            continue
        expected[entry.symbol] = tuple(
            sorted(m for m in modules if entry.dotted in g.closure(g.nodes_in(m)))
        )
    assert provenance.hardcoding_readers(g) == expected


def test_module_reach_is_computed_once_per_module_not_once_per_entry() -> None:
    """The hoist is the point; a counter proves it happened."""
    from flab2bp.dsp import provenance
    from flab2bp.indexed import ReferenceGraph

    calls: list[str] = []
    original = ReferenceGraph.reachable_from

    def counting(self, roots, *, block=()):  # type: ignore[no-untyped-def]
        calls.append("reach")
        return original(self, roots, block=block)

    ReferenceGraph.reachable_from = counting  # type: ignore[method-assign]
    try:
        provenance.hardcoding_readers(provenance.build_graph())
    finally:
        ReferenceGraph.reachable_from = original  # type: ignore[method-assign]
    modules = (*provenance.STRATEGY_MODULES, provenance.VALIDATE_MODULE)
    assert len(calls) <= len(modules)
```

- [ ] **Step 2: Run to verify the third test fails**

Run: `uv run pytest tests/dsp/test_provenance.py -k "frozen_captures_is_unchanged or hardcoding_readers_is_unchanged or module_reach_is_computed" -v`
Expected: the first two PASS (they characterise today's behaviour), the third FAILS with an
assertion on the call count — today `hardcoding_readers` calls `closure` once per
(entry, module) pair.

- [ ] **Step 3: Convert `frozen_captures`**

Replace `src/flab2bp/dsp/provenance.py:496-510` with:

```python
    index = ReferenceGraph.of(graph if graph is not None else build_graph())
    out: dict[str, tuple[str, ...]] = {}
    for entry in registry.rules():
        holders = index.holders_of(entry.dotted)
        if holders:
            out[entry.symbol] = holders
    return out
```

- [ ] **Step 4: Convert `hardcoding_readers`**

Replace `src/flab2bp/dsp/provenance.py:519-530` with:

```python
    index = ReferenceGraph.of(graph if graph is not None else build_graph())
    modules = (*STRATEGY_MODULES, VALIDATE_MODULE)
    # Hoisted out of the entry loop -- exactly what `consultation()` already
    # does at :429-430, and the one thing :527 did not.
    per_module_reach = index.module_reach(modules)
    out: dict[str, tuple[str, ...]] = {}
    for entry in registry.ENTRIES:
        if not entry.hardcodes:
            continue
        out[entry.symbol] = tuple(
            sorted(m for m in modules if entry.dotted in per_module_reach[m])
        )
    return out
```

Add the import at the top of `src/flab2bp/dsp/provenance.py`, in the first-party block:

```python
from flab2bp.indexed import ReferenceGraph
```

- [ ] **Step 5: Convert `scan_source`'s needle matching (site #38)**

At `src/flab2bp/dsp/provenance.py:637-653`, the literal hunt tests every AST float against every
needle with `math.isclose`. Bucket the needles by a rounded key so each literal probes three
buckets instead of the whole dict. Insert, immediately before the `ast.walk(tree)` loop:

```python
    # A float match is by tolerance, not equality, so an exact dict cannot
    # replace the scan -- but a rounded bucket can narrow it: a value within
    # `math.isclose`'s default relative tolerance of a needle rounds to that
    # needle's key or to one of its two neighbours.
    by_key: dict[int, list[tuple[str, float]]] = {}
    for name, value in hunted.items():
        by_key.setdefault(round(value * 1_000_000), []).append((name, value))
```

and replace the inner `for name, value in hunted.items():` loop body's candidate source with:

```python
        probe = round(literal * 1_000_000)
        candidates = (
            *by_key.get(probe - 1, ()),
            *by_key.get(probe, ()),
            *by_key.get(probe + 1, ()),
        )
        for name, value in candidates:
            if math.isclose(literal, value):
                ...
```

**If the existing lint test's output changes at all, revert this step alone and record it.** The
bucketing is a hygiene conversion (Ruling I-5) with no measured cost today; a lint verdict that
moves is not worth it. Keep steps 3 and 4.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/dsp/test_provenance.py -v ; echo "exit=$?"
uv run pytest tests/indexed/test_backend_containment.py -v
```
Expected: exit 0, and the containment guard still passes (`provenance.py` imports
`flab2bp.indexed`, not `networkx`).

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src scripts && uv run ruff format --check src scripts && uv run mypy src scripts
export GIT_EDITOR=true
git add src/flab2bp/dsp/provenance.py tests/dsp/test_provenance.py
git commit -m "perf(dsp): index the provenance reference graph instead of rewalking it"
```

---

## Task 12: `dsp/colliders.py` and the `BeltOverlap` index — site #22

**Files:**
- Create: `src/flab2bp/indexed/belt_overlap.py`
- Modify: `src/flab2bp/indexed/__init__.py`,
  `src/flab2bp/dsp/colliders.py:1742` (`_belt_overlap_candidates`),
  `:1798-1800` (`belt_collisions`), `:1901-1904` (`stable_belt_collisions`)
- Test: `tests/indexed/test_belt_overlap.py`, plus one test in `tests/dsp/test_colliders.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `BeltOverlap.for_previews(previews: tuple[Preview, ...]) -> BeltOverlap` — memoized on the
    identity of `previews`, so the two rules that ask on the same pass share one grid
  - `BeltOverlap.candidates(box: tuple[int, int, int, int]) -> tuple[int, ...]`
  - `BeltOverlap.clear_cache() -> None` — for tests only

- [ ] **Step 1: Write the failing tests**

Create `tests/indexed/test_belt_overlap.py`:

```python
"""One grid per previews tuple, shared by both rules that ask.

`belt_collisions` (colliders.py:1798-1800) and `stable_belt_collisions`
(:1901-1904) each build the overlap grid from the same frozen `previews`, and
both are reached from validate.py on the same `ctx` in one validation pass. The
`previews` tuple is frozen between those two calls -- `Preview` is
`@dataclass(frozen=True)` -- which is what makes memoizing on its identity safe.
"""

from __future__ import annotations

from flab2bp.indexed import BeltOverlap


def _boxes() -> tuple[tuple[int, int, int, int], ...]:
    return ((0, 0, 2, 2), (1, 1, 3, 3), (10, 10, 11, 11))


def test_candidates_equal_a_brute_force_overlap_scan() -> None:
    boxes = _boxes()
    index = BeltOverlap.of(boxes)
    for probe in ((0, 0, 1, 1), (2, 2, 4, 4), (10, 10, 10, 10), (50, 50, 51, 51)):
        brute = tuple(
            i
            for i, (x0, y0, x1, y1) in enumerate(boxes)
            if not (probe[2] < x0 or probe[0] > x1 or probe[3] < y0 or probe[1] > y1)
        )
        assert index.candidates(probe) == brute, probe


def test_for_previews_returns_the_same_index_for_the_same_tuple() -> None:
    BeltOverlap.clear_cache()
    previews = ("a", "b")
    first = BeltOverlap.for_previews(previews, lambda _p: _boxes())
    second = BeltOverlap.for_previews(previews, lambda _p: _boxes())
    assert first is second


def test_a_different_previews_tuple_gets_its_own_index() -> None:
    BeltOverlap.clear_cache()
    first = BeltOverlap.for_previews(("a",), lambda _p: _boxes())
    second = BeltOverlap.for_previews(("b",), lambda _p: _boxes())
    assert first is not second


def test_an_empty_box_list_answers_empty() -> None:
    assert BeltOverlap.of(()).candidates((0, 0, 1, 1)) == ()
```

Append to `tests/dsp/test_colliders.py`:

```python
def test_both_belt_collision_rules_build_the_overlap_grid_once() -> None:
    """The two rules that ask on one pass must share one grid, not build two."""
    from flab2bp.dsp import colliders
    from flab2bp.indexed import BeltOverlap

    BeltOverlap.clear_cache()
    builds: list[int] = []
    original = BeltOverlap.of

    def counting(boxes):  # type: ignore[no-untyped-def]
        builds.append(1)
        return original(boxes)

    BeltOverlap.of = staticmethod(counting)  # type: ignore[method-assign]
    try:
        previews = _previews_fixture()  # existing helper in this file
        colliders.belt_collisions(previews)
        colliders.stable_belt_collisions(previews)
    finally:
        BeltOverlap.of = original  # type: ignore[method-assign]
    assert len(builds) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/indexed/test_belt_overlap.py tests/dsp/test_colliders.py -v`
Expected: FAIL — `ImportError: cannot import name 'BeltOverlap'`.

If `_previews_fixture` does not exist in `tests/dsp/test_colliders.py`, build the fixture the way
the file's nearest existing belt-collision test does and name it `_previews_fixture`.

- [ ] **Step 3: Write `BeltOverlap`**

`src/flab2bp/indexed/belt_overlap.py`:

```python
"""A bucket grid over belt preview boxes, built once per previews tuple.

`belt_collisions` (dsp/colliders.py:1798-1800) and `stable_belt_collisions`
(:1901-1904) each build `grid`/`boxes` from scratch inside
`_belt_overlap_candidates` (:1742), and validate.py reaches both -- from
`game.belt_crossing` and `game.belt_collide` -- on the same `ctx` in one
validation pass. `previews` is frozen between them (`Preview` is
`@dataclass(frozen=True)`, held in a tuple), so one grid answers both.

Backend: a plain dict bucket grid. Ruling 2's plain-index clause: single-key
spatial lookup. littletable adds nothing to a bucket grid and polars cannot
express one.

The cache is keyed on `id(previews)` AND holds a reference to the tuple, so the
id cannot be recycled underneath it while an entry is live. It is bounded to the
two most recent tuples, which is the pass structure: one `ctx`, two rules.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

_BUCKET = 8

Box = tuple[int, int, int, int]


class BeltOverlap:
    """Which preview boxes could overlap a probe box."""

    __slots__ = ("_boxes", "_grid")

    _cache: dict[int, tuple[Any, BeltOverlap]] = {}

    def __init__(self, boxes: Sequence[Box]) -> None:
        self._boxes = tuple(boxes)
        grid: dict[tuple[int, int], list[int]] = {}
        for index, (x0, y0, x1, y1) in enumerate(self._boxes):
            for bx in range(x0 // _BUCKET, x1 // _BUCKET + 1):
                for by in range(y0 // _BUCKET, y1 // _BUCKET + 1):
                    grid.setdefault((bx, by), []).append(index)
        self._grid = grid

    @staticmethod
    def of(boxes: Sequence[Box]) -> BeltOverlap:
        """Index one list of boxes."""
        return BeltOverlap(boxes)

    @classmethod
    def for_previews(
        cls,
        previews: Any,
        boxes_of: Callable[[Any], Sequence[Box]],
    ) -> BeltOverlap:
        """The index for one previews tuple, built at most once per tuple."""
        key = id(previews)
        hit = cls._cache.get(key)
        if hit is not None and hit[0] is previews:
            return hit[1]
        index = cls.of(boxes_of(previews))
        if len(cls._cache) >= 2:
            cls._cache.pop(next(iter(cls._cache)))
        cls._cache[key] = (previews, index)
        return index

    @classmethod
    def clear_cache(cls) -> None:
        """Drop every memoized index. Tests only."""
        cls._cache.clear()

    def candidates(self, box: Box) -> tuple[int, ...]:
        """Box indices whose rectangle intersects ``box``, ascending."""
        px0, py0, px1, py1 = box
        seen: set[int] = set()
        for bx in range(px0 // _BUCKET, px1 // _BUCKET + 1):
            for by in range(py0 // _BUCKET, py1 // _BUCKET + 1):
                seen.update(self._grid.get((bx, by), ()))
        boxes = self._boxes
        return tuple(
            index
            for index in sorted(seen)
            if not (
                px1 < boxes[index][0]
                or px0 > boxes[index][2]
                or py1 < boxes[index][1]
                or py0 > boxes[index][3]
            )
        )
```

- [ ] **Step 4: Route both rules through it**

In `src/flab2bp/dsp/colliders.py`, change `_belt_overlap_candidates` (`:1742`) to obtain its grid
from `BeltOverlap.for_previews(previews, _belt_boxes)` where `_belt_boxes(previews)` is the
existing box-building expression lifted into a module-level function, and delete the per-call
`grid`/`boxes` construction. Both `belt_collisions` (`:1798-1800`) and `stable_belt_collisions`
(`:1901-1904`) keep their signatures unchanged.

Add at the top of `src/flab2bp/dsp/colliders.py`:

```python
from flab2bp.indexed import BeltOverlap
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/indexed/test_belt_overlap.py tests/dsp/test_colliders.py -v ; echo "exit=$?"
uv run pytest tests/layout/test_validate.py -v ; echo "exit=$?"
```
Expected: both exit 0. The validate suite matters here because `game.belt_crossing` and
`game.belt_collide` are its rules, and a shared grid that answered differently would show there.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/indexed/belt_overlap.py src/flab2bp/indexed/__init__.py src/flab2bp/dsp/colliders.py tests/indexed/test_belt_overlap.py tests/dsp/test_colliders.py
git commit -m "perf(dsp): share one belt-overlap grid between both belt collision rules"
```

---

## Task 13: `dsp` band lookup — site #39

**Files:**
- Modify: `src/flab2bp/dsp/planet.py` (add `bands_by_segment`),
  `src/flab2bp/dsp/codec.py:239-246` (`_area_for`),
  `src/flab2bp/dsp/splitter_ports.py:248-255` (`blueprint_port_anchor`)
- Test: `tests/dsp/test_planet.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `flab2bp.dsp.planet.bands_by_segment() -> Mapping[int, Band]`, `@cache`d alongside
  the existing `bands()` (`@lru_cache(maxsize=8)`).

- [ ] **Step 1: Write the failing test**

Append to `tests/dsp/test_planet.py`:

```python
def test_bands_by_segment_equals_the_next_over_bands_scan() -> None:
    """The `next(... if candidate.area_segments == X)` scan, keyed.

    dsp/codec.py:239-246 and dsp/splitter_ports.py:248-255 both linear-scan the
    cached `bands()` tuple for a band by `area_segments`, and the pattern recurs
    at 6+ sites. `catalog._recipe_ids()` is the model: build the map once.
    """
    from flab2bp.dsp import planet

    by_segment = planet.bands_by_segment()
    for band in planet.bands():
        assert by_segment[band.area_segments] is band
    assert set(by_segment) == {b.area_segments for b in planet.bands()}


def test_bands_by_segment_is_built_once() -> None:
    from flab2bp.dsp import planet

    assert planet.bands_by_segment() is planet.bands_by_segment()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/dsp/test_planet.py -k bands_by_segment -v`
Expected: FAIL — `AttributeError: module 'flab2bp.dsp.planet' has no attribute 'bands_by_segment'`.

- [ ] **Step 3: Add the index**

In `src/flab2bp/dsp/planet.py`, immediately after `bands()`:

```python
@cache
def bands_by_segment() -> Mapping[int, Band]:
    """Band by ``area_segments``, so the six `next()` scans become lookups.

    `bands()` is small and `@lru_cache`d, so this is a duplication fix rather
    than a hot-path fix -- but the scan is reimplemented at six sites and one of
    them is on the emission path, which is what puts it in scope.
    """
    return MappingProxyType({band.area_segments: band for band in bands()})
```

Add `from types import MappingProxyType` and `from collections.abc import Mapping` to the
imports if they are not already there.

- [ ] **Step 4: Convert both call sites**

`src/flab2bp/dsp/codec.py:239-246` — replace the `next(candidate for candidate in
planet.bands() if candidate.area_segments == ...)` expression with
`planet.bands_by_segment()[...]`, keeping the surrounding error handling: where the old
expression could raise `StopIteration`, the new one raises `KeyError`, so wrap it in the same
`try`/`except` shape the site already uses and raise the same domain error with the same message.

`src/flab2bp/dsp/splitter_ports.py:248-255` — same change, same error-shape rule.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/dsp -v ; echo "exit=$?"
```
Expected: exit 0.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/dsp/planet.py src/flab2bp/dsp/codec.py src/flab2bp/dsp/splitter_ports.py tests/dsp/test_planet.py
git commit -m "perf(dsp): key bands by area_segments instead of scanning bands()"
```

---

## Task 14: `layout/global_router.py` — sites #5 and #36

**Files:**
- Modify: `src/flab2bp/layout/global_router.py:68-107` (`_CapacityLedger`),
  `:395-408` (`_route_ends`)
- Test: `tests/layout/test_global_router.py`

**Interfaces:**
- Consumes: nothing new — this task adds no domain type. `_CapacityLedger` is already the domain
  type for its collection; the change is inside it.
- Produces: `_CapacityLedger.present_cost` and `.occupy` keep their exact signatures
  (`(index: int, compatible: frozenset[NetId]) -> int` and
  `(index: int, net_id: NetId, compatible: frozenset[NetId]) -> int`).

**Why no new type:** the scout (#5) proposed "a running 'fully shared' boolean maintained by
`occupy()`". That is wrong — `present_cost(index, compatible)` decides sharing against the
**caller's** `compatible` set, which differs per net, and `occupy` cannot know a future querier's
set. The cost that *can* be removed is the Python-level membership loop: replace
`all(owner in compatible for owner in unit)` with a frozenset subset test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_global_router.py`:

```python
def test_present_cost_is_unchanged_by_the_frozenset_units() -> None:
    """Same answers, cheaper test. The scan is per A* node expansion."""
    import random

    from flab2bp.layout.global_router import _CapacityLedger

    rng = random.Random(91)
    ledger = _CapacityLedger(size=64)
    history: list[tuple[int, int, frozenset[int]]] = []
    for _ in range(400):
        index = rng.randrange(64)
        net_id = rng.randrange(8)
        compatible = frozenset(rng.sample(range(8), rng.randrange(1, 5)))
        ledger.occupy(index, net_id, compatible)
        history.append((index, net_id, compatible))
    for index, _net, compatible in history:
        units = ledger.units.get(index)
        assert units is not None
        shares = any(all(owner in compatible for owner in unit) for unit in units)
        expected = max(0, len(units) - 1) if shares else len(units)
        assert ledger.present_cost(index, compatible) == expected, index


def test_occupy_returns_the_same_delta_as_before() -> None:
    from flab2bp.layout.global_router import _CapacityLedger

    ledger = _CapacityLedger(size=4)
    assert ledger.occupy(0, 1, frozenset({1})) == 0
    assert ledger.occupy(0, 2, frozenset({9})) == 1
    assert ledger.occupy(0, 3, frozenset({1, 2, 3})) == 0


def test_route_ends_finds_the_same_reserved_port_by_owner() -> None:
    """`grid.reserved` was scanned linearly for `owner == destination` (:395-408)."""
    from flab2bp.layout.global_router import _reserved_by_owner

    reserved = (((1, 1), "a"), ((2, 2), "b"), ((3, 3), "a"))
    index = _reserved_by_owner(reserved)
    for owner in ("a", "b", "c"):
        expected = next((at for at, who in reserved if who == owner), None)
        assert index.get(owner) == expected, owner
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/layout/test_global_router.py -k "frozenset_units or same_delta or reserved_port" -v`
Expected: the first two PASS (they characterise today), the third FAILS —
`ImportError: cannot import name '_reserved_by_owner'`.

- [ ] **Step 3: Convert `_CapacityLedger`**

Replace `src/flab2bp/layout/global_router.py:68-107` with:

```python
@dataclass(slots=True)
class _CapacityLedger:
    """Integer occupancy plus the prepared sibling unit using each cell.

    `present_cost` is asked once per A* NODE EXPANSION -- thousands per net
    search, times nets, times rounds, times packing candidates -- so the shape
    of its innermost test is worth more than its asymptotics. Each unit's owners
    are held as a `frozenset` so "does this unit share with the caller" is one
    subset test in C rather than a Python generator over the unit.

    NOT a cached boolean: sharing is decided against the CALLER's `compatible`
    set, which differs per net, so `occupy` cannot precompute the answer a later
    `present_cost` needs.
    """

    size: int
    occupancy: list[int] = field(init=False)
    units: dict[int, list[frozenset[NetId]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.occupancy = [0] * self.size

    def present_cost(self, index: int, compatible: frozenset[NetId]) -> int:
        units = self.units.get(index)
        if units is None:
            return 0
        shares = any(unit <= compatible for unit in units)
        return max(0, len(units) - 1) if shares else len(units)

    def occupy(
        self,
        index: int,
        net_id: NetId,
        compatible: frozenset[NetId],
    ) -> int:
        units = self.units.get(index)
        before = max(0, self.occupancy[index] - 1)
        if units is None:
            self.units[index] = [frozenset({net_id})]
            self.occupancy[index] = 1
        else:
            position = next(
                (i for i, unit in enumerate(units) if unit <= compatible),
                None,
            )
            if position is None:
                units.append(frozenset({net_id}))
                self.occupancy[index] += 1
            else:
                units[position] = units[position] | {net_id}
        return max(0, self.occupancy[index] - 1) - before
```

**The first-match rule is load-bearing.** The original `occupy` merged into the FIRST unit whose
owners are all compatible (`next((unit for unit in units if ...), None)` at `:98-101`); the
replacement keeps that by taking the first index. A different unit means a different shared
group means a different route.

- [ ] **Step 4: Convert `_route_ends`**

Add above `_route_ends` in `src/flab2bp/layout/global_router.py`:

```python
def _reserved_by_owner(
    reserved: Sequence[tuple[Cell, object]],
) -> dict[object, Cell]:
    """Owner -> its FIRST reserved cell, matching the `next()` scan at :395-408.

    First wins, because the scan it replaces stopped at the first hit and a
    later duplicate never reached the caller.
    """
    out: dict[object, Cell] = {}
    for at, owner in reserved:
        out.setdefault(owner, at)
    return out
```

and in `_route_ends` build it once before the net loop, replacing the per-net
`next((at for at, owner in grid.reserved if owner == destination), None)` with
`reserved_by_owner.get(destination)`.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/layout/test_global_router.py -v ; echo "exit=$?"
uv run pytest tests/layout -k "route or freeform" ; echo "exit=$?"
```
Expected: exit 0 for the first; for the second, exit 0 or exit 1 with only the two known reds.

- [ ] **Step 6: Prove the router did not move — `route_bench` digest**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
uv run python scripts/route_bench.py --cases docs/superpowers/evidence/2026-09-07-indexed-scans/route-cases.pkl --check
```
Expected: the digest line ends `MATCH`. If the capture file does not exist yet, create it first
with `uv run python scripts/route_bench.py --capture universe-matrix --budget 4 --cases
docs/superpowers/evidence/2026-09-07-indexed-scans/route-cases.pkl` **from a checkout of
`master@2e861af0`**, commit it, and only then run `--check` from this branch. A capture taken on
this branch proves nothing.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/global_router.py tests/layout/test_global_router.py docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "perf(router): frozenset capacity units and an owner-keyed reserved index"
```

---

## Task 15: `lab/` — sites #15, #16 (partial), #17, #41

**Files:**
- Modify: `src/flab2bp/lab/flow.py:442-470` (`FlowSelection`, `by_item`, `by_recipe`),
  `:529-563` (`external_items`), `src/flab2bp/lab/data.py:229-231` (`load_vendored`),
  `src/flab2bp/lab/techs.py:65-154` (`logistics_tiers_for_request`)
- Test: `tests/lab/test_flow.py`, `tests/lab/test_data.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `FlowSelection.by_item` and `.by_recipe` keep their exact types
  (`Mapping[str, FlowRow]`) and become built-once fields rather than rebuilt-per-access
  properties. `load_vendored()` keeps its signature and gains `@cache`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lab/test_flow.py`:

```python
def test_by_item_is_built_once_rather_than_per_access() -> None:
    """`by_item` was a plain @property rebuilding `{r.item_id: r ...}` per read.

    `_rate_findings` (lab/flow.py:1065) reads it once per item inside its
    finding loop, so a 100-row flow rebuilt the map once per finding.

    NOTE: `functools.cached_property` CANNOT be used here. `FlowSelection` is
    `@dataclass(frozen=True, slots=True)` (lab/flow.py:442-443) and a slotted
    class has no `__dict__` for `cached_property` to write into -- it raises
    `TypeError: No '__dict__' attribute on 'FlowSelection'`.
    """
    selection = _selection_fixture()  # existing helper in this file
    assert selection.by_item is selection.by_item
    assert selection.by_recipe is selection.by_recipe


def test_by_item_and_by_recipe_answer_exactly_what_the_comprehensions_did() -> None:
    selection = _selection_fixture()
    assert dict(selection.by_item) == {r.item_id: r for r in selection.rows if r.item_id}
    assert dict(selection.by_recipe) == {r.recipe_id: r for r in selection.rows if r.recipe_id}


def test_the_maps_cannot_be_mutated_through_the_public_attribute() -> None:
    selection = _selection_fixture()
    try:
        selection.by_item["invented"] = next(iter(selection.by_item.values()))
    except TypeError:
        return
    raise AssertionError("by_item must be read-only; a caller mutation would be shared state")
```

Append to `tests/lab/test_data.py`:

```python
def test_load_vendored_parses_the_dataset_once() -> None:
    """bench/runner.py calls it twice per corpus URL (specs_for, belt_rules_for_url).

    Twelve URLs meant 24 full re-reads and re-parses of an unchanged file, plus
    24 rebuilds of `Dataset.__post_init__`'s indexes.
    """
    from flab2bp.lab import data

    data.load_vendored.cache_clear()
    assert data.load_vendored() is data.load_vendored()
    assert data.load_vendored.cache_info().hits == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/lab/test_flow.py tests/lab/test_data.py -k "built_once or read_only or parses_the_dataset_once" -v`
Expected: FAIL — `by_item` returns a new dict per access, and `load_vendored` has no
`cache_clear`.

- [ ] **Step 3: Convert `FlowSelection`**

In `src/flab2bp/lab/flow.py`, add two `init=False` fields to the dataclass body (they must be
declared so `slots=True` allocates them) and populate them in `__post_init__` with
`object.__setattr__`, which is the only way to write a frozen slotted dataclass:

```python
    #: Built once in `__post_init__`, not per access: `_rate_findings` reads
    #: `by_item` once per item inside its finding loop (lab/flow.py:1065) and a
    #: plain @property rebuilt the whole map every time. `cached_property` is
    #: unavailable -- `slots=True` leaves no `__dict__` for it to write into.
    by_item: Mapping[str, FlowRow] = field(init=False, repr=False, compare=False)
    by_recipe: Mapping[str, FlowRow] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "by_item",
            MappingProxyType({r.item_id: r for r in self.rows if r.item_id}),
        )
        object.__setattr__(
            self,
            "by_recipe",
            MappingProxyType({r.recipe_id: r for r in self.rows if r.recipe_id}),
        )
```

Delete the two `@property` definitions at `lab/flow.py:464-470`. `MappingProxyType` is already
imported at `lab/flow.py:99`; add `field` to the `dataclasses` import at `:96`.

If `FlowSelection` already has a `__post_init__`, extend it rather than adding a second.

- [ ] **Step 4: Convert `load_vendored`**

`src/flab2bp/lab/data.py:229-231`:

```python
@cache
def load_vendored() -> Dataset:
    """Load the in-repo copy directly, bypassing cache and network.

    `@cache`d because `bench/runner.py` calls it TWICE per corpus URL --
    `specs_for` (:164) and `belt_rules_for_url` (:199) -- so a 12-URL run
    re-read and re-parsed an unchanged `data.json` 24 times and rebuilt
    `Dataset.__post_init__`'s indexes 24 times. `Dataset` is
    `@dataclass(frozen=True, slots=True)`, so sharing one instance is safe.
    """
    return Dataset.parse(_parse_json((VENDORED_DIR / "data.json").read_text(encoding="utf-8")))
```

Add `from functools import cache` to the imports.

- [ ] **Step 5: Convert `logistics_tiers_for_request` (site #41)**

`src/flab2bp/lab/techs.py:65-154` makes three independent full passes over `dataset.items` for
three predicates. Merge them into one pass that accumulates all three results:

```python
    technologies: list[Item] = []
    belts: list[Item] = []
    sorters: list[Item] = []
    for item in dataset.items:
        if item.technology:
            technologies.append(item)
        if item.belt:
            belts.append(item)
        if item.id in SORTER_RATE_AT_1:
            sorters.append(item)
```

then use those three lists where the three comprehensions were. **Keep the original predicate
expressions byte-for-byte** — copy them from the three comprehensions rather than retyping — and
keep the result order, which is `dataset.items` order in all three.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/lab -v ; echo "exit=$?"
uv run pytest tests/ -k "pipeline or bench" ; echo "exit=$?"
```
Expected: exit 0 for the first; exit 0 or the two known reds for the second.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run ruff format --check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/lab/flow.py src/flab2bp/lab/data.py src/flab2bp/lab/techs.py tests/lab
git commit -m "perf(lab): build flow maps once, cache the vendored dataset, fuse the tech passes"
```

---

## Task 16: `bench/` — sites #40, #43, and the four-way "best per url" duplication

**Files:**
- Modify: `src/flab2bp/bench/scoring.py:70-79` (`_best_per_url`),
  `src/flab2bp/bench/report.py:44-52` (`_best`) and `:145-152` (`_winning_candidates`),
  `src/flab2bp/bench/regression.py:65-72` (`_best_per_url`),
  `src/flab2bp/bench/ab.py:544-630` (`Cell` properties) and `:703-778` (`Comparison` properties),
  `src/flab2bp/bench/promotion.py:155-192` (`_scope_reasons`)
- Test: `tests/bench/test_scoring.py`, `tests/bench/test_report.py`, `tests/bench/test_ab.py`

**Interfaces:**
- Consumes: `Cells.of`, `.best_per_url`, `.for_url`, `.url_ids` (Task 4).
- Produces: `_best_per_url` / `_best` / `_winning_candidates` keep their exact signatures and
  return types; `bench/report.py` no longer defines `_best` (it calls the shared one).

- [ ] **Step 1: Write the failing tests**

Append to `tests/bench/test_scoring.py`:

```python
def test_one_best_per_url_implementation_serves_every_reader() -> None:
    """Four copies of the same reduction, all reached in one render pass.

    bench/scoring.py:70-79, bench/report.py:44-52 (identical body),
    bench/report.py:145-152 (inline), bench/regression.py:65-72 (different rank
    key). This is a HYGIENE conversion kept under Ruling I-5 because it removes
    three re-implementations, not because it is faster.
    """
    import inspect

    from flab2bp.bench import regression, report, scoring

    assert not hasattr(report, "_best"), "report._best must be gone, not shadowed"
    assert "Cells" in inspect.getsource(scoring._best_per_url)
    assert "Cells" in inspect.getsource(regression._best_per_url)


def test_best_per_url_answers_exactly_what_it_did_before() -> None:
    from flab2bp.bench.scoring import _best_per_url

    cells = _cells_fixture()  # existing helper in this file
    for strategy in {c.strategy for c in cells}:
        expected = {}
        for cell in cells:
            if cell.strategy != strategy or not cell.valid:
                continue
            current = expected.get(cell.url_id)
            if current is None or cell.area < current.area:
                expected[cell.url_id] = cell
        assert _best_per_url(cells, strategy) == expected
```

Append to `tests/bench/test_ab.py`:

```python
def test_cell_derived_properties_are_computed_once(monkeypatch) -> None:
    """`relative_spread` re-derived `areas` three times through chained properties,
    and `Comparison.wins` -> `separated` -> `comparable` was three nested
    uncached O(pairs) scans, all touched by one `headline()`."""
    from flab2bp.bench.ab import Cell

    cell = _cell_fixture()  # existing helper in this file
    assert cell.areas is cell.areas


def test_comparison_comparable_is_computed_once() -> None:
    from flab2bp.bench.ab import Comparison

    comparison = _comparison_fixture()  # existing helper in this file
    assert comparison.comparable is comparison.comparable
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/bench -k "one_best_per_url or computed_once" -v`
Expected: FAIL — `report._best` still exists and the properties re-derive.

- [ ] **Step 3: Collapse the four reductions onto `Cells`**

`src/flab2bp/bench/scoring.py:70-79`:

```python
def _best_per_url(cells: Sequence[CellResult], strategy: str) -> dict[str, CellResult]:
    """The best valid candidate per URL, which is what the pipeline would ship."""
    return Cells.of(cells).best_per_url(strategy=strategy)
```

`src/flab2bp/bench/regression.py:65-72`:

```python
def _best_per_url(cells: Sequence[CellResult]) -> dict[str, CellResult]:
    """The result the pipeline would actually ship for each URL."""
    return Cells.of(cells).best_per_url(valid_only=False, rank=_rank)
```

`src/flab2bp/bench/report.py` — **delete** `_best` (`:44-52`) entirely and import the shared one:

```python
from flab2bp.bench.scoring import _best_per_url
```

then replace every `_best(...)` call with `_best_per_url(...)`, and replace the inline reduction
at `:145-152` in `_winning_candidates` with a call to the same function. Where `_winning_candidates`
needs the *candidate* rather than the cell, read `.candidate` off the returned cell.

Add `from flab2bp.indexed import Cells` to `scoring.py` and `regression.py`.

- [ ] **Step 4: Cache the derived `bench/ab.py` properties**

`Cell` and `Comparison` are `@dataclass(frozen=True, slots=True)`, so `functools.cached_property`
is unavailable for the same reason as `FlowSelection` in Task 15. Use the same pattern: declare
`areas` and `comparable` as `field(init=False, repr=False, compare=False)` and populate them in
`__post_init__` through `object.__setattr__`, then have `median_area`, `lo`, `hi`,
`relative_spread`, `covered`, `separated` and `wins` read the stored values instead of
re-deriving.

- [ ] **Step 5: Group `promotion._scope_reasons` rows by trial once (site #43)**

`src/flab2bp/bench/promotion.py:155-192` re-filters `rows` by `sample.trial` inside the nested
key×trial loop even though `by_cell` was already grouped at `:157-159`. Add, immediately after
the `by_cell` build:

```python
    by_trial: dict[tuple[str, int], list[Sample]] = {}
    for cell_key, cell_rows in by_cell.items():
        for sample in cell_rows:
            by_trial.setdefault((cell_key, sample.trial), []).append(sample)
```

and replace the inner `[s for s in rows if s.trial == trial]` with
`by_trial.get((cell_key, trial), [])`.

- [ ] **Step 6: Run the tests and record the polars decision number**

```bash
uv run pytest tests/bench -v ; echo "exit=$?"
uv run python - <<'PY' | tee docs/superpowers/evidence/2026-09-07-indexed-scans/bench-cells-build-cost.txt
import time
from flab2bp.indexed import Cells
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class C:
    url_id: str; strategy: str; candidate: str; valid: bool; area: int

cells = [C(f"u{i%12}", "freeform", "default", True, 100+i) for i in range(72)]
t = time.perf_counter()
for _ in range(1000):
    Cells.of(cells).best_per_url(strategy="freeform")
print("Cells.of + best_per_url, 72 rows, 1000x:", time.perf_counter()-t, "s")
PY
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}' \
  >> docs/superpowers/evidence/2026-09-07-indexed-scans/bench-cells-build-cost.txt
```
Expected: exit 0. The recorded number is the evidence behind Ruling I-3 for this collection: a
72-row reduction costs microseconds, so polars' per-call overhead cannot pay for itself here.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/bench tests/bench docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "refactor(bench): one best-per-url reduction and built-once derived properties"
```

---

## Task 17: `web/trace.py` — site #42

**Files:**
- Modify: `src/flab2bp/web/trace.py:147-163` (`TraceRing.since`)
- Test: `tests/web/test_trace.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `TraceRing.since` keeps its exact signature and return type.

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_trace.py`:

```python
def test_since_equals_the_linear_filter_for_every_cursor() -> None:
    """`since` linearly filtered a 256-frame ring on every HTTP poll, and a live
    viewer polls every ~100ms for the life of a job. `seq` is monotonic in
    append order, so `bisect` answers in O(log 256 + page)."""
    ring = _ring_fixture(frames=256)  # existing helper in this file
    frames = list(ring._frames)
    for cursor in (-1, 0, 1, 7, 128, 255, 256, 10_000):
        expected = [f for f in frames if f["seq"] > cursor]
        assert list(ring.since(cursor)) == expected, cursor


def test_since_is_correct_on_an_empty_ring() -> None:
    ring = _ring_fixture(frames=0)
    assert list(ring.since(0)) == []
```

- [ ] **Step 2: Run to verify the first passes and characterises today**

Run: `uv run pytest tests/web/test_trace.py -k since -v`
Expected: PASS — these characterise current behaviour; they are the guard for the rewrite.

If `_ring_fixture` does not exist, write it: construct a `TraceRing` and append `frames` dicts
with `seq` running from 1 upward, matching what the collector thread appends.

- [ ] **Step 3: Convert to a bisect**

Replace the linear filter in `src/flab2bp/web/trace.py:147-163` with:

```python
        with self._lock:
            frames = list(self._frames)
        # `seq` is assigned in append order and the deque preserves it, so the
        # copied list is sorted on `seq` and the first frame past the cursor is
        # a binary search rather than a scan of all 256.
        start = bisect.bisect_right([frame["seq"] for frame in frames], cursor)
        return frames[start:]
```

Add `import bisect` to the imports.

**Keep the copy-under-lock exactly where it is.** The deque is appended by the collector thread
concurrently; moving the bisect inside or outside the lock differently from the copy would be a
race, not an optimisation.

- [ ] **Step 4: Run to verify it still passes**

Run: `uv run pytest tests/web -v ; echo "exit=$?"`
Expected: exit 0.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/web/trace.py tests/web/test_trace.py
git commit -m "perf(web): bisect the trace ring instead of filtering it linearly"
```

---

## Task 18: `scripts/` — sites #44, #45, #46, #47, #48, #49 and the `URL_CORPUS` lookup

**Files:**
- Modify: `scripts/measure_geometry_cache_working_sets.py:134-145`, `:259-278`, `:304-325`;
  `scripts/route_profile.py:660-696`; `scripts/route_bench.py:189-260`, `:267-277`, `:101`, `:202`;
  `scripts/last_mile_bench.py:142-144`; `scripts/audit.py:884-885`;
  `scripts/spawn_cost.py:83`; `scripts/trace_overhead.py:136-138`
- Test: `tests/scripts/test_bench_scripts.py` (create if absent)

**Interfaces:**
- Consumes: nothing new.
- Produces: `flab2bp.bench.corpus.entry_for(url_id: str) -> CorpusEntry` — the single keyed
  `URL_CORPUS` lookup that five scripts currently re-implement with `next(...)`. Placed in the
  module that already owns `URL_CORPUS`.

This is the batched trivial-conversion task the brief asks for. Every row is a benchmark or CLI
tool, none is on the build path, and all are hygiene conversions under Ruling I-5.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_bench_scripts.py`:

```python
"""The benchmark tools' repeated reductions, done in one pass each."""

from __future__ import annotations

from collections import Counter


def test_entry_for_equals_the_next_over_url_corpus_scan() -> None:
    """Five scripts reimplement `next(e for e in URL_CORPUS if e.url_id == x)`:
    route_bench.py:101, route_bench.py:202, route_profile.py:94,
    spawn_cost.py:83, trace_overhead.py:136-138."""
    import pytest

    from flab2bp.bench.corpus import URL_CORPUS, entry_for

    for entry in URL_CORPUS:
        assert entry_for(entry.url_id) is entry
    with pytest.raises(KeyError):
        entry_for("no-such-url-id")


def test_route_bench_capture_counts_match_a_counter() -> None:
    """route_bench.py:267-277 did `list.count(v)` per distinct value: O(K*N)."""
    from scripts.route_bench import _tally

    outcomes = ["a", "b", "a", "c", "a", "b"]
    assert _tally(outcomes) == dict(Counter(outcomes))


def test_audit_expired_strategy_counts_match_a_counter() -> None:
    """audit.py:884-885 re-summed `jobs[done:]` once per strategy name."""
    from scripts.audit import _strategy_counts

    class Job:
        def __init__(self, strategy: str) -> None:
            self.strategy = strategy

    jobs = [Job("freeform"), Job("sequence-pair"), Job("freeform")]
    assert _strategy_counts(jobs, ("freeform", "sequence-pair", "best")) == {
        "freeform": 2,
        "sequence-pair": 1,
        "best": 0,
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/scripts/test_bench_scripts.py -v`
Expected: FAIL — `entry_for`, `_tally` and `_strategy_counts` do not exist.

- [ ] **Step 3: Add `entry_for` and convert the five call sites**

In the module that defines `URL_CORPUS` (find it with
`grep -rn --include='*.py' 'URL_CORPUS *=' src/`):

```python
@cache
def _by_url_id() -> Mapping[str, CorpusEntry]:
    return MappingProxyType({entry.url_id: entry for entry in URL_CORPUS})


def entry_for(url_id: str) -> CorpusEntry:
    """The corpus entry with that id.

    Five scripts reimplemented this as `next(e for e in URL_CORPUS if ...)`;
    `URL_CORPUS` is a frozen 12-entry tuple, so this is a duplication fix, not a
    speed fix -- but an unknown id now raises `KeyError` with the id in the
    message instead of `StopIteration` with nothing.
    """
    return _by_url_id()[url_id]
```

Replace the `next(...)` expression at `scripts/route_bench.py:101` and `:202`,
`scripts/route_profile.py:94`, `scripts/spawn_cost.py:83`, and
`scripts/trace_overhead.py:136-138` with `entry_for(url_id)`. Where a site caught
`StopIteration`, catch `KeyError` instead and keep its message.

- [ ] **Step 4: Convert the single-pass reductions**

`scripts/route_bench.py:267-277` — extract the counting into a helper and use `Counter`:

```python
def _tally(values: Sequence[str]) -> dict[str, int]:
    """One pass instead of `list.count(v)` per distinct value (O(K*N))."""
    return dict(Counter(values))
```

then use `_tally(outcomes)` and `_tally(bounds_hit)`.

`scripts/route_bench.py:189-260` — change `pending` from a `list` drained with `.pop(0)` (O(n)
per pop) to a `collections.deque` drained with `.popleft()`. Nothing else moves.

`scripts/audit.py:884-885` — extract:

```python
def _strategy_counts(jobs: Sequence[Job], names: Sequence[str]) -> dict[str, int]:
    """One pass over the unreached jobs instead of one `sum(...)` per name."""
    counted = Counter(job.strategy for job in jobs)
    return {name: counted.get(name, 0) for name in names}
```

and call it once on the expired path.

`scripts/last_mile_bench.py:142-144` — replace the four separate O(N) passes over `replayable`
with one loop accumulating `sizes`, `truncated`, `runs[1]` and `runs[2]` together.

`scripts/route_profile.py:660-696` — replace the three `sorted()` calls over overlapping data
with one pass computing the count and sums, plus `heapq.nsmallest`/`heapq.nlargest` for the
top-ten lists. **Keep the tie order:** `sorted` is stable, so pass the same key function to
`nsmallest`/`nlargest` and, where the report prints ties, verify the printed block is unchanged
against a `master` run before committing.

`scripts/measure_geometry_cache_working_sets.py` — build `combined` once in `_function_report`
(`:259-278`) and pass it into `recommended_maxsize` (`:134-145`) and `_add_timings` (`:304-325`)
as a parameter, instead of each rebuilding it. Three rebuilds become one.

- [ ] **Step 5: Run the tests and the scripts themselves**

```bash
uv run pytest tests/scripts -v ; echo "exit=$?"
uv run python scripts/route_bench.py --cases docs/superpowers/evidence/2026-09-07-indexed-scans/route-cases.pkl --check
uv run python scripts/last_mile_bench.py --help
uv run python scripts/measure_geometry_cache_working_sets.py --help
```
Expected: tests exit 0; the route_bench digest still ends `MATCH`; both `--help` invocations exit
0 (a syntax or signature error in a script shows up here and nowhere else, because these have no
test coverage).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check scripts src && uv run mypy scripts src
export GIT_EDITOR=true
git add scripts src/flab2bp/bench tests/scripts
git commit -m "refactor(scripts): key the corpus lookup and single-pass the bench reductions"
```

---

## Task 19: `layout/last_mile.py` and `layout/route_feedback.py` — sites #18, #34

**Files:**
- Modify: `src/flab2bp/layout/last_mile.py:132-152` (`_distance_to_stranded`) and
  `:257-280` (`build_cluster`); `src/flab2bp/layout/route_feedback.py:640-707`
  (`select_lns_neighbourhood`) and `:747-757` (`_sequence_neighbours`)
- Test: `tests/layout/test_last_mile.py`, `tests/layout/test_route_feedback.py`

**Interfaces:**
- Consumes: `StripPositions.of`, `.position_of` (Task 6).
- Produces: `last_mile._seed_distance_field(seeds, endpoints) -> dict[Cell, int]` — the BFS
  distance transform that replaces the per-candidate walk. `select_lns_neighbourhood` and
  `_distance_to_stranded` keep their signatures.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_last_mile.py`:

```python
def test_the_seed_distance_field_equals_the_per_candidate_walk() -> None:
    """`_distance_to_stranded` (last_mile.py:132-152) recomputed a triple-nested
    Manhattan minimum over the SAME fixed seeds and endpoints for every
    candidate in every BFS frontier round of `build_cluster` (:274-279).
    `seeds` is a tuple built once at :257 and never reassigned."""
    from flab2bp.layout.last_mile import _distance_to_stranded, _seed_distance_field

    seeds, endpoints, candidates = _cluster_fixture()  # existing helper in this file
    field = _seed_distance_field(seeds, endpoints)
    for candidate in candidates:
        assert field[candidate] == _distance_to_stranded(candidate, seeds, endpoints), candidate


def test_build_cluster_orders_candidates_identically_after_the_change() -> None:
    from flab2bp.layout.last_mile import build_cluster

    problem = _cluster_problem_fixture()  # existing helper in this file
    assert build_cluster(**problem) == _expected_cluster_fixture()
```

Append to `tests/layout/test_route_feedback.py`:

```python
def test_positions_are_built_once_per_call_not_twice() -> None:
    """`select_lns_neighbourhood` rebuilt `positions` from `pair.positive` and
    `pair.negative` TWICE per call (route_feedback.py:640-707), and the call runs
    once per LNS/ALNS repair iteration -- hundreds or thousands in a stagnating
    search."""
    import inspect

    from flab2bp.layout import route_feedback

    source = inspect.getsource(route_feedback.select_lns_neighbourhood)
    assert source.count("StripPositions.of") <= 2


def test_select_lns_neighbourhood_picks_the_same_strips() -> None:
    from flab2bp.layout.route_feedback import select_lns_neighbourhood

    problem, gaps, pair, hot_boxes = _lns_fixture()  # existing helper in this file
    assert select_lns_neighbourhood(problem, gaps, pair, hot_boxes) == _expected_lns_fixture()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_last_mile.py tests/layout/test_route_feedback.py -k "distance_field or built_once" -v`
Expected: FAIL — `_seed_distance_field` does not exist, and the source contains two separate
positions rebuilds.

- [ ] **Step 3: Add the distance field**

In `src/flab2bp/layout/last_mile.py`, above `_distance_to_stranded`:

```python
def _seed_distance_field(
    seeds: Sequence[int],
    endpoints: Mapping[int, Sequence[Cell]],
) -> dict[Cell, int]:
    """Manhattan distance from every cell to its nearest seed endpoint.

    One multi-source BFS over the endpoint set, computed once per
    `build_cluster` call, instead of the O(seeds x path) walk
    `_distance_to_stranded` did per candidate per frontier round. `seeds` is
    built once at last_mile.py:257 and never reassigned inside `build_cluster`
    -- only `frontier`, `cluster`, `members` and `refused` mutate -- which is
    what makes one field valid for the whole call.
    """
    field: dict[Cell, int] = {}
    frontier: deque[tuple[Cell, int]] = deque()
    for seed in seeds:
        for cell in endpoints.get(seed, ()):
            if cell not in field:
                field[cell] = 0
                frontier.append((cell, 0))
    while frontier:
        cell, distance = frontier.popleft()
        for dx, dy in _STEPS:
            nxt = (cell[0] + dx, cell[1] + dy, cell[2])
            if nxt in field:
                continue
            field[nxt] = distance + 1
            frontier.append((nxt, distance + 1))
    return field
```

**A four-neighbour BFS on a grid gives Manhattan distance only on an unobstructed grid.** Check
`_distance_to_stranded` at `last_mile.py:132-152`: if it computes a raw
`abs(dx) + abs(dy)` minimum over endpoints and does *not* route around obstacles, replace the BFS
above with the equivalent obstacle-free field, or keep the BFS and let the first test decide —
it compares the field against the original function on the real fixture, so a mismatch is caught
at this task, not at the gate. If they disagree, the original function is authoritative; make
the field match it.

In `build_cluster` (`:257-280`), compute `field = _seed_distance_field(seeds, endpoints)` once,
immediately after `seeds` is built, and replace the `sorted()` key at `:274-280` with a lookup
into `field`. Keep the rest of the key tuple byte-for-byte — the sort is a tie-break chain and
dropping a component changes which cluster is built.

- [ ] **Step 4: Hoist `positions` in `route_feedback.py`**

In `select_lns_neighbourhood` (`:640-707`), build the two position indexes once at the top:

```python
    positive_positions = StripPositions.of(pair.positive)
    negative_positions = StripPositions.of(pair.negative)
```

and use `positive_positions.position_of(strip)` / `negative_positions.position_of(strip)`
everywhere the two rebuilt dicts were read, including inside `_sequence_neighbours` (`:747-757`),
which takes them as parameters rather than rebuilding.

Add `from flab2bp.indexed import StripPositions` to the imports.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/layout/test_last_mile.py tests/layout/test_route_feedback.py -v ; echo "exit=$?"
uv run python scripts/last_mile_bench.py --cases docs/superpowers/evidence/2026-09-07-indexed-scans/last-mile-cases.pkl
```
Expected: exit 0. Capture `last-mile-cases.pkl` from `master@2e861af0` first if it does not exist,
the same way Task 14 captures `route-cases.pkl`.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/last_mile.py src/flab2bp/layout/route_feedback.py tests/layout docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "perf(layout): one seed distance field and hoisted LNS position indexes"
```

---

## Task 20: `layout/hierarchy/` — sites #35, #37, and the `BlockGraph` measurement

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/partition.py:200-226` (`_topo_order`) and `:192`
  (`derive_cuts`), `:476`; `src/flab2bp/layout/hierarchy/pressure.py:194`, `:206`
  (`depth_pressure_blocks`)
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/block-graph-backend.md`
- Test: `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `BlockGraph.of`, `.topological_order` (Task 8).
- Produces: `_topo_order` keeps its exact signature and return type.

`hierarchy/*` is held by `hierarchical-v4`. Land this task's single commit and rebase on top of
that branch's merge if it lands first; the conversion touches only `_topo_order`'s body and two
lines of `pressure.py`, so a conflict is textual, not semantic.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/hierarchy/test_partition.py`:

```python
def test_topo_order_is_unchanged_by_the_block_graph() -> None:
    """The order decides which cut a round takes, so equality is the proof.

    partition.py:200-226 re-sorted its ready frontier on every dequeue:
    `ready = sorted(set(ready) - seen)`, O(n^2 log n) for an O(n log n) walk. It
    is re-derived every round of `HierarchicalLayout.lay_out`
    (hierarchy/strategy.py:607) by design -- the block graph really does change
    -- so only the internals move.
    """
    import random

    from flab2bp.layout.hierarchy.partition import _topo_order

    rng = random.Random(101)
    for node_count in (1, 3, 9, 25, 80):
        for _ in range(20):
            blocks = _blocks_fixture(node_count, rng)  # existing helper in this file
            assert _topo_order(blocks) == _reference_topo_order(blocks)


def test_depth_pressure_blocks_computes_recipe_depths_once() -> None:
    """pressure.py:194 and :206 both call `recipe_depths(spec)` -- one via
    `depth_profile`, one directly -- so the O(recipes) pass ran twice."""
    from flab2bp.layout.hierarchy import pressure

    calls: list[int] = []
    original = pressure.recipe_depths

    def counting(spec):  # type: ignore[no-untyped-def]
        calls.append(1)
        return original(spec)

    pressure.recipe_depths = counting  # type: ignore[assignment]
    try:
        pressure.depth_pressure_blocks(_spec_fixture())  # existing helper in this file
    finally:
        pressure.recipe_depths = original  # type: ignore[assignment]
    assert len(calls) == 1
```

`_reference_topo_order` is a verbatim transcription of today's `partition.py:200-226` body,
written into the test file so the comparison survives the conversion.

- [ ] **Step 2: Run to verify the second test fails**

Run: `uv run pytest tests/layout/hierarchy/test_partition.py -k "topo_order_is_unchanged or computes_recipe_depths_once" -v`
Expected: the first PASSES (it characterises today), the second FAILS with `len(calls) == 2`.

- [ ] **Step 3: Measure the backend before choosing it (Ruling 4)**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
uv run python - <<'PY' | tee docs/superpowers/evidence/2026-09-07-indexed-scans/block-graph-backend.md
import random, time
from flab2bp.indexed import BlockGraph

def inline(n, edges):
    indeg = dict.fromkeys(range(n), 0); succ = {k: [] for k in range(n)}
    for a, b in edges: succ[a].append(b); indeg[b] += 1
    ready = sorted(k for k in range(n) if indeg[k] == 0); seen=set(); out=[]
    while ready:
        node = ready.pop(0)
        if node in seen: continue
        seen.add(node); out.append(node)
        for nxt in succ[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0: ready.append(nxt)
        ready = sorted(set(ready) - seen)
    return tuple(out)

rng = random.Random(7)
print("| blocks | inline (s/1000) | BlockGraph (s/1000) |")
print("|---|---|---|")
for n in (8, 20, 50, 120, 300):
    order = list(range(n)); rng.shuffle(order)
    edges = [(order[i], order[j]) for i in range(n) for j in range(i+1, n) if rng.random() < 0.1]
    t = time.perf_counter()
    for _ in range(1000): inline(n, edges)
    a = time.perf_counter() - t
    t = time.perf_counter()
    for _ in range(1000): BlockGraph.of(n, edges).topological_order()
    b = time.perf_counter() - t
    assert inline(n, edges) == BlockGraph.of(n, edges).topological_order(), n
    print(f"| {n} | {a:.4f} | {b:.4f} |")
PY
```

**Decide from the table, not from preference.** If `BlockGraph` is slower at the block counts
this codebase actually produces (find them with
`grep -rn --include='*.py' 'derive_cuts' src/` and read the call site's block list length), edit
`src/flab2bp/indexed/block_graph.py` so `topological_order` always uses `_heap_order` and the
networkx `DiGraph` is kept only for `has_cycle`/`successors`. Record which branch was taken, and
why, in the evidence file. The abstraction is unchanged either way — that is the point of
Ruling 3.

- [ ] **Step 4: Convert `_topo_order`**

Replace the body of `partition.py:200-226` with a `BlockGraph` call, keeping the signature and
the way it derives `node_count` and `edges` from `blocks`:

```python
    return BlockGraph.of(len(blocks), edges).topological_order()
```

Add `from flab2bp.indexed import BlockGraph` to the imports. Do the same at `partition.py:476` if
that site re-implements the walk rather than calling `_topo_order`.

- [ ] **Step 5: Convert `depth_pressure_blocks`**

In `pressure.py`, compute `depth = recipe_depths(spec)` once at the top of
`depth_pressure_blocks` and pass it to the `depth_profile` call at `:194` (adding a keyword
parameter `depth: Mapping[str, int] | None = None` to `depth_profile`, defaulting to
`recipe_depths(spec)` when omitted so every other caller is unaffected), and use the same
`depth` at `:206`.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/layout/hierarchy -v ; echo "exit=$?"
uv run pytest tests/ -k hierarch ; echo "exit=$?"
```
Expected: exit 0 for both.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/hierarchy src/flab2bp/indexed/block_graph.py tests/layout/hierarchy docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "perf(hierarchy): order blocks through BlockGraph and compute recipe depths once"
```

---

## Task 21: `pipeline.py` — site #16

**Files:**
- Modify: `src/flab2bp/pipeline.py:816-820` (the candidate-frontier legality filter) and
  `:1371`; `src/flab2bp/lab/flow.py:1026` (`cross_check`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `unsupplied_inputs` gains a keyword-only `external: Mapping[str, Fraction] | None = None`
  so the caller can pass an already-derived `flow.external_items(data)`; when it is `None` the
  function derives it exactly as today, so every other caller is unaffected.

`pipeline.py` is held by `selfloop`. One commit, one file plus the `flow.py` signature change.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py`:

```python
def test_external_items_is_derived_once_per_build_not_once_per_candidate() -> None:
    """pipeline.py:819 called `unsupplied_inputs` inside
    `for spec in spec_set.candidates:` and each call rescanned every flow row via
    `external_items` (lab/flow.py:529-563). `flow` and `data` are invariant
    across that loop, and the same map is derived again at pipeline.py:1371 and
    inside `cross_check` (lab/flow.py:1026): three derivations per build."""
    from flab2bp.lab import flow as flow_module

    calls: list[int] = []
    original = flow_module.FlowSelection.external_items

    def counting(self, data):  # type: ignore[no-untyped-def]
        calls.append(1)
        return original(self, data)

    flow_module.FlowSelection.external_items = counting  # type: ignore[method-assign]
    try:
        _build_fixture()  # existing helper in this file; one full pipeline.build()
    finally:
        flow_module.FlowSelection.external_items = original  # type: ignore[method-assign]
    assert len(calls) <= 1, f"external_items derived {len(calls)} times in one build"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -k external_items_is_derived_once -v`
Expected: FAIL — the count is the frontier size plus two.

- [ ] **Step 3: Thread the derived map through**

In `src/flab2bp/lab/flow.py`, change `unsupplied_inputs` (`:946`) to accept the map:

```python
def unsupplied_inputs(
    flow: FlowSelection,
    data: Dataset,
    external_inputs: Mapping[str, Fraction],
    *,
    exempt: frozenset[str] = frozenset(),
    external: Mapping[str, Fraction] | None = None,
) -> tuple[str, ...]:
```

and inside, replace the `flow.external_items(data)` derivation with
`flow.external_items(data) if external is None else external`.

In `src/flab2bp/pipeline.py`, derive it once immediately before the candidate loop at `:816`:

```python
        # Invariant across the whole candidate frontier: `flow` and `data` do
        # not change inside this loop, so deriving it per candidate rescanned
        # every row 2-8 times for one answer.
        external = selection.external_items(data)
        legal: list[tuple[BuildSpec, tuple[str, ...]]] = []
        illegal: list[tuple[BuildSpec, tuple[str, ...]]] = []
        for spec in spec_set.candidates:
            stray = unsupplied_inputs(
                selection, data, spec.external_inputs, exempt=exempt, external=external
            )
            (legal if not stray else illegal).append((spec, stray))
```

Reuse the same `external` at `pipeline.py:1371`, and pass it into `cross_check` so
`lab/flow.py:1026` stops deriving a third copy — add the same keyword-only `external` parameter
to `cross_check`, defaulting to `None`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_pipeline.py tests/lab -v ; echo "exit=$?"
```
Expected: exit 0.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/pipeline.py src/flab2bp/lab/flow.py tests/test_pipeline.py
git commit -m "perf(pipeline): derive the flow's external items once per build"
```

---

# Phase 3 — contended files, each followed by its measurement

## Task 22: `layout/sequence_pair.py` — sites #4, #23, #24, #25

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py:1472-1481` (`apply_move`, SWAP_BOTH),
  `:1057-1088` (`_topological_order`), `:1902-1905` (`merge_stage_boundary`),
  `:2064-2138` (`build_elite_archive`)
- Test: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `StripPositions.of`, `.positions_of`, `.position_of` (Task 6).
- Produces: every converted function keeps its exact signature and return type. No new public
  names.

**Site #3 is deliberately absent.** `decode_sequence_pair`'s O(N²) adjacency (`:853-860`) is not
converted — see the disagreement table and Ruling I-1: `build_sequence_kernel`
(`sequence_kernel.py:273-280`) returns `CompiledSequenceKernel` on the production path, so the
Python decoder is the reference implementation, not the hot loop.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_sequence_pair.py`:

```python
def test_swap_both_produces_the_same_state_as_the_index_scan_version() -> None:
    """SWAP_BOTH did `negative.index(a)` and `negative.index(b)` -- two O(N)
    scans -- once per move inside `anneal_stage`'s per-move loop
    (sequence_pair.py:1656). `apply_move` is Python and runs per move whichever
    kernel scores, which is what makes this the hottest scan in the solver."""
    import random

    from flab2bp.layout.sequence_pair import MoveKind, apply_move

    for seed in range(50):
        state = _anneal_state_fixture(size=24, seed=seed)  # existing helper in this file
        moved = apply_move(state, MoveKind.SWAP_BOTH, random.Random(seed))
        replay = _swap_both_by_index_scan(state, random.Random(seed))
        assert moved.pair.positive == replay.pair.positive, seed
        assert moved.pair.negative == replay.pair.negative, seed


def test_topological_order_is_unchanged_by_the_heap_frontier() -> None:
    """`_topological_order` (sequence_pair.py:1057-1088) did `ready.pop(0)` and
    `ready.sort(key=key)` on every promotion. The ORDER is what
    `encode_placement` turns into a sequence pair, so equality is the proof."""
    import random

    from flab2bp.layout.sequence_pair import _topological_order

    rng = random.Random(111)
    for size in (1, 2, 6, 20, 60):
        for _ in range(25):
            successors, key = _precedence_fixture(size, rng)  # existing helper in this file
            assert _topological_order(successors, key) == _reference_kahn(successors, key)


def test_merge_stage_boundary_picks_the_same_positions() -> None:
    from flab2bp.layout.sequence_pair import merge_stage_boundary

    state, left = _merge_fixture()  # existing helper in this file
    assert merge_stage_boundary(state, left) == _expected_merge_fixture()


def test_build_elite_archive_is_unchanged_by_the_single_pass() -> None:
    """`build_elite_archive` (:2064-2138) made SIX full passes over the same
    `values` tuple: four `min(...)`, one `sorted(...)`, one filtered `min(...)`."""
    from flab2bp.layout.sequence_pair import build_elite_archive

    distinct = _archive_fixture()  # existing helper in this file
    assert build_elite_archive(distinct) == _expected_archive_fixture()
```

`_swap_both_by_index_scan` and `_reference_kahn` are verbatim transcriptions of today's bodies,
written into the test file so the comparison survives the conversion.

- [ ] **Step 2: Run to verify they pass as characterisation**

Run: `uv run pytest tests/layout/test_sequence_pair.py -k "swap_both or topological_order_is_unchanged or merge_stage_boundary_picks or elite_archive_is_unchanged" -v`
Expected: all PASS. They characterise master; they are the guard, and any of them going red
during this task means the conversion moved the search.

- [ ] **Step 3: Convert SWAP_BOTH (site #4)**

Replace `src/flab2bp/layout/sequence_pair.py:1472-1481` with:

```python
    elif kind is MoveKind.SWAP_BOTH:
        first, second = rng.sample(range(size), 2)
        first_strip = positive[first]
        second_strip = positive[second]
        positive = _swap_positions(positive, first, second)
        # Two `negative.index(...)` scans, once per move, on the hottest Python
        # loop in the solver. `decode_sequence_pair` already builds this exact
        # index at :849-851 and throws it away.
        negative_positions = StripPositions.of(negative)
        first_at, second_at = negative_positions.positions_of(first_strip, second_strip)
        negative = _swap_positions(negative, first_at, second_at)
```

Add `from flab2bp.indexed import StripPositions` to the imports.

**The `rng` draw must stay exactly where it is.** `rng.sample(range(size), 2)` before anything
else, drawing the same number of values in the same order — the RNG stream is the search, and a
moved draw is a different anneal.

- [ ] **Step 4: Convert `merge_stage_boundary` (site #25)**

At `:1902-1905`, replace the `permutation.index(left_strip)` inside
`for permutation in (positive, negative):` with a `StripPositions.of(permutation)` built inside
that two-iteration loop and queried once. This is the same idea as step 3 at a fraction of the
frequency; it is here so one pattern covers every `.index()` on a permutation in this file.

- [ ] **Step 5: Convert `_topological_order` (site #23) — pending measurement**

Replace `ready.pop(0)` + `ready.sort(key=key)` at `:1057-1088` with a `heapq` keyed on
`(key(node), node)`:

```python
    frontier: list[tuple[Any, int]] = [(key(node), node) for node in ready]
    heapq.heapify(frontier)
    out: list[int] = []
    while frontier:
        _rank, node = heapq.heappop(frontier)
        out.append(node)
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(frontier, (key(nxt), nxt))
    return out
```

Add `import heapq`.

**Tie-breaking:** `list.sort` is stable, so a `pop(0)` after a sort took the first node with the
smallest key *in insertion order*. The heap's `(key(node), node)` tuple breaks ties by node id
instead. If `test_topological_order_is_unchanged_by_the_heap_frontier` goes red, the ties are not
equivalent — change the heap key to `(key(node), sequence_number)` with a monotonically
increasing `sequence_number` assigned at push time, which reproduces stable-sort order exactly.

**networkx is not used here** and the reason is Ruling 4's own "never by assertion" clause read
honestly: `_topological_order` runs on strip counts in the tens, and Task 23's measurement is
what settles whether a graph library could pay for a per-call build at that size. If it can, the
change belongs in `indexed/strip_precedence.py` behind a domain type, and Task 23 says so.

- [ ] **Step 6: Convert `build_elite_archive` (site #24)**

At `:2064-2138`, replace the four separate `min(values, key=...)` calls with one loop that carries
all four running minima, keeping each comparison's exact key expression and its exact
tie-breaking (`<`, not `<=`, so the first value wins a tie, as `min` does). Leave the `sorted(...)`
and the filtered `min(...)` alone unless they read the same four keys — if they do, fold them into
the same pass; if they do not, they stay.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/layout/test_sequence_pair.py -v ; echo "exit=$?"
uv run pytest tests/ -k sequence ; echo "exit=$?"
```
Expected: exit 0 for the first; for the second, exit 1 with only
`test_all_products_sequence_pair_honours_the_exact_layout_deadline` red.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git commit -m "perf(sequence-pair): index permutation positions and heap the Kahn frontier"
```

---

## Task 23: MEASUREMENT — the sequence-pair hot path

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/sequence-pair-measurement.md`

No source changes. This task exists so a sequence-pair regression is caught here rather than at
the gate, and so the `_topological_order` backend is chosen by measurement (Ruling 4).

- [ ] **Step 1: Record the environment**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure (mean runnable procs):", sum/5}'
git rev-parse HEAD
uv run python -c "import flab2bp; print(flab2bp.__file__)"
uv run python -c "from flab2bp.layout.sequence_kernel import compiled_backend_available as a; print('compiled kernel:', a())"
```

Write all four outputs into the evidence file. **If `compiled kernel: False`, stop.** The Cython
extension is missing from this worktree, every timing below would measure the Python fallback,
and the conclusion would be the scout's error repeated.

- [ ] **Step 2: `route_bench` digest — the tie-breaking guard**

```bash
uv run python scripts/route_bench.py \
  --cases docs/superpowers/evidence/2026-09-07-indexed-scans/route-cases.pkl --check \
  | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/sequence-pair-measurement.md
```
Expected: the digest line ends `MATCH`. **A `DIFFER` here reverts Task 22 in full** (Ruling I-6).
Note in the evidence file that this line is router-only evidence: it replays a committed A*
capture and says nothing about sequence-pair or ALNS neutrality, which is what step 4 is for.

- [ ] **Step 3: cProfile three cells, before and after**

Pick three corpus cells spanning the range — small, mid, largest — from
`uv run python -c "from flab2bp.bench.corpus import URL_CORPUS; print([e.url_id for e in URL_CORPUS])"`.
`universe-matrix` is the largest. For each cell, and for both `master@2e861af0` (a separate
checkout) and this branch's HEAD:

```bash
uv run python -m cProfile -o /tmp/prof-<branch>-<cell>.pstats \
  -m flab2bp.cli --url-id <cell> --strategy sequence-pair --budget 30 --workers 1
uv run python - <<'PY'
import pstats
s = pstats.Stats("/tmp/prof-<branch>-<cell>.pstats")
s.sort_stats("cumulative").print_stats(
    "apply_move|_topological_order|merge_stage_boundary|build_elite_archive|anneal_stage"
)
s.sort_stats("cumulative").print_stats(12)
PY
```

Record in the evidence file, per cell: total wall, and cumulative time for `apply_move`,
`_topological_order`, `merge_stage_boundary`, `build_elite_archive`, before and after, with the
`vmstat` figure taken beside each run.

- [ ] **Step 4: Sequence-pair multi-run audit compare (Ruling 5)**

```bash
uv run python scripts/audit.py --budget 30 --strategy sequence-pair \
  --json /tmp/seqpair-candidate.jsonl
uv run python scripts/audit_compare.py /tmp/seqpair-master.jsonl /tmp/seqpair-candidate.jsonl \
  | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/sequence-pair-measurement.md
```
`/tmp/seqpair-master.jsonl` comes from the same command run in a `master@2e861af0` checkout.
`audit.py` reports NOT CLEAN on any refusal, so **compare the counts and the named differing
cells, not the CLEAN/NOT CLEAN word**. Expected: identical cell counts and no cell named as
differing on area or validity.

- [ ] **Step 5: Decide the `_topological_order` backend**

If step 3 shows `_topological_order` still material (>1% of total wall on any cell), benchmark
`heapq` against `rustworkx` at the observed strip counts and, if `rustworkx` wins by more than
20%, add `src/flab2bp/indexed/strip_precedence.py` wrapping it, add `rustworkx` to
`pyproject.toml`, and re-run steps 2 and 4. Otherwise record "`heapq` retained; networkx and
rustworkx not adopted, per the table above" with the numbers. **Do not adopt a library on
plausibility.**

- [ ] **Step 6: Commit the evidence**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "docs: sequence-pair measurement for the indexed-scans conversions"
```

---

## Task 24: `layout/sequence_solver.py` — sites #1, #2, #14, #26

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py:1119` (`_stage_stats` declaration),
  `:1280`, `:1228`, `:1618`, `:1625`, `:1647`, `:2030`, `:2106-2107`, `:3119`,
  `:1308-1315` (the two frontier scans), `:3484-3496` (`swapped`), `:5646` (`transform_stage`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `Stages` (Task 5), `StripPositions` (Task 6).
- Produces: no new public names. `SequenceSearchResult.stages` stays `tuple[StageObservation, ...]`
  — `:1647` builds it from `self._stage_stats.as_tuple()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_sequence_solver.py`:

```python
def test_the_scheduled_stage_count_matches_a_brute_force_sum_at_every_step() -> None:
    """The sum at sequence_solver.py:1280 runs on EVERY iteration of the
    top-level `while True:` driver, and again at :2030 from three sites inside
    that loop -- O(S) per iteration, O(S^2) per solve.

    The rewrite at :2106-2107 is the trap: it replaces `_stage_stats[-1]` with a
    copy whose `global_skip_reason` is "projection-feedback", and
    `_counts_as_scheduled_stage` is False for that reason. A counter bumped only
    on append over-counts and stops the search early."""
    from flab2bp.layout.sequence_solver import _counts_as_scheduled_stage

    solver = _solver_fixture()  # existing helper in this file
    solver.search(max_stages=6)
    stages = solver._stage_stats
    assert stages.scheduled_count() == sum(_counts_as_scheduled_stage(s) for s in stages)


def test_a_projection_feedback_rewrite_decrements_the_scheduled_count() -> None:
    from dataclasses import replace

    solver = _solver_fixture()
    solver.search(max_stages=4)
    stages = solver._stage_stats
    before = stages.scheduled_count()
    last = stages.last()
    if last.global_skip_reason is None:
        stages.replace_last(replace(last, global_skip_reason="projection-feedback"))
        assert stages.scheduled_count() == before - 1


def test_the_search_terminates_identically_to_master() -> None:
    """Termination reason and stage count are the observable the count feeds."""
    solver = _solver_fixture()
    result = solver.search(max_stages=8)
    assert (result.termination, len(result.stages)) == _expected_termination_fixture()


def test_the_pending_work_frontier_finds_the_same_heights() -> None:
    """:1308-1315 walked `self._heights` TWICE per driver iteration, on two
    different flags. `_heights` is built once at :1108 and never appended to."""
    solver = _solver_fixture()
    heights = solver._heights
    assert solver._deferred_feedback_height() is next(
        (h for h in heights if h.deferred_feedback_budget is not None), None
    )
    assert solver._pending_compact_height() is next(
        (h for h in heights if h.pending_compact_seed is not None), None
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -k "scheduled_stage_count or projection_feedback_rewrite or pending_work_frontier" -v`
Expected: FAIL — `_stage_stats` is a list with no `scheduled_count`, and the two frontier helpers
do not exist.

- [ ] **Step 3: Convert `_stage_stats` to `Stages`**

`sequence_solver.py:1119`:

```python
        self._stage_stats: Stages[StageObservation] = Stages(_counts_as_scheduled_stage)
```

Then, mechanically:

- `:1280` → `if self._stage_stats.scheduled_count() >= stage_limit:`
- `:2030` → `scheduled_stages = self._stage_stats.scheduled_count()`
- `:3119` → unchanged (`.append(stage)` is `Stages.append`)
- `:2106-2107` →
  ```python
                observation = self._stage_stats.last()
                self._stage_stats.replace_last(
                    replace(observation, global_skip_reason="projection-feedback")
                )
  ```
- `:1228` (`for stage in reversed(self._stage_stats)`) → unchanged; `Stages.__reversed__` exists
- `:1618`, `:1625` (comprehensions over `self._stage_stats`) → unchanged; `Stages.__iter__` exists
- `:1647` (`stages=tuple(self._stage_stats)`) → `stages=self._stage_stats.as_tuple()`
- `:6218`, `:6264` (`solver._stage_stats[-1]`) → `solver._stage_stats.last()`
- `:6548`, `:6550`, `:6564` (iteration and `len`) → unchanged

Add `from flab2bp.indexed import Stages` to the imports.

- [ ] **Step 4: Convert the frontier scans (site #2)**

Add two small methods to the solver and call them at `:1308-1315`:

```python
    def _deferred_feedback_height(self) -> _HeightState | None:
        """The first height with a deferred feedback budget, or ``None``.

        `self._heights` is built once at :1108 and never appended to -- only the
        `_HeightState` fields flip -- so the walk is over a fixed list of ~5-50
        entries. It is here rather than inline because :1308-1315 walked that
        list TWICE per driver iteration on two different flags, and one named
        method per question is what makes a later worklist a local change.
        """
        return next(
            (height for height in self._heights if height.deferred_feedback_budget is not None),
            None,
        )

    def _pending_compact_height(self) -> _HeightState | None:
        """The first height with a pending compact seed, or ``None``."""
        return next(
            (height for height in self._heights if height.pending_compact_seed is not None),
            None,
        )
```

**No worklist yet.** The scout's suggestion — an incrementally maintained worklist of heights
with pending work — is a behavioural change to a list of at most 50 entries, and Task 25's
profile decides whether it is worth the staleness risk. This step only names the questions;
Task 25 says whether to go further.

- [ ] **Step 5: Convert `swapped()` (site #14) and `transform_stage` (site #26)**

At `:3484-3496`, hoist the position index out of the closure so the up-to-32 `.index()` scans
become 32 dict reads:

```python
    positive_positions = StripPositions.of(problem.pair.positive)
    negative_positions = StripPositions.of(problem.pair.negative)

    def swapped(
        permutation: tuple[int, ...],
        left: int,
        right: int,
        positions: StripPositions,
    ) -> tuple[int, ...]:
        values = list(permutation)
        left_position, right_position = positions.positions_of(left, right)
        values[left_position], values[right_position] = (
            values[right_position],
            values[left_position],
        )
        return tuple(values)
```

and pass the matching index at each call site — `positive_positions` when the permutation is
`positive`, `negative_positions` when it is `negative`. Read `:3500-3510` to bind them correctly;
passing the wrong one silently produces a valid-looking wrong permutation.

At `:5646`, replace `problem.instance_ids.index(requirement.instance_id)` with a
`StripPositions.of(problem.instance_ids)` built once per `PlacementProblem` — store it on the
`transform_stage` closure's enclosing scope, not per call.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/layout/test_sequence_solver.py -v ; echo "exit=$?"
uv run pytest tests/ ; echo "exit=$?"
```
Expected: the first exits 0; the whole suite exits 1 with only the two known reds.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "perf(solver): keep the scheduled stage count instead of resumming it per iteration"
```

---

## Task 25: MEASUREMENT — the solver driver

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/solver-driver-measurement.md`

- [ ] **Step 1: Record the environment and profile**

Same shape as Task 23 step 1 and step 3, filtering on the converted names:

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
uv run python - <<'PY'
import pstats
s = pstats.Stats("/tmp/prof-<branch>-<cell>.pstats")
s.sort_stats("cumulative").print_stats(
    "search|_run_pending_projection_feedback|_projection_feedback_stage_update|transform_stage"
)
PY
```
Record total wall and per-function cumulative time for three cells, before and after.

- [ ] **Step 2: Count the stages, not just the clock**

```bash
uv run python -c "
from flab2bp.bench.corpus import entry_for
" 2>/dev/null || true
uv run python scripts/audit.py --budget 30 --strategy sequence-pair --only universe-matrix \
  --json /tmp/solver-candidate.jsonl
```
Compare the `stages` field per cell against the same field from a `master@2e861af0` run. **The
stage counts must be identical.** A different stage count means the maintained counter answered
differently from the sum — the exact defect the scout's proposal would have introduced — and it
reverts Task 24 step 3 rather than being explained.

- [ ] **Step 3: Decide on the height worklist (site #2)**

If the profile shows the two `next(...)` walks at `:1308-1315` are below 0.5% of total wall on
every cell, record "worklist not built: the walk is over ≤50 entries and does not appear in the
profile" and stop. Only if they are material does the worklist get built, in its own follow-up
task, with a staleness test for every flag flip.

- [ ] **Step 4: Commit the evidence**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "docs: solver driver measurement for the indexed-scans conversions"
```

---

## Task 26: `layout/freeform.py` — sites #7, #19, #27, #28, #29, #30, #31

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:9931`, `:9942`, `:9962` (`_stake`/`_unstake`),
  `:10290-10360` (`_leaning`), `:10190-10192` (`reverse_link_guard` in `_ends`),
  `:10442-10456` (`_repair`'s stranded-net loop), `:12111-12129` and `:17317-17321`
  (`matches_demand`), `:13629-13667` (`_route_boundary_nets`), `:21630-21641` (`_Unseatable`),
  `:16008-16115`, `:16115-16236`, `:8959-9020` (three union-finds),
  `:16694-16935` (`_prepare_routing_problem`'s nested merge-plan loop)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `StakedPaths` (Task 7), `Nets` (Task 10), `UnionFind` (Task 9).
- Produces: no new public names. Every converted function keeps its signature.

`freeform.py` is held by `coater-placed` and `hierarchical-v4`. One commit, one file. If either
branch has merged by the time this task runs, rebase first and re-read every line number — the
file is 22,768 lines and the offsets will have moved.

**Sites #6 and the three `_tap_source` fallback rebuilds are NOT in this task.** They are
buildings scans; see "Requests to `buildings-index`". Add them as `Buildings.<method>` calls in a
follow-up commit once that branch has landed, and say in the final report that they are pending.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_freeform.py`:

```python
def test_leaning_grows_the_same_victim_set_as_the_rebuild_version() -> None:
    """`_leaning` rebuilt `touch` and `sole` from every staked path on EVERY
    call -- once per stranded net inside `_repair`'s loop, itself once per
    routing round per candidate pack per candidate height. The victim set is
    what the repair acts on, so equality is the proof."""
    problem = _repair_fixture()  # existing helper in this file
    for seed_set in _victim_seed_sets_fixture():
        assert _leaning_via_index(problem, seed_set) == _leaning_by_rebuild(problem, seed_set)


def test_the_staked_path_index_never_goes_stale_across_stake_and_unstake() -> None:
    """`paths` is REWRITTEN under `_leaning`: `paths[index] = path` at
    freeform.py:9931 and `paths.pop(index)` at :9962, both inside the same phase."""
    from flab2bp.indexed import StakedPaths

    index, live = _stake_replay_fixture()  # existing helper in this file
    for cell in _probe_cells_fixture():
        brute = frozenset(
            net
            for net, path in live.items()
            for end in (path[0], path[-1])
            for dx, dy in _STEPS
            if (end[0] + dx, end[1] + dy, end[2]) == cell
        )
        assert index.beside(cell) == brute, cell


def test_matches_demand_finds_the_same_nets() -> None:
    """:12111-12129 / :17317-17321 ran a `next()` over every prepared net inside
    a comprehension over every missing demand."""
    nets, demands = _prepared_nets_fixture()  # existing helper in this file
    for demand in demands:
        assert _matching_via_index(nets, demand) == _matching_by_scan(nets, demand), demand


def test_the_three_union_finds_group_identically_to_the_shared_one() -> None:
    pairs, nodes = _union_fixture()  # existing helper in this file
    assert _groups_via_shared(nodes, pairs) == _groups_by_the_old_closure(nodes, pairs)


def test_a_full_freeform_pack_produces_the_same_blueprint() -> None:
    """The end-to-end guard: same string, or the conversion is wrong."""
    assert _pack_fixture_blueprint() == _expected_blueprint_fixture()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -k "leaning_grows or never_goes_stale or matches_demand_finds or union_finds_group" -v`
Expected: FAIL — the helper functions the tests reference do not exist yet.

- [ ] **Step 3: Maintain the path index in `_stake`/`_unstake` (sites #7, #19, #28)**

Construct `staked = StakedPaths(_STEPS)` alongside `paths` where `paths` is created, and in
`_stake` (`:9931`) call `staked.stake(index, path)` on the same line that assigns
`paths[index] = path`; in `_unstake` (`:9962`) call `staked.unstake(index)` alongside
`paths.pop(index)`. **Do not delete `paths`** — many readers want the path itself, and the index
is an addition, not a replacement.

Then:
- `_leaning` (`:10331-10344`) drops its `touch`/`sole` rebuild and reads
  `staked.beside(cell)` and `staked.sole_neighbours(other, owner)`.
- `reverse_link_guard` (`:10190-10192`) reads `staked.nets()` / `staked.beside(...)` instead of
  scanning `path_tap` in full.
- `_repair`'s `selected_tap in paths.get(sibling, ())` then `sibling_path.index(selected_tap)`
  (`:10442-10456`) becomes one `staked.position_in(sibling, selected_tap)` and a `None` check —
  the double walk of the same tuple collapses to one dict read.

- [ ] **Step 4: Index the prepared nets (sites #27, #29, #30)**

- `:12111-12129` / `:17317-17321`: build `Nets.of(...)` once before the
  `preparation_failures` comprehension and replace the inner `next(...)` with
  `nets.matching_demand(item, kind, cell)`.
- `:21630-21641` (`_Unseatable`): build a
  `dict[(family_id, machine_start, machine_count), Strip]` once per strips-list version, outside
  the pack-attempt loop, and replace the `next(...)`.
- `:13629-13667` (`_route_boundary_nets`): maintain a reverse
  `reserved_cell_by_key: dict[Key, Cell]` wherever `canvas.reserved` is written, and replace the
  value-scan with a lookup. **`canvas.reserved` is mutated by other routing phases** (`del
  canvas.reserved[mine]` right after the read), so the reverse index must be updated at every
  write site, not built once — find them with
  `grep -n 'canvas\.reserved\[' src/flab2bp/layout/freeform.py`.
- `:16694-16935`: build a `(item, cargo_domain) -> [(src_key, sources)]` index from
  `out_ports.items()` once, before the `merge_plans` loop, and index into it instead of rescanning
  all of `out_ports` per merge plan.

- [ ] **Step 5: Collapse the three union-finds (site #31)**

Replace the closures at `:16008-16115`, `:16115-16236` and `:8959-9020` with `UnionFind` from
`flab2bp.indexed`. **Check the group ORDER at each site before and after** — two of the three feed
their result straight into a routing decision, which is why `UnionFind.groups()` is ordered; if a
site sorted differently, sort the result at that site rather than changing the shared type.

Add `from flab2bp.indexed import Nets, StakedPaths, UnionFind` to the imports.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -v ; echo "exit=$?"
uv run pytest tests/ ; echo "exit=$?"
```
Expected: the first exits 0; the whole suite exits 1 with only the two known reds.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(freeform): maintain the staked-path index and key the prepared nets"
```

---

## Task 27: MEASUREMENT — the router ledger and the freeform repair

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/freeform-router-measurement.md`

- [ ] **Step 1: Environment, then profile the three cells**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
uv run python -m cProfile -o /tmp/prof-ff-<cell>.pstats \
  -m flab2bp.cli --url-id <cell> --strategy freeform --budget 30 --workers 1
uv run python - <<'PY'
import pstats
s = pstats.Stats("/tmp/prof-ff-<cell>.pstats")
s.sort_stats("cumulative").print_stats(
    "_leaning|_repair|_ends|present_cost|occupy|_route_ends|_prepare_routing_problem"
)
s.sort_stats("cumulative").print_stats(15)
PY
```
Record per-function cumulative time and total wall, before and after, for all three cells.

- [ ] **Step 2: Settle Ruling I-4 — the `StakedPaths` backend**

```bash
uv run python - <<'PY' | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/freeform-router-measurement.md
import random, time
from flab2bp.indexed import StakedPaths
STEPS = ((1,0),(-1,0),(0,1),(0,-1))
rng = random.Random(3)
paths = [tuple((rng.randrange(80), rng.randrange(80), 0) for _ in range(rng.randrange(2, 30)))
         for _ in range(140)]
t = time.perf_counter()
for _ in range(200):
    index = StakedPaths(STEPS)
    for net, path in enumerate(paths):        # the WRITE path: once per stake
        index.stake(net, path)
    for net in range(0, 140, 3):              # rip-up
        index.unstake(net)
    for path in paths[:20]:                   # the READ path: once per stranded net
        index.beside(path[0])
print("StakedPaths stake/unstake/read cycle, 140 paths, 200x:", time.perf_counter()-t, "s")
PY
```
Compare against the same loop with a littletable table (write the comparison inline in the
evidence file). **If littletable wins on the total, change the backend inside
`src/flab2bp/indexed/staked_paths.py` and no caller moves** — that is the whole point of
Ruling 3, and the switch is a one-file commit.

- [ ] **Step 3: Freeform audit compare**

```bash
uv run python scripts/audit.py --budget 30 --strategy freeform --json /tmp/ff-candidate.jsonl
uv run python scripts/audit_compare.py /tmp/ff-master.jsonl /tmp/ff-candidate.jsonl \
  | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/freeform-router-measurement.md
```
Compare counts and named cells, not the CLEAN word. Expected: identical counts, no differing cell.

- [ ] **Step 4: Apply Ruling I-5**

For each converted site in Tasks 14 and 26, write one line: **moved the numbers** (with the
before/after figures) or **hygiene** (with what duplication it removed). Anything that is neither
gets reverted in its own commit, named here.

- [ ] **Step 5: Commit the evidence**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-indexed-scans/ src/flab2bp/indexed
git commit -m "docs: freeform and router measurement, and the StakedPaths backend decision"
```

---

## Task 28: `layout/validate.py` — sites #8, #9, #21, #33

**Files:**
- Modify: `src/flab2bp/layout/validate.py:234-280` (`_Cache`), `:4609-4629`
  (`_belt_reaches_any`), `:4180-4182`, `:4358`, `:4396` (`_close_over_junctions` call sites),
  `:4920-5008` (`_unsprayed_belts`), `:5040-5079` (`_sprayed_cargo_reaches_machines`),
  `:5296-5372` (`_lane_balance`'s graph build)
- Test: `tests/layout/test_validate.py`

**Interfaces:**
- Consumes: `Sorters.of`, `.drawing_from`, `.feeding`, `.drawing_from_carrying`, `.item`,
  `.indices` (Task 3).
- Produces: `Context.sorters() -> Sorters` — memoized on `ctx.cache` exactly like `of_kind`;
  `_Cache` gains `sorters: Sorters | None = None`, `internal_seeds: frozenset[int] | None = None`,
  `junction_closure: dict[frozenset[int], frozenset[int]] | None = None`, and
  `lane_belt_edges: tuple[tuple[int, int], ...] | None = None`.

`validate.py` is held by `selfloop`. One commit, one file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_validate.py`:

```python
def test_belt_reaches_any_walks_the_same_nodes_as_the_scan_version() -> None:
    """validate.py:4620-4628 scanned EVERY sorter at every BFS step, inside a
    per-sorter loop, inside a per-proof loop -- three levels deep. The frontier
    ORDER decides the traversal, so equality of the visited set AND of the
    answer is the proof."""
    ctx = _context_fixture()  # existing helper in this file
    from flab2bp.layout.validate import _belt_reaches_any, _belt_successors

    for start in range(min(40, len(ctx.kinds))):
        for item in _items_fixture(ctx):
            targets = _targets_fixture(ctx)
            assert _belt_reaches_any(ctx, start, targets, item) == _reaches_by_scan(
                ctx, start, targets, item, _belt_successors
            ), (start, item)


def test_the_sorter_index_is_built_once_per_context() -> None:
    ctx = _context_fixture()
    assert ctx.sorters() is ctx.sorters()


def test_the_sorter_index_matches_of_kind_exactly() -> None:
    from flab2bp.layout.validate import Kind

    ctx = _context_fixture()
    sorters = ctx.sorters()
    assert sorters.indices() == tuple(i for i, _b in ctx.of_kind(Kind.SORTER))
    for i, b in ctx.of_kind(Kind.SORTER):
        assert sorters.building(i) is b


def test_the_junction_closure_is_computed_once_for_three_call_sites() -> None:
    """`_close_over_junctions(ctx, _internal_seeds(ctx))` is computed
    independently at :4182 (`_lane_sourced`), :4358 (`_entry_runs`) and :4396
    (`_entry_items`) -- same source, same fixpoint, not cached, while
    `entry_runs`/`entry_items` right beside it ARE."""
    from flab2bp.layout import validate

    calls: list[int] = []
    original = validate._close_over_junctions

    def counting(ctx, seeds):  # type: ignore[no-untyped-def]
        calls.append(1)
        return original(ctx, seeds)

    validate._close_over_junctions = counting  # type: ignore[assignment]
    try:
        validate.certify(_placement_fixture())  # existing helper in this file
    finally:
        validate._close_over_junctions = original  # type: ignore[assignment]
    assert len(calls) <= 2, f"junction closure computed {len(calls)} times"


def test_certify_returns_exactly_the_same_findings() -> None:
    """The end-to-end guard. A verdict that moves reverts the whole task."""
    from flab2bp.layout.validate import certify

    assert certify(_placement_fixture()) == _expected_findings_fixture()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_validate.py -k "sorter_index or junction_closure_is_computed" -v`
Expected: FAIL — `Context.sorters` does not exist, and the closure runs three times.

- [ ] **Step 3: Add `Context.sorters()` and convert site #8**

Add to `_Cache` (`:258-280`): `sorters: Sorters | None = None`. Add to `Context`, beside
`of_kind`:

```python
    def sorters(self) -> Sorters:
        """Every sorter, keyed by what it draws from, feeds, and carries.

        Four places rebuilt this map ad hoc from `of_kind(SORTER)`:
        `_run_sorter_sources` (:4322, cached), `_belt_reaches_any`'s inline
        filter (:4620, NOT cached -- run once per BFS step),
        `_unsprayed_belts`'s `hops` (:4977) and
        `_sprayed_cargo_reaches_machines`'s `feeds` (:5048).
        """
        got = self.cache.sorters
        if got is None:
            items = _sorter_items(self)
            got = Sorters.of(
                (index, building, items.get(index))
                for index, building in self.of_kind(Kind.SORTER)
            )
            self.cache.sorters = got
        return got
```

Then replace `validate.py:4620-4628` with:

```python
        sorters = ctx.sorters()
        pending.extend(
            sorters.building(sorter_index).output_obj
            for sorter_index in sorters.drawing_from_carrying(index, item)
            if sorters.building(sorter_index).output_obj is not None
            and 0 <= sorters.building(sorter_index).output_obj < len(ctx.kinds)
            and ctx.kinds[sorters.building(sorter_index).output_obj]
            in (Kind.BELT, Kind.SPLITTER)
        )
```

**Hoist `sorters = ctx.sorters()` above the `while pending:` loop**, not inside it. And keep the
order: `Sorters.drawing_from_carrying` returns placement order, which is what
`ctx.of_kind(Kind.SORTER)` produced, so the frontier grows the same way.

Add `from flab2bp.indexed import Sorters` to the imports.

- [ ] **Step 4: Convert `_unsprayed_belts` and `_sprayed_cargo_reaches_machines` (site #33)**

Replace the private `hops` build (`:4977-4988`) and `feeds` build (`:5048-5057`) with
`ctx.sorters().drawing_from(...)` / `.feeding(...)` calls. Both are per-call locals today; both
answer the same question the shared index answers.

- [ ] **Step 5: Memoize the junction closure (site #21)**

Add to `_Cache`: `internal_seeds: frozenset[int] | None = None` and
`junction_closure: dict[frozenset[int], frozenset[int]] | None = None`. Wrap `_internal_seeds`
and `_close_over_junctions` so each consults the cache first, keyed by the seed set:

```python
def _cached_closure(ctx: Context, seeds: frozenset[int]) -> frozenset[int]:
    """The junction fixpoint, memoized per seed set.

    `entry_runs` and `entry_items` are already promoted to `ctx.cache`
    (:258-280); the closure they both stand on was not, so :4182, :4358 and
    :4396 each ran the whole `while changed:` re-scan of every junction.

    WHAT COMES OUT OF HERE IS SHARED -- `_Cache`'s own docstring rule. The
    result is a `frozenset`, so a caller cannot mutate it into another check's
    answer.
    """
    store = ctx.cache.junction_closure
    if store is None:
        store = {}
        ctx.cache.junction_closure = store
    got = store.get(seeds)
    if got is None:
        got = frozenset(_close_over_junctions(ctx, seeds))
        store[seeds] = got
    return got
```

and call `_cached_closure(ctx, _cached_internal_seeds(ctx))` at `:4182`, `:4358` and `:4396`.
`_cached_internal_seeds` follows the same shape against `ctx.cache.internal_seeds`.

**If any of the three call sites mutates the returned collection**, the `frozenset` will raise
and the fix is to copy at that call site, never to hand back a mutable set.

- [ ] **Step 6: Split `_lane_balance`'s graph build (site #9)**

Precompute the item-independent belt edges once, before the `for item in wanted_items:` loop:

```python
    # The belt half of the flow topology (validate.py:5299-5313) does not depend
    # on `item`; the sorter half (:5315) and the dock half (:5350) do. The
    # edges are precomputed as a plain list because `_add_flow_link` writes
    # MUTABLE residual capacities into `graph`, so the graph itself still has to
    # be rebuilt per item -- what is saved is the scan and the legality tests,
    # not the allocation.
    belt_edges: list[tuple[int, int]] = []
    for index, belt in ctx.of_kind(Kind.BELT):
        onward = belt.output_obj
        if onward is not None and 0 <= onward < building_count and ctx.kinds[onward] in physical_kinds:
            belt_edges.append((index, onward))
        upstream = belt.input_obj
        if (
            upstream is not None
            and 0 <= upstream < building_count
            and ctx.kinds[upstream] in (Kind.SPLITTER, Kind.PILER)
        ):
            belt_edges.append((upstream, index))
```

and inside the per-item loop, replace `:5299-5313` with
`for src, dst in belt_edges: _add_flow_link(graph, predecessors, src, dst, total_demand)`.

**Edge insertion order into `graph` must not change.** `_max_flow` is a hand-rolled Edmonds-Karp
(`:5198-5235`) whose augmenting-path choice depends on adjacency order, so `belt_edges` must be
appended in exactly the order the two original branches produced — which is why the loop above is
a transcription, not a rewrite.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/layout/test_validate.py -v ; echo "exit=$?"
uv run pytest tests/ ; echo "exit=$?"
```
Expected: the first exits 0; the whole suite exits 1 with only the two known reds.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src && uv run mypy src
export GIT_EDITOR=true
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "perf(validate): index the sorters and memoize the junction closure"
```

---

## Task 29: MEASUREMENT — `_coproduct_buffer` and `_lane_balance`

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/validate-measurement.md`

- [ ] **Step 1: Environment, then profile `certify` alone**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
uv run python -m cProfile -o /tmp/prof-val-<cell>.pstats - <<'PY'
from flab2bp.layout.validate import certify
placement = ...  # load the committed placement for <cell> from the evidence dir
for _ in range(3):
    certify(placement)
PY
uv run python - <<'PY'
import pstats
s = pstats.Stats("/tmp/prof-val-<cell>.pstats")
s.sort_stats("cumulative").print_stats(
    "certify|_coproduct_buffer|_belt_reaches_any|_lane_balance|_unsprayed_belts|_close_over_junctions|sorters"
)
PY
```

Profiling `certify` directly rather than a whole build is deliberate: validation is a fraction of
a build's wall, and a whole-build profile would bury the very functions this task changed. Record
both — `certify` alone for the per-function numbers, and the whole-build wall for the ratio that
actually ships.

Use `universe-matrix` as the largest cell: `_Cache`'s own docstring measures a 37,225-building
`universe-matrix` placement, which is the scale this index was built for.

- [ ] **Step 2: The `polars` number for validate (Ruling I-3)**

Record, for the largest cell: the row count of `ctx.of_kind(Kind.SORTER)`, the number of
`Sorters` queries during one `certify`, and the wall of `Sorters.of(...)`. This is the evidence
behind refusing polars for the one collection in this codebase large enough to have been a
candidate. State the conclusion in the file explicitly, so a later reader does not re-open it
without new numbers.

- [ ] **Step 3: Whole-corpus validate ratio**

```bash
uv run python scripts/audit.py --budget 30 --strategy both --json /tmp/val-candidate.jsonl
uv run python scripts/audit_compare.py /tmp/master-baseline.jsonl /tmp/val-candidate.jsonl \
  | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/validate-measurement.md
```
Compare counts and named cells. **Any cell whose validity flips reverts Task 28 in full**
(Ruling I-6): a validator that answers differently is not an optimisation.

- [ ] **Step 4: Apply Ruling I-5 and commit**

One line per converted site — moved the numbers, or hygiene — then:

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "docs: validate measurement for the indexed-scans conversions"
```

---

## Task 30: The final profile, the paired corpus guard, and the report

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/README.md`
- Create: `docs/superpowers/evidence/2026-09-07-indexed-scans/deterministic-controls.md`

This is the last task. `git diff --stat -- src tests` against this task's own commit must be
**empty** when the evidence is written: the numbers must describe the branch's final HEAD, not a
mid-branch state.

- [ ] **Step 1: Confirm the tree is final**

```bash
export GIT_EDITOR=true
git status --porcelain
git rev-parse HEAD
git diff --stat -- src tests
```
Expected: clean tree, and an empty diff. If anything is outstanding, commit it in its own task
first and start this task again.

- [ ] **Step 2: The full gate (Ruling 5)**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/indexed-scans
uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"     # must be inside the worktree
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts
uv run pytest ; echo "pytest exit=$?"
```
Expected: ruff, ruff format and mypy all clean; pytest exits 1 with **only**
`test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
`test_all_products_sequence_pair_honours_the_exact_layout_deadline` red. Any third failure blocks
the branch. There is no summary line here — read the exit code and the listed failures.

- [ ] **Step 3: Deterministic controls — twelve cells, exact blueprint strings**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu-pressure:", sum/5}'
for cell in $(uv run python -c \
  "from flab2bp.bench.corpus import URL_CORPUS; print(' '.join(e.url_id for e in URL_CORPUS))"); do
  uv run python -m flab2bp.cli --url-id "$cell" --strategy freeform --budget 30 --workers 1 \
    > "/tmp/bp-candidate-$cell.txt"
done
```
Run the identical loop in a `master@2e861af0` checkout into `/tmp/bp-master-$cell.txt`, then:

```bash
for cell in ...; do
  diff -q "/tmp/bp-master-$cell.txt" "/tmp/bp-candidate-$cell.txt" \
    || echo "DIFFERS: $cell"
done | tee docs/superpowers/evidence/2026-09-07-indexed-scans/deterministic-controls.md
```
Expected: no `DIFFERS` line. `--workers 1` is `DETERMINISTIC_WORKERS` (`layout/base.py:56-60`);
without it CP-SAT's multi-worker search makes the strings incomparable and the control proves
nothing.

**A single differing cell blocks the branch** (Ruling I-6). Bisect it by reverting one task's
commit at a time until the string matches, then fix that task.

- [ ] **Step 4: The full paired corpus compare**

```bash
uv run python scripts/audit.py --budget 30 --strategy both --json /tmp/final-candidate.jsonl
uv run python scripts/audit_compare.py /tmp/master-baseline.jsonl /tmp/final-candidate.jsonl \
  | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/README.md
```
`/tmp/master-baseline.jsonl` is the same command from `master@2e861af0`. `audit.py` says NOT
CLEAN on any refusal, and this corpus has known refusing cells, so **read the counts and the
named cells**: the number of clean cells must not fall, and no cell may be named as newly
refusing or as differing on area.

- [ ] **Step 5: The wall ratios on the eight largest cells (Ruling 6)**

```bash
for cell in <the eight largest url_ids by area>; do
  vmstat 1 6 | tail -n 5 | awk -v c="$cell" '{sum+=$1} END {print c, "cpu-pressure:", sum/5}'
  /usr/bin/time -f "$cell candidate %e" uv run python -m flab2bp.cli \
    --url-id "$cell" --strategy both --budget 30 --workers 1 > /dev/null
done 2>&1 | tee -a docs/superpowers/evidence/2026-09-07-indexed-scans/README.md
```
and the same from the master checkout. Record the ratio per cell beside its `vmstat` figure.
**Never wait for the box to be idle** — it never is; record the pressure and move on.

- [ ] **Step 6: Write the report**

`docs/superpowers/evidence/2026-09-07-indexed-scans/README.md` must contain, in this order:

1. **Verdict** — one line: does the branch meet Ruling 5's byte-identity bar, yes or no.
2. **What moved the numbers** — one row per site, with before/after cumulative time and the
   cell it was measured on. Cite the site number from the scout's file and the `file:line`.
3. **Hygiene conversions** — one row per site, naming the duplication removed and stating
   explicitly that it did not move the clock. Ruling 6 requires these two lists to be separate,
   and Ruling I-5 requires a site in neither list to have been reverted.
4. **Reverted** — every conversion Ruling I-5 or I-6 sent back, with its commit and the number
   or the differing cell that sent it.
5. **Backend decisions, as measured** — the `StakedPaths` outcome (Task 27 step 2), the
   `BlockGraph` outcome (Task 20 step 3), the `_topological_order` outcome (Task 23 step 5), and
   the two polars numbers (Task 16 step 6, Task 29 step 2).
6. **Still pending `buildings-index`** — scout sites #6, #12, #13, the three `_tap_source`
   fallback rebuilds, and the four requests at the top of this plan, with the method each needs.
7. **Where this plan disagreed with the scout** — copy the table from this plan and add any
   further disagreement found during execution.
8. **Environment** — every `vmstat` figure recorded beside its timing, the branch HEAD, and the
   confirmation that `flab2bp.__file__` was inside the worktree for every run.

- [ ] **Step 7: Commit**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-indexed-scans/
git commit -m "docs: indexed-scans evidence, gate results, and backend decisions"
git diff --stat -- src tests HEAD~1   # must be empty: evidence describes the final HEAD
```

---

## Self-review

Run against the spec (the scout's findings file plus the six rulings) with fresh eyes.

### 1. Spec coverage

**Rulings.** Ruling 1 → every task converts a ranked scan or graph site. Ruling 2 → the
per-collection backend table, with the mutability evidence and the "why not the other two" column,
plus measurement tasks 16/20/23/27/29 that carry the cost numbers. Ruling 3 → `src/flab2bp/indexed/`
with one module per type, domain-typed public methods, and
`tests/indexed/test_backend_containment.py` (Task 1) grepping the whole tree. Ruling 4 → the
graph-site backend table; networkx for `ReferenceGraph` and `BlockGraph`; the duplicate-adjacency
groups collapsed (Tasks 11, 12, 26, 28); the scipy precedent checked and found not to exist,
recorded as Ruling I-2. Ruling 5 → Task 30 steps 2-4, plus the `route_bench` MATCH in Tasks 14, 18
and 23 and the sequence-pair multi-run compare in Task 23 step 4. Ruling 6 → Tasks 23, 25, 27, 29
and 30, with `vmstat` beside every timing and Task 30 step 6 items 2 and 3 separating movers from
hygiene.

**Scout sites.** Converted: #1, #2, #4, #5, #7, #8, #9, #10, #11, #14, #15, #16, #17, #18, #19,
#20, #21, #22, #23, #24, #25, #26, #27, #28, #29, #30, #31, #33, #34, #35, #36, #37, #38, #39,
#40, #41, #42, #43, #44, #45, #46, #47, #48, #49. Deferred to `buildings-index` with a named
method: #6, #12, #13. Dropped with a recorded ruling: #3 (Ruling I-1). That is 49 of 49 accounted
for. The scout's duplicate-adjacency groups are each named in the task that collapses them, and
its "not worth converting" list is untouched except where a domain type built for a ranked site
covered a row anyway (#39's band lookup, Task 13, which the scout ranked rather than excluded).

**Gap check.** The scout's "`_splitter_successors`-shaped adjacency" group lists five build sites;
this plan converts none of them and defers all five, because every one reads `canvas.buildings`.
That is the brief's boundary, and it is stated in the requests section rather than left implicit.

### 2. Placeholder scan

No "TBD", no "implement later", no "similar to Task N", no "add error handling". Three steps
describe an edit at a line range rather than quoting the replacement in full — Task 13 step 4,
Task 16 step 4, and Task 22 step 6 — and each states the invariant that decides the edit (keep
the error shape; use the `object.__setattr__` pattern from Task 15; keep `<` so the first value
wins a tie), which is the part an implementer would otherwise get wrong. Task 26 step 4 lists four
sub-edits rather than quoting each; each names its exact line range and its exact key.

Five test helpers are referenced as "existing helper in this file" (`_previews_fixture`,
`_selection_fixture`, `_cells_fixture`, `_context_fixture`, `_placement_fixture` and their
siblings). Each is followed by an instruction for what to do if it does not exist. That is a real
dependency on the current test suite, not a placeholder.

### 3. Type consistency

`Stages` is generic and constructed as `Stages[StageObservation](_counts_as_scheduled_stage)` in
Task 24, matching its Task 5 signature. `StripPositions.positions_of` returns
`tuple[int, int]` and is destructured as two values in Tasks 19, 22 and 24. `Sorters.of` takes
`(index, building, item)` triples in Task 3 and is fed exactly those in Task 28 step 3.
`Cells.best_per_url` takes `strategy` / `valid_only` / `rank` in Task 4 and is called with those
names in Task 16 step 3. `ReferenceGraph.module_reach` returns `dict[str, frozenset[str]]` in Task
2 and is indexed as such in Task 11 step 4. `BlockGraph.of(node_count, edges)` matches its Task 20
call. `StakedPaths.position_in` returns `int | None` and is `None`-checked in Task 26 step 3.
`UnionFind.groups()` returns a tuple of tuples in both Task 9 and Task 26 step 5.

One inconsistency found and fixed while reviewing: Task 4's `Cells` step 3 did not show the
`__init__.py` edit its step 5 commits, so the note after Task 4 now spells out the file's final
shape and states that every later domain-type task appends to it alphabetically.
