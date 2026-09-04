# R3 — sequence-pair on `universe-matrix`: the lockstep, the clock, and what the window buys

**Repo:** `/home/dannyb/sources/factorio-lab-to-blueprint` at `e0bf432`
(`fix(layout): tidy the race module and validate islands before racing`), read-only.
**Throwaway copy for instrumentation:**
`/tmp/claude-839601109/-home-dannyb-sources-factorio-lab-to-blueprint/8e787b45-e7bb-460a-9069-84e8ce0bea85/scratchpad/phase-e-R3`
(`git archive HEAD | tar -x`, plus the two compiled kernels copied in; run with the checkout's
`.venv/bin/python`).
Every `file:line` below was read at `e0bf432`. Line numbers are hints; resolve by symbol name.

---

## 0. Headline

Four findings, in order of how much they change the plan.

1. **The lockstep is not a tendency, it is an isomorphism.** With two destroy arms and two repair
   arms, `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` and `(BAND_BOUNDARY, SEQUENCE_REINSERT)` are
   **unreachable**, for every reward sequence, forever — not just on the first two draws. Proven by
   construction below and by 60 000 randomized draws.
2. **The window arm is not merely starved — it is worthless on this cell.** Four different
   lockstep-breaking variants make it fire (4–7 CP-SAT solves per cell, 2–4 installs at 30 s;
   17–19 solves and 13–15 installs per cell at 120 s). **None produces a CLEAN cell, at either
   budget.** Each solve costs a hard 1.006 s — CP-SAT hits its time limit every time — and the arm
   consumes 4–9 s of a 30 s budget, cutting the stage count roughly in half.
3. **At 30 s `universe-matrix` under sequence-pair is not band-bound — it is routing-bound.** The
   Phase C note's `1334x131` extent does **not reproduce at `e0bf432`**. Every candidate the search
   evaluates at 30 s is 107–340 wide by 54–126 tall, `band_target_width == width` on 46 of 51 of
   them (i.e. band-legal), `band_overflow == 0` on 43 of 51 — and **every single one strands 3–7
   nets**. `validation_time_s == 0.0` on every run: the validator was never reached, because no
   candidate ever routed completely.
4. **It is not time-bound at 4x, and at 10x the failure MODE changes rather than the verdict.** All
   three policies still REFUSE at `--budget 120` (106–118 s). At `--budget 300`,
   `no-proliferator` still refuses (284 s) but now with a *different* detail: the outline-160
   height reaches **`stranded == 0`** — a fully routed placement — and the refusal becomes
   `no legal DSP latitude band/orientation accepts the final placement: … a 166x162 extent …
   needs 162 latitude rows … the tallest band (200 segments) holds 160`. That is the **same wall
   the freeform arm hits on this cell at 30 s** (Phase C: a 264x162 extent), which Phase C judged
   "unreachable by any placement-search repair".

Consequence for the spec: "break the lockstep so the window arm fires" is a **correctness fix worth
making on its own merits** (a two-arm portfolio that can only ever play two of its four pairings is
a defect), but it is **not the lever that closes `universe-matrix`**. Section 6 names what is.

---

## 1. The lockstep mechanism, exactly

### 1.1 Where the two choices are made

`OperatorSession.select` (`src/flab2bp/layout/sequence_alns.py:490-504`) builds one
`OperatorChoice` from **two independent ledgers**:

```python
choice = OperatorChoice(
    destroy=DestroyOperator(self._destroy.best(self._exploration)),
    repair=RepairOperator(
        self._repair.best(self._exploration, among=self._affordable_repairs(context))
    ),
    scale=operator_scale(context),
    ordinal=len(self._choices),
)
```

The ledgers are `_Ledger.over([...])` instances created in `OperatorSession.__init__`
(`:440-441`) over `SHIPPED_DESTROY` (`:93-96`, `FAILED_ENDPOINTS` then `BAND_BOUNDARY`) and
`SHIPPED_REPAIR` (`:97-100`, `SEQUENCE_REINSERT` then `LOCAL_EXACT_PACK`). Both tuples are length 2
and **declaration order is the tie-break** (`:72`, `:85`).

The untried-arm probe is `_Ledger.best` (`:388-393`):

```python
arms = tuple(among) if among else self.order
untried = [arm for arm in arms if self.counts[arm] == 0.0]
if untried:
    return untried[0]
```

`untried[0]` — first in declaration order, no exploration, no reward, no clock.

### 1.2 Why the pairing is deterministic — the isomorphism argument

`OperatorSession.observe` (`:506-533`) credits **both** ledgers from the **same** reward vector and
the **same** `applied` flag, after decaying both by the same discount:

```python
credited = tuple(reward) if applied else (0.0,) * REWARD_RANKS
self._destroy.decay(self._discount)
self._repair.decay(self._discount)
self._destroy.credit(choice.destroy.value, credited)
self._repair.credit(choice.repair.value, credited)
```
(`sequence_alns.py:524-528`)

Consider the index-preserving map φ: destroy arm *i* ↦ repair arm *i*
(`FAILED_ENDPOINTS ↦ SEQUENCE_REINSERT`, `BAND_BOUNDARY ↦ LOCAL_EXACT_PACK`).

- **Base case.** After `__init__`, both ledgers are `dict.fromkeys(arms, 0.0)` with zero reward
  vectors (`_Ledger.over`, `:367-373`). They are φ-identical.
- **Inductive step.** If the two ledgers are φ-identical before a draw, then `best` is a pure
  function of (counts, rewards, arm order) and returns the same *index* in both — whether via the
  untried probe (`untried[0]`, same index) or via the lexicographic means plus the exploration
  bonus (`:394-408`, identical inputs ⇒ identical argmax). So `choice.destroy` and `choice.repair`
  sit at the same index. `observe` then decays both identically and credits the same index in each
  with the same vector, so the ledgers remain φ-identical.

Therefore the pairing at every draw *n* is `(SHIPPED_DESTROY[i_n], SHIPPED_REPAIR[i_n])` for a
single shared index `i_n`. **The cross pairings are structurally unreachable.**

Nothing about the reward magnitudes matters. `reward_vector` (`:189-208`) is irrelevant to the
argument — whatever it returns goes to both ledgers.

The **one** thing that can break φ is `_affordable_repairs` (`:480-488`):

```python
if context.remaining_fraction >= C_WINDOW_FRACTION_FLOOR:
    return self._repair.order
affordable = tuple(
    operator.value
    for operator in self._repair_arms
    if operator is not RepairOperator.LOCAL_EXACT_PACK
)
```

Restricting `among` to `(SEQUENCE_REINSERT,)` lets the repair ledger take a different index from the
destroy ledger, desynchronizing φ from then on. That happens only when
`remaining_fraction < C_WINDOW_FRACTION_FLOOR` (`:57`, `= 1`), i.e. in the **last 10 %** of the
clock — precisely the window in which the same guard also forbids `LOCAL_EXACT_PACK`. It is a
catch-22: the only escape from the lockstep is a bucket in which the window is banned.

