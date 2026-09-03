# R2 — why the freeform sweep stops early on `universe-matrix`, and what would change it

Read-only research. Checkout: `/home/dannyb/sources/factorio-lab-to-blueprint` at master `e0bf432`.
Every experiment ran in a throwaway copy at
`/tmp/claude-839601109/-home-dannyb-sources-factorio-lab-to-blueprint/8e787b45-e7bb-460a-9069-84e8ce0bea85/scratchpad/phase-e-R2`
(built with `git archive HEAD | tar -x`, plus the checkout's compiled `_*.cpython-314-x86_64-linux-gnu.so`
kernels copied into `src/flab2bp/layout/`). No file in the checkout was modified; this report is the only
thing written, and `.superpowers/` is ignored (`.gitignore:46`).

All line numbers below are 1-based on master `e0bf432` unless a line is explicitly marked "in the copy".

---

## 0. Headline

The refusal text is wrong about the defect and the premise of the question is wrong about the exit.

* The sweep is **not** exhausting its candidate heights. It `break`s out of the candidate loop at
  `src/flab2bp/layout/freeform.py:17729-17730` — the "arrangement 1+ needs an incumbent" gate — having
  consumed 6 of 15 candidate slots.
* It is **not** running out of packs to try. Every arrangement past the first returns a **byte-identical
  CP-SAT assignment** and is dropped by the duplicate-assignment guard at
  `freeform.py:17858-17859`, so the sweep has exactly **five** distinct packs to offer no matter how long
  it runs or how many arrangements it is given.
* It is **not** a packer defect. All five packs fail **before any routing happens at all**, in
  `_reserve_port_access` (`freeform.py:10062`), with `held=1 wants=2 roles=['dst'] twice=True options=1`
  on a handful of `hydrogen` lane heads. A lane head that has **one** geometric approach and needs
  **two** cannot be fixed by moving strips. Zero A\* expansions are ever spent
  (`freeform.py:15042-15048` and `freeform.py:15074`).
* The cause of the change at the rates commit `98dfa5d` is that `hydrogen` became an **external belt-in
  input** while still being produced internally. That is exactly the `twice=` / `shared_feed` condition at
  `freeform.py:14191-14195`, and it is what makes those lane heads demand a second approach they do not have.

**No experiment wired either cell.** Raising `--arrangements` to 4/8/16, removing the arrangement gate and
running all 80 candidates, forcing the Phase C window repair to fire on every failing pack, and varying
`strip_len` from 3 to 12 all produced the identical refusal at the identical failure count.

---

## 1. Box load (recorded before every timed run)

```
$ uptime; vmstat 1 3
 13:39:21 up 18 days, 19:25,  9 users,  load average: 3.38, 2.87, 4.35
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 4  0      0 1039176716  0 8430400   0    0 49798 15286 23403   4  5  2 93  0  0  0
 4  0      0 1039175932  0 8430400   0    0     0   184 14212 25594 3 0 97  0  0  0
 4  0      0 1039173376  0 8430400   0    0     0   469 14350 27624 3 0 97  0  0  0
```

```
$ uptime; vmstat 1 3      # before the traced baseline
 13:41:41 up 18 days, 19:27,  9 users,  load average: 8.05, 5.08, 4.98
 0  3      0 1039798556  0 8436924   0    0 49794 15286 23403   4  5  2 93  0  0  0
 7  2      0 1039800316  0 8436924   0    0    20 62682 30031 69749 1 2 94  3  0  0
 0  3      0 1039800840  0 8436924   0    0     0 29892 20462 42613 1 1 95  2  0  0
```

Before the `--arrangements` sweep: `13:44:09 ... load average: 2.44, 3.93, 4.56` (`r=1..3`, `wa=0`).
Before the gate-bypass runs: `13:45:12 ... load average: 3.22, 3.88, 4.50`.
Before the forced-window run: `13:47:03 ... load average: 4.14, 3.96, 4.45`.
Before the `strip_len` sweep: `13:48:40 ... load average: 3.41, 3.83, 4.37`.
Load is I/O wait as always on this box; nothing was waited for.

---

## 2. Baseline reproduction in the copy

```
$ cd <copy> && time /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python scripts/audit.py \
    --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json <scratch>/base.jsonl
3 cells of stress, 3 at a time, 42 CP-SAT workers each, cap 900s
  X [  1/3]     4s freeform  stress   universe-matrix/no-proliferator power=1 budget=30s   REFUSED    2.8s
  X [  2/3]     4s freeform  stress   universe-matrix/output-products power=1 budget=30s   REFUSED    3.4s
  X [  3/3]     7s freeform  stress   universe-matrix/all-products power=1 budget=30s      REFUSED    6.0s

=== freeform: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
    REFUSED  universe-matrix/output-products ... no packing of 43 strips could be wired at any candidate height; ...
    REFUSED  universe-matrix/all-products    ... no packing of 42 strips could be wired at any candidate height; ...
7s wall, 3/3 cells
```

