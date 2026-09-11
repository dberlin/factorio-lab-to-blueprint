# cython: language_level=3, wraparound=False, initializedcheck=False, cdivision=True
"""The oriented-box separating-axis test, compiled.

A port of ``colliders._obb_overlap_python`` and its helpers ``_qrot``,
``_axes``, ``_dot`` and ``_box_radius``, operation for operation.  The Python
body is the reference; this is only allowed to be faster, never different, and
``tests/dsp/test_colliders.py`` proves the two agree on a random sample and on
the touching cases a random sample never lands on.

Keeping them equal is a matter of not rearranging the arithmetic:

* every sum is accumulated in the Python's association order, so
  ``ea[0] * r[0][j] + ea[1] * r[1][j] + ea[2] * r[2][j]`` rounds where the
  Python rounds and not somewhere else;
* ``x ** 2`` becomes ``x * x`` -- for a finite double those are the same
  number, because a correctly rounded ``pow(x, 2.0)`` is the correctly rounded
  product;
* the ``1e-9`` added to each ``abs_rot`` term stays exactly where it is, since
  it is what makes a parallel pair (which every axis-aligned pair here is) fall
  through the cross-product axes instead of separating on rounding noise;
* the three separating-axis loops keep their order and their early returns, so
  the first axis to separate is the same one;
* ``setup.py`` compiles this with ``-ffp-contract=off``, which forbids the
  compiler from fusing ``a * b + c`` into an FMA.  An FMA is *more* accurate --
  it keeps the product unrounded -- and that is precisely the problem: it would
  disagree with Python at the boundary, which is the only place the verdict is
  in doubt.

``_axes`` and ``_box_radius`` are ``@cache``d on the Python side, so hoisting
them into the per-box unpack below is the same computation, not a new one; it
just lets ``any_box_overlap`` pay for them once per box instead of once per
pair.
"""

from libc.math cimport copysign, cos, fabs, sin, sqrt
from libc.stdlib cimport free, malloc


cdef struct CBox:
    double centre[3]
    double half[3]
    double radius
    double axes[3][3]


cdef inline void _qrot(
    double x, double y, double z, double w,
    double vx, double vy, double vz,
    double* out,
) noexcept nogil:
    """``colliders._qrot``: rotate ``v`` by the quaternion ``(x, y, z, w)``."""
    cdef double tx = 2.0 * (y * vz - z * vy)
    cdef double ty = 2.0 * (z * vx - x * vz)
    cdef double tz = 2.0 * (x * vy - y * vx)
    out[0] = vx + w * tx + (y * tz - z * ty)
    out[1] = vy + w * ty + (z * tx - x * tz)
    out[2] = vz + w * tz + (x * ty - y * tx)


cdef CBox _unpack(box) except *:
    """Read one ``colliders.Box`` into C doubles, with its axes and radius."""
    cdef CBox out
    centre = box.centre
    half = box.half
    rot = box.rot
    out.centre[0] = centre[0]
    out.centre[1] = centre[1]
    out.centre[2] = centre[2]
    out.half[0] = half[0]
    out.half[1] = half[1]
    out.half[2] = half[2]
    cdef double x = rot[0]
    cdef double y = rot[1]
    cdef double z = rot[2]
    cdef double w = rot[3]
    # ``_box_radius``.
    out.radius = sqrt(
        out.half[0] * out.half[0] + out.half[1] * out.half[1] + out.half[2] * out.half[2]
    )
    # ``_axes``.
    _qrot(x, y, z, w, 1.0, 0.0, 0.0, out.axes[0])
    _qrot(x, y, z, w, 0.0, 1.0, 0.0, out.axes[1])
    _qrot(x, y, z, w, 0.0, 0.0, 1.0, out.axes[2])
    return out


