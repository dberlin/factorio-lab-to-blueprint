# Phase C: ALNS Placement with a CP-SAT Window Repair

**Status:** Executed 2026-09-02/03 on branch `phase-c-alns` (merged master at 8ab701f; evidence d9aefd2 and 2ec8279); all three §3 gates FAILED, no regression: six interleaved 72-cell rounds at budget 30 (three from master a4501e0, three from the branch) give 66/72 CLEAN on both arms in every round, zero status flips in either direction, INVALID 0, CRASH 0, p95 28.4–28.8 s, paired area ratio 0.998–1.000, one CLEAN cell improved (`sequence-pair information-matrix/output-products`, 5394 → 5150). Gate 1 fails only on `feasibility_restart_batches >= 1` (an exact incumbent exists, so the continuation never runs; the cell was CLEAN at baseline). Gate 2: the four-cell refusal count did not fall. Gate 3: `universe-matrix/no-proliferator` refuses under freeform at the validator (`game.blueprint_area`, a 264 x 162 extent against the 160-segment band ceiling, unreachable by any placement-search repair) and under sequence-pair at the 30 s deadline (never `feasibility-exhausted`, so Ruling Z's condition for moving the bound is unmet). The evidence is at `docs/superpowers/evidence/2026-09-02-phase-c-alns/` (README carries the gate table, the machine-load lines and the suite re-run policy).

Why both repair arms are corpus-inert at HEAD, established by instrumented runs: (1) sequence-pair: the D-UCB selector pairs `LOCAL_EXACT_PACK` with `BAND_BOUNDARY` on every draw on the refusing cells, and that destroy set is either empty (the core already fits a band) or, uncapped, the whole problem, which `_alns_substitution`'s whole-problem guard drops before the window is asked; Task 7's scale cap (`cap_scale=True`) was first blamed and is now lifted for the window arm (Ruling AF, ed7f428, measured neutral), but the pairing is the real starvation; (2) freeform: the §5.7 trigger fires only where the clock refuses a wanted retry, and freeform exhausts its candidate list well inside 30 s on all 36 cells (Ruling AB). Neither is a defect in the operators themselves: unit and mutant coverage prove each arm does what §5 says when it is reached.

OPEN, ranked, for Phase D: (1) give the window a destroy set it can use: the destroy and repair ledgers each probe their untried arms first, so with two arms apiece they explore in lockstep and the window's first draw is structurally `BAND_BOUNDARY`; stagger that probe, or pair `LOCAL_EXACT_PACK` with `FAILED_ENDPOINTS`, or bound `_band_boundary`'s whole-problem fallback, so an exact solve is actually posed; (1b) the geometry-learned replan settles an already-routed in-flight choice unapplied (safe; costs the destroy ledger one measurement) and `window_metrics`'s docstring omits that `strips` is late-bound; (2) widen the freeform trigger to any routing failure with a slot and clock to spare (drop the `arrangement == 0 and (learned or feedback_retry)` conjunct, keep `retry_slot_found and not retry_admitted`), a spec change; (3) count `window_pack`'s early-return reasons separately (guard, whole-problem, unchanged, inexact) so the next gate can see why a window did not solve; (4) do not cut `C_WINDOW_SECONDS`/`C_WINDOW_DETERMINISTIC_WORK` (the measured sub-millisecond means are an artefact of inertness; a posed solve costs about 1 s); (5) delete the legacy `_lns_neighbourhood`/`_routing_feedback_substitution` pair (kept only as the equivalence oracle) once a corpus round certifies the new path; (6) `C_FEASIBILITY_RESTART_BATCHES = 8` stays (Ruling Z). Deviations from this text carried by rulings in the branch ledger: Z (§5.1 bound and reporting), AB (§5.7 trigger wording), AC (freeform arms only the window repair), AD (§5.7 remainder-based charge), AE (an equivalent mutant), AF (window scale uncapped). §6 gained `_RepairAdapters.window_installed` (sequence-pair counts `alns_window_accepted` at the install site; freeform counts a window that produced a different pack; never sum them). §8's graphene test asserts the continuation stays at zero because master fixed that cell before this phase.
**Revision:** 2 (2026-09-02). Revision 1's operator portfolio was cut from nine operators to four,
the selector's exploration bonus was moved out of the per-rank comparison, and the reward lost its
wall-clock divisor. Section 11 records the consequences.
**Companion specs:** `docs/superpowers/specs/2026-09-01-evaluation-throughput-design.md` (Phase A,
merged), `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md` (the program this
phase implements two sections of)
**Depends on:** Phase B (complete last-mile router with real no-goods), whose
`ClusterRelationNoGood` this phase consumes and whose `scripts/audit_compare.py` flags this phase's
gate uses
**Plan:** `docs/superpowers/plans/2026-09-02-phase-c-alns-window-repair.md`

Every `file:line` in this document was read at `b3c990a` on 2026-09-02. Line numbers are hints;
resolve each target by symbol name.

## 1. Decision

Make the placement search react to a routing failure with a *chosen* local repair instead of one
hardcoded one, and give it a repair that is exact rather than heuristic. Three changes, in this
order, each with its own gate:

1. **Feasibility-first continuation.** `SequenceSolver.search` stops at a derived stage limit even
   when the deadline has seconds left and no exact incumbent exists. When the caller is production
   (not an explicit `max_stages` probe), the search appends one deterministic feasibility restart
   per height and continues while the wall deadline, the measured stage admission, and the
   expansion ledger allow.
2. **`src/flab2bp/layout/sequence_alns.py`.** Two destroy operators and two repair operators behind
   immutable `OperatorContext` / `OperatorChoice` / `OperatorMetrics` / `OperatorOutcome` records,
   chosen by a deterministic discounted-UCB selector over a lexicographic reward. The existing
   `select_lns_neighbourhood` and `repair_neighbourhood` become the implementations behind
   `FAILED_ENDPOINTS` and `SEQUENCE_REINSERT`; nothing is deleted.
3. **`LOCAL_EXACT_PACK`.** One CP-SAT fix-and-reoptimize window: the freeform `_pack` formulation
   with every strip outside the window pinned to its current origin, `num_search_workers = 1`, a
   wall limit of `C_WINDOW_SECONDS`, and a deterministic-time bound. The same operator serves both
   strategies. In sequence-pair the repaired placement is re-encoded into a `SequencePair` by a new
   encoder; in freeform it replaces the full `_pack` re-solve when a full solve is unaffordable.

Nothing here changes what an evaluation concludes. Preparation, routing, finalization, validation,
the exact winner ordering `(area, belt_tiles)`, and every refusal reason for a candidate that is
actually evaluated are untouched. What changes is which candidates get evaluated.

**The portfolio is deliberately small.** Four operators ship, and each is here because a refusing
cell names its mechanism: `FAILED_ENDPOINTS` + `SEQUENCE_REINSERT` is the existing behaviour, kept
so the selector has a baseline arm to beat; `BAND_BOUNDARY` + `LOCAL_EXACT_PACK` is the mechanism
the "fits no latitude band" refusals name. The five operators the reliability spec also lists are
follow-ups (section 4) governed by one rule: **an operator is added when a refusing cell names its
mechanism.** The operator identity enums stay open so adding one is a new member and a new dispatch
branch, not a redesign.

## 2. Evidence

All figures from the Phase A three-round corpus at `--budget 30 --jobs 16`
(`docs/superpowers/evidence/2026-09-01-evaluation-throughput/candidate-budget30-round{1,2,3}.jsonl`):
65/72 CLEAN, INVALID 0, CRASH 0, p95 wall 30.4-30.7 s.

**The refusals this phase targets.** Four of the seven, all four at the placement layer:

| Cell | Strategy | Detail string | Budget-dependent? |
|---|---|---|---|
| `graphene/output-products` | sequence-pair | `no scheduled stage produced an exact layout` | No: refuses in ~2 s of a 30 s budget |
| `universe-matrix/no-proliferator` | sequence-pair | `deadline exhausted before finding an exact layout`; last placement extent 1334x131 fits no band | Partly |
| `universe-matrix/all-products` | sequence-pair | `deadline exhausted before finding an exact layout` | Partly |
| `universe-matrix/no-proliferator` | freeform | validator/projection rejection: `no legal DSP latitude band/orientation accepts the final placement` on a 507x163 extent | No |

The two refusals Phase B owns (`quantum-chip/all-products` and `universe-matrix/output-products`
under freeform, 1-2 nets stranded) and the one Phase D owns
(`quantum-chip/no-proliferator`, 35-40 s wall on a 30 s budget) are out of scope here.

**Why `graphene/output-products` is budget-independent.** `_search_stage_cap`
(`sequence_solver.py:3333`) returns `2` when `strip_count < _TOPOLOGY_BEAM_MIN_STRIPS` (7) and
`sprayed_lanes == _TINY_FAST_PATH_SPRAY_LANES` (2); graphene is a 6-machine spec. That `2` is
threaded through `_ProductionRun.max_search_stages` (`:3839`, set at `:5106`) into
`run.solver.search(max_stages=run.max_search_stages)` (`SequencePairLayout.lay_out`, `:5281`), where
it is a hard cap. `search` then falls out of its loop with `termination = "stage-limit"`, no
incumbent, and raises `NoValidLayout("no scheduled stage produced an exact layout")` (`:1344-1381`)
with 28 seconds unspent.

**Candidates evaluated per budget.** From
`docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-after.jsonl` at a 15 s budget on
`universe-matrix`: freeform prepares 3 candidates (`prepare_calls_s` `[2.19, 1.66, 0.53]`,
`[1.95, 1.43, 1.57]`), sequence-pair prepares 2 (`[2.19, 1.25]`, `[4.62, 3.95]`). On
`quantum-chip` freeform prepares 6 (`[1.03, 0.64, 0.83, 0.87, 0.73, 0.80]`). At 30 s freeform
routes 5 to 8 packs on the largest specs and sequence-pair gets a few stages. One preparation costs
1.9-4.6 s cold and 0.5-1.6 s warmed on `universe-matrix`; one A* pass costs 0.5-1.6 s at 1-4 million
expansions. These are the numbers gate 2 records as absolutes; the audit JSONL carries no
per-candidate column, so this phase adds `alns_evaluations` to `PlacementStats` rather than to the
audit schema.

**What that budget buys today after a failure.** Sequence-pair's only reaction is
`_routing_feedback_substitution` (`sequence_solver.py:2653`): one call to
`select_lns_neighbourhood` (`route_feedback.py:549`) through the thin wrapper `_lns_neighbourhood`
(`:2711`), then `repair_neighbourhood` (`sequence_pair.py:1508`) — a weighted-random remove-and-
reinsert in both permutations plus a random +/-1 gap nudge. Freeform's only reaction is a *full*
`_pack` CP-SAT re-solve over every strip with a new no-good or a strip replan
(`freeform.py:16669-16755`, `_proof_scoped_no_goods` at `:13681`). Neither can repair a region.

**The load-bearing negative result this design must respect.** The removed routing-capacity cut
(the comment block at `freeform.py:3268-3335`) measured four cheap routability surrogates on 270
real packs and got AUC 0.500, 0.500, 0.535, 0.525, 0.491, with cut-capacity slack anti-correlated at
0.422 as the control. No cheap proxy predicts routability. Therefore every operator in this design
is credited by *what the real router then did*, never by a surrogate, and the reward is observed one
evaluation later rather than estimated at selection time.

## 3. Goals

Three gates, each measured, each its own commit.

1. **Continuation gate.** `uv run python scripts/audit.py --budget 30 --jobs 4 --strategy
   sequence-pair --only graphene --json <candidate>` reports `graphene/output-products` CLEAN, and
   the placement stats for that cell carry `feasibility_restart_batches >= 1`.
2. **Window gate.** On `universe-matrix` under both strategies at `--budget 30`, the four cells in
   section 2 are recorded with their status, wall seconds, area, and `alns_evaluations` as
   **absolute numbers** in the gate file. The gate passes when the refusal count over those four
   cells falls against the Phase B baseline and no cell regresses.
3. **Corpus gate (the acceptance gate).** `uv run python scripts/audit.py --budget 30 --jobs 16`,
   both strategies, three rounds, compared to the Phase B round files with Phase B's
   `scripts/audit_compare.py --regressions-only --require-clean <cell>`:
   `graphene/output-products` and `universe-matrix/no-proliferator` under both strategies CLEAN in
   every round, no cell that was CLEAN in the baseline refuses, INVALID 0, CRASH 0, wall p95 per
   cell at or under 30 s, and paired geometric-mean area over cells clean in both arms no worse
   than `1 + 0.013`.

**Determinism is a property, not a gate line, and for the search state it is total.** The selector
reads no wall clock into its ledgers: the reward vector is a pure lexicographic improvement with no
time divisor, every RNG draw derives from `derive_stage_seed` (`sequence_pair.py:1242`), and every
CP-SAT window solve pins `num_search_workers = 1` with `max_deterministic_time` set, as
`compact_seed.py` already does at `:454` and `:652`. Therefore, for a fixed `config.seed` and a
fixed deterministic budget, **the sequence of operator choices is reproducible**, and so is the
placement each choice produces.

What is not deterministic, and never was, is *how many* choices happen: the wall clock decides how
many stages, candidates, and window solves fit. Two runs of the same cell on differently loaded
boxes can stop at different points and return different incumbents. This is the same escape clause
the rest of the solver carries, and the corpus gate compares CLEAN counts and area, never step
counts.

## 4. Non-goals

- **Five operators from the reliability spec are follow-ups, not this phase.**
  `BLOCKER_COMPONENT`, `CONGESTED_CUT`, `RELATED_CARGO`, `DIVERSIFY` (destroy) and
  `ROUTING_REGRET` (repair) are named in `DestroyOperator`/`RepairOperator` so the enums stay
  extensible, but no dispatch branch, no plan task, and no arm ships in this phase. The rule for
  adding one: **an operator is added when a refusing cell names its mechanism** — a cell whose
  detail string, blame walls, or telemetry says the failure is a blocker component, a congested
  cut, a cargo relation, or search stagnation. Adding one is then a new enum member, a new branch
  in `destroy_strips`, its unit tests, and a single-cell measurement.
- **`select_lns_neighbourhood`'s ring-growth branch stays off.** Production has never passed
  `stagnation`/`grow_after` (the wrapper `_lns_neighbourhood` at `sequence_solver.py:2711` uses the
  defaults), so the branch has never run on this corpus, and no refusing cell names stagnation as
  its mechanism. `FAILED_ENDPOINTS` passes `stagnation=0` and the branch stays dormant. It is a
  follow-up under the same rule.
- No learned selector beyond discounted UCB. No PyTorch or other training dependency.
- No new strip variant, pitch, pose, junction geometry, coater seating rule, or power rule.
- No cross-strategy sharing of incumbents or no-goods; that is Phase D.
- No fallback corridor tier and no deterministic feasibility constructor.
- No change to the routing kernel, the expansion budget constants (`_ROUTING_BUDGET = 2_000_000`,
  `_ROUTING_EXPANSIONS_PER_SECOND = 400_000`, `freeform.py:471`, `:487`), the compact-seed wall
  share (`_COMPACT_SEED_WALL_SHARE = Fraction(1, 3)`), or the arrangement schedule.
- No deadline-overshoot fix; `_MeasuredStageAdmission.try_start`'s missing cold-stage cap
  (`sequence_solver.py:622-636`) stays as it is and remains Phase D's.
- No change to CLI, web, or `pipeline.build` interfaces, and no change to `scripts/audit.py`'s
  JSONL schema.
- No new compiled code. Everything in this phase is Python over the existing Cython kernels.

## 5. Architecture

### 5.1 Feasibility-first continuation

`SequenceSolver.search` (`sequence_solver.py:1036`) derives

```python
stage_limit = (1 + (self.config.stages - 1) * self.config.restarts_per_height) * len(self._heights)
```

when `max_stages is None`, and loops `while sum(_counts_as_scheduled_stage(...)) < stage_limit`.
The exact change is a new keyword and a new branch at the top of the loop:

```python
def search(
    self,
    *,
    max_stages: int | None = None,
    feasibility_continuation: bool = False,
) -> SequenceSearchResult:
```

with the `while` condition becoming `while True` and the first statement inside:

```python
if sum(_counts_as_scheduled_stage(stage) for stage in self._stage_stats) >= stage_limit:
    if (
        not feasibility_continuation
        or self._incumbent is not None
        or feasibility_restart_batches >= C_FEASIBILITY_RESTART_BATCHES
        or self.budget.shared_left == 0
        or self.deadline_reached()
        or not self._append_feasibility_restarts()
    ):
        if feasibility_continuation and self._incumbent is None:
            termination = "deadline" if self.deadline_reached() else "feasibility-exhausted"
        break
    feasibility_restart_batches += 1
    stage_limit += len(self._heights)
    continue
```

Each batch adds exactly one stage per height, so the continuation buys at most
`C_FEASIBILITY_RESTART_BATCHES` extra stages per height, not a search that runs to the deadline;
Phase C's gate evidence decides whether the bound moves.

Everything else in the loop body is unchanged, so admission (`_start_measured_stage`), the
expansion ledger (`self.budget.shared_left`), and `deadline_reached()` keep their existing places
as the real stopping rules.

`_append_feasibility_restarts()` appends one `_RestartState` to every `_HeightState.restarts`
(`:786-807`) and returns `True` if it appended any:

- ordinal `restart = len(height_state.restarts)`;
- `seed = derive_stage_seed(derive_stage_seed(self.config.seed, height_state.order), restart)` —
  the identical derivation `_new_height_state` uses at `:2932-2934`, so a continuation seed is a
  pure function of `(config.seed, height order, restart ordinal)` and never of completion order;
- the starting state is the archived incumbent with the lowest `quality_archive_key` over every
  existing restart of that height, re-seeded with `replace(state, base_seed=seed, stage_index=0)`;
  when no archive entry exists, `AnnealState.initial(problem.size, seed)`.

The new restart has `stages = 0`, so `_select_height`'s eligibility test
(`any(run.stages < self.config.stages for run in height.restarts)`, `:1311-1315`) and
`_select_restart`'s `min(..., key=lambda r: (r.stages, r.restart))` (`:1423-1426`) pick it up with
no further change.

**This is also how the tiny fast-path cap stops ending the search.** `SequencePairLayout.lay_out`
passes `max_stages=run.max_search_stages` *and* `feasibility_continuation=True`, and so do the two
other `search()` call sites — `sequence_solver.py:5229` (`solver.search().placement`) and
`sequence_islands.py:139` (an island child that already carries its own deadline). For
`graphene/output-products`, `max_search_stages == 2`: two stages run under the cap, then the
continuation branch appends a batch and raises `stage_limit`. `_search_stage_cap` itself is not
changed, so its `0` (terminal exact seed) and `1` (no nets) cases keep their meaning — in both, an
exact incumbent already exists after the first stage and the branch above never fires. An explicit
`max_stages` from a test or probe defaults `feasibility_continuation=False` and stays a hard cap,
which the reliability spec requires.

`SequenceSearchResult` gains `feasibility_restart_batches: int = 0`, `PlacementStats`
(`base.py:198`) gains the `feasibility_restart_batches: float` key, and the production stats dict
(`sequence_solver.py:5390-5445`) writes it beside the existing `"termination"`. The `NoValidLayout`
reason map at `:1345-1351` gains
`"feasibility-exhausted": "feasibility continuation exhausted its restart budget before an exact
layout"`.

### 5.2 `sequence_alns.py`

A new module with no dependency on `sequence_solver`, so it is testable in isolation.

**Operator identities** (`StrEnum`; declaration order is the deterministic tie-break order):

```python
class DestroyOperator(StrEnum):
    FAILED_ENDPOINTS = "failed-endpoints"     # ships
    BAND_BOUNDARY = "band-boundary"           # ships
    BLOCKER_COMPONENT = "blocker-component"   # follow-up, no dispatch branch
    CONGESTED_CUT = "congested-cut"           # follow-up, no dispatch branch
    RELATED_CARGO = "related-cargo"           # follow-up, no dispatch branch
    DIVERSIFY = "diversify"                   # follow-up, no dispatch branch

class RepairOperator(StrEnum):
    SEQUENCE_REINSERT = "sequence-reinsert"   # ships
    LOCAL_EXACT_PACK = "local-exact-pack"     # ships
    ROUTING_REGRET = "routing-regret"         # follow-up, no dispatch branch
```

`SHIPPED_DESTROY` and `SHIPPED_REPAIR` are module constants naming the members that have a dispatch
branch. `destroy_strips` raises `NotImplementedError` for a follow-up member, and `OperatorSession`
defaults its arms to the shipped tuples, so a follow-up member can never be selected by accident.

**Records** (all frozen, slotted). Every field has a reader; nothing is carried for decoration:

```python
@dataclass(frozen=True, slots=True)
class OperatorContext:
    strip_count: int          # read by operator_scale
    stagnation: int           # read by operator_scale
    remaining_fraction: int   # read by OperatorSession.select: gates LOCAL_EXACT_PACK
```

- `OperatorChoice(destroy, repair, scale, ordinal)` — `scale` is the destroy cardinality,
  `ordinal` the monotonically increasing selection index, used for deterministic ordering in
  telemetry and as the seed component for any future randomized operator.
- `OperatorMetrics(validator_clean, failed_nets, band_overflow, congestion, area)` — the five
  measured quantities the reward ranks over, in rank order. `congestion` is the summed
  `FeedbackState.cell_history` weight over the failure walls of the evaluated candidate;
  `band_overflow` is `max(0, used_height - outline_height) + max(0, width - band_target_width)`;
  `area` is `width * used_height` — the *realized* extent, not `width * outline_height`, because
  the outline is a search parameter and the extent is what gets built and validated.
- `OperatorOutcome(choice, before, after, applied)` — `applied=False` when the destroy set was
  empty or the repair returned nothing, which is credited as a zero-reward observation so a
  chronically inapplicable operator loses its turn rather than being retried forever. The record
  carries **no** measured seconds: `reward_vector` reads only the two metric snapshots, and a field
  nothing reads is a field that invites someone to read it. Measured routing seconds reach the
  session through `observe(..., routing_seconds=...)`, which sums them into
  `OperatorSession.routing_seconds` for telemetry and nothing else.

**Selector.** `OperatorSession` holds two independent discounted-UCB ledgers, one over the shipped
`DestroyOperator` arms and one over the shipped `RepairOperator` arms. Per arm it keeps a discounted
count `n[a]` and one discounted reward sum `w[a][r]` per reward rank `r` in `0..4`. On each
observation, every arm's `n` and `w` are multiplied by `C_DUCB_DISCOUNT` first, then the played
arm's are incremented:

```
n[a]    <- C_DUCB_DISCOUNT * n[a]      for every arm a
w[a][r] <- C_DUCB_DISCOUNT * w[a][r]   for every arm a, every rank r
n[played]    += 1.0
w[played][r] += reward[r]
```

The score of arm `a` is a six-component tuple: the five **mean** rewards, then the exploration
bonus **once**, as the final tie-break:

```
score(a) = (w[a][0]/n[a], w[a][1]/n[a], w[a][2]/n[a], w[a][3]/n[a], w[a][4]/n[a], bonus(a))
bonus(a) = C_DUCB_EXPLORATION * sqrt(log(N) / n[a])          N = sum(n[b] for every arm b)
```

Selection is `max` over arms comparing that tuple lexicographically after quantizing each mean to
`C_DUCB_SCORE_QUANTUM = 1e-9`, ties broken by declaration order. An arm with `n[a] == 0.0` sorts
above every scored arm, so **every arm is played once before any arm is played twice**, in
declaration order; `log(N)` uses `math.log(max(N, math.e))` so the bonus is never negative. No RNG
is consulted anywhere in selection.

Adding the bonus once rather than per rank is what makes the ordering mean what it says: a bonus
added to every component would let exploration on rank 4 outvote a real difference on rank 1, which
is exactly the exchange a lexicographic reward exists to forbid.

`select` also filters the repair arms by affordability: `LOCAL_EXACT_PACK` is dropped from the
candidate arms when `context.remaining_fraction < C_WINDOW_FRACTION_FLOOR`, because a window solve
started with no room to finish spends `C_WINDOW_SECONDS` and buys nothing — the same argument
`_room_for_another` (`freeform.py:16984`) makes about a whole candidate. When every repair arm is
filtered out, the unfiltered set is used, so `select` always returns a choice.

**Reward.** Lexicographic, exactly the reliability spec's ordering, with **no divisor**:

| Rank | Quantity | Improvement |
|---|---|---|
| 0 | exact validator-clean placement | `1.0 if after.validator_clean and not before.validator_clean else 0.0` |
| 1 | failed-net count | `float(max(0, before.failed_nets - after.failed_nets))` |
| 2 | projection/band overflow | `float(max(0, before.band_overflow - after.band_overflow))` |
| 3 | stranded/congestion measure | `max(0.0, before.congestion - after.congestion)` |
| 4 | exact area | `max(0, before.area - after.area) / before.area`, and `0.0` unless `after.validator_clean` |

Rank 4 is gated on a clean placement so area can never be exchanged for validity, which is the
property the reliability spec asks for.

The reliability spec's "divide improvement by measured detailed-routing seconds within its rank"
is **not implemented**. A wall-clock divisor makes the ledger a function of machine load, so the
same seed on a busy box selects a different operator, and the corpus audit runs 16 cells in
parallel by design. Determinism of the search state is worth more than a cost normalization whose
own denominator is dominated by preparation rather than by the operator (1.9-4.6 s of preparation
against a 1.0 s window). Measured seconds are still summed into
`OperatorSession.routing_seconds` and reported, so the trade stays visible in the gate file — they
just never touch a ledger.

**Scale.** Not learned; a pure function of the context, so the arm count stays at 2 + 2:

```python
def operator_scale(context: OperatorContext) -> int:
    base = max(C_MIN_DESTROY_STRIPS, round(C_SCALE_FRACTION * context.strip_count))
    grown = base + C_SCALE_GROWTH * context.stagnation
    return max(1, min(grown, C_MAX_DESTROY_STRIPS, max(1, context.strip_count - 1)))
```

`context.strip_count - 1` keeps a destroy set from becoming the whole problem, which is the guard
`_routing_feedback_substitution` already applies at `:2688-2691`.

**Where it runs.** `_alns_substitution` replaces `_routing_feedback_substitution` at both of its
call sites — `sequence_solver.py:1555` (the compact-seed feedback closure) and `:2433` (the
ordinary stage boundary, inside `if starting_mode is ObjectiveMode.EXPLORATION`). It keeps the same
return type `tuple[AnnealState, frozenset[int]]`, so the surrounding code
(`if neighbourhood and restart.stages < self.config.stages: height_state.feedback_restart = ...`)
is unchanged. `_routing_feedback_substitution` stays in the file as the implementation behind the
`FAILED_ENDPOINTS` + `SEQUENCE_REINSERT` pairing.

The credit for a choice is observed one call later: `OperatorSession.observe_and_select(metrics,
context, routing_seconds=...)` first credits the pending choice with the metrics of the candidate
that choice produced, then selects the next one. The first call has no pending choice and no
baseline, and only selects. This is what keeps the design honest against the AUC-0.5 finding — an
operator is paid by what `_route_all` did, never by a proxy.

**Note on the brief.** The brief placed the fixed neighbourhood rule in
`_pose_stage_boundary_update`. The code disagrees: `_pose_stage_boundary_update`
(`sequence_solver.py:3739`) is the split/merge topology step built on `select_split_candidate` and
`merge_stage_boundary`, and the neighbourhood rule lives in `_routing_feedback_substitution`. The
selector goes where the neighbourhood rule actually is. `select_split_candidate` remains the split
step inside `_pose_stage_boundary_update`, untouched.

### 5.3 The two shipped destroy operators

Each returns `frozenset[int]` of strip indices, capped at `choice.scale`, deterministic, and empty
when its evidence is absent (which the session credits as `applied=False`).

| Operator | Implementation |
|---|---|
| `FAILED_ENDPOINTS` | `route_feedback.select_lns_neighbourhood(result, pair, gaps, problem, decoded, stagnation=0, grow_after=C_GROW_AFTER)`, then truncated to `scale` by ascending strip index. Existing code, called with the parameter values production has always used. |
| `BAND_BOUNDARY` | Return the strips whose decoded right edge `decoded.x[i] + problem.sizes[i][0]` exceeds `band_target_width`, ranked by descending right edge then ascending index. If none exceed it but the placement still overflows the outline height, return the strips with the largest right edges. When the placement fits a band and does not overflow, return `frozenset()`. |

`finalize.band_target_width(envelope, *, height, width) -> int` is a new pure helper over the
existing `finalize.BandPolicySearchEnvelope` (`finalize.py:99`): the largest `w <= width` for which
`envelope.frame_candidates(w, height)` is non-empty. `envelope.frame_candidates` returning `()` is
exactly the condition whose failure text is `finalize.ProjectionRefusal`'s "no legal DSP latitude
band/orientation accepts the final placement" (`finalize.py:80-84`), which is the
`universe-matrix/no-proliferator` freeform refusal.
`finalize.band_policy_search_envelope(policy, perimeter=_ENTRY_RING)` is already constructed in
both strategies (`freeform.py:16124`, `sequence_solver.py:4100`), so no new projection work is
introduced.

The search over `w` is a binary search **if and only if** `frame_candidates` is monotone in width at
a fixed height. Monotonicity is plausible (a wider core needs a strictly larger frame) but is a
property of `_frame_candidates_for_extent`, not an axiom, so the plan tests it first and falls back
to a descending linear scan if the test fails. `C_BAND_SCAN_MAX = 4096` is the largest core width
the helper accepts; a wider input is a programming error and raises, rather than being silently
clamped. (The corpus peaks near 1334.)

### 5.4 The two shipped repair operators

- **`SEQUENCE_REINSERT`** — `sequence_pair.repair_neighbourhood(pair, gaps, neighbourhood,
  seed=derive_stage_seed(seed, stage_index + 1), variant_indices=...)`, exactly as
  `_routing_feedback_substitution` calls it today (`sequence_solver.py:2694-2700`). Unchanged code.
- **`LOCAL_EXACT_PACK`** — section 5.5.

### 5.5 The `LOCAL_EXACT_PACK` window model

**It is a sub-model, not a re-solve.** `_pack` (`freeform.py:3179`) is refactored into a model
builder plus a solve, with two new parameters:

```python
def _pack_model(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    fixed_at: Mapping[int, tuple[int, int]] = MappingProxyType({}),
    width_target: int | None = None,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    seed: _Pack | None = None,
) -> _PackModel | None
```

`fixed_at` maps a strip index to its **content** origin, the same convention as `_Pack.at`; the
builder subtracts `strips[i].west_channel` to get the box origin, exactly as the existing warm-start
code does at `:3578-3585`. `_pack` calls `_pack_model` with `fixed_at={}` and `width_target=None`
and is otherwise unchanged, so the production model is byte-identical to today's.

**The equivalence claim, stated precisely.** `_pack_window(..., window=every strip, fixed_at={},
seed=None, width_target=None)` builds the *same model* as `_pack(..., seed=None)` — same variables,
same constraints, same objective — and, given the same solver parameters, returns the same `_Pack`.
`seed` is therefore optional in `_pack_window`: the equivalence test compares a seedless window
against a seedless `_pack`, so no warm start and no seed-derived width bound is in play on either
side, and the comparison is of the model alone.

Piece by piece, this is what the window does to each part of the model. Everything named is in
`_pack` at `b3c990a`:

| `_pack` piece | In the window model |
|---|---|
| `sizes = [_box(s) for s in strips]`, the `h > height` rejection, `total_area`, `widest`, `w_lb` (`:3226-3237`) | Unchanged. Every strip is still in the model; only its domain changes. |
| `w_var` (`:3238`) | Unchanged domain `[min(w_lb, width_bound), width_bound]`. Callers pass the current pack's width as `width_bound`, so a repair may not widen the block. |
| `xs[i]`, `ys[i]` (`:3242-3243`) | For `i` in the window, unchanged. For a pinned `i`, `model.new_int_var(bx, bx, f"x{i}")` and `model.new_int_var(by, by, f"y{i}")` — a singleton domain, not a constant expression, so every constraint below is written by the *same* code. |
| `x_iv[i]`, `y_iv[i]`, `add_no_overlap_2d` (`:3246-3250`) | Unchanged. Pinned-against-pinned pairs are trivially satisfied and presolved away; pinned-against-window pairs are the real constraint the window respects. |
| `model.add(x + w <= w_var)` (`:3248`) | Unchanged. On a pinned strip this becomes a constant lower bound on `w_var`. |
| exact-pack no-goods (`:3252-3255`, `_add_exact_pack_no_good` at `:3038`) | Guarded twice, then unchanged. Skipped when a pinned strip's current origin differs from the no-good's (the forbidden tuple is unreachable, so the constraint is dead weight), and skipped when the no-good names no free strip — in that degenerate case its only free variable is `w_var` and it would forbid a width for no geometric reason. |
| projection no-goods (`:3257-3266`, `_add_projection_no_good` at `:3062`) | Unchanged, with the same two guards keyed on the no-good's two strips. |
| symmetry breaking (`:3339-3348`) | Added **only when both `i` and `j` are in the window.** A pinned strip is a given, not a symmetry, and the lexicographic constraint would otherwise reject the incumbent it was pinned to. With `fixed_at={}` every pair qualifies, so `_pack` is unaffected. |
| HPWL `dx`/`dy` and CUT 2 separation (`:3352-3370`) | Unchanged. Both-pinned pairs contribute a constant to the objective and a satisfied constraint (non-overlap implies the separation cut). |
| direct-insert booleans (`:3384-3413`) | Unchanged. A pair with both ends pinned reduces to a constant reification, which is the correct semantics: the window inherits, and cannot break, the direct inserts outside it. |
| direct-relation no-goods (`:3415-3446`) | Unchanged, with the same two guards. |
| `ClusterRelationNoGood` (Phase B, `route_feedback.py`) | New: `_add_cluster_relation_no_good` adds one `add_forbidden_assignments` over the cluster strips' `(xs, ys)` with the proved origins — "at least one of these strips moves", the same shape `_DirectRelationNoGood` uses for two strips. ONE guard, not the other two: each pinned named strip implies an anchor position (its content origin minus its delta), and the no-good is skipped only when two pinned strips imply DIFFERENT anchors, which makes the relation unreachable. Otherwise it is modelled — including when every named strip is pinned, because this constraint never touches `w_var` and a fully pinned forbidden arrangement is not degenerate: the window model is then INFEASIBLE, which is the truthful "this window cannot repair the incumbent". |
| objective `cap`, `base_tier`, feedback evidence terms, `minimize` (`:3505-3560`) | Unchanged. Pinned coordinates make some evidence terms constant; the argmin over the window is the same. |
| warm start (`:3567-3585`) | Unchanged when `seed is None`. When a seed is given, `add_hint` is applied to window strips only (a hint on a singleton domain is noise) and the `w_var <= min(seed.width, width_bound)` bound keeps its existing `feedback is None` condition. |
| new `width_target` | When `width_target is not None` and every pinned strip satisfies `bx + w <= width_target`, add `model.add(w_var <= width_target)`. Otherwise skip it and count it in `skipped_no_goods`: `BAND_BOUNDARY` still gets the objective's width minimization, which is lexicographically first anyway, but a target that never applies is a repair aimed at nothing, so it must be visible. |

`_pack_window` is the thin caller. It returns `None` for `INFEASIBLE`/`UNKNOWN` and otherwise
returns whatever CP-SAT found, **including an assignment identical to the seed's**. Revision 1
short-circuited on `packed.at == seed.at`; that contradicted the equivalence test (which passes no
seed and must still return a pack) and hid a real signal. The caller decides what an unchanged
assignment means: the sequence-pair adapter treats it as "no repair" and credits `applied=False`;
the freeform sweep dedupes windows before solving so it never asks the same question twice.

**Solver parameters, and why there are two of them.**

```python
C_WINDOW_WORKERS = 1
C_WINDOW_SECONDS = 1.0
C_WINDOW_DETERMINISTIC_WORK = 25 * _DETERMINISTIC_PACK_WORK      # 0.5
```

`_DETERMINISTIC_PACK_WORK = 0.02` (`freeform.py:318`) is what a *full* pack of 15 or more strips
gets when `deterministic=True`; it is calibrated to return a feasible incumbent quickly from a shelf
warm start. A window has at most `C_MAX_DESTROY_STRIPS = 12` free strips but no equivalent
guarantee that its free strips start feasible, so it gets 25 times that allowance and is expected to
prove optimality of a small model rather than to stop at the first incumbent.

The two limits do different jobs. `max_deterministic_time` counts solver work, so it is the limit
that makes two runs ask CP-SAT the same question, and on an idle box it is the one that fires.
`max_time_in_seconds = C_WINDOW_SECONDS` is the guard under contention: the corpus audit runs
`--jobs 16`, and `pyproject.toml:69-77` records that one CP-SAT solve already saturates the box at
~700% CPU, so 0.5 deterministic units can take far more than 0.5 seconds of wall when sixteen cells
share the machine. Whichever fires first ends the solve. Under contention the wall limit can
therefore return a *worse* incumbent than the deterministic limit would have — which is acceptable
precisely because a window result is never trusted: it is handed to the real router and validator
like any other candidate. The multiple is a starting value with a measurement attached: the gate
records `alns_window_seconds / alns_window_solves`, and if that mean exceeds `C_WINDOW_SECONDS` the
deterministic bound is lowered rather than the wall limit raised.

**Why this is affordable where a full solve is not.** The full `_pack` on `universe-matrix` gets
`per_solve = share * _PACK_SHARE / len(heights)` (`freeform.py:16109`, `_PACK_SHARE = 0.35`) and is
followed by a 1.9-4.6 s preparation and a 0.5-1.6 s routing pass. The window solve costs at most
1.0 s and leaves the same preparation and routing to follow; what it buys is that the next
evaluation differs from the last one in a way the router's own evidence chose.

### 5.6 Placement-to-sequence-pair encoder

**No encoder exists.** `grep -rn 'def encode' src/flab2bp/layout/` returns nothing; `sequence_pair.py`
has `decode_sequence_pair` (`:819`) and `decode_state` (`:893`) and no inverse. So this phase
specifies one from the decode.

`decode_sequence_pair` builds its two precedence graphs from the pair alone (`:846-853`):

```python
for first_position, first in enumerate(pair.positive):
    for second in pair.positive[first_position + 1:]:
        if negative_position[first] < negative_position[second]:
            horizontal[first].append(second)      # first is west of second
        else:
            vertical[second].append(first)        # first is ABOVE second
```

and then takes earliest coordinates by `_earliest_coordinates` (`:2150`), a longest-path sweep in
which a strip's coordinate is `max` over its predecessors of `coordinate + dimension + slack`, with
`slack` the per-strip `GapProfile.east`/`north` entry. The inverse is therefore:

```python
def encode_placement(
    sizes: tuple[tuple[int, int], ...],
    x: tuple[int, ...],
    y: tuple[int, ...],
    *,
    outline_height: int,
) -> EncodedPlacement
```

**Read the vertical direction off `_earliest_coordinates`, not off the variable's name.**
`_earliest_coordinates(successors, ...)` (`sequence_pair.py:2150-2161`) treats `successors[s]` as
the strips that must come *after* `s`: `coordinates[destination] = max(..., coordinates[source] +
dimensions[source] + slack[source])`. So `vertical[second].append(first)` makes `second` the source
and `first` the destination, which means `y_first >= y_second + h_second` — **`first` is ABOVE
`second`**. Combined with the loop above it: `i` before `j` in the positive permutation and *after*
`j` in the negative permutation encodes "**i is above j**", not "i is below j". Revision 1 of this
spec had that backwards, and an encoder built on the inverted reading violated
`decoded <= input` on every one of twenty test placements.

The encoder works with two geometric relations, "west" (`x_i + w_i <= x_j` gives `i` west of
`j`) and "above" (`y_j + h_j <= y_i` gives `i` above `j`), and **it cannot choose a relation pair
by pair.** Any rule that reads only one pair's own coordinates (the tighter separation, the looser
one, or a fixed axis preference) produces relation sets no sequence pair can express, because the
implied precedences run in a cycle. Two minimal non-overlapping counterexamples close both
directions. `A=(1,0)` sized `(2,1)`, `B=(4,2)` sized `(1,1)`, `C=(0,1)` sized `(10,1)`: A/C and
B/C overlap in `x`, forcing "C above A" and "B above C"; A/B is the only pair with a choice and its
two separations are equal, so every horizontal-preferring rule closes A -> B -> C -> A, and only
"B above A" is consistent. `i=(0,0)`, `j=(3,1)`, `k=(6,2)`, all sized `(2,2)`: i/j and j/k overlap
in `y`, forcing "i west j" and "j west k"; i/k is disjoint on both axes with vertical separation 0
against horizontal 4, so every vertical-preferring rule closes i -> j -> k -> i, and only "i west
k" is consistent. Run against this plan's own shelf generator at seed `20260902`, the tighter-axis
rule this spec originally prescribed leaves the positive graph cyclic on 30 of 80 placements and
the negative graph on 38 of 80.

