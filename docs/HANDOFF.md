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
| freeform, budget 4 | 56/72 | **62–66/72, median 66** |
| INVALID, either strategy | 0 | **0** |
| `flow.conservation` islands, quantum-chip/free-prolif | ~3.5% of builds | **0 in 608** |

**Freeform varies 62–66 across nine runs. Never quote a single run** — one measurement is
worth ±2 cells. Spine is deterministic enough that 72/72 reproduces, but it is still CP-SAT.

The suite varies **41–58s** against its 60s ceiling. I chased that and my hypothesis (that
`DEFAULT_SEARCH_WORKERS = 0` made big machines slower) was **wrong** — measured 55.7s at 16
cores, 55.8s at 32, 50.2s at 128. It is plain solver nondeterminism. It is a live risk to the
gate — a bad roll fails a suite that is fine — and nobody has costed a remedy.

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
2. **`--candidates 4`.** `all-speed-mode` laid out `information-matrix` in **4,488 tiles**
   against 5,133 for the best of the default three — 12.6% better — but `DEFAULT_CANDIDATES` is
   3 so users never see it. Measure across the corpus before changing a default; one URL is not
   evidence.
3. **`_source_for`'s last fallback** still returns `net.src.belt` even when far from the head,
   emitting a cross-map link. Safe — `belt.link_adjacent` catches it and it becomes a refusal,
   never a silent bad build — but it is the one remaining place that function can name a
   building it is nowhere near.
4. **Suite variance** (41–58s vs a 60s ceiling). Cause is solver nondeterminism; my core-count
   hypothesis was measured and refuted. Nobody has costed a fix.
5. **Regenerate `docs/AB_RESULTS.md` / `AB_COMPARISON.md`.** Still stale — they predate both
   fallback removals and everything today. **Do not quote them.** Cheap now, and
   cross-validation would finally make that column real.
6. **A\* speed / `validate.certify` speed** — both still open from the previous handoff, both
   still real. `certify` is 3.8s on a 92,907-tile placement and runs on every attempt.

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
  `assembling-machine-2` 3×3, `matrix-lab` 5×5, `chemical-plant` 9×5, **`oil-refinery` 3×7**.
  That 4-tile spread against a sorter reach of 3 is what `57c3f3e` is about.
- **Exactly 2 of 493 recipes consume an item they also produce:** `reforming-refine` and
  `x-ray-cracking`. Both are refined-oil/hydrogen. Any cycle bug will involve them.
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
