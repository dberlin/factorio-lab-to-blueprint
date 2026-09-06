# Speedups round 2: ranked levers for the next major throughput gain

**Status (2026-09-05): §2's first batch — L2 then L1 — is implemented and
GATED.**  `6efd447` (compact seed to a twelfth of the budget, 2.5 s floor),
`300116c` (four islands by default with the race completion grace) and
`c3d7229` (race parallelism kept, island deadlines clamped under the parent).
Three paired 30 s corpus rounds against master `a232f0a`: **zero regressions,
INVALID 0, CRASH 0, max `wall_overshoot_s` 0.000 s**, and
`sequence-pair universe-matrix/all-products` — REFUSED on master in all three
rounds — clears in two of three.  Sequence-pair area **-8.0 %** on the gate
corpus (the design's -13.6 % was four large cells; 16 of 36 corpus cells are
byte-identical), freeform unchanged.  §2's fourth gate item, peak RSS per
cell, is UNMET: nothing writes an RSS key for the non-raced sequence-pair arm.
Gate record: `docs/superpowers/evidence/2026-09-05-speedups-2/gate.md`.

**Status (2026-09-06): §2's second batch — L3 — is implemented and GATED
(PASS).**  `2cf583b` (memoize `_direct_alignment_targets` on the candidate
mapping's read set) and `ef3da8f` (memoize `_direct_net_candidates` per strip
pair, adapted spec pinned by identity), with the drift guard closed in
`ef2207a`.  Three paired 30 s corpus rounds against master `79eed92`: **zero
regressions, INVALID 0, CRASH 0, max `wall_overshoot_s` 0.000 s**, sequence-pair
area **-0.15 %** and freeform **-0.27 %**, both inside the baseline tree's own
+0.65 % round-to-round noise; the single differing cell
(`sequence-pair universe-matrix/all-products`) is a load flake that six
dedicated re-runs clear on both trees.  The memoized functions are 60-72 %
cheaper per call and the mall completes a second pass inside the same 60 s
budget, but the design's headline — 55-67 % of the sequence-pair search — was
measured at `a232f0a` and **no longer held at `79eed92`**: the first batch had
already taken it, leaving the pre-pass at ~10 % of a qc180 run, so the corpus
area is flat.  The brief's `DirectInsertTarget` copy path was NOT implemented
(0.12 s of a 23 s run at HEAD, measured); the lever moved to
`_direct_net_candidates` instead.  Next lever named by the measurement:
`_selected_strips` (`sequence_solver.py:3730`), 9.56 s cumulative on the mall.
Gate record: `docs/superpowers/evidence/2026-09-06-speedups-2-batch2/gate.md`.
L4 + L5 (third batch) are next and unstarted.

Evidence: `docs/superpowers/evidence/2026-09-05-speedups-2/README.md`
(measurements, cProfile dumps, core traces, two prototypes).  Baseline is
master `a232f0a` with the `2026-09-05-scale-levers` work already merged.

## 0. What "major speedup" means here, restated against this round's data

The last round's framing was "every large cell runs to its budget, so a cheaper
phase buys more candidate attempts, not a shorter run."  This round refines it
on three points, all measured:

1. **Cells do NOT reliably run to their budget.**  6 % to 37 % of a 30 s budget
   is never spent (evidence §1), because `_room_for_another`
   (`freeform.py:21268`) will not start a candidate unless the clock left
   exceeds the *dearest* candidate the sweep has completed.
2. **A build uses exactly 1.00 cores** for every second after start-up, on a
   128-core box, in both strategies, on all five cells (evidence §2).  The
   16-worker CP-SAT budget reaches one solve that costs 0.28-1.64 s of 22-28 s.
3. **More budget is not monotonically better quality.**  qc180/sequence-pair
   returns 17724 at 20 s and 21384 at 30 s (evidence §4).  Any lever must be
   gated with paired rounds, never a single run.

So the three currencies are: (a) same quality at a smaller budget, (b) more
search per budget, (c) refusals that become successes.  Every lever below is
scored in those terms.

---

## 1. Ranked levers