The encoder therefore records only the precedences the geometry **forces** and lets two
topological sorts settle the rest: `j` strictly west of `i` forces `j` before `i` in both
permutations; `j` strictly above `i` forces `j` before `i` in the positive permutation only; `j`
strictly below `i` forces `j` before `i` in the negative permutation only. Equivalently, the
positive successors of `i` are every `j` that is neither west of nor above `i`, and the negative
successors every `j` that is neither west of nor below `i`. A pair overlapping on one axis is
pinned by these in both permutations; a pair disjoint on both axes is pinned in exactly one
permutation and left free in the other, and **both** outcomes of the free permutation name a
relation the input already satisfies ("i west j" one way, "i above j" the other). Each permutation
is a deterministic Kahn sort over a totally ordered ready set, keys `(x_i, -y_i, i)` for the
positive and `(x_i, y_i, i)` for the negative, so the same placement always encodes to the same
pair. Gaps are `GapProfile.zero(len(sizes))`; the pair is then decoded and compared, giving
`EncodedPlacement(pair, gaps, decoded, exact)` with `exact = decoded.x == x and decoded.y == y`.

**The decode is a compaction, and it provably cannot exceed the input.** Every relation the
emitted pair implies, forced or settled by a sort, is an inequality the *input* placement already
satisfies, so the input coordinates are a feasible point of the constraint system the emitted pair
defines. With zero gaps, `_earliest_coordinates` computes the componentwise-minimum feasible point
of that system. Hence `decoded.x[i] <= x[i]` and `decoded.y[i] <= y[i]` for every `i`, and
therefore `decoded.width <= max(x[i] + w_i)` and `decoded.used_height <= max(y[i] + h_i)`: **never
wider, never taller.** `_MAX_GAP` plays no part in this argument, because the emitted gaps are
zero.