### 1.3 Verified empirically

Command (run against the checkout, read-only):

```
$ cd /home/dannyb/sources/factorio-lab-to-blueprint && .venv/bin/python - <<'PY'
# 2000 traces x 30 draws, random rewards / applied flags / remaining_fraction buckets
...
PY
pairings reachable over 60000 draws (destroy, repair, window_affordable):
    ('band-boundary', 'local-exact-pack', True)
    ('band-boundary', 'sequence-reinsert', False)
    ('band-boundary', 'sequence-reinsert', True)
    ('failed-endpoints', 'local-exact-pack', True)
    ('failed-endpoints', 'sequence-reinsert', False)
    ('failed-endpoints', 'sequence-reinsert', True)

with remaining_fraction always at the ceiling (no _affordable_repairs restriction):
    ('band-boundary', 'local-exact-pack')
    ('failed-endpoints', 'sequence-reinsert')
```

The second block is the lockstep: with the window always affordable, exactly **two** of the four
pairings ever occur, in 60 000 draws. The cross pairings in the first block appear only after a
`remaining_fraction == 0` draw has desynchronized the ledgers.

And on the corpus itself (instrumented `--budget 30`, all three policies, 45 selections total):

```
base30.2497347  selects: {('failed-endpoints','sequence-reinsert'): 16, ('band-boundary','local-exact-pack'): 1}
base30.2497350  selects: {('failed-endpoints','sequence-reinsert'):  7, ('band-boundary','local-exact-pack'): 4}
base30.2497351  selects: {('failed-endpoints','sequence-reinsert'):  9, ('band-boundary','local-exact-pack'): 8}
```

Zero cross pairings. `remaining_fraction` observed values were 0–7 (never below 0, and only one
process ever reached 0), so the `_affordable_repairs` escape effectively never fired.

### 1.4 What happens to the (BAND_BOUNDARY, LOCAL_EXACT_PACK) proposal — the code path

`_alns_substitution` (`src/flab2bp/layout/sequence_solver.py:3066-3193`):

1. `:3117` — `choice = session.observe_and_select(...)` yields `(BAND_BOUNDARY, LOCAL_EXACT_PACK)`.
2. `:3118` — the `adapters.window_pack is None` skip does **not** fire in production: the adapter is
   wired at `:5519-5522`.
3. `:3125-3145` — `destroy_strips(BAND_BOUNDARY, scale=problem.size, ...)`. The scale is
   `problem.size` because the window is exempt from `cap_scale` (Ruling AF, `:3141-3147`), so
   `_capped` (`sequence_alns.py:264-272`) truncates nothing.
4. `_band_boundary` (`sequence_alns.py:275-308`) returns one of three things:
   - **`[]`** when `band_target_width >= decoded.width and decoded.used_height <= problem.outline_height` (`:292-293`);
   - **`over`**, the strips whose right edge exceeds `band_target_width` (`:301-305`);
   - **`ranked`**, *all* `problem.size` strips, when `over` is empty but the outline still overflows (`:308`).
5. `:3151` — the guard
   `if not neighbourhood or (problem.size > 1 and len(neighbourhood) == problem.size)`
   credits the choice as **unapplied** with a zero reward and returns `unchanged`. `window_pack` is
   **never called**.

**Measured on `universe-matrix` at `--budget 30`, 13 `BAND_BOUNDARY` draws across the three cells:**

| outcome of `_band_boundary` | count | dropped at |
|---|---:|---|
| `[]` ("fits") | 9 | `sequence_solver.py:3151`, `not neighbourhood` |
| whole `ranked` list (43 of 43) | 4 | `sequence_solver.py:3151`, `len == problem.size` |
| strict subset | **0** | — |

`window_pack` call count: **0**. `alns_window_solves`: **0**. `alns_window_accepted`: **0**.

Why `over` is always empty: `band_target_for` (`sequence_solver.py:5469-5480`) delegates to
`finalize.band_target_width` (`finalize.py:192-225`), which returns the **input width unchanged**
when a frame already exists (`finalize.py:216-217`). So on a band-legal placement
`band_target_width == decoded.width`, and the strict inequality at `sequence_alns.py:304`
(`decoded.x[strip] + problem.sizes[strip][0] > band_target_width`) can never hold — the rightmost
strip's edge *equals* the width. Observed band targets vs widths on the `BAND_BOUNDARY` draws:
`309/309, 232/232, 148/148, 177/177, 235/235, 278/278, 195/195, 202/202, 242/242, 217/217, 223/223, …`
— equal in every case.

There is a **second** whole-problem guard inside the adapter itself
(`sequence_solver.py:5377-5378`, `if not window or len(window) >= problem.size: return None`), so
relaxing only `:3151` would not help.

**Important nuance: `BAND_BOUNDARY` is not inherently inert on this corpus.** The `--budget 300`
run logged 76 evaluations, of which **14 had `band_target_width < decoded.width`** (`154/210`,
`154/224`, `154/202`, `154/173`, `154/193`, `154/168`, `154/205`, `154/191`, `154/161`, `154/186`,
`154/157`, `154/225`, `154/180`, `154/164`) with `band_overflow` up to 73. On any of those,
`_band_boundary`'s `over` list would have been a **strict, useful subset**. The selector simply
never played `BAND_BOUNDARY` on one of them — it played it once, on a band-legal placement, and the
zero reward removed it. So the accurate statement is: *the destroy set was empty-or-whole on every
draw the selector actually gave it* (13/13 at 30 s, 1/1 at 300 s), **not** that the operator is
structurally incapable of producing evidence.

### 1.5 Could a later turn pair LOCAL_EXACT_PACK with another destroy operator?

**No, not on master's production path.** Two independent reasons:

- By §1.2, `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` is unreachable while φ holds, and φ holds for
  every draw at `remaining_fraction >= 1`. Confirmed by 60 000 randomized draws (§1.3) and by 45
  real corpus draws (zero cross pairings).
- Independently, the D-UCB **cannot reward an arm that was dropped**: `_alns_substitution:3153`
  calls `session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)`, and `observe:524` replaces
  the reward with all-zeros whenever `applied` is false. So `BAND_BOUNDARY`'s and
  `LOCAL_EXACT_PACK`'s discounted means stay pinned at exactly zero while
  `FAILED_ENDPOINTS`/`SEQUENCE_REINSERT` accumulate positive means — and even when the paired arm
  earns nothing either, the exploration bonus at `:405` favours the lower-count arm, which by φ is
  the same index in both ledgers. **A dropped proposal is charged a count and can never buy its way
  out.**

The only φ-breaking event on master is a `remaining_fraction == 0` draw, and that same condition
bans the window (`_affordable_repairs:481-488`).

**Measured at scale.** The `--budget 300` `no-proliferator` run made **76** selections:

```
alns_operators: destroy:failed-endpoints:75|destroy:band-boundary:1|
                repair:sequence-reinsert:75|repair:local-exact-pack:1
pairings: {'failed-endpoints+sequence-reinsert': 75, 'band-boundary+local-exact-pack': 1}
drops: {'empty': 1}
```

The `(BAND_BOUNDARY, LOCAL_EXACT_PACK)` proposal is drawn **once**, dropped as `empty`, credited
`applied=False` with an all-zero reward — and, because `FAILED_ENDPOINTS`/`SEQUENCE_REINSERT` then
accumulate strictly positive discounted means while the dropped pair stays pinned at exactly zero,
the selector **never returns to it in the remaining 74 draws**. That is the clearest available
statement of "the D-UCB never rewards an arm that was dropped": one turn, one zero, permanent
exclusion.

(At 30 s the same run shape gives 4–8 `BAND_BOUNDARY` draws instead of 1 — there the
`FAILED_ENDPOINTS` arm also earns nothing, so the exploration bonus at `:405` rotates the two arms.
Rotation, not learning, is what keeps the window arm's play count above zero on the short clock.)

---

## 2. What sequence-pair actually does on `universe-matrix` in 30 s

Instrumented in the copy: `src/flab2bp/layout/_probe.py` (new), plus probes in the copy's
`sequence_alns.py` (`_band_boundary` returns, `OperatorSession.select`) and `sequence_solver.py`
(`_alns_substitution` drop reasons, `window_pack` early-returns and solve wall,
`window_installed` identity check, and a `search_end` dump before the refusal-reason lookup at
`sequence_solver.py:1535`).

**Process model.** The audit's `sequence-pair` factory (`scripts/audit.py:126-129`) constructs
`SequencePairLayout` **without** `islands`, and `SequencePairLayout.__init__` defaults
`islands: int = 1` (`sequence_solver.py:5892`). So an explicit `--strategy sequence-pair` cell runs
**one island, in-process** — `run_sequence_islands`' spawned children
(`sequence_islands.py:297-301`) are the `best`/racing path only. Confirmed: exactly three probe
files for three cells. `--sequence-islands` **does not exist** as an `audit.py` flag (`build_parser`,
`scripts/audit.py:636-701`); the only knobs are `--budget --tier --strategy --jobs --max-seconds
--only --skip --arrangements --candidate-policy --quiet --json`.

### 2.1 Stages, restarts, heights, candidates (baseline, `--budget 30`)

| | all-products (pid 2497347) | no-proliferator (2497350) | output-products (2497351) |
|---|---:|---:|---:|
| termination | `deadline` | `deadline` | `deadline` |
| incumbent found | no | no | no |
| stages | 17 | 11 | 17 |
| anneal stages | 16 | 10 | 16 |
| global routes | 21 | 9 | 18 |
| detailed routes (= ALNS evaluations) | 17 | 11 | 17 |
| heights scheduled | 11 | 10 | 11 |
| heights that got ≥1 stage | 9 | 6 | 9 |
| `alns_choices` / `alns_applied` | 17 / 15 | 11 / 6 | 17 / 8 |
| `feasibility_restart_batches` | 0 | 0 | 0 |
| strips (`problem.size`) | 43 | 42 | 43 |
| stranded nets per height at the end | 6,5,5,6,7,6,6,6,6 | 3,5,4,4,4,4 | 6,6,6,6,6,6,6,6,6 |

`feasibility_restart_batches == 0` everywhere: the Ruling-Z continuation never ran, because the
deadline arrived first.

### 2.2 Where the 30 s goes

`search_end` sums over `self._stage_stats`, seconds:

| | all-products | no-proliferator | output-products |
|---|---:|---:|---:|
| `preparation_time_s` | 7.494 | 11.726 | 7.671 |
| `global_route_time_s` | 3.704 | 1.675 | 4.035 |
| `detailed_route_time_s` | 1.141 | 0.513 | 0.920 |
| `validation_time_s` | **0.0** | **0.0** | **0.0** |
| accounted adapter time | 12.34 | 13.91 | 12.63 |
| wall at `search_end` | 28.60 | 27.94 | 28.98 |
| **remainder = annealing / placement search** | **≈ 16.3** | **≈ 14.0** | **≈ 16.4** |

So: **~25–40 % preparation, ~6–14 % global routing, ~2–4 % detailed routing, 0 % validation,
~50–58 % the placement anneal itself.** The first ALNS decision does not happen until
t ≈ 9.6 / 11.9 / 10.4 s — a third of the budget is gone before the operator portfolio is consulted
even once.

`validation_time_s == 0.0` is the load-bearing number: **the validator was never invoked**, because
no candidate ever reached a complete detailed route.

### 2.3 Extents — the `1334x131` claim does not reproduce

Every evaluated failing candidate (`width` × `used_height`), across all three cells at
`--budget 30`, baseline:

```
all-products    : 295x82 309x86 155x119 175x116 176x123 227x113 196x92 217x101 ...
no-proliferator : 180x67 232x77 127x114 148x113 154x78 177x84 146x78 235x80 ...
output-products : 226x78 278x84 172x96 195x95 216x84 202x110 242x79 242x87 ...
```

Widths 107–340, heights 54–126. Nothing remotely like 1334 wide. `band_target_width == width` on
46 of the 51 logged evaluations; `band_overflow == 0` on 43 of 51. The five exceptions are all in
`all-products` at outline height 160 (`btw=154` against widths 166–227, overflow 12–73).

**These placements are band-legal and they still refuse.** `failed_nets` on every one of the 51
evaluations is between 3 and 7 — never 0, never 1, never 2.

### 2.4 The last state when the deadline hits

`termination = "deadline"`, `self._incumbent is None`, so `SequenceSolver.search`
(`sequence_solver.py:1535-1551`) raises with
`"deadline exhausted before finding an exact layout"`. `validation_checks` is empty (nothing was
validated) and `projection_failures` is empty, so no suffix is appended — which is exactly the
detail string the corpus reports.

Per-height, at the end: 6 of 11 heights (all-products) still carry
`stranded == 1<<60` (`1152921504606846976`), i.e. they were **never started** — the deadline
arrived before discovery reached them. The heights that were started all sit at 3–7 stranded nets.

---

## 3. Is the cell time-bound? No.

### `--budget 30` (baseline, master, read-only run in the checkout)

```
$ uptime
 13:38:20 up 18 days, 19:24,  9 users,  load average: 2.64, 2.65, 4.40
$ vmstat 1 3
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 1040233376  0 8051492   0    0 49800 15286 23403   4  5  2 93  0  0  0
 3  0      0 1040251496  0 8051496   0    0     0     0 13498 35688 3 0 97  0  0  0
 3  0      0 1040250676  0 8051496   0    0   228  1824 12564 24117 1 0 98  0  0  0

$ uv run python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix \
      --strategy sequence-pair --json .../b30.jsonl
3 cells of stress, 3 at a time, 42 CP-SAT workers each, cap 900s
  X [  1/3]    29s sequence-pair stress   universe-matrix/all-products power=1 budget=30s      REFUSED   27.5s  <-- 28s
  X [  2/3]    30s sequence-pair stress   universe-matrix/output-products power=1 budget=30s   REFUSED   28.4s  <-- 28s
  X [  3/3]    31s sequence-pair stress   universe-matrix/no-proliferator power=1 budget=30s   REFUSED   29.4s  <-- 29s

=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
    REFUSED  universe-matrix/all-products power=1 budget=30s  deadline exhausted before finding an exact layout
    REFUSED  universe-matrix/output-products power=1 budget=30s  deadline exhausted before finding an exact layout
    REFUSED  universe-matrix/no-proliferator power=1 budget=30s  deadline exhausted before finding an exact layout
31s wall, 3/3 cells
wall 32.77
```

### `--budget 120`

```
$ uptime
 13:39:28 up 18 days, 19:25,  9 users,  load average: 3.51, 2.90, 4.36
$ vmstat 1 3
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 8  0      0 1039287204  0 8430396   0    0 49798 15286 23403   4  5  2 93  0  0  0
 5  0      0 1039312604  0 8430396   0    0     0     0 16655 35965 5 1 94  0  0  0
 6  0      0 1039252460  0 8430400   0    0     0     4 15655 41343 5 1 94  0  0  0

$ uv run python scripts/audit.py --budget 120 --jobs 3 --only universe-matrix \
      --strategy sequence-pair --max-seconds 1200 --json .../b120.jsonl
3 cells of stress, 3 at a time, 42 CP-SAT workers each, cap 1200s
  X [  1/3]   108s sequence-pair stress   universe-matrix/no-proliferator power=1 budget=120s  REFUSED  106.4s  <-- 106s
  X [  2/3]   110s sequence-pair stress   universe-matrix/output-products power=1 budget=120s  REFUSED  108.9s  <-- 109s
  X [  3/3]   120s sequence-pair stress   universe-matrix/all-products power=1 budget=120s     REFUSED  118.3s  <-- 118s

=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
    REFUSED  universe-matrix/no-proliferator power=1 budget=120s  deadline exhausted before finding an exact layout
    REFUSED  universe-matrix/output-products power=1 budget=120s  deadline exhausted before finding an exact layout
    REFUSED  universe-matrix/all-products power=1 budget=120s  deadline exhausted before finding an exact layout
120s wall, 3/3 cells
wall 120.84
```

**All three still refuse at 4x the clock, with the same detail string.**

### `--budget 120`, instrumented (the copy) — same verdict, same mechanism

Re-run under the probe (load line: `13:53` up 18 days, load 3.0–4.6; three cells, `--jobs 3`).
REFUSED 107.3 / 109.7 / 117.4 s.

| | all-products | no-proliferator | output-products |
|---|---:|---:|---:|
| stages | 25 | 21 | 24 |
| `preparation_time_s` | 11.59 | 25.49 | 11.96 |
| `global_route_time_s` | **66.59** | **65.38** | **69.34** |
| `detailed_route_time_s` | 1.62 | 0.98 | 1.19 |
| `validation_time_s` | **0.0** | **0.0** | **0.0** |
| stranded per height at the end | 6–7 (all 11) | 3–5 (all 10) | 6 (all 11) |
| window solves / installs | **0 / 0** | **0 / 0** | **0 / 0** |
| `_band_boundary` drops | 1 empty | 1 whole-problem | 7 empty + 5 whole-problem |

Nothing structural improves: the extra 90 s buys 8–14 more stages, all of them still stranding
3–7 nets, and the window arm still never reaches CP-SAT. Global routing has become the dominant
cost (55–61 % of the wall, versus 6–14 % at 30 s).

One incidental confirmation of §1.2: the `output-products` process logged a single
`band-boundary+sequence-reinsert` draw — a **cross pairing**. That is the
`_affordable_repairs` escape (`sequence_alns.py:481-488`) firing once at
`remaining_fraction == 0`, desynchronizing φ exactly as predicted. It is the only cross pairing in
**166 baseline selections** across all budgets.

### `--budget 300`, `no-proliferator` only — the failure mode changes

```
$ PHASE_E_LOG=.../base300 PHASE_E_VARIANT=baseline \
  <checkout>/.venv/bin/python scripts/audit.py --budget 300 --jobs 1 --only universe-matrix \
      --candidate-policy no-proliferator --strategy sequence-pair --max-seconds 1200 \
      --json out/base-b300.jsonl
1 cells of stress, 1 at a time, 128 CP-SAT workers each, cap 1200s
  X [  1/1]   284s sequence-pair stress   universe-matrix/no-proliferator power=1 budget=300s  REFUSED  284.2s  <-- 284s

=== sequence-pair: 0/1 clean -- NOT CLEAN   (refused 1, invalid 0, crashed 0, not run 0)
    REFUSED  universe-matrix/no-proliferator power=1 budget=300s  deadline exhausted before
    finding an exact layout; no legal DSP latitude band/orientation accepts the final placement:
    band 0 game.blueprint_area (): a 166x162 extent fits no band on a segment-200 planet: it needs
    162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The
    game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.; band 0
    game.blueprint_area (): a 179x163 extent fits no band on a segment-200 planet: it needs 163
    latitude rows in its better orientation and the tallest band (200 segments) holds 160. ...
284s wall, 1/1 cells
```

Still REFUSED — **no longer CLEAN at any clock we measured** — but the mechanism has moved. From
the instrumentation:

```
search_end: {"termination": "deadline", "incumbent": false, "stages": 81, "anneal_stages": 79,
 "global_routes": 86, "detailed_routes": 81, "preparation_time_s": 33.639,
 "global_route_time_s": 195.135, "detailed_route_time_s": 5.006, "validation_time_s": 0.0,
 "feasibility_restart_batches": 0, "alns_choices": 76, "alns_applied": 74,
 "alns_operators": "destroy:failed-endpoints:75|destroy:band-boundary:1|
                   repair:sequence-reinsert:75|repair:local-exact-pack:1",
 "heights":         [99, 125, 160, 100, 80, 60, 127, 162, 102, 82, 62],
 "height_stages":   [ 2,  11,  11,   2,  2, 11,   9,  11,   3, 11,  8],
 "height_stranded": [ 7,   6,   0,   6,  7,  6,   7,   6,   7,  6,  6],
 "t": 284.5119}
```

Three things changed at 10x the clock:

1. **A placement routes.** `height_stranded[2] == 0` at outline height 160 — the first
   fully-routed candidate anywhere in this investigation. It is then rejected by the finaliser
   because its *finalized* extent is 162–163 latitude rows against the 160-row band ceiling.
2. **The refusal detail gains the projection failures** appended at `sequence_solver.py:1563-1571`.
   `universe-matrix/no-proliferator` under sequence-pair at 300 s therefore hits **exactly the
   wall the freeform arm hits on the same cell at 30 s** (Phase C recorded a 264x162 extent /
   507x163 extent, and judged it "unreachable by any placement-search repair").
3. **Global routing becomes the cost centre**: 195.1 s of 284 s (69 %) versus 6–14 % at 30 s.
   Preparation is 33.6 s; detailed routing only 5.0 s; validation still 0.0 s.

So the honest answer to "is the cell time-bound" is: **no at 30 s and 120 s** (routing-bound), and
**at 300 s it converts into the band-ceiling refusal the program already classifies as
placement-search-unreachable**. A longer clock does not wire any policy; it relocates the wall.

---

## 4. Experiments in the copy

Four selector variants were implemented behind `PHASE_E_VARIANT` in the copy's
`sequence_alns._probe_pairing` (appended to the copy's `sequence_alns.py`); each rewrites the
`(destroy, repair)` pair `select` computed, leaving the ledgers, the reward and the scale
untouched.

| variant | rule |
|---|---|
| `baseline` | master |
| `stagger` | the destroy ledger's **untried** probe walks its arms in reverse declaration order; the repair ledger keeps declaration order. Draw 0 becomes `(BAND_BOUNDARY, SEQUENCE_REINSERT)`, draw 1 becomes `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`. |
| `force-pairs` | the first four draws are the four pairings, `LOCAL_EXACT_PACK` first; the D-UCB then takes over |
| `fe-window` | whenever the D-UCB asks for `LOCAL_EXACT_PACK`, force the destroy operator to `FAILED_ENDPOINTS` |
| `window-always` | every draw is `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` — the upper bound on what the arm can buy |

All run with the copy's own `scripts/audit.py` under the checkout's `.venv/bin/python`.

### 4.1 (a) Does the window fire? Yes — in all four variants.

Totals over the three cells at `--budget 30` (and the 120 s baseline / `window-always` rows for
comparison):

| variant | budget | window_pack calls | CP-SAT solves | produced an encoding | **installed** (`window_installed` identity match) | total window wall |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 30 | **0** | **0** | 0 | **0** | 0.00 s |
| baseline | 120 | **0** | **0** | 0 | **0** | 0.00 s |
| `stagger` | 30 | 15 | 15 | 10 | **10** | 15.1 s (4.0–7.1 per cell) |
| `force-pairs` | 30 | 10 | 10 | 9 | **9** | 10.1 s (1.0–5.0 per cell) |
| `fe-window` | 30 | 16 | 16 | 11 | **11** | 16.1 s (4.0–7.1 per cell) |
| `window-always` | 30 | 24 | 24 | 20 | **20** | 24.2 s (6.0–9.1 per cell) |
| `window-always` | 120 | 55 | 55 | 42 | **42** | 55.4 s (17.1–19.2 per cell) |

So the answer to "would breaking the lockstep make the window arm fire" is an unambiguous **yes**,
and the counter that proves it (`alns_window_accepted`, via `window_installed` at
`sequence_solver.py:5450-5459`) goes from 0 to 4–8 per cell.

### 4.2 (b) CP-SAT wall and window size

The measurement is remarkably uniform:

- **Every solve costs 1.003–1.009 s.** `_pack_window` is given
  `time_budget_s=min(C_WINDOW_SECONDS, remaining - C_WINDOW_DEADLINE_SAFETY_SECONDS)`
  (`sequence_solver.py:5403-5405`) with `C_WINDOW_SECONDS = 1.0` (`freeform.py:3254`).
  **CP-SAT hits its time limit on every single solve** — it never proves optimality on a window
  this size. Phase C's "a posed solve costs about 1 s" (its OPEN item 4) is exactly right.
- **Window size is 16–31 strips of 42–43.** That is the whole `select_lns_neighbourhood` failure
  set, uncapped by Ruling AF: 38–72 % of the problem in one exact solve.
- **20 of 24 (`window-always` at 30 s) and 47 of 55 (at 120 s) solves returned a *changed*
  assignment**; the rest returned `repaired.at == pack.at` (the "unchanged" early return at
  `sequence_solver.py:5409-5414`).
- `width_target == width_bound` on 22 of 24 solves — the window is being asked to compact a
  placement that **already fits a band**, so the objective it is given has nothing to buy.

### 4.3 (c) Does any variant produce a CLEAN cell? **No.**

```
=== VARIANT window-always budget 30 ===
  X [  1/3]    26s ... universe-matrix/all-products     REFUSED   25.2s
  X [  2/3]    28s ... universe-matrix/no-proliferator  REFUSED   26.6s
  X [  3/3]    29s ... universe-matrix/output-products  REFUSED   27.5s
=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)

=== VARIANT force-pairs budget 30 ===
  X [  1/3]    29s ... universe-matrix/all-products     REFUSED   27.5s
  X [  2/3]    29s ... universe-matrix/output-products  REFUSED   27.8s
  X [  3/3]    29s ... universe-matrix/no-proliferator  REFUSED   27.9s
=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)

=== VARIANT fe-window budget 30 ===
  X [  1/3]    28s ... universe-matrix/no-proliferator  REFUSED   26.8s
  X [  2/3]    29s ... universe-matrix/all-products     REFUSED   27.3s
  X [  3/3]    29s ... universe-matrix/output-products  REFUSED   27.6s
=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)

=== VARIANT stagger budget 30 ===
  X [  1/3]    ...   universe-matrix/*                  REFUSED
=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
```

**Zero CLEAN cells out of twelve variant runs.** Every cell still refuses at
`deadline exhausted before finding an exact layout`.

**And it does not become CLEAN with 4x the clock either.** `window-always` at `--budget 120`
(load line: `13:52:43 up 18 days, load 3.21 3.80 4.25`; `vmstat` `r=3,1,1`, `wa=0`):

```
=== VARIANT window-always budget 120 ===
  X [  1/3]   113s ... universe-matrix/no-proliferator  REFUSED  111.5s
  X [  2/3]   113s ... universe-matrix/all-products     REFUSED  111.5s
  X [  3/3]   113s ... universe-matrix/output-products  REFUSED  111.7s
=== sequence-pair: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
```

with **55 CP-SAT window solves, 42 installs, 55.4 s of window wall** across the three cells
(`repair:local-exact-pack:19|17|19` of 20/18/20 draws; window sets 16–31 strips of 42–43;
8 of 55 returned an unchanged assignment). Every height still ends at 3–7 stranded nets.
The arm is exercised as hard as it can be exercised and moves nothing.

### 4.4 Why it does not help — and what it costs

The window is an **area/geometry** repair aimed at a **routing** failure. `window_pack`'s objective
is `width_target = band_target_for(outline_height, decoded.width)` (`sequence_solver.py:5402`),
which on a band-legal placement equals the current width — so the solve is asked to compact
something that has nothing to gain, and it returns a different-but-equally-unroutable pack. Stranded
counts across the twelve variant runs stay at 3–7, exactly the baseline range.

Meanwhile it is expensive. Stage counts, baseline vs `window-always`, per cell:

| cell | baseline stages | `window-always` stages | budget spent in CP-SAT windows |
|---|---:|---:|---:|
| all-products | 17 | **9** | 9.07 s of 30 |
| no-proliferator | 11 | **6** | 6.04 s of 30 |
| output-products | 17 | **9** | 9.07 s of 30 |

`fe-window` and `stagger` land in between (8–11 stages). **Firing the window arm roughly halves the
search's throughput** and buys nothing on this cell. That is a real, measured cost that any
un-lockstepping change must be gated against.

---

## 5. Design options for "break the lockstep so the window arm fires"

The lockstep is a genuine defect: a portfolio advertised as two-by-two can play only two of its
four pairings, and no reward sequence can ever change that. Fixing it is correct regardless of what
`universe-matrix` does. Three options, then a recommendation.

**First, a measured correction that eliminates the obvious fix.** A constant probe *offset* does
**not** make the portfolio fully reachable — it merely rotates *which two* pairings are reachable,
because a shifted bijection is still a bijection. Verified against the checkout:

```
master  -> [('band-boundary','local-exact-pack'), ('failed-endpoints','sequence-reinsert')]
offset  -> [('band-boundary','sequence-reinsert'), ('failed-endpoints','local-exact-pack')]
product -> all four
```

and confirmed on the corpus: the `stagger` variant produced exactly
`{band-boundary+sequence-reinsert, failed-endpoints+local-exact-pack}` on all three cells — never
the other two.

### Option A — stagger the untried probe by ledger rank

**Change.** `_Ledger.best` (`sequence_alns.py:388-393`) grows a probe offset; `select` (`:490-504`)
passes `0` to the destroy ledger and a named `C_REPAIR_PROBE_OFFSET = 1` to the repair ledger.

**Effect.** Draw 0 becomes `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` — the window posed against the
routing-failure set, the evidence it was designed for. Draw 1 becomes
`(BAND_BOUNDARY, SEQUENCE_REINSERT)`.

**Assessment.** Achieves the phase's literal goal (the window arm fires against the right set) with
one integer and no reward-semantics change. Measured as `stagger`: 15 window solves, 10 installs,
0 CLEAN cells. **But it swaps the blind spot rather than removing it** — `(BAND_BOUNDARY,
LOCAL_EXACT_PACK)` becomes the unreachable pairing. Cheap and honest, but it does not let a gate
claim the portfolio is whole.

### Option A′ — round-robin the product while any arm is untried (recommended)

**Change.** In `OperatorSession.select` (`sequence_alns.py:490-504`), while **either** ledger still
has an untried arm, take the pairing from an ordinal-indexed walk over the product rather than from
two independent probes:

```python
probe = len(self._choices)
if probe < len(self._destroy.order) * len(self._repair.order):
    destroy = DestroyOperator(self._destroy.order[probe // len(self._repair.order)])
    repair = RepairOperator(self._repair.order[probe % len(self._repair.order)])
else:
    destroy = DestroyOperator(self._destroy.best(self._exploration))
    repair = RepairOperator(
        self._repair.best(self._exploration, among=self._affordable_repairs(context))
    )
```

with the `_affordable_repairs` gate still applied to the probe (a probe that would name
`LOCAL_EXACT_PACK` below `C_WINDOW_FRACTION_FLOOR` falls through to the D-UCB, exactly as the copy's
`force-pairs` variant does).

**Effect.** Every pairing is played once before any is played twice; after the probe the two ledgers
are genuinely desynchronized (destroy plays `d0,d0,d1,d1`, repair plays `r0,r1,r0,r1`, so their
count/reward patterns differ) and **all four pairings stay reachable** under D-UCB. Verified above
(`product -> all four`) and on the corpus: `force-pairs` produced all four pairings on one cell and
three of four on the others.

**Why A′ over A.** It is the only option that makes the shipped portfolio's advertised behaviour
true, and it is the only one a gate can assert on without special-casing which two pairings are
"the reachable ones". It keeps two ledgers, so `OperatorSession.__doc__`'s reason for not learning
the product (`:411-418`) still holds — the product is *probed*, not *learned*.

**Cost.** Two extra exploration draws per session (4 instead of 2), of which one extra is a window
draw at ~1.006 s. On a cell with 6–17 evaluations that is 6–17 % of the search. Measured:
`force-pairs` ran 9–15 stages vs the baseline's 11–17 — a smaller hit than `window-always`'s 45 %,
but real. This is why §5.3's gate needs a stage-cost clause.

**Replayability (program invariant).** "For a fixed seed and a fixed deterministic budget the
sequence of choices replays exactly" (`sequence_alns.py:12-15`). Preserved: the probe is a pure
function of `len(self._choices)` and the two arm tuples; it reads no RNG and no clock;
`reward_vector` (`:189-208`) and `operator_scale` (`:219-229`) are untouched; `observe` is
untouched. The *values* of the replayed sequence change once — a deliberate, gated behaviour change
— so every pinned choice-sequence expectation must be re-derived. `select` remains total and
side-effect-free apart from appending to `_choices` and setting `_pending`.

**How the reward ledger treats a dropped proposal.** Unchanged, and deliberately so:
`_alns_substitution:3120` (no adapter), `:3153` (empty or whole-problem set) and `:3161-3163`
(`window_pack` returned `None`) each call `session.observe(choice, (0.0,) * REWARD_RANKS,
applied=False)`, and `observe:524` replaces the reward with all-zeros. The accounting is right — an
arm whose evidence is chronically absent should lose its turn. What A′ changes is only *which
destroy set the window arm is handed*, so the zeros it collects become informative rather than
structural. Note the consequence measured at 300 s (§1.5): one drop is enough to exclude a pairing
for the rest of a long session, so the probe is the **only** chance a pairing gets on a well-behaved
run. That is an argument for probing the product, not against it.

### Option B — bound `_band_boundary`'s whole-problem fallback

**Change.** `_band_boundary` (`sequence_alns.py:308`) stops returning `over or ranked` and returns
`over` alone (empty when nothing exceeds the target), or returns `ranked[:k]` for a bounded `k`.
Additionally `band_target_for` (`sequence_solver.py:5469-5480`) could return a target *strictly
below* the current width when the placement already fits, so `over` is non-empty.

**Assessment.** This addresses the *symptom on this corpus* (9 empties + 4 whole-problems at 30 s)
but not the lockstep: `LOCAL_EXACT_PACK` would still only ever pair with `BAND_BOUNDARY`, and
`BAND_BOUNDARY`'s set is the wrong evidence for a routing failure (§4.4). Measured: `fe-window`
(which gives the window the *right* set) still produces zero CLEAN cells, so this option's ceiling
is below a variant we already know fails. **Not recommended alone** — but §1.4's nuance means it is
worth doing *later*, alongside A′: once the selector can reach `(BAND_BOUNDARY, SEQUENCE_REINSERT)`,
the 14-of-76 evaluations at 300 s where `band_target_width < width` become real evidence, and the
`over or ranked` fallback at `sequence_alns.py:308` is then the thing that throws it away.

### Option C — make the pairing a single joint arm over the product

**Change.** Replace the two `_Ledger`s with one over the four `(destroy, repair)` pairs. The
untried probe then walks all four, so every pairing is played once before any is played twice, by
construction.

**Assessment.** Directly contradicts the documented reason for two ledgers
(`OperatorSession.__doc__`, `sequence_alns.py:411-418`): "the product of the two portfolios cannot
be learned inside a thirty-second budget". With 6–17 evaluations per cell (§2.1), four arms would
get 1–4 observations each — a portfolio that never leaves its exploration phase. **Not
recommended.**

### 5.1 Deterministic unit tests (mutant tables, no wall clock)

All of these are pure-function tests over `OperatorSession`; none touches a clock, an RNG, or a
solver.

1. **`test_the_window_arm_is_paired_with_the_failure_set_on_its_first_draw`** — a fresh session at
   `remaining_fraction = C_CONTEXT_FRACTION_STEPS`; assert
   `select(...) == (FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`. Mutant: `probe_offset = 0` on both
   ledgers restores master and fails this.
2. **`test_every_shipped_pairing_is_reachable`** — the exhaustive reachability harness of §1.3 as a
   test: a fixed table of `(reward, applied)` traces, asserting that the four-element set
   `SHIPPED_DESTROY x SHIPPED_REPAIR` is covered. This is the test master cannot pass, and it is
   the honest statement of the defect. Table-driven, no randomness in the committed version —
   derive one concrete 8-draw trace that covers all four and pin it.
3. **`test_each_ledger_still_plays_every_arm_once_before_any_arm_twice`** — the existing property
   (`test_sequence_alns.py:168-179`), re-asserted per-ledger, so the fix cannot be mistaken for
   permission to skip an arm.
4. **`test_selection_is_deterministic_for_the_same_observation_sequence`** — the existing
   `test_sequence_alns.py:272-285` re-run; it must still pass verbatim (`run() == run()`).
5. **`test_a_dropped_window_proposal_is_charged_a_count_and_no_reward`** — assert
   `credit["count:local-exact-pack"] == 1.0` and every `reward:local-exact-pack:*` is `0.0` after
   one `observe(..., applied=False)`. Pins that the fix did not quietly start paying for a drop.
6. **`test_the_window_is_still_withheld_without_room_to_finish`** — the existing
   `test_local_exact_pack_is_not_offered_without_room_for_a_window`
   (`test_sequence_alns.py:316-321`) must still hold under the new probe offset, so the offset
   cannot smuggle a window past `C_WINDOW_FRACTION_FLOOR`.
7. **`test_band_boundary_on_a_band_legal_placement_is_empty`** — a decoded placement with
   `band_target_width == width` and `used_height <= outline_height`, asserting `_band_boundary`
   returns `[]`; and one with a vertical-only overflow asserting it returns all `problem.size`
   strips. This pins the two drop paths §1.4 measured, so a later change to `band_target_for`
   cannot silently make `BAND_BOUNDARY` productive without a test moving.
8. **`test_a_whole_problem_destroy_set_never_reaches_the_window`** — drive `_alns_substitution`
   with a stub `window_pack` that records calls, and a destroy operator returning all strips;
   assert zero calls and one `applied=False` observation. Pins `sequence_solver.py:3151`.

### 5.2 Files and functions to touch

| file | symbol | change |
|---|---|---|
| `src/flab2bp/layout/sequence_alns.py` | `_Ledger.best` | add `probe_offset` parameter, applied only to the untried branch |
| | `OperatorSession.select` | pass the destroy/repair probe offsets |
| | module constants | add `C_REPAIR_PROBE_OFFSET = 1` with a docstring naming the lockstep |
| | module docstring (`:1-20`) | record that the two ledgers are otherwise φ-isomorphic and why the offset exists |
| `src/flab2bp/layout/sequence_solver.py` | `_ProductionTelemetry` (`:4340-4346`) | add `alns_window_dropped_empty`, `alns_window_dropped_whole`, `alns_window_unchanged` |
| | `_alns_substitution` (`:3151-3163`) | increment the new counters at each drop site (needs the telemetry threaded in, or a counter callback on `_RepairAdapters`) |
| | `window_pack` (`:5377-5414`) | increment `alns_window_reject_guard` / `_clock` / `_unchanged` (Phase C OPEN item 3) |
| | stats dict (`:6171-6181`) | publish the new counters |
| `scripts/audit.py` | `Result`, `run_cell` (`:181-343`) | **carry the counters on REFUSED rows** — see §5.3 |
| `tests/layout/test_sequence_alns.py` | — | the eight tests of §5.1 |
| `tests/layout/test_sequence_solver.py` | `_window_arms` (`:1166-1170`) etc. | the `_alns_substitution` drop-path tests |

### 5.3 The counters a gate needs — and the blocker

**A gate cannot currently see any of this.** Verified: an `audit.py` JSONL row for a REFUSED cell
carries no `stats` at all —

```
$ python3 -c "...print(sorted(row['stats']))"   # first row of b30.jsonl
STATS KEYS: []
ALNS: {}
```

because every `alns_*` stat is written in `_with_observational_stats`
(`sequence_solver.py:6023-6228`), which only runs on a **successful** placement, and `Result`
(`scripts/audit.py:181-228`) has no stats field at all. Phase D's ranked lever (2) — "put the
incumbent and no-good counters on `audit.Result` so a gate can see sharing" — is the same blocker,
one phase later.

So the gate work is in two parts:

1. **`audit.Result` gains a `stats: dict[str, float]` field** populated on REFUSED rows as well as
   CLEAN ones. That needs the solver to surface its telemetry on the `NoValidLayout` path — e.g.
   `NoValidLayout` gains an optional `stats` mapping filled at `sequence_solver.py:1535`, or
   `SequencePairLayout.lay_out` catches and re-raises with the run's telemetry attached
   (`:6011-6018` is already re-raising, so the hook exists).
2. **The gate asserts, on the three `universe-matrix` sequence-pair rows:**
   - `alns_operators` contains `repair:local-exact-pack:N` with `N >= 1` **and**
     `destroy:failed-endpoints:M` with `M >= N` — i.e. the window was paired with the failure set;
   - `alns_window_solves >= 1` (the arm reached CP-SAT, not just the selector);
   - `alns_window_accepted >= 1` (a window repair was **installed**, `window_installed` at
     `sequence_solver.py:5450-5459`);
   - `alns_window_dropped_whole == 0` on any draw that named `LOCAL_EXACT_PACK`;
   - and a **cost clause**: `stages` must not fall by more than X % against the baseline row,
     because §4.4 measured a 45 % stage loss when the window fires freely.

Without the last clause a gate would pass on a change that halves the search.

---

## 6. The cells are not deadline-bound — the next lever

They are **routing-bound at 30–120 s and band-ceiling-bound at 300 s**. Evidence:

- 4x the clock changes nothing (§3): REFUSED at 120 s on all three policies, same detail string.
- At 30 s every candidate is band-legal (`band_overflow == 0` on 43 of 51) and still strands 3–7
  nets (§2.3); the validator is never reached (`validation_time_s == 0.0`, §2.2).
- At 300 s one candidate finally routes (`stranded == 0` at outline 160) and is then refused by the
  finaliser for needing 162–163 latitude rows against a 160-row ceiling (§3).
- Twelve variant runs with the window arm firing (10–20 installs) produce **zero** CLEAN cells.

The window arm is an *area* repair. Neither failure it could address is the one occurring: at short
clocks the failure is *connectivity*, at long clocks it is a *2–3 row* band overshoot on an already
routed placement. Ranked levers:

1. **Phase D Task 12 — the deferred no-good receivers.** Ruling AN records that
   `ClusterRelationNoGood` names strips by integer index into the *producer's* arrays and that
   "sequence-pair has no relation-exclusion collection to receive into". At 30 s the sequence-pair
   arm re-derives 3–7 stranded nets on 51 consecutive evaluations across 6–9 heights, never
   learning that the relation is infeasible; at 300 s it does the same 76 times. That is precisely
   what a relation-exclusion collection exists to stop. It is aimed at the failure that is actually
   occurring, and it also feeds the intra-arm case (a sequence-pair solver receiving its **own**
   no-goods across restarts), which needs none of Ruling AN's cross-process identity vector. **The
   highest-value deferred item for this cell.**
2. **A height schedule that can reach the band ceiling from below.** The 300 s run's heights are
   `[99, 125, 160, 100, 80, 60, 127, 162, 102, 82, 62]` — nothing between 128 and 160. The only
   height that routes is 160, whose finalized extent is 162–163, two to three rows over. A
   schedule offering ~150–158 would let a routed placement finalize inside the ceiling. This is
   cheap to test and directly targets the 300 s wall; it needs the height generator, not a new
   operator.
3. **A destroy/repair pair whose reward is stranded nets, not area.** This is the bar
   `DestroyOperator`'s docstring sets for adding an arm (`sequence_alns.py:76-78`, "Added when a
   refusing cell names the mechanism"). The evidence already exists —
   `select_lns_neighbourhood` produced 19–29 strips per evaluation — but the repairs applied to it
   are a *random reinsert* (`repair_neighbourhood`) or an *area compaction* (the window); neither
   targets connectivity. The declared-but-undispatched `BLOCKER_COMPONENT` / `CONGESTED_CUT`
   (`sequence_alns.py:78-79`) with `ROUTING_REGRET` (`:90`) are the named candidates. Note this is
   the lever that would *justify* A′: a third and fourth arm makes the product-probe cost
   (`|D|x|R|` draws) much larger, so **A′ should land before, not after, the portfolio grows.**
4. **Warm-start sequence-pair from the freeform arm through the race.** Freeform reaches a
   placement on this cell where sequence-pair reaches none inside 120 s. Handing sequence-pair a
   routed freeform placement as an `initial_states` entry (`sequence_solver.py:5504`) would replace
   7.5–11.7 s of cold preparation (§2.2) with a placement already known to route. Phase D lever (3)
   is the mirror image (warm-starting the *raced freeform* arm), so the transport is half-built.
   Caveat: on `no-proliferator` freeform's own extent is 507x163 / 264x162 — over the same ceiling —
   so this helps the other two policies more than the one Phase C named.
5. **The program's deterministic feasibility fallback**
   (`docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`, "Deterministic
   feasibility fallback", success criterion 3 and step 8), reserved for "supported instances that
   stochastic search still misses, at deliberately lower density" and explicitly "not mixed into
   ALNS". `universe-matrix` under sequence-pair — three policies, unmoved by 4x the clock, unmoved
   by four selector variants, and at 10x landing on a band ceiling Phase C already called
   placement-search-unreachable — is the canonical instance of that description.

**Recommendation for the spec.** Land Option A′ plus the counters (§5) as a
correctness-and-observability change, gated on a stage-cost clause — it is cheap, it makes a
documented portfolio property true, and without the counters no future lever on this cell is
attributable (a REFUSED audit row currently carries **no stats at all**). Do **not** book it as the
`universe-matrix` closure. Book lever 1 (Task 12's receivers, starting with the intra-arm case) and
lever 2 (the height schedule) for that.

---

## Appendix A — commands run

Machine load was recorded immediately before every timed run; all `uptime`/`vmstat` output is
inline in §3 and in `out/run-*.log` in the copy. Load averages 2.6–4.4 on a 128-core box whose load
is I/O wait, never idle.

```
# baseline, in the checkout (read-only)
uv run python scripts/audit.py --budget 30  --jobs 3 --only universe-matrix --strategy sequence-pair --json out/b30.jsonl
uv run python scripts/audit.py --budget 120 --jobs 3 --only universe-matrix --strategy sequence-pair --max-seconds 1200 --json out/b120.jsonl

# throwaway copy
mkdir -p <copy> && git -C <checkout> archive HEAD | tar -x -C <copy>
cp <checkout>/src/flab2bp/layout/_{sequence,route}_kernel.cpython-314-x86_64-linux-gnu.so <copy>/src/flab2bp/layout/

# instrumented runs, copy's audit.py under the checkout's interpreter
PHASE_E_LOG=<copy>/out/logs/base30 PHASE_E_VARIANT=baseline \
  <checkout>/.venv/bin/python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix \
  --strategy sequence-pair --json out/inst-b30.jsonl
# ... and the same with PHASE_E_VARIANT in {window-always, force-pairs, fe-window, stagger}
# ... and --budget 120 / --budget 300 --candidate-policy no-proliferator --jobs 1
```

## Appendix B — instrumentation added to the copy (never on master)

- `src/flab2bp/layout/_probe.py` — new; env-gated JSONL writer keyed by pid, and the
  `PHASE_E_VARIANT` switch.
- `sequence_alns.py` — probes at both `_band_boundary` return points and in
  `OperatorSession.select` (emitting the chosen pair, the context and both ledgers' counts); the
  `_probe_pairing` variant dispatcher appended at module end.
- `sequence_solver.py` — probes at `_alns_substitution`'s three drop sites and around the
  `window_pack` call; at `window_pack`'s guard, clock and unchanged early returns and around the
  CP-SAT solve; at `window_installed`'s identity check; and a `search_end` dump immediately before
  the refusal-reason lookup in `SequenceSolver.search`.
