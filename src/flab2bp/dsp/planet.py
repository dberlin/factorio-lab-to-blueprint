"""The planet's longitude bands, and what a paste into one is allowed to be.

A DSP planet is not a plane.  Its build grid keeps a constant number of tiles
per unit of LATITUDE and drops the number of tiles per full circle of LONGITUDE
in steps as you go poleward, so that a tile never becomes a sliver.  The steps
are the "tropics" (``回归线``), and a blueprint that straddles one is refused
outright -- ``EBuildCondition.BlueprintAreaCrossTropic = 45``.

Why this module exists
----------------------
:mod:`flab2bp.dsp.colliders` evaluates its default model on a flat grid at
``GRID_ARC`` in both axes and says so plainly: within the equatorial band that
is the SUPREMUM of the real column spacing, because ``cos(lat) <= 1``.  That
makes every collision it finds real, and it makes every collision it MISSES
possible.  A blueprint that passes there can still be refused when pasted
anywhere but the equator, and a blueprint whose extent does not fit the
equatorial band cannot be pasted at the equator at all.

So "does this layout paste" is not a question about the layout alone.  It is a
question about the layout AND the band, and the band is decided by the layout's
extent.  This module is the band half: the game's own quantisation, the table of
bands it produces, the smallest band a given extent fits, the exact projection
of a blueprint's tile coordinates into that band, and the game's own paste
predicates evaluated on the projected result.

Exactness policy, stated because it differs between the two halves
------------------------------------------------------------------
* **The band index is reproduced in float32, bit for bit.**  It is a DISCRETE
  function of a ``float`` cosine put through a 512-entry lookup, so a one-ulp
  disagreement is not a small error, it is a different band.  Every arithmetic
  step in :func:`determine_longitude_segment_count` is narrowed to float32 with
  :func:`_f32`, and ``MathF.PI`` is the float32 pi the game uses, not
  :data:`math.pi`.
* **The world projection is computed in double.**  The game computes it in
  float32; the disagreement is continuous, relative, and bounded near 1e-6 world
  units over a blueprint-sized patch -- an order of magnitude below the 2e-5
  that ``layout.slots.seated_sorter`` is validated to against sorters the game
  really built.  This is a statement about precision, NOT a tolerance: no
  comparison in this module is softened by an epsilon, and every threshold is
  the game's literal.
* **Nothing here is a rate or a capacity in the metering sense**, so no
  :class:`~fractions.Fraction` appears.  The two quantities that ARE capacities
  -- how many grid rows and how many grid columns a band holds -- are integers,
  and are counted as integers rather than derived from a float.

Where the source is
-------------------
``/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/``, one file per type.
Line numbers below are that dump's, per file; ``PlanetGrid.cs`` and
``BlueprintUtils.cs`` were both checked and neither carries the "constant offset
of 143582" that circulated on this project.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from flab2bp.dsp import colliders, rules

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


def _f32(x: float) -> float:
    """``x`` narrowed to a C# ``float``.

    Every arithmetic step of a float expression in C# rounds to float32.  Python
    does not, so a faithful port has to narrow after each operation rather than
    once at the end -- the two differ by an ulp often enough to move a
    ``CeilToInt`` across an integer, which is a whole band.
    """
    return float(struct.unpack("<f", struct.pack("<f", x))[0])


#: ``MathF.PI`` -- the float32 pi.  ``math.pi`` is the double, and it is a
#: different number: 3.14159274101257324 against 3.14159265358979312.
MATHF_PI = _f32(math.pi)


# --- PlanetGrid.segmentTable -----------------------------------------------

#: ``PlanetGrid.segmentTable``, ``PlanetGrid.cs:19-80`` -- all 512 entries.
#:
#: NOT TRANSCRIBED AGAIN.  It is imported from :mod:`flab2bp.dsp.colliders`,
#: which carries the port, so there is exactly one copy of the table in this
#: repository and no way for two copies to drift.  A second transcription would
#: be a second thing to get wrong, and the values here are load-bearing in a way
#: they never were before: this module is the first code that indexes the table
#: AWAY from the equator, where 478 of its 492 fall-through entries differ from
#: their index.
#:
#: The table takes 17 distinct values, and those are the only longitude segment
#: counts a planet has:
#: ``{1, 4, 8, 16, 20, 32, 40, 60, 80, 100, 120, 160, 200, 240, 300, 400, 500}``.
#: It also appears verbatim in ``PlatformSystem.cs:59`` and
#: ``UIDysonPaintingGrid.cs:75``.
#:
#: The private name is deliberate on the far side, not an oversight on this one:
#: :mod:`flab2bp.dsp.colliders` owns the transcription today.  The handoff in
#: ``docs/BACKLOG.md`` moves it HERE and has ``colliders`` import it back, which
#: is the direction the dependency wants to run -- ``colliders`` needs one band,
#: this module needs all of them.
SEGMENT_TABLE: tuple[int, ...] = colliders._SEGMENT_TABLE


def determine_longitude_segment_count(latitude_index: int, segment: int) -> int:
    """``PlanetGrid.DetermineLongitudeSegmentCount``, ``PlanetGrid.cs:1838``::

        public static int DetermineLongitudeSegmentCount(int latitudeIndex, int segment)
        {
            int num = Mathf.CeilToInt(Mathf.Abs(Mathf.Cos((float)latitudeIndex
                / ((float)segment / 4f) * MathF.PI * 0.5f)) * (float)segment);
            if (num < 500)
            {
                return segmentTable[num];
            }
            return (num + 49) / 100 * 100;
        }

    ``latitudeIndex`` is a BAND index, not a grid row: five grid rows share one,
    and :func:`longitude_segment_count` is the conversion.  ``Mathf.Abs`` is
    applied to the COSINE rather than to the index, so a negative index gives the
    same answer as its positive twin and the grid is symmetric about the equator.

    Reproduced in float32 throughout -- see this module's exactness policy.
    ``Mathf.CeilToInt(f)`` is ``(int)Math.Ceiling((double)f)``, so the widening
    to double happens after the float32 multiply and before the ceiling.
    """
    scaled = _f32(_f32(latitude_index) / _f32(_f32(segment) / _f32(4.0)))
    angle = _f32(_f32(scaled * MATHF_PI) * _f32(0.5))
    cos = _f32(math.cos(angle))
    raw = math.ceil(_f32(_f32(abs(cos)) * _f32(segment)))
    if raw < 500:
        return SEGMENT_TABLE[raw]
    return (raw + 49) // 100 * 100


def longitude_segment_count(latitude_grid_idx: int, segment: int) -> int:
    """``BlueprintUtils.GetLongitudeSegmentCount(int)``, ``BlueprintUtils.cs:223``::

        if (_latitudeGridIdx < 0) _latitudeGridIdx = -_latitudeGridIdx;
        if (_latitudeGridIdx > 0) _latitudeGridIdx--;
        return PlanetGrid.DetermineLongitudeSegmentCount(_latitudeGridIdx / 5, _segmentCnt);

    THE DECREMENT IS THE WHOLE SHAPE OF THE EQUATORIAL BAND.  Without it the
    band containing row 0 would be a single ring of nine rows straddling the
    equator while every other band was five rows per hemisphere; with it, row
    ``5k+1`` through ``5k+5`` share band ``k`` in each hemisphere and row 0 joins
    band 0.  Dropping it, or applying it in the wrong place, mis-sizes the
    equatorial band -- which is the one every blueprint we emit lands in.

    ``PlanetGrid.CalcSegmentsAcross`` (``PlanetGrid.cs:1855``) spells the same
    mapping a different way, ``FloorToInt(Max(0f, Abs(gridIdx / 5f) - 0.1f))``,
    and the two agree on every integer grid index.  That agreement is checked by
    ``test_the_two_band_index_spellings_agree``.
    """
    idx = abs(latitude_grid_idx)
    if idx > 0:
        idx -= 1
    return determine_longitude_segment_count(idx // 5, segment)


def latitude_rad_per_grid(segment: int) -> float:
    """``BlueprintUtils.GetLatitudeRadPerGrid``, ``BlueprintUtils.cs:124``::

        return MathF.PI * 2f / (float)(_segmentCnt * 5);

    Constant over the whole planet -- rows never compress, only columns do.
    """
    return 2.0 * math.pi / (segment * 5)


def longitude_rad_per_grid(longitude_seg_cnt: int) -> float:
    """``BlueprintUtils.GetLongitudeRadPerGrid(int)``, ``BlueprintUtils.cs:275``::

        return MathF.PI * 2f / (float)(_longitudeSegCnt * 5);
    """
    return 2.0 * math.pi / (longitude_seg_cnt * 5)


def pole_grid_idx(segment: int) -> int:
    """The latitude grid index of a pole.

    ``BlueprintUtils.GetSnappedLatitudeGridIdx`` clamps to ``_segmentCnt * 5 / 4``
    at ``|y| > 0.9999999f`` (``BlueprintUtils.cs:166-173``), so that is the
    largest grid index a build can have.
    """
    return segment * 5 // 4


def area_count(lo_grid_idx: int, hi_grid_idx: int, segment: int) -> int:
    """``BlueprintUtils.GetAreaCount``, ``BlueprintUtils.cs:953``, on grid indices.

    The game's own version takes two latitudes, snaps each to a grid index, and
    then counts the runs::

        int num = 1;
        int num2 = GetLongitudeSegmentCount(snappedLatitudeGridIdx2, _segmentCnt);
        for (int i = snappedLatitudeGridIdx2; i < snappedLatitudeGridIdx; i++)
        {
            int longitudeSegmentCount = GetLongitudeSegmentCount(i + 1, _segmentCnt);
            if (num2 != longitudeSegmentCount) num++;
            num2 = longitudeSegmentCount;
        }
        return num;

    This is the predicate behind ``EBuildCondition.BlueprintAreaCrossTropic``:
    ``GenerateAreaGratBoxByBPData`` (``BlueprintUtils.cs:2500``) raises the
    condition when ``GetAreaCount(_latitude, w, _segmentCnt) > 1``, and
    ``RefreshBuildPreview`` (``BlueprintUtils.cs:2061``) hands it to every
    building in the area.  The snapping is skipped here because a blueprint's
    rows ARE grid indices; taking them as such is the same function without a
    float round trip.
    """
    lo, hi = min(lo_grid_idx, hi_grid_idx), max(lo_grid_idx, hi_grid_idx)
    count = 1
    previous = longitude_segment_count(lo, segment)
    for i in range(lo, hi):
        current = longitude_segment_count(i + 1, segment)
        if current != previous:
            count += 1
        previous = current
    return count


# --- the band table ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Band:
    """One longitude band of a planet -- what the game calls a tropic area.

    ``rows`` and ``columns`` are the band's CAPACITY in grid cells, counted as
    integers rather than derived from a float, and they are what an extent has to
    fit inside.
    """

    #: The band's longitude segment count.  This is the number a blueprint
    #: copied from this band records as ``BlueprintArea.areaSegments``
    #: (``BlueprintUtils.cs:1426``).
    area_segments: int
    #: Inclusive span of ``DetermineLongitudeSegmentCount``'s band index.
    latitude_index_lo: int
    latitude_index_hi: int
    #: Inclusive span of ``|latitude grid index|`` -- one hemisphere's rows.
    grid_lo: int
    grid_hi: int
    #: Longest run of CONSECUTIVE latitude grid indices sharing this band.  For
    #: every band but the equatorial one this is one hemisphere's worth, because
    #: the two hemispheres' copies of the band are separated by every band
    #: between them.  The equatorial band is the one that spans the equator, so
    #: its run is both hemispheres plus row zero.
    rows: int
    #: Longitude grid cells around the planet: ``area_segments * 5``.
    columns: int

    @property
    def is_equatorial(self) -> bool:
        return self.latitude_index_lo == 0

    def anchors(self, rows: int) -> tuple[int, ...]:
        """Every southmost grid row an extent of ``rows`` rows may occupy here.

        A blueprint occupies ``rows`` CONSECUTIVE grid indices, so its legal
        placements in this band are the windows of that length inside the band's
        own run: ``[-grid_hi, grid_hi]`` for the equatorial band, which spans
        both hemispheres, and ``[grid_lo, grid_hi]`` together with its southern
        mirror ``[-grid_hi, -grid_lo]`` for every other band.

        THE SOUTHERN MIRROR IS ENUMERATED RATHER THAN ARGUED AWAY.  It is
        tempting to drop it -- the grid is symmetric about the equator, by
        ``Mathf.Abs`` in :func:`determine_longitude_segment_count`, so a
        southern placement is a northern one reflected.  But reflecting the
        PLANET also reflects the BLUEPRINT, and a blueprint is not symmetric:
        the southern window is where the layout's top row sits at the poleward
        end instead of its bottom row.  That is a different configuration of the
        same building set, and the game's own paste reaches it through the
        latitude sign flip in ``RefreshBuildPreview``
        (``BlueprintUtils.cs:2034``, ``num3``).  Enumerating both is what makes
        the flip unnecessary to model separately.
        """
        if rows > self.rows:
            return ()
        if self.is_equatorial:
            return tuple(range(-self.grid_hi, self.grid_hi - rows + 2))
        north = range(self.grid_lo, self.grid_hi - rows + 2)
        south = range(-self.grid_hi, -self.grid_lo - rows + 2)
        return tuple(south) + tuple(north)


@lru_cache(maxsize=8)
def bands(segment: int = colliders.PLANET_SEGMENT) -> tuple[Band, ...]:
    """Every band of a planet with this segment count, equator first.

    ``segment = (int)(planet.radius / 4f + 0.1f) * 4`` -- the radius rounded to a
    multiple of four (cited in :mod:`flab2bp.dsp.colliders`).  200 is a
    terrestrial planet; the table is recomputed rather than tabulated so a gas
    giant or a moon gets its own without a second transcription.
    """
    pole = pole_grid_idx(segment)
    last_index = pole // 5
    out: list[Band] = []
    index_lo = 0
    previous = determine_longitude_segment_count(0, segment)
    for k in range(1, last_index + 2):
        current = determine_longitude_segment_count(k, segment) if k <= last_index else None
        if current == previous:
            continue
        grid_lo = 5 * index_lo + 1
        grid_hi = min(5 * (k - 1) + 5, pole)
        rows = (2 * grid_hi + 1) if index_lo == 0 else (grid_hi - grid_lo + 1)
        out.append(
            Band(
                area_segments=previous,
                latitude_index_lo=index_lo,
                latitude_index_hi=k - 1,
                grid_lo=grid_lo,
                grid_hi=grid_hi,
                rows=rows,
                columns=previous * 5,
            )
        )
        index_lo = k
        if current is None:
            break
        previous = current
    return tuple(out)


class BandRefusal(ValueError):
    """No band on this planet can hold the extent, in either orientation.

    A refusal, never a fallback.  A blueprint taller than the equatorial band is
    a blueprint that cannot be pasted anywhere on the planet, and quietly
    declaring it band 200 anyway would ship geometry the game refuses.
    """


@dataclass(frozen=True, slots=True)
class Fit:
    """The smallest band an extent fits, and the orientation that fits it."""

    band: Band
    #: ``True`` when the fit needs the blueprint turned a quarter turn -- the
    #: paste's own ``yaw`` 90/270 case, which swaps ``width`` and ``height``
    #: (``BlueprintUtils.RecalculateRotateStartAndEndRad``,
    #: ``BlueprintUtils.cs:2400``).
    rotated: bool
    #: Latitude grid rows the extent occupies in this orientation.
    rows: int
    #: Longitude grid columns it occupies.
    columns: int


def widest_band_for_extent(
    width: int, height: int, segment: int = colliders.PLANET_SEGMENT
) -> Fit:
    """The LARGEST band the extent fits -- the answer for a caller that has not
    checked legality.

    :func:`band_for_extent` gives the smallest band the extent fits, which is
    only a useful answer once something has verified the layout is legal there;
    on its own it is the most compressed geometry on the planet and, for a small
    blueprint, a band nothing at all can be built in.  A caller with no verdict
    to declare should declare the band it can honestly claim the area fits, which
    is the widest one, and that is what the encoder wrote as the literal 200 for
    every blueprint before any of this existed.

    Still refuses when nothing fits: an extent that crosses a tropic at every
    anchor on the planet has no honest band either.
    """
    best: Fit | None = None
    for band in bands(segment):
        for rotated, (cols, rows) in ((False, (width, height)), (True, (height, width))):
            if rows > band.rows or cols > band.columns:
                continue
            if best is None or band.area_segments > best.band.area_segments:
                best = Fit(band=band, rotated=rotated, rows=rows, columns=cols)
    if best is None:
        return band_for_extent(width, height, segment)  # raises, with the message
    return best


def band_for_extent(width: int, height: int, segment: int = colliders.PLANET_SEGMENT) -> Fit:
    """The SMALLEST band a ``width x height`` extent fits, either orientation.

    Smallest means fewest longitude segments -- the narrowest, most poleward
    band.  That is the useful end of the table and not the obvious one, so it is
    worth saying why: a tile's ARC in longitude shrinks toward the poles, so a
    layout that is legal in the narrowest band it can occupy is legal in every
    wider one, while the converse is false.  Choosing the widest band that fits
    would be choosing the most permissive geometry and would prove nothing.

    Both orientations are considered because the paste can rotate: at yaw 90 or
    270 the area's width and height swap
    (``BlueprintUtils.RecalculateRotateStartAndEndRad``), so an extent needs
    ``min(width, height)`` rows, not ``height`` rows.  Ties go to the unrotated
    orientation.

    Raises :class:`BandRefusal` when nothing fits.
    """
    if width <= 0 or height <= 0:
        raise BandRefusal(f"an extent of {width}x{height} is not a rectangle")
    best: Fit | None = None
    for band in bands(segment):
        for rotated, (cols, rows) in ((False, (width, height)), (True, (height, width))):
            if rows > band.rows or cols > band.columns:
                continue
            if best is None or band.area_segments < best.band.area_segments:
                best = Fit(band=band, rotated=rotated, rows=rows, columns=cols)
    if best is None:
        widest = max(bands(segment), key=lambda b: b.rows)
        raise BandRefusal(
            f"a {width}x{height} extent fits no band on a segment-{segment} planet: "
            f"it needs {min(width, height)} latitude rows in its better orientation "
            f"and the tallest band ({widest.area_segments} segments) holds "
            f"{widest.rows}. The game refuses this paste with "
            f"EBuildCondition.BlueprintAreaCrossTropic."
        )
    return best


# --- the projection ---------------------------------------------------------


def _norm(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return v if n == 0.0 else (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _qmul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by + ay * bw + az * bx - ax * bz,
        aw * bz + az * bw + ax * by - ay * bx,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _look_rotation(forward: Vec3, up: Vec3) -> Quat:
    """``Quaternion.LookRotation``, Unity's left-handed form.

    Cross-checked against :mod:`flab2bp.dsp.colliders`, which carries its own
    port of the same function -- ``test_the_projection_agrees_with_colliders_at_the_equator``
    fails if the two ever diverge.
    """
    f = _norm(forward)
    r = _norm(_cross(up, f))
    u = _cross(f, r)
    m00, m01, m02 = r
    m10, m11, m12 = u
    m20, m21, m22 = f
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return ((m12 - m21) / s, (m20 - m02) / s, (m01 - m10) / s, s * 0.25)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (s * 0.25, (m10 + m01) / s, (m20 + m02) / s, (m12 - m21) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m10 + m01) / s, s * 0.25, (m21 + m12) / s, (m20 - m02) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m20 + m02) / s, (m21 + m12) / s, s * 0.25, (m01 - m10) / s)


def spherical_rotation(direction: Vec3, yaw_deg: float) -> Quat:
    """``Maths.SphericalRotation`` -- upright at ``direction``, turned by ``yaw``."""
    p = _norm(direction)
    r = _cross(p, (0.0, 1.0, 0.0))
    if _dot3(r, r) < 1e-4:
        sign = 1.0 if p[1] >= 0.0 else -1.0
        forward = (0.0, 0.0, sign)
    else:
        forward = _norm(_cross(_norm(r), p))
    q = _look_rotation(forward, p)
    if yaw_deg == 0.0:
        return q
    half = math.radians(yaw_deg) * 0.5
    return _qmul(q, (0.0, math.sin(half), 0.0, math.cos(half)))


def quaternion_angle_deg(a: Quat, b: Quat) -> float:
    """``Quaternion.Angle(a, b)`` in degrees.

    ``2 * Acos(Min(Abs(Dot(a, b)), 1))``, which is what the game's ``TooSkew``
    pair test compares against 30.
    """
    d = min(abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]), 1.0)
    return math.degrees(2.0 * math.acos(d))


def _forward(q: Quat) -> Vec3:
    """``Quaternion.Forward()`` -- the rotation applied to ``(0, 0, 1)``."""
    x, y, z, w = q
    return (
        2.0 * (x * z + w * y),
        2.0 * (y * z - w * x),
        1.0 - 2.0 * (x * x + y * y),
    )


@dataclass(frozen=True, slots=True)
class Projection:
    """Blueprint tile coordinates to world positions, at one anchor in one band.

    This is ``BlueprintUtils.RefreshBuildPreview``'s own arithmetic
    (``BlueprintUtils.cs:2027-2049``)::

        float longitudeRadPerGrid4 = GetLongitudeRadPerGrid(num33, _segmentCnt);
        float longitudeRad = num32 + vector4.x * longitudeRadPerGrid4 * num2;
        float num34        = num33 + vector4.y * latitudeRadPerGrid * num3;
        num34 = ((Math.Abs(num34) > MathF.PI / 2f)
                 ? (MathF.PI / 2f * (float)Math.Sign(num34)) : num34);
        Vector3 dir = GetDir(longitudeRad, num34);
        buildPreview.lpos = dir * (blueprintBuilding.localOffset_z * 1.3333333f
                                   + 0.2f + _planet.realRadius);
        buildPreview.lrot = Maths.SphericalRotation(dir, blueprintBuilding.yaw - num * 90f);

    Two facts do all the work.  The LONGITUDE step is evaluated ONCE, at the
    anchor's latitude, so it is one constant for the whole paste; each building's
    own latitude then scales its world arc by ``cos``.  The LATITUDE step is
    constant everywhere.  So a paste is a flat grid in the row direction and a
    ``cos``-compressed one in the column direction, and the compression is what
    the flat model in :mod:`flab2bp.dsp.colliders` deliberately ignores.
    """

    band: Band
    #: Latitude grid index of the blueprint's row 0.
    anchor_row: int
    segment: int
    radius: float
    #: Which quarter turn the paste is at: ``Mathf.FloorToInt(_yaw / 89.9f)``,
    #: 0 through 3.  It decides three things at once, and all three are modelled
    #: because only one of them is an isometry.
    #:
    #: ``TransitionWidthAndHeight`` (``BlueprintUtils.cs:2441``) SWAPS the local
    #: offsets at quadrants 1 and 3, and ``RefreshBuildPreview`` multiplies them
    #: by the two steps and the two signs (``BlueprintUtils.cs:2031-2036``)::
    #:
    #:     Vector2 vector4 = TransitionWidthAndHeight(_yaw, localOffset_x, localOffset_y);
    #:     float longitudeRad = num32 + vector4.x * longitudeRadPerGrid4 * num2;
    #:     float num34        = num33 + vector4.y * latitudeRadPerGrid * num3;
    #:     ...
    #:     buildPreview.lrot = Maths.SphericalRotation(dir, blueprintBuilding.yaw - num * 90f);
    #:
    #: WHICH AXIS COMPRESSES IS THE WHOLE DIFFERENCE.  A blueprint that is wide
    #: and short fits a far smaller band turned sideways -- and turned sideways
    #: it is its WIDTH that gets squeezed, not its height.
    #:
    #: AND THE YAW TURNS WITH IT.  Leaving the ``- num * 90f`` out makes every
    #: sorter in a quarter-turned paste face 90 degrees off the line it runs
    #: along, which reads as ``TooSkew`` on the entire blueprint.  That was this
    #: model's own first answer, and it was this model's bug, not the game's.
    #:
    #: ONLY 0 AND 1 ARE MODELLED, and that is a completeness claim rather than a
    #: shortcut.  Quadrant 2 differs from quadrant 0 by flipping BOTH signs
    #: (``num2`` and ``num3``, both ``-1``) and turning every yaw by 180
    #: degrees -- which is exactly a half turn of the whole layout about the
    #: anchor's own up axis, an isometry of the sphere.  It maps the
    #: configuration to a congruent one, so no predicate here can tell them
    #: apart.  Quadrant 3 stands in the same relation to quadrant 1.
    #:
    #: Modelling the signs SEPARATELY, without moving the anchor, is wrong and
    #: was wrong here: with ``num3 = -1`` the extent grows southward from the
    #: anchor while :meth:`Band.anchors` hands out anchors that grow northward,
    #: so rows land outside the band entirely and get clamped at the pole. The
    #: game does not have that problem because
    #: ``RecalculateRotateStartAndEndRad`` (``BlueprintUtils.cs:2424-2435``)
    #: swaps start and end whenever a sign is negative, so its ``_startLat`` is
    #: always the southern edge.  Dropping the signs and keeping the anchor
    #: convention is the same statement with nothing left to get wrong.
    quadrant: int = 0

    @property
    def rotated(self) -> bool:
        """Whether this quadrant swaps the two axes."""
        return self.quadrant == 1

    @property
    def yaw_offset(self) -> float:
        """``-num * 90`` -- what the paste adds to every building's own yaw."""
        return -90.0 * self.quadrant

    @property
    def latitude_step(self) -> float:
        return latitude_rad_per_grid(self.segment)

    @property
    def longitude_step(self) -> float:
        """``GetLongitudeRadPerGrid(anchor latitude)`` -- fixed for the paste.

        Taken from the band rather than re-derived from the anchor's latitude:
        they are the same number by construction, because the anchor row is
        inside the band, and going through the band makes that a stated
        invariant instead of a coincidence.  ``test_the_projection_uses_the_bands_own_step``
        asserts the two agree for every row of every band.
        """
        return longitude_rad_per_grid(self.band.area_segments)

    def _transition(self, x: float, y: float) -> tuple[float, float]:
        """``TransitionWidthAndHeight`` and the two signs, as one step.

        Returns ``(longitude offset, latitude offset)``.  Only the SWAP is
        here; see :attr:`Projection.quadrant` for why the two sign flips are
        not, and why leaving them out loses nothing.
        """
        return (y, x) if self.rotated else (x, y)

    def latitude(self, x: float, y: float) -> float:
        _, dy = self._transition(x, y)
        lat = (self.anchor_row + dy) * self.latitude_step
        limit = math.pi / 2.0
        return math.copysign(limit, lat) if abs(lat) > limit else lat

    def direction(self, x: float, y: float) -> Vec3:
        """``GetDir(longitudeRad, latitudeRad)``, ``BlueprintUtils.cs:342``."""
        dx, _ = self._transition(x, y)
        lat = self.latitude(x, y)
        lng = dx * self.longitude_step
        cos_lat = math.cos(lat)
        return (cos_lat * math.sin(lng), math.sin(lat), cos_lat * -math.cos(lng))

    def position(self, x: float, y: float, z: float) -> Vec3:
        d = self.direction(x, y)
        scale = z * 4.0 / 3.0 + 0.2 + self.radius
        return (d[0] * scale, d[1] * scale, d[2] * scale)

    def pose(self, x: float, y: float, z: float, yaw: float) -> tuple[Vec3, Quat]:
        d = self.direction(x, y)
        scale = z * 4.0 / 3.0 + 0.2 + self.radius
        return (
            (d[0] * scale, d[1] * scale, d[2] * scale),
            spherical_rotation(d, yaw + self.yaw_offset),
        )

    def _shell(self, z: float) -> float:
        """The radius a building at level ``z`` actually sits on.

        ``localOffset_z * 1.3333333f + 0.2f + realRadius``
        (``BlueprintUtils.cs:2048``).  The ``0.2`` matters at the 1e-3 level and
        is included because leaving it out would make
        :data:`~flab2bp.dsp.colliders.GRID_ARC` look like the exact equatorial
        spacing when the real one is 0.1% larger -- a small thing to be wrong
        about, and free to be right about.
        """
        return z * 4.0 / 3.0 + 0.2 + self.radius

    def column_arc(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> float:
        """World units between adjacent COLUMNS at blueprint tile ``(x, y, z)``.

        ``shell * cos(latitude) * longitude_step``.  At the equator on a
        terrestrial planet this is :data:`~flab2bp.dsp.colliders.GRID_ARC` times
        ``(radius + 0.2) / radius``; everywhere else it is smaller or larger, and
        how much is the whole reason this module exists.
        """
        return self._shell(z) * math.cos(self.latitude(x, y)) * self.longitude_step

    def row_arc(self, z: float = 0.0) -> float:
        """World units between adjacent ROWS.  Constant over the planet."""
        return self._shell(z) * self.latitude_step


def projections_for(
    fit: Fit, segment: int = colliders.PLANET_SEGMENT, radius: float = colliders.PLANET_RADIUS
) -> tuple[Projection, ...]:
    """Every placement a blueprint of this fit has in its band.

    THE POINT OF ENUMERATING THEM IS TO AVOID A MARGIN.  "Works in the smallest
    band that fits" is a statement about EVERY placement in that band, not about
    a representative one, and a band holds few enough placements that the
    universally quantified question can simply be asked.  A conservative
    worst-case column arc would be an approximation of this; this is the thing
    itself.

    The anchors come from :meth:`Band.anchors`, which covers both hemispheres.
    One quadrant per orientation: 0 upright, 1 turned.  Quadrants 2 and 3 are
    half turns of those two and so congruent to them -- see
    :attr:`Projection.quadrant`.
    """
    quadrants = (1,) if fit.rotated else (0,)
    return tuple(
        Projection(band=fit.band, anchor_row=a, segment=segment, radius=radius, quadrant=q)
        for q in quadrants
        for a in fit.band.anchors(fit.rows)
    )


# --- PlanetGrid.CalcSegmentsAcross ------------------------------------------


def calc_segments_across(pos_r: Vec3, pos_a: Vec3, pos_b: Vec3, segment: int) -> float:
    """``PlanetGrid.CalcSegmentsAcross``, ``PlanetGrid.cs:1848``::

        posR.Normalize(); posA.Normalize(); posB.Normalize();
        float num  = Mathf.Asin(posR.y);
        float f    = num / (MathF.PI * 2f) * (float)segment;
        float num2 = DetermineLongitudeSegmentCount(
            Mathf.FloorToInt(Mathf.Max(0f, Mathf.Abs(f) - 0.1f)), segment);
        float num3 = Mathf.Max(0.0048f, Mathf.Cos(num) * MathF.PI * 2f / (num2 * 5f));
        float num4 = MathF.PI * 2f / ((float)segment * 5f);
        ... blend by how much of the separation is longitude and how much latitude
        return (posA - posB).magnitude / num14;

    How many GRID CELLS a sorter reaches across, blended between the column
    pitch at the reference point's latitude and the constant row pitch.  All
    three positions are normalised first, so altitude is discarded -- the paste
    handles that separately, as ``num130``.

    This is the term ``flab2bp.dsp.rules`` records as deliberately unported:
    *"Two of the game's tests are NOT ported, both because they need the
    planet's grid rather than ours."*  They need this module, and they are
    ported below.

    ``pos_r`` is the reference: ``BuildTool_BlueprintPaste.cs:3438`` picks the
    NON-belt end's peer, or the midpoint when both ends are alike.  Only its
    direction is used.
    """
    a, b = _norm(pos_a), _norm(pos_b)
    r = _norm(pos_r)
    lat_r = math.asin(max(-1.0, min(1.0, r[1])))
    f = lat_r / (2.0 * math.pi) * segment
    band_index = math.floor(max(0.0, abs(f) - 0.1))
    lon_count = determine_longitude_segment_count(band_index, segment)
    col = max(0.0048, math.cos(lat_r) * 2.0 * math.pi / (lon_count * 5.0))
    row = 2.0 * math.pi / (segment * 5.0)
    lat_a = math.asin(max(-1.0, min(1.0, a[1])))
    lng_a = math.atan2(a[0], -a[2])
    lat_b = math.asin(max(-1.0, min(1.0, b[1])))
    lng_b = math.atan2(b[0], -b[2])
    d_lng = abs(_delta_angle(lng_a, lng_b))
    d_lat = abs(lat_a - lat_b)
    total = d_lat + d_lng
    # ``num12``/``num13`` default to 0 and 1 when the two points coincide, which
    # makes the blended pitch the row pitch -- the same branch, spelled the way
    # the game spells it.
    pitch = col * (d_lng / total) + row * (d_lat / total) if total > 0.0 else row
    return math.dist(a, b) / pitch


def _delta_angle(a: float, b: float) -> float:
    """``Mathf.DeltaAngle`` in radians -- the shortest way round the circle."""
    d = (b - a) % (2.0 * math.pi)
    if d > math.pi:
        d -= 2.0 * math.pi
    return d


# --- the paste's sorter ladder ----------------------------------------------

#: ``num133`` -- the most GRID CELLS a pasted sorter may reach across, keyed by
#: how many of its two ends land on a belt (``flag21``/``flag22``).
#: ``BuildTool_BlueprintPaste.cs:3445-3458``, and the interactive tool sets the
#: same four numbers together at ``BuildTool_Inserter.cs:1313-1329``.
#:
#: THIS IS THE THRESHOLD ``flab2bp.dsp.rules`` DECLINED TO PORT, and the reason
#: it gave is the reason this module exists.  Its comment reads: *"`num7` and
#: `num8` are not ported AS THRESHOLDS because `CalcSegmentsAcross` is a function
#: of latitude and our grid is uniform ... On a uniform grid `num7` reduces
#: exactly to `SORTER_MAX_REACH`."*  Both halves of that stop being true here:
#:
#: * the grid is NOT uniform once a blueprint is projected into a band -- that
#:   is the definition of a band -- so the reduction has no force; and
#: * even on a uniform grid the reduction is to an INTEGER span, and a seated
#:   sorter's ends are not on tile centres.  ``layout.slots.seated_sorter`` moves
#:   a machine end by up to 0.6 of a tile, so ``num128`` is a real number that
#:   an integer span check cannot bound in either direction.
#:
#: It is also tighter than :data:`~flab2bp.dsp.rules.SORTER_LENGTH`, which bounds
#: the same sorter's world-unit length: at the equator a cell is ``GRID_ARC`` =
#: 1.2566 world units, so the mixed case allows 5.5 world units -- 4.376 cells --
#: against 3.499 here.  The two are not redundant and never were.
SORTER_SEGMENTS_MAX = {2: 3.2, 1: 3.499, 0: 3.799}

#: ``num134`` -- floor on ``sqrt(segmentsAcross^2 + altitudeSteps^2)``, same
#: passage (``BuildTool_BlueprintPaste.cs:3446-3459``,
#: ``BuildTool_Inserter.cs:1347``), same key.  ``altitudeSteps`` is ``num130``,
#: the radial separation of the two ends divided by 0.2.
SORTER_COMBINED_MIN = {2: 0.8, 1: 0.88, 0: 1.451}

#: ``num129 -= 0.3f`` -- the machine-to-machine case biases the value that
#: becomes the sorter's length parameter before it is clamped to 1..3
#: (``BuildTool_BlueprintPaste.cs:3460`` and ``:3486``).  It does not affect any
#: legality test; it is here because the parameter is emitted.
SORTER_PARAM_BIAS = {2: 0.0, 1: 0.0, 0: -0.3}

#: ``0.2f`` -- ``num130 = Abs(lpos.magnitude - lpos2.magnitude) / 0.2f``.  The
#: game's own unit for a radial step, not a tile and not a level.
SORTER_ALTITUDE_UNIT = 0.2


@dataclass(frozen=True, slots=True)
class Sorter:
    """One seated sorter, in blueprint tile coordinates, ready to project.

    ``(x, y, z)`` and ``(x2, y2, z2)`` are ``lpos``/``lpos2`` AFTER seating --
    build them with :func:`flab2bp.layout.slots.seated_sorter`, which is the
    validated port of the paste's own re-seating and is 2e-5 accurate against
    sorters the game really built.  Passing the tile centres a strategy chose
    instead asks about a sorter the game will not create.

    ``input_belt`` and ``output_belt`` are ``flag21`` and ``flag22``
    (``BuildTool_BlueprintPaste.cs:3433-3434``): true when that end's peer is a
    belt.  NOTE this is not the same predicate as ``SorterPreview.input_open``,
    which is also true for an end that meets NOTHING -- the collider grows on an
    unattached end, but the length thresholds treat unattached as machine-like.

    ``ref_*`` is ``zero`` (``BuildTool_BlueprintPaste.cs:3438``): the peer
    position ``CalcSegmentsAcross`` measures the local grid at.  Belt on the
    input only takes the output peer, belt on the output only takes the input
    peer, otherwise the midpoint of the two.
    """

    x: float
    y: float
    z: float
    x2: float
    y2: float
    z2: float
    yaw: float
    yaw2: float
    input_belt: bool
    output_belt: bool
    ref_x: float
    ref_y: float
    ref_z: float

    @property
    def belt_ends(self) -> int:
        return int(self.input_belt) + int(self.output_belt)


def sorter_condition(sorter: Sorter, projection: Projection) -> str | None:
    """The ``EBuildCondition`` this sorter would raise, or ``None`` if it pastes.

    The whole ladder from ``BuildTool_BlueprintPaste.CheckBuildConditions``
    (``BuildTool_BlueprintPaste.cs:3433-3504``), in the game's own order, on
    positions projected into ``projection``'s band::

        float num128 = mainGrid.CalcSegmentsAcross(zero, lpos, lpos2);
        float num130 = Mathf.Abs(lpos.magnitude - lpos2.magnitude) / 0.2f;
        float magnitude = forward2.magnitude;                 // |lpos2 - lpos|
        ... thresholds by flag21/flag22 ...
        if (magnitude > num131)                       -> TooFar
        if (magnitude < num132)                       -> TooClose
        if (num128 > num133)                          -> TooFar
        if (Sqrt(num128*num128 + num130*num130) < num134) -> TooClose
        if (Quaternion.Angle(lrot, lrot2) > 30f)      -> TooSkew
        num135 = Acos(Abs(Dot(axis, lrot .Forward()))) in degrees
        num136 = Acos(Abs(Dot(axis, lrot2.Forward()))) in degrees
        if (num135 > 24f || num136 > 24f)             -> TooSkew

    Returned as the condition's name so a caller can report WHICH rule refused,
    which is the difference between "the packer must make this shorter" and "the
    packer must make this straighter".

    The last four tests already have flat-model twins in ``layout.validate``
    (``game.inserter_paste``, ``game.inserter_skew``).  They are here as well
    because they are not band-invariant: the axis a skew angle is measured
    against runs between two ends whose column separation compresses with
    latitude while their row separation does not, so a sorter's skew CHANGES
    with the band.  ``MayBeBuried`` is not ported -- it is a terrain test.
    """
    belts = sorter.belt_ends
    min_len, max_len = rules.SORTER_LENGTH[belts]
    lpos = projection.position(sorter.x, sorter.y, sorter.z)
    lpos2 = projection.position(sorter.x2, sorter.y2, sorter.z2)
    reference = projection.position(sorter.ref_x, sorter.ref_y, sorter.ref_z)

    magnitude = math.dist(lpos, lpos2)
    if magnitude > max_len:
        return "TooFar"
    if magnitude < min_len:
        return "TooClose"

    across = calc_segments_across(reference, lpos, lpos2, projection.segment)
    if across > SORTER_SEGMENTS_MAX[belts]:
        return "TooFar"
    altitude = abs(_magnitude(lpos) - _magnitude(lpos2)) / SORTER_ALTITUDE_UNIT
    if math.hypot(across, altitude) < SORTER_COMBINED_MIN[belts]:
        return "TooClose"

    offset = projection.yaw_offset
    lrot = spherical_rotation(projection.direction(sorter.x, sorter.y), sorter.yaw + offset)
    lrot2 = spherical_rotation(projection.direction(sorter.x2, sorter.y2), sorter.yaw2 + offset)
    if quaternion_angle_deg(lrot, lrot2) > rules.SKEW_PAIR_DEG:
        return "TooSkew"
    axis = _norm((lpos2[0] - lpos[0], lpos2[1] - lpos[1], lpos2[2] - lpos[2]))
    for rot in (lrot, lrot2):
        cos = min(abs(_dot3(axis, _forward(rot))), 1.0)
        if math.degrees(math.acos(cos)) > rules.SKEW_AXIS_DEG:
            return "TooSkew"
    return None


def _magnitude(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


# --- collisions at a band ---------------------------------------------------


def collider_radius(model_index: int) -> float:
    """A sphere, centred on the building's own origin, containing every collider.

    Used only to rule pairs OUT before the exact test -- see
    :func:`candidate_pairs`.  Over-estimating it costs time; under-estimating it
    would lose a collision, so it is the sum of the offset's magnitude and the
    half-extent's, which is the corner-to-corner bound and cannot be too small.
    """
    worst = 0.0
    for pos, ext, _q in colliders.build_colliders(model_index):
        worst = max(worst, _magnitude(pos) + _magnitude(ext))
    return worst


def candidate_pairs(
    buildings: Sequence[colliders.Placed], band: Band, segment: int, radius: float
) -> list[tuple[int, int]]:
    """Pairs that could possibly collide SOMEWHERE in this band.

    A filter, never a verdict.  The exact overlap test is
    :func:`colliders.obb_overlap` and it still runs on everything this returns;
    all this does is stop the anchor loop rebuilding boxes for the overwhelming
    majority of pairs that are tens of tiles apart and could not touch at any
    latitude.

    The bound is a LOWER bound on the world separation, so it can only ever
    over-include.  Rows are a fixed arc apart everywhere; columns are narrowest
    at the band's poleward edge; and the chord between two points is shorter than
    the arc, which is why the arc is scaled down before it is used.  The scale is
    not a tolerance on the verdict -- make it 0.5 and the answers do not change,
    only the running time.
    """
    if not buildings:
        return []
    step = longitude_rad_per_grid(band.area_segments)
    lat_step = latitude_rad_per_grid(segment)
    poleward = min(
        math.cos(min(abs(g), pole_grid_idx(segment)) * lat_step)
        for g in (band.grid_lo, band.grid_hi)
    )
    # 0.9 absorbs chord-against-arc, which is under 4% for the three-columns
    # case even in the 4-segment band and far less anywhere a collision lives.
    col = radius * poleward * step * 0.9
    row = radius * lat_step * 0.9
    radii = [collider_radius(b.model_index) for b in buildings]
    reach = max(radii, default=0.0) * 2.0
    # Bucket by column so the scan is linear in the number of NEAR pairs rather
    # than quadratic in the number of buildings.
    span = max(1.0, reach / max(col, 1e-9))
    grid: dict[int, list[int]] = {}
    for i, b in enumerate(buildings):
        grid.setdefault(int(math.floor(b.x / span)), []).append(i)
    out: set[tuple[int, int]] = set()
    for key, members in grid.items():
        others = members + [j for k in (key + 1,) for j in grid.get(k, ())]
        for a_pos, i in enumerate(members):
            for j in others[a_pos + 1 :]:
                if i == j:
                    continue
                bi, bj = buildings[i], buildings[j]
                gap = math.sqrt(
                    ((bi.x - bj.x) * col) ** 2
                    + ((bi.y - bj.y) * row) ** 2
                    + ((bi.z - bj.z) * 4.0 / 3.0) ** 2
                )
                if gap <= radii[i] + radii[j]:
                    out.add((i, j) if i < j else (j, i))
    return sorted(out)


def collisions_at(
    buildings: Sequence[colliders.Placed],
    projection: Projection,
    pairs: Sequence[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """``EBuildCondition.Collide`` pairs among machines projected into a band.

    :func:`flab2bp.dsp.colliders.collisions` answers this on a FLAT grid, which
    its docstring identifies as the supremum of real spacing inside the
    equatorial band.  Away from the equator columns are narrower, so the flat
    answer is a lower bound on what a real paste hits.  This asks the same
    question with the real spacing.

    ``colliders.collisions`` already accepts an ``anchor_lat``, and this does not
    use it: that path routes through ``colliders._longitude_segment_count``,
    whose ``segmentTable`` is truncated to its first eight entries and whose band
    index omits the decrement in ``GetLongitudeSegmentCount``.  It is right at
    the equator and wrong in every other band -- 176 instead of 160 at the top of
    band 160, for one.  Replacing it with :func:`longitude_segment_count` is the
    handoff recorded in ``docs/BACKLOG.md``; until then this module does not
    consult it.

    The query box and the target box are both built with
    :func:`~flab2bp.dsp.colliders.target_boxes`.  The two sides differ only in
    whether the collider's OWN quaternion is composed onto the preview rotation,
    and every collider in the shipped data has an identity quaternion --
    ``colliders``' own docstring says so, and
    ``test_every_shipped_collider_quaternion_is_identity`` keeps it true, so this
    shortcut has a guard rather than an assumption.

    ``pairs`` restricts the exact test to a candidate set from
    :func:`candidate_pairs`.  It changes the running time, not the answer:
    anything it leaves out is a pair no projection in the band can bring within
    the sum of its two collider radii.  Passing ``None`` tests everything, at the
    cost of projecting every building whether or not it has a neighbour.
    """
    if pairs is None:
        pairs = [(i, j) for i in range(len(buildings)) for j in range(i + 1, len(buildings))]
    if not pairs:
        return []
    wanted = {i for pair in pairs for i in pair}
    boxes = {
        i: colliders.target_boxes(
            buildings[i], *projection.pose(*_placed_at(buildings[i]))
        )
        for i in wanted
    }
    hits = [
        pair
        for pair in pairs
        if any(colliders.obb_overlap(q, t) for q in boxes[pair[0]] for t in boxes[pair[1]])
    ]
    return sorted(hits)


def _placed_at(b: colliders.Placed) -> tuple[float, float, float, float]:
    return (b.x, b.y, b.z, b.yaw)
