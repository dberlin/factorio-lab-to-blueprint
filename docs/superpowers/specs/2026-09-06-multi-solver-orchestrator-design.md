# Multi-solver orchestration: coverage and time first, density inside a band

**Date:** 2026-09-06. **Tree:** worktree `design-multi-solver`, branch of master `79eed92`.
**Status:** design study, read-only. No code, no gate, nothing implemented.
**Sources credited:** Hindsight pages "Reliability program Phases B, C, D: last-mile router,
ALNS window repair, portfolio racing" and "Phase E: universe-matrix closure" (initiative
history, the parked multi-belt Deliverables B/C, the Serena-in-worktrees hazard). The
"Core concepts", "Component map" and "Key decisions and rationale" pages are empty in this
bank and contributed nothing; everything else is read from the specs, the committed evidence,
the git history and the code, cited inline.

**Honest answer first.** An orchestrator pays. A zoo of *dense* solvers does not. And the
single most important fact in this document is historical: this project already built a
structured, routable-by-construction solver — `layout/spine.py`, "Strategy A" — that reached
**66/72 corpus cells clean at a 1-second budget with zero validator errors**, and was
**15.5-19.2 % denser** than the freeform of its day, not sparser (§5.1). It was deleted, and
not because it was slow or loose. That changes the shape of the answer: "structured but
bounded-overhead" is not a hope, it is a thing this repo measured and then dropped.

---

## 1. Objective

The user's statement, which supersedes the density-first framing the current gates encode:

> *"At this point I feel like we may be a little far in the weeds of trying to minimize size
> at all costs. To me there is a huge difference between giving up 10 % size or 20 % size but
> being able to solve ridiculously large complex recipes relatively fast, and just giving up
> and laying out huge strips of things at near-zero cost but ridiculous sizes."*

So the objective is, in order:

1. **Coverage.** Every supported spec produces a valid blueprint — including 900-machine
   malls and deep chains like 2000/min green cubes — not a refusal.
2. **Time.** Inside a bounded budget, and preferably far inside it.
3. **Density, inside a tolerance band.** Within roughly 10-20 % of the best-known dense
   result for that spec, not minimised at all costs.

The two failure modes to avoid are both named in the quote: refusing (or taking 100 s and
still refusing) in pursuit of the last few percent, and laying out a trivially routable but
absurdly large blueprint. Correctness is not on this list because it is not in question:
across six full corpus rounds and ~70 investigation runs there is **not one INVALID verdict**
(`evidence/2026-09-05-speedups-2/gate.md` §1; `2026-09-05-multibelt-above-capacity-
investigation.md` §5). Every failure is an honest refusal. An orchestrator here buys coverage
and wall time; it cannot buy correctness because correctness is not missing.

### 1.1 How far today's gates are from that objective

Batch 1 of the speedups work is the cleanest illustration. It bought **-8.0 % sequence-pair
area** on the corpus and paid **+45 % corpus wall** — a round went from 133 s to 192 s, p95
per-cell wall 29.2 s → 31.1 s (`speedups-2/gate.md` §1, §3, §4). It was a good trade under a
density-first objective and a bad one under this objective, on a corpus that was already
71/72 covered. The gate that approved it was regression-only on area and status
(`gate.md` §6). Under the new objective that gate is measuring the wrong thing (§5.3).

### 1.2 What "one size fits all" means concretely today

The knobs that exist: **strategy** (`best`/`freeform`/`sequence-pair`, `pipeline.py:62-75`;
`best` = both, always, `_strategy_names` `:193-197`); **band policy** (`portable` or one
explicit `HxW`, `band_policy.py:49-58`, `:83-104`); **candidate policy** (`no-proliferator` /
`all-products` / `output-products`, `rates/candidates.py:45-50`, default all three laid out
by every strategy); **sequence islands** (default 4 spawned solves, `pipeline.py:93`,
`:104-140`, resolved from the *box* and never from the spec); **strategy race** (opt-in,
`race=False`, `pipeline.py:609`); **ALNS destroy/repair** (`sequence_alns.py`, selected
inside sequence-pair); and **workers / candidate parallelism** (`pipeline.py:80`, `:159-190`,
again from the box). Every one of them is set by the caller or the machine. None is set by
the shape of the spec.

