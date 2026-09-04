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
from functools import cache, lru_cache
from pathlib import Path
from typing import Protocol

__all__ = [
    "BELT_PROBE_LIFT",
    "BELT_PROBE_RADIUS",
    "Box",
    "GRID_ARC",
    "Preview",
    "StableBeltCollision",
    "belt_chain_excuses",
    "belt_collisions",
    "stable_belt_collisions",
    "belt_crossing_height",
    "belt_crossings",
    "belt_keepout_offsets",
    "belt_probe",
    "belt_run_ends_in_a_building",
    "build_colliders",
    "collisions",
    "obb_overlap",
    "own_centre_extent",
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

#: ``PlanetGrid.segmentTable``, ``PlanetGrid.cs:19-80``.  All 512 entries.
#:
#: This was ``_SEGMENT_TABLE_HEAD``, the first EIGHT entries, cited as
#: "decompiled line 102624" -- a number that resolves under neither line-number
#: convention this repository uses; the table is at ``PlanetGrid.cs:19``.
#: :func:`_longitude_segment_count` fell through to ``return raw`` for every
#: index from 8 to 499, and ``segmentTable[i] != i`` for **478 of those 492**.
#: The port was right at exactly the indices where the table happens to be the
#: identity, and ``200`` -- the only one the equatorial model reaches -- is one
#: of them.  That is why nothing caught it.
#:
#: The table takes only 17 distinct values, so it maps the 512 latitude indices
#: onto 17 BANDS.  A blueprint's recorded ``area_segments`` is an output of this
#: table, and therefore names a band and not a latitude; fitting a single
#: latitude to one is fitting a point to a band.
_SEGMENT_TABLE = (
    1,
    4,
    4,
    4,
    4,
    4,
    4,
    4,
    8,
    8,
    8,
    8,
    8,
    8,
    8,
    8,
    16,
    16,
    16,
    16,
    20,
    20,
    20,
    20,
    20,
    20,
    20,
    20,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    40,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    60,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    80,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    120,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    160,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    200,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    240,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    300,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    400,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
)


def _longitude_segment_count(latitude_rad: float, segment: int) -> int:
    """``BlueprintUtils.GetLongitudeSegmentCount(float)``, exactly.

    ``BlueprintUtils.cs:209-220`` first snaps latitude to a grid row with
    ``_round2int(latitude / GetLatitudeRadPerGrid())``, takes the absolute row,
    decrements every non-equatorial row, and only then divides by five and calls
    ``PlanetGrid.DetermineLongitudeSegmentCount``.

    The former local port divided first, omitted the decrement, used double
    cosine arithmetic, and subtracted a ``1e-9`` fudge before ``ceil``.  It was
    wrong in 300 ``(segment, latitude)`` cases including every pole.  Delegate
    the band lookup to :mod:`flab2bp.dsp.planet`, which owns the exact float32
    implementation and the decrement; this wrapper only performs the
    float-latitude snapping that its integer API deliberately does not.
    """
    from flab2bp.dsp import planet

    scaled = latitude_rad / _latitude_rad_per_grid(segment)
    grid_idx = int(scaled + 0.5) if scaled > 0.0 else int(scaled - 0.5)
    return planet.longitude_segment_count(grid_idx, segment)


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


@cache
def own_centre_extent(model_index: int, yaw: float) -> tuple[float, float]:
    """Full width and depth, in world units, of the smallest box about the
    building's OWN centre that contains every build collider at ``yaw``.

    The collider set is not symmetric about the prefab origin -- a Chemical
    Plant's boxes run from x = -4.0 to x = +4.3 -- and the building is placed by
    its centre, so the figure that matters is ``max |c +- h|`` per axis, taken
    over the corners after turning.  A corner sweep rather than composed
    rotation matrices: it is the same answer and obviously the same answer.

    ``catalog.derive_footprint`` and ``catalog.clearance`` both read this.  They
    ask different questions of it -- which tile centres are covered, and how far
    apart two of these must be -- and neither may be answered from
    ``blueprintBoxSize``, which the game derives from the LAST Build box and
    which is therefore the one box ``buildColliders`` excludes.
    """
    boxes = build_colliders(model_index)
    if not boxes:
        return (0.0, 0.0)
    half_turn = math.radians(yaw) * 0.5
    spin = (0.0, math.sin(half_turn), 0.0, math.cos(half_turn))
    ex = ez = 0.0
    for centre, half, rot in boxes:
        turned = _qmul(spin, rot)
        corner = _qrot(spin, centre)
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    spun = _qrot(turned, (sx * half[0], sy * half[1], sz * half[2]))
                    ex = max(ex, abs(corner[0] + spun[0]))
                    ez = max(ez, abs(corner[2] + spun[2]))
    return (ex * 2.0, ez * 2.0)


# --- overlap ----------------------------------------------------------------


@cache
def _axes(q: Quat) -> tuple[Vec3, Vec3, Vec3]:
    return (
        _qrot(q, (1.0, 0.0, 0.0)),
        _qrot(q, (0.0, 1.0, 0.0)),
        _qrot(q, (0.0, 0.0, 1.0)),
    )


@cache
def _box_radius(half: Vec3) -> float:
    """Bounding-sphere radius shared by every instance of one collider box."""
    return math.sqrt(half[0] * half[0] + half[1] * half[1] + half[2] * half[2])


def obb_overlap(a: Box, b: Box) -> bool:
    """Separating-axis test, matching ``Physics.OverlapBox`` on two boxes."""
    delta = (
        b.centre[0] - a.centre[0],
        b.centre[1] - a.centre[1],
        b.centre[2] - a.centre[2],
    )
    radius = _box_radius(a.half) + _box_radius(b.half)
    if delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2 > radius**2:
        return False
    ax = _axes(a.rot)
    bx = _axes(b.rot)
    rot = [[_dot(ax[i], bx[j]) for j in range(3)] for i in range(3)]
    # The epsilon guards the cross-product axes when two boxes are parallel,
    # which every axis-aligned pair here is.
    abs_rot = [[abs(rot[i][j]) + 1e-9 for j in range(3)] for i in range(3)]
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
      re-seats ``lpos`` onto ``desc.slotPoses``).

      THE REASON THIS IS OUT IS THE RE-SEATING, NOT THE DATA.  It used to say
      "that needs slot data this repository is currently known to have wrong",
      and that has not been true since the real ``slotPoses`` were extracted
      from the prefabs.  What is still missing is the rebuild: a sorter's
      ``buildColliders`` is one box of half-extents ``(0.26, 0.15, 0.115)``, and
      testing it where the record puts it is refuted by the game's own output --
      **53 pairs closer than 0.52 units among the 1132 sorters in the five
      single-area fixtures**, in blueprints that paste.  Porting 180039-180096
      is what would make the question answerable; until then this reports
      nothing about sorters rather than reporting those 53 shapes as errors.
      ``test_a_raw_sorter_box_test_convicts_blueprints_the_game_wrote`` pins
      both halves.
    * A belt IS tested, as a 0.23 sphere rather than a box, and a belt hitting a
      machine is NOT excused -- but not HERE.  That model lives in
      :func:`belt_crossings` and, with the paste's own excusals applied, in
      :func:`belt_collisions`; the over-reporting recorded here (belts three
      tiles from an Interstellar Logistics Station in ``12-s-purple-science``,
      which the game wrote) was the excusals missing, and with them the fixture
      corpus goes from 1189 raw findings to zero.  Belts stay out of THIS
      function because their verdict needs the preview graph, which a list of
      boxes does not carry.

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
            b.x,
            b.y,
            b.z,
            b.yaw,
            anchor_lat=anchor_lat,
            anchor_lng=anchor_lng,
            radius=radius,
            segment=segment,
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


