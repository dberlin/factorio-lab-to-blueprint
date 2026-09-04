# Gate C: Automatic Pilers

Verdict: **PASS** in all three rounds, with the measured caveats below.

## Audited arms and provenance

| arm | commit | evidence |
| --- | --- | --- |
| baseline | `5e9b6c387397e9523047b17e23917e9ffab09a88` | Task 10's three committed candidate files at `docs/superpowers/evidence/2026-09-03-stacked-lanes/candidate-budget30-round{1,2,3}.jsonl`; not re-run |
| candidate | `fa9032df25f46f2c50f86d18e09b30d9eae020bc` | three fresh rounds in this directory |

`provenance.txt` is the executable provenance record. The candidate was extracted with
`git archive fa9032df25f46f2c50f86d18e09b30d9eae020bc` into scratch outside the repository.
The archive has a detached minimal `.git/HEAD` holding that full SHA plus empty `objects/` and
`refs/`, so `scripts/audit.py:_head_commit()` stamps the archive commit rather than the live
worktree. The baseline helper ran from a separate archive prepared the same way at Task 10's SHA.

The following command had empty output:

```text
git diff --name-status 5e9b6c387397e9523047b17e23917e9ffab09a88 fa9032df25f46f2c50f86d18e09b30d9eae020bc -- '*.pyx' '*.pxd' setup.py pyproject.toml
```

The two unchanged CPython 3.14 Cython kernels were copied into both archives. Their candidate and
baseline SHA-256 values match pairwise (`provenance.txt`). Archive import resolution points at the
candidate archive, and `route_kernel.selected_backend` reports `cython`. A six-cell candidate smoke
(`--only iron-ingot --budget 5 --jobs 2`) was CLEAN 6/6 and stamped the candidate SHA and Cython
backend on all six rows before the gate rounds.

## Candidate rounds

Before every round, `load.txt` records `uptime` followed by the complete output of `vmstat 1 3`.
The one-minute load averages were 2.58, 4.92, and 9.27. No idle-box assumption is made.

Each round ran in the foreground from the frozen candidate archive with the worktree's CPython 3.14
interpreter:

```text
python scripts/audit.py --budget 30 --jobs 16 --json candidate-budget30-round<N>.jsonl
```

`--strategy` was left at its default `both`, so every round contains the 72 expected cells: 12 URLs
x 3 default candidate policies x the two explicit strategies (`freeform`, `sequence-pair`). The
script exits 1 because it treats every refusal as NOT CLEAN; the concise captured summaries are
`audit-round{1,2,3}.txt`.

| round | rows / unique cells | CLEAN | REFUSED | INVALID | CRASH | commit rows | Cython rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 72 / 72 | 70 | 2 | 0 | 0 | 72 | 72 |
| 2 | 72 / 72 | 70 | 2 | 0 | 0 | 72 | 72 |
| 3 | 72 / 72 | 70 | 2 | 0 | 0 | 72 | 72 |
| total | 216 / 216 round-cells | 210 | 6 | 0 | 0 | 216 | 216 |

Every round has 36 Freeform and 36 SequencePair rows. Every one of the 216 rows carries
`commit=fa9032df25f46f2c50f86d18e09b30d9eae020bc` and `route_backend="cython"`.
`piler-stats.txt` contains the exact round counts and refusal details.

## Required round-for-round comparator

Each `compare-round<N>.txt` is the verbatim output of:

```text
python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-stacked-lanes/candidate-budget30-round<N>.jsonl \
  docs/superpowers/evidence/2026-09-04-pilers/candidate-budget30-round<N>.jsonl \
  --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
```

| clause | round 1 | round 2 | round 3 | verdict |
| --- | ---: | ---: | ---: | --- |
| comparator final line | PASS | PASS | PASS | **PASS** |
| expected candidate rows | 72 | 72 | 72 | **PASS** |
| CLEAN | 70 | 70 | 70 | **PASS** (Task 10 had 66) |
| REFUSED | 2 | 2 | 2 | carried status, no CLEAN regression |
| INVALID / CRASH | 0 / 0 | 0 / 0 | 0 / 0 | **PASS** |
| jointly-CLEAN paired area cells | 66 | 66 | 66 | measured |
| geometric-mean area ratio | 0.9968 | 0.9997 | 1.0016 | **PASS**, all <= 1.013 |
| p95 wall | 28.9 s | 28.5 s | 28.4 s | **PASS**, all <= 31 s |
| `REGRESSION:` lines | 0 | 0 | 0 | **PASS** |

Four Task 10 refusals are CLEAN in every candidate round: both explicit strategies on
`universe-matrix/{all-products,output-products}`. Two remain REFUSED in every round:
`universe-matrix/no-proliferator` under both strategies. `--regressions-only` labels both
`CARRIED` because that mode classifies by paired status. The SequencePair refusal detail is
unchanged (`deadline exhausted before finding an exact layout`). The Freeform refusal's status is
carried but its reason is not: Task 10 reached a `game.blueprint_area` rejection, while Task 15 says
no packing of 43 strips could be wired. This gate claims no reason-level identity for that cell.

