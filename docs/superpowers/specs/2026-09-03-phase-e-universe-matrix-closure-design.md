# Phase E: Universe-Matrix Closure

**Status:** Executed 2026-09-03–04 on branch `phase-e-universe-matrix`; Tasks 1–14 reviewed.
Gate E1 **PASSED** all five clauses
(`docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e1.md`): all four target
`universe-matrix/{output-products,all-products}` cells were CLEAN under both strategies in every
round, with 70/72 CLEAN, zero regressions, area ratios 1.0009 / 0.9994 / 0.9983, and p95 wall
29.07 / 28.45 / 28.36 s. The §5.2.1 witness reversion condition did not fire, so Task 5 is kept.
Gate E2 **FAILED**
(`docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e2.md`), and Gate E3 was not
run: `universe-matrix/no-proliferator` remained REFUSED under both strategies in all three rounds,
leaving every round at 70/72 CLEAN. Clause 2 nevertheless passed with INVALID 0, CRASH 0, no
regressions, area ratios 0.9990 / 0.9977 / 1.0004, p95 28.24 / 28.67 / 28.40 s, and maxima
28.72 / 29.90 / 31.89 s. Freeform made six distinct assignments and six evaluations per round,
launched and accepted one window per round, and recorded zero stale draws, but still refused with
the forbidden `PACKER defect` wording. Sequence-pair recorded 5 / 4 / 5 stages,
`destroy:failed-endpoints` 4 / 3 / 4 and `repair:local-exact-pack` 1 on the refusing rows, but zero
window solves; all nine sequence-pair `universe-matrix` rows had zero window solves, and
`all-products` also had zero local-exact-pack repairs. Thus Gate E2 clauses 1, 3 and 4 failed.

**Delivery-order deviation:** §§5.4.1 and 5.4.2 landed in the reverse of the planned order. The
continuation landed first because the diversification cut was unreachable behind the old gate. It
was bounded immediately by `C_SWEEP_STALE_DRAWS`: three duplicate draws cost only 0.06–0.09 s.
Both changes landed before Gate E1.

**Final branch validation and smoke:** the full Python suite passed; Ruff was clean; mypy reported
the exact merged baseline of 178 findings. `uv run --with build python -m build` produced the sdist
and CPython 3.14 wheel with both Cython kernels (bare `python -m build` lacked the build frontend).
The frozen web install, lint, typecheck, 289 tests and production build passed. The actual CLI entry
point is `uv run flab2bp` (the package has no `__main__`); budget-30 `universe-matrix` smokes for
freeform and sequence-pair both exited 0 with blueprints and no traceback, producing 153,976 and
131,034 bytes respectively. The product probe remains production-default-off per Ruling E11.

**Companion specs:** `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md` (the
program), `2026-09-02-phase-c-alns-window-repair-design.md` (Phase C, whose status note ranks the
levers this phase consumes), `2026-09-02-phase-d-portfolio-racing-design.md` (Phase D, whose
Ruling AN and lever 2 this phase touches).
**Predecessor state:** 66/72 CLEAN at budget 30 in every round of Phases C and D. All six refusing
cells are `universe-matrix` (three policies, both strategies).

Every `file:line` in this document is a design-time hint from `e0bf432`; Phase E was verified
against shipped symbols and gate evidence. Resolve current targets by symbol with LSP, not by line number.

## 1. Decision

Close the six `universe-matrix` refusals with changes aimed at the mechanisms the research measured,
in this order:

1. **Seat a both-fed ingredient on the outermost lane row.** The four cells that refuse on
   `output-products` and `all-products` under both strategies fail before routing starts: their
   `hydrogen` input port needs two belt approaches (it is fed from outside the block and from an
   internal producer) and the strip generator seats it on a middle lane row whose head tile has one
   free neighbour. One sort key in strip generation fixes all four cells; measured 66/72 to 70/72 on
   both strategies, zero regressions, area indistinguishable from noise.
2. **Make the band ceiling bind in both strategies.** Freeform keeps a 160-row candidate height
   whose own greedy seed is 162 rows tall because the reservation witness is a width no real pack
   reaches; sequence-pair's height schedule offers nothing between 128 and 160, so its only routed
   placement at 300 s is 2 to 3 rows over the ceiling. Both are height-generation changes, not
   search changes.
3. **Report refusals honestly and carry solver stats on refused audit rows.** Today the
   `no-proliferator` freeform refusal blames the validator (nothing wired), the other two blame the
   packer (nothing was routed), and a REFUSED audit row carries no solver stats at all, so no lever
   on these cells is attributable.
