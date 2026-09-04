# Gate B: stacked lanes

Verdict: **PASS** in all three rounds.

Deliverable B (Tasks 6-10) makes the cargo stack a planned and validated quantity. This gate asks the
only question the corpus can answer: did any of it move an `ist=1` build?

## Arms

| arm | commit | what it is |
| --- | --- | --- |
| baseline | `2f7d366750f907af3946e4a1b6cf3204cffde834` | Task 5's committed CANDIDATE rounds (Deliverable A), read from `docs/superpowers/evidence/2026-09-03-multiple-belts/candidate-budget30-round{1,2,3}.jsonl`. **Not re-run.** |
| candidate | `5e9b6c387397e9523047b17e23917e9ffab09a88` | this worktree's HEAD: Deliverable B complete (Tasks 6-10). |

`git diff 2f7d366 5e9b6c3 --stat -- '*.pyx'` was **empty**, so the compiled kernels were copied rather
than rebuilt. The candidate archive was extracted with `git archive 5e9b6c3 | tar -x`, the two
`.so` kernels copied into `src/flab2bp/layout/`, and a minimal `.git` (`objects/`, `refs/`, and `HEAD`
holding the full 40-hex sha) written so `_head_commit` stamps every row with the ARCHIVE's sha rather
than the worktree's.

Provenance, checked on the rows themselves and not assumed: every row of all three candidate files
carries `commit = 5e9b6c387397e9523047b17e23917e9ffab09a88` and `route_backend = "cython"` (so the
copied kernels loaded, not a pure-Python fallback). A 6-cell smoke run
(`--only iron-ingot --budget 5 --jobs 2`) confirmed both before any gate round.

## Rounds

Three candidate rounds at `--budget 30 --jobs 16`, each in the foreground, redirected to a scratch
file, never a background or Monitor wait. `uptime` and `vmstat 1 3` recorded to `load.txt` before
every round; the box is never idle and no round waited for it.

| round | CLEAN/72 | REFUSED | INVALID | CRASH |
| --- | --- | --- | --- | --- |
| 1 | 66 | 6 | 0 | 0 |
| 2 | 66 | 6 | 0 | 0 |
| 3 | 66 | 6 | 0 | 0 |

The 6 REFUSED cells are the six known `universe-matrix` cells, refusing identically in the baseline
with matching `detail` text. `audit.py` exits non-zero and prints `NOT CLEAN` on any refusal; that is
its behaviour with a pre-existing refusal present, not a finding of this gate.

## Clause by clause

`uv run python scripts/audit_compare.py <baseline> <candidate> --expect-cells 72 --p95-seconds 31
--regressions-only`, one per round (verbatim in `compare-round{1,2,3}.txt`).

| clause | round 1 | round 2 | round 3 | verdict |
| --- | --- | --- | --- | --- |
| no `REGRESSION:` line | 0 | 0 | 0 | **PASS** |
| all 72 cells ran (`--expect-cells 72`) | 72 | 72 | 72 | **PASS** |
| INVALID = 0, both arms | 0 | 0 | 0 | **PASS** |
| CRASH = 0, both arms | 0 | 0 | 0 | **PASS** |
| CLEAN not reduced (66 baseline) | 66 | 66 | 66 | **PASS** |
| p95 wall <= 31.0 s | 28.3 s | 28.3 s | 28.5 s | **PASS** |
| area ratio within 1.3% noise | 1.0008 | 0.9992 | 1.0014 | **PASS** |
| script verdict | PASS | PASS | PASS | **PASS** |

Every refusal appears as a `CARRIED:` note, never a `REGRESSION:` line: the same six cells, refusing
for the same reasons, in both arms, in every round.

## Every cell in default mode (`--noise-area 0.013`)

`compare-default-round{1,2,3}.txt` holds the same three comparisons without `--regressions-only`.
All three print `FAIL`, and the reason is recorded here rather than glossed: default mode marks
**every** REFUSED cell `FAIL REFUSED` whether or not the baseline refused it too. All six lines in
all three rounds are the six pre-existing `universe-matrix` refusals. Default mode cannot distinguish
a carried refusal from a new one; that is what `--regressions-only` is for, and it reports zero
regressions. The aggregate numbers default mode prints are the same ones in the table above.

