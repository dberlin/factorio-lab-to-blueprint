# Task 3: does the corridor oracle now predict the router?

Controlled before/after measurement of two large gate cells --
`belt3` and `zurl2`, both `--strategy hierarchical --budget 60 --band portable
--candidate-policy all-products` -- taken once at the hierarchical-v4 merge
base (`1d2a790cd8c184480a6eb63e72cdfb3bb1d69226`, Tasks 1/2 absent, "before")
and once at this branch's HEAD at measurement time
(`ca72fc6de5d3681f6ef121233960e06cf023982f`, Tasks 1/2 present, "after").
**No production code was changed to produce this document.**

v3 gate §5 lever 1 named the failure as a prediction failure: belt3's
`missing` sat constant at 91 while the router's own unrouted count moved
5, 16, 7, 9, 6, 3 across a multi-point budget ladder -- the oracle's number
tracked nothing. This document is the single before/after data point (one
budget, one candidate policy, per cell) that lets Task 9's gate say whether
Task 1 ("commit the surveyed partial instead of returning `{}` wholesale")
and Task 2 (count that partial as both `reservation_partial` and
`reservation_degraded`) changed that.

## Method note: two absent keys, not one

`reservation_partial` does not exist in the stats line at the merge base --
Task 2 is what adds it. The BEFORE column for it is **`n/a (key absent)`**,
not `0`; the two are not the same claim and this table does not conflate
them. `reservation_missing` and `reservation_degraded`, by contrast, already
existed in v3 and are reported as measured (including `0`) at the merge base.

## The table

| cell | when | cut_lanes | port_demands | reservation_degraded | reservation_partial | reservation_missing | unrouted_cuts | compose_gap | in-process wall (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| belt3 | before | 89 | 102 | 1 | n/a (key absent) | 0 | 18 | 2 | 53.30 |
| belt3 | after  | 89 | 102 | 5 | 5 | 16 | 32 | 4 | 60.44 |
| zurl2 | before | 127 | 144 | 1 | n/a (key absent) | 0 | 71 | 2 | 63.07 |
| zurl2 | after  | 127 | 144 | 4 | 3 | 11 | 100 | 2 | 60.84 |

`cut_lanes` and `port_demands` are identical before/after on both cells, as
expected -- they are properties of the input spec and the cut plan, not of
the corridor matcher.

Both cells refused (`exit=3`) in all four runs; there is no successful build
to report area/buildings/validator numbers for.

### CPU load at each run (rules out load as a confound for the regression)

| cell | when | `-load.txt` file | runnable_5s_mean |
|---|---|---|---:|
| belt3 | before | `probe-belt3-all-products-before-load.txt` | 57.2 |
| belt3 | after  | `probe-belt3-all-products-after-load.txt`  | 50.0 |
| zurl2 | before | `probe-zurl2-all-products-before-load.txt` | 23.6 |
| zurl2 | after  | `probe-zurl2-all-products-after-load.txt`  | 12.8 |

**Both AFTER runs ran at lower CPU pressure than their BEFORE runs (belt3
57.2 -> 50.0, zurl2 23.6 -> 12.8) and still produced worse routing outcomes
(`unrouted_cuts` 18 -> 32 and 71 -> 100 respectively).** Load therefore does
not explain the regression reported above -- if anything, the AFTER runs had
more headroom, not less. This rules load out as the explanation; it does not
by itself prove what the mechanism is.

### zurl2's unrouted-cuts breakdown by failure class

The brief's caveat: zurl2's refusals were 69/70 and 71/73 `BUDGET` at 60s in
v3 -- the router ran out of clock, not ground -- so a zurl2 `unrouted_cuts`
change is not geometry unless the non-`BUDGET` count changed.

| when | BUDGET | DYNAMIC_ACCESS | `no port access corridor (held=…, wants=…, options=…)` | non-BUDGET total | unrouted_cuts |
|---|---:|---:|---:|---:|---:|
| before | 69 | 2 | 0 | 2 | 71 |
| after  | 89 | 0 | 11 (options=5: 2, options=6: 2, options=9: 6, options=7: 1) | 11 | 100 |

The non-`BUDGET` count moved from 2 to 11 -- it did change, so per the
brief's own caveat the zurl2 `unrouted_cuts` change is not purely a clock
artifact this time. But the dominant component is still `BUDGET`, which
also grew (69 -> 89); that growth is not distinguishable from clock exhaustion
by this measurement, since both runs hit the same 60s wall and the AFTER run
does strictly more corridor-matching work (survey-and-commit vs.
give-up-and-return-`{}`) before it starts routing cuts, which itself could
eat into the router's clock. This document reports the split; it does not
adjudicate how much of the BUDGET growth is "more geometry to route" versus
"less clock left to route it in."

### belt3's unrouted-cuts breakdown by failure class

Not requested by the brief's caveat (belt3 wasn't reported as BUDGET-heavy
in v3), included for completeness:

