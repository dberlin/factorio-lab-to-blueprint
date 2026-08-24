"""``tile_to_local_offset`` checked against the real-blueprint corpus.

``dsp/codec.py::tile_to_local_offset`` is the single place tile space becomes DSP
world coordinates, and it used to carry a "provisional" warning because nothing
exercised it: the round-trip tests replay *decoded* structures, so
``decode(encode(decoded))`` can be byte-perfect while the rule is wrong, and the
validator works in tile space and never sees a world coordinate.

The corpus is a real oracle for it, because a blueprint the game produced is
necessarily legal: no two buildings overlap, no belt sits inside a machine, and
every sorter has one end on a tile of the machine it serves.  Those three facts
are *translation-invariant within one footprint size* but NOT across sizes, so
they pin the per-footprint offset -- which is exactly what the rule is.

Three candidate readings of a stored ``localOffset`` ``c`` for a footprint of
width ``w`` are compared throughout:

    centre (ours)  tiles c-(w-1)/2 .. c+(w-1)/2    i.e. c = x + (w-1)/2
    corner o=0     tiles c         .. c+w-1        i.e. c = x
    corner o=-(w-1) tiles c-w+1    .. c            i.e. c = x + w - 1

Choosing the geometry corpus
----------------------------
Most fixtures cannot be used.  DSP stores positions on a sphere, so a blueprint
taken near a pole or spanning a planet is latitude-compressed: distinct surface
tiles collapse onto the same local coordinate and spacings stop being 1.0.  A
fixture is usable here only if **every** non-sorter building is integer-aligned
*and* no two of them land on the same ``(x, y, z)``.  That second half matters --
``temple-of-effectiveness`` passes the alignment half with 796/796 yet stacks 83
buildings onto already-occupied cells, and it would otherwise contribute nine
belts sitting exactly on top of a Wireless Power Tower.

Sorters are excluded from the alignment test throughout: a sorter's record is a
*line* between two endpoints with a visual inset of roughly 0.2, so it is
legitimately off-grid.  Its rounded endpoints are still tile-accurate, which is
what :func:`test_sorter_endpoints_lie_inside_the_machine_they_serve` uses.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from fractions import Fraction
from functools import cache

import pytest

from flab2bp.dsp import catalog
from flab2bp.dsp.codec import decode, tile_to_local_offset
from flab2bp.dsp.records import Blueprint
from tests.dsp.conftest import fixture_paths

#: How far a real coordinate may sit from its tile centre and still count as
#: on-grid.  The corpus's own noise floor is 1.5e-4 on the fixtures selected
#: below; 0.02 is two orders of magnitude of headroom and still an order of
#: magnitude below the 0.2 a sorter inset would need.
TOL = 0.02

#: The fixtures with no latitude compression, derived by
#: :func:`test_geometry_corpus_is_derived_not_assumed`, which is the authority.
GEOMETRY_CORPUS = (
    "12-s-purple-science-from-smelted-refined-products",
    "factory-quick-start-step-1-minimum-blue-cube-automation",
    "new-planet-establishment-polar-buildings-calldown-for-mass-production",
)

#: A candidate reading: ``localOffset`` and footprint width to minimum tile.
MinTile = Callable[[int, int], int]


def _min_tile_centre(c: int, w: int) -> int:
    return c - (w - 1) // 2


def _min_tile_corner0(c: int, w: int) -> int:
    return c


def _min_tile_corner_max(c: int, w: int) -> int:
    return c - w + 1


CENTRE: MinTile = _min_tile_centre
CORNERS: tuple[MinTile, ...] = (_min_tile_corner0, _min_tile_corner_max)


@cache
def _decoded() -> dict[str, Blueprint]:
    return {
        p.stem: decode(p.read_text(encoding="utf-8").strip())
        for p in fixture_paths(include_dyson=False)
    }


def _dev(v: float) -> float:
    """Distance from ``v`` to the nearest integer."""
    return abs(v - round(v))


def _oriented_footprint(item_id: int, yaw: float) -> tuple[int, int]:
    """Catalog footprint with width/height swapped for a quarter-turn yaw."""
    w, h = catalog.footprint(item_id)
    return (h, w) if round(yaw / 90) % 4 in (1, 3) else (w, h)


def _machines(
    bp: Blueprint, *, include_low_confidence: bool = False
) -> list[tuple[int, int, int, int, int, int]]:
    """``(x, y, z, w, h, item_id)`` for everything that reserves its own tiles.

    Belt-integrated buildings (belts, sorters, splitters) are excluded because
    they deliberately share a tile with the belt line, and
    :data:`catalog.LOW_CONFIDENCE_FOOTPRINTS` is excluded by default so that a
    doubtful *footprint* cannot be mistaken for a wrong *offset*.
    """
    out: list[tuple[int, int, int, int, int, int]] = []
    for b in bp.buildings:
        if catalog.building(b.item_id).is_belt_addon:
            continue
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not include_low_confidence and b.item_id in catalog.LOW_CONFIDENCE_FOOTPRINTS:
            continue
        w, h = _oriented_footprint(b.item_id, b.yaw)
        out.append((round(b.x), round(b.y), round(b.z), w, h, b.item_id))
    return out


def _occupancy(bp: Blueprint, min_tile: MinTile) -> Counter[tuple[int, int, int]]:
    occ: Counter[tuple[int, int, int]] = Counter()
    for mx, my, mz, w, h, _ in _machines(bp):
        x0, y0 = min_tile(mx, w), min_tile(my, h)
        for xx in range(x0, x0 + w):
            for yy in range(y0, y0 + h):
                occ[(xx, yy, mz)] += 1
    return occ


# ---------------------------------------------------------------------------
# Which fixtures may be used at all
# ---------------------------------------------------------------------------


def _geometry_report(bp: Blueprint) -> tuple[int, int, int]:
    """``(considered, off_grid, collapsed)`` for one blueprint."""
    cells: Counter[tuple[int, int, int]] = Counter()
    considered = off_grid = 0
    for b in bp.buildings:
        if catalog.is_sorter(b.item_id) or catalog.building(b.item_id).is_belt_addon:
            continue
        considered += 1
        if _dev(b.x) > TOL or _dev(b.y) > TOL:
            off_grid += 1
        cells[(round(b.x), round(b.y), round(b.z))] += 1
    collapsed = sum(n - 1 for n in cells.values() if n > 1)
    return considered, off_grid, collapsed


def test_geometry_corpus_is_derived_not_assumed() -> None:
    """:data:`GEOMETRY_CORPUS` is whatever measures clean, not a hand-picked list.

    This is deliberately a *test* rather than a module-level computation, so
    that a fixture drifting in or out of the set is a visible failure rather
    than a silent change of what everything below is measuring.
    """
    derived = tuple(
        name
        for name, bp in _decoded().items()
        if _geometry_report(bp)[1] == 0 and _geometry_report(bp)[2] == 0
    )
    assert derived == GEOMETRY_CORPUS


def test_rejected_fixtures_are_rejected_for_a_stated_reason() -> None:
    """Every excluded fixture fails on alignment, on collapse, or on both."""
    reasons = {
        name: _geometry_report(bp)
        for name, bp in _decoded().items()
        if name not in GEOMETRY_CORPUS
    }
    assert reasons, "expected some fixtures to be latitude-distorted"
    for name, (considered, off_grid, collapsed) in reasons.items():
        assert off_grid or collapsed, f"{name} was excluded but measures clean"
        assert considered > 0


# ---------------------------------------------------------------------------
# 1. The rule round-trips: every building's tile is recoverable
# ---------------------------------------------------------------------------


def _round_trip_by_footprint() -> dict[str, Counter[str]]:
    per: dict[str, Counter[str]] = {}
    for name in GEOMETRY_CORPUS:
        for b in _decoded()[name].buildings:
            if catalog.building(b.item_id).is_belt_addon or catalog.is_sorter(b.item_id):
                continue
            w, h = _oriented_footprint(b.item_id, b.yaw)
            tx = b.x - w / 2.0 + 0.5
            ty = b.y - h / 2.0 + 0.5
            key = f"{w}x{h}"
            bucket = per.setdefault(key, Counter())
            if _dev(tx) > TOL or _dev(ty) > TOL:
                bucket["non-integer-tile"] += 1
                continue
            rx, ry, rz = tile_to_local_offset(round(tx), round(ty), Fraction(round(b.z)), w, h)
            near = abs(rx - b.x) <= TOL and abs(ry - b.y) <= TOL
            bucket["agree" if near else "reapply-mismatch"] += 1
    return per


def test_inverse_rule_recovers_an_integer_tile_for_every_building() -> None:
    """The rule is invertible on real data: every recovered tile is an integer.

    Exact float equality is *not* achievable and asking for it would be a bug in
    the test, not in the rule.  DSP stores positions as float32 projected off a
    sphere, so a building the game itself placed on tile 12 comes back as
    ``12.000019``.  Across this corpus the worst residual is 1.5e-4.
    """
    per = _round_trip_by_footprint()
    bad = {k: dict(v) for k, v in per.items() if set(v) != {"agree"}}
    assert not bad, f"footprint sizes where the rule does not round-trip: {bad}"
    # Guard the guard: the corpus really does cover more than one footprint size,
    # otherwise this test is translation-invariant and proves nothing.
    assert {"1x1", "3x3", "5x5"} <= set(per), sorted(per)
    assert sum(sum(v.values()) for v in per.values()) > 3000


def test_round_trip_residual_is_the_corpus_noise_floor() -> None:
    """Pin the actual residual, so a real regression cannot hide inside ``TOL``."""
    worst = 0.0
    for name in GEOMETRY_CORPUS:
        for b in _decoded()[name].buildings:
            if catalog.building(b.item_id).is_belt_addon or catalog.is_sorter(b.item_id):
                continue
            w, h = _oriented_footprint(b.item_id, b.yaw)
            worst = max(worst, _dev(b.x - w / 2.0 + 0.5), _dev(b.y - h / 2.0 + 0.5))
    assert worst < 1e-3, worst


# ---------------------------------------------------------------------------
# 2. The rule is the RIGHT one: the corner readings are refuted
# ---------------------------------------------------------------------------


def test_centre_rule_gives_zero_footprint_overlaps() -> None:
    """A blueprint the game emitted cannot contain overlapping buildings."""
    for name in GEOMETRY_CORPUS:
        occ = _occupancy(_decoded()[name], CENTRE)
        overlaps = sum(n - 1 for n in occ.values() if n > 1)
        assert overlaps == 0, f"{name}: {overlaps} overlapping cells under the centre rule"


def test_corner_rules_produce_overlaps() -> None:
    """The discriminating half: a wrong anchor makes legal blueprints illegal."""
    for min_tile in CORNERS:
        total = 0
        for name in GEOMETRY_CORPUS:
            occ = _occupancy(_decoded()[name], min_tile)
            total += sum(n - 1 for n in occ.values() if n > 1)
        assert total > 0, f"{min_tile.__name__} is indistinguishable from the centre rule"


def test_no_belt_sits_inside_a_machine_footprint() -> None:
    """Belts run *around* machines; one inside a machine means a wrong anchor."""
    inside = total = 0
    for name in GEOMETRY_CORPUS:
        bp = _decoded()[name]
        occ = set(_occupancy(bp, CENTRE))
        for b in bp.buildings:
            if not catalog.is_belt(b.item_id):
                continue
            total += 1
            if (round(b.x), round(b.y), round(b.z)) in occ:
                inside += 1
    assert total > 2000, total
    assert inside == 0, f"{inside}/{total} belts land inside a machine footprint"


def test_corner_rules_bury_belts_inside_machines() -> None:
    for min_tile in CORNERS:
        inside = 0
        for name in GEOMETRY_CORPUS:
            bp = _decoded()[name]
            occ = set(_occupancy(bp, min_tile))
            inside += sum(
                1
                for b in bp.buildings
                if catalog.is_belt(b.item_id)
                and (round(b.x), round(b.y), round(b.z)) in occ
            )
        assert inside > 100, f"{min_tile.__name__} buries only {inside} belts"


def _sorter_endpoints(bp: Blueprint, min_tile: MinTile) -> tuple[Counter[str], Counter[str]]:
    """``(inside, outside)`` counts of machine-side sorter endpoints, by footprint.

    A sorter spans a belt tile and a tile of the machine it serves.  The
    belt-side end is identified by there being a belt there; the other end is
    attributed to the machine whose footprint -- grown by a one-tile skirt, so
    that a wrong anchor is *counted* rather than silently dropped -- contains it.
    """
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    belts = {(round(b.x), round(b.y)) for b in bp.buildings if catalog.is_belt(b.item_id)}
    occupied: dict[tuple[int, int], str] = {}
    skirt: dict[tuple[int, int], str] = {}
    for mx, my, _mz, w, h, _ in _machines(bp):
        if w == 1 and h == 1:
            continue  # a 1x1 carries no information about the offset
        key = f"{w}x{h}"
        x0, y0 = min_tile(mx, w), min_tile(my, h)
        for xx in range(x0, x0 + w):
            for yy in range(y0, y0 + h):
                occupied[(xx, yy)] = key
        for xx in range(x0 - 1, x0 + w + 1):
            for yy in range(y0 - 1, y0 + h + 1):
                skirt.setdefault((xx, yy), key)
    for b in bp.buildings:
        if not catalog.is_sorter(b.item_id):
            continue
        for px, py in ((b.x, b.y), (b.x2, b.y2)):
            cell = (round(px), round(py))
            if cell in belts:
                continue
            attributed = skirt.get(cell)
            if attributed is None:
                continue
            if cell in occupied:
                inside[occupied[cell]] += 1
            else:
                outside[attributed] += 1
    return inside, outside


def test_sorter_endpoints_lie_inside_the_machine_they_serve() -> None:
    """The sharpest evidence available: 686 endpoints, zero exceptions.

    This is the check that actually pins the *offset* rather than merely the
    parity, because a sorter endpoint is a 1x1 anchor and the machine is 3x3 or
    5x5 -- the two disagree by ``(w-1)/2`` under any wrong reading.
    """
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    for name in GEOMETRY_CORPUS:
        i, o = _sorter_endpoints(_decoded()[name], CENTRE)
        inside += i
        outside += o
    assert sum(inside.values()) > 600, dict(inside)
    assert {"3x3", "5x5"} <= set(inside), dict(inside)
    assert not outside, f"machine-side endpoints outside the footprint: {dict(outside)}"


def test_corner_rules_put_sorter_endpoints_outside_the_machine() -> None:
    for min_tile in CORNERS:
        outside: Counter[str] = Counter()
        for name in GEOMETRY_CORPUS:
            outside += _sorter_endpoints(_decoded()[name], min_tile)[1]
        assert sum(outside.values()) > 100, f"{min_tile.__name__}: {dict(outside)}"


# ---------------------------------------------------------------------------
# 3. What the corpus cannot reach
# ---------------------------------------------------------------------------


def test_no_catalog_footprint_is_even() -> None:
    """The even-footprint half-tile branch of the rule is unreachable today.

    ``catalog.derive_footprint`` returns ``2 * ceil(box / 2) - 1``, which is
    always odd, and both entries in ``_FOOTPRINT_OVERRIDES`` are odd too.  So
    ``width / 2 - 0.5`` is *always* the integer ``(width - 1) / 2`` for anything
    the generator can place, the odd/even distinction never fires, and the
    corpus therefore says nothing at all about the even branch -- it cannot be
    wrong in production and it cannot be validated here either.

    If an even footprint is ever introduced, this test fails and the half-tile
    branch needs its own evidence before it is trusted.
    """
    even = [
        (b.item_id, b.name, b.width, b.height)
        for b in catalog.all_buildings()
        if b.width % 2 == 0 or b.height % 2 == 0
    ]
    assert not even, even


@pytest.mark.parametrize("width", [1, 3, 5, 7, 9, 11])
def test_odd_footprints_stay_on_whole_coordinates(width: int) -> None:
    x, y, z = tile_to_local_offset(4, 7, Fraction(2), width, width)
    assert x == float(4 + (width - 1) // 2)
    assert y == float(7 + (width - 1) // 2)
    assert z == 2.0


def test_altitude_passes_through_unchanged() -> None:
    for z in (-3, 0, 1, 5):
        assert tile_to_local_offset(0, 0, Fraction(z), 3, 3)[2] == float(z)


def test_anchor_is_the_minimum_corner_matching_placement_occupancy() -> None:
    """The layout side spans ``x .. x + width - 1``; the codec must agree.

    ``layout.base.Placement`` enumerates a building's tiles as
    ``range(width)`` from ``x``, so ``x`` is the minimum corner.  If the codec
    ever treated it as a centre instead, every multi-tile building would land
    half a footprint off with nothing else failing.
    """
    for w, h in ((1, 1), (3, 3), (5, 5), (3, 7)):
        cx, cy, _ = tile_to_local_offset(10, 20, Fraction(0), w, h)
        assert cx - (w - 1) / 2 == 10.0
        assert cy - (h - 1) / 2 == 20.0


def test_a_building_and_its_neighbour_do_not_overlap_after_conversion() -> None:
    """Two 3x3s placed edge to edge in tile space stay edge to edge in world space."""
    a = tile_to_local_offset(0, 0, Fraction(0), 3, 3)
    b = tile_to_local_offset(3, 0, Fraction(0), 3, 3)
    assert b[0] - a[0] == 3.0
    # And a 1x1 belt in the gap column sits exactly one tile past the 3x3's edge.
    belt = tile_to_local_offset(3, 0, Fraction(0), 1, 1)
    assert belt[0] - a[0] == 2.0
