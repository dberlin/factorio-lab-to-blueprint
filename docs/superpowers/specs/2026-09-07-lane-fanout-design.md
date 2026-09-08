# Producer-lane fan-out — design

Branch `lane-fanout`, cut from master `a1401518` (the `selfloop` merge). Every
number below was measured on this box on 2026-09-07, in this worktree, with
`uv run` bound to the worktree's own `.venv`
(`flab2bp.__file__` verified inside `.claude/worktrees/lane-fanout`). Nothing is
predicted, estimated, or rounded toward a better answer.

CPU pressure is the five-second mean of runnable processes
(`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`), never load
average. 128 cores; below 64 is fine. Before the probe series **11.4**, after
**12.4**.

Evidence: `docs/superpowers/evidence/2026-09-07-lane-fanout/probes/`.
The throwaway source patch every build probe ran against is saved verbatim as
`probes/throwaway-probe.patch`; `src/` in this branch is unmodified.

---

## 1. The refusal, exactly

`universe-matrix` refuses on all three candidate policies and both placers with

```
antimatter: mass-energy-storage#23 lane is 10 tile(s) wide
but must tap 15 consumer lane(s) of universe-matrix#37
```

The arithmetic that produces it is four lines:

| what | where |
|---|---|
| `tiles` is the producer strip's width | `freeform.py:19911` — `src_tiles[key] = min(src_tiles.get(key, s.width), s.width)` |
| a strip's width is its machine band and nothing else | `freeform.py:1017-1018` — `def width(self): return self.machines * self.pw` |
| the refusal condition | `freeform.py:19932` — `if per_lane > tiles:`, with `per_lane = -(-n_sink // n_src)` at `19930` |
| raised, freeform arm | `freeform.py:20517-20524` |
| raised, sequence-pair arm | `sequence_solver.py:4973-4980` — same `_fanout_shortfall`, its own `raise` |

So the two arms share one predicate and refuse for one reason. A fix at the
predicate covers both; nothing in `sequence_solver.py` needs its own fan-out
logic.

### 1.1 The one offending edge, and the tile budget behind it

`probes/probe_fanout_edges.py` prints every producer→consumer lane edge in a
spec's strip plan, offending or not (`probes/fanout-edges-um.csv`, 189 edges).
Across all three `universe-matrix` candidates exactly **one** edge offends:

| candidate | item | producer | src lanes | sink lanes | per lane | src tiles |
|---|---|---|---|---|---|---|
| `no-proliferator` | `antimatter` | `mass-energy-storage#23` | 1 | **15** | 15 | **10** |
| `all-products` | `antimatter` | `mass-energy-storage#23` | 1 | **12** | 12 | **10** |
| `output-products` | `antimatter` | `mass-energy-storage#23` | 1 | **12** | 12 | **10** |

Every other matrix ingredient clears it, and the CSV says why: they are either
wider (`energy-matrix#12` is 36 tiles) or already sharded across two producer
strips (`gravity-matrix#17`, `information-matrix#19`, `structure-matrix#33`
all have `n_src = 2`).

`probes/probe_producer_budget.py` (`probes/producer-budget-um.txt`) measures the
producer group:

```
producer group: strips=1 machines=1 pw=10 widths=[10] tail_extension=0
TOTAL TILE BUDGET=10
```

**One machine.** That is the whole story of lever (b) — see §3.

The 15 consumer lanes are not an accident either: `universe-matrix#37` is one
Matrix Lab family capped at **one machine per strip**, because `drain_outermost`
forces it (`freeform.py:973-981`, and spec
`2026-09-06-self-loop-recipes-design.md` §9 R2). Fifteen labs become fifteen
strips, each with its own single-item `antimatter` in-lane.

### 1.2 Corpus reach of the guard

`probes/guard-fires-corpus.txt` runs `_fanout_shortfall` over every corpus spec
at plan time:

```
cells where the guard fires: 3 of 36
```

All three are `universe-matrix`, all three name `antimatter`. Times two placers,
that is exactly the six cells the `selfloop` gate lost. Nothing else in the
corpus touches this code path.

