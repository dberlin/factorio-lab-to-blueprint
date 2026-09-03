# Corpus gate — Deliverable A (capacity-bounded strips), Task 5

Verdict: **PASS**, three rounds, both arms.

## What was measured, and from where

- **Candidate: `2f7d366750f907af3946e4a1b6cf3204cffde834`** (`2f7d366`, branch `multibelt`) —
  Tasks 1-4: `d1e61d5` (cap machines per strip by lane capacity), `1cf021d` (bound every strip
  partition by the family machine cap), `fd17b00` (say how many entry lanes an external item
  needs), `2f7d366` (a flow above the ceiling arrives on several lanes).
- **Baseline: `60ab5f8339776b6c8020046dc1c04733f9a0c2fa`** (`60ab5f8`, the branch point on
  `master`) — "docs(spec): Phase E design for closing the universe-matrix refusals". No committed
  baseline from an earlier gate was reusable per the task brief: every earlier evidence directory
  pre-dates this base.
- **`git diff 60ab5f8 2f7d366 --stat -- '*.pyx'` is empty** — Deliverable A touches no kernel
  source, confirmed before archiving. The worktree's compiled
  `_route_kernel.cpython-314-x86_64-linux-gnu.so` and
  `_sequence_kernel.cpython-314-x86_64-linux-gnu.so` were copied unmodified into both archives'
  `src/flab2bp/layout/`.
- Both arms were extracted fresh with `git archive <sha> | tar -x` into scratch directories (not
  the live worktree), each given a minimal read-only `.git` (`HEAD` holding the full 40-hex sha,
  plus empty `objects/` and `refs/` directories so `git rev-parse HEAD` resolves without needing
  the object store) purely so `scripts/audit.py`'s `_head_commit()` could stamp rows. `git rev-parse
  HEAD` was verified inside each archive before any round ran (see below).
- `scripts/audit.py` inserts its own `_ROOT/src` at the head of `sys.path` (`_ROOT =
  Path(__file__).resolve().parent.parent`), so each archive's own package tree is what ran, driven
  by the worktree's `.venv/bin/python` (CPython 3.14). Verified two ways before the gate rounds: a
  6-cell smoke run against each archive (`--only iron-ingot --budget 5 --jobs 2`) showed
  `route_backend: "cython"` on every row (confirming the copied kernels loaded) and `commit` equal
  to that archive's own sha on every row — `60ab5f833...` for the baseline archive, `2f7d366750...`
  for the candidate archive, never the worktree's HEAD.

### Provenance of the rows

| file | `commit` (all rows) | `route_backend` (all rows) | rows |
| --- | --- | --- | --- |
| `baseline-budget30-round{1,2,3}.jsonl` | `60ab5f8339776b6c8020046dc1c04733f9a0c2fa` | `cython` | 72 each |
| `candidate-budget30-round{1,2,3}.jsonl` | `2f7d366750f907af3946e4a1b6cf3204cffde834` | `cython` | 72 each |

(Spot-checked with `python3 -c "import json; ..."` over each file: every row's `commit` field
matches that arm's archive sha and every `route_backend` is `"cython"`.)

### Invocation, per round r in {1,2,3}, interleaved baseline-then-candidate

```
.venv/bin/python $ARCHIVE/scripts/audit.py --budget 30 --jobs 16 --json $d/<arm>-budget30-round$r.jsonl
```

run from the worktree directory
(`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/multibelt`), `$ARCHIVE` being
the baseline or candidate scratch extraction. `--strategy` left at its default `both` -> `freeform`
+ `sequence-pair`, 72 cells (12 corpus URLs x 3 spec variants x 2 strategies), matching every
earlier gate in this repo.

### Comparison, per round

```
uv run python scripts/audit_compare.py $d/baseline-budget30-round$r.jsonl $d/candidate-budget30-round$r.jsonl \
    --expect-cells 72 --p95-seconds 31 --regressions-only
