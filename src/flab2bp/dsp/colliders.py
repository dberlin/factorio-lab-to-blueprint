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
from dataclasses import dataclass
from functools import cache
from pathlib import Path

__all__ = [
    "GRID_ARC",
    "Box",
    "build_colliders",
    "collisions",
    "obb_overlap",
    "preview_pose",
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


def _target_boxes(p: Placed, lpos: Vec3, lrot: Quat) -> list[Box]:
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
    targets = [_target_boxes(b, *poses[i]) for i, b in enumerate(buildings)]

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