4. **Spend the clock on `universe-matrix/no-proliferator` only where it can buy something.**
   Freeform: give arrangements a real diversification cut so a second draw is not a byte-identical
   copy of the first, then replace the "no incumbent after arrangement 0" break with a continuation
   that stops on stale draws or the deadline, and widen Phase C's window trigger to any routing
   failure with a slot and clock to spare. Sequence-pair: probe the full destroy-by-repair product
   before the discounted-UCB takes over, so the window arm can be paired with the failure set, and
   count why a window proposal is dropped.

What this phase does **not** do: it does not add an operator, does not touch routing, does not change
`(area, belt_tiles)` ordering, does not change the default budget or the racing default, and does
not start the program's deterministic-fallback spike. The Phase C freeform "sweep-to-deadline" as
originally approved for this phase is not shipped on its own: R2 proved it is a no-op by construction
on these cells (every later arrangement returns the same assignment), so it ships only behind the
diversification cut and a staleness guard (section 5.4).

## 2. Evidence

### 2.1 The six refusing cells at `e0bf432`, budget 30

| Cell | Strategy | Refusal at HEAD | Wall used | Mechanism (research) |
|---|---|---|---:|---|
| `universe-matrix/output-products` | freeform | "no packing of 43 strips could be wired ... PACKER defect" | 2.0 s | port seating: 6 `hydrogen` ports `wants=2 held=1` (R2, R4) |
| `universe-matrix/all-products` | freeform | same, 42 strips | 4.5 s | port seating: 3 ports (R2, R4) |
| `universe-matrix/no-proliferator` | freeform | "every packing that wired was rejected ... 264x162 extent fits no band" | 3.3 s | seed 2 rows over the ceiling, then port seating: 6 ports (R1, R4) |
| `universe-matrix/output-products` | sequence-pair | "deadline exhausted" | 28 s | port seating (R4: the fix clears it) |
| `universe-matrix/all-products` | sequence-pair | "deadline exhausted" | 28 s | port seating (R4: the fix clears it) |
| `universe-matrix/no-proliferator` | sequence-pair | "deadline exhausted" | 28 s | routing-bound to 120 s; band-ceiling-bound at 300 s (R3) |

### 2.2 The port-seating defect (R4, R2)

- The stranded ports are the west head tile of the **middle** input lane of a lane stack. Three of
  its four neighbours are the sink strip's own belts and machine band; only the `WEST_CHANNEL` tile
  is free. That is true by construction for every middle lane of every strip.
- `_prepare_routing_problem`'s `twice` set (`freeform.py:14188-14196`) demands a second corridor for
  any input port whose item is also in `spec.external_inputs`, because the lane is fed from the
  boundary and from an internal producer. `_reserve_port_access` (`freeform.py:10061-10190`) then
  reports `wants=2, held=1`; `freeform.py:14512-14529` turns the port into a
  `RouteFailureKind.STATIC_ACCESS` `NetFailure` for every net ending there.
- A preparation failure short-circuits the router: `freeform.py:15042-15048` substitutes a synthetic
  stranded result and `freeform.py:15074` skips A* (zero expansions). It also forces
  `exhaustive=False` (`freeform.py:15141-15147`), so `_proof_scoped_no_goods` returns nothing
  (`freeform.py:14836-14841`) and no Phase B or C mechanism ever sees the failure.