### L1. Turn on sequence-pair islands (MEASURED: -13.6 % area at the same budget) — cost S

**What.** `SequencePairLayout(islands=N)` and
`sequence_islands.run_sequence_islands` already exist, spawn N complete solves
with derived seeds, and keep the best exact result.  Production never uses
them: `pipeline.build(sequence_islands=1)` (`pipeline.py:503`), `cli.py:349-352`
raises it above 1 only for an *explicit* `--strategy sequence-pair` and never
for the default `best`, and `scripts/audit.py:126` builds
`SequencePairLayout(...)` with no islands at all — so the corpus gate has never
measured them.

**Evidence.** Prototype 2, `proto-islands.jsonl`, same 30 s budget:

| cell | 1 island | 4 | 8 |
|---|---|---|---|
| um60 | 17654 | 17654 (0 %) | 17654 (0 %) |
| qc180 | 21384 | 12608 (**-41.0 %**) | 12152 (**-43.2 %**) |
| gm200 | 22140 | 21402 (-3.3 %) | 22140 (0 %) |
| um120 | 43676 | 39312 (-10.0 %) | 38916 (-10.9 %) |

Mean **-13.6 % at 4 islands, -13.5 % at 8**; no cell got worse.  The win is
diversification, not throughput: on qc180 the winner used
`compact_seed_attempt = 6` at height 57, a branch the serial run
(`_serial_compact_seed_attempt`, always attempt 0) cannot reach — the serial run
lands at height 127.

**Gain.** Currency (a) and (b): 13 % less area at the same wall, and it takes
the sequence-pair arm from 1 core to 4-8 on a box that has 128.  Likely also
(c): `um120/sequence-pair` refused in one of two 30 s runs on master and every
island run cleared it.

**Risk / exactness.** The result is "best of N seeds", already deterministic per
seed (`_sequence_island_seeds` pins island zero to the serial seed, so a
1-island run is bit-identical to today).  Real risks: wall cost is +2-3 s
(25.3 -> 29.2 s on um60) for spawn plus ~0.9-1.3 s of import per child
(evidence §3), which is close to the 30 s gate wall and needs its own overshoot
check; N processes multiply peak RSS; and `_ISLAND_COMPLETION_GRACE_S = 90.0` is
a second budget, not a grace, so it must be replaced with the race grace before
this goes near the corpus gate.  Under `best`, `race_worker_split(16)[1] = 4`
caps islands at 4 — and 4 measured as good as 8, so that cap costs nothing.

**Cost.** S to change the default and thread it through `audit.py`; M including
the grace fix and a three-round paired gate.

---

### L2. Cut the compact-seed WALL share from 1/3 to 1/12 (MEASURED: +25 % of every sequence-pair budget, identical area) — cost S

**What.** `sequence_solver._COMPACT_SEED_WALL_SHARE = Fraction(1, 3)`
(`sequence_solver.py:191`, read at `:5060` and `:5920`) gives one third of the
whole budget — 10 s of 30 — to one CP-SAT solve pinned to
`num_search_workers = 1` (`compact_seed.py:453-457`, `:652-657`).  This is the
"~7 s CP-SAT lock wait" the previous profile could not name; cProfile shows it
as `{method 'acquire' of '_thread.lock'}` 7.18 s tot on um60-sequence-pair,
matching `compact_seed_wall_time_s = 7.02` exactly.

**Evidence.** Prototype 1, `proto-compact.jsonl`, budget 30:

| cell | area @ 1/3 | @ 1/6 | @ 1/12 | @ none | seed status at 1/3 |
|---|---|---|---|---|---|
| um60 | 17654 | 17654 | **17654** | 20600 (worse) | feasible, 2.56 det-s |
| qc180 | 21384 | 21384 | **21384** | 18445 (better) | **cancelled, 0.0 det-s** |
| gm200 | 22140 | 22140 | **22140** | 22140 | **cancelled, 0.0 det-s** |
| um120 | 43676 | 43676 | **43676** | REFUSED | unknown, 2.56 det-s |