For transparency, `compare-default-round{1,2,3}.txt` preserves the same comparisons without
`--regressions-only`. All three end `FAIL`, solely because default mode treats each candidate
REFUSED row as a failure even when the paired baseline row was already REFUSED. These files and the
status/detail record in `piler-stats.txt` distinguish carried refusal status from a new regression.

## Effective pre-search strips: byte-identical

`effective_strip_counts.py` does not compute or inspect raw `plan_strips` output. It fails if either
required seam or its signature is unavailable, then runs the real default audit matrix and stops
only when deterministic preprocessing reaches the production search boundary:

- Freeform is intercepted at `_machines_without_poses(strips)`, after
  `_coarsen_saturated_strip_plan`.
- SequencePair is intercepted at `_variant_search_inputs(spec, strips, *, families=None,
  strip_len)`, after its actual strip-length heuristics, `_coarsen_saturated_strip_plan`, and
  `_sequence_reservation_strips`.

Each record contains the effective strip count and the sum of `PilerPlan.count` over those effective
strips. The helper emitted 72 sorted records from each frozen archive. The preserved outputs are
`baseline-effective-strips.jsonl` and `candidate-effective-strips.jsonl`.

`effective-strip-equality.txt` records:

```text
command: cmp -s baseline-effective-strips.jsonl candidate-effective-strips.jsonl
result: EQUAL (exit 0; byte-for-byte identical)
baseline rows: 72
candidate rows: 72
baseline piler total: 0
candidate piler total: 0
baseline sha256: e57b457ae3ec23ceb5d3c73e2a2d7dfc734c5803f84a3547319ac028d8b42c76
candidate sha256: e57b457ae3ec23ceb5d3c73e2a2d7dfc734c5803f84a3547319ac028d8b42c76
```

Thus every strategy/cell pair reaches search with the same number of effective strips under Task 10
and Task 15, and every candidate pair has zero planned pilers.

## Piler count in the audit rows

All 210 CLEAN candidate rows explicitly serialize `stats.pilers=0.0`. The six placement-free
REFUSED rows omit solver stats; read by the audit consumer convention
`row.get("stats", {}).get("pilers", 0)`, all 216 round-rows are zero. The independent seam output
closes the omission rather than pretending an absent field was explicit: both refused cells also
report `pilers=0` in `candidate-effective-strips.jsonl`, and every one of the 216 audit rows joins to
one of those 72 zero-piler cell records. No corpus cell exercised a piler; this gate measures the
required unstacked-corpus non-regression only.

## Aggregate and per-cell area movement

`per-cell-area.txt` preserves every changed paired CLEAN cell, not only the aggregate. The exact
summary is:

| round | jointly CLEAN | byte-identical area | changed area | outside +/-1.3% |
| --- | ---: | ---: | ---: | ---: |
| 1 | 66 | 60 | 6 | 5 |
| 2 | 66 | 63 | 3 | 3 |
| 3 | 66 | 63 | 3 | 2 |

The gate does **not** claim every cell stayed inside 1.3%; the measured gate is the comparator's
geometric-mean ratio, and all three aggregate ratios pass. Three cells move outside the per-cell
band in at least two paired rounds:

- Freeform `information-matrix/all-products`: down in round 1, up in round 3; both values already
  occur in Gate B's Task 5 + Task 10 history.
- Freeform `processor/no-proliferator`: down in rounds 1 and 2, up in round 3; Gate B itself recorded
  this cell flipping down/up, and every Gate C value already occurs in Gate B history.
- Freeform `super-magnetic-ring/no-proliferator`: the only repeated directional mover, up in rounds
  1 and 2 (2124 -> 2183 and 2146 -> 2233), with round 3 unchanged at 2146.

The directional mover was explicitly checked against Gate B's historical picture. Gate B measured
Task 5 + Task 10 CLEAN areas `[2220, 2156, 2146, 2124, 2146, 2146]` for that cell, including an
opposite-direction 2220 -> 2124 movement in its round 1. Gate C measures `[2183, 2233, 2146]`;
its maximum 2233 is 13 tiles (0.586%) above Gate B's historical maximum. The prior opposite move,
the candidate's unchanged third pair, and the multi-round spread are consistent with solver
variance, but these data cannot exclude an implementation contribution at this one cell. The PASS
therefore rests on the three passing aggregate comparisons and the byte-identical effective strip
records, not on a stronger per-cell attribution claim.

## Gate decision and caveats

**PASS** is the exact Gate C verdict because all three required `--regressions-only` comparisons
pass: full 72-cell coverage, zero INVALID/CRASH, no CLEAN regression, p95 below 31 s, and aggregate
area ratio within the 1.3% gate in every round. Effective pre-search strip records are byte-identical
for all 72 strategy/cell pairs, and the candidate effective plans contain zero pilers.

Exact caveats:

1. The unstacked corpus exercises no piler, so this evidence proves only its non-regression surface;
   it makes no claim about piled-build behavior.
2. Two status-carried refusals remain per round. One of their reason strings changed, as detailed
   above; default comparison mode consequently ends FAIL in every round.
3. Six REFUSED JSONL rows omit `stats.pilers`; their zero count is established by the all-cell seam
   helper rather than misreported as an explicit row field.
4. One per-cell area mover repeats upward in two rounds. Its historical investigation is preserved
   above and in `per-cell-area.txt`; no stronger attribution is claimed.
