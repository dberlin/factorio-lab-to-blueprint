"""Strategy B -- free-form packing plus belt routing.

Where Strategy A commits to a global skeleton, this places its units anywhere a
2D packer can fit them and then *routes* the belts through whatever space is
left.  The density ceiling is higher because nothing is reserved in advance; the
risk is the classic place-then-route failure, where phase 1 optimises a proxy
that knows nothing about routing and hands phase 2 a placement it cannot wire.

Three things keep that risk bounded:

* **A strip is routable on its own.**  The placeable unit is not a bare machine
  but a *strip*: a run of machines of one recipe, with its input lanes already
  attached above and its output lanes below, each within sorter reach.  Phase 1
  therefore cannot produce a machine that is impossible to feed -- only one that
  is awkward to reach.
* **A reserved margin** on each strip's east and south faces guarantees a
  connected mesh of free cells for the router, rather than a legal-but-choked
  pack.
* **Negotiated congestion** (PathFinder-style rip-up-and-reroute) resolves the
  contention that remains, and a hard iteration cap plus a guaranteed-feasible
  fallback mean ``lay_out`` always returns something valid.

Deliberate simplifications, each with its reason:

* **No splitters.**  A strip gets one output lane *per destination strip*, so
  every net has exactly one source and one sink.  Belts merge natively in DSP
  (two chains pointing at one tile), so many-to-one needs nothing; giving each
  destination its own lane removes the one-to-many case entirely.  The cost is
  extra lanes, bounded by sorter reach at three per side.
* **Level changes cost two tiles.**  Belts climb 0.5 per tile, so one integer
  level is two tiles of run.  The router reserves both.

Where this differs from the written spec, and why
-------------------------------------------------
The spec's §2.3 chose I/O pads with a solver-chosen face.  This implements the
fixed east/south margin instead: it is the same structural guarantee -- every
unit has free cells adjacent to it -- without a face variable per unit, and the
lanes that pads were meant to reach are already part of the strip.

The spec's §5.3 made the tower lattice a fixed blockage set inside phase 1.  That
encoding fights the objective: the lattice extent depends on the final width,
which is the variable being minimised, so fixing it either inflates the bounding
box or under-covers the result.

Towers are therefore placed between packing and routing, by :func:`_power_plan`,
which covers by NEED rather than by grid: every powered tile must have a free
cell within the tower radius, that condition is checked exactly, and a pack that
fails it is refused as infeasible before a belt is laid.  A pack that passes gets
a placement built greedily against the same condition, connected as it grows, and
held in ``keep_out`` so the router paths around it.

This replaced a lattice with a coverage repair behind it, and the repair is the
part that mattered: it ran AFTER routing, so it searched ground the packing and
the router had already spent, and when it found none it returned quietly and the
candidate died on `power.coverage` having paid for a full routing pass first.
The guarantee is now genuinely structural rather than post-hoc -- and covering by
need measured 2-4x fewer towers than the grid it replaced, which is density
rather than tidiness.
"""

from __future__ import annotations

import hashlib
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog
from flab2bp.layout import finalize, last_mile, routing_domain, slots, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    DEFAULT_SEARCH_WORKERS,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementStats,
    ProjectionFailureRecord,
)
from flab2bp.layout.belt_tiers import retier_belts
from flab2bp.layout.buildings import Kind as BuildingKind
from flab2bp.layout.coater_mode import coater_mode
from flab2bp.layout.finalize import ProjectionNoGood
from flab2bp.layout.observe import SearchEvent, SearchObserver, SearchPhase, stranded_endpoints
from flab2bp.layout.piling import PilerPlan
from flab2bp.layout.route_feedback import (
    Cell,
    ClusterRelationNoGood,
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    LastMileReport,
    LogicalNetId,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    combine_last_mile_reports,
    update_feedback,
)
from flab2bp.layout.sequence_alns import (
    REWARD_RANKS,
    OperatorChoice,
    OperatorContext,
    OperatorMetrics,
    OperatorOutcome,
    OperatorSession,
    RepairOperator,
    destroy_strips,
    metrics_from_evaluation,
    operator_tally,
    remaining_fraction_bucket,
    reward_vector,
)
from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    DirectInsertTarget,
    GapProfile,
    PlacementProblem,
    SequencePair,
    encode_placement,
)
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
from flab2bp.layout.strip_variants import CargoDomain, StripFamilyId, StripInstanceId
from flab2bp.spec import BuildSpec

if TYPE_CHECKING:
    from flab2bp.layout.strip_variants import (
        LaneAttachmentPlan,
        LanePlan,
        LanePortDockPlan,
        ProjectionPitchRequirement,
        StripFamily,
        StripPoseId,
        StripVariant,
    )

_NO_PITCH_REQUIREMENTS: Mapping[StripPoseId, int] = MappingProxyType({})
_NO_STAGED_STATIC_CLEARANCE: Mapping[routing_domain.StagedStaticClearanceKey, int] = (
    MappingProxyType({})
)
_DEFAULT_BAND_POLICY = BandPolicy("portable")

#: Free tiles reserved on a strip's east and south faces.  One is enough for a
#: belt to pass; the router uses upper levels when one is not.
MARGIN = 1
#: Additional free row and column in the deterministic routing seed.  The exact
#: packer may remove it; retaining it in the seed gives every port-access
#: corridor one cell in which to turn before another strip can occupy the route.
_GREEDY_ROUTE_CLEARANCE = 1
#: Sprayed lanes need two additional west cells so the 3x1 coater body clears
#: the machine footprint while retaining a straight predecessor and successor.
_COATER_WEST_CHANNEL = 3

#: At fifteen strips CP-SAT's multi-worker portfolio already changes whether the
#: fixed-seed packing can be routed: the same fifteen-strip plan repeatedly
#: wires with one worker and can exhaust every candidate with the default
#: portfolio.  Pin this structural size and larger so the seed actually names a
#: reproducible candidate, independent of audit job allocation.
_DETERMINISTIC_PACK_STRIPS = 15
#: Fixed CP-SAT work for reproducible large-pack incumbents.  A wall-clock
#: cutoff still raced at one worker: the authoritative fifteen-strip cell
#: alternated between a clean width-48 packing and a width-47 packing whose
#: routing failed exact validation.  0.02 deterministic units reaches the same
#: routable incumbent well inside its 0.6s wall allowance; 0.005 stopped before
#: that incumbent existed.  The wall limit remains armed as the hard deadline.
#:
#: IT SCALES WITH THE PACK, and the fixed constant was a defect.  0.02 was
#: calibrated on fifteen strips and was handed unchanged to a 53-strip
#: `universe-matrix` pack, which returned UNKNOWN on all five solves and
#: produced no incumbent at all -- giving up in 2.58s with 299s of a 300s
#: budget unspent.  See docs/superpowers/specs/2026-09-07-lane-fanout-design.md
#: section 4.1.
_DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE = 0.02


def _deterministic_pack_work(strip_count: int) -> float:
    """Deterministic CP-SAT units a pack of ``strip_count`` strips may spend."""
    scale = max(1, strip_count) / _DETERMINISTIC_PACK_STRIPS
    return _DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE * scale


#: Outer repair iterations before falling back.
OUTER_MAX = 3

#: How many ARRANGEMENTS of each height the sweep may ask CP-SAT for.
#:
#: One was the whole search until this was measured.  ROUTABILITY IS A PROPERTY
#: OF ARRANGEMENT, not of how much room a pack has: over 270 packs really routed
#: across `casimir-crystal`, `information-matrix`, `quantum-chip` and
#: `universe-matrix`, 28 of 50 (spec, height) groups had CP-SAT seeds that
#: DISAGREED on whether the pack wires, and 21 of those 50 disagreed at
#: IDENTICAL WIDTH -- same height, same width, one arrangement wires and another
#: does not.  Seed 0 wired 34 of 50 height-groups; some seed of five wired 48.
#:
#: That is a real property and it is NOT a licence to spend the clock on it. See
#: :meth:`FreeformLayout._sweep`, which stops later draws once they stop adding
#: new assignments, while retaining the measured affordability gate after a
#: routed pack exists.
#:
#: Three, because that is what the density measurement supports -- -1.98% area
#: over four paired rounds at the budget where arrangements are affordable, and
#: -0.25 cells (95% CI [-1.40, +0.90]) over twelve at the budget where mostly
#: they are not -- and every further draw costs a CP-SAT solve and a routing
#: pass.  ``1`` is the search as it stood before this existed and is the control
#: the A/B compares against; see ``audit.py --arrangements``.
_ARRANGEMENTS = 3

#: Consecutive draws that may add no new entry to ``routed_assignments`` before
#: the sweep stops looking, when nothing has wired yet.
#:
#: MEASURED, not guessed.  R2 §6b bypassed the arrangement gate on
#: `universe-matrix` at `--arrangements 16`: EIGHTY candidate slots produced FIVE
#: routing evaluations and cost up to 10 s per cell, because every slot past
#: arrangement 0 returned a byte-identical CP-SAT assignment and hit the
#: duplicate-assignment skip.  Three draws is enough to see that the draw is not
#: moving -- each costs one bounded CP-SAT solve at 0.06 to 0.09 s on those cells
#: -- and it bounds the continuation's cost at the cost of PROVING there is
#: nothing new, which is the only thing that makes it affordable at the audit's
#: `--jobs 16`.
C_SWEEP_STALE_DRAWS = 3

#: CP-SAT's random seed for arrangement 0 -- the constant this always used.
_PACK_RANDOM_SEED = 20260822

#: Gap between one arrangement's seed and the next.  Any coprime-ish stride does;
#: what matters is that it is FIXED, so a re-run asks for the same arrangements.
_ARRANGEMENT_STRIDE = 7919

#: Objective weights.  ``λ`` pulls connected strips together (this is what makes
#: routing tractable); ``μ`` rewards a direct insert, which deletes a whole net.
LAMBDA_HPWL = 1
MU_DIRECT = 4

#: How much of a sweep's clock CP-SAT may have, the rest belonging to the
#: router.  See :meth:`FreeformLayout._sweep`, which is where the measurement
#: that sets it is written down.
_PACK_SHARE = 0.35

#: Expansions the whole `lay_out` call may spend, per second of its ceiling.
#:
#: A BACKSTOP, not the binding constraint -- the wall clock is what bounds the
#: call, and this exists so a re-run at the same budget explores the same
#: number of nodes rather than however many the machine happened to manage.
#:
#: Sized well above what the clock can actually spend, and that margin is not
#: slack, it is the whole point.  One shared `_ROUTING_BUDGET` was tried and it
#: measured four cells WORSE: A* had just got 2.1x faster, so 2M expansions went
#: from more than a 15s ceiling could reach to less, the second candidate height
#: exhausted it, and every height after that got nothing.  A budget that binds
#: before the clock does not bound the runaway the clock already bounds; it just
#: silently deletes the back half of the sweep.  Four hundred thousand a second
#: is roughly two and a half times the measured 155k/sec.
_ROUTING_EXPANSIONS_PER_SECOND = 400_000


def lanes_for(rate: Fraction, capacity: Fraction) -> int:
    """Parallel lanes needed to carry ``rate`` at ``capacity`` per lane.

    Exact throughout: ``math.ceil`` of a ``Fraction`` is exact, so a rate that
    lands precisely on a lane boundary needs no extra lane.  A float would make
    ``24/12`` occasionally demand three lanes.
    """
    if rate <= 0:
        return 0
    if capacity <= 0:
        raise ValueError("belt capacity must be positive")
    return math.ceil(rate / capacity)


def _box(s: routing_domain.Strip) -> tuple[int, int]:
    """The footprint one strip occupies in a pack: its extent plus its channels.

    Stated once so the shelf seed, the CP-SAT model and the height sweep cannot
    drift apart about how much ground a strip costs -- they did, and a seed
    whose width is not measured the same way as the solver's is not an upper
    bound on anything.
    """
    return s.width + s.west_channel + s.tail_extension + MARGIN, s.height + MARGIN