`no-proliferator` is a *different* refusal (a `game.blueprint_area` validator rejection of a 264x162
extent) and is out of scope here; the two "PACKER defect" cells are `output-products` (43 strips) and
`all-products` (42 strips).

For tracing I drove one cell at a time in-process with a scratchpad driver
(`<scratch>/drive.py`) that imports the **copy's** `scripts/audit.py` and calls `audit.run_cell` on
`audit.build_jobs(strategies=["freeform"], ..., only={"universe-matrix"})`. Its `#0/#1/#2` spec indices are
`no-proliferator` / `all-products` (42 strips) / `output-products` (43 strips).

---

## 3. Q1 — the trace: heights, arrangements, per-pack times, and the exit taken

Instrumentation added **in the copy only**: a `_TR` stderr tracer, one line per loop turn at the point
after `improvement_soft` is computed (`freeform.py:17593-17598`), one per routing outcome at
`freeform.py:18157`, a tag on every `break` in the loop, and one at the sweep's return
(`freeform.py:18706`).

```
$ SWEEP_TRACE=1 .venv/bin/python drive.py universe-matrix 30
```

### `all-products` (spec `#1`, 42 strips)

```
[sweep] start strips= 42 heights= [128, 100, 80, 64, 48] share=29.59 per_solve=2.07 cands= 15 arrangements= 3 deadline_left=29.59
[sweep] turn i= 1 h= 128 arr= 0 ... t=0.00 left=29.56 dear=0.00 rem=0.00 best= False
[sweep] route h= 128 arr= 0 w= 202 failed= 3 status= stranded stage= None route_s=0.91 pack_s=0.06 t=0.97 kinds= ['static-access'] netpairs= [(26, 1, 'hydrogen'), (31, 1, 'hydrogen'), (None, 1, 'hydrogen')]
[sweep] window? promote= False slot= False admitted= False learned= False fbretry= False wcost=1.00 room= True
[sweep] turn i= 2 h= 100 arr= 0 ... t=0.97 left=28.59
[sweep] route h= 100 arr= 0 w= 223 failed= 3 status= stranded route_s=0.85 pack_s=0.09 t=1.91 kinds= ['static-access'] netpairs= [(26, 1, 'hydrogen'), (31, 1, 'hydrogen'), (None, 1, 'hydrogen')]
[sweep] turn i= 3 h= 80  arr= 0 ... route h= 80  w= 254 failed= 3 route_s=0.82 pack_s=0.08 t=2.81
[sweep] turn i= 4 h= 64  arr= 0 ... route h= 64  w= 275 failed= 3 route_s=0.67 pack_s=0.07 t=3.55
[sweep] turn i= 5 h= 48  arr= 0 ... route h= 48  w= 332 failed= 3 route_s=0.84 pack_s=0.08 t=4.48
[sweep] turn i= 6 h= 128 arr= 1 pretry= False queued= False t=4.48 left=25.08 dear=0.97 rem=0.91 best= False
[sweep] BREAK arrangement_gate_best_none t=4.48 left=25.08
[sweep] sweep_end best= False idx= 6 of 15 wq= 0 evals= 5 wsolves= 0 t=4.48 left=25.08
RESULT universe-matrix/#1 power=1 budget=30s status=REFUSED secs=4.93 area=0.0
DETAIL no packing of 42 strips could be wired at any candidate height; ...
```

### `output-products` (spec `#2`, 43 strips)

```
[sweep] start strips= 43 heights= [148, 93, 116, 74, 55] share=29.83 per_solve=2.09 cands= 15 arrangements= 3 deadline_left=29.83
[sweep] route h= 148 arr= 0 w= 212 failed= 6 route_s=0.37 pack_s=0.07 t=0.44 kinds= ['static-access'] netpairs= [(27, 1, 'hydrogen'), (27, 14, 'hydrogen'), (32, 1, 'hydrogen'), (33, 14, 'hydrogen'), (None, 1, 'hydrogen'), (None, 14, 'hydrogen')]
[sweep] route h= 93  arr= 0 w= 242 failed= 6 route_s=0.31 pack_s=0.09 t=0.84
[sweep] route h= 116 arr= 0 w= 256 failed= 6 route_s=0.30 pack_s=0.08 t=1.22
[sweep] route h= 74  arr= 0 w= 284 failed= 6 route_s=0.30 pack_s=0.08 t=1.60
[sweep] route h= 55  arr= 0 w= 348 failed= 6 route_s=0.32 pack_s=0.08 t=2.01
[sweep] turn i= 6 h= 148 arr= 1 ... t=2.01 left=27.82 best= False
[sweep] BREAK arrangement_gate_best_none t=2.01 left=27.82
[sweep] sweep_end best= False idx= 6 of 15 wq= 0 evals= 5 wsolves= 0 t=2.01 left=27.82
RESULT universe-matrix/#2 power=1 budget=30s status=REFUSED secs=2.19 area=0.0
```

### What the numbers say

