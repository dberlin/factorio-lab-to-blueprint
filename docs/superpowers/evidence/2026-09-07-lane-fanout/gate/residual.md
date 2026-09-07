# Task 4: what is left after the guard (Task 1) and the pack bound (Task 3)

Worktree HEAD at measurement time: `00ab70433db18c30fe947185bd9c0b57ad9ad48d`. No source file was
changed to produce this evidence. Venv check:

```
$ uv run python -c "import flab2bp; print(flab2bp.__file__)"
/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/lane-fanout/src/flab2bp/__init__.py
```
inside the worktree, as required.

URL under test (all four builds, identical):

```
https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11
```

Per Ruling T4-A, step 1 of the brief was run TWICE with an explicit `--strategy`, for four builds total,
one at a time. All four ran to completion (no wall-clock kill), all four refused (`NoValidLayout`), and no
build produced a blueprint file.

## Build 1: freeform, `--budget 30`

```
cpu_pressure before: 9.2
/usr/bin/time -v uv run flab2bp "$UM" --budget 30 --strategy freeform -v \
  -o gate/bp-um-b30-freeform.txt > gate/build-um-b30-freeform.log 2> gate/build-um-b30-freeform.err
cpu_pressure after: 19.6
```

- Exit status: **3**
- Wall clock: **1:33.34**
- CPU percent: **108%**
- User time: 100.68 s, System time: 1.04 s
- Output file `gate/bp-um-b30-freeform.txt`: not produced

Refusal text, verbatim (from `gate/build-um-b30-freeform.err`):

> flab2bp: no valid layout for no-proliferator, all-products, output-products after 30s: freeform/no-proliferator: the 30s deadline passed with no completed packing of 57 strips; 2 packs were routed in that time and the best of them still left 3 nets unrouted (worst 49), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec; freeform/all-products: the 30s deadline passed with no completed packing of 53 strips; 2 packs were routed in that time and the best of them still left 30 nets unrouted (worst 202), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec; freeform/output-products: the 30s deadline passed with no completed packing of 54 strips; 2 packs were routed in that time and the best of them still left 12 nets unrouted (worst 80), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

Per-cell stats line (attempts and pack solves), from the same `.err`:

- `no-proliferator`: `attempts=2 pack_cp_solves=2 pack_cp_feasible=2 pack_cp_unknown=0 budget_unspent_s=0`
- `all-products`: `attempts=2 pack_cp_solves=2 pack_cp_feasible=1 pack_cp_optimal=1 budget_unspent_s=0`
- `output-products`: `attempts=2 pack_cp_solves=2 pack_cp_feasible=1 pack_cp_optimal=1 budget_unspent_s=0`

`budget_unspent_s=0` on all three: the 30 s clock was fully spent.

## Build 2: sequence-pair, `--budget 30`

```
cpu_pressure before: 5.6
/usr/bin/time -v uv run flab2bp "$UM" --budget 30 --strategy sequence-pair -v \
  -o gate/bp-um-b30-seqpair.txt > gate/build-um-b30-seqpair.log 2> gate/build-um-b30-seqpair.err
cpu_pressure after: 21
```

- Exit status: **3**
- Wall clock: **1:34.68**
- CPU percent: **495%**
- User time: 462.19 s, System time: 7.24 s
- Output file `gate/bp-um-b30-seqpair.txt`: not produced

Refusal text, verbatim (from `gate/build-um-b30-seqpair.err`):

> flab2bp: no valid layout for no-proliferator, all-products, output-products after 30s: sequence-pair/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout; sequence-pair/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout; sequence-pair/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

## Build 3: freeform, `--budget 300`

```
cpu_pressure before: 12.4
/usr/bin/time -v uv run flab2bp "$UM" --budget 300 --strategy freeform -v \
  -o gate/bp-um-b300-freeform.txt > gate/build-um-b300-freeform.log 2> gate/build-um-b300-freeform.err
cpu_pressure after: 12.4
```

- Exit status: **3**
- Wall clock: **7:44.30**
- CPU percent: **101%**
- User time: 470.67 s, System time: 1.58 s
- Output file `gate/bp-um-b300-freeform.txt`: not produced

Refusal text, verbatim (from `gate/build-um-b300-freeform.err`):

> flab2bp: no valid layout for no-proliferator, all-products, output-products after 300s: freeform/no-proliferator: no packing of 57 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing; the sweep stopped after 3 draws that produced no new packing; freeform/all-products: no packing of 53 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing; freeform/output-products: no packing of 54 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

