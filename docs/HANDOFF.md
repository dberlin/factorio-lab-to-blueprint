# flab2bp handoff — 2026-08-23, evening

**Repo:** `/home/dannyb/sources/factorio-lab-to-blueprint`, branch `master`, HEAD `00d1f78`,
**working tree clean.** 24 commits landed today, from `d5b319d`.

The previous handoff is preserved at `../handoff-2026-08-23-morning.md`. Its domain facts are
still good and are carried forward below. **Its numbers are all superseded.**

---

## Verify before you start

```
uv run ruff check src tests scripts        # All checks passed
uv run mypy --strict src tests             # Success: 73 source files
uv run pytest -p no:randomly -q            # green, 41-58s
uv run python scripts/audit.py --strategy spine --budget 4 --jobs 16 --quiet   # 72/72
```

`bun` and a `../dsp-blueprint-viewer` checkout are both present on this machine, so
cross-validation against the independent TypeScript decoder is **live** — five `bun`-marked
tests that used to skip now run. If you move machines and lose that checkout you lose the only
check on our codec that our own decoder does not share assumptions with.

---

## Honest numbers, as of `00d1f78`. I ran every one of these myself.

| | this morning | now |
|---|---|---|
| spine, budget 4 | 67/72 | **72/72** |
| spine, budgets 1/2/4/15 | — | **288/288** |
| freeform, budget 4 | 56/72 | **66–69/72** (see below) |
| INVALID, either strategy | 0 | **0** |
| `flow.conservation` islands, quantum-chip/free-prolif | ~3.5% of builds | **0 in 608** |

**Freeform moved twice this evening and the figure above is the latest.** The progression, all
measured: 56 this morning → 60 after the west channel → 62–66 after the linking work → **66–69
after `cc1d8ed` (mixed-lane merges) and `f346c50` (starved shards)**, with the canonical gate
returning **67/72 three times running**. `universe-matrix` produced its **first ever clean
cell** after `f346c50` — I reproduced 1/6 clean on a `--budget 15` run myself.

**Never quote a single run.** One measurement is worth ±2 cells, and area is worse: the
corpus's own area noise floor is a **median 1.84%, max 21.08%** on an identical configuration
(`universe-matrix` 19.5%, `quantum-chip` up to 21.1%, though 11 of 24 cells are exactly
deterministic). **Establish the noise floor before believing any density comparison** — two
separate measurements today were reframed by it, and one conclusion of mine was overturned
outright.

**Spine is NOT deterministic, and an earlier draft of this document said it was.** I wrote
"deterministic enough that 72/72 reproduces"; it then returned **71/72 once in five
consecutive runs** at `--budget 4 --jobs 16`, the refusal on `universe-matrix`. The other four
were clean. The mechanism was already identified this afternoon and never cleared:
**`lay_out`'s deadline is `now + max(budget, RETRY_BUDGET_S)` in WALL-CLOCK**, so a loaded box
eats the search budget. The spine agent saw the same shape — load-correlated `universe-matrix`
refusals in runs where cells took 69s against a typical 45s — and said plainly it could not
prove they were not its own. They were not: this happened with `spine.py` untouched since.
Treat spine as ~1-in-5 at that config under load, not as a fixed 72/72, and **do not read a
single 71/72 as a regression** without re-running.

The suite runs **45.9–47.9s** on a quiet machine (three consecutive runs after the `certify`
work), against a 60s ceiling. But I measured **61.92s** once, with background load — an actual
breach, not a near miss. Earlier readings spanned 41–58s. My hypothesis that
`DEFAULT_SEARCH_WORKERS = 0` made big machines slower was **measured and refuted** (55.7s at 16
cores, 55.8s at 32, 50.2s at 128). It is solver nondeterminism plus whatever else is running.
The ceiling is a live risk under load and nobody has costed a remedy.

**The general rule both of these teach:** every gate in this project is timing-sensitive, so a
single bad result is a hypothesis, not a finding. Re-run before you believe a regression — and
re-run before you believe a fix.

---

## THE RULE THAT MATTERS MOST — unchanged, and it held all day

**There is no fallback. There will not be one. It has been deleted twice** (`7fa18c9` spine,
`d5b319d` freeform). Do not reintroduce either, and do not invent a third under a new name.

