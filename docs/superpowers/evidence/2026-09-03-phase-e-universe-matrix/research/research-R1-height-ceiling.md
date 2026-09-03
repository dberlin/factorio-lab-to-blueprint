# R1 — Why freeform `universe-matrix/no-proliferator` refuses with a 264x162 band extent

Read-only research, master `e0bf432`. All experiments ran in a throwaway `git archive` copy at
`/tmp/claude-839601109/-home-dannyb-sources-factorio-lab-to-blueprint/8e787b45-e7bb-460a-9069-84e8ce0bea85/scratchpad/phase-e-R1`
with the checkout's compiled kernels copied in and the checkout's `.venv/bin/python` driving the
copy's own `scripts/audit.py`. **No file in the checkout was modified.**

---

## 0. Headline

Two independent defects, both proved on the cell:

1. **A candidate height of 160 rows survives the band reservation filter.** The filter's
   infeasibility witness is `_minimum_pack_width` — an area-based *lower* bound that comes out at
   **92** for this cell while every real pack at that height is **258** wide. At width 92 the
   200-segment band accepts the frame **rotated** (98 columns of latitude → 98 ≤ 160 rows), so
   height 160 is "not proved infeasible" and is kept. The greedy seed at that height is
   `258x156`; its extent is `258+6 x 156+6 = 264x162`, which fits no band. That refusal is
   *retained* and becomes the cell's headline message.
2. **The headline message is false.** Nothing wired. The retained refusal comes from a **pre-pack
   seed gate** (`freeform.py:17766-17778`), before any solve, power plan, coater, router or
   finalizer has run. `lay_out` (`freeform.py:17026-17036`) turns a non-empty `rejected` list into
   *"every packing that wired was rejected by our own validator"*, which sends the reader to the
   finalizer instead of to the actual blocker.

**The actual blocker** (item 6): every candidate height of all three universe-matrix freeform
cells strands the *same* nets with `RouteFailureKind.STATIC_ACCESS` — 6 for `no-proliferator`,
3 for `all-products`, 6 for `output-products` — and the count is **identical at every height from
48 to 154**. Removing the band refusal (experiment E1 below) changes the message and nothing else.

---

## 1. How freeform derives candidate heights, and what the ceiling actually is

### The chain

| step | location | what it does |
|---|---|---|
| `_candidate_heights(strips)` | `src/flab2bp/layout/freeform.py:18781-18788` | pure `sqrt(area)` heuristic: `h0 = max(tallest_box, isqrt(area))`, then `{max(tall, int(h0*f)) for f in (0.6, 0.8, 1.0, 1.25, 1.6)}`. **Knows nothing about the planet.** |
| `_greedy_pack(strips, h)` | `freeform.py:3044-3065` | shelf pack, seeds each height |
| `_minimum_pack_width(strips, h)` | `freeform.py:18791-18796` | `max(widest_box, ceil(area/h))` — a valid but very loose *lower* bound on any pack width at that height |
| `_band_policy_candidate_heights` | `freeform.py:18799-18815` | orders heights by `(seed.width, height)` and calls `reserve_boundary_height` |
| `band_policy_search_envelope(policy, perimeter=_ENTRY_RING)` | `src/flab2bp/layout/finalize.py:163-181` | builds the envelope; `policy=BandPolicy("portable")` → `explicit_segments is None` → `band=None` |
| `BandPolicySearchEnvelope` | `finalize.py:99-160` | `boundary_core_height` (107), `frame_candidates` (115), `extent_failure` (130), `reserve_boundary_height` (145) |
| consumed by the sweep | `freeform.py:17256` | `heights = list(_band_policy_candidate_heights(strips, self.band_policy))` |

`_ENTRY_RING = _ROUTE_RING + 1 = 3` (`freeform.py:642-643`).

### The numbers

`planet.bands()` (`src/flab2bp/dsp/planet.py:307-341`) for a segment-200 planet — verbatim output of
`uv run python -c "from flab2bp.dsp import planet; [print(b.area_segments,'rows',b.rows,'cols',b.columns) for b in planet.bands()]"`:

```
200 rows 160 cols 1000 lat 0 15 grid 1 80
160 rows 50  cols 800
120 rows 25  cols 600
100 rows 25  cols 500
 80 rows 15  cols 400
 60 rows 15  cols 300
 40 rows 10  cols 200
 32 rows 10  cols 160
 20 rows  5  cols 100
 16 rows  5  cols 80
  8 rows  5  cols 40
  4 rows  5  cols 20
```

So the tallest band is the equatorial 200-segment band: **160 latitude rows × 1000 longitude
columns**.

**Is the packer's height ceiling the 160-row band limit? No — it is 154, and it is not applied as a
ceiling.**

- `BandPolicySearchEnvelope.boundary_core_height` (`finalize.py:107-113`) = `band.rows - 2*perimeter`
  = `160 - 6` = **154**. That is the largest *unrotated* CORE (pack) height, since `frame_candidates`
  (`finalize.py:115-127`) adds `margin = 2*perimeter = 6` before asking the finalizer.
- 154 is *not* a cap on `_candidate_heights`. `reserve_boundary_height` (`finalize.py:145-160`)
  only ever **replaces the first height it can prove infeasible**, and only when 154 is not already
  in the list. If it proves nothing, the over-ceiling heights stay.

Latitude padding does **not** eat into 154: `_frame_candidates_for_extent` (`finalize.py:2448-2485`)
offers `added_rows in range(5)` with every south/north split, and sorts candidates by frame *area*
first, so the zero-padding candidate is always tried first and padding is never forced.

---

## 2. Where the extra rows come from — measured, per pack