cdef bint _overlap(CBox* a, CBox* b) noexcept nogil:
    """``colliders._obb_overlap_python``, line for line."""
    cdef double delta[3]
    delta[0] = b.centre[0] - a.centre[0]
    delta[1] = b.centre[1] - a.centre[1]
    delta[2] = b.centre[2] - a.centre[2]
    cdef double radius = a.radius + b.radius
    if delta[0] * delta[0] + delta[1] * delta[1] + delta[2] * delta[2] > radius * radius:
        return False

    cdef double rot[3][3]
    cdef double abs_rot[3][3]
    cdef Py_ssize_t i, j, i1, i2, j1, j2
    for i in range(3):
        for j in range(3):
            # ``_dot(ax[i], bx[j])``.
            rot[i][j] = (
                a.axes[i][0] * b.axes[j][0]
                + a.axes[i][1] * b.axes[j][1]
                + a.axes[i][2] * b.axes[j][2]
            )
            # The epsilon guards the cross-product axes when two boxes are
            # parallel, which every axis-aligned pair here is.
            abs_rot[i][j] = fabs(rot[i][j]) + 1e-9

    cdef double t[3]
    for i in range(3):
        # ``_dot(delta, ax[i])``.
        t[i] = delta[0] * a.axes[i][0] + delta[1] * a.axes[i][1] + delta[2] * a.axes[i][2]

    cdef double ra, rb, span
    for i in range(3):
        ra = a.half[i]
        rb = (
            b.half[0] * abs_rot[i][0]
            + b.half[1] * abs_rot[i][1]
            + b.half[2] * abs_rot[i][2]
        )
        if fabs(t[i]) > ra + rb:
            return False

    for j in range(3):
        ra = (
            a.half[0] * abs_rot[0][j]
            + a.half[1] * abs_rot[1][j]
            + a.half[2] * abs_rot[2][j]
        )
        rb = b.half[j]
        if fabs(t[0] * rot[0][j] + t[1] * rot[1][j] + t[2] * rot[2][j]) > ra + rb:
            return False

    for i in range(3):
        for j in range(3):
            i1 = (i + 1) % 3
            i2 = (i + 2) % 3
            j1 = (j + 1) % 3
            j2 = (j + 2) % 3
            ra = a.half[i1] * abs_rot[i2][j] + a.half[i2] * abs_rot[i1][j]
            rb = b.half[j1] * abs_rot[i][j2] + b.half[j2] * abs_rot[i][j1]
            span = fabs(t[i2] * rot[i1][j] - t[i1] * rot[i2][j])
            if span > ra + rb:
                return False
    return True


def obb_overlap(a, b) -> bool:
    """Separating-axis test on two ``colliders.Box`` values."""
    cdef CBox ca = _unpack(a)
    cdef CBox cb = _unpack(b)
    return _overlap(&ca, &cb)


def any_box_overlap(queries, targets) -> bool:
    """``any(obb_overlap(q, t) for q in queries for t in targets)``.

    The targets are unpacked once and reused across every query, which is where
    the win over the Python nested loop comes from: one building's collider set
    is tested against another's, and the projection hands the same boxes to
    every pair it shares.
    """
    cdef Py_ssize_t count = len(targets)
    if count == 0:
        return False
    cdef CBox* unpacked = <CBox*>malloc(<size_t>count * sizeof(CBox))
    if unpacked == NULL:
        raise MemoryError
    cdef CBox query
    cdef Py_ssize_t i
    try:
        for i in range(count):
            unpacked[i] = _unpack(targets[i])
        for box in queries:
            query = _unpack(box)
            for i in range(count):
                if _overlap(&query, &unpacked[i]):
                    return True
    finally:
        free(unpacked)
    return False


cdef struct CSphereBox:
    double centre[3]
    double half[3]
    double rot[4]


cdef CSphereBox _unpack_sphere(box) except *:
    cdef CSphereBox out
    centre = box.centre
    half = box.half
    rot = box.rot
    cdef Py_ssize_t axis
    for axis in range(3):
        out.centre[axis] = centre[axis]
        out.half[axis] = half[axis]
    for axis in range(4):
        out.rot[axis] = rot[axis]
    return out


cdef bint _prepared_sphere_overlap(
    double cx, double cy, double cz, double radius, CSphereBox* box,
) noexcept nogil:
    """Exact ``colliders._sphere_box_overlap_python`` arithmetic, without tuples."""
    cdef double dx = cx - box.centre[0]
    cdef double dy = cy - box.centre[1]
    cdef double dz = cz - box.centre[2]
    cdef double local[3]
    _qrot(-box.rot[0], -box.rot[1], -box.rot[2], box.rot[3], dx, dy, dz, local)
    cdef double squared_distance = 0.0
    cdef double extent, excess
    cdef Py_ssize_t axis
    for axis in range(3):
        extent = box.half[axis]
        excess = fabs(local[axis]) - extent
        if excess > 0.0:
            squared_distance += excess * excess
    return squared_distance < radius * radius


cdef bint _sphere_overlap(double cx, double cy, double cz, double radius, box) except *:
    cdef CSphereBox prepared = _unpack_sphere(box)
    return _prepared_sphere_overlap(cx, cy, cz, radius, &prepared)


def sphere_box_overlap(centre, double radius, box) -> bool:
    """Exact strict sphere/box overlap."""
    return _sphere_overlap(centre[0], centre[1], centre[2], radius, box)


def sphere_box_candidates(centre, double radius, targets, candidates) -> list:
    """Preserve candidate order, emitting each hit target once across its boxes."""
    cdef double cx = centre[0]
    cdef double cy = centre[1]
    cdef double cz = centre[2]
    cdef Py_ssize_t index
    hits = []
    for index in candidates:
        for box in targets[index]:
            if _sphere_overlap(cx, cy, cz, radius, box):
                hits.append(index)
                break
    return hits