---

## 2. Why the guard's model is wrong — measured, not argued

`_fanout_shortfall`'s docstring (`freeform.py:19888-19896`) says each reuse of a
producer lane "taps a different tile of that lane", so two taps on one tile would
need two splitters on one square. **The router does not work that way.**

`_pair_lanes` (`freeform.py:16074-16118`) pairs the two sides cyclically and
states outright that walking a lane inward was tried and is worse: a mid-lane
tile is walled in. What actually happens is in `_route`
(`freeform.py:9772-9789`): nets that share a source lane are grouped by
`same_src` and **branch off each other's committed paths**. `_tap_source`
(`freeform.py:13373-13401`) then builds the splitter wherever that sibling path
happens to be — not on a lane tile. `_Port.at_tile` (`freeform.py:6293`), the
method the tile-per-tap model is named after, has **no production caller at
all** (`grep -rn at_tile src/` finds only two comments and a hierarchy note).

The measurement. `probes/throwaway-probe.patch` adds
`FLAB2BP_PROBE_NO_FANOUT_GUARD=1`, which skips the refusal and lets the plan
through unchanged. With it set, on `all-products` at `--budget 120`
(`probes/p6-noguard-netdump.err`):

```
PROBE attempts=7 failed_counts=[1, 1, 3, 15, 22, 30, 212]
PROBE failed=1 by (item, kind): [(('titanium-ingot', 'static-access'), 1)]
PROBE   (src_strip,dst_strip): [((40, 38), 1)]
```

**The twelve `antimatter` nets leaving that 10-tile lane all routed.** The best
two packs of seven each left exactly one net unrouted, and it was
`titanium-ingot`, a `static-access` failure between two entirely different
strips. A 10-tile lane fanned out to twelve consumers, which the guard says is
impossible.

That is the finding. The guard refuses plans its own router can wire.

It is not baseless, though, and the honest version of its intuition is visible
at a shorter budget. At `--budget 30` the sweep gets two packs instead of seven
(`probes/p9-noguard-pw05-b30.err`):

```
PROBE failed=30 by (item, kind): [(('antimatter', 'dynamic-access'), 12), ...]
PROBE   (src_strip,dst_strip): [..., ((26, 41), 1), ((26, 42), 1), ((26, 43), 1), ...]
```

Twelve `antimatter` nets from strip 26 fail with `dynamic-access` — the lane's
free neighbour cells are contended. So the fan-out is **routable but expensive**:
it costs the router several packs and rip-up rounds to find. A refusal is the
wrong instrument for that; it is a cost, not an impossibility.

---

## 3. The levers, each with its measurement

### (a) Lengthen the producer lane to the tap count it needs — **LOSES**

`_box` already reserves tail columns (`freeform.py:1815`,
`s.width + s.west_channel + s.tail_extension + MARGIN`) for the piler work, and
the output lane's belt run is one line (`freeform.py:6786`,
`lane_tiles_of[s.row_of_output(k)] = width`). The probe patch adds
`FLAB2BP_PROBE_LANE_TAIL=1`, which sizes `tail_extension` to the shortfall on
every convicted producer, lengthens the emitted out-lane run to match, and lets
`_fanout_shortfall` count the tail. The `antimatter` lane goes 10 tiles → 15.

| probe | budget | best pack | the failures |
|---|---|---|---|
| `p6` guard off, lane 10 tiles | 120 s | **1** net unrouted | `titanium-ingot static-access` (40→38) |
| `p7` lane tail, lane 15 tiles | 120 s | **1** net unrouted | `titanium-ingot static-access` (40→38) — identical |
| `p9` guard off, lane 10 tiles | 30 s | 30 net unrouted | `antimatter dynamic-access` ×12 |
| `p10` lane tail, lane 15 tiles | 30 s | 27 net unrouted | `antimatter dynamic-access` **×12** — unchanged |

The tail changes nothing, at either budget, and in particular does not move the
twelve `antimatter` failures by one. It cannot: the taps do not leave from
distinct lane tiles, they branch off siblings' paths (§2), so extra tiles are
extra belt nobody uses. Rejected on measurement, not on taste.

