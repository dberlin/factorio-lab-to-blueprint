"""DSP's ``EBuildCondition.Collide`` predicate, reimplemented offline.

Pasting a blueprint the game refuses with "Collide with other object" is
``EBuildCondition.Collide = 34``.  On an EMPTY planet the only thing a preview
can collide with is another preview from the same blueprint, and that is decided
entirely by data the blueprint already carries -- so it is checkable here rather
than only in game.  (Contrast ``NeedGround``, which is a paste-time terrain
raycast and genuinely cannot be checked offline.)

The rule, from the game
-----------------------
``BuildTool_BlueprintPaste.CheckBuildConditions`` runs after
``ActiveColliders``, which has already put every preview's colliders into the
live physics world on layer 18 ("Build Preview", confirmed from the TagManager).
Decompiled lines 145712-145760::

    if (buildPreview2.desc.hasBuildCollider)
    {
        ColliderData[] buildColliders = buildPreview2.desc.buildColliders;
        for (int num16 = 0; num16 < buildColliders.Length; num16++)
        {
            ColliderData colliderData = buildPreview2.desc.buildColliders[num16];
            ...
            colliderData.pos = lpos + lrot * colliderData.pos;
            colliderData.q = lrot * colliderData.q;
            int mask = 395264;
            ...
            int num17 = ((!buildPreview2.desc.isBelt)
                ? Physics.OverlapBoxNonAlloc(colliderData.pos, colliderData.ext,
                      BuildTool._tmp_cols, colliderData.q, mask, QueryTriggerInteraction.Collide)
                : Physics.OverlapSphereNonAlloc(buildPreview2.lpos
                      + buildPreview2.lpos.normalized * 0.2f, 0.23f, BuildTool._tmp_cols,
                      395264, QueryTriggerInteraction.Collide));

``mask = 395264`` is layers 11 (Vein), 17 (Building Collider) and 18 (Build
Preview) -- so previews DO test against one another.  Every hit is a collision
unless it is excused.  The exemptions that matter here are lines 145859-145887::

    if (component != null && component.index == buildPreview2.previewIndex) continue;   // self
    ...
    if ((buildPreview2.desc.isInserter && !component.buildPreview.desc.isInserter)
     || (!buildPreview2.desc.isInserter && component.buildPreview.desc.isInserter)
     || (!buildPreview2.desc.isBelt && component.buildPreview.desc.isBelt))
        continue;

and then, un-excused, line 145911 ``flag6 = true`` -> line 146071
``buildPreview2.condition = EBuildCondition.Collide``.

Note the guards, because they narrow this a long way:

* a sorter is excused against everything that is not a sorter, and vice versa;
* a machine is excused against a belt -- but **not** the other way round, since
  the third clause tests ``!A.isBelt``, so a belt's sphere hitting a machine is
  a genuine collision;
* belt-vs-belt is excused only when ``dotsCursor > 1`` (line 145875), i.e. a
  dragged multi-paste, never a single one.

What the target box is
----------------------
The colliders a query hits belong to ``BuildPreviewModel.SetCollider``
(line 139317)::

    cols[num].center = colliderData.pos;
    cols[num].size = colliderData.ext * 2f;

-- centre and size only, so the target box's orientation is the preview
transform's rotation (``bp.lrot``) and the collider's own ``q`` is discarded.
The query side keeps ``lrot * cd.q``.  Every build collider in the shipped data
has ``q`` identity, so the two agree in practice; both are modelled faithfully
anyway.

Where world positions come from
-------------------------------
``BlueprintUtils.RefreshBuildPreview`` lines 179977-179997::

    float longitudeRadPerGrid4 = GetLongitudeRadPerGrid(num33, _segmentCnt);
    float longitudeRad = num32 + vector4.x * longitudeRadPerGrid4 * num2;
    float num34 = num33 + vector4.y * latitudeRadPerGrid * num3;
    ...
    buildPreview.lpos = dir * (blueprintBuilding.localOffset_z * 1.3333333f
                               + 0.2f + _planet.realRadius);
    buildPreview.lrot = Maths.SphericalRotation(dir, blueprintBuilding.yaw - (float)num * 90f);

Two things follow.  The longitude step is evaluated ONCE at the anchor latitude,
so it is constant for the whole paste; the latitude step is
``GetLatitudeRadPerGrid = 2 * pi / (segment * 5)`` (line 178071).  And since
``segment = (int)(planet.radius / 4f + 0.1f) * 4`` (line 102684) is the radius
rounded to a multiple of four, the arc between two grid rows is

    realRadius * 2 * pi / (segment * 5)  ~=  2 * pi / 5  =  1.2566 world units

on every planet.  **A tile is 1.2566 units wide, not 1.0.**  That single number
is why a 3.82-wide Assembling Machine cannot sit three tiles from another one:
three tiles is 3.770 units and the two colliders are 3.82 wide together.

Why the default model is FLAT
-----------------------------
Rows are ``GRID_ARC`` apart at every latitude, but COLUMNS are not: the
longitude step is fixed at the anchor's latitude and each building's own
latitude then scales it by ``cos``.  Two Matrix Labs five tiles apart are clear
at the equator (6.283 units) and collide 81 rows north of it (5.487 against a
5.6-wide collider).  That is real -- it is why a blueprint can paste in one
place and not another -- but it is a property of WHERE the paste lands, not of
the blueprint.

So :func:`collisions` evaluates on a flat grid at ``GRID_ARC`` in both axes.
Within the equatorial band that is the supremum of the real spacing
(``cos(lat) <= 1``), so a collision found there is one no paste in that band can
avoid, and latitude compression can only ever add more.  :func:`preview_pose`
keeps the exact spherical formula for anything that wants to ask the
where-can-this-paste question instead.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Protocol

__all__ = [
    "BELT_PROBE_LIFT",
    "BELT_PROBE_RADIUS",
    "Box",
    "GRID_ARC",
    "Preview",
    "belt_chain_excuses",
    "belt_collisions",
    "belt_crossing_height",
    "belt_crossings",
    "belt_probe",
    "belt_run_ends_in_a_building",
    "build_colliders",
    "collisions",
    "obb_overlap",
    "paste_input_links",
    "preview_pose",
    "probe_inside_footprint",
    "sphere_box_overlap",
    "target_boxes",
]

_DATA = Path(__file__).parent / "data" / "colliders.json"

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]

#: Grid rows are ``2 * pi / (segment * 5)`` radians apart and ``segment`` tracks
#: the planet radius, so the arc between adjacent build-grid cells is this on
#: every planet.  Derived above; NOT 1.0, which is what a tile-square footprint
#: model silently assumes.
GRID_ARC = 2.0 * math.pi / 5.0

#: The planet the model is evaluated on.  Any radius gives the same ``GRID_ARC``;
#: the value only sets how fast longitude compresses away from the anchor, and
#: 200 is the standard terrestrial planet.
PLANET_RADIUS = 200.0
PLANET_SEGMENT = 200


class HasModel(Protocol):
    """Anything that names a model, so a caller need not build a :class:`Placed`."""

    @property
    def model_index(self) -> int: ...


@dataclass(frozen=True, slots=True)
class Box:
    """An oriented box in planet-local world space."""

    centre: Vec3
    half: Vec3
    rot: Quat


# --- Unity quaternion arithmetic -------------------------------------------


def _qmul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _qrot(q: Quat, v: Vec3) -> Vec3:
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _norm(v: Vec3) -> Vec3:
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / m, v[1] / m, v[2] / m)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _look_rotation(forward: Vec3, up: Vec3) -> Quat:
    """``Quaternion.LookRotation``."""
    f = _norm(forward)
    r = _cross(up, f)
    r = _norm(r) if _dot(r, r) > 1e-12 else (1.0, 0.0, 0.0)
    u = _cross(f, r)
    m00, m01, m02 = r[0], u[0], f[0]
    m10, m11, m12 = r[1], u[1], f[1]
    m20, m21, m22 = r[2], u[2], f[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


def _spherical_rotation(pos: Vec3, angle_deg: float) -> Quat:
    """``Maths.SphericalRotation``, decompiled line 17747."""
    p = _norm(pos)
    r = _cross(p, (0.0, 1.0, 0.0))
    if _dot(r, r) < 1e-4:
        sign = 1.0 if p[1] >= 0.0 else -1.0
        r = (sign, 0.0, 0.0)
        forward = (0.0, 0.0, sign)
    else:
        r = _norm(r)
        forward = _norm(_cross(r, p))
    q = _look_rotation(forward, p)
    if angle_deg == 0.0:
        return q
    h = math.radians(angle_deg) * 0.5
    return _qmul(q, (0.0, math.sin(h), 0.0, math.cos(h)))


# --- the planet grid --------------------------------------------------------

#: ``PlanetGrid.segmentTable``, decompiled line 102624.  Only entry 200 is
#: reached at the equator, but the whole prefix is needed away from it.
_SEGMENT_TABLE_HEAD = (1, 4, 4, 4, 4, 4, 4, 4)


def _longitude_segment_count(latitude_rad: float, segment: int) -> int:
    """``PlanetGrid.DetermineLongitudeSegmentCount``, decompiled line 103293.

    The table it consults snaps the raw count to a "nice" value.  Reproducing
    the whole 512-entry table here would be dead weight: the model is evaluated
    at the equator (see :func:`collisions`), where ``cos`` is 1 and the raw count
    is already ``segment``.
    """
    lat_index = int(abs(latitude_rad) / _latitude_rad_per_grid(segment) / 5)
    raw = math.ceil(abs(math.cos(lat_index / (segment / 4.0) * math.pi * 0.5)) * segment - 1e-9)
    if raw >= 500:
        return (raw + 49) // 100 * 100
    if raw < len(_SEGMENT_TABLE_HEAD):
        return _SEGMENT_TABLE_HEAD[raw]
    return raw


def _latitude_rad_per_grid(segment: int) -> float:
    """``BlueprintUtils.GetLatitudeRadPerGrid``, decompiled line 178071."""
    return 2.0 * math.pi / (segment * 5)


def preview_pose(
    x: float,
    y: float,
    z: float,
    yaw: float,
    *,
    anchor_lat: float = 0.0,
    anchor_lng: float = 0.0,
    radius: float = PLANET_RADIUS,
    segment: int = PLANET_SEGMENT,
) -> tuple[Vec3, Quat]:
    """``(lpos, lrot)`` for one blueprint building, per ``RefreshBuildPreview``."""
    lat_step = _latitude_rad_per_grid(segment)
    lng_step = 2.0 * math.pi / (_longitude_segment_count(anchor_lat, segment) * 5)
    lng = anchor_lng + x * lng_step
    lat = anchor_lat + y * lat_step
    if abs(lat) > math.pi / 2:
        lat = math.copysign(math.pi / 2, lat)
    cos_lat = math.cos(lat)
    direction = (cos_lat * math.sin(lng), math.sin(lat), cos_lat * -math.cos(lng))
    scale = z * 4.0 / 3.0 + 0.2 + radius
    lpos = (direction[0] * scale, direction[1] * scale, direction[2] * scale)
    return lpos, _spherical_rotation(direction, yaw)


# --- collider table ---------------------------------------------------------


@cache
def _table() -> dict[int, tuple[tuple[Vec3, Vec3, Quat], ...]]:
    raw = json.loads(_DATA.read_text())
    return {
        int(k): tuple(
            (
                (c["pos"][0], c["pos"][1], c["pos"][2]),
                (c["ext"][0], c["ext"][1], c["ext"][2]),
                (c["q"][0], c["q"][1], c["q"][2], c["q"][3]),
            )
            for c in v
        )
        for k, v in raw.items()
    }


def build_colliders(model_index: int) -> tuple[tuple[Vec3, Vec3, Quat], ...]:
    """``PrefabDesc.buildColliders`` for a model, in prefab-local space.

    Empty when the prefab has no Build collider at all, which is
    ``hasBuildCollider == false`` and makes the game skip the test entirely.
    """
    return _table().get(model_index, ())


# --- overlap ----------------------------------------------------------------


def _axes(q: Quat) -> tuple[Vec3, Vec3, Vec3]:
    return (
        _qrot(q, (1.0, 0.0, 0.0)),
        _qrot(q, (0.0, 1.0, 0.0)),
        _qrot(q, (0.0, 0.0, 1.0)),
    )


def obb_overlap(a: Box, b: Box) -> bool:
    """Separating-axis test, matching ``Physics.OverlapBox`` on two boxes."""
    ax = _axes(a.rot)
    bx = _axes(b.rot)
    rot = [[_dot(ax[i], bx[j]) for j in range(3)] for i in range(3)]
    # The epsilon guards the cross-product axes when two boxes are parallel,
    # which every axis-aligned pair here is.
    abs_rot = [[abs(rot[i][j]) + 1e-9 for j in range(3)] for i in range(3)]
    delta = (b.centre[0] - a.centre[0], b.centre[1] - a.centre[1], b.centre[2] - a.centre[2])
    t = (_dot(delta, ax[0]), _dot(delta, ax[1]), _dot(delta, ax[2]))
    ea, eb = a.half, b.half
    for i in range(3):
        ra = ea[i]
        rb = eb[0] * abs_rot[i][0] + eb[1] * abs_rot[i][1] + eb[2] * abs_rot[i][2]
        if abs(t[i]) > ra + rb:
            return False
    for j in range(3):
        ra = ea[0] * abs_rot[0][j] + ea[1] * abs_rot[1][j] + ea[2] * abs_rot[2][j]
        rb = eb[j]
        if abs(t[0] * rot[0][j] + t[1] * rot[1][j] + t[2] * rot[2][j]) > ra + rb:
            return False
    for i in range(3):
        for j in range(3):
            i1, i2 = (i + 1) % 3, (i + 2) % 3
            j1, j2 = (j + 1) % 3, (j + 2) % 3
            ra = ea[i1] * abs_rot[i2][j] + ea[i2] * abs_rot[i1][j]
            rb = eb[j1] * abs_rot[i][j2] + eb[j2] * abs_rot[i][j1]
            span = abs(t[i2] * rot[i1][j] - t[i1] * rot[i2][j])
            if span > ra + rb:
                return False
    return True


@dataclass(frozen=True, slots=True)
class Placed:
    """The minimum a building must expose to be tested."""

    model_index: int
    x: float
    y: float
    z: float
    yaw: float


def flat_pose(x: float, y: float, z: float, yaw: float) -> tuple[Vec3, Quat]:
    """``(lpos, lrot)`` on a flat grid at ``GRID_ARC`` pitch.

    The limit of :func:`preview_pose` as the paste shrinks toward its anchor,
    written in the same local frame the game uses there: ``+x`` tile is east
    (local right), ``+y`` tile is north (local forward), ``+z`` is up, and
    ``yaw`` turns about the local up exactly as ``Maths.SphericalRotation``
    does.  ``z`` keeps the game's 4/3 blueprint-to-world conversion.
    """
    half = math.radians(yaw) * 0.5
    return (
        (x * GRID_ARC, z * 4.0 / 3.0 + 0.2, y * GRID_ARC),
        (0.0, math.sin(half), 0.0, math.cos(half)),
    )


def _query_boxes(p: Placed, lpos: Vec3, lrot: Quat) -> list[Box]:
    """The overlap query, ``CheckBuildConditions`` lines 145751-145752."""
    out = []
    for pos, ext, q in build_colliders(p.model_index):
        r = _qrot(lrot, pos)
        out.append(Box((lpos[0] + r[0], lpos[1] + r[1], lpos[2] + r[2]), ext, _qmul(lrot, q)))
    return out


def target_boxes(p: HasModel, lpos: Vec3, lrot: Quat) -> list[Box]:
    """The preview model's colliders, ``BuildPreviewModel.SetCollider``.

    Centre and size only -- the collider's own ``q`` never reaches the
    ``BoxCollider``, so the box inherits the preview transform's rotation.
    """
    out = []
    for pos, ext, _q in build_colliders(p.model_index):
        r = _qrot(lrot, pos)
        out.append(Box((lpos[0] + r[0], lpos[1] + r[1], lpos[2] + r[2]), ext, lrot))
    return out


def collisions(
    buildings: list[Placed],
    *,
    anchor_lat: float | None = None,
    anchor_lng: float = 0.0,
    radius: float = PLANET_RADIUS,
    segment: int = PLANET_SEGMENT,
) -> list[tuple[int, int]]:
    """Indices of pairs the game would reject with ``EBuildCondition.Collide``.

    Scope is deliberately the case that is settled: a preview whose box overlaps
    another preview's box, with neither a belt nor a sorter.  Those two are
    excluded because the game excuses them, or because the model for them is not
    yet trustworthy:

    * A sorter is excused against everything that is not a sorter and vice versa
      (line 145871), so it can only ever collide with another sorter -- and a
      sorter's own box is rebuilt from the pose of the buildings it connects
      (lines 145718-145746, and ``RefreshBuildPreview`` lines 180039-180096
      re-seats ``lpos`` onto ``desc.slotPoses``).  That needs slot data this
      repository is currently known to have wrong, so it is left out rather than
      guessed at.
    * A belt IS tested, as a 0.23 sphere rather than a box, and a belt hitting a
      machine is NOT excused.  But that model over-reports on real blueprints --
      it flags belts three tiles from an Interstellar Logistics Station in
      ``12-s-purple-science``, which the game wrote -- so something about it is
      still wrong and shipping it would break the negative control.  Excluded
      until it can be made to pass.

    By default the flat model is used -- see "Why the default model is FLAT" in
    the module docstring.  Every pair reported is then one that no paste in the
    equatorial band can avoid, which is what makes this safe to raise as an
    error rather than a maybe.  Pass ``anchor_lat`` to ask the other question
    instead: what happens if this blueprint is pasted THERE, latitude
    compression included.  The two differ a lot on a tall blueprint -- one
    ``information-matrix`` layout gives 5 pairs flat, 15 anchored at the equator
    and 28 anchored at 0.3 radians.
    """
    poses = [
        flat_pose(b.x, b.y, b.z, b.yaw)
        if anchor_lat is None
        else preview_pose(
            b.x, b.y, b.z, b.yaw, anchor_lat=anchor_lat, anchor_lng=anchor_lng,
            radius=radius, segment=segment,
        )
        for b in buildings
    ]
    targets = [target_boxes(b, *poses[i]) for i, b in enumerate(buildings)]

    # Broad phase.  Every build collider is well under this, so one cell plus
    # its 26 neighbours bounds any overlap.
    cell_size = 32.0
    grid: dict[tuple[int, int, int], set[int]] = {}
    for i, boxes in enumerate(targets):
        for box in boxes:
            key = tuple(int(math.floor(box.centre[k] / cell_size)) for k in range(3))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        grid.setdefault((key[0] + dx, key[1] + dy, key[2] + dz), set()).add(i)

    hits: set[tuple[int, int]] = set()
    for i, b in enumerate(buildings):
        for query in _query_boxes(b, *poses[i]):
            key = (
                int(math.floor(query.centre[0] / cell_size)),
                int(math.floor(query.centre[1] / cell_size)),
                int(math.floor(query.centre[2] / cell_size)),
            )
            for j in grid.get(key, ()):
                pair = (i, j) if i < j else (j, i)
                if j == i or pair in hits:
                    continue
                if any(obb_overlap(query, other) for other in targets[j]):
                    hits.add(pair)
    return sorted(hits)


# --- belts ------------------------------------------------------------------
#
# A belt is not tested with its build collider.  The SAME query loop in
# ``BuildTool_BlueprintPaste.CheckBuildConditions`` branches on ``isBelt``
# (decompiled line 145761)::
#
#     int num17 = ((!buildPreview2.desc.isBelt)
#         ? Physics.OverlapBoxNonAlloc(colliderData.pos, colliderData.ext,
#               BuildTool._tmp_cols, colliderData.q, mask, QueryTriggerInteraction.Collide)
#         : Physics.OverlapSphereNonAlloc(buildPreview2.lpos
#               + buildPreview2.lpos.normalized * 0.2f, 0.23f, BuildTool._tmp_cols,
#               395264, QueryTriggerInteraction.Collide));
#
# ``lpos.normalized`` is radial up, so the probe is a 0.23 sphere centred 0.2
# ABOVE the belt node -- one probe per belt TILE, since a blueprint stores every
# belt tile as its own building.  The interactive belt tool asks the same
# question one size larger: ``BuildTool_Path`` line 157520 uses 0.28 at
# ``+ 0.22``, as a capsule between the 0.65-scaled neighbour positions when the
# belt has a belt input or output.  What decides whether OUR blueprint pastes is
# the paste query, so the paste numbers are the ones here.
#
# THIS IS THE ANSWER TO "MAY A BELT CROSS A BUILDING, AND AT WHAT HEIGHT".  It
# may.  The test is three-dimensional and the probe is small, so a belt high
# enough that the sphere clears the building's build collider does not collide
# with it, and one whose sphere passes UNDER a raised collider does not either.
# Nothing else in the paste path re-tests it: the only other belt-specific query
# is a terrain/vein probe against layer 11 (line 146093) that an empty flat
# planet cannot fail.
#
# The direction is asymmetric.  The excusal at line 145872 reads::
#
#     || (!buildPreview2.desc.isBelt && component.buildPreview.desc.isBelt)
#
# so a MACHINE is excused against a belt and a BELT is not excused against a
# machine.  A belt that fails to clear is a real ``Collide`` even though the
# machine testing the same pair says nothing.
#
# ``isBelt`` is exactly "has a ``BeltDesc`` whose speed is positive''
# (``PrefabDesc.ReadPrefab`` line 217564, ``isBelt = beltSpeed > 0``).  A
# Splitter takes the ``SplitterDesc`` branch four lines later and sets
# ``isSplitter``, NOT ``isBelt``, so a Splitter is box-tested like any machine
# and this rule does not govern it.

#: Radius of the belt probe sphere, ``CheckBuildConditions`` line 145761.
BELT_PROBE_RADIUS = 0.23

#: How far above the belt node the probe sphere is centred, same line.  It is
#: SMALLER than the radius, so the probe reaches 0.03 units BELOW the node.
BELT_PROBE_LIFT = 0.2


def belt_probe(x: float, y: float, z: float) -> Vec3:
    """Centre of the sphere the game tests a belt tile with, in the flat frame.

    ``lpos + lpos.normalized * BELT_PROBE_LIFT``, written in the local frame
    :func:`flat_pose` uses, where radial up is ``+y``.
    """
    return (x * GRID_ARC, z * 4.0 / 3.0 + 0.2 + BELT_PROBE_LIFT, y * GRID_ARC)


def sphere_box_overlap(centre: Vec3, radius: float, box: Box) -> bool:
    """``Physics.OverlapSphere`` against one oriented box.

    Squared closest-point-on-box distance, which is what Unity's sphere-vs-box
    narrow phase computes.  Touching exactly does not overlap.
    """
    inv = (-box.rot[0], -box.rot[1], -box.rot[2], box.rot[3])
    d = _qrot(
        inv,
        (centre[0] - box.centre[0], centre[1] - box.centre[1], centre[2] - box.centre[2]),
    )
    out = 0.0
    for i in range(3):
        excess = abs(d[i]) - box.half[i]
        if excess > 0.0:
            out += excess * excess
    return out < radius * radius


def belt_crossing_height(model_index: int) -> float:
    """Lowest blueprint ``z`` at which a belt tile clears this model's collider.

    The vertical half of the rule above, solved for a building standing at
    ``z = 0``: the probe's lowest point is ``z * 4/3 + 0.2 + LIFT - RADIUS`` and
    the collider's top is ``0.2 + max(pos.y + ext.y)``, so the belt clears when

        ``z > (top + RADIUS - LIFT) * 3/4``

    Strictly greater.  The returned value is that bound, NOT a legal ``z``; a
    caller wanting one rounds it up to :data:`flab2bp.dsp.catalog.BELT_Z_QUANTUM`.
    ``0.0`` for a model with no build collider, which is
    ``hasBuildCollider == false`` and skips the test entirely.

    Add the building's own ``z`` for a building that is not on the ground.  This
    answers the vertical question only: a belt beside a building, rather than
    over it, is decided by :func:`belt_crossings`.
    """
    cols = build_colliders(model_index)
    if not cols:
        return 0.0
    top = max(pos[1] + ext[1] for pos, ext, _q in cols)
    return (top + BELT_PROBE_RADIUS - BELT_PROBE_LIFT) * 3.0 / 4.0


def probe_inside_footprint(centre: Vec3, box: Box) -> bool:
    """Whether a point is inside a box's footprint, ignoring height."""
    inv = (-box.rot[0], -box.rot[1], -box.rot[2], box.rot[3])
    d = _qrot(
        inv,
        (centre[0] - box.centre[0], centre[1] - box.centre[1], centre[2] - box.centre[2]),
    )
    return abs(d[0]) <= box.half[0] and abs(d[2]) <= box.half[2]