**"Never wider, never taller" is the only guarantee. An exact round trip is not promised, and is
rare.** Exactness holds only when the input already *is* that compaction (an abutting row, an
abutting column, a tight grid), because a pair with slack on the axis that relates it lets the
compaction close that slack, and closing it can free a third strip that no surviving relation holds
up. Measured on the shipped construction: 59 of 4000 shelf placements and 0 of 4000 scattered
placements round-trip exactly, with zero componentwise violations in either set. Acyclicity of the
two forced graphs is not proven in general: an exhaustive sweep over abstract relation types with
difference-constraint realizability shows no realizable chordless cycle of length 3 through 6 in
either graph, and none of any length appeared in 3.3 million random non-overlapping placements, but
`_topological_order` still raises `ValueError` rather than returning a partial order. That raise,
and an overlapping input, are caught at the operator boundary, counted in `alns_encode_errors`, and
become `applied=False`. Treat it as a real if unobserved control path, not as a bug detector.

The contract this phase adopts is therefore **`decoded` is the candidate, not the input.** What the
compaction can lose is a direct-insert alignment the window solve bought, because moving a strip
changes `origin_delta`, and — less often — a relation the router's failure evidence implicated. Both
are handled where they must be: the decoded placement is scored by `sequence_pair.score_candidate`
and realigned before acceptance, so what is evaluated is what would be built, and the real router
then decides whether it was worth it. A non-exact re-encode is counted in telemetry
(`alns_encode_inexact`); a `ValueError` (an overlapping input, or a cyclic relation graph, which has never
been produced but is not proven impossible) is caught at the operator boundary, counted as
`alns_encode_errors`, and becomes `applied=False`.

