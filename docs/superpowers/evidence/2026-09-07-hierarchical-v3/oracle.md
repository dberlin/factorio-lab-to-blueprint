# What the boundary-aware oracle predicts about the router, rung by rung

Task 6 of `docs/superpowers/plans/2026-09-07-hierarchical-v3.md`, on branch
`hierarchical-v3` at `a2ecd5b2`. No `src/` file is changed by this task.

`gate.md` §3.4 could only report the rung the composer COMMITTED, because both
its harnesses wrapped `pack_with_access` and saw only its return value. This
measurement wraps that function and, before calling through to it, walks EVERY
rung of `compose.GAP_LADDER = (2, 4, 6, 8, 12, 16)` itself: it packs the rung,
asks `_reserve_port_access` the trunk-goal question Tasks 4 and 5 shipped, and
then routes that rung's canvas with `_route_all`. The harness is
`rung_probe.py` beside this file; its module docstring says exactly what it
wraps, what it does not change, and why the raw goal-driven verdict and the
routing column are read off two different reservations.

## The runs

Both cells are `--strategy hierarchical --band portable --candidate-policy
all-products --budget 180`, one build each, belt3 first and zurl2 only after
belt3 had finished. **180 s is a MEASUREMENT budget and not a gate budget**;
no gate clause may be read from these two runs.

| cell | shell wall | compose wall on entry | rungs judged | exit | load sample |
| --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 139.66 s | 139.41 s | **6 of 6** | 3 | `rung-belt3-all-products-load.txt` — load avg 64.99, 89 % idle, 0 % iowait |
| zurl2 / all-products | 182.51 s | 157.46 s | **6 of 6** | 3 | `rung-zurl2-all-products-load.txt` — load avg 13.38, 90 % idle, 0 % iowait |

Every rung of both cells was judged and routed; nothing is truncated. Each
rung's `_route_all` ran on roughly a sixth of the composition's wall
(`rung_deadline_s` in the JSON, 20.5–58.0 s on belt3 and 20.7–23.0 s on
zurl2), which matters for zurl2 and is dealt with under finding 3.

## belt3 / all-products — 9 blocks, 77 cut nets, 91 demands

`missing`, `of which sealed` and `assigned` are the RAW goal-driven verdict —
the one `pack_with_access` discards. `verdict` says whether that rejection was
GRADED (some demands assigned, some not: a geometric answer) or WHOLESALE (the
matcher assigned nothing at all: a give-up, not geometry). `routed` /
`unrouted` are measured after the shipped rule has been applied, so they are
comparable with production on that rung's canvas.

| gap | canvas | demands | `missing` | of which sealed | assigned | verdict | routed | unrouted | by kind | reserve wall | route wall |
| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| 2 | 228×98 | 91 | 91 | **0** | 0 | WHOLESALE | 62 | 15 | DYNAMIC_ACCESS 7, COMMIT_LINK 4, SEALED_POCKET 4 | 0.59 s | 15.01 s |
| 4 | 143×172 | 91 | 91 | **0** | 0 | WHOLESALE | 61 | 16 | COMMIT_LINK 6, DYNAMIC_ACCESS 6, SEALED_POCKET 4 | 0.45 s | 10.46 s |
| 6 | 269×98 | 91 | 91 | **0** | 0 | WHOLESALE | 70 | 7 | DYNAMIC_ACCESS 6, SEALED_POCKET 1 | 0.45 s | 10.84 s |
| 8 | 280×98 | 91 | 91 | **0** | 0 | WHOLESALE | 68 | 9 | DYNAMIC_ACCESS 6, COMMIT_LINK 2, SEALED_POCKET 1 | 0.46 s | 12.01 s |
| 12 | 292×99 | 91 | 91 | **0** | 0 | WHOLESALE | 71 | 6 | DYNAMIC_ACCESS 3, SEALED_POCKET 2, COMMIT_LINK 1 | 0.48 s | 14.60 s |
| 16 | 304×107 | 91 | 91 | **0** | 0 | WHOLESALE | 74 | 3 | DYNAMIC_ACCESS 2, SEALED_POCKET 1 | 0.53 s | 14.05 s |

Every belt3 rung is a wholesale give-up: 0 of 91 demands assigned, on all six.
Not one unrouted cut on any belt3 rung is a BUDGET refusal — all 56 unrouted
cuts across the six rungs are geometric.

## zurl2 / all-products — 17 blocks, 127 cut nets, 144 demands