| when | DYNAMIC_ACCESS | SEALED_POCKET | COMMIT_LINK | `no port access corridor (...)` | unrouted_cuts |
|---|---:|---:|---:|---:|---:|
| before | 8 | 5 | 5 | 0 | 18 |
| after  | 6 | 7 | 3 | 16 (options=5: 3, options=3: 5, options=6: 2, options=9: 6) | 32 |

**A failure class that did not exist at the merge base appears on both cells
after Task 1/2**: `no port access corridor (held=0 wants=1 options=N)`. It
is 0 occurrences at the merge base on both cells and 16 (belt3) / 11 (zurl2)
occurrences after. This document does not diagnose why -- that would mean
reading `freeform.py` / `compose.py` internals, which is out of scope for a
measurement-only task -- but it is the single largest source of the
`unrouted_cuts` increase on belt3 and the whole of the non-BUDGET increase
on zurl2, and Task 9's gate should treat it as a named, distinct failure
mode rather than folding it into the pre-existing `DYNAMIC_ACCESS` /
`SEALED_POCKET` / `COMMIT_LINK` buckets.

## Question 1: does the matcher still give up wholesale?

The brief names two outcomes and this measurement adds a third, per the
dispatch:

- `reservation_partial > 0` on a cell is proof the matcher does not give up
  wholesale.
- `reservation_degraded > 0` with `reservation_partial == 0` is proof it
  still does -- a FAILED Lever 1.
- `reservation_degraded == 0` with `reservation_partial == 0` on a composing
  cell would mean the matcher converged outright -- a clean win, distinct
  from failure.

**Neither cell hits the failed-Lever-1 state.** Both AFTER cells have
`reservation_partial > 0`. Neither cell hits the converged state either --
both AFTER cells have `reservation_degraded > 0`.

What the numbers actually show, cell by cell:

- **belt3**: `reservation_degraded=5`, `reservation_partial=5`. Every
  degraded match on this cell resulted in a committed partial -- full
  coverage, 5/5.
- **zurl2**: `reservation_degraded=4`, `reservation_partial=3`. Three of
  four degraded matches resulted in a committed partial; **one degraded
  match did not** (`degraded - partial = 1`). Since Task 2 counts every
  partial as also degraded, this residual gap is a degraded match that
  still produced nothing -- the old wholesale-give-up behavior, surviving
  on one event out of four on this cell.

**Verdict: Lever 1 is delivered, but not uniformly.** The matcher commits a
partial in the large majority of degrade events observed (5/5 on belt3,
3/4 on zurl2) rather than discarding them; it is not the failed state the
brief defines. It is also not a clean convergence -- degradation still
happens on both cells, and on zurl2 one instance of it still yields nothing.
Report this as a partial, not total, fix, plainly: on this evidence, zurl2
still exhibits a residual wholesale-give-up case.

## Question 2: does `missing` now predict `unrouted`?

| cell | reservation_missing before | reservation_missing after | unrouted_cuts before | unrouted_cuts after | same direction? |
|---|---:|---:|---:|---:|---|
| belt3 | 0 | 16 | 18 | 32 | yes (both up) |
| zurl2 | 0 | 11 | 71 | 100 | yes (both up) |

By the brief's literal directional test -- "the oracle predicts the router
if `missing` moved in the same direction as `unrouted` on both cells" --
**yes**: `missing` went from 0 to a positive nonzero value on both cells,
in the same direction as `unrouted`, which itself increased on both cells.
This is unlike v3's complaint, where `missing` sat constant (91) while the
router's number moved across a multi-point ladder.

Two things this measurement does NOT establish, stated plainly rather than
implied:

1. **This is a two-point comparison per cell** (one budget, one candidate
   policy), not the multi-rung ladder v3's original complaint was built on.
   `missing` moving from a floor of 0 to a positive number when a
   wholesale-give-up path is replaced by a partial-commit path is a much
   weaker claim than tracking the router's number across several budgets.
   Task 9's gate, which does run the ladder, is where the stronger version
   of this claim gets tested.
