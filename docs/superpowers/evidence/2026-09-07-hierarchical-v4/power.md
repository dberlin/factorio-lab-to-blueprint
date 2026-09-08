# titanium-glass / all-products, `--budget 60` — before and after the partial top-up

`flab2bp.__file__` = `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4/src/flab2bp/__init__.py`
(confirmed inside the worktree before every run below.)

This document now carries two measurements of the same cell:

- **BEFORE** (Task 5, HEAD `d12694fa9d6f7f93bec47b12907d0614b25cc9f3`): the branch had
  **REGRESSED** this cell relative to v3 — it refused at the router, never reaching
  `validate.certify`, where v3 had reached certify and refused only on `power.coverage`.
  This is the measured regression that justifies Task 4b existing.
- **AFTER** (Task 5b, this document's own measurement, HEAD `e02bd31ac08ff4015f161ef19ff0f04e2277fb9e`,
  i.e. after Task 4b's partial top-up): re-measured below. **No production code was changed
  to produce this document.**

## Headline: the top-up changes the verdict, but not deterministically

Two rounds at the required protocol (`--budget 60 --band portable --candidate-policy
all-products`, `probe.py`, no monkeypatching) **both EMITTED**, bit-identical to each other:
116 machines, 11297 tiles, 5994 buildings, exit 0, no `VALIDATION ERRORS` line. Neither round
prints a `stats` line — `probe.py` only ever captures that line on the refusal path (see its
own docstring), so `reservation_degraded`/`reservation_partial`/`reservation_missing`/
`power_infill_towers`/`power_uncovered_tiles`/`unrouted_cuts` are **absent, not zero**, for
these two rounds specifically.

To confirm the certify report the brief asks for ("`-o` writing a file is NOT the claim"),
`certify_probe.py` was run on the identical argv **twice**, because the first attempt did not
corroborate the two rounds:

- **certify attempt 1: REFUSED** (exit 3), `certifications: []` — `validate.certify` was
  **never called**. The refusal happened at a later, different stage than Task 5's: DSP
  latitude band/orientation finalization, not the router's cut-routing pass, and not
  `power.coverage`. Verbatim: `composed placement refused finalization: no legal DSP latitude
  band/orientation accepts the final placement: band 200 game.addon_splitter_clearance
  (3418, 6049): Splitter connection body enters the Spray Coater projected lateral keepout.`
  Its stats line (present, because this run refused) reads `compose_gap=2 cut_lanes=26
  port_demands=31 power_infill_towers=2 power_uncovered_tiles=0 reservation_degraded=1
  reservation_missing=0 reservation_partial=1 unrouted_cuts=0` — full line below.
- **certify attempt 2: EMITTED** (exit 0), matching r1/r2 exactly (area 11297, buildings
  5994), and this time `validate.certify` **was** called and returned `ok: true, errors_total:
  0, errors_by_check: {}`.

So across four runs of the identical argv: three emitted (r1, r2, certify-attempt-2) with
bit-identical output, and one (certify-attempt-1) refused at a stage neither r1/r2 nor Task
5's measurement exercised. **This is reported as a genuine finding, not smoothed over**: this
cell's outcome is not perfectly deterministic run-to-run at this budget. The compose-stage
numbers visible in certify-attempt-1's refusal (`unrouted_cuts=0`, `reservation_missing=0`)
are consistent with — not proven identical to — whatever compose stage produced r1/r2/attempt-2's
identical final output, because the divergence point (band/orientation finalization) is
strictly *after* compose in the pipeline. No load spike explains the one refusal: its
`-load.txt` (`runnable_5s_mean=35.2`) is not the highest of the four (`45`, `37`, `35.2`,
`42.8`), so this is not attributed to CPU pressure.

**On the strength of the certify report that did fire (certify-attempt-2): this is the first
blueprint this project has ever emitted from `--strategy hierarchical` with a clean certify
report** (`errors_total: 0`). It is not claimed on the strength of the CLI's own truncated
output alone, per the brief's warning that `-o` writing a file is not the claim.

## Both rounds, walls and loads (the required two-round protocol)

| round | in-process `wall_s` | shell wall | `-load.txt` (runnable_5s_mean) | exit | emitted? |
|---|---|---|---|---|---|
| r1 (after-topup) | 28.68 | 30.03 | 45 | 0 | **EMITTED** |
| r2 (after-topup) | 27.29 | 28.92 | 37 | 0 | **EMITTED** |

Both loads well under the 64 threshold; recorded immediately before each run, never waited
on. Neither round's `.json` sidecar carries a `stats` object (`{}`), by `probe.py`'s
documented success-path behavior.

Extra certify-confirmation runs (not part of the two-round protocol, run to obtain the
`errors_by_check` the brief requires):

| run | in-process `wall_s` | shell wall | `-load.txt` | exit | emitted? | reached `certify`? |
|---|---|---|---|---|---|---|
| certify attempt 1 | n/a (crash path, no `wall_s` field written — see log) | 36.88 | 35.2 | 3 | REFUSED | **no** — `certifications: []` |
| certify attempt 2 | n/a | 29.79 | 42.8 | 0 | EMITTED | **yes** — `ok: true` |

## Full stats line — BEFORE (Task 5, both rounds, byte-identical)

```
stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5
arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26
nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=1 power_uncovered_tiles=0
recut_rounds=0 reservation_degraded=5 reservation_missing=3 reservation_partial=5
resplits=0 unrouted_cuts=4
```

Refusal (both rounds, byte-identical):

```
flab2bp: no valid layout for all-products after 60s: hierarchical/all-products: unrouted
cut(s): titanium-glass: block 5 lane head 3857: no port access corridor (held=0 wants=1
options=4); titanium-glass: block 5 lane head 3835: no port access corridor (held=0
wants=1 options=4); glass: block 1 lane head 587: no port access corridor (held=0 wants=1
options=9); titanium-glass: block 2 -> block 5: BUDGET.
```

**The `no port access corridor (held=0 …)` count, BEFORE: 3.**

## Full stats line — AFTER, certify attempt 1 (the only after-topup run with a stats line)

```
stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5
arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26
nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=2 power_uncovered_tiles=0
recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=1
resplits=0 unrouted_cuts=0
```

Refusal text (this run only, band/orientation finalization, not the router):

```
flab2bp: no valid layout for all-products after 60s: hierarchical/all-products: composed
placement refused finalization: no legal DSP latitude band/orientation accepts the final
placement: band 200 game.addon_splitter_clearance (3418, 6049): Splitter connection body
enters the Spray Coater projected lateral keepout.
```

**The `no port access corridor (held=0 …)` count, AFTER (this run): 0.** No occurrence of
that string anywhere in this refusal — the refusal is not a corridor/port-access failure at
all. `unrouted_cuts=0` confirms every one of the 26 cut lanes routed.

## Before / after table

| key | BEFORE (Task 5) | AFTER (certify attempt 1, only after-topup run with a stats line) | reading |
|---|---:|---:|---|
| `unrouted_cuts` | 4 | **0** | all 26 cut lanes now route, in the one run this is observable |
| `no port access corridor (held=0…)` count | 3 | **0** | the number Task 4b exists to move — moved to 0 |
| `reservation_missing` | 3 | **0** | driven to 0, per Task 4b's target — see caveat below |
| `reservation_degraded` | 5 | **1** | ladder total fell — **see Ruling L1-C**, next |
| `reservation_partial` | 5 | **1** | ladder total fell — **see Ruling L1-C**, next |
| `power_infill_towers` | 1 | **2** | one more infill tower stood; area unchanged (11297 both) |
| `power_uncovered_tiles` | 0 | 0 | unchanged |
| `compose_gap` | 2 | 2 | unchanged |
| reached `validate.certify`? | **no** | no (this run), **yes** (r1, r2, certify attempt 2) | see headline |
| `errors_by_check` | n/a (never reached certify) | `{}` (certify attempt 2, `errors_total: 0`) | first clean hierarchical certify this project has produced |
| area | n/a (refused, no `Build`) | **11297** (r1, r2, certify attempt 2) | same as v3's area |
| buildings | n/a | **5994** | +1 vs v3's 5993 (one more Tesla tower) |
| splitters (item 2020) | n/a | **80** | matches v3 exactly |
| Tesla towers (item 2201) | n/a | **62** | v3 had 61; +1, consistent with the extra infill tower |

**Caveat on `reservation_missing`, per the brief's required correction:** the numeric
equality between `reservation_missing` (BEFORE: 3) and the `held=0` corridor-refusal count
(BEFORE: 3) is supported only as a **numeric equality** by this evidence — the two counters
are computed in different places and this document does not assert they are the same demands
by construction, only that the two counts are **consistent with** that reading, both before
and after.

## Ruling L1-C — read this before concluding anything from `reservation_degraded`/`reservation_partial` falling

A topped-up rung has an empty `missing`, so it is `complete`, so `compose.py`'s `if
reservation.complete: return candidate` **ends the gap ladder at that rung**.
`reservation_degraded` and `reservation_partial` are ladder **totals** across however many
rungs the ladder walks before stopping, so a fall from `5/5` (BEFORE) to `1/1` (AFTER, the one
run that shows it) is **the ladder stopping sooner, not the matcher converging more often**.
This was ruled correct: property 2 cannot be satisfied without it, and it restores the
pre-Task-1 shape under which v3's titanium-glass committed at `compose_gap = 2` and reached
`certify`. A reader who sees 5 → 1 and concludes the oracle got better at matching has
misread this document. It also means the composer now commits rung 0's narrower packing
where before it could walk to a wider one — **area and `compose_gap` may move for that
reason alone**. Here, `compose_gap` did not move (2 → 2), and area is unchanged from v3's
figure (11297), but that is a fact about this cell, not a rule that generalizes.

## Comparison to v3 (carried forward, unchanged from the original)

v3 (same cell, same budget, same policy): composed, wired all 26 cut lanes (`unrouted_cuts=0`),
reached `validate.certify`, refused with exactly four `power.coverage` findings, one check,
nothing else wrong — 5993 buildings, area 11297 (1.97x of best-known 5727), 80 splitters, 61
Tesla towers, 76 of 80 splitters covered, `{power.coverage: 4}`.

AFTER (this measurement, when it emits — r1, r2, certify attempt 2, all bit-identical): 5994
buildings, area 11297 (**1.9725859961585472**, i.e. still ≈1.97x of best-known 5727), 80
splitters, 62 Tesla towers, `errors_by_check: {}` — **zero findings**, an improvement over
v3's four `power.coverage` findings. This is the "power.coverage findings are now what
convicts it" shape from the brief's Step 3 list only in the sense that power.coverage is now
**fully resolved** rather than "finally getting a fair test and still convicting" — Lever 2
(the composition power infill) got its fair test here and the extra tower it stands closes
every gap v3 left open, on the runs where the build reaches that point at all.

## Regression, named explicitly

Task 5's BEFORE measurement is a **regression**: the hierarchical-v4 branch, at that
commit, made `titanium-glass/all-products @ budget 60` **worse than the v3 tree** — v3
reached `certify` and refused only on four `power.coverage` findings; the branch instead
refused upstream at the router with `unrouted_cuts=4`, never reaching `certify` at all. Task
4b's partial top-up is the repair for that regression, and this AFTER measurement shows the
repair restores router convergence (`unrouted_cuts: 4 → 0`) and, in three of four runs,
restores emission with a clean certify report — but the fourth run shows the restoration is
not yet fully reliable at this budget: one run of four still refuses, at a different stage
(band/orientation finalization) that Task 5's BEFORE measurement never reached either.

## Neither of the two required rounds (r1, r2) directly show reservation/unrouted-cut counts

Both required rounds emitted, and `probe.py` only ever captures the `stats` line on the
refusal path — so `reservation_degraded`, `reservation_partial`, `reservation_missing`,
`power_infill_towers`, `power_uncovered_tiles` and `unrouted_cuts` are simply **absent** from
r1 and r2's own sidecars, not zero. The AFTER-column values in the table above for those keys
come from certify attempt 1, the one after-topup run that refused and therefore printed a
stats line. Its `area`/`buildings` figures were not directly observable (it refused before
producing a `Build`); its `unrouted_cuts=0` and `reservation_missing=0` are consistent with,
but not proof of, what compose produced in r1/r2/certify-attempt-2's identical successful
output, since the divergence between the two outcomes happens strictly after compose, in
band/orientation finalization.

## Files

- `titanium-glass-b60-after-topup-r{1,2}.{json,log,shellwall.txt}`, `-load.txt` — the two
  required rounds, both EMITTED.
- `titanium-glass-b60-after-topup.blueprint.txt` — the emitted blueprint (81256 bytes; both
  rounds wrote the same file, matching each other byte-for-byte per the CLI's own report).
- `titanium-glass-b60-after-topup-certify{,2}.{json,log,shellwall.txt}`, `-load.txt` — the
  two certify-confirmation attempts (1: refused before certify; 2: emitted, certify clean).
- `titanium-glass-b60-{r1,r2}.*` — **Task 5's original files, untouched**, the committed
  record of the regression.
