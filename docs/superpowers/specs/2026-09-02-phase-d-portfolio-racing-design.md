# Phase D: Portfolio Racing With Shared Incumbents, and Wall Discipline

**Status:** Executed 2026-09-03 on branch `phase-d-portfolio`. Gate D1 PASSED; Gate D2 FAILED on one clause, so racing ships OPT-IN (`race=False`, `--race`) and the §6.3 step-two flip (Task 17: default `race=True`, the web ceiling losing its strategy factor) was NOT done. Gate D2 (`docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d2.md`, three 108-cell rounds at budget 30, `--jobs 16`): coverage PASS (no `best` cell missed a baseline-CLEAN arm, three rounds), per-cell seconds max 30.3 s PASS, freeform and sequence-pair not worse than D1 PASS (66/72 both arms every round), but `best` area exceeded `1.013 x min(serial freeform, serial sequence-pair)` on 8/7/6 cells (worst 1.399x on `energy-matrix/output-products`, identical every round, not noise). Mechanism, exactly the one §11 predicted: under `--jobs 16` a `best` cell splits 8 workers into (6, 2), the raced freeform arm starts with a cold `geometry_memo` beside a competing CP-SAT process, and it never reaches the serial arm's quality, so `best` ends up equal to its own raced sequence-pair number. Wall-discipline caveat carried from D1: no wall-discipline poll fired in 324 rows either; the code is proved cost-free when idle, not effective. Ruling AN (below) keeps no-good sharing transport-only. Next levers, ranked (whole-branch review order): (0) run one corpus round through `pipeline.build(race=True)`, the production racing path, which Gate D2 never exercised (it measured `RacingLayout` through the audit's own factory); (1) the gate's per-cell worker budget is the confound: a standalone build splits 128 cores into (96, 32); re-measure `best` at `--jobs 4` (32 workers per cell, split (24, 8)) before touching `RACE_FREEFORM_WORKER_SHARE`; (2) put the incumbent and no-good counters on `audit.Result` so a gate can see sharing (Gate D2's rows cannot; Task 10's unit tests and its real-pool `plastic` proof are the only evidence that incumbents flow, so every quality lever is unattributable until this lands); (3) hand the raced freeform arm the warm start the serial arm gets (a cross-process geometry memo is a non-goal of this phase); (4) `attempt_wall_s` / `wall_overshoot_s` now reach placement-bearing refused rows; only placement-free `NoValidLayout` and CRASH rows carry neither. Also recorded: both raced attempts share one `attempt_started`, so the second arm's finalization window is shortened by the first arm's post-processing (documented, untested). Wall discipline (5.1) landed; Gate D1 PASSED every clause in three rounds (`docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d1.md`), with the caveat that the 35–40 s overshoot this text targets was already absent at the branch point, so no wall-discipline poll fired on the corpus. OPEN, Ruling AN: the no-good half of 5.3 is transport-only. `ClusterRelationNoGood` names strips by integer index into the producer's own arrays (`strips: tuple[int, ...]`, `route_feedback.py`), not by `StripInstanceId`, and sequence-pair has no relation-exclusion collection to receive into; the identity assertion this section describes therefore has no field to key on, and an applied cut would land on whatever strips occupy those indices in the receiver. The receivers are not wired (Task 12 deferred); `published_no_goods` / `consumed_no_goods` are structurally zero and Gate D2 measures incumbent sharing only. The design for a later phase: the message carries an id vector aligned with `strips`, the receiver maps ids to its own live indices and rebuilds a renumbered no-good, applying only when every id is present, and sequence-pair gains a collection. Phase C's evidence (its Ruling W) is that cluster no-goods are corpus-inert on this corpus, so the shared value forgone today is nil. OPEN, Task 14: `sequence_islands != 1` is now legal with `strategy="best"`, and a raced sequence-pair child that spawns islands pays the spawn cost TWICE (once for the race arm, once per island) while its islands start a fresh `time_budget_s` those spawn seconds late — `SequencePairLayout.lay_out`'s `islands > 1` branch deliberately ignores `absolute_deadline` (brief-mandated at Task 9) and `run_sequence_islands` takes none. Threading it is not the one-line hand-off Task 14's addendum offered as the preferred option: it needs a new parameter on `run_sequence_islands`, a Ruling AJ span (`min(ceiling, max(0.0, deadline - started))`) inside `_sequence_island_deadlines`, a new argument at the `sequence_solver.py` call site, and its own island-deadline tests — three files outside that task's scope, reversing a Task 9 mandate. Documented instead, here and in the `--sequence-islands` help text. No production caller can reach the combination today: `cli.py` still refuses `--sequence-islands` without `--strategy sequence-pair`, and `web/` never passes islands at all, so the cost is latent until a later task opens that door.