Three consequences. **`best` is already a two-solver portfolio with no selection logic**: it
runs both arms on every candidate and takes `min(area, belt_tiles)` over the clean attempts
(`pipeline.py:1250-1256`) — a pure density rule with no time or coverage term.
**Spec-shape dispatch already exists, undeclared**: `_serial_compact_seed_attempt` picks a
topology role from `(machine_count, sprayed_lanes)` against measured thresholds 90/10/120/250
(`sequence_solver.py:221-225`, `:322-346`); `_dense_spray_initial_strip_len` keys on
`(sprayed_lanes, direct_candidates)` (`:230`, `:349-358`); freeform re-plans the whole strip
set above 40 strips (`_coarsen_saturated_strip_plan`, `freeform.py:2675-2707`). And
**freeform's search schedule is spec-independent**: exactly five candidate heights,
`isqrt(total strip box area) x {0.6, 0.8, 1.0, 1.25, 1.6}` (`freeform.py:21460-21467`),
band-filtered at `:21478-21527` — the same five for a one-machine smelter and a 935-machine
mall.

---

## 2. Failure and complexity taxonomy

### 2.1 The axis is complexity type; size is a magnitude multiplier

Size does not predict success. `gravity-matrix*200` — **349 machines**, 26 groups — lays out
on both strategies (`evidence/2026-09-05-scale-profile/README.md`). The mall at **449
machines** (5 objectives, 33 recipes, 46 strips) lays out on neither at 60 s or 100 s
(`speedups-2/gate.md` §5). `universe-matrix/no-proliferator` at **43 strips** is clean in
25 s; the mall at **46 strips** never produces a wireable pack.

The user's own contrast holds numerically. One recipe at high rate is easy at any size:
`iron-ingot*2400` and `*3000` (20 and 25 machines, 4-5 lanes) are CLEAN on both strategies
inside 30 s, on a Mk.III and on a Mk.II ceiling (`multibelt…` §1, rows A1-A6). A deep chain
at the same order of magnitude is not: `electromagnetic-matrix*1800` — blue cubes, 163
machines, 29 strips — **refuses on freeform** ("best pack left 4 nets unrouted") and needs
120 s on sequence-pair (row C3); `microcrystalline-component*1800`, 115 machines / 20 strips,
same pattern (row F5).

So the classes below are keyed on complexity *type*; size is the multiplier that says when
each mechanism binds.

### 2.2 The classes, with what they cost in coverage and time