Because the round trip is not exact, `_RepairAdapters.window_pack` returns the whole
`EncodedPlacement` rather than a bare `DecodedPlacement`: the caller uses the pair the adapter
already computed instead of re-encoding the compaction and risking a second, different one.

### 5.7 Freeform integration through `_room_for_another`

`_room_for_another(deadline, soft, candidate_s)` (`freeform.py:16984`) answers "is there clock left
to pack, route, power and validate one more candidate", charging `dearest_candidate_s` — the
dearest candidate this sweep has *completed*. `_sweep` uses it through
`projection_retry_affordable()` (`:16140-16147`) to decide whether a proved no-good earns an
immediate retry (`:16719-16723`), and when it says no, the failed pack is simply dropped
(`continue` at `:16755`).

Phase C adds one measured quantity, one branch, and an explicit re-visit queue:

- `dearest_remainder_s` tracks, over the candidates this sweep has completed, the largest value of
  (that candidate's total seconds minus that same candidate's `_pack` seconds), alongside the
  existing `dearest_candidate_s`. `window_candidate_s = C_WINDOW_SECONDS + dearest_remainder_s` —
  the cost of a window solve plus the measured cost of everything after packing. It is a
  measurement, like `dearest_candidate_s`, not a tuned constant. (Ruling AD: an earlier draft
  differenced two independent maxima, `dearest_candidate_s - dearest_pack_s`, which is not an
  upper bound on any single candidate's post-pack span and could admit a repair that then overran
  the deadline.) The same remainder is what a queued repair is charged at the loop-head
  affordability gates, since its pack is already paid for.