cdef class ProjectedBeltProbe:
    """One immutable frame; exact Projection direction and lifted probe arithmetic."""
    cdef double anchor, latitude_step, longitude_step, radius, lift
    cdef bint rotated

    def __cinit__(
        self, double anchor, double latitude_step, double longitude_step,
        double radius, double lift, bint rotated,
    ):
        self.anchor = anchor
        self.latitude_step = latitude_step
        self.longitude_step = longitude_step
        self.radius = radius
        self.lift = lift
        self.rotated = rotated

    cdef void _probe(self, double x, double y, double z, double* out) noexcept nogil:
        cdef double latitude = (self.anchor + (x if self.rotated else y)) * self.latitude_step
        cdef double longitude = (y if self.rotated else x) * self.longitude_step
        cdef double limit = 1.5707963267948966
        if fabs(latitude) > limit:
            latitude = copysign(limit, latitude)
        cdef double cos_latitude = cos(latitude)
        cdef double dx = cos_latitude * sin(longitude)
        cdef double dy = sin(latitude)
        cdef double dz = cos_latitude * -cos(longitude)
        cdef double shell = z * 4.0 / 3.0 + 0.2 + self.radius
        out[0] = dx * shell + dx * self.lift
        out[1] = dy * shell + dy * self.lift
        out[2] = dz * shell + dz * self.lift

    def __call__(self, double x, double y, double z):
        cdef double out[3]
        self._probe(x, y, z, out)
        return (out[0], out[1], out[2])


cdef class ProjectedBeltScan:
    """Frame-owned packed targets; broadphase bounds still come from _belt_cells."""
    cdef ProjectedBeltProbe probe
    cdef double radius
    cdef CSphereBox* boxes
    cdef Py_ssize_t* offsets
    cdef tuple target_indices
    cdef dict grid

    def __cinit__(self, ProjectedBeltProbe probe, double radius, targets, cells, target_indices):
        cdef Py_ssize_t target_count = len(targets)
        cdef Py_ssize_t box_count = 0
        cdef Py_ssize_t index, offset = 0
        if len(cells) != target_count or len(target_indices) != target_count:
            raise ValueError("targets, cells and target_indices must have equal lengths")
        self.probe = probe
        self.radius = radius
        self.target_indices = tuple(target_indices)
        self.grid = {}
        for target in targets:
            box_count += len(target)
        if box_count:
            self.boxes = <CSphereBox*>malloc(<size_t>box_count * sizeof(CSphereBox))
            if self.boxes == NULL:
                raise MemoryError
        self.offsets = <Py_ssize_t*>malloc((<size_t>target_count + 1) * sizeof(Py_ssize_t))
        if self.offsets == NULL:
            raise MemoryError
        for index in range(target_count):
            self.offsets[index] = offset
            for box in targets[index]:
                self.boxes[offset] = _unpack_sphere(box)
                offset += 1
            # Same first-registration dedup as BeltOverlap.of, on compact
            # target indices. No geometry or cross-frame cache lives here.
            for cell in dict.fromkeys(cells[index]):
                self.grid.setdefault(cell, []).append(index)
        self.offsets[target_count] = offset
        self.grid = {key: tuple(indices) for key, indices in self.grid.items()}

    def __dealloc__(self):
        free(self.boxes)
        free(self.offsets)

    def scan(self, previews, Py_ssize_t start, cancelled=None):
        """Return (next offset, hits), stopping at the first raw-hit belt.

        At most 256 previews are examined. Cancellation is checked before each
        preview, including non-belts, exactly like the Python reference. Never
        look ahead past a hit: Python must apply graph rescue before we resume.
        """
        from flab2bp.dsp.planet import ProjectionCancelled

        cdef Py_ssize_t count = len(previews)
        if start < 0 or start > count:
            raise ValueError("start must be within the previews sequence")
        cdef Py_ssize_t stop = start + min(256, count - start)
        cdef Py_ssize_t index, target, box
        cdef double centre[3]
        for index in range(start, stop):
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            preview = previews[index]
            if not preview.is_belt:
                continue
            self.probe._probe(preview.x, preview.y, preview.z, centre)
            # Keep Python float floor division, including signed/subnormal
            # boundary behavior; cdivision=True must not rewrite these keys.
            key = (
                int((<object>centre[0]) // 8.0),
                int((<object>centre[1]) // 8.0),
                int((<object>centre[2]) // 8.0),
            )
            candidates = self.grid.get(key)
            if candidates is None:
                continue
            hits = []
            for target in candidates:
                for box in range(self.offsets[target], self.offsets[target + 1]):
                    if _prepared_sphere_overlap(
                        centre[0], centre[1], centre[2], self.radius, &self.boxes[box]
                    ):
                        hits.append(self.target_indices[target])
                        break
            if hits:
                return index + 1, tuple(sorted(hits))
        return stop, ()
