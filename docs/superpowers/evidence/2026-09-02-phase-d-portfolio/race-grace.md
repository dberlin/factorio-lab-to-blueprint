# The measured race completion grace

`RACE_COMPLETION_GRACE_S` (`src/flab2bp/layout/strategy_race.py`) is how long
past the soft deadline the parent's single `wait` runs before it kills a racer.
Spec §5.2 requires it to be **measured, not guessed**, and Ruling AL fixes
*which span* is measured:

```
RACE_COMPLETION_GRACE_S = ceil(post-deadline tail) + ATOMIC_COMPLETION_GRACE_S
```

## Which span, and why it is not the spawn cost

Two different costs, only one of which the grace has to cover.

**Spawn-to-first-instruction is INSIDE the wall.** The parent starts the clock
and hands the child an *absolute* deadline, so whatever the child spends
spawning, starting an interpreter and unpickling the spec is search it does not
get. It is a real cost of racing — named in the spec's Risks — but the parent is
not waiting for it after the deadline. It is measured below as context and it is
**not** a term in the grace.

**The post-deadline tail is what the grace covers.** At the soft deadline a
child is holding a finished `Placement`. The parent cannot kill it yet, because
the answer still has to arrive: the child returns, the pool pickles a real
`Placement` through the result queue, and the parent unpickles it and resolves
the future. That span is the first term.

The second term, `base.ATOMIC_COMPLETION_GRACE_S` (5.0), is the in-process
atomic completion a serial arm already gets. The tail is the part racing adds on
top of it.

(The pool's `shutdown(wait=True)` happens *after* the `wait` returns and is
therefore not bounded by the grace at all, so it is deliberately outside the
measured span.)

## Method

`scripts/spawn_cost.py`, run as `uv run python scripts/spawn_cost.py`. Every run
uses exactly the pool shape `strategy_race._pool_submit` builds:
`ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn"),
max_tasks_per_child=1)`.

- **Spawn (context).** Ten independent pools. The parent records
  `time.monotonic()` immediately before `submit`; the first thing the child does
  is read `time.monotonic()` again and return the difference. Legitimate because
  Linux `CLOCK_MONOTONIC` is system-wide — the same property `sequence_islands`
  already relies on when it hands a child an absolute deadline. The script
  imports `flab2bp` only *inside* its functions, never at module level, because
  under `spawn` a module-level import is paid again by every child and would
  land in this number.
- **Tail (the grace's first term).** Ten independent pools. The child solves a
  real spec with freeform and returns `(time.monotonic(), placement)` — the
  timestamp being the instant the wall passes in the worst realistic case, a
  child that finished *exactly* at its deadline. The parent stops the clock the
  moment `future.result()` returns. The measured span is therefore precisely:
  child return → pickle a real `Placement` → result queue → parent unpickle →
  future resolved.

The spec is the corpus cell `iron-ingot` (first candidate), the same one the
Task 9 end-to-end proof uses: a real production spec with a real `Placement`.

**Deviation from the literal instruction, stated.** Ruling AL suggests a child
"with `absolute_deadline` already passed on entry". A child whose deadline has
already passed refuses immediately and has **no `Placement` to pickle**, and
pickling a real `Placement` back is the thing being measured — so the child is
given a normal deadline and the wall is taken to pass at the instant its
placement exists. That is the same tail, on the worst realistic crossing.

## Box load at the time of measurement

Per Ruling R the box is never idle and its load is disk I/O; the load is
recorded rather than waited out. (`vmstat`'s first row is a since-boot average.)

```
 06:04:40 up 18 days, 11:50,  8 users,  load average: 4.02, 3.76, 3.57
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 0  0      0 1037645900  0 8372416   0    0 50642 15349 23512   4  5  2 93  0  0  0
 4  0      0 1037646940  0 8372420   0    0   184 21968 17318 40213 1 1 97  0  0  1
 3  0      0 1037646992  0 8372420   0    0     0   612 13117 24740 1 1 98  0  0  0
```

## Results

**Post-deadline tail — the grace's first term.** Ten runs, sorted, seconds:

| # | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tail | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |

| min | median | **max (worst case)** |
| --- | --- | --- |
| 0.001 s | 0.001 s | **0.001 s** |

```
RACE_COMPLETION_GRACE_S = ceil(0.001) + 5.0 = 1 + 5.0 = 6.0
```

**Spawn-to-first-instruction — context only, inside the wall.** Ten runs:

| # | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cost | 0.100 | 0.101 | 0.101 | 0.103 | 0.104 | 0.104 | 0.105 | 0.105 | 0.105 | 0.107 |

| min | median | max |
| --- | --- | --- |
| 0.100 s | 0.104 s | 0.107 s |

That is the interpreter start alone; a real racer also unpickles a `BuildSpec`
and imports `flab2bp` on top of it, which is why a raced arm's usable search is
visibly shorter than a serial arm's. None of it is in the grace.

Raw script output: `spawn-cost.txt` in this directory.

**The value is 6.0** — unchanged from the number Task 8 wrote as a placeholder
and from Task 9's first (wrongly-derived) measurement, but now derived from the
right span. `ceil` of any positive tail under one second is 1, so the constant
would only move if the tail exceeded 1.0 s.

**Caveat, honestly.** The `Placement` measured here is a small one (area 63).
A much larger placement pickles more slowly, so 0.001 s is a floor rather than a
universal worst case. The margin absorbs it: the tail would have to grow a
thousandfold before `ceil` reached 2, and the 5.0 s atomic-completion term sits
on top of that.

## R1 lint check (Ruling AI)

Any timing constant in `flab2bp.layout` whose value collides with a linted game
value must be declared as a `registry.LintException`, never re-spelled around
the lint. Checked directly against `flab2bp.dsp.provenance.linted_values()`
(66 needles):

| value | in `linted_values()` |
| --- | --- |
| 6.0 (`RACE_COMPLETION_GRACE_S`) | no |
| 1.0 (`ceil(tail_max)`) | no |
| 5.0 (`ATOMIC_COMPLETION_GRACE_S`) | no |

No collision, so **no `LintException` is declared for this constant**. (30.0
*is* a linted value — `rules.SKEW_PAIR_DEG` — which is why the check is run at
all; no 30.0 is written into this module.) The re-derivation did not change the
value, so this check did not need to be repeated against a new number.

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
close without holding the parent open. The same path is now pinned by
`test_the_real_pool_races_both_arms_end_to_end` (2.6 s, `@pytest.mark.slow`).

## What this number is not

It is deliberately not `sequence_islands._ISLAND_COMPLETION_GRACE_S`'s 90.0: a
grace that large is a second budget.