2. **What `missing` is predicting here is a regression, not an
   improvement.** Both `unrouted_cuts` and `reservation_missing` got worse
   (larger) after Task 1/2 on both cells, at this budget. The oracle number
   moving together with the router number is the literal claim under test
   and it holds -- but "moves together" here means "both cells route worse
   than before," not "the oracle now helps the router route more." That
   distinction matters for how Task 9 should read this result and is
   carried forward plainly rather than left implicit in the direction test.

**The belt3 `missing=91` discrepancy, reconciled**: v3 gate §5 describes
belt3's `missing` as constant at 91, while this measurement's belt3 BEFORE
`reservation_missing` is 0. The two figures come from different instruments
at different budgets, not from a contradiction. v3's own `gate.md` (the
Task 5 discussion) records the production 60s-budget belt3 cell as
`reservation_missing=0 reservation_degraded=1 unrouted_cuts=18` -- which
matches this document's belt3 BEFORE row exactly (see the table above). The
`91` comes from a different instrument entirely: Task 6's `oracle.md`, a
bespoke 180s rung-walking probe that wraps `pack_with_access` directly and
walks every rung of `compose.GAP_LADDER` itself ("Every belt3 rung is a
wholesale give-up: 0 of 91 demands assigned, on all six"). `oracle.md`
itself states "180 s is a MEASUREMENT budget and not a gate budget; no gate
clause may be read from these two runs," and v3's `gate.md` explicitly
disclaims it as non-gating: "`oracle.md` is explicit that its cells' final
CLI verdicts are probe artifacts, and no gate clause is read from it -- it
is cited for the rung-level mechanism only." So the 91 is real, but it is
Task 6's 180s rung-mechanism probe, not the gate's own 60s production
measurement -- which is the same instrument and the same budget this
document uses, and which already agreed with 0 before Task 1/2 landed.

**Verdict**: `missing` and `unrouted` moved in the same direction on both
cells, satisfying the brief's directional test as literally stated. Lever 1
is not a null result on this question. It is also not an unambiguous win:
the direction both numbers moved in is worse, and the test is a two-point
comparison rather than the ladder that motivated it. Report both facts.

## Question 3: did `compose_gap` move off 2?

- **belt3**: 2 -> 4. Moved off 2.
- **zurl2**: 2 -> 2. Did not move.

v3 pinned `compose_gap` at 2 on every cell in four gates because no rung
could ever be ranked. belt3's AFTER run is the first evidence across those
four gates that a rung above 2 gets committed at all. zurl2 shows no such
movement in this measurement -- it is still pinned at 2.

**Verdict: partial, one cell out of two.** Report it as exactly that: one
cell shows the first sign the ladder can rank past floor, the other cell
shows none.

## Summary verdict for Task 9

- **Q1 (wholesale give-up)**: not the failed state on either cell; not a
  clean convergence on either cell either. belt3 is full coverage (5/5
  degraded events committed a partial); zurl2 is partial coverage (3/4),
  with one residual wholesale-give-up instance. **Lever 1 works, but is
  incomplete on zurl2.**
- **Q2 (missing predicts unrouted)**: yes, by the literal directional test,
  on both cells, at this one budget point. Not tested here: whether that
  holds across a ladder, and the direction both numbers moved was worse,
  not better.
- **Q3 (compose_gap off 2)**: yes on belt3, no on zurl2. First evidence of
  ladder movement in four gates, but only on one of two cells measured.
- **Cost of the change, stated plainly, not softened**: `unrouted_cuts`
  roughly doubled on belt3 (18 -> 32) and increased by ~41% on zurl2
  (71 -> 100) at this budget, and a brand-new failure class (`no port
  access corridor (held=0 wants=1 options=N)`) appeared on both cells that
  did not exist at the merge base at all. Lever 1 changes what the oracle
  reports and, on this evidence, the router's outcome at a fixed 60s budget
  got worse, not better, on both cells measured. This is not read here as
  a refutation of Lever 1's narrow claim (does the matcher stop giving up
  wholesale, does `missing` move with `unrouted`) -- both hold, per Q1/Q2
  above -- but Task 9 should not read "Lever 1 delivered" as "the router
  is in better shape now." On this evidence it plainly is not, at this
  budget, on these two cells.

## Reproduction

`run_probe.sh` beside this document is the exact procedure used, staged so
each dangerous step (the merge-base detach) is a separate, hand-invoked
function with its own verification lines rather than a single unattended
script. `probe.py` is the harness itself, copied byte-for-byte from
`docs/superpowers/evidence/2026-09-07-hierarchical-v3/run_cell.py` except
for its module docstring, which now documents `reservation_partial`.