```

(flags taken verbatim from the task brief; `scripts/audit_compare.py --help` was read first to
confirm they exist and mean what the brief says.)

## Per-round CLEAN counts, both arms

Computed directly from the JSONL rows (`collections.Counter` over `status`), not from the
truncated `tail -8` of the live progress output (some progress lines scrolled past that window):

| round | baseline CLEAN/72 | baseline REFUSED | baseline INVALID | baseline CRASH | candidate CLEAN/72 | candidate REFUSED | candidate INVALID | candidate CRASH |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 66 | 6 | 0 | 0 | 66 | 6 | 0 | 0 |
| 2 | 66 | 6 | 0 | 0 | 66 | 6 | 0 | 0 |
| 3 | 66 | 6 | 0 | 0 | 66 | 6 | 0 | 0 |

The 6 REFUSED cells are the six known universe-matrix cells (`no-proliferator`, `all-products`,
`output-products`, each under both `freeform` and `sequence-pair`) — refusing on **both arms, in
every round**, with the same `detail` text every time (see the compare output below). This matches
the brief's "known" expectation exactly; no new refusal, no INVALID, no CRASH, in either arm, in
any round.

## Compare output, verbatim, all three rounds

### Round 1 (`compare-round1.txt`)

```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0002  p95 28.6s
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: freeform universe-matrix/output-products: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: freeform universe-matrix/all-products: no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
```

### Round 2 (`compare-round2.txt`)

```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0007  p95 28.9s
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: freeform universe-matrix/output-products: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: freeform universe-matrix/all-products: no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
```

### Round 3 (`compare-round3.txt`)

```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9991  p95 28.5s
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: freeform universe-matrix/output-products: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: freeform universe-matrix/all-products: no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
```

## The gate, clause by clause

| # | Clause | round 1 | round 2 | round 3 | verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | No `REGRESSION:` line in any round | none | none | none | PASS |
| 2 | No INVALID / CRASH in any round, either arm | 0/0 | 0/0 | 0/0 | PASS |
| 3 | `wall p95` at or under 31.0 s (`--p95-seconds 31`) | 28.6 s | 28.9 s | 28.5 s | PASS |
| 4 | Candidate covers all 72 cells (`--expect-cells 72`) | 72 rows | 72 rows | 72 rows | PASS |
| 5 | Geometric-mean area ratio over jointly-CLEAN cells within noise (default `--noise-area 0.013`) | 1.0002 | 1.0007 | 0.9991 | PASS |

**Overall verdict: PASS.** No cell that was CLEAN in the baseline became non-CLEAN in the
candidate, in any round; INVALID and CRASH are 0/0 in both arms in every round; every round's p95
wall time is comfortably under the 31 s threshold; the area ratio sits within about 0.1% of 1.0 in
either direction each round, well inside the 1.3% noise band. Deliverable A did not cost a clean
cell.

## Cells whose strip count changed

Rows carry no strip-count field (`json.loads(line).keys()` on a CLEAN row: `area,
attempt_failures, attempt_wall_s, budget, build_wall_time_s, commit, detail, ...` — no `strips`
key), and `detail` is the empty string on every CLEAN row in every file (checked with a script over
all 6 files). Per the brief's fallback, neither reveals strip counts directly, so this section
gives the coverage/area evidence instead, computed per-cell (not just the aggregate ratio the
compare tool prints):

- 66/66 jointly-CLEAN cells matched in every round (no cell moved between CLEAN and non-CLEAN
  between arms, in either direction, in any round).
- Per-cell area deltas among jointly-CLEAN cells (computed directly from the two files' `area`
  fields, paired by `(strategy, url_id, spec_index)`):
  - round 1: 4/66 cells differ (`information-matrix/1` freeform +8.4%, `processor/0` freeform
    -2.3%, `super-magnetic-ring/2` freeform +0.4%, `information-matrix/2` sequence-pair -4.5%)
  - round 2: 4/66 cells differ (`processor/0` freeform +2.3%, `super-magnetic-ring/0` freeform
    -2.9%, `super-magnetic-ring/1` freeform +4.3%, `super-magnetic-ring/2` freeform +1.0%)
  - round 3: 6/66 cells differ (`casimir-crystal/2` freeform -3.9%, `magnetic-coil/2` freeform
    +4.8%, `processor/0` freeform +2.3%, `super-magnetic-ring/0` freeform -1.7%,
    `super-magnetic-ring/1` freeform +4.3%, `information-matrix/1` sequence-pair -11.1%)
  - **These are CP-SAT run-to-run noise, not a systematic effect of the cap.** The evidence:
    `processor/0` (freeform) goes -2.3% in round 1 and then **+2.3% in both round 2 and round 3**
    — the sign flips depending on which round happened to land which equally-valid packing on
    which arm, not on which arm is the baseline. No cell is a repeat offender in the same
    direction across all three rounds. The aggregate geometric-mean ratio (1.0002, 1.0007, 0.9991)
    already captures this: no net growth either way.

## Coarsening count (spec section 10)

`_coarsen_saturated_strip_plan` (`freeform.py:2323`, `_COARSE_STRIP_THRESHOLD = 40` at
`freeform.py:2320`) only fires for the `freeform` strategy, so it was instrumented and measured
**separately from the three gate rounds above**, per the brief's explicit allowance ("instrument
... ONLY IF you run that instrumented round separately and do not count it as one of the three
gate rounds").

**What was done:** both scratch archives' `src/flab2bp/layout/freeform.py` (the baseline archive
and the candidate archive used for the gate rounds — never the worktree, which was not edited) got
one identical one-off `print(..., file=sys.stderr)` inserted right after the `plan_strips(...)`
re-partition call inside `_coarsen_saturated_strip_plan`, logging `spec.label`, the strip count
before re-partitioning, the strip count after, the `coarse_len` chosen, and whether the result
dropped back under the 40-strip threshold (`rescued`). Two extra runs — `--budget 30 --jobs 1
--strategy freeform` (serial, so the debug line for a cell prints immediately before that cell's
own completion line, letting each event be attributed unambiguously) — were made against each
instrumented archive and their JSONL/stdout/stderr discarded to scratch; they are not part of the
gate's 6 counted rounds and are not committed.

**Result — identical in both arms:**

```
COARSEN_DEBUG label='no-proliferator' before=57 after=43 coarse_len=224 rescued=False
COARSEN_DEBUG label='all-products' before=46 after=42 coarse_len=113 rescued=False
COARSEN_DEBUG label='output-products' before=53 after=43 coarse_len=193 rescued=False
```

in both the baseline-archive run and the candidate-archive run, matching (by job order and by the
42/43-strip counts named in the REFUSED `detail` text) the three `universe-matrix` freeform cells
— the same three that refuse in every gate round above. `_coarsen_saturated_strip_plan` entered
its collapsing branch for exactly these 3 cells in **both** arms, produced the exact same
before/after strip counts in both arms (57->43, 46->42, 53->43), and rescued none of them (all
stayed above the 40-strip threshold) in **both** arms.

**Coarsening-no-longer-rescues count: 0.** On this corpus, at this budget, Deliverable A's cap did
not change which cells trigger coarsening, how many strips they start or end with, or whether
coarsening rescues them — the cap simply does not bind tightly enough on `universe-matrix`'s
`machine_cap` to move these strip counts. This is consistent with the corpus gate showing no area
or coverage regression: the risk section 10 flags (coarsening losing its rescue where the cap
binds) has not materialized on the 72-cell corpus at budget 30.

## Load at the moment each round started

(`uptime` plus `vmstat 1 3 | tail -3`, written before every round per the brief; the box is never
idle by house rule — load average climbs from ~5 to ~22 over the run as other work overlaps, which
is expected and not a confound since baseline and candidate in the same round ran back-to-back
under the same ambient load.)

```
=== round 1 load (before baseline) ===
 17:57:00 up 18 days, 23:43,  9 users,  load average: 5.00, 4.64, 5.57
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 4  0      0 1037072044  0 10117264   0    0 49336 15357 23373   4  5  2 93  0  0  0
 5  0      0 1036874168  0 10117292   0    0     0   500 17854 27996 2 1 97  0  0  0
 2  0      0 1036994920  0 10117264   0    0     0 13520 16222 34261 2 1 97  0  0  0