| # | class | symptom | witnesses | strategy | mechanism | different algorithm, or bug? |
|---|---|---|---|---|---|---|
| C1 | **packer/router disagreement** | `no packing of N strips could be wired … That is a PACKER defect` (`freeform.py:19584-19590`), after 56-90 s of preparation | mall/all-products (46 strips, 449 m); belt3/no-proliferator (26 strips, 537 m) | freeform | the pack has no routability model; corridors are reserved *after* packing (`_reserve_port_access`, `:11634`) | **algorithm** — reserve corridors first (§4 D) |
| C2 | **no pack at all / band ceiling** | `no pack of N strips was ever produced …; 2 candidate heights were skipped as over-band`, in **0.6-0.9 s** | mall/no-proliferator (54 strips, 935 m); zurl2/no-proliferator (50 strips, 868 m) | freeform | five fixed heights; the largest legal band cannot hold 54 strips of this size — "a capacity refusal, not a hotspot" (`scale-levers/mall-profile/README.md` finding 7) | **algorithm** — decomposition or lane multiplicity (§4 E; `multibelt…` §4 Task 3) |
| C3 | **deadline exhausted** | `deadline exhausted` / `all 4 sequence islands refused`, at 60 s *and* 100 s | every ≥436-machine cell | sequence-pair | per-anneal-state cost scales with strips x coaters: `_selected_strips` 31 s of 93 s at 449 m; direct-insert geometry 34 s of 78 s at 935 m; prepare 12 s per candidate at 449 m (`mall-profile` findings 3-5) | **mostly throughput bug** — `speedups-2-design.md` L3/L6, designed and unbuilt |
| C4 | **spray-coater access** | a height is discarded when any coater cannot be seated (`_Unseatable`, `freeform.py:17823-17834`) | every `all-products` cell; sharpest at `universe-matrix/all-products` (69 coaters, 42 strips) | both | one coater per sprayed lane at the **lane head**, plus a one-cell lateral keep-out (`_coater_keepout_hits`, `:4930-4956`); it forbids direct insertion on that edge | **algorithm** — fold the coater into the strip (§4 B) |
| C5 | **port access / ingredient fan-in** | corridor matcher takes 71 s of 100 s (20 CP-SAT solves over 10 calls) | mall/all-products | freeform | `_match_access_corridors` runs a `maximize` per claim rank plus a lexicographic tie-break over every corridor choice (`:11473-11516`); claims scale with distinct ingredients per strip | **partly bug** (uncapped tie-break, fixed by scale-levers Task 10), partly C1 |
| C6 | **rate-free nets** | `flow.belt_capacity` (`validate.py:5469`): `belt run 95 must carry 35222/875 items/s but its tier sustains only 30` | zurl2/all-products (436 m), deterministic at 60 s and 100 s; `processor*1200` | freeform (and sequence-pair on C4-electric-motor) | `_nets_between` returns bare `(i, j)` pairs with no item and no rate (`:3613-3625`) | **model gap** — `multibelt…` §4 Task 2 |
| C7 | **both-fed / above one belt** | fixed `_merge_lanes` `ValueError`; `flow.sorter_capacity` (`validate.py:5611`) still has no planner-side cap | `universe-matrix*90/*120`; D3 on a Mk.II ceiling | both | supply-vs-draw confusion (`scale-levers-design.md` §2, closed); nothing bounds what a sorter must move | **planner limit** — `multibelt…` §4 Task 4 |
| C8 | **budget non-monotonicity** | more clock, worse or no answer | `electric-motor*600` mk2ceil CLEAN at 30 s and 60 s, REFUSED at a 30 s repeat and at 120 s; `zurl2` sequence-pair 40905 at 60 s vs **42255 at 100 s** | both | no retention of the best completed placement across the sweep; islands race on wall clock | **bug** — `multibelt…` §4 Task 5. Also the reason every dispatch change must be gated on paired rounds |
| C9 | **budget spent where it never pays** | sequence-pair burns the whole budget on cells freeform finishes in 2 s | the 18 tiny corpus cells (≤10 machines) | orchestration | `best` runs both arms unconditionally | **pure orchestration** |

### 2.3 The spray-coater case and the mall case, with numbers

**Coaters.** Same URL, two policies, freeform arm
(`evidence/2026-09-05-speedups-2/candidate-round3.jsonl`):

| cell | machines | strips | coaters | nets | area | wall |
|---|---|---|---|---|---|---|
| `universe-matrix/no-proliferator` | 224 | 43 | 0 | 69 | 26752 | 25.0 s |
| `universe-matrix/all-products` | 113 | 42 | **69** | **137** | **29744** | 26.0 s |

Half the machines, twice the nets, **11 % more area**. A coater consumes no grid tile
(`freeform.py:17803`) and still costs 11 %, because it must sit at its lane's head with a
keep-out, it blocks direct insertion there, and each one adds a proliferator-supply net. Its
search cost is measured: freeform `_place_coaters` 10 s over 5 calls at 449 machines (peel
4.3 s, keep-out hits 3.2 s, `mall-profile` finding 6); sequence-pair recomputes
`_staged_static_clearance_keys` for every coater strip on every anneal state, 14.9 s of a
31 s share (finding 3).

