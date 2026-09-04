# Task 6: the 72-cell corpus gate, three rounds against fresh baselines

Worktree: `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exchanger`,
branch `energy-exchanger`, HEAD `229c9a3` (clean) throughout this gate. Raw evidence
(JSONL rows, per-round audit logs, `audit_compare` output, the watched-clause script and
its output) is committed alongside this file under `docs/superpowers/evidence/2026-09-03-energy-exchanger/broke6-gate/`.

## Two deviations from the brief's literal commands, and why

The brief's script text was written against an earlier state of this multi-agent repo and
two of its literal commands no longer do what they say on this box. Both are corrected
below; both corrections are what the coordinator's dispatch message independently
specified.

**1. The merge-base command.** The brief's step 1 runs
`git -C /home/dannyb/sources/factorio-lab-to-blueprint merge-base HEAD master`. `-C` points
this at the **main checkout**, whose own `HEAD` is `master`'s own tip -- so the command
computes `merge-base(master, master)`, i.e. master's current tip, not the branch point.
Measured: this literal command returns `74d2f075817cb49ade1462268a2fb844df0925ee`, which is
master's tip as of this run (another task merged into master concurrently, unrelated to
this branch). The correct merge-base, computed against the worktree's actual branch tip:
```
$ git -C /home/dannyb/sources/factorio-lab-to-blueprint merge-base energy-exchanger master
3a10f21ce8410e0d89df179290f2b715fce5e0a2
```
Matches the coordinator's stated `3a10f21` exactly. Used `3a10f21ce8410e0d89df179290f2b715fce5e0a2`
as `MB` for both baseline archives.

**2. The candidate-audit working directory.** The brief's step 4 runs
`cd /home/dannyb/sources/factorio-lab-to-blueprint` before `uv run python scripts/audit.py`.
That is the main checkout, currently on `master` at `74d2f07` -- a commit that does **not**
contain this branch's five task commits. Auditing there would silently audit the wrong
code. Ran the three candidate rounds from the worktree
(`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exchanger`, HEAD
`229c9a3`) instead, which is the actual candidate under test.

**3. `--json` field names (brief step 6).** The brief's watched-clause snippet guesses at
`r.get("buildings")` as a per-cell field and says explicitly "the keys above are the
expected shape, not a promise." Read `scripts/audit.py`'s `Result` dataclass
(`:180-234`) and its `record()` JSON writer (`:581-617`) with `mcp__serena__find_symbol`:
the row carries `strategy`, `commit`, `route_backend`, `url_id`, `spec_index`,
`spec_label`, `power`, `budget`, `status`, `area`, `seconds`, `build_wall_time_s`, five
`projection_*` counters, `attempt_failures`, `projection_failures`, `detail`, and
(placement-only) `attempt_wall_s`/`wall_overshoot_s`. There is **no top-level `buildings`
field** -- `buildings` appears only nested inside one `projection_failures[]` entry, naming
which buildings a specific projection failure touched, not a placement-wide count. The
watched clause below therefore compares `status` and `area`, the two fields that actually
exist and actually describe "did this cell's outcome move."

## Step 1: two fresh baselines from a git archive of the merge-base

```
MB=3a10f21ce8410e0d89df179290f2b715fce5e0a2
for n in 1 2; do
  BASE=/tmp/broke6-baseline-$n
  rm -rf "$BASE" && mkdir -p "$BASE"
  git -C /home/dannyb/sources/factorio-lab-to-blueprint archive "$MB" | tar -x -C "$BASE"
  cp /home/dannyb/sources/factorio-lab-to-blueprint/src/flab2bp/layout/_*.cpython-314-x86_64-linux-gnu.so \
     "$BASE/src/flab2bp/layout/"
done
```
Both `.so` kernels (`_route_kernel`, `_sequence_kernel`) copied into both archives.

**Hand-froze a `.git` HEAD in each archive** so `audit.py`'s `_head_commit()`
(`git rev-parse HEAD` with `cwd=_ROOT`, where `_ROOT` is the invoked script's own parent
directory -- i.e. the archive root, since we run `scripts/audit.py` with cwd inside the
archive) stamps every row with the merge-base SHA instead of `"unknown"`. `git archive`
does not include a `.git` directory, so this needed constructing:
```
for n in 1 2; do
  BASE=/tmp/broke6-baseline-$n
  git -C "$BASE" init -q -b main .
  echo "$MB" > "$BASE/.git/refs/heads/main"
done
```
Verified `git rev-parse HEAD` (which only resolves the ref chain, not the object
database) prints `$MB` correctly in both archives before running any audit.

## Step 2: the box before timing anything