- In the `if failed:` block, after the `promote_retry` branch and before `continue`
  (`freeform.py:16700-16755`): when a full retry was WANTED (`promote_retry`), had a slot
  (`retry_slot_found`), and the clock refused it (`not retry_admitted`), and
  `_room_for_another(deadline, soft, window_candidate_s)`, run `LOCAL_EXACT_PACK` on the failed
  pack — destroy set from the same selector, `fixed_at` for everything else,
  `width_target = band_target_width(projection_envelope, height=height, width=pack.width)`.
- **Re-visit mechanism.** `candidate_packs` is a list of `(height, arrangement, projection_retry)`
  triples iterated by index (`freeform.py:16062`, `:16184-16185`), and existing code already mutates
  it mid-iteration in four places. Phase C adds no fifth mutation. A successful window solve stores
  the pack in `window_packs[(height, arrangement)]` and appends `(height, arrangement)` to a
  separate `window_queue: list[tuple[int, int]]`. The candidate loop's head drains `window_queue`
  before advancing `candidate_index`: a queued entry is evaluated with its stored pack instead of
  calling `_pack`, and is removed whether it succeeds or fails. `candidate_packs` is not touched.
- **Windows are deduped per `_sweep` call** by `(height, arrangement, window)` in a
  `solved_windows: set[tuple[int, int, frozenset[int]]]`. Without it, a pack that fails the same way
  twice asks CP-SAT the identical question twice and spends `C_WINDOW_SECONDS` for a known answer.
  The set is per sweep, not per `lay_out`, because `replan_strips_for_learned_geometry` renumbers the
  strip indices the key is built from between sweeps.
- **Consequence at budget 30 (measured in Task 13).** The trigger fires only where the clock refuses
  a wanted retry; on the current corpus freeform exhausts its candidate list well inside the budget,
  so no freeform window fires on any of the 36 cells. That is the rule working as written, not a
  defect. Whether to widen the trigger (for example to any routing failure with a slot and clock to
  spare) is decided at the gate from the sequence-pair arm's evidence, not by the implementer.

**Credit is keyed by the candidate it belongs to.** The `OperatorSession` is constructed in
`FreeformLayout.lay_out` before the sweep, so it lives for the whole call and survives a
`replan_strips_for_learned_geometry()`. Freeform does not use `observe_and_select`, because its
choices and outcomes interleave across candidates: it calls `session.select(context)` when it
launches a window and stores the choice and the pre-repair metrics in
`window_choices[(height, arrangement)]`. When that queued candidate finishes evaluating, the sweep
builds an `OperatorOutcome` from the stored pair and the *real* attempt — `validator_clean` from the
`validate.certify` report at `:16948`, False for any candidate that never reaches it — and calls
`session.observe(..., routing_seconds=<the measured route span of that attempt>)`. A
window whose candidate is never reached before the deadline is credited `applied=False` at the end
of the sweep, so a launched-but-unevaluated window is a cost with no reward, which is the truth.

So the operator fires exactly where a full re-solve was proved unaffordable, it costs one bounded
CP-SAT solve rather than a full one, and every acceptance rule downstream is untouched: a windowed
pack that fails validation is discarded like any other (`:16959-16961`), and `best` is still only
updated for a routed, certified candidate keyed on `(area, belt_tiles)` (`:16973-16980`).

`_pack_relation_problem(pack, strips, height)` builds the `PlacementProblem` the shared destroy
operators read from a freeform pack. It carries `sizes` (`_box` per strip), `nets`
(`_nets_between`, `freeform.py:2999`, which returns sorted strip-index pairs), `outline_height` and
`area_lower_bound`. It leaves `logical_net_ids` empty: with `RELATED_CARGO` a follow-up, no shipped
operator reads it, and `_nets_between` does not carry the item identity a `LogicalNetId` needs, so
populating it would mean synthesizing identities nothing consumes. The day `RELATED_CARGO` ships,
that field and its source are part of that operator's task.

`_pack_relation_pair` runs `encode_placement` over the pack, because `FAILED_ENDPOINTS` needs a
`SequencePair` for `_sequence_neighbours`. Its gaps are zero, so
`select_lns_neighbourhood`'s gap-rectangle branch never fires in freeform — the neighbourhood there
is failure endpoints plus sequence neighbours only.