**The mall.** 935 / 449 / 830 machines across the three candidates, 54 / 46 strips, 33
recipes, 5 objectives. Nothing lays out at 60 s or 100 s, before or after batch 1. Its two
freeform failures are different problems: at 46 strips it produces packs it cannot wire (C1)
after 90 s, 80 s of that inside `_reserve_port_access` (C5); at 54 strips it produces **no
pack at all in 0.9 s** with two of five heights over-band (C2).

### 2.4 What the dense placers give up to buy their density

This is the quantification the objective demands.

*Coverage given up.* On the three large URLs at 60 s and 100 s, after batch 1: **18 of 24
rows REFUSED**; at 100 s specifically, **9 of 12** (`speedups-2/gate.md` §5). Freeform
refuses at 26, 46, 50 and 54 strips; sequence-pair refuses on the deadline at 537, 868 and
935 machines at *both* budgets. In the investigation, freeform additionally refuses at 20,
29 and 34 strips on cells sequence-pair clears (`multibelt…` §1 rows C1, C3, F5), and
sequence-pair refuses `electric-motor*600` where freeform succeeds (row C4). Neither arm
covers the other.

*Time given up.* Median build wall by size class, three candidate rounds, CLEAN cells only:

| class | median wall freeform | median wall sequence-pair |
|---|---|---|
| ≤10 machines (18 cells) | 2.1 s | **30.3 s** |
| 11-60 machines (11 cells) | 11.7 s | 29.5 s |
| >60 machines (7 cells) | 24.2 s | 29.2 s |

Sequence-pair spends the whole budget on a one-machine smelter. And the density that buys:
geometric mean `sequence-pair area / freeform area`, same rounds —

| class | gmean sp/ff area |
|---|---|
| ≤10 machines, coated (12) | **1.022** — freeform is *smaller* |
| ≤10 machines, uncoated (6) | 0.936 |
| 11-60 machines, coated (8) | 0.936 |
| 11-60 machines, uncoated (3) | 0.961 |
| >60 machines, coated (3) | 0.853 |
| >60 machines, uncoated (3) | **0.622** |

So on 18 of 72 cells we pay 28 extra seconds for 2 % *worse* area (coated) or 6 % better
(uncoated); on the three large uncoated cells the second arm is worth 38 %. Under a
10-20 % tolerance band, the tiny and mid classes are already inside the band with the cheap
arm alone, and only the large-uncoated class needs the expensive one.

---

## 3. What an orchestrator needs under this objective

### 3.1 A feature vector, computed once, before any placement

All of it is available from the rate solution plus one strip plan. Today each strategy
derives its own and neither publishes it.

From `BuildSpec` (`spec.py:122-199`; `MachineGroup` `:79-108`): `machine_count` (`:295`),
group count, **recipe-graph depth and width** (longest producer→consumer chain, widest
antichain), `len(external_inputs)`, `len(spray_lanes)` (`:189`), `lanes_requiring_split`
(`:195`), `lane_capacity` (`:310`), `belt_stack` / `piler_unlocked` (`:161`, `:175`),
`coproduct_buffer_proofs` (`:199`).

From one strip plan (`plan_strips`, `freeform.py:2442`): strip count; per-strip box;
**maximum distinct ingredient lanes on one strip** — the port fan-in that drives C5 and, as
§5.1 shows, the thing that killed the last structured solver; coater strips; `nets`
(`_nets_between`, `:3613`); direct-insert candidates (`:2713`); and two ratios that predict
freeform's two capacity refusals, `sum(strip box) / band area` (C2) and `nets / strips` (C1).

Cost: strip planning is under 1 s even on the stress cells (`scale-levers-design.md` §3,
"Not levers"). Computing it once and handing it to both arms is *less* work than today.

### 3.2 A registry where a solver claims a complexity class

```
class SolverEntry:
    name: str
    targets: frozenset[ComplexityClass]   # C1..C9, not size buckets
    admits(features) -> bool              # hard precondition, e.g. max_fan_in <= 6
    expected_cost_s(features) -> float
    expected_density(features) -> float   # ratio vs the class's best-known dense result
```

`LayoutStrategy` (`layout/base.py:582-614`) stays the execution interface unchanged. The
registry is description beside it, so a solver is added without touching the dispatcher.

