# Mall block 20: measured density/search-space bound

## Status and ruling

Task 8's direct replay establishes the bound below. Tests, the unconditional paired
corpus guard and independent review remain pending. Main runs validation; the
recovery worker runs none. The capture and replay are Main's measured evidence.

The recovered source HEAD is `dd507484` (Task 7 fix round). Preserve that work.
Neither the archive nor the live replay identifies one wrong geometric invariant
with a local repair. The change therefore bounds what retained attempts establish;
it does not change packing, routing, funding, acceptance, or the Task 7 A2 ruling.
A repeated logical recipe edge is a diagnostic target, not proof of impossibility.
No starvation-avoidance threshold has been introduced.

## What the archive establishes

The v3 `large-mall-all-products-b60-r1.json` and `r2.json` name block 20
`(steel, titanium-alloy)`, three strips, with the generic `PACKER defect` refusal.
The v4 `mall-all-products-b60-r1.json` and `r2.json` retain that same refusal.
Both v4 rounds report 39 blocks, zero unattempted blocks, dispatch counts 44/6/13
and nine blocks never placed; their shell walls are 37.08 s and 36.67 s.
These are the predecessor's measurements, not recovery-wave runs.

Neither those JSON records nor their terminal logs contain the individual
`PackAttempt` records. Consequently the archive cannot answer:

1. Whether the same logical net fails at every height.
2. The per-height failure-kind counts (in particular BUDGET versus geometry).
3. Which candidate heights were band-skipped, or whether any viable height was tried.

The `floor-b20-*.json` files are from **no-proliferator**, and concern a different
block. They are not evidence about this all-products steel/titanium-alloy block.
The plan's illustrative 9.7 s must not be represented as a recovered per-job
measurement: the archived terminal records do not establish block 20's exact
allocated budget.

## Live recovery: the block is a recut entry

Main's first replay exited 1 before layout: no initial-partition block has exactly
the recipe pair. That invalidates the brief's initial-block-20 fixture assumption,
not the recipe assertion. The archived cell itself reported two recut rounds.

The corrected `--capture` mode delegates real hierarchical rounds unchanged and
retains their actual entries. Main's `block-20-hierarchy-capture-r1.json` contains
round 2, block 20, funded **10.12666118494235 s**, with these exact units:

| uid | source group index | recipe | count |
| --- | --- | --- | --- |
| 2000002 | 29 | steel | 11 |
| 2000003 | 31 | titanium-alloy | 6 |

Initial block 9 instead contains carbon-nanotube/frame-material/steel/titanium-alloy.
The test and replay now reconstruct only the captured units, preserving their
source groups/rates/counts and asserting recipes. No synthetic recipe subset or
different-policy floor fixture is substituted.

The live production refusal reports **15 retained packs**, candidate heights
**12, 16, 21, 26, 33**, **static-access=9, dynamic-access=6**, and **no logical net
common to every retained pack**. This supports the permitted search-space bound,
not a single proved wrong invariant with a local repair. It contains no BUDGET
failure.

### Direct replay at 60 seconds

`block-20-b60-r2.json` reproduces that refusal in **5.329457168933004 s**, with
four production block workers, three packed strips and **no skipped heights**.
The wrapper exits 0 because it records a diagnosed result; `ok=false` is the
solver outcome, not a successful placement.

| candidate height | retained packs | routed nets per pack | failure per pack |
| --- | --- | --- | --- |
| 12 | 3 | 0 | static-access; one stranded port |
| 16 | 3 | 0 | static-access; one stranded port |
| 21 | 3 | 0 | static-access; one stranded port |
| 26 | 3 | 14 of 15 | dynamic-access |
| 33 | 3 | 14 of 15 | dynamic-access |

This answers all three diagnosis questions. The failing logical identity changes
across the retained search; smaller packs fail seating while larger packs reach
the router. The failures are access geometry, not BUDGET. Larger candidate
heights actually pack and route fourteen nets, and none is skipped as over-band:
this is not an all-viable-heights-skipped BAND finding. It does not prove any
candidate is fully wireable, or that widening would fix the failure.