### Per-cell area movement — what the data actually shows

The brief asked this gate to assert that no `ist=1` cell moved outside noise. **That assertion is not
what the data supports, and it is not made here.** The recorded per-cell comparison
(`per-cell-area.txt`) over the 66 jointly-CLEAN cells is:

| round | byte-identical area | outside +/-1.3% |
| --- | --- | --- |
| 1 | 62 / 66 | 4 |
| 2 | 63 / 66 | 1 |
| 3 | 62 / 66 | 4 |

Six distinct cells account for every movement, and each one's area across all three rounds of BOTH
arms is:

| cell | baseline r1/r2/r3 | candidate r1/r2/r3 |
| --- | --- | --- |
| freeform `casimir-crystal/output-products` | 1144/1144/1100 | 1100/1144/1144 |
| freeform `processor/no-proliferator` | 864/884/884 | 943/884/864 |
| freeform `super-magnetic-ring/no-proliferator` | 2220/2156/2146 | 2124/2146/2146 |
| freeform `super-magnetic-ring/all-products` | 1880/1960/1960 | 1880/1880/1880 |
| sequence-pair `information-matrix/output-products` | 5150/5394/5394 | 5394/5394/5394 |
| sequence-pair `information-matrix/all-products` | 3960/3960/3960 | 3960/3960/4453 |

What that shows:

* **Each arm varies against itself.** Every one of these cells takes more than one value across the
  baseline's own three rounds, or across the candidate's. This is CP-SAT run-to-run variance at a 30 s
  budget, the same effect Gate A recorded for the same cells.
* **No cell moves consistently in one direction to a value the other arm never reaches.** Two of the
  three repeat movers flip sign between rounds. The third,
  `freeform super-magnetic-ring/all-products`, lands on 1880 in all three candidate rounds — but 1880
  is a value the BASELINE itself produced in its round 1, and it is the SMALLER area.
* **One single-round outlier:** `sequence-pair information-matrix/all-products` reads 4453 in candidate
  round 3 where every other reading in both arms is 3960. It does not repeat, and the round-3 aggregate
  ratio (1.0014) absorbs it.

So the honest statement is: **the aggregate area ratio is inside the 1.3% band in all three rounds, and
no cell shows a movement attributable to Deliverable B** — but 1 to 4 cells per round do fall outside
the band, on both arms, from solver noise.

## Why the corpus cannot exercise the stacked path

**No corpus URL carries `ist>1`.** Measured, not assumed: `corpus-ist.txt` parses all 12
`URL_CORPUS` entries and every one reports `ist=None`.

Design rule 1 says an `ist=1` save is judged exactly as it was, and the code keeps that literally:
`BuildSpec.planning_stack` returns 1 immediately when `belt_stack == 1`, `Context.stack_of` returns 1
for every run on the same condition, and `_pick_sorter`'s two stack parameters default to 1. So on
this corpus every stack is 1, every capacity comparison is multiplied by 1, and the retier pass divides
by 1. **This gate proves Deliverable B costs the unstacked corpus nothing. It proves nothing about the
stacked path, because the corpus contains none of it.**

The only evidence of the stacked path is
`tests/test_pipeline.py::test_a_stacked_url_belts_hydrogen_in_on_one_lane`: the deuteron-fuel-rod URL
with `ist=2` patched onto the request, every technology researched, `sequence-pair`, 45 s budget. It
records that the build validates, that `spec.belt_stack == 2` reaches the spec, and that hydrogen's
entry-lane finding reports `capacity 60/s` with `lanes_needed 1` where the unstacked build reports
30/s and 2 (pinned in `tests/test_cli.py`). Two entry lanes are still emitted — freeform seats one
in-lane per consumer strip and two strips want hydrogen — which is a seating decision, not a rate one.

## Verification at the candidate commit

* `uv run pytest -q`: exit **0**, no `FAILED` lines.
* `uv run ruff check .`: `All checks passed!`
* `uv run mypy src tests`: `Found 184 errors in 16 files (checked 168 source files)` — the documented
  baseline, unchanged.