**Phase E status (Ruling E12; executed 2026-09-03–04):** Phase E deliberately broadened
`_feedback_retry_eligible` to any non-exhaustive, non-empty `STRANDED` routing result with at least
one failure whose net has both a feedback weight and endpoint offsets. That eligibility is only
"aimable evidence"; it does **not** collapse the older retry and the window into one path. The old
single-failure exact feedback retry remains distinct: only `single_failure_feedback_retry` consumes
and bypasses the next arrangement slot unconditionally, while newly learned proof evidence may
still admit an affordable full retry. An aimable multi-failure pack leaves the slot free, and only a
strictly better best-failing pack seen so far may launch `_pack_window` under
`retry_slot_found and not retry_admitted and best_failing`. Ties do not launch, and the existing
`_room_for_another` affordability calculation is unchanged.

Gate E2
(`docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e2.md`) measured that widened
path honestly: freeform `universe-matrix/no-proliferator` made six distinct assignments and six
evaluations, launched and accepted one window in every round, and had zero stale draws, but still
refused with the forbidden `PACKER defect` wording. Sequence-pair still refused the same cell, with
zero window solves in all nine `universe-matrix` rows. Gate E2 therefore failed clauses 1, 3 and 4;
Gate E3 was not run.

### 5.8 Determinism

- **The selector's ledgers are a pure function of the reward vectors it has seen.** No wall clock,
  no measured seconds, no RNG. `routing_seconds` reaches `OperatorOutcome` and telemetry and stops
  there.
- `OperatorContext.remaining_fraction` is quantized to `C_CONTEXT_FRACTION_STEPS` buckets and is
  read only to decide whether `LOCAL_EXACT_PACK` is affordable, so wall jitter can change *whether a
  window is attempted*, never the ordering of the arms that remain.
- Reward means are quantized to `C_DUCB_SCORE_QUANTUM` before comparison, and the exploration bonus
  is a deterministic function of the counts.
- Every window solve pins one worker and a deterministic-time bound.
- The encoder's relation rule (`h >= v`) and its two topological sorts have total orders.
- Continuation restart seeds are a pure function of `(config.seed, height order, restart ordinal)`.

Consequently, for a fixed `config.seed` and a fixed deterministic budget, the sequence of operator
choices and the placement each produces are reproducible. The same escape clause as the rest of the
solver applies to *how many* of them happen: the wall clock decides how many stages, candidates and
window solves fit, so two runs on differently loaded boxes can stop at different points. The corpus
gate compares CLEAN counts and area, not step counts.

### 5.9 Constants

Each constant's owning module is named.

| Name | Default | Module | Meaning |
|---|---|---|---|
| `C_FEASIBILITY_RESTART_BATCHES` | `8` | `sequence_solver` | max continuation batches per search |
| `C_DUCB_DISCOUNT` | `0.9` | `sequence_alns` | per-observation discount applied to every arm |
| `C_DUCB_EXPLORATION` | `0.5` | `sequence_alns` | coefficient of the single tie-break bonus |
| `C_DUCB_SCORE_QUANTUM` | `1e-9` | `sequence_alns` | quantization of each mean before comparison |
| `C_CONTEXT_FRACTION_STEPS` | `10` | `sequence_alns` | buckets for `remaining_fraction` |
| `C_WINDOW_FRACTION_FLOOR` | `1` | `sequence_alns` | bucket below which `LOCAL_EXACT_PACK` is not offered |
| `C_MIN_DESTROY_STRIPS` | `2` | `sequence_alns` | floor on destroy cardinality |
| `C_MAX_DESTROY_STRIPS` | `12` | `sequence_alns` | cap on destroy cardinality |
| `C_SCALE_FRACTION` | `0.15` | `sequence_alns` | destroy cardinality as a share of strip count |
| `C_SCALE_GROWTH` | `2` | `sequence_alns` | extra strips per stagnation step |
| `C_GROW_AFTER` | `2` | `sequence_alns` | `select_lns_neighbourhood`'s ring-growth threshold, passed with `stagnation=0` so the branch stays dormant |
| `REWARD_RANKS` | `5` | `sequence_alns` | components of a reward vector |
| `C_BAND_SCAN_MAX` | `4096` | `finalize` | largest core width `band_target_width` accepts; wider raises |
| `C_WINDOW_SECONDS` | `1.0` | `freeform` | wall limit of one window solve |
| `C_WINDOW_DETERMINISTIC_WORK` | `25 * _DETERMINISTIC_PACK_WORK` (`0.5`) | `freeform` | `max_deterministic_time` of one window solve |
| `C_WINDOW_WORKERS` | `1` | `freeform` | `num_search_workers` of one window solve |
| `C_WINDOW_DEADLINE_SAFETY_SECONDS` | `0.05` | `freeform` | margin kept between a window solve and the run deadline |

## 6. Interfaces

Public surface unchanged: `FreeformLayout`, `SequencePairLayout`, `pipeline.build`, CLI, web,
`scripts/audit.py` and its JSONL schema.

```python
# flab2bp.layout.sequence_alns  (new module)
class DestroyOperator(StrEnum): ...     # members in section 5.2
class RepairOperator(StrEnum): ...
SHIPPED_DESTROY: tuple[DestroyOperator, ...]
SHIPPED_REPAIR: tuple[RepairOperator, ...]
REWARD_RANKS: int

@dataclass(frozen=True, slots=True)
class OperatorContext:
    strip_count: int
    stagnation: int
    remaining_fraction: int

@dataclass(frozen=True, slots=True)
class OperatorChoice:
    destroy: DestroyOperator
    repair: RepairOperator
    scale: int
    ordinal: int

@dataclass(frozen=True, slots=True)
class OperatorMetrics:
    validator_clean: bool
    failed_nets: int
    band_overflow: int
    congestion: float
    area: int

@dataclass(frozen=True, slots=True)
class OperatorOutcome:
    choice: OperatorChoice
    before: OperatorMetrics
    after: OperatorMetrics
    applied: bool
    # No measured seconds: nothing would read them.  Seconds reach the session
    # through observe(..., routing_seconds=...) and are telemetry only.

def reward_vector(outcome: OperatorOutcome) -> tuple[float, ...]: ...
def operator_scale(context: OperatorContext) -> int: ...
def remaining_fraction_bucket(remaining_s: float, ceiling_s: float) -> int: ...

def metrics_from_evaluation(
    result: DetailedRouteResult, decoded: DecodedPlacement, feedback: FeedbackState, *,
    outline_height: int, band_target_width: int, validator_clean: bool,
) -> OperatorMetrics: ...

def destroy_strips(
    operator: DestroyOperator, *, scale: int,
    result: DetailedRouteResult, pair: SequencePair, gaps: GapProfile,
    problem: PlacementProblem, decoded: DecodedPlacement, band_target_width: int,
) -> frozenset[int]: ...

def operator_tally(session: OperatorSession) -> str: ...   # "destroy:<name>:<n>|repair:<name>:<n>"

class OperatorSession:
    def __init__(
        self, *,
        destroy_arms: Sequence[DestroyOperator] = SHIPPED_DESTROY,
        repair_arms: Sequence[RepairOperator] = SHIPPED_REPAIR,
        discount: float = C_DUCB_DISCOUNT,
        exploration: float = C_DUCB_EXPLORATION,
    ) -> None: ...
    def select(self, context: OperatorContext) -> OperatorChoice: ...
    def observe(
        self, choice: OperatorChoice, reward: Sequence[float], *,
        applied: bool, routing_seconds: float = 0.0,
    ) -> None: ...
    def observe_and_select(
        self, metrics: OperatorMetrics, context: OperatorContext, *,
        routing_seconds: float = 0.0, applied: bool = True,
    ) -> OperatorChoice: ...
    @property
    def choices(self) -> tuple[OperatorChoice, ...]: ...
    @property
    def pending(self) -> OperatorChoice | None: ...
    @property
    def applied(self) -> int: ...
    @property
    def routing_seconds(self) -> float: ...
    @property
    def credit(self) -> Mapping[str, float]: ...

# flab2bp.layout.sequence_pair
@dataclass(frozen=True, slots=True)
class EncodedPlacement:
    pair: SequencePair
    gaps: GapProfile
    decoded: DecodedPlacement
    exact: bool

def encode_placement(
    sizes: tuple[tuple[int, int], ...], x: tuple[int, ...], y: tuple[int, ...],
    *, outline_height: int,
) -> EncodedPlacement: ...

# flab2bp.layout.finalize
C_BAND_SCAN_MAX: int
def band_target_width(
    envelope: BandPolicySearchEnvelope, *, height: int, width: int
) -> int: ...

# flab2bp.layout.freeform
C_WINDOW_SECONDS: float
C_WINDOW_DETERMINISTIC_WORK: float
C_WINDOW_WORKERS: int
C_WINDOW_DEADLINE_SAFETY_SECONDS: float

@dataclass(frozen=True, slots=True)
class _PackModel:
    model: cp_model.CpModel
    w_var: cp_model.IntVar
    xs: list[cp_model.IntVar]
    ys: list[cp_model.IntVar]
    direct_vars: dict[tuple[int, int], cp_model.IntVar]
    sizes: list[tuple[int, int]]
    skipped_no_goods: int

def _pack_model(...) -> _PackModel | None: ...        # signature in section 5.5
def _pack_result(
    built: _PackModel, solver: cp_model.CpSolver, strips: Sequence[Strip],
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate], height: int,
    admission: cp_model.CpSolverSolutionCallback | None,
) -> _Pack | None: ...
def _pack_window(
    strips: list[Strip], *, height: int, width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    window: frozenset[int], fixed_at: Mapping[int, tuple[int, int]],
    seed: _Pack | None = None, width_target: int | None = None, arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    time_budget_s: float = C_WINDOW_SECONDS,
    deterministic_work: float = C_WINDOW_DETERMINISTIC_WORK,
    on_skipped: Callable[[int], None] | None = None,
) -> _Pack | None: ...

def _window_candidate_seconds(*, dearest_remainder_s: float) -> float: ...
def _decoded_from_pack(pack: _Pack, strips: Sequence[Strip], height: int) -> DecodedPlacement: ...
def _pack_relation_problem(
    pack: _Pack, strips: Sequence[Strip], height: int
) -> PlacementProblem: ...
def _pack_relation_pair(pack: _Pack, strips: Sequence[Strip], height: int) -> SequencePair: ...

# flab2bp.layout.sequence_solver
C_FEASIBILITY_RESTART_BATCHES: int

class SequenceSearchResult:
    feasibility_restart_batches: int = 0          # new field, default preserves callers

class SequenceSolver[PreparedT]:
    def __init__(
        self, *,
        ...,                                        # every existing keyword, unchanged
        alns_session: OperatorSession | None = None,
        alns_adapters: _RepairAdapters | None = None,
        remaining_fraction: Callable[[], int] | None = None,
        band_target_for: Callable[[int, int], int] | None = None,
    ) -> None: ...
    def search(self, *, max_stages: int | None = None,
               feasibility_continuation: bool = False) -> SequenceSearchResult: ...

@dataclass(frozen=True, slots=True)
class _RepairAdapters:
    window_pack: Callable[
        [frozenset[int], PlacementProblem, AnnealState, DecodedPlacement],
        EncodedPlacement | None,
    ] | None = None
    # Called by the two caller sites with the state they actually install; the
    # production closure counts `alns_window_accepted` only when that state's
    # pair is the one its window returned (the install site, not the encode).
    window_installed: Callable[[AnnealState], None] | None = None

def _alns_substitution(
    detailed: DetailedRouteResult, selected_state: AnnealState,
    problem: PlacementProblem, decoded: DecodedPlacement, *,
    seed: int, stage_index: int, session: OperatorSession,
    context: OperatorContext, metrics: OperatorMetrics, routing_seconds: float,
    band_target_width: int, adapters: _RepairAdapters,
    cap_scale: bool = False,
) -> tuple[AnnealState, frozenset[int]]: ...
```