=== round 1 load (before candidate) ===
 17:58:21 up 18 days, 23:44,  9 users,  load average: 12.76, 7.60, 6.56
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 2  0      0 1035224876  0 10117296   0    0 49334 15357 23373   4  5  2 93  0  0  0
 3  0      0 1035222000  0 10117300   0    0     0     0 14425 27764 2 0 98  0  0  0
 2  0      0 1036634992  0 10117300   0    0     0     0 19353 28424 2 0 98  0  0  0

=== round 2 load (before baseline) ===
 17:59:40 up 18 days, 23:45,  9 users,  load average: 22.13, 11.62, 8.04
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 1  0      0 1036495776  0 10118128   0    0 49331 15356 23373   4  5  2 93  0  0  0
 1  0      0 1036493344  0 10118132   0    0     0 15860 15528 34006 1 1 98  0  0  0
 2  0      0 1036496476  0 10118132   0    0     0     4 13453 26737 1 0 98  0  0  0

=== round 2 load (before candidate) ===
 18:00:59 up 18 days, 23:47,  9 users,  load average: 17.32, 12.92, 8.81
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 2  0      0 1036410804  0 10118132   0    0 49329 15358 23373   4  5  2 93  0  0  0
 3  0      0 1036413112  0 10118132   0    0     0   504 15692 29667 2 2 96  0  0  0
 8  0      0 1036410384  0 10118136   0    0     2   314 19713 26437 2 1 96  0  0  0

