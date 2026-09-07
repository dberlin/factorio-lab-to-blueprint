# titanium-glass / all-products, `--budget 60`, after the composition power pass (Task 5)

`flab2bp.__file__` = `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4/src/flab2bp/__init__.py`
(confirmed inside the worktree before either run.)

HEAD at both runs: `d12694fa9d6f7f93bec47b12907d0614b25cc9f3` (this is also the SHA the
brief calls the diff base against `src`/`tests`).

## Headline: REFUSED, both rounds, bit-identical — and NOT on `power.coverage`

Neither round emitted a blueprint. `titanium-glass-b60.blueprint.txt` (r1) and
`titanium-glass-b60-r2.blueprint.txt` (r2) do not exist (0 bytes / not created).

This is **not** the v3 outcome re-measured. v3 reached `validate.certify` with
`unrouted_cuts=0` and refused there with four `power.coverage` findings — one check,
nothing else wrong. In this v4 measurement the cell refuses **before compose ever reaches
certify**, on `unrouted_cuts=4`. `validate.certify` is never called, so there is no
`errors_by_check` to report and `certify_probe.py` was **not run** — the brief's own
"if it emits" and "if it refuses [via certify]" gate both point to it being pointless
here (nothing to certify: no `Build`, no placement handed to the validator at all).

So none of Step 3's three named shapes fit as written — this is a fourth shape the brief
did not anticipate: **the router itself refuses first**, upstream of the point where the
power infill's own success or failure would even matter. Reported here exactly as it is,
not forced into one of the three boxes.

## The refusal, verbatim (identical in both rounds)

```
flab2bp: no valid layout for all-products after 60s: hierarchical/all-products: unrouted
cut(s): titanium-glass: block 5 lane head 3857: no port access corridor (held=0 wants=1
options=4); titanium-glass: block 5 lane head 3835: no port access corridor (held=0
wants=1 options=4); glass: block 1 lane head 587: no port access corridor (held=0 wants=1
options=9); titanium-glass: block 2 -> block 5: BUDGET. Treat a spec that cannot be laid
out in the requested budget as a layout-model defect until shown otherwise.
```

Four unrouted cuts, matching `unrouted_cuts=4` in the stats line:

1. `titanium-glass: block 5 lane head 3857` — `no port access corridor (held=0 wants=1 options=4)`
2. `titanium-glass: block 5 lane head 3835` — `no port access corridor (held=0 wants=1 options=4)`
3. `glass: block 1 lane head 587` — `no port access corridor (held=0 wants=1 options=9)`
4. `titanium-glass: block 2 -> block 5` — `BUDGET`

## The `no port access corridor (held=0 …)` count — the controller decision point

**Count on titanium-glass, both rounds: 3.** (Task 3's belt3/zurl2 finding — a class with
zero occurrences at the merge base — reproduces here too, and at nonzero count on the
single most consequential gate cell in this plan.) `grep -c` on both `.log` files
independently confirms 3 in each.

## Both rounds, walls and loads

| round | in-process `wall_s` (probe.py) | shell wall (`shellwall.txt`) | `-load.txt` (runnable_5s_mean) | exit | emitted? |
|---|---|---|---|---|---|
| r1 | 42.77 | 44.32 | 18.0 | 3 | REFUSED |
| r2 | 40.81 | 42.13 | 16.2 | 3 | REFUSED |

Both loads are well under the 64 threshold; recorded immediately before each run, never
waited on, per the box-discipline rule.

Budget is 60 s + `RACE_COMPLETION_GRACE_S = 6.0` = 66 s ceiling; both walls are under that.

## Full stats line, both rounds (byte-identical)

```
stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5
arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26
nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=1 power_uncovered_tiles=0
recut_rounds=0 reservation_degraded=5 reservation_missing=3 reservation_partial=5
resplits=0 unrouted_cuts=4
```

Confirmed identical between r1 and r2 by a programmatic diff of the two JSON sidecars
(`exit`, `refusals`, `stats` all `MATCH`; only the `blueprint.path` field differs, because
r1 and r2 write to different filenames by design).

## Reading the new-since-v3 keys

- **`power_infill_towers=1`, `power_uncovered_tiles=0`.** Task 4's composition-power-infill
  step DID run and, on whatever partial canvas `_route_all` produced before the cut-routing
  failure surfaced, it stood 1 tower and found nothing it could not cover. This is
  informative but not dispositive: `unrouted_cuts=4 > 0` means the composition as a whole
  is still invalid regardless of what the infill did, so `compose` raises `NoValidLayout`
  on the unrouted-cut path, not the power-coverage path. **This is not the "wall already
  spent" failure string** (`"composition power infill: did not run, the composition's wall
  was already spent before it could start"`) — that string does not appear in either log —
  and it is not the `_Unpowerable` "site taken between plan and stand" string either. The
  infill ran and reports a clean, if small, result; it just never gets to matter because
  three of the four cuts fail earlier in `_route_all` on port access, and the fourth on
  budget.
- **`reservation_partial=5`, `reservation_degraded=5`, `reservation_missing=3`.** All three
  keys are nonzero. Per the v3/v4 stats-key notes, `reservation_degraded == 0` together with
  `reservation_partial == 0` would be "the matcher converged outright"; that is not the case
  here. `reservation_partial=5 == reservation_degraded=5` here (Task 2's accounting: every
  degraded rung is a partial commit, none is a wholesale give-up) — consistent with the
  matcher committing surveyed partials rather than returning `{}` wholesale, but still
  leaving `reservation_missing=3` demands with no corridor at all, which is exactly what
  surfaces as the three `no port access corridor (held=0 …)` cuts above.

## Explicit comparison to v3

v3 (same cell, same budget, same policy): composed, wired all 26 cut lanes
(`unrouted_cuts=0`), reached `validate.certify`, refused with **exactly four
`power.coverage` findings, one check, nothing else wrong** — 5993 buildings, area 11297
(1.97x of best-known 5727), 80 splitters, 61 Tesla towers, 76/80 splitters covered.

v4 (this measurement, Task 1/2/4 all present): does **not** reach `validate.certify` at
all. `unrouted_cuts=4` (was 0), `cut_lanes=26` still (unchanged spec), and the refusal is
entirely a router-side "unrouted cut(s)" failure — three `no port access corridor
(held=0 …)` plus one `BUDGET`. There is therefore **no `errors_by_check` to compare against
v3's `{power.coverage: 4}`** — the comparison point does not exist in this run because
compose never gets far enough to produce it. Whatever Task 4's infill would or would not
have fixed on the FULL composed canvas is now moot for this cell: something upstream
(consistent with Task 1/2's partial-commit change to `_match_access_corridors`, per the
`reservation_partial`/`reservation_missing` split above and Task 3's prior finding of this
exact new failure class on belt3/zurl2) blocks the composition before power coverage is
even evaluated.

**This is not the first blueprint this project has emitted from `--strategy hierarchical`.**
Lever 2 (the power infill) did not get a fair test on this cell at this budget: it ran, it
covered what it saw, but the composition it belongs to never reaches certification because
of an unrelated, earlier router refusal that did not exist in v3's measurement of this same
cell.

## Certification

Not run. Neither round emitted a blueprint (`-o` target does not exist in either round), so
there is no `Build`/placement to hand to `certify_probe.py`, and running it would either
crash on a missing artifact or silently re-run the whole build for no new information — the
`.log`/`.json` sidecars already contain everything `cli.main` printed. `certify-titanium-
glass.{json,log}` were therefore not created; their absence here is the record of that
decision, per the brief's "report a null result as exactly that."