| gap | canvas | demands | `missing` | of which sealed | assigned | verdict | routed | unrouted | by kind | reserve wall | route wall |
| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| 2 | 645×68 | 144 | 144 | **0** | 0 | WHOLESALE | 26 | 101 | BUDGET 100, DYNAMIC_ACCESS 1 | 1.66 s | 22.24 s |
| 4 | 676×70 | 144 | 144 | **0** | 0 | WHOLESALE | 25 | 102 | BUDGET 101, DYNAMIC_ACCESS 1 | 1.85 s | 22.32 s |
| 6 | 704×70 | 144 | 144 | **0** | 0 | WHOLESALE | 25 | 102 | BUDGET 101, DYNAMIC_ACCESS 1 | 2.01 s | 22.16 s |
| 8 | 720×72 | 144 | 144 | **0** | 0 | WHOLESALE | 22 | 105 | BUDGET 104, DYNAMIC_ACCESS 1 | 2.18 s | 20.90 s |
| 12 | 606×91 | 144 | 144 | **0** | 0 | WHOLESALE | 22 | 105 | BUDGET 104, DYNAMIC_ACCESS 1 | 2.39 s | 18.72 s |
| 16 | 665×92 | 144 | **0** | 0 | **144** | **COMPLETE** | 19 | 108 | BUDGET 107, DYNAMIC_ACCESS 1 | 4.17 s | 16.60 s |

zurl2's rung 16 is the one rung on either cell where the trunk-goal oracle
returned a USABLE answer: 144 of 144 demands assigned in 4.17 s, `complete`,
`degraded` False. The router then refused 108 of 127 cuts on that same
canvas — but 107 of those are BUDGET, so on zurl2 the router never got far
enough to disagree with the oracle about geometry.

## Finding 1 — does the oracle now reject anything?

**It rejects, and on eleven of the twelve judged rungs the rejection is a
WHOLESALE MATCHER GIVE-UP rather than a sealed-trunk verdict: `assigned` is 0
of 91 on all six belt3 rungs and 0 of 144 on five of six zurl2 rungs, and
`missing_sealed` is 0 on all twelve.** Not one missing demand on either cell
carried a non-empty `PortAccessEvidence.frontier`. The stored `missing_detail`
rows are sorted by descending frontier, so the top row being 0 is a proof for
the whole set, not a sample.

What those rows say instead is the opposite of a pocket. Every one of the 24
recorded missing demands per rung, on both cells, reports `reachable_options`
**2** — the `_PORT_ACCESS_PROBE_KEEP = 2` cap, meaning the A* PROVED two
corridors reachable to a trunk partner's doorstep and stopped only because it
had proved enough — with `local_options` 5 to 9, `held` 0, `wanted` 1,
`exhaustive` False, `kind` `internal-departure`. A demand with two proven
reachable options and zero held corridors is a demand the joint matcher
declined to serve, not a lane head the packing walled in. This is Task 5's
`_match_access_corridors` / `_ACCESS_CUT_ROUNDS = 8` give-up, reproduced at
every rung of the ladder rather than only at rung 0, and it is exactly why
`pack_with_access` discards the answer and re-asks local-only
(`reservation_degraded = 1` in both cells' shipped stats lines).

## Finding 2 — are the upper rungs reachable?

**Yes: all six rungs, up to and including gap 16, were judged AND routed on
both cells, and zurl2's gap-16 reservation was complete at 144/144 in 4.17 s.**
`gate.md` §6 recorded that rungs 6, 8, 12 and 16 "have never been exercised by
any measurement here"; they now have been, twelve times. The cost is modest:
a rung costs 0.3–0.8 s to pack and 0.45–4.17 s to reserve, so the whole ladder's
oracle is ~3 s on belt3 and ~14 s on zurl2 — it is the ROUTING of six rungs,
not the judging of them, that made these runs 140–183 s.

Production, meanwhile, committed **gap 2** on both cells with a degraded
(local-only) reservation — `compose_gap=2`, `reservation_degraded=1`,
`reservation_missing=0` in both shipped stats lines. So the upper rungs are
reachable to a measurement and are still not reachable to the shipped ladder,
because the local-only oracle it falls back to answers `complete` at rung 0
and the ladder returns on the first complete rung.

## Finding 3 — does `missing` track `unrouted`?

**No, on both cells, and on zurl2 it is inverted.**

* belt3: the rung with the fewest `missing` is a **six-way tie at 91** —
  `missing` is CONSTANT across the whole ladder and carries zero rung-ordering
  information. The rung with the fewest `unrouted` is **gap 16, at 3**. The
  router's own ordering is **15, 16, 7, 9, 6, 3** — improving 5× end to end
  but NOT monotone: gap 4 is worse than gap 2, and gap 8 worse than gap 6.
  It is nonetheless a REAL ordering rather than a first-pass artifact, because
  one round is shipped policy at 77 nets and every belt3 rung returned
  STRANDED with all 77 nets decided. They are not the same rung, because one
  of them is not a rung.
* zurl2: the rung with the fewest `missing` is **gap 16, at 0** — the only
  complete reservation in the measurement. The rung with the fewest `unrouted`
  is **gap 2, at 101**. They are not the same rung; they are opposite ends of
  the ladder, and gap 16's 108 unrouted is the WORST of the six.

zurl2's routing column is BUDGET-dominated (100–107 of each rung's unrouted
count), so its ordering is mostly "how much clock did this rung get", not
geometry; its geometric unrouted count is flat at **1 DYNAMIC_ACCESS on every
rung**, which is also no signal. belt3's is entirely geometric (0 BUDGET on
all six rungs) and is therefore the honest half of this finding: there, a real
5× rung ordering exists in the router and the oracle reports the same number
at every rung of it.

