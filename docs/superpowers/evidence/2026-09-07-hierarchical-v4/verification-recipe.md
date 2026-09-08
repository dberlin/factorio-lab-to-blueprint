# Recovery handoff: exact verification recipe (not executed)

Run only under Main's single-build/single-audit orchestration after all concurrent
edits settle. Working directory throughout is the existing `hierarchical-v4`
worktree. No worker executed the commands below. Do not treat this as `gate.md`
or as measurement evidence.

```bash
export GIT_EDITOR=true
E=docs/superpowers/evidence/2026-09-07-hierarchical-v4
V3=docs/superpowers/evidence/2026-09-07-hierarchical-v3
```

## 1. Task 8 live diagnosis and proof

```bash
uv run pytest tests/layout/test_freeform.py::test_lay_out_bounds_a_routed_refusal_to_the_recurring_net tests/layout/test_freeform.py::test_routing_clock_evidence_cannot_convict_geometry tests/layout/test_freeform.py::test_different_logical_failures_bound_the_searched_space_not_one_net -x
uv run pytest tests/layout/test_freeform.py::test_the_mall_block_the_packer_convicted_is_placed_or_names_the_cause -x
MALL=$(cat "$E/mall-url.txt")
REPLAY=$(mktemp -d "$E/block-20-b60-replay.XXXXXX")
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' > "$REPLAY/load.txt"
uv run python "$E/block_probe.py" "$REPLAY/result.json" "$MALL" 60 "$E/block-20-hierarchy-capture-r1.json" > "$REPLAY/run.log" 2>&1
```

Each invocation allocates a fresh replay directory. Preserve the archived
`block-20-b60-r2.json` and `.log`: they are the specific 5.329457-second
measurement cited in `packer-defect.md`, and their runnable load was not recorded.
New results and load samples belong only to their newly allocated directory.

The exact recut fixture is already captured by Main in
`block-20-hierarchy-capture-r1.json`; its round-2 allocated budget is
10.12666118494235 s. The first `block-20-b60-r1.log` records a pre-layout fixture
error and must not be overwritten or called a solver refusal. Record logical
failure intersection, per-height kinds, stranded ports and skipped heights. If
60 s succeeds, repeat the same command with budget10.12666118494235 and a fresh
output stem. If the regression returns an
existing deadline/port-seating refusal rather than the proposed routed bound,
that is new diagnosis evidence, not permission to loosen it to accept any error.
Reconcile the bound/test before claiming Task 8 complete.

Main's once-at-end suite/check commands inherited from Task 8:

```bash
uv run pytest tests/layout/test_freeform.py -x
uv run pytest tests/layout/hierarchy/ -x
uv run ruff check
uv run ruff format --check
uv run mypy src
```

Inherited unrelated red sequence-alignment failures must be reported, not silently
fixed or suppressed. The pre-fix deadline ceiling was deliberately remeasured in
Task 6: budget 1.0, ceiling 1.25. Do not restore an older timing assertion.

## 2. Prepare the inherited gate scripts before measurement

This copies the established harness rather than inventing a second measurement
convention. `run_cell.py` and `judge.py` remain byte-identical to v3. The guard's
baseline is pinned to `1d2a790c` because master moved. The extra rounds select only
titanium@60; r1/r2 still execute exactly the original eight cells.

```bash
python - <<'PY'
from pathlib import Path
import shutil
v3 = Path('docs/superpowers/evidence/2026-09-07-hierarchical-v3')
v4 = Path('docs/superpowers/evidence/2026-09-07-hierarchical-v4')
for name in ('run_cell.py', 'judge.py'):
    shutil.copyfile(v3 / name, v4 / name)
text = (v3 / 'run_large.sh').read_text().replace('hierarchical-v3', 'hierarchical-v4')
needle = 'run belt3          "$BELT3"    all-products    60\n'
assert text.count(needle) == 1
extra = '''if [ "$R" = "3" ] || [ "$R" = "4" ]; then
  run titanium-glass "$TITANIUM" all-products 60
  exit 0
fi
'''
(v4 / 'run_large.sh').write_text(text.replace(needle, extra + needle))
text = (v3 / 'run_guard.sh').read_text()
text = text.replace('hierarchical-v3', 'hierarchical-v4').replace('BASE=1ce8a0d3', 'BASE=1d2a790c')
text = text.replace('TMP=/tmp/v3gate', 'TMP=$(mktemp -d /tmp/v4gate.XXXXXX)')
(v4 / 'run_guard.sh').write_text(text)
PY
```

The original guard prints `pgrep -af '[s]cripts/audit\.py'` matching lines next to
the count, waits for an empty audit slot before each half, samples five runnable
seconds (records, never waits for low load), and restores the branch on exit.
It uses the SAME worktree detached at the pinned baseline; no stash/second
worktree. Run a `/tmp` copy so checkout cannot remove the executing script.
The script removes its named JSONL because `--json` APPENDS; use fresh phase
paths and preserve existing evidence before any rerun. Confirm 72 distinct rows,
not just the audit exit banner, after each half.

### Task 8 mandatory own guard, before final review

Commit the implementation and harness first, excluding `.superpowers`. Tree must
be clean. This invocation keeps the Task 8 guard separate from Task 9's final gate.

```bash
ROOT=$PWD
TASK8_SCRIPT=$(mktemp /tmp/v4-task8-guard.XXXXXX.sh)
python - "$E/run_guard.sh" "$TASK8_SCRIPT" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
source = source.replace('DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v4\n', 'DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v4/task8-guard\n')
source = source.replace('"$DIR/judge.py"', '"$DIR/../judge.py"')
Path(sys.argv[2]).write_text(source)
PY
bash "$TASK8_SCRIPT" "$ROOT"
```

