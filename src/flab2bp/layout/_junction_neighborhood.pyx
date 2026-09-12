# cython: language_level=3, boundscheck=False, wraparound=False
# distutils: language = c++
"""Frontier-local physical broad phase; no admission answers are retained.

The owner snapshots only selected tap coordinates. Ordered survivors must still
pass the canonical collider, guard, reservation, and ownership checks. Callers
must discard the owner before changing which taps are selected.
"""
from time import monotonic
from cpython.exc cimport PyErr_CheckSignals
from libcpp.vector cimport vector

cdef extern from *:
    r"""
    struct JunctionPoint { long long x, y, z; };
    static inline bool junction_near(const JunctionPoint& a, const JunctionPoint& b) noexcept {
        if (a.x == b.x && a.y == b.y && a.z == b.z) return false;
        __int128 dx = (__int128)a.x - b.x;
        __int128 dy = (__int128)a.y - b.y;
        __int128 dz = (__int128)a.z - b.z;
        return -3 <= dx && dx <= 3 && -3 <= dy && dy <= 3 && -3 <= dz && dz <= 3;
    }
    """
    cdef cppclass JunctionPoint:
        long long x, y, z
    bint junction_near(const JunctionPoint&, const JunctionPoint&) noexcept nogil

cdef void poll(cancelled, deadline) except *:
    PyErr_CheckSignals()
    if cancelled is not None and cancelled():
        raise InterruptedError("junction neighborhood cancelled")
    if deadline is not None and monotonic() >= deadline:
        raise TimeoutError("junction neighborhood deadline")


cdef class JunctionNeighborhood:
    cdef vector[JunctionPoint] peers
    cdef list cells
    cdef object deadline, cancelled

    def __cinit__(self, planned, *, deadline=None, cancelled=None):
        cdef JunctionPoint point
        cdef Py_ssize_t i
        self.deadline, self.cancelled = deadline, cancelled
        self.cells = []
        poll(cancelled, deadline)
        self.peers.reserve(len(planned))
        for i, cell in enumerate(planned):
            if (i & 63) == 0:
                poll(cancelled, deadline)
            point.x, point.y, point.z = cell
            self.peers.push_back(point)
            self.cells.append(cell)
        poll(cancelled, deadline)

    def nearby(self, cell):
        """Return exact ordered broad-phase survivors, never a partial result."""
        cdef JunctionPoint point
        cdef Py_ssize_t i
        point.x, point.y, point.z = cell
        poll(self.cancelled, self.deadline)
        result = []
        for i in range(self.peers.size()):
            if i and (i & 4095) == 0:
                poll(self.cancelled, self.deadline)
            if junction_near(self.peers[i], point):
                result.append(self.cells[i])
        poll(self.cancelled, self.deadline)
        return tuple(result)

    @property
    def storage_bytes(self):
        """Owned native capacity and Python coordinate-reference list storage."""
        return self.peers.capacity() * sizeof(JunctionPoint) + self.cells.__sizeof__()