The four new `SequenceSolver` keywords all default to something inert, so every existing
construction in the tests keeps working: no session means the shipped portfolio, no adapters means
no window, `remaining_fraction` reports the full bucket, and `band_target_for` returns its input
(which makes `BAND_BOUNDARY` inert, correct for a solver with no band envelope). `cap_scale` is
`False` until the portfolio opens: the legacy rule destroyed the whole neighbourhood, so capping it
in the wiring commit would be a behaviour change smuggled into a refactor.

**`PlacementStats` (`base.py:198`, a `TypedDict(total=False)` with alphabetically ordered keys)
gains these**, each added in the task that first writes it: `alns_applied`, `alns_choices`,
`alns_encode_errors`, `alns_encode_inexact`, `alns_evaluations`, `alns_routing_seconds`,
`alns_skipped_no_goods`, `alns_window_accepted`, `alns_window_seconds`, `alns_window_solves`,
`feasibility_restart_batches` (all `float`), and `alns_operators` (`str`). `alns_evaluations`
counts the candidates that reached the detailed router in this `lay_out` call; it is what gate 2
records as an absolute.

## 7. Failure handling

- A destroy operator with no evidence returns `frozenset()`; the session records `applied=False`
  with a zero reward vector and the caller falls through to the unchanged state, exactly as
  `_routing_feedback_substitution` does today when the neighbourhood is empty or is the whole
  problem.
- A window solve that returns `INFEASIBLE` or `UNKNOWN` returns `None` and the candidate is dropped
  exactly as it is dropped today. A window solve never produces a no-good: a bounded solve proves
  nothing, which is the same rule `_proof_scoped_no_goods` applies to `BUDGET` failures
  (`freeform.py:13681`).
- A window solve that returns the seed assignment unchanged is not an error. In sequence-pair the
  adapter compares and credits `applied=False`; in freeform the dedupe set stops the same window
  being asked twice, so an unchanged result is evaluated once and then not repeated.
- A no-good is skipped, and counted in `alns_skipped_no_goods`, when a pinned strip's origin
  contradicts it (unreachable) or when it names no free strip (its only free variable would be
  `w_var`). A chronically skipped no-good is a silent loss of a constraint; the counter exists so
  the gate can see it.
- The encoder raises `ValueError` on an overlapping input or a cyclic relation graph. It is caught
  at the operator boundary, counted in `alns_encode_errors`, and becomes `applied=False`.
- A non-exact round trip is not an error: the decoded compaction is the candidate, and the count is
  telemetry.
- `LOCAL_EXACT_PACK` is not offered as an arm when `remaining_fraction < C_WINDOW_FRACTION_FLOOR`;
  if every repair arm is filtered out, the unfiltered set is used so `select` always returns.
- Feasibility continuation that cannot append (every height already at its cap) breaks with
  `termination = "feasibility-exhausted"` and its own refusal string; it never loops.
- If Phase B has not landed, `cluster_relation_no_goods` is always empty and every window solve is
  identical to one without it. The plan's window task verifies the Phase B record's field names
  before writing the accessor.

## 8. Testing

Unit tests, all serial (`uv run pytest -q`), no new fixtures beyond the existing
`two_stage_spec()` (`tests/layout/test_freeform.py:180`) and `plastic_spec()` (`:206`) plus one
tracked proto snapshot for the `_pack` split. The five tests that drive a whole solver at a real
budget are marked `@pytest.mark.slow` (the marker is declared at `pyproject.toml:89` and still runs
by default): the graphene continuation gate, the sequence-pair and freeform stats tests, and the two
`_production_run` adapter tests.

- **Operator selection determinism.** Two `OperatorSession`s fed the identical sequence of
  `(metrics, context)` emit identical `choices` tuples. **Every arm is played once before any arm
  is played twice**, in declaration order. A follow-up member is never selected by a
  default-constructed session, and `destroy_strips` raises `NotImplementedError` for one.
- **Selector ordering.** Two arms tie on rank 0 (both zero) and the arm with the better rank 1 mean
  wins. An arm with a large rank-4 mean does not beat an arm with a better rank-1 mean. The
  exploration bonus breaks a tie between two arms equal on all five means, and only then.
- **Reward accounting.** `reward_vector` is lexicographic; rank 4 is zero unless
  `after.validator_clean`; a regression never produces a negative component; **the vector does not
  change when `routing_seconds` changes.** Discount arithmetic: after `k` plays an arm's count is
  `sum(C_DUCB_DISCOUNT**i for i in range(k))` to within `1e-12`. An `applied=False` outcome
  contributes a count and a zero reward.
- **Affordability filter.** With `remaining_fraction = 0`, `select` never returns
  `LOCAL_EXACT_PACK`; with `remaining_fraction = C_CONTEXT_FRACTION_STEPS` it can.
- **`frame_candidates` monotonicity.** A scan over a range of widths at two heights asserts that
  once `frame_candidates(w, h)` is non-empty it stays non-empty for every smaller `w`. This test
  decides `band_target_width`'s implementation: binary search if it passes, descending linear scan
  if it fails.
- **`band_target_width`.** Returns the largest fitting width and rejects the next one up; returns
  its input when the input already fits; raises above `C_BAND_SCAN_MAX`.
- **`BAND_BOUNDARY`.** Selects the strips whose right edge exceeds the target, ranked by descending
  edge; returns `frozenset()` when the placement fits and does not overflow; respects `scale`.
- **Model-split equivalence.** The `_pack` refactor is fenced by a tracked snapshot: the text
  serialization of the model `_pack` builds on a `plastic_spec()` slice is captured *before* the
  split into `tests/layout/data/plastic_pack_model.pbtxt`, and a permanent test asserts that
  `_pack_model(..., fixed_at={}, seed=None)`'s proto serializes to exactly those bytes. Regenerating
  that file is a separate, reviewed commit. No test asserts variable-domain shapes: a strip whose
  height equals the candidate height legitimately gets a singleton `y` domain even with nothing
  pinned.
- **Window model equivalence.** On a slice of `plastic_spec()`,
  `_pack_window(..., window=frozenset(range(n)), fixed_at={}, seed=None, width_target=None)`
  returns a `_Pack` equal to `_pack(..., seed=None)` for the same `height`, `width_bound`,
  `arrangement`, `direct_candidates`, and no-goods, at the same deterministic bound. Two narrower
  tests: pinning every strip but one leaves the other strips' origins untouched in the result, and
  a window solve never returns a wider `_Pack` than its `width_bound`. Two guard tests, both
  against `_pack_model` directly because `_pack_window` forbids an empty window: an exact-pack
  no-good every one of whose strips is pinned reports `skipped_no_goods == 1` and is absent from
  the model, and an unapplicable `width_target` is counted the same way. One end-to-end test that
  `on_skipped` fires with that count and that the sequence-pair adapter's
  `alns_skipped_no_goods` stat carries it.
- **Encoder.** `decoded` is componentwise `<=` the input on every generated placement, and
  `width`/`used_height` are no larger — the only guaranteed property. Exactness is asserted only
  where it is guaranteed: two hand-built *tight* placements (a single row of abutting boxes, a
  single column of abutting boxes) where every pair's chosen relation has separation zero must
  round-trip identically. The generator for the componentwise property builds multi-row shelf
  packings so vertical relations are actually exercised — a single-row generator would test half
  the encoder. Encoding the same placement twice gives the same pair. An overlapping input raises
  `ValueError`.
- **Feasibility continuation.** A `SequenceSolver` built with adapters that never certify runs
  exactly `stage_limit` stages with `feasibility_continuation=False` and more with it, until the
  stub deadline fires; the appended restart seeds equal
  `derive_stage_seed(derive_stage_seed(seed, order), ordinal)`; an explicit `max_stages` with the
  default keyword is still a hard cap.
- **Feasibility continuation on the graphene fast path** (`@pytest.mark.slow`, 30 s budget).
  `graphene/output-products` under `SequencePairLayout` returns a placement whose
  `stats["feasibility_restart_batches"] >= 1.0`. This pins gate 1.
