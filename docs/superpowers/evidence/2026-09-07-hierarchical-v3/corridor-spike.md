# Corridor spike (Task 7) — killed at Step 0

**LEVER C: SKIPPED, because the reservation rejected no rung on either cell
for a sealed-trunk reason.**

Verdict and evidence taken from `oracle.md` (Task 6 of
`docs/superpowers/plans/2026-09-07-hierarchical-v3.md`), which walked every
rung of `compose.GAP_LADDER = (2, 4, 6, 8, 12, 16)` on both `belt3` and
`zurl2` (`all-products`) and asked `_reserve_port_access` the trunk-goal
question directly, rather than reading only what `pack_with_access` commits.

## Which clause failed

Task 7's gate requires BOTH clauses to hold; only one did.

- **Clause 1 — a rung rejected for a sealed-trunk reason (a `missing` demand
  whose `PortAccessEvidence.frontier` is non-empty): FAILS.** No rung on
  either cell produced a sealed-trunk rejection.
- **Clause 2 — the widest rung judged still leaves at least one unrouted cut:
  HOLDS.** belt3's gap-16 rung leaves 3 unrouted cuts on geometry, not clock.

Because clause 1 fails, Task 7 does not run.

## The numbers

`missing_sealed` is **0 on all twelve judged rungs** across both cells (six
rungs each, belt3 and zurl2) — confirmed directly against
`rung-belt3-all-products.json` and `rung-zurl2-all-products.json`, not only
`oracle.md`'s tables.

The rejections that did occur are wholesale, not graded:

- belt3: `assigned` is **0 of 91** demands on all six rungs (gap 2, 4, 6, 8,
  12, 16).
- zurl2: `assigned` is **0 of 144** demands on five of its six rungs (gap 2,
  4, 6, 8, 12).

A wholesale give-up assigns nothing; a graded rejection would leave some
demands assigned and others not. Every rejected rung here assigned zero,
which is what makes it wholesale rather than a partial, geometry-shaped
answer.

## What the SKIP does and does not mean

This SKIP is a statement about the assignment step (`_match_access_corridors`)
giving up wholesale, not a finding that the composed canvas's geometry is
adequate. `oracle.md` is explicit that the give-up happens before a sealed
lane head could even be reported separately, so a matcher that did not give
up might still find one. The SKIP should be revisited if that wholesale
give-up is ever fixed — a corridor's value cannot be judged while the oracle
cannot grade a rung.

## The new fact

zurl2's widest rung (gap 16) is the one rung on either cell where the
trunk-goal oracle returned a usable answer: **144 of 144 demands assigned in
4.17 s, `complete`, `degraded` False.** This is the first time the ladder's
upper rungs (6, 8, 12, 16) have been exercised by any measurement.

Source: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/oracle.md`.
