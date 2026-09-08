# Buildings index: branch correctness evidence adjudication

## Verdict and scope

**Source review PASS; 12 deterministic controls PASS; paired 72-cell emitted
correctness PASS. The deadline subgate is FAIL in the saved parallel run and
does not reproduce in the serial reruns. The recorded full suite is FAIL, with its
four branch test-cutover failures corrected and focused-green afterward; the
inherited alignment failure remains. This is not an integrated-ready or merged
verdict.**

This report applies the user's revised acceptance: retain the cleaner indexing
regardless of marginal +/-3% timings; no microbenchmark keep/revert gate.
Correctness and real deadline checks remain mandatory. Independent verification
jobs may run concurrently; failing scenarios alone require serial reruns. These
rulings supersede the original plan/ledger's global serialization and timing
acceptance instructions, not its output-equivalence or domain invariants.

Read before adjudication: original brief
`/home/dannyb/handoff-agents/briefs/buildings-index-brief.md`, approved plan
`docs/superpowers/plans/2026-09-07-buildings-index.md` (plan commit `e1f070f3`),
and `.superpowers/sdd/2026-09-07-buildings-index/progress.md`. This worker only
analyzed saved evidence and wrote documentation; no tests, builds, gates,
formatters, linters, benchmarks, commits, or checkout changes were run.

## Exact provenance

Evidence directory: `parallel-correctness-AWM9wmPE/` beside this report.

| Arm | Immutable production source |
|---|---|
| before | `2e861af02b6a5062792f8d21fca009b64aee5ab6` |
| after | `12dd4f3f15861666ff679b392093d4cca1cddbc0` |

Every corpus row names its corresponding SHA. Both arms use the `cython` route
backend, budget 30, power enabled, and the same cell keys. Both corpus log
banners say `72 cells, 1 at a time, 128 CP-SAT workers each, cap 7200s`.
Independent arms/jobs ran concurrently under the revised policy. Their logs
warn that the inherited main-checkout `VIRTUAL_ENV` is ignored in favor of the
project environment; the ledger records the branch-local import verification.
Main's later TEST-ONLY fixture corrections are committed at `4605c7c8`,
following measured production revision `12dd4f3f`. They do not change that
production source and are not retroactively part of the original full-suite
run. Combined integration is verified separately.

Raw evidence is preserved unchanged: `controls.json`, each arm's
`control-exits.json`, twelve `.log`/`.blueprint.txt` pairs, `corpus.jsonl`, and
`corpus.log`. The following comparison was computed directly from those saved
JSONL records, not inferred from a coordinator's success exit.

## Deterministic controls: PASS, 12/12

Main has already compared all twelve complete fixed-timestamp blueprint byte
streams and reported exact equality. This report accepts that completed
comparison, without rerunning it. Saved manifests independently contain all
12 named controls on both arms, all 24 exits are 0, and all 24 output files are
nonempty. Original Task 3's timestamp-only discrepancy is not waived here:
the recovered control procedure fixes encoder ticks to zero so the whole text,
including checksum, is comparable.

| Control | Before exit | After exit | Main's full-byte comparison |
|---|---:|---:|---|
| iron-ingot | 0 | 0 | exact |
| magnetic-coil | 0 | 0 | exact |
| graphene | 0 | 0 | exact |
| electromagnetic-matrix | 0 | 0 | exact |
| plastic | 0 | 0 | exact |
| processor | 0 | 0 | exact |
| energy-matrix | 0 | 0 | exact |
| super-magnetic-ring | 0 | 0 | exact |
| casimir-crystal | 0 | 0 | exact |
| information-matrix | 0 | 0 | exact |
| quantum-chip | 0 | 0 | exact |
| universe-matrix | 0 | 0 | exact |

The exact URL selection is in `controls.json`; this is not a newly selected
subset. These controls are separate from the bounded-search corpus below.

## Corpus completeness and correctness: PASS

Pair key: `(url_id, strategy, spec_label, power, budget)`. Each arm has exactly
72 rows and 72 unique keys; the key sets match with no duplicates, omissions,
or extras. They cover the same twelve products above, both strategies
(`freeform` and `sequence-pair`, 36 rows each), and all three spec labels
(`no-proliferator`, `all-products`, `output-products`, 24 rows each).

| Status transition | Pairs |
|---|---:|
| CLEAN -> CLEAN | 72 |
| Any other transition | 0 |

Each arm has 72 CLEAN, 0 REFUSED, 0 INVALID, 0 CRASH, and 0 not-run cells;
`attempt_failures` and `projection_failures` are empty and `detail` is empty
on every row. Both corpus logs end `EXIT=0`, but the row-level evidence above,
not that exit alone, establishes this result.

The following stats are present and equal in **all 72 pairs**: machines,
pilers, strips, sorters, spray_coaters, nets, routed, route_failures,
last_mile_commit_rejected, and last_mile_restore_mismatch. No emitted
correctness/status regression appears in the saved records. This is not a
claim that all 72 non-deterministic corpus blueprints are byte-identical.

### Exact non-time top-level changed cells