# --- sorters ----------------------------------------------------------------

#: How far a sorter's collider grows past an end that meets a BELT, or nothing.
#: ``CheckBuildConditions`` 2137-2158 of the decompiled
#: ``BuildTool_BlueprintPaste``.  The shift and the growth are the same number,
#: so the box grows on that side only -- by ``2 * 0.35``, since the shift moves
#: the far face out as well.
SORTER_END_EXTENSION = 0.35

#: Floor on the stretched half-length, same passage.  It does NOT undo the
#: shift, which is why two very short sorters can still be pushed into contact.
SORTER_HALF_LENGTH_MIN = 0.1


@dataclass(frozen=True)
class SorterPreview:
    """One sorter as the paste tests it, in blueprint local-offset coordinates.

    ``(x, y, z)`` is ``BuildPreview.lpos`` -- the end the sorter draws FROM --
    and ``(x2, y2, z2)`` is ``lpos2``, the end it feeds INTO.  Both must already
    be SEATED: ``BlueprintUtils.RefreshBuildPreview`` moves each end onto the
    slot pose it names before any condition is evaluated::

        Pose pose = buildPreview2.input.desc.slotPoses[buildPreview2.inputFromSlot];
        Pose transformedBy = pose.GetTransformedBy(
            new Pose(buildPreview2.input.lpos, buildPreview2.input.lrot));
        buildPreview2.lpos = transformedBy.position;

    guarded by ``!buildPreview2.input.desc.isBelt``, and symmetrically for
    ``lpos2`` against ``outputToSlot``.  So where WE put a sorter's machine end
    does not survive the paste: the slot INDEX decides it.  A caller that passes
    the tile centre it emitted is asking a question about a sorter the game will
    not build.

    ``input_open`` and ``output_open`` are the branch conditions on that end --
    true when it meets a belt (``desc.isBelt``) or meets nothing at all
    (``inputObjId == 0 && input == null``).  Both cases extend the box; a machine
    end does not.
    """

    model_index: int
    x: float
    y: float
    z: float
    x2: float
    y2: float
    z2: float
    input_open: bool = True
    output_open: bool = True


