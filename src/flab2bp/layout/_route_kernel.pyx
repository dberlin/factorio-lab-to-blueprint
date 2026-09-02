# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True
"""Flat-grid A* inner loop.  Byte-identical to ``freeform._astar``'s loop.

The heap orders on ``(f, g, index)`` exactly as ``heapq`` orders the Python
tuples, costs are accumulated in the same association order, and the
expansion checkpoint arithmetic is copied rather than simplified, so the
replay digest in ``scripts/route_bench.py`` is unchanged.
"""

from array import array

from libc.math cimport INFINITY
from libc.stdlib cimport free, malloc


cdef struct Entry:
    double f
    double g
    long long index


cdef inline bint entry_less(Entry a, Entry b) noexcept nogil:
    if a.f != b.f:
        return a.f < b.f
    if a.g != b.g:
        return a.g < b.g
    return a.index < b.index


cdef class _Heap:
    """A binary heap of ``Entry`` ordered exactly as ``heapq`` orders the tuples.

    ``(f, g, index)`` is a strict total order -- ``index`` alone would be, and
    two pushes of the same index carry the same ``(f, g)`` only when they are
    the same entry -- so the pop sequence does not depend on which correct heap
    implementation produced it.  That is what makes the replay digest stable.
    """

    cdef Entry* data
    cdef Py_ssize_t size
    cdef Py_ssize_t capacity

    def __cinit__(self, Py_ssize_t capacity):
        self.capacity = capacity if capacity > 16 else 16
        self.data = <Entry*> malloc(self.capacity * sizeof(Entry))
        if self.data == NULL:
            raise MemoryError()
        self.size = 0

    def __dealloc__(self):
        if self.data != NULL:
            free(self.data)

    cdef int push(self, double f, double g, long long index) except -1:
        cdef Entry* grown
        cdef Py_ssize_t pos, parent
        cdef Entry item
        if self.size == self.capacity:
            grown = <Entry*> malloc(self.capacity * 2 * sizeof(Entry))
            if grown == NULL:
                raise MemoryError()
            for pos in range(self.size):
                grown[pos] = self.data[pos]
            free(self.data)
            self.data = grown
            self.capacity *= 2
        item.f = f
        item.g = g
        item.index = index
        pos = self.size
        self.size += 1
        while pos > 0:
            parent = (pos - 1) >> 1
            if entry_less(item, self.data[parent]):
                self.data[pos] = self.data[parent]
                pos = parent
            else:
                break
        self.data[pos] = item
        return 0

    cdef Entry pop(self) noexcept nogil:
        cdef Entry top = self.data[0]
        cdef Entry last
        cdef Py_ssize_t pos = 0, child
        self.size -= 1
        if self.size > 0:
            last = self.data[self.size]
            while True:
                child = 2 * pos + 1
                if child >= self.size:
                    break
                if child + 1 < self.size and entry_less(self.data[child + 1], self.data[child]):
                    child += 1
                if entry_less(self.data[child], last):
                    self.data[pos] = self.data[child]
                    pos = child
                else:
                    break
            self.data[pos] = last
        return top


cdef double _h(
    long long col, long long gh, bint single, bint exact,
    long long only_x, long long only_y,
    const long long[::1] goal_columns, Py_ssize_t goal_count,
    long long bx0, long long by0, long long bx1, long long by1,
    Py_ssize_t bands, const long long* band_index, const long long* band_lo,
    const long long* band_hi, const long long[::1] alt_flat, long long columns,
) noexcept nogil:
    cdef long long x = col // gh
    cdef long long y = col - x * gh
    cdef long long dx, dy, dsum, best_d, fx, fy, dial, gap
    cdef double far
    cdef Py_ssize_t k, b
    if single:
        dx = x - only_x
        dy = y - only_y
        far = <double> ((dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy))
    elif exact:
        best_d = 1 << 30
        for k in range(goal_count):
            fx = goal_columns[2 * k]
            fy = goal_columns[2 * k + 1]
            dx = x - fx
            dy = y - fy
            dsum = (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)
            if dsum < best_d:
                best_d = dsum
        far = <double> best_d
    else:
        dx = bx0 - x
        if x - bx1 > dx:
            dx = x - bx1
        if dx < 0:
            dx = 0
        dy = by0 - y
        if y - by1 > dy:
            dy = y - by1
        if dy < 0:
            dy = 0
        far = <double> (dx + dy)
    for b in range(bands):
        dial = alt_flat[band_index[b] * columns + col]
        if dial < 0:
            continue
        gap = band_lo[b] - dial
        if <double> gap > far:
            far = <double> gap
        gap = dial - band_hi[b]
        if <double> gap > far:
            far = <double> gap
    return far