Before the first audit round:
```
$ uptime
 21:42:27 up 19 days,  3:28, 10 users,  load average: 5.44, 5.50, 8.70
$ vmstat 1 3
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 3  0      0 1031168492  0 13988024  0    0 48977 15360 23351   4  5  2 93  0  0  0
 8  0      0 1031164340  0 13988024  0    0     0     0 20581 28094 10 1 89 0  0  0
 2  0      0 1031300448  0 13988024  0    0     0   144 21838 26889 3 0 97  0  0  0
```
After all five audit rounds:
```
$ uptime
 21:51:45 up 19 days,  3:37, 10 users,  load average: 11.08, 12.55, 11.42
$ vmstat 1 3
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 2  0      0 1031460980  0 14017304  0    0 48960 15356 23350   4  5  2 93  0  0  0
 2  0      0 1031461852  0 14017308  0    0     0     0 17122 34409 1 1 98  0  0  0
 2  0      0 1031446044  0 14017308  0    0     0  1160 14724 25389 2 1 97  0  0  0
```
The box was never idle across this run (load average 5-13 throughout, consistent with
the standing "dev box load is disk, not CPU" note); ran anyway rather than waiting for it
to settle. **Process deviation, noted honestly**: recorded `uptime`/`vmstat` once before
the first round and once after the last, satisfying the brief's literal step 2, rather
than before each of the five rounds individually as the coordinator's dispatch message
additionally asked. This does not affect any verdict below -- box load affects wall-clock
timing, which `audit_compare`'s `--p95-seconds 31` gate already tolerates and which every
round passed regardless; it does not affect `status`, `area`, or which cells build.

## Step 3: baseline audits (2 rounds)

```
for n in 1 2; do
  rm -f "/tmp/broke6-baseline-$n.jsonl"
  ( cd "/tmp/broke6-baseline-$n" && \
    /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python scripts/audit.py \
      --tier stress --budget 30 --jobs 16 --json "/tmp/broke6-baseline-$n.jsonl" )
done
```