- **Freeform integration** (monkeypatched `time.monotonic`). Two branches, both asserted: when
  `projection_retry_affordable()` is False and `_room_for_another(deadline, soft,
  window_candidate_s)` is True, `_pack_window` is called exactly once for that failed pack and
  `_pack` is not called again for the same `(height, arrangement)`; when both are False, neither is
  called. A third assertion: the same `(height, arrangement, window)` is never solved twice.
- **Regression fences.** The existing tests that pin `select_lns_neighbourhood`/
  `repair_neighbourhood` (`tests/layout/test_sequence_pair.py:2182-2320`) and the no-good scoping
  tests in `tests/layout/test_freeform.py` must pass unchanged; if any needs a change, the change is
  a finding to report, not a fix to make silently.
- **Gate.** Section 3, run by script, with the baseline and candidate JSONL, the
  `audit_compare.py` output, and a `gate.md` committed under
  `docs/superpowers/evidence/2026-09-02-phase-c-alns/`.

**Measurement discipline.** Intermediate tasks measure with single-cell audits
(`scripts/audit.py --only <url_id> --jobs 4`) on the cell that task targets. The full three-round,
72-cell audit runs once, in the gate task. A 72-cell round costs 3 to 5 minutes and cannot be run
after every commit without dominating the phase.

Two existing test facts carry over from Phase A and must be respected: the wall-clock tests
`tests/layout/test_freeform.py::TestDirectInsertion::test_the_sweep_prefers_area_over_direct_insertion`
and `TestTheTimeBudgetIsAWall::test_magnetic_ring_repeated_one_second_calls_complete` were removed
during Phase B because they flake under load and must not be reintroduced, and
`tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` runs at
a 1.5 s budget and trips DID NOT RAISE when preparation gets faster. **The continuation makes the
second one more fragile**: a search that previously stopped at its stage limit now keeps going until
the deadline, so the test's refusal now depends on the continuation not finding an exact layout
inside 1.5 s. Risk 11 records it and the plan lowers the budget rather than deleting the assertion
if it trips.

## 9. Delivery order

1. Evidence directory and the Phase B baseline pointer.
2. Feasibility-first continuation, with the graphene gate. (Gate 1.)
3. `sequence_alns.py`: identities, records, DUCB selector, lexicographic reward, `operator_scale`,
   `destroy_strips(FAILED_ENDPOINTS)`, `metrics_from_evaluation`.
4. `_alns_substitution` as a standalone function.
5. Switch both call sites, plumb the session through `_production_run`, add `alns_evaluations`.
6. `finalize.band_target_width` and the `BAND_BOUNDARY` operator.
7. Open the destroy portfolio.
8. `encode_placement`.
9. `_pack_model` refactor with the equivalence-preserving split.
10. `_pack_window`.
11. `LOCAL_EXACT_PACK` in sequence-pair.
12. Freeform window adapters.
13. Freeform sweep integration. (Gate 2.)
14. The three-round corpus gate and its evidence. (Gate 3.)

These are the plan's fourteen tasks in order. Each is a separate commit that leaves the tree green:
`uv run pytest -q`, `uv run ruff check .`, `uv run mypy` against the locked baseline of 176
pre-existing errors. A step whose gate fails is reverted, not tuned around; a step whose measurement
misses its stated number is recorded with the number and reported.

## 10. Relationship to Phases A, B, and D

- **A** (merged, `b3c990a`) made an evaluation cheap enough that a search which spends more
  evaluations can fit a 30 s budget. Phase C is the search that spends them. It relies on A's
  Cython kernels, the spec-scoped `geometry_memo`, and `scripts/audit_compare.py`.
- **B must land first**, for two reasons: Phase C consumes `route_feedback.ClusterRelationNoGood`
  in the window model, and Phase C's gate uses Phase B's `audit_compare.py --regressions-only
  --require-clean <cell>` flags, which do not exist in Phase A's version of that script.
- **D** races the two strategies and shares incumbents and no-goods across them. It consumes this
  phase's operators unchanged; the only contract D needs from C is that a window solve is
  process-local and holds no global state, which it does — `OperatorSession` is constructed per
  `_production_run` and per `lay_out` and dies with them.
- Phase C explicitly does *not* fix the deadline overshoot on `quantum-chip/no-proliferator`. A
  continuation that appends restarts could make an overshoot worse, which is why the continuation
  branch checks `deadline_reached()` and `_start_measured_stage` before every appended stage and why
  the corpus gate keeps p95 at or under 30 s.

## 11. Risks

1. **The brief named the wrong hook for the selector.** It says the fixed neighbourhood rule lives
   in `_pose_stage_boundary_update`. It lives in `_routing_feedback_substitution`
   (`sequence_solver.py:2653`), called from `:1555` and `:2433`; `_pose_stage_boundary_update`
   (`:3739`) is the split/merge topology step. The spec follows the code. Consequence:
   `select_split_candidate` is *not* wrapped as an ALNS operator, contrary to the brief's "and a
   split step"; it stays where it is.
2. **No encoder exists, the one specified is not a bijection, and revision 1 had its vertical
   direction inverted.** Section 5.6. `vertical[second].append(first)` means `first` is *above*
   `second`, because `_earliest_coordinates` treats that list as `second`'s successors; revision 1
   read it the other way and would have produced placements that violate `decoded <= input` on
   every measured case. The direction is now derived in the spec from the sweep rather than from
   the variable's name, and the componentwise-`<=` property test is the standing check. What
   remains true of the corrected encoder is only that: never wider, never taller. It can still lose
   a direct insert the window solve bought. The mitigation is that the decoded placement is
   re-scored and realigned before acceptance, that non-exact re-encodes are counted, and that the
   real router decides.
3. **Exactness is not guaranteed, so a repair can be silently diluted.** Measured on the shipped
   encoder: 59 of 4000 shelf placements and 0 of 4000 scattered ones round-trip exactly. Nearly
   every re-encode is a compaction that moved at least one strip, which means a window solve's
   specific answer is only partly what the search continues from. That is acceptable because
   the compaction is never worse on area or band fit and is evaluated by the real router — but it
   caps how surgical `LOCAL_EXACT_PACK` can be in sequence-pair, and it is the first thing to
   examine if the gate shows windows accepted but no cell moving. The fix, if needed, is a
   gap-aware encoder that reinstates up to `_MAX_GAP` of slack per strip, not a looser acceptance
   rule.
4. **The window model can be infeasible or over-constrained for reasons outside the window.** An
   exact-pack or projection no-good matched entirely by pinned strips, or a `width_target` the
   pinned strips already violate, is skipped and counted (section 5.5). `alns_skipped_no_goods`
   exists so a chronically dropped constraint is visible at the gate.
5. **Evidence terms lose their gradient under heavy pinning.** `_pack`'s feedback objective builds
   `dx`/`dy` and hot-cell proximity variables from `xs[i]`/`ys[i]` (`freeform.py:3513-3555`). When
   both endpoints of a failed net are pinned, those terms are constants: they still sit in the
   objective, scaled by `evidence_cap = (width_bound + 1) * cap`, but they no longer *move*. A
   window that pins most of the evidence therefore optimizes almost pure width, and the routing
   evidence that motivated the repair has no influence on it. The two mitigations are that
   `BAND_BOUNDARY` selects exactly the strips the extent problem implicates, and that the outcome is
   credited by the real router. If the gate shows windows accepted but not improving, the fix is to
   require the window to contain at least one endpoint of a failed net, not to reweight the
   objective.
6. **Repeated identical windows.** A pack that fails the same way twice would ask CP-SAT the
   identical question twice and spend `C_WINDOW_SECONDS` for a known answer. Freeform dedupes by
   `(height, arrangement, window)` per `lay_out`; sequence-pair's windows differ by stage state, so
   an identical repeat there is credited `applied=False` when the result equals the seed and the
   selector's discounting demotes the arm.
7. **Symmetry breaking had to change.** `_pack`'s lexicographic constraint between identical strips
   is added only when both are in the window, because a pinned strip's current origin may violate
   it. With `fixed_at={}` the model is identical, and the equivalence test proves that; but a window
   containing one of a symmetric pair loses the symmetry break for that pair and may search
   redundant completions. At `C_MAX_DESTROY_STRIPS = 12` this is a bounded cost.
8. **Under `--jobs 16` the wall limit, not the deterministic limit, ends a window solve.** Section
   5.5. The consequence is a possibly worse incumbent, never an invalid one, and the gate records
   the mean observed window seconds so the deterministic bound can be lowered if the wall limit is
   doing the work.
9. **The AUC-0.5 finding bounds what any selector can learn.** No cheap signal predicts routability,
   so the selector can only learn from realized outcomes, and on the largest cells there are 2 to 8
   of them per budget. Discounted UCB over four arms will not converge in 8 pulls. What it can do is
   stop replaying an operator that just produced nothing, which is the specific failure mode the
   fixed rule has, and four arms is a portfolio small enough that one pass over it fits inside a
   large cell's budget. The gate measures refusals, not regret.
10. **Gate 2 has no column in the audit schema.** `scripts/audit.py`'s JSONL carries no
    per-candidate count, and this phase does not change that contract (Phase D does). So gate 2 is
    recorded from `PlacementStats["alns_evaluations"]` on single-cell runs of the four target cells,
    as absolute numbers in `gate.md`, alongside status, wall seconds, and area from the audit rows.
    No "candidates per budget rose" claim is made against the Phase B files, because those files do
    not carry the number.
11. **Continuation makes the 1.5 s deadline test more fragile.**
    `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`
    asserts a refusal at a 1.5 s budget. The continuation now keeps searching until that deadline
    rather than stopping at a stage limit, which is what the test wants — but if the continuation
    ever finds an exact layout inside 1.5 s, the test trips DID NOT RAISE. The remedy, already the
    remedy for the Phase A fragility, is to lower the budget until it refuses again and record the
    new value; never to delete the assertion.
12. **Four operators is a bet that two mechanisms cover four cells.** The scope cut assumes the
    graphene refusal is a scheduling problem and the three `universe-matrix` refusals are an extent
    problem. If a gate-2 measurement shows a `universe-matrix` cell failing for a reason
    `BAND_BOUNDARY` does not name — a blocker component, a congested cut — the answer is to add that
    operator under section 4's rule, in its own task with its own single-cell measurement, not to
    widen `BAND_BOUNDARY` until it covers everything.