The argument that keeps bringing it back is "a *checked* fallback differs in kind — it's
validated, so it's safe, and a loose blueprint beats no blueprint." Wrong twice:

1. The check proves only that the fallback output is not broken. It says nothing about **why
   the solver had nothing to return**, which is the only question worth asking.
2. It is bought in the currency this program exists to minimise. Measured: spine's seed
   fallback **50,512 tiles** vs ~39,000 solved; freeform's `_loose_sweep` **8786–11628** vs
   4960–6120 solved.

**A distinction that came up today and is worth keeping straight:** `validate.certify` running
on `lay_out`'s own output before it returns is **not** a fallback and is **not** a forbidden
post-pass. Spine always did it; freeform gained it in `e1174f0` and that was correct. Emitting
a *looser* layout hides a defect; checking your own output *surfaces* one. Opposite things. An
agent nearly removed it on that confusion.

### The rule's other half: **unroutable anything is a bug**

**Feasible = routable.** A spec the rate solver accepted is a spec that must lay out. Every
refusal is a defect in OUR code — the packer, the router, or the net planning — and never a
property of the spec or a fact about the world.

This is stated because the language for describing failures keeps drifting into excuses, mine
included. Watch for these, all of which appeared in this project's own prose today:

* *"clock-bound"* — a cell that cannot route inside its deadline is a bug in the router or the
  packer. The deadline is not a natural limit; it is a budget our code failed to work inside.
  I wrote this one about `universe-matrix` and it reads like an acceptable outcome. It is not.
* *"a structural limit in the row model"* — that was spine's refusal text for a bug fixed in
  `57c3f3e`. The limit was a missing height term in a constraint, not structure.
* *"the packer cannot feed this arrangement"* — then the packer is wrong.
* *"this spec is hard"* — never an answer.

A refusal is the correct *behaviour* when we cannot produce a valid layout — far better than a
fallback — but it is never a correct *outcome*. Report it precisely enough that someone can
fix it, and treat every one as open work.

---

## What changed today

### The rate solver was lying about magnitudes (`a049bb6`, `7d2a5a3`, `aec89bf`)

`_exact_rates` took only *structure* from the MILP and re-derived every magnitude by a
hand-rolled fixed-point iteration, `len(internal_items) + 8` rounds. On a recipe cycle that
diverges geometrically. Measured, varying only the loop bound: **+8 → 732,268 machines, +10 →
2,928,937, +12 → 11,715,615, +14 → 46,862,330** — exactly ×4 per +2 iterations. There was no
732,268-machine plan; that figure was purely where the loop stopped.

Two real defects, the second hiding the first. The balance equation **double-counted**: a
maker's own draw on the item it makes was charged to the requirement *and* netted out of its
supply. For the 491 of 493 recipes that do not consume what they produce that is identical
arithmetic. The two that do are `reforming-refine` (refined-oil in 2 / out 3) and
`x-ray-cracking` (hydrogen in 2 / out 3) — I verified that count independently.

Now: **the MILP's integer machine counts are authoritative**, and the balances are one exact
rational LP via `sympy.solvers.simplex.linprog`. Cycles are ordinary matrix entries.

`aec89bf`: SCIP returning FEASIBLE rather than OPTIMAL used to raise, throwing away a
buildable factory for a proof we do not need. It now warns and proceeds — `universe-matrix`
sits at ~25s of a 30s budget and tipped over under load. A solve returning *nothing* usable
still raises.

### Spine (`5fb2d3c`, `a6f761a`, `57c3f3e`, `bcea40d`)

`5fb2d3c` — the whole budget was going to CP-SAT **presolve probing**, so no solve ever reached
its search phase and every width returned UNKNOWN, reported as "no feasible row assignment".
`cp_model_probing_level = 0`. Measured 0/6 clean at 4s, 4/6 at 30s, 5/6 at 120s before;
72/72 after. This model states its implications explicitly, so probing rediscovered ~10,900
Booleans' worth of what was already written down.