| fact | `all-products` | `output-products` |
| --- | --- | --- |
| strips | 42 | 43 |
| candidate heights (in sweep order) | 128, 100, 80, 64, 48 | 148, 93, 116, 74, 55 |
| `share` / `per_solve` (`_PACK_SHARE=0.35`, `freeform.py:405,17355`) | 29.59 s / 2.07 s | 29.83 s / 2.09 s |
| candidate slots (`3 x 5`, `freeform.py:17306-17310`) | 15 | 15 |
| CP-SAT per pack (`pack_s`) | 0.06-0.09 s | 0.07-0.09 s |
| "routing" per pack (`route_s`) | 0.67-0.91 s | 0.30-0.37 s |
| routing outcome, every pack | `stranded`, `failed=3` | `stranded`, `failed=6` |
| failing nets, every pack | `26->1`, `31->1`, `ext->1` hydrogen | `27->1`, `27->14`, `32->1`, `33->14`, `ext->1`, `ext->14` hydrogen |
| failure kind, every pack | `static-access` only | `static-access` only |
| sweep returns `None` at | t = 4.48 s | t = 2.01 s |
| budget left at that moment | 25.08 s of 30 | 27.82 s of 30 |
| loop position when it left | slot 6 of 15 | slot 6 of 15 |

The `route_s` figure is not routing. When `prepared.preparation_failures` is non-empty the router is never
called: `freeform.py:15042-15048` substitutes a synthetic `DetailedRouteStatus.STRANDED` result carrying the
preparation failures with `iterations=0, expansions=0`, and the three real routing calls at
`freeform.py:15053-15071`, `15074-15086` and `15088-15098` are all guarded by
`not prepared.preparation_failures`. So `route_s` is the cost of *building the canvas and preparing nets*,
and zero A\* nodes are expanded on these cells.

### Exactly which exit

1. `_sweep` (`freeform.py:17133`) leaves its `while window_queue or candidate_index < len(candidate_packs)`
   loop (`freeform.py:17579`) by the `break` at **`freeform.py:17729-17730`**:

   ```python
   if not projection_retry and arrangement and best is None:
       break
   ```

   `candidate_packs` is arrangement-outer (`freeform.py:17306-17310`), so slots 1-5 are `arrangement=0`
   over the five heights and slot 6 is the first `arrangement=1`. With `best is None` — nothing ever wired
   — that gate fires immediately. The loop condition was still true (`idx=6 of 15`); the sweep did **not**
   exhaust its candidates.
2. `_sweep` then returns `None` at `freeform.py:18706-18716` (`best` is `None`).
3. `lay_out`'s single-element `for sweep_s in budgets:` (`freeform.py:16955`, `16977-16990`) falls through.
4. `deadline_expired = _expired(deadline)` (`freeform.py:17003`) is **False** — 25-28 s of the 30 s ceiling
   remain — so the deadline branch at **`freeform.py:17037`** (the one whose `raise` is at
   `freeform.py:17116`) is not entered. This is the branch that would have produced the old
   "4 packs were routed in that time..." text.
5. `rejected` is empty for these two cells (no pack ever wired, so nothing reached the validator), so the
   `if rejected and not completion_expired:` branch at `freeform.py:17026` is skipped too.
6. Control reaches the unconditional `raise NoValidLayout(...)` at **`freeform.py:17124-17130`** — the
   "PACKER defect" text.

For `no-proliferator` the picture differs only at step 5: one of its heights *does* wire and is then
rejected by `game.blueprint_area`, so `rejected` is non-empty and it takes the `freeform.py:17027` raise.

---

## 4. Q2 — why the Phase C window repair never fires

The window launch site is `freeform.py:18306`:

```python
if promote_retry and retry_slot_found and not retry_admitted:
```