def sorter_box(p: SorterPreview) -> Box:
    """A sorter's build collider, stretched between its two ends.

    A sorter is the one building whose collider is not the prefab box placed at
    the record's position.  ``BuildTool_BlueprintPaste.CheckBuildConditions``
    rebuilds it (decompiled ``BuildTool_BlueprintPaste`` 2136-2166)::

        if (buildPreview2.desc.isInserter)
        {
            colliderData.ext = new Vector3(colliderData.ext.x, colliderData.ext.y,
                Vector3.Distance(lpos2, lpos) * 0.5f + colliderData.ext.z - 0.5f);
            if (ObjectIsBelt(inputObjId) || (input != null && input.desc.isBelt))
            { colliderData.pos.z -= 0.35f; colliderData.ext.z += 0.35f; }
            else if (inputObjId == 0 && input == null)
            { colliderData.pos.z -= 0.35f; colliderData.ext.z += 0.35f; }
            if (ObjectIsBelt(outputObjId) || (output != null && output.desc.isBelt))
            { colliderData.pos.z += 0.35f; colliderData.ext.z += 0.35f; }
            else if (outputObjId == 0 && output == null)
            { colliderData.pos.z += 0.35f; colliderData.ext.z += 0.35f; }
            if (colliderData.ext.z < 0.1f) colliderData.ext.z = 0.1f;
            colliderData.pos = vector2 + quaternion * colliderData.pos;
            colliderData.q = quaternion * colliderData.q;
        }

    with, from the same method 1848-1854::

        Vector3 vector2 = Vector3.Lerp(lpos, lpos2, 0.5f);
        Vector3 forward2 = lpos2 - lpos;
        Quaternion quaternion = Quaternion.LookRotation(
            forward2, (lrot * Vector3.up + lrot2 * Vector3.up).normalized);

    So the box is centred on the MIDPOINT of the two ends, its local ``+z``
    runs from ``lpos`` toward ``lpos2``, and it is as long as the sorter plus
    :data:`SORTER_END_EXTENSION` past each open end.  ``ext.x`` and ``ext.y``
    stay the prefab's -- 0.26 and 0.15, so the box is 0.52 wide, which is
    0.41 of a 1.2566-unit tile.

    The TARGET side agrees, and that had to be checked separately: the box a
    query hits belongs to ``BuildPreviewModel.SetCollider``, which repeats this
    same stretch verbatim, on a transform ``BuildModel.AddPreviewModel`` seats at
    ``(bp.lpos + bp.lpos2) * 0.5f`` with the same ``LookRotation``.  Both sides
    of the test are therefore this box.  ``BuildTool_BlueprintPaste`` 1749-1770
    is what puts those colliders in the world during a paste, so this is the
    paste's test and not only the interactive tool's.
    """
    lpos, _ = flat_pose(p.x, p.y, p.z, 0.0)
    lpos2, _ = flat_pose(p.x2, p.y2, p.z2, 0.0)
    (pos, ext, q) = build_colliders(p.model_index)[0]

    half_z = math.dist(lpos, lpos2) * 0.5 + ext[2] - 0.5
    off_z = pos[2]
    if p.input_open:
        off_z -= SORTER_END_EXTENSION
        half_z += SORTER_END_EXTENSION
    if p.output_open:
        off_z += SORTER_END_EXTENSION
        half_z += SORTER_END_EXTENSION
    half_z = max(half_z, SORTER_HALF_LENGTH_MIN)

    forward = (lpos2[0] - lpos[0], lpos2[1] - lpos[1], lpos2[2] - lpos[2])
    if _dot(forward, forward) < 1e-4:
        # ``forward2 = Maths.SphericalRotation(lpos, 0f).Forward()``, which on
        # the flat model is local north.
        forward = (0.0, 0.0, 1.0)
    rot = _look_rotation(forward, (0.0, 1.0, 0.0))
    centre = _qrot(rot, (pos[0], pos[1], off_z))
    mid = (
        (lpos[0] + lpos2[0]) * 0.5,
        (lpos[1] + lpos2[1]) * 0.5,
        (lpos[2] + lpos2[2]) * 0.5,
    )
    return Box(
        (mid[0] + centre[0], mid[1] + centre[1], mid[2] + centre[2]),
        (ext[0], ext[1], half_z),
        _qmul(rot, q),
    )


