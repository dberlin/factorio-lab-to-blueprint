# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True

from array import array as py_array

from libc.math cimport fabs, isfinite


def decode_score(
    const long long[::1] positive,
    const long long[::1] negative,
    const long long[::1] east,
    const long long[::1] north,
    const long long[::1] sizes,
    const long long[::1] nets,
    const double[::1] weights,
    const double[::1] history,
    const long long[::1] targets,
    long long outline_height,
    long long history_width,
    long long sorter_max_reach,
):
    cdef Py_ssize_t size = positive.shape[0]
    cdef Py_ssize_t net_count = weights.shape[0]
    cdef Py_ssize_t target_count = targets.shape[0] // 6
    cdef Py_ssize_t position, first_position, second_position, source_position
    cdef Py_ssize_t index, destination
    cdef long long first, second, source, other
    cdef long long after_source, extent, latest, source_span
    cdef long long width = 0
    cdef long long used_height = 0
    cdef long long gap_area = 0
    cdef long long box_area = 0
    cdef long long dx, dy, x0, y0, x1, y1
    cdef long long stride
    cdef long long producer, consumer, row_gap
    cdef long long missed = 0
    cdef long long overflow
    cdef bint direct
    cdef double weighted_hpwl = 0.0
    cdef double compensation = 0.0
    cdef double term, combined
    cdef double history_cost = 0.0

    cdef object negative_position_array = py_array("q", [0]) * size
    cdef object horizontal_array = bytearray(size * size)
    cdef object vertical_array = bytearray(size * size)
    cdef object earliest_x_array = py_array("q", [0]) * size
    cdef object earliest_y_array = py_array("q", [0]) * size
    cdef object latest_x_array = py_array("q", [0]) * size
    cdef object latest_y_array = py_array("q", [0]) * size
    cdef object weighted_terms_array = py_array("d", [0.0]) * net_count
    cdef long long[::1] negative_position = negative_position_array
    cdef unsigned char[::1] horizontal = horizontal_array
    cdef unsigned char[::1] vertical = vertical_array
    cdef long long[::1] earliest_x = earliest_x_array
    cdef long long[::1] earliest_y = earliest_y_array
    cdef long long[::1] latest_x = latest_x_array
    cdef long long[::1] latest_y = latest_y_array
    cdef double[::1] weighted_terms = weighted_terms_array

    for position in range(size):
        negative_position[negative[position]] = position

    for first_position in range(size):
        first = positive[first_position]
        for second_position in range(first_position + 1, size):
            second = positive[second_position]
            if negative_position[first] < negative_position[second]:
                horizontal[first * size + second] = 1
            else:
                vertical[second * size + first] = 1

    for source_position in range(size):
        source = positive[source_position]
        after_source = earliest_x[source] + sizes[source * 2] + east[source]
        for destination in range(size):
            if horizontal[source * size + destination] and earliest_x[destination] < after_source:
                earliest_x[destination] = after_source

    for source_position in range(size - 1, -1, -1):
        source = positive[source_position]
        after_source = earliest_y[source] + sizes[source * 2 + 1] + north[source]
        for destination in range(size):
            if vertical[source * size + destination] and earliest_y[destination] < after_source:
                earliest_y[destination] = after_source

    for index in range(size):
        extent = earliest_x[index] + sizes[index * 2]
        if extent > width:
            width = extent
        extent = earliest_y[index] + sizes[index * 2 + 1]
        if extent > used_height:
            used_height = extent
    for index in range(size):
        latest_x[index] = width - sizes[index * 2]
        latest_y[index] = outline_height - sizes[index * 2 + 1]

    for source_position in range(size - 1, -1, -1):
        source = positive[source_position]
        source_span = sizes[source * 2] + east[source]
        for destination in range(size):
            if horizontal[source * size + destination]:
                latest = latest_x[destination] - source_span
                if latest < latest_x[source]:
                    latest_x[source] = latest

    for source_position in range(size):
        source = positive[source_position]
        source_span = sizes[source * 2 + 1] + north[source]
        for destination in range(size):
            if vertical[source * size + destination]:
                latest = latest_y[destination] - source_span
                if latest < latest_y[source]:
                    latest_y[source] = latest

    for index in range(size):
        gap_area += east[index] * sizes[index * 2 + 1] + north[index] * sizes[index * 2]
        box_area += sizes[index * 2] * sizes[index * 2 + 1]

    for index in range(net_count):
        source = nets[index * 2]
        destination = nets[index * 2 + 1]
        dx = earliest_x[source] - earliest_x[destination]
        if dx < 0:
            dx = -dx
        dy = earliest_y[source] - earliest_y[destination]
        if dy < 0:
            dy = -dy
        weighted_terms[index] = weights[index] * (dx + dy)
    for index in range(net_count):
        term = weighted_terms[index]
        combined = weighted_hpwl + term
        if fabs(weighted_hpwl) >= fabs(term):
            compensation = compensation + ((weighted_hpwl - combined) + term)
        else:
            compensation = compensation + ((term - combined) + weighted_hpwl)
        weighted_hpwl = combined
    if compensation != 0.0 and isfinite(compensation):
        weighted_hpwl = weighted_hpwl + compensation

    stride = history_width + 1
    for index in range(net_count):
        source = nets[index * 2]
        destination = nets[index * 2 + 1]
        x0 = earliest_x[source]
        if earliest_x[destination] < x0:
            x0 = earliest_x[destination]
        if x0 < 0:
            x0 = 0
        if x0 > history_width:
            x0 = history_width
        y0 = earliest_y[source]
        if earliest_y[destination] < y0:
            y0 = earliest_y[destination]
        if y0 < 0:
            y0 = 0
        if y0 > outline_height:
            y0 = outline_height
        x1 = earliest_x[source] + sizes[source * 2]
        other = earliest_x[destination] + sizes[destination * 2]
        if other > x1:
            x1 = other
        if x1 > history_width:
            x1 = history_width
        y1 = earliest_y[source] + sizes[source * 2 + 1]
        other = earliest_y[destination] + sizes[destination * 2 + 1]
        if other > y1:
            y1 = other
        if y1 > outline_height:
            y1 = outline_height
        history_cost += (
            history[y1 * stride + x1]
            - history[y0 * stride + x1]
            - history[y1 * stride + x0]
            + history[y0 * stride + x0]
        )

    for index in range(target_count):
        producer = targets[index * 6]
        consumer = targets[index * 6 + 1]
        row_gap = (
            earliest_y[consumer]
            + targets[index * 6 + 3]
            - earliest_y[producer]
            - targets[index * 6 + 2]
        )
        direct = (
            row_gap >= 1
            and row_gap <= sorter_max_reach
            and earliest_x[producer] <= earliest_x[consumer] + targets[index * 6 + 5] - 1
            and earliest_x[consumer] <= earliest_x[producer] + targets[index * 6 + 4] - 1
        )
        if not direct:
            missed += 1

    overflow = used_height - outline_height
    if overflow < 0:
        overflow = 0

    return (
        earliest_x_array,
        earliest_y_array,
        latest_x_array,
        latest_y_array,
        width,
        used_height,
        gap_area,
        box_area,
        weighted_hpwl,
        history_cost,
        missed,
        overflow,
    )
