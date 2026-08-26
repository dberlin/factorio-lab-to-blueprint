"""``EBuildCondition.PowerTooClose``, pinned to the paste that found it.

THE DEFECT THIS MODULE EXISTS FOR.  The user pasted
``tests/fixtures/ours/power-too-close-freeform.txt`` -- 372 buildings we
generated -- into a real game.  Every belt, sorter, splitter and machine built.
Two of its six Tesla Towers were refused for standing 1.777 world units apart.
Nothing in the repository could see it: a Tesla Tower has NO build collider, so
``geom.collide`` is blind to two of them however they are stacked, and the rule
the game actually applies is a dedicated predicate with its own three-tier
threshold ladder.

So this file does three things, in order of how much they are worth:

1. **Convicts the real blueprint**, on exactly the pair the game reddened and
   on no other -- the other four towers must stay clean, or the rule is
   over-explaining the failure it was written from.
2. **Clears every blueprint the GAME wrote.**  That control is what separates
   this from a plausible-sounding rule: any conviction in ``tests/fixtures`` is
   this port being wrong, not the game breaking its own rules.
3. Pins the ladder case by case against the decompiled branches, including the
   two tiers nothing we emit reaches -- a flattened rule is right by coincidence
   at one tier and silently wrong at the others.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders as C
from flab2bp.dsp import rules as R
from flab2bp.dsp.codec import decode
from flab2bp.dsp.records import BlueprintBuilding

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: The blueprint the game refused, kept byte-for-byte as it was pasted.
THE_PASTE = FIXTURES / "ours" / "power-too-close-freeform.txt"

#: Blueprints whose coordinates this model can place.  The same restriction
#: ``tests/dsp/test_colliders.py`` applies, for the same reason: a building's
#: local offset is relative to its OWN area, and a multi-area blueprint
#: additionally goes through the tropic-anchor re-basing at decompiled
#: 179769-179806.  Dropped into one flat frame its buildings land tens of tiles
#: from where they belong, and the answer is noise rather than evidence.
#:
#: Measured, not assumed: over the four multi-area fixtures the flat frame
#: reports 102,875 convicting pairs, including Wind Turbines it places 0.30
#: world units apart -- inside their own 3x3 footprints, which is impossible.
#: Restricting to pairs within ONE area drops two of the four to zero on its
#: own; the other two are whole-planet captures whose areas form a
#: ``parentIndex`` chain, and no single frame exists for them at all.
SINGLE_AREA = (
    "12-s-purple-science-from-smelted-refined-products",
    "factory-heretical-smelter-block",
    "factory-quick-start-step-1-minimum-blue-cube-automation",
    "factory-quick-start-step-3-red-cube",
    "falk-v7-mall-full",
    "ours/sorter-collide-built",
    "ours/sorter-collide-freeform",
)

TESLA = R.PowerNode(is_power_node=True)
WIND = R.PowerNode(is_power_node=True, wind_forced_power=True)
GEOTHERMAL = R.PowerNode(is_power_node=True, geothermal=True)
ACCUMULATOR = R.PowerNode(is_power_node=True, is_accumulator=True)


def _node(item_id: int) -> R.PowerNode | None:
    try:
        info = cat.building(item_id)
    except KeyError:
        return None
    if not info.is_power_node:
        return None
    return R.PowerNode(
        is_power_node=True,
        is_accumulator=info.is_accumulator,
        wind_forced_power=info.wind_forced_power,
        geothermal=info.geothermal,
    )


def _nodes(path: Path) -> list[tuple[int, BlueprintBuilding, R.PowerNode]]:
    bp = decode(path.read_text(encoding="utf-8").strip())
    out = []
    for i, b in enumerate(bp.buildings):
        node = _node(b.item_id)
        if node is not None:
            out.append((i, b, node))
    return out


def _convictions(
    nodes: list[tuple[int, BlueprintBuilding, R.PowerNode]],
) -> list[tuple[int, int, float, R.PowerSpacing]]:
    """Every ordered pair the ladder refuses, at the blueprint's own coordinates.

    ``flat_pose`` rather than ``preview_pose``: these blueprints record no paste
    latitude, and the flat frame is the one ``validate.game.power_too_close``
    and ``validate.geom.collide`` both use.
    """
    out = []
    for (ia, a, na), (ib, b, nb) in itertools.combinations(nodes, 2):
        pa = C.flat_pose(a.x, a.y, a.z, 0.0)[0]
        pb = C.flat_pose(b.x, b.y, b.z, 0.0)[0]
        d2 = sum((p - q) ** 2 for p, q in zip(pa, pb, strict=True))
        cond = R.power_node_condition(na, nb, d2) or R.power_node_condition(nb, na, d2)
        if cond is not None:
            out.append((ia, ib, d2, cond))
    return out


# --- 1. the blueprint the game refused --------------------------------------


def test_the_rule_convicts_the_pair_the_game_reddened() -> None:
    """Towers #367 (21,15) and #371 (22,16), diagonally adjacent.

    1.4142 tiles is 1.777 world units against a bound of 3.5, so ``num35`` is
    3.150 against ``num37`` of 12.25.
    """
    hits = _convictions(_nodes(THE_PASTE))
    assert [(a, b, cond) for a, b, _d2, cond in hits] == [
        (367, 371, R.PowerSpacing.POWER_TOO_CLOSE)
    ]
    (_a, _b, d2, _cond) = hits[0]
    assert math.sqrt(d2) == pytest.approx(1.7772, abs=1e-3)


def test_the_rule_does_not_over_explain_the_failure() -> None:
    """The other four towers built, so the rule must clear all of them.

    A rule with a wider bound would still "explain" the refusal and would be
    refuted here: the next-closest pair in this blueprint is 11.24 world units,
    so anything up to 126 squared would fit the one observation and only 12.25
    fits both halves of it.
    """
    nodes = _nodes(THE_PASTE)
    assert len(nodes) == 6, "six Tesla Towers, five of them uninvolved"
    gaps = sorted(
        math.sqrt(
            sum(
                (p - q) ** 2
                for p, q in zip(
                    C.flat_pose(a.x, a.y, a.z, 0.0)[0],
                    C.flat_pose(b.x, b.y, b.z, 0.0)[0],
                    strict=True,
                )
            )
        )
        for (_ia, a, _na), (_ib, b, _nb) in itertools.combinations(nodes, 2)
    )
    assert gaps[0] == pytest.approx(1.777, abs=1e-3), "the refused pair"
    assert gaps[1] == pytest.approx(11.240, abs=1e-3), "the next one, which built"
    assert math.sqrt(R.POWER_TOO_CLOSE_SQR) < gaps[1], "the bound must clear it"


def test_no_build_collider_is_why_geom_collide_could_not_see_it() -> None:
    """The reason this needed its own rule rather than a fix to an old one."""
    assert C.build_colliders(cat.TESLA_TOWER_ID) == ()


# --- 2. the control: blueprints the game itself wrote ------------------------


@pytest.mark.parametrize("name", SINGLE_AREA)
def test_the_rule_convicts_nothing_the_game_wrote(name: str) -> None:
    assert _convictions(_nodes(FIXTURES / f"{name}.txt")) == []


def test_that_control_could_have_failed() -> None:
    """A sample that cannot produce a conviction proves nothing.

    75 power nodes over 1468 pairs, and they are not all far apart: the closest
    real pair in the corpus is 6.00 tiles, which is 2.15 times the bound.  A
    rule that read 12.25 as a squared TILE distance -- 3.5 tiles -- would still
    clear them, so this control does NOT pin the unit; that is
    ``test_the_bound_is_world_units_not_tiles``' job.  What it does establish is
    that the rule refuses nothing the game accepts.
    """
    total = 0
    closest = math.inf
    for name in SINGLE_AREA:
        nodes = _nodes(FIXTURES / f"{name}.txt")
        total += len(nodes)
        for (_ia, a, _na), (_ib, b, _nb) in itertools.combinations(nodes, 2):
            pa = C.flat_pose(a.x, a.y, a.z, 0.0)[0]
            pb = C.flat_pose(b.x, b.y, b.z, 0.0)[0]
            closest = min(closest, sum((p - q) ** 2 for p, q in zip(pa, pb, strict=True)))
    assert total == 75
    # 5.99999 rather than 6: the corpus records float positions with terrain
    # jitter in them, so this is six tiles as the game wrote them.
    assert math.sqrt(closest) / C.GRID_ARC == pytest.approx(6.0, abs=1e-4)


# --- 3. the ladder, branch by branch -----------------------------------------


def test_the_bound_is_world_units_not_tiles() -> None:
    """The trap, bracketed from both sides.

    ``sqrt(12.25)`` = 3.5 is a distance between two Unity ``Vector3``s, and a
    tile is ``GRID_ARC`` = 1.2566 of those.  A knight's move (2.236 tiles) is
    2.810 world units and refused; ``(2, 2)`` (2.828 tiles) is 3.554 and clear.
    Read as tiles the bound would sit at 3.5 TILES and refuse ``(2, 2)`` too, so
    these two assertions cannot both hold under the wrong reading.
    """
    assert math.sqrt(R.POWER_TOO_CLOSE_SQR) == pytest.approx(3.5)
    assert math.sqrt(R.POWER_TOO_CLOSE_SQR) / C.GRID_ARC == pytest.approx(2.7853, abs=1e-4)

    def gap2(dx: int, dy: int, dz: int = 0) -> float:
        g = R.world_gap(dx, dy, dz)
        return g * g

    assert R.power_node_condition(TESLA, TESLA, gap2(2, 1)) is R.PowerSpacing.POWER_TOO_CLOSE
    assert R.power_node_condition(TESLA, TESLA, gap2(2, 2)) is None


def test_the_gate_is_a_lookup_and_not_a_scalar() -> None:
    """``num37 = (geothermal ? 144f : (windForcedPower ? 110.25f : 12.25f))``."""
    assert R.power_node_gate_sqr() == R.POWER_TOO_CLOSE_SQR
    assert R.power_node_gate_sqr(wind_forced_power=True) == R.WIND_TOO_CLOSE_SQR
    assert R.power_node_gate_sqr(geothermal=True) == R.GEOTHERMAL_TOO_CLOSE_SQR
    # geothermal wins the conditional, exactly as the ternary nests.
    assert (
        R.power_node_gate_sqr(wind_forced_power=True, geothermal=True)
        == R.GEOTHERMAL_TOO_CLOSE_SQR
    )


def test_the_upper_tiers_need_the_flag_on_both_buildings() -> None:
    """``windForcedPower && item.prefabDesc.windForcedPower``, and its twin.

    A Wind Turbine one tile from a Tesla Tower is inside the turbine's 10.5
    gate, takes neither upper branch, and is then judged by the ordinary 3.5 --
    which it fails.  At four tiles it is over 3.5 and under 10.5 and is CLEAR,
    which is the case that distinguishes a tiered rule from a flattened one.
    """
    def gap2(tiles: float) -> float:
        g = R.world_gap(tiles, 0)
        return g * g

    assert R.power_node_condition(WIND, WIND, gap2(8)) is R.PowerSpacing.WIND_TOO_CLOSE
    assert R.power_node_condition(WIND, WIND, gap2(9)) is None
    assert R.power_node_condition(WIND, TESLA, gap2(1)) is R.PowerSpacing.POWER_TOO_CLOSE
    assert R.power_node_condition(WIND, TESLA, gap2(4)) is None
    assert (
        R.power_node_condition(GEOTHERMAL, GEOTHERMAL, gap2(9))
        is R.PowerSpacing.GEOTHERMAL_TOO_CLOSE
    )
    assert R.power_node_condition(GEOTHERMAL, GEOTHERMAL, gap2(10)) is None
    assert R.power_node_condition(GEOTHERMAL, WIND, gap2(9)) is None


def test_the_accumulator_exemption_is_one_sided() -> None:
    """``isPowerNode && !isAccumulator`` guards the building being PLACED only."""
    assert R.power_node_condition(ACCUMULATOR, ACCUMULATOR, 0.0) is None
    assert R.power_node_condition(ACCUMULATOR, TESLA, 0.0) is None
    assert R.power_node_condition(TESLA, ACCUMULATOR, 0.0) is R.PowerSpacing.POWER_TOO_CLOSE


def test_the_catalog_flags_match_the_prefabs() -> None:
    """Which buildings the tiers actually apply to, so a table edit is visible."""
    nodes = {b.item_id for b in cat.all_buildings() if b.is_power_node}
    assert nodes == {2201, 2202, 2203, 2204, 2205, 2206, 2208, 2209, 2210, 2211, 2212, 2213, 3007}
    assert {i for i in nodes if cat.building(i).wind_forced_power} == {2203}
    assert {i for i in nodes if cat.building(i).geothermal} == {2213}
    assert {i for i in nodes if cat.building(i).is_accumulator} == {2206}
    # Three nodes cover nothing and are still nodes -- the reason this check
    # cannot select towers the way `power.coverage` does.
    assert {i for i in nodes if cat.building(i).cover_radius == 0} == {2205, 2206, 2213}


def test_the_keepout_projection_agrees_with_the_predicate() -> None:
    """The compiled projection has no content of its own, and that is asserted.

    ``power_node_keepout_offsets`` is what both packers consult, so a projection
    that drifted from the predicate would put the search and the check on
    different rules -- the exact failure the consolidation plan exists to stop.
    """
    for a, b in ((TESLA, TESLA), (WIND, WIND), (WIND, TESLA), (TESLA, ACCUMULATOR)):
        offsets = R.power_node_keepout_offsets(a, b, reach=12, levels=4)
        for dx in range(-12, 13):
            for dy in range(-12, 13):
                for dz in range(-4, 5):
                    g = R.world_gap(dx, dy, dz)
                    want = R.power_node_condition(a, b, g * g) is not None
                    assert ((dx, dy, dz) in offsets) is want, (a, b, dx, dy, dz)


def test_the_keepout_disc_is_the_shape_the_arithmetic_implies() -> None:
    """21 cells on the ground: every ``dx**2 + dy**2 <= 7``, and nothing more.

    Written out rather than recomputed, because a projection tested only against
    its own generator can be wrong in both places at once.
    """
    ground = {(x, y) for x, y, z in R.power_node_keepout_offsets(TESLA, TESLA) if z == 0}
    assert ground == {(x, y) for x in range(-2, 3) for y in range(-2, 3) if x * x + y * y <= 7}
    assert len(ground) == 21
    # An altitude LEVEL is 4/3 world units, so two levels up is still inside and
    # three is not -- and that is not a tile count.
    assert (0, 0, 2) in R.power_node_keepout_offsets(TESLA, TESLA)
    assert (0, 0, 3) not in R.power_node_keepout_offsets(TESLA, TESLA)