**Ruling: bound, not fix.** Altering the explored packing/seating space needs a
design and evidence this task does not have. Preserve the honest mixed-access
finding and do not tune the sweep. The original unqualified PACKER conviction
no longer hides these observations.

The r2 replay has no immediately preceding `-load.txt` in the evidence set;
its runnable load is **unrecorded**, not borrowed from the capture run. Its wall
is diagnostic/report-only. The initial r1 log is a pre-layout fixture error and
is retained, not relabeled as a solver refusal.

## Reachable implementation

`block_probe.py` builds ALL_PRODUCTS through the same rates entry point as
`floor_probe.py`. Capture mode retains actual production recut entries; replay
reads their unit identities and rejects mismatched URLs or group recipes. It uses
production block workers and vertical rules. Its `_sweep` override calls through,
retaining the supplied attempt and skipped-height containers. JSON includes
geometry, attempted/routed nets, complete routing records, logical identities,
failure kinds, stranded ports and budget stages. Successful placement is judged
by `validate.certify(..., expect_power=True)`.

The terminal refusal change reports retained candidate heights and
failure-kind counts. All-BUDGET and mixed-BUDGET records remain clock findings;
non-budget recurring logical edges identify a net-level investigation; disjoint
failures identify the explored density/search space. One retained pack explicitly
cannot establish recurrence. Existing deadline and port-seating diagnoses retain
their precedence. The change does not assert that different failing nets prove a
particular geometric repair, or that a larger search would succeed.

The regression calls the real all-products block solver at 60 s and asserts the
recipe pair. It accepts only certified placement or a routed refusal carrying a
specific diagnostic bound; it does not accept every exception. Focused tests
protect recurring/disjoint logical identities and the BUDGET/geometry boundary.
The former test that pinned the generic PACKER wording was replaced rather than
re-pinned. The recovery worker did not run these tests. Main subsequently ran
all four focused/real-block regressions with exit 0; see `recovery-task8-tests.log`.
Ruff, formatter check and mypy also exited 0 in the `recovery-final-*.log` files.
Main also ran the complete `tests/layout/test_freeform.py` and
`tests/layout/hierarchy` groups; both exited 0. Their full outputs are retained
in `recovery-full-freeform.log` and `recovery-full-hierarchy.log`.

## Required next evidence

Main corroborated at the captured 10.12666118494235 s budget: the real block
refused after 7.328826766926795 s with the same 15-pack evidence, nine static-access
and six dynamic-access failures, and no common logical failing net. The immediately
preceding runnable-load mean was 5.6. The `block-20-b10.126661-r1.{json,log}` and
`block-20-b10.126661-r1-load.txt` retain this observation.

The revised recipe was also exercised in the fresh
`block-20-b60-replay.983zaF/` directory. Main verified that both archived r2 file
hashes remained unchanged; this new run has its own load, result and log.
The 60 s refusal was already established, so the smaller-budget corroboration is
not a funding diagnosis. A future local repair still needs its own failing
reproduction; the present measured outcome remains the bound above.

Run the default-unchanged paired 72-cell guard **unconditionally** (inherited
T1-A), including if the final resolution is only diagnostic wording. Baseline is
`1d2a790c`, not moving master. Record CLEAN counts, all named differing cells,
0 INVALID / 0 CRASH and both-trees controls for status changes. No guard result is
claimed here. Task 9 needs its own final-HEAD guard after all reviews/fixes settle.

## Review boundary

Task 7's separate `3d5aba53..dd507484` review is complete: independent spec PASS,
quality PASS, no findings (HierarchyFixReview, confidence 0.98). Task 8's separate
source/spec review passed (HierarchyTask8Review). Its sole report-quality finding
was an overwriting replay recipe; that fix passed scoped re-review, confidence 0.99,
and Main exercised the corrected recipe as recorded above. The mandatory Task 8
guard and final whole-branch review still precede the first Task 9 cell.
The measured Task 7 residual remains: one of four
post-fix mall/no-proliferator rounds starved 70 blocks, while three left six never
placed. No evidence in this task erases that residual.