`57c3f3e` — the row packer's tap-capacity constraint was a flat `2 * reach` (6 lanes), correct
only when every machine in a row is the same height. An `oil-refinery` is 3×**7**, an
`arc-smelter` 3×**3**; a short machine in a tall row loses reach into one corridor. The bound
is now `lanes with gap >= t  <=  reach + max(0, reach - t)` per threshold, mirroring
`_fits_below` exactly (so the "three lanes at a gap of 2" case is preserved). Area cost +0.53%,
**inside the baseline's own 2.3% run-to-run spread** — not a measured cost.

### Freeform (`e1174f0`, `a834293`, `3f04239`, `00d1f78`, and three measured reverts)

- `a834293` — three altitudes existed and the router used one, then could not cross its own
  belts. A quarter-tile toll on ground level sends through-traffic upstairs. Biggest single
  win, and it **gained** density (casimir 5760 → 4875).
- `e4f07bf` — `WEST_CHANNEL = 1`. Every net runs output-lane-east to input-lane-west, and with
  a margin on the east face only, one column served both faces: two ports fighting over their
  only access cell, the loser getting an empty frontier so A\* returned `None` having expanded
  zero nodes — which rip-up can never price, because a search that expands nothing registers no
  conflict.
- `3f04239` — `_sink_for` emitted a deliberately-broken link when a path reached nothing and
  `_commit_paths` counted only *source-side* failures, so it reported `failed=0`. That is how a
  pack with belts linking 40 tiles across the block got ranked and returned.
- `00d1f78` — `_source_for` took *the first adjacent belt carrying the right item*; at a merge
  point several do. It fed a joining net from the other shard's own path into the same lane — a
  one-tile belt taking items off a lane and handing them straight back. Adjacent, acyclic,
  right item, both counters green. The scan had to be **restricted** to source-lane siblings,
  not reordered; preferring siblings would still have picked the wrong belt.

### Elsewhere

- `b1b4188` — `power.connectivity` used `min` of the two reaches where `OnNodeAdded` uses
  **`max`** (a Wireless Power Tower pulls a Tesla Tower in at 45.5, not 22.5). Latent, not
  live: we place Tesla Towers only, and it flips none of the four mixed-reach fixtures. Fixed
  because the code is already written for mixed towers.
- `bd36452` — the URL's proliferator tier was parsed and discarded; every build got Mk.III
  whatever the player selected. The sprayed item is belted in from outside, so that shipped
  plans asking for an item they may not have. Read from **three** places: `mps=` lands in
  `proliferator_spray_id`, a `z=` URL lands in `modules` and/or each machine's own `modules`.
  Absence is **not** a constraint (11 of 12 corpus URLs name no proliferator). Mode is
  deliberately left free — it is the frontier's optimisation dimension and costs the player
  nothing they did not authorise.
- `70fc732` — deleted the PackingSolver experiment, 546 lines. It was rejected in `d72859f`:
  identical pack (same width, height, area) and **44% worse routing**, because a
  connectivity-blind arrangement costs more in routing than it saves in packing. That is an
  argument about connectivity, so a better external packer would not change it.
- `1b5062a` — `scripts/audit.py --only` / `--skip` by url_id. A six-cell question cost a
  72-cell run before; an agent called this the single highest-value change available.
- `c82f2fd` — the audit's trailing line claimed slow cells meant "a lay_out that does not
  honour time_budget_s". Measured false, on ~25 cells a run.
- `332f12d` — audit budgets from `sched_getaffinity`, not `os.cpu_count()`, so `taskset` stops
  silently oversubscribing.

---

## The pattern worth internalising

**Four of six defects today were things that looked fine because something was lying**, and in
three cases the lie had been "confirmed" against itself:

- presolve eating the budget, reported as "no feasible row assignment"
- a diverging iteration, reported as 732,268 machines
- `_commit_paths` counting one side, reported as `failed=0`
- `min` where the DLL says `max`

Add the two from the previous handoff (the bake-off that scored layouts the validator had
rejected; the counter that "proved" direct insertion never fired when it fired 17 times) and
the house rule writes itself: **verify the instrument before believing the measurement.** An
agent today caught its own test reading green against the bug it was pinning — it had
pre-placed a belt on the head cell, so `canvas.free` rejected the path and nothing was linked.
It only found that by running the test against the *unfixed* code. Do that every time.

---

## Open work, in the order I would do it