def belt_crossings(
    belts: list[Placed], buildings: list[Placed], *, directly_over_only: bool = False
) -> list[tuple[int, int]]:
    """``(belt index, building index)`` pairs the game would call ``Collide``.

    Each belt's probe sphere against each building's build collider, on the flat
    grid :func:`collisions` uses and for the same reason.

    Nothing is excused here.  The caller must leave out what the game excuses,
    because which of those a placement contains is the caller's fact: sorters
    (line 145871, in both directions), belt addons (``AddonPass``, lines 145885
    and 146029), other belts (line 145875) and a belt a building covers (lines
    145970-146003).

    The excusal that matters most is not in this file at all, because it is a
    property of the preview GRAPH rather than of geometry: a belt marked
    ``Collide`` here is re-probed at 147384 and put back to ``Ok`` when every
    hit is a building it reaches within three belt hops along its own run
    (147451), or when the run ends in a buildable non-belt building (147492).
    ``layout.validate.game.belt_crossing`` is where that lives, with the C#.
    Raw, this function flags 1189 belts across the fixture corpus in blueprints
    the game itself wrote; with those excusals applied, zero, on every fixture
    whose geometry the model can place.

    ``directly_over_only`` narrows the answer to belts whose probe centre is
    inside the collider's FOOTPRINT -- the crossing question alone, "how high
    must a belt be to pass over this".  It is not the shipped rule any more; it
    remains because the crossing question is still worth asking on its own, and
    because ``belt_crossing_height`` answers it in closed form.  Over the
    single-area fixtures 133 belts pass over or under a collider and clear it,
    so neither form of the test is vacuous.
    """
    hits: list[tuple[int, int]] = []
    for i, belt in enumerate(belts):
        probe = belt_probe(belt.x, belt.y, belt.z)
        for j, b in enumerate(buildings):
            lpos, lrot = flat_pose(b.x, b.y, b.z, b.yaw)
            for box in target_boxes(b, lpos, lrot):
                if directly_over_only and not probe_inside_footprint(probe, box):
                    continue
                if sphere_box_overlap(probe, BELT_PROBE_RADIUS, box):
                    hits.append((i, j))
                    break
    return hits


