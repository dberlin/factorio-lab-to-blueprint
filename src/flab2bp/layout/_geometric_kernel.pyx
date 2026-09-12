# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False
# distutils: language = c++
"""Directed affine-interval wavefront; no cell-priority search or A* fallback."""
from time import monotonic

from cpython.ref cimport PyObject
from libcpp.vector cimport vector

cdef extern from *:
    r"""
    #include <Python.h>
    #include <algorithm>
    #include <chrono>
    #include <cmath>
    #include <cstdint>
    #include <limits>
    #include <memory>
    #include <mutex>
    #include <queue>
    #include <stdexcept>
    #include <vector>

    namespace flab_geometry {
    using Index = std::int64_t;
    using Clock = std::chrono::steady_clock;
    constexpr double infinity = std::numeric_limits<double>::infinity();
    struct Move { int dx, dy, dz; bool via; double cost; };
    struct Extra { Index source, target; double cost; };
    struct Run { int lo, hi; double price; bool free; };
    struct Segment { int lo, hi; Index label; };
    struct Label {
        int y, z, lo, hi;
        // Preserve affine sums across differently segmented paths. Rounding
        // each interval back to double manufactures strict improvements on
        // equal-cost plateaus and repeatedly fractures their envelopes.
        long double cost, slope;
        Index parent;
        int fixed, dx;
        bool via, horizontal;
        // Real labels cover one uniform row-price run. A reverse edge pays
        // this source toll: it is the original forward landing price.
        double toll = 0.0;
        long double value(int x) const { return cost + slope * (x - lo); }
    };
    struct Row {
        std::vector<Run> runs;
        std::vector<Segment> envelope;
        std::vector<Extra> extras;
        std::vector<int> goals;
    };
    struct Goal { int x, y, z; double toll; };
    struct GoalSegment { int lo, hi, y, y_hi, z; double toll; };
    struct Entry { long double lower; int near; Index label; int horizontal = 0; };
    struct Later {
        bool operator()(const Entry& a, const Entry& b) const {
            if (a.lower != b.lower) return a.lower > b.lower;
            if (a.near != b.near) return a.near > b.near;
            return a.label > b.label;
        }
    };
    struct Reach { int y, z, lo, hi; };
    struct Answer {
        int status = 2;
        std::vector<Index> path;
        std::vector<Reach> reached;
        double cost = infinity;
        Index work = 0, prepared_cells = 0, interval_pops = 0;
        Index labels = 0, offers = 0, intersections = 0, profile_scans = 0;
        Index certified_edges = 0, memory_bytes = 0;
        double preparation_s = 0, search_s = 0, certification_s = 0;
    };
    struct Limit {};
    struct Cancelled {};

    struct DistanceProfile {
        int extent, goal_level;
        std::vector<std::vector<Move>> topology;
        std::vector<long double> costs;
        std::vector<std::vector<int>> corners;
        // Costs are nondecreasing from this distance onward, per source level.
        std::vector<int> monotone_from;
        bool matches(const std::vector<std::vector<Move>>& candidate, int distance, int goal) const {
            if (extent < distance || goal_level != goal || topology.size() != candidate.size()) return false;
            for (std::size_t z = 0; z < topology.size(); ++z) {
                if (topology[z].size() != candidate[z].size()) return false;
                for (std::size_t i = 0; i < topology[z].size(); ++i) {
                    const Move& a = topology[z][i]; const Move& b = candidate[z][i];
                    if (a.dx != b.dx || a.dy != b.dy || a.dz != b.dz || a.via != b.via || a.cost != b.cost)
                        return false;
                }
            }
            return true;
        }
    };
    // Only immutable movement topology is shared. Occupancy, congestion,
    // endpoints and query-local profile preparation are never cached.
    std::mutex distance_cache_mutex;
    std::vector<std::shared_ptr<const DistanceProfile>> distance_cache;

    class Wave {
        int nx, ny, nz;
        bool transposed;
        const unsigned char* flags;
        const double* history;
        PyObject* history_list;
        const double* present;
        bool charge_occupied_cells;
        PyObject* cancelled;
        bool reverse_reach;
        bool backwards;
        double pressure;
        long double xy_price = 0.0, z_price = 0.0;
        bool distance_is_linear = false;
        const std::vector<std::vector<Move>>& forward_moves;
        const std::vector<Extra>& forward_extras;
        std::vector<std::vector<Move>> backward_moves;
        std::vector<Extra> backward_extras;
        const std::vector<std::vector<Move>>& moves;
        const std::vector<Index>& starts;
        const std::vector<Index>& goal_indices;
        const std::vector<Extra>& extras;
        Index limit;
        Clock::time_point deadline;
        bool timed;
        unsigned checks = 0;
        std::vector<Row> rows;
        std::vector<Label> labels;
        std::vector<Segment> patch;
        std::vector<Run> profile_patch;
        std::vector<Goal> goals;
        std::vector<GoalSegment> goal_segments;
        std::vector<std::shared_ptr<const DistanceProfile>> distance_profiles;
        std::vector<std::vector<Move>> distance_topology;
        std::priority_queue<Entry, std::vector<Entry>, Later> queue;
        Answer answer;
        long double best = infinity;
        Index goal_label = -1;
        int goal_x = 0;

        Index index(int x, int y, int z) const {
            return (transposed ? Index(y) * nx + x : Index(x) * ny + y) * nz + z;
        }
        void cell(Index i, int& x, int& y, int& z) const {
            z = int(i % nz); i /= nz;
            if (transposed) { x = int(i % nx); y = int(i / nx); }
            else { y = int(i % ny); x = int(i / ny); }
        }
        double price(int x, int y, int z) const {
            if (reverse_reach) return 0.0;
            Index at = index(x, y, z);
            double historical = history ? history[at]
                : (history_list ? PyFloat_AsDouble(PyList_GET_ITEM(history_list, at)) : 0.0);
            return ((present ? present[at] : 0.0) + historical) * pressure;
        }
        void check(bool force = false) {
            ++checks;
            if ((checks & 4095) == 0 || (force && cancelled)) {
                PyGILState_STATE state = PyGILState_Ensure();
                int interrupted = PyErr_CheckSignals(), stop = 0;
                if (!interrupted && cancelled) {
                    PyObject* result = PyObject_CallNoArgs(cancelled);
                    if (result) {
                        stop = PyObject_IsTrue(result);
                        Py_DECREF(result);
                    } else stop = -1;
                }
                PyGILState_Release(state);
                if (interrupted || stop < 0) throw std::runtime_error("geometric search callback interrupted");
                if (stop) throw Cancelled();
            }
            if (timed && (force || (checks & 63) == 0) && Clock::now() >= deadline) throw Limit();
        }
        void charge() {
            check();
            if (answer.work >= limit) throw Limit();
            ++answer.work;
        }
        static bool same_profile(const Run& a, const Run& b) {
            return a.free == b.free && (!a.free || a.price == b.price);
        }
        bool scan_gap(Row& target, int y, int z, int lo, int hi, int sign,
                      bool stop_at_blocker, int& last) {
            // The caller proves this entire gap is unknown. Each cell is read
            // and charged once, then retained in the query-local sparse profile.
            profile_patch.clear();
            bool blocked = false;
            for (int x = sign > 0 ? lo : hi; lo <= x && x <= hi; x += sign) {
                charge(); ++answer.prepared_cells;
                bool free = flags[index(x, y, z)] != 0;
                Run fresh{x, x, free ? price(x, y, z) : 0.0, free};
                if (!profile_patch.empty() && same_profile(profile_patch.back(), fresh)) {
                    if (sign > 0) profile_patch.back().hi = x;
                    else profile_patch.back().lo = x;
                } else profile_patch.push_back(fresh);
                last = x;
                if (stop_at_blocker && !free) { blocked = true; break; }
            }
            if (sign < 0) std::reverse(profile_patch.begin(), profile_patch.end());
            auto& runs = target.runs;
            auto at = std::lower_bound(runs.begin(), runs.end(), profile_patch.front().lo,
                [](const Run& run, int x) { return run.lo < x; });
            std::size_t first = std::size_t(at - runs.begin()), end = first;
            if (first > 0 && runs[first - 1].hi + 1 == profile_patch.front().lo
                          && same_profile(runs[first - 1], profile_patch.front())) {
                profile_patch.front().lo = runs[--first].lo;
            }
            if (end < runs.size() && profile_patch.back().hi + 1 == runs[end].lo
                                  && same_profile(profile_patch.back(), runs[end])) {
                profile_patch.back().hi = runs[end++].hi;
            }
            runs.erase(runs.begin() + first, runs.begin() + end);
            runs.insert(runs.begin() + first, profile_patch.begin(), profile_patch.end());
            return blocked;
        }
        Row& row(int y, int z, int lo, int hi) {
            Row& result = rows[y * nz + z];
            lo = std::max(0, lo); hi = std::min(nx - 1, hi);
            if (lo > hi) return result;
            auto first = std::lower_bound(result.runs.begin(), result.runs.end(), lo,
                [](const Run& run, int x) { return run.hi < x; });
            if (first != result.runs.end() && first->lo <= lo && first->hi >= hi) return result;
            auto began = Clock::now();
            try {
                int cursor = lo;
                while (cursor <= hi) {
                    check(); ++answer.profile_scans;
                    auto at = std::lower_bound(result.runs.begin(), result.runs.end(), cursor,
                        [](const Run& run, int x) { return run.hi < x; });
                    if (at != result.runs.end() && at->lo <= cursor) {
                        cursor = at->hi + 1;
                        continue;
                    }
                    int last = at == result.runs.end() ? hi : std::min(hi, at->lo - 1);
                    int scanned = cursor;
                    scan_gap(result, y, z, cursor, last, 1, false, scanned);
                    cursor = last + 1;
                }
            } catch (...) {
                answer.preparation_s += std::chrono::duration<double>(Clock::now() - began).count();
                throw;
            }
            answer.preparation_s += std::chrono::duration<double>(Clock::now() - began).count();
            return result;
        }
        void prepare_ray(int y, int z, int origin, int sign, int end) {
            Row& target = rows[y * nz + z];
            auto began = Clock::now();
            try {
                int cursor = origin + sign;
                while (0 <= cursor && cursor < nx && (sign > 0 ? cursor <= end : cursor >= end)) {
                    check(); ++answer.profile_scans;
                    auto at = std::lower_bound(target.runs.begin(), target.runs.end(), cursor,
                        [](const Run& run, int x) { return run.hi < x; });
                    if (at != target.runs.end() && at->lo <= cursor) {
                        if (!at->free) break;
                        cursor = sign > 0 ? at->hi + 1 : at->lo - 1;
                        continue;
                    }
                    int lo = cursor, hi = cursor;
                    if (sign > 0) hi = std::min(end, at == target.runs.end() ? nx - 1 : at->lo - 1);
                    else lo = std::max(end, at == target.runs.begin() ? 0 : (at - 1)->hi + 1);
                    int scanned = cursor;
                    if (scan_gap(target, y, z, lo, hi, sign, true, scanned)) break;
                    cursor = scanned + sign;
                }
            } catch (...) {
                answer.preparation_s += std::chrono::duration<double>(Clock::now() - began).count();
                throw;
            }
            answer.preparation_s += std::chrono::duration<double>(Clock::now() - began).count();
        }
        void measure_distance_prices() {
            // Every primitive and connector must dominate this weighted
            // Manhattan metric. First price XY, then the remaining Z cost.
            auto visit_edges = [&](auto&& visit) {
                for (const auto& level : moves) for (const Move& move : level) {
                    check();
                    visit(std::abs(move.dx) + std::abs(move.dy), std::abs(move.dz), move.cost);
                }
                for (const Extra& edge : extras) {
                    check();
                    int sx, sy, sz, tx, ty, tz;
                    cell(edge.source, sx, sy, sz); cell(edge.target, tx, ty, tz);
                    visit(std::abs(tx - sx) + std::abs(ty - sy), std::abs(tz - sz), edge.cost);
                }
            };
            xy_price = infinity;
            distance_is_linear = nz == 1;
            visit_edges([&](int xy, int, double cost) {
                if (xy == 0) return;
                if (xy > 1) distance_is_linear = false;
                long double unit = static_cast<long double>(cost) / xy;
                while (unit > 0.0 && unit * xy > cost) unit = std::nextafter(unit, 0.0L);
                xy_price = std::min(xy_price, unit);
            });
            if (!std::isfinite(xy_price)) xy_price = 0.0;
            z_price = infinity;
            visit_edges([&](int xy, int z, double cost) {
                if (z == 0) return;
                long double unit = std::max(0.0L, (cost - xy_price * xy) / z);
                while (unit > 0.0 && xy_price * xy + unit * z > cost)
                    unit = std::nextafter(unit, 0.0L);
                z_price = std::min(z_price, unit);
            });
            if (!std::isfinite(z_price)) z_price = 0.0;
        }
        void prepare_distance_topology() {
            if (!distance_topology.empty()) return;
            distance_topology.resize(nz);
            for (int z = 0; z < nz; ++z) for (const Move& move : moves[z]) {
                check();
                if (0 <= z + move.dz && z + move.dz < nz)
                    distance_topology[z].push_back({std::abs(move.dx) + std::abs(move.dy),
                                                   0, move.dz, false, move.cost});
            }
            for (const Extra& edge : extras) {
                check();
                int sx, sy, sz, tx, ty, tz;
                cell(edge.source, sx, sy, sz); cell(edge.target, tx, ty, tz);
                distance_topology[sz].push_back({std::abs(tx - sx) + std::abs(ty - sy),
                                               0, tz - sz, false, edge.cost});
            }
            for (auto& level : distance_topology) {
                std::sort(level.begin(), level.end(), [&](const Move& a, const Move& b) {
                    check();
                    if (a.dz != b.dz) return a.dz < b.dz;
                    if (a.dx != b.dx) return a.dx < b.dx;
                    return a.cost < b.cost;
                });
                level.erase(std::unique(level.begin(), level.end(), [&](const Move& a, const Move& b) {
                    check(); return a.dz == b.dz && a.dx == b.dx;
                }), level.end());
            }
        }
        std::shared_ptr<const DistanceProfile> prepare_distance_profile(int goal_level) {
            int extent = nx + ny - 2;
            prepare_distance_topology();
            {
                std::lock_guard<std::mutex> lock(distance_cache_mutex);
                for (auto at = distance_cache.rbegin(); at != distance_cache.rend(); ++at)
                    if ((*at)->matches(distance_topology, extent, goal_level)) return *at;
            }
            auto profile = std::make_shared<DistanceProfile>();
            profile->extent = extent; profile->goal_level = goal_level;
            profile->topology = distance_topology;
            profile->costs.resize(std::size_t(extent + 1) * nz, infinity);
            profile->corners.resize(nz);
            profile->monotone_from.resize(nz, 0);
            std::vector<std::vector<Move>> incoming(nz);
            for (int z = 0; z < nz; ++z) for (const Move& move : distance_topology[z]) {
                check();
                incoming[z + move.dz].push_back({move.dx, 0, z, false, move.cost});
            }
            // This is a topology relaxation, not a coordinate-space search.
            // A displacement k can change Manhattan distance d only to
            // |d-k|..d+k with the same parity as d+k. Retaining that overshoot
            // obligation avoids treating a ramp as a free XY return at d=0.
            std::priority_queue<Entry, std::vector<Entry>, Later> pending;
            profile->costs[goal_level] = 0.0;
            pending.push({0.0, 0, goal_level});
            while (!pending.empty()) {
                check();
                Entry entry = pending.top(); pending.pop();
                if (entry.lower != profile->costs[entry.label]) continue;
                int distance = int(entry.label / nz), level = int(entry.label % nz);
                for (const Move& edge : incoming[level]) {
                    int first = std::abs(distance - edge.dx), last = std::min(extent, distance + edge.dx);
                    for (int d = first; d <= last; d += 2) {
                        check();
                        Index at = Index(d) * nz + edge.dz;
                        long double value = entry.lower + edge.cost;
                        if (value < profile->costs[at]) {
                            profile->costs[at] = value;
                            pending.push({value, 0, at});
                        }
                    }
                }
            }
            for (int z = 0; z < nz; ++z) {
                for (int d = 0; d <= extent; ++d) {
                    check();
                    long double& value = profile->costs[std::size_t(d) * nz + z];
                    // Keep queue bounds finite for unreachable projected
                    // states: exact reachable-row certificates still require
                    // exhaustive exploration of the original admitted graph.
                    if (!std::isfinite(value)) value = xy_price * d + z_price * std::abs(z - goal_level);
                }
                for (int d = 1; d <= extent; ++d) {
                    check();
                    if (profile->costs[std::size_t(d) * nz + z]
                        < profile->costs[std::size_t(d - 1) * nz + z])
                        profile->monotone_from[z] = d;
                }
                for (int d = 1; d < extent; ++d) {
                    check();
                    long double before = profile->costs[std::size_t(d - 1) * nz + z];
                    long double value = profile->costs[std::size_t(d) * nz + z];
                    long double after = profile->costs[std::size_t(d + 1) * nz + z];
                    if (after - value > value - before) profile->corners[z].push_back(d);
                }
            }
            check(true);
            {
                std::lock_guard<std::mutex> lock(distance_cache_mutex);
                if (distance_cache.size() == 16) distance_cache.erase(distance_cache.begin());
                distance_cache.push_back(profile);
            }
            return profile;
        }
        void prepare_goal_segments() {
            for (const Goal& goal : goals) {
                check();
                if (std::isfinite(goal.toll)) continue;
                // Preserve the original individual-goal path for nonfinite
                // prices; they must never enter an ordering comparator.
                for (const Goal& single : goals) {
                    check();
                    goal_segments.push_back({single.x, single.x, single.y, single.y, single.z, single.toll});
                }
                return;
            }
            auto sorted = goals;
            std::sort(sorted.begin(), sorted.end(), [this](const Goal& a, const Goal& b) {
                check();
                if (a.z != b.z) return a.z < b.z;
                if (a.y != b.y) return a.y < b.y;
                if (a.toll != b.toll) return a.toll < b.toll;
                return a.x < b.x;
            });
            for (const Goal& goal : sorted) {
                check();
                if (!goal_segments.empty()) {
                    auto& last = goal_segments.back();
                    if (last.z == goal.z && last.y == goal.y && last.toll == goal.toll
                        && goal.x <= last.hi + 1) {
                        last.hi = std::max(last.hi, goal.x);
                        continue;
                    }
                }
                goal_segments.push_back({goal.x, goal.x, goal.y, goal.y, goal.z, goal.toll});
            }
            // Adjacent rows with identical X runs form an exact rectangle:
            // no hole, level change or unequal terminal toll is filled.
            std::sort(goal_segments.begin(), goal_segments.end(), [this](const GoalSegment& a, const GoalSegment& b) {
                check();
                if (a.z != b.z) return a.z < b.z;
                if (a.lo != b.lo) return a.lo < b.lo;
                if (a.hi != b.hi) return a.hi < b.hi;
                if (a.toll != b.toll) return a.toll < b.toll;
                return a.y < b.y;
            });
            std::size_t count = 0;
            for (const GoalSegment& goal : goal_segments) {
                check();
                if (count) {
                    auto& last = goal_segments[count - 1];
                    if (last.z == goal.z && last.lo == goal.lo && last.hi == goal.hi
                        && last.toll == goal.toll && goal.y <= last.y_hi + 1) {
                        last.y_hi = std::max(last.y_hi, goal.y_hi);
                        continue;
                    }
                }
                goal_segments[count++] = goal;
            }
            goal_segments.resize(count);
        }
        long double lower(const Label& label) {
            if (reverse_reach) return 0.0;
            if (goals.empty()) return std::min(label.cost, label.value(label.hi));
            long double result = infinity;
            for (const GoalSegment& goal : goal_segments) {
                check();
                const DistanceProfile* profile = nullptr;
                if (!distance_is_linear) {
                    if (distance_profiles.empty()) distance_profiles.resize(nz);
                    auto& cached = distance_profiles[goal.z];
                    if (!cached) cached = prepare_distance_profile(goal.z);
                    profile = cached.get();
                }
                int y_distance = std::max({0, goal.y - label.y, label.y - goal.y_hi});
                auto visit = [&](int lo, int hi, int y_distance) {
                    auto distance_x = [&](int x) { return x < lo ? lo - x : x > hi ? x - hi : 0; };
                    auto consider = [&](int x) {
                        int d = distance_x(x) + y_distance;
                        long double distance = profile ? profile->costs[std::size_t(d) * nz + label.z]
                            : xy_price * d + z_price * std::abs(label.z - goal.z);
                        long double value = label.value(x) + distance;
                        bool at_goal = lo <= x && x <= hi && y_distance == 0 && label.z == goal.z;
                        if (backwards) {
                            if (!at_goal) value += label.toll;
                            if (charge_occupied_cells) value += goal.toll;
                        } else if (!at_goal) value += goal.toll;
                        result = std::min(result, value);
                    };
                    // A point interval has one candidate, including at every
                    // profile kink. Re-evaluating it cannot improve the bound.
                    consider(label.lo);
                    if (label.lo == label.hi) return;
                    int near_lo = std::clamp(lo, label.lo, label.hi);
                    int near_hi = std::clamp(hi, label.lo, label.hi);
                    if (label.lo < near_lo && near_lo < label.hi) consider(near_lo);
                    consider(label.hi);
                    if (near_hi != near_lo && label.lo < near_hi && near_hi < label.hi)
                        consider(near_hi);
                    if (profile) {
                        const auto& corners = profile->corners[label.z];
                        int first = std::min(distance_x(near_lo), distance_x(near_hi)) + y_distance;
                        int last = std::max(distance_x(label.lo), distance_x(label.hi)) + y_distance;
                        for (auto at = std::lower_bound(corners.begin(), corners.end(), first);
                             at != corners.end() && *at <= last; ++at) {
                            check();
                            int delta = *at - y_distance;
                            int left = lo - delta, right = hi + delta;
                            if (label.lo < left && left < label.hi && left != near_lo && left != near_hi)
                                consider(left);
                            if (label.lo < right && right < label.hi && right != near_lo && right != near_hi
                                && right != left) consider(right);
                        }
                    }
                };
                // A directed profile may decrease near the goal but be
                // monotone over every distance this label can reach. Only
                // those suffixes admit the nearest-point goal-run minimum.
                int nearest = std::max({0, goal.lo - label.hi, label.lo - goal.hi}) + y_distance;
                if (profile && nearest < profile->monotone_from[label.z])
                    for (int y = goal.y; y <= goal.y_hi; ++y) {
                        int distance = std::abs(label.y - y);
                        for (int x = goal.lo; x <= goal.hi; ++x) { check(); visit(x, x, distance); }
                    }
                // A negative entry toll can favor a different goal over the
                // zero-entry goal itself. Keep the original row minima there.
                else if (nearest == 0 && goal.y != goal.y_hi && (backwards ? label.toll : goal.toll) < 0)
                    for (int y = goal.y; y <= goal.y_hi; ++y) { check(); visit(goal.lo, goal.hi, std::abs(label.y - y)); }
                else visit(goal.lo, goal.hi, y_distance);
            }
            return result;
        }
        int proximity(const Label& label) {
            if (reverse_reach) return 0;
            int result = nx + ny + nz;
            for (const GoalSegment& goal : goal_segments) {
                check();
                result = std::min(result, std::max({0, goal.lo - label.hi, label.lo - goal.hi})
                    + std::max({0, goal.y - label.y, label.y - goal.y_hi}) + std::abs(label.z - goal.z));
            }
            return result;
        }
        bool is_goal(int x, int y, int z) {
            for (int goal : rows[y * nz + z].goals) {
                check();
                if (goal == x) return true;
            }
            return false;
        }
        void queue_horizontal(Index identity, long double bound) {
            Label source = labels[identity];
            for (int sign : {-1, 1}) {
                long double base = infinity;
                for (const Move& move : moves[source.z]) {
                    check();
                    if (move.dx == sign && move.dy == 0 && move.dz == 0 && !move.via)
                        base = std::min(base, static_cast<long double>(move.cost));
                }
                if (!std::isfinite(base)) continue;
                int origin = sign < 0 ? (source.slope < -base ? source.hi : source.lo)
                                      : (source.slope > base ? source.lo : source.hi);
                // Ignore unknown future congestion while retaining the original
                // interval bound. Each direction remains a queued continuation.
                Label ray = source;
                ray.lo = sign < 0 ? 0 : origin + 1;
                ray.hi = sign < 0 ? origin - 1 : nx - 1;
                if (ray.lo > ray.hi) continue;
                ray.cost = source.value(origin) + base * std::abs(ray.lo - origin);
                ray.slope = sign * base;
                long double pending = std::max(bound, lower(ray));
                if (pending < best) queue.push({pending, proximity(source), identity, sign});
            }
        }
        bool improved(const Label& label, int& lo, int& hi, Index old) {
            if (old < 0) return true;
            const Label& previous = labels[old];
            bool left = label.value(lo) < previous.value(lo);
            bool right = label.value(hi) < previous.value(hi);
            if (left == right) return left;
            int a = lo, b = hi;
            while (a < b) {
                check();
                int middle = a + (b - a) / 2;
                if ((label.value(middle) < previous.value(middle)) == left) a = middle + 1;
                else b = middle;
            }
            if (left) hi = a - 1; else lo = a;
            return true;
        }
        void append(int lo, int hi, Index label) {
            if (!patch.empty() && patch.back().label == label && patch.back().hi + 1 == lo)
                patch.back().hi = hi;
            else patch.push_back({lo, hi, label});
        }
        bool offer(const Label& label) {
            check(); ++answer.offers;
            if (std::isfinite(best) && lower(label) >= best) return false;
            Row& target = rows[label.y * nz + label.z];
            auto& envelope = target.envelope;
            if (envelope.empty()) envelope.push_back({0, nx - 1, -1});
            auto begin = std::lower_bound(envelope.begin(), envelope.end(), label.lo,
                [](const Segment& segment, int x) { return segment.hi < x; });
            std::size_t first = std::size_t(begin - envelope.begin()), end = first;
            patch.clear();
            bool changed = false;
            for (; end < envelope.size() && envelope[end].lo <= label.hi; ++end) {
                check(); ++answer.profile_scans;
                const Segment& segment = envelope[end];
                int a = segment.lo, b = segment.hi;
                Index old = segment.label;
                if (a < label.lo) append(a, label.lo - 1, old);
                int lo = std::max(a, label.lo), hi = std::min(b, label.hi);
                int l = lo, h = hi;
                if (!improved(label, l, h, old)) append(lo, hi, old);
                else {
                    changed = true;
                    if (lo < l) append(lo, l - 1, old);
                    Label fresh = label; fresh.lo = l; fresh.hi = h; fresh.cost = label.value(l);
                    if (backwards) fresh.toll = price(l, fresh.y, fresh.z);
                    Index identity = Index(labels.size()); labels.push_back(fresh);
                    append(l, h, identity);
                    queue.push({lower(fresh), proximity(fresh), identity});
                    for (int x : target.goals) {
                        check();
                        long double terminal = fresh.value(x)
                            + (backwards && charge_occupied_cells ? price(x, fresh.y, fresh.z) : 0.0);
                        if (l <= x && x <= h && terminal < best) {
                            best = terminal; goal_label = identity; goal_x = x;
                        }
                    }
                    if (h < hi) append(h + 1, hi, old);
                }
                if (b > label.hi) append(label.hi + 1, b, old);
            }
            if (!changed) return false;
            if (first > 0 && envelope[first - 1].label == patch.front().label) {
                patch.front().lo = envelope[--first].lo;
            }
            if (end < envelope.size() && envelope[end].label == patch.back().label) {
                patch.back().hi = envelope[end++].hi;
            }
            envelope.erase(envelope.begin() + first, envelope.begin() + end);
            envelope.insert(envelope.begin() + first, patch.begin(), patch.end());
            return true;
        }
        void cross(Index identity, int lo, int hi, const Move& move) {
            // Copy: offer may grow labels and invalidate references into it.
            Label source = labels[identity];
            int y = source.y + move.dy, z = source.z + move.dz;
            if (y < 0 || y >= ny || z < 0 || z >= nz) return;
            int target_lo = std::max(0, lo + move.dx), target_hi = std::min(nx - 1, hi + move.dx);
            if (target_lo > target_hi) return;
            if (std::isfinite(best) && lower({y, z, target_lo, target_hi,
                    source.value(target_lo - move.dx) + move.cost + (backwards ? source.toll : 0.0), source.slope,
                    identity, -1, move.dx, move.via, false}) >= best) return;
            row(y, z, target_lo, target_hi);
            int via_z = reverse_reach || backwards ? z : source.z;
            bool eager_mid = reverse_reach || backwards || (move.dy == 0 && z == source.z);
            if (move.via && eager_mid) row(source.y + move.dy / 2, via_z,
                                           target_lo - move.dx / 2, target_hi - move.dx / 2);
            const auto& targets = rows[y * nz + z].runs;
            const std::vector<Run>* mids = move.via
                ? &rows[(source.y + move.dy / 2) * nz + via_z].runs : nullptr;
            // Explicit starts may be released/blocked, but are admitted as
            // sources. They terminate the reverse probe, never become free
            // intermediate or ramp-via cells.
            if (reverse_reach) for (int x : rows[y * nz + z].goals) {
                check();
                if (target_lo <= x && x <= target_hi &&
                    (!move.via || flags[index(x - move.dx / 2, source.y + move.dy / 2, via_z)]))
                    best = 0.0;
            }
            if (backwards) for (int x : rows[y * nz + z].goals) {
                check();
                if (x < target_lo || x > target_hi || flags[index(x, y, z)]) continue;
                int mx = x - move.dx / 2, my = source.y + move.dy / 2;
                if (move.via && !flags[index(mx, my, via_z)]) continue;
                offer({y, z, x, x, source.value(x - move.dx) + move.cost + source.toll
                       + (move.via && charge_occupied_cells ? price(mx, my, via_z) : 0.0),
                       0, identity, -1, move.dx, move.via, false});
            }
            auto first_target = std::lower_bound(targets.begin(), targets.end(), lo + move.dx,
                [](const Run& run, int x) { return run.hi < x; });
            for (auto it = first_target; it != targets.end() && it->lo <= hi + move.dx; ++it) {
                const Run& target = *it;
                check(); ++answer.profile_scans;
                if (!target.free) continue;
                int l = std::max(lo + move.dx, target.lo);
                int h = std::min(hi + move.dx, target.hi);
                if (l > h) continue;
                if (!mids) {
                    ++answer.intersections;
                    offer({y, z, l, h, source.value(l - move.dx) + move.cost + (backwards ? source.toll : target.price),
                           source.slope, identity, -1, move.dx, move.via, false});
                } else {
                    // A blocked landing cannot use a ramp: leave its via
                    // profile unknown rather than scanning it needlessly.
                    if (!eager_mid) row(source.y + move.dy / 2, via_z,
                                        l - move.dx / 2, h - move.dx / 2);
                    auto first_mid = std::lower_bound(mids->begin(), mids->end(), l - move.dx / 2,
                        [](const Run& run, int x) { return run.hi < x; });
                    for (auto mi = first_mid; mi != mids->end() && mi->lo <= h - move.dx / 2; ++mi) {
                        const Run& mid = *mi;
                        check(); ++answer.profile_scans;
                        if (!mid.free) continue;
                        int ml = std::max(l, mid.lo + move.dx / 2);
                        int mh = std::min(h, mid.hi + move.dx / 2);
                        if (ml > mh) continue;
                        ++answer.intersections;
                        offer({y, z, ml, mh, source.value(ml - move.dx) + move.cost + (backwards ? source.toll : target.price)
                               + (charge_occupied_cells ? mid.price : 0.0),
                               source.slope, identity, -1, move.dx, true, false});
                    }
                }
            }
        }
        void horizontal(Index identity, int lo, int hi, int direction) {
            Label source = labels[identity];
            double left_base = infinity, right_base = infinity;
            for (const Move& move : moves[source.z]) {
                if (move.dy == 0 && move.dz == 0 && !move.via) {
                    if (move.dx == -1) left_base = std::min(left_base, move.cost);
                    if (move.dx == 1) right_base = std::min(right_base, move.cost);
                }
            }
            if (!std::isfinite(left_base) && !std::isfinite(right_base)) return;
            row(source.y, source.z, lo, hi);
            double toll = price(lo, source.y, source.z);
            for (int sign : {-1, 1}) {
                if (direction != 0 && sign != direction) continue;
                long double base = sign < 0 ? left_base : right_base;
                if (!std::isfinite(base)) continue;
                int origin = sign < 0 ? (source.slope < -(base + toll) ? hi : lo)
                                      : (source.slope > base + toll ? lo : hi);
                int end = sign < 0 ? 0 : nx - 1;
                // Offer at a goal projection before inspecting the boundary
                // tail: that offer may establish a closing incumbent.
                if (!reverse_reach) for (const GoalSegment& goal : goal_segments) {
                    check();
                    for (int x : {goal.lo, goal.hi})
                        if (sign > 0 ? x > origin && x < end : x < origin && x > end) end = x;
                }
                long double cost = source.value(origin);
                double previous_toll = toll;
                int at = origin;
                for (;;) {
                    prepare_ray(source.y, source.z, at, sign, end);
                    const auto& runs = rows[source.y * nz + source.z].runs;
                    if (reverse_reach) for (const Run& run : runs) {
                        check();
                        if (!run.free || run.lo > origin || run.hi < origin) continue;
                        for (int x : rows[source.y * nz + source.z].goals) {
                            check();
                            if (x == (sign < 0 ? run.lo - 1 : run.hi + 1)) best = 0.0;
                        }
                        break;
                    }
                    for (int n = 0; n < int(runs.size()); ++n) {
                        check(); ++answer.profile_scans;
                        const Run& run = runs[sign > 0 ? n : int(runs.size()) - n - 1];
                        if (sign > 0) {
                            if (run.hi <= at) continue;
                            if (!run.free) break;
                            int l = std::max(run.lo, at + 1), h = std::min(run.hi, end);
                            if (l != at + 1 || l > h) break;
                            long double slope = base + run.price;
                            long double first = cost + base + (backwards ? previous_toll : run.price);
                            if (!offer({source.y, source.z, l, h, first, slope, identity, origin, 0, false, true})) break;
                            cost = first + slope * (h - l); at = h; previous_toll = run.price;
                        } else {
                            if (run.lo >= at) continue;
                            if (!run.free) break;
                            int l = std::max(run.lo, end), h = std::min(run.hi, at - 1);
                            if (h != at - 1 || l > h) break;
                            long double slope = -(base + run.price);
                            long double first = cost + base + (backwards ? previous_toll : run.price)
                                - slope * (at - l - 1);
                            if (!offer({source.y, source.z, l, h, first, slope, identity, origin, 0, false, true})) break;
                            cost = first; at = l; previous_toll = run.price;
                        }
                    }
                    int next = at + sign;
                    if (backwards && (sign > 0 ? next <= end : next >= end)
                        && !flags[index(next, source.y, source.z)] && is_goal(next, source.y, source.z))
                        offer({source.y, source.z, next, next, cost + base + previous_toll,
                               0, identity, origin, 0, false, true});
                    if (lower(source) >= best) return;
                    int boundary = sign < 0 ? 0 : nx - 1;
                    if (end == boundary || at != end) break;
                    end = boundary;
                }
            }
        }
        void reconstruct() {
            Index identity = goal_label;
            int x = goal_x;
            while (identity >= 0) {
                check();
                const Label& label = labels[identity];
                answer.path.push_back(index(x, label.y, label.z));
                if (label.parent < 0) break;
                const Label& parent = labels[label.parent];
                if (label.fixed >= 0) {
                    int target = label.fixed;
                    if (label.horizontal) {
                        int step = target > x ? 1 : -1;
                        for (int k = x + step; k != target; k += step) {
                            check(); answer.path.push_back(index(k, label.y, label.z));
                        }
                    }
                    x = target;
                } else {
                    int prior = x - label.dx;
                    if (label.via) answer.path.push_back(index(prior + label.dx / 2,
                                                              (parent.y + label.y) / 2, backwards ? label.z : parent.z));
                    x = prior;
                }
                identity = label.parent;
            }
            if (!backwards) std::reverse(answer.path.begin(), answer.path.end());
        }
        void certify() {
            auto began = Clock::now();
            try {
                reconstruct();
                const auto& path = answer.path;
                const auto& admitted_starts = backwards ? goal_indices : starts;
                if (path.empty() || std::find(admitted_starts.begin(), admitted_starts.end(), path.front()) == admitted_starts.end())
                    throw std::logic_error("interval witness has no admitted start");
                int sx, sy, sz; cell(path.front(), sx, sy, sz);
                std::vector<double> costs(path.size(), infinity);
                costs[0] = charge_occupied_cells ? price(sx, sy, sz) : 0.0;
                for (std::size_t at = 0; at + 1 < path.size(); ++at) {
                    check();
                    if (!std::isfinite(costs[at])) continue;
                    int x, y, z; cell(path[at], x, y, z);
                    for (const Move& move : forward_moves[z]) {
                        check(); ++answer.certified_edges;
                        int tx = x + move.dx, ty = y + move.dy, tz = z + move.dz;
                        if (tx < 0 || tx >= nx || ty < 0 || ty >= ny || tz < 0 || tz >= nz) continue;
                        Index target = index(tx, ty, tz);
                        std::size_t end = at + (move.via ? 2 : 1);
                        if (end >= path.size() || path[end] != target || !flags[target]) continue;
                        double via_price = 0.0;
                        if (move.via) {
                            Index via = index(x + move.dx / 2, y + move.dy / 2, z);
                            if (path[at + 1] != via || !flags[via]) continue;
                            if (charge_occupied_cells) via_price = price(x + move.dx / 2, y + move.dy / 2, z);
                        }
                        costs[end] = std::min(costs[end], costs[at] + move.cost + price(tx, ty, tz) + via_price);
                    }
                    int tx, ty, tz; cell(path[at + 1], tx, ty, tz);
                    const auto& links = rows[(backwards ? ty : y) * nz + (backwards ? tz : z)].extras;
                    for (const Extra& edge : links) {
                        check(); ++answer.certified_edges;
                        Index source = backwards ? edge.target : edge.source;
                        Index target = backwards ? edge.source : edge.target;
                        if (source != path[at] || target != path[at + 1] || !flags[target]) continue;
                        costs[at + 1] = std::min(costs[at + 1], costs[at] + edge.cost + price(tx, ty, tz));
                    }
                }
                bool goal = false;
                for (Index end : backwards ? starts : goal_indices) {
                    check();
                    if (end == path.back()) goal = true;
                }
                if (!goal || !std::isfinite(costs.back()) || std::abs(costs.back() - best) > 1e-9 * std::max(1.0L, std::abs(best)))
                    throw std::logic_error("interval witness differs from its directed graph price");
                answer.cost = costs.back();
                check(true);
            } catch (...) {
                answer.certification_s = std::chrono::duration<double>(Clock::now() - began).count();
                throw;
            }
            answer.certification_s = std::chrono::duration<double>(Clock::now() - began).count();
        }
        void memory() {
            answer.labels = Index(labels.size());
            answer.memory_bytes = Index(labels.capacity() * sizeof(Label) + rows.capacity() * sizeof(Row)
                                         + goals.capacity() * sizeof(Goal) + queue.size() * sizeof(Entry)
                                         + goal_segments.capacity() * sizeof(GoalSegment)
                                         + patch.capacity() * sizeof(Segment)
                                         + profile_patch.capacity() * sizeof(Run));
            for (const Row& row : rows) answer.memory_bytes += Index(row.runs.capacity() * sizeof(Run)
                + row.envelope.capacity() * sizeof(Segment) + row.extras.capacity() * sizeof(Extra)
                + row.goals.capacity() * sizeof(int));
            answer.memory_bytes += Index(distance_profiles.capacity() * sizeof(std::shared_ptr<const DistanceProfile>));
            answer.memory_bytes += Index(distance_topology.capacity() * sizeof(std::vector<Move>));
            for (const auto& level : distance_topology)
                answer.memory_bytes += Index(level.capacity() * sizeof(Move));
            for (const auto& profile : distance_profiles) if (profile) {
                answer.memory_bytes += Index(profile->costs.capacity() * sizeof(long double)
                    + profile->corners.capacity() * sizeof(std::vector<int>)
                    + profile->monotone_from.capacity() * sizeof(int)
                    + profile->topology.capacity() * sizeof(std::vector<Move>));
                for (const auto& corners : profile->corners)
                    answer.memory_bytes += Index(corners.capacity() * sizeof(int));
                for (const auto& level : profile->topology)
                    answer.memory_bytes += Index(level.capacity() * sizeof(Move));
            }
            answer.memory_bytes += Index(answer.path.capacity() * sizeof(Index) + answer.reached.capacity() * sizeof(Reach));
            answer.memory_bytes += Index(backward_moves.capacity() * sizeof(std::vector<Move>)
                + backward_extras.capacity() * sizeof(Extra));
            for (const auto& level : backward_moves)
                answer.memory_bytes += Index(level.capacity() * sizeof(Move));
        }
    public:
        Wave(int nx_, int ny_, int nz_, const unsigned char* flags_, const double* history_, PyObject* history_list_,
             double pressure_, const std::vector<std::vector<Move>>& moves_, const std::vector<Index>& starts_,
             const std::vector<Index>& goals_, const std::vector<Extra>& extras_, Index limit_, double remaining,
             const double* present_, bool charge_occupied_cells_, PyObject* cancelled_, bool reverse_reach_,
             bool backwards_, bool transposed_)
            : nx(transposed_ ? ny_ : nx_), ny(transposed_ ? nx_ : ny_), nz(nz_), transposed(transposed_),
              flags(flags_), history(history_), history_list(history_list_),
              present(present_), charge_occupied_cells(charge_occupied_cells_), cancelled(cancelled_),
              reverse_reach(reverse_reach_), backwards(backwards_), pressure(pressure_),
              forward_moves(moves_), forward_extras(extras_), moves(backwards_ ? backward_moves : moves_),
              starts(starts_), goal_indices(goals_), extras(backwards_ ? backward_extras : extras_),
              limit(limit_), timed(remaining >= 0),
              rows(std::size_t(ny) * nz) {
            deadline = Clock::now() + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(std::max(0.0, remaining)));
        }
        Answer solve() {
            auto began = Clock::now();
            try {
                check(true);
                if (limit <= 0) throw Limit();
                for (Index goal : goal_indices) {
                    check(); int x, y, z; cell(goal, x, y, z);
                    goals.push_back({x, y, z, price(x, y, z)}); rows[y * nz + z].goals.push_back(x);
                }
                if (backwards) {
                    backward_moves.resize(nz);
                    for (int z = 0; z < nz; ++z) for (const Move& move : forward_moves[z]) {
                        check();
                        int target = z + move.dz;
                        if (target >= 0 && target < nz)
                            backward_moves[target].push_back({-move.dx, -move.dy, -move.dz, move.via, move.cost});
                    }
                    backward_extras.reserve(forward_extras.size());
                    for (const Extra& edge : forward_extras) {
                        check(); backward_extras.push_back({edge.target, edge.source, edge.cost});
                    }
                }
                for (const Extra& edge : extras) {
                    check(); int x, y, z; cell(edge.source, x, y, z);
                    rows[y * nz + z].extras.push_back(edge);
                }
                if (!extras.empty()) for (Row& row : rows) {
                    check();
                    std::stable_partition(row.extras.begin(), row.extras.end(), [&](const Extra& edge) {
                        check();
                        int x, y, z; cell(edge.target, x, y, z);
                        for (int goal : rows[y * nz + z].goals) {
                            check();
                            if (goal == x) return true;
                        }
                        return false;
                    });
                }
                if (!reverse_reach) { measure_distance_prices(); prepare_goal_segments(); }
                // Admit every zero-edge intersection before preparing any
                // non-overlapping seed; endpoint order must not consume quota.
                if (backwards) for (Index start : starts) {
                    check(); int x, y, z; cell(start, x, y, z);
                    if (!is_goal(x, y, z)) continue;
                    offer({y, z, x, x, 0.0, 0, -1, -1, 0, false, false});
                    if (best == 0.0) break;
                }
                for (Index start : starts) {
                    if (best == 0.0) break;
                    check(); int x, y, z; cell(start, x, y, z);
                    if (backwards && is_goal(x, y, z)) continue;
                    if (reverse_reach || backwards) row(y, z, x, x);
                    if (backwards && !flags[start]) continue;
                    if (reverse_reach && !flags[start]) {
                        if (std::find(rows[y * nz + z].goals.begin(), rows[y * nz + z].goals.end(), x)
                            != rows[y * nz + z].goals.end()) best = 0.0;
                        continue;
                    }
                    offer({y, z, x, x, !backwards && charge_occupied_cells ? price(x, y, z) : 0.0,
                           0, -1, -1, 0, false, false});
                }
                while (!queue.empty()) {
                    check();
                    Entry entry = queue.top(); queue.pop();
                    if (entry.lower >= best) break;
                    Label source = labels[entry.label];
                    if (backwards && !flags[index(source.lo, source.y, source.z)]) continue;
                    std::vector<Segment> active;
                    for (const Segment& segment : rows[source.y * nz + source.z].envelope) {
                        check(); ++answer.profile_scans;
                        if (segment.label == entry.label) active.push_back(segment);
                    }
                    for (const Segment& segment : active) {
                        // Cross propagation and its deferred horizontal closure
                        // are one interval operation, not two charged searches.
                        if (!entry.horizontal) { charge(); ++answer.interval_pops; }
                        if (entry.horizontal || reverse_reach) horizontal(entry.label, segment.lo, segment.hi, entry.horizontal);
                        if (entry.horizontal || entry.lower >= best) continue;
                        for (const Extra& edge : rows[source.y * nz + source.z].extras) {
                            check();
                            if (entry.lower >= best) break;
                            int x, y, z; cell(edge.source, x, y, z);
                            if (x < segment.lo || x > segment.hi) continue;
                            if (source.value(x) + edge.cost + (backwards ? source.toll : 0.0) >= best) continue;
                            int tx, ty, tz; cell(edge.target, tx, ty, tz);
                            row(ty, tz, tx, tx);
                            if (reverse_reach &&
                                std::find(rows[ty * nz + tz].goals.begin(), rows[ty * nz + tz].goals.end(), tx)
                                != rows[ty * nz + tz].goals.end()) best = 0.0;
                            if (!flags[edge.target] && !(backwards && is_goal(tx, ty, tz))) continue;
                            offer({ty, tz, tx, tx, source.value(x) + edge.cost + (backwards ? source.toll : price(tx, ty, tz)),
                                   0, entry.label, x, 0, false, false});
                        }
                        if (entry.lower >= best) continue;
                        for (const Move& move : moves[source.z]) {
                            check();
                            if (entry.lower >= best) break;
                            if (move.dy == 0 && move.dz == 0 && !move.via && std::abs(move.dx) == 1) continue;
                            cross(entry.label, segment.lo, segment.hi, move);
                        }
                    }
                    if (!reverse_reach && !entry.horizontal && entry.lower < best && !active.empty())
                        queue_horizontal(entry.label, entry.lower);
                }
                if (reverse_reach && std::isfinite(best)) answer.status = 0;
                else if (goal_label >= 0) {
                    certify();
                    check(true); answer.status = 0;
                }
                else {
                    for (int y = 0; y < ny; ++y) for (int z = 0; z < nz; ++z)
                        for (const Segment& segment : rows[y * nz + z].envelope) {
                            check();
                            if (segment.label < 0) continue;
                            if (!transposed) answer.reached.push_back({y, z, segment.lo, segment.hi});
                            else for (int x = segment.lo; x <= segment.hi; ++x) {
                                check(); answer.reached.push_back({x, z, y, y});
                            }
                        }
                    check(true); answer.status = 2;
                }
            } catch (const Limit&) {
                answer.status = 1; answer.path.clear(); answer.reached.clear(); answer.cost = infinity;
            } catch (const Cancelled&) {
                answer.status = 3; answer.path.clear(); answer.reached.clear(); answer.cost = infinity;
            }
            answer.search_s = std::chrono::duration<double>(Clock::now() - began).count()
                              - answer.preparation_s - answer.certification_s;
            memory(); return std::move(answer);
        }
    };
    Answer run(int nx, int ny, int nz, const unsigned char* flags, const double* history, PyObject* history_list, double pressure,
               const std::vector<std::vector<Move>>& moves, const std::vector<Index>& starts,
               const std::vector<Index>& goals, const std::vector<Extra>& extras, Index limit, double remaining,
               const double* present, bool charge_occupied_cells, PyObject* cancelled, bool transposed) {
        auto began = Clock::now();
        if (!goals.empty() && goals.size() < starts.size()) {
            double left = remaining < 0 ? -1 : std::max(0.0,
                remaining - std::chrono::duration<double>(Clock::now() - began).count());
            Answer answer = Wave(nx, ny, nz, flags, history, history_list, pressure, moves, goals, starts,
                                 extras, limit, left, present, charge_occupied_cells, cancelled, false, true, transposed).solve();
            if (answer.status == 2) answer.status = 4;
            answer.preparation_s += std::chrono::duration<double>(Clock::now() - began).count()
                - answer.preparation_s - answer.search_s - answer.certification_s;
            return answer;
        }
        // A bounded zero-price interval probe can prove a small destination
        // pocket sealed without traversing a large source component. It never
        // supplies a candidate path, and consumes the original shared work.
        Answer reverse;
        Index allowance = std::min<Index>(limit / 16, 1024);
        if (allowance > 0 && !starts.empty() && !goals.empty()) {
            std::vector<std::vector<Move>> incoming(nz);
            for (int z = 0; z < nz; ++z) for (const Move& move : moves[z]) {
                int target = z + move.dz;
                if (target >= 0 && target < nz)
                    incoming[target].push_back({-move.dx, -move.dy, -move.dz, move.via, 0.0});
            }
            std::vector<Extra> backwards;
            backwards.reserve(extras.size());
            for (const Extra& edge : extras) backwards.push_back({edge.target, edge.source, 0.0});
            double left = remaining < 0 ? -1 : std::max(0.0,
                remaining - std::chrono::duration<double>(Clock::now() - began).count());
            reverse = Wave(nx, ny, nz, flags, nullptr, nullptr, 0.0, incoming, goals, starts,
                           backwards, allowance, left, nullptr, false, cancelled, true, false, transposed).solve();
            if (reverse.status == 2) {
                reverse.status = 4;
                reverse.preparation_s += std::chrono::duration<double>(Clock::now() - began).count()
                    - reverse.preparation_s - reverse.search_s - reverse.certification_s;
                return reverse;
            }
            if (reverse.status == 3) return reverse;
        }
        double left = remaining < 0 ? -1 : std::max(0.0,
            remaining - std::chrono::duration<double>(Clock::now() - began).count());
        Answer answer = Wave(nx, ny, nz, flags, history, history_list, pressure, moves, starts, goals,
                             extras, limit - reverse.work, left, present, charge_occupied_cells, cancelled, false, false, transposed).solve();
        answer.work += reverse.work;
        answer.prepared_cells += reverse.prepared_cells;
        answer.interval_pops += reverse.interval_pops;
        answer.labels += reverse.labels;
        answer.offers += reverse.offers;
        answer.intersections += reverse.intersections;
        answer.profile_scans += reverse.profile_scans;
        answer.memory_bytes = std::max(answer.memory_bytes, reverse.memory_bytes);
        answer.preparation_s += reverse.preparation_s;
        answer.search_s += reverse.search_s;
        double total = std::chrono::duration<double>(Clock::now() - began).count();
        answer.preparation_s += total - answer.preparation_s - answer.search_s - answer.certification_s;
        return answer;
    }
    }
    """
    ctypedef long long Index "flab_geometry::Index"
    cdef cppclass Move "flab_geometry::Move":
        int dx, dy, dz
        bint via
        double cost
    cdef cppclass Extra "flab_geometry::Extra":
        Index source, target
        double cost
    cdef cppclass Reach "flab_geometry::Reach":
        int y, z, lo, hi
    cdef cppclass Answer "flab_geometry::Answer":
        int status
        vector[Index] path
        vector[Reach] reached
        double cost
        Index work, prepared_cells, interval_pops, labels, offers, intersections, profile_scans
        Index certified_edges, memory_bytes
        double preparation_s, search_s, certification_s
    Answer run "flab_geometry::run"(int, int, int, const unsigned char*, const double*, PyObject*, double,
                                   const vector[vector[Move]]&, const vector[Index]&, const vector[Index]&,
                                   const vector[Extra]&, Index, double, const double*, bint, PyObject*, bint) except + nogil