def sorter_collisions(previews: Sequence[SorterPreview]) -> list[tuple[int, int]]:
    """Index pairs of sorters the game rejects with ``EBuildCondition.Collide``.

    Sorter-on-sorter is the ONE pairing the paste's collision excusal does not
    forgive.  ``CheckBuildConditions`` 2290 reads::

        if ((buildPreview2.desc.isInserter && !component.buildPreview.desc.isInserter)
         || (!buildPreview2.desc.isInserter && component.buildPreview.desc.isInserter)
         || (!buildPreview2.desc.isBelt && component.buildPreview.desc.isBelt))
            continue;

    -- an exclusive OR.  A sorter is excused against everything that is not a
    sorter, and everything that is not a sorter is excused against a sorter, so
    the only un-excused hit a sorter can score is against another sorter, and
    that one is a real ``Collide``.  Nothing later takes it back: the second pass
    at 3558-3670 re-runs the identical query and the identical excusal, and only
    for a sorter one of whose peers is COVERING an existing building.

    This is why the pairing matters at all, and it is not a theory: it is the
    error the user's game reported, by name, on the two clusters this function
    convicts in ``tests/fixtures/sorter-collide-freeform.txt``.

    THE FIXTURE COUNTER-MEASUREMENT, which is what makes it safe to raise as an
    error.  Over the 1132 sorters in the five single-area fixtures -- blueprints
    the game itself wrote -- this reports ZERO pairs.  That is not a vacuous
    sample: the same corpus has 97 pairs of sorter BODIES sharing a plan tile and
    35 belt-to-belt sorters, so a rule that banned either of those would light it
    up.  The box is what separates them.  ``test_sorter_collisions_are_absent_
    from_the_game_s_own_blueprints`` pins it.

    Multi-area fixtures are excluded from that statement, and must be: a
    building's local offset is relative to its own area, so putting two areas in
    one flat frame moves sorter ends by up to 73 units and the answer is noise.

    ONE TERM IS MODELLED OUT, stated rather than hidden.  When a sorter's
    machine end is seated and its OTHER end is a belt lying across the sorter
    (``|Dot(sorter axis, belt forward)| < 0.5``), ``RefreshBuildPreview``
    2100-2106 drags the belt end sideways by the seating delta.  We seat but do
    not drag.  Measured on the failing blueprint the difference is 0.263 against
    0.300 units of penetration on the same three pairs -- it changes no verdict
    there, and it cannot manufacture one, because the drag is bounded by the
    seating delta and our seating delta is at most a tile edge.
    """
    boxes = [sorter_box(p) for p in previews]
    cell = 8.0
    grid: dict[tuple[int, int, int], list[int]] = {}
    for i, box in enumerate(boxes):
        reach = max(box.half) + 0.01
        lo = tuple(int(math.floor((box.centre[k] - reach) / cell)) for k in range(3))
        hi = tuple(int(math.floor((box.centre[k] + reach) / cell)) for k in range(3))
        for cx in range(lo[0], hi[0] + 1):
            for cy in range(lo[1], hi[1] + 1):
                for cz in range(lo[2], hi[2] + 1):
                    grid.setdefault((cx, cy, cz), []).append(i)
    hits: set[tuple[int, int]] = set()
    for bucket in grid.values():
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                i, j = bucket[a], bucket[b]
                pair = (i, j) if i < j else (j, i)
                if pair in hits:
                    continue
                if obb_overlap(boxes[i], boxes[j]):
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


