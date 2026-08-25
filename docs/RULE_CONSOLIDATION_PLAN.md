# Plan: 100% of the game's rules in one place, and that place decides legality

Companion to `docs/RULE_AUDIT.md`, which is the evidence. This is the sequence.

## The end state, stated so it can be falsified

1. Every rule whose falsification is *"the game draws it red"* lives in
   `src/flab2bp/dsp/` — `rules.py`, `colliders.py`, or the rule half of
   `catalog.py` — and nowhere else.
2. No layout module re-implements, approximates, or hand-copies such a rule.
   They may **consult** it. They may not **restate** it.
3. A fast search-time structure is a **compiled projection** of the
   authoritative rule, produced by a function that lives next to the rule.
   Never an independently-derived formula that happens to agree.
4. Every rule constant in `dsp/` is *consulted by something*. A constant with no
   readers is an unported rule wearing a ported rule's clothes — that is exactly
   what `BEND_MIN_ANGLE_WHEN_SLOPED_RAD` turned out to be.
5. "100%" is a number a test prints, not a claim in a document.

**Done-when:** the rule registry test (Step R2) reports every `dsp/` rule
constant named by at least one check, the mutation suite (Step R4) shows every
one of them turning both a validator test *and* a strategy test red, and the
lint (Step R1) is green.

## The line, restated because getting it wrong is worse than doing nothing

**Legality → `dsp/`, no exceptions.** Every `game.*` check, `geom.collide`,
`geom.belt_single_occupancy`, `geom.altitude_step`, the ceiling half of
`geom.altitude_range`, `sorter.*` reach and slot rules, `junction.ports`,
`power.coverage`, `power.connectivity`.

**Quality → stays in the layout models.** Density, pitch, search order, altitude
budgets, time budgets, congestion weights, rip-up policy, candidate counts.
`freeform.LEVELS = 3` and `spine.UNIFORM_ROW_PITCH` are the canonical traps: both
were set by measurement, both look like rules, neither is one. A consolidation
that drags these into `dsp/` has made the codebase worse.

## Standing constraints this plan does not get to relax

- **No fallbacks.** A case that cannot be built is a bug to fix or an honest
  refusal. Never a looser path that silently emits something worse.
- **An INVALID blueprint is the worst outcome**, worse than a refusal. Every
  `CHANGE` step below must keep INVALID at 0 in every audit round.
- **Density is the objective.** Every `CHANGE` step needs paired, interleaved
  area measurement, reported cell-for-cell over the cells both arms wire —
  never a total across differing cell sets.
- **Exact `Fraction` arithmetic** in all rate and capacity paths.

---

# Phase 0 — Settle the one open question about the game

Nothing else in this plan is blocked by it, but it is the only item whose
failure mode is an invalid blueprint, and it cannot be settled by reading code.

### Step 0.1 — Paste and look. [not code, IN FLIGHT]

`catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` (5/2) and `catalog.SLOPE_DEADZONE`
(1/10) carry the decompiled C# for `EBuildCondition.TooBendToLift` and have
**zero readers anywhere in the repository**. `geom.altitude_step` ports
`TooSteep` from the same C# function three lines away. Either both bind on a
paste or neither does; we enforce exactly one.

The blueprint already handed over (`/home/dannyb/coil-best.txt`, freeform,
1170 tiles) contains exactly two instances, which makes the paste a designed
experiment rather than a spot check:

| location | turn while sloped | climb |
|---|---|---|
| (22, 16) z=0 | **180°** (a U-turn) | 1.000 |
| (-1, 2) z=1 | 90° | 1.000 |

- **Red** → the rule binds. Go to Step 0.2. We have been emitting invalid
  geometry and no check could see it.
- **Green** → the rule does not bind as its constants suggest. Record the
  evidence in `catalog.py` next to the constants, and Step R2 must then treat
  them as deliberately-unenforced-with-a-reason rather than as a hole.

Independent of the bend rule: the 180° case is a belt reversing on itself on one
tile while climbing a full level. Worth a look regardless of the verdict.

### Step 0.2 — Act on the answer. [CHANGE if it binds]

Port `TooBendToLift` into `dsp/rules.py` as a predicate over
`(incoming_dir, outgoing_dir, dz)`, add a default-ERROR `geom.bend_while_sloped`
check, and make `_astar`'s legal-move table (Step 2.2) refuse it at search time
so it becomes a routing constraint rather than a late refusal. Expect refusals
before the router learns the constraint; that is the correct order — validator
first, then teach the search.

---

# Phase 1 — Behaviour-preserving consolidation

Every step here is a refactor. If any of them moves a layout, that is a bug in
the step, and the paired audit is how it gets caught. Run the mid-tier audit
before and after each: `spine` and `freeform` clean counts and areas must be
**identical**, not merely close.