=== round 3 load (before baseline) ===
 18:02:21 up 18 days, 23:48,  9 users,  load average: 18.71, 14.91, 9.88
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 2  0      0 1036763180  0 10118184   0    0 49326 15361 23373   4  5  2 93  0  0  0
 4  0      0 1036755948  0 10118192   0    0     0    12 16134 27784 1 2 96  0  0  0
 4  0      0 1036756916  0 10118192   0    0    16   260 13432 23976 1 1 97  0  0  0

=== round 3 load (before candidate) ===
 18:03:41 up 18 days, 23:49,  9 users,  load average: 15.35, 15.13, 10.39
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 4  0      0 1037498704  0 10117308   0    0 49324 15361 23373   4  5  2 93  0  0  0
 1  1      0 1037500124  0 10117308   0    0     0 76780 17221 43405 1 2 97  0  0  0
 3  0      0 1037500912  0 10117308   0    0     8  2309 13679 27027 1 0 98  0  0  0
```

## Step 3: verification

- `uv run pytest -q`: exit **0** (the pytest-summary line does not print in this environment per
  house convention; exit code is authoritative). Tail of output ends `.... [100%]` with no
  failures reported anywhere in the run.
- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: `Found 184 errors in 16 files (checked 168 source files)` — matches the documented
  184-error baseline exactly (pre-existing `attr-defined` / `name-defined` noise in
  `tests/scripts/test_audit.py`, `tests/scripts/test_ab_compare.py`, `tests/bench/test_runner.py`;
  unrelated to this change).

## Expected direction

The corpus gate shows the expected direction for Deliverable A: it did not cost a clean cell (66
CLEAN in both arms, every round), it did not move the area ratio outside noise, and the six
universe-matrix cells refuse identically on both arms, as documented as a known, pre-existing
condition. No new refusal appeared and none of the six existing refusals changed.