@lru_cache(maxsize=1)
def belt_keepout_offsets(
    model_index: int, yaw: float = 0.0, reach: int = 3, levels: int = 4
) -> frozenset[tuple[int, int, int]]:
    """Tile offsets at which a belt's probe touches this model's build collider.

    ``(dx, dy, dz)`` from the building's own tile and blueprint ``z``, MEASURED
    rather than asserted: the belt probe of :func:`belt_probe` is placed at every
    offset in the box and asked whether it overlaps any of
    :func:`target_boxes`.  That is the same question
    :func:`belt_collisions` asks, minus the excusals -- so this is the set of
    places an UNLINKED belt may not stand, and a caller that keeps foreign belts
    out of it cannot be convicted by that check.

    For a Splitter it comes out as the four orthogonal neighbours and the tile
    itself, at ``dz`` 0 AND 1 and nowhere else: the arms reach 1.19 world units
    against a 1.2566 tile, so a diagonal at 1.777 clears, and the collider stands
    2.30 units tall against a level's 4/3, so one level up is still inside it and
    two are not.  ``reach`` and ``levels`` are the search box, not the answer;
    they are wide enough that a non-empty ring at their edge would show.

    Negative ``dz`` is searched too -- a belt UNDER an elevated building -- and
    for every model in this catalog it comes back empty, because a collider
    starts at the ground and rises.
    """
    lpos, lrot = flat_pose(0.0, 0.0, 0.0, yaw)
    boxes = target_boxes(Placed(model_index, 0.0, 0.0, 0.0, yaw), lpos, lrot)
    if not boxes:
        return frozenset()
    out = set()
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            for dz in range(-levels, levels + 1):
                probe = belt_probe(dx, dy, dz)
                if any(sphere_box_overlap(probe, BELT_PROBE_RADIUS, b) for b in boxes):
                    out.add((dx, dy, dz))
    return frozenset(out)


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


@dataclass(frozen=True, slots=True)
class StableBeltCollision:
    """A collision that is not safe under every preview serialization.

    ``unstable_merges`` names the belt previews whose reconstructed reverse
    input can choose both a rescuing and a non-rescuing feeder.  It is empty for
    an ordinary collision that no feeder order can rescue.
    """

    belt: int
    collider: int
    unstable_merges: tuple[int, ...] = ()


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

    Ascending, so a merge leaves the last feeder in place, overwriting both an
    earlier feeder and a belt's recorded non-belt input.  This is the exact
    current-preview-order primitive: blueprint canonicalization may reorder
    previews without changing their forward links, so any feeder at a merge can
    become the last writer.  Production certification must therefore use
    :func:`stable_belt_collisions`, not treat this tuple as serialization-stable.
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


def _chain_near(
    previews: Sequence[Preview], links: Sequence[int | None], other: int
) -> frozenset[int]:
    """Preview indices accepted as the first two hops for ``other``."""
    near = {other}
    if previews[other].is_splitter:
        for candidate in (
            _resolve(previews, previews[other].output),
            links[other],
        ):
            if candidate is not None:
                near.add(candidate)
    return frozenset(near)