Every trace line reads `promote= False slot= False admitted= False learned= False fbretry= False`. So the
condition that is false is the **first** one, `promote_retry`, and the documented trigger ("a retry was
wanted and could not be afforded") is never even reached. Affordability was never the blocker:
`room= True` on every turn, `wcost` 1.00-2.37 s against 25+ s remaining.

`promote_retry` is `freeform.py:18225`:

```python
promote_retry = arrangement == 0 and (learned or feedback_retry)
```

Both disjuncts are false, and both for the same underlying reason.

**`learned` is false** because `_proof_scoped_no_goods` (`freeform.py:14791`) returns `((), None, ())`.
Its early return at `freeform.py:14836-14841` requires `routing.exhaustive`:

```python
if (
    not routing.exhaustive
    or routing.status is not DetailedRouteStatus.STRANDED
    or not routing.failures
    or any(failure.kind is RouteFailureKind.BUDGET for failure in routing.failures)
):
    return (), None, ()
```

and `exhaustive` is forced false by the preparation failure at **`freeform.py:15141-15147`**:

```python
exhaustive=(
    not prepared.preparation_failures
    and external_routing.exhaustive
    ...
),
```

There is also no `promised_direct - realized_direct` residue, so the `local` direct-relation branch
(`freeform.py:14804-14832`) contributes nothing either.

**`feedback_retry` is false** at `_feedback_retry_eligible` (`freeform.py:14900-14913`) on two counts:
it demands `not routing.exhaustive` **and** `len(routing.failures) == 1`, and these cells carry 3 and 6
failures respectively.

So the exact predicate: **a static-access preparation failure produces a non-exhaustive routing result with
more than one failure, which yields no no-good and no feedback retry, so `promote_retry` is False and the
window's own launch condition is never evaluated.**

I verified this is the only thing standing in the way, by forcing it (see §6c): with
`promote_retry = arrangement == 0 and bool(failed)` patched in, the trace flips to
`promote= True slot= True admitted= True` — i.e. the retry *was* affordable and would have been admitted,
which by `freeform.py:18301-18306` is itself another reason the window would still not launch.

---

## 5. Q3 — what the rates commit changed

Evidence rows for `universe-matrix`, freeform, budget 30:

`docs/superpowers/evidence/2026-09-02-phase-b-last-mile/candidate-budget30-round3.jsonl` (before `98dfa5d`):

```
output-products  REFUSED 30.82s  the 30s deadline passed with no completed packing of 46 strips; 4 packs were
                                 routed in that time and the best of them still left 1 nets unrouted (worst 1),
                                 so a longer clock alone would not have wired this spec; 1 other pack stopped
                                 during exact preparation.
no-proliferator  REFUSED 32.63s  ... a 507x163 extent fits no band on a segment-200 planet ...
all-products     CLEAN   33.36s  area 37045
```

`docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-master-a4501e0-budget30-round1.jsonl` (after):

```
no-proliferator  REFUSED  3.37s  ... a 264x162 extent fits no band ...
output-products  REFUSED  3.66s  no packing of 43 strips could be wired at any candidate height ...
all-products     REFUSED  6.72s  no packing of 42 strips could be wired at any candidate height ...
```

Commit `98dfa5d` — *"Rates: price extraction recipes as FactorioLab does instead of cutting them"* — states
its own effect in the message:

> An item became a belt-in input only when NO crafting recipe could make it, so any item with a crafting
> recipe -- **hydrogen**, sulfuric acid, organic crystal, deuterium -- was crafted regardless of cost.

After the commit, `hydrogen` is an external input on **all three** specs:

```
0 no-proliferator machine_count=224 groups=38 ext_in=[coal, copper-ore, crude-oil, hydrogen, iron-ore, organic-crystal, silicon-ore, stone, sulfuric-acid, titanium-ore, water]
1 all-products    machine_count=113 groups=38 ext_in=[..., deuterium, hydrogen, ..., proliferator-3, ...]
2 output-products machine_count=193 groups=38 ext_in=[..., hydrogen, ..., proliferator-3, ...]
```

and the spec shrank (46 strips -> 43/42; the `no-proliferator` extent 507x163 -> 264x162, roughly half the
width), because the hydrogen chain that used to be built is now belted in.

**The answer to "fewer heights / faster CP-SAT / faster routing failure" is: faster routing failure, and
specifically no routing at all.** The old shape ran real A\* and near-missed by one net after 30 s of work
across 4 packs. The new shape never routes: `hydrogen` arrives on a lane that *also* still receives an
internally-produced hydrogen net, which is precisely the `shared_feed` set at `freeform.py:14191-14195`:

```python
shared_feed = {
    (port.x, port.y, port.z)
    for ports in strip_in_ports
    for item, port in ports.items()
    if item in spec.external_inputs
} & net_ports
```

That set is handed to `_reserve_port_access(..., twice=shared_feed, ...)` at `freeform.py:14198-14203`,
which raises those lane heads' corridor demand from 1 to 2 (`wants` at `freeform.py:10121`). They cannot
meet it, `unreachable_ports` is populated (`freeform.py:10188-10191`), `static_access_failure`
(`freeform.py:14499-14510`) turns each affected net into a `STATIC_ACCESS` `NetFailure`, and `_build`
short-circuits routing. Each pack therefore costs 0.3-0.9 s instead of 7-28 s, and five of them fit in
2-4.5 s.

CP-SAT is also not the constraint: `pack_s` is 0.06-0.09 s per pack against a `per_solve` allowance of
2.07-2.09 s.

### The root cause, measured

Instrumented `_reserve_port_access` in the copy to print each `missing` port:

```
[reserve] port (0, 10, 0)   held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (1, 10, 0)   held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (1, 113, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (128, 1, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (75, 1, 0)   held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (75, 23, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (75, 41, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (93, 15, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (93, 41, 0)  held= 1 wants= 2 roles= ['dst'] twice= True options= 1
[reserve] port (97, 8, 0)   held= 1 wants= 2 roles= ['dst'] twice= True options= 1
```

Every one of them: a destination-only lane head, in `twice`, with **exactly one candidate access cell**,
holding it, and short by one. `options` is built from the port's four in-plane neighbours
(`freeform.py:10151-10162`); the other three are occupied by the strip's own belts and machines. Printing
the neighbours confirms it — e.g. for `(1, 10, 0)`: `(2,10,0)` blocked by building 57, `(1,11,0)` by 66,
`(1,9,0)` by 47, and `(0,10,0)` is the adjacent sibling lane head.

`options` is a property of the **emitted strip geometry**, not of where the strip sits. That is the whole
explanation for why nothing downstream of `plan_strips` can help.

---

## 6. Q4 — experiments

All in the copy, budget 30, via `drive.py` (three cells per invocation, in-process, `workers=42`).

### (a) `--arrangements` raised

```
$ for A in 4 8 16; do .venv/bin/python drive.py universe-matrix 30 $A; done
=== arrangements=4 ===   #0 REFUSED 2.61s   #1 REFUSED 4.86s   #2 REFUSED 2.19s   wall 11.01s
=== arrangements=8 ===   #0 REFUSED 2.85s   #1 REFUSED 4.87s   #2 REFUSED 2.09s   wall 11.31s
=== arrangements=16 ===  #0 REFUSED 2.51s   #1 REFUSED 4.68s   #2 REFUSED 2.09s   wall 10.50s
```

Identical to the default within noise, and for a structural reason: `--arrangements` only lengthens
`candidate_packs`, and the gate at `freeform.py:17729-17730` breaks on the first `arrangement=1` slot
regardless of how many follow. **No clean cell. No extra work done at all.**

### (b) Keep sweeping past the gate / re-sweep to the deadline

Patched the copy so the gate is bypassed under `EXP_B1=1`, letting the loop run every candidate slot:

```
$ EXP_B1=1 SWEEP_TRACE=1 .venv/bin/python drive.py universe-matrix 30 3
[sweep] sweep_end best= False idx= 15 of 15 wq= 0 evals= 4 wsolves= 0 t=2.23 left=27.29   -> #0 REFUSED 3.25s
[sweep] sweep_end best= False idx= 15 of 15 wq= 0 evals= 5 wsolves= 0 t=5.07 left=24.52   -> #1 REFUSED 5.50s
[sweep] sweep_end best= False idx= 15 of 15 wq= 0 evals= 5 wsolves= 0 t=2.82 left=27.00   -> #2 REFUSED 3.02s
wall 13.17s
route outcomes across the whole run:  5 x failed=3,  9 x failed=6   (unchanged)

$ EXP_B1=1 SWEEP_TRACE=1 .venv/bin/python drive.py universe-matrix 30 16
[sweep] sweep_end best= False idx= 80 of 80 wq= 0 evals= 4 wsolves= 0 t=6.97 left=22.53   -> #0 REFUSED 8.04s
[sweep] sweep_end best= False idx= 80 of 80 wq= 0 evals= 5 wsolves= 0 t=10.53 left=19.05  -> #1 REFUSED 10.96s
[sweep] sweep_end best= False idx= 80 of 80 wq= 0 evals= 5 wsolves= 0 t=8.84 left=20.97   -> #2 REFUSED 9.05s
wall 29.44s
route outcomes across the whole run:  5 x failed=3,  9 x failed=6   (unchanged)
```

**Read the `evals` counter.** 80 candidate slots produced **5** routing evaluations. Every slot past
`arrangement=0` hit the duplicate-assignment guard at `freeform.py:17858-17859`:

```
[sweep] SKIP duplicate_assignment h= 128 arr= 1 w= 202
[sweep] SKIP duplicate_assignment h= 128 arr= 2 w= 202
[sweep] SKIP duplicate_assignment h= 100 arr= 1 w= 223
... (every height, every arrangement > 0)
```

CP-SAT returns the **identical** assignment for every arrangement index on these cells — the packing model
at 42-43 strips is easy enough that it proves optimality in under 0.1 s and the arrangement seed does not
move it. So "re-sweep with fresh arrangements until the deadline" has **nothing new to hand the router**.
This is the single most important negative result in this report: it kills option (b) *by construction*,
not by budget. **No clean cell.**

### (c) Force the Phase C window repair onto the failing packs

Patched the copy (`EXP_C=1`) to set `promote_retry = arrangement == 0 and bool(failed)`, to bypass
`retry_slot_found`/`retry_admitted` at `freeform.py:18306`, and to bypass the `_room_for_another` charge at
`freeform.py:18310-18314`, then traced each `_pack_window` result.

```
$ EXP_C=1 SWEEP_TRACE=1 .venv/bin/python drive.py universe-matrix 30 3
#0: [sweep] window_solve h=125 arr=0 window=[0,1,2,11,12,13] repaired=True same=False secs=0.07
    [sweep] route      h=125 arr=0 w=258 failed=6  (was 6)
    ... 4 window solves, wsolves=4, evals=8, t=3.47, left=25.81  -> REFUSED 5.04s
#1: window_solve h=128 window=[0,1,2,16,17,18] repaired=True same=False secs=0.17 -> failed 3 -> 4  (WORSE)
    window_solve h=100 ... -> failed 3 -> 3
    window_solve h=80  ... secs=0.42 -> failed 3 -> 3
    window_solve h=64  ... -> failed 3 -> 4  (WORSE)
    window_solve h=48  ... -> failed 3 -> 4  (WORSE)
    wsolves=5, evals=10, t=8.69, left=20.90  -> REFUSED 9.11s
#2: window_solve h=148 ... -> failed 6 -> 6
    window_solve h=93  ... -> failed 6 -> 7  (WORSE)
    window_solve h=116 ... -> failed 6 -> 6
    window_solve h=74  ... -> failed 6 -> 6
    window_solve h=55  ... secs=1.01 -> failed 6 -> 6
    wsolves=5, evals=10, t=5.31, left=24.53  -> REFUSED 5.48s
wall 21.25s
```

The window machinery works exactly as designed: `destroy_strips` picks a 6-strip window, `_pack_window`
returns a genuinely different assignment (`same=False`) in 0.05-1.01 s, and the repaired pack is installed
and re-evaluated. **Every repair leaves the failure count the same or higher.** It cannot help: the window
moves strips, and the failing corridor demand is inside a strip. **No clean cell.**

Note also `promote= True slot= True admitted= True` in this run — proving that if `learned` had been true
the *ordinary retry* would have been admitted and the window would still not have launched under
`freeform.py:18306`.

### (d) Vary `strip_len` (change the strip plan, which is where the geometry lives)

Patched the copy's `scripts/audit.py` freeform factory to read `STRIP_LEN` from the environment.

```
$ for SL in 3 4 8 12; do STRIP_LEN=$SL .venv/bin/python drive.py universe-matrix 30 3; done
strip_len=3   #0 REFUSED 2.51s  #1 REFUSED 4.70s  #2 REFUSED 2.11s   wall 10.55s
strip_len=4   #0 REFUSED 2.64s  #1 REFUSED 4.85s  #2 REFUSED 2.15s   wall 11.01s
strip_len=8   #0 REFUSED 2.55s  #1 REFUSED 4.70s  #2 REFUSED 2.15s   wall 10.65s
strip_len=12  #0 REFUSED 2.54s  #1 REFUSED 4.64s  #2 REFUSED 2.07s   wall 10.35s
```

Byte-identical strip counts (43/42/43), heights, widths and failure counts in all four. Reason:
`_coarsen_saturated_strip_plan` (`freeform.py:16897-16903`) rewrites the plan to the same coarse
representation regardless of the requested `strip_len`. **No clean cell.**

### Summary of Q4

| variant | wall | outcome |
| --- | --- | --- |
| baseline | 2.1 / 4.9 s per cell | REFUSED |
| `--arrangements 4 / 8 / 16` | unchanged | REFUSED, zero extra evaluations |
| gate bypassed, 15 candidates | 2.2-5.1 s | REFUSED, still 5 evaluations |
| gate bypassed, 80 candidates | 7.0-10.5 s | REFUSED, still 5 evaluations |
| forced window repair, 4-5 solves/cell | 3.5-8.7 s | REFUSED, failures same or worse |
| `strip_len` 3 / 4 / 8 / 12 | unchanged | REFUSED, identical packs |

**No variant produced a validator-clean cell at any wall.**

---

## 7. Q5 — design options

I will give the three asked-for options, but the measurement above changes the recommendation: on *these*
cells "continue the sweep to the deadline" is provably a no-op, so shipping it as a fix for them would be
buying nothing and paying CPU for it. It is still defensible as a **density** lever on cells that already
wire (that is the `tier large --budget 60` case the note at `freeform.py:17649-17658` was measured on), and
the refusal text is a separate, real defect that should be fixed regardless.

### Option 1 — Fix the refusal text; do not touch the loop *(recommended)*

The `freeform.py:17124-17130` message asserts "That is a PACKER defect -- it is producing packs its own
router cannot wire". On these cells that is false twice over: nothing was routed, and the packer is
blameless. A refusal that names the wrong subsystem sends the next reader to the wrong file, which is
exactly what this research had to undo.

* Touch `FreeformLayout.lay_out` (`freeform.py:16784`), the raise at `freeform.py:17124`. `attempts` is
  already in scope and every `PackAttempt` carries `static_access` (`freeform.py:14733-14735`, populated at
  `freeform.py:18165-18169`). When **every** retained attempt's failures are `STATIC_ACCESS` and
  `routing.expansions == 0`, say so: *"no pack was ever routed: N lane heads could not obtain the belt
  approaches they need (…item, …strip), which is a PORT-SEATING defect and is independent of the packing —
  every candidate height produced the same N failures."*
* Optionally surface `held`/`wants`/`options` by threading a small record out of `_reserve_port_access`
  (`freeform.py:10062`, `missing` at `freeform.py:10188`) into the `NetFailure` detail, so the refusal names
  the port and not just the net.
* Cost: zero CPU, zero risk to the 66 clean cells. Deterministic to test.

### Option 2 — Sweep-to-deadline with a *new-evidence* guard

Replace the `break` at `freeform.py:17729-17730` with a continuation that keeps drawing candidates until the
deadline, but only while the sweep is still learning something.

* Shape: keep `candidate_packs` as the ordered draw list; on reaching its end (or the arrangement gate) with
  `best is None`, `not _expired(deadline)` and room for one more candidate by `_room_for_another`
  (`freeform.py:18720`), re-seed. The guard that makes it honest is the counter this research needed anyway:
  track `evaluations` (already at `freeform.py:17409`) against `candidate_index`, and stop when K
  consecutive draws produce **no new `routed_assignments` entry** (`freeform.py:17311-17318, 17858-17859`).
  On `universe-matrix` that counter trips after one arrangement round and the loop exits at the same 2-4.5 s
  it does today — the cost is bounded to the cost of proving there is nothing new.
* Reuse of the Phase C machinery: the sweep already holds one `OperatorSession`
  (`sequence_alns.py:410`, constructed at `freeform.py:16974`) for the whole `lay_out` call, with
  `select`/`observe` (`sequence_alns.py:489`, `505`) driving D-UCB over destroy arms and the single
  `RepairOperator.LOCAL_EXACT_PACK` arm. A continued sweep should keep using **that same session**, so the
  ledger spans the re-sweeps and `remaining_fraction_bucket(soft - time.monotonic(), ...)`
  (`freeform.py:18334-18337`) keeps shrinking as the deadline nears. Nothing needs a second session.
* Bounding: the absolute wall is `deadline`, threaded from `lay_out` (`freeform.py:16836`) and read only
  through `_expired` (`freeform.py:695`) and `_room_for_another` (`freeform.py:18720`); the sweep's own soft
  clock stays `soft` (`freeform.py:17358`) and the portfolio's stays `_portfolio_soft_deadline`
  (`freeform.py:16704`, used at `freeform.py:17593`). A continuation loop must call `_room_for_another` with
  `dearest_candidate_s` exactly as the existing turn does, and must keep the
  `completion_reserve_s` check at `freeform.py:17760-17764` ahead of every draw.
* Honest refusal: with more evaluations, `attempts` grows, so the existing deadline-branch text at
  `freeform.py:17037-17122` starts to apply and already says the right thing ("N packs were routed in that
  time and the best of them still left M nets unrouted"). The `freeform.py:17124` text must still be
  corrected as in Option 1, because it is what a *non-deadline* exhaustion produces.
* Tests: `tests/layout/test_freeform.py` already has the pattern — `monkeypatch.setattr(freeform.time,
  "monotonic", <counter>)` (e.g. `tests/layout/test_freeform.py:3931-3942, 4359-4367`) and
  `monkeypatch.setattr(freeform, "_room_for_another", lambda *_args: False)`
  (`tests/layout/test_freeform.py:4316, 4429, 4457, 4480`). Pin: (i) with a fake clock and an injected
  sequence of failing packs that repeat, the loop stops after K stale draws and does **not** run to the
  deadline; (ii) with injected packs that keep producing new assignments, it runs until `_expired` and no
  further; (iii) the refusal text names the deadline in case (ii) and names staleness in case (i). No
  wall-clock assertions.

### Option 3 — Diversify the draw instead of repeating it

The reason Option 2 buys nothing is that arrangement N returns arrangement 0's assignment. Fix *that*
rather than the loop: give `_pack` a real diversification lever — a randomized objective tie-break, a
forced-different-assignment no-good seeded from `routed_assignments`, or a solution-hint perturbation — so
that arrangement N is genuinely a different draw.

* Touch `_pack` (the CP-SAT packing entry `_sweep` calls at `freeform.py:17800-17845`) and
  `_ExactPackNoGoodState` (`freeform.py:17323`): after each evaluated pack, add its assignment as a
  *diversification* cut for the next arrangement at the same height only (never sweep-wide — it is not a
  proof of infeasibility, exactly as the comment at `freeform.py:18256-18259` argues for the feedback case).
* This is the only one of the three that could ever make Option 2's extra clock useful. It is also the
  riskiest for area (see §8) and it still would not wire these two cells, because their failure is
  packing-invariant.

### Recommendation

**Option 1 now, unconditionally.** Then, if Phase E still wants the clock spent, Option 3 followed by
Option 2 behind the staleness guard — and gate both on a `tier large --budget 60` area A/B, not on the
stress tier, because the stress tier cannot benefit. Do **not** ship Option 2 alone: this report's §6b is
direct evidence that it would consume up to 10 s per stress cell and change nothing.

The actual lever for `output-products` / `all-products` is upstream of all three: `_seat_inputs` must not
put an external ingredient and an internally-produced one on a lane whose head has `options == 1`, or the
lane head must be emitted with a second approach. That is R-something-else's problem, but it is where the
cells get fixed.

---

## 8. Q6 — risks

**Area regression on the 66 clean cells.** Options 2 and 3 both hand the sweep more draws on cells that
already wire. `best_key` is `(area, belt_tiles)` (`freeform.py:18652`), so extra draws can only improve
the kept placement — the risk is not *worse* area but *different* area, and therefore churn in every
committed area number. The measured precedent is in the note at `freeform.py:17649-17658`: ungated extra
arrangements were **-1.51% area** at `tier large --budget 60` but **-0.67 cells** at `--budget 4`. Option 3
adds a second-order risk the note does not cover: a diversification cut changes the *first* arrangement's
neighbourhood too if it is mis-scoped sweep-wide, which would move area on cells that never asked for a
second draw. Scope it per (height, arrangement) as `feedback_retry_no_goods` already is
(`freeform.py:17324`, `18261`).

**CPU cost.** Measured here: bypassing the gate at `--arrangements 16` took `universe-matrix` from ~9 s to
~29 s of wall for three cells and produced nothing. Across the 72-cell audit at `--jobs 16` that is a real
multiple, and the memory note "Dev box load is disk, not CPU" does not protect against it — this is CP-SAT
and canvas emission, which is CPU. The staleness guard in Option 2 is what keeps it bounded; without it,
every refusing cell spends its whole ceiling.

**Racing path.** `RacingLayout` (`src/flab2bp/layout/strategy_race.py`) runs freeform as one leg with a
worker split (`race_worker_split`, `RACE_FREEFORM_WORKER_SHARE`) and a *shared* incumbent
(`portfolio_incumbent` / `publish_incumbent`, `freeform.py:16778-16784`). Three specific hazards:

1. A freeform leg that now runs to the deadline instead of returning at 4 s **holds its workers for the
   full ceiling**, starving the sequence-pair leg. Phase D already measured a 6/2 split starving raced
   freeform; this inverts and worsens that interaction.
2. `_portfolio_soft_deadline` (`freeform.py:16704`, applied at `freeform.py:17593`) is what lets another
   process's incumbent shorten this one's improvement window. A continuation loop must keep calling it per
   turn — rebinding `soft` instead (which the comment at `freeform.py:17590-17592` explicitly warns against)
   would let the race refuse this leg's own retries.
3. The race judges a cell against `RACE_COMPLETION_GRACE_S`, not the serial
   `ATOMIC_COMPLETION_GRACE_S`. A leg that now finishes at `deadline` rather than well inside it eats the
   grace it used to leave, so `wall_overshoot_s` on `best` cells is the number to watch in any A/B.
4. `_NoGoodInbox` / `applicable_no_good` route cluster no-goods across the race. On these cells no no-good
   is ever produced (§4), so the inbox stays empty and the race is inert here — consistent with the
   memory note that both repair arms are corpus-inert.

---

## 9. Open unknowns

* Whether the pre-`98dfa5d` 46-strip shape failed for a genuinely different reason (a real A\* stranding) is
  inferred from its refusal text — "4 packs were routed ... left 1 nets unrouted" implies real routing —
  but I could not run that shape, since doing so needs a checkout at the older commit.
* Whether `options == 1` on those lane heads is forced by `_seat_inputs`' lane assignment or by the strip
  emitter's building placement. Both are upstream of `_sweep`; I did not trace into `_seat_inputs`.
* Whether the same shared-feed condition is latent on any of the 66 clean cells (it would show as a
  `held < wants` port that happens to have `options >= 2`). A cheap corpus-wide probe would be to log
  `[reserve]` counts for every cell in one audit run.
* Whether `sequence-pair` fails these cells for the same reason. Its arm was not exercised here.

---

## 10. Commands run, verbatim

```bash
mkdir -p <scratch>/phase-e-R2
git -C /home/dannyb/sources/factorio-lab-to-blueprint archive HEAD | tar -x -C <scratch>/phase-e-R2
cp /home/dannyb/sources/factorio-lab-to-blueprint/src/flab2bp/layout/_*.cpython-314-x86_64-linux-gnu.so \
   <scratch>/phase-e-R2/src/flab2bp/layout/

cd <scratch>/phase-e-R2 && time /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python \
   scripts/audit.py --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json <scratch>/base.jsonl

# in-process single-cell driver against the copy
SWEEP_TRACE=1 /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python <scratch>/drive.py universe-matrix 30
for A in 4 8 16;  do /home/.../python <scratch>/drive.py universe-matrix 30 $A; done
for A in 3 16;    do EXP_B1=1 SWEEP_TRACE=1 /home/.../python <scratch>/drive.py universe-matrix 30 $A; done
EXP_C=1 SWEEP_TRACE=1 /home/.../python <scratch>/drive.py universe-matrix 30 3
for SL in 3 4 8 12; do STRIP_LEN=$SL SWEEP_TRACE=1 /home/.../python <scratch>/drive.py universe-matrix 30 3; done
```

Instrumentation applied to the copy only (none of it in the checkout):

* `_TR` tracer + `_T0` module-level, inserted before `class FreeformLayout`.
* One trace at `_sweep`'s `soft = ...`, one per loop turn, one per `break` (tagged), one per routing
  outcome at `failed = result.routing.failed_count`, one at the two `continue` skips, one at the window
  decision, one at sweep return.
* `hold_ports` prints each unreachable port with its neighbours' occupancy.
* `_reserve_port_access` prints each `missing` port's `held` / `wants` / `roles` / `twice` / `options`.
* `EXP_B1` bypasses `freeform.py:17729-17730`; `EXP_C` forces `promote_retry` and the window launch;
  `STRIP_LEN` overrides the copy's audit freeform factory.