Identical areas on 4/4 cells at 1/12, freeing 7.5 s of 30.  Those seconds buy
measurable search: qc180 goes 12000 -> 20000 anneal moves, 6 -> 12 decoded
candidates, 4 -> 7 detailed routes, 1.77 M -> 3.35 M A\* expansions; gm200 goes
3 -> 8 decoded candidates and 1.04 M -> 2.24 M expansions.

**Why it is safe.** On qc180 and gm200 the seed returns
`compact_seed_status = cancelled`, `deterministic_time = 0.0`, `closures = 0` at
*every* share — the 10 s is pure loss there.  On um60 and um120 it matters, but
2.5 s suffices (um60 reaches `feasible` in 1.48 deterministic seconds).  The
real bound on useful work is already the deterministic cap
`_COMPACT_SEED_DETERMINISTIC_SECONDS_PER_BUDGET_SECOND = 32/375`
(`sequence_solver.py:190`) = 2.56 deterministic seconds at budget 30.  The wall
share only binds when the solve cannot reach that cap — exactly the case where
it produces nothing.  Removing the seed entirely is NOT safe (um120 refuses).

**Recommended shape.** Do not just retune the constant: make the wall share
`max(deterministic-cap-derived floor, budget/12)` so it stays proportional and
cannot again be four times the useful work, and record `compact_seed_status` in
the gate so a future regression is visible.

**Gain.** Currency (b): +25 % of the sequence-pair budget spent on search, at
measured-identical area.  Plausibly (c) on the borderline um120 cell.

**Risk.** Low and bounded — the only cells that lose the seed's value are the
ones where 2.5 s already delivers it.  One run per configuration, so gate with
three paired rounds.

**Cost.** S.

---

### L3. Memoize `_variant_direct_eligibility` / `_direct_alignment_targets` — cost M

**What.** `_variant_direct_eligibility` (`sequence_solver.py:4352`) is a
one-call pre-pass that re-selects strips and re-enumerates
`DirectInsertTarget`s for every producer/consumer variant pair.

**Evidence.** cProfile cumtime, evidence §7:

| cell | `search` total | `_variant_direct_eligibility` | share |
|---|---|---|---|
| qc180-sequence-pair | 18.20 | **10.08** (1 call) | **55 %** |
| mall-sequence-pair | 49.58 | **33.35** (1 call) | **67 %** |

Underneath: `_selected_direct_targets` (`:3805`) 1561/3065 calls,
`_direct_alignment_targets` (`freeform.py:3163`) 2157 calls / 6.83 s cum,
`DirectInsertTarget.__post_init__` (`sequence_pair.py:216`) **131,840 calls** /
6.46 s cum, whose two `origin_deltas` generator expressions
(`sequence_pair.py:240`, `:242`) run 9.0 M and 7.4 M times.  On the mall
`_selected_strips` (`:3714`) is 24.00 s cum over 3345 calls.

This is the unfinished half of scale-levers §3b lever 9, which memoized
`_selected_strips`' `replace` and the clearance keys but left the enumeration.

**Design.** `_direct_alignment_targets(candidates)` is a pure function of the
candidate mapping and is called once per variant pair over a mapping that
changes in at most two entries — memoize it on the `_DirectCandidateSnapshot`
identity (that class exists at `freeform.py:3155` precisely to bind candidates
to their plan).  Separately, the `replace(...)` path re-runs a full
`__post_init__` on already-valid targets: keep the validation at construction
and give the replace path a checked constructor that revalidates only the
fields it changed.  Both are exact rewrites.

**Gain.** Currency (b), potentially the largest of all: up to 2x the
sequence-pair search inside the same budget on the two cells where it binds.

**Risk.** Memo-key correctness is the whole risk; a wrong key silently returns
another pair's targets.  The key must include everything
`_selected_direct_targets` reads.  Weakening `__post_init__` needs the
"validate at the boundary" argument written down, since this codebase validates
aggressively on purpose.

**Cost.** M.

---

### L4. Certify only a candidate that would become the incumbent (freeform) — cost M

**What.** `_sweep` calls `validate.certify(placement, spec, expect_power=True)`
on **every** completed candidate (`freeform.py:21121`) before any
`(area, belt_tiles)` comparison.