def astar_flat(
    const unsigned char[::1] flags,
    const double[::1] hist,
    double pressure,
    const long long[::1] alt_flat,
    long long band_count,
    const unsigned char[::1] goal_flag,
    const long long[::1] goal_columns,
    bint exact_goals,
    tuple goal_box,
    const long long[::1] starts,
    long long gh,
    long long xstep,
    long long levels,
    const double[::1] level_toll,
    long long max_expansions,
    long long budget_left,
    long long deadline_every,
    object deadline,
    object expired,
):
    """Expand from ``starts`` until a goal, a budget, or an empty heap.

    Returns ``(path, expansions, kind, settled, budget_left)``.  ``kind`` is 0
    when a goal was popped -- ``path`` is then the cell indices oldest first,
    with each ramp's intermediate run cell spliced in after the cell it serves
    -- 1 when the expansion cap, the deadline or the shared budget stopped the
    search, and 2 when the heap emptied, which is the one ending that proves
    the pocket is sealed and the only one that fills ``settled`` (every cell
    with a finite cost, in index order).  ``path`` is None and ``settled``
    empty for every kind that does not name them.

    ``budget_left`` reproduces the Python loop's write-back exactly, including
    its deliberate asymmetry: the cap and deadline exits return
    ``start_left - expansions + 1`` because the budget was charged for an
    expansion only AFTER those two had let it through, while exhausting the
    budget, finding a goal and sealing all return ``start_left - expansions``.
    The caller stores it verbatim; getting the +1 wrong changes how many nodes
    every later net in the pass is allowed to spend.
    """
    cdef Py_ssize_t size = flags.shape[0]
    cdef long long columns = size // levels
    cdef bint negotiating = hist.shape[0] > 0
    cdef Py_ssize_t goal_count = goal_columns.shape[0] // 2
    cdef bint single = goal_count == 1
    cdef long long only_x = goal_columns[0] if goal_count else 0
    cdef long long only_y = goal_columns[1] if goal_count else 0
    cdef long long bx0 = goal_box[0], by0 = goal_box[1], bx1 = goal_box[2], by1 = goal_box[3]
    cdef Py_ssize_t b, k, i, bands = 0
    cdef long long lo, hi, dial, at
    cdef long long* band_index = NULL
    cdef long long* band_lo = NULL
    cdef long long* band_hi = NULL
    cdef double* best = NULL
    cdef long long* prev = NULL
    cdef long long* via = NULL
    cdef double* hcache = NULL
    cdef _Heap heap
    cdef Entry cur
    cdef long long si, col, expansions = 0, start_left = budget_left
    cdef long long checkpoint, due, q, lvl, nxt, run, top, step, node, found = -1
    cdef long long walked, walk_limit
    cdef double g, cost, step_toll, run_base, far, toll2, h0
    cdef int kind = 2
    cdef Py_ssize_t d, r
    cdef long long one, two, colone, coltwo
    cdef long long moves[4][4]
    cdef long long ramp_steps[2]

    # EXACTLY `band_count` fields, not "at least".  `alt` and `alt_flat` are
    # written together and a buffer of the wrong length in either direction
    # means they have come apart -- too long is a stale `alt_flat` left behind
    # by a shorter `alt`, and every dial this reads after that belongs to the
    # wrong landmark.  `boundscheck=False` would neither catch that nor the
    # too-short case, which reads past the buffer outright.
    if band_count > 0 and band_count * columns != alt_flat.shape[0]:
        raise ValueError(
            "alt_flat holds a different number of landmark fields than band_count"
        )
    # The `try` opens on the FIRST allocation so a MemoryError on any later one
    # still frees what came before it.  Every pointer is NULL-initialised above
    # and `free(NULL)` is a no-op, so the `finally` can free unconditionally.
    if band_count > 0:
        band_index = <long long*> malloc(band_count * sizeof(long long))
    try:
        if band_count > 0:
            band_lo = <long long*> malloc(band_count * sizeof(long long))
            band_hi = <long long*> malloc(band_count * sizeof(long long))
            if band_index == NULL or band_lo == NULL or band_hi == NULL:
                raise MemoryError()
        best = <double*> malloc(size * sizeof(double))
        prev = <long long*> malloc(size * sizeof(long long))
        via = <long long*> malloc(size * sizeof(long long))
        hcache = <double*> malloc(columns * sizeof(double))
        if best == NULL or prev == NULL or via == NULL or hcache == NULL:
            raise MemoryError()
        # Landmark bands: the goals occupy [lo, hi] on each landmark's dial; a
        # landmark that cannot reach every goal is DROPPED, as in Python.
        for b in range(band_count):
            lo = -1
            hi = -1
            for k in range(goal_count):
                at = goal_columns[2 * k] * gh + goal_columns[2 * k + 1]
                dial = alt_flat[b * columns + at]
                if dial < 0:
                    lo = -1
                    break
                if lo < 0 or dial < lo:
                    lo = dial
                if dial > hi:
                    hi = dial
            if lo >= 0:
                band_index[bands] = b
                band_lo[bands] = lo
                band_hi[bands] = hi
                bands += 1

        for i in range(size):
            best[i] = INFINITY
            prev[i] = -1
            via[i] = -1
        for i in range(columns):
            hcache[i] = -1.0

        # (one-step cell offset, two-step cell offset, one-step column offset,
        # two-step column offset) for _STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1)).
        moves[0][0] = xstep;   moves[0][1] = 2 * xstep;   moves[0][2] = gh;   moves[0][3] = 2 * gh
        moves[1][0] = -xstep;  moves[1][1] = -2 * xstep;  moves[1][2] = -gh;  moves[1][3] = -2 * gh
        moves[2][0] = levels;  moves[2][1] = 2 * levels;  moves[2][2] = 1;    moves[2][3] = 2
        moves[3][0] = -levels; moves[3][1] = -2 * levels; moves[3][2] = -1;   moves[3][3] = -2
        ramp_steps[0] = 1
        ramp_steps[1] = -1

        heap = _Heap(1024)
        for i in range(starts.shape[0]):
            si = starts[i]
            best[si] = 0.0
            prev[si] = -1
            col = si // levels
            h0 = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns, goal_count,
                    bx0, by0, bx1, by1, bands, band_index, band_lo, band_hi, alt_flat, columns)
            heap.push(h0, 0.0, si)

        checkpoint = max_expansions + 1
        if checkpoint > deadline_every:
            checkpoint = deadline_every
        if start_left < checkpoint:
            checkpoint = start_left

        while heap.size > 0:
            cur = heap.pop()
            g = cur.g
            if g > best[cur.index]:
                continue
            expansions += 1
            if expansions >= checkpoint:
                if expansions > max_expansions:
                    kind = 1
                    budget_left = start_left - expansions + 1
                    break
                if expansions % deadline_every == 0 and expired(deadline):
                    kind = 1
                    budget_left = start_left - expansions + 1
                    break
                if expansions >= start_left:
                    kind = 1
                    budget_left = start_left - expansions
                    break
                checkpoint = max_expansions + 1
                due = (expansions // deadline_every + 1) * deadline_every
                if due < checkpoint:
                    checkpoint = due
                if start_left < checkpoint:
                    checkpoint = start_left
            if goal_flag[cur.index]:
                kind = 0
                found = cur.index
                budget_left = start_left - expansions
                break
            q = cur.index // levels
            lvl = cur.index - q * levels
            step_toll = 1.0 + level_toll[lvl]
            run_base = g + 3.0
            for d in range(4):
                one = moves[d][0]
                two = moves[d][1]
                colone = moves[d][2]
                coltwo = moves[d][3]
                nxt = cur.index + one
                if not flags[nxt]:
                    continue
                cost = g + step_toll
                if negotiating:
                    cost += hist[nxt] * pressure
                if cost < best[nxt]:
                    best[nxt] = cost
                    prev[nxt] = cur.index
                    via[nxt] = -1
                    col = q + colone
                    far = hcache[col]
                    if far < 0.0:
                        far = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns,
                                 goal_count, bx0, by0, bx1, by1, bands, band_index, band_lo,
                                 band_hi, alt_flat, columns)
                        hcache[col] = far
                    heap.push(cost + far, cost, nxt)
                run = cur.index + two
                for r in range(2):
                    step = ramp_steps[r]
                    if lvl + step < 0 or lvl + step >= levels:
                        continue
                    toll2 = level_toll[lvl + step]
                    top = run + step
                    if not flags[top]:
                        continue
                    cost = run_base + toll2
                    if negotiating:
                        cost += hist[top] * pressure
                    if cost < best[top]:
                        best[top] = cost
                        prev[top] = cur.index
                        via[top] = nxt
                        col = q + coltwo
                        far = hcache[col]
                        if far < 0.0:
                            far = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns,
                                     goal_count, bx0, by0, bx1, by1, bands, band_index, band_lo,
                                     band_hi, alt_flat, columns)
                            hcache[col] = far
                        heap.push(cost + far, cost, top)
        else:
            # The heap emptied: sealed.  Same write-back as the Python loop.
            budget_left = start_left - expansions

        path = None
        settled = array("q")
        if kind == 0:
            out = array("q")
            node = found
            walked = 0
            # `prev` must be acyclic; the Python loop guards the same walk with a
            # visited set.  A cycle cannot produce more entries than there are
            # cells plus one via apiece, so overrunning that is the same fault
            # and fails as loudly instead of growing `out` without bound.
            walk_limit = 2 * <long long> size + 2
            while node != -1:
                out.append(node)
                if via[node] != -1:
                    out.append(via[node])
                node = prev[node]
                walked += 1
                if walked > walk_limit:
                    raise AssertionError(
                        "cycle in A* predecessor chain; "
                        "a ramp move corrupted an existing predecessor"
                    )
            out.reverse()
            path = out
        elif kind == 2:
            for i in range(size):
                if best[i] != INFINITY:
                    settled.append(i)
        return path, expansions, kind, settled, budget_left
    finally:
        free(best)
        free(prev)
        free(via)
        free(hcache)
        free(band_index)
        free(band_lo)
        free(band_hi)


