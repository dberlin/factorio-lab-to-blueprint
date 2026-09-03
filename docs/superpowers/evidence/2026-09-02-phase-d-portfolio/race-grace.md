# The measured race completion grace

`RACE_COMPLETION_GRACE_S` (`src/flab2bp/layout/strategy_race.py`) is the number
of seconds past the soft deadline the parent waits before killing a racer. Spec
§5.2 requires it to be **measured, not guessed**:

```
RACE_COMPLETION_GRACE_S = ceil(worst spawn-to-first-instruction) + ATOMIC_COMPLETION_GRACE_S
```

A child pays two costs the serial path does not: spawn plus interpreter start
plus unpickling the `BuildSpec` before its first instruction, and its own atomic
completion after the wall. That second cost is `base.ATOMIC_COMPLETION_GRACE_S`
(5.0). The first is what is measured here.

## Method

`scripts/spawn_cost.py`, run as `uv run python scripts/spawn_cost.py`. Ten
independent `ProcessPoolExecutor`s from the **spawn** context with
`max_tasks_per_child=1` — the same pool shape `run_strategy_race` builds. The
parent records `time.monotonic()` immediately before `submit`; the first thing
the child does is read `time.monotonic()` again and return the difference. That
is legitimate because Linux `CLOCK_MONOTONIC` is system-wide, which is the same
property `sequence_islands` already relies on when it hands a child an absolute
deadline.

The script deliberately does **not** import `flab2bp`, so what it times is the
interpreter start alone; the `BuildSpec` unpickle a real racer also pays is
charged on top and is covered by rounding the worst case up to a whole second.

The measurement cannot be run from a heredoc: under `spawn` the child re-imports
`__main__` by path, and a script fed on stdin has `__file__ == "<stdin>"`, so
the pool fails before it measures anything. Hence a file in `scripts/`.

## Box load at the time of measurement

Per Ruling R the box is never idle and its load is disk I/O; the load is
recorded rather than waited out. (`vmstat`'s first row is a since-boot average.)

```
 05:30:52 up 18 days, 11:16,  8 users,  load average: 3.96, 4.09, 5.25
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 1036464844  0 8341920   0    0 50706 15351 23522   4  5  2 93  0  0  0
 2  0      0 1036469568  0 8341924   0    0    16 23448 15524 37672 1 1 98  0  0  0
 4  0      0 1036470260  0 8341924   0    0     0   372 12514 25300 1 1 98  0  0  0
```

## Result

Ten spawns, sorted, seconds:

| # | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cost | 0.098 | 0.098 | 0.099 | 0.099 | 0.099 | 0.099 | 0.100 | 0.100 | 0.101 | 0.101 |

| min | median | **max (worst case)** |
| --- | --- | --- |
| 0.098 s | 0.099 s | **0.101 s** |

```
RACE_COMPLETION_GRACE_S = ceil(0.101) + 5.0 = 1 + 5.0 = 6.0
```

Raw script output: `spawn-cost.txt` in this directory.

**The measured value is 6.0**, which is what Task 8 had written into the
constant as a placeholder. The constant is therefore left at `6.0` — now as a
measurement rather than a guess — and its comment says so.

## R1 lint check (Ruling AI)

Any timing constant in `flab2bp.layout` whose value collides with a linted game
value must be declared as a `registry.LintException`, never re-spelled around
the lint. Checked directly against `flab2bp.dsp.provenance.linted_values()`
(66 needles):

| value | in `linted_values()` |
| --- | --- |
| 6.0 (`RACE_COMPLETION_GRACE_S`) | no |
| 1.0 (`ceil(max)`) | no |
| 5.0 (`ATOMIC_COMPLETION_GRACE_S`) | no |

No collision, so **no `LintException` is declared for this constant**. (30.0
*is* a linted value — `rules.SKEW_PAIR_DEG` — which is why the check is run at
all; no 30.0 is written into this module.)

## The grace in use: one real cell through the real pool

`run_strategy_race` on the corpus cell `iron-ingot` (first candidate),
`time_budget_s=10.0`, `workers=8`, sharing on, through the real spawn-context
`ProcessPoolExecutor` — not the test seam:

```
freeform      completed  area 63  dropped 0
sequence-pair completed  area 63  dropped 0
wall 2.25s
```

Both arms finished well inside the soft deadline, so the grace was never spent;
what this shows is that the pool starts, the request pickles, both children run
a whole strategy on the parent's wall, both outcomes pickle back, and the queues
close without holding the parent open.

## What this number is not

It is deliberately not `sequence_islands._ISLAND_COMPLETION_GRACE_S`'s 90.0: a
grace that large is a second budget. And the spawn cost is *inside* the wall,
not added to it — a child that spends 0.1 s starting has 0.1 s less search than
the serial arm had. That is a real cost of racing, named in the spec's Risks.