1. **Freeform's router cost model.** The big one, worth ~6 cells. Established by flooding the
   free space *before any belt exists*: all 197 ports of `universe-matrix/no-proliferator` sit
   in one connected 54,077-cell component, so **the packer is not the problem** — every pocket
   the router fails in was cut out by its own committed paths. It cannot price that, because a
   committed path is marked `blocked` rather than expensive, so negotiated congestion's history
   term is **identically zero**. Charging for board-cutting was built and is decisive on the
   target pack (1 unrouted → **0**, and routing got *faster*, 42.4s → 24.4s) but measured worse
   corpus-wide (64/66/64 vs 66/66/66) because the wall census is four dict lookups per settled
   cell across thousands. **The concept is right; the implementation is too expensive.** Next
   move — bound walks per round, or collect the wall during expansion — is written into the
   code at the site (`43b3f4e`, `69d7303`).
2. ~~**`--candidates 4`**~~ — **ANSWERED: no. Do not raise it.** Measured over 2,592 layouts,
   9 reps, both budgets, both power settings, and recorded on `DEFAULT_CANDIDATES` in
   `rates/candidates.py` (`9b122ff`) so nobody re-asks.
   * The chosen area **did not move in 187 of 216 cells**; corpus median saving **+0.058%**.
   * **The null arm settles it:** re-running the *same three* candidates and keeping the
     smaller saves **1.10%**; adding a fourth saves **0.67%**. The fourth candidate buys less
     density than another roll of the dice on the three already there.
   * Cost: **+33% layout wall-clock** (every strategy lays out the extra spec). No new
     refusals — 0 of 324 cells lost a valid layout.
   * **My 12.6% figure was wrong, and instructively so.** I measured `all-speed-mode` against
     spine only. Freeform lays that same URL out in **2,430 tiles** against spine's 4,074, so
     under the default `strategy="best"` the fourth candidate wins a race nobody runs. It
     gains **exactly 0.00%**, 9/9 reps. When comparing candidates, compare the way
     `pipeline.build` actually chooses: `min` over every *(candidate, strategy)* pair.
2a. **`_connect_short_cuts` chains islands in arbitrary order — READY TO APPLY, patch below.**
   A **latent correctness bug `flow.conservation` structurally cannot report.** It chains
   islands in union-find root order, an implementation artefact, where `_join_shard_islands`
   (`f346c50`) chains in descending balance so each edge runs surplus→deficit.
   * **Not live today:** 10 firings across 36 specs, root order coincided with
     descending-balance order in **10/10**.
   * **Abundantly reachable:** over **8,620,618** reachable firing configurations (machine
     vectors `plan_strips` can actually emit), **53.4% emit a backwards edge** and **83.5%
     emit an edge out of a deficit island**. Smallest case: producer `machines=[1,1]`,
     consumer strips `machines=[2,1]`, any rates.
   * **Nothing catches it.** `validate._islands` (`validate.py:2082`) unions
     `(s.input_obj, s.output_obj)` **without regard to direction**, so a backwards belt merges
     exactly the same two islands and `flow.conservation` passes identically.
   * **Physical consequence:** the belt runs from the starving island's producer into the
     satisfied island's consumer. Backpressure makes it inert — the receiving consumer is
     already fed — so the shortfall it was emitted to fix stays unfixed while the validator
     reports clean.
   * **Fix**, at `freeform.py` ~4135–4143 (function at 4071). Hoist the arithmetic the
     `any(...)` already computes inline, then order by balance:
     ```python
     balance = {
         r: sum(srcs[i].machines for i in mine) * out_rate
         - sum(sinks[j].machines for j in theirs) * in_rate
         for r, (mine, theirs) in islands.items()
     }
     if all(v >= 0 for v in balance.values()) or len(islands) < 2:
         return []
     order = sorted(islands, key=lambda r: (-balance[r], r))
     ```
   * **Risk, measured:** emitted pairs **identical on 36/36** cells, all 10 firings unchanged,
     strip plans identical, 186 unit tests pass. Fault injection proves it is not a no-op —
     on `srcs=[1,1] / sinks=[2,1]` the current code emits `(0,1)`, draining the starving
     island; the fix emits `(1,0)`. **Pin it with a test on that shape**; it goes red against
     the current code. Line numbers are against `f346c50` — re-locate before applying.