cdef inline double _congestion(
    long long index,
    double weight,
    const double[::1] present,
    bint has_history,
    const double[::1] history,
) noexcept nogil:
    """``weight * (present + historical)`` for one cell.

    ``present`` arrives already multiplied by ``_PRESENT_COST`` so this is the
    same double the Python ``congestion`` closure computes, term for term.
    """
    cdef double historical = history[index] if has_history else 0.0
    return weight * (present[index] + historical)


cdef inline double _relaxed_h(
    long long index,
    long long gh,
    long long levels,
    const long long[::1] goal_xy,
) noexcept nogil:
    """Manhattan distance to the nearest goal column, as a double.

    The Python heuristic is an ``int``; every value it can take here is a small
    non-negative integer, exactly representable, and ``next_cost + heuristic``
    is the same double whichever type the addend arrived as.
    """
    cdef long long column = index // levels
    cdef long long x = column // gh
    cdef long long y = column - x * gh
    cdef long long closest = -1, distance, k, gx, gy
    cdef long long count = goal_xy.shape[0] // 2
    for k in range(count):
        gx = goal_xy[2 * k]
        gy = goal_xy[2 * k + 1]
        distance = (x - gx if x >= gx else gx - x) + (y - gy if y >= gy else gy - y)
        if closest < 0 or distance < closest:
            closest = distance
    return <double> closest