**Evidence.** `validate` phase seconds / calls, evidence §1: um60-ff 3.5 s over
5 calls (15 % of the run), gm200-ff 3.5 s over 4 (16 %), um120-ff **4.7 s over
3 (19 %)**, qc180-ff 2.2 s over 6.  Candidate count equals validate count, so
nothing is skipped today.

**Design.** Compare the finalized `(area, belt_tiles)` against the current
*certified* incumbent first; certify only when the new candidate would win, or
when there is no certified incumbent yet.  The certified set is then a subset of
today's and the returned placement is identical, because a candidate that loses
on area can never be selected regardless of its report.

**Gain.** Currency (b): 15-19 % of the freeform budget back on the largest
cells, i.e. roughly one extra candidate per run.

**Risk.** The failure mode to avoid is certifying nothing and then discovering
the incumbent is INVALID; keeping "certify every new best" preserves exactly
today's fallback behaviour.  `validation_reserve_s` is derived from observed
certify spans (`freeform.py:21133`) and must keep being fed, so the reserve
still needs one measured certify early in the sweep.

**Cost.** M.

---

### L5. Stop charging `_room_for_another` the *dearest* candidate — cost S/M

**What.** `_room_for_another(deadline, soft, candidate_s)`
(`freeform.py:21268-21289`) refuses to start a candidate unless the clock left
exceeds `dearest_candidate_s`, the maximum candidate the sweep has completed.

**Evidence.** Unused budget, evidence §1: gm200-ff 8.0 s of 30 (27 %), um60-ff
7.3 s (24 %), um120-sp 11.0 s (37 %), qc180-sp 6.2 s (21 %); mean across the
eight 30 s runs is 5.9 s (20 %).  The ladder (§4) shows utilisation of 62-104 %
with a mean near 86 %.

**Design.** Split the two things this predicate conflates.  What genuinely must
fit is the *completion* tail (`compaction_reserve_s + finalize_reserve_s +
validation_reserve_s`, already computed separately at `freeform.py:20197`), and
that stays a maximum.  What need not be a maximum is the estimate of the next
candidate's total: a median or a recency-weighted mean of completed candidates
with the completion reserve added is still safe, because an over-running
candidate is abandoned at `remaining <= 0` and discarded — the sweep already
holds its incumbent.

**Gain.** Currency (b): ~20 % more budget actually spent, which is
approximately one extra candidate on the large cells.

**Risk.** This is the guard that keeps the wall a wall.  It must not be relaxed
for the completion tail, and the corpus gate's `wall_overshoot_s`
(`scripts/audit.py:398`) is the check that would catch it going wrong.

**Cost.** S to change, M to gate honestly.

---

### L6. Memoize the coater `west_channel` lift and the `_StagedStaticPreclearanceProof` facade — cost S

**What.** `sequence_solver.py:3786-3800` recomputes, for every selected
spray-domain strip on every anneal state, `max(... for relation in
_staged_static_clearance_keys(selected_strip))` with a
`_staged_static_preclearance_proved` call per relation.

**Evidence.** mall-sequence-pair: `_StagedStaticPreclearanceProof.__call__`
(`freeform.py:1673`) **2,331,465 calls**, 2.75 s tot / **14.22 s cum** of a
49.58 s search; the enclosing genexpr (`sequence_solver.py:3790`) is 2,468,610
calls / 15.60 s cum.  The proof itself is already `@cache`d
(`freeform.py:1661`) — the cost is the ContextVar set/reset facade and the
generator around it.

**Design.** scale-levers §3b left this deliberately, because "proofs accumulate
during the run" so the answer can change.  That makes it a *versioned* memo, not
an impossible one: cache the computed `west_channel` per (strip geometry key,
proof-table generation counter) and bump the counter whenever a new proof is
installed.  Exact by construction.

**Gain.** Currency (b), concentrated on the mall-shaped specs — up to ~25 % of a
sequence-pair search there, near zero on the four corpus cells.

**Risk.** The generation counter must be bumped on every install path, including
the transactional one.

**Cost.** S.

---

### L7. Finalizer projection certification per candidate — cost M/L