2b. **`_shard_sinks` preferring `_merge_lanes` — MEASURED, DO NOT DO IT.** Proposed by the
   agent that wrote `f346c50` as the cheaper answer to starved shards. It is not.
   * **Zero slack is 99.2% of producers** (354 of 357), so "prefer merge when there is no
     slack" is not a targeted rule — it is *stop sharding*, corpus-wide.
   * **The "zero extra belts" claim is backwards.** One shard means every strip of the group
     carries every lane: energetic-graphite's 21 machines go from 2 shards × (1+3) strips
     carrying 8 lanes to 4 strips carrying 12. Measured **+82 to +114 nets (+10.9% to
     +15.2%)** against 7 join nets saved.
   * **It loses cells.** Interleaved A/B, 12 cells × 12 rounds: base **137/144** vs merge
     **121/144**; worse in 8 rounds, better in **0**, sign test **p = 0.0078**. It fires on
     `plasma-refining` in casimir-crystal and quantum-chip — URLs where
     `_join_shard_islands` never fires, so they pay pure cost. 0 INVALID either arm; the
     failure is `_merge_lanes` raising → REFUSED.
   * It would make `_join_shard_islands` dead on the corpus — a **cost**, not a benefit:
     deleting a proven guard (it bought `universe-matrix/no-proliferator`'s first clean
     layout) for a preference that loses cells on URLs it does not help.

3. **`_source_for`'s last fallback** still returns `net.src.belt` even when far from the head,
   emitting a cross-map link. Safe — `belt.link_adjacent` catches it and it becomes a refusal,
   never a silent bad build — but it is the one remaining place that function can name a
   building it is nowhere near.
4. **Suite variance** (41–58s vs a 60s ceiling). Cause is solver nondeterminism; my core-count
   hypothesis was measured and refuted. Nobody has costed a fix.
5. **Regenerate `docs/AB_RESULTS.md` / `AB_COMPARISON.md`.** Still stale — they predate both
   fallback removals and everything today. **Do not quote them.** Cheap now, and
   cross-validation would finally make that column real.
6. **A\* speed** — improved 1.8x tonight (`2d321b2`, `80e5086`), still open as a lever.
   `validate.certify` speed is **DONE**: see below.
   **Libraries are permitted here and `numpy` 2.5.2 is already installed;** `rustworkx`
   can be added on request (the user has confirmed this). The 1.8x came from a
   flat-int-index rewrite with no dependency, and the reasons a library may not fit are
   in the previous handoff — 3D with two-cell ramps, per-cell costs that change every
   rip-up round — but **do not hand-roll anything a library provides.** An agent wrote a
   simplex today and it was thrown away; `sympy` is now a dependency because of it.

---

## Corrections to this document, made the same evening

Kept rather than silently edited, because *what was wrong and how it was found* is the most
reusable thing here.

**`certify` speed (was item 6) is done.** It is now **15x faster overall, 18.7x on the largest
placement** (`b147d6d`, `2ca6b28`, `698d82a`). Four checks were 90% of the cost —
`flow.belt_capacity`, `flow.sorter_capacity`, `power.coverage`, `flow.headroom` — and none for
a reason connected to what they decide: rebuilt indices, a genuine quadratic (`of_kind` scanned
every building, once per sorter: 986 × 37,225, twice over), and `Fraction` construction per
tower per tile. Fixed with a per-`validate` `_Cache`, one-pass peer scan, and doubled-integer
coordinates for the tower predicate (`d2 <= floor((2r)²)` — the same predicate, not a
tolerance; **no float anywhere**).

Measured: **7.302s → 0.392s** on 37,225 buildings; I independently measured a 39,320-building
spine build at **0.410s**. Verified verdict-identical two ways — the author's 162 report pairs
and my own independent A/B of 40 comparisons, **0 mismatches**, with **14,981 finding lines
moved by injected damage** proving the oracle was not blind. That last point matters: on clean
input those four checks emit *nothing*, so a clean-only oracle agrees with a deleted check.

So **the numbers "3.8s on a 92,907-tile placement" (item 6 above) and "8.7s to certify a
77,000-tile placement" (`scripts/audit.py::_slow_note`) are both stale by >15x.** The audit
docstring is corrected. The self-check is no longer a meaningful part of the post-deadline
tail — but **emission has not been re-measured**, so do not conclude "emission is the tail
now". Nobody has re-attributed it.