### (b) Split the producer output across parallel lanes — **IMPOSSIBLE**

`_shard_sinks` is called with `max_shards=group.count`
(`strip_variants.py:1596`) — the number of MACHINES, because a shard with no
machine leaves its destinations unfed (`freeform.py:1899-1906`).
`mass-energy-storage#23` has **one machine**. There is no second shard to give.

And even with machines to spare, sharding cannot fix a tile shortfall. `n`
shards of `m/n` machines each are `(m/n)·pw` tiles wide and tap `ceil(n_sink/n)`
lanes, so the condition `ceil(n_sink/n) ≤ (m/n)·pw` reduces to
`n_sink ≤ m·pw` — the group's total tile budget, invariant in `n`.
`probes/producer-budget-um.txt` prints the counterfactual for every affordable
`n`; there is one row and it says `still short`. Rejected.

### (c) Feed a consumer lane by a routed net from the producer port — **ALREADY THE CASE**

This is what the router does today and what §2 measured: the net leaves the
producer lane's port and, when a sibling got there first, branches off the
sibling's path. There is nothing to build. The lever's premise — that taps are
tile-bound and nets are not — is the thing that turned out to be false. Folded
into (e).

### (d) Chain consumer lanes, tail to head — **LOSES on cost**

All 15 lanes carry only `antimatter`, so a chain is legal (`belt.acyclic` is
untouched: a chain is a DAG). It would cut the tap count from 15 to 1. But it is
a change to the flow model, not to a guard: a chained lane must carry the SUM of
everything downstream of it, which wakes `_check_shared_lane_capacity`
(`freeform.py:2115-2124`, dormant since §9 R1) and changes what
`layout/validate.py` decomposes into single-commodity flows. It buys a problem
that §2 shows we do not have. Rejected as unnecessary, and recorded here so a
future spec that does need it knows what it costs.

### (e) Retire the tile-per-tap arithmetic — **CHOSEN**

Delete the `per_lane > tiles` refusal. The predicate's true content — that a
producer lane must have somewhere to drain to at all — is already enforced by
`_drainable_by_port` (`freeform.py:19940-19949`) and by `_shard_sinks`'
distinct-cargo check (`freeform.py:1917-1922`). What is left of
`_fanout_shortfall` after the arithmetic goes is nothing, so it goes with it, at
both call sites.

**Cost if this ruling is wrong:** a spec whose fan-out really is unroutable now
burns a full height sweep before refusing, instead of refusing in milliseconds.
That is the cost `_fanout_shortfall` was written to avoid
(`freeform.py:19896-19899`). It is bounded by one budget per candidate, it is
paid by no corpus cell today (§1.2 — the guard fires on three specs, and all
three are the ones we are trying to unblock), and the paired corpus round in the
gate is what measures it.

---

## 4. What the fan-out fix does NOT buy — the two blockers behind it

This is the part the brief's PASS condition depends on, and it must be stated
before the plan rather than discovered in the gate.

With the guard bypassed, `universe-matrix` does not build. It refuses further
down, twice, for reasons that have nothing to do with fan-out.

### 4.1 The freeform packer's fixed deterministic work bound

`probes/p1-noguard-build.err`, `--budget 30`, all six pairs:

```
freeform/no-proliferator: no pack of 57 strips was ever produced at any candidate
height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the
0.02-unit deterministic work bound a pack of 57 strips is given, so the SOLVE
gave up before the packing was shown impossible, and 28.7s of the 30s ceiling
went unspent; the sweep stopped after 5 draws that produced no new packing
```

**It is not a clock.** `probes/p2-noguard-b300-freeform.err` runs the same thing
at `--budget 300` and gives up in **2.58 s** with 299.1 s unspent,
`pack_cp_solves=5 pack_cp_unknown=5 pack_cp_deterministic_time_s=0.100477
stale_stop=1`.