| Step | What | Audit ref |
|---|---|---|
| 1.1 | Re-key `freeform.belt_ban` and `junction.keepout_cells` on blueprint `z` rather than integer routing level. A ramp tile stands at a `z` that is not its level, so the two disagree by construction. Latent today (0 half-level belts over a coater on the audited sample) but structurally identical to the `_make_grid` bug. | D2 |
| 1.2 | One owner for *"how high must a belt be over X"*: fold `catalog.BELT_CROSSING_CLEARANCE` and `spine._belt_floor_over` into a single `dsp/` function. `BELT_CROSSING_CLEARANCE = 1` is hand-typed, and it is the **wrong number for a coater** (1.8975). Right answer today only because the coater path happens to consult the collider instead. | D3, Step 3–4 |
| 1.3 | One owner for pairwise centre separation: `catalog.min_centre_separation(a_id, a_yaw, b_id, b_yaw)`. Deletes the two hand-written `(a + b) / 2.0` copies at `spine.py:4406` and `junction.py:143`. | Step 5 |
| 1.4 | Delete `TESLA_COVER_RADIUS` / `TESLA_LINK_DISTANCE` hand-typed copies; spine reads the extracted value freeform already uses. Power coverage is the **best-consolidated rule in the codebase** — this removes its only blemish. | N1, Step 5b |
| 1.5 | Split `SKEW_AXIS_DEG`: one constant currently serves two different rules. | D5 |
| 1.6 | Move the addon-facing rule out of `validate.py` into `dsp/`. `game.addon_facing` **is** the rule; it just lives in the wrong module. | D4 |
| 1.7 | Remove the three hand-rolled copies of `CONN_SLOTS_PER_OBJECT` (the `* 16 + slot` arithmetic). | D6 |
| 1.8 | Fix the stale `OPT_IN` docstrings. `OPT_IN` is `set()`, but `_belt_collide`'s docstring still opens *"WHY THIS IS IN `OPT_IN`"* and describes turning it on as a future event. In a codebase where docstrings carry rule provenance, a stale one is a correctness hazard, not a typo. | 3.3 |

---

# Phase 2 — Compile, don't call

The mechanism that answers the performance objection. `_astar` expands ~1.25M
nodes on a `quantum-chip` pass and asks *"is this cell free"* once per expansion
per direction; `certify()` asks *"is this layout legal"* once. That asymmetry is
why `_make_grid` hand-built a flat array beside `_Canvas.free` — and hand-building
it beside the rule is exactly how it drifted out of agreement.

The rule stays a pure predicate in `dsp/`. The hot path never calls it per query;
it calls it **once per object at setup** and materialises the answer into
whatever fast structure it likes. Two properties make that safe, and both are
already proven in this codebase by `colliders.belt_keepout_offsets` and
`catalog.clearance`:

1. The compiled form is produced by a function **next to the rule**, not next to
   the search.
2. The search's structures are built **only** from compiled sets, never from an
   independently-derived formula.

### Step 2.1 — `_make_grid` becomes a pure projection. [BP]

Every contributing set becomes a compiled keep-out from `dsp/`, keyed on
blueprint `z`. `_make_grid` projects `_Canvas`; `_Canvas` projects compiled rule
sets. Nothing derives anything twice.

### Step 2.2 — The legal-move table. [BP, or CHANGE if 0.2 fired]

`_RAMPS` / `_legal_link` / `_altitude_profile` currently encode step legality by
hand. The legal move set is small and enumerable: build it once at import from
`catalog.MAX_BELT_SLOPE`, `BELT_Z_PER_WORLD_UNIT` and — if Step 0 says it binds
— the bend rule, as a table of `(dlevel, dtiles, turns_allowed)`. `_RAMPS`
becomes that table's projection instead of a hand-written `(1, -1)`.

### Step 2.3 — Assert-mode grid cross-check. [BP]

An env flag under which `_make_grid` re-derives its array from `_Canvas.free`
cell by cell and diffs, and under which `certify()` runs on every intermediate
placement rather than only the final one. O(cells), affordable once per test
run. **This is the permanent guard for the entire `_make_grid` class of bug.**

---

# Phase 3 — Close the holes

Rules this repository quotes in its own comments and enforces with nothing.

### Step 3.1 — The addon corner rule (decompiled 145812). [CHANGE]

The `AddonPass` excusal requires the ridden belt's own *input and output* belts
to lie within 0.3 of the addon's line, so a coater on a corner is refused.
`game.addon_facing` tests one direction only. Our coaters sit on straight runs,
so today this is **silence, not a pass** — the check does not test it.

### Step 3.2 — The `DistancePointLine < 0.3f` clause. [CHANGE]

Companion to `ADDON_AREA_RADIUS`. Decides whether a belt *two* tiles behind a
coater counts as supplying it: `world_gap` for that offset is 0.94 against a
radius of 1.0. Unported, and the margin is 0.06.