Instrumented the copy at four points (seed gate, post-pack outline gate, `_prepare`'s core gate, and
`finalize_placement`'s entry) and ran:

```
PHASE_E_TRACE=1 .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 1 \
    --only universe-matrix --strategy freeform --json trace.jsonl
```

Load before the run (the box is never idle):

```
 13:47:33 up 18 days, 19:33,  9 users,  load average: 4.21, 3.99, 4.45
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 4  1      0 1039353840  0 8423716   0    0 49783 15284 23402   4  5  2 93  0  0  0
 4  0      0 1039341360  0 8423720   0    0   228   636 14621 27283 3 0 97  0  0  0
 4  0      0 1039329916  0 8423720   0    0     0     0 14539 27594 3 0 97  0  0  0
```

### The height schedule (all three cells)

```
[TRACE] HEIGHTS strips=43 ordered=(125, 160, 100, 80, 60) seed_widths={125: 258, 160: 258, 100: 292, 80: 342, 60: 439} min_widths={125: 92, 160: 92, 100: 101, 80: 126, 60: 168} boundary=154 frames_at_min={125: 30, 160: 15, 100: 30, 80: 30, 60: 15} out=(125, 160, 100, 80, 60)
[TRACE] HEIGHTS strips=42 ordered=(128, 100, 80, 64, 48) seed_widths={128: 202, 100: 223, 80: 254, 64: 275, 48: 332} min_widths={128: 76, 100: 76, 80: 84, 64: 105, 48: 139} boundary=154 frames_at_min={128: 30, 100: 30, 80: 30, 64: 30, 48: 30} out=(128, 100, 80, 64, 48)
[TRACE] HEIGHTS strips=43 ordered=(148, 93, 116, 74, 55) seed_widths={148: 212, 93: 242, 116: 256, 74: 284, 55: 348} min_widths={148: 76, 93: 94, 116: 76, 74: 119, 55: 159} boundary=154 frames_at_min={148: 30, 93: 30, 116: 30, 74: 30, 55: 15} out=(148, 93, 116, 74, 55)
```

Group ↔ cell mapping (from strip counts and coater counts in the `PREPARE` traces, cross-checked
against the audit's refusal texts): group 1 = `no-proliferator` (43 strips, 0 coaters), group 2 =
`all-products` (42 strips, 69 coaters), group 3 = `output-products` (43 strips, 2 coaters).

**`out == ordered` for all three: `reserve_boundary_height` replaced nothing.** For
`no-proliferator` it walked `125` (30 frames at width 92 → feasible → `continue`), then `160`
(**15** frames at width 92 → still feasible → `continue`), then 100/80/60, and returned unchanged.
`160 > boundary 154` survived.

Why 15 and not 0 at `h=160`: `frame_candidates(92, 160)` asks
`_frame_candidates_for_extent(98, 166, policy)` (`finalize.py:2448`), which asks
`_primary_band_for_extent(98, 166, policy)` (`finalize.py:2399-2412`) → `planet.band_for_extent`
(`planet.py:370-405`) which **tries both orientations**: rotated, the extent needs
`min(98,166) = 98` rows and 166 columns, and the 200-band holds 160 rows × 1000 columns. It fits.
`_frame_candidate_for_primary` (`finalize.py:2415-2444`) then emits the 15 rotated frames
(2 orientations × 15 padding splits, minus the 15 unrotated ones that need 166 rows). **The
rotation allowance is the whole reason height 160 is not proved infeasible.**

### Where 160 becomes 162

```
[TRACE] SEED h_cand=125 arr=0 seed.w=258 seed.h=125 outline=258x121 frames=15 ceiling=154 heights=[125, 160, 100, 80, 60]
[TRACE] SEED h_cand=160 arr=0 seed.w=258 seed.h=160 outline=258x156 frames=0  ceiling=154 heights=[125, 160, 100, 80, 60]
[TRACE] SEED h_cand=100 arr=0 seed.w=292 seed.h=100 outline=292x100 frames=15 ceiling=154 heights=[125, 160, 100, 80, 60]
[TRACE] SEED h_cand=80  arr=0 seed.w=342 seed.h=80  outline=342x79  frames=15 ceiling=154 heights=[125, 160, 100, 80, 60]
[TRACE] SEED h_cand=60  arr=0 seed.w=439 seed.h=60  outline=439x58  frames=15 ceiling=154 heights=[125, 160, 100, 80, 60]
```

The arithmetic, exactly:

| contributor | rows | source |
|---|---|---|
| greedy shelf pack of 43 strips at candidate height 160 | **156** | `_greedy_pack` `freeform.py:3044`, measured by `strip_outline` `freeform.py:17475-17480` |
| `_ENTRY_RING` south margin | +3 | `BandPolicySearchEnvelope.frame_candidates` `margin = 2*self.perimeter`, `finalize.py:120` |
| `_ENTRY_RING` north margin | +3 | same |
| latitude padding (`south_padding`/`north_padding`) | **+0** | never reached — `_frame_candidates_for_extent` returns `()` before any padding is chosen |
| band clearance rows / power poles / coaters / routed belts | **+0** | none exist yet; this is a *pre-pack seed* rejection |
| **total** | **162** | `264 = 258 + 6` columns |

The refusal object is built by `BandPolicySearchEnvelope.extent_failure` (`finalize.py:130-142`) →
`_extent_failure_for_dimensions` (`finalize.py:2784-2816`) → `planet.band_for_extent(264, 162)`
raising `BandRefusal` → `ProjectionFailure(check="game.blueprint_area", band=0, detail=str(exc))`.
It is retained at `freeform.py:17771-17778` and reported at `freeform.py:17028`.

Note `_frame_candidates_for_extent` on `264x162` **also** offers no rotated escape: rotated it needs
264 latitude rows.

**Width is nowhere near binding.** The 200-segment band holds **1000 columns**. The widest extent
this cell ever produced is `439 + 6 = 445`. Column capacity never fails on any universe-matrix cell.

**`finalize_placement` never ran on this cell.** The instrumented `finalize_placement` entry trace
(bounds + candidate count) printed **zero lines** across all three cells — no pack ever reached
compaction/finalization, because every routed pack stranded nets first (§3). `_prepare`'s own core
gate (`freeform.py:14269-14282`) also never fired; the largest core it saw for `no-proliferator` was
`256x120`:

```
[TRACE] PREPARE pack.w=258 pack.h=125 coaters=0 core_bounds=(1, 0, 256, 119) (256x120) after_extend=(1, 0, 256, 119) (256x120) boundary_core_height=154
[TRACE] PREPARE pack.w=439 pack.h=60  coaters=0 core_bounds=(1, 0, 437, 56)  (437x57)  after_extend=(1, 0, 437, 56)  (437x57)  boundary_core_height=154
```

---

## 3. Is the rotated orientation relevant? Would a legal height wire?

**Rotation is relevant, and it is the proximate cause.** `band_for_extent` deliberately tries both
orientations (`planet.py:379-390`), which is correct for a real placement. It is *wrong as a
feasibility witness for a height*, because the witness width (`_minimum_pack_width` = 92) is three
times narrower than anything the packer will actually produce (258). The rotation that "saves"
height 160 is only available to a pack ≤ 154 wide, and no pack of these 43 strips is.

### Experiment E1 — replace the witness with an achievable width

In the copy only, `_band_policy_candidate_heights` was changed to
`max(_minimum_pack_width(strips, h), seeds[h].width)` behind `PHASE_E_SEEDWIDTH=1`. The greedy seed
width is a *constructive* width the packer has already realised.

```
[TRACE] HEIGHTS strips=43 ordered=(125, 160, 100, 80, 60) min_widths={125: 258, 160: 258, 100: 292, 80: 342, 60: 439} boundary=154 frames_at_min={125: 15, 160: 0, 100: 15, 80: 15, 60: 15} out=(125, 154, 100, 80, 60)
[TRACE] SEED h_cand=154 arr=0 seed.w=258 seed.h=154 outline=258x153 frames=3 ceiling=154 heights=[125, 154, 100, 80, 60]
```

Height 160 is replaced by the boundary 154, the 154 seed (`258x153` → extent `264x159`) passes with
3 frames, and it is packed and routed. The audit message becomes honest:

```
REFUSED  universe-matrix/no-proliferator power=1 budget=30s  no packing of 43 strips could be
wired at any candidate height; every pack the sweep produced left nets unrouted.
```

No `game.blueprint_area` anywhere. All three cells still refuse, for routing.

### Heights tried and their routing outcomes

`failed = result.routing.failed_count` (`freeform.py:18157`):

**Baseline (master behaviour):**
```
[TRACE] ROUTE h_cand=125 arr=0 pack=258x125 failed=6 status=stranded route_s=0.43   # no-proliferator
[TRACE] ROUTE h_cand=100 arr=0 pack=292x100 failed=6 status=stranded route_s=0.50
[TRACE] ROUTE h_cand=80  arr=0 pack=342x80  failed=6 status=stranded route_s=0.32
[TRACE] ROUTE h_cand=60  arr=0 pack=439x60  failed=6 status=stranded route_s=0.28
[TRACE] ROUTE h_cand=128 arr=0 pack=202x128 failed=3 status=stranded route_s=0.83   # all-products
[TRACE] ROUTE h_cand=100 arr=0 pack=223x100 failed=3 status=stranded route_s=0.83
[TRACE] ROUTE h_cand=80  arr=0 pack=254x80  failed=3 status=stranded route_s=0.82
[TRACE] ROUTE h_cand=64  arr=0 pack=275x64  failed=3 status=stranded route_s=0.69
[TRACE] ROUTE h_cand=48  arr=0 pack=332x48  failed=3 status=stranded route_s=0.84
[TRACE] ROUTE h_cand=148 arr=0 pack=212x148 failed=6 status=stranded route_s=0.36   # output-products
[TRACE] ROUTE h_cand=93  arr=0 pack=242x93  failed=6 status=stranded route_s=0.30
[TRACE] ROUTE h_cand=116 arr=0 pack=256x116 failed=6 status=stranded route_s=0.30
[TRACE] ROUTE h_cand=74  arr=0 pack=284x74  failed=6 status=stranded route_s=0.30
[TRACE] ROUTE h_cand=55  arr=0 pack=348x55  failed=6 status=stranded route_s=0.31
```

**E1 adds exactly one line and changes nothing else:**
```
[TRACE] ROUTE h_cand=154 arr=0 pack=258x154 failed=6 status=stranded route_s=0.35
```

**Answer: no.** The legal height 154 packs and routes and strands the same 6 nets as every other
height. Height is not the lever for this cell.

---

## 4. The other two freeform universe-matrix policies

Neither is at or over the ceiling.

| cell | strips | coaters | heights tried | largest core (post-`_prepare`) | largest EXTENT | ceiling | stranded nets |
|---|---|---|---|---|---|---|---|
| `no-proliferator` | 43 | 0 | 125, **160**, 100, 80, 60 | `256x120` @h=125 | `262x126` — but the **seed** at h=160 is rejected at `264x162` | 154 core / 160 rows | 6 at every height |
| `all-products` | 42 | 69 | 128, 100, 80, 64, 48 | `202x137` @h=128 (`_extend_core_for_unique_proliferator_roots` raised 127 → 137) | `338x143` @h=48 | 154 core | 3 at every height |
| `output-products` | 43 | 2 | 148, 93, 116, 74, 55 | `210x145` @h=148 | `216x151` | 154 core | 6 at every height |

`_extend_core_for_unique_proliferator_roots` (`freeform.py:16102-16117`) raises `all-products`'
core to `4*(35-1)+1 = 137` rows for 69 coaters, and it is **correctly clamped** by
`boundary_core_height` (154), so it never overruns. `PREPARE` traces confirm `after_extend` height
137 for every `all-products` height.

So only `no-proliferator` hits the band, and only through the un-filtered candidate height 160.

---

## 5. Design options

### (a) Tighten the reservation witness to an achievable width — **RECOMMENDED**

`_band_policy_candidate_heights` (`freeform.py:18799-18815`) passes
`max(_minimum_pack_width(strips, h), _greedy_pack(strips, h).width)` — or, equivalently, the seed's
`strip_outline` width — as `minimum_width_for_height`. The greedy seed is *constructive*: a pack of
that width at that height exists, so a height whose seed extent fits no band is a height where the
sweep's own first move is illegal.

- **Exactness:** unaffected. This only changes which candidate heights are *searched*. Every pack
  still passes `_prepare`'s core gate (`freeform.py:14281`), `finalize_placement`'s frame
  certification (`finalize.py:2832`) and the validator. It can never emit an illegal blueprint; the
  worst case is that a tall-narrow height that CP-SAT could have packed narrower than greedy is
  swapped for the boundary height 154 (which is always legal and is the tallest legal height).
- **Area cost:** none measured. E1 produced `258x154` where master produced nothing at that slot.
- **Files/functions:** `src/flab2bp/layout/freeform.py` `_band_policy_candidate_heights` only
  (2 lines). `seeds` is already computed in that function.
- **Deterministic unit test:** extend
  `tests/layout/test_finalize.py:2080` `test_portable_schedule_reserves_the_tallest_legal_core_boundary`
  with a sibling that uses a *narrow* witness — this is exactly the gap the existing test hides: it
  passes only because its witnesses are 380..522 wide, wide enough to defeat rotation. Add
  `test_portable_schedule_reserves_a_boundary_when_only_rotation_admits_the_height`:
  `ordered=(125,160,100,80,60)`, `minimum_width_for_height={...160: 92...}` → assert the current
  code returns `(125,160,...)` and the fixed code returns `(125,154,...)`. Plus a freeform-level
  test beside `tests/layout/test_freeform.py:16136` asserting that for every height
  `_band_policy_candidate_heights` returns, `envelope.frame_candidates(*strip_outline(greedy(h)))`
  is non-empty. All pure functions; no wall clock.
- **Cell-level proof:** `uv run python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix
  --strategy freeform --json out.jsonl` — the `no-proliferator` row's refusal must no longer mention
  `game.blueprint_area` and its `projection_failures` must be empty; the extents in the trace must
  all be ≤ 160 rows. (Verified in the copy: E1 output above.)

### (b) Make the finalizer choose zero padding when the band is full

Not applicable and would fix nothing. `_frame_candidates_for_extent` (`finalize.py:2448-2485`)
already enumerates `added_rows = 0` first and sorts by frame area, and the failing path never
reaches padding selection at all — `264x162` has **no** primary band, so the candidate set is empty
before any `south_padding`/`north_padding` is considered. Zero cost, zero benefit.

### (c) Do not retain a pre-pack seed rejection as a "wired then rejected" refusal — **RECOMMENDED alongside (a)**

`freeform.py:17766-17779` retains an `extent_failure` from the *seed* gate into `rejected`, and
`freeform.py:17026-17036` reads a non-empty `rejected` as "every packing that **wired** was rejected
by our own validator". Nothing wired. Give the seed gate its own list (`skipped_heights`) that is
reported as "N candidate heights were skipped as over-band" but does not suppress the routing
diagnosis; or drop the retention entirely, since the post-pack gate at `freeform.py:17911-17925`
already covers a real pack.

- **Exactness:** message-only; no geometry changes.
- **Area cost:** none.
- **Files/functions:** `src/flab2bp/layout/freeform.py` `FreeformLayout._sweep` (the retention at
  17771) and the `rejected` narration at 17026.
- **Deterministic unit test:** a fixture spec whose seed at one height is over-band and whose packs
  strand a net; assert the raised `NoValidLayout` message names the router, and that
  `projection_failures` is empty. No clock.
- **Cell-level proof:** the same audit command; the message must be the routing one.

### (d) Reject the over-ceiling pack before routing

Already the case, and it costs nothing to fix — the seed gate at `freeform.py:17766` fires *before*
`_pack`, so no solver, router or finalizer time is spent on the illegal height. The measurable cost
of the bug is only (i) the wrong headline and (ii) one of five candidate slots wasted. Listed for
completeness; nothing to do.

**Recommendation: (a) + (c).** (a) recovers the wasted slot with a legal 154-row candidate and makes
the ceiling actually bind; (c) makes the refusal say what is really wrong. Together they turn this
cell from "a band bug" into an honest, correctly-attributed router refusal — which is where Phase E
work should then go.

---

## 6. What actually stops this cell wiring, at any legal height

`result.routing.failures` for `no-proliferator` at every height is **six `static-access`
failures**, and they are the *same six* at h=60 as at h=154:

| stranded net | destination cell | wall | blocking nets |
|---|---|---|---|
| `hydrogen` `mass-energy-storage#23` → `casimir-crystal#1` | `(1, 10, 0)` | 5 | `graphene#15→casimir-crystal#1`, `titanium-crystal#34→casimir-crystal#1` |
| `hydrogen` `mass-energy-storage#23` → `energy-matrix#12` | `(1, 113, 0)` | 4 | `energetic-graphite#11→energy-matrix#12` |
| `hydrogen` `plasma-refining#28[0]` → `casimir-crystal#1` | `(1, 10, 0)` | 5 | same two |
| `hydrogen` `plasma-refining#28[1]` → `energy-matrix#12` | `(1, 113, 0)` | 4 | `energetic-graphite#11→energy-matrix#12` |
| `hydrogen` EXTERNAL → `casimir-crystal#1` | `(1, 10, 0)` | 5 | same two |
| `hydrogen` EXTERNAL → `energy-matrix#12` | `(1, 113, 0)` | 4 | `energetic-graphite#11→energy-matrix#12` |

Every failure is a **`hydrogen` net into one of exactly two destination strips**, blocked at a
**fixed destination port** by the *other* input lanes of that same strip. `all-products` shows the
identical pattern with `CargoDomain.REQUIRES_SPRAY` and 3 failures, all into `casimir-crystal#1`.

Two structural facts follow:

- This is a **per-strip input-port crowding** defect (the `casimir-crystal` strip wants graphene +
  titanium-crystal + hydrogen and only two lanes reach it; `energy-matrix` wants energetic-graphite
  + hydrogen), not a packing-density or band problem. Neither height, width, arrangement nor clock
  moves it.
- **The sweep uses ~3 s of its 30 s budget.** `freeform.py:17729` —
  `if not projection_retry and arrangement and best is None: break` — means arrangements 1 and 2
  (`_ARRANGEMENTS = 3`, `freeform.py:388`) are never attempted once arrangement 0 fails at every
  height. `no-proliferator` refuses at 2.5-3.4 s of a 30 s budget in every run above. So the cell is
  not budget-starved; it is out of *candidates*, and giving it more clock is provably useless.

Non-issues, ruled out by measurement: **band width** (1000 columns vs a 445-column worst case),
**strip count** (43 strips pack fine at every height), **widest strip** (`_minimum_pack_width` floor
is 168 at h=60, i.e. the widest box is ≤ 168), **coater seating** (`no-proliferator` has 0 coaters),
**power coverage** (no `_Unpowerable` raised), and **latitude padding** (never reached).

---

## Appendix — commands run

```bash
# baseline on the checkout (read-only)
uptime; vmstat 1 3
uv run python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix \
    --strategy freeform --json base.jsonl

# throwaway copy
mkdir -p <scratch>/phase-e-R1
git -C /home/dannyb/sources/factorio-lab-to-blueprint archive HEAD | tar -x -C <scratch>/phase-e-R1
cp src/flab2bp/layout/_*.cpython-314-x86_64-linux-gnu.so <scratch>/phase-e-R1/src/flab2bp/layout/

# instrumented runs (copy only)
PHASE_E_TRACE=1 /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python \
    <scratch>/phase-e-R1/scripts/audit.py --budget 30 --jobs 1 --only universe-matrix \
    --strategy freeform --json trace.jsonl
PHASE_E_TRACE=1 PHASE_E_SEEDWIDTH=1 /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python \
    <scratch>/phase-e-R1/scripts/audit.py --budget 30 --jobs 1 --only universe-matrix \
    --strategy freeform --json traceE1.jsonl

# band table
uv run python -c "from flab2bp.dsp import planet; [print(b.area_segments, b.rows, b.columns) for b in planet.bands()]"
```

Baseline audit output on master (verbatim, `--jobs 3`):

```
  X [  1/3]     4s freeform  stress   universe-matrix/no-proliferator power=1 budget=30s   REFUSED    2.8s
  X [  2/3]     5s freeform  stress   universe-matrix/output-products power=1 budget=30s   REFUSED    3.6s
  X [  3/3]     7s freeform  stress   universe-matrix/all-products power=1 budget=30s      REFUSED    6.0s

=== freeform: 0/3 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
    REFUSED  universe-matrix/no-proliferator power=1 budget=30s  every packing that wired was
    rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area ():
    a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better
    orientation and the tallest band (200 segments) holds 160. The game refuses this paste with
    EBuildCondition.BlueprintAreaCrossTropic.); ...
```

Load records for the timed runs are inline in §2 and were taken before each; a representative set:

```
 13:39:16 up 18 days, 19:25,  9 users,  load average: 3.27, 2.83, 4.36   (baseline)
 13:40:37 up 18 days, 19:26,  9 users,  load average: 6.82, 4.03, 4.64   (trace 1)
 13:45:42 up 18 days, 19:31,  9 users,  load average: 2.79, 3.72, 4.43   (heights trace)
 13:47:33 up 18 days, 19:33,  9 users,  load average: 4.21, 3.99, 4.45   (baseline + E1 pair)
 13:50:22 up 18 days, 19:36,  9 users,  load average: 5.12, 4.19, 4.43   (failure detail)
```