def _belt_chain_excuses_direction(
    previews: Sequence[Preview],
    links: Sequence[int | None],
    belt: int,
    other: int,
    *,
    downstream: bool,
) -> bool:
    near = _chain_near(previews, links, other)
    one, two, three = _hops(previews, links, belt, downstream=downstream)
    return one in near or two in near or three == other


def belt_chain_excuses(
    previews: Sequence[Preview], links: Sequence[int | None], belt: int, other: int
) -> bool:
    """``CheckBuildConditions`` 147443-147453, for one belt against one hit.

    ``other`` is a preview the belt's probe overlapped, and the answer is
    whether the belt's own run reaches it within three hops -- or, when it is a
    Splitter, reaches either of the previews that Splitter is linked to within
    two.  The third hop matches only the hit itself, never the Splitter's
    neighbours; that asymmetry is the game's and is reproduced.
    """
    return any(
        _belt_chain_excuses_direction(
            previews,
            links,
            belt,
            other,
            downstream=downstream,
        )
        for downstream in (True, False)
    )


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


def _belt_overlap_candidates(
    previews: Sequence[Preview],
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """Raw belt/collider probe hits after flag excusals, before graph rescue."""
    poses = [flat_pose(p.x, p.y, p.z, p.yaw) for p in previews]
    boxes = [target_boxes(p, *poses[i]) if not p.is_belt else [] for i, p in enumerate(previews)]
    cell = 8.0
    grid: dict[tuple[int, int], list[int]] = {}
    for j, bxs in enumerate(boxes):
        for box in bxs:
            # An OBB's horizontal circumradius is rotation-invariant. Index
            # exactly the grid cells its probe-expanded AABB can reach instead
            # of copying every collider into a fixed 3x3 neighbourhood.
            reach = math.hypot(box.half[0], box.half[2]) + BELT_PROBE_RADIUS
            min_x = math.floor((box.centre[0] - reach) / cell)
            max_x = math.floor((box.centre[0] + reach) / cell)
            min_y = math.floor((box.centre[2] - reach) / cell)
            max_y = math.floor((box.centre[2] + reach) / cell)
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    grid.setdefault((x, y), []).append(j)

    candidates: list[tuple[int, tuple[int, ...]]] = []
    for i, belt in enumerate(previews):
        if not belt.is_belt:
            continue
        probe = belt_probe(belt.x, belt.y, belt.z)
        key = (int(probe[0] // cell), int(probe[2] // cell))
        hits: list[int] = []
        for j in dict.fromkeys(grid.get(key, ())):
            if j == i:
                continue
            other = previews[j]
            if other.is_inserter or other.is_belt_addon:
                continue
            if any(sphere_box_overlap(probe, BELT_PROBE_RADIUS, box) for box in boxes[j]):
                hits.append(j)
        if hits:
            candidates.append((i, tuple(sorted(hits))))
    return tuple(candidates)


def belt_collisions(previews: Sequence[Preview]) -> list[tuple[int, int]]:
    """Exact current-order ``(belt, building)`` pairs DSP calls ``Collide``.

    This is the source-faithful verdict for one concrete preview sequence.  The
    paste first reconstructs reverse links with :func:`paste_input_links`, then
    re-probes each collided belt and applies the one/two/three-hop rescue from
    ``CheckBuildConditions`` 147443-147453.  A belt addon or sorter is excused
    before that walk, and a run directly ending in a good non-belt building is
    restored to ``Ok`` at 147492-147500.

    At a merge the reconstructed reverse input is last-preview-wins, so this
    result is intentionally order-sensitive.  Use :func:`stable_belt_collisions`
    to certify a placement that may be canonicalized before it reaches DSP.
    """
    links = paste_input_links(previews)
    hits: list[tuple[int, int]] = []
    for belt, candidates in _belt_overlap_candidates(previews):
        bad = [
            other for other in candidates if not belt_chain_excuses(previews, links, belt, other)
        ]
        if not bad or belt_run_ends_in_a_building(previews, links, belt):
            continue
        hits.extend((belt, other) for other in bad)
    return hits


def _reverse_input_choices(
    previews: Sequence[Preview],
) -> tuple[tuple[int | None, ...], ...]:
    """Every reverse input DSP's last-writer reconstruction can leave behind."""
    feeders: list[set[int]] = [set() for _ in previews]
    for i, preview in enumerate(previews):
        output = _resolve(previews, preview.output)
        if preview.is_belt and output is not None and previews[output].is_belt:
            feeders[output].add(i)
    return tuple(
        tuple(sorted(own)) if own else (_resolve(previews, preview.input),)
        for preview, own in zip(previews, feeders, strict=True)
    )


@dataclass(frozen=True, slots=True)
class _UniversalRescue:
    all_paths: bool
    any_path: bool
    unstable_merges: frozenset[int]


def _upstream_rescue_for_every_choice(
    previews: Sequence[Preview],
    choices: Sequence[tuple[int | None, ...]],
    links: Sequence[int | None],
    belt: int,
    other: int,
) -> _UniversalRescue:
    """Universally evaluate the game's bounded upstream walk without permutations."""
    near = _chain_near(previews, links, other)
    memo: dict[tuple[int, int], _UniversalRescue] = {}

    def walk(current: int, hop: int) -> _UniversalRescue:
        key = (current, hop)
        if key in memo:
            return memo[key]
        branches: list[_UniversalRescue] = []
        for predecessor in choices[current]:
            direct = predecessor is not None and (
                (hop < 3 and predecessor in near) or (hop == 3 and predecessor == other)
            )
            if direct:
                branch = _UniversalRescue(True, True, frozenset())
            elif predecessor is None or hop == 3 or not previews[predecessor].is_belt:
                branch = _UniversalRescue(False, False, frozenset())
            else:
                branch = walk(predecessor, hop + 1)
            branches.append(branch)

        all_paths = all(branch.all_paths for branch in branches)
        any_path = any(branch.any_path for branch in branches)
        unstable = frozenset().union(*(branch.unstable_merges for branch in branches))
        if len(choices[current]) > 1 and any_path and not all_paths:
            unstable |= frozenset((current,))
        result = _UniversalRescue(all_paths, any_path, unstable)
        memo[key] = result
        return result

    return walk(belt, 1)


def _belt_run_stably_ends_in_a_building(
    previews: Sequence[Preview],
    choices: Sequence[tuple[int | None, ...]],
    belt: int,
) -> bool:
    output = _resolve(previews, previews[belt].output)
    if output is not None and not previews[output].is_belt:
        return True
    return all(
        predecessor is not None and not previews[predecessor].is_belt
        for predecessor in choices[belt]
    )


def stable_belt_collisions(
    previews: Sequence[Preview],
) -> list[StableBeltCollision]:
    """Collisions that survive universal last-writer reverse-link reasoning.

    Forward links never change during preview serialization, so a downstream
    one/two/three-hop rescue is stable immediately.  Upstream, every feeder of a
    merge can become DSP's reconstructed ``input``.  The bounded dynamic program
    requires every such reverse path to satisfy the same rescue; it visits each
    ``(belt, hop)`` state once rather than enumerating feeder permutations.

    The direct-good-building override is likewise accepted only when its
    relevant link is stable.  Each returned value carries the collider and any
    merge at which rescuing and non-rescuing choices diverge.
    """
    choices = _reverse_input_choices(previews)
    recorded_links = tuple(_resolve(previews, preview.input) for preview in previews)
    hits: list[StableBeltCollision] = []
    for belt, candidates in _belt_overlap_candidates(previews):
        if _belt_run_stably_ends_in_a_building(previews, choices, belt):
            continue
        for other in candidates:
            if _belt_chain_excuses_direction(
                previews,
                recorded_links,
                belt,
                other,
                downstream=True,
            ):
                continue
            rescue = _upstream_rescue_for_every_choice(
                previews,
                choices,
                recorded_links,
                belt,
                other,
            )
            if not rescue.all_paths:
                hits.append(
                    StableBeltCollision(
                        belt,
                        other,
                        tuple(sorted(rescue.unstable_merges)),
                    )
                )
    return hits