def _shard_sinks(
    sinks: Sequence[routing_domain._CargoSink],
    *,
    cap: int | None = None,
    max_shards: int | None = None,
) -> list[list[routing_domain._CargoSink]]:
    """Chunk output sinks so no strip carries more lanes than a sorter can span.

    EVERY shard drains EVERY product.  One machine makes all of its recipe's
    outputs at once, so a shard that carries lanes for only some of them has
    machines that back up on the rest and stop -- and the strip looks perfectly
    healthy, because the lanes it does have are all connected.  Sequential
    chunking did exactly that: ``plasma-refining`` yields refined-oil and
    hydrogen, its four destinations chunked into a shard of three and a shard of
    one, and the second shard's five machines had nowhere to put their hydrogen.

    So the split is per ITEM rather than across the flat list: each product's
    destinations are divided between the shards, and a shard that would come out
    with none of some product is given a repeat of one of that product's
    destinations instead.  A repeat is not waste -- a sharded producer already
    feeds one consumer from several strips, and the router merges them -- it is
    the only way a shard can drain a product whose consumers are fewer than the
    shards.

    ``cap`` is the room left on the south side once any overflow input lanes are
    seated there; it defaults to the full sorter reach.

    ``max_shards`` is the number of MACHINES available.  A shard with no machine
    leaves its destinations unfed, so the split can never be finer than that --
    and a producer with one machine and four consumers is ordinary
    (``mass-energy-storage`` in the universe-matrix build).  Rather than refuse,
    the chunking stops at ``max_shards`` and hands back shards that may exceed
    ``cap`` lanes; :func:`_merge_lanes` then puts several destinations on ONE
    lane, which is the other axis the geometry actually has.  Callers that pass
    ``max_shards`` must therefore call :func:`_merge_lanes` on every shard.
    """
    reach = catalog.SORTER_MAX_REACH if cap is None else cap
    if reach <= 0:
        raise ValueError("no room left on the south side for any output lane")

    by_cargo: dict[routing_domain.CargoKey, list[str]] = {}
    for item, dest, cargo_domain in sinks:
        by_cargo.setdefault((item, cargo_domain), []).append(dest)
    if not by_cargo:
        return []
    if len(by_cargo) > reach:
        raise ValueError(
            f"a machine yields {len(by_cargo)} distinct cargo lanes but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    n = 1
    while sum(max(1, math.ceil(len(d) / n)) for d in by_cargo.values()) > reach:
        if max_shards is not None and n >= max_shards:
            break
        n += 1

    out: list[list[routing_domain._CargoSink]] = [[] for _ in range(n)]
    for (item, cargo_domain), dests in by_cargo.items():
        per = math.ceil(len(dests) / n)
        for s in range(n):
            chunk = dests[s * per : (s + 1) * per] or [dests[s % len(dests)]]
            out[s].extend((item, d, cargo_domain) for d in chunk)
    return out


def _merge_lanes(
    shard: Sequence[routing_domain._CargoSink],
    reach: int,
    demand: Mapping[routing_domain._CargoSink, Fraction],
    capacity: Fraction,
    stacks: Mapping[str, int] | None = None,
    *,
    supply: Mapping[str, Fraction] | None = None,
) -> list[routing_domain._CargoSink]:
    """Fold a shard's destinations onto at most ``reach`` output lanes.

    ``capacity`` is the belt's rate in CARGO per second; ``stacks`` says how
    many items each item's lane puts in one cargo (multiple-belts design,
    section 5.3).  An absent entry is 1, so an unstacked plan is judged exactly
    as it was.

    Sharding splits a producer's destinations across STRIPS and needs one
    machine per shard.  A producer with one machine and four destinations has no
    second shard to give, so the other axis has to move: one lane serves several
    destinations, each consumer tapping the same lane end, and ``_tap_source``
    turns the second and later taps into a junction there.  That is the same
    mechanism a lane already uses when one destination group is sharded into
    several consumer strips, so it costs no new machinery -- only the
    bookkeeping that a lane's destination field is now a SET.

    Which destinations share a lane is a bin-packing question, and the bin is a
    belt: two consumers whose combined draw exceeds the tier would jam the lane
    however it is routed.  Destinations are therefore packed largest-demand
    first into the least-loaded lane, and a lane that still comes out over
    capacity raises -- refusing is honest, while emitting it would produce a
    blueprint that pastes and then starves whichever consumer loses the race.

    Lanes are handed out one per product first (a shard must drain every
    product, or its machines back up on the one it cannot) and the spares go to
    whichever product has the most destinations per lane so far.

    ``supply`` is items/s of each product the shard's own machines emit.  A lane
    cannot carry more than its producer puts on it, whatever its consumers draw
    -- a both-fed item's consumers are served mostly by the bus -- so the
    over-capacity verdict is taken on ``min(draw, supply)``.  Draw still decides
    which destinations share a lane.  Without ``supply`` the verdict is the
    draw, exactly as before.
    """
    if len(shard) <= reach:
        return list(shard)

    by_cargo: dict[routing_domain.CargoKey, list[str]] = {}
    for item, dest, cargo_domain in shard:
        by_cargo.setdefault((item, cargo_domain), []).append(dest)
    if len(by_cargo) > reach:
        raise ValueError(
            f"a machine yields {len(by_cargo)} distinct cargo lanes but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    alloc = dict.fromkeys(by_cargo, 1)
    for _ in range(reach - len(by_cargo)):
        room = [cargo for cargo in by_cargo if alloc[cargo] < len(by_cargo[cargo])]
        if not room:
            break
        chosen = max(
            room,
            key=lambda cargo: (
                Fraction(len(by_cargo[cargo]), alloc[cargo]),
                cargo[0],
                cargo[1].value,
            ),
        )
        alloc[chosen] += 1

    out: list[routing_domain._CargoSink] = []
    for item, cargo_domain in sorted(
        by_cargo,
        key=lambda cargo: (cargo[0], cargo[1].value),
    ):
        cargo = (item, cargo_domain)
        k = alloc[cargo]
        bins: list[list[str]] = [[] for _ in range(k)]
        loads = [Fraction(0)] * k
        order = sorted(
            by_cargo[cargo],
            key=lambda dest: (
                -demand.get((item, dest, cargo_domain), Fraction(0)),
                dest,
            ),
        )
        for dest in order:
            b = min(range(k), key=lambda i: (loads[i], i))
            bins[b].append(dest)
            loads[b] += demand.get((item, dest, cargo_domain), Fraction(0))
        lane_capacity = capacity * ((stacks or {}).get(item, 1))
        for b, group in enumerate(bins):
            if not group:
                continue
            carried = loads[b]
            if supply is not None and item in supply and supply[item] < carried:
                carried = supply[item]
            if carried > lane_capacity:
                raise ValueError(
                    f"{item}: destinations {sorted(group)} have to share one "
                    f"output lane carrying {carried} items/s, over the "
                    f"{lane_capacity}/s the belt sustains"
                )
            out.append((item, routing_domain.DEST_SEP.join(sorted(group)), cargo_domain))
    return out


def _allocate_machines(
    count: int,
    shards: Sequence[Sequence[routing_domain._CargoSink]],
    demand: Mapping[routing_domain._CargoSink, Fraction],
) -> list[int]:
    """Split ``count`` machines across shards in proportion to demand served.

    An even split would starve whichever shard happens to carry the hungrier
    consumers, so each shard's weight is the largest fraction of any one item's
    total demand that it is responsible for -- one machine produces all of its
    recipe's outputs at once, so the binding item is the one needing most.

    Every shard gets at least one machine (a shard with none leaves its
    destinations unfed), and the total is exactly ``count`` so the placement
    still matches the spec's machine counts.
    """
    n = len(shards)
    totals: dict[routing_domain.CargoKey, Fraction] = defaultdict(Fraction)
    for (item, _dest, cargo_domain), rate in demand.items():
        totals[item, cargo_domain] += rate

    weights: list[Fraction] = []
    for shard in shards:
        served: dict[routing_domain.CargoKey, Fraction] = defaultdict(Fraction)
        for item, dest, cargo_domain in shard:
            cargo = (item, cargo_domain)
            served[cargo] += demand.get((item, dest, cargo_domain), Fraction(0))
        weight = Fraction(0)
        for cargo, rate in served.items():
            total = totals.get(cargo, Fraction(0))
            weight = max(weight, rate / total if total > 0 else Fraction(1, n))
        weights.append(weight if weight > 0 else Fraction(1, n))

    total_weight = sum(weights, Fraction(0))
    if total_weight <= 0:
        weights = [Fraction(1)] * n
        total_weight = Fraction(n)

    # One machine each, then hand out the rest by largest remainder.
    allocation = [1] * n
    remaining = count - n
    exact = [remaining * w / total_weight for w in weights]
    floors = [int(v) for v in exact]
    for i, f in enumerate(floors):
        allocation[i] += f
    leftover = remaining - sum(floors)
    order = sorted(range(n), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        allocation[i] += 1
    return allocation


def _check_shared_lane_capacity(
    g: routing_domain._Group,
    lanes: tuple[tuple[str, ...], ...],
    machines: int,
    spec: BuildSpec,
    *,
    stack: int = 1,
) -> None:
    """A shared lane must carry the SUM of its items within the belt tier.

    PERMANENTLY INERT SINCE SPEC §9 R1, and left in place deliberately.  Its
    body is ``if len(lane) < 2: continue`` and no lane reaches it with two items
    any more, so it never rejects anything and never will while the ban holds.
    That is not a bug to fix by deleting it: it is the check a later ruling
    readmitting a shared lane would need on day one, and removing it is not the
    mixing ban's call to make.  Read it as a dormant guard, not a live one --
    the same status as ``StripVariant.attachment_plan``'s per-item column
    assignment, which is dormant for the same reason.

    Only shared lanes are checked.  A single-item lane is left exactly as it
    was, so this cannot reject a spec that already worked -- mixing was the new
    thing, so mixing is what got the new constraint.

    ``stack`` is the LANE's, taken from the ``LogicalLane`` the family already
    planned rather than re-derived here: one belt has one cargo size, and the
    planner has already reduced a mixed lane to the smallest stack its items
    share.  It defaults to 1, so an omitted stack is "loose items", never
    "unbounded".

    Exact ``Fraction`` throughout: a float here would let a lane that lands
    precisely on the tier's limit read as over capacity, or worse, the reverse.
    """
    cap = spec.lane_capacity * stack
    for lane in lanes:
        if len(lane) < 2:
            continue
        total = sum(
            (g.inputs.get(item, Fraction(0)) * machines for item in lane),
            Fraction(0),
        )
        if total > cap:
            raise ValueError(
                f"recipe {g.recipe_id!r}: lane carrying {list(lane)} needs "
                f"{total} items/s across {machines} machine(s), over the "
                f"{cap}/s the fastest belt this save can build sustains; these ingredients "
                f"cannot share a belt at this rate"
            )


def _side_lane_caps(item_id: int, yaw: float, band_rows: int) -> tuple[int, int]:
    """Lane rows above and below the machine band a sorter can actually reach.

    THIS IS THE SEATING HALF OF THE CORRECTION ``sorter_span`` TOOK IN 5e982bb.
    Both sides were assumed to carry ``SORTER_MAX_REACH`` lanes, counted from the
    machine's FOOTPRINT EDGE, and that is right only for a machine whose insert
    poses sit on that edge with no clearance padding under it.  Two families in
    the catalog break it, in opposite directions:

    * a **Chemical Plant** (and its quantum variant) anchors its north face on
      the row INSIDE its top edge, so the outermost of three lanes above is FOUR
      tiles from anything a sorter can hold: two rows above, three below;
    * an **Assembling Machine** (and the Re-composing Assembler) covers three
      rows and RESERVES four -- its 3.82-unit collider does not fit a 3-tile
      pitch -- and ``_emit_strip`` seats the machines at the top of that band, so
      the padding lands on the south side: three rows above, two below.

    Seating a lane outside that is not a near miss.  ``slots.attachment``
    returns ``None`` for it, ``_link_lane`` places no sorter at all, and the
    machine ships joined to nothing on that lane -- which is what
    ``_machines_without_poses`` refuses on and why the ``organic-crystal`` URL
    refused on every candidate.  Tightening the seat is the fix; widening the
    reach would emit a sorter the game rejects on paste.

    A row is counted only while every row nearer the machine is reachable too,
    so the answer is a contiguous run outward from the band.  It cannot have a
    hole in practice -- span grows monotonically as a lane moves away from the
    one pose row a face offers -- and a prefix is the conservative reading if it
    ever did.

    A BUILDING WITH NO POSES AT ALL GETS THE OLD CONSTANT BACK, deliberately.  A
    Ray Receiver and an Energy Exchanger ship a zero-length ``slotPoses``, so
    every row would score 0 and seating would raise ``cannot be seated`` -- a
    worse message than ``_machines_without_poses``' own, which names the prefab
    and says the game gives it no pose on any face.  That refusal stays the
    owner of this case.
    """
    if not catalog.building(item_id).slot_poses:
        return catalog.SORTER_MAX_REACH, catalog.SORTER_MAX_REACH
    probe = slots.probe_building(item_id, yaw)
    caps: list[int] = []
    for lane_ys in (
        [-(k + 1) for k in range(catalog.SORTER_MAX_REACH)],
        [band_rows + k for k in range(catalog.SORTER_MAX_REACH)],
    ):
        n = 0
        for lane_y in lane_ys:
            if not slots.attachable_columns(probe, lane_y):
                break
            n += 1
        caps.append(n)
    return caps[0], caps[1]


def _flank_seat(item_id: int, yaw: float, gap: int) -> slots.Attachment | None:
    """Where a machine's product leaves eastward, for a belt in column ``gap``.

    ``gap`` is measured from the machine's own west edge and is its CLEARANCE
    width, so the belt stands one column clear of everything the collider needs.
    Putting it inside the clearance would paste as a collision on the belt, which
    is the same rule that makes an Assembling Machine reserve four columns for a
    three-column footprint.

    The row nearest the machine's south edge wins: the gap belt runs from that
    row down to the output lane under the band, and every row above it is another
    belt tile to lay and another cell the router has to path around.

    ``None`` means this building offers no pose on its east face a sorter of that
    span could name.  There is no nearest-legal answer -- refusing to flank is the
    caller's only honest move, and the six-slot ceiling stands.
    """
    probe = slots.probe_building(item_id, yaw)
    rows = slots.attachable_rows(probe, gap)
    if not rows:
        return None
    return rows[max(rows)]


def _seat_inputs(
    items: tuple[str, ...],
    n_sinks: int,
    above_cap: int,
    below_cap: int,
    columns: int,
    *,
    flank_outputs: bool = False,
    seating_fits: Callable[[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]], bool]
    | None = None,
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Seat ingredients into lanes above and below the machine band.

    ONE ITEM PER LANE, or no seating at all.  Spec §9 R1 bans a mixed input
    lane absolutely -- not chosen and not forced -- because nothing controls the
    interleaving on a belt carrying two items into a machine: whichever item the
    machines are not short of fills the belt and the others back up, and the
    machines starve.  The user reported exactly that build.

    So this searches ONE split, not a ladder.  It used to try one item per lane
    first and then climb -- two to a lane, then three, up to a ``max_per_lane``
    cap -- and a ``prefer_shared`` flag reversed the climb for proliferated
    groups to save Spray Coaters.  All of it is gone, the cap parameter with it:
    a bound on how far mixing may go is machinery for a thing that may not
    happen at all.  A seating that cannot fit one item per lane raises,
    :func:`~flab2bp.layout.strip_variants._logical_strip_plans` turns that into
    a refusal, and the audit says REFUSED, which is the truth.  The alternative
    is worse and not cheaper: an emitted mixed lane is an ERROR under
    ``flow.lane_single_item``, so the cell would come back INVALID having paid a
    full routing pass to discover it.  Here the emitter really does agree with
    the validator rather than race it, because a lane's items are settled at
    seating time and nothing downstream adds one.

    That is NOT true of the coater seat chooser this used to be compared to.
    ``prolif.coater_rides_one_run`` has two clauses and :func:`_coater_seats`
    enforces only the second; the first convicts a belt merge the ROUTER makes,
    long after the seat is chosen, so no pre-routing filter can agree with it
    (spec §9 R9).  Do not cite the coater path as the model for this one.

    A ``lane_fits`` per-lane rate predicate went with them, and deliberately was
    not kept as a seam for single-item lanes: it summed the WHOLE group's
    throughput across every strip against one belt, while a lane serves one
    strip, and :func:`~flab2bp.layout.strip_variants._machine_cap` is already the
    single-item rate gate.  Spec §9 R8 records the measurement.

    ``above_cap`` and ``below_cap`` are THIS MACHINE's rows per side, from
    :func:`_side_lane_caps`, and they are not both ``SORTER_MAX_REACH``: a
    Chemical Plant carries two lanes above and an Assembling Machine two below.

    ``columns`` is how many insert poses one FACE of this machine offers a lane,
    and it bounds the side differently from the row caps: a row cap counts
    LANES, this counts SORTERS.  Every item on a side needs its own column,
    because a machine slot holds exactly one connection -- see
    :data:`~flab2bp.dsp.rules.CONN_SLOTS_PER_OBJECT` and
    ``validate.game.slot_occupancy``.  Mixing two items onto one lane saved a
    row and saved no column at all, which is why "mix harder" used to walk
    straight past the real limit without this bound; with the ladder gone,
    ``columns`` is simply what refuses a side carrying more ingredients than the
    face has insert poses.

    It was missing, and what it cost was not hypothetical.  ``universe-matrix``
    takes six ingredients and produces one, and a Matrix Lab offers three
    columns above and three below: seven sorters into six slots.  The old
    seating accepted it, and the emitted blueprint put THREE sorters on slot 6
    and three more on slot 7 of every Matrix Lab -- measured, 4 shared slots per
    build -- which pastes with four of the six unwired.  A refusal here is the
    honest answer, and it is raised where the arithmetic is visible rather than
    left to surface downstream as an unfed machine.

    ``flank_outputs`` says the product leaves by the machines' EAST face, so the
    output lane costs no COLUMN on the south face, and the ROW it costs need not
    be one a sorter can reach.  That is the one degree of freedom that seats
    seven connections on a building that offers six per pair of faces, and it is
    why ``universe-matrix`` seats at all: a Matrix Lab carries all six
    ingredients on six SINGLE-ITEM lanes, three above and three below, with the
    product out east.

    The drain row is where that sixth lane comes from.  A flanked output's lane
    carries no sorter at all -- ``_flank_lane`` puts the only one on the east
    face and runs a gap belt south into the lane -- so the drain can sit on the
    row PAST ``below_cap``, which is the first row with no ``attachable_columns``
    and therefore useless to an input.  ``below_cap`` still bounds the input
    lanes above (an input lane may never sit past reach); only the output's
    reservation is waived, and only when flanked.  Spec §9 R2 records the
    ruling, and §9 R1 is why it had to be made: the seating this replaced put
    three ingredients on one belt above and three on one below, and a belt
    carrying two items into a machine starves it however the sorters filter.
    That seating is not a fallback any more, it is unreachable -- the row had to
    be freed or the Matrix Lab would refuse, because ``flow.lane_single_item``
    convicts the mixed alternative and this function no longer offers it.

    ``seating_fits`` judges a whole candidate split rather than one lane: it is
    where the caller asks whether the ROWS this split implies can be served at
    all.  A row's distance sizes the sorter that reaches it, and no tier is
    faster than the Pile Sorter, so a lane whose rate exceeds what that tier
    sustains across the row it landed on cannot be built however the picker
    upgrades.  It is a PREFERENCE, not a filter: when no split satisfies it the
    search runs again without it, so a spec that has no servable seating keeps
    exactly the seating it had and is judged downstream as before.

    Returns ``(above, below)``.  ``below`` shares the south side with the output
    lanes, so it is kept as small as possible.
    """
    # The output lane still needs its ROW under the band even when flanked --
    # the gap belts drain into it -- but that row need not be one a SORTER can
    # reach, because the drain carries no sorter.  So the column charge goes
    # away entirely and the row charge moves outward, past `below_cap`, where
    # `Strip.row_of_output` seats it once `drain_outermost` says the inputs
    # took every reachable row.
    out_columns = 0 if flank_outputs else (1 if n_sinks else 0)
    n = len(items)
    if n == 0:
        return (), ()
    # One rung, and it is deliberately a one-element tuple rather than an
    # inlined `k = 1`: the ladder is what spec §9 R1 removed, and leaving its
    # shape visible says that the next rung is not missing, it is banned.
    mix_sizes = (1,)

    def search(
        require_servable: bool,
    ) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]] | None:
        for k in mix_sizes:
            lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]
            # The split point is searched rather than fixed at `above_cap`.
            # Filling the north side first was harmless while only ROWS were
            # rationed -- a full north side left the whole south side for the
            # rest.  With columns rationed too it is not: four ingredients mixed
            # two-to-a-lane give two lanes, both of which fit above by row count
            # and neither of which fits by column count, and a fixed split would
            # have refused a spec that seats perfectly well one lane per side.
            # Largest `above` first, so `below` stays as small as it can and
            # leaves the output lane its room.
            for a in range(min(len(lanes), above_cap), -1, -1):
                above, below = tuple(lanes[:a]), tuple(lanes[a:])
                if len(below) > below_cap:
                    continue  # more lanes than that side can hold; try the other split
                if n_sinks and not flank_outputs and below_cap - len(below) <= 0:
                    continue  # no room left below for an output lane
                if sum(len(lane) for lane in above) > columns:
                    continue  # more sorters than the north face has slots
                if sum(len(lane) for lane in below) + out_columns > columns:
                    continue  # ... or than the south face has, output lane included
                if require_servable and seating_fits is not None and not seating_fits(above, below):
                    continue  # rows this split implies carry less than the lanes need
                return above, below
        return None

    if seating_fits is not None:
        servable = search(True)
        if servable is not None:
            return servable
    seated = search(False)
    if seated is not None:
        return seated
    flanked = " with the product leaving east" if flank_outputs else ""
    raise ValueError(
        f"{n} ingredients cannot be seated{flanked}: {above_cap} lane(s) above "
        f"and {below_cap} below, each carrying ONE item, over a face that offers "
        f"{columns} insert pose(s) per side, leaves no room for {n} ingredient "
        f"sorter(s) and the output lane. A machine slot holds one connection, so "
        f"two sorters cannot share a column, and spec §9 R1 forbids merging two "
        f"items onto one belt to save a row -- nothing controls the interleaving "
        f"and the machines starve"
    )


def _plan_strip_pilers(
    spec: BuildSpec,
    groups: Mapping[str, routing_domain._Group],
    strips: list[routing_domain.Strip],
) -> list[routing_domain.Strip]:
    """Stamp tail-end pilers from the stack producer sorters actually place."""
    lane_owners, merge_plans = routing_domain._strip_merge_plans(spec, groups, strips)
    if not merge_plans:
        return strips

    planned_by_lane: dict[tuple[int, int], PilerPlan] = {}
    for merge in merge_plans.values():
        for plan in merge.pilers:
            owner = lane_owners[plan.lane_id]
            previous = planned_by_lane.get(owner)
            if previous is None or (plan.count, plan.stack) > (previous.count, previous.stack):
                planned_by_lane[owner] = plan

    if not planned_by_lane:
        return strips
    piler_tiles = catalog.building(catalog.PILER_ID).height
    planned = list(strips)
    for strip_ordinal in sorted({owner[0] for owner in planned_by_lane}):
        pilers = tuple(
            plan
            for (_owner, plan) in sorted(
                (
                    (owner, plan)
                    for owner, plan in planned_by_lane.items()
                    if owner[0] == strip_ordinal
                ),
                key=lambda entry: entry[0][1],
            )
        )
        count = max(plan.count for plan in pilers)
        planned[strip_ordinal] = replace(
            planned[strip_ordinal],
            tail_extension=piler_tiles * count + count - 1,
            pilers=pilers,
        )
    return planned


def plan_strips(
    spec: BuildSpec,
    *,
    strip_len: int = 6,
    band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS,
    families: Sequence[StripFamily] | None = None,
    minimum_staged_static_clearance: Mapping[
        routing_domain.StagedStaticClearanceKey,
        int,
    ] = _NO_STAGED_STATIC_CLEARANCE,
    cancelled: Callable[[], bool] | None = None,
) -> list[routing_domain.Strip]:
    """Select each logical family's deterministic compatibility pose.

    The legacy Freeform planner remains strip-based until the later atomic
    variant cutover.  Logical rate/shard allocation and physical pose
    generation now happen once; this adapter partitions only machine ordinals
    and projects the selected pose back into the existing :class:`Strip`.
    """
    from flab2bp.layout.strip_variants import (
        default_strip_variant,
        generate_strip_families,
        partition_strip_variant,
        strip_pose_id,
        variant_with_minimum_pitch,
    )

    groups = routing_domain._adapt(spec)
    selected_families = (
        tuple(generate_strip_families(spec)) if families is None else tuple(families)
    )
    templates: dict[StripFamilyId, StripVariant] = {}
    for family in selected_families:
        if not family.variants:
            continue
        template = default_strip_variant(family)
        required_pitch = minimum_pitch_x.get(strip_pose_id(template))
        if required_pitch is not None:
            template = variant_with_minimum_pitch(template, required_pitch)
        templates[family.family_id] = template

    strips: list[routing_domain.Strip] = []
    for family in selected_families:
        by_side_index = sorted(family.input_lanes, key=lambda lane: lane.side_index)
        input_lanes_in_order = tuple(
            lane for lane in by_side_index if lane.side == "south"
        ) + tuple(lane for lane in by_side_index if lane.side == "north")
        inputs_above = tuple(lane.items for lane in by_side_index if lane.side == "south")
        inputs_below = tuple(lane.items for lane in by_side_index if lane.side == "north")
        outputs = tuple(
            (
                lane.items[0],
                routing_domain.DEST_SEP.join(lane.destination_group_keys),
                lane.cargo_domain,
            )
            for lane in sorted(family.output_lanes, key=lambda lane: lane.side_index)
        )
        group = groups[family.group_key]
        # EXPERIMENT: a node arm takes the coater OFF this strip's channel, so
        # the strip stops paying `_COATER_WEST_CHANNEL` for it.  That is the
        # trade the measurement is about: the node buys its own ground back.
        needs_coater_keepout = (not coater_mode().is_node) and any(
            lane.cargo_domain is CargoDomain.REQUIRES_SPRAY for lane in family.input_lanes
        )
        realized: tuple[tuple[int, int, StripVariant | None], ...]
        if family.variants:
            template = templates[family.family_id]
            instances = partition_strip_variant(
                family,
                template,
                max_machine_count=max(1, strip_len),
            )
            realized = tuple(
                (
                    instance.machine_start,
                    instance.machine_count,
                    instance.variant,
                )
                for instance in instances
            )
        else:
            # Compatibility only: a mode-driven building with no sorter poses
            # still reaches emission, which owns the established structured
            # refusal.  It has no physical StripVariant and must not be exposed
            # to projection feedback or sequence search as though it did.
            capped_len = max(1, strip_len)
            if family.machine_cap > 0:
                capped_len = min(capped_len, family.machine_cap)
            instance_count = max(1, math.ceil(family.total_machine_count / capped_len))
            base, extra = divmod(family.total_machine_count, instance_count)
            machine_counts = tuple(
                base + (1 if index < extra else 0) for index in range(instance_count)
            )
            machine_start = 0
            realized_list: list[tuple[int, int, StripVariant | None]] = []
            for machine_count in machine_counts:
                realized_list.append((machine_start, machine_count, None))
                machine_start += machine_count
            realized = tuple(realized_list)
        for machine_start, machine_count, physical_variant in realized:
            # Per lane, because the stack is the LANE's: two input lanes of the
            # same strip can be planned at different stacks, so one call over
            # all of them would have to pick one and be wrong about the other.
            # Same order as `inputs_above + inputs_below`, so which lane a
            # multi-lane failure names does not change.
            for lane in input_lanes_in_order:
                _check_shared_lane_capacity(
                    group,
                    (lane.items,),
                    machine_count,
                    spec,
                    stack=lane.stack,
                )
            lane_plan: LanePlan | None
            attachment_plan: tuple[LaneAttachmentPlan, ...]
            port_dock_plan: tuple[LanePortDockPlan, ...]
            if physical_variant is None:
                footprint_width = group.width
                footprint_height = group.height
                yaw = group.yaw
                building = catalog.building(family.machine_item_id)
                port_inputs = bool(
                    (inputs_above or inputs_below)
                    and building.takes_belt_ports
                    and not building.slot_poses
                )
                # Port-input branches occupy the pitch column immediately east
                # of each machine.  Keep one more column so adjacent machine
                # colliders remain disjoint after spherical projection.
                pitch_width = group.pitch_w + int(family.flank_outputs or port_inputs)
                pitch_height = group.pitch_h
                lane_plan = None
                attachment_plan = ()
                port_dock_plan = ()
                box_height = (
                    len(inputs_above)
                    + int(bool(inputs_above) and port_inputs)
                    + pitch_height
                    + len(outputs)
                    + len(inputs_below)
                )
            else:
                footprint_width = physical_variant.footprint_width
                footprint_height = physical_variant.footprint_height
                yaw = physical_variant.yaw
                pitch_width = physical_variant.pitch_x
                pitch_height = physical_variant.pitch_y
                lane_plan = physical_variant.lane_plan
                attachment_plan = physical_variant.attachment_plan
                port_dock_plan = physical_variant.port_dock_plan
                box_height = physical_variant.box_height
            west_channel = (
                _COATER_WEST_CHANNEL if needs_coater_keepout else routing_domain.WEST_CHANNEL
            )
            selected = routing_domain.Strip(
                group_key=family.group_key,
                recipe_id=family.recipe_id,
                item_id=family.machine_item_id,
                model_index=family.model_index,
                cargo_domain=(
                    CargoDomain.REQUIRES_SPRAY if group.proliferated else CargoDomain.UNSPRAYED
                ),
                machines=machine_count,
                mw=footprint_width,
                mh=footprint_height,
                yaw=yaw,
                pw=pitch_width,
                ph=pitch_height,
                in_above=inputs_above,
                out_lanes=outputs,
                in_below=inputs_below,
                lane_plan=lane_plan,
                attachment_plan=attachment_plan,
                port_dock_plan=port_dock_plan,
                box_height=box_height,
                physical_variant=physical_variant,
                mode_params=family.mode_params,
                flank_outputs=family.flank_outputs,
                drain_outermost=family.drain_outermost,
                family_id=family.family_id,
                machine_start=machine_start,
                west_channel=west_channel,
            )
            strips.append(selected)
    clearance_keys = tuple(routing_domain._staged_static_clearance_keys(strip) for strip in strips)
    unresolved = tuple(
        dict.fromkeys(
            relation
            for relations in clearance_keys
            for relation in relations
            if relation not in minimum_staged_static_clearance
        )
    )
    precleared: frozenset[routing_domain.StagedStaticClearanceKey] = frozenset()
    if unresolved:
        exact_relations = tuple(
            candidate
            for relation in unresolved
            for candidate in (
                relation,
                replace(relation, delta_x=relation.delta_x + 1),
            )
        )
        if cancelled is not None and cancelled():
            raise routing_domain._PreparationDeadline
        token = routing_domain._STAGED_STATIC_PROOF_CANCELLED.set(cancelled)
        try:
            exact_risks = routing_domain._staged_static_relation_projection_risks(
                exact_relations,
                band_policy,
            )
        finally:
            routing_domain._STAGED_STATIC_PROOF_CANCELLED.reset(token)
        precleared = frozenset(
            relation
            for ordinal, relation in enumerate(unresolved)
            if exact_risks[2 * ordinal] and not exact_risks[2 * ordinal + 1]
        )
    planned = [
        replace(
            strip,
            west_channel=max(
                (
                    minimum_staged_static_clearance[relation]
                    if relation in minimum_staged_static_clearance
                    else (
                        _COATER_WEST_CHANNEL + 1 if relation in precleared else _COATER_WEST_CHANNEL
                    )
                    for relation in relations
                ),
                default=strip.west_channel,
            ),
        )
        for strip, relations in zip(strips, clearance_keys, strict=True)
    ]
    return _plan_strip_pilers(spec, groups, planned)


_COARSE_STRIP_THRESHOLD = 40


def _coarsen_saturated_strip_plan(
    spec: BuildSpec,
    strips: list[routing_domain.Strip],
    *,
    strip_len: int,
    band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS,
    families: Sequence[StripFamily] | None = None,
    minimum_staged_static_clearance: Mapping[
        routing_domain.StagedStaticClearanceKey,
        int,
    ] = _NO_STAGED_STATIC_CLEARANCE,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[routing_domain.Strip], int]:
    """Repartition redundant stress strips before packing or routing."""
    if len(strips) < _COARSE_STRIP_THRESHOLD or strip_len >= spec.machine_count:
        return strips, strip_len
    coarse_len = max(strip_len, spec.machine_count)
    return (
        plan_strips(
            spec,
            strip_len=coarse_len,
            band_policy=band_policy,
            minimum_pitch_x=minimum_pitch_x,
            families=families,
            minimum_staged_static_clearance=minimum_staged_static_clearance,
            cancelled=cancelled,
        ),
        coarse_len,
    )


# --- direct insertion ------------------------------------------------------


def _direct_insert_candidates(spec: BuildSpec) -> list[tuple[str, str]]:
    """Producer/consumer recipe pairs a sorter could bridge with no belt.

    Excluded entirely, not merely constrained to zero, when the consumer is
    proliferated: spray is applied on a belt and does not survive crafting, so a
    directly-inserted edge could never be sprayed.  Leaving the variable in with
    a zero bound would let ``-MU_DIRECT`` mislead the search toward placements
    whose apparent reward is unrealisable.
    """
    return _direct_insert_candidates_from_groups(spec, routing_domain._adapt(spec))


def _direct_insert_candidates_from_groups(
    spec: BuildSpec,
    groups: Mapping[str, routing_domain._Group],
) -> list[tuple[str, str]]:
    """Direct-insert eligibility from one already adapted group graph."""
    proliferated = {g.recipe_id for g in groups.values() if g.proliferated}
    producers: dict[str, list[str]] = defaultdict(list)
    for g in groups.values():
        for item in g.outputs:
            producers[item].append(g.recipe_id)

    out: list[tuple[str, str]] = []
    for g in groups.values():
        for item in g.inputs:
            for src in producers.get(item, []):
                if src == g.recipe_id:
                    continue
                if g.recipe_id in proliferated:
                    continue
                if (src, g.recipe_id) in spec.belt_required_edges:
                    continue
                out.append((src, g.recipe_id))
    return sorted(set(out))


@dataclass(frozen=True, slots=True)
class _DirectCandidate:
    """A net a single sorter could replace, and its proved legal alignments.

    ``prod_row`` and ``cons_row`` are offsets from each strip's origin to the
    lane row the sorter would span. ``origin_deltas`` are consumer-minus-
    producer strip-origin x offsets with at least one occupied column that no
    sorter already seated on either lane meets.
    """

    item: str
    cargo_domain: CargoDomain
    prod_row: int
    cons_row: int
    #: Belt tiles each lane occupies, counted east from its strip's west edge.
    #: The sorter needs a column both lanes cover, and an input lane is trimmed
    #: to its last sorter, so the consumer's span is usually SHORTER than its
    #: strip.
    prod_span: int
    cons_span: int
    origin_deltas: tuple[int, ...]


def _direct_clear_columns(
    strip: routing_domain.Strip,
    plan: LaneAttachmentPlan,
    span: int,
) -> frozenset[int]:
    """Occupied lane columns clear of every sorter already seated on the lane.

    A bridge is vertical and a strip sorter leaves that same lane vertically in
    the opposite direction. Their seated colliders can intersect only when they
    share the lane column: sorter bodies are narrower than one tile, while the
    end extension is along their run. Excluding the exact planned attachment
    columns therefore proves the collider precondition before CP-SAT can reward
    the candidate.
    """
    occupied = set(range(span))
    occupied.difference_update(
        machine * strip.pw + attachment.column
        for machine in range(strip.machines)
        for attachment in plan.attachments
    )
    return frozenset(occupied)


def _packed_nonzero_digits(
    packed: Sequence[int],
    coefficient_bytes: int,
    digit_count: int,
) -> bytearray:
    """Mark non-zero fixed-width digits with one linear packed-byte scan."""
    present = bytearray(digit_count)
    for byte_offset, value in enumerate(packed):
        if value:
            present[byte_offset // coefficient_bytes] = 1
    return present


def _direct_column_deltas(
    source_columns: Sequence[int],
    destination_columns: Sequence[int],
) -> tuple[int, ...]:
    """Compose two sorted column sets into their exact difference set.

    The naïve run-pair formulation creates one interval for every source and
    destination run. Alternating occupied/attachment columns make both run
    counts linear in strip width, so that intermediate becomes quadratic even
    though every possible delta lies in one linear-size integer range.

    Treat each column set as a polynomial with a one at every occupied column,
    reverse the destination polynomial, and multiply them. A non-zero
    coefficient proves at least one exact source/destination pair for that
    delta. Coefficients are packed in base ``2 ** (8 * coefficient_bytes)``;
    choosing a base greater than the maximum pair count prevents carries, so
    Python's exact integer multiplication is also an exact convolution.
    """
    if not source_columns or not destination_columns:
        return ()

    source_min = source_columns[0]
    source_max = source_columns[-1]
    destination_min = destination_columns[0]
    destination_max = destination_columns[-1]
    source_degree = source_max - source_min
    destination_degree = destination_max - destination_min
    max_pair_count = min(len(source_columns), len(destination_columns))
    coefficient_bytes = max(1, (max_pair_count.bit_length() + 7) // 8)
    assert max_pair_count < 1 << (8 * coefficient_bytes)

    source_coefficients = bytearray((source_degree + 1) * coefficient_bytes)
    for column in source_columns:
        source_coefficients[(column - source_min) * coefficient_bytes] = 1

    destination_coefficients = bytearray((destination_degree + 1) * coefficient_bytes)
    for column in destination_columns:
        destination_coefficients[(destination_max - column) * coefficient_bytes] = 1

    product_digit_count = source_degree + destination_degree + 1
    product = int.from_bytes(source_coefficients, "little") * int.from_bytes(
        destination_coefficients, "little"
    )
    product_bytes = product.to_bytes(
        product_digit_count * coefficient_bytes,
        "little",
    )
    present = _packed_nonzero_digits(
        product_bytes,
        coefficient_bytes,
        product_digit_count,
    )

    delta_origin = source_min - destination_max
    return tuple(delta_origin + degree for degree, pair_count in enumerate(present) if pair_count)


#: ``(producer geometry, consumer geometry, lane, item)`` -> origin deltas.
#:
#: The sequence-pair annealer asks :func:`_direct_net_candidates` for these once
#: per state, for every net (45k calls on ``gravity-matrix``*200), while a move
#: changes one or two strips -- so nearly every ask repeats an earlier one, and
#: the answer depends on nothing but the two strips' geometry.  Bounded so a
#: long audit worker cannot grow it without limit; clearing on overflow costs
#: recomputation and keeps the answer exact.
_DIRECT_ORIGIN_DELTAS_MEMO: dict[tuple[object, ...], tuple[int, ...]] = {}
_DIRECT_ORIGIN_DELTAS_MEMO_LIMIT = 65536


#: The ``Strip`` fields :func:`_direct_geometry_key` puts in the memo key, and
#: the ones it deliberately leaves out.  Together they must PARTITION
#: ``dataclasses.fields(Strip)``, which
#: ``test_direct_geometry_key_classifies_every_strip_field`` enforces: a new
#: field is a test failure until somebody decides which side it belongs on.
#: That is the guard on the memo's whole correctness argument -- the key is
#: exact only while it is the read set, and a helper that starts reading, say,
#: ``west_channel`` would otherwise serve wrong cached answers in silence.
_DIRECT_GEOMETRY_KEY_FIELDS: frozenset[str] = frozenset(
    {
        "machines",
        "pw",
        "ph",
        "item_id",
        "yaw",
        "cargo_domain",
        "in_above",
        "in_below",
        "out_lanes",
        "pilers",
        "lane_plan",
        "attachment_plan",
        "flank_outputs",
    }
)
_UNREAD_BY_DIRECT_GEOMETRY: frozenset[str] = frozenset(
    {
        "group_key",
        "recipe_id",
        "model_index",
        "mw",
        "mh",
        # `drain_outermost` moves rows only on a FLANKED strip, and a flanked
        # strip has no `physical_variant`, so `_direct_geometry_key` returns
        # `None` for it and no two strips this memo keys can disagree about it.
        "drain_outermost",
        "box_height",
        "physical_variant",
        "port_dock_plan",
        "mode_params",
        "family_id",
        "machine_start",
        "west_channel",
        "tail_extension",
    }
)


def _direct_geometry_key(strip: routing_domain.Strip) -> tuple[object, ...] | None:
    """Everything :func:`_direct_origin_deltas` reads off one strip.

    THE FIELDS ARE THE READ SET, not the strip: two strips agreeing on all of
    them cannot disagree about the deltas, and a field left out here is a wrong
    cached answer.  Taken from ``_output_attachment_plan``, ``lane_of_input``,
    ``_input_attachment_plan``, ``input_lane_tiles`` and
    :func:`_direct_clear_columns`, plus the ``width`` this function passes:

    * ``machines``, ``pw`` -- ``width``, the per-machine column stride in
      :func:`_direct_clear_columns`, and ``input_lane_tiles``' last tap.
    * ``ph`` -- ``band_rows``, hence ``first_row_below_band``.
    * ``item_id``, ``yaw`` -- the probed building, its slot poses, its belt
      docks, and ``takes_belt_ports``.
    * ``cargo_domain`` -- the logical lane a flank-output plan synthesizes.
    * ``in_above``, ``in_below`` -- ``lane_of_input``, the lane's side and
      index, ``column_offset``, and ``machine_row``.
    * ``out_lanes`` -- the south side's lane index, via ``column_offset``.
    * ``pilers`` -- whether the selected output lane has a piler and its exact
      serial count, which fixes the emitted tail column.
    * ``lane_plan`` -- ``machine_row``.
    * ``attachment_plan`` -- both attachment-plan lookups.
    * ``flank_outputs`` -- the synthesized-plan branch, ``machine_row``, and
      ``column_offset``.

    Deliberately absent because nothing here reads them: ``group_key``,
    ``recipe_id`` (error text only), ``model_index``, ``mw``, ``mh``,
    ``box_height``, ``physical_variant`` (the gate below, but never read -- the
    lane and attachment plans it produced are carried on the strip and are in
    the key already), ``port_dock_plan`` (``input_lane_tiles`` probes the
    building's docks, not the strip's plan), ``mode_params``, ``family_id``,
    ``machine_start``, ``west_channel`` and ``tail_extension``.
    Every field kept is hashable -- strings, ints, floats, an enum, and frozen
    dataclasses of those.

    ``None`` means "do not memo": a strip without a realized pose belongs to a
    compatibility family, and those are rare enough not to be worth a key.

    The two lists above are :data:`_DIRECT_GEOMETRY_KEY_FIELDS` and
    :data:`_UNREAD_BY_DIRECT_GEOMETRY`; they partition ``Strip``'s fields and a
    test says so, so a field added to ``Strip`` cannot slip past this decision.
    The literal below is read back by that test rather than driven from the
    constant, because the annealer builds this key 130k times a run and a
    ``getattr`` loop is slower than the attribute loads.
    """
    if strip.physical_variant is None:
        return None
    return (
        strip.machines,
        strip.pw,
        strip.ph,
        strip.item_id,
        strip.yaw,
        strip.cargo_domain,
        strip.in_above,
        strip.in_below,
        strip.out_lanes,
        strip.pilers,
        strip.lane_plan,
        strip.attachment_plan,
        strip.flank_outputs,
    )


def _direct_origin_deltas(
    source: routing_domain.Strip,
    destination: routing_domain.Strip,
    source_lane: int,
    item: str,
    *,
    source_rate: Fraction,
    required_rate: Fraction,
) -> tuple[int, ...]:
    """Memoize occupied, sorter-clear direct origin offsets.

    Memoized on :func:`_direct_geometry_key` because the annealer re-asks the
    same question for every unmoved strip pair in every state.  An empty answer
    is cached too -- it is the common one, and recomputing it costs the same
    three attachment-plan scans as a non-empty one.
    """
    source_key = _direct_geometry_key(source)
    destination_key = _direct_geometry_key(destination)
    memo_key: tuple[object, ...] | None = (
        None
        if source_key is None or destination_key is None
        else (
            source_key,
            destination_key,
            source_lane,
            item,
            source_rate,
            required_rate,
        )
    )
    if memo_key is not None:
        cached = _DIRECT_ORIGIN_DELTAS_MEMO.get(memo_key)
        if cached is not None:
            return cached

    deltas = _direct_origin_deltas_uncached(
        source,
        destination,
        source_lane,
        item,
        source_rate=source_rate,
        required_rate=required_rate,
    )

    if memo_key is not None:
        if len(_DIRECT_ORIGIN_DELTAS_MEMO) >= _DIRECT_ORIGIN_DELTAS_MEMO_LIMIT:
            _DIRECT_ORIGIN_DELTAS_MEMO.clear()
        _DIRECT_ORIGIN_DELTAS_MEMO[memo_key] = deltas
    return deltas


def _direct_origin_deltas_uncached(
    source: routing_domain.Strip,
    destination: routing_domain.Strip,
    source_lane: int,
    item: str,
    *,
    source_rate: Fraction,
    required_rate: Fraction,
) -> tuple[int, ...]:
    """Consumer offsets with a collision-clear, directionally safe column.

    The bridge replaces this destination strip's whole net, so it must land
    before every destination pickup.  On the source side it needs only enough
    upstream producers to cover that exact demand: later injections are
    surplus for this net and remain on the source lane for its other consumers.
    Both rates stay exact :class:`Fraction` values.
    """
    try:
        source_plan = source._output_attachment_plan(source_lane)
        destination_plan = destination._input_attachment_plan(item)
    except IndexError, KeyError:
        return ()
    if source_rate <= 0 or required_rate <= 0 or not source_plan.attachments:
        return ()
    source_machines_needed = math.ceil(required_rate / source_rate)
    if source_machines_needed > source.machines:
        return ()
    last_source_injection = (source_machines_needed - 1) * source.pw + source_plan.attachments[
        0
    ].column
    first_destination_pickup = min(
        machine * destination.pw + attachment.column
        for machine in range(destination.machines)
        for attachment in destination_plan.attachments
    )
    piled_tail_column = routing_domain._piled_output_tail_column(source, source_lane)
    source_columns: tuple[int, ...]
    if piled_tail_column is not None:
        # Emission replaces the original lane with one belt after the piler.
        source_columns = (piled_tail_column,)
    else:
        source_columns = tuple(
            column
            for column in _direct_clear_columns(source, source_plan, source.width)
            if column > last_source_injection
        )
    destination_span = destination.input_lane_tiles(destination.lane_of_input(item))
    destination_columns = sorted(
        column
        for column in _direct_clear_columns(
            destination,
            destination_plan,
            destination_span,
        )
        if column < first_destination_pickup
    )
    if not source_columns or not destination_columns:
        return ()

    return _direct_column_deltas(source_columns, destination_columns)


#: The ``Strip`` fields :func:`_direct_candidate_key` puts in the pair memo key,
#: and the ones it deliberately leaves out.  Together they must PARTITION
#: ``dataclasses.fields(Strip)``, which
#: ``test_direct_candidate_key_classifies_every_strip_field`` enforces, for the
#: same reason as :data:`_DIRECT_GEOMETRY_KEY_FIELDS`: the key is exact only
#: while it IS the read set of :func:`_direct_net_candidate_uncached`, and a
#: field that quietly joins that read set without joining the key would hand one
#: strip pair another pair's candidate in silence.
#:
#: It is a strict SUPERSET of the geometry key.  Enumeration asks three
#: questions ``_direct_origin_deltas`` never asks: ``recipe_id`` for the
#: eligibility lookup, ``group_key`` for the destination match and the two rate
#: lookups, and ``port_dock_plan`` for ``row_of_output``'s planned-dock branch.
#: ``physical_variant`` is read by :func:`_direct_geometry_key` itself as the
#: "do not memo" gate, so it is classified here as read rather than unread.
_DIRECT_CANDIDATE_KEY_FIELDS: frozenset[str] = _DIRECT_GEOMETRY_KEY_FIELDS | frozenset(
    {
        "group_key",
        "recipe_id",
        "port_dock_plan",
        "physical_variant",
    }
)
_UNREAD_BY_DIRECT_CANDIDATE: frozenset[str] = frozenset(
    {
        "model_index",
        "mw",
        "mh",
        # Same argument as in :data:`_UNREAD_BY_DIRECT_GEOMETRY`: the pair key
        # inherits that key's `None` gate, so a flanked strip -- the only kind
        # whose drain row can move -- never reaches this memo.
        "drain_outermost",
        "box_height",
        "mode_params",
        "family_id",
        "machine_start",
        "west_channel",
        "tail_extension",
    }
)

#: One entry per DISTINCT strip pair, not per selection, so the bound is the
#: number of distinct endpoint geometries a run projects.  Bounded and cleared
#: on overflow like :data:`_DIRECT_ALIGNMENT_MEMO_LIMIT`: clearing costs
#: recomputation and stays exact.
_DIRECT_CANDIDATE_MEMO_LIMIT = 16384

#: ``(source geometry key, source group/recipe/variant/dock plan, then the same
#: for the destination)`` -- everything :func:`_direct_net_candidate_uncached`
#: reads off its two endpoints.
type _DirectCandidatePairKey = tuple[object, ...]


@dataclass(slots=True)
class DirectCandidateMemo:
    """Run-scoped memo for :func:`_direct_net_candidates`.

    Two halves, both keyed by what the enumeration actually reads:

    * the adapted spec.  ``_adapt`` plus ``_direct_insert_candidates_from_groups``
      is a pure function of ``spec`` and cost a third of this function's time
      when it ran once per call, so it is held here and reused while the SAME
      spec object comes back.  Identity, not equality: the memo holds the spec
      it adapted, so the object cannot be collected and its identity reused.
    * one entry per strip pair.  ``_variant_direct_eligibility`` moves one
      producer and one consumer variant at a time, so every net between the
      other unmoved strips re-asks a question already answered.

    A different spec means different groups and a different eligible set, which
    invalidates every pair entry -- ``adapt`` clears them rather than trying to
    namespace the key by a spec it would then have to hash.
    """

    spec: BuildSpec | None = None
    groups: dict[str, routing_domain._Group] = field(default_factory=dict)
    eligible: frozenset[tuple[str, str]] = frozenset()
    pairs: dict[_DirectCandidatePairKey, _DirectCandidate | None] = field(default_factory=dict)

    def adapt(
        self, spec: BuildSpec
    ) -> tuple[dict[str, routing_domain._Group], frozenset[tuple[str, str]]]:
        """The adapted group graph and eligible recipe edges for ``spec``."""
        if self.spec is not spec:
            groups = routing_domain._adapt(spec)
            eligible = frozenset(_direct_insert_candidates_from_groups(spec, groups))
            self.pairs.clear()
            self.spec = spec
            self.groups = groups
            self.eligible = eligible
        return self.groups, self.eligible


def _direct_candidate_key(
    source: routing_domain.Strip,
    destination: routing_domain.Strip,
) -> _DirectCandidatePairKey | None:
    """Everything :func:`_direct_net_candidate_uncached` reads off one pair.

    THE FIELDS ARE THE READ SET, not the strips: two pairs agreeing on all of
    them cannot disagree about the candidate, and a field left out here is a
    wrong cached answer.  :func:`_direct_geometry_key` already certifies the
    geometry half -- it is the read set of ``_direct_origin_deltas``, which in
    turn covers ``input_lane_tiles``, ``lane_of_input`` and
    ``_piled_output_tail_column``.  The four fields added on top are the ones
    enumeration reads and the deltas never do; see
    :data:`_DIRECT_CANDIDATE_KEY_FIELDS`.

    ``None`` means "do not memo", inherited from the geometry key: a strip with
    no realized pose belongs to a compatibility family and is rare enough not to
    be worth an entry.  ``physical_variant`` therefore enters the key through
    that gate as well as on its own.
    """
    source_key = _direct_geometry_key(source)
    if source_key is None:
        return None
    destination_key = _direct_geometry_key(destination)
    if destination_key is None:
        return None
    return (
        source_key,
        source.group_key,
        source.recipe_id,
        source.physical_variant,
        source.port_dock_plan,
        destination_key,
        destination.group_key,
        destination.recipe_id,
        destination.physical_variant,
        destination.port_dock_plan,
    )


def _direct_net_candidate_uncached(
    source: routing_domain.Strip,
    destination: routing_domain.Strip,
    groups: Mapping[str, routing_domain._Group],
    eligible: frozenset[tuple[str, str]],
) -> _DirectCandidate | None:
    """The lane rows a bridging sorter would connect for ONE strip pair.

    ``None`` is a real answer, not a failure: most nets are not direct-insert
    candidates, and the memo caches that verdict like any other.
    """
    if source.takes_belt_ports or (source.recipe_id, destination.recipe_id) not in eligible:
        return None
    lane = next(
        (
            (k, item)
            for k, (item, dest, cargo_domain) in enumerate(source.out_lanes)
            if cargo_domain is CargoDomain.UNSPRAYED
            and destination.group_key in routing_domain._dests(dest)
        ),
        None,
    )
    if lane is None:
        return None
    k, item = lane
    if item not in destination.in_lanes:
        return None
    # Ask the strip for the rows rather than recomputing the layout here:
    # inputs may sit above or below the machine band, and duplicating that
    # arithmetic is how the two drift apart.
    source_rate = groups[source.group_key].outputs.get(item, Fraction(0))
    required_rate = destination.machines * groups[destination.group_key].inputs.get(
        item,
        Fraction(0),
    )
    origin_deltas = _direct_origin_deltas(
        source,
        destination,
        k,
        item,
        source_rate=source_rate,
        required_rate=required_rate,
    )
    if not origin_deltas:
        # With no occupied lane column clear of both strips' already seated
        # sorters, emission cannot prove a bridge. Do not create a Boolean:
        # an absent variable cannot earn the direct-insert reward.
        return None
    piled_tail_column = routing_domain._piled_output_tail_column(source, k)
    return _DirectCandidate(
        item=item,
        prod_row=source.row_of_output(k),
        cons_row=destination.row_of_input(item),
        prod_span=(piled_tail_column + 1 if piled_tail_column is not None else source.width),
        cons_span=destination.input_lane_tiles(destination.lane_of_input(item)),
        cargo_domain=CargoDomain.UNSPRAYED,
        origin_deltas=origin_deltas,
    )


def _direct_net_candidates(
    strips: list[routing_domain.Strip],
    spec: BuildSpec,
    *,
    memo: DirectCandidateMemo | None = None,
) -> dict[tuple[int, int], _DirectCandidate]:
    """Map eligible nets to the lane rows a bridging sorter would connect.

    Works at *strip* granularity because that is what the packer places, while
    :func:`_direct_insert_candidates` works at recipe granularity -- one recipe
    can be split across several strips, and each of those nets is separately
    eligible.

    ``memo`` optionally shares the adapted spec and the per-pair verdicts across
    callers that re-enumerate the SAME endpoint geometry.  It must stay
    RUN-SCOPED: every entry is a pure function of its key, but the dict would
    otherwise outlive the plan whose strips it describes for no benefit.
    Omitted, the walk below is exactly the one this function has always done.
    """
    if memo is None:
        groups: Mapping[str, routing_domain._Group] = routing_domain._adapt(spec)
        eligible = frozenset(_direct_insert_candidates_from_groups(spec, groups))
        pairs: dict[_DirectCandidatePairKey, _DirectCandidate | None] | None = None
    else:
        groups, eligible = memo.adapt(spec)
        pairs = memo.pairs
    if not eligible:
        return {}

    out: dict[tuple[int, int], _DirectCandidate] = {}
    for i, j in _nets_between(strips):
        source, destination = strips[i], strips[j]
        key = None if pairs is None else _direct_candidate_key(source, destination)
        if key is not None and pairs is not None and key in pairs:
            candidate = pairs[key]
        else:
            candidate = _direct_net_candidate_uncached(source, destination, groups, eligible)
            if key is not None and pairs is not None:
                if len(pairs) >= _DIRECT_CANDIDATE_MEMO_LIMIT:
                    pairs.clear()
                pairs[key] = candidate
        if candidate is not None:
            out[i, j] = candidate
    return out


@dataclass(frozen=True, slots=True, eq=False)
class _DirectCandidateSnapshot:
    """Immutable direct-net geometry owned by one exact strip plan."""

    strips: tuple[routing_domain.Strip, ...]
    candidates: Mapping[tuple[int, int], _DirectCandidate]

    def __post_init__(self) -> None:
        if not isinstance(self.strips, tuple):
            raise ValueError("direct candidates must retain an immutable strip plan")
        object.__setattr__(
            self,
            "candidates",
            MappingProxyType(dict(self.candidates)),
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _DirectCandidateSnapshot)
            and self.matches(other.strips)
            and self.candidates == other.candidates
        )

    def __hash__(self) -> int:
        return hash(
            (
                tuple(id(strip) for strip in self.strips),
                tuple(sorted(self.candidates.items())),
            )
        )

    def matches(self, strips: Sequence[routing_domain.Strip]) -> bool:
        """Whether ``strips`` contains the exact physical port owners retained."""
        return len(self.strips) == len(strips) and all(
            retained is current for retained, current in zip(self.strips, strips, strict=True)
        )


def _direct_candidate_snapshot(
    strips: list[routing_domain.Strip],
    spec: BuildSpec,
    *,
    enabled: bool,
) -> _DirectCandidateSnapshot:
    """Enumerate direct candidates once and bind them to their physical plan."""
    return _DirectCandidateSnapshot(
        tuple(strips),
        _direct_net_candidates(strips, spec) if enabled else {},
    )


#: The ``_DirectCandidate`` fields :func:`_direct_alignment_key` puts in the
#: memo key, and the ones it deliberately leaves out.  Together they must
#: PARTITION ``dataclasses.fields(_DirectCandidate)``, which
#: ``test_direct_alignment_key_classifies_every_candidate_field`` enforces, for
#: the same reason as :data:`_DIRECT_GEOMETRY_KEY_FIELDS`: the key is exact only
#: while it IS the read set, and a candidate field that quietly joins the read
#: set without joining the key would serve another pair's targets in silence.
_DIRECT_ALIGNMENT_KEY_FIELDS: frozenset[str] = frozenset(
    {
        "prod_row",
        "cons_row",
        "prod_span",
        "cons_span",
        "origin_deltas",
    }
)
_UNREAD_BY_DIRECT_ALIGNMENT: frozenset[str] = frozenset(
    {
        "item",
        "cargo_domain",
    }
)

#: One memo entry per DISTINCT candidate mapping, not per variant pair, so the
#: bound is the number of distinct direct geometries a run projects rather than
#: the number of selections it tries.  Bounded and cleared on overflow like
#: :data:`_SELECTED_STRIP_MEMO_LIMIT` in ``sequence_solver``: clearing costs
#: recomputation and stays exact.
_DIRECT_ALIGNMENT_MEMO_LIMIT = 16384

#: ``(net endpoints, prod_row, cons_row, prod_span, cons_span, origin_deltas)``
#: for every candidate, in sorted key order.
type _DirectAlignmentKey = tuple[tuple[tuple[int, int], int, int, int, int, tuple[int, ...]], ...]
type DirectAlignmentMemo = dict[_DirectAlignmentKey, tuple[DirectInsertTarget, ...]]


def _direct_alignment_key(
    candidates: Mapping[tuple[int, int], _DirectCandidate],
) -> _DirectAlignmentKey:
    """Everything :func:`_direct_alignment_targets_uncached` reads off the map.

    THE FIELDS ARE THE READ SET: two candidate mappings agreeing on the net
    endpoints and on these five fields cannot disagree about the emitted
    ``DirectInsertTarget``s, because those are the only values the constructor
    is handed.  ``item`` and ``cargo_domain`` are deliberately absent -- they
    select WHICH nets became candidates, upstream in
    :func:`_direct_net_candidates`, but no target field is derived from them.
    The partition is declared in :data:`_DIRECT_ALIGNMENT_KEY_FIELDS` /
    :data:`_UNREAD_BY_DIRECT_ALIGNMENT` and a test says so, so a field added to
    ``_DirectCandidate`` cannot slip past this decision.
    """
    return tuple(
        (
            key,
            candidate.prod_row,
            candidate.cons_row,
            candidate.prod_span,
            candidate.cons_span,
            candidate.origin_deltas,
        )
        for key, candidate in sorted(candidates.items())
    )


def _direct_alignment_targets_uncached(
    candidates: Mapping[tuple[int, int], _DirectCandidate],
) -> tuple[DirectInsertTarget, ...]:
    """Expose candidate lane geometry as immutable placement-alignment inputs."""
    return tuple(
        DirectInsertTarget(
            key=key,
            producer=key[0],
            consumer=key[1],
            producer_row=candidate.prod_row,
            consumer_row=candidate.cons_row,
            producer_span=candidate.prod_span,
            consumer_span=candidate.cons_span,
            origin_deltas=candidate.origin_deltas,
        )
        for key, candidate in sorted(candidates.items())
    )


def _direct_alignment_targets(
    candidates: Mapping[tuple[int, int], _DirectCandidate],
    *,
    memo: DirectAlignmentMemo | None = None,
) -> tuple[DirectInsertTarget, ...]:
    """Expose candidate lane geometry as immutable placement-alignment inputs.

    ``memo`` optionally shares the built tuple across callers that re-enumerate
    the SAME geometry -- ``_variant_direct_eligibility`` re-selects every
    unmoved strip for each producer/consumer variant pair, so all but the two
    moved endpoints project the identical candidate mapping every time.  The
    memo must stay RUN-SCOPED: the targets it holds are pure functions of the
    key, but the dict would otherwise outlive the plan whose geometry it
    describes for no benefit.
    """
    if memo is None:
        return _direct_alignment_targets_uncached(candidates)
    key = _direct_alignment_key(candidates)
    targets = memo.get(key)
    if targets is None:
        targets = _direct_alignment_targets_uncached(candidates)
        if len(memo) >= _DIRECT_ALIGNMENT_MEMO_LIMIT:
            memo.clear()
        memo[key] = targets
    return targets


def tie_break_cap(n_terms: int, *, width_bound: int, height: int, n_direct: int) -> int:
    """Weight that makes width outrank every tie-break term put together.

    The objective is lexicographic on purpose: width first, then wirelength and
    direct-insert reward as tie-breaks among equal-width packings.  Blending them
    is what once made *more* solver time produce *worse* area, because the
    blended proxy was anti-correlated with the metric actually reported.

    The cap must therefore exceed the largest value the whole tie-break tier can
    take, and it has to grow when the direct-insert reward joins that tier --
    otherwise direct inserts could buy width, quietly reinstating the blend.
    """
    return n_terms * (width_bound + height) + MU_DIRECT * n_direct + 1


@dataclass(frozen=True, slots=True)
class _ExactRetryKey:
    """One proof-scoped retry token for a configured pack candidate."""

    height: int
    arrangement: int
    evidence: routing_domain._ExactRetryEvidence


@dataclass(frozen=True, slots=True)
class ExactProjectionPair:
    """The two physical strips implicated by one exact projection refusal."""

    left_strip: int
    right_strip: int
    left_geometry: finalize.ProjectionGeometrySignature
    right_geometry: finalize.ProjectionGeometrySignature

    def __post_init__(self) -> None:
        if self.left_strip < 0 or self.left_strip >= self.right_strip:
            raise ValueError("exact projection pair requires two ordered strips")
        if not self.left_geometry or not self.right_geometry:
            raise ValueError("exact projection pair requires physical signatures")


@dataclass(frozen=True, slots=True)
class ExactPackNoGood:
    """One immutable full packed assignment rejected by exact evidence."""

    height: int
    outline: tuple[tuple[int, int], ...]
    width: int
    origins: tuple[tuple[int, int], ...]
    evidence: tuple[finalize.ProjectionFailure, ...]
    projection_pair: ExactProjectionPair | None = None

    def __post_init__(self) -> None:
        if self.height <= 0 or self.width <= 0:
            raise ValueError("exact pack dimensions must be positive")
        if len(self.outline) != len(self.origins):
            raise ValueError("exact pack outline and origins must cover every strip")
        if not self.evidence:
            raise ValueError("exact pack no-good requires structured evidence")


@dataclass(slots=True)
class _ExactPackNoGoodState:
    """Deduplicated exact cuts plus the bounded retry tokens they justified."""

    no_goods: list[ExactPackNoGood] = field(default_factory=list)
    no_good_keys: set[ExactPackNoGood] = field(default_factory=set)
    retry_keys: set[_ExactRetryKey] = field(default_factory=set)
    retried_candidates: set[tuple[int, int]] = field(default_factory=set)

    def remember(self, no_good: ExactPackNoGood) -> bool:
        if no_good in self.no_good_keys:
            return False
        self.no_good_keys.add(no_good)
        self.no_goods.append(no_good)
        return True

    def admit_retry(
        self,
        key: _ExactRetryKey,
        no_good: ExactPackNoGood,
        *,
        affordable: bool,
    ) -> bool:
        candidate = (key.height, key.arrangement)
        if (
            not affordable
            or candidate in self.retried_candidates
            or key in self.retry_keys
            or no_good in self.no_good_keys
        ):
            return False
        self.retried_candidates.add(candidate)
        self.retry_keys.add(key)
        self.no_good_keys.add(no_good)
        self.no_goods.append(no_good)
        return True


@dataclass(frozen=True, slots=True)
class _DirectRelationNoGood:
    """One proved-impossible direct promise at one endpoint relation."""

    direct_id: routing_domain.DirectInsertId
    delta_x: int
    delta_y: int


def _strip_geometry_signature(
    strip: routing_domain.Strip,
) -> finalize.ProjectionGeometrySignature:
    """Return every immutable strip field that determines physical emission."""
    return (
        strip.item_id,
        strip.model_index,
        strip.cargo_domain,
        strip.machines,
        strip.mw,
        strip.mh,
        strip.yaw,
        strip.pw,
        strip.ph,
        strip.in_above,
        strip.out_lanes,
        strip.in_below,
        strip.lane_plan,
        strip.attachment_plan,
        strip.box_height,
        (strip.physical_variant.variant_id if strip.physical_variant is not None else None),
        strip.port_dock_plan,
        strip.mode_params,
        strip.flank_outputs,
        strip.family_id,
        strip.machine_start,
        strip.west_channel,
        strip.tail_extension,
        strip.pilers,
    )


def _projection_strip_pair(
    placement: Placement,
    failure: finalize.ProjectionFailure,
) -> tuple[int, int] | None:
    """Map exact static evidence to two distinct physical strip owners."""
    if failure.check != "geom.collide" or len(failure.buildings) != 2:
        return None
    left_building, right_building = failure.buildings
    if not 0 <= left_building < len(placement.buildings) or not 0 <= right_building < len(
        placement.buildings
    ):
        return None
    left_strip = placement.buildings[left_building].owner_strip
    right_strip = placement.buildings[right_building].owner_strip
    if type(left_strip) is not int or type(right_strip) is not int or left_strip == right_strip:
        return None
    return (left_strip, right_strip) if left_strip < right_strip else (right_strip, left_strip)


def _exact_projection_pair(
    strips: Sequence[routing_domain.Strip],
    strip_pair: tuple[int, int],
) -> ExactProjectionPair | None:
    """Retain an implicated pair only when both physical strips still exist."""
    left_strip, right_strip = strip_pair
    if not 0 <= left_strip < right_strip < len(strips):
        return None
    return ExactProjectionPair(
        left_strip=left_strip,
        right_strip=right_strip,
        left_geometry=_strip_geometry_signature(strips[left_strip]),
        right_geometry=_strip_geometry_signature(strips[right_strip]),
    )


def _projection_no_good(
    placement: Placement,
    pack: routing_domain._Pack,
    strips: Sequence[routing_domain.Strip],
    failure: finalize.ProjectionFailure,
    policy: BandPolicy,
) -> ProjectionNoGood | None:
    """Map a pair-local universal static collision to two packed strips."""
    strip_pair = _projection_strip_pair(placement, failure)
    if strip_pair is None:
        return None
    left_strip, right_strip = strip_pair
    if (
        left_strip not in pack.at
        or right_strip not in pack.at
        or not 0 <= left_strip < len(strips)
        or not 0 <= right_strip < len(strips)
    ):
        return None
    left_building, right_building = failure.buildings
    proved = finalize.independent_projection_pair(
        (
            (left_building, placement.buildings[left_building]),
            (right_building, placement.buildings[right_building]),
        ),
        policy,
    )
    if proved is None:
        return None
    left_x, left_y = pack.at[left_strip]
    right_x, right_y = pack.at[right_strip]
    return ProjectionNoGood(
        left_strip=left_strip,
        right_strip=right_strip,
        delta_x=left_x - right_x,
        delta_y=left_y - right_y,
        pack_width=pack.width,
        pack_height=pack.height,
        left_origin=(left_x, left_y),
        right_origin=(right_x, right_y),
        left_geometry=_strip_geometry_signature(strips[left_strip]),
        right_geometry=_strip_geometry_signature(strips[right_strip]),
        failure=failure,
    )


def _projection_pitch_requirements(
    placement: Placement,
    strips: list[routing_domain.Strip],
    failures: tuple[finalize.ProjectionFailure, ...],
) -> tuple[ProjectionPitchRequirement | None, ...]:
    """Map ordered Freeform failures through one realized-strip placement index."""
    from flab2bp.layout.strip_variants import (
        StripInstanceId,
        projection_pitch_requirements,
    )

    instance_ids: list[StripInstanceId] = []
    variants: list[StripVariant] = []
    for strip in strips:
        if strip.family_id is None or strip.physical_variant is None:
            return (None,) * len(failures)
        instance_ids.append(
            StripInstanceId(
                strip.family_id,
                strip.machine_start,
                strip.machines,
            )
        )
        variants.append(strip.physical_variant)
    return projection_pitch_requirements(
        placement,
        instance_ids=tuple(instance_ids),
        variants=tuple(variants),
        failures=failures,
    )


def _nets_between(strips: list[routing_domain.Strip]) -> list[tuple[int, int]]:
    """Strip index pairs that will need a belt route.

    The pairs come off ``out_lanes`` -> destination group key.
    """
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(strips):
        by_group[s.group_key].append(i)
    nets: set[tuple[int, int]] = set()
    for i, strip in enumerate(strips):
        for _item, destination, _cargo_domain in strip.out_lanes:
            for group_key in routing_domain._dests(destination):
                for j in by_group.get(group_key, []):
                    if i != j:
                        nets.add((i, j))
    return sorted(nets)


def _greedy_pack(
    strips: list[routing_domain.Strip],
    height: int,
    *,
    route_clearance: int = 0,
) -> routing_domain._Pack:
    """Shelf packing with optional expendable routing cells between strip boxes.

    It is the deterministic safety candidate and the exact packer's upper bound.
    The solver remains free to compact requested clearance, but a short search
    can retain this seed instead of making an honest refusal from a tighter pack
    whose port corridors have no turning cell.
    """
    at: dict[int, tuple[int, int]] = {}
    shelf_x, shelf_y, shelf_h = 0, 0, 0
    width = 0
    for i, s in enumerate(strips):
        packed_width, packed_height = _box(s)
        w = packed_width + route_clearance
        h = packed_height + route_clearance
        if shelf_y + h > height and shelf_h:
            shelf_x, shelf_y, shelf_h = width, 0, 0
        # `at` is the CONTENT origin, so the west channel is stepped over here
        # and every consumer of a pack goes on meaning the same thing by it.
        at[i] = (shelf_x + s.west_channel, shelf_y)
        shelf_y += h
        shelf_h = max(shelf_h, w)
        width = max(width, shelf_x + w)
    return routing_domain._Pack(at=at, width=width, height=height, status="greedy")


def _realized_pack_outline(
    strips: Sequence[routing_domain.Strip],
    pack: routing_domain._Pack,
) -> tuple[int, int]:
    """Return occupied strip-box extent, excluding expendable seed clearance."""
    boxes = tuple(
        (
            pack.at[index][0] - strip.west_channel,
            pack.at[index][1],
            *_box(strip),
        )
        for index, strip in enumerate(strips)
    )
    left = min(x for x, _y, _width, _height in boxes)
    bottom = min(y for _x, y, _width, _height in boxes)
    right = max(x + width for x, _y, width, _height in boxes)
    top = max(y + height for _x, y, _width, height in boxes)
    return right - left, top - bottom


def _routing_seed_clearance(
    strips: Sequence[routing_domain.Strip],
    *,
    sprayed_lanes: int,
) -> int:
    """Return the shared freeform/sequence safety gap for this strip plan."""
    return (
        _GREEDY_ROUTE_CLEARANCE
        if sprayed_lanes == 0 and len(strips) >= _DETERMINISTIC_PACK_STRIPS
        else 0
    )


def _add_exact_pack_no_good(
    model: cp_model.CpModel,
    width: cp_model.IntVar,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[routing_domain.Strip],
    no_good: ExactPackNoGood,
) -> None:
    """Forbid the one complete assignment named by ``no_good``."""
    if len(no_good.origins) != len(strips):
        raise ValueError("exact pack no-good must retain every strip origin")
    variables = [width]
    values = [no_good.width]
    for strip_index, origin in enumerate(no_good.origins):
        variables.extend((xs[strip_index], ys[strip_index]))
        values.extend(
            (
                origin[0] - strips[strip_index].west_channel,
                origin[1],
            )
        )
    model.add_forbidden_assignments(variables, [tuple(values)])


def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[routing_domain.Strip],
    height: int,
    width_bound: int,
    index: int,
    no_good: ClusterRelationNoGood,
) -> None:
    """Forbid one RELATIVE placement: at least one cluster strip must move.

    Unlike :func:`_add_exact_pack_no_good`, which removes a single point, this
    removes every translation of the proved relation -- which is exactly what
    the proof supports, because the CBS run behind it removed every other belt
    and so said nothing about where the cluster sits, only how its strips sit
    relative to one another.
    """
    anchor = no_good.strips[0]
    if any(strip >= len(strips) for strip in no_good.strips):
        return
    variables: list[cp_model.IntVar] = []
    values: list[int] = []
    for position, strip_index in enumerate(no_good.strips[1:], start=1):
        relation_x = model.new_int_var(
            -width_bound,
            width_bound,
            f"cluster_ng{index}_dx{position}",
        )
        relation_y = model.new_int_var(-height, height, f"cluster_ng{index}_dy{position}")
        model.add(
            relation_x
            == (xs[strip_index] + strips[strip_index].west_channel)
            - (xs[anchor] + strips[anchor].west_channel)
        )
        model.add(relation_y == ys[strip_index] - ys[anchor])
        variables.extend((relation_x, relation_y))
        values.extend(no_good.deltas[position])
    model.add_forbidden_assignments(variables, [tuple(values)])


def _add_projection_no_good(
    model: cp_model.CpModel,
    width: cp_model.IntVar,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[routing_domain.Strip],
    no_good: ProjectionNoGood,
) -> None:
    """Forbid one proved pair while preserving unrelated-strip freedom."""
    left = no_good.left_strip
    right = no_good.right_strip
    if (
        _strip_geometry_signature(strips[left]) != no_good.left_geometry
        or _strip_geometry_signature(strips[right]) != no_good.right_geometry
    ):
        return
    variables = [width, xs[left], ys[left], xs[right], ys[right]]
    values = [
        no_good.pack_width,
        no_good.left_origin[0] - strips[left].west_channel,
        no_good.left_origin[1],
        no_good.right_origin[0] - strips[right].west_channel,
        no_good.right_origin[1],
    ]
    model.add_forbidden_assignments(variables, [values])


@dataclass(frozen=True, slots=True)
class _FeedbackObjectiveEvidence:
    """One exact physical net and the route evidence that may move its endpoints."""

    net_id: NetId
    weight: int
    source_offset: Cell
    destination_offset: Cell
    hot_cells: tuple[tuple[Cell, int], ...]


def _feedback_objective_evidence(
    feedback: FeedbackState,
    *,
    strip_count: int,
) -> tuple[_FeedbackObjectiveEvidence, ...]:
    """Keep exact net identities separate when translating feedback to CP terms."""
    evidence: list[_FeedbackObjectiveEvidence] = []
    ordered = sorted(
        feedback.net_weight.items(),
        key=lambda pair: (
            -1 if pair[0].source_strip is None else pair[0].source_strip,
            -1 if pair[0].destination_strip is None else pair[0].destination_strip,
            pair[0].item,
            pair[0].cargo_domain.value,
            pair[0].role.value,
            pair[0].ordinal,
        ),
    )
    for net, weight in ordered:
        if (
            net.source_strip is None
            or net.destination_strip is None
            or not 0 <= net.source_strip < strip_count
            or not 0 <= net.destination_strip < strip_count
            or (offsets := feedback.endpoint_offsets.get(net)) is None
            or weight <= 0.0
        ):
            continue
        source_offset, destination_offset = offsets
        hot_cells = tuple(
            (cell, max(1, math.ceil(history)))
            for cell, history in sorted(feedback.net_cell_history.get(net, {}).items())
            if history > 0.0
        )
        evidence.append(
            _FeedbackObjectiveEvidence(
                net_id=net,
                weight=max(1, math.ceil(weight)),
                source_offset=source_offset,
                destination_offset=destination_offset,
                hot_cells=hot_cells,
            )
        )
    return tuple(evidence)


def _feedback_objective_score(
    evidence: tuple[_FeedbackObjectiveEvidence, ...],
    origins: tuple[tuple[int, int], ...],
    outline: tuple[int, int],
) -> int:
    """Evaluate the same exact-net evidence tier for one concrete assignment."""
    max_distance = outline[0] + outline[1]
    score = 0
    for term in evidence:
        source_strip = term.net_id.source_strip
        destination_strip = term.net_id.destination_strip
        if source_strip is None or destination_strip is None:
            continue
        source = (
            origins[source_strip][0] + term.source_offset[0],
            origins[source_strip][1] + term.source_offset[1],
        )
        destination = (
            origins[destination_strip][0] + term.destination_offset[0],
            origins[destination_strip][1] + term.destination_offset[1],
        )
        score += term.weight * (abs(source[0] - destination[0]) + abs(source[1] - destination[1]))
        for (wall_x, wall_y, _level), history in term.hot_cells:
            wall_distance = (
                abs(source[0] - wall_x)
                + abs(source[1] - wall_y)
                + abs(destination[0] - wall_x)
                + abs(destination[1] - wall_y)
            )
            score += term.weight * history * max(0, max_distance - wall_distance)
    return score


#: Wall limit of one fix-and-reoptimize window solve.  A window is affordable
#: exactly because it is not a full pack: the full solve on the largest cells
#: gets `share * _PACK_SHARE / len(heights)` and is followed by a 1.9-4.6 s
#: preparation, so a repair that costs more than a second buys nothing.
C_WINDOW_SECONDS = 1.0
#: Deterministic work bound for a window solve.  A full pack of fifteen or
#: more strips gets `_deterministic_pack_work(len(strips))` and is expected
#: to stop at its first incumbent from a shelf warm start; a window has at
#: most twelve free strips but no such guarantee, and is expected to close a
#: small model, so it gets this bound instead.  This constant is twenty-five
#: times the *calibrated-size* allowance -- what a fifteen-strip pack gets --
#: so larger packs narrow the ratio.  On an idle box this is the limit that
#: fires; under `--jobs 16` the wall limit above fires first.
C_WINDOW_DETERMINISTIC_WORK = 25 * _DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE
#: One CP-SAT worker per window.  `pyproject.toml` records that a single solve
#: already runs at ~700% CPU; a window must not race the packer for cores.
C_WINDOW_WORKERS = 1
#: Margin a window solve keeps between itself and the run deadline.
C_WINDOW_DEADLINE_SAFETY_SECONDS = 0.05


@dataclass(slots=True)
class _PackCpProfile:
    """Aggregate CP-SAT work for one Freeform layout attempt."""

    wall_time_s: float = 0.0
    deterministic_time_s: float = 0.0
    solves: int = 0
    optimal: int = 0
    feasible: int = 0
    infeasible: int = 0
    model_invalid: int = 0
    unknown: int = 0
    last_status: str = "UNKNOWN"
    last_objective: float = math.nan
    last_best_bound: float = math.nan
    window_solves: int = 0
    window_optimal: int = 0
    window_feasible: int = 0
    window_infeasible: int = 0
    window_model_invalid: int = 0
    window_unknown: int = 0
    window_repeated_submodels: int = 0
    window_repeated_submodel_seconds: float = 0.0
    window_fingerprints: set[str] = field(default_factory=set)

    def observe(
        self,
        solver: cp_model.CpSolver,
        status: cp_model.CpSolverStatus,
        wall_s: float,
    ) -> None:
        name = solver.StatusName(status)
        self.wall_time_s += wall_s
        self.deterministic_time_s += solver.response_proto.deterministic_time
        self.solves += 1
        self.last_status = name
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self.last_objective = solver.ObjectiveValue()
            self.last_best_bound = solver.BestObjectiveBound()
        else:
            self.last_objective = math.nan
            self.last_best_bound = math.nan
        if name == "OPTIMAL":
            self.optimal += 1
        elif name == "FEASIBLE":
            self.feasible += 1
        elif name == "INFEASIBLE":
            self.infeasible += 1
        elif name == "MODEL_INVALID":
            self.model_invalid += 1
        else:
            self.unknown += 1

    def observe_window(self, outcome: _PackSolveOutcome) -> None:
        self.window_solves += 1
        if outcome.status == "OPTIMAL":
            self.window_optimal += 1
        elif outcome.status == "FEASIBLE":
            self.window_feasible += 1
        elif outcome.status == "INFEASIBLE":
            self.window_infeasible += 1
        elif outcome.status == "MODEL_INVALID":
            self.window_model_invalid += 1
        else:
            self.window_unknown += 1
        if outcome.model_fingerprint in self.window_fingerprints:
            self.window_repeated_submodels += 1
            self.window_repeated_submodel_seconds += outcome.wall_time_s
        else:
            self.window_fingerprints.add(outcome.model_fingerprint)

    def stats(self) -> dict[str, float | str]:
        return {
            "pack_cp_wall_time_s": self.wall_time_s,
            "pack_cp_deterministic_time_s": self.deterministic_time_s,
            "pack_cp_solves": float(self.solves),
            "pack_cp_optimal": float(self.optimal),
            "pack_cp_feasible": float(self.feasible),
            "pack_cp_infeasible": float(self.infeasible),
            "pack_cp_model_invalid": float(self.model_invalid),
            "pack_cp_unknown": float(self.unknown),
            "pack_cp_last_status": self.last_status,
            "pack_cp_last_objective": self.last_objective,
            "pack_cp_last_best_bound": self.last_best_bound,
            "pack_window_solves": float(self.window_solves),
            "pack_window_optimal": float(self.window_optimal),
            "pack_window_feasible": float(self.window_feasible),
            "pack_window_infeasible": float(self.window_infeasible),
            "pack_window_model_invalid": float(self.window_model_invalid),
            "pack_window_unknown": float(self.window_unknown),
            "pack_window_distinct_submodels": float(len(self.window_fingerprints)),
            "pack_window_repeated_submodels": float(self.window_repeated_submodels),
            "pack_window_repeated_submodel_seconds": self.window_repeated_submodel_seconds,
        }


_PACK_CP_PROFILE: ContextVar[_PackCpProfile | None] = ContextVar(
    "_PACK_CP_PROFILE",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _PackSolveOutcome:
    """Typed result of one concrete CP-SAT pack submodel."""

    pack: routing_domain._Pack | None
    status: str
    objective_value: float | None
    best_objective_bound: float | None
    wall_time_s: float
    deterministic_time_s: float
    model_fingerprint: str


@dataclass(frozen=True, slots=True)
class _PackModel:
    """One built packing model and the handles a caller needs to read it back."""

    model: cp_model.CpModel
    w_var: cp_model.IntVar
    xs: list[cp_model.IntVar]
    ys: list[cp_model.IntVar]
    direct_vars: dict[tuple[int, int], cp_model.IntVar]
    sizes: list[tuple[int, int]]
    #: No-goods dropped because a pinned strip contradicted them or because they
    #: named no free strip.  Adding either would constrain the sub-model for a
    #: reason outside the window.
    skipped_no_goods: int


def _pack_model(
    strips: list[routing_domain.Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    fixed_at: Mapping[int, tuple[int, int]] = MappingProxyType({}),
    width_target: int | None = None,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    seed: routing_domain._Pack | None = None,
) -> _PackModel | None:
    """Build the packing model, optionally with some strips pinned in place.

    ``fixed_at`` maps a strip index to its CONTENT origin -- the same convention
    ``_Pack.at`` uses -- and pins that strip by giving its ``x``/``y`` variables a
    singleton domain.  A singleton domain rather than a constant expression is
    deliberate: every constraint below is then written by the SAME code for a
    pinned strip as for a free one, so the window model is provably the full
    model with fewer degrees of freedom rather than a second formulation that
    has to be kept in step.  With ``fixed_at`` empty this is exactly the model
    ``_pack`` has always built.
    """
    model = cp_model.CpModel()
    n = len(strips)
    skipped = 0
    if n == 0:
        return None

    # Sizes first: several cuts below need them before any variable exists.
    # A size is the strip PLUS its reserved channels -- see `WEST_CHANNEL`. The
    # routing corridors are part of what `add_no_overlap_2d` keeps apart, which
    # is what makes them a constraint the model respects rather than a corridor
    # the router has to hope for.
    sizes = [_box(s) for s in strips]
    if any(h > height for _, h in sizes):
        return None  # this height cannot hold some strip at all

    # CUT 1 -- area.  Everything must fit inside `w_var x height`, so
    # `w_var >= ceil(total_area / height)`.  Without this `w_var`'s lower bound
    # is 1 and the relaxation can drive the width term to nothing, which is most
    # of why the bound crawled while the incumbent sat still.  `height` is a
    # constant here, so this stays linear.
    total_area = sum(w * h for w, h in sizes)
    widest = max(w for w, _ in sizes)
    w_lb = max(widest, -(-total_area // height))  # ceil division
    w_var = model.new_int_var(min(w_lb, width_bound), width_bound, "W")

    xs, ys, x_iv, y_iv = [], [], [], []
    for i, (w, h) in enumerate(sizes):
        pinned = fixed_at.get(i)
        if pinned is None:
            x = model.new_int_var(0, max(0, width_bound - w), f"x{i}")
            y = model.new_int_var(0, max(0, height - h), f"y{i}")
        else:
            bx = pinned[0] - strips[i].west_channel
            by = pinned[1]
            if not (0 <= bx <= max(0, width_bound - w)) or not (0 <= by <= max(0, height - h)):
                return None  # the pin is outside this outline; nothing to repair here
            x = model.new_int_var(bx, bx, f"x{i}")
            y = model.new_int_var(by, by, f"y{i}")
        xs.append(x)
        ys.append(y)
        x_iv.append(model.new_fixed_size_interval_var(x, w, f"xi{i}"))
        y_iv.append(model.new_fixed_size_interval_var(y, h, f"yi{i}"))
        model.add(x + w <= w_var)

    model.add_no_overlap_2d(x_iv, y_iv)

    def _no_good_is_live(named: Iterable[int], origins: Iterable[tuple[int, int]]) -> bool:
        """Is this no-good worth adding to a model with pinned strips?

        No, twice over.  If a pinned strip already sits somewhere else, the
        forbidden tuple is unreachable and the constraint is dead weight.  If
        every strip it names is pinned, its only free variable is ``w_var`` and
        it would forbid a WIDTH for no geometric reason.
        """
        named = tuple(named)
        origins = tuple(origins)
        if all(index in fixed_at for index in named):
            return False
        for index, origin in zip(named, origins, strict=True):
            current = fixed_at.get(index)
            if current is not None and current != origin:
                return False
        return True

    def _cluster_no_good_is_live(no_good: ClusterRelationNoGood) -> bool:
        """ONE rejection, and it is not the one :func:`_no_good_is_live` makes.

        A cluster no-good names offsets rather than origins, so it never names
        an absolute position on its own.  What it does fix is where the ANCHOR
        would have to sit for any one strip to satisfy it: subtract that strip's
        delta from its pinned content origin.  Two pinned strips that imply
        different anchors therefore contradict the relation outright, and no
        placement of the strips still free can complete it -- the constraint is
        dead weight whether or not the anchor itself is one of the pinned ones.
        That, and only that, is what this skips.

        There is deliberately NO "every named strip is pinned" rejection here,
        which is where this differs from its sibling.  That rejection exists so
        an exact-pack no-good cannot forbid a WIDTH for no geometric reason, and
        the reason does not carry over: :func:`_add_cluster_relation_no_good`
        never touches ``w_var``.  Its relation variables are differences of
        content origins, so a fully pinned cluster whose pins AGREE with the
        forbidden offsets is not a degenerate constraint -- it is the statement
        that this pack already sits in the relative placement Phase B proved
        unroutable, and CP-SAT should say INFEASIBLE.  "This window cannot
        repair the incumbent" is the truthful answer; silently dropping the cut
        would hand back the arrangement the proof rejected.
        """
        implied: tuple[int, int] | None = None
        for index, delta in zip(no_good.strips, no_good.deltas, strict=True):
            current = fixed_at.get(index)
            if current is None:
                continue
            anchor = (current[0] - delta[0], current[1] - delta[1])
            if implied is not None and anchor != implied:
                return False
            implied = anchor
        return True

    for exact_no_good in exact_pack_no_goods:
        if exact_no_good.height != height or exact_no_good.outline != tuple(sizes):
            continue
        if not _no_good_is_live(range(n), exact_no_good.origins):
            skipped += 1
            continue
        _add_exact_pack_no_good(model, w_var, xs, ys, strips, exact_no_good)

    for cluster_index, cluster_no_good in enumerate(cluster_relation_no_goods):
        if cluster_no_good.height != height or cluster_no_good.outline != tuple(sizes):
            continue
        if not _cluster_no_good_is_live(cluster_no_good):
            skipped += 1
            continue
        _add_cluster_relation_no_good(
            model,
            xs,
            ys,
            strips,
            height,
            width_bound,
            cluster_index,
            cluster_no_good,
        )

    for projection_no_good in projection_no_goods:
        if (
            projection_no_good.left_strip == projection_no_good.right_strip
            or not 0 <= projection_no_good.left_strip < n
            or not 0 <= projection_no_good.right_strip < n
        ):
            raise ValueError("projection no-good must name two distinct packed strips")
        if projection_no_good.pack_height != height:
            continue
        if not _no_good_is_live(
            (projection_no_good.left_strip, projection_no_good.right_strip),
            (projection_no_good.left_origin, projection_no_good.right_origin),
        ):
            skipped += 1
            continue
        _add_projection_no_good(model, w_var, xs, ys, strips, projection_no_good)

    # CUT 3 -- ROUTING CAPACITY was built here, measured, and taken out.
    #
    # The argument is sound as far as it goes and the brief for this work said
    # it had never been built and measured, so it now has been.  A net whose
    # endpoints straddle a vertical cut occupies AT LEAST one cell on that
    # column, so free cells in a column bound the nets crossing it, and nothing
    # in this model said so while the objective drove straight at the bound:
    # `universe-matrix/no-proliferator` at h=69 packs a column with 70 free
    # cells against 70 nets crossing it.  Slack ZERO, with a band of neighbours
    # at 2.  By counting alone no router can wire that, and `_pack` called it
    # feasible.
    #
    # It was expressed as one `add_cumulative` over the strips' CONTENT spans,
    # charging `LEVELS` cells per machine row and one per lane row, against a
    # column budget that reserved one free cell per net in the block.  It works:
    # h=69 becomes infeasible and is no longer offered.
    #
    # AND IT MADE THE SPEC WORSE, which is what the calibration behind it could
    # not see.  The numbers that motivated it compared DIFFERENT specs -- 4.6
    # free cells per crossing net on `casimir-crystal`, 5.0 on `quantum-chip`,
    # 1.0 on the `universe-matrix` pack -- and that comparison is confounded by
    # spec size.  Within ONE spec it inverts: h=69, the saturated pack, routes
    # all but ONE of its 140 nets given no clock, while h=92, h=116, h=145 and
    # h=185 all satisfy the bound comfortably and leave 12, 26, 14 and 17
    # unrouted.  Rejecting h=69 deletes the best candidate the sweep has.
    # Corpus at 4s: 66/65/66 clean with it against 66/66/66 without.
    #
    # So cut capacity is a NECESSARY condition that is not the binding one, and
    # enforcing a necessary condition that correlates the wrong way inside a
    # spec costs more than it buys. What decides routability here is which cells
    # are free, not how many.
    #
    # AND NO CHEAP ESTIMATE OF "WHICH CELLS ARE FREE" PREDICTS IT EITHER. That
    # was the open question the note above left, so it has now been measured
    # rather than argued, because a cheap predictor is the hinge on which a whole
    # class of redesign turns: replace CP-SAT with a sequence-pair search under
    # annealing, score each arrangement with a fast global router instead of the
    # real one, and search thousands of arrangements instead of five. All of that
    # rests on the surrogate agreeing with `_route_all`.
    #
    # Four estimates were computed on the REAL canvas at the moment before
    # routing -- 270 packs, really routed, on `casimir-crystal`,
    # `information-matrix`, `quantum-chip` and `universe-matrix`, 55 of which
    # failed -- and scored by AUC against what the router then did. AUC 0.5 is a
    # coin flip. Pooled WITHIN (spec, candidate), which is the comparison that
    # matters and the one the calibration above got wrong:
    #
    #   connectivity, nets whose ports are in different components   0.500
    #   the same test on real 3D cells rather than a projection      0.500
    #   coarse capacity-based global router, total overflow          0.535
    #   the same router's worst single-edge overflow                 0.525
    #   free-column fraction                                         0.491
    #   cut-capacity slack -- THE CONTROL                            0.422
    #
    # The control is what makes the nulls trustworthy: cut slack comes out
    # ANTI-correlated, independently reproducing the finding above, so the
    # instrument could have detected a signal and there was none to detect. Hold
    # the height fixed as well, so only arrangement varies, and every one of them
    # sits between 0.495 and 0.513.
    #
    # The global router is genuinely fast -- 69ms against 13.5s of real routing
    # on `universe-matrix`, some 200x -- and a 200x-faster oracle at AUC 0.51 is
    # worth nothing. Emission alone is 0.108s there, which is the floor on ANY
    # routability evaluation since you cannot know which cells are free without
    # it, so such a search gets ~130 evaluations per 15s ceiling and not the
    # thousands annealing wants. What survives the experiment is the opposite
    # conclusion: arrangement decides routability and only the real router can
    # tell you, which is what `_ARRANGEMENTS` spends its solves on.

    # Symmetry breaking between identical strips of the same recipe: without it
    # the search burns itself on permutations that differ by nothing.
    for i in range(n):
        for j in range(i + 1, n):
            if i in fixed_at or j in fixed_at:
                continue
            a, b = strips[i], strips[j]
            if (a.group_key, a.machines, a.in_lanes, a.out_lanes) == (
                b.group_key,
                b.machines,
                b.in_lanes,
                b.out_lanes,
            ):
                model.add(xs[i] * height + ys[i] <= xs[j] * height + ys[j])

    # Half-perimeter wirelength over the nets, which is what keeps phase 2's job
    # tractable and costs almost nothing to express.
    terms: list[cp_model.IntVar] = []
    for i, j in _nets_between(strips):
        dx = model.new_int_var(0, width_bound, f"dx{i}_{j}")
        dy = model.new_int_var(0, height, f"dy{i}_{j}")
        model.add_abs_equality(dx, xs[i] - xs[j])
        model.add_abs_equality(dy, ys[i] - ys[j])

        # CUT 2 -- separation.  Two strips cannot overlap, so they are disjoint
        # in x or in y; either way their origins differ by at least the smaller
        # of the two extents on that axis.  Without this every `dx`/`dy` has a
        # relaxation value of 0, so the entire HPWL half of the objective is
        # invisible to the bound -- which is why `bound` sat near the width term
        # alone while `obj` was more than twice it.
        wi, hi = sizes[i]
        wj, hj = sizes[j]
        model.add(dx + dy >= min(min(wi, wj), min(hi, hj)))

        terms.append(dx)
        terms.append(dy)

    # Direct insertion: one Boolean per eligible net, reified against the
    # geometry that would let a single sorter replace the whole belt route.
    #
    # The condition is deliberately strict: the consumer lane sits south of the
    # producer lane and their occupied endpoints share an exact x coordinate,
    # because a DSP sorter runs straight rather than diagonally. Both lanes are
    # at z=0 by construction, so alignment in y is the whole altitude story.

    # The gap floor is MARGIN + 1 rather than 1: the packed boxes carry a margin,
    # so anything tighter would collide with `no_overlap_2d` and make the
    # Boolean unsatisfiable rather than merely unattractive.
    direct_vars: dict[tuple[int, int], cp_model.IntVar] = {}
    for (i, j), cand in direct_candidates.items():
        di = model.new_bool_var(f"di{i}_{j}")
        # The consumer sits BELOW the producer, and the sorter runs vertically
        # down a column both lanes share.
        #
        # Vertical is the geometry this architecture actually wants. A strip is
        # input lanes / machines / output lanes stacked top to bottom, so a
        # producer's output lane is its bottom row and a consumer's input lane is
        # its top row -- they meet naturally when one is stacked under the other.
        #
        # The east/west alternative was tried and is strictly worse: it forces
        # the two strips side by side, which WIDENS the pack, and width outranks
        # the direct-insert reward lexicographically. The solver correctly
        # refused every such pair, so the feature never fired.
        gap = (ys[j] + cand.cons_row) - (ys[i] + cand.prod_row)
        model.add(gap >= 1).only_enforce_if(di)
        model.add(gap <= catalog.SORTER_MAX_REACH).only_enforce_if(di)
        # Reward only exact x offsets with a witness column that is occupied by
        # both lanes and clear of every sorter already seated on either lane.
        # Encoding the witness set here keeps an unprovable candidate out of the
        # objective instead of letting emission discover the missing precondition
        # after the reward has already influenced the pack.
        origin_delta = (xs[j] + strips[j].west_channel) - (xs[i] + strips[i].west_channel)
        permitted_delta = model.new_int_var_from_domain(
            cp_model.Domain.from_values(cand.origin_deltas),
            f"direct_dx{i}_{j}",
        )
        model.add(origin_delta == permitted_delta).only_enforce_if(di)
        direct_vars[i, j] = di

    for no_good_index, relation_no_good in enumerate(direct_relation_no_goods):
        direct = relation_no_good.direct_id
        pair = (direct.source_strip, direct.destination_strip)
        candidate = direct_candidates.get(pair)
        direct_var = direct_vars.get(pair)
        if (
            candidate is None
            or direct_var is None
            or candidate.item != direct.item
            or candidate.cargo_domain is not direct.cargo_domain
        ):
            continue
        if pair[0] in fixed_at and pair[1] in fixed_at:
            skipped += 1
            continue
        relation_x = model.new_int_var(
            -width_bound,
            width_bound,
            f"direct_ng_dx{no_good_index}",
        )
        relation_y = model.new_int_var(
            -height,
            height,
            f"direct_ng_dy{no_good_index}",
        )
        model.add(
            relation_x
            == (xs[pair[1]] + strips[pair[1]].west_channel)
            - (xs[pair[0]] + strips[pair[0]].west_channel)
        )
        model.add(relation_y == ys[pair[1]] - ys[pair[0]])
        model.add_forbidden_assignments(
            [direct_var, relation_x, relation_y],
            [(1, relation_no_good.delta_x, relation_no_good.delta_y)],
        )

    # Objective: width first, wirelength only as a tie-break.
    #
    # Height is fixed for this solve, so `w_var` IS the area being minimised.
    # Previously width carried weight 5 while HPWL contributed two terms per net
    # each as large as `width_bound`, so wirelength dominated and the solver
    # traded width away to shorten wires.  That is measurable: with the old
    # weights, giving the solver MORE time made the final area WORSE
    # (1460 tiles at 0.1s versus 1566 at 4s), because it was optimising a proxy
    # anti-correlated with the metric we actually report.
    #
    # Scaling width above the largest achievable HPWL sum makes the comparison
    # lexicographic without a second solve: any width saving beats every
    # wirelength saving, and HPWL then breaks ties among equal-width packings --
    # which is all it was ever needed for, since it exists to keep phase 2's
    # routing tractable rather than to shrink the build.
    # The direct-insert reward joins the tie-break tier rather than competing
    # with width: a direct insert deletes belt tiles, not bounding box. It is
    # expressed as a PENALTY for *not* direct-inserting so every term stays
    # non-negative -- a negative reward would let the tier range below zero and
    # a width increase could be bought back, which is exactly the blend this
    # ordering exists to prevent.
    #
    # A BACKWARD-NET PENALTY WAS BUILT HERE, MEASURED, AND TAKEN OUT -- and its
    # numbers are worth keeping, because half of it was right.
    #
    # The argument: `dx` is an ABSOLUTE value, so a net running the wrong way
    # costs exactly what the same net running the right way costs. But a net
    # leaves its producer's output lane at the EAST end and arrives at its
    # consumer's input lane at the WEST head, so a consumer placed west of its
    # producer makes the belt wrap all the way around the producer. HPWL cannot
    # see that. The term is `max(0, x_i + w_i - x_j)`, the overlap a net has to
    # double back over -- one variable and one inequality per net, since a
    # positive coefficient in a minimisation drives it to its floor unaided.
    #
    # It was tried in two positions, with `tie_break_cap` grown to cover it so
    # width stayed lexicographically above it either way: inside this tie-break
    # tier beside HPWL, and in a tier of its own between width and HPWL. Both
    # move the quantity they aim at -- backward overlap on `super-magnetic-ring`
    # h=29 fell 614 -> 205 -> 144 across off, tier and own-tier.
    #
    # AND BOTH COST CLEAN CELLS, dose-responsively, which is what says it is the
    # term and not the encoding. Corpus at `--budget 4`, against 70.88 clean of
    # 72 over eight runs: 69.00 in the tie-break tier (t = -3.49), 68.62 in its
    # own tier (t = -3.89), and 68.00 when weighted eight times harder inside the
    # tie-break tier (t = -8.21). The harder it is enforced the more it costs.
    # An arrangement multi-start does not rescue it either -- paired against the
    # same multi-start without it, still -1.25 cells.
    #
    # THE OTHER HALF IS REAL AND IS LEFT ON THE TABLE DELIBERATELY. On the 61
    # cells clean in every run of every arm it is -2.40% AREA -- denser on 32
    # cells, larger on 9, biggest wins `information-matrix/free-proliferation` at
    # -572 and -450 tiles -- and the mechanism is plain enough: a belt that does
    # not wrap around its producer does not push the bounding box out. So this is
    # a DENSITY lever that is anti-correlated with routability at a fixed clock,
    # not the routability fix it was proposed as. It belongs in a build that has
    # cells to spare, and it does not belong in the objective while the binding
    # constraint is still whether a pack wires at all.
    cap = tie_break_cap(
        len(terms), width_bound=width_bound, height=height, n_direct=len(direct_vars)
    )
    missed = sum(di.Not() for di in direct_vars.values())
    base_tier = LAMBDA_HPWL * sum(terms) + MU_DIRECT * missed
    evidence = () if feedback is None else _feedback_objective_evidence(feedback, strip_count=n)
    evidence_terms: list[cp_model.LinearExpr] = []
    max_distance = width_bound + height
    for evidence_index, term in enumerate(evidence):
        source_strip = term.net_id.source_strip
        destination_strip = term.net_id.destination_strip
        if source_strip is None or destination_strip is None:
            continue
        source_x = xs[source_strip] + strips[source_strip].west_channel + term.source_offset[0]
        source_y = ys[source_strip] + term.source_offset[1]
        destination_x = (
            xs[destination_strip]
            + strips[destination_strip].west_channel
            + term.destination_offset[0]
        )
        destination_y = ys[destination_strip] + term.destination_offset[1]
        dx = model.new_int_var(0, width_bound, f"feedback_dx{evidence_index}")
        dy = model.new_int_var(0, height, f"feedback_dy{evidence_index}")
        model.add_abs_equality(dx, source_x - destination_x)
        model.add_abs_equality(dy, source_y - destination_y)
        evidence_terms.append(term.weight * (dx + dy))
        for wall_index, ((wall_x, wall_y, _level), history) in enumerate(term.hot_cells):
            distances: list[cp_model.IntVar] = []
            for label, coordinate, wall, upper in (
                ("sx", source_x, wall_x, width_bound),
                ("sy", source_y, wall_y, height),
                ("dx", destination_x, wall_x, width_bound),
                ("dy", destination_y, wall_y, height),
            ):
                distance = model.new_int_var(
                    0,
                    upper,
                    f"feedback_wall_{label}{evidence_index}_{wall_index}",
                )
                model.add_abs_equality(distance, coordinate - wall)
                distances.append(distance)
            proximity = model.new_int_var(
                0,
                max_distance,
                f"feedback_hot{evidence_index}_{wall_index}",
            )
            model.add_max_equality(
                proximity,
                [0, max_distance - sum(distances)],
            )
            evidence_terms.append(term.weight * history * proximity)
    if not evidence_terms:
        model.minimize(w_var * cap + base_tier)
    else:
        evidence_cap = (width_bound + 1) * cap
        model.minimize(sum(evidence_terms) * evidence_cap + w_var * cap + base_tier)

    # Warm start.  The seed is feasible at this height by construction, so its
    # width bounds `w_var` from above and its positions give the search an
    # incumbent to improve on rather than one to find.  Values are clamped into
    # each variable's domain: an out-of-domain hint is not a tighter hint, it is
    # a discarded one.
    if seed is not None:
        if feedback is None:
            model.add(w_var <= min(seed.width, width_bound))
        for i, (hx, hy) in seed.at.items():
            if i >= n or i in fixed_at:
                continue
            w, h = sizes[i]
            # `seed.at` is a CONTENT origin and `xs` is a BOX origin, so the
            # west channel comes back off before the hint is offered. An
            # out-by-one hint is not a weaker hint, it is a hint for a packing
            # that overlaps.
            model.add_hint(
                xs[i],
                min(
                    max(hx - strips[i].west_channel, 0),
                    max(0, width_bound - w),
                ),
            )
            model.add_hint(ys[i], min(max(hy, 0), max(0, height - h)))

    if width_target is not None:
        if all(
            fixed_at[index][0] - strips[index].west_channel + sizes[index][0] <= width_target
            for index in fixed_at
        ):
            model.add(w_var <= width_target)
        else:
            # A pinned strip already reaches past the target, so the bound cannot
            # be added without making the sub-model infeasible for a reason
            # outside the window.  Count it: a target that never applies is a
            # repair aimed at nothing, and the gate must be able to see that.
            skipped += 1

    return _PackModel(
        model=model,
        w_var=w_var,
        xs=xs,
        ys=ys,
        direct_vars=direct_vars,
        sizes=sizes,
        skipped_no_goods=skipped,
    )


def _pack_result(
    built: _PackModel,
    solver: cp_model.CpSolver,
    strips: Sequence[routing_domain.Strip],
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    height: int,
    admission: cp_model.CpSolverSolutionCallback | None,
    *,
    model_fingerprint: str = "",
) -> _PackSolveOutcome:
    """Solve one built model and retain the exact CP status and bound."""
    solve_started = time.perf_counter()
    status = solver.Solve(built.model, admission)
    elapsed = time.perf_counter() - solve_started
    profile = _PACK_CP_PROFILE.get()
    if profile is not None:
        profile.observe(solver, status, elapsed)
    status_name = solver.StatusName(status)
    solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    pack = (
        routing_domain._Pack(
            at={
                i: (
                    solver.Value(built.xs[i]) + strips[i].west_channel,
                    solver.Value(built.ys[i]),
                )
                for i in range(len(strips))
            },
            width=solver.Value(built.w_var),
            height=height,
            status=status_name,
            hit_budget=status == cp_model.FEASIBLE,
            direct=frozenset(
                routing_domain.DirectInsertId(
                    i,
                    j,
                    direct_candidates[i, j].item,
                    direct_candidates[i, j].cargo_domain,
                )
                for (i, j), di in built.direct_vars.items()
                if solver.Value(di)
            ),
        )
        if solved
        else None
    )
    return _PackSolveOutcome(
        pack=pack,
        status=status_name,
        objective_value=solver.ObjectiveValue() if solved else None,
        best_objective_bound=solver.BestObjectiveBound() if solved else None,
        wall_time_s=elapsed,
        deterministic_time_s=solver.response_proto.deterministic_time,
        model_fingerprint=model_fingerprint,
    )


def _pack_window(
    strips: list[routing_domain.Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    window: frozenset[int],
    fixed_at: Mapping[int, tuple[int, int]],
    seed: routing_domain._Pack | None = None,
    width_target: int | None = None,
    arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    time_budget_s: float = C_WINDOW_SECONDS,
    deterministic_work: float = C_WINDOW_DETERMINISTIC_WORK,
    on_skipped: Callable[[int], None] | None = None,
) -> _PackSolveOutcome | None:
    """Re-solve `_pack`'s formulation for ``window`` with everything else pinned.

    This is a sub-model, not a re-solve: every strip, constraint, no-good and
    objective term of the full model is present, and only the pinned strips'
    domains are collapsed.  `test_pack_window_over_every_strip_reproduces_the_full_pack`
    pins that claim by asking for the whole problem as the window, with no seed
    on either side, and comparing against `_pack`.

    ``width_bound`` is the incumbent's width, so a window may NARROW the block
    and can never widen it.

    A CP-SAT invocation returns its typed status and objective bound even when it
    has no incumbent.  ``None`` means no model was solved because the request was
    statically unaffordable or inconsistent.
    """
    if not window:
        raise ValueError("a repair window must name at least one strip")
    if any(index in fixed_at for index in window):
        raise ValueError("window strips must not also be pinned")
    if set(fixed_at) | window != set(range(len(strips))):
        raise ValueError("window and pinned strips must cover every strip")
    if time_budget_s <= 0:
        return None
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        fixed_at=fixed_at,
        width_target=width_target,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        cluster_relation_no_goods=cluster_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None:
        return None
    if on_skipped is not None and built.skipped_no_goods:
        on_skipped(built.skipped_no_goods)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    # One worker and a deterministic-work bound, always: a window runs BESIDE a
    # packer that already saturates the box, and its result must not depend on
    # wall time except through the wall limit above firing as a hard deadline.
    solver.parameters.num_search_workers = C_WINDOW_WORKERS
    solver.parameters.max_deterministic_time = min(time_budget_s, deterministic_work)
    # A function of `arrangement` and nothing else -- see `_pack`.
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement
    fingerprint = hashlib.sha256(str(built.model.Proto()).encode()).hexdigest()
    outcome = _pack_result(
        built,
        solver,
        strips,
        direct_candidates,
        height,
        None,
        model_fingerprint=fingerprint,
    )
    profile = _PACK_CP_PROFILE.get()
    if profile is not None:
        profile.observe_window(outcome)
    return outcome


def _decoded_from_pack(
    pack: routing_domain._Pack, strips: Sequence[routing_domain.Strip], height: int
) -> DecodedPlacement:
    """View one packed assignment as a decoded placement for the destroy operators.

    `_Pack.at` holds CONTENT origins and a decoded placement holds BOX origins,
    so the west channel comes back off -- each strip's own, because channels
    differ from strip to strip and a single shared subtraction would move two
    thirds of a pack.  The coordinate windows are degenerate (each equals its
    coordinate) because a packed assignment has no slack left to describe:
    nothing downstream of a destroy operator reads them.

    `height` is the outline the pack was solved at.  It is carried for symmetry
    with the other two adapters and deliberately not used to clamp anything: a
    decoded placement reports the height its own boxes reach, not the one it was
    allowed.
    """
    sizes = [_box(strip) for strip in strips]
    xs = tuple(pack.at[index][0] - strips[index].west_channel for index in range(len(strips)))
    ys = tuple(pack.at[index][1] for index in range(len(strips)))
    return DecodedPlacement(
        x=xs,
        y=ys,
        width=pack.width,
        used_height=max((ys[index] + sizes[index][1] for index in range(len(strips))), default=0),
        x_windows=tuple((value, value) for value in xs),
        y_windows=tuple((value, value) for value in ys),
        gap_area=0,
    )


def _pack_relation_problem(
    pack: routing_domain._Pack, strips: Sequence[routing_domain.Strip], height: int
) -> PlacementProblem:
    """A placement problem carrying this pack's sizes and nets, for operator reuse.

    ``logical_net_ids`` is left empty on purpose.  No shipped destroy operator
    reads it, and `_nets_between` returns bare strip-index pairs with no item
    identity, so filling it would mean synthesizing `LogicalNetId`s nothing
    consumes.  The operator that would need them (RELATED_CARGO) is a follow-up,
    and populating this field belongs to that operator's task.

    `pack` is taken for the signature the spec declares and for the day an
    adapter needs the assignment; the problem itself is a property of the strips
    and the outline, not of where this particular solve put them.
    """
    sizes = tuple(_box(strip) for strip in strips)
    return PlacementProblem(
        sizes=sizes,
        nets=tuple(_nets_between(list(strips))),
        outline_height=height,
        area_lower_bound=sum(width * box_height for width, box_height in sizes),
    )


def _pack_relation_pair(
    pack: routing_domain._Pack, strips: Sequence[routing_domain.Strip], height: int
) -> SequencePair:
    """The sequence pair this pack encodes to, for the sequence-neighbour operator.

    Its gaps are zero by construction, so `select_lns_neighbourhood`'s
    gap-rectangle branch never fires on a freeform pack: the neighbourhood there
    is failure endpoints plus sequence neighbours only.

    Only the pair is returned, and only the pair is safe to use: `encode_placement`
    reports `exact=False` on most placements with slack, so its decode is a
    compaction of this pack and not this pack.  A caller that wants coordinates
    wants `_decoded_from_pack`, or must score the encoder's decode itself.
    """
    decoded = _decoded_from_pack(pack, strips, height)
    return encode_placement(
        tuple(_box(strip) for strip in strips),
        decoded.x,
        decoded.y,
        outline_height=height,
    ).pair


def _pack(
    strips: list[routing_domain.Strip],
    *,
    height: int,
    width_bound: int,
    time_budget_s: float,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    workers: int,
    deterministic: bool = False,
    seed: routing_domain._Pack | None = None,
    arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    stop_when_seed_admissible: bool = False,
) -> routing_domain._Pack | None:
    """Minimise width at a fixed height with CP-SAT.

    Height is swept outside rather than multiplied inside: ``W * H`` is a product
    of two variables, whose CP-SAT relaxation is weak enough that the search
    flounders.  Several easy solves beat one hard one.

    ``seed`` is a shelf packing at this same height -- feasible by construction,
    so it does two things no heuristic guess could.  It hints every ``x``/``y``,
    which gives the search an incumbent immediately instead of after it finds
    one; and its width is a proven upper bound on ``w_var``, which cuts the
    domain the bound has to climb through.  This is the construction that used
    to be the fallback, put to the one use it is genuinely good for.

    ``arrangement`` asks for a DIFFERENT optimum of the SAME model.  Nothing
    about the model changes -- not the objective, not a cut, not the warm start
    -- only which of many equally wide packings CP-SAT walks to.  ``0`` is the
    constant this always used, so a caller that does not ask gets exactly the
    solve it used to get.  See :meth:`FreeformLayout._sweep` for why a second
    arrangement is worth a solve.
    """
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        cluster_relation_no_goods=cluster_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None or time_budget_s <= 0:
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    # Determinism is load-bearing for the bake-off: multi-worker CP-SAT would
    # make the A-vs-B comparison noise rather than measurement.
    solver.parameters.num_search_workers = workers
    if deterministic:
        # A single CP-SAT worker removes portfolio races, but a wall-clock
        # cutoff can still return a different incumbent under CPU contention.
        # Deterministic time counts solver work instead, while the wall limit
        # above remains the hard deadline if the machine cannot finish it.
        solver.parameters.max_deterministic_time = min(
            time_budget_s,
            _deterministic_pack_work(len(strips)),
        )
    # A FUNCTION of `arrangement`, never a clock or a counter: two runs of the
    # same sweep must ask for the same arrangements in the same order, or the
    # bake-off is comparing samples rather than strategies.
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement

    # Bound outside the callback: a closure over `built` would carry its
    # `| None` into the class body, where the narrowing above does not reach.
    w_var = built.w_var

    class SeedAdmission(cp_model.CpSolverSolutionCallback):
        """End this solve once its exact incumbent admits the routed seed."""

        def on_solution_callback(self) -> None:
            assert seed is not None
            if seed.width <= _width_slack_cap(self.Value(w_var)):
                self.StopSearch()

    admission = SeedAdmission() if stop_when_seed_admissible and seed is not None else None
    return _pack_result(
        built,
        solver,
        strips,
        direct_candidates,
        height,
        admission,
    ).pack


class _BuildBudgetStage(Enum):
    """The phase whose shared deadline prevented a build attempt from finishing."""

    PREPARATION = "preparation"
    ROUTING = "routing"
    CERTIFICATION = "certification"
    FINALIZATION = "finalization"


@dataclass(frozen=True, slots=True)
class PackAttempt:
    """Complete immutable evidence from one packed-and-routed assignment."""

    origins: tuple[tuple[int, int], ...]
    compact_width: int
    height: int
    outline: tuple[tuple[int, int], ...]
    routing: DetailedRouteResult
    budget_stage: _BuildBudgetStage | None
    static_access: tuple[NetFailure, ...]
    promised_direct: frozenset[routing_domain.DirectInsertId]
    realized_direct: frozenset[routing_domain.DirectInsertId]
    direct_candidates: _DirectCandidateSnapshot
    stranded_ports: tuple[routing_domain.StrandedPort, ...] = ()

    def __post_init__(self) -> None:
        if any(
            failure.kind is not RouteFailureKind.STATIC_ACCESS for failure in self.static_access
        ):
            raise ValueError("PackAttempt.static_access accepts only STATIC_ACCESS failures")
        if self.routing.status is DetailedRouteStatus.BUDGET:
            if self.budget_stage not in (
                _BuildBudgetStage.PREPARATION,
                _BuildBudgetStage.ROUTING,
            ):
                raise ValueError("a routing-budget attempt must name its routing stage")
        elif self.budget_stage in (
            _BuildBudgetStage.PREPARATION,
            _BuildBudgetStage.ROUTING,
        ):
            raise ValueError("only a routing-budget attempt may name a routing stage")
        if (
            self.budget_stage
            in (
                _BuildBudgetStage.CERTIFICATION,
                _BuildBudgetStage.FINALIZATION,
            )
            and self.routing.status is not DetailedRouteStatus.ROUTED
        ):
            raise ValueError("completion-stage evidence requires a fully routed attempt")
        if self.budget_stage is _BuildBudgetStage.PREPARATION and (
            self.routing.routed or self.routing.failures
        ):
            raise ValueError("preparation stopped before routing evidence existed")
        if not self.realized_direct <= self.promised_direct:
            raise ValueError("a realized direct insert must name a rewarded promise")


def _width_slack_cap(compact_width: int) -> int:
    """Return ``ceil(1.10 * compact_width)`` without floating-point drift."""
    if type(compact_width) is not int or compact_width <= 0:
        raise ValueError("compact width must be a positive integer")
    return (11 * compact_width + 9) // 10


def _seed_admission_preserves_best_band(
    seed: routing_domain._Pack,
    minimum_width: int,
    envelope: finalize.BandPolicySearchEnvelope,
) -> bool:
    """Whether stopping at the warm seed cannot forfeit a narrower latitude band."""

    def primary_band(width: int) -> int | None:
        return min(
            (
                candidate.frame.primary_band
                for candidate in envelope.frame_candidates(width, seed.height)
            ),
            default=None,
        )

    seed_band = primary_band(seed.width)
    best_band = primary_band(minimum_width)
    return seed_band is not None and seed_band == best_band


def _proof_scoped_no_goods(
    attempt: PackAttempt,
    strips: list[routing_domain.Strip],
) -> tuple[
    tuple[_DirectRelationNoGood, ...],
    ExactPackNoGood | None,
    tuple[ClusterRelationNoGood, ...],
]:
    """Derive only relation or assignment exclusions proved by this attempt."""
    if not attempt.direct_candidates.matches(strips):
        raise ValueError("direct candidate evidence belongs to a different strip plan")
    direct_candidates = attempt.direct_candidates.candidates
    local: list[_DirectRelationNoGood] = []
    for direct in sorted(attempt.promised_direct - attempt.realized_direct):
        source = direct.source_strip
        destination = direct.destination_strip
        if not 0 <= source < len(attempt.origins) or not 0 <= destination < len(attempt.origins):
            continue
        candidate = direct_candidates.get((source, destination))
        source_origin = attempt.origins[source]
        destination_origin = attempt.origins[destination]
        delta_x = destination_origin[0] - source_origin[0]
        delta_y = destination_origin[1] - source_origin[1]
        structurally_impossible = (
            candidate is None
            or candidate.item != direct.item
            or candidate.cargo_domain is not direct.cargo_domain
            or delta_x not in candidate.origin_deltas
            or not (
                1 <= delta_y + candidate.cons_row - candidate.prod_row <= catalog.SORTER_MAX_REACH
            )
        )
        if structurally_impossible:
            local.append(
                _DirectRelationNoGood(
                    direct_id=direct,
                    delta_x=delta_x,
                    delta_y=delta_y,
                )
            )

    if local:
        return tuple(local), None, ()

    routing = attempt.routing
    if (
        not routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or not routing.failures
        or any(failure.kind is RouteFailureKind.BUDGET for failure in routing.failures)
    ):
        return (), None, ()

    evidence = tuple(
        finalize.ProjectionFailure(
            check="route.exhaustive",
            buildings=(),
            detail=(
                f"{failure.kind.value}: net={failure.net_id!r}; "
                f"wall={failure.wall!r}; blockers={failure.blocking_nets!r}; "
                f"expansions={failure.expansions}"
            ),
            band=0,
        )
        for failure in routing.failures
    )
    # The relaxed cluster run's own proof, which the router could only hand
    # back through the routing report.  It is a REGION exclusion where the
    # exact no-good beside it is a point one, so it is built from the same
    # origins and stands or falls with the same attempt.
    report = routing.last_mile
    cluster_no_good = (
        None
        if report is None or not report.relation_strips
        else last_mile.relation_no_good(
            strips=report.relation_strips,
            origins=attempt.origins,
            outline=attempt.outline,
            height=attempt.height,
            evidence=report.relation_evidence,
        )
    )
    return (
        (),
        ExactPackNoGood(
            height=attempt.height,
            outline=attempt.outline,
            width=attempt.compact_width,
            origins=attempt.origins,
            evidence=evidence,
        ),
        () if cluster_no_good is None else (cluster_no_good,),
    )


def _attempt_feedback_state(
    attempt: PackAttempt,
    previous: FeedbackState | None,
) -> FeedbackState:
    """Accumulate immutable failed-net, blocker, and hot-wall evidence."""
    outline = (attempt.compact_width, attempt.height)
    state = FeedbackState.empty(outline) if previous is None else previous.for_outline(outline)
    return update_feedback(
        state,
        attempt.routing,
        origins=attempt.origins,
    )


def _feedback_retry_eligible(
    attempt: PackAttempt,
    feedback: FeedbackState,
) -> bool:
    """Whether this exact attempt earned one bounded evidence-driven retry.

    THE "EXACTLY ONE FAILURE" CONJUNCT IS GONE.  It was written for a near miss
    and it excluded every cell this program still refuses: R2 §4 measured
    `universe-matrix/all-products` at 3 failures and `output-products` at 6, so
    the retry -- and with it the Phase C window, whose launch is downstream of
    this -- never fired on the specs it was built for.  What the predicate is
    really asking is whether the sweep LEARNED something aimable: a failure the
    feedback state can weight and whose endpoints it knows.  One such failure is
    as aimable as one of six.
    """
    routing = attempt.routing
    if (
        routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or not routing.failures
    ):
        return False
    return any(
        failure.net_id in feedback.net_weight and failure.net_id in feedback.endpoint_offsets
        for failure in routing.failures
    )


@dataclass(slots=True)
class _BuildResult:
    placement: Placement | None
    routing: DetailedRouteResult
    budget_stage: _BuildBudgetStage | None
    towers: tuple[PlacedBuilding, ...]
    promised_direct: frozenset[routing_domain.DirectInsertId] = frozenset()
    realized_direct: frozenset[routing_domain.DirectInsertId] = frozenset()
    stranded_ports: tuple[routing_domain.StrandedPort, ...] = ()
    preparation_time_s: float = 0.0
    detailed_route_time_s: float = 0.0


def _build(
    spec: BuildSpec,
    strips: list[routing_domain.Strip],
    pack: routing_domain._Pack,
    *,
    power: bool,
    route: bool,
    policy: BandPolicy,
    belt_rules: catalog.BeltAltitudeRules = routing_domain._DEFAULT_BELT_RULES,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    staged_static_cache: routing_domain._StagedStaticCache | None = None,
) -> _BuildResult:
    """Prepare one pack, then emit it through the reusable detailed entry point."""
    cancelled = None if deadline is None else lambda: time.monotonic() >= deadline
    preparation_started = time.monotonic()
    try:
        prepared = routing_domain._prepare_routing_problem(
            spec,
            strips,
            pack,
            power=power,
            policy=policy,
            _reserve_ports=route,
            belt_rules=belt_rules,
            staged_static_cache=staged_static_cache,
            cancelled=cancelled,
            deadline=deadline,
        )
    except routing_domain._PreparationDeadline, finalize.ProjectionCancelled:
        return _BuildResult(
            placement=None,
            routing=DetailedRouteResult(
                DetailedRouteStatus.BUDGET,
                (),
                (),
                0,
                0,
            ),
            towers=(),
            budget_stage=_BuildBudgetStage.PREPARATION,
            preparation_time_s=time.monotonic() - preparation_started,
        )
    preparation_time_s = time.monotonic() - preparation_started
    if cancelled is not None and cancelled():
        return _BuildResult(
            placement=None,
            routing=DetailedRouteResult(
                DetailedRouteStatus.BUDGET,
                (),
                (),
                0,
                0,
            ),
            towers=(),
            budget_stage=_BuildBudgetStage.PREPARATION,
            stranded_ports=prepared.stranded_ports,
            preparation_time_s=preparation_time_s,
        )
    built = _build_prepared(
        spec,
        strips,
        prepared,
        power=power,
        route=route,
        deadline=deadline,
        budget=budget,
    )
    return replace(
        built,
        preparation_time_s=preparation_time_s,
    )


def _build_prepared(
    spec: BuildSpec,
    strips: list[routing_domain.Strip],
    prepared: routing_domain._PreparedRoutingProblem,
    *,
    power: bool,
    route: bool,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    prioritize_source_families: bool = True,
) -> _BuildResult:
    """Emit, route, and power one already-prepared immutable problem."""
    prelinked_routed = tuple(net.net_id for net in prepared.nets if net.prelinked) if route else ()
    workspace = prepared.routing_problem().new_workspace()
    canvas = workspace.canvas
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    external_nets = [
        net
        for net in workspace.nets
        if net.net_id is not None and net.net_id.role is NetRole.EXTERNAL
    ]
    external_entry_counts: dict[str, int] = defaultdict(int)
    for net in external_nets:
        external_entry_counts[net.item] += 1
    route_nets = [
        net
        for net in workspace.nets
        if net.net_id is not None and net.net_id.role is not NetRole.EXTERNAL
    ]
    early_output_nets = [
        net
        for net in workspace.external_output_nets
        if net.net_id not in prepared.late_output_net_ids
    ]
    late_output_nets = [
        net for net in workspace.external_output_nets if net.net_id in prepared.late_output_net_ids
    ]

    empty_routing = DetailedRouteResult(
        DetailedRouteStatus.ROUTED,
        (),
        (),
        0,
        0,
        exhaustive=True,
    )
    external_routing = empty_routing
    early_output_routing = empty_routing
    internal_routing = empty_routing
    late_output_routing = empty_routing

    detailed_route_started = time.monotonic()
    if route and prepared.preparation_failures:
        internal_routing = DetailedRouteResult(
            DetailedRouteStatus.STRANDED,
            (),
            prepared.preparation_failures,
            0,
            0,
        )
    else:
        # Inputs and pure outputs retain first claim on routing space. An
        # output lane that also feeds an internal consumer is continued only
        # after that internal graph exists, from its downstream surplus tail.
        if route:
            external_routing = routing_domain._route_external_inputs(
                canvas,
                external_nets,
                belt_id,
                belt_model,
                prepared.core,
                deadline,
                budget,
            )
            early_output_routing = routing_domain._route_external_outputs(
                canvas,
                early_output_nets,
                belt_id,
                belt_model,
                prepared.core,
                deadline,
                budget,
            )

    if route and route_nets and not prepared.preparation_failures:
        internal_routing = routing_domain._route_all(
            canvas,
            route_nets,
            belt_id,
            belt_model,
            prepared.route_bounds,
            deadline,
            budget,
            prepared.power_sites if power else None,
            prepared.junction_frame_bans,
            prioritize_source_families=prioritize_source_families,
        )

    if (
        route
        and late_output_nets
        and not prepared.preparation_failures
        and external_routing.status is DetailedRouteStatus.ROUTED
        and early_output_routing.status is DetailedRouteStatus.ROUTED
        and internal_routing.status is DetailedRouteStatus.ROUTED
    ):
        late_output_routing = routing_domain._route_external_outputs(
            canvas,
            routing_domain._output_tail_nets(canvas, late_output_nets),
            belt_id,
            belt_model,
            prepared.core,
            deadline,
            budget,
        )
    detailed_route_time_s = time.monotonic() - detailed_route_started

    failures = (
        external_routing.failures
        + early_output_routing.failures
        + internal_routing.failures
        + late_output_routing.failures
    )
    routing_status = (
        DetailedRouteStatus.BUDGET
        if any(
            result.status is DetailedRouteStatus.BUDGET
            for result in (
                external_routing,
                early_output_routing,
                internal_routing,
                late_output_routing,
            )
        )
        else (DetailedRouteStatus.STRANDED if failures else DetailedRouteStatus.ROUTED)
    )
    routing = DetailedRouteResult(
        status=routing_status,
        routed=(
            prelinked_routed
            + external_routing.routed
            + early_output_routing.routed
            + internal_routing.routed
            + late_output_routing.routed
        ),
        failures=failures,
        iterations=internal_routing.iterations,
        expansions=(
            external_routing.expansions
            + early_output_routing.expansions
            + internal_routing.expansions
            + late_output_routing.expansions
        ),
        exhaustive=(
            prepared.preparation_exhaustive
            if prepared.preparation_failures
            else (
                external_routing.exhaustive
                and early_output_routing.exhaustive
                and internal_routing.exhaustive
                and late_output_routing.exhaustive
            )
        ),
        last_mile=combine_last_mile_reports(
            (
                external_routing.last_mile,
                early_output_routing.last_mile,
                internal_routing.last_mile,
                late_output_routing.last_mile,
            )
        ),
    )
    if routing.status is DetailedRouteStatus.BUDGET:
        return _BuildResult(
            placement=None,
            routing=routing,
            towers=(),
            budget_stage=_BuildBudgetStage.ROUTING,
            promised_direct=prepared.promised_direct,
            realized_direct=prepared.realized_direct,
            stranded_ports=prepared.stranded_ports,
            detailed_route_time_s=detailed_route_time_s,
        )

    # Reservations and tentative markers are attempt-local and are spent before
    # the held power sites become buildings.
    routing_domain._CorridorReservations(canvas).finish()
    for cell in [c for c, owner in canvas.blocked.items() if owner == routing_domain._TENTATIVE]:
        del canvas.blocked[cell]
    canvas.keep_out.clear()
    tower_start = len(canvas.buildings)
    if power and not routing.failed_count:
        routing_domain._place_power(canvas, prepared.power_sites)
    towers = tuple(canvas.buildings[tower_start:])

    # Slot indices are geometry, so they are derived here once rather than at
    # each of the several places a sorter gets created. Every sorter this
    # strategy emitted before carried a defaulted zero in all four fields, which
    # the game rejects outright.
    #
    # A sorter whose slot cannot be derived is a REFUSAL, not a crash and not a
    # guess. The one case that reaches this today is a Spray Coater: it ships
    # zero slot poses, and `BuildTool_Inserter` will not even let a sorter
    # target a building with none, so the connection this strategy wants does
    # not exist in the game. Refusing says so; emitting an index the game never
    # writes would not.
    try:
        wired = assign_sorter_slots(canvas.buildings)
    except SlotUndetermined as exc:
        raise NoValidLayout(f"a sorter's slot could not be derived: {exc}") from exc

    placement = Placement(
        buildings=wired,
        description=f"flab2bp freeform layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            # Match `flow.external_entry_points`: only items with at least two
            # physical entry roots count, using the fastest researched belt's
            # cargo rate times the incoming stack and exact ceiling division.
            # `planning_stack(..., external=True)` is the spec-side counterpart
            # of the validator's derived `Context.stack_of` for an entry run.
            "entry_lanes_needed": float(
                sum(
                    max(
                        1,
                        lanes_for(
                            demand,
                            spec.lane_capacity * spec.planning_stack(item, external=True),
                        ),
                    )
                    for item, demand in spec.external_inputs.items()
                    if external_entry_counts[item] >= 2
                )
            ),
            "machines": float(spec.machine_count),
            "pilers": float(sum(b.item_id == catalog.PILER_ID for b in wired)),
            "strips": float(len(strips)),
            "sorters": float(prepared.sorters),
            "towers": float(len(towers)),
            "spray_coaters": float(prepared.coaters),
            "nets": float(len(route_nets)),
            "routed": float(len(internal_routing.routed)),
            "route_failures": float(routing.failed_count),
            "repair_iterations": float(routing.iterations),
            "belt_tiles": float(canvas.buildings.count_by_kind(BuildingKind.BELT)),
            "direct_inserts": float(prepared.direct_inserts),
            # Combined across the four sub-routings, not just the interior
            # one: each of them runs a last-mile pass of its own, and reading
            # one makes every counter under-read by whatever the other three
            # did.  Identical today because only `_route_all` reports.
            **_last_mile_stats(routing.last_mile),
        },
    )
    placement = retier_belts(placement, spec)
    return _BuildResult(
        placement=placement,
        routing=routing,
        towers=towers,
        budget_stage=None,
        promised_direct=prepared.promised_direct,
        realized_direct=prepared.realized_direct,
        stranded_ports=prepared.stranded_ports,
        detailed_route_time_s=detailed_route_time_s,
    )


def _last_mile_stats(report: LastMileReport | None) -> PlacementStats:
    """Flatten the last-mile report so both strategies report it identically."""
    if report is None:
        return {
            "last_mile_invocations": 0.0,
            "last_mile_solved": 0.0,
            "last_mile_proved": 0.0,
            "last_mile_bounded": 0.0,
            "last_mile_commit_rejected": 0.0,
            "last_mile_restore_mismatch": 0.0,
            "last_mile_relation_skipped_siblings": 0.0,
            "last_mile_nodes": 0.0,
            "last_mile_expansions": 0.0,
            "last_mile_seconds": 0.0,
            "last_mile_relation_strips": 0.0,
        }
    return {
        "last_mile_invocations": float(report.invocations),
        "last_mile_solved": float(report.solved),
        "last_mile_proved": float(report.proved),
        "last_mile_bounded": float(report.bounded),
        "last_mile_commit_rejected": float(report.commit_rejected),
        "last_mile_restore_mismatch": float(report.restore_mismatch),
        "last_mile_relation_skipped_siblings": float(report.relation_skipped_siblings),
        "last_mile_nodes": float(report.nodes),
        "last_mile_expansions": float(report.expansions),
        "last_mile_seconds": report.seconds,
        "last_mile_relation_strips": float(len(report.relation_strips)),
    }


def _drainable_by_port(strip: routing_domain.Strip) -> bool:
    """Can every output lane claim a distinct port facing the lane band?

    The raw, unfloored count: unlike the planner's `_logical_strip_plans`,
    which floors a zero to "try one lane anyway" because it needs a strip to
    exist before anything can be refused, this is the refusal itself, so a
    true zero must stay zero -- flooring it would make `0 <= 0` read True.
    """
    capacity = slots.drain_dock_count(strip.item_id, strip.yaw)
    return bool(strip.out_lanes) and len(strip.out_lanes) <= capacity


def _feedable_by_port(strip: routing_domain.Strip) -> bool:
    """Can each input lane branch through a distinct east-facing prefab port?"""
    probe = slots.probe_building(strip.item_id, strip.yaw)
    docks = slots.port_docks(probe).values()
    capacity = sum(
        dock.facing is Facing.EAST
        and routing_domain._port_approach_offset(probe, dock, strip.pw) is not None
        for dock in docks
    )
    lanes = strip.in_above + strip.in_below
    return (
        bool(lanes)
        and all(len(lane) == 1 for lane in lanes)
        and len(lanes) <= capacity
        and (not strip.out_lanes or _drainable_by_port(strip))
    )


def _machines_without_poses(strips: list[routing_domain.Strip]) -> list[str]:
    """Lanes seated where no sorter of any tier can join them to their machine.

    Three shapes, and they are worth telling apart in the message because they
    call for different fixes.

    THE MACHINE HAS NO INSERT POSE AT ALL.  ``slots.attachment`` reads the
    game's own ``PrefabDesc.slotPoses``, and for a Ray Receiver and an Energy
    Exchanger that array has LENGTH ZERO.  ``BuildTool_Inserter`` will not
    target a building with no pose, so no sorter can attach to one on any face
    at any distance.  ``Strip.input_lane_tiles`` correctly returns 0 for such a
    machine, ``_emit_strip`` then built that row as an empty lane, and ``feed``
    indexed its head -- ``IndexError: list index out of range``.  The OUTPUT
    side did not even crash: ``_link_lane`` finds no usable column, places
    nothing and returns 0, so the machine shipped joined to nothing at either
    end.  That is the shape spine measured on the mode-driven spec -- two Energy
    Exchangers and ZERO sorters in the whole placement, which `validate` called
    ok.

    THE LANE IS SIMPLY TOO FAR from the nearest pose.  A machine's poses are not
    on its footprint edge in general, so a lane that looks two rows clear can be
    three or four tiles from anything a sorter can anchor on, and every tier
    reaches exactly ``SORTER_MAX_REACH``.  Over the 36 corpus specs this is 31
    lanes; the old edge-row arithmetic charged 24 of them a span of 3 -- legal,
    so a sorter was emitted that could not reach -- and the other 7 a span of 4,
    which is `ValueError: span 4 outside 1..3` and is the crash every
    `universe-matrix` stress cell reported.

    THE LANES HAVE POSES BUT NO COMPLETE DISTINCT-SLOT ASSIGNMENT.  Variant
    generation matches every logical item across all lane rows before accepting
    a pose.  If that matching fails, no physical variant exists: falling back to
    each row's first attachment would put multiple sorters in one machine slot,
    and the game would evict all but the last connection written there.

    THE MESSAGE NEVER QUOTES A DISTANCE, because it has none to quote.
    ``sorter_span`` reads the slot table through ``slots.attachment``, which has
    already rejected anything outside ``1..SORTER_MAX_REACH``, so the only
    failing value it can return is 0 -- meaning nothing anchorable was found at
    all, not a measured four tiles.  Printing that 0 as a distance is what made
    the ``organic-crystal`` refusal read "0 tile(s) ... past the 3-tile reach".
    ``_side_lane_caps`` now keeps seating inside what the poses reach, so this
    is a guard against a future seating bug rather than a routine outcome.

    A sorterless belt-port host is not a refusal when every lane can claim an
    authoritative dock.  Output docks merge into their lane; input docks branch
    from their shared lane through explicit splitters, because a belt tile has
    only one output link.

    Returns one description per distinct offending building and combined lane
    role, empty when every lane in the plan can be joined to its machine.
    """
    reach = catalog.SORTER_MAX_REACH
    seen: set[tuple[int, str, int]] = set()
    out: list[str] = []
    for s in strips:
        if s.port_dock_plan and not s.in_lanes and len(s.port_dock_plan) == len(s.out_lanes):
            continue
        if s.lane_plan is None:
            if s.flank_outputs:
                continue
            building = catalog.building(s.item_id)
            if s.takes_belt_ports and not s.in_lanes and s.out_lanes and _drainable_by_port(s):
                continue
            if s.takes_belt_ports and s.in_lanes and _feedable_by_port(s):
                continue
            kinds = tuple(
                kind
                for kind, present in (
                    ("ingredient", bool(s.in_lanes)),
                    ("output", bool(s.out_lanes)),
                )
                if present
            )
            if not kinds:
                continue
            kind_phrase = " and ".join(kinds)
            key = (s.item_id, kind_phrase, 0)
            if key in seen:
                continue
            seen.add(key)
            if s.takes_belt_ports and s.in_lanes and s.out_lanes and not _drainable_by_port(s):
                out.append(
                    f"{building.name} ({s.recipe_id}): its "
                    f"{len({(i, d) for i, _dest, d in s.out_lanes})} distinct output "
                    f"cargo(es) cannot claim distinct docks facing the lane band "
                    f"from its {len(building.port_poses)} belt port(s)"
                )
            elif s.takes_belt_ports and s.in_lanes:
                out.append(
                    f"{building.name} ({s.recipe_id}): its ingredient lanes cannot "
                    f"claim distinct east-facing input docks from its "
                    f"{len(building.port_poses)} belt port(s) while preserving one "
                    "legal splitter-backed fan-out per machine"
                )
            elif s.takes_belt_ports:
                out.append(
                    f"{building.name} ({s.recipe_id}): none of its "
                    f"{len(building.port_poses)} belt port(s) faces the output "
                    "lane below the machine band"
                )
            else:
                out.append(
                    f"{building.name} ({s.recipe_id}): its {kind_phrase} lanes "
                    "cannot be assigned distinct legal sorter slots across all "
                    "lanes; a machine slot holds one connection"
                )
            continue
        rows: list[tuple[int, str]] = [(j, "ingredient") for j in range(len(s.in_above))]
        rows += [(s.row_of_output(k), "output") for k in range(len(s.out_lanes))]
        rows += [(s.row_of_input(lane[0]), "ingredient") for lane in s.in_below]
        for row, kind in rows:
            span = s.sorter_span(row)
            if 1 <= span <= reach:
                continue
            key = (s.item_id, kind, span)
            if key in seen:
                continue
            seen.add(key)
            building = catalog.building(s.item_id)
            name = building.name
            if not building.slot_poses:
                out.append(
                    f"{name} ({s.recipe_id}): the game's prefab gives it no "
                    f"insert pose on any face and {len(building.slots)} belt "
                    f"port(s), so its {kind} lane cannot be joined to it by a "
                    f"sorter -- it takes a belt docked into a port, which "
                    f"neither strategy emits"
                )
            else:
                out.append(
                    f"{name} ({s.recipe_id}): its {kind} lane is seated on row "
                    f"{row}, which has no insert pose within the {reach}-tile "
                    "reach of any sorter tier on any column of the machine"
                )
    return out


def fallback_placement(
    spec: BuildSpec,
    *,
    band_policy: BandPolicy,
    power: bool = True,
    belt_rules: catalog.BeltAltitudeRules = routing_domain._DEFAULT_BELT_RULES,
) -> Placement:
    """One strip per group, stacked vertically.  NOT a usable layout.

    It cannot fail to *construct*, which is a different and much weaker property
    than the "always valid" it was once documented with.  It calls
    ``_build(route=False)``: it never attempts the wiring, so it cannot report
    that the wiring is impossible, and on real specs it is not routable.  That
    is why :class:`FreeformLayout` no longer falls back to it -- returning it
    when the solver found nothing returned a smaller *broken* layout in place of
    an honest refusal.

    Kept only because :mod:`flab2bp.layout.packsolver`, the rejected
    PackingSolver experiment, still calls it.  Do not add callers; if you want
    the construction for its bounding value, use :func:`_greedy_pack`, which is
    what :func:`_pack` warm-starts from.
    """
    strips = plan_strips(
        spec,
        strip_len=max(1, spec.machine_count),
        band_policy=band_policy,
    )
    at: dict[int, tuple[int, int]] = {}
    y = 0
    for i, s in enumerate(strips):
        at[i] = (0, y)
        y += s.height + MARGIN
    width = max((s.width for s in strips), default=1) + MARGIN
    pack = routing_domain._Pack(at=at, width=width, height=y, status="fallback")
    result = _build(
        spec,
        strips,
        pack,
        power=power,
        route=False,
        policy=band_policy,
        belt_rules=belt_rules,
    )
    assert result.routing.status is DetailedRouteStatus.ROUTED
    placement = result.placement
    assert placement is not None
    placement.stats["fallback_used"] = 1.0
    placement.stats["solver_status"] = 0.0
    # The fallback stacks strips vertically without ever asking whether two of
    # them could sit within sorter reach, so it direct-inserts nothing. `_build`
    # already reported 0; this stays only to keep the key present when a caller
    # reads the fallback's stats without checking `fallback_used` first.
    placement.stats.setdefault("direct_inserts", 0.0)
    placement.stats["direct_insert_candidates"] = 0.0
    placement.stats["hit_time_budget"] = 0.0
    placement.stats["area"] = float(placement.area)
    return placement


type _RefusalFinding = str | validate.Finding | finalize.ProjectionFailure


def _retain_refusal(
    rejected: list[_RefusalFinding],
    finding: _RefusalFinding,
) -> None:
    """Keep authoritative findings in first-seen order without duplicates."""
    if finding not in rejected:
        rejected.append(finding)


def _port_seating_refusal(attempts: Sequence[PackAttempt]) -> str | None:
    """The refusal for a sweep whose router never ran, or ``None``.

    Every retained attempt failed at PREPARATION with static access only and
    expanded zero A* nodes: `_build` substitutes a synthetic STRANDED result and
    skips routing entirely when `prepared.preparation_failures` is non-empty, so
    "the packer produced packs its own router cannot wire" is false twice over --
    nothing was routed and the packer is blameless.  Measured on all three
    freeform `universe-matrix` cells at `e0bf432` (R2 §3, R4 §1).

    Logical identity is ``(instance_id, lane_id)``.  ``instance_id`` is the
    stable family/machine-range identity of one physical strip, so two shards of
    the same group remain distinct; ``lane_id`` is placement-independent, so
    moving that lane's port cell on another attempt does not multiply it.  The
    first attempt is the representative for held/wants/options detail, keeping
    the diagnostic reproducible.
    """
    if not attempts:
        return None
    for attempt in attempts:
        if attempt.routing.expansions:
            return None
        if not attempt.routing.failures:
            return None
        if any(
            failure.kind is not RouteFailureKind.STATIC_ACCESS
            for failure in attempt.routing.failures
        ):
            return None
    ports: dict[tuple[StripInstanceId, str], routing_domain.StrandedPort] = {}
    for attempt in attempts:
        for port in attempt.stranded_ports:
            ports.setdefault((port.instance_id, port.lane_id), port)
    if not ports:
        return None
    named = ", ".join(
        f"{port.item} into {port.strip_label} at {port.cell} "
        f"(wants {port.wants}, held {port.held}, {port.options} free side(s))"
        for port in sorted(
            ports.values(),
            key=lambda port: (
                port.strip_label,
                port.item,
                port.instance_id,
                port.lane_id,
                port.cell,
            ),
        )[:3]
    )
    counts = {
        len({(port.instance_id, port.lane_id) for port in attempt.stranded_ports})
        for attempt in attempts
    }
    same = (
        f"every candidate height produced the same {next(iter(counts))} failures"
        if len(counts) == 1
        else "the failure count varied by candidate height"
    )
    port_count = len(ports)
    lane_noun = "lane head" if port_count == 1 else "lane heads"
    return (
        f"no pack was ever routed: {port_count} {lane_noun} could not obtain the "
        f"belt approaches they need ({named}); this is a PORT-SEATING defect "
        f"independent of the packing -- {same}"
    )


def _routing_failure_bound(attempts: Sequence[PackAttempt]) -> str | None:
    """Name what the retained routing attempts prove, without blaming all packing.

    A packer's coordinates move between candidate heights, but logical recipe
    edges survive repacking.  Recurring failures identify a net-level target;
    changing failures identify the searched assignments, not a proof that the
    spec is impossible.  BUDGET stays separate from geometry evidence.

    This is deliberately a diagnostic bound, not a new search rule.  The
    archived mall/all-products block-20 evidence proves that routed packs were
    refused, but did not retain their per-attempt identities or failure kinds.
    Widening the sweep around an unnamed invariant would therefore be tuning.
    """
    routed = tuple(
        attempt
        for attempt in attempts
        if attempt.routing.failures and attempt.budget_stage is not _BuildBudgetStage.PREPARATION
    )
    if not routed:
        return None

    kind_counts: dict[RouteFailureKind, int] = defaultdict(int)
    logical_by_attempt: list[set[LogicalNetId]] = []
    for attempt in routed:
        logical_by_attempt.append({failure.net_id.logical for failure in attempt.routing.failures})
        for failure in attempt.routing.failures:
            kind_counts[failure.kind] += 1
    kinds = ", ".join(
        f"{kind.value}={count}"
        for kind, count in sorted(kind_counts.items(), key=lambda pair: pair[0].value)
    )
    heights = ", ".join(str(height) for height in sorted({attempt.height for attempt in routed}))
    evidence = (
        f"route evidence from {len(routed)} packs at candidate heights {heights}: "
        f"failure kinds {kinds}; "
    )
    if set(kind_counts) == {RouteFailureKind.BUDGET}:
        return (
            evidence + "every failure is BUDGET, so this is a ROUTING-CLOCK bound and not "
            "a verdict on the packing"
        )
    if RouteFailureKind.BUDGET in kind_counts:
        return (
            evidence + "BUDGET and non-budget failures coexist; the routing clock must "
            "be separated from geometry before assigning a cause"
        )
    if len(routed) == 1:
        return (
            evidence + "one routed pack is insufficient to distinguish a recurring net "
            "from a density/search-space defect"
        )

    common = set.intersection(*logical_by_attempt)
    if common:
        logical = min(common, key=repr)
        return (
            evidence + f"the same logical net {logical.item}/{logical.role.value} failed "
            "in every retained pack; investigate that NET-LEVEL routing constraint, "
            "not a wholesale packing impossibility"
        )
    return (
        evidence + "no logical net failed in every retained pack; investigate the "
        "DENSITY/SEARCH-SPACE explored, not a proved impossibility"
    )


def _refusal_summary(rejected: Sequence[_RefusalFinding]) -> str:
    """List concise checks first, then the structured records that explain them."""
    checks: list[str] = []
    records: list[str] = []
    for finding in rejected:
        check = finding if isinstance(finding, str) else finding.check
        if check not in checks:
            checks.append(check)
        if isinstance(finding, finalize.ProjectionFailure):
            records.append(
                f"band {finding.band} {finding.check} {finding.buildings}: {finding.detail}"
            )
        elif isinstance(finding, validate.Finding):
            record = f"{finding.check} {finding.buildings}: {finding.message}"
            if finding.detail:
                record += f" ({dict(finding.detail)})"
            records.append(record)
    summary = ", ".join(checks)
    return summary + (f"; findings: {'; '.join(records)}" if records else "")


def _portfolio_soft_deadline(
    soft: float,
    external_key: tuple[int, int] | None,
    best_key: tuple[int, float] | None,
    now: float,
) -> float:
    """The IMPROVEMENT deadline, which is NEVER this sweep's own ``soft``.

    ``soft`` is the sweep's own share and is what stops it improving; the hard
    ``deadline`` is what stops it entirely.  The value returned here is bound to
    a SEPARATE name and read only at the four sites already guarded by ``best is
    not None`` -- never written back over ``soft``.  Several ``_room_for_another``
    sites have no such guard -- ``projection_retry_affordable``, the
    learned-retry promotion and the window launch -- and all of them are finding
    paths that the soft-deadline breaks deliberately exempt (``if not
    projection_retry and ...``).  Setting ``soft`` itself would refuse every
    retry for the rest of the sweep, and a spec that only routes after a retry
    would then refuse under racing where the unraced arm succeeds -- a refusal
    manufactured by another process.

    A bound WORSE than what this sweep already holds moves nothing: an incumbent
    we have already beaten is not a reason to stop polishing.  Both keys are
    ``(area, belt_tiles)`` in that order, so ``>`` is the same lexicographic rule
    ``best_key`` is selected by.
    """
    if external_key is None:
        return soft
    if best_key is not None and external_key > best_key:
        return soft
    return min(soft, now)


class FreeformLayout:
    """Free-form packing plus belt routing."""

    name = "freeform"

    def __init__(
        self,
        *,
        band_policy: BandPolicy,
        belt_rules: catalog.BeltAltitudeRules,
        strip_len: int = 6,
        workers: int | None = None,
        direct_insert: bool = True,
        arrangements: int | None = None,
        portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
        #: Told what this sweep is doing, for a debugging view.  A SEPARATE
        #: parameter from `publish_incumbent` on purpose: in the raced child
        #: that callback runs a full `validate.validate` before publishing
        #: (strategy_race.py:515-530) because a bound the parent would reject
        #: must not prune the peer -- a cost a picture must never pay -- and it
        #: fires only on an improvement, so it cannot express a pack, a refusal,
        #: or a stranded net.
        observer: SearchObserver | None = None,
    ) -> None:
        self.band_policy = band_policy
        self.belt_rules = belt_rules
        self.strip_len = strip_len
        #: CP-SAT search workers. ``None`` takes the module default (all
        #: cores); the bake-off pins ``DETERMINISTIC_WORKERS``.
        self.workers = DEFAULT_SEARCH_WORKERS if workers is None else workers
        #: Off only for A/B measurement -- the feature is worth having, but
        #: proving it works means comparing against its own absence.
        self.direct_insert = direct_insert
        #: Arrangements per candidate height. ``None`` takes
        #: :data:`_ARRANGEMENTS`, which is the measured default; ``1`` is the
        #: search as it stood before arrangements existed, and is what the A/B
        #: compares against.
        self.arrangements = _ARRANGEMENTS if arrangements is None else arrangements
        #: The best ``(area, belt_tiles)`` another racing strategy has certified,
        #: or ``None``.  A SCHEDULING input only: it never enters ``best_key``,
        #: so it can never select or reject a placement.
        self.portfolio_incumbent = portfolio_incumbent
        #: Called with each placement this sweep certifies, so the other racer
        #: can use it as a bound.
        self.publish_incumbent = publish_incumbent
        self.observer = observer

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        """Return the densest ROUTABLE ``Placement``, or raise :class:`NoValidLayout`.

        Routability is a condition for existing, not a ranking key.  It used to
        be the latter -- packs were ordered ``(routable, area, belt_tiles)`` and
        the least-bad one was returned even when every height failed to wire --
        which meant a pack nothing could connect still came back, still got
        measured, and measured *small*: an unrouted net is a belt run that does
        not exist, so the broken pack has the tighter bounding box and wins.
        That is how a build with 119 unrouted nets scored as the densest
        candidate on offer.

        The old escape hatch, :func:`fallback_placement`, is gone from this path.
        It was documented as routable by construction and is not -- it calls
        ``_build(route=False)``, so it never even attempts the wiring it claims.
        On the calibration spec it returned 3162 tiles against the solver's 2208
        while carrying the same unsourced lanes, so it traded area away for
        nothing.  What replaces it is the shelf packing it was built on, handed
        to :func:`_pack` as a warm start.  It normally bounds the search; the
        first candidate may substitute it only after an exact incumbent proves
        that it fits the same evidence-bound width slack.  It is never used when
        the solve fails.

        ``time_budget_s`` is the wall-clock search deadline for the whole call.
        Every phase takes what is left of exactly the budget the caller asked
        for, and a phase that finds the clock already spent is not started.

        Running out of it RAISES.  A deadline may cost a placement -- and the
        cells it costs are named in the commit message rather than bought back
        by raising the ceiling -- but it can never return a degraded one: the
        clock is only ever read where the answer is "this net did not route",
        and a pack with an unrouted net is discarded, never emitted.
        """
        if time_budget_s <= 0:
            raise NoValidLayout(
                "no time budget was given, so the packer was never asked",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        ceiling = time_budget_s
        started = time.monotonic()
        _PACK_CP_PROFILE.set(_PackCpProfile())
        # A racing child starts the budget its PARENT started, so it must be
        # told the wall rather than compute one: spawn, interpreter start and
        # unpickling the spec all happen after the clock began.  Same expression
        # `sequence_solver._production_run` already uses for the same reason.
        deadline = started + ceiling if absolute_deadline is None else absolute_deadline
        # ONE routing budget for the call. `_MAX_EXPANSIONS` bounds a single
        # search and `_ROUTING_BUDGET` bounded one routing pass; nothing bounded
        # the ten to twenty passes a sweep makes, so the packer could spend it
        # over and over. The wall clock bounds them in seconds; this bounds them
        # deterministically, which is what keeps a re-run reproducible -- and it
        # is scaled to the ceiling so that it stays a backstop rather than
        # becoming the thing that ends the sweep. See
        # `_ROUTING_EXPANSIONS_PER_SECOND`.
        budget = {
            "left": max(
                routing_domain._ROUTING_BUDGET, int(_ROUTING_EXPANSIONS_PER_SECOND * ceiling)
            )
        }

        def planning_cancelled() -> bool:
            return routing_domain._expired(deadline)

        from flab2bp.layout.strip_variants import generate_strip_families

        families = tuple(generate_strip_families(spec))

        try:
            strips = plan_strips(
                spec,
                strip_len=self.strip_len,
                band_policy=self.band_policy,
                families=families,
                cancelled=planning_cancelled,
            )
        except routing_domain._PreparationDeadline as exc:
            raise NoValidLayout(
                "the requested deadline passed while proving strip projection clearance",
                spec_label=spec.label,
                budget_s=time_budget_s,
            ) from exc
        except (ValueError, KeyError) as exc:
            # One retry with every machine of a group on a single strip. That is
            # the coarsest legal strip plan, so if it also fails the spec cannot
            # be turned into strips at all and no budget will change that.
            try:
                strips = plan_strips(
                    spec,
                    strip_len=max(1, spec.machine_count),
                    band_policy=self.band_policy,
                    families=families,
                    cancelled=planning_cancelled,
                )
            except routing_domain._PreparationDeadline as deadline_exc:
                raise NoValidLayout(
                    "the requested deadline passed while proving fallback strip "
                    "projection clearance",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from deadline_exc
            except ValueError, KeyError:
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        # Forty or more physical strips makes preparation and detailed
        # negotiation scale the same logical lanes into hundreds of redundant
        # branch nets. On the stress families this was 40-76 strips and repeated
        # one-net/zero-expansion misses; the same authoritative families
        # partitioned coarsely are 27-46 strips and route in one round.
        # Choose that representation before packing, not as a rescue afterward.
        try:
            strips, _effective_strip_len = _coarsen_saturated_strip_plan(
                spec,
                strips,
                strip_len=self.strip_len,
                band_policy=self.band_policy,
                families=families,
                cancelled=planning_cancelled,
            )
        except routing_domain._PreparationDeadline as exc:
            raise NoValidLayout(
                "the requested deadline passed while proving coarsened strip projection clearance",
                spec_label=spec.label,
                budget_s=time_budget_s,
            ) from exc
        if not strips:
            raise NoValidLayout(
                "the spec contains no machine groups",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        # Refuse a strip plan that no packing can serve BEFORE sweeping heights.
        # This is not an optimisation of the failure path, it is the difference
        # between an error that names the cause and one that blames the packer:
        # The sweep used to retry at a hidden fifteen-second floor and report a
        # generic routing miss. Structural failures are named before the one
        # requested-budget sweep instead.
        #
        # A machine no sorter can attach to is the one structural refusal named
        # before the sweep, because it is not a question about the packing at
        # all: `_emit_strip` crashes on the empty lane it implies, so every
        # later stage would be reporting a symptom of this one.
        unreachable = _machines_without_poses(strips)
        if unreachable:
            raise NoValidLayout(
                "a machine in this spec has lanes to wire and no insert pose to "
                "wire them to, so it would paste joined to nothing. " + "; ".join(unreachable[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )

        planning_time_s = time.monotonic() - started
        budgets = (time_budget_s,)

        #: Ordered authoritative findings from candidates rejected after packing.
        rejected: list[_RefusalFinding] = []
        #: Candidate heights whose greedy seed extent fits no band.  NOT a
        #: rejection: no pack existed to reject.
        skipped_heights: list[int] = []
        sweep_telemetry: dict[str, float | str] = {}
        #: Complete immutable evidence from every pack the sweep routed. Empty
        #: means no pack got that far. Refusal reporting reads counts from the
        #: detailed results without destroying identities Task 10 consumes.
        attempts: list[PackAttempt] = []
        # ONE session for the whole call, so operator credit survives a strip
        # replan and a second arrangement pass.  It dies with this call:
        # nothing here is process-wide, and two `lay_out` calls never share a
        # ledger.
        #
        # ONE REPAIR ARM, because freeform has exactly one repair: the window.
        # `_sweep` never reads `choice.repair` -- it runs `_pack_window`
        # unconditionally -- so a session armed with the shipped PAIR would
        # train its repair ledger on `sequence-reinsert`, an operator with no
        # dispatch here, and `alns_operators` would report `local-exact-pack:0`
        # on a run that did nothing but local exact packs.  The destroy arm is
        # still chosen (spec 5.7: "destroy set from the same selector"); it is
        # the repair that is fixed.
        alns_session = OperatorSession(repair_arms=(RepairOperator.LOCAL_EXACT_PACK,))
        for sweep_s in budgets:
            if routing_domain._expired(deadline):
                break
            try:
                best = self._sweep(
                    spec,
                    strips,
                    sweep_s,
                    deadline,
                    budget,
                    rejected,
                    attempts,
                    skipped_heights=skipped_heights,
                    session=alns_session,
                    telemetry=sweep_telemetry,
                )
            except routing_domain._PreparationDeadline as exc:
                raise NoValidLayout(
                    "candidate PREPARATION deadline passed while applying learned "
                    "projection geometry",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
            if best is not None:
                from flab2bp.layout import route_kernel

                best.stats["route_backend"] = route_kernel.selected_backend()
                best.stats["planning_time_s"] = planning_time_s
                best.stats["total_time_s"] = time.monotonic() - started
                return best

        deadline_expired = routing_domain._expired(deadline)
        completion_expired = deadline_expired and any(
            attempt.budget_stage
            in (
                _BuildBudgetStage.CERTIFICATION,
                _BuildBudgetStage.FINALIZATION,
            )
            for attempt in attempts
        )
        projection_failures = tuple(
            ProjectionFailureRecord(
                finding.band,
                finding.check,
                finding.buildings,
                finding.detail,
            )
            for finding in rejected
            if isinstance(finding, finalize.ProjectionFailure)
        )
        over_band = (
            f"; {len(skipped_heights)} candidate heights were skipped as over-band"
            if skipped_heights
            else ""
        )
        stale_note = (
            f"; the sweep stopped after {int(sweep_telemetry.get('stale_draws', 0))} "
            "draws that produced no new packing"
            if sweep_telemetry.get("stale_stop")
            else ""
        )
        refusal_stats: dict[str, float | str] = {
            **sweep_telemetry,
            "attempts": float(len(attempts)),
            "skipped_heights": float(len(skipped_heights)),
        }
        # A build that WIRED and then failed our own validator is a different
        # defect from one that could not be wired, and saying so is the whole
        # value of checking: "the packer produced packs its own router cannot
        # wire" would be false here and would send the next reader to the packer.
        if rejected and not completion_expired:
            raise NoValidLayout(
                "every packing that wired was rejected by our own validator ("
                + _refusal_summary(rejected)
                + "); a placement that fails validation is refused rather than "
                "returned, because an invalid blueprint pastes and then does not "
                "run" + over_band + stale_note,
                spec_label=spec.label,
                budget_s=budgets[-1],
                projection_failures=projection_failures,
                stats=refusal_stats,
            )
        if deadline_expired:
            # AND IT HAS TO SAY HOW CLOSE THE PACKS CAME, because the clock
            # expiring is not evidence that the clock is what was missing.
            #
            # This message used to assert that the sweep "ran out of clock
            # rather than out of candidates", and it asserted that on no
            # evidence beyond `_expired(deadline)` -- so EVERY refusal whose
            # ceiling elapsed read as a routing-throughput failure, whatever the
            # packs had been doing.  That reading is what a whole line of work
            # was aimed at, and it is not what the numbers say.
            #
            # `universe-matrix/no-proliferator` power=1 under the sequence-pair
            # packer, given 240 seconds -- sixteen times its ceiling -- routed
            # EIGHT packs in 7.0 to 28.4 seconds each and every one of them left
            # between 39 and 138 of its nets unrouted.  Not one was a near miss.
            # The same cell under freeform reaches a pack that wires with zero
            # failures, but only as its FOURTH height, about eighty seconds in.
            # Those two are opposite defects and the old message called them the
            # same thing.
            #
            # So the counts go in the refusal.  A reader can then tell "the
            # sweep never got to the candidate that works" from "every candidate
            # it tried was nowhere near", and aim at the right half of the
            # program.
            routing_attempts = [
                attempt
                for attempt in attempts
                if attempt.budget_stage is not _BuildBudgetStage.PREPARATION
            ]
            preparation_cancellations = len(attempts) - len(routing_attempts)
            completion_stages = tuple(
                dict.fromkeys(
                    attempt.budget_stage.value.upper()
                    for attempt in routing_attempts
                    if attempt.budget_stage
                    in (
                        _BuildBudgetStage.CERTIFICATION,
                        _BuildBudgetStage.FINALIZATION,
                    )
                )
            )
            failed_counts = [attempt.routing.failed_count for attempt in routing_attempts]
            tried = (
                "1 pack was"
                if len(routing_attempts) == 1
                else f"{len(routing_attempts)} packs were"
            )
            if not attempts:
                note = "no pack finished exact preparation inside it"
            elif not routing_attempts:
                noun = "pack" if preparation_cancellations == 1 else "packs"
                note = (
                    f"{preparation_cancellations} {noun} exhausted the deadline "
                    "during exact preparation, before a net set existed to route"
                )
            elif min(failed_counts) == 0:
                completed = " and ".join(completion_stages)
                note = f"{tried} routed in that time and at least one wired every net" + (
                    f", but the deadline passed during {completed}"
                    if completed
                    else ", so the clock is what was missing"
                )
            else:
                note = (
                    f"{tried} routed in that time and the best of them still "
                    f"left {min(failed_counts)} nets unrouted (worst "
                    f"{max(failed_counts)}), so a longer clock alone would not have "
                    "wired this spec"
                )
            if preparation_cancellations and routing_attempts:
                noun = "pack" if preparation_cancellations == 1 else "packs"
                note += (
                    f"; {preparation_cancellations} other {noun} stopped during exact preparation"
                )
            if rejected:
                note += (
                    "; earlier completed packs were also rejected by our own "
                    f"validator ({_refusal_summary(rejected)})"
                )
            # A sweep whose router never ran has a mechanism, and the deadline is
            # not it.  When every retained attempt is a preparation-time static
            # access with zero expansions, say so instead of counting packs that
            # were never routed.
            seating = _port_seating_refusal(attempts)
            if seating is not None:
                note = seating
            note += over_band + stale_note
            raise NoValidLayout(
                f"the {ceiling:g}s deadline passed with no completed packing of "
                f"{len(strips)} strips; {note}. This is a REFUSAL and not a "
                "verdict on the spec",
                spec_label=spec.label,
                budget_s=ceiling,
                projection_failures=projection_failures,
                stats=refusal_stats,
            )
        # "every pack the sweep produced left nets unrouted" is false when no
        # pack was ever produced. `attempts` is empty whenever `_sweep` never
        # got as far as a routed-or-refused candidate, and that has more than
        # one cause: every candidate height's greedy seed skipped as over-band
        # (`skipped_heights`) is one, but `_pack` returning `None` or repeating
        # an already-seen assignment (both `continue`, recording nothing) is
        # another -- and that second kind is a packer failure the seed-gate
        # sentence would misname.  Only claim the seed gate when EVERY
        # candidate that reached it was skipped; otherwise stay neutral and let
        # `over_band` supply whatever skip count there was.
        if attempts:
            bound = _routing_failure_bound(attempts)
            base = bound or (
                f"no packing of {len(strips)} strips could be wired at any candidate "
                "height; retained attempts contain no classifiable routing evidence"
            )
        elif skipped_heights and len(skipped_heights) == len(
            _band_policy_candidate_heights(strips, self.band_policy)
        ):
            base = (
                f"no packing of {len(strips)} strips was ever attempted at any "
                "candidate height; every candidate's greedy seed was skipped before "
                "a pack could be produced"
            )
        else:
            base = f"no pack of {len(strips)} strips was ever produced at any candidate height"
            # AND IT HAS TO SAY WHICH OF THE TWO THINGS THAT MEANS.  A pack
            # solve that returns INFEASIBLE is a verdict on the packing; one
            # that returns UNKNOWN is the solve running out of its own
            # allowance, and the sentence above reads as the first while being
            # true of both.  The user's compressed-mall URL is the second: at 33
            # strips all fifteen candidate solves ended UNKNOWN inside the
            # `_deterministic_pack_work` bound that pack was given -- then a
            # fixed 0.02 units for every size (0.02 is now only its value at
            # the calibrated fifteen-strip size), calibrated on the
            # fifteen-strip cell where a shelf warm start yields an incumbent
            # at once -- and the sweep exhausted its candidates in 1.4s with
            # 28.6s of a 30s ceiling never spent.  Raising that bound to 0.5 on
            # the same spec turns all fifteen UNKNOWNs into four FEASIBLE
            # packs, so the packing was never the thing that could not be
            # found.
            solves = float(refusal_stats.get("pack_cp_solves", 0.0))
            unknown = float(refusal_stats.get("pack_cp_unknown", 0.0))
            if solves and unknown == solves:
                unspent = max(0.0, budgets[-1] - (time.monotonic() - started))
                work = (
                    f", inside the {_deterministic_pack_work(len(strips)):g}-unit "
                    f"deterministic work bound a pack of {len(strips)} strips is given"
                    if len(strips) >= _DETERMINISTIC_PACK_STRIPS
                    else ""
                )
                base += (
                    f"; all {int(solves)} pack solves ended UNKNOWN rather than "
                    f"INFEASIBLE{work}, so the SOLVE gave up before the packing was "
                    f"shown impossible, and {unspent:.1f}s of the {budgets[-1]:g}s "
                    "ceiling went unspent"
                )
        raise NoValidLayout(
            (_port_seating_refusal(attempts) or base) + over_band + stale_note,
            spec_label=spec.label,
            budget_s=budgets[-1],
            stats=refusal_stats,
        )

    def _sweep(
        self,
        spec: BuildSpec,
        strips: list[routing_domain.Strip],
        time_budget_s: float,
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        rejected: list[_RefusalFinding] | None = None,
        attempts: list[PackAttempt] | None = None,
        skipped_heights: list[int] | None = None,
        *,
        session: OperatorSession,
        telemetry: dict[str, float | str] | None = None,
    ) -> Placement | None:
        """Try every candidate height, returning the best FULLY ROUTED placement.

        ``attempts`` collects immutable :class:`PackAttempt` records with the
        exact assignment, full detailed routing, static-access failures, and
        promised-versus-realized direct identities. Refusal reporting derives
        counts from those records rather than reducing evidence to an integer.

        ``None`` means no height produced one -- which is a refusal, not a
        degraded answer.  Packs with unrouted nets are discarded here rather than
        ranked below routed ones, so an unwireable pack can never be what this
        returns, and neither can one our own validator rejects.

        ``rejected`` collects ordered structured findings from placements thrown
        out by self-checks or projected geometry, so a terminal refusal can name
        the broken promise and retain the authoritative record that proved it.

        ``skipped_heights`` collects candidate heights whose GREEDY SEED extent
        fits no band.  They are kept apart from ``rejected`` deliberately: that
        gate fires before `_pack`, so no pack ever existed, and feeding it into
        ``rejected`` made `lay_out` report "every packing that wired was rejected
        by our own validator" for a cell where nothing wired (R1 §0).  The
        POST-pack gate still retains a real pack's rejection.

        ``telemetry`` receives this sweep's counters whatever the outcome, so a
        refusal can carry them.  `best.stats` is stamped only when a placement
        exists, and a refusing cell is precisely the one whose numbers a gate
        needs.

        ``time_budget_s`` bounds the WHOLE sweep, not just CP-SAT.  It used to
        bound only the packing: routing is limited by an expansion count, not a
        clock, so a 1s budget could spend 13.5s and a 4s budget 68.6s -- both on
        specs that then refused.  A caller who says one second and waits over a
        minute has not been given a budget, and the bake-off cannot sweep a
        parameter the code ignores.

        The deadline is polled between search phases and inside preparation,
        routing, compaction, and final projection. An interrupted candidate is
        discarded because a half-routed or half-certified pack is not a result.
        Certification is checked again after it returns, so a completed phase
        that crossed the wall can never install a late placement.
        """
        cancelled = None if deadline is None else lambda: routing_domain._expired(deadline)
        candidates = _direct_insert_candidates(spec)
        # Select the deterministic fallback from the immutable input plan. A
        # geometry replan can split strips, but changing seed policy halfway
        # through this sweep would mix two policies in one fixed height schedule.
        routing_seed_clearance = _routing_seed_clearance(
            strips,
            sprayed_lanes=len(spec.spray_lanes),
        )

        def greedy_seed(height: int) -> routing_domain._Pack:
            if routing_seed_clearance:
                return _greedy_pack(
                    strips,
                    height,
                    route_clearance=routing_seed_clearance,
                )
            return _greedy_pack(strips, height)

        greedy = greedy_seed(_height_seed(strips))
        bound = max(greedy.width, max((w for w, _h in map(_box, strips)), default=1))
        direct_candidate_snapshot = _direct_candidate_snapshot(
            strips,
            spec,
            enabled=self.direct_insert,
        )
        net_candidates = direct_candidate_snapshot.candidates

        # SHORTEST FIRST, and TALLEST-first was tried against it and reverted.
        #
        # The case for reversing rested on a diagnosis that later measurement
        # CONTRADICTED, and it is left here with the correction rather than
        # quietly deleted, because the numbers under it are still real.
        #
        # The story was that the scarce resource is the east-west corridor: a
        # strip's machine band blocks the bottom three levels, so the only way
        # past a strip is the one-row channel on its south face, and a wide pack
        # asks its nets to cross the whole width through those. That is not what
        # the failures are. Flooding from the start cells of failing searches
        # says the median reachable region is ONE CELL -- see
        # `_reserve_port_access`, which now holds the way out of it. Nothing is
        # crossing anything; the source port cannot leave its own access cell. A
        # one-row corridor also carries several belts, not one, since only a
        # machine denies the whole band -- and since `LEVELS` rose to 4 a net
        # can go OVER the strip as well as around it.
        #
        # What the measurement under it DOES show is that some heights wire and
        # others do not, unpredictably, and shortest-first can spend the whole
        # ceiling short of the one that would. Routing every candidate height of
        # `quantum-chip/max-proliferation` with a 20M expansion budget and no
        # clock: h=30 w=104 left two nets unrouted, h=40 w=87 three, h=50 w=61
        # four, h=62 w=52 three, and h=80 w=39 routed EVERY net. It reads as a
        # width story and is not one -- `quantum-chip/no-proliferator` at a fixed
        # w=56 fails 12 nets at h=170, none at h=255 and h=340, and one again at
        # h=595, on a canvas with 33,000 tiles for 40 strips. Which heights wire
        # is a property of the arrangement, not of how much room it has.
        #
        # It measured 60/72 clean at 4s, which is what shortest-first measures,
        # with the refusals shuffled between cells. The gain on `quantum-chip` is
        # paid straight back on `universe-matrix`, whose tall packs are both
        # wider AND slower to route, so the sweep reaches fewer of them. Reverted
        # for want of a number, not for want of a reason: a height ORDER that
        # depended on the strips rather than on a fixed direction is the shape
        # this wants, and nobody has built one.
        #
        # `universe-matrix` is where that would have to pay off and it is not
        # close. With the port exits held, its five candidate heights at 10s of
        # packing each and NO routing clock leave 29, 4, 26, 23 and 10 nets
        # unrouted -- so no order over these five reaches a pack that wires, and
        # each pass costs 25-40 seconds against a ceiling of 15 or 120. All six
        # of its cells refuse at both budgets and they are named in the commit
        # message rather than bought back.
        # SO HERE IS THAT ORDER, AND IT DEPENDS ON THE STRIPS.
        #
        # A fixed band first prefers the greedy envelope with the most exact
        # latitude-padding choices. A zero-headroom envelope can route and only
        # then fail projection; spending a short budget on it prevents a later
        # proved-fit height from running. Within equal projection headroom, and
        # for portable layouts, try the warm-start with the smallest LONGEST
        # AXIS first. The detailed router, boundary projection, and exact
        # validator all traverse a two-dimensional build; bounding the longer
        # realized axis is the deterministic model-derived proxy shared by all
        # three.
        #
        # Measured on `universe-matrix/no-proliferator` power=0, one routing
        # pass per height on a fixed pack, no routing clock:
        #
        #   h= 69  w=361  26.4s      h= 92  w=309  19.0s
        #   h=116  w=255  28.5s      h=145  w=226  17.3s
        #   h=185  w=188   7.5s
        #
        # Its tallest height is its NARROWEST and routes three times faster than
        # the shortest, which the sweep used to try first and never get past.
        # The note above says tall packs here are "both wider AND slower"; the
        # second half is right and the first is backwards, which is how that
        # experiment came out even.
        #
        # The greedy pack is already built per height as `_pack`'s seed, so the
        # order adds no model, solve, candidate, or work.
        heights = list(
            _band_policy_candidate_heights(
                strips,
                self.band_policy,
                route_clearance=routing_seed_clearance,
            )
            if routing_seed_clearance
            else _band_policy_candidate_heights(strips, self.band_policy)
        )
        seeds = {height: greedy_seed(height) for height in heights}
        original_height_ordinal = {height: ordinal for ordinal, height in enumerate(heights)}
        envelope = finalize.band_policy_search_envelope(
            self.band_policy,
            perimeter=routing_domain._ENTRY_RING,
        )
        projection_headroom = {
            height: (
                max(
                    (
                        candidate.added_rows
                        for candidate in envelope.frame_candidates(
                            seeds[height].width,
                            seeds[height].height,
                        )
                    ),
                    default=-1,
                )
                if envelope.band is not None
                else 0
            )
            for height in heights
        }
        heights.sort(
            key=lambda height: (
                -projection_headroom[height],
                max(seeds[height].width, seeds[height].height),
                seeds[height].width,
                seeds[height].height,
                original_height_ordinal[height],
            )
        )
        # AND A CANDIDATE IS A (HEIGHT, ARRANGEMENT) PAIR, NOT A HEIGHT.
        #
        # The note above ends "the lever is the packer's arrangement, not the
        # stopwatch", and this is that lever. The sweep used to try each height
        # once, and when none of them wired, `lay_out`'s retry packed the SAME
        # heights again -- more solver time on the same five arrangements, which
        # the note above `per_solve` shows is actively counterproductive, since a
        # longer solve returns a tighter pack and tighter is harder to wire.
        #
        # Measured instead: at ONE height and ONE WIDTH, two CP-SAT seeds give
        # arrangements that differ in whether the router can wire them, on 21 of
        # 50 height-groups. See `_ARRANGEMENTS` for that measurement, and the
        # note at the top of the loop for what it is and is not worth.
        #
        # Arrangement-outer: every height gets one packing before density
        # alternatives begin.  A stress refusal must not spend the whole clock
        # redrawing one height while a later height is known to route cleanly.
        candidate_packs = [
            (height, arrangement, False)
            for arrangement in range(max(1, self.arrangements))
            for height in heights
        ]
        routed_assignments: set[
            tuple[
                int,
                int,
                tuple[tuple[int, int], ...],
                tuple[tuple[int, int], ...],
            ]
        ] = set()
        projection_no_goods: list[ProjectionNoGood] = []
        projection_no_good_keys: set[ProjectionNoGood] = set()
        minimum_pitch_x: dict[StripPoseId, int] = {}
        minimum_staged_static_clearance: dict[routing_domain.StagedStaticClearanceKey, int] = {}
        exact_no_good_state = _ExactPackNoGoodState()
        feedback_retry_no_goods: dict[tuple[int, int], ExactPackNoGood] = {}
        #: Per-candidate DIVERSIFICATION cuts: the assignments already drawn at
        #: one height, excluded from that height's NEXT arrangement.  Deliberately
        #: NOT in `_ExactPackNoGoodState`: that class is sweep-wide by
        #: construction (`_sweep` reads `tuple(exact_no_good_state.no_goods)` for
        #: every candidate) and its entries are infeasibility PROOFS.  A pack that
        #: failed to route is not proved infeasible -- the same argument the
        #: feedback-retry cut makes for itself -- so the cut lives beside that
        #: state, keyed by `(height, arrangement)`, and never inside it.
        #:
        #: Never applied once a placement exists, so no cell that wires can see
        #: one.  The tuple carries every earlier draw at that height, so
        #: arrangement N + 1 cannot return arrangement N - 1's pack either.
        diversification_no_goods: dict[tuple[int, int], tuple[ExactPackNoGood, ...]] = {}
        staged_static_exact_retries: set[tuple[int, int]] = set()
        direct_relation_no_goods: list[_DirectRelationNoGood] = []
        direct_relation_no_good_keys: set[_DirectRelationNoGood] = set()
        cluster_relation_no_goods: list[ClusterRelationNoGood] = []
        cluster_relation_no_good_keys: set[ClusterRelationNoGood] = set()
        feedback_by_height: dict[int, FeedbackState] = {}
        compact_width_by_height: dict[int, int] = {}
        # This sweep's own share, never more than the CALL has left. A sweep
        # asked for 15s when 3 remain must not spend 15.
        left = time_budget_s if deadline is None else deadline - time.monotonic()
        share = min(time_budget_s, max(left, 0.0))
        if share <= 0:
            return None
        # AND PACKING ONLY GETS PART OF IT.
        #
        # This was `share / len(heights)`, which hands CP-SAT the WHOLE ceiling
        # -- five heights times a fifth of it each -- and leaves routing to run
        # on whatever the deadline had not already spent.  It only ever looked
        # affordable because the first height's routing overran and the other
        # four were never packed.  Measured at a 15s ceiling on
        # `universe-matrix`: one height packed at 3.18s, routed for 11.45s and
        # hit the wall, and the sweep saw a single candidate.
        #
        # Routing is where the answer is, so packing is capped at a fraction and
        # the rest belongs to the router.  Spending longer in CP-SAT is not even
        # free of charge to routing: a longer solve returns a TIGHTER pack, and
        # tighter is harder to wire.  Same 30 height-cells, pack budget varied,
        # generous routing clock -- 0.5s wired 12 of 30, 3.0s wired 6 of 30, and
        # the widths tell the story (`max-proliferation` h=90 power=1: w=134 and
        # 2 nets unrouted at 0.5s, w=83 and 31 unrouted at 3.0s).
        per_solve = share * _PACK_SHARE / max(len(heights), 1)
        # This sweep's SOFT deadline, and the call's HARD one, and they are not
        # the same rule.
        soft = time.monotonic() + share

        best: Placement | None = None
        best_key: tuple[int, float] | None = None
        #: The dearest candidate this sweep has COMPLETED, pack through validate.
        #: Still the charge for the two sites that price a WHOLE candidate they
        #: may not abandon cheaply -- the projection retry and the learned-retry
        #: promotion -- and no longer the charge for the next arrangement.
        dearest_candidate_s = 0.0
        #: Every completed candidate's total, in the same units and measured at
        #: the same place as `dearest_candidate_s`.  `_next_candidate_seconds`
        #: takes their median, which is what the next arrangement is charged
        #: (L5): the maximum prices every later candidate at whichever one
        #: happened to walk into a congestion wall.
        candidate_totals_s: list[float] = []
        #: The dearest POST-PACK REMAINDER this sweep has completed: over the
        #: candidates that finished, the largest value of (that candidate's own
        #: total minus that SAME candidate's own `_pack` seconds).  A windowed
        #: retry is charged for what it actually replaces rather than for a
        #: whole candidate -- the window swaps out the pack and leaves routing,
        #: power, finalize and validate exactly where they were.
        #:
        #: RULING AD: it must be a per-candidate remainder, not
        #: `dearest_candidate_s - dearest_pack_s`.  Those two maxima can belong
        #: to DIFFERENT candidates -- one slow to pack and quick to route, one
        #: the other way round -- and their difference is then an upper bound on
        #: nothing, collapsing toward zero exactly when some candidate's own
        #: post-pack span is the largest thing the sweep has measured.
        dearest_remainder_s = 0.0
        #: This candidate's own `_pack` span, reset when its turn starts and
        #: left at zero for a queued repair, whose pack was already bought.
        candidate_pack_s = 0.0
        pack_time_s = 0.0
        preparation_time_s = 0.0
        detailed_route_time_s = 0.0
        compaction_time_s = 0.0
        finalization_time_s = 0.0
        validation_time_s = 0.0
        #: Completed candidates that never reached `validate.certify` because
        #: they could not have displaced the certified incumbent (L4).
        certify_skipped = 0
        #: Clock left on the CALL's wall when the sweep last declined to start a
        #: candidate, and zero if it never did -- a sweep that ran out of
        #: candidates rather than out of clock has no unspent decision to
        #: report.  This is the currency L5 buys, measured rather than argued.
        budget_unspent_s = 0.0
        #: Window repairs waiting to be evaluated, and the queue that drains
        #: them.  `candidate_packs` is iterated by index and already mutated in
        #: four places; a separate queue adds no fifth mutation.
        window_packs: dict[tuple[int, int], routing_domain._Pack] = {}
        window_queue: list[tuple[int, int]] = []
        #: The choice and the pre-repair metrics that produced each queued pack,
        #: so credit lands on the choice that earned it rather than on whatever
        #: the selector happened to pick last.
        window_choices: dict[tuple[int, int], tuple[OperatorChoice, OperatorMetrics]] = {}
        #: Asked-and-answered windows, so the same question is never put to
        #: CP-SAT twice inside one SWEEP.  `lay_out` runs exactly one sweep
        #: today, so "per sweep" is also "per `lay_out`": this set spans every
        #: replan the sweep makes rather than being scoped inside one.  What the
        #: key MEANS is strip indices, and `replan_strips_for_learned_geometry`
        #: renumbers the strips -- the same `(height, arrangement, window)`
        #: triple names a DIFFERENT question afterwards, so an entry recorded
        #: against the old numbering can refuse a window nobody has asked
        #: against the new one.  Left that way deliberately: refusing a window
        #: costs a repair the sweep might have made and can never produce a
        #: wrong pack, and it is the third thing to clear at the replan --
        #: beside `window_packs` and `window_queue` -- if that miss is measured.
        solved_windows: set[tuple[int, int, frozenset[int]]] = set()
        window_solves = 0
        window_accepted = 0
        window_seconds = 0.0
        window_skipped_no_goods = 0
        window_encode_errors = 0
        evaluations = 0
        #: Fewest unrouted nets any evaluated pack has left.  A window is posed
        #: only against a pack that BEATS it, so one hard CP-SAT second (R3 §4.2)
        #: is never spent on evidence the sweep has already matched.
        best_failed_count = math.inf
        #: Consecutive draws that added no new entry to `routed_assignments`.
        #: Task 11 makes it move; it is published from here so the refused-row
        #: schema does not change again a task later.
        stale_draws = 0
        stale_stop = False
        started_at: float | None = None
        candidate_index = 0

        def _count_window_skips(count: int) -> None:
            nonlocal window_skipped_no_goods
            window_skipped_no_goods += count

        def settle_window_credit(
            height: int,
            arrangement: int,
            *,
            after: OperatorMetrics | None,
            routing_seconds: float,
        ) -> None:
            """Credit the choice that produced this candidate, if there was one.

            ``after`` carries the metrics of the routing pass this candidate
            ACTUALLY RAN, and its ``validator_clean`` is True only where
            `validate.certify` said so -- False for every candidate that never
            reached the certifier (spec 5.7).

            ``after=None`` means no routing evaluation of this candidate is in
            HAND: the wall arrived before its turn came round, or `_build`
            raised before returning a result.  That is a cost with no reward, so
            it is credited unapplied.  It is NOT what a repair that routed and
            was then refused downstream gets: that one was measured, and the
            measurement is what it is paid on.

            One of those raising exits did route.  `finalize.ProjectionRefusal`
            and `_Unseatable` are decided before any net is laid, but
            `_Unpowerable` from `_place_power` is raised AFTER `_build` has
            finished routing (it runs under `if power and not
            routing.failed_count`), and the handler that catches it sits above
            `route_seconds`, so no `DetailedRouteResult` is in scope to settle
            on and that candidate is drained here at zero.  Paying it correctly
            means changing what `_build` hands back on that path, not this call.
            """
            stored = window_choices.pop((height, arrangement), None)
            if stored is None:
                return
            choice, before = stored
            if after is None:
                session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                return
            session.observe(
                choice,
                reward_vector(
                    OperatorOutcome(
                        choice=choice,
                        before=before,
                        after=after,
                        applied=True,
                    )
                ),
                applied=True,
                routing_seconds=routing_seconds,
            )

        from flab2bp.layout import geometry_memo

        staged_static_cache = geometry_memo.for_spec(spec)
        projection_envelope = finalize.band_policy_search_envelope(
            self.band_policy,
            perimeter=routing_domain._ENTRY_RING,
        )

        def strip_outline(pack: routing_domain._Pack) -> tuple[int, int]:
            return _realized_pack_outline(strips, pack)

        compaction_reserve_s = 0.0
        finalize_reserve_s = 0.0
        validation_reserve_s = 0.0

        def projection_retry_affordable() -> bool:
            current_candidate_s = 0.0 if started_at is None else time.monotonic() - started_at
            # A WHOLE candidate, measured whole, so it carries its own completion
            # transforms and the reserves must not be added on top of it.  The
            # maximum stays the charge here on purpose: this is a retry of a
            # candidate that has already spent most of its cost, so the estimate
            # is about THIS candidate rather than about a typical one.
            return _room_for_another(
                deadline,
                soft,
                completion_tail_s=0.0,
                next_candidate_s=max(dearest_candidate_s, current_candidate_s),
            )

        def decline_to_start() -> None:
            """Record the wall clock the sweep is about to hand back.

            Called at every break that refuses to START a candidate, and never
            at one that abandons a candidate already running: the number is
            "budget the sweep chose not to spend", which is the thing L5 is
            trying to make small.  The last such decision wins, and there is at
            most one -- each of these breaks leaves the loop.
            """
            nonlocal budget_unspent_s
            budget_unspent_s = 0.0 if deadline is None else max(0.0, deadline - time.monotonic())

        def band_target_for(height: int, width: int) -> int:
            """Widest core this policy's bands still accept at ``height``, guarded.

            `finalize.band_target_width` raises `ValueError` above
            `finalize.C_BAND_SCAN_MAX` and for a non-positive height or width,
            and a pack's width is not bounded by either.  Neither caller here may
            raise over that: one is the window launch, where a repair attempt must
            never take the whole sweep down, and the other is the metrics closure,
            which runs inside a `finally` where a raise would REPLACE the
            exception already in flight.  Falling back to the input width makes
            the band term inert for that call, which is the same choice the
            sequence-pair arm's own `band_target_for` makes.
            """
            try:
                return finalize.band_target_width(
                    projection_envelope,
                    height=height,
                    width=width,
                )
            except ValueError:
                return width

        def index_strips() -> dict[tuple[StripFamilyId | None, int, int], routing_domain.Strip]:
            return {
                (strip.family_id, strip.machine_start, strip.machines): strip
                for strip in reversed(strips)
            }

        strips_by_instance = index_strips()

        def replan_strips_for_learned_geometry() -> None:
            nonlocal strips, greedy, bound, direct_candidate_snapshot, net_candidates, seeds
            nonlocal strips_by_instance

            replan_strip_len = max(strip.machines for strip in strips)
            strips = plan_strips(
                spec,
                strip_len=replan_strip_len,
                band_policy=self.band_policy,
                minimum_pitch_x=minimum_pitch_x,
                minimum_staged_static_clearance=(minimum_staged_static_clearance),
                cancelled=cancelled,
            )
            strips_by_instance = index_strips()
            greedy = greedy_seed(_height_seed(strips))
            bound = max(
                greedy.width,
                max((w for w, _h in map(_box, strips)), default=1),
            )
            direct_candidate_snapshot = _direct_candidate_snapshot(
                strips,
                spec,
                enabled=self.direct_insert,
            )
            net_candidates = direct_candidate_snapshot.candidates
            seeds = {
                candidate_height: greedy_seed(candidate_height) for candidate_height in heights
            }
            # These proofs carry offsets, widths, or relation rows from the old
            # strip geometry. Exact and projection cuts self-filter by outline or
            # geometry signature; these do not, so retaining them can forbid a
            # relation the widened strip just made feasible.
            feedback_by_height.clear()
            compact_width_by_height.clear()
            direct_relation_no_goods.clear()
            direct_relation_no_good_keys.clear()
            cluster_relation_no_goods.clear()
            cluster_relation_no_good_keys.clear()
            # AND SO DOES EVERY PENDING WINDOW.  A queued repair is a set of
            # origins keyed by STRIP INDEX, and the numbering it was solved
            # against is the numbering this function just replaced: installing
            # one afterwards would seat the new strips at the old strips' places,
            # and settling its credit reads `pack.at` at the new indices, which
            # raises `KeyError` the moment the strip count changes.
            #
            # The choice behind each one is settled FIRST, and unapplied: it
            # bought a CP-SAT solve, so the ledger has to see the cost, and the
            # routing pass it would have been paid on describes a pack that no
            # longer exists.  Settling here is also what keeps the settle to
            # ONE: `settle_window_credit` pops, so the `finally` below the
            # candidate body finds nothing left to pay, and neither does the
            # post-loop drain.
            for pending_height, pending_arrangement in list(window_choices):
                settle_window_credit(
                    pending_height,
                    pending_arrangement,
                    after=None,
                    routing_seconds=0.0,
                )
            window_choices.clear()
            window_packs.clear()
            window_queue.clear()

        try:
            while window_queue or candidate_index < len(candidate_packs):
                # A queued window repair is a candidate that has ALREADY been
                # packed, so it consumes a turn of this loop without consuming a
                # `candidate_packs` slot: the `pop` below is what removed it.
                queued = window_queue.pop(0) if window_queue else None
                if queued is not None:
                    height, arrangement = queued
                    projection_retry = False
                else:
                    height, arrangement, projection_retry = candidate_packs[candidate_index]
                    candidate_index += 1
                # A SECOND deadline, never a replacement for `soft`.  See
                # `_portfolio_soft_deadline` for why rebinding `soft` would let
                # another process refuse this one's retries.
                improvement_soft = _portfolio_soft_deadline(
                    soft,
                    None if self.portfolio_incumbent is None else self.portfolio_incumbent(),
                    best_key,
                    time.monotonic(),
                )
                # Charge the PREVIOUS candidate here, at the one place every path
                # through the body reaches. The body leaves by five different
                # routes -- no pack, unpowerable, unrouted, rejected, kept -- and a
                # cost recorded at only some of them would systematically
                # UNDER-estimate, since the expensive exits are the failures that run
                # a full routing pass into the wall.
                if started_at is not None:
                    candidate_total_s = time.monotonic() - started_at
                    dearest_candidate_s = max(dearest_candidate_s, candidate_total_s)
                    candidate_totals_s.append(candidate_total_s)
                    # The remainder is taken against THIS candidate's own pack,
                    # so it is a span one candidate really ran (Ruling AD) and
                    # never a difference between two different ones.
                    dearest_remainder_s = max(
                        dearest_remainder_s,
                        candidate_total_s - candidate_pack_s,
                    )
                    # CHARGED ONCE.  A turn that never starts a candidate --
                    # the height whose seed no frame can hold `continue`s
                    # BEFORE `started_at` is set below -- would otherwise leave
                    # this pointing at the last candidate that really ran, and
                    # the next turn would charge that candidate a second time
                    # from a later clock.  The maximum absorbed the duplicate;
                    # the median does not, and it is biased upwards.
                    started_at = None
                # WHAT THIS TURN COSTS, in the two halves `_room_for_another`
                # keeps apart: the completion tail, which must fit in full and is
                # a maximum, and the estimate of the turn's own work in front of
                # it, which is a median (L5).
                #
                # The reserves cannot move between here and the point they are
                # read again below -- everything in between is a gate that breaks
                # or continues -- so this is the same sum that check computes.
                completion_tail_s = compaction_reserve_s + finalize_reserve_s + validation_reserve_s
                # AND A QUEUED REPAIR DOES NOT COST A WHOLE CANDIDATE.  A window
                # has already bought this candidate's pack, so what is left to
                # spend on it is route, power, finalize and validate -- the same
                # measured remainder `_window_candidate_seconds` charges on top of
                # the window's own wall.  Charging a queued repair for a whole
                # candidate drops repairs the sweep can plainly afford, and drops
                # them AFTER paying for the CP-SAT solve that produced them.
                #
                # That remainder is measured WHOLE and already contains the
                # completion transforms it ran, so it is charged as the turn's
                # own work with a zero tail; adding the reserves would bill them
                # twice and is the one way this split could tighten a gate it was
                # meant to loosen.
                if queued is not None:
                    turn_tail_s = 0.0
                    turn_candidate_s = dearest_remainder_s
                else:
                    turn_tail_s = completion_tail_s
                    # Capped at the old charge (Ruling D3): a median taken over
                    # totals that each contain their own tail, plus the tail
                    # again, can ask for more than any candidate ever cost.
                    turn_candidate_s = _capped_next_candidate_seconds(
                        _next_candidate_seconds(candidate_totals_s),
                        completion_tail_s=completion_tail_s,
                        dearest_candidate_s=dearest_candidate_s,
                    )
                if best is not None and not _room_for_another(
                    deadline,
                    improvement_soft,
                    completion_tail_s=turn_tail_s,
                    next_candidate_s=turn_candidate_s,
                ):
                    decline_to_start()
                    break
                # A SECOND ARRANGEMENT NORMALLY IMPROVES; ONE STRONG NEAR MISS MAY RESCUE.
                #
                # This is the whole shape of the feature and it was measured into
                # existence rather than designed. Extra arrangements were tried
                # unconditionally first, and on a spec that has not wired anything
                # they buy NOTHING: every refusal on the stress specs reads "the 15s
                # deadline passed", 36 of 36 across ten runs, so the binding
                # constraint there is the clock and another arrangement spends it
                # rather than buying it. Paired, five rounds, `universe-matrix` and
                # `quantum-chip` at budget 4: 8.4 of 12 clean either way, difference
                # exactly 0.00.
                #
                # AND THE EARLIER NUMBER FOR THIS DID NOT SURVIVE THE POWER REWRITE,
                # which is why the gate exists at all. Before `_power_plan` decided
                # coverage in the solve, ungated arrangements measured +1.17 clean
                # cells on the corpus (paired, six rounds, t = +3.80). Re-measured
                # after it: -0.33 (t = -0.79). The rewrite lifted the baseline from
                # 70.0 to 71.8 of 72 and took the headroom with it, so what was a
                # routability lever is now primarily a density one.
                #
                # Where they DO pay is on a spec that has already wired and has clock
                # left, because the sweep keeps the best `(area, belt_tiles)` it has
                # seen and a further arrangement is another draw at a denser one.
                # Tier `large` at budget 60, six paired rounds, 60 of 60 clean in
                # every run of both arms: -1.51% AREA, paired t = -5.26, denser in
                # SIX OF SIX rounds, and per cell denser on 24 of 60 against larger
                # on 1. That costs 2.6x the cell-seconds, which is the trade being
                # made knowingly: `time_budget_s` is an allowance the caller has
                # already agreed to spend, the sweep used to hand most of it back,
                # and density is the objective it is spent on.
                #
                # So the first pass over the heights is exactly what shipped before,
                # and arrangements past it are normally gated TWICE: on having
                # something to improve, and on being able to afford the improvement.
                #
                # `best is None` alone was not enough, and the number that says so
                # was measured at the DEFAULT budget rather than at the budget the
                # density win came from. Nine paired rounds at `--budget 4
                # --jobs 16`, arrangements 3 against 1: -4, 0, 0, 0, 0, -1, +1, 0,
                # -2, a mean of -0.67 cells. The -1.51% area is real and it is a
                # `tier large --budget 60` number; shipping it unconditionally
                # charges budget-4 cells for a budget-60 gain, which is the wrong way
                # round because budget 4 is what the audit runs and what a user gets.
                #
                # THE AFFORDABILITY RULE, and it carries no tuned constant: an
                # improvement arrangement may start only if as much clock remains as
                # the most expensive candidate so far actually took. By the time
                # `best` exists at least one candidate has been packed, routed,
                # powered and validated, so its cost is MEASURED for this spec on
                # this machine rather than guessed -- which is the only honest
                # estimate of what the next one costs, and it self-calibrates across
                # a corpus spanning 1 to 955 machines instead of asking a threshold
                # to span it.
                #
                # It reads on both ends the way the diagnosis says it should. At
                # budget 4 a `universe-matrix` candidate costs ten seconds or more
                # against a sweep share of four, so no improvement arrangement ever
                # starts and the stress cells get back the search they had. At budget
                # 60 a tier-`large` candidate costs a second or two against a share
                # of sixty, so they all run and the density win stands.
                #
                # Measured on both ends after the rule went in, paired and
                # interleaved:
                #
                #   budget 4, jobs 16, full corpus, TWELVE rounds
                #     -3 +1 0 +1 0 0 -1 +2 -4 +2 -1 0
                #     mean -0.25 cells, 95% CI [-1.40, +0.90], median 0, and the
                #     rounds split 4 better / 4 worse / 4 level. INVALID 0 over all
                #     1728 cells. The two specs that carry every refusal are where
                #     the rule has to work and it does: `universe-matrix` refuses 11
                #     times against 10, and `quantum-chip` measured alone at jobs 6,
                #     away from the audit's own CPU contention, is identical on six
                #     of seven rounds.
                #
                #   tier large, budget 60, four rounds
                #     -1.98% AREA, paired t = -5.41, denser in FOUR OF FOUR rounds,
                #     60 of 60 clean in every run of both arms, per cell denser on 21
                #     and larger on 2.
                #
                # So the default is the one both ends support, which is the thing the
                # unconditional version got wrong: it was measured at budget 60 and
                # shipped to budget 4.
                # One bounded exception lets a strong near miss look at the next
                # arrangement for that exact height. The candidate already exists in
                # `candidate_packs`: ordinary improvements still require the measured
                # cost above, while a complete one-net geometric near miss may use any
                # positive hard time left after the completion reserve. The marker
                # preserves that admission through this gate; the hard deadline still
                # applies. A failed admitted retry cannot unlock the height's later
                # arrangements.
                # Once a valid candidate exists, every later base height is an
                # improvement attempt too. Starting one without enough measured
                # clock for a complete candidate can only discard the valid result
                # at the hard deadline; it cannot improve it.
                if (
                    not projection_retry
                    and best is not None
                    and not _room_for_another(
                        deadline,
                        improvement_soft,
                        completion_tail_s=turn_tail_s,
                        next_candidate_s=turn_candidate_s,
                    )
                ):
                    decline_to_start()
                    break
                # A SECOND ARRANGEMENT WITH NOTHING TO IMPROVE USED TO BE A HARD
                # STOP, and it stopped the sweep at slot 6 of 15 with 25 to 28 s
                # of a 30 s ceiling still in hand (R2 §3).  That was right while
                # every later draw was a byte-identical copy of the first; with a
                # diversification cut behind it, a later draw is a genuinely
                # different pack, and the honest stop condition is that the draws
                # have stopped being new.
                #
                # the `_room_for_another` improvement call, the completion-tail
                # check and the hard `remaining <= 0`
                # break all sit immediately BELOW this gate and are unchanged, so
                # a draw this gate now lets through still has to buy its clock
                # from them: it can only ever extend a sweep INSIDE clock it
                # already had.  (The `_room_for_another` call ABOVE this gate is
                # the improvement one, guarded by `best is not None`; it never
                # fires on this path.)
                #
                # `--arrangements` remains the hard cap: `candidate_packs` is not
                # re-seeded, so the continuation cannot draw a slot the caller
                # did not ask for.
                if (
                    not projection_retry
                    and arrangement
                    and best is None
                    and stale_draws >= C_SWEEP_STALE_DRAWS
                ):
                    stale_stop = True
                    break
                # The charge here is the fresh-candidate one under every
                # reachable state: a window launches only from
                # `arrangement == 0`, so every queued turn short-circuits on
                # `and arrangement` before this predicate runs.  It is written as
                # the turn's own pair so the day a window launches from a later
                # arrangement the charge is already right; no fixture can
                # distinguish the two today.
                if (
                    not projection_retry
                    and arrangement
                    and not _room_for_another(
                        deadline,
                        soft if best is None else improvement_soft,
                        completion_tail_s=turn_tail_s,
                        next_candidate_s=turn_candidate_s,
                    )
                ):
                    decline_to_start()
                    break
                # The SOFT deadline stops us IMPROVING, never FINDING. A refusal
                # means the model could not lay the spec out; a sweep's own clock
                # must not be able to manufacture one. Breaking on time alone did
                # exactly that: heights are tried shortest-first and the
                # free-proliferation chain only wires at the tallest, so a 2s budget
                # refused a spec that routes every net cleanly given the chance to
                # reach it.
                if (
                    not projection_retry
                    and best is not None
                    and time.monotonic() >= improvement_soft
                ):
                    decline_to_start()
                    break
                # The HARD deadline is the call's, and it does stop us finding --
                # that is what makes `time_budget_s` a wall rather than a suggestion.
                # `lay_out` turns it into a refusal that names the deadline, so the
                # distinction between "cannot" and "ran out" survives into the error.
                if deadline is not None and deadline - time.monotonic() < completion_tail_s:
                    decline_to_start()
                    break
                seed = seeds[height]
                seed_width, seed_height = strip_outline(seed)
                if not projection_envelope.frame_candidates(
                    seed_width,
                    seed_height,
                ):
                    if skipped_heights is not None and height not in skipped_heights:
                        skipped_heights.append(height)
                    continue
                started_at = time.monotonic()
                candidate_pack_s = 0.0
                remaining = (
                    per_solve if deadline is None else min(per_solve, deadline - time.monotonic())
                )
                if remaining <= 0:
                    decline_to_start()
                    break
                # CP-SAT's multi-worker portfolio changes the returned large-plan
                # arrangement with audit job allocation.  Those 24+ strip cells
                # route in one round from the deterministic seed; pin only their
                # packing solve so jobs=2 and a standalone call ask the same model.
                feedback = feedback_by_height.get(height)
                width_bound = max(bound * 2, 8)
                if feedback is not None and height in compact_width_by_height:
                    width_bound = min(
                        width_bound,
                        _width_slack_cap(compact_width_by_height[height]),
                    )
                retry_no_good = feedback_retry_no_goods.pop((height, arrangement), None)
                exact_pack_no_goods = tuple(exact_no_good_state.no_goods)
                if retry_no_good is not None:
                    exact_pack_no_goods += (retry_no_good,)
                diversification_cuts = diversification_no_goods.pop(
                    (height, arrangement),
                    (),
                )
                if best is not None:
                    # An improvement arrangement draws exactly what it drew
                    # before. The cut exists to escape a repeated FAILING draw;
                    # applying it to a cell that already wired would move area on
                    # a cell that never asked for a second draw.
                    diversification_cuts = ()
                exact_pack_no_goods += diversification_cuts
                # A window repair IS this candidate's pack.  Re-solving it here
                # would throw away the bounded solve that was just paid for and
                # hand routing the same assignment that stranded a net.
                pending_pack = window_packs.pop((height, arrangement), None)
                pack: routing_domain._Pack | None
                if pending_pack is not None:
                    # THE INSTALL SITE, and where `alns_window_accepted` is
                    # counted -- mirroring the sequence-pair arm, so the gate
                    # can read one number across both.  A window that solved
                    # and produced a different pack has not been accepted by
                    # anything yet; it is accepted here, where the sweep hands
                    # it to the pipeline in place of a `_pack` call.
                    window_accepted += 1
                    pack = pending_pack
                else:
                    pack_started = time.monotonic()
                    pack = _pack(
                        strips,
                        height=height,
                        width_bound=width_bound,
                        time_budget_s=remaining,
                        direct_candidates=net_candidates,
                        workers=(1 if len(strips) >= _DETERMINISTIC_PACK_STRIPS else self.workers),
                        deterministic=len(strips) >= _DETERMINISTIC_PACK_STRIPS,
                        seed=seed,
                        arrangement=arrangement,
                        projection_no_goods=tuple(projection_no_goods),
                        exact_pack_no_goods=exact_pack_no_goods,
                        direct_relation_no_goods=tuple(direct_relation_no_goods),
                        cluster_relation_no_goods=tuple(cluster_relation_no_goods),
                        feedback=feedback,
                        stop_when_seed_admissible=(
                            candidate_index == 1
                            and arrangement == 0
                            and not projection_retry
                            and feedback is None
                            and _seed_admission_preserves_best_band(
                                seed,
                                _minimum_pack_width(strips, height),
                                projection_envelope,
                            )
                        ),
                    )
                    candidate_pack_s = time.monotonic() - pack_started
                    pack_time_s += candidate_pack_s
                if pack is None:
                    stale_draws += 1
                    continue
                assignment = (
                    pack.height,
                    pack.width,
                    tuple(_box(strip) for strip in strips),
                    tuple(pack.at[index] for index in range(len(strips))),
                )
                # A retry is useful only when CP-SAT actually moved something.
                # Deterministic short solves can return the same incumbent for two
                # arrangement seeds; routing it again is the same deterministic
                # multi-second search and can consume the candidate that would wire.
                if assignment in routed_assignments:
                    stale_draws += 1
                    continue
                routed_assignments.add(assignment)
                stale_draws = 0
                if best is None:
                    # A queued window repair re-enters this SAME arrangement
                    # after its original pack already populated the next slot.
                    # Preserve that destination's cut; `diversification_cuts`
                    # came from the current slot and cannot recover it.
                    next_candidate = (height, arrangement + 1)
                    prior_destination_cuts = diversification_no_goods.get(
                        next_candidate,
                        (),
                    )
                    diversification_no_goods[next_candidate] = (
                        *prior_destination_cuts,
                        *diversification_cuts,
                        ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=(
                                finalize.ProjectionFailure(
                                    check="pack.diversification",
                                    buildings=(),
                                    detail=(
                                        f"assignment already drawn at height {height} "
                                        f"arrangement {arrangement}; excluded from "
                                        f"arrangement {arrangement + 1} at this height only"
                                    ),
                                    band=0,
                                ),
                            ),
                        ),
                    )
                if (
                    deadline is not None
                    and deadline - time.monotonic()
                    < compaction_reserve_s + finalize_reserve_s + validation_reserve_s
                ):
                    break
                if feedback is None:
                    compact_width_by_height.setdefault(height, pack.width)
                # Route the deterministic warm-start once this exact solve has
                # produced a compact incumbent that admits it under the existing
                # evidence-bound width contract.  The width-36 warm-start routes on
                # the fourteen-strip calibration chain, while continuing to tighten
                # it can replace it with a width-35 arrangement that strands one net.
                #
                # The admission callback stops only this first optimisation once the
                # same exact width proof exists.  It does not add a solve, route,
                # arrangement, worker, or deadline, and the seed REPLACES the
                # candidate rather than acting as the deleted loose fallback.  If
                # the exact incumbent is too narrow to admit the seed, CP-SAT keeps
                # its normal bounded search and the final incumbent is routed.
                #
                # A WINDOW REPAIR IS NOT A FRESH SOLVE and must not be swapped out
                # for the seed.  A budget-stage failure takes no feedback snapshot,
                # so a queued repair can arrive here on the first candidate with
                # `feedback is None` still true -- and replacing it would discard
                # the bounded solve and route the greedy pack that already stranded.
                if (
                    pending_pack is None
                    and candidate_index == 1
                    and arrangement == 0
                    and not projection_retry
                    and feedback is None
                    and seed.width <= _width_slack_cap(pack.width)
                    and (
                        seed.at != pack.at or seed.width != pack.width or seed.height != pack.height
                    )
                ):
                    pack = replace(
                        seed,
                        status="WARM_START",
                        hit_budget=pack.hit_budget,
                    )
                # Reject a provably oversized strip outline before emitting coaters,
                # reserving power, and preparing exact routing geometry.  The
                # emitted core contains every packed strip, so an outline that fits
                # no legal frame cannot become feasible when later passes only add
                # buildings.  This is the same projection envelope `_prepare` asks,
                # moved to the first point where the exact solved origins exist.
                outline_width, outline_height = strip_outline(pack)
                if not projection_envelope.frame_candidates(
                    outline_width,
                    outline_height,
                ):
                    if rejected is not None:
                        _retain_refusal(
                            rejected,
                            projection_envelope.extent_failure(
                                outline_width,
                                outline_height,
                            ),
                        )
                    continue
                # RATIONING THE CLOCK BETWEEN HEIGHTS WAS TRIED AND IS WORSE.
                #
                # The observation is real: a routing pass that will wire this pack
                # does it in four to eleven seconds and one that will not runs to
                # the wall, so the first candidate can spend a whole cell's ceiling
                # on a pack that was never going to work. Eighteen runs at a 15s
                # ceiling on `universe-matrix`: every refusal reads `f138@13.9s`,
                # one pass, one height, while every success reads 4.0s, 5.6s, 5.7s,
                # 10.7s, 10.8s, 10.9s.
                #
                # Capping a height at a share of what remains buys nothing, because
                # the successes are spread right across the range the cap has to cut.
                # `universe-matrix` at budget 15, three runs each: uncapped 3, 3, 3
                # of 6; at 55% of the remaining clock 2, 2, 2; at 75%, 4, 3, 2 and
                # 2, 3, 4 -- the same mean, more variance. And the corpus pays for
                # it: 68, 69, 68 against 69, 70, 70, 68, 70.
                #
                # What that says is that the spread is not the sweep's to manage.
                # Two solves of one height to the same width differ by seconds of
                # routing and by whether they converge at all, so the clock is not
                # being misallocated between heights -- it is being spent on a pack
                # CP-SAT happened to return. The lever is the packer's arrangement,
                # not the stopwatch.
                # A pack that cannot be POWERED is discarded exactly like a pack
                # that cannot be WIRED, and for the same reason: it is not a
                # feasible packing, so there is nothing here to rescue.
                #
                # There is no `claim_power=False` retry, and there is no coverage
                # repair behind this either. The retry gave the whole power claim up
                # as soon as a pack left one to three nets unrouted, on the
                # reasoning that a build which cannot be wired is worth nothing
                # while coverage still had a repair pass to fall back on. The second
                # half of that never held: the repair needed free ground and a pack
                # tight enough to strand a net has none, so what came back was a
                # wired blueprint with buildings outside every tower's radius --
                # `power.coverage`, an INVALID, in place of a refusal that would
                # have emitted nothing.
                #
                # `_power_plan` now decides coverage before routing and says so when
                # it cannot, which costs a pack rather than a pack plus a full
                # routing pass. If no height survives, the spec is REFUSED. Trading
                # coverage for the last net or two, like trading density for it, is
                # buying a green cell with something the build needed.
                evaluations += 1
                route_started = time.monotonic()
                try:
                    result = _build(
                        spec,
                        strips,
                        pack,
                        power=True,
                        route=True,
                        policy=self.band_policy,
                        belt_rules=self.belt_rules,
                        deadline=deadline,
                        budget=budget,
                        staged_static_cache=staged_static_cache,
                    )
                    preparation_time_s += result.preparation_time_s
                    detailed_route_time_s += result.detailed_route_time_s
                except finalize.ProjectionRefusal as exc:
                    if rejected is not None:
                        for failure in exc.failures:
                            _retain_refusal(rejected, failure)
                    continue
                except routing_domain._Unpowerable as exc:
                    if rejected is not None:
                        _retain_refusal(rejected, exc.failure or "power.coverage")
                    evidence = exc.exact_retry_evidence
                    if evidence is not None and exc.failure is not None:
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        retry_key = _ExactRetryKey(height, arrangement, evidence)
                        if exact_no_good_state.admit_retry(
                            retry_key,
                            no_good,
                            affordable=projection_retry_affordable(),
                        ):
                            candidate_packs.insert(
                                candidate_index,
                                (height, arrangement, True),
                            )
                    continue
                except routing_domain._Unseatable as exc:
                    # A pack that cannot seat one of its Spray Coaters is not a
                    # pack, for the same reason one that cannot be powered is not:
                    # the spec asked for proliferation and this height cannot
                    # deliver it. Discarding the height is the search doing its job;
                    # what is NOT allowed is emitting the pack with the coater left
                    # out, which is what this replaced.
                    if rejected is not None:
                        _retain_refusal(
                            rejected,
                            exc.failure or "prolif.sprayed_cargo_reaches_machines",
                        )

                    retry_promoted = False
                    evidence = exc.exact_retry_evidence
                    if evidence is not None and exc.failure is not None:
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        retry_key = _ExactRetryKey(height, arrangement, evidence)
                        retry_promoted = exact_no_good_state.admit_retry(
                            retry_key,
                            no_good,
                            affordable=projection_retry_affordable(),
                        )

                    pending_clearance: (
                        tuple[routing_domain.StagedStaticClearanceKey, int] | None
                    ) = None

                    clearance_exhausted = False
                    requirement = exc.clearance_requirement
                    if requirement is not None:
                        selected_strip = strips_by_instance.get(
                            (
                                requirement.instance_id.family_id,
                                requirement.instance_id.machine_start,
                                requirement.instance_id.machine_count,
                            )
                        )
                        if (
                            selected_strip is not None
                            and selected_strip.physical_variant is not None
                            and selected_strip.staged_static_variant_id == requirement.variant_id
                        ):
                            if requirement.required_west_channel > _COATER_WEST_CHANNEL + 1:
                                clearance_exhausted = True
                            else:
                                retained_clearance = minimum_staged_static_clearance.get(
                                    requirement.relation,
                                    selected_strip.west_channel,
                                )
                                if requirement.required_west_channel > retained_clearance:
                                    pending_clearance = (
                                        requirement.relation,
                                        requirement.required_west_channel,
                                    )

                    # The physical variant gets one bounded upstream seat first.
                    # If an extended pack still projects into its own machine, the
                    # absolute frame latitude remains pack-dependent: forbid this
                    # complete assignment once and let CP-SAT move it.  The bound
                    # belongs to the height/arrangement retry boundary, not to the
                    # assignment identity: every successful no-good necessarily
                    # produces a distinct assignment, so identity alone can never
                    # make a second W4 exhaustion terminal.
                    staged_retry_key = (height, arrangement)
                    if (
                        clearance_exhausted
                        and exc.failure is not None
                        and staged_retry_key not in staged_static_exact_retries
                        and projection_retry_affordable()
                    ):
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        if exact_no_good_state.remember(no_good):
                            staged_static_exact_retries.add(staged_retry_key)
                            retry_promoted = True

                    if pending_clearance is not None:
                        relation, required_west_channel = pending_clearance
                        minimum_staged_static_clearance[relation] = required_west_channel
                        replan_strips_for_learned_geometry()
                    if retry_promoted:
                        candidate_packs.insert(
                            candidate_index,
                            (height, arrangement, True),
                        )
                    continue
                # The measured routing span of THIS evaluation, which is what an
                # operator choice is billed for when its repair is credited.
                route_seconds = time.monotonic() - route_started
                # THE CHOICE THIS CANDIDATE ARRIVED WITH, held by identity.  A
                # window launched further down stores a choice under this same
                # key, and that one belongs to the repair it queued -- a
                # candidate this turn has not evaluated and must not be paid
                # for.  Membership alone cannot tell the two apart, because a
                # queued repair that fails again settles its own credit and
                # then immediately stores a fresh choice under the key it just
                # cleared.
                inbound_choice = window_choices.get((height, arrangement))

                def window_metrics(
                    *,
                    validator_clean: bool,
                    current_pack: routing_domain._Pack = pack,
                    current_height: int = height,
                    routing: DetailedRouteResult = result.routing,
                ) -> OperatorMetrics:
                    """This candidate's routing pass, as the operator ledger reads it.

                    The three places that settle a window's credit differ in one
                    field only -- `validator_clean`, which is True at exactly one
                    of them, the acceptance path that has a `validate.certify`
                    report to read.  The turn's `pack`, `height` and routing
                    result are bound at definition, as `retain_attempt` binds its
                    attempt, so the closure cannot describe a later candidate;
                    the feedback lookup stays late because the sweep writes to
                    `feedback_by_height` inside this turn.
                    """
                    return metrics_from_evaluation(
                        routing,
                        _decoded_from_pack(current_pack, strips, current_height),
                        feedback_by_height.get(
                            current_height,
                            FeedbackState.empty((current_pack.width, current_height)),
                        ),
                        outline_height=current_height,
                        band_target_width=band_target_for(
                            current_height,
                            current_pack.width,
                        ),
                        validator_clean=validator_clean,
                    )

                try:
                    failed = result.routing.failed_count
                    best_failing = bool(failed) and failed < best_failed_count
                    if failed:
                        best_failed_count = min(best_failed_count, failed)
                    attempt = PackAttempt(
                        origins=tuple(pack.at[index] for index in range(len(pack.at))),
                        compact_width=pack.width,
                        height=pack.height,
                        outline=tuple(_box(strip) for strip in strips),
                        routing=result.routing,
                        budget_stage=result.budget_stage,
                        static_access=tuple(
                            failure
                            for failure in result.routing.failures
                            if failure.kind is RouteFailureKind.STATIC_ACCESS
                        ),
                        promised_direct=result.promised_direct,
                        realized_direct=result.realized_direct,
                        direct_candidates=direct_candidate_snapshot,
                        stranded_ports=result.stranded_ports,
                    )

                    def retain_attempt(
                        stage: _BuildBudgetStage | None = None,
                        *,
                        current: PackAttempt = attempt,
                    ) -> None:
                        if attempts is not None:
                            attempts.append(
                                current if stage is None else replace(current, budget_stage=stage)
                            )

                    if failed:
                        retain_attempt()
                    if failed:
                        local_no_goods, exact_no_good, cluster_no_goods = _proof_scoped_no_goods(
                            attempt,
                            strips,
                        )
                        learned = False
                        for relation_no_good in local_no_goods:
                            if relation_no_good in direct_relation_no_good_keys:
                                continue
                            direct_relation_no_good_keys.add(relation_no_good)
                            direct_relation_no_goods.append(relation_no_good)
                            learned = True
                        for cluster_no_good in cluster_no_goods:
                            if cluster_no_good in cluster_relation_no_good_keys:
                                continue
                            cluster_relation_no_good_keys.add(cluster_no_good)
                            cluster_relation_no_goods.append(cluster_no_good)
                            learned = True
                        if exact_no_good is not None and exact_no_good_state.remember(
                            exact_no_good
                        ):
                            learned = True

                        budget_failure = result.routing.status is DetailedRouteStatus.BUDGET or any(
                            failure.kind is RouteFailureKind.BUDGET
                            for failure in result.routing.failures
                        )
                        feedback_state: FeedbackState | None = None
                        if not budget_failure:
                            feedback_state = _attempt_feedback_state(
                                attempt,
                                feedback_by_height.get(height),
                            )
                            feedback_by_height[height] = feedback_state

                        feedback_retry = feedback_state is not None and _feedback_retry_eligible(
                            attempt, feedback_state
                        )
                        # RULING E12: "aimable" is wider than "take a full exact
                        # retry".  The one-failure near miss keeps its existing
                        # unmetered retry; multiple failures leave the slot for
                        # the bounded window.  A learned proof may still buy its
                        # existing affordable full re-solve below.
                        single_failure_feedback_retry = (
                            feedback_retry and len(attempt.routing.failures) == 1
                        )
                        promote_retry = arrangement == 0 and (
                            learned or single_failure_feedback_retry
                        )
                        #: A window launches where a retry SLOT exists and was not
                        #: taken.  The slot lookup used to sit under
                        #: `promote_retry`, which is exactly the conjunct that
                        #: never held on a refusing cell (R2 §4).  Resolving it
                        #: independently lets an aimable multi-failure pack spend
                        #: the bounded window instead of the old single-failure
                        #: exact retry.  The affordability check below is
                        #: untouched and still bounds the cost.
                        retry_slot_found = False
                        retry_admitted = False
                        retry_candidate = (height, arrangement + 1)
                        try:
                            next_index = candidate_packs.index(
                                (*retry_candidate, False),
                                candidate_index,
                            )
                        except ValueError:
                            pass
                        else:
                            retry_slot_found = True
                            if promote_retry:
                                current_candidate_s = (
                                    0.0 if started_at is None else time.monotonic() - started_at
                                )
                                retry_cost = max(
                                    dearest_candidate_s,
                                    current_candidate_s,
                                )
                                if single_failure_feedback_retry or (
                                    learned
                                    and _room_for_another(
                                        deadline,
                                        soft,
                                        # A whole candidate, measured whole, so
                                        # it carries its own completion tail.
                                        completion_tail_s=0.0,
                                        next_candidate_s=retry_cost,
                                    )
                                ):
                                    if single_failure_feedback_retry:
                                        # This exact failed assignment is not proved
                                        # infeasible, so its cut belongs only to the
                                        # promoted feedback draw. Never remember it in
                                        # the sweep-wide exact no-good state.
                                        routing_failure = attempt.routing.failures[0]
                                        feedback_retry_no_goods[retry_candidate] = ExactPackNoGood(
                                            height=attempt.height,
                                            outline=attempt.outline,
                                            width=attempt.compact_width,
                                            origins=attempt.origins,
                                            evidence=(
                                                finalize.ProjectionFailure(
                                                    check="route.feedback_retry",
                                                    buildings=(),
                                                    detail=(
                                                        f"{routing_failure.kind.value}: "
                                                        f"net={routing_failure.net_id!r}; "
                                                        f"wall={routing_failure.wall!r}; "
                                                        "blockers="
                                                        f"{routing_failure.blocking_nets!r}; "
                                                        f"expansions={routing_failure.expansions}"
                                                    ),
                                                    band=0,
                                                ),
                                            ),
                                        )
                                    retry_admitted = True
                                    candidate_packs.pop(next_index)
                                    candidate_packs.insert(
                                        candidate_index,
                                        (height, arrangement + 1, True),
                                    )
                        # A queued repair that failed again settles its own credit
                        # here, on the outcome it actually produced, before this
                        # candidate is allowed to ask for another window.  The
                        # membership test only avoids ENCODING an outcome for the
                        # ordinary candidates that never had a choice behind them;
                        # `settle_window_credit` is a no-op for those anyway.
                        if (height, arrangement) in window_choices:
                            settle_window_credit(
                                height,
                                arrangement,
                                after=window_metrics(validator_clean=False),
                                routing_seconds=route_seconds,
                            )
                        # A WINDOW USES AN UNUSED NEXT-ARRANGEMENT SLOT.  The old
                        # one-failure feedback retry and an affordable learned
                        # retry consume that slot above; a multi-failure draw does
                        # not.  Only a strict best-failing improvement can spend
                        # the bounded window, so a tie never buys a second solve.
                        if retry_slot_found and not retry_admitted and best_failing:
                            window_cost = _window_candidate_seconds(
                                dearest_remainder_s=dearest_remainder_s,
                            )
                            if (
                                (height, arrangement) not in window_packs
                                and (height, arrangement) not in window_choices
                                and _room_for_another(
                                    deadline,
                                    soft,
                                    # The bounded solve plus a remainder measured
                                    # whole: the tail is already inside it.
                                    completion_tail_s=0.0,
                                    next_candidate_s=window_cost,
                                )
                            ):
                                target = band_target_for(height, pack.width)
                                relation_problem = _pack_relation_problem(pack, strips, height)
                                relation_decoded = _decoded_from_pack(pack, strips, height)
                                feedback_state_now = feedback_by_height.get(
                                    height,
                                    FeedbackState.empty((pack.width, height)),
                                )
                                before_metrics = metrics_from_evaluation(
                                    attempt.routing,
                                    relation_decoded,
                                    feedback_state_now,
                                    outline_height=height,
                                    band_target_width=target,
                                    validator_clean=False,
                                )
                                choice = session.select(
                                    OperatorContext(
                                        strip_count=len(strips),
                                        stagnation=0,
                                        remaining_fraction=remaining_fraction_bucket(
                                            soft - time.monotonic(),
                                            max(time_budget_s, 1e-6),
                                        ),
                                    )
                                )
                                try:
                                    window = destroy_strips(
                                        choice.destroy,
                                        scale=choice.scale,
                                        result=attempt.routing,
                                        pair=_pack_relation_pair(pack, strips, height),
                                        gaps=GapProfile.zero(len(strips)),
                                        problem=relation_problem,
                                        decoded=relation_decoded,
                                        band_target_width=target,
                                    )
                                except ValueError:
                                    # The encoder refused this pack.  Impossible for a
                                    # `no_overlap_2d` result, so it is a bug detector.
                                    window_encode_errors += 1
                                    window = frozenset()
                                window_key = (height, arrangement, window)
                                if (
                                    not window
                                    or len(window) >= len(strips)
                                    or window_key in solved_windows
                                ):
                                    session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                                else:
                                    solved_windows.add(window_key)
                                    window_solves += 1
                                    window_started = time.monotonic()
                                    outcome = _pack_window(
                                        strips,
                                        height=height,
                                        width_bound=pack.width,
                                        direct_candidates=net_candidates,
                                        window=window,
                                        fixed_at={
                                            index: origin
                                            for index, origin in pack.at.items()
                                            if index not in window
                                        },
                                        seed=pack,
                                        width_target=target,
                                        arrangement=arrangement,
                                        projection_no_goods=tuple(projection_no_goods),
                                        exact_pack_no_goods=exact_pack_no_goods,
                                        direct_relation_no_goods=tuple(direct_relation_no_goods),
                                        # THE SAME PROOFS `_pack` GETS.  A window
                                        # is a sub-model of the full formulation,
                                        # so a collection the packer is forbidden
                                        # to violate cannot be dropped here: the
                                        # window would hand back a pack the sweep
                                        # has already proved unroutable.
                                        cluster_relation_no_goods=tuple(cluster_relation_no_goods),
                                        feedback=feedback_by_height.get(height),
                                        on_skipped=_count_window_skips,
                                    )
                                    window_seconds += time.monotonic() - window_started
                                    repaired = None if outcome is None else outcome.pack
                                    if repaired is None or repaired.at == pack.at:
                                        session.observe(
                                            choice,
                                            (0.0,) * REWARD_RANKS,
                                            applied=False,
                                        )
                                    else:
                                        # NOT counted here.  `alns_window_accepted`
                                        # means INSTALLED into the candidate stream
                                        # -- the `_pack` site above, where the queue
                                        # drains -- and not "CP-SAT handed back a
                                        # different assignment".  A repair the sweep
                                        # never gets to is not an acceptance.  This
                                        # mirrors the sequence-pair arm so the gate
                                        # reads one number across both;
                                        # `alns_applied` counts a repair whose
                                        # routing pass was MEASURED, certified or
                                        # not, which is a wider set than this one.
                                        window_packs[height, arrangement] = repaired
                                        window_choices[height, arrangement] = (
                                            choice,
                                            before_metrics,
                                        )
                                        window_queue.append((height, arrangement))
                        continue
                    if result.routing.status is not DetailedRouteStatus.ROUTED:
                        retain_attempt()
                        if self.observer is not None and self.observer.due(SearchPhase.REFUSED):
                            self.observer.note(
                                SearchEvent(
                                    strategy="freeform",
                                    candidate=spec.label,
                                    phase=SearchPhase.REFUSED,
                                    placement=None,
                                    height=height,
                                    arrangement=arrangement,
                                    reason=f"routing {result.routing.status}",
                                    stranded=stranded_endpoints(result.routing),
                                )
                            )
                        continue
                    assert result.promised_direct == result.realized_direct, (
                        "a routed pack may not retain an unrealized rewarded direct insert"
                    )
                    placement = result.placement
                    assert placement is not None
                    if self.observer is not None and self.observer.due(SearchPhase.PACKED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.PACKED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area if placement.frame is not None else None,
                            )
                        )
                    # AND THE PLACEMENT HAS TO PASS OUR OWN VALIDATOR BEFORE IT COUNTS.
                    #
                    # `lay_out` promises a valid `Placement` or `NoValidLayout`, and
                    # until now freeform ARGUED that promise while `spine` enforced it
                    # -- `spine._rejected` has called `validate.certify` all along and
                    # this did not. The gap is not theoretical: `quantum-chip`
                    # /free-proliferation power=1 emits, roughly one build in sixteen, a
                    # placement whose titanium-glass production is cut into islands, so
                    # eleven machines can reach 16/7 items/s of an item they consume
                    # 11/4 of. It pastes and then does not run, which is the one failure
                    # nobody discovers until they are standing in front of it in game.
                    #
                    # A rejected candidate is DISCARDED, not repaired and not returned
                    # with a warning, and the sweep goes on to the next height. That is
                    # the same trade `_build`'s `failed` already makes and it goes the
                    # same way: several separately solved and separately validated packs
                    # is a search, and refusing outright is honest, while an invalid
                    # blueprint is the worst outcome this program has.
                    #
                    # A fully routed incumbent still has to finish three exact completion
                    # transforms. Search stops at the caller's wall, but a wired candidate
                    # gets the fixed loaded-machine atomic grace: discarding a valid route
                    # halfway through projection makes load, rather than geometry, decide
                    # whether the same deterministic blueprint exists.
                    completion_deadline = (
                        None if deadline is None else deadline + ATOMIC_COMPLETION_GRACE_S
                    )
                    projection = finalize.prepare_placement_completion(
                        placement,
                        spec,
                        self.band_policy,
                        belt_rules=self.belt_rules,
                        expect_power=True,
                        deadlines=finalize.PlacementCompletionDeadlines(
                            completion_deadline, completion_deadline, completion_deadline
                        ),
                    )
                    compaction_elapsed = projection.timings.cleanup_s
                    compaction_time_s += compaction_elapsed
                    compaction_reserve_s = max(compaction_reserve_s, compaction_elapsed)
                    finalize_elapsed = projection.timings.projection_s
                    finalization_time_s += finalize_elapsed
                    finalize_reserve_s = max(finalize_reserve_s, finalize_elapsed)
                    if isinstance(projection, finalize.PlacementCompletionCancelled):
                        retain_attempt(
                            _BuildBudgetStage.CERTIFICATION
                            if projection.phase == "cleanup"
                            else _BuildBudgetStage.FINALIZATION
                        )
                        break
                    placement = projection.candidate
                    if isinstance(projection, finalize.PlacementProjectionRefused):
                        retain_attempt()
                        learned = False
                        exact_projection_pair: ExactProjectionPair | None = None
                        geometry_learned = False
                        exact_retry_evidence: routing_domain._ExactRetryEvidence | None = None
                        pitch_requirements = _projection_pitch_requirements(
                            placement,
                            strips,
                            projection.refusal.failures,
                        )
                        from flab2bp.layout.strip_variants import (
                            StripInstanceId,
                            strip_pose_id,
                        )

                        projection_strips_by_instance: dict[
                            StripInstanceId, routing_domain.Strip
                        ] = {}
                        for strip in strips:
                            if strip.family_id is None:
                                continue
                            projection_strips_by_instance.setdefault(
                                StripInstanceId(
                                    strip.family_id,
                                    strip.machine_start,
                                    strip.machines,
                                ),
                                strip,
                            )
                        for failure, pitch_requirement in zip(
                            projection.refusal.failures,
                            pitch_requirements,
                            strict=True,
                        ):
                            if rejected is not None:
                                _retain_refusal(rejected, failure)

                            strip_pair = _projection_strip_pair(placement, failure)
                            projection_no_good = _projection_no_good(
                                placement,
                                pack,
                                strips,
                                failure,
                                self.band_policy,
                            )
                            if strip_pair is not None and projection_no_good is None:
                                if exact_projection_pair is None:
                                    exact_projection_pair = _exact_projection_pair(
                                        strips,
                                        strip_pair,
                                    )
                                if exact_retry_evidence is None:
                                    exact_retry_evidence = routing_domain._exact_retry_evidence(
                                        "finalizer",
                                        failure,
                                        {
                                            index: placement.buildings[index]
                                            for index in failure.buildings
                                            if 0 <= index < len(placement.buildings)
                                        },
                                    )
                            if projection_no_good is not None:
                                projection_no_good_key = projection_no_good
                                if projection_no_good_key not in projection_no_good_keys:
                                    projection_no_good_keys.add(projection_no_good_key)
                                    projection_no_goods.append(projection_no_good)
                                    learned = True

                            if pitch_requirement is None:
                                continue
                            selected_strip = projection_strips_by_instance.get(
                                pitch_requirement.instance_id
                            )
                            if (
                                selected_strip is None
                                or selected_strip.physical_variant is None
                                or selected_strip.physical_variant.variant_id
                                != pitch_requirement.variant_id
                            ):
                                continue

                            pose_id = strip_pose_id(selected_strip.physical_variant)
                            retained_pitch = minimum_pitch_x.get(
                                pose_id,
                                selected_strip.physical_variant.pitch_x,
                            )
                            if pitch_requirement.required_pitch <= retained_pitch:
                                continue
                            minimum_pitch_x[pose_id] = pitch_requirement.required_pitch
                            learned = True
                            geometry_learned = True
                        retry_promoted = False
                        if exact_retry_evidence is not None:
                            exact_no_good = ExactPackNoGood(
                                height=pack.height,
                                outline=tuple(_box(strip) for strip in strips),
                                width=pack.width,
                                origins=tuple(pack.at[index] for index in range(len(strips))),
                                evidence=projection.refusal.failures,
                                projection_pair=exact_projection_pair,
                            )
                            retry_key = _ExactRetryKey(
                                height,
                                arrangement,
                                exact_retry_evidence,
                            )
                            retry_promoted = exact_no_good_state.admit_retry(
                                retry_key,
                                exact_no_good,
                                affordable=projection_retry_affordable(),
                            )
                        learned_retry_affordable = (
                            learned and not retry_promoted and projection_retry_affordable()
                        )
                        if geometry_learned:
                            replan_strips_for_learned_geometry()
                        if learned_retry_affordable:
                            retry_promoted = True
                        if retry_promoted:
                            candidate_packs.insert(
                                candidate_index,
                                (height, arrangement, True),
                            )
                        continue
                    if routing_domain._expired(completion_deadline):
                        retain_attempt(_BuildBudgetStage.FINALIZATION)
                        break
                    if self.observer is not None and self.observer.due(SearchPhase.ROUTED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.ROUTED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area if placement.frame is not None else None,
                                belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                stranded=stranded_endpoints(result.routing),
                                no_goods=tuple(
                                    no_good.strips for no_good in cluster_relation_no_goods
                                ),
                            )
                        )
                    # Area, then belt count. Two packs of equal area are not equally
                    # good: the one with fewer belt tiles is fewer buildings to paste,
                    # and a direct insert shows up here as exactly that. Without the
                    # second key, ties fell to whichever height the sweep tried first,
                    # which silently discarded direct-inserted packs.
                    #
                    # Read BEFORE certification, and `replace` below only rewrites
                    # `completion`, so neither term can move between here and the
                    # comparison that uses it.
                    key = (placement.area, float(placement.stats["belt_tiles"]))
                    # L4: certifying a candidate that cannot displace the incumbent
                    # buys nothing -- it is not returnable at any report -- and
                    # certification is 15-19 % of the freeform budget on the largest
                    # cells.  Held back while a window credit is outstanding: the
                    # acceptance settle below is the one place a `validator_clean=True`
                    # outcome exists, and dropping it would move the operator ledger
                    # that steers the rest of the sweep.
                    #
                    # The skip takes the SAME exit a rejected candidate takes -- both
                    # certified exits, `report.errors` and a losing key, call
                    # `retain_attempt()` with no stage and go round again -- so the
                    # attempts ledger and the loop control are unchanged.  The CLOCK
                    # is not: this turn is shorter, the budget terms drawn from it
                    # shrink, and a later candidate can be admitted that the un-gated
                    # sweep would have refused.  That makes the search a superset and
                    # the answer no worse, never a different pick among the same
                    # candidates; `_would_become_incumbent` states it in full.
                    if inbound_choice is None and not _would_become_incumbent(key, best_key):
                        certify_skipped += 1
                        if routing_domain._expired(completion_deadline):
                            retain_attempt(_BuildBudgetStage.CERTIFICATION)
                            break
                        retain_attempt()
                        continue
                    completion = finalize.complete_placement(projection)
                    report = completion.report
                    validation_elapsed = completion.timings.certification_s
                    validation_time_s += validation_elapsed
                    if (
                        inbound_choice is not None
                        and window_choices.get((height, arrangement)) is inbound_choice
                    ):
                        settle_window_credit(
                            height,
                            arrangement,
                            after=window_metrics(validator_clean=not report.errors),
                            routing_seconds=route_seconds,
                        )
                    validation_reserve_s = max(
                        validation_reserve_s,
                        validation_elapsed,
                    )
                    if self.observer is not None and self.observer.due(SearchPhase.CERTIFIED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.CERTIFIED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area if placement.frame is not None else None,
                                belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                reason=None if not report.errors else report.errors[0].message,
                            )
                        )
                    if report.errors and rejected is not None:
                        for finding in report.errors:
                            _retain_refusal(rejected, finding)
                    if (
                        self.observer is not None
                        and report.errors
                        and self.observer.due(SearchPhase.REFUSED)
                    ):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.REFUSED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                reason=report.errors[0].message,
                            )
                        )
                    if isinstance(completion, finalize.PlacementCertificationExpired) or (
                        routing_domain._expired(completion_deadline)
                    ):
                        retain_attempt(_BuildBudgetStage.CERTIFICATION)
                        break
                    if isinstance(completion, finalize.PlacementInvalid):
                        retain_attempt()
                        continue
                    placement = completion.placement
                    retain_attempt()
                    # The authority on what is returned, spelled inline rather than
                    # delegated to `_would_become_incumbent`: see that docstring for
                    # why the gate above is deliberately a separate copy.
                    if best_key is None or key < best_key:
                        placement.stats["solver_status"] = 1.0 if pack.status == "OPTIMAL" else 0.5
                        placement.stats["hit_time_budget"] = float(pack.hit_budget)
                        placement.stats["fallback_used"] = 0.0
                        placement.stats["direct_insert_candidates"] = float(len(candidates))
                        placement.stats["area"] = float(placement.area)
                        best, best_key = placement, key
                        if self.publish_incumbent is not None:
                            self.publish_incumbent(placement)
                        if self.observer is not None and self.observer.due(SearchPhase.INCUMBENT):
                            self.observer.note(
                                SearchEvent(
                                    strategy="freeform",
                                    candidate=spec.label,
                                    phase=SearchPhase.INCUMBENT,
                                    placement=placement,
                                    height=height,
                                    arrangement=arrangement,
                                    area=placement.area if placement.frame is not None else None,
                                    belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                    incumbent=True,
                                )
                            )
                finally:
                    # SPEC 5.7: a queued repair is paid on the metrics THIS
                    # routing pass measured, and `validator_clean` is False for
                    # any candidate that never reaches `validate.certify`.
                    # Every exit that HOLDS a routing result passes through here
                    # -- the unrouted `continue`, the two completion breaks, the
                    # projection/pitch refusal -- so none of them can fall
                    # through to the post-loop drain and be paid `after=None`,
                    # which is a zero reward for a repair that was measured.
                    # The one post-routing exit outside this block is
                    # `_Unpowerable`, raised from `_place_power` after routing
                    # but caught above `route_seconds`, where no result exists to
                    # settle on; `settle_window_credit`'s docstring names it.
                    # The two settles inside the body have already popped the
                    # choice by the time control reaches here: the failure block
                    # must settle BEFORE it is allowed to ask for another
                    # window, and the acceptance path is the only place a
                    # `validator_clean=True` outcome exists at all.
                    if (
                        inbound_choice is not None
                        and window_choices.get((height, arrangement)) is inbound_choice
                    ):
                        settle_window_credit(
                            height,
                            arrangement,
                            after=window_metrics(validator_clean=False),
                            routing_seconds=route_seconds,
                        )
        finally:
            # A choice whose candidate never produced a routing evaluation --
            # the wall arrived before its turn, or an exception took the sweep
            # out from under it -- is a cost with no reward, and the ledger has
            # to see it as one.  In a `finally` because an escaping exception
            # must not hand an operator a free turn: the session outlives this
            # call and the arm it credits is chosen from what the ledger holds.
            for outstanding_height, outstanding_arrangement in list(window_choices):
                settle_window_credit(
                    outstanding_height,
                    outstanding_arrangement,
                    after=None,
                    routing_seconds=0.0,
                )
        cp_stats = (_PACK_CP_PROFILE.get() or _PackCpProfile()).stats()
        if telemetry is not None:
            telemetry["alns_choices"] = float(len(session.choices))
            telemetry["alns_applied"] = float(session.applied)
            telemetry["alns_evaluations"] = float(evaluations)
            telemetry["alns_routing_seconds"] = session.routing_seconds
            telemetry["alns_operators"] = operator_tally(session)
            telemetry["alns_window_solves"] = float(window_solves)
            telemetry["alns_window_accepted"] = float(window_accepted)
            telemetry["alns_window_seconds"] = window_seconds
            telemetry["alns_encode_errors"] = float(window_encode_errors)
            telemetry["alns_skipped_no_goods"] = float(window_skipped_no_goods)
            # The names spec 5.3.2 asks for on a REFUSED freeform row, beside the
            # `alns_*` names the CLEAN rows already use.
            telemetry["evaluations"] = float(evaluations)
            telemetry["distinct_assignments"] = float(len(routed_assignments))
            telemetry["stale_draws"] = float(stale_draws)
            telemetry["stale_stop"] = float(stale_stop)
            telemetry["window_solves"] = float(window_solves)
            telemetry["window_accepted"] = float(window_accepted)
            telemetry.update(
                {
                    "pack_time_s": pack_time_s,
                    "preparation_time_s": preparation_time_s,
                    "detailed_route_time_s": detailed_route_time_s,
                    "compaction_time_s": compaction_time_s,
                    "finalization_time_s": finalization_time_s,
                    "validation_time_s": validation_time_s,
                    "certify_skipped": float(certify_skipped),
                    "budget_unspent_s": budget_unspent_s,
                    **cp_stats,
                }
            )
        # `stats["route_backend"]` is stamped in `lay_out`, where none of these
        # locals exist, so the operator telemetry is stamped here instead --
        # guarded, because a sweep that refuses has no placement to carry it.
        if best is not None:
            best.stats["alns_choices"] = float(len(session.choices))
            best.stats["alns_applied"] = float(session.applied)
            best.stats["alns_evaluations"] = float(evaluations)
            best.stats["alns_routing_seconds"] = session.routing_seconds
            best.stats["alns_operators"] = operator_tally(session)
            best.stats["alns_window_solves"] = float(window_solves)
            best.stats["alns_window_accepted"] = float(window_accepted)
            best.stats["alns_window_seconds"] = window_seconds
            best.stats["alns_encode_errors"] = float(window_encode_errors)
            best.stats["alns_skipped_no_goods"] = float(window_skipped_no_goods)
            best.stats.update(
                {
                    "pack_time_s": pack_time_s,
                    "preparation_time_s": preparation_time_s,
                    "detailed_route_time_s": detailed_route_time_s,
                    "compaction_time_s": compaction_time_s,
                    "finalization_time_s": finalization_time_s,
                    "validation_time_s": validation_time_s,
                    "certify_skipped": float(certify_skipped),
                    "budget_unspent_s": budget_unspent_s,
                }
            )
            best.stats.update(cast(PlacementStats, cp_stats))
        return best


def _would_become_incumbent(
    candidate_key: tuple[int, float],
    incumbent_key: tuple[int, float] | None,
) -> bool:
    """Would this ``(area, belt_tiles)`` displace the sweep's certified best?

    Pure, and deliberately the SAME predicate `_sweep`'s acceptance path spells
    inline.  The two are not shared on purpose: this one is an optimisation --
    it decides whether a candidate is worth certifying at all -- and the
    acceptance one is the authority that decides what is returned.  Keeping the
    authority independent means a wrong answer here can only cost clock, and it
    is what lets a test force this gate open and compare the two runs.

    ``incumbent_key`` is ``None`` until a candidate has been CERTIFIED clean, so
    the first completed candidate always answers True: the sweep never skips its
    way into having no measured certify span, and a candidate the validator
    rejects leaves the key it was measured against untouched.

    WHAT THE GATE PROMISES, AND WHAT IT DOES NOT.  It does not promise the same
    placement on every input, and the reason is the clock rather than the
    ranking.  A skipped certify is time the candidate's turn does not spend, so
    the `candidate_total_s` it is charged comes out smaller and with it both
    terms taken from it -- `dearest_candidate_s` and the `candidate_totals_s`
    `_next_candidate_seconds` takes its median over.  `validation_reserve_s`
    likewise becomes a maximum over incumbent-sized certifies alone.  All three
    feed `_room_for_another` and the completion-reserve break, so this sweep can
    START a candidate the un-gated one would have refused admission.

    What does hold, and what the tests pin:

    * the certified set is a SUBSET of the set certifying everything produces;
    * among the candidates actually evaluated, selection is bit-identical -- the
      key is read before certification and no report can move either term, so a
      skipped candidate is one the acceptance comparison would have rejected;
    * every budget term the skip perturbs can only SHRINK, so the sweep explores
      a SUPERSET of the un-gated candidates and the placement it returns is no
      worse than the un-gated one on `(area, belt_tiles)`.

    The extra candidate is bought inside the gate's own wall, so Ruling D2 leaves
    this as it stands and checks it at the gate's ``wall_overshoot_s`` maximum
    rather than with a code change here.
    """
    return incumbent_key is None or candidate_key < incumbent_key


def _next_candidate_seconds(completed_s: Sequence[float]) -> float:
    """What ONE MORE candidate is expected to cost, and why it is not a maximum.

    The median of what the completed candidates actually took, and zero until
    one has completed -- so the first candidate of a sweep is never refused for
    want of a measurement.

    THE MAXIMUM WAS THE WRONG STATISTIC.  A sweep's candidate costs are not
    symmetric: most candidates route in a comparable time and one occasionally
    walks into a congestion wall and burns several times that.  Charging the
    next candidate the dearest one ever seen therefore prices it at the outlier,
    and the sweep hands the clock back rather than spend it -- 6-37 % of every
    30 s budget on the profiled cells (speedups-2 design L5).

    Under-estimating is cheap and over-estimating is not.  A candidate admitted
    on a median it then over-runs is abandoned at the pack budget's
    ``remaining <= 0``, at the completion-tail check that follows its pack, or by
    `_expired(completion_deadline)` inside the completion transforms; in every
    one of those the sweep still holds an incumbent that is already compacted,
    finalized and certified, so what the abandoned candidate cost is clock and
    nothing else.  A candidate REFUSED on an outlier's price, by contrast, is a
    draw at a denser placement that was affordable and never taken.

    What must NOT be estimated this way is the completion tail; see
    `_room_for_another`, which is where the two are added.
    """
    if not completed_s:
        return 0.0
    return statistics.median(completed_s)


def _capped_next_candidate_seconds(
    next_candidate_s: float,
    *,
    completion_tail_s: float,
    dearest_candidate_s: float,
) -> float:
    """RULING D3: never charge a fresh candidate more than the dearest completed one.

    `_room_for_another` charges ``completion_tail_s + next_candidate_s``, and the
    median is taken over candidate TOTALS -- each of which already contains that
    candidate's own compaction, finalization and certification.  Adding the
    reserves on top therefore counts the tail twice, and on a cell whose
    candidates all cost about the same the sum comes out ABOVE the dearest
    candidate the sweep ever completed: `[8, 8, 8]` with a 3 s tail asks for
    11 s where the old rule asked for 8.  A lever meant to spend more budget
    must not be able to refuse a candidate the rule it replaces would admit.

    ``dearest_candidate_s`` -- the old charge -- was itself wall-safe precisely
    because a completed total contains its own tail, so capping the sum at it
    can only ever LOWER the charge and never below what one candidate really
    cost.  The floor is the tail: this returns what to hand
    `_room_for_another` as ``next_candidate_s`` so that the resulting charge is
    ``max(completion_tail_s, min(dearest_candidate_s, completion_tail_s +
    next_candidate_s))``.  The tail must still fit in full whatever the estimate
    says, which is the one direction this cap deliberately does not relax.

    Pure, and applied only at the fresh-candidate gates.  The sites that charge
    a span they measured whole -- the queued repair's remainder, the window, the
    projection and learned retries -- pass ``completion_tail_s=0.0`` and are not
    capped here: their charge IS a whole candidate's measurement, and Ruling AD
    turns on it staying one.
    """
    capped_charge_s = min(dearest_candidate_s, completion_tail_s + next_candidate_s)
    return max(0.0, capped_charge_s - completion_tail_s)


def _room_for_another(
    deadline: float | None,
    soft: float,
    *,
    completion_tail_s: float,
    next_candidate_s: float,
) -> bool:
    """Is there clock left to pack, route, power and validate one more candidate?

    Both clocks have to allow it and they say different things.  ``soft`` is the
    sweep's own share and is what stops it improving; ``deadline`` is the call's
    wall and is what stops it entirely.  A candidate started against either one
    with no room to finish is a candidate whose whole cost is wasted -- the sweep
    already holds a routed placement, so an abandoned improvement buys nothing
    and spends the clock a later spec-critical pass might have used.

    THE CHARGE IS TWO DIFFERENT KINDS OF NUMBER and they used to be one.

    ``completion_tail_s`` is what MUST fit, and it is always a maximum: the
    compaction, finalization and validation reserves, each the dearest span this
    sweep has measured for that transform.  Those three are the exact work that
    turns a routed candidate into a placement this program will emit, they are
    not interruptible into anything useful, and a sweep that starts a candidate
    without room for them has bought a routing pass it cannot cash.

    ``next_candidate_s`` is what the next turn's own work is EXPECTED to cost,
    and it deliberately need not be a maximum -- see `_next_candidate_seconds`
    for why the median is the honest estimate and what an under-estimate costs.

    The two are added, so the caller decides the split.  A caller charging a
    span it has MEASURED WHOLE -- a queued repair's post-pack remainder, a
    window's bounded solve plus that remainder, a projection retry's whole
    candidate -- passes it as ``next_candidate_s`` with a zero tail, because
    such a span already contains its own completion transforms and adding the
    reserves on top would charge for them twice.  Only the fresh-candidate gate
    in :meth:`FreeformLayout._sweep` splits them.

    A ``deadline`` of ``None`` means a caller with no wall -- a test or a probe
    -- and only the soft clock then applies.
    """
    charge_s = completion_tail_s + next_candidate_s
    now = time.monotonic()
    if soft - now < charge_s:
        return False
    return deadline is None or deadline - now >= charge_s


def _window_candidate_seconds(*, dearest_remainder_s: float) -> float:
    """What one windowed retry costs, measured rather than tuned.

    A full retry is charged the dearest completed candidate, pack included.  A
    window replaces the pack with a bounded solve and leaves everything after it
    -- preparation, routing, power, finalize, validate -- exactly where it was,
    so its charge is that bounded solve plus the measured remainder.  Like
    `_room_for_another`'s `candidate_s`, this is a measurement: a fixed constant
    cannot span a corpus running from one to 955 machines.

    ``dearest_remainder_s`` is the largest post-pack span ONE candidate really
    ran, not `dearest_candidate_s - dearest_pack_s` (Ruling AD).  That
    difference subtracts two maxima that need not belong to the same candidate,
    so a sweep holding one slow-to-pack candidate and one slow-to-route one
    collapses it toward zero and admits a repair that then overruns the wall.

    No clock is read here.  The charge is a pure function of a measurement the
    sweep already keeps, and `_room_for_another` is the one that compares it
    against the wall.
    """
    return C_WINDOW_SECONDS + max(0.0, dearest_remainder_s)


def _height_seed(strips: list[routing_domain.Strip]) -> int:
    area = sum(w * h for w, h in map(_box, strips))
    tall = max((h for _w, h in map(_box, strips)), default=1)
    return max(tall, int(math.isqrt(max(1, area))))


def _candidate_height_box(strip: routing_domain.Strip) -> tuple[int, int]:
    """Exclude lateral staged-static feedback from the fixed height schedule."""
    width, height = _box(strip)
    if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY:
        width -= max(0, strip.west_channel - _COATER_WEST_CHANNEL)
    return width, height


def _candidate_heights(strips: list[routing_domain.Strip]) -> list[int]:
    """Heights to sweep, since ``W * H`` is too weak a form to minimise directly."""
    boxes = tuple(_candidate_height_box(strip) for strip in strips)
    area = sum(width * height for width, height in boxes)
    tall = max((height for _width, height in boxes), default=1)
    h0 = max(tall, int(math.isqrt(max(1, area))))
    out = {max(tall, int(h0 * f)) for f in (0.6, 0.8, 1.0, 1.25, 1.6)}
    return sorted(out)


def _minimum_pack_width(strips: list[routing_domain.Strip], height: int) -> int:
    """Return a proof-valid width floor for any packing at one height."""
    boxes = tuple(map(_box, strips))
    area = sum(width * box_height for width, box_height in boxes)
    widest = max((width for width, _box_height in boxes), default=1)
    return max(widest, (area + height - 1) // height)


def _band_policy_candidate_heights(
    strips: list[routing_domain.Strip],
    policy: BandPolicy,
    *,
    route_clearance: int = 0,
) -> tuple[int, ...]:
    """Keep the measured order while reserving one proved fixed-band boundary.

    THE WITNESS IS THE GREEDY SEED'S REALISED STRIP OUTLINE, not
    `_minimum_pack_width`'s.  The latter is a valid area-based LOWER bound and it
    is far below anything the packer builds: 92 against 258 on
    `universe-matrix/no-proliferator`, where a 98x166 extent fits the 200-segment
    band rotated and a 264x162 extent fits nothing.  Height 160 therefore
    survived the filter, its greedy seed was rejected at the pre-pack gate, and
    one of five candidate slots was spent proving that (R1 §2).  With the seed's
    realised width the boundary height 154 replaces it, and its 258x154 pack
    packs and routes (R1 §3, E1).

    `max(...)` rather than the outline alone: `_minimum_pack_width` is still a
    proof and can exceed the seed for a height the shelf pack seats badly, and
    taking the larger of the two keeps the filter no weaker than it was.

    Expendable routing clearance after the final shelf is deliberately excluded,
    exactly as it is at `_sweep`'s seed gate.  This is a WIDTH witness at the
    SCHEDULED height; the gate separately checks the realised outline height.
    """

    def greedy_seed(height: int) -> routing_domain._Pack:
        if route_clearance:
            return _greedy_pack(
                strips,
                height,
                route_clearance=route_clearance,
            )
        return _greedy_pack(strips, height)

    seeds = {height: greedy_seed(height) for height in _candidate_heights(strips)}
    outlines = {height: _realized_pack_outline(strips, seed) for height, seed in seeds.items()}
    ordered = tuple(sorted(seeds, key=lambda height: (outlines[height][0], height)))
    envelope = finalize.band_policy_search_envelope(
        policy,
        perimeter=routing_domain._ENTRY_RING,
    )
    return envelope.reserve_boundary_height(
        ordered,
        minimum_width_for_height={
            height: max(_minimum_pack_width(strips, height), outlines[height][0])
            for height in ordered
        },
    )