**`quantum-chip/max-proliferation` is NOT a distinguished cell — do not fix it.** Diagnosed
read-only. Under identical conditions (N=32 each) it refuses ~13% against `no-proliferator`
3/32 and `free-proliferation` 1/32, and eight audit repeats over 48 cells produced three
refusals, **none of them `max-proliferation`**. An audit naming it twice is a coin flip, not a
signature. It is the same defect as `universe-matrix`, an order of magnitude milder — the
packer reserves every port's access cells on **36 of 36 packs** (0 walled), and the wall on 165
sealed-pocket failures is **53% the router's own tentative paths**.

Two findings from that work, both actionable:

* **`ee9bc2a` does not help there**, measured interleaved, N=72 per arm: 12.5% vs 15.3%.
  `_BLAME_MAX_WALL = 64` gates on the distinct tentative wall, and all 49 failures in pockets
  ≥1000 cells have a median wall of **1128, 17x the cap**. **Do not simply raise the cap** —
  the uncapped variant was already measured corpus-wide and is worse (mean 65.0 uncapped vs
  65.4 capped).
* **The binding constraint is the clock, not expansions.** Every failure left **4.5–6.0M of 6M
  expansions unspent** (≤25% consumed), while 8–11s of the 15s ceiling went into rip-up rounds
  that never converge — and **a pack oscillating 1→2→1→2 never trips `_RRR_STALE_ROUNDS`**.
  **13 of 25 observed heights DID wire**, so buying more heights inside the ceiling is the
  lever. Unmeasured hypothesis, with the numbers that motivate it.

**Item 1's "next move" was the wrong question, and one command proved it.** The brief was
"make the wall census cheap". Measured with the charge *zeroed* — paying every lookup, changing
no decision — the corpus was unaffected: 66/65/65 against 65/66/65 with it off. **The walk is
free.** The corpus loss was the term's *behaviour*, not its price: a pocket walled by three
cells names a suspect, one walled by three thousand describes the whole corridor network.
`ee9bc2a` caps the blamed wall at 64 cells; corpus-neutral (65.3 vs 65.2 over interleaved
pairs), and it buys the h=69 pack at no cost — 139/140 paths → **140/140**, and faster,
36.7s → 24.6s. **Always measure the null arm before optimising.**

**The next blocker on `universe-matrix` is linking, not pathfinding.** At h=69 every net now
finds a path and **nine cannot attach to anything at the far end**. Different function,
different fix, still worth ~6 cells. Note h=69's failure count went 0 → 9 across `3f04239` and
`00d1f78` purely as *accounting* — those commits stopped counting a path that reaches nothing
as a success — proven by A\* expansion counts being byte-identical across the change
(5,280,277 / 3,622,155 in both sessions).

---

## Domain facts that were expensive to establish — do not re-derive

Carried forward from the previous handoff, all still true:

- **Blueprint format:** `BLUEPRINT:<csv header>"<base64(gzip(payload))>"<MD5F hash>`. MD5F is
  an MD5 variant with 2 altered init constants and 8 altered round constants.
- **Splitters** (2020): the junction records **no links**; belts around it name it, every
  attached belt co-located, slots 14/15, max 4.
- **Sorters:** max reach **3**, not tier-dependent, never span altitudes.
- **`TESLA_LINK_DISTANCE = 22.5`**, from `Assembly-CSharp.dll`. `OnNodeAdded` links on
  `max(a.connDistance2, b.connDistance2)` — a distance, not a diameter, and the **larger** of
  the pair.
- **`tile_to_local_offset`** verified 686/686 sorter endpoints.
- **CP-SAT and `highspy` cannot coexist** — importing both segfaults.
- **`DEFAULT_SEARCH_WORKERS = 0`** is the shipping default, worth ~23% density, nondeterministic
  by design.

New today:

- **Machine footprints that matter to the row model:** `arc-smelter` and
  `assembling-machine-2` 3×3, `matrix-lab` 5×5, `chemical-plant` 7×5, **`oil-refinery` 3×7**.
  That 4-tile spread against a sorter reach of 3 is what `57c3f3e` is about.
  (The plant read 9×5 until the footprint rule stopped treating a tile as one
  world unit; a tile is `GRID_ARC` = 1.2566.)