Read counts and every named differing cell from `task8-guard/judge-round1.txt`,
not `NOT CLEAN`/wall-gate banners. For every status movement run that exact URL,
policy and strategy on BOTH pinned trees and record both values before judging
regression. Zero CLEAN→not-CLEAN, 0 INVALID and 0 CRASH are required. This guard is
unconditional even if Task 8 resolves to only a message bound (T1-A). A geometric
fix that regresses must be withdrawn in favor of the evidence-backed bound;
message-only regressions still require explanation and controls, not waiver.

## 3. Review and freeze prerequisites

- Task 7 `3d5aba53..dd507484` independent re-review is already PASS/PASS; do not
  repeat it as a substitute for Task 8 review.
- Finish Task 8 diagnosis, its guard, tests and independent review.
- Run the inherited final whole-branch independent review BEFORE Task 9 (P1).
  At most one final fix wave and one scoped re-review before the first gate cell.
- All source/tests, fixes, review responses and pre-gate documents must be committed.
- Write Task 9 `gate.md` §0 with the **verbatim** PASS/FAIL rule in
  `task-9-brief.md` lines 24–25 / the approved plan's Task 9; commit §0 ALONE before
  any Task 9 measurement. No result sections yet.
- Clause (a) is existential, unchanged. G2 requires FOUR titanium@60 rounds and an
  explicit reliability fraction, including refusals; do not reroll failures away.
- Area is report-only: belt3 12408, zurl2 40905, titanium 5727, mall no baseline.
  Wall budget+6.0 is report-only. Both malls must compose; titanium@15 must emit;
  other composing refusals must name Lever 1/2/3 under the original rule.
- Record the actual frozen commit after the rule-only commit in the §0 evidence
  record. No source/test mutations after the first cell; affected cells rerun if
  that changes. Task 9 review is documentation-only (P2), not another code wave.

## 4. Task 9 eight cells twice, plus inherited G2 titanium rounds

```bash
git rev-parse HEAD > "$E/gate-measured-head.txt"
bash "$E/run_large.sh" 1
bash "$E/run_large.sh" 2
bash "$E/run_large.sh" 3
bash "$E/run_large.sh" 4
```

The eight r1/r2 cells are, in order: belt3/all@60, belt3/no-proliferator@60,
zurl2/all@60, mall/all@60, mall/no-proliferator@60, titanium/all@60,
titanium/all@15, belt3/all@15. No `--workers`. Each uses the unchanged CLI,
`--strategy hierarchical --band portable --candidate-policy <policy> -o`,
whole stats line, in-process wall, shell wall and immediately preceding load.
Do not run any of these builds concurrently.

Certify every emitted cell independently with the existing probe and exactly its
recorded argv. The probe rebuilds; it does NOT decode/certify the earlier file.
Preserve both original and rebuilt outputs and refusals, and don't substitute a
successful rebuild for a failed measured round. This command creates distinct
certification output stems and records their own load and shell wall:

```bash
python - <<'PY'
from pathlib import Path
import json, subprocess, time
root = Path('docs/superpowers/evidence/2026-09-07-hierarchical-v4')
for path in sorted(root.glob('large-*-r[1234].json')):
    record = json.loads(path.read_text())
    argv = list(record['argv'])
    output_index = argv.index('-o') + 1
    if not Path(argv[output_index]).is_file():
        continue
    stem = path.with_suffix('')
    cert = Path(str(stem) + '-certify')
    argv[output_index] = str(cert) + '.blueprint.txt'
    samples = subprocess.check_output(['vmstat', '1', '6'], text=True).splitlines()[-5:]
    mean = sum(int(line.split()[0]) for line in samples) / 5
    Path(str(cert) + '-load.txt').write_text(f'runnable_5s_mean={mean}\n')
    started = time.monotonic()
    with Path(str(cert) + '.log').open('w') as log:
        result = subprocess.run(['uv', 'run', 'python', str(root / 'certify_probe.py'), str(cert) + '.json', '--', *argv], stdout=log, stderr=subprocess.STDOUT)
    Path(str(cert) + '.shellwall.txt').write_text(f'exit={result.returncode}\nwall_s={time.monotonic()-started}\n')
PY
```

Record full errors_by_check, buildings, area, and tower/splitter census from
certifications. A CLI file alone does not establish the certify clause. Retain
both rounds' values (r1 with differing r2 parenthesized) and all four titanium
outcomes. Carry Task 7's one-of-four starvation residual without new heuristics.

## 5. Task 9 final guard and reporting

Commit measurement artifacts without source/test changes so the guard starts
clean. The declared measured source/test tree must remain unchanged. Run the
fresh final-head guard separately from Task 8:

```bash
ROOT=$PWD
GATE_SCRIPT=$(mktemp /tmp/v4-final-guard.XXXXXX.sh)
cp "$E/run_guard.sh" "$GATE_SCRIPT"
bash "$GATE_SCRIPT" "$ROOT"
git rev-parse HEAD
git diff --no-ext-diff --stat "$(cat "$E/gate-measured-head.txt")" HEAD -- src tests
```

Final source/test diff must be empty. Populate gate §§1–8.1 in the approved order,
including rule-by-rule verdict, both-round stats/refusals, all three lever
comparisons, paired counts/controls, ranked next three levers with current
file:line and measured count, residuals, as-shipped constants, files and provenance.
`reservation_partial`, `power_infill_towers` and `power_uncovered_tiles` must be
included; missing fields are missing, never zero. Area/timing stay report-only.
Update the backlog only for demonstrated closures; keep cache/outcome-driven cap
and the previously rejected bus corridor residuals. No gate verdict is knowable
until these observations exist. Independent final documentation review does not
mark missing measurements complete.