### Step 3.3 — `BELT_SLOT_AUTO_RANGE`'s second consequence. [BP, cheap]

A belt tile accepts at most `12 - 4 = 8` auto-slot connections; past that the
connection is **silently dropped**. Corpus worst is 6, so it has never bound —
but "never bound yet" is how the shared-slot defect looked before someone pasted
one. Cheap to add, and it is a silent-corruption failure mode.

### Step 3.4 — Read the decompiled source for what nobody has written down.

The audit's declared gap: it could only audit against rules this repo already
quotes. Rules the game has that nobody here has ever written down are invisible
to it. Closing that needs the decompiled source, not another audit of our tree.

---

# Phase 4 — The invented constraint, and the largest density item in the audit

### Step 4.1 — Freeform: stop treating machines as solid at every altitude. [CHANGE, big]

`freeform` marks every machine `solid` at every level, so **no belt may ever
cross a machine**. That is not a game rule. The game prices a machine crossing by
height (`colliders.belt_crossing_height` gives 2.80–4.97), and **spine already
implements exactly that pricing** in `_belt_floor_over`. Freeform forbids what
spine sells.

It compounds: `freeform.py:148-152` justifies `LEVELS = 3` *by* this restriction
— "it treats machines as solid at every altitude, so headroom beyond a crossing
plus one buys it nothing" — so the invented constraint is also capping the
router's altitude budget. Removing it makes `LEVELS` the quality knob it was
always meant to be.

This is the **single largest density item** in the audit, and density is the
objective. It is also the most likely to move layouts in both directions, so it
gets the most careful measurement: paired, interleaved, all three tiers,
cell-for-cell area, INVALID 0 in every round.

### Step 4.2 — Retire the remaining invented constraints. [BP, zero cost today]

Belt `z` quantisation as a *game* rule (the game quantises nothing — keep the
ceiling, move the quantum next to the emitters), and `slots.attachment`'s
cos(24°) alignment, which is stricter than the game's sign test.

---

# Phase R — The mechanisms that keep it at 100%

Without these the consolidation decays back within a month and we rediscover it
the same way we found it this time: by pasting into the game.

### R1 — Lint: no game constant outside `dsp/`. [cheap, starts green]

Walk the AST of every module under `layout/`, `bench/`, `rates/`; fail on any
float or `Fraction` constant that also appears as a rule constant in `dsp/`.
This is exactly the check that would have caught `24.0` living in two files.
Layout code is clean today, so it starts green and only has to stay that way.

### R2 — A declared rule registry. [the one that prints the number]

Extend the decorator: `@check("game.belt_crossing", rule="colliders.belt_crossing_height")`.
Assert that (a) every declared symbol resolves inside `flab2bp.dsp`, (b) the
check body actually references it, and (c) **every rule constant exported from
`dsp/` is named by at least one check.**

Clause (c) is what finds unported rules. `BEND_MIN_ANGLE_WHEN_SLOPED_RAD` would
have failed it the day it was written.

### R3 — Assert-mode corpus run. [= Step 2.3, turned on in CI]

On in the test suite and in `scripts/audit.py`.

### R4 — Constant-mutation coverage. [the only one that proves consultation]

For each rule constant in `dsp/`, perturb it and assert that **both** a validator
test **and** a strategy test go red. Bump `rules.SLOT_REACH` to 0.4 and
`slots.attachment` must start refusing. Bump `colliders.BELT_PROBE_RADIUS` and
freeform's `belt_ban` must widen.

A module that holds its own copy of a rule will not notice the perturbation —
and that is precisely what *"the search re-implements the rule"* looks like from
outside. **Mutation coverage is the only one of the four that cannot be
satisfied by a module that imports a constant and then ignores it.**

Today, bumping `catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` changes nothing
anywhere. That is this audit's headline finding, expressed as a test.

---

# Sequencing against work already in flight

Two branches are editing `freeform.py`, `spine.py` and `slots.py` right now:
`bl-ew-faces` (east/west machine faces, for `universe-matrix`) and
`bl-spine-repair` (the intermittent `game.slot_occupancy` refusal). **Phase 1
and Phase 2 must not start until both have merged** — they touch the same
functions, and this plan's whole value is removing duplicate implementations,
which is the worst possible thing to be doing during a three-way merge.

Phase 0 is a paste and blocks nothing. Phase R1 and R2 touch only `dsp/` and
test files and can start immediately and in parallel.

**Recommended order:** 0.1 (paste, in flight) → R1 + R2 (start now, independent)
→ land the two in-flight branches → Phase 1 → Phase 2 → R3, R4 → Phase 3 →
Phase 4.

Phase 4.1 is the density prize and is deliberately last: it is the step most
likely to move layouts, and it should land on a codebase where a single
authoritative rule already prices a machine crossing, rather than on one where
that price exists in two places.
