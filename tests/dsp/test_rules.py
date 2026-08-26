"""``EBuildCondition.TooBendToLift``, and the corpus measurement that sizes it.

``rules.BEND_MIN_ANGLE_WHEN_SLOPED_RAD`` and ``rules.SLOPE_DEADZONE`` carried the
decompiled C# for a year and had **zero readers anywhere in the repository** --
a ported rule's clothes on an unported rule.  This module is their reader.

It MEASURES rather than gates.  Whether the rule binds on a PASTE, as opposed to
on the interactive path tool it is decompiled from, is Step 0.1 of
``docs/RULE_CONSOLIDATION_PLAN.md`` -- an in-game experiment.  Until that
reports, wiring a default-ERROR check would refuse geometry we do not yet know is
refused, which is a guess in the opposite direction.  What this file establishes
is the number that decides the follow-up.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import rules as R
from flab2bp.dsp.codec import decode
from flab2bp.dsp.records import BlueprintBuilding

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_the_predicate_matches_the_decompiled_branch_case_by_case() -> None:
    """``if (num21 < 2.5f && num25 > 0.1f)``, one case per way through it.

    ``num21`` defaults to ``MathF.PI`` when the belt has fewer than two
    neighbours (``BuildTool_Path.cs:1889``), which is why a run end never trips
    however steep it is.
    """
    steep, flat = 0.67, 0.0
    # A straight belt is `pi`, and `pi` is not < 2.5, at any slope.
    assert not R.too_bend_to_lift((1, 0), (1, 0), steep)
    # A quarter turn is `pi/2` = 1.571 < 2.5 -- illegal, but only while sloped.
    assert R.too_bend_to_lift((1, 0), (0, 1), steep)
    assert not R.too_bend_to_lift((1, 0), (0, 1), flat)
    # A belt reversing on its own tile is `0`.
    assert R.too_bend_to_lift((1, 0), (-1, 0), steep)
    # An end of a run keeps the `MathF.PI` default and cannot trip.
    assert not R.too_bend_to_lift(None, (1, 0), steep)
    assert not R.too_bend_to_lift((1, 0), None, steep)
    # The deadzone is exclusive: `num25 > 0.1f`, so exactly 0.1 is not sloped.
    assert not R.too_bend_to_lift((1, 0), (0, 1), R.SLOPE_DEADZONE)
    assert R.too_bend_to_lift((1, 0), (0, 1), R.SLOPE_DEADZONE + 1e-9)


def test_the_bend_limit_sits_where_the_constant_puts_it() -> None:
    """The transition is at ``pi - 2.5`` = 36.76 degrees off straight.

    Mutation-checked by construction: this brackets the constant from both
    sides, so moving ``BEND_MIN_ANGLE_WHEN_SLOPED_RAD`` moves the test.
    """
    limit = math.pi - R.BEND_MIN_ANGLE_WHEN_SLOPED_RAD
    assert math.degrees(limit) == pytest.approx(36.76, abs=0.01)
    for off, want in ((limit - 0.01, False), (limit + 0.01, True)):
        out = (math.cos(off), math.sin(off))
        assert R.too_bend_to_lift((1.0, 0.0), out, 0.67) is want, off


def _bend_hits(paths: list[Path]) -> tuple[int, int, int, int]:
    """``(convictions, belts examined, turning belts, sloped belts)``."""
    seen = looked = turns = sloped = 0
    for f in paths:
        try:
            bp = decode(f.read_text())
        except Exception:  # noqa: BLE001 -- a fixture the decoder rejects is not our subject
            continue
        if len(bp.areas) > 1:
            # A building's local offset is relative to its OWN area, so putting
            # two areas in one flat frame moves belts by tens of tiles and the
            # answer is noise.  `colliders.sorter_collisions` excludes them for
            # the same reason.
            continue
        belts = {b.index: b for b in bp.buildings if cat.is_belt(b.item_id)}
        back: dict[int, BlueprintBuilding] = {}
        for o in belts.values():
            if o.output_obj_idx in belts:
                back[o.output_obj_idx] = o
        for b in belts.values():
            nxt = belts.get(b.output_obj_idx)
            prv = back.get(b.index)
            if nxt is None or prv is None:
                continue
            incoming = (b.x - prv.x, b.y - prv.y)
            outgoing = (nxt.x - b.x, nxt.y - b.y)
            run_in = math.hypot(*incoming)
            run_out = math.hypot(*outgoing)
            # Latitude compression: away from the anchor a "one tile" step is
            # not one tile, and a run of 0.1 turns 0.02 of terrain jitter into a
            # slope of 0.13.  Neighbours a whole tile apart are the undistorted
            # ones; anything else is not a measurement of this rule.
            if abs(run_in - 1.0) > 0.05 or abs(run_out - 1.0) > 0.05:
                continue
            looked += 1

            def slope(dz: float, run: float) -> float:
                # Denoised the way `catalog.BELT_Z_QUANTUM` records: terrain
                # jitter tops out at 0.0235, well inside a half step.
                q = round(float(dz) * 2.0) / 2.0
                return abs(q / float(cat.BELT_Z_PER_WORLD_UNIT)) / (run * 1.2566)

            num25 = max(slope(b.z - prv.z, run_in), slope(nxt.z - b.z, run_out))
            if num25 > R.SLOPE_DEADZONE:
                sloped += 1
            if abs(incoming[0] * outgoing[1] - incoming[1] * outgoing[0]) > 1e-9:
                turns += 1
            if R.too_bend_to_lift(incoming, outgoing, num25):
                seen += 1
    return seen, looked, turns, sloped


def test_the_games_own_blueprints_never_bend_a_sloped_belt() -> None:
    """The control on the port: the game wrote these, so the count must be 0.

    A port that got the angle convention backwards -- measuring the TURN rather
    than the interior angle the game subtends -- would convict every STRAIGHT
    belt instead and light this up with thousands.  That is the failure this
    exists to catch.

    Scope, and why it is not cherry-picking.  Three exclusions, each the same
    one the rest of this codebase already applies and each necessary:

    * multi-area blueprints -- a local offset is relative to its own area;
    * neighbours not one tile apart -- latitude compression, which turns 0.02 of
      terrain jitter over a 0.1 run into a slope of 0.13, just over the
      deadzone.  Before this scope was applied the count was 34, and **32 of
      them were one nine-area blueprint** with runs of 0.1 to 0.2 tiles;
    * z denoised to the half step, per ``catalog.BELT_Z_QUANTUM``.

    None of that can hide a real violation, because the sample retains both
    ingredients and the assertions below prove it: a corpus with no turn or no
    slope in it would be a vacuous control, and this one has both.
    """
    seen, looked, turns, sloped = _bend_hits(sorted(FIXTURES.glob("*.txt")))
    assert looked > 500, f"only {looked} belts survived scoping; sample too small"
    assert turns > 0, "no turning belt in the sample; the control is vacuous"
    assert sloped > 0, "no sloped belt in the sample; the control is vacuous"
    assert seen == 0, f"{seen} corpus belts bend while sloped -- the port is wrong"