### 3.3 Selection: an anytime portfolio, not "best area"

The selection rule the objective implies:

> Run the **cheapest solver whose expected density meets the floor for this complexity
> class**. If it returns inside the budget and inside the band, stop. Escalate to a denser
> solver only with the time that remains, and only while the incumbent is outside the band.

Consequences, spelled out because they invert current behaviour:

* `min(area, belt_tiles)` (`pipeline.py:1250-1256`) stays as the *tie-break among results we
  have*, but it stops being the reason to run a second solver. Today it is the only reason.
* A structured result that is 15 % larger and arrives in 2 s is a **success**, not a
  fallback, and should be returned as such when no denser result exists inside the budget.
* The escalation ladder is per class, and it is the orchestrator's whole job: e.g. for a
  high-fan-in mall, structured first, dense only if the structured answer is outside the
  band and time remains.
* A solver that trades density for routability is evaluated on **solve-rate and wall at
  scale first, area second**. That reverses the ranking every gate in this repo has used.

### 3.4 Composition with the race and islands

The orchestrator chooses the *field* and the *budget split*; `strategy_race.run_strategy_race`
still runs it. That is a strict improvement on today's fixed two-arm race, whose Gate D2
failed precisely because the field was fixed: under `--jobs 16` a `best` cell splits 8
workers into (6, 2), the raced freeform arm starts cold beside a competing CP-SAT process and
never reaches the serial arm's quality, so `best` came out **1.399x** worse than
`min(serial)` on `energy-matrix/output-products`
(`2026-09-02-phase-d-portfolio-racing-design.md`, status header). Narrowing the field on
classes where an arm has never won removes that starvation by construction. Islands stay
orthogonal — they diversify inside the sequence-pair arm and are resolved from the box budget
(`pipeline.py:104-140`); a freed slot is well spent on more islands for the one candidate
that needs them, which is how batch 1 turned `zurl2/all-products` from REFUSED into OK.

---

## 4. Candidate solvers and transforms

Ranked by cost, and judged first on solve-rate and wall at scale.

### A. Per-class parameterisation of the two existing placers — cost **S**

*Targets C9, C3, wall.* No new code path: choose strategy set, budget, island count and
candidate-policy order from the feature vector. From §2.4: freeform alone below the tiny
threshold (≈28 s saved on 18 of 72 cells, no density loss on the coated half); the
large-uncoated class to sequence-pair with the freeform seconds; both arms on large-coated,
where each wins cells the other loses. **Reuses:** everything. **Risk:** C8 — gate on paired
rounds, never one run.

### B. Composite coater+strip units (problem transform) — cost **M**

*Targets C4, and C1 on all-products cells.* Fold the coater body, its lateral keep-out and
its supply-drop cell into the **strip box** at plan time, and record the supply drop as a
real net. The packer then cannot produce a height whose coaters are unseatable, the corridor
matcher sees the claim up front, and `_place_coaters` (`freeform.py:17789`) becomes an
emitter rather than a search. **Reuses:** packer, router, finalizer, validator;
`prolif.coaters_are_supplied` / `prolif.sprayed_cargo_reaches_machines`
(`validate.py:4832`, `:5011`) remain the arbiters. **Evidence:** §2.3's 69-coater row, and
10 s + 14.9 s of measured per-arm search cost. **Risk:** a bigger box may push
`sum(box)/band` over the ceiling on cells that build today.

### C. Rate-aware net assignment (problem transform) — cost **M**

*Targets C6, probably C7.* `multibelt…` §4 Task 2 unchanged: widen the net tuple to
`(item, cargo_domain, rate)` and replace the cross product with a transportation solve over
producer supply and consumer demand, capped at
`min(consumer strip demand, lane_capacity x planning_stack(item))`. **Evidence:** the only
place a strategy is *wrong* rather than slow — freeform refuses `zurl2/all-products` with
`flow.belt_capacity` at 40.25/s on a 30/s belt, deterministically at every budget, while
sequence-pair lays the same spec out.