# --- the whole belt verdict, excusals included ------------------------------


@dataclass(frozen=True)
class Preview:
    """One paste preview, carrying what ``CheckBuildConditions`` asks of it.

    The flags are ``PrefabDesc``'s own, not a taxonomy invented here: the rule
    branches on ``isBelt``, ``isInserter``, ``isSplitter`` and
    ``addonType == EAddonType.Belt`` and on nothing else about what a building
    is.  ``output`` and ``input`` are indices into the same sequence -- the
    blueprint's ``outputObj`` / ``inputObj``, which is what
    ``BlueprintUtils.InitBuildPreviewByBPData`` (179570-179572) loads them from.
    """

    model_index: int
    x: float
    y: float
    z: float
    yaw: float = 0.0
    is_belt: bool = False
    is_inserter: bool = False
    is_splitter: bool = False
    is_belt_addon: bool = False
    output: int | None = None
    input: int | None = None


def _resolve(previews: Sequence[Preview], j: int | None) -> int | None:
    """A link, or ``None`` when it names nothing in this sequence.

    A blueprint the game wrote never dangles, but a placement under validation
    may: ``geom.belt_continuity`` exists to report exactly that, and this rule
    must not crash before that check gets to speak.
    """
    return j if j is not None and 0 <= j < len(previews) else None


