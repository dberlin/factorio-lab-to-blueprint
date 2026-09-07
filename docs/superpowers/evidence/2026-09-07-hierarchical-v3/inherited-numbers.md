# Inherited numbers: measurements `gate.md` cites that were taken on trees that no longer exist

`gate.md` §5's provenance note names the figures in this gate that trace to no
committed evidence file. This file is where they now live, because the workspace
they came from — `.superpowers/sdd/2026-09-07-hierarchical-v3/`, which is
gitignored and is deleted when the plan finishes — is not part of the record.

**What every entry below is, and is not.** Each is quoted VERBATIM from an
implementer's own task report, with the commit its tree sat at. **None of them
was re-measured at HEAD (`bf081859`)**, and none of them can be: each was taken
on an intermediate tree that was subsequently changed or reverted, and the
builds wrote to `/tmp` logs that no longer exist. They are inherited testimony,
not this gate's measurements. Where the gate could re-measure the same quantity
at HEAD it did, twice, and those numbers are in `gate.md` §2.1 and in the
`large-*-r{1,2}.json` sidecars beside this file.

They are carried because each is load-bearing for a RANKING rather than for a
clause. **No gate clause is decided by anything on this page.**

---

## 1. Task 5, pre-Ruling-R7: `reservation_missing = 102` and `unrouted_cuts = 126`

**Source:** `task-5-report.md` §5.2-§5.3, tree at commit `e91886fb`
(`feat(hierarchy): probe each cut lane's trunk, not just its doorstep`), before
Ruling R7's empty-assignment discard landed at `b9473715`.
**Cell:** belt3 / all-products, `--budget 60 --band portable`, one build, exit 3,
shell wall 62.20 s. Log was `/tmp/v3-t5-belt3.log`.

> ```
> uv run flab2bp '<belt3 url>' --strategy hierarchical --budget 60 \
>     --candidate-policy all-products --band portable > /dev/null 2> /tmp/v3-t5-belt3.log
> ```
>
> Exit code **3** (refusal, as v2). Shell wall **62.20 s** (budget 60 s plus the
> 6 s `RACE_COMPLETION_GRACE_S` ceiling — inside contract).
>
> Verbatim `stats` line from `/tmp/v3-t5-belt3.log`:
>
> ```
>   stats hierarchical/all-products: arm_dispatch_both=2 arm_dispatch_freeform=7 arm_dispatch_sequence_pair=5 blocks=11 blocks_unattempted=0 compose_gap=2 cut_lanes=89 nogood_skips=2 player_fed=0 port_demands=102 recut_rounds=2 reservation_missing=102 resplits=2 unrouted_cuts=126
> ```
>
> ### 5.3 Beside v2
>
> | number | v2 | v3 Task 5 | moved? |
> |---|---|---|---|
> | `compose_gap` | 2 | **2** | no |
> | `port_demands` | 102 | **102** | no |
> | `reservation_missing` | 0 | **102** | **YES — 0 → all of them** |
> | `unrouted_cuts` | 28 | **126** | yes (102 corridor refusals + 24 router refusals) |

**This is the whole intermediate measurement, not just the `126`.** Both
`reservation_missing = 102` and `unrouted_cuts = 126` are from this run, and
`gate.md` §3's Task 5 bullet cites the `0 -> 102` move from here too.

## 2. Task 5, post-Ruling-R7: `unrouted_cuts = 18`

**Source:** `task-5-report.md` §5.9, tree at commit `b9473715`
(`fix(hierarchy): treat an empty access assignment as an unusable answer`).
Same cell and argv, one build, exit 3, shell wall 54.24 s. Log was
`/tmp/v3-t5-r7-belt3.log`.

> ```
>   stats hierarchical/all-products: arm_dispatch_both=2 arm_dispatch_freeform=7 arm_dispatch_sequence_pair=5 blocks=11 blocks_unattempted=0 compose_gap=2 cut_lanes=89 nogood_skips=2 player_fed=0 port_demands=102 recut_rounds=2 reservation_degraded=1 reservation_missing=0 resplits=2 unrouted_cuts=18
> ```
>
> | number | v2 | Task 5 pre-ruling | Task 5 + R7 |
> |---|---|---|---|
> | `compose_gap` | 2 | 2 | **2** |
> | `port_demands` | 102 | 102 | **102** |
> | `reservation_missing` | 0 | 102 | **0** |
> | `reservation_degraded` | — | — | **1** |
> | `unrouted_cuts` | 28 | 126 | **18** |
> | shell wall | — | 62.2 s | 54.2 s |