All values below are before -> after. Omitted fields are unchanged. In the
compact projection column: `frames` = projection_frame_candidates, `count` =
projection_count, `collider` = projection_collider_pairs, `power` =
projection_power_pairs, `sorters` = projection_sorters. Every row remains CLEAN.

| Product / strategy / spec | Area | Belt tiles | Projection changes |
|---|---|---|---|
| casimir-crystal / freeform / output-products | unchanged | 430 -> 431 | collider 8158 -> 8102; power 51 -> 0 |
| energy-matrix / sequence-pair / no-proliferator | 616 -> 504 | 139 -> 154 | count 50 -> 22; collider 1610 -> 734; power 50 -> 6; sorters 1300 -> 572 |
| information-matrix / freeform / no-proliferator | 8030 -> 7917 | 2944 -> 3436 | frames 2 -> 1; count 129 -> 147; collider 58012 -> 64575; power 652 -> 245; sorters 37281 -> 42483 |
| information-matrix / freeform / output-products | 5856 -> 5434 | 2756 -> 3273 | count 101 -> 150; collider 54237 -> 79166; power 404 -> 682; sorters 25149 -> 37350 |
| processor / freeform / no-proliferator | unchanged | 272 -> 271 | collider 18666 -> 18483 |
| processor / sequence-pair / output-products | 810 -> 816 | 398 -> 371 | count 183 -> 62; collider 24618 -> 7420; power 3 -> 53; sorters 9333 -> 3162 |
| super-magnetic-ring / freeform / all-products | unchanged | 1198 -> 1196 | collider 38846 -> 42180; power 6 -> 296 |
| super-magnetic-ring / freeform / no-proliferator | 2233 -> 2183 | 1122 -> 1101 | count 177 -> 153; collider 49250 -> 46290; power 144 -> 163; sorters 31683 -> 27387 |
| super-magnetic-ring / freeform / output-products | 2080 -> 2044 | 1261 -> 1164 | count 144 -> 180; collider 43974 -> 52790; sorters 23040 -> 28800 |
| universe-matrix / sequence-pair / all-products | 33605 -> 31603 | 17055 -> 16296 | collider 20045 -> 21432; power 522 -> 531 |
| universe-matrix / sequence-pair / no-proliferator | 17836 -> 17745 | 9394 -> 8753 | collider 87401 -> 87259; power 1326 -> 1137 |
| universe-matrix / sequence-pair / output-products | 16720 -> 19926 | 8467 -> 8297 | count 67 -> 39; collider 70149 -> 41964; power 904 -> 796; sorters 43215 -> 25155 |

Thus 12 pairs have non-time top-level differences (excluding source commit and
nested stats): area changes in 9, belt_tiles and projection_collider_pairs in
12, projection_power_pairs in 10, projection_count and projection_sorters in 7,
and projection_frame_candidates in 1. The remaining 60 pairs have none of
those differences. Source commit, seconds, build_wall_time_s, attempt_wall_s,
and nested stats differ in all 72; wall_overshoot_s differs in two. Nested
stats also record different search work, solver choices, tower counts and
layout objectives; they are not asserted identical. Certified bounded-search
layout/area and work-counter variation is not a microbenchmark veto under the
revised acceptance. The deadline distinction below is not waived.

## Deadline evidence: saved-run FAIL; serial reruns PASS

The logs each report 21 cells finishing after the requested search deadline,
with maximum total completion tails 5.2s before and 6.6s after. That log note
alone is not the grace-overrun metric: `audit.py` computes `wall_overshoot_s`
as `max(0, attempt_wall_s - budget - grace)`. Before has zero positive values;
after has these two positive values, despite CLEAN status:

| Cell (budget 30, power on) | Attempt seconds before -> after | Grace overshoot before -> after |
|---|---|---|
| universe-matrix / freeform / output-products | 32.890193248167634 -> 36.29694606596604 | 0 -> 1.29694606596604 |
| universe-matrix / sequence-pair / all-products | 35.21013646409847 -> 36.620731562841684 | 0 -> 0.6207315628416836 |

These are beyond the recorded completion grace, not merely +/-3% performance
noise. The saved parallel deadline subgate remains FAIL. Main completed the
two serial adjudications below: both PASS, CLEAN with zero grace overshoot.
Combined integration remains separately verified; no source regression is
inferred solely from concurrent timing.

Main reran only the two failed scenarios serially. Both are CLEAN with
`wall_overshoot_s=0.0`: freeform/output-products attempt26.60436619212851s;
sequence-pair/all-products attempt34.43567831395194s. Evidence under
`parallel-correctness-AWM9wmPE/`:
`serial-universe-matrix-freeform-output-products.{jsonl,log}` and
`serial-universe-matrix-sequence-pair-all-products.{jsonl,log}`, with load
files. The original parallel overruns remain recorded, not overwritten.

## Source reviews and executed test evidence are separate

Final read-only source reviews cover immutable `2e861af0..12dd4f3f`:

- `agent://BuildingsDomainFinal`: source/spec PASS, quality APPROVE, no findings,
  confidence 0.94. Ordered mutable buckets, frozen positional identity,
  snapshots and explicit opt-in machine-host traversal reviewed.
