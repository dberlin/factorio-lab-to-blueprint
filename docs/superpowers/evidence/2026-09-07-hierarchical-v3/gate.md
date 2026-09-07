# Gate: hierarchical v3 on the large URLs

Branch `hierarchical-v3` at `bf081859` (the code HEAD every measurement below
is taken at). Merge base: master `1ce8a0d3`. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v3`.

Box: 128 cores, never idle, load is I/O wait. Every timed step has a
`-load.txt` beside it with `uptime` and one `vmstat 1 3` sample taken
immediately before the run. At most one layout build ran at a time from this
plan, and no two audits ever ran at once (`ps -eo args | grep -cE 'scripts/audit\.py'`
checked before each audit invocation; note that a plain `pgrep -f audit.py`
matches its OWN command line here and always returns a hit).

This is the successor to `../2026-09-07-hierarchical-v2/gate.md`, which it
supersedes. It gates seven tasks: Task 1 the stats carried into every refusal
and printed by the CLI (`d89b78e3`), Task 2 bounded and funded re-cut rounds
(`0bf58d3d`, `d5f2b4ad`), Task 3 one-arm dispatch from a routing-difficulty
feature key (`94c4edaf`, `69031212`, `f18502e7`), Task 4 the per-demand
reachability goal (`900afa1e`, `97ea65c5`, `ea65ab15`, `8362b22d`), Task 5 the
trunk-partner doorstep (`e91886fb`, `b9473715`, `a2ecd5b2`), Task 6 the
rung-by-rung oracle measurement (`6457e215`, `3067adfa`), Task 7 the corridor
spike killed at Step 0 (`bf081859`).

## 0. The rule, declared before the results

Written and committed before a single cell was run, and not amended
afterwards. Copied verbatim from `task-8-brief.md` Step 1:

> **PASS** if all four hold: (a) every cell that COMPOSES emits a blueprint
> whose `validate.certify` report has zero errors; (b) both malls compose —
> every block placed, the build reaching `compose`; (c) titanium-glass builds
> at `--budget 15`, emitting a blueprint; (d) the default-unchanged corpus
> guard has zero regressions — no cell CLEAN on the merge base and not CLEAN on
> the branch, 0 INVALID, 0 CRASH.
> **FAIL** otherwise, naming the clause AND the lever that failed (A
> funding/dispatch, B the oracle, C the corridor), and ranking the next three
> levers with the file:line and the number behind each, as v2's §6 did.

**The area clauses v2 carried are reported but NOT gating this time.** v2's
rule required belt3 ≤ 1.25 x 12408, zurl2 ≤ 1.0 x 40905 and titanium-glass
≤ 1.25 x 5727, and demonstrated none of them, because no cell emitted a
blueprint: all three came back "not demonstrated" rather than passed or
violated. A coverage gate that also fails on area cannot say which of the two
it failed on. So this gate gates coverage and time, and **reports
`area / best_known` for every cell that emits**, with no threshold attached.

Best-known dense areas for that column, as the controller supplied them
(`constraints.md`): belt3 all-products **12408**, zurl2 all-products **40905**,
titanium-glass all-products **5727** (sequence-pair, `best` at 30 s). The mall
has no best-known area.

The eight cells, the same as v2's, one candidate policy per run so each cell
gets the whole budget, `--band portable`, `-o`, and **no `--workers`** so the
strategy sees the `None` the CLI passes by default:

| cell | policy | budget |
| --- | --- | --- |
| belt3 | all-products | 60 |
| belt3 | no-proliferator | 60 |
| zurl2 | all-products | 60 |
| mall | all-products | 60 |
| mall | no-proliferator | 60 |
| titanium-glass | all-products | 60 |
| titanium-glass | all-products | 15 |
| belt3 | all-products | 15 |

Each is run TWICE. The corpus guard is one paired
`scripts/audit.py --budget 30 --json` round: the BASELINE half on the detached
merge base, the CANDIDATE half on this branch, compared with
`scripts/audit_compare.py`. **`audit.py` prints `NOT CLEAN` on any refusal, so
what is read is the CLEAN COUNTS and the NAMED DIFFERING CELLS, never the
banner.**
