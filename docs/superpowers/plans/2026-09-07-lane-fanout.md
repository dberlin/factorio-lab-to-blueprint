# Producer-lane fan-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a producer lane feed more consumer lanes than it has tiles, so the
six `universe-matrix` cells the `selfloop` merge lost can reach a blueprint
again.

**Architecture:** The refusal is a plan-time guard, `freeform._fanout_shortfall`,
whose model of a tap (one per lane TILE) is not the model the router uses (nets
sharing a source lane branch off each other's committed paths). The guard is
deleted at both its call sites. That exposes two further blockers the design
measured — a fixed CP-SAT deterministic work bound that produces no pack at all
for a 53-strip spec, and residual routing contention — which are staged as their
own tasks behind it.

**Tech Stack:** Python 3.12, `uv`, pytest, OR-Tools CP-SAT, Cython route kernel.

**Spec:** `docs/superpowers/specs/2026-09-07-lane-fanout-design.md`

## Global Constraints

- **The absolute ban on mixed input lanes stays.** No input lane ever carries two
  distinct items, not chosen and not forced (spec
  `2026-09-06-self-loop-recipes-design.md` §9 R1). Nothing in this plan
  reintroduces lane sharing, and the three dormant guards named in R1
  (`freeform._check_shared_lane_capacity`, `StripVariant.attachment_plan`'s
  per-item column assignment, `_input_stack`'s `default=1`) stay in the tree and
  stay dormant.
- **`belt.acyclic` is absolute.** No task adds a belt cycle.
- **No scans of `buildings` inside loops.** Use
  `flab2bp.layout.buildings.Buildings` from the `buildings-index` branch once it
  merges; until then a plain `dict` index built once outside the loop.
- **Serena is read-only in this repo right now** — it is a shared server and the
  last `activate_project` wins, so a concurrent agent's edits land in the wrong
  worktree. Read with Serena or grep, **edit with Read/Edit only**.
- **No interactive git.** Every commit uses `git commit -m` or `-F`; export
  `GIT_EDITOR=true` first. Never `git commit` bare, never `git rebase -i`,
  never `git add -i`.
- **The worktree must have its own venv.** Run `uv sync` in the worktree and
  confirm `uv run python -c "import flab2bp; print(flab2bp.__file__)"` prints a
  path inside the worktree before running any test. A worktree without it runs
  the tests against master.
- **One build at a time.** Five other agents build on this box. Never a
  `run_in_background` build; foreground with a bounded timeout.
- **CPU pressure is `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`**
  (mean runnable processes; fine below 64). Never load average. Record it beside
  every timing; never wait for it.
- **`pytest` prints no summary line on this box.** The exit code is the result.
  A 120 s `pytest-timeout` backstop hard-kills a run.
- **Known reds, not caused by this work, must stay red and must not be
  "fixed":** `test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
  `test_all_products_sequence_pair_honours_the_exact_layout_deadline`.
- **`scripts/audit.py` reports NOT CLEAN on any refusal**, so never read its
  single verdict word — compare cell counts and the named differing cells with
  `scripts/audit_compare.py`.

---

## File Structure

| file | responsibility in this plan |
|---|---|
| `src/flab2bp/layout/freeform.py` | delete `_fanout_shortfall` (19885-19937) and its raise (20517-20524); scale `_DETERMINISTIC_PACK_WORK` (365) by pack size |
| `src/flab2bp/layout/sequence_solver.py` | delete the second raise site (4973-4980) and the now-unused import |
| `tests/layout/test_freeform.py` | the fan-out regression tests, in `TestOneLaneCanServeSeveralDestinations` (class at 12902) beside `one_machine_fan_out_spec` (12863); the pack-work scaling tests |
| `tests/layout/test_sequence_solver.py` | the sequence-pair arm's matching plan-level test |
| `docs/superpowers/evidence/2026-09-07-lane-fanout/gate/` | the gate's measurements |

---

### Task 1: A one-machine producer with more consumers than tiles PLANS and LAYS OUT

The design's §3(e). `_fanout_shortfall` convicts a plan the router can wire
(spec §2, probe `p6`), so the refusal goes. This task is the whole fan-out fix.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:19885-19937` (delete `_fanout_shortfall`)
- Modify: `src/flab2bp/layout/freeform.py:20517-20524` (delete the raise)
- Modify: `src/flab2bp/layout/sequence_solver.py:4973-4980` (delete the raise)
- Test: `tests/layout/test_freeform.py` (in `TestOneLaneCanServeSeveralDestinations`, class at 12902)

**Interfaces:**
- Consumes: `one_machine_fan_out_spec(consumers: int = 4) -> BuildSpec`
  (`tests/layout/test_freeform.py:12863`), `plan_strips(spec, *, strip_len=6)`,
  `FreeformLayout(band_policy=..., workers=...).lay_out(spec, time_budget_s=...)`,
  `_full_report(placement, spec)`.
- Produces: nothing new. `_fanout_shortfall` ceases to exist; any later task or
  future reader looking for it should find §6 F2 of the spec instead.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_freeform.py`, inside
`class TestOneLaneCanServeSeveralDestinations` (line 12902), after
`test_the_merged_plan_lays_out_and_validates` (line 13008):

```python
    def test_a_lane_serves_more_consumers_than_it_has_tiles(self) -> None:
        """The tap count is not bound by the lane's tile count.

        `_fanout_shortfall` used to refuse here, on the theory that each
        consumer taps a different TILE of the producer lane.  The router does
        not do that: nets that share a source lane branch off each other's
        committed paths (`_route`'s `same_src` grouping), and `_tap_source`
        builds the splitter on that path.  Measured on `universe-matrix`: a
        10-tile lane wired all twelve of its consumers
        (spec 2026-09-07-lane-fanout-design.md section 2).
        """
        spec = one_machine_fan_out_spec(4)
        strips = plan_strips(spec, strip_len=6)
        producers = [s for s in strips if s.group_key.startswith("copper-ingot")]
        assert len(producers) == 1, "one machine cannot be split across shards"
        consumers = [s for s in strips if "copper-ingot" in s.in_lanes]
        assert len(consumers) > producers[0].width, (
            "this spec no longer exercises fan-out past the lane's tiles: "
            f"{len(consumers)} consumer lane(s) against a {producers[0].width}-tile lane"
        )
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(spec, time_budget_s=8.0)
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f.message for f in report.errors[:5])
```

If `one_machine_fan_out_spec(4)` does not by itself put more consumer lanes than
tiles on that producer, raise the `consumers` argument until it does — the
second assertion is there to say so out loud rather than let the test pass
vacuously. Do not weaken that assertion; a vacuous fan-out test is worse than no
test.

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd .claude/worktrees/lane-fanout && uv sync && \
  uv run python -c "import flab2bp; print(flab2bp.__file__)" && \
  uv run pytest tests/layout/test_freeform.py -k a_lane_serves_more_consumers -q; echo "exit=$?"
```

Expected: non-zero exit, with
`a producer lane has fewer tiles than the consumers it must tap` in the failure —
or, if the fixture does not reach the threshold, the second assertion firing.
Fix the fixture size, not the assertion, and re-run until the failure is the
refusal.

- [ ] **Step 3: Delete the guard at the freeform call site**

In `src/flab2bp/layout/freeform.py`, remove these eight lines (20517-20524):

```python
        shortfall = _fanout_shortfall(strips)
        if shortfall:
            raise NoValidLayout(
                "a producer lane has fewer tiles than the consumers it must tap, "
                "so two junctions would have to share one tile. " + "; ".join(shortfall[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )
```

- [ ] **Step 4: Delete the guard at the sequence-pair call site**

In `src/flab2bp/layout/sequence_solver.py`, remove the identical eight lines at
4973-4980, then remove `_fanout_shortfall` from the `from ...freeform import`
list at the top of the file. Run
`uv run ruff check src/flab2bp/layout/sequence_solver.py` to confirm no unused
import is left behind.

- [ ] **Step 5: Delete the function itself**

In `src/flab2bp/layout/freeform.py`, delete `def _fanout_shortfall` and its whole
body and docstring (19885-19937). Confirm nothing else refers to it:

```bash
grep -rn "_fanout_shortfall\|must tap" src/ tests/; echo "exit=$?"
```

Expected: no matches (exit 1 from grep).

- [ ] **Step 6: Record why, where the next reader will look**

Add to the `Strip.drain_outermost` docstring in
`src/flab2bp/layout/freeform.py` (the sentence at 979-981 that reads
"That cap is why ``universe-matrix`` refuses today -- 15 one-machine strips
out-fan the ``antimatter`` producer's lane"), replacing that sentence with:

```python
    #: That cap turns ``universe-matrix#37`` into 15 one-machine strips.  It used
    #: to refuse there, on ``_fanout_shortfall``'s theory that each consumer taps
    #: a different TILE of the producer lane; that theory was measured wrong --
    #: nets sharing a source lane branch off each other's committed paths
    #: (``_route``'s ``same_src``), and a 10-tile lane wired all twelve of its
    #: consumers.  See ``docs/superpowers/specs/2026-09-07-lane-fanout-design.md``
    #: section 2, and section 4 for the two blockers behind it.
```

- [ ] **Step 7: Run the new test and the file's suite**

```bash
uv run pytest tests/layout/test_freeform.py -k a_lane_serves_more_consumers -q; echo "exit=$?"
uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q; echo "exit=$?"
```

Expected: the first exits 0. The second exits 0 except for the two known reds
listed in Global Constraints; if any other test fails, it is this task's
regression and must be fixed here, not deferred.

- [ ] **Step 8: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py \
        tests/layout/test_freeform.py
git commit -m "layout: a producer lane may serve more consumers than it has tiles

_fanout_shortfall refused plans the router can wire.  Its model -- one tap per
lane TILE -- is not the router's: nets sharing a source lane branch off each
other's committed paths.  Measured: a 10-tile universe-matrix lane wired all
twelve of its consumers.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 2: Control — the corpus does not move when the guard goes

The guard fires on exactly three of thirty-six corpus specs (spec §1.2), all
`universe-matrix`. This task proves the other thirty-three are untouched, before
anything else changes.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-lane-fanout/gate/control-task2.md`
- Test: none — this is a measured control, not a unit test

**Interfaces:**
- Consumes: `scripts/audit.py --json`, `scripts/audit_compare.py`
- Produces: `gate/audit-baseline.jsonl` (master `a1401518`) reused by Task 5.

- [ ] **Step 1: Record CPU pressure and run the baseline arm on master**

From a clean checkout of master `a1401518` (a second worktree, `uv sync`'d,
`flab2bp.__file__` verified):

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
uv run python scripts/audit.py --tier stress --budget 30 --strategy both \
  --json gate/audit-baseline.jsonl 2>&1 | tee gate/audit-baseline.log
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
```

Expected: 72 cells. Ignore the final verdict word.

- [ ] **Step 2: Run the candidate arm at Task 1's HEAD**

Same command in the `lane-fanout` worktree, writing
`gate/audit-task2.jsonl` / `gate/audit-task2.log`. One build at a time: do not
run this while step 1 is running.

- [ ] **Step 3: Compare**

```bash
uv run python scripts/audit_compare.py gate/audit-baseline.jsonl gate/audit-task2.jsonl \
  2>&1 | tee gate/audit-compare-task2.txt
uv run python scripts/audit_compare.py gate/audit-baseline.jsonl gate/audit-task2.jsonl \
  --regressions-only 2>&1 | tee gate/audit-compare-task2-regressions.txt
```

- [ ] **Step 4: Write the control down**

In `gate/control-task2.md` record, as measured numbers and not as a verdict:
the clean / refused / invalid / crashed counts for both arms, the paired cell
count, the geomean area ratio, the p95 wall, both CPU pressure readings, and the
full list of cells whose status changed in either direction.

The control PASSES when: no cell that was CLEAN on master is not CLEAN here, and
no cell outside `universe-matrix` changed status at all. `universe-matrix` is
still expected REFUSED — Task 1 removes the fan-out refusal, and spec §4 says
two blockers remain behind it. Its refusal MESSAGE must have changed, and the
new message must be recorded verbatim; if it still says "must tap", Task 1 did
not land.

The control FAILS if any other cell moved, or if p95 wall rose by more than the
1.3 % same-arm noise this repo uses — a spec that used to refuse in
milliseconds now burns a full sweep, and that cost is exactly what spec §3(e)
said to measure.

- [ ] **Step 5: Commit**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-lane-fanout/gate/
git commit -m "evidence(lane-fanout): the corpus does not move when the fan-out guard goes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 3: The pack's deterministic work bound scales with the pack

Spec §4.1. `_DETERMINISTIC_PACK_WORK = 0.02` is a fixed constant applied to
every pack of 15 strips or more, and its own comment says it was calibrated on a
fifteen-strip cell. A 53-strip pack gets the same 0.02 units, returns UNKNOWN
five times out of five, and the sweep stale-stops in 2.58 s with 299 s of a
300 s budget unspent (probe `p2`).

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:359-365` (the constant and its comment)
- Modify: `src/flab2bp/layout/freeform.py:5178` and `:5331` (the two
  `max_deterministic_time` assignments that read it)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_DETERMINISTIC_PACK_STRIPS = 15` (`freeform.py:354`).
- Produces: `_deterministic_pack_work(strip_count: int) -> float` — the work
  bound for a pack of `strip_count` strips. Task 4 and Task 5 call nothing from
  this task; the constant's callers are internal to `_pack`.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_freeform.py`, in the class that already covers packing
constants (find it with
`grep -n "_DETERMINISTIC_PACK_WORK\|_DETERMINISTIC_PACK_STRIPS" tests/layout/test_freeform.py`;
if there is none, add a new `class TestThePackWorkBoundScalesWithThePack:` next
to the other pack tests):

```python
class TestThePackWorkBoundScalesWithThePack:
    """A 53-strip pack cannot have the same work bound as a 15-strip one.

    Measured on `universe-matrix` (spec 2026-09-07-lane-fanout-design.md
    section 4.1): at the fixed 0.02 units the 53-strip pack returned UNKNOWN
    five solves out of five and produced no incumbent at all, giving up in
    2.58s with 299s of a 300s budget unspent.
    """

    def test_the_calibrated_size_keeps_its_calibrated_bound(self) -> None:
        assert _deterministic_pack_work(_DETERMINISTIC_PACK_STRIPS) == 0.02

    def test_a_smaller_pack_is_not_given_more_work(self) -> None:
        assert _deterministic_pack_work(4) <= 0.02

    def test_a_much_larger_pack_is_given_proportionally_more(self) -> None:
        small = _deterministic_pack_work(_DETERMINISTIC_PACK_STRIPS)
        large = _deterministic_pack_work(53)
        assert large > small, "a 53-strip pack must get more work than a 15-strip one"
        assert large / small >= 53 / _DETERMINISTIC_PACK_STRIPS, (
            "the bound must grow at least linearly in the strip count: a pack's "
            "CP-SAT model grows at least that fast"
        )
```

Import `_deterministic_pack_work` and `_DETERMINISTIC_PACK_STRIPS` from
`flab2bp.layout.freeform` at the top of the test file alongside the other
private imports.

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/layout/test_freeform.py -k ThePackWorkBoundScales -q; echo "exit=$?"
```

Expected: non-zero, `ImportError: cannot import name '_deterministic_pack_work'`.

- [ ] **Step 3: Write the minimal implementation**

Replace `_DETERMINISTIC_PACK_WORK = 0.02` at `freeform.py:365` with a function,
keeping the existing comment block above it and appending the new sentence:

```python
#: Fixed CP-SAT work for reproducible large-pack incumbents.  A wall-clock
#: cutoff still raced at one worker: the authoritative fifteen-strip cell
#: alternated between a clean width-48 packing and a width-47 packing whose
#: routing failed exact validation.  0.02 deterministic units reaches the same
#: routable incumbent well inside its 0.6s wall allowance; 0.005 stopped before
#: that incumbent existed.  The wall limit remains armed as the hard deadline.
#:
#: IT SCALES WITH THE PACK, and the fixed constant was a defect.  0.02 was
#: calibrated on fifteen strips and was handed unchanged to a 53-strip
#: `universe-matrix` pack, which returned UNKNOWN on all five solves and
#: produced no incumbent at all -- giving up in 2.58s with 299s of a 300s
#: budget unspent.  See docs/superpowers/specs/2026-09-07-lane-fanout-design.md
#: section 4.1.
_DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE = 0.02


def _deterministic_pack_work(strip_count: int) -> float:
    """Deterministic CP-SAT units a pack of ``strip_count`` strips may spend."""
    scale = max(1, strip_count) / _DETERMINISTIC_PACK_STRIPS
    return _DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE * scale
```

Plain linear scaling in the strip count, anchored so that a pack of exactly
`_DETERMINISTIC_PACK_STRIPS` strips gets the calibrated 0.02 units and nothing
about the fifteen-strip cell changes. Step 5 measures whether the downward half
of that line is safe.

Then update the two call sites. At `freeform.py:5178`:

```python
    solver.parameters.max_deterministic_time = min(time_budget_s, deterministic_work)
```

and `freeform.py:5331`, whichever passes `_DETERMINISTIC_PACK_WORK` down: trace
`deterministic_work` back to where it is assigned from the constant
(`grep -n "_DETERMINISTIC_PACK_WORK" src/flab2bp/layout/freeform.py`) and change
that assignment to `_deterministic_pack_work(len(strips))`, using whatever the
strip sequence is called in that scope. Do not change the `min(time_budget_s, …)`
clamps: the wall limit stays armed as the hard deadline, exactly as the comment
says.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -k ThePackWorkBoundScales -q; echo "exit=$?"
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
```

Expected: the first exits 0; the second exits 0 apart from the two known reds.

- [ ] **Step 5: Measure the cost on a small cell before believing it**

The bound now shrinks for packs under fifteen strips. That is a change to every
small corpus cell, so measure it directly rather than assume it is free:

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
uv run python scripts/audit.py --tier small --budget 30 --strategy both \
  --json gate/audit-task3-small.jsonl 2>&1 | tee gate/audit-task3-small.log
```

If any small cell that was CLEAN is no longer CLEAN, the downward scaling is
wrong: change `_deterministic_pack_work` to floor at the calibrated constant

```python
    return max(0.02, 0.02 * max(1, strip_count) / _DETERMINISTIC_PACK_STRIPS)
```

update `test_a_smaller_pack_is_not_given_more_work` to assert equality at 0.02
for small packs, and re-run. Record which of the two you shipped and the
measurement that decided it in the commit message.

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py \
        docs/superpowers/evidence/2026-09-07-lane-fanout/gate/
git commit -m "pack: scale the deterministic work bound with the pack's strip count

0.02 units was calibrated on a fifteen-strip cell and handed unchanged to a
53-strip pack, which returned UNKNOWN on all five solves and produced no
incumbent -- 2.58s spent of a 300s budget.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 4: Measure what is left, and say so

Spec §4.2 and §4.3. After Tasks 1 and 3 the `universe-matrix` refusal has moved
twice. This task measures where it now stands, on both placers, and writes the
answer down. It changes no source.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-lane-fanout/gate/residual.md`
- Create: `docs/superpowers/evidence/2026-09-07-lane-fanout/gate/build-um-*.log`

**Interfaces:**
- Consumes: the branch HEAD after Task 3.
- Produces: the ranked residual-blocker list the gate's reading section quotes.

- [ ] **Step 1: Build the refusing cell on both arms at the gate's budget**

One at a time, foreground, recording CPU pressure either side of each:

```bash
UM='https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11'
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
/usr/bin/time -v uv run flab2bp "$UM" --budget 30 -v -o gate/bp-um-b30.txt \
  > gate/build-um-b30.log 2> gate/build-um-b30.err; echo "exit=$?"
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
```

- [ ] **Step 2: Build it at a budget that is not the constraint**

```bash
/usr/bin/time -v uv run flab2bp "$UM" --budget 300 --strategy freeform -v \
  -o gate/bp-um-b300-freeform.txt > gate/build-um-b300-freeform.log \
  2> gate/build-um-b300-freeform.err; echo "exit=$?"
/usr/bin/time -v uv run flab2bp "$UM" --budget 300 --strategy sequence-pair -v \
  -o gate/bp-um-b300-seqpair.txt > gate/build-um-b300-seqpair.log \
  2> gate/build-um-b300-seqpair.err; echo "exit=$?"
```

The point of the 300 s arm is to separate "needs a longer clock" from "a longer
clock would not have wired this spec" — the refusal text says which, verbatim,
and that sentence is the finding.

- [ ] **Step 3: If it builds, check what it built**

Only if step 1 or 2 produced a blueprint:

```bash
uv run python -m flab2bp.decode gate/bp-um-b300-freeform.txt > gate/decode-um.txt
grep -c SHARED-INPUT-RUN gate/decode-um.txt
```

Expected `0`. A non-zero count means the absolute ban was violated and this task
stops and reports it as the finding; do not proceed to the gate.

- [ ] **Step 4: Write `gate/residual.md`**

Record, as measurements: each arm's exit code, wall, CPU percent, CPU pressure
before and after, and the refusal text verbatim. Then rank what is left, one
line each, each line naming the file:line or the refusal clause it rests on. Do
not net anything, do not predict, and do not describe a blocker you did not
measure this round.

State plainly whether the brief's PASS condition (all six cells CLEAN at
`--budget 30`) is met, not met, or met on one arm only. Spec §4.3 says the
honest expectation is "not met"; if the measurement disagrees with the spec, the
measurement wins and the spec gets a correction note appended in the same commit.

- [ ] **Step 5: Commit**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-lane-fanout/gate/
git commit -m "evidence(lane-fanout): what is left after the guard and the pack bound

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 5: The gate — two rounds, both placers, at the branch's final HEAD

Last task. Runs at whatever HEAD the branch ends on, after every other task has
landed and been reviewed. Certifies the arbiter; no player hand-back.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-lane-fanout/gate/verdict.md`
- Modify: `README.md` (`## Gate result`)

**Interfaces:**
- Consumes: `gate/audit-baseline.jsonl` from Task 2 (master `a1401518`); if the
  branch has moved on since, re-run the baseline arm at master's then-current
  HEAD and say which commit it was.

- [ ] **Step 1: Confirm the worktree is the tree under test**

```bash
cd .claude/worktrees/lane-fanout && uv sync && \
  uv run python -c "import flab2bp; print(flab2bp.__file__)"
git rev-parse HEAD
git status --short
```

Expected: a path inside `.claude/worktrees/lane-fanout`, and a clean tree. A
dirty tree invalidates the gate.

- [ ] **Step 2: Round 1 — the full suite**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
uv run pytest -q 2>&1 | tail -40 > gate/pytest-round1.log; echo "exit=$?"
```

Expected: the only failures are the two known reds from Global Constraints.
Record their names verbatim. Any third failure fails the gate.

- [ ] **Step 3: Round 1 — the paired corpus round**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
uv run python scripts/audit.py --tier stress --budget 30 --strategy both \
  --json gate/audit-candidate-r1.jsonl 2>&1 | tee gate/audit-candidate-r1.log
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_pressure", sum/5}'
uv run python scripts/audit_compare.py gate/audit-baseline.jsonl \
  gate/audit-candidate-r1.jsonl 2>&1 | tee gate/audit-compare-r1.txt
uv run python scripts/audit_compare.py gate/audit-baseline.jsonl \
  gate/audit-candidate-r1.jsonl --regressions-only 2>&1 \
  | tee gate/audit-compare-r1-regressions.txt
```

- [ ] **Step 4: Round 2 — the same corpus round again**

Identical command, into `gate/audit-candidate-r2.jsonl`. Two rounds because a
budget-limited search varies between runs, and one round cannot tell a
regression from a draw. One build at a time: round 2 starts after round 1 exits.

- [ ] **Step 5: Name the six cells explicitly**

The six cells this work exists for are, on both placers:

- `universe-matrix / no-proliferator`
- `universe-matrix / all-products`
- `universe-matrix / output-products`

Report each one's status in both rounds and on both arms, in a six-row table,
with its refusal text verbatim when it is not CLEAN. Do not summarise them into
a count.

- [ ] **Step 6: Write `gate/verdict.md`**

Every number measured on this box, this day, in this worktree. Nothing
predicted, estimated, or rounded toward a better answer. It must carry:

- the branch SHA and the baseline SHA;
- CPU pressure before and after every timed command;
- the `audit_compare` verdict line verbatim for both rounds, and every
  `FAIL REFUSED:` / `FAIL REGRESSION:` line;
- per arm: CLEAN / REFUSED / INVALID counts for baseline and candidate, the
  cells CLEAN → not CLEAN and not CLEAN → CLEAN in each direction, the geomean
  area ratio over cells clean in both, and p50/p95 wall;
- the six-row `universe-matrix` table from step 5;
- the two known reds, named, with the statement that they are pre-existing;
- a reading section that states the PASS condition, states whether it was met,
  and if not, which of the three blockers in spec §4.3 is the one still standing,
  quoted from `gate/residual.md` or from this round's own refusal text.

PASS is: all six `universe-matrix` cells CLEAN in both rounds and both arms,
every lane single-item, 72/72 paired against master with zero regressions. Say
FAIL if that is not what was measured. Spec §4.3 expects a FAIL on coverage;
that expectation does not license softening the verdict, and it does not license
declaring FAIL without running the rounds either.

- [ ] **Step 7: Append the gate result to the README**

Under `## Gate result` in `README.md`, one paragraph: the date, the branch, the
verdict word, the coverage count, the area ratio, and a pointer to
`docs/superpowers/evidence/2026-09-07-lane-fanout/gate/verdict.md`.

- [ ] **Step 8: Commit**

```bash
export GIT_EDITOR=true
git add docs/superpowers/evidence/2026-09-07-lane-fanout/gate/ README.md
git commit -m "gate(lane-fanout): two rounds, both placers, six universe-matrix cells

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

## Self-review

**Spec coverage.** §1 and §2 (the refusal and why its model is wrong) → Task 1.
§1.2 (corpus reach) → Task 2. §3(a), §3(b), §3(c), §3(d) are rejected levers and
need no task; they are recorded in the spec's §6 F2/F3 so they are not
re-proposed. §3(e) → Task 1. §4.1 → Task 3. §4.2 and §4.3 → Task 4. §5 scope
(both arms, one predicate) → Task 1 steps 3-5. §6 F4 (the bound is calibrated by
measurement) → Task 3 step 5. The gate → Task 5.

**No task for §4.2's fixes.** Deliberate, and it is the plan's one open edge:
the residual `titanium-ingot static-access` net and sequence-pair's exact-layout
deadline have no measured fix in hand, so Task 4 measures and ranks them rather
than a task pretending to fix them. Inventing a task for an undiagnosed failure
is how a plan acquires a placeholder.

**Placeholders.** None. Every code step carries the code. Task 3 step 3 offers
two forms and Task 3 step 5 says which measurement chooses between them, which
is a decision procedure rather than a TODO.

**Type consistency.** `_deterministic_pack_work(strip_count: int) -> float` and
`_DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE` are used with those exact names in
Task 3's steps 1, 3 and 5. `_fanout_shortfall` appears only as something being
deleted, and Task 1 step 5 greps to prove no reference survives.