The bound is `_DETERMINISTIC_PACK_WORK = 0.02` (`freeform.py:365`), applied to
every pack of `_DETERMINISTIC_PACK_STRIPS = 15` strips or more
(`freeform.py:354`). Its own comment says it was calibrated on "the
authoritative fifteen-strip cell". A 53-strip pack gets the same 0.02 units and
never produces an incumbent. Raising it to 2.0 for the probe
(`FLAB2BP_PROBE_PACK_WORK`) turns `pack_cp_feasible=0` into
`pack_cp_feasible=10, pack_cp_optimal=1` and lets the sweep reach routing at all.

This is a scaling defect, and it gates `universe-matrix` independently of
fan-out.

### 4.2 The residual routing failures

Once packs exist, the best freeform pack at `--budget 120` still leaves one net
unrouted — `titanium-ingot`, `static-access`, strips 40→38 (§2) — and at
`--budget 30` the sweep only reaches two packs, where the `antimatter`
`dynamic-access` contention has not been negotiated away yet.

The sequence-pair arm has its own wall. `probes/p8-noguard-seqpair.err`,
`--budget 120`, guard bypassed:

```
sequence-pair/all-products: all 4 sequence islands refused: island 0: deadline
exhausted before finding an exact layout; island 1: ... island 2: ... island 3: ...
```

Not a fan-out refusal — an exact-layout deadline at this strip count.

### 4.3 Ruling F1 — the PASS condition needs three fixes, and the plan says so

The brief's PASS condition is all six `universe-matrix` cells CLEAN at
`--budget 30`, corpus 72/72, zero regressions. **The fan-out fix alone does not
reach it, and no probe suggests it could.** The measured chain is

1. `_fanout_shortfall` refuses (§1) — fixed by §3(e);
2. the packer produces no pack for 53–57 strips (§4.1) — fixed by scaling the
   deterministic bound with the pack's size;
3. the router needs more packs than 30 s buys, and leaves one unrelated
   `static-access` net even at 120 s (§4.2); sequence-pair exhausts its exact
   deadline.

The plan carries all three, in that order, because each one is only visible once
its predecessor is gone. Blocker 3 is the one with no measured fix in hand, and
the plan's gate reports what it measures rather than promising a verdict.

*Cost if this ruling is wrong:* nothing is lost — 1 and 2 are real defects
worth fixing whatever 3 does. What would be lost by NOT recording it is the
gate arriving as a surprise.

---

## 5. Scope

* **Both arms.** One predicate, two `raise` sites (§1). The fan-out change is
  not freeform-only, but it needs no sequence-pair-specific logic — only the
  second call site deleted.
* **The packer bound is freeform-only** (`freeform.py:365` is read by `_pack`).
  Sequence-pair's deadline exhaustion is its own, separate, and is scoped to a
  measurement task rather than a fix.
* **The absolute ban stays.** Nothing here reintroduces a shared or mixed input
  lane; `_check_shared_lane_capacity` and the other two dormant guards stay
  dormant and stay in the tree (spec `2026-09-06-self-loop-recipes-design.md`
  §9 R1).
* `belt.acyclic` is untouched and stays absolute.

---

## 6. Rulings

**F1 — three blockers, staged.** §4.3. Binding on the plan's shape.

**F2 — `_fanout_shortfall` is deleted, not weakened.** A guard whose arithmetic
is wrong and whose remaining content is already enforced elsewhere is not
improved by a looser constant; it is removed, and its docstring's model is
recorded here so the next reader does not rebuild it. If a real fan-out bound is
ever discovered, it will be discovered as a routing failure with a measurement
attached, which is where it belongs.

**F3 — the lane tail is not shipped.** Lever (a) is implementable and cheap and
was measured twice at two budgets and bought exactly zero nets (§3a). Shipping
it would add belt tiles, area, and a `tail_extension` interaction with the piler
plans for no effect. Recorded as rejected so it is not re-proposed.

**F4 — `_DETERMINISTIC_PACK_WORK` scales with strip count, and the scaling is
calibrated by measurement, not chosen.** The plan's task measures the corpus
p50/p95 pack time at the shipped constant and at candidates, and the paired
corpus round is the arbiter. A fixed larger constant would tax every cell in the
corpus to unblock one.