Per-cell stats line, from the same `.err` (contrast with build 1's `attempts=2`):

- `no-proliferator`: `attempts=8 pack_cp_solves=11 pack_cp_feasible=8 pack_cp_unknown=3 pack_cp_optimal=0 budget_unspent_s=0 stale_draws=3 stale_stop=1`
- `all-products`: `attempts=14 pack_cp_solves=16 pack_cp_feasible=13 pack_cp_unknown=2 pack_cp_optimal=1 budget_unspent_s=0`
- `output-products`: `attempts=16 pack_cp_solves=16 pack_cp_feasible=15 pack_cp_unknown=0 pack_cp_optimal=1 budget_unspent_s=0`

10x the clock bought 4-8x more attempts (2→8/14/16), and every single one of those additional attempted
packs still failed to route completely — the refusal text itself changed category, from "deadline passed
with no completed packing" (build 1, clock-limited) to "PACKER defect ... packs its own router cannot
wire" (build 3, not clock-limited: `attempts` is non-empty so the code takes the PACKER-defect branch
instead of the deadline branch — see ranked list below).

## Build 4: sequence-pair, `--budget 300`

```
cpu_pressure before: 10.8
/usr/bin/time -v uv run flab2bp "$UM" --budget 300 --strategy sequence-pair -v \
  -o gate/bp-um-b300-seqpair.txt > gate/build-um-b300-seqpair.log 2> gate/build-um-b300-seqpair.err
cpu_pressure after: 18.4
```

- Exit status: **3**
- Wall clock: **13:12.01**
- CPU percent: **405%**
- User time: 3197.67 s, System time: 10.77 s
- Output file `gate/bp-um-b300-seqpair.txt`: not produced

Refusal text, verbatim (from `gate/build-um-b300-seqpair.err`):

> flab2bp: no valid layout for no-proliferator, all-products, output-products after 300s: sequence-pair/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout; sequence-pair/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout; sequence-pair/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

This text is **byte-for-byte identical** to build 2's (`--budget 30`) refusal text, except for the "after
30s"/"after 300s" preamble. A 10x longer clock did not change a single word of the per-island diagnosis.

## Mixed-lane check (Ruling P5)

None of the four builds produced a blueprint file (`gate/bp-um-*.txt` was never written by any of them;
confirmed with `ls` immediately after each run — "No such file or directory" in every case). Per Ruling
P5, step 3 is therefore **skipped**: there is nothing to decode and nothing to check this round.

Method identified for when a blueprint IS produced (recorded per Ruling P5's requirement to state the
method, even though it was not exercised this round): `scripts/audit.py` calls
`report = validate.validate(placement, spec, ...)` at `scripts/audit.py:446` and treats the cell CLEAN only
`if report.ok and not skipped_power` (`scripts/audit.py:463`). `validate.validate` runs every function
registered in its `CHECKS` registry (`src/flab2bp/layout/validate.py:826`), which includes
`_lane_single_item` (`src/flab2bp/layout/validate.py:6318`), registered as
`@check("flow.lane_single_item", needs_spec=True, needs_groups=True)`. Its docstring cites the exact
invariant this task was told to guard: "One input belt carries one item. No exemption (spec Sec 9 R1)." It
walks every sorter feeding a machine from a belt, groups sorters by belt run, and raises an ERROR-severity
finding (`flow.lane_single_item`) whenever a run's sorters carry two or more distinct items into machines —
which would make `report.ok` false and the cell not CLEAN. This is the real mechanism; there is no
`flab2bp.decode` module and no `SHARED-INPUT-RUN` string anywhere in `src/`, `scripts/`, or `tests/`
(confirmed absent, per Ruling P5). No violation was found because no blueprint existed to check.

## Ranked list of what is left

1. **The freeform packer produces packs its own router cannot wire, and more clock does not fix it** —
   `src/flab2bp/layout/freeform.py:20692-20696` (the `PACKER defect` refusal clause, taken only when
   `attempts` is non-empty). Measured directly: build 3 (300 s) had 8-16 routed attempts per cell (vs. 2 at
   30 s) and every one of them still left nets unrouted, so the refusal text itself names this a packer
   defect rather than a clock shortage. This is the residual blocker with no measured fix in hand — it is
   what spec §4.3 blocker 3 names for the freeform arm.