**What.** `finalize_placement` -> `_certify_frame` -> `_failure_at_projection`
runs for every candidate.

**Evidence.** qc180-freeform cumtime: `finalize_placement` (`finalize.py:2690`)
8.35 s over 4 calls, `_certify_frame` (`finalize.py:1968`) 7.96 s,
`_failure_at_projection` (`finalize.py:1855`) 7.37 s over 296 calls — about
28 % of a 28 s run.  Supporting tottime: `_projected_power_candidates`
(`finalize.py:705`) 2381 calls / 2.04 s cum, `collisions_at` (`planet.py:1059`)
8901 calls / 3.82 s cum, `spherical_rotation` (`planet.py:463`) 164,133 calls.

**Design.** Two independent options: (i) apply L4's ordering to finalization as
well by pre-filtering on the pack's outline area before finalizing, so a
candidate that cannot beat the incumbent's outline is never finalized; (ii)
absorb the `planet.collisions_at` / `spherical_rotation` inner loop into the
existing geometry kernel, as the oriented-box overlap kernel (`ceb5eda`) already
did for `finalize`.

**Gain.** Currency (b): up to a quarter of the freeform budget on the
finalizer-heavy cells.

**Risk.** (i) changes which candidates get finalized, so the outline bound must
be proved to be a lower bound on the finalized area — it is not obviously one,
since finalization adds latitude padding.  (ii) is a parity-tested kernel port,
the same shape as work already done twice.

**Cost.** M for (i) if the bound holds, L for (ii).

---

### L8. `dataclasses.replace` churn and `is_belt` in the hot loop — cost S/M

**What.** The §5-deferred allocation churn, now measured big enough to rank.

**Evidence.** `dataclasses._replace` (`dataclasses.py:1782`): 122,943 calls /
1.97 s cum on um60-freeform, 525,223 / 6.22 s on mall-freeform, 516,332 /
6.66 s on mall-sequence-pair.  `is_belt` (`catalog.py:234`) is called
**17,557,761** times on mall-freeform for 2.59 s tot; `<lambda>`
(`freeform.py:17088`) 3,834,777 calls; `Fraction.__eq__` 1,869,188 calls /
1.67 s and `hash` 7.27 M / 2.16 s on mall-sequence-pair.

**Design.** `replace` on a frozen slots dataclass re-runs `__init__` plus
`__post_init__`; the hot sites (`_relink`, `assign_belt_slots`,
`_merge_frontier`, `_selected_strips`) mutate one or two fields of an object
whose invariants those fields do not touch.  Give those types an explicit
`_evolve` that constructs via `object.__new__` + `object.__setattr__` for the
proven-safe field sets.  For `is_belt`, hoist the item-id set lookup out of the
per-cell loop into a precomputed frozenset in the caller.

**Gain.** Currency (b): 5-13 % of the mall-shaped runs, 5-8 % of the corpus
cells.  This is the smallest per-lever gain on the list but the cheapest and
the most broadly distributed.

**Risk.** Bypassing `__post_init__` is exactly the kind of shortcut this
codebase avoids; it must be limited to field sets where the invariant is proved
independent, with a test that the bypassed constructor and `replace` agree.

**Cost.** S for `is_belt`, M for the `_evolve` work.

---

## 2. Recommended first batch

**L2 (compact-seed share) + L1 (islands), in that order, in one branch.**

Reasons:

* Both are **measured, not estimated**, on this box, this week, at the budget the
  gate uses.  Nothing else on the list is.
* They are the two cheapest items on the list (S and S) and they compose: L2
  gives every island 25 % more search, and L1 spends the freed seconds on
  diversified seeds instead of on the one branch the serial run explores.
  Islands at 4 also make L2 strictly safer — the cells that need the seed keep
  attempt 0 on island zero while the others explore.
* Together they address the round's headline finding (1.00 cores) with code that
  already exists and is already tested.
* Expected combined effect on the corpus: ~13 % smaller sequence-pair areas at
  the same 30 s budget, plus a real chance at the borderline
  `universe-matrix*120` / sequence-pair cell.