def relaxed_search_flat(
    const unsigned char[::1] flags,
    const double[::1] present,
    const double[::1] history,
    double weight,
    const long long[::1] transitions_target,
    const long long[::1] transitions_via,
    const double[::1] transitions_cost,
    const long long[::1] starts,
    const long long[::1] goals,
    const long long[::1] goal_xy,
    long long gh,
    long long levels,
    long long budget,
    object cancelled,
):
    """The relaxed global search's inner loop.  Byte-identical to ``_search_relaxed``.

    Returns ``(path, expansions, exhausted, cancelled)``.  ``path`` is the cell
    indices oldest first with each ramp's run cell spliced in after the cell it
    serves -- the caller decodes and de-loops them -- or None when the search
    ran out of budget, was cancelled, or emptied its heap.  ``exhausted`` is set
    only by the budget exit and ``cancelled`` only by the cancellation exit, so
    exactly one of the three None endings is distinguishable, as in Python.

    The heap orders on ``(f, g, index)`` exactly as ``heapq`` orders the Python
    tuples, ``next_cost = cost + base + congestion(target)`` keeps the Python
    association order, and the goal, budget and cancellation checks sit at the
    same points in the loop, so the paths and expansion counts are the caller's
    unchanged.

    PRECONDITIONS the caller must establish, because the loop indexes
    ``cur + 2 * xstep +- 2 * levels +- 1`` with no bounds check of its own:

    * ``flags`` describes a ``gw x gh x levels`` grid whose passable cells all
      sit at least TWO cells inside the extent in x and y -- the ``_Grid`` pad
      invariant.  Every index the loop touches is either a start or a cell that
      passed ``flags[...]``, so that margin is what keeps the neighbour
      arithmetic inside every buffer.
    * every start index is passable and inside that margin.
    * ``transitions_via`` names a cell one step from the source at the source's
      own level, and a ramp's target level is already inside ``[0, levels)``.

    The three transition buffers hold, per level, a count slot followed by that
    level's entries, and ONLY ``transitions_target`` carries the count: the slot
    is padding in ``transitions_via`` and ``transitions_cost``, never read, and
    a zero there is not a flat step's via.

    Everything checkable in O(size-independent) time -- the buffer lengths
    agreeing with each other, the level table covering exactly ``levels``
    levels without running off its end, and the start and goal indices lying
    inside the grid -- is checked here instead, because buffers that have come
    apart read green under ``boundscheck=False``.
    """
    cdef Py_ssize_t size = flags.shape[0]
    cdef Py_ssize_t table = transitions_target.shape[0]
    cdef bint has_history = history.shape[0] > 0
    cdef double* best = NULL
    cdef long long* predecessor = NULL
    cdef long long* via = NULL
    cdef unsigned char* is_goal = NULL
    cdef long long level_start[16]
    cdef long long level_count[16]
    cdef Py_ssize_t i, pos = 0
    cdef long long lv, s, level, t, at, target, run, node, found = -1, expansions = 0
    cdef long long walked, walk_limit
    cdef double cost0, cost, next_cost
    cdef bint exhausted = False, was_cancelled = False
    cdef _Heap heap
    cdef Entry cur

    if levels < 1 or levels > 16:
        raise ValueError("relaxed_search_flat supports 1 to 16 levels")
    if gh < 1 or size < 1 or size % levels != 0 or (size // levels) % gh != 0:
        raise ValueError("flags does not describe a gw x gh x levels grid")
    if present.shape[0] != size:
        raise ValueError("present holds a different number of cells than flags")
    if has_history and history.shape[0] != size:
        raise ValueError("history holds a different number of cells than flags")
    if transitions_via.shape[0] != table or transitions_cost.shape[0] != table:
        raise ValueError("the three transition buffers hold different numbers of entries")
    if goals.shape[0] < 1:
        raise ValueError("relaxed_search_flat needs at least one goal")
    if goal_xy.shape[0] != 2 * goals.shape[0]:
        raise ValueError("goal_xy does not hold one (x, y) pair per goal")
    for lv in range(levels):
        if pos >= table:
            raise ValueError("the transition table does not cover every level")
        level_count[lv] = transitions_target[pos]
        level_start[lv] = pos + 1
        if level_count[lv] < 0 or pos + 1 + level_count[lv] > table:
            raise ValueError("a transition level runs past the end of the table")
        pos += 1 + level_count[lv]
    for i in range(goals.shape[0]):
        if goals[i] < 0 or goals[i] >= size:
            raise ValueError("a goal index lies outside the grid")
    for i in range(starts.shape[0]):
        if starts[i] < 0 or starts[i] >= size:
            raise ValueError("a start index lies outside the grid")

    # The `try` opens on the FIRST allocation so a MemoryError on any later one
    # still frees what came before it.  Every pointer is NULL-initialised above
    # and `free(NULL)` is a no-op, so the `finally` can free unconditionally.
    best = <double*> malloc(size * sizeof(double))
    try:
        predecessor = <long long*> malloc(size * sizeof(long long))
        via = <long long*> malloc(size * sizeof(long long))
        is_goal = <unsigned char*> malloc(size)
        if best == NULL or predecessor == NULL or via == NULL or is_goal == NULL:
            raise MemoryError()
        for i in range(size):
            best[i] = INFINITY
            predecessor[i] = -2
            via[i] = -1
            is_goal[i] = 0
        for i in range(goals.shape[0]):
            is_goal[goals[i]] = 1

        heap = _Heap(1024)
        for i in range(starts.shape[0]):
            s = starts[i]
            cost0 = _congestion(s, weight, present, has_history, history)
            if cost0 < best[s]:
                best[s] = cost0
                predecessor[s] = -1
                heap.push(cost0 + _relaxed_h(s, gh, levels, goal_xy), cost0, s)

        while heap.size > 0:
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            cur = heap.pop()
            cost = cur.g
            if cost > best[cur.index]:
                continue
            if expansions >= budget:
                exhausted = True
                break
            expansions += 1
            if is_goal[cur.index]:
                found = cur.index
                break
            level = cur.index % levels
            for t in range(level_count[level]):
                at = level_start[level] + t
                target = cur.index + transitions_target[at]
                if not flags[target]:
                    continue
                run = -1
                if transitions_via[at] != 0:
                    run = cur.index + transitions_via[at]
                    if not flags[run]:
                        continue
                next_cost = (
                    cost
                    + transitions_cost[at]
                    + _congestion(target, weight, present, has_history, history)
                )
                if run != -1:
                    next_cost += _congestion(run, weight, present, has_history, history)
                if next_cost >= best[target]:
                    continue
                best[target] = next_cost
                predecessor[target] = cur.index
                via[target] = run
                heap.push(next_cost + _relaxed_h(target, gh, levels, goal_xy), next_cost, target)

        path = None
        if found != -1:
            out = array("q")
            node = found
            walked = 0
            # `predecessor` must be acyclic; the Python `_reconstruct` guards the
            # same walk with a visited set.  A cycle cannot produce more entries
            # than there are cells plus one via apiece, so overrunning that is
            # the same fault and fails as loudly instead of growing `out`
            # without bound.
            walk_limit = 2 * <long long> size + 2
            while node != -1:
                out.append(node)
                if via[node] != -1:
                    out.append(via[node])
                node = predecessor[node]
                # -2 is the "never reached" sentinel and cannot appear on the
                # chain: `predecessor` is written whenever `best` is, and every
                # node on the chain has a finite `best`.  Python's walk would
                # merely index the array from the wrong end; this one would
                # read `via[-2]` past the buffer, so it stops instead.
                if node < -1:
                    raise AssertionError("relaxed A* predecessor chain left an unvisited cell")
                walked += 1
                if walked > walk_limit:
                    raise AssertionError("cycle in relaxed A* predecessor chain")
            out.reverse()
            path = out
        return path, expansions, exhausted, was_cancelled
    finally:
        free(best)
        free(predecessor)
        free(via)
        free(is_goal)