def paste_input_links(previews: Sequence[Preview]) -> tuple[int | None, ...]:
    """``BuildPreview.input`` as the paste path leaves it, per preview.

    A DSP blueprint records a belt chain in ONE direction: every belt names its
    successor in ``outputObj`` and almost every belt's ``inputObj`` is empty.
    The paste materialises the reverse links itself, before any condition is
    checked (``BuildTool_BlueprintPaste.ArrangeOverlapBP``, 144472-144479)::

        if (buildPreview.desc.isBelt && buildPreview.output != null
            && buildPreview.output.desc.isBelt)
        {
            buildPreview.output.input = buildPreview;
        }

    Ascending, so a merge leaves the last feeder in place, and it OVERWRITES a
    belt's recorded non-belt input.  See :func:`belt_collisions` for why this is
    load-bearing and for the one thing about it that is not settled.
    """
    links: list[int | None] = [_resolve(previews, p.input) for p in previews]
    for i, p in enumerate(previews):
        j = _resolve(previews, p.output)
        if p.is_belt and j is not None and previews[j].is_belt:
            links[j] = i
    return tuple(links)


def _hops(
    previews: Sequence[Preview],
    links: Sequence[int | None],
    belt: int,
    *,
    downstream: bool,
) -> tuple[int | None, int | None, int | None]:
    """The 1st, 2nd and 3rd preview along a belt's own run from ``belt``.

    ``CheckBuildConditions`` 147451 spells the walk out longhand and guards each
    step on the PREVIOUS node being a belt -- ``bp.output.output`` is only
    consulted when ``bp.output.desc.isBelt`` -- so a chain that reaches a
    machine stops there rather than continuing through its ports.
    """
    out: list[int | None] = [None, None, None]
    cur = belt
    for n in range(3):
        nxt = _resolve(previews, previews[cur].output) if downstream else links[cur]
        out[n] = nxt
        if nxt is None or not previews[nxt].is_belt:
            break
        cur = nxt
    return out[0], out[1], out[2]