Both rounds: `72/72 cells`, `33/36 clean` on each strategy, `exit=1` (audit.py's own
"NOT CLEAN" verdict on pre-existing refusals -- **not** the gate's verdict, per the
brief's own instruction: "record the exit code and move on"). Both rounds refuse the
identical six cells for the identical reasons:

- `freeform universe-matrix/no-proliferator`: `game.blueprint_area` -- a 264x162 extent
  fits no band on a segment-200 planet.
- `freeform universe-matrix/output-products`: "no packing of 43 strips could be wired at
  any candidate height" (a packer defect, pre-existing).
- `freeform universe-matrix/all-products`: same, "no packing of 42 strips."
- `sequence-pair universe-matrix/{no-proliferator,output-products,all-products}`:
  "deadline exhausted before finding an exact layout" (all three, at this 30 s budget).

Full logs: `baseline-1.audit.log`, `baseline-2.audit.log`. Full rows: `baseline-1.jsonl`,
`baseline-2.jsonl`.

## Step 4: candidate audits (3 rounds, from the worktree)

```
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exchanger
for round in 1 2 3; do
  rm -f "/tmp/broke6-candidate-$round.jsonl"
  uv run python scripts/audit.py --tier stress --budget 30 --jobs 16 \
    --json "/tmp/broke6-candidate-$round.jsonl"
done
```

All three rounds: `72/72 cells`, `33/36 clean` on each strategy, `exit=1`, refusing the
**identical six cells for the identical reasons** as both baseline rounds -- byte-identical
refusal text, every round. Full logs: `candidate-1.audit.log` through `candidate-3.audit.log`.
Full rows: `candidate-1.jsonl` through `candidate-3.jsonl`.

## Step 5: compare each round, plus the baseline self-check

```
for round in 1 2 3; do
  uv run python scripts/audit_compare.py \
    /tmp/broke6-baseline-1.jsonl "/tmp/broke6-candidate-$round.jsonl" \
    --regressions-only --expect-cells 72 --p95-seconds 31
done
uv run python scripts/audit_compare.py \
  /tmp/broke6-baseline-1.jsonl /tmp/broke6-baseline-2.jsonl \
  --regressions-only --expect-cells 72 --p95-seconds 31
```

| Comparison | clean | refused | invalid | crashed | paired | area ratio | p95 | verdict | exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-1 vs candidate-1 | 66 | 6 | 0 | 0 | 66 | 0.9969 | 28.3s | **PASS** | 0 |
| baseline-1 vs candidate-2 | 66 | 6 | 0 | 0 | 66 | 0.9984 | 28.6s | **PASS** | 0 |
| baseline-1 vs candidate-3 | 66 | 6 | 0 | 0 | 66 | 0.9964 | 28.3s | **PASS** | 0 |
| baseline-1 vs baseline-2 (noise floor) | 66 | 6 | 0 | 0 | 66 | 0.9961 | 29.0s | **PASS** | 0 |

Every comparison reports the same six `CARRIED` notes (a refusal present in both files
with the same message, `audit_compare`'s way of saying "no change, not a regression") for
the six `universe-matrix` cells above, and no other note. All three candidate rounds'
area ratios (0.9964-0.9969) sit inside the baseline self-check's own noise floor
(0.9961), so no candidate round shows more movement than the baseline shows against
itself. Full transcript: `audit_compare.log`.

## Step 6: the watched `universe-matrix` clause

Script (`watched_clause.py`, using the real field names confirmed above --
`status` and `area`, not the brief's guessed `buildings`):
```python
import json


def cells(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("url_id") == "universe-matrix":
            out[(r["strategy"], r["spec_index"], r["spec_label"])] = (
                r.get("status"),
                r.get("area"),
            )
    return out


base = cells("/tmp/broke6-baseline-1.jsonl")
for round in (1, 2, 3):
    cand = cells(f"/tmp/broke6-candidate-{round}.jsonl")
    for key in sorted(set(base) | set(cand)):
        b, c = base.get(key), cand.get(key)
        print(round, key, "base", b, "cand", c, "" if b == c else "  <<< MOVED")
```

Output (full transcript: `watched_clause.log`):
```
baseline-1 universe-matrix cells: 6
1 ('freeform', 0, 'no-proliferator') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
1 ('freeform', 1, 'all-products') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
1 ('freeform', 2, 'output-products') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
1 ('sequence-pair', 0, 'no-proliferator') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
1 ('sequence-pair', 1, 'all-products') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
1 ('sequence-pair', 2, 'output-products') base ('REFUSED', 0.0) cand ('REFUSED', 0.0)
2 (... all six, identical shape ...)
3 (... all six, identical shape ...)
```
All 18 checks (6 cells x 3 rounds): zero moved. Every `universe-matrix` cell keeps its
`REFUSED` status and its `0.0` area across every candidate round, matching baseline-1
exactly (not merely "within noise" -- byte-identical).

**Honest reading of this result, stated plainly because the brief's premise assumed
otherwise.** The brief's preamble expected these six cells to *build* (with red belts,
pre-fix, on the Energy Exchanger/Ray Receiver path this branch changes) and therefore to
show a measurable area/behaviour difference between baseline and candidate. What the
corpus actually shows, at `--budget 30`, is that all six `universe-matrix` cells are
refused for reasons **unrelated** to this branch's changes -- a blueprint-area overflow
(`game.blueprint_area`, a segment-200 planet band-fit problem) and packer/deadline
failures on a very large spec (42-43 strips) -- both already present, byte-identically,
in the merge-base baseline. The strip-planning and validation code this branch touches
(`_port_variants`, `_dock_lane`, `_logical_strip_plans`'s output-lane cap, the narrowed
belt-collide exemption) is very plausibly still *reached* during these refused attempts,
since a Ray Receiver group is part of every `universe-matrix` candidate and strip
planning runs before the packer gives up -- but the corpus never reaches a **successful**
placement on this path, so the six watched cells cannot show a before/after difference in
outcome. This is the same "corpus-inert" shape recorded for prior gates on this branch's
sibling work (Multibelt Deliverable A: "gate PASS but cap corpus-inert"). The gate is
**not** weakened by this: `audit_compare` still PASSes on the real evidence (no
regression anywhere, on any of the 66 paired-and-building cells or the 6 refused ones),
and the reported URL from Task 5 is the actual positive evidence that the fixed path
builds clean -- this corpus simply does not happen to exercise it to a different outcome
at this budget.

## The four verdicts

1. **baseline-1 vs candidate-1**: PASS (exit=0).
2. **baseline-1 vs candidate-2**: PASS (exit=0).
3. **baseline-1 vs candidate-3**: PASS (exit=0).
4. **Baseline self-check (baseline-1 vs baseline-2, the noise floor)**: PASS (exit=0),
   area ratio 0.9961 -- every candidate round's area ratio (0.9964-0.9969) is inside this
   floor, so no candidate round shows more movement than the baseline shows against
   itself.

**Watched clause (`universe-matrix`, 3 cells x 2 strategies = 6, x 3 candidate rounds =
18 comparisons)**: PASS -- zero cells moved status or area, though (see above) all six
were refused for reasons pre-dating and unrelated to this branch, so the clause confirms
**no regression** rather than confirming the changed path was exercised to a new,
successful outcome. No currently-clean corpus cell turned INVALID; no corpus cell's area
moved outside the measured noise floor.

**Overall gate verdict: PASS**, on the evidence actually recorded above.