- `universe-matrix` is the only corpus spec in which `hydrogen` is both an external input and an
  internally produced item; that is why `casimir-crystal`, `energy-matrix` and `quantum-chip` place
  the same strips and wire. The condition arrived with the rates commit (`98dfa5d`, extraction
  recipes priced as FactorioLab does), which is why the strip count changed from 46 to 42/43 and the
  two previously clean cells flipped (recorded in Phase C's baseline note).
- `input_items` at `strip_variants.py:928` is `tuple(sorted(group.inputs))`, plain alphabetical, so
  `hydrogen` lands in the middle by accident of the alphabet.

R4 measured four full 72-cell gates on a throwaway copy (loads recorded in the report):

| Arm | freeform | sequence-pair | total | area over the 66 clean cells |
|---|---:|---:|---:|---|
| baseline run 1 / run 2 | 33/36 | 33/36 | 66/72 | noise floor: 4 cells differ, up to 12.4 % per cell |
| both-fed items first, broad rule | 35/36 | 35/36 | 70/72 | 14 cells changed, +0.78 % total, one +27.2 % reproduced |
| both-fed items first, surgical rule (run 1, run 2) | 35/36 | 35/36 | 70/72 | 2 cells changed, +0.11 % total, inside noise |

The surgical rule reorders only items in `set(spec.external_inputs) & internally_produced`. Newly
clean in every arm: `output-products` and `all-products` under **both** strategies (the shared strip
generator is the fix's owner). `box_height` and `width` of both affected strips are unchanged.

Narrowing the `twice` predicate instead was tried and fails: the same ports fail again at route time
with `dynamic-access, exp=0`. The second corridor demand is real; the docstring, which speaks of a
shared lane carrying two items, is what is wrong.

### 2.3 The band ceiling (R1, R3)

- Freeform's only ceiling is `BandPolicySearchEnvelope.boundary_core_height = 160 - 2 * _ENTRY_RING
  = 154` (`finalize.py:107`). `_candidate_heights` (`freeform.py:18781`) is planet-blind;
  `reserve_boundary_height` (`finalize.py:145`) replaces a height only when it can prove it
  infeasible, and its witness is `_minimum_pack_width`, 92 for this cell, while every real pack is
  258 wide. A 98x166 extent fits the 200-segment band rotated, so height 160 survives; its greedy
  seed is 258x156, and with the two entry rings 264x162, which fits nothing. The rejection is a
  pre-pack seed gate (`freeform.py:17766-17779`); `finalize_placement` never runs, and the retained
  rejection makes `freeform.py:17026-17036` narrate "every packing that wired was rejected".
  Passing `max(_minimum_pack_width, seed.width)` as the witness in `_band_policy_candidate_heights`
  (`freeform.py:18798`) yields height 154, a 258x154 pack and a 264x159 extent; verified in a copy.
- Sequence-pair at 300 s (`no-proliferator`): heights `[99, 125, 160, 100, 80, 60, 127, 162, 102,
  82, 62]`, nothing between 128 and 160; the only height that routes is 160 and its finalized
  extent is 162 to 163 rows, refused by the finalizer. At 30 and 120 s the same cell is
  routing-bound (3 to 7 stranded nets on every candidate, `validation_time_s == 0`).

### 2.4 Why the clock is not the lever (R2, R3)

- Freeform breaks at `freeform.py:17729-17730` (`arrangement >= 1` with no incumbent) at slot 6 of
  15, with 25 to 28 s left; `_expired` is false so the deadline branch at `freeform.py:17037` is
  skipped and the unconditional raise at `freeform.py:17124` fires. Raising `--arrangements` to 16
  costs up to 10 s per cell and evaluates nothing new: every arrangement above 0 returns a
  byte-identical assignment and hits the duplicate-assignment skip (`freeform.py:17858-17859`).
- The Phase C freeform window never fires because `promote_retry` (`freeform.py:18225`) is false:
  `learned` is false (no proof-scoped no-goods) and `_feedback_retry_eligible`
  (`freeform.py:14900-14913`) requires exactly one failure against 3 to 6. Affordability was never
  the blocker. Forcing the window onto the failing packs made failures the same or worse.
- Sequence-pair refuses all three policies at 120 s. Four selector variants that make the window arm
  fire (10 to 24 solves, 9 to 20 installs at 30 s) produce zero CLEAN cells across 15 runs; each
  window solve costs a hard 1.006 s (CP-SAT always times out) and halves the stage count.
- After the seating fix, `universe-matrix/no-proliferator` under freeform still refuses, now with
  ordinary pack-specific `dynamic-access` / `sealed-pocket` / `commit-link` failures, 1 to 5 per
  pack and a different net each time, out of candidates at 20 s of a 120 s budget. That cell is
  where more diverse packs and the window repair can matter, and it is the only one.

### 2.5 The lockstep (R3)

`OperatorSession.observe` (`sequence_alns.py:524-528`) credits both ledgers from the same reward and
`applied` flag, so the destroy and repair ledger states stay index-identical forever; `_Ledger.best`'s
`untried[0]` (`sequence_alns.py:391-393`) and the UCB argmax then return the same index in both.
`(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` and `(BAND_BOUNDARY, SEQUENCE_REINSERT)` are unreachable
(60,000 random draws, 166 corpus selections). Every `(BAND_BOUNDARY, LOCAL_EXACT_PACK)` proposal dies
at `sequence_solver.py:3151` (empty or whole-problem set); `window_pack` is never called; a dropped
arm collects a zero reward and is drawn once in 76 at 300 s. A constant probe offset only rotates
which two pairings are reachable (a shifted bijection is still a bijection); walking the product does
reach all four.

## 3. Non-Negotiable Invariants

All of the program's invariants hold. In addition for this phase:

- No geometry rule is relaxed. `_seat_inputs` row caps, `_side_seatings` reach profiles, the
  attachment plan, sorter tiers, `finalize_placement` and the validator are untouched.
- A refusal names the subsystem that refused. A message may not say "wired" when nothing routed or
  "packer" when routing never ran.
- Search seeds and operator selection remain replayable. The product probe is a pure function of the
  draw ordinal and the two arm tuples; it reads no RNG and no clock.
- No wall-clock assertions in tests (Ruling S). Continuation and deadline behaviour is pinned with a
  fake `time.monotonic` and injected packs.
- Explicit `--arrangements` and `max_stages` remain hard caps.
- The racing default stays `race=False`; the default budget stays as it is.

## 4. Non-goals

- No new destroy or repair operator (`BLOCKER_COMPONENT`, `CONGESTED_CUT`, `ROUTING_REGRET` stay
  declared and undispatched); adding one is Phase C's rule, "a refusing cell names its mechanism",
  and after this phase at most one cell can.
- No change to the router's access model (`_reserve_port_access`, `_net_ends`,
  `_route_external_inputs`); R4's option (C) is ruled out by measurement.
- No staircase lane heads (R4's option (B)); it is the answer for a strip with three both-fed
  ingredients, which the corpus does not contain, and it taxes every strip's width.
- No cross-process no-good identity vector (Phase D Ruling AN stays); section 5.6 names the
  intra-arm receiver as a conditional lever, not a deliverable.
- No deterministic feasibility fallback; the program's item 8 is scheduled only if Gate E2 leaves
  `universe-matrix/no-proliferator` refusing under sequence-pair.

## 5. Design

### 5.1 Seat both-fed ingredients on the outermost lane row

**Owner:** `src/flab2bp/layout/strip_variants.py`, `_logical_strip_plans`, the `input_items`
assignment (`strip_variants.py:928`), and `_seat_inputs`.

**Rule.** Define, per spec, `needs_two_approaches = set(spec.external_inputs) &
{item for every group in groups for item in group.outputs}`. An ingredient in that set is seated on
the outermost lane row of whichever side it lands on: row 0 of `in_above` (north, farthest from the
machine band) or the last row of `in_below` (south, farthest from the band). Other ingredients keep
today's alphabetical order among themselves, so every strip that has no both-fed ingredient is
byte-identical to today's.

The rule is expressed on the **seated rows**, not merely on the order of `input_items`: R4's open
item 2 records that index 0 of `input_items` is the worst row if `_seat_inputs` seats lane 0 in
`in_below`. The implementation orders `input_items` so that both-fed items come first, and
`_seat_inputs` (or the row assignment it produces) is checked by the invariant below; if a both-fed
item is seated south, it takes the south outermost row.

**Invariant (checked in tests, over every corpus spec and every strip):** for every ingredient in
`needs_two_approaches`, the seated row is the outermost row of its side. Stated as a geometry
property: the lane head has at least as many free 4-neighbours on a canvas containing only that strip
as the number of independent feeds the lane accepts.

**Docstring correction.** The prose to rewrite is the `twice` paragraph in
**`_reserve_port_access`'s docstring**; the original `freeform.py:14188-14196` hint points instead
to the `shared_feed` construction and comment in `_prepare_routing_problem.hold_ports`. Both sites
are corrected to say what the code does: a lane fed from both the boundary and from inside the block
needs two approaches, whatever the lane's cardinality. The predicate is not narrowed.

**Tests (pure, no clock, no solver):**
1. Build the `universe-matrix` `no-proliferator` candidate, call `freeform.plan_strips(spec)`,
   assert `strip.in_above[0] == ("hydrogen",)` and `strip.row_of_input("hydrogen") == 0` for
   `casimir-crystal#1` and `energy-matrix#12`, and that `box_height` and `width` equal the
   alphabetical seating's.
2. The invariant above as a property test over every corpus spec.
3. A router-side pin beside `tests/layout/test_freeform.py:3108`: a canvas with a three-lane strip
   whose middle lane head is in `twice`; `_reserve_port_access` reports exactly that head in
   `failed_ports`. This catches a future reordering that puts a both-fed item back in the middle.
4. A strip with no both-fed ingredient plans byte-identically before and after (mutant: dropping
   the `not in needs_two_approaches` key must fail test 1 and pass this one).

**Expected effect:** `output-products` and `all-products` CLEAN under both strategies (70/72).

### 5.2 Make the band ceiling bind

**5.2.1 Freeform witness.** `_band_policy_candidate_heights` (`freeform.py:18798`) passes
`max(_minimum_pack_width(strips, h), _greedy_pack(strips, h).width)` as
`minimum_width_for_height` to `reserve_boundary_height`. The greedy seed is constructive, so a
height whose seed extent fits no band is a height whose first move is illegal; the boundary height
154 replaces it. `seeds` is already computed in that function.

Tests: a sibling of `tests/layout/test_finalize.py:2080`
(`test_portable_schedule_reserves_the_tallest_legal_core_boundary`) with a narrow witness,
`ordered=(125,160,100,80,60)`, `minimum_width_for_height={160: 92}`, asserting `(125,154,...)`; the
existing test passes only because its witnesses are 380 to 522 wide. Plus a freeform-level test beside
`tests/layout/test_freeform.py:16136` asserting that for every height
`_band_policy_candidate_heights` returns, `envelope.frame_candidates(*strip_outline(greedy(h)))` is
non-empty.

Area: R4 measured the witness fix bundled with the broad seating rule at +0.73 % total over the
surgical rule alone, inside a run pair whose noise floor is 12 % per cell, so that number is not
evidence either way. Gate E1 judges the witness change on its own with paired rounds. Decision rule:
if E1's area clause fails and a round with the witness change reverted passes, the witness change is
reverted and recorded in the status note, because it buys no coverage by itself (R4); the seed-gate
narration of 5.2.2 ships regardless.

**5.2.2 Freeform seed-gate narration.** The seed gate's rejection (`freeform.py:17766-17779`) is
kept in its own `skipped_heights` list, reported as "N candidate heights were skipped as over-band",
and never fed into `rejected`, so the narration at `freeform.py:17026-17036` cannot say "wired" for
a pack that never existed. The post-pack gate (`freeform.py:17911-17925`) still covers a real pack.

**5.2.3 Sequence-pair height schedule.** The sequence-pair height generator (the schedule that
produced `[99, 125, 160, 100, 80, 60, 127, 162, ...]`, resolved by symbol in
`sequence_solver.py`) offers at least one height in `[boundary_core_height - 6,
boundary_core_height]` (148 to 154 at 160 rows and 3-row entry rings), and offers no height above the
boundary core **whenever a distinct approach slot is free**. The exact spacing is a named constant
`C_CEILING_APPROACH_STEP` with a docstring naming R3's 300 s run. Tests: the schedule generator,
called with a fake envelope of ceiling 160, yields a height in the band and none above it; explicit
`max_stages` probes are unchanged.

Two implementation deviations, recorded here because they are behaviour and not detail:

1. The clause is conditional, not absolute. A replacement must be distinct — `SequenceSolver.__init__`
   raises on a duplicate height — and the transformation must preserve length and position, because
   `_production_run` re-splits the schedule BY INDEX into the coarse heights and the protected
   follow-ups. When the approach band's `C_CEILING_APPROACH_STEP + 1` slots are all taken, the
   over-ceiling height is left in place, which is exactly what happens today for every such height.
2. The bounding applies to the WHOLE schedule, not only once the deadline-continuation restarts
   begin, so it can rewrite the primary schedule of any corpus cell that ever schedules an
   over-ceiling height. Gate E1 is what judges that. The compact-seed height, which is prepended
   after the schedule is built, is bounded at its own site against the schedule it joins.

### 5.3 Honest refusals and stats on refused rows

**5.3.1 Freeform refusal text.** At the raise at `freeform.py:17124`: when every retained
`PackAttempt` has only `STATIC_ACCESS` failures and `routing.expansions == 0`, the message reads
"no pack was ever routed: N lane heads could not obtain the belt approaches they need (item, strip
...); this is a PORT-SEATING defect independent of the packing; every candidate height produced the
same N failures". The `PACKER defect` wording is reserved for the case where routing actually ran
and every pack left nets unrouted. `_reserve_port_access`'s `missing` record (`freeform.py:10188`)
threads `held`/`wants`/`options` into the `NetFailure` detail so the refusal names the port.

**5.3.2 Stats on refused rows.** `NoValidLayout` gains an optional `stats: Mapping[str, float | str]
| None` attached at the raise sites of both strategies (`sequence_solver.py:1535` and the re-raise at
`sequence_solver.py:6011-6018`; freeform's raises at `freeform.py:17116` and `17124`). `audit.Result`
gains `stats: dict[str, float | str]` (default empty) filled on CLEAN rows from `PlacementStats` as
today and on **every** REFUSED row — `run_cell` has two of them, and the second is the
`finalize.ProjectionRefusal` handler that follows the audit's own `finalize_placement` call, where a
placement exists and its own stats are the right source. The value type admits `str` because
`alns_operators` is a tally string (`operator_tally` returns `str`, and `PlacementStats` types it
`str`) and section 7's Gate E2 asserts on it. Keys this phase needs on refused rows: freeform
`attempts`, `evaluations`, `distinct_assignments`, `stale_draws`, `window_solves`,
`window_accepted`; sequence-pair `stages`, `alns_operators`, `alns_window_solves`,
`alns_window_accepted`, `alns_window_dropped_empty`, `alns_window_dropped_whole`,
`alns_window_unchanged`. Keys absent on a row are read as zero by the gate, or as the empty string
for `alns_operators`.

### 5.4 Freeform: diversify, then continue while new evidence appears

Applies only when no incumbent exists at the end of arrangement 0. A cell that wires is untouched.

**5.4.1 Diversification cut.** After each evaluated pack at a height, its assignment is kept as a
diversification cut for the **next arrangement at the same height only**, in a per-candidate
`(height, arrangement)` collection **beside** `_ExactPackNoGoodState` (`freeform.py:17323`) and never
inside it: that class is sweep-wide by construction — `_sweep` reads
`tuple(exact_no_good_state.no_goods)` for every candidate — and its entries are infeasibility proofs,
which a diversification cut is not (the comment at `freeform.py:18256-18259` makes the same argument
for feedback cuts). The cut is what makes arrangement N a different draw from arrangement 0; R2
showed that without it every later draw is byte-identical.

**5.4.2 Staleness-guarded continuation.** The break at `freeform.py:17729-17730` becomes: with
`best is None`, `not _expired(deadline)`, room for one more candidate by `_room_for_another`
(`freeform.py:18720`) and the `completion_reserve_s` check at `freeform.py:17760-17764`, keep
drawing; stop when `C_SWEEP_STALE_DRAWS` consecutive draws add no new entry to
`routed_assignments` (`freeform.py:17311-17318`) or when the deadline arrives. The sweep keeps its
one `OperatorSession` (constructed at `freeform.py:16974`) so the ledger spans the re-sweeps; it
keeps calling `_portfolio_soft_deadline` per turn (`freeform.py:17593`) and never rebinds `soft`.

**5.4.3 Trigger widening (Phase C lever 2; Ruling E12).** `_feedback_retry_eligible` drops the
"exactly one failure" conjunct and admits any non-exhaustive, non-empty `STRANDED` result with at
least one failure whose net has both a feedback weight and endpoint offsets. That broader predicate
means "aimable", not "take the old exact retry". The old exact feedback retry remains distinct and
single-failure-only: `single_failure_feedback_retry` is the path that consumes and bypasses the next
arrangement slot unconditionally; learned proof evidence may still consume it when a full retry is
affordable. An aimable multi-failure pack leaves the slot available. The window launch guard is
`retry_slot_found and not retry_admitted and best_failing`, so it is posed against the failing nets'
strips of the best-failing pack the sweep has seen **so far**. `_sweep` retains no earlier pack, and
re-posing against one would queue a repair at a candidate slot already consumed. The comparison is
strict: a pack that merely ties the fewest unrouted nets seen so far offers no better evidence than
the solve already spent, and R3 §4.2 prices one window solve at a hard 1.006 s. The
`_room_for_another` affordability calculation is unchanged. This execution change is recorded in
Phase C §5.7.

**Refusal text:** with more evaluations, the deadline branch at `freeform.py:17037-17122` applies and
already says "N packs were routed and the best of them still left M nets unrouted"; a stale stop says
"the sweep stopped after K draws that produced no new packing".

**Tests (fake clock, injected packs):** (i) repeating failing packs stop after `C_SWEEP_STALE_DRAWS`
and do not run to the deadline; (ii) packs that keep producing new assignments run until `_expired`
and no further; (iii) the refusal names staleness in (i) and the deadline in (ii); (iv) a cell with an
incumbent after arrangement 0 makes exactly today's number of draws; (v) the diversification cut is
scoped to `(height, arrangement + 1)` and absent from every other height; (vi) the window fires on a
best-failing pack with three failures and a slot; (vii) `--arrangements 1` still makes one draw.

**Racing hazard (documented, tested where cheap):** a refusing freeform leg may now hold its workers
until the deadline or staleness; the race is opt-in and its `wall_overshoot_s` on `best` rows is
the number a later racing gate watches. Nothing here changes the serial path's clock on a cell that
wires.

### 5.5 Sequence-pair: probe the product, count the drops

**5.5.1 Product probe.** Ruling E11 changed the execution contract after measurement:
`OperatorSession(..., probe_product=False)` is the default, and both production factories use that
default. Production therefore keeps master's discounted-UCB pairing. With `probe_product=True`,
while `len(self._choices) < len(destroy.order) * len(repair.order)`, `OperatorSession.select`
(`sequence_alns.py:500-575`) pairs
`(destroy.order[probe // len(repair)], repair.order[probe % len(repair)])` — destroy-major, with the
repair order **as declared** — still subject to `_affordable_repairs` (a probe naming
`LOCAL_EXACT_PACK` below `C_WINDOW_FRACTION_FLOOR` falls through to the D-UCB). Since
`SHIPPED_REPAIR = (SEQUENCE_REINSERT, LOCAL_EXACT_PACK)`, explicit-probe draw 0 stays master's own
`(FAILED_ENDPOINTS, SEQUENCE_REINSERT)` and draw 1 is `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`: the
window is posed against the routing-failure set, one ordinal later. Keeping draw 0 identical is
deliberate and measured — reversing the repair axis to reach the window on draw 0 moved six
`tests/layout/test_sequence_solver.py` behaviour tests. Those six production-behaviour tests remain
untouched; the selector expectations exercise the explicit probe. After the probe the two ledgers
are genuinely desynchronised and all four pairings stay reachable. Two ledgers are kept; the product
is probed, not learned (`OperatorSession.__doc__` still holds). `observe`, `reward_vector`,
`operator_scale` and dropped-proposal accounting are untouched.

The probe remains available for tests and future measurement, but does not ship on the production
path: with it enabled, Ruling E11 measured sequence-pair `universe-matrix/output-products`
REFUSED in 3/3 budget-30 runs and needing about 54 s at budget 60, versus about 25 s under master's
pairing. Gate E2 consequently measured the production-default-off path.

**5.5.2 Drop counters.** `_ProductionTelemetry` (`sequence_solver.py:4340-4346`) gains
`alns_window_dropped_empty`, `alns_window_dropped_whole`, `alns_window_unchanged`, incremented at
each drop site in `_alns_substitution` and in `window_pack` (`sequence_solver.py:5377-5414`,
Phase C open item 3), published in the stats dict (`sequence_solver.py:6171-6181`) and, through
5.3.2, on refused rows.

**Tests (pure, table-driven):** the eight tests R3 lists: the first draw that names
`LOCAL_EXACT_PACK` is paired with `FAILED_ENDPOINTS` (draw 1 under the declared repair order); every
shipped pairing is reachable within the first `|D| x |R|` draws (the test master cannot pass); each
ledger still plays every arm the same number of times over the probe;
selection is deterministic for the same observation sequence; a dropped window proposal is charged a
count and no reward; the window is still withheld without room; `_band_boundary` on a band-legal
placement is empty and on a vertical-only overflow is the whole problem; a whole-problem destroy set
never reaches `window_pack`. Every pinned choice-sequence expectation in the existing suite is
re-derived once, deliberately.

### 5.6 Conditional levers (not deliverables)

Named so the plan's stop conditions can point at them:

1. **Intra-arm no-good receiver.** If, after 5.1 and 5.2.3, the sequence-pair
   `no-proliferator` rows show the same stranded set re-derived across restarts (visible through
   5.3.2's counters), the next lever is a relation-exclusion collection in sequence-pair fed by the
   solver's own cluster no-goods across restarts. It needs none of Ruling AN's cross-process identity
   vector. It is out of this phase.
2. **Warm-start sequence-pair from the freeform placement through the race.** Out of this phase.
3. **The program's deterministic fallback spike (item 8).** Now scheduled because Gate E2 left
   `universe-matrix/no-proliferator` refusing under sequence-pair.

**Post-gate order:** Gate E2 fixes the remaining levers in this exact §5.6 order: (1) the intra-arm
no-good receiver — a relation-exclusion collection in sequence-pair fed by the solver's own cluster
no-goods across restarts, with no Ruling AN cross-process identity vector; (2) warm-start
sequence-pair from the freeform placement through the race; (3) program item 8, the deterministic
feasibility fallback. Item 8 is scheduled now because sequence-pair still refuses
`universe-matrix/no-proliferator`.

## 6. Public Interfaces

- `NoValidLayout(..., stats: Mapping[str, float | str] | None = None)`; existing positional and
  keyword callers are unchanged. The value type admits `str` for `alns_operators` (see §5.3.2).
- `scripts/audit.py` `Result.stats: dict[str, float | str] = {}`; JSONL rows gain a `stats` object on
  CLEAN and REFUSED rows; rows without it read as empty.
- `sequence_alns.OperatorSession.select` keeps its signature; the optional
  `OperatorSession(..., probe_product=True)` mode changes its first `|D| x |R|` draws, while
  production uses the default `False`.
- New named constants, each with a docstring naming the measurement behind it:
  `freeform.C_SWEEP_STALE_DRAWS`, `sequence_solver.C_CEILING_APPROACH_STEP`, and the three
  telemetry keys of 5.5.2. Any constant whose value collides with a linted game value is declared
  through `registry.LintException` (Ruling AI), never re-spelled.
- `pipeline.build`, the CLI, the web contract, `PlacementStats` keys already present, and every
  strategy's `lay_out` signature are unchanged.

## 7. Verification Gates

All corpus rounds run from a `git archive` of the measured tip with a hand-frozen `.git` so
`_head_commit` stamps rows (Phase D gate recipe), with `uptime` and `vmstat 1 3` recorded before
every round, never waiting for an idle box. Baseline rows are generated fresh at the branch point
with the same audit code. Evidence goes to `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/`.

### Gate E1: seating and ceilings (after 5.1, 5.2, 5.3)

Three interleaved 72-cell rounds at `--budget 30 --jobs 16`, baseline and candidate:

- `universe-matrix/output-products` and `universe-matrix/all-products` CLEAN under both strategies
  in every round.
- No regression: `audit_compare.py --regressions-only` reports zero REGRESSION lines against the
  baseline round; INVALID 0, CRASH 0.
- Area: paired ratio over the 66 baseline-clean cells within `--noise-area` 0.013 in every round; a
  single cell above 1.13x that reproduces in all three rounds fails the gate (R4's broad rule
  produced +27.2 % on one cell; the surgical rule must not).
- p95 wall at most 31 s; max cell at most 35 s.
- `no-proliferator` freeform refusal names routing, not the validator; its `projection_failures` is
  empty; every REFUSED row carries a non-empty `stats` object.

### Gate E2: `universe-matrix/no-proliferator` (after 5.4, 5.5)

Three interleaved 72-cell rounds at `--budget 30 --jobs 16` against E1's candidate rounds as
baseline:

- Pass: `universe-matrix/no-proliferator` CLEAN under both strategies in every round (72/72).
  Partial: CLEAN under one strategy in every round; the spec status note records which and why the
  other refuses, with the counters.
- No regression against E1's rounds; INVALID 0, CRASH 0; area within the same margin; p95 at most
  31 s; max at most 35 s (the continuation runs only on refusing cells, so a wall change on a
  clean cell is a defect).
- Sequence-pair rows for `universe-matrix` carry `alns_operators` with
  `repair:local-exact-pack >= 1` paired with `destroy:failed-endpoints >= 1`,
  `alns_window_solves >= 1`, and `stages` not more than 25 % below E1's row for the same cell.
- Freeform `no-proliferator` row carries `distinct_assignments >= 2` and either CLEAN or a refusal
  that names staleness or the deadline, never "PACKER defect".

### Gate E3: the program's budget gate (only if E2 passes at 72/72)

Freeform at 30 s: 36/36 clean in ten complete repetitions; sequence-pair the same. The full
720/720 production-concurrency gate and any default-budget change stay with the program's item 4
and are not part of this phase.

### Final repository gate

Full Python suite, ruff, mypy at the locked baseline (184) with no new diagnostic, package build
including the Cython sequence kernel, frozen web install, lint, typecheck, tests and production
build, live CLI smoke on `universe-matrix` for both strategies, whole-branch review before landing.

## 8. Delivery Order

1. Branch `phase-e-universe-matrix` in its own worktree from master; ledger under
   `.superpowers/sdd/2026-09-03-phase-e-universe-matrix-closure/` (untracked); baseline rounds.
2. 5.1 seating rule, invariant and tests; 5.3.1 refusal text; 5.2.2 seed-gate narration.
3. 5.2.1 freeform witness; 5.2.3 sequence-pair height schedule.
4. 5.3.2 stats on refused rows (`NoValidLayout.stats`, `Result.stats`).
5. Gate E1.
6. 5.5 product probe and drop counters (before the freeform work, so E2's sequence-pair clause has
   its counters).
7. 5.4.1 diversification cut; 5.4.2 continuation; 5.4.3 trigger widening, each with its tests.
8. Gate E2; Gate E3 if E2 passes at 72/72.
9. Status notes on this spec, Phase C's §5.7 (trigger widening) and Phase D's lever 2 (stats on
   refused rows); memory; whole-branch review; fast-forward merge.

Each task is implemented by a fresh subagent and reviewed read-only by an opus reviewer from an
archived commit; shared files (`freeform.py`, `sequence_solver.py`, `sequence_alns.py`,
`strip_variants.py`, `scripts/audit.py`) are edited by one agent at a time. Every symbol and call
site is resolved with Serena `find_symbol` / `find_referencing_symbols` (LSP fallback), plus a grep
for the quoted name whenever a signature or arity changes (monkeypatch sites).

## 9. Risks

- **A both-fed ingredient seated south.** No corpus spec exercises it; the invariant test is the
  guard, and the rule is stated on seated rows for that reason.
- **The unwritten coupling "the row north of a strip is free"** (`_size` charges `height +
  MARGIN`, `_greedy_pack` seats at the top of each slot) is what gives the outermost row its second
  free neighbour. A packer change that removed the margin row would reintroduce the refusal; the
  router-side pin (5.1 test 3) and the property test are the tripwires, and the coupling is written
  down in `strip_variants.py` next to the rule.
- **Three both-fed ingredients on one strip** would refuse again; the honest refusal text of 5.3.1
  names the mechanism, and R4's option (B) is the recorded answer.
- **Area churn from extra freeform draws** on cells that refuse today and might now wire at a
  different density; `(area, belt_tiles)` still picks the best, so the direction is not worse, but
  every committed area number for those cells changes once.
- **Stage cost of the product probe** (measured 9 to 15 stages against 11 to 17); the E2 clause
  bounds it at 25 %.
- **Sequence-pair area noise** is 12 % per cell between identical runs; the gates use paired
  three-round agreement, not single-run deltas.
- **The residual `no-proliferator` sequence-pair refusal** may survive every lever here; the spec
  says so in advance and names the conditional levers in 5.6.

## 10. Research Basis

The four research reports under
`docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/research/` (R1 to R4), each with its
commands, box-load lines and verbatim outputs, and the Phase C baseline note
(`docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline.md`) that attributed the strip-count
change to the rates commit.