2. **The sequence-pair per-island exact-layout search does not converge with a longer clock** —
   `src/flab2bp/layout/sequence_islands.py:223` (aggregation: `f"all {requested} sequence islands
   refused"`) and `src/flab2bp/layout/sequence_solver.py:1600` (`"deadline": "deadline exhausted before
   finding an exact layout"`). Measured directly: build 2 (30 s) and build 4 (300 s) produced
   byte-for-byte identical refusal text for all three cells and all four islands each — a 10x clock
   multiplier changed nothing. This is spec §4.3 blocker 3 for the sequence-pair arm.

3. **At the gate's own budget (30 s), the freeform failure mode is still partly clock-limited, and that
   mode is distinct from the 300 s mode** — contrast `src/flab2bp/layout/freeform.py:20673-20676` (the
   deadline-exhaustion refusal clause reached at 30 s, where `budget_unspent_s=0` and only 2 attempts
   occurred) against `freeform.py:20692-20696` (the PACKER-defect clause reached at 300 s with 8-16
   attempts). Measured directly: build 1's refusal text says "the 30s deadline passed with no completed
   packing... a longer clock alone would not have wired this spec" (already conceding the clock isn't the
   whole story) while still reporting only 2 attempts, whereas build 3 with 4-8x more attempts converts to
   the router/packer mismatch language. The two refusal texts are not just longer/shorter versions of each
   other; they describe two measured, different symptoms at the two budgets.

4. **Task 3's pack-work bound is reached and is not obviously starving the solve any more** —
   `src/flab2bp/layout/freeform.py:354` (`_DETERMINISTIC_PACK_STRIPS = 15`) and `freeform.py:21617`
   (`deterministic=len(strips) >= _DETERMINISTIC_PACK_STRIPS`). All three refusing cells (57/53/54 strips)
   are above the threshold, so the deterministic path Task 3 rescaled is now live for them (unlike the
   small-tier corpus documented in `pack-work-task3.md`, where it is never reached). Measured directly:
   build 1's `pack_cp_solves` include `FEASIBLE`/`OPTIMAL` outcomes rather than being all `UNKNOWN` (e.g.
   `output-products`: `pack_cp_feasible=1 pack_cp_optimal=1` out of 2 solves) — Task 2's baseline measured
   "all 5 pack solves ended UNKNOWN"; that specific symptom is gone in this round's measurement. This does
   not, by itself, close the refusal — items 1-3 above are what remain — but it is a measured change from
   the pre-Task-3 tree and belongs in the ranking as the thing that moved.

5. **The mixed-lane absolute ban (`flow.lane_single_item`) is unverified for this spec this round** —
   `src/flab2bp/layout/validate.py:6318`, invoked via `scripts/audit.py:446`/`:463`. Not because of any
   suspicion, but because no build produced a placement for it to run against. This is a gap in coverage,
   not a finding of a defect, and it stays open until a build on this URL actually produces a blueprint.

## PASS / NOT MET

**NOT MET.** All four builds refused; neither arm produced a blueprint for `universe-matrix*60` at
`--budget 30` (nor at `--budget 300`, which was run only to separate "needs a longer clock" from "a longer
clock would not fix this," per the brief). The PASS condition (all six `universe-matrix` cells CLEAN at
`--budget 30`) is not met on the one cell/URL this task builds (`*60`), on either arm.

This measurement **agrees with** spec §4.3's stated honest expectation ("Blocker 3 is the one with no
measured fix in hand, and the plan's gate reports what it measures rather than promising a verdict") — no
disagreement, so **no spec correction note was appended**. The `all-products`/`output-products`/
`no-proliferator` cells named in spec §4.2 are the same three cells measured here, and this round's
`--budget 300` freeform text ("PACKER defect") sharpens what §4.2 only characterized as "the antimatter
dynamic-access contention has not been negotiated away yet" — it is now diagnosed by the code itself as a
producer/consumer (packer/router) mismatch, not merely an unresolved contention.

## Scope note

This task built only the `universe-matrix*60` URL/spec (one of the six `universe-matrix` cells the PASS
condition names). The other five cells were not built here; the six-cell claim is Task 5's job. This file
establishes, for `*60` only: both arms refuse at 30 s and at 300 s, the freeform refusal text changes
category between the two budgets (clock-limited to router/packer-mismatch) while the sequence-pair text
does not change at all, and no blueprint was available this round to exercise the mixed-lane invariant.
