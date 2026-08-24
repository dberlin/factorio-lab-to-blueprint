"""Guards on the frozen ``Placement`` contract.

The tests here exist because of a specific bug that shipped twice: a helper
rebuilt ``PlacedBuilding`` field by field and silently dropped every field it
did not enumerate.  It was already discarding ``parameters``; when
``carries_item`` was added it swallowed that too, so belt marker icons came out
empty while the emitter was setting them correctly -- the symptom pointed at the
marker pass, several layers from the cause.

Every field having a default is what makes this invisible: a constructor call
that omits one is perfectly legal.  So the guard is a test, not a type.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

from flab2bp.layout.base import Facing, PlacedBuilding, Placement


def fully_populated() -> PlacedBuilding:
    """A building with every field set to something distinguishable from its default."""
    return PlacedBuilding(
        item_id=2002,
        model_index=36,
        x=3,
        y=4,
        z=Fraction(1),
        width=2,
        height=5,
        yaw=90.0,
        x2=7,
        y2=8,
        z2=Fraction(1),
        yaw2=270.0,
        recipe_id=103,
        filter_id=1001,
        output_obj=11,
        input_obj=12,
        output_to_slot=1,
        input_from_slot=2,
        output_from_slot=3,
        input_to_slot=4,
        output_offset=5,
        input_offset=6,
        parameters=(1001, 0),
        carries_item="iron-ore",
    )


def test_the_fixture_sets_every_field_to_a_non_default() -> None:
    """Otherwise the preservation test below silently stops covering new fields."""
    b = fully_populated()
    defaults = PlacedBuilding(item_id=0, model_index=0, x=0, y=0)
    same_as_default = [
        f.name
        for f in dataclasses.fields(PlacedBuilding)
        if getattr(b, f.name) == getattr(defaults, f.name)
    ]
    assert not same_as_default, (
        f"fields left at their default in fully_populated(): {same_as_default}. "
        "Add them, or the field-preservation guard will not cover them."
    )


def test_replace_preserves_every_other_field() -> None:
    """``dataclasses.replace`` is the only sanctioned way to modify a building.

    A hand-written rebuild that enumerates fields is what caused the original
    bug; this pins that ``replace`` does not have the same hazard.
    """
    b = fully_populated()
    out = dataclasses.replace(b, output_obj=99)
    assert out.output_obj == 99
    for f in dataclasses.fields(PlacedBuilding):
        if f.name == "output_obj":
            continue
        assert getattr(out, f.name) == getattr(b, f.name), f"replace() dropped {f.name}"


def test_no_layout_module_rebuilds_a_placedbuilding_by_hand() -> None:
    """Catch the bug at its source rather than at its symptom.

    A helper that takes a ``PlacedBuilding`` and returns a modified one must use
    ``replace``.  Constructing a fresh one from another one's attributes drops
    whatever the author forgot, and every field has a default, so nothing
    complains.
    """
    import re
    from pathlib import Path

    layout = Path(__file__).resolve().parent.parent.parent / "src" / "flab2bp" / "layout"
    offenders: list[str] = []
    # A constructor call that reads three or more attributes off some other
    # building is a rebuild, not a fresh placement.
    pattern = re.compile(r"PlacedBuilding\((?:[^()]|\([^()]*\))*?\)", re.S)
    for path in layout.glob("*.py"):
        for call in pattern.findall(path.read_text()):
            copied = re.findall(r"=\s*([a-zA-Z_]\w*)\.\w+", call)
            if len(copied) >= 3 and len(set(copied)) == 1:
                offenders.append(f"{path.name}: rebuilds from {copied[0]!r}")
    assert not offenders, (
        "these construct a PlacedBuilding from another one's fields instead of "
        "using dataclasses.replace, which silently drops any field they forget:\n  "
        + "\n  ".join(offenders)
    )


def test_area_and_bounds_cover_full_footprints() -> None:
    p = Placement(
        buildings=(
            PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),
            PlacedBuilding(item_id=2302, model_index=62, x=5, y=2, width=3, height=3),
        )
    )
    assert p.bounds == (0, 0, 7, 4)
    assert p.area == 8 * 5


def test_facing_delta_and_opposite_are_consistent() -> None:
    for f in Facing:
        dx, dy = f.delta
        ox, oy = f.opposite().delta
        assert (dx + ox, dy + oy) == (0, 0)