**This one the gate DID re-measure at HEAD**, twice: `large-belt3-all-products-b60-r{1,2}.json`
both carry `unrouted_cuts=18 reservation_missing=0 reservation_degraded=1
port_demands=102 cut_lanes=89 compose_gap=2 blocks=11`, identical to the row
above on every field. It is reproduced here only so the three-column comparison
is readable in one place. The implementer explicitly declined to claim 28 → 18
as an improvement, because the two runs are not a controlled pair, and
`gate.md` §3 keeps that refusal.

## 3. Task 2, both arms funded: `mall/no-proliferator` leaves **6** blocks never placed

**Source:** `task-2-report.md` Step 5, tree at commit `0bf58d3d`
(`fix(hierarchy): bound re-cut rounds and fund the blocks that exist at dispatch`),
BEFORE Task 3's one-arm dispatch (`94c4edaf`). Log was
`/tmp/v3-t2-mall-no-proliferator-60.log`.

> Exit: 3. Shell wall: 23s.
>
> Verbatim stats line:
> ```
>   stats hierarchical/no-proliferator: arm_dispatch_both=0 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=87 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=150 player_fed=0 port_demands=0 recut_rounds=2 reservation_missing=0 resplits=2 unrouted_cuts=0
> ```
> Refusal names 6 blocks never placed (`magnetic-coil` x4, `electromagnetic-turbine` x2), all via
> "out of re-cut round(s) after 2 of 2 the 36.0s round wall allows", with per-block verdicts
> `REFUSED: expansion budget exhausted...` / `REFUSED: deadline exhausted...` -- i.e. the real
> placers, not the funding rule, are what refuses each block.

This is the number that makes `gate.md` §5 lever 3 a REGRESSION rather than a
standalone figure: **6 blocks never placed under both arms against 31 under
one.** The 31 is committed and re-measured — `t3-r5-mall-no-proliferator.log`
and this gate's own `large-mall-no-proliferator-b60-r{1,2}.json`, three
measurements agreeing — and the `6` rests on the paragraph above alone.

Note the arm counters read `0 / 0 / 0` on this line: at `0bf58d3d` Task 3 had
not yet landed, so nothing wrote them. That is what "both arms funded" means
here, and it is why the comparison with Task 3's `sequence_pair=71` is a
comparison of two dispatch REGIMES rather than of two runs of one.

## 4. Task 1, the CLI surface proving itself: `nogood_skips = 36`

**Source:** `task-1-report.md` Step 8, tree at commit `d89b78e3`
(`feat(hierarchy): carry the strategy's stats into every refusal and print them`),
BEFORE Task 2's funding fix. Cell: mall / all-products, `--budget 60 --band
portable`, exit 3.

> Command (the mall URL from `constraints.md`, quoted):
> ```
> uv run flab2bp '<mall url>' --strategy hierarchical --budget 60 \
>     --candidate-policy all-products --band portable
> ```
> Exit code: 3.
>
> The `stats` line, verbatim:
> ```
>   stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=52 blocks_unattempted=22 compose_gap=0 cut_lanes=0 nogood_skips=36 player_fed=0 port_demands=0 recut_rounds=0 reservation_missing=0 resplits=2 unrouted_cuts=0
> ```

**Do not confuse this with `t3-fix1-mall-all-products.log`.** That committed log
is a DIFFERENT tree (Task 3 fix round 1, `69031212`, under Ruling R4's round
accounting, which Ruling R5 then reverted) and a different line:
`blocks=52 blocks_unattempted=22 nogood_skips=40 recut_rounds=2 resplits=2`.
The two agree on `blocks` and `blocks_unattempted` and disagree on
`nogood_skips` and `recut_rounds`; they are not the same measurement and
neither is a re-run of the other. There are **no `t1-*` evidence files** — Task
1 committed no build artifacts.

What the gate uses this for is narrow and does not depend on the exact
`nogood_skips`: it is the demonstration that the CLI surface reproduces a
number v2 could only get from a harness spy (v2's own `run_cell.py` read 22
unattempted for this same cell, `../2026-09-07-hierarchical-v2/gate.md` §2.1).

---

## What a reader should take from this page

Four measurements, on four different intermediate trees, none of them HEAD.
Two of the four quantities were re-measured at HEAD by this gate and agree
(`unrouted_cuts = 18` and its whole stats line; `blocks_unattempted = 22` as a
v2 cross-check). Two were not and cannot be: the pre-R7 `102 / 126` pair, and
Task 2's `6`. Both of those sit in `gate.md` §5's ranking, and §5 says so.