- **Exactly 2 of 493 recipes consume an item they also produce:** `reforming-refine` and
  `x-ray-cracking`. Both are refined-oil/hydrogen. Any cycle bug will involve them.
- **Two power nodes may not stand within 3.5 WORLD units of each other**, which
  is 2.785 tiles — `EBuildCondition.PowerTooClose`,
  `BuildTool_BlueprintPaste.cs:2547`. Wind-to-wind is 10.5 and
  geothermal-to-geothermal 12.0; accumulators are exempt. **A Tesla Tower has no
  build collider at all**, so `geom.collide` can never see this and the rule
  needs its own check (`game.power_too_close`). Found by shipping: a blueprint
  we generated pasted with all 366 of its other buildings green and two of its
  six towers red. See `docs/RULE_LEDGER.md` §1c and
  `tests/fixtures/ours/power-too-close-freeform.txt`.
- **Sphere projection does not threaten power.** DSP compares a 3D chord between
  sphere-projected nodes, and a chord is always shorter than the surface arc: at 22.5 tiles on
  a standard planet the chord is 22.488, 0.05% short. So our flat check errs **safe** — anything
  we certify as linked will link. I raised this as a risk and it is not one.

---

## Working rules — these are the user's, and they are firm

- **300-second hard timeout cap** on any command, mine or a subagent's. An agent was stopped
  today for 1500s runs. On a 128-core box, wanting longer means the work is serial when it
  should be fanned out.
- **Serena/LSP is mandatory for symbol work, and if it is broken you STOP and say so** — never
  fall back to grep silently. This has now caused problems twice.
- **The `mcp__serena__*` and `LSP` tools are DEFERRED.** Calling one directly fails with
  `InputValidationError`, which reads exactly like "not available" but is not. Load them first:
  `ToolSearch(query: "select:mcp__serena__get_symbols_overview,mcp__serena__find_symbol,...")`.
  Two agents today reported Serena missing when this was all that was wrong. **Put the recipe
  in every dispatch prompt.**
- **Do not hand-roll a solver.** One agent wrote a simplex today because "CP-SAT has no
  fractions and sympy is not a dependency". `sympy` is now a dependency (`ae63738`). If it is
  ever too slow, z3's optimisation support is next — not a bespoke solver.
- **No more slow tests.** The suite is at its ceiling. Pin a bug by finding its deterministic
  core, not by building 300 times. Today's 4%-intermittent island bug is pinned by four
  synthetic canvases costing ~1.3s.

## Tooling gotchas that cost me time

- **`diff.external` is difftastic.** Plain `git diff` emits no `@@` hunks and is useless to
  pipe or grep. Use `git --no-pager diff --no-ext-diff --no-color`.
- **`scripts/audit.py --jobs N` pins each cell to `cores // N` CP-SAT workers.** Do not raise
  `--jobs` without understanding that.
- **Give each agent exclusive file ownership and half the cores** (`taskset`). Three agents ran
  concurrently today on disjoint files with zero collisions. Two agents in one file is still
  the only thing that has actually lost work here.
- **`git add <explicit paths>` only.** Never `-A`, `.`, `checkout`, `reset`, `stash`, `rebase`
  while another agent is live.

## Process notes

- **Do not trust a subagent's number without re-running it.** I re-ran every headline claim
  today and they all held — but one agent led with its best run (66/72) where the distribution
  was 63–66, and one measured `--candidates 4` while reporting on a default of 3. Neither was
  dishonest; both would have misled.
- **Capture a regression oracle BEFORE the change**, independently of the agent making it. Mine
  for the rate solver was 12 URLs × 3 candidates, per recipe, and I verified it caught an
  injected fault before trusting it. It then caught the only real drift (`universe-matrix`
  belting in *less* crude oil — an improvement, but I would rather see it than not).
- **Measure, then keep or revert, and keep the numbers in comments.** Six experiments were
  built, measured and reverted today with their figures preserved. That is working.
- **I would rather have 66/72 and an honest account of the other six than a claim of 72/72
  that has to be re-verified.** That was the previous handoff's line and it is still right.