### D. Revive the structured skeleton ("spine") as a first-class fast solver — cost **L**

*Targets C1, C5, C3, and gives C2 an honest floor.* See §5.1 for the history: this existed,
it worked, and its removal was a supersession rather than a defeat. The core claim from its
own spec (`docs/superpowers/specs/section-strategy-a.md`, deleted at `5072a93`):

> *"The skeleton is routable by construction: every lane an item could need has a reserved,
> collision-free channel before the solver runs. CP-SAT therefore only ever chooses how much
> structure to spend, never whether a route exists. No place-then-route repair loop, no
> infeasible-placement dead ends."*

That is precisely the property C1 lacks. The one structural limit is documented and proved
(`a2805d3`): a row touches exactly two corridors and a sorter reaches 3 lanes into each, so a
machine can tap **6 distinct lanes**, and `universe-matrix#39` needs 7. Reviving it means
re-deciding that geometry — a wider corridor, a second sorter tier, or a two-row group — not
re-deriving the strategy. This is also the same shape as the reliability spec's
still-unbuilt "deterministic feasibility fallback" (`2026-09-01-zero-refusal-reliability-
design.md`: widest legal band, canonical strip ordering, explicit trunk and crossing
corridors reserved before placement, routing levels assigned before emission, existing
emitters/finalizer/validator retained), which is program item 8, conditional on Phase E.
**Reuses:** strip planner, router, finalizer, validator, encoder — all of which are far
better now than they were in August. **Risk:** the file was 5,593 lines with 3,457 lines of
tests; a revival is a port, not a `git revert`, and its fan-in cap must be lifted or it will
refuse the malls that motivated this study.

### E. Hierarchical / sharded block solver — cost **XL**

*Targets C2.* The optional "would be cool" design, worked out so the cost is visible.
*Decompose* the recipe graph into blocks of ≤ ~40 strips (the size at which freeform stops
re-planning, `_COARSE_STRIP_THRESHOLD`, `freeform.py:2675`, and below which both placers
demonstrably work — `universe-matrix` at 43 strips is clean): the mall's 54 strips become two
blocks of 27. *Interface:* a typed port list `(cell, item, rate, direction, lane index, cargo
domain)` on a shared bus corridor reserved before block placement, with taps at each block's
ports; the bus is what lets `flow.external_entry_points` (`validate.py:4499`) and
`flow.conservation` (`:5112`) still have something to check. *Composition:*
`finalize.finalize_placement` projects a **whole** placement and `validate.validate` judges a
**whole** placement — neither composes from parts — so blocks may be placed independently but
must be merged into one `Placement`, with every inter-block run routed by the same global
router over the merged canvas, then finalized and validated once. **For it:** C2 is a
capacity refusal in one band that no single-band search can fix. **Against doing it first:**
the largest new interface here, one of nine classes, no corpus cell needs it. **The
recommendation does not depend on it.**

### F. Keep or drop the freeform packer at high strip counts?

**Keep and gate.** It is the better placer on 18 of 72 cells and 10x faster (§2.4), and its
0.9 s refusal at 54 strips is cheap and honest. What must change is that the dispatcher stops
*sending* it a spec whose `sum(strip box) / band area` says no height can hold the pack — a
registry precondition, not a deletion.

---

## 5. Recommendation

### 5.1 The history that decides it: Strategy A ("spine")

Before freeform and sequence-pair, `src/flab2bp/layout/spine.py` implemented a structured
spine with a CP-SAT arrangement. What it achieved, from its own commits:

* **66/72 corpus cells clean at 1 s, 4 s and 15 s budgets, zero validator errors at every
  budget** — "no low budget ever produced an invalid layout instead of a refusal"
  (`a2805d3`, 2026-08-23). For scale: the reliability spec's baseline for *both* current
  strategies at 15 s was **63/72** (`2026-09-01-zero-refusal-reliability-design.md`,
  "Current Evidence").