Gate for that batch, before anything else lands:

1. Three 30 s `audit_compare` rounds against master `a232f0a`, regression-only.
2. `wall_overshoot_s` explicitly checked, because islands add 2-3 s of spawn and
   `_ISLAND_COMPLETION_GRACE_S = 90.0` must be replaced with the race grace
   first.
3. Peak RSS recorded per cell at 4 islands (`strategy_race._peak_rss_kib`
   already measures this for racers).
4. `compact_seed_status` and `compact_seed_wall_time_s` recorded per
   sequence-pair cell so the L2 change is visible in the gate record rather
   than inferred.

**Second batch: L3 (direct-insert eligibility memo) alone.**  It is the largest
single gain on the list (55-67 % of the sequence-pair search on two cells) but
it is the one whose failure mode is a *wrong* answer rather than a slow one, so
it should not share a gate with anything else.

**Third batch: L4 + L5** — the two freeform budget-discipline levers, which are
the same conversation (what must fit before a candidate starts, and what must be
certified once it finishes) and want one gate between them.

---

## 3. Rejected

* **Give the CP-SAT solves more workers.**  Freeform's `_pack` is the only
  multi-threaded solve and it costs 0.28-1.64 s of a 22-28 s run
  (`pack_cp_wall_time_s`), so the 16-worker budget is already spent on 1-6 % of
  the work; widening it buys at most a second.  Raising `num_search_workers`
  above 1 on `compact_seed` (`compact_seed.py:454`, `:653`) or the corridor
  tie-break (`freeform.py:11484`) would trade the reproducibility those sites
  exist to guarantee for a solve that L2 shows should be *shorter*, not wider.
* **Compile more of A\*.**  `_astar` is already the Cython kernel at ~0.6 µs per
  expansion and is 6-25 % of wall; it is the search, not overhead.
* **Run the freeform height sweep in a process pool.**  The candidates are not
  independent: `exact_no_good_state`, `routed_assignments`, `minimum_pitch_x`
  and the ALNS `session` all accumulate across candidates inside `_sweep`
  (`freeform.py:19477+`), and a pack learned-about at height H prunes height
  H+1.  A pool would need the `strategy_race` message channel to exchange them,
  which is L-cost work whose payoff is bounded by L4/L5 first freeing the same
  seconds inside one process.  Revisit only after L4 and L5 land.
* **"Return the first clean layout" / early exit.**  Measured and rejected:
  evidence §4 shows um60-freeform improving 40920 -> 26752 (-35 %) between 8 s
  and 30 s, and qc180-freeform 24297 -> 15680 (-35 %) between 4 s and 12 s.
  Stopping at first-clean would cost a third of the area on half the corpus.
  The defensible version is a *stagnation* stop (stop after N consecutive
  candidates that fail to beat the incumbent), which on um120-freeform would
  recover 22 of 30 seconds for 0.07 % of area — but that is a variant of L5,
  not a separate lever.
* **Cut process start-up.**  1.41 s pre-search, of which 1.20 s is imports and
  ~85 % of that is third-party (`ortools.sat.python.cp_model` 0.347 s, which
  itself pulls pandas 0.267 s and numpy 0.093 s; `sympy` 0.267 s under
  `flab2bp.rates.solve`, which genuinely needs `sympy.solvers.simplex`).
  `flab2bp.layout.freeform` already imports neither sympy nor `flab2bp.rates`,
  so a spawned layout child pays none of the rate solver's cost.  There is no
  0.5 s here to win without vendoring someone else's package.
* **Raise `moves_per_stage` / `stages` for the anneal.**  Every corpus cell
  already reports `moves = 12000`, the full `6 x 2000` allowance
  (`SequenceSolverConfig`, `sequence_solver.py:254-255`), and then terminates on
  `deadline` in decode-and-route.  The binding constraint is detailed routing,
  not moves; L2 and L3 are the levers that reach it.
* **Cache `load_vendored()` across processes.**  20 ms.
* **Fix the `_room_for_another` overshoot by raising the budget.**  The gate is
  30 s by definition; buying clean cells with seconds is the thing the whole
  programme exists to avoid.