- `agent://BuildingsConsumersFinal`: spec PASS, quality PASS, no findings,
  confidence 0.88. Indexed narrowing and retained geometric/flow predicates,
  predecessor ordering, coater filtering, hierarchy weights and cutovers reviewed.
- Prior `BuildingsCutoverReview` PASS and actual host-rate/assigned-supply and
  magnetic-coil CLI red/green are recorded in the ledger. CLI pre-fix was
  NameError/exit 1; fixed exit 0, certified 4 machines / 198 tiles / 65 buildings,
  bands 60/80/100 (`routing-smoke-red.log`, `routing-smoke-green.log`).

Saved logs under `.superpowers/sdd/2026-09-07-buildings-index/`:

| Evidence | Actual result |
|---|---|
| parallel-full-suite.log | EXIT=1; five named failures below |
| serial-failed-nodes.log | EXIT=1; all five reproduce serially |
| serial-test-cutover-fixed.log | four dots, 100%, EXIT=0 after Main's four TEST-ONLY corrections |
| recovery-final-ruff.log | All checks passed!, EXIT=0 |
| recovery-final-format.log | 223 files already formatted, EXIT=0 |
| recovery-final-mypy.log | Success: no issues found in 90 source files, EXIT=0 |

The three stale freeform fixtures are methods on
`TestASprayedLaneEitherGetsACoaterOrRefuses`:
`test_staged_static_alternate_seat_advances_in_order`,
`test_staged_static_alternate_seat_never_passes_the_first_pickup`, and
`test_staged_static_mixed_same_strip_seat_failures_request_clearance`. Each
failed because its stub rejected the new `max_obstacle_span` keyword.
`test_projection_pitch_origin_matching_has_linear_structural_growth` passed
its relative-growth assertion but failed the incidental absolute ceiling
`10364 <= 128 * 10`. Main corrected these four test-cutover issues; the focused
four-case rerun is green. There is no post-correction full-suite PASS in this
evidence, and no total passing-test count is invented.

`test_two_stage_alignment_retains_cp_sat_direct_opportunity` remains the known
inherited failure documented at baseline. The other historically known red,
`test_all_products_sequence_pair_honours_the_exact_layout_deadline`, is not in
this full run's failure list; it must not be reported as failing here merely
because the original plan names it. The two corpus grace overruns above remain
separate from that test's outcome.

## Remaining integration work

1. Preserve the original parallel grace-overrun evidence alongside the completed
   serial reruns; both exact scenarios are now CLEAN with zero grace overrun.
2. Main verifies the final integrated source/tests, including fixture fixes
   already committed at `4605c7c8`. Historical static checks and the focused
   four-case rerun are not a substitute for integrated verification.
3. Integrate with the newer lane-fanout/hierarchy/coater source, then convert
   `markers.py`'s per-seed scans and `freeform._coater_candidate_rides_a_merge`
   using the shared index, driving marker queries from `group_machines` rather
   than all buildings. These sites do not exist on this branch's old base.
4. Preserve the absolute mixed-item input-lane ban, `belt.acyclic`, single-run
   coater riding, certification as arbiter, and FactorioLab flow as authority.
   Defaults remain exact/tesla. Do not weaken these to obtain a green corpus.
5. Preserve the existing default traversal API for indexed-scans and all other
   callers: `Buildings.of`, `splitter_successors(index)`,
   `predecessor_of(index)`, `belt_run(index, *, forward)`; machine-host traversal
   remains explicit `through_any_host=True`, with the default false crossing
   Splitter/Piler only. Reconcile indexed-scans against that shared contract.
6. Retain plan follow-ups for unused junction/port helpers and the latent
   all-pairs collision fallback/singleton belt-crossing assumptions. They are
   not claims of completed conversion or permission for unrelated deletion.

No merge, rebase, integration readiness, or measured speedup is claimed here.
See `profile.md` for the explicitly superseded timing acceptance and missing
profile evidence.

## Combined integration verification

Main merged current lane-fanout/master and hierarchy into this branch. The only
text conflict was the composer test import group; both APIs were retained.
The prescribed `self_loop_prime_heads` and coater-merge callers now use the
shared index, with ascending output-sorter order and exact anchor/altitude
predicates preserved.

Executed frozen-before/current equivalence: 200 reordered single-machine and
series-tap loop graphs, plus 15,000 coater candidate cases, all MATCH.
Ruff `src tests`, format check `src tests`, and mypy `src` each exited 0.
The complete Buildings, markers, freeform, strip-variants, validator, hierarchy,
and bench-metrics module run retained only
`test_all_products_band_160_cold_proof_reaches_a_valid_layout`, already failing
on current master. No blanket green-suite or new integrated-corpus claim.
Logs: `.superpowers/sdd/2026-09-07-buildings-index/integration-*.log`.

Independent bounded integration review: source/spec PASS, quality PASS, no
actionable findings, confidence 0.96. The earlier report review's two stale
state statements (serial adjudication and committed fixture fixes) are corrected
above. Shared indexed-scans delegation still belongs to that later integration.