**Phase E status for ranked lever 2 (executed 2026-09-03–04):** The observability lever shipped
through Phase E §5.3.2. `NoValidLayout` now carries optional
`Mapping[str, float | str]` stats, populated at freeform's three post-sweep raises and the
sequence-pair re-raise. `audit.Result.stats` is populated on both `run_cell` REFUSED returns
(including the audit's own `finalize.ProjectionRefusal`), as well as CLEAN and INVALID rows; a
missing mapping remains empty. Before this change `_with_observational_stats` attached solver stats
only to successful sequence-pair placements. The audit exercises strategies directly in workers and
flattens the scalar mapping, so no exception or `Placement` is pickled for this telemetry.

The remaining boundary is unchanged and explicit: `pipeline` constructs its own `NoValidLayout`
from attempt failures, and `strategy_race` re-raises a flattened refusal without solver stats, so
CLI and web refusals still carry none. Phase D Ruling AN is untouched: no cross-process no-good
identity vector or receiver was added.

**Plan:** `docs/superpowers/plans/2026-09-02-phase-d-portfolio-racing.md`
**Predecessors:** Phase A `docs/superpowers/specs/2026-09-01-evaluation-throughput-design.md`;
Phase B (complete last-mile router) and Phase C (ALNS placement) design briefs.

Every `file:line` in this document was read at `b3c990a` (master, clean). Line
numbers are hints; resolve each target by symbol name.

## 1. Decision

Two changes, gated separately.

1. **Wall discipline.** Stop the sequence-pair solver from running past its
   budget. Bound the one call that actually overruns it today
   (`_variant_direct_eligibility`), give the cold-stage admission a time cap,
   poll the clock inside the annealing move loop and the archive routing loop,
   and make `pipeline.build` measure and report each attempt's overshoot
   against `budget + ATOMIC_COMPLETION_GRACE_S`.
2. **Racing.** `strategy="best"` stops running freeform and then sequence-pair
   serially with the full budget each. Both run concurrently in spawned
   processes for one budget, sharing two things over two `multiprocessing`
   queues: certified incumbent bounds, and Phase B cluster no-goods keyed by
   strip instance identity. The race ends at the deadline or when both finish;
   the winner is still `min(area)` over validator-clean attempts, chosen in the
   parent, unchanged.

Nothing here adds a search operator, changes routing, or caches geometry across
processes.

## 2. Evidence

### 2.1 The serial `best` cost model

`pipeline.build` (`src/flab2bp/pipeline.py:353`) runs a flat nested loop, outer
over `spec_set.candidates`, inner over `wanted = _strategy_names(strategy)`
(`pipeline.py:515-544`), and hands **every** pair the full, undivided budget:

```python
placement = layout.lay_out(spec, time_budget_s=time_budget_s)
```

`_strategy_names("best")` returns `PRODUCTION_STRATEGIES = ("freeform",
"sequence-pair")` (`pipeline.py:63-74`), so `best` is two serial solves, not a
portfolio. The web ceiling states the same model as an arithmetic identity
(`src/flab2bp/web/jobs.py`, `Options.solver_ceiling_s`):

```python
per_spec = pipeline.PRODUCTION_STRATEGY_COUNT if self.strategy == "best" else 1
return self.effective_candidate_count * per_spec * self.budget_s
```

With `MAX_SOLVER_SECONDS = 300.0` (`jobs.py`) and the default three candidate
policies, a `best` request is admitted only up to `3 * 2 * budget <= 300`, i.e.
50 s per solve. After racing the same request costs `3 * 1 * budget`, so the
same ceiling admits 100 s per solve.

### 2.2 The overshoot: measured, and not where the research note put it

Corpus at `--budget 30 --jobs 16`, three rounds
(`docs/superpowers/evidence/2026-09-01-evaluation-throughput/candidate-budget30-round{1,2,3}.jsonl`),
65/72 CLEAN, INVALID 0, CRASH 0. Every row above 30 s:

| Round | s | Cell | Status |
|---:|---:|---|---|
| 1 | 34.77 | sequence-pair quantum-chip/no-proliferator | REFUSED |
| 1 | 31.38 | freeform universe-matrix/output-products | REFUSED |
| 1 | 30.78 | freeform quantum-chip/all-products | REFUSED |
| 2 | 38.97 | sequence-pair quantum-chip/no-proliferator | REFUSED |
| 2 | 32.40 | freeform universe-matrix/no-proliferator | REFUSED |
| 2 | 30.96 | freeform universe-matrix/output-products | REFUSED |
| 3 | 40.29 | sequence-pair quantum-chip/no-proliferator | REFUSED |
| 3 | 31.41 | freeform universe-matrix/no-proliferator | REFUSED |
| 3 | 30.76 | freeform universe-matrix/output-products | REFUSED |

`wall p95` per round: 30.53 / 30.67 / 30.37 s. `wall max`: 34.77 / 38.97 /
40.29 s. `audit_compare.py` fails all three on `p95 wall ... exceeds 30.0s`.

**The research note's hypothesis was cold-stage admission in
`_MeasuredStageAdmission.try_start`. It is falsified for this cell.** A
stack-sampling probe of `SequencePairLayout.lay_out` on
`quantum-chip/no-proliferator` at `--budget 30` on an idle box, two runs:

| Run | Wall | Overshoot | Samples in `solver.search()` | Samples in `_variant_direct_eligibility` |
|---:|---:|---:|---:|---:|
| 1 | 33.41 s | +3.41 s | 0 | all of them |
| 2 | 35.33 s | +5.33 s | 0 | 23.40 s before the deadline, 4.20 s after |

`solver.search()` never ran a single stage, so no stage was ever admitted and
`try_start` cannot be the cause. The deepest post-deadline stack frame was:

```
sequence_solver.py:lay_out       -> _production_run:4199
  -> _variant_direct_eligibility:3660 -> _selected_direct_targets:3166
  -> _refinement_direct_targets:3415
```

The mechanism is exact. In `_production_run`:

```python
compact_deadline = min(deadline, compact_started + ceiling * 1/3)   # ~:4190
try:
    direct_eligibility = (
        _variant_direct_eligibility(spec, strips, problems[compact_height],
                                    band_policy=band_policy)
        if ceiling >= _COMPACT_SEED_DIRECT_MIN_BUDGET_S and not deadline_reached()
        else ()
    )                                                               # ~:4198-4207
```

`_variant_direct_eligibility` (`sequence_solver.py:3627`) is a triple nested
loop — one `_selected_direct_targets` call per (baseline candidate x producer
variant x consumer variant) — with **no `cancelled` parameter and no clock poll
of any kind**. The `not deadline_reached()` guard runs once, *before* the call.
`_COMPACT_SEED_DIRECT_MIN_BUDGET_S = 30.0` (`sequence_solver.py:158`), which is
why the overshoot appears at the 30 s corpus budget and is absent from the 15 s
evidence. The already-computed `compact_deadline` on the line above is never
applied to it. The scan consumed ~27 of the 35 s and then `solve_compact_seed`
(which *is* deadline-aware, `absolute_deadline=compact_deadline,
cancelled=deadline_reached`) returned immediately, `search()` broke at its first
`self.deadline_reached()` (`sequence_solver.py:1058-1060`), and the refusal text
"deadline exhausted before finding an exact layout"
(`sequence_solver.py:1346`) was emitted with `self._incumbent is None`.

The cold-stage gap is nevertheless real and is fixed here too. `try_start`
(`sequence_solver.py:620-634`) admits any role whose history is empty whenever
`remaining > 0.0`, because `required = history.speculative_s +
history.completion_s` is `0.0` and the guard is
`remaining <= 0.0 or (required > 0.0 and remaining <= required)`. The admitted
stage then runs `_anneal_restarts` -> `anneal_stage`, whose only bound is
`AnnealConfig.moves_per_stage = 2_000` (`sequence_pair.py:353`), a move count
with no clock; and `_route_archive` (`sequence_solver.py:2002-2150`), whose
candidate loop calls `self.adapters.prepare(...)` per elite with no
`self.deadline_reached()` check.

### 2.3 Cancellation that already exists, and cancellation that does not

Deadline-aware today: `prepare` (checks `deadline_reached()` and threads
`cancelled=deadline_reached` into `_prepare_routing_problem`,
`sequence_solver.py:4360-4425`), `global_route` (`:4489-4515`), `detailed_route`
(`:4524-4544`, and `_route_detailed_candidate(deadline=deadline)`),
`solve_compact_seed`, the topology-beam refinement, and `certify`
(`:4558-4620`, on a *separate* `completion_deadline = deadline +
ATOMIC_COMPLETION_GRACE_S`). Freeform threads one deadline from `lay_out`
through every phase and polls it every `_DEADLINE_CHECK_EVERY = 4096`
expansions (`freeform.py:_expired`, `_DEADLINE_CHECK_EVERY`).

Not deadline-aware today: `_variant_direct_eligibility` (2.2), `anneal_stage`,
`_route_archive`'s candidate loop, and — at the pipeline level —
`finalize.compact_open_boundary_belts` and `validate.validate`
(`pipeline.py:569-613`). `finalize.finalize_placement` *does* accept
`cancelled: Callable[[], bool] | None` but `pipeline.py:576` does not pass it.
`validate.validate` has no cancellation parameter at all.

### 2.4 CPU

`os.cpu_count() == 128` and `len(os.sched_getaffinity(0)) == 128` on this
machine. `pyproject.toml` records the governing fact: "CP-SAT already saturates
the machine on its own -- a single solve runs at ~700% CPU", which is why pytest
is serial and why `flab2bp-web --workers` defaults to 1.

Only **one** CP-SAT solve in the tree is multi-threaded: freeform's `_pack`
(`freeform.py:3593`, `solver.parameters.num_search_workers = workers`), fed by
`FreeformLayout.workers`, which defaults to `DEFAULT_SEARCH_WORKERS = 0`
(`base.py`) — ortools' spelling of *all cores*. Every other solve is pinned to
one worker: `compact_seed.py:454`, `compact_seed.py:652`,
`freeform.py:8920` (tie-break), and `sequence_solver.py:4870`
(`DETERMINISTIC_WORKERS`). `scripts/audit.py` already computes
`per_cell_workers = max(1, cores // jobs_n)` and passes it to freeform only;
`_STRATEGIES["sequence-pair"]` ignores its `workers` argument entirely
(`audit.py:107-116`).

### 2.5 What a process already carries across a fork boundary

`src/flab2bp/layout/sequence_islands.py` is the working precedent.
`_SequenceIslandRequest` (frozen, `slots=True`) pickles `spec: BuildSpec`,
`time_budget_s`, `soft_deadline`, `power`, `band_policy`,
`belt_vertical_construction`, `strip_len`, `config: SequenceSolverConfig`,
`island_id`, `seed`, `compact_seed_attempt`, `compact_seed_base_seed`,
`compact_seed_config`. `_SequenceIslandOutcome` returns
`status: Literal["completed","refused","invalid"]`, an optional `Placement`,
and the refusal's `reason`, `spec_label`, `budget_s`,
`projection_failures: tuple[ProjectionFailureRecord, ...]` — `NoValidLayout` is
caught in the child and flattened, never pickled. `run_sequence_islands` uses
`ProcessPoolExecutor(max_workers=islands,
mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1)`, one
`wait(futures, timeout=...)`, and `_terminate_executor` (`future.cancel()`,
then `executor.terminate_workers()`, then `kill_workers()`, then
`shutdown(wait=False, cancel_futures=True)`).

Two facts this phase reuses directly:

- `soft_deadline` is an **absolute `time.monotonic()` value produced in the
  parent and consumed as `absolute_deadline` in the child**
  (`_sequence_island_deadlines`, `_run_sequence_island`). On Linux
  `CLOCK_MONOTONIC` is system-wide, so this already works and Phase D relies on
  the same guarantee rather than inventing a clock protocol.
- `_ISLAND_COMPLETION_GRACE_S = 90.0` is an order of magnitude larger than
  `ATOMIC_COMPLETION_GRACE_S = 5.0`. Phase D does not inherit 90 s.

## 3. Goals

Two gates, each measurable, each against the Phase C three-round files.

**Gate D1, wall discipline.** `scripts/audit.py --budget 30 --jobs 16`, both
explicit strategies, three rounds: per-cell `seconds` maximum at or under
35.0 s, `wall p95` at or under 30.0 s, no cell that was CLEAN in the
baseline becomes non-CLEAN, INVALID 0, CRASH 0, geometric-mean area over
jointly-CLEAN cells within `--noise-area 0.013`. Run before racing exists, so a
failure has one cause.

**Gate D2, racing.** `scripts/audit.py --budget 30 --jobs 16 --strategy all`
(freeform, sequence-pair, and `best`), three rounds, 108 cells:

- every `best` cell whose freeform **or** sequence-pair cell is CLEAN in the
  baseline is CLEAN. "The baseline" throughout this document means the single
  72-cell `baseline-budget30.jsonl` the plan's Task 1 generates on the Phase C
  tip this phase branches from, not Phase C's own round files;
- per-cell `seconds` maximum at or under 35.0 s, including `best` cells;
- the freeform and sequence-pair cells are not worse than Gate D1's rounds;
- for each `best` cell clean in both arms, `best` area is at most
  `(1 + 0.013) * min(freeform_area, sequence_pair_area)` in the same round.

Both gate records live under
`docs/superpowers/evidence/2026-09-02-phase-d-portfolio/`.

## 4. Non-goals

- No new search operator, no-good kind, or acceptance rule. Phase D transports
  Phase B's no-goods; it does not invent any.
- No change to routing, strip planning, or any objective.
- No learned scheduling, no bandit over strategies. The portfolio is exactly
  two arms and both always run.
- No cross-process or on-disk geometry cache. `geometry_memo` stays
  process-local and dies with its process; the two racers each pay their own
  preparation.
- No third strategy, no islands *between* the racers. `--sequence-islands`
  composes by living **inside** the sequence-pair child.
- No first-clean-wins early stop. The race runs to the deadline or to both
  finishing.

## 5. Architecture

### 5.1 Wall discipline

Five changes, smallest first.

**5.1.1 Bound the variant-direct-eligibility scan.** `_variant_direct_eligibility`
gains `cancelled: Callable[[], bool] | None = None` and polls it once per
`baseline` candidate and once per producer variant, returning `()` the moment it
fires. `()` is not a new outcome: it is exactly what the existing
`else ()` branch produces when the budget is too small, and
`solve_compact_seed(direct_eligibility=())` already handles it. The call site
passes a predicate over the `compact_deadline` computed on the line above, and
declines to start the scan at all with less than
`_DIRECT_ELIGIBILITY_MIN_REMAINING_S = 1.0` s of the compact share left. This
caps the scan at `ceiling * _COMPACT_SEED_WALL_SHARE` = 10 s of a 30 s budget,
against the measured 27 s.

**5.1.2 Cap a cold stage.** `_MeasuredStageAdmission` today knows only its
`deadline`, so it can express a cold-stage rule only in terms of `remaining` —
and `remaining > remaining * fraction` is vacuous for every fraction under 1.
It therefore gains the span it is bounding: `total_budget_s: float = 0.0`, set
by `_production_run` to the wall it actually has, `min(ceiling, max(0.0, deadline
- started))` (Ruling AJ: under `absolute_deadline` a raced child can be handed
`time_budget_s = 30` with five seconds of parent wall left, and a cold role
refused against a 7.5 s requirement never records history, so `ceiling` alone
would refuse every cold role for that child's whole life). For a role with no history
(`required == 0.0`) the requirement becomes

```
required = max(COLD_STAGE_MIN_RESERVE_S, COLD_STAGE_FRACTION * total_budget_s)
```

with `COLD_STAGE_FRACTION = 0.25` and `COLD_STAGE_MIN_RESERVE_S = 0.25`. On a
30 s budget a stage of unknown cost is refused with less than 7.5 s left; on a
1 s budget, with less than 0.25 s left. The `0.0` default — which every existing
construction takes until `_production_run` is edited — collapses `required` to
the floor, so an un-migrated caller keeps today's behaviour minus the last
quarter second. Once the role has history the existing rule applies unchanged,
so warm admission does not move.

**5.1.3 Poll the clock in the annealing loop.** `anneal_stage` gains
`cancelled: Callable[[], bool] | None = None`, checked every
`ANNEAL_DEADLINE_CHECK_MOVES = 256` moves inside `for move_index in
range(config.moves_per_stage)`; on a fire it breaks and returns the
`AnnealStageResult` built from the moves already made, with a new
`cancelled: bool = False` field (`compare=False`, like `backend`). With
`cancelled=None` — every existing caller and test — the loop is byte-identical.
`SequenceSolver._anneal_restarts` passes `cancelled=self.deadline_reached`.

**5.1.4 Poll the clock in the archive routing loop.** `_route_archive`'s
candidate loop breaks before `self.adapters.prepare(...)` when
`self.deadline_reached()` **and** `prepared_candidates` is non-empty. The first
candidate is always prepared, because `prepare` already short-circuits a passed
deadline into `preparation_error="deadline"` and `detailed_route` turns that into
`DetailedRouteStatus.BUDGET`, the existing tested path, while an empty
`prepared_candidates` would raise. The break does **not** reuse the existing
`completion_reserve_stop` (`sequence_solver.py:2036`): that flag's only reader
selects `global_skip_reason = "completion-reserve"`, a specific claim about the
measured completion reserve, and a deadline stop must not report itself as a
reserve stop. Ruling AK: the deadline stop only shortens the loop and writes no
stage telemetry of its own. An earlier draft had it select
`global_skip_reason = "deadline"` when `global_candidates` was empty, but with
the break placed before `prepare` that arm is unreachable: the stop can only
fire at candidate index one or later, and reaching a later index means the
previous candidate ran to the bottom of the body and appended its global
result. Global routing was never skipped, so no skip reason is true; the
already-prepared candidates are routed through the unchanged
`elif global_candidates:` branch. The observable effect is one fewer
`prepare` per deadline-crossing stage (the pre-change loop already stopped one
candidate later, after a post-deadline `prepare` returned a cancelled empty
result), visible only as a smaller `global_routes` count.

**5.1.5 Measure the attempt wall in the pipeline.** `pipeline.build` computes
`attempt_deadline = attempt_started + time_budget_s + ATOMIC_COMPLETION_GRACE_S`
per pair, passes `cancelled=lambda: time.monotonic() >= attempt_deadline` to
`finalize.finalize_placement` (which accepts it and is not given it today), and
writes two stats onto every returned placement:
`attempt_wall_s` and `wall_overshoot_s = max(0.0, wall - budget -
ATOMIC_COMPLETION_GRACE_S)`. `validate.validate` has no cancellation parameter,
so this is enforcement where a hook exists and *reporting* everywhere else —
see Risks.

### 5.2 Racing

New module `src/flab2bp/layout/strategy_race.py`.

**Process model.** One
`ProcessPoolExecutor(max_workers=len(RACE_STRATEGIES),
mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1)`, two
submitted tasks, one per strategy — the shape `run_sequence_islands` already
uses. Each child runs one strategy end to end, including its own finalize and
certification, and returns a `Placement` or a flattened refusal. The parent does
nothing but wait; it does not poll the queues (nobody in the parent consumes a
hint).

The queue topology is **hard-coded for exactly two arms**: one queue per
direction is a complete graph only for two, and `_install_race_channels` takes
exactly two queues and keys them by the two strategy names. `run_strategy_race`
therefore asserts `max_workers == len(RACE_STRATEGIES) == 2` at construction, so
a third strategy added later fails loudly at the assertion rather than silently
losing every message addressed to it.

**The child's wall.** A child cannot compute its own deadline from
`time.monotonic() + time_budget_s`: it starts spawn-cost seconds after the
parent started the clock, so it would run past the parent's wall by exactly that
cost. Both layouts therefore take the parent's absolute deadline:
`SequencePairLayout.lay_out` and `FreeformLayout.lay_out` each gain
`absolute_deadline: float | None = None`. Sequence-pair passes it straight into
`_production_run`, which already has the parameter and already prefers it over
`started + ceiling`. Freeform's `lay_out` computes
`deadline = started + ceiling if absolute_deadline is None else
absolute_deadline`, the same expression `_production_run` uses, and everything
downstream is unchanged because `lay_out` already threads exactly one `deadline`
through every phase. `_run_race_leg` passes `request.soft_deadline`.

**Request and outcome.** Mirroring `_SequenceIslandRequest` /
`_SequenceIslandOutcome`:

```python
@dataclass(frozen=True, slots=True)
class _StrategyRaceRequest:
    spec: BuildSpec
    #: ``RaceStrategyName``, i.e. Literal["freeform", "sequence-pair"] -- the
    #: same alias ``RACE_STRATEGIES`` is typed with, so a third name is a type
    #: error rather than a message nobody reads.
    strategy: RaceStrategyName
    time_budget_s: float
    soft_deadline: float  # absolute time.monotonic() from the parent
    band_policy: BandPolicy
    belt_vertical_construction: bool
    max_belt_z: Fraction  # for the child's own validate before publishing
    workers: int
    arrangements: int | None
    sequence_islands: int
    config: SequenceSolverConfig
    compact_seed_config: CompactSeedConfig
    share: bool


@dataclass(frozen=True, slots=True)
class _StrategyRaceOutcome:
    strategy: str
    status: Literal["completed", "refused", "invalid", "terminated", "crashed"]
    placement: Placement | None = None
    refusal_reason: str | None = None
    refusal_spec_label: str = ""
    refusal_budget_s: float = 0.0
    refusal_projection_failures: tuple[ProjectionFailureRecord, ...] = ()
    published_incumbents: int = 0
    consumed_incumbents: int = 0
    published_no_goods: int = 0
    consumed_no_goods: int = 0
    dropped_messages: int = 0
```

Every field is read: `config` and `compact_seed_config` go to
`SequencePairLayout(config=..., compact_seed_config=...)`, `workers` and
`arrangements` to `FreeformLayout(workers=..., arrangements=...)`, `max_belt_z`
to the child's own `validate.validate`. There is deliberately no `power` field:
both `FreeformLayout.lay_out` and `SequencePairLayout.lay_out` hard-code powered
emission, so a field carrying a constant would be a knob that does not turn.

What pickles, and nothing else: on the way out, `BuildSpec`, `BandPolicy`,
`SequenceSolverConfig`, `CompactSeedConfig`, a `Fraction` and scalars — every
one of which `_SequenceIslandRequest` already pickles per island. On the way
back,
`Placement` (its `buildings` tuple, its `stats` `TypedDict`, its `frame`) and
`ProjectionFailureRecord` — both already returned across this boundary by
`_SequenceIslandOutcome`. `NoValidLayout` is caught in the child and flattened
into `status="refused"`, never pickled, exactly as `_run_sequence_island` does.
The queues are **not** in the request: a `multiprocessing.Queue` cannot be
pickled as a task argument, so it is passed through the executor's
`initializer=_install_race_channels, initargs=(to_freeform, to_sequence_pair)`,
which reaches the child through `Process(args=...)` where queue inheritance is
supported. The child selects publish/consume from its own
`request.strategy`.

**Termination.** `soft_deadline = started + time_budget_s`;
`hard_deadline = soft_deadline + RACE_COMPLETION_GRACE_S`. One
`wait(futures, timeout=max(0.0, hard_deadline - time.monotonic()))`. Anything
still running is stopped with the module's own `_terminate_executor`, copied in
behaviour from `sequence_islands._terminate_executor` (`future.cancel()` on
every future, then `terminate_workers()`, then `kill_workers()`, then
`shutdown(wait=False, cancel_futures=True)`), and recorded as
`status="terminated"`. Both queues are closed in a `finally`, so a race that
raises cannot leave a feeder thread holding the parent open. The first
validator-clean result does not stop the race.

`RACE_COMPLETION_GRACE_S` is **measured, not guessed**. A child pays two costs
the serial path does not: spawn plus interpreter start plus unpickling the
`BuildSpec` before its first instruction, and its own atomic completion after
the wall. The grace is therefore
`ceil(measured spawn-to-first-instruction) + ATOMIC_COMPLETION_GRACE_S`, taken
on this box by a child that records `time.monotonic()` on entry against the
parent's submit time, over ten spawns, worst case. `ATOMIC_COMPLETION_GRACE_S`
is 5.0 and the measurement is expected to be well under a second, so the value
is expected to be 6.0; whatever it measures is recorded in the evidence
directory and written into the constant. It is deliberately not
`_ISLAND_COMPLETION_GRACE_S`'s 90.0: a grace that large is a second budget.

The spawn cost is inside the wall, not added to it: the parent starts the clock,
so a child that spends 0.4 s starting has 0.4 s less search than the serial arm
had. That is a real cost of racing and is named in Risks.

**CPU split.** `pipeline.build` gains `workers: int | None = None`, threaded
into `_new_layout` and hence into `FreeformLayout(workers=...)` — which it does
not set today, so a `best` build currently gives freeform's `_pack` all 128
cores. `strategy_race.race_worker_split(total)` returns
`(freeform_workers, sequence_pair_workers)`:

```python
RACE_FREEFORM_WORKER_SHARE = Fraction(3, 4)
RACE_MIN_WORKERS = 1


def race_worker_split(total: int) -> tuple[int, int]:
    if type(total) is not int or total < 1:
        raise ValueError("racing worker total must be a positive integer")
    if total <= 2:
        return (RACE_MIN_WORKERS, RACE_MIN_WORKERS)
    freeform = max(
        RACE_MIN_WORKERS,
        total * RACE_FREEFORM_WORKER_SHARE.numerator // RACE_FREEFORM_WORKER_SHARE.denominator,
    )
    return (freeform, max(RACE_MIN_WORKERS, total - freeform))
```

Freeform takes three quarters because it owns the tree's only multi-threaded
CP-SAT solve; sequence-pair's sub-solves are pinned at one worker each
(`compact_seed.py:454,652`, `sequence_solver.py:4870`), so its share is headroom
for its own process rather than a solver setting. `total` defaults to
`len(os.sched_getaffinity(0))` when `workers is None`, falling back to
`os.cpu_count() or 4` where `sched_getaffinity` is absent — the same guard
`scripts/audit.py`'s `_available_cores` already uses, because it is Linux-only.
**The value 0 is never
passed to a racer**: in ortools `num_search_workers = 0` means *all cores*, so a
split that ever produced 0 would hand one racer the whole box. `RACE_MIN_WORKERS
= 1` is the floor and `race_worker_split(1) == (1, 1)`, which oversubscribes a
single-core box by one thread and is the correct behaviour there.

Concrete defaults on this machine: standalone `pipeline.build(strategy="best")`
splits 128 into **(96, 32)**. Under `scripts/audit.py --jobs 16`, a cell's
`per_cell_workers` is `max(1, 128 // 16) = 8`, so a `best` cell splits into
**(6, 2)**. On a 4-core box a standalone race is (3, 1); on 2 cores or fewer it
is (1, 1).

### 5.3 Sharing

Two `multiprocessing.Queue(maxsize=RACE_QUEUE_MAXSIZE)` (default `64`), created
from the same spawn context: `to_freeform` and `to_sequence_pair`. One queue per
direction; each carries both message kinds, tagged by type.

```python
@dataclass(frozen=True, slots=True)
class IncumbentMessage:
    """A validator-clean placement one arm proved, as a bound for the other."""

    strategy: str
    #: ``(area, belt_tiles)``.  One field, not three: ``area`` and ``belt_tiles``
    #: as separate fields would be the same two numbers a second time, and
    #: ``height`` had no reader at all.
    exact_key: tuple[int, int]


@dataclass(frozen=True, slots=True)
class NoGoodMessage:
    """A Phase B cluster no-good, with the identity the receiver must match."""

    strategy: str
    instance_ids: tuple[StripInstanceId, ...]
    #: Phase B's ``ClusterRelationNoGood``, typed ``object`` on purpose:
    #: ``strategy_race`` is a transport and must import at a commit where
    #: ``last_mile`` may not exist yet.  The receiver -- which does know the
    #: type -- is what applies it.
    no_good: object
```

`StripInstanceId(family_id: StripFamilyId, machine_start: int, machine_count:
int)` (`strip_variants.py:480`) is a frozen, hashable, picklable value that both
strategies already build: freeform at `freeform.py:2952,2985,16844`,
sequence-pair through `PlacementProblem.instance_ids: tuple[StripInstanceId,
...]` (`sequence_pair.py:86`). It is the shared identity, so no new key is
invented.

**Publication, and what makes an incumbent publishable.** A strategy publishes
an `IncumbentMessage` at the exact point it already records a certified result:
freeform where `_sweep` sets `best, best_key = placement, key` with
`key = (placement.area, float(placement.stats["belt_tiles"]))`
(`freeform.py:16973-16980`); sequence-pair where `_complete_routing_stage` sets
`self._incumbent` after `verdict.ok` with `exact_key = _exact_key(finalized)`
(`sequence_solver.py:2204-2215`). The two keys carry the same two numbers in the
same order but are **not** the same type: freeform's `best_key` is
`tuple[int, float]` (it takes `float(placement.stats["belt_tiles"])`) and
`_exact_key(placement) -> tuple[int, int]`
(`sequence_solver.py:3010`) takes `int(...)`. The publish path therefore does
not forward `best_key`; it rebuilds the message key as
`(placement.area, int(placement.stats["belt_tiles"]))` from the placement it was
handed, so one `IncumbentMessage` schema serves both directions and both ends
compare `tuple[int, int]`. Freeform's own comparisons against its `best_key`
are untouched, and Python compares `int` against `float` correctly where the two
kinds meet.

Neither of those points is the parent's standard of proof. Freeform's `report`
there comes from its own in-sweep certification, and sequence-pair's `verdict`
comes from `certify`, which runs `validate.certify`, not `validate.validate`;
the parent runs the full `validate.validate(placement, spec, ids=_id_map(spec),
expect_power=True, max_belt_z=..., belt_vertical_construction=...)` on every
attempt and can still reject it. A bound derived from a placement the parent
will reject would prune the other arm's search on a promise nobody keeps.

**So a child runs `validate.validate` on its own placement before publishing,
and publishes only on `report.ok`.** The cost is one extra validation per
published incumbent — paid in the child, off the parent's critical path, and
bounded by how rarely an arm improves its incumbent. The child has everything
the call needs: `spec` from the request, `validate.id_map(spec)`, `max_belt_z`
and `belt_vertical_construction` from the request.

Publication is `put_nowait` inside `try/except queue.Full: pass`; a dropped
message is a lost hint and is counted, never an error.

**Consumption of an incumbent bound.**

- *Freeform: a second deadline, read only at the improvement sites.* The
  receiver drains its queue at the top of `_sweep`'s
  `while candidate_index < len(candidate_packs)` loop and keeps the smallest
  `exact_key` seen. The bound must never be able to make freeform *refuse*:
  every exit from that loop is a `break`, and a `break` taken with `best is
  None` ends the sweep with nothing. The loop guard at `freeform.py:16198`
  therefore keeps its `best is not None` term exactly as it is — an external
  incumbent adds no new exit.

  **`soft` itself is never rebound.** `_sweep` has seven references to it and
  they fall into two groups:

  | Site | Guarded by `best is not None`? | Kind |
  |---|---|---|
  | `:16112` `soft = time.monotonic() + share` | — | definition |
  | `:16200` (under the `:16198` guard) | yes, directly | improvement |
  | `:16301` (under the `:16299` guard) | yes, directly | improvement |
  | `:16309` (the `:16307` arrangement arm) | yes, via the `:16304` pre-break | improvement |
  | `:16319` `time.monotonic() >= soft` | yes, directly | improvement |
  | `:16144` inside `projection_retry_affordable` | **no** | finding |
  | `:16721` the learned-retry promotion | **no** | finding |

  The two finding sites are deliberately exempt from the soft-deadline breaks —
  each break is spelled `if not projection_retry and ...` (`:16299`, `:16304`,
  `:16308`, `:16319`) precisely so a retry is not charged as an improvement.
  `projection_retry_affordable` is called from `:16535`, `:16569`, `:16618`,
  `:16925` and `:16928`, and its answer decides whether a projection or
  exact-evidence retry is admitted at all. Rebinding the enclosing `soft` would
  set it to `now` for the rest of the sweep and refuse **every** retry, so a
  spec that only routes after a retry would refuse under racing where the
  unraced arm succeeds. That is a refusal manufactured by an external
  incumbent, which this design forbids.

  The bound is therefore carried in a **separate value**, `improvement_soft`,
  recomputed each iteration and read at the four improvement sites only. `soft`
  keeps its own value everywhere else, `projection_retry_affordable` and the
  `:16721` promotion included.

  ```python
  def _portfolio_soft_deadline(
      soft: float,
      external_key: tuple[int, int] | None,
      best_key: tuple[int, float] | None,
      now: float,
  ) -> float:
      """The IMPROVEMENT deadline, which is never this sweep's own ``soft``."""
      if external_key is None:
          return soft
      if best_key is not None and external_key > best_key:
          return soft  # the portfolio's is worse than ours: it says nothing
      return min(soft, now)
  ```

  The key comparison is the second half of "participates exactly as an own
  `best_key` would": an incumbent this sweep has already beaten is not a reason
  to stop polishing. Both keys are `(area, belt_tiles)` in that order, so `>` is
  the same lexicographic rule `best_key` is selected by, and `int` against
  `float` compares correctly. `external_key` never enters `best_key`, so it can
  never select or reject a placement — only shorten the polish. With no own
  `best`, all four improvement sites are unreachable and freeform sweeps to its
  hard `deadline` exactly as it does today.
- *Sequence-pair: strict, on area alone.* `SequenceSolver` gains
  `portfolio_area: Callable[[], int | None] | None = None`. `search()` drains
  before each stage and filters both selection points — the `discovery` lookup
  and the `eligible` comprehension — with

  ```python
  def _portfolio_pruned(self, height_state) -> bool:
      bound = None if self.portfolio_area is None else self.portfolio_area()
      return bound is not None and height_state.problem.area_lower_bound > bound
  ```

  **Strict `>`, not `>=`, and area only.** Full exact keys cannot be compared
  here: `PlacementProblem.area_lower_bound` (`sequence_pair.py:85`) is an area
  and there is no per-height lower bound on belt tiles, so the second component
  of the key has no counterpart. The winner is chosen on `(area, belt_tiles)`
  lexicographically, so a placement of *equal* area with fewer belt tiles beats
  the incumbent — and `>=` would prune exactly the heights that could produce
  it. `>` keeps every height that could still tie on area, and drops only those
  that provably cannot even reach it. When pruning empties both sets,
  `termination = "portfolio-bound"` and the reason table gains
  `"portfolio-bound": "every scheduled height's area lower bound is above the
  portfolio incumbent"`. Note that `search()` *raises* `NoValidLayout` with that
  reason when no incumbent was found — inside a race that is correct, since a
  bound exists only because the other arm certified something.

**Consumption of a no-good, and the strip-identity assertion.** The predicate is

```python
def applicable_no_good(message, planned: frozenset[StripInstanceId]) -> bool:
    return bool(message.instance_ids) and set(message.instance_ids) <= planned
```

and it is evaluated **at application time against the receiver's current strip
set**, never against a snapshot taken when planning first finished. Freeform
replans strips mid-sweep — `replan_strips_for_learned_geometry` rebuilds
`strips` and then clears `direct_relation_no_goods` and
`direct_relation_no_good_keys` (`freeform.py:16179-16182`) precisely because
"these proofs carry offsets, widths, or relation rows from the old strip
geometry... retaining them can forbid a relation the widened strip just made
feasible." A cross-process no-good is that same kind of proof, so it obeys that
same rule: it is admitted only against the strip set in force at the moment it
would constrain a solve, and a queued message whose ids are not a subset of the
*current* set is not applied on that application; it stays in the inbox
(Ruling AM: a later replan may make it match again, and freeform clears its own
relation no-goods on replan, so a message consumed on first match could never
be re-supplied). `dropped_messages` counts only what no strip set could ever
match (empty ids), what the inbox cap evicted, and what a full queue refused.
A matched message is re-judged on every application and never consumed, so
each receiver dedupes what it has already applied. The inbox therefore holds
undecided messages and the receiver supplies its current
`frozenset[StripInstanceId]` on each application — freeform from its live
`strips` list, sequence-pair from the live `problem.instance_ids`.

Only a message that passes is applied — freeform by adding the disjunction to
`_pack` the way `_DirectRelationNoGood` (`freeform.py:2803`) is modelled,
sequence-pair by the Phase C relation exclusion. Instance ids embed
`machine_start` and `machine_count`, so a receiver whose strip plan sharded
differently fails the predicate by construction. A dropped no-good costs a hint;
an applied wrong one would forbid a legal placement.

**No geometry memo crosses the boundary.** `geometry_memo` is `id(spec)`-keyed
and process-local (`geometry_memo.py`); each child builds its own. That
constraint stands.

### 5.4 Result selection

`run_strategy_race(...)` returns `tuple[_StrategyRaceOutcome, ...]` in a fixed
order (`RACE_STRATEGIES = ("freeform", "sequence-pair")`), never in completion
order and never a winner. The parent walks the futures in that same order when
it collects results, so which of two simultaneously crashed arms raises is
fixed, not a set-iteration accident.
`pipeline.build` turns each `completed` outcome into an `Attempt` through the
unchanged per-attempt path — `compact_open_boundary_belts` /
`finalize_placement` when `completion is not COMPACTED_AND_FINALIZED`, then
`validate.validate`, `markers.mark_external_belts`, `codec.encode` — and each
`refused`, `terminated`, or `crashed` outcome into a `LayoutAttemptFailure` with
its reason. `AttemptProgress` still fires `started` for both pairs before the
race and `laid-out`/`refused` per outcome after it. Selection stays
`pool = valid or attempts; best = min(pool, key=lambda a: a.area)`
(`pipeline.py:670-692`), untouched.

Two attempts therefore still reach `Build.attempts`, so
`web/payload.py:_attempt_detail`'s per-attempt reporting is unaffected.

### 5.5 Determinism

Racing does not make an already-deterministic build nondeterministic; it adds
one source to a set that is not empty today. `freeform._pack`'s
`deterministic=False` path is bounded only by
`solver.parameters.max_time_in_seconds`, a wall-clock cutoff
(`freeform.py:3595-3599`), and the tree's own comment block records clean-cell
counts varying 69-72 of 72 across repeated audit runs at a fixed budget.

The claim this design does make, and tests:

- With `share=False`, each child reproduces the serial arm's decisions exactly
  given the same wall: seeds are unchanged (`freeform._PACK_RANDOM_SEED =
  20260822`, `SequenceSolverConfig.seed = 20260824`,
  `_serial_compact_seed_attempt` still selects the serial compact-seed index),
  and no message alters control flow.
- With `share=True`, the messages a strategy receives depend on when the other
  published, so the *schedule* is not reproducible. Every message is a bound or
  a proved exclusion, so neither can make a result worse than the same arm
  without sharing would have found within the same clock — but which of two
  equal-area placements wins may differ between runs, exactly as it may today.
- `run_strategy_race(..., share=False)` under a stubbed executor is the parity
  fixture.

## 6. Interfaces

### 6.1 New module

```python
# flab2bp.layout.strategy_race
RACE_STRATEGIES: tuple[Literal["freeform", "sequence-pair"], ...]
RACE_COMPLETION_GRACE_S: float  # measured spawn cost + 5.0; see 5.2
RACE_QUEUE_MAXSIZE: int  # 64
RACE_DRAIN_MAX_MESSAGES: int  # 32
NOGOOD_INBOX_MAX: int  # 256
RACE_FREEFORM_WORKER_SHARE: Fraction  # Fraction(3, 4)
RACE_MIN_WORKERS: int  # 1
DEFAULT_RACE_MAX_BELT_Z: Fraction  # catalog.DEFAULT_MAX_BELT_Z


def race_worker_split(total: int) -> tuple[int, int]: ...


class _MessageQueue(Protocol):
    """The two methods this module needs from a queue.

    A ``multiprocessing.Queue`` and a ``queue.Queue`` both satisfy it and share
    no base class, so this is what lets one ``RaceChannels`` serve the real race
    and the in-process tests without an ``Any`` or a ``type: ignore``.
    """

    def put_nowait(self, item: object, /) -> None: ...
    def get_nowait(self) -> object: ...


@dataclass(frozen=True, slots=True)
class IncumbentMessage: ...


@dataclass(frozen=True, slots=True)
class NoGoodMessage: ...


@dataclass(frozen=True, slots=True)
class _StrategyRaceRequest: ...


@dataclass(frozen=True, slots=True)
class _StrategyRaceOutcome: ...


class RaceChannels:
    publish: _MessageQueue
    consume: _MessageQueue

    def publish_incumbent(self, message: IncumbentMessage) -> None: ...
    def publish_no_good(self, message: NoGoodMessage) -> None: ...
    def drain(self) -> tuple[IncumbentMessage | NoGoodMessage, ...]: ...
    def close(self) -> None: ...  # cancel_join_thread on the publish end
    @property
    def dropped(self) -> int: ...


def applicable_no_good(message: NoGoodMessage, planned: frozenset[StripInstanceId]) -> bool: ...


class _NoGoodInbox:
    """Holds UNDECIDED messages; the predicate runs at application time.

    Bounded at ``NOGOOD_INBOX_MAX`` (default 256).  A message is held until some
    strip set matches it, so an unbounded inbox would grow for the whole solve
    on a receiver whose strips never match -- exactly the case the identity
    predicate exists for.  The OLDEST is dropped first and counted: a no-good
    proved earlier is the one most likely to name strips a later replan has
    already invalidated.
    """

    def offer(self, message: NoGoodMessage) -> None: ...
    def applicable(self, planned: frozenset[StripInstanceId]) -> tuple[object, ...]: ...
    @property
    def dropped(self) -> int: ...


def run_strategy_race(
    spec: BuildSpec,
    *,
    time_budget_s: float,
    band_policy: BandPolicy,
    belt_vertical_construction: bool,
    max_belt_z: Fraction = DEFAULT_RACE_MAX_BELT_Z,
    workers: int | None = None,
    arrangements: int | None = None,
    sequence_islands: int = 1,
    config: SequenceSolverConfig | None = None,
    compact_seed_config: CompactSeedConfig | None = None,
    share: bool = True,
    submit: RaceSubmit | None = None,  # test seam; None uses the pool
    monotonic: Callable[[], float] = time.monotonic,  # test seam for the wall
) -> tuple[_StrategyRaceOutcome, ...]: ...


class RacingLayout:  # satisfies base.LayoutStrategy
    name: str = "best"

    def __init__(
        self,
        band_policy: BandPolicy,
        *,
        workers: int | None = None,
        arrangements: int | None = None,
        belt_vertical_construction: bool = True,
        sequence_islands: int = 1,
        share: bool = True,
        max_belt_z: Fraction = DEFAULT_RACE_MAX_BELT_Z,
    ) -> None: ...
    def _merge(self, outcomes: Sequence[_StrategyRaceOutcome]) -> Placement: ...
    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,  # accepted and ignored: a race
    ) -> Placement: ...  # owns its own children's walls
```

`max_belt_z` defaults to `validate.validate`'s own default, which is what
`scripts/audit.py` effectively uses today: `run_cell` passes only
`belt_rules.vertical_construction` to a strategy and never a belt ceiling. It is
a parameter rather than a constant because the child's pre-publication
validation must judge by the same rule the parent will.

`RacingLayout.lay_out` merges for callers that want one placement (the audit
`best` cell): `min(completed, key=lambda o: (*_exact_key(o.placement),
RACE_STRATEGIES.index(o.strategy)))`, raising `NoValidLayout` naming both arms'
reasons when neither completed — the shape
`_merge_sequence_island_outcomes` already uses.

### 6.2 Changed signatures

```python
# flab2bp.layout.sequence_solver
def _variant_direct_eligibility(
    spec, strips, problem, *, band_policy,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[VariantDirectInsertTarget, ...]: ...

_DIRECT_ELIGIBILITY_MIN_REMAINING_S: float   # 1.0
COLD_STAGE_FRACTION: float                   # 0.25
COLD_STAGE_MIN_RESERVE_S: float              # 0.25

@dataclass(slots=True)
class _MeasuredStageAdmission:
    deadline: float
    monotonic: Callable[[], float] = time.monotonic
    #: The attempt's WHOLE wall, set by ``_production_run`` from its ``ceiling``.
    #: ``0.0`` leaves only ``cold_floor_s``, which is what every caller outside
    #: ``_production_run`` gets.
    total_budget_s: float = 0.0
    cold_fraction: float = COLD_STAGE_FRACTION
    cold_floor_s: float = COLD_STAGE_MIN_RESERVE_S

class SequenceSolver[PreparedT]:
    def __init__(
        self, *, ...,
        portfolio_area: Callable[[], int | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
    ) -> None: ...
    def _portfolio_pruned(self, height_state: _HeightState) -> bool: ...

# flab2bp.layout.sequence_pair
ANNEAL_DEADLINE_CHECK_MOVES: int             # 256

def anneal_stage(
    problem, state, config, context=None, *,
    direct_targets_for_state=None,
    cancelled: Callable[[], bool] | None = None,
) -> AnnealStageResult: ...

@dataclass(frozen=True, slots=True)
class AnnealStageResult:
    ...
    cancelled: bool = field(default=False, compare=False)

# flab2bp.layout.freeform, and the same four hooks on SequencePairLayout.
# Every one is keyword-only and defaults to None, so a non-raced construction is
# unchanged.  There is deliberately no `on_planned_strips`: a snapshot of the
# strip set taken when planning finished would go stale on a replan, so
# `external_no_goods` is handed the CURRENT set on every call instead (5.3).
def _portfolio_soft_deadline(
    soft: float,
    external_key: tuple[int, int] | None,
    best_key: tuple[int, float] | None,
    now: float,
) -> float: ...
def _planned_instance_ids(strips: Sequence[Strip]) -> frozenset[StripInstanceId]: ...

class FreeformLayout:            # and SequencePairLayout
    def __init__(
        self, *, ...,
        portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
        external_no_goods: (
            Callable[[frozenset[StripInstanceId]], tuple[object, ...]] | None
        ) = None,
        publish_no_good: (
            Callable[[object, tuple[StripInstanceId, ...]], None] | None
        ) = None,
    ) -> None: ...

    def lay_out(
        self, spec: BuildSpec, *,
        time_budget_s: float = 15.0,
        # The PARENT's absolute wall, so a spawned child does not start a fresh
        # budget spawn-cost seconds late.  `base.LayoutStrategy.lay_out` gains it
        # too, so both implementations still satisfy the protocol.
        absolute_deadline: float | None = None,
    ) -> Placement: ...
```

### 6.3 `pipeline.build`, and the two-step contract change

Racing lands **off by default** and is switched on in its own commit only after
Gate D2 passes. A behaviour that halves a `best` build's wall time and doubles
its process count is not something to make live in the same commit that first
makes it possible, and an opt-in flag means every existing caller, test, and web
request keeps today's semantics while the racing code is reviewed and gated.

```python
def build(
    url: str, *,
    strategy: StrategyName = "best",
    ...
    workers: int | None = None,       # NEW: CP-SAT search workers, split when racing
    race: bool = False,               # NEW: opt in with race=True / --race
    share: bool = True,               # NEW: applies only when race=True
    sequence_islands: int = 1,        # now legal with strategy="best"
    ...
) -> Build: ...
```

**Step one (this phase's cutover task).** `race` defaults to `False`, so
`strategy="best"` runs the serial loop exactly as it does today: two solves, one
full budget each, `PRODUCTION_STRATEGY_COUNT` still the wall multiplier, every
existing `best` test green and untouched. `race=True` opts a caller in.
Gate D2 does not depend on the default: the audit's `best` cell constructs
`RacingLayout` directly, so it measures racing whatever `pipeline.build`
defaults to.

**Step two (the final task, only if Gate D2 passes).** The default flips to
`race=True` and the contract changes: a `best` build's wall time per candidate
becomes **one** `time_budget_s`, not two, and the web ceiling drops its strategy
factor:

```python
# flab2bp.web.jobs, AFTER the flip
MAX_SOLVER_SECONDS = 300.0  # unchanged


@property
def solver_ceiling_s(self) -> float:
    return self.effective_candidate_count * self.budget_s
```

The tests that encode the old arithmetic are repaired in that same commit and
nowhere earlier — they are correct until the flip. Every one, by name:
`tests/web/test_options.py:194-215` (`test_the_candidate_policy_ceiling_is_on_the_product_not_the_budget`),
`:228-229` (`test_best_ceiling_follows_the_selected_candidate_policy_subset`),
`:264` (`test_pinned_flow_effective_candidate_count_and_ceiling_are_one`),
`:267-276` (`test_candidate_ceiling_error_reports_the_effective_pinned_count`, whose
message assertion loses the strategy term);
`tests/web/test_jobs.py:322` and `:557` (both assert
`snap["solver_ceiling_s"] == ... * pipeline.PRODUCTION_STRATEGY_COUNT * 4.0`);
`tests/test_pipeline.py:336-345` (the `best` encode-failure test) and
`:393-405` (`test_best_reports_freeform_and_sequence_pairs`, whose progress
assertions the raced loop is designed to preserve).

Unchanged either way: `Build.attempts` still holds one `Attempt` per (candidate,
strategy) pair and `Build.refused` one `LayoutAttemptFailure` per refusal, so
every consumer of the result shape — `web/payload.py:_attempt_detail` included —
is unaffected. The guard `if sequence_islands != 1 and strategy !=
"sequence-pair": raise ValueError` (`pipeline.py:395-396`) becomes `... and
strategy not in ("sequence-pair", "best")` in step one. `flab2bp-web --workers`
(concurrent *builds*, `ThreadPoolExecutor`) is untouched and still defaults to 1
— once racing is live, one build saturates the box with two processes rather
than one, so raising it is worse advice than before, not better.

### 6.4 Test doubles that implement `LayoutStrategy`

Adding `absolute_deadline` to `lay_out` widens a protocol the suite implements
in several places, and Python only complains where the argument is actually
passed -- so these are enumerated here rather than discovered at the gate.

**Blocking, and not optional.** `tests/conftest.py` replaces
`FreeformLayout.lay_out` process-wide with a memoising wrapper
(`_install_memo(FreeformLayout)`, `tests/conftest.py:74-101`), and that
wrapper's signature is `(self, spec, *, time_budget_s=15.0)`. Once anything
calls `lay_out(..., absolute_deadline=...)`, **every** test that reaches
freeform through the wrapper raises `TypeError: lay_out() got an unexpected
keyword argument 'absolute_deadline'`. The wrapper's signature and its
`_key(layout, spec, time_budget_s)` (`:57-71`) both gain the parameter -- `_key`
because a memo whose key omits an input that changes the result returns the
wrong answer, which is worse than being slow. The `_Layout` protocol at `:48-49`
gains it too. `SequencePairLayout` is not memoised and needs no change there.

Flagged by strict mypy rather than by an exception: the `_StrategyFactory`
doubles at `tests/scripts/test_audit.py:106`, `:185`, `:311`, `:424` and the two
`monkeypatch.setitem` doubles at `tests/scripts/test_ab_compare.py:93`, `:153`.
These are `lambda workers, vertical: ...` values in dicts typed
`Callable[[int, bool], LayoutStrategy]` and `Callable[[bool], LayoutStrategy]`,
so 6.6's third factory argument changes their arity. Whole-project
`uv run mypy` against the locked 176-error baseline is the authority on which
need editing, and it is run inside the task that widens the signature rather
than left to the gate.

### 6.5 CLI

`src/flab2bp/cli.py` gains three flags and relaxes one rule:

- `--workers N` — CP-SAT search workers for this build. Default `None` = all
  cores for an explicit strategy, `race_worker_split(all cores)` for a raced
  `best`.
- `--race` — `race=True`. Opt-in, matching `pipeline.build`'s `race=False`
  default, until the final task flips both together (`--race` then becomes
  `--no-race`, `dest="race"`, `action="store_false"`).
- `--no-share` — `share=False`; race without the two channels.
- `--sequence-islands N` becomes legal with `--strategy best` as well as
  `--strategy sequence-pair`; the islands live inside the sequence-pair child.
  The existing `1 <= N <= 16` check and the
  `min(8, _available_cpu_count())` default are unchanged.

### 6.6 Audit

```python
# scripts/audit.py
# The factory gains a third argument.  `run_cell` validates the winner at
# `belt_rules.max_z` (`audit.py:325`), and a raced child that validates its own
# incumbent at a DIFFERENT ceiling would publish a bound the cell then rejects.
# The two existing lambdas ignore it: neither layout takes a belt ceiling, and
# only the racing child validates on its own.
_StrategyFactory = Callable[[int, bool, Fraction], LayoutStrategy]

_STRATEGIES["freeform"] = lambda workers, vertical, _max_belt_z: FreeformLayout(...)
_STRATEGIES["sequence-pair"] = lambda _workers, vertical, _max_belt_z: SequencePairLayout(...)
_STRATEGIES["best"] = lambda workers, vertical, max_belt_z: RacingLayout(
    BandPolicy("portable"),
    workers=workers,
    belt_vertical_construction=vertical,
    max_belt_z=max_belt_z,
)
_DEFAULT_STRATEGIES = ("freeform", "sequence-pair")          # unchanged
def strategy_names(requested: str) -> tuple[str, ...]:       # "all" -> the three
```

`run_cell`'s two construction sites pass `belt_rules.max_z` as the third
argument. The type is `Fraction`, not `int`:
`catalog.BeltAltitudeRules.max_z: Fraction`, and `validate.validate`'s own
default is `catalog.DEFAULT_MAX_BELT_Z`.

`--strategy` choices become `("both", "all", "freeform", "sequence-pair",
"best")`. `both` still means the two explicit arms and 72 cells; `all` adds the
36 `best` cells for 108. Every JSONL row gains two provenance fields, which the
shared-context constraint asked the first phase touching `audit.py` to add:

- `"route_backend"`: `flab2bp.layout.route_kernel.selected_backend()` read in
  the worker process. It is a property of the process, not of a placement, so it
  is present on REFUSED and CRASH rows too — which is the point, since a refusal
  under the Python fallback means something different from one under Cython.
- `"commit"`: `git rev-parse HEAD` read once in `main()` and copied onto every
  row, `"unknown"` if git is unavailable.

`scripts/audit_compare.py` needs no schema change: it keys on `(strategy,
url_id, spec_index)` and `"best"` is simply a third `strategy`. The gate passes
`--expect-cells 108`.

## 7. Failure handling

- **A strategy process crashes.** `future.result()` raises in the parent. The
  arm becomes `status="crashed"` with `refusal_reason = f"{strategy} strategy
  process failed: {type(exc).__name__}: {exc}"`, and the race is decided on the
  survivor. If *both* crash, `run_strategy_race` re-raises the first exception,
  so `scripts/audit.py` classifies the cell CRASH — the status its docstring
  reserves for "always a bug here".
- **A strategy ignores its deadline.** The parent's single
  `wait(timeout=hard_deadline - now)` returns it in `not_done`;
  `_terminate_executor` kills it at the OS level, and the arm becomes
  `status="terminated"` with the reason `f"{strategy} overran the
  {time_budget_s:g}s budget by more than {RACE_COMPLETION_GRACE_S:g}s and was
  terminated"`. The winner's stats carry
  `race_terminated: float` (arms killed) so the audit row's `detail` is not the
  only trace.
- **Queue backpressure.** Queues are bounded at `RACE_QUEUE_MAXSIZE`.
  Publishers use `put_nowait` in `try/except queue.Full: pass` and increment a
  drop counter; receivers drain with `get_nowait()` in
  `try/except queue.Empty: break`, at most `RACE_DRAIN_MAX_MESSAGES` per poll,
  so a burst can never turn a poll into a long pause. On exit each child calls
  `queue.cancel_join_thread()` on its publish queue: a `multiprocessing.Queue`
  with unflushed data otherwise blocks the child's exit until a reader arrives,
  and after the deadline there is no reader. Dropped and undrained messages are
  reported in the outcome and are never an error — every message is a hint whose
  absence only costs search, never correctness.
- **A no-good from a differently-planned strip set, or from before a replan.**
  Dropped by the identity predicate in 5.3, evaluated against the receiver's
  *current* strips, and counted. It cannot be applied, so it cannot forbid a
  legal placement.
- **`ClusterRelationNoGood` absent.** The transport (`NoGoodMessage`,
  `applicable_no_good`, `_NoGoodInbox`, the queue routing) types the payload as
  `object` and has no import of `last_mile`, so it builds, ships, and is tested
  against a stand-in payload at a commit where Phase B has not landed. Only the
  *wiring* task — which touches the two receivers' no-good collections — needs
  Phase B and Phase C on the branch, and the plan states that dependency in its
  Global Constraints rather than discovering it mid-task.
- **A published incumbent the parent later rejects.** Prevented, not handled:
  a child runs `validate.validate` before publishing (5.3) and publishes only on
  `report.ok`, so the bound the other arm prunes against has met the same
  standard the parent applies.

## 8. Testing

**Deadline tests, fake clock.** `_MeasuredStageAdmission` already takes
`monotonic: Callable[[], float]`, so cold-stage admission is tested with
injected times and no sleeping. With `deadline=100.0, total_budget_s=100.0`,
`COLD_STAGE_FRACTION * total_budget_s` is 25.0, so a cold role is admitted at
`now = 10.0` (90 s remaining, over 25.0) and refused at `now = 80.0` (20 s
remaining, under 25.0) and at `now = 99.9`; the arithmetic is written out in the
test's docstring so a later reader does not have to rederive it. A warm role's
decisions are byte-identical to the current implementation across a table of
`(speculative_s, completion_s, remaining)`. `anneal_stage`'s cancellation is
tested with a `cancelled` closure that fires after N polls, asserting the result
carries `cancelled=True`, no more accepted moves than the uncancelled run, a
`final_state` of the right size, a non-empty archive, and — with `cancelled=None`
— a result equal to today's. `_route_archive`'s is tested by driving one real
stage through `SequenceSolver._run_stage` with four merged elites and counting
`_FakeRouting.prepared_candidates`: 4 today, 1 after the change.
`_variant_direct_eligibility` is tested with a `cancelled` that fires on the
first poll (returns `()`), never (returns the full tuple, equal to the
un-parameterised call), and a counter proving it is polled more than once.

**Race tests, in-process stub strategies.** `run_strategy_race` takes a
`submit` seam; tests pass a synchronous stub that runs both arms in the current
process with `RaceChannels` backed by `queue.Queue`. Cases: both complete and
both outcomes are returned in `RACE_STRATEGIES` order; one refuses and the other
completes; one raises and the survivor decides; both raise and the first
exception propagates; one never returns and is reported `terminated` after
`RACE_COMPLETION_GRACE_S` on a fake clock; `share=False` delivers zero messages;
an incumbent published by one arm is consumed by the other and appears in
`consumed_incumbents`; a `NoGoodMessage` whose `instance_ids` are not a subset
is dropped and counted; `race_worker_split` over `{1, 2, 3, 4, 8, 16, 128}`
never returns 0 and always sums to `total` for `total >= 3`.

**Pickling tests.** `pickle.loads(pickle.dumps(x))` round-trips
`_StrategyRaceRequest` (built over a real small `BuildSpec` from
`tests/layout/test_freeform.py::two_stage_spec`, the fixture
`tests/layout/test_sequence_islands.py` already imports),
`_StrategyRaceOutcome` in each status, `IncumbentMessage`, and `NoGoodMessage`,
each compared by equality; and a test asserts a `multiprocessing.Queue` is
**not** a field of `_StrategyRaceRequest`, which is the mistake that would make
the pool fail only under `spawn`.

**Audit cell tests.** `scripts/audit.py`: `strategy_names("all")` returns the
three names; `_STRATEGIES["best"]` builds a `RacingLayout` with the cell's
workers; `record()` writes `route_backend` and `commit` on CLEAN, REFUSED, and
CRASH rows; `build_jobs` over the whole corpus with the three strategies yields
108 jobs. `scripts/audit_compare.py` needs no new behaviour, so its test asserts
that a 108-row candidate with `--expect-cells 108` passes and with the default
72 fails.

**Pipeline and web.** `pipeline.build(..., race=True)` produces the same
`Build.attempts` shape as the default `race=False` on a small spec (a
`strategy_race` stub); `sequence_islands=2, strategy="best"` no longer raises;
`wall_overshoot_s` and `attempt_wall_s` are present on every attempt's placement
stats. The web ceiling tests are unchanged until the flip task, which is where
`Options(strategy="best", budget_s=100.0).solver_ceiling_s == 300.0` replaces
the old `600.0` and the eight tests named in 6.3 are repaired.

**Gates.** The two corpus audits of section 3, run by script, with every JSONL
file and the `audit_compare.py` output committed under
`docs/superpowers/evidence/2026-09-02-phase-d-portfolio/`.

## 9. Delivery order

Starting point: the branch carrying Phase C's gate, whose tip is where Task 1's
`baseline-budget30.jsonl` is taken.

1. Evidence baseline; `route_backend` and `commit` on every audit row.
2. Bound `_variant_direct_eligibility` by the compact-seed deadline.
3. Cold-stage time cap in `_MeasuredStageAdmission.try_start`.
4. Clock poll inside `anneal_stage`.
5. Clock poll inside `_route_archive`, on its own `deadline_stop` flag.
6. Per-attempt deadline and overshoot stats in `pipeline.build`.
7. **Gate D1.** Three rounds at 30 s, two strategies.
8. Race messages, channels, and pickling.
9. Race executor, `absolute_deadline` on both `lay_out`, the measured
   `RACE_COMPLETION_GRACE_S`, termination, worker split.
10. Incumbent channel: validate-before-publish, freeform's `soft` consumption,
    sequence-pair's strict height pruning.
11. No-good predicate, inbox, and message routing — no dependency on Phase B.
12. No-good wiring into the two receivers' collections — **requires Phase B and
    Phase C on the branch.**
13. `RacingLayout` and its merge rule.
14. `pipeline.build` gains `workers` / `race=False` / `share`; islands guard
    relaxed.
15. CLI flags and the `best` audit cell.
16. **Gate D2.** Three rounds at 30 s, three strategies, 108 cells.
17. Flip `race` to `True`, drop the web ceiling's strategy factor, repair the
    eight tests named in 6.3. Only if Gate D2 passed.

Each step is a separate commit that leaves the tree green. A step whose gate
fails is reverted, not tuned around.

## 10. Relationship to A, B, and C

Phase A made an evaluation cheap and left the wall-clock tail and the serial
`best` untouched; its own risk section named the `quantum-chip/no-proliferator`
overshoot as "a cancellation gap" and left it for this phase. Phase B produces
`ClusterRelationNoGood`; Phase D is the only thing that moves one between
strategies, and it transports it without changing what it means. Phase C makes
both strategies find more per second, which is what makes an incumbent bound
worth publishing: a bound arrives only when a strategy certifies something, and
before Phase C the largest cells often certified nothing. Phase D shares Phase
C's no-goods and races Phase C's solvers; it adds no operator of its own.

Phase D's second gate is the first measurement of the portfolio as a portfolio.
Nothing before it could tell whether `best` was worth its two budgets.

## 11. Risks

- **The brief's overshoot attribution is wrong, and this spec overrides it.**
  The design brief and the Phase D research note both name cold-stage admission
  in `_MeasuredStageAdmission.try_start` as the cause of the 35-40 s
  `quantum-chip/no-proliferator` overshoot. Two stack-sampling runs (2.2) show
  `solver.search()` executing **zero** stages on that cell, so no admission
  decision was ever made; the whole budget and the whole overshoot are one
  uninterruptible `_variant_direct_eligibility` call in `_production_run`,
  guarded by a `not deadline_reached()` check that runs before it starts and
  never again. The code wins: 5.1.1 is the change that closes the measured gap,
  and 5.1.2 is kept because the admission gap is real, not because it is this
  cell's cause. If Gate D1's max wall does not fall below 35 s after 5.1.1
  alone, re-run the probe before adding anything. An independent review
  reproduced the attribution with a second probe: zero samples in
  `solver.search()`, every post-deadline frame under
  `_variant_direct_eligibility`.
- **The pipeline's "hard deadline" is not hard.** `validate.validate` has no
  cancellation parameter and `finalize.compact_open_boundary_belts` is called
  without one at `pipeline.py:570-574`. 5.1.5 therefore *reports* the overshoot
  and cancels only `finalize_placement`, which accepts `cancelled` and is not
  given it today. A cell whose validation alone exceeds the grace will still
  exceed the wall, and the gate will name it rather than hide it.
- **Two CP-SAT users on one box.** `pyproject.toml` records that one solve runs
  at ~700% CPU, and `web/jobs.py` defaults `--workers` to 1 for exactly that
  reason. Racing deliberately runs two solvers at once. The mitigation is the
  explicit split (5.2): freeform's `_pack` is the only multi-threaded solve, so
  it is the only one whose worker count needs bounding, and it is bounded. The
  residual risk is that both arms get less search than either did serially and
  `best` area regresses; Gate D2's per-cell area condition against the better of
  the two arms is the detector, and `--no-race` is the escape hatch.
- **The web contract changes under existing users.** After the flip a `best`
  request costs one budget per candidate instead of two, so
  `MAX_SOLVER_SECONDS = 300.0` admits requests it used to reject and a UI
  showing elapsed time against `solver_ceiling_s` will show a different scale.
  The ceiling value is left at 300.0 rather than halved, because halving it
  would take away capacity users already have. The two-step landing (6.3) is the
  mitigation: nothing about the web contract moves until Gate D2 has passed.
- **Spawn cost is inside the wall.** A child starts the budget the parent
  started, so spawn, interpreter start, and unpickling the `BuildSpec` come out
  of its search time — every arm gets that much less than the serial arm did.
  `RACE_COMPLETION_GRACE_S` is measured from that cost rather than guessed
  (5.2), which sizes the grace correctly but does not give the time back. On the
  largest cells, where preparation alone is seconds, a few hundred milliseconds
  is noise; on the trivial tier it is not, and the trivial cells are the ones
  with time to spare. Gate D2's coverage condition is the detector.
- **The lost geometry-memo warm start, knowingly paid.** `geometry_memo`'s own
  module docstring gives its motivating case as "the second strategy in a `best`
  build... re-derived what the first had proved". Serial `best` runs both
  strategies in one process against one `spec` object, so the second arm's
  preparation is warm: 0.5-1.6 s against the first arm's 1.9-4.6 s on
  `universe-matrix`. Racing puts each arm in its own process, so **both** arms
  pay the cold 1.9-4.6 s. That is up to ~3 s of the sequence-pair arm's 30 s
  budget handed back, against a 30 s saving from not running serially — the
  trade is heavily positive at the candidate level, and it is a real regression
  for the second arm considered alone. The constraint forbidding a cross-process
  geometry cache is what makes this unavoidable in this phase, and it stands.
- **Both arms get less CPU than either did serially.** Serial `best` gave
  freeform's `_pack` `DEFAULT_SEARCH_WORKERS = 0`, i.e. all 128 cores, for its
  whole budget. Raced, it gets 96 standalone or 6 under `--jobs 16`, while a
  second CP-SAT process competes for the same cores. `_pack`'s
  non-`deterministic` path is bounded by `max_time_in_seconds` alone
  (`freeform.py:3595-3599`), so fewer effective cores buys a *worse incumbent in
  the same wall*, not a longer solve — the regression is silent and shows up
  only as area. Gate D2's per-cell area condition against the serial baseline
  arms is the detector; `RACE_FREEFORM_WORKER_SHARE` and `--no-race` are the
  knobs, and neither is turned without re-running the gate.
- **The queue topology is hard-coded for two arms.** One queue per direction is
  a complete graph only for two strategies, and `_install_race_channels` keys
  exactly two. A third arm added later would silently receive nothing. The
  assertion `max_workers == len(RACE_STRATEGIES) == 2` in `run_strategy_race`
  turns that into a loud failure at construction.
- **Strip identity can go stale mid-run.** Freeform replans strips inside a
  sweep (`replan_strips_for_learned_geometry`), which changes `machine_start`
  and `machine_count` and therefore every `StripInstanceId`. A no-good admitted
  against the old set could forbid a relation the replanned strips just made
  feasible — the exact failure `freeform.py:16179-16182` clears the local
  relation no-goods to avoid. The mitigation is that the predicate runs at
  application time against the current set (5.3), never against a snapshot, so a
  replan drops every queued message that no longer matches.
- **Determinism under racing.** A shared message's arrival time is not
  reproducible, so a shared race's schedule is not reproducible. This is a
  degree, not a kind: the tree's own comment block records 69-72 of 72 clean
  cells across repeated audit runs at a fixed budget today, because
  `freeform._pack`'s non-deterministic path is bounded by wall clock. The
  testable claim is narrowed to `share=False` (5.5), and `--no-share` exists so
  a parity investigation has a switch.
- **Absolute monotonic times across processes.** `soft_deadline` is a parent's
  `time.monotonic()` consumed as a child's `absolute_deadline`, which is only
  valid because Linux `CLOCK_MONOTONIC` is system-wide.
  `sequence_islands.py` already depends on this in production, so the risk is
  inherited rather than introduced — but it is a portability constraint, and any
  move off Linux breaks both.
- **Cutting the annealer mid-stage.** 5.1.3 returns a partially annealed state
  when the clock fires. The result is a legal `AnnealState` and the archive is
  built from incumbents that were scored, so nothing invalid escapes; but a
  stage's outcome now depends on the wall in a place where it previously did
  not. `cancelled=None` is the default so every existing caller is unchanged,
  and the corpus gate is what decides whether the trade pays.