def search_intervals(const unsigned char[::1] flags, history, double pressure,
                     int nx, int ny, int nz, transitions, starts, goals, extra_edges,
                     Index max_work, deadline, present=None, bint charge_occupied_cells=False, cancelled=None):
    """Return status/path/price/component/counters; status 2 is forward, 4 reverse."""
    cdef double began = monotonic()
    cdef double remaining = -1
    cdef const double[::1] hist
    cdef const double* history_ptr = NULL
    cdef PyObject* history_list = NULL
    cdef const double[::1] present_view
    cdef const double* present_ptr = NULL
    cdef PyObject* cancelled_ptr = NULL
    cdef vector[vector[Move]] moves
    cdef vector[Move] level_moves
    cdef vector[Index] seeds, ends
    cdef vector[Extra] extras
    cdef Move move
    cdef Extra edge
    cdef Answer result
    cdef Index size = <Index>nx * ny * nz
    cdef Index node
    cdef int sxlo = nx, sxhi = -1, sylo = ny, syhi = -1
    cdef int gxlo = nx, gxhi = -1, gylo = ny, gyhi = -1
    cdef int x, y
    cdef bint transposed
    if nx <= 0 or ny <= 0 or nz <= 0 or size != flags.shape[0]:
        raise ValueError("geometric dimensions do not match occupancy")
    if present is not None:
        if len(present) != size:
            raise ValueError("geometric present congestion does not match occupancy")
        present_view = present
        present_ptr = &present_view[0]
    if cancelled is not None:
        cancelled_ptr = <PyObject*> cancelled
    if history is not None:
        if len(history) != size:
            raise ValueError("geometric history does not match occupancy")
        if isinstance(history, list):
            history_list = <PyObject*> history
        else:
            hist = history
            history_ptr = &hist[0]
    if len(transitions) != nz:
        raise ValueError("geometric transitions do not match levels")
    for node in starts:
        if node < 0 or node >= size:
            raise ValueError("geometric start is outside occupancy")
        seeds.push_back(node)
        x, y = <int>(node // nz // ny), <int>(node // nz % ny)
        sxlo, sxhi = min(sxlo, x), max(sxhi, x)
        sylo, syhi = min(sylo, y), max(syhi, y)
    for node in goals:
        if node < 0 or node >= size:
            raise ValueError("geometric goal is outside occupancy")
        ends.push_back(node)
        x, y = <int>(node // nz // ny), <int>(node // nz % ny)
        gxlo, gxhi = min(gxlo, x), max(gxhi, x)
        gylo, gyhi = min(gylo, y), max(gyhi, y)
    # Compress along the query's larger endpoint separation. The field stays
    # borrowed in physical order; only coordinates and primitive directions rotate.
    transposed = (not seeds.empty() and not ends.empty()
                  and max(0, gylo - syhi, sylo - gyhi) > max(0, gxlo - sxhi, sxlo - gxhi))
    for row in transitions:
        level_moves.clear()
        for dx, dy, dz, via, cost in row:
            move.dx, move.dy, move.dz = (dy if transposed else dx), (dx if transposed else dy), dz
            move.via, move.cost = via, cost
            level_moves.push_back(move)
        moves.push_back(level_moves)
    for source, edges in extra_edges.items():
        edge.source = source
        for target, cost in edges:
            edge.target, edge.cost = target, cost
            if edge.source < 0 or edge.source >= size or edge.target < 0 or edge.target >= size:
                raise ValueError("geometric connector is outside occupancy")
            extras.push_back(edge)
    if deadline is not None:
        remaining = max(0.0, deadline - monotonic())
    cdef double boundary_s = monotonic() - began
    if history_list != NULL:
        # List-backed repair histories are borrowed lazily under the GIL.
        result = run(nx, ny, nz, &flags[0], history_ptr, history_list, pressure, moves, seeds, ends, extras, max_work, remaining, present_ptr, charge_occupied_cells, cancelled_ptr, transposed)
    else:
        with nogil:
            result = run(nx, ny, nz, &flags[0], history_ptr, NULL, pressure, moves, seeds, ends, extras, max_work, remaining, present_ptr, charge_occupied_cells, cancelled_ptr, transposed)
    return (
        result.status,
        tuple(result.path) if result.status == 0 else None,
        result.cost if result.status == 0 else None,
        tuple((part.y, part.z, part.lo, part.hi) for part in result.reached),
        {"charged_work": result.work, "prepared_cells": result.prepared_cells,
         "interval_pops": result.interval_pops, "labels": result.labels,
         "offers": result.offers, "intersections": result.intersections,
         "profile_scans": result.profile_scans, "certified_edges": result.certified_edges,
         "retained_native_bytes": result.memory_bytes, "copied_history_cells": 0,
         "preparation_s": result.preparation_s + boundary_s,
         "search_s": result.search_s, "certification_s": result.certification_s},
    )