def belt_chain_excuses(
    previews: Sequence[Preview], links: Sequence[int | None], belt: int, other: int
) -> bool:
    """``CheckBuildConditions`` 147443-147453, for one belt against one hit.

    ``other`` is a preview the belt's probe overlapped, and the answer is
    whether the belt's own run reaches it within three hops -- or, when it is a
    Splitter, reaches either of the previews that Splitter is linked to within
    two::

        int num156 = ((bp13.previewIndex == -1) ? (-2) : bp13.previewIndex);
        int num157 = ((bp13.desc.isSplitter && bp13.output != null)
                          ? bp13.output.previewIndex : (-2));
        int num158 = ((bp13.desc.isSplitter && bp13.input != null)
                          ? bp13.input.previewIndex : (-2));
        if ((bp12.output != null
                && (bp12.output.previewIndex == num156 || == num157 || == num158))
            || (bp12.output != null && bp12.output.desc.isBelt
                && bp12.output.output != null && (... == num156 || num157 || num158))
            || (... && bp12.output.output.output.previewIndex == num156)
            || (bp12.input != null && (... == num156 || num157 || num158))
            || (bp12.input != null && bp12.input.desc.isBelt
                && bp12.input.input != null && (... == num156 || num157 || num158))
            || (... && bp12.input.input.input.previewIndex == num156))
        {
            continue;
        }

    The third hop matches only the hit itself, never the Splitter's neighbours;
    that asymmetry is the game's and is reproduced.
    """
    near: set[int | None] = {other}
    if previews[other].is_splitter:
        near.add(_resolve(previews, previews[other].output))
        near.add(links[other])
    near.discard(None)
    for downstream in (True, False):
        one, two, three = _hops(previews, links, belt, downstream=downstream)
        if one in near or two in near or three == other:
            return True
    return False