* **15.5-19.2 % denser than the freeform of its day**, geometric mean over 8 URLs, stable
  across 2 s and 8 s budgets, both arms 8/8 on coverage (`e68937c`, `b2651ce`). Later, at
  tier mid and budget 4 s, a paired audit put it at **-1.31 %** — parity (`51147e9`).
  Freeform beat it on *building count* on four specs even while losing bounding box.
* Its refusals had one named, proved cause: the six-lane fan-in cap above.

Why it went away: it was **disabled from `best` on 2026-08-26** in the same day's work that
**promoted SequencePair into `best`** (`53d1885`, `8361d6b`), and deleted the next day
(`5072a93`, −5,593 lines of solver and −3,457 of tests). No commit body records a density or
coverage argument against it. The record is a supersession, and it happened at a moment when
the objective was density.

**This is directly load-bearing.** "Structured but bounded-overhead" is not speculative here:
it was measured at 1-second budgets with better coverage than today's pair has at 15 s, and
at density parity-to-better, not 10-20 % worse. The plausible trade a revived structured
solver asks for is therefore **generality, not density**: a fixed skeleton has hard
structural caps and refuses outside them, cheaply and early — which under this objective is
exactly the right failure mode, provided the orchestrator has somewhere to escalate to.

### 5.2 The decision

**Partial yes: build the orchestrator, and make the structured solver its default first
attempt on the hard classes.** Dispatch on **complexity class primary, size as a multiplier
inside each class** — not size tiers. A size-tier dispatcher would have put the mall and
`gravity-matrix*200` in the same bucket and been wrong about both.

Which existing placer is the better specialist today (§2.4): freeform for ≤10-machine specs
and for the coated tiny/mid classes, where it is equal or smaller in a tenth of the wall;
sequence-pair for large uncoated specs, where it is 38 % smaller; both for large coated
specs. Coverage is complementary in every class, so the field narrows only where the loser
lost in all three rounds of a paired gate.

**Build in this order.**

1. **Publish the feature vector (S).** Compute it once in `pipeline.build`, hand it to both
   arms, record it on every `audit.Result` row. Pure observability; nothing else here can be
   gated honestly without it.