## What this measurement is NOT

Two cells, one candidate policy, one round each, at a budget no gate uses.
The routing column is a single `_route_all` per rung on roughly a sixth of one
composition's wall.

**`route_iterations` = 1 on all twelve rungs is SHIPPED POLICY, not this
probe's clock.** `freeform._route_all` sets `round_limit = 1 if len(nets) >=
_SINGLE_ROUND_NETS else RRR_MAX`, with `_SINGLE_ROUND_NETS = 64`; belt3 has 77
cut nets and zurl2 127, so production routes these two canvases in one round
too. Nothing here was starved out of a second rip-up pass. Combined with
belt3's `route_status` being **STRANDED on all six of its rungs** — a status
`_route_all` returns only when neither `budget_exhausted` nor any BUDGET-kind
failure is present — and with `routed + unrouted = 77` exactly on every belt3
rung (no net left undecided), belt3's six routing rows are
**production-equivalent single-round routing on those canvases**, not
first-pass upper bounds.

zurl2's are not: its six rows are BUDGET-bound (100–107 of each rung's
unrouted count) at 16–22 s of routing, and should not be read as geometry at
all. That is a clock limit and it is this probe's — six rungs sharing one
composition's wall — not a policy one. The cells' final CLI verdicts
(both exit 3, refusing with unrouted cuts) are probe artifacts: the six-rung
probe spends 90 % of the composition's own deadline, so the shipped
`pack_with_access` ran afterwards on a nearly spent clock. Nothing in this
file is evidence about the shipped strategy's area, runtime or refusal rate.

The `missing_sealed` = 0 result is a statement about these twelve canvases and
this oracle, not a proof that no composed canvas ever seals a lane head: the
wholesale give-up happens BEFORE a sealed lane head could be reported
separately, so a matcher that did not give up might still find one.
`tests/layout/hierarchy/test_compose.py`'s trunk-probe test (commit
`a2ecd5b2`) shows the mechanism can reject a sealed lane head on a
purpose-built canvas; it did not fire on a real one here.

## LEVER C

Task 7 runs only if BOTH clauses hold.

* **Clause 1 — a rung rejected for a sealed-trunk reason (a `missing` demand
  whose frontier is non-empty): FAILS.** `missing_sealed` is 0 on all twelve
  judged rungs across both cells. Every rejection recorded is a wholesale
  matcher give-up — `assigned` 0 while the same demands report
  `reachable_options` 2 — which says the assignment step gave up, not that the
  geometry is impossible. A `missing` of 91 or 144 is not a sealed-trunk
  rejection however large it is.
* **Clause 2 — the widest rung judged still leaves at least one unrouted cut:
  HOLDS, and holds on geometry rather than on clock.** belt3 gap 16 leaves 3
  unrouted (2 DYNAMIC_ACCESS, 1 SEALED_POCKET, **0 BUDGET**, status STRANDED,
  all 77 nets decided). Because one round is what `_route_all` does on a
  77-net problem by policy, those 3 cuts are the real single-round answer for
  that canvas and not an artifact of the probe's wall. zurl2 gap 16 leaves 108
  (107 BUDGET, 1 DYNAMIC_ACCESS) and satisfies the clause only on its clock,
  so belt3 is what carries it.

**LEVER C: SKIPPED, because the reservation rejected no rung on either cell
for a sealed-trunk reason — `missing_sealed` is 0 on all twelve judged rungs,
and every rejection is a wholesale matcher give-up.**

The oracle is still not the binding constraint, and the next lever is
elsewhere. What this measurement puts on the table for it, in order of the
size of the number behind it:

1. **`_match_access_corridors` gives up wholesale on a composed canvas at
   every rung, not just at rung 0.** 0 of 91 and 0 of 144 assigned, on eleven
   of twelve rungs, on demands with two proven reachable corridors each. Until
   that is fixed the trunk-goal oracle cannot say anything the ladder can act
   on, and Tasks 4 and 5's goals are paid for and thrown away every build.
   zurl2's rung 16 proves the matcher CAN complete on a composed canvas, so
   this is a matcher-scaling problem with a worked counterexample, not a wall.
2. **More ground does route more cuts, and the ladder never asks for it.**
   belt3's router goes 15, 16, 7, 9, 6, 3 unrouted across the ladder — 5×
   better at gap 16 than at gap 2, though not monotone — with no BUDGET
   refusals anywhere and at the round count production itself uses, so this is
   a real ordering. Meanwhile the shipped ladder commits gap 2 because the
   local-only oracle it degrades to answers `complete` there. A ladder that
   could see the router's own number would take rung 16 on this cell.
3. **zurl2 is clock-bound before it is ground-bound.** 107 of 108 refusals at
   its widest rung are BUDGET at ~17 s of routing; nothing about zurl2's
   geometry is measurable until its router gets a wall it can finish on.