def belt_run_ends_in_a_building(
    previews: Sequence[Preview], links: Sequence[int | None], belt: int
) -> bool:
    """``CheckBuildConditions`` 147492-147500.

    After the excusals, a belt with an unexcused hit left is STILL let off when
    the thing it feeds or draws from is a non-belt building the game can
    build::

        if (buildPreview12.output != null && !buildPreview12.output.desc.isBelt
            && buildPreview12.output.condition == EBuildCondition.Ok)
        { buildPreview12.condition = ...EBuildCondition.Ok; }

    with the mirror clause for ``input`` two lines down.  The game consults that
    building's own ``condition``; a caller validating a placement has separate
    findings for whether a building is legal, so this reads it as legal.

    Measured, this clause costs nothing on the corpus: with it removed the
    single-area fixtures still give zero.  It is here because the game has it,
    and leaving it out would make the check STRICTER than the game -- a refusal
    where the game builds.
    """
    for j in (_resolve(previews, previews[belt].output), links[belt]):
        if j is not None and not previews[j].is_belt:
            return True
    return False


def belt_collisions(previews: Sequence[Preview]) -> list[tuple[int, int]]:
    """``(belt, building)`` pairs a blueprint paste would call ``Collide``.

    The whole belt verdict, lateral half included: the 0.23 probe of
    :func:`belt_crossings` and every excusal the paste path applies to it.

    A hit is not the verdict.  ``CheckBuildConditions`` sets a belt's condition
    to ``Collide`` at 146072 WITHOUT calling ``AddErrorMessage`` -- the one
    branch in that method that stays silent -- because a later pass over the
    belts, at 147257, re-probes every belt already marked ``Collide`` and can
    put it back to ``Ok``.  That pass is what the lateral half was missing, and
    :func:`belt_chain_excuses` and :func:`belt_run_ends_in_a_building` are its
    two clauses.  Before them, the same loop excuses by ``PrefabDesc`` flag:
    a sorter (the ``isInserter`` asymmetry at 147437, in both directions) and a
    belt addon (147454, ``AddonPass``'s twin) are never a collision for a belt.
    Belt on belt is left out here -- it is a single-occupancy question, and the
    game's own answer to it turns on ``dotsCursor``.

    ONE DETAIL IS READ BUT NOT SETTLED, and it decides whether the upstream half
    of 147451 is reachable at all.  ``ArrangeOverlapBP`` materialises the
    reverse belt links at 144472-144479 (:func:`paste_input_links`) and then
    CLEARS them again at 144554-144560::

        if (buildPreview5.desc.isBelt && buildPreview5.input != null
            && buildPreview5.input.desc.isBelt)
        {
            buildPreview5.input = null;
        }

    Taken at face value that makes the three ``input`` clauses dead on a paste.
    The corpus refutes it.  With them dead, 25 belts across the single-area
    fixtures are convicted in blueprints the game itself wrote -- 4 against a
    Splitter at exact, uncontaminated spacing, 21 against a station -- and each
    of the 4 is the second or third node of a run leaving a Splitter, which is
    exactly what those clauses describe.  With the reverse links live, ZERO are
    convicted across every fixture whose geometry this model can place.  So
    either the clearing does not survive to 147384 or something restores it;
    what is MEASURED is that the rule is symmetric, and that is what is here.

    ONE SIMPLIFICATION, in the conservative direction.  The re-probe at 147384
    is not always the same sphere: when a belt has a belt on BOTH sides it uses
    ``Physics.OverlapCapsuleNonAlloc`` between its neighbours scaled to 0.65 and
    pulled 0.45 back toward the middle.  On a straight run that collapses to a
    segment of +-0.065 tiles about the node -- the sphere, to three decimals --
    but on a corner it shifts about 0.46 tiles toward the outside of the turn.
    The hits fed to the excusals here are the MAIN loop's sphere in every case.
    That can only convict where the game would excuse, never the reverse: the
    belt is already ``Collide`` when this pass begins, so the pass can lower the
    verdict and never raise it, and a hit the capsule would have missed is one
    the game drops.  It costs nothing on the corpus -- zero either way -- and
    modelling it would mean carrying neighbour positions into a query that is
    otherwise pure geometry.

    Not vacuous, and the falsifier is the same measurement run the other way:
    the raw probe flags 1189 belts over the fixture corpus, so a sample that
    could not have shown a residue is not what this is.
    """
    links = paste_input_links(previews)
    poses = [flat_pose(p.x, p.y, p.z, p.yaw) for p in previews]
    boxes = [
        target_boxes(p, *poses[i]) if not p.is_belt else [] for i, p in enumerate(previews)
    ]
    cell = 8.0
    grid: dict[tuple[int, int], list[int]] = {}
    for j, bxs in enumerate(boxes):
        for box in bxs:
            key = (int(box.centre[0] // cell), int(box.centre[2] // cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    grid.setdefault((key[0] + dx, key[1] + dy), []).append(j)
    hits: list[tuple[int, int]] = []
    for i, belt in enumerate(previews):
        if not belt.is_belt:
            continue
        probe = belt_probe(belt.x, belt.y, belt.z)
        key = (int(probe[0] // cell), int(probe[2] // cell))
        bad: list[int] = []
        for j in dict.fromkeys(grid.get(key, ())):
            if j == i:
                continue
            other = previews[j]
            if other.is_inserter or other.is_belt_addon:
                continue
            if not any(sphere_box_overlap(probe, BELT_PROBE_RADIUS, b) for b in boxes[j]):
                continue
            if belt_chain_excuses(previews, links, i, j):
                continue
            bad.append(j)
        if not bad or belt_run_ends_in_a_building(previews, links, i):
            continue
        hits.extend((i, j) for j in sorted(bad))
    return hits