2. **Anytime dispatch of strategy, budget and islands (S/M; §4 A).** The first change that
   spends the budget the way §1 asks. Motivating cells: the 18 tiny cells, and
   `energy-matrix/output-products` (Gate D2's 1.399x).
3. **Spike the structured solver's revival (L; §4 D)** against the mall and zurl2 *before*
   committing to it: port the skeleton onto today's router/finalizer/validator, lift or
   confirm the six-lane fan-in cap, and measure solve-rate and wall at 46 and 54 strips. This
   is a spike with a kill criterion, not a build.

Then, conditionally: **§4 C (rate-aware nets)** as soon as a second cell joins
`zurl2/all-products` in refusing on `flow.belt_capacity` — it is a correctness gap and should
not queue; **§4 B (coater composites)** whenever the coated classes are what is blocking;
**§4 E (hierarchical)** only if a real user spec cannot fit one band.

### 5.3 The gate this objective needs

Regression-only-on-area is the wrong gate now. Replace it with three components, and make the
**large-URL set the primary benchmark** with the 72-cell corpus as the regression guard:

* **Coverage (primary).** On the large-URL set (`speedups-2/large-urls/`, 3 URLs x 2 policies
  x 2 budgets = 12 rows per arm) plus the mall's third candidate, the count of rows producing
  a valid blueprint must **increase**, and no row may go valid → refused. Today's number to
  beat: **3 of 12 at 100 s, 6 of 24 overall.**
* **Time (primary).** p95 build wall must not rise, and median wall on the ≤10-machine class
  must **fall** (today 30.3 s on the sequence-pair arm). Corpus round wall is a reported
  number, not noise: 133 s → 192 s was a real cost.
* **Density (tolerance band, secondary).** Per cell, `area / best-known-dense(cell)` ≤ 1.20,
  with the best-known-dense figure pinned in the evidence directory and only ever revised
  downward. Inside the band, area is not a gate criterion; outside it, the cell fails. The
  geometric-mean area ratio stays as a *reported* number so a silent 5 % drift is visible.
* Unchanged: INVALID 0, CRASH 0, `wall_overshoot_s` 0, three paired rounds (C8 makes single
  runs meaningless), and `uptime` + `vmstat` recorded beside every timing.

### 5.4 What would make me say this is premature

If one arm dominated everywhere, or if the tiny classes were rare, the answer would be
"harden the two strategies". Neither holds: 18 of 72 cells pay 28 seconds for nothing, the
race's fixed field costs 40 % area on one measured cell, three of nine classes are cured by
transforms rather than search, and 9 of 12 large-URL rows still refuse at 100 s. What the
orchestrator does *not* buy is correctness (zero INVALID, six rounds) and it does not by
itself buy the mall — C2 is a capacity wall that only §4 D or §4 E reaches.

---

## 6. Open questions

1. **Do we revive spine, or write a new structured solver?** *I would revive — as a port onto
   today's router/finalizer/validator, behind the §5.2 spike's kill criterion.* Its 66/72 at
   1 s is the strongest single datum in this document, and rewriting from the spec throws away
   a year-equivalent of geometry bug-fixing. Against: 5,593 lines deleted six weeks ago will
   not apply cleanly to a codebase that has changed under it every day since.
2. **Where exactly is the density floor — 10 %, 20 %, or per class?** *I would set 20 % as
   the band and 10 % as the target, per class, pinned per cell in the evidence directory.*
   A single global number will be wrong for tiny cells (where 20 % is a few tiles) and for
   the mall (where 20 % of nothing is nothing).
3. **When a structured answer is inside the band, do we still spend the remaining budget
   trying to beat it?** *I would not, by default* — returning in 2 s is the product win, and
   an opt-in `--dense` flag serves the person who wants the last 15 %. Against: it makes the
   default output non-optimal in a way users may notice by comparing runs.
4. **Should the dispatcher be allowed to narrow the field to one arm, given that coverage is
   complementary?** *Yes, but only where the loser lost in all three rounds of a paired gate,
   and never for a spec whose feature vector is outside the measured range* — an unseen shape
   gets both arms. All the wall-time win is here; the risk is a refusal we would have covered.
5. **Is a spec whose strips cannot fit one band a refusal or a multi-blueprint answer?**
   *I would keep refusing, precisely* ("54 strips need N band-widths"), until a user asks
   otherwise — that decision alone determines whether §4 E is ever built, and it is a product
   question, not a solver question.

---

## 7. Rejected alternatives

* **Keeping `min(area, belt_tiles)` as the reason to run a second solver.** It is a pure
  density rule with no time or coverage term, and under §1 it is the wrong objective
  function. It stays as a tie-break among results already in hand.
* **A learned selector now.** 72 cells x 3 policies is ~200 labelled points; a learned policy
  would fit the corpus, not the class. The reliability spec's own rule applies — "learning is
  guidance for classical search, never an acceptance authority". A rule table with cited
  constants is auditable in a way a model is not.
* **Size tiers as the primary dispatch key.** 349 machines builds and 449 does not; 43 strips
  builds and 46 does not. `bench/corpus.py:23-40` already grades *budget* by size tier, which
  is the right use of size.
* **Forking `freeform.py` into per-class variants.** 21,527 lines, sharing planner, router,
  finalizer and validator with sequence-pair. Per-class *parameters* and *transforms* keep one
  code path under one gate; forks multiply the surface every validator change must be
  re-proved against.
* **Dropping the freeform packer above 40 strips** (§4 F), and **making the race default-on
  to paper over selection** — Gate D2 failed on area with the field fixed at two arms and the
  split at (6, 2); racing an unselected field is the problem, not the fix.
* **Building the hierarchical block solver first.** Largest new interface here, one of nine
  classes, no corpus cell needs it.
* **More CP-SAT workers or more compiled A\* to reach the mall.** Measured and rejected in
  `speedups-2-design.md` §3: the pack solve is 1-6 % of the run and A\* is ~0.6 µs per
  expansion. The mall's freeform failure arrives in 0.9 s; no throughput reaches it.
