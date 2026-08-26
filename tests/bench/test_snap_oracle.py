"""Differential test: our snap rule against the game's own ``MatchInserter``.

``oracle/`` holds ``BuildTool_BlueprintPaste.MatchInserter`` transcribed line for
line out of the decompiled shipped assembly and compiled against the game's own
``Assembly-CSharp.dll``.  These tests drive the SAME inputs through it and
through :mod:`flab2bp.layout.slots`, and pin every place the two answers differ.

WHAT THESE PROVE, AND WHAT THEY DO NOT
--------------------------------------
The game finds its snap candidates with ``Physics.OverlapSphereNonAlloc`` against
a live PhysX scene.  That query cannot be run outside the game, and a synthesised
collider set would be OUR model of the scene -- the thing under test.  So here
the candidate set is an INPUT.

* A disagreement found here is real: same candidates in, different answers out.
* Agreement here says nothing about whether we predict the right candidate set.
  That needs the real scene.

Everything skips cleanly when ``dotnet`` or the game install is missing, and the
skip reason names which.
"""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

from flab2bp.bench import snaporacle as O
from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders
from flab2bp.dsp import rules as R
from flab2bp.dsp.codec import decode
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import BlueprintBuilding
from flab2bp.layout import slots as S

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

needs_oracle = pytest.mark.skipif(
    not O.oracle_available(),
    reason=O.unavailable_reason() or "",
)

#: An Artificial Star's poses are a special case the corpus tests already
#: exclude; see ``tests/layout/test_sorter_slots.py``.
ARTIFICIAL_STAR = 2210

#: How far off the integer grid a machine may sit and still be read as geometry.
#: The same bound, for the same reason, as ``test_sorter_slots.ON_GRID_TOLERANCE``.
ON_GRID_TOLERANCE = 0.2


def test_skips_cleanly_when_the_game_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence of the install must be a skip reason, never a failure."""
    monkeypatch.setenv("DSP_MANAGED", "/nonexistent/path/for/testing")
    assert O.game_managed_dir() is None
    reason = O.unavailable_reason()
    assert reason is not None
    assert "Dyson Sphere Program" in reason


def test_the_grid_conversion_is_its_own_inverse() -> None:
    """``unity_point`` and ``to_tiles`` round-trip, in the units the rules use."""
    for tile in ((0.0, 0.0, 0.0), (3.0, -4.5, 1.0), (-12.25, 7.75, -2.0)):
        back = O.to_tiles(O.unity_point(*tile))
        assert back == pytest.approx(tile, abs=1e-9)
    # One tile east is exactly one GRID_ARC of Unity x, and one level is exactly
    # one WORLD_UNITS_PER_LEVEL of Unity y. `world_gap` depends on both.
    assert O.unity_point(1.0, 0.0)[0] == pytest.approx(colliders.GRID_ARC)
    assert O.unity_point(0.0, 0.0, 1.0)[1] == pytest.approx(R.WORLD_UNITS_PER_LEVEL)


# --- the corpus ------------------------------------------------------------


#: ``(east, north)`` in tiles.
Tile = tuple[float, float]
#: ``(file, peer, recorded slot, end, other end)`` for one machine-side sorter end.
Row = tuple[str, BlueprintBuilding, int, Tile, Tile]
#: ``(item id, yaw, end, other end)`` for one synthetic sweep point.
Point = tuple[int, float, Tile, Tile]


def _corpus_rows() -> list[Row]:
    """``(file, peer, recorded slot, end, other end)`` for machine-side ends.

    The same selection ``tests/layout/test_sorter_slots.py`` uses, so the two
    tests are asking about the same 1206 records.
    """
    rows: list[Row] = []
    for path in sorted(FIXTURES.glob("*.txt")):
        try:
            bp = decode(path.read_text().strip())
        except BlueprintFormatError:
            continue  # `dyson-sphere-iridescent` is a DYBP, not a factory blueprint
        by_index = {b.index: b for b in bp.buildings}
        for s in bp.buildings:
            if not cat.is_sorter(s.item_id):
                continue
            for ref, slot, end, other in (
                (s.output_obj_idx, s.output_to_slot, (s.x2, s.y2), (s.x, s.y)),
                (s.input_obj_idx, s.input_from_slot, (s.x, s.y), (s.x2, s.y2)),
            ):
                peer = by_index.get(ref)
                if peer is None or cat.is_belt(peer.item_id):
                    continue
                if peer.item_id == ARTIFICIAL_STAR:
                    continue
                off = max(abs(peer.x - round(peer.x)), abs(peer.y - round(peer.y)))
                if off > ON_GRID_TOLERANCE:
                    continue
                rows.append((path.name, peer, slot, end, other))
    return rows


def _one_machine_case(
    name: str, peer: BlueprintBuilding, end: Tile, other: Tile, table: str
) -> O.Case:
    """A sorter end offered exactly one candidate: the machine the record names.

    ``output_obj_id`` is set non-zero so the ladder's ``flag`` branch is already
    satisfied and only the input branch runs -- the branch whose ``vector`` is
    ``lpos``.  That makes both ends of a real sorter expressible in one shape.
    """
    return O.Case(
        name=name,
        lpos=O.unity_point(end[0], end[1]),
        lpos2=O.unity_point(other[0], other[1]),
        output_obj_id=999,
        candidates=(
            O.machine_candidate(
                peer.item_id, peer.yaw, (peer.x, peer.y), obj_id=1, table=table
            ),
        ),
    )


@pytest.mark.dotnet
@needs_oracle
def test_the_quaternion_substitutes_agree_with_shipped_game_code() -> None:
    """The only two lines of the transcription that are not the game's.

    ``Quaternion.Euler`` and ``Quaternion.Slerp`` are native thunks and throw
    outside the engine, so the oracle re-implements them.  This checks both
    against game code that DOES run -- ``Maths.LookRotation`` and
    ``Maths.Forward``, managed and shipped -- over 145 yaws.  A wrong half-angle
    or a sign flip fails it by orders of magnitude.
    """
    assert O.selftest() == []


@pytest.mark.dotnet
@needs_oracle
def test_the_ladder_reproduces_the_games_own_slot_indices() -> None:
    """1206 real machine-side records, through the game's own arithmetic.

    Wherever the transcribed ladder connects at all, it names the index the game
    itself wrote into the blueprint -- and :func:`flab2bp.layout.slots.machine_slot`
    names the same one.  Three independent answers, no disagreement.

    The 58 it does NOT connect are the falsifier this could have failed on, and
    they are pinned by ``test_the_ladder_refuses_records_it_did_not_make``.
    """
    rows = _corpus_rows()
    assert len(rows) == 1206, "the corpus selection drifted"
    tables = {str(peer.item_id): O.slot_table(peer.item_id) for _n, peer, *_ in rows}
    cases = [
        _one_machine_case(str(i), peer, end, other, str(peer.item_id))
        for i, (_n, peer, _slot, end, other) in enumerate(rows)
    ]
    verdicts = O.ask(cases, tables=tables)
    assert [v.name for v in verdicts if v.error] == []

    connected = 0
    disagree: list[str] = []
    for v, (name, peer, slot, end, other) in zip(verdicts, rows, strict=True):
        if not v.connected:
            continue
        connected += 1
        ours = S.machine_slot(
            peer.item_id,
            peer.yaw,
            (end[0] - peer.x, end[1] - peer.y),
            (end[0] - other[0], end[1] - other[1]),
        )
        if v.input_from_slot != slot or ours != slot:
            disagree.append(
                f"{name}: {cat.building(peer.item_id).name} at ({peer.x:.2f},{peer.y:.2f}) "
                f"yaw={peer.yaw:.1f} end={end} recorded={slot} "
                f"ladder={v.input_from_slot} ours={ours}"
            )
    assert connected == 1148
    assert disagree == [], "\n".join(disagree[:20])


@pytest.mark.dotnet
@needs_oracle
def test_the_ladder_refuses_records_it_did_not_make() -> None:
    """58 corpus records name a slot ``MatchInserter`` would not have picked.

    That is not a contradiction and not a defect in either model.
    ``BlueprintUtils`` (line 1623) hands a pasted sorter its peer PREVIEW
    straight from the blueprint's own ``inputObj`` / ``outputObj``, and
    ``BuildTool_BlueprintPaste`` (line 1795) calls ``MatchInserter`` only for an
    end whose preview came back null.  So a connection the blueprint already
    carries is never re-derived, and these 58 are connections the ladder was
    never asked about.

    They are pinned because the number is a fact about the corpus: it moves only
    if the ladder, the slot table, or the corpus changes.
    """
    rows = _corpus_rows()
    tables = {str(peer.item_id): O.slot_table(peer.item_id) for _n, peer, *_ in rows}
    cases = [
        _one_machine_case(str(i), peer, end, other, str(peer.item_id))
        for i, (_n, peer, _slot, end, other) in enumerate(rows)
    ]
    verdicts = O.ask(cases, tables=tables)
    refused = collections.Counter(
        cat.building(peer.item_id).name
        for v, (_n, peer, *_) in zip(verdicts, rows, strict=True)
        if not v.connected
    )
    assert dict(refused) == {"Negentropy Smelter": 50, "Depot Mk.I": 8}


# --- the synthetic sweep, where the two rules actually part company ---------

#: Four tables that between them cover every shape the extraction found: a ring
#: of twelve un-mirrored, a ring of twelve mirrored, nine that leave one face
#: bare, and eight in two rows one of which is INSIDE the footprint.
SWEEP_TYPES = (2303, 2901, 2308, 2309)
SWEEP_YAWS = (0.0, 90.0, 180.0, 270.0)
SWEEP_APPROACH = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
SWEEP_STEP = 0.5
SWEEP_REACH = 2.5


def _sweep() -> tuple[list[O.Case], list[Point]]:
    n = int(round(SWEEP_REACH / SWEEP_STEP))
    coords = [i * SWEEP_STEP for i in range(-n, n + 1)]
    cases: list[O.Case] = []
    meta: list[Point] = []
    for item_id in SWEEP_TYPES:
        for yaw in SWEEP_YAWS:
            cand = O.machine_candidate(
                item_id, yaw, (0.0, 0.0), obj_id=1, table=str(item_id)
            )
            for ex in coords:
                for ey in coords:
                    for ax, ay in SWEEP_APPROACH:
                        cases.append(
                            O.Case(
                                name=str(len(cases)),
                                lpos=O.unity_point(ex, ey),
                                lpos2=O.unity_point(ex - ax, ey - ay),
                                output_obj_id=999,
                                candidates=(cand,),
                            )
                        )
                        meta.append((item_id, yaw, (ex, ey), (ex - ax, ey - ay)))
    return cases, meta


def _ours(item_id: int, yaw: float, end: Tile, other: Tile) -> tuple[bool, int | None]:
    """Our answer: would :func:`flab2bp.layout.slots.attachment` take this end, and for which slot.

    The two tests are the ones ``attachment`` applies per candidate cell -- the
    slot is within :data:`~flab2bp.dsp.rules.SLOT_REACH` and faces back along the
    run to within :data:`~flab2bp.dsp.rules.SKEW_AXIS_DEG`.  Spelt out here rather
    than called, because ``attachment`` also insists the end be a tile of the
    machine, and the sweep deliberately walks off the lattice.
    """
    try:
        slot = S.machine_slot(
            item_id, yaw, end, (end[0] - other[0], end[1] - other[1])
        )
    except S.SlotUndetermined:
        return (False, None)
    sx, sy, sz = S.slot_offset(item_id, yaw, slot)
    reach = R.world_gap(sx - end[0], sy - end[1], sz)
    wx, wy, _wz = S.slot_forward(item_id, yaw, slot)
    ax, ay = other[0] - sx, other[1] - sy
    n = (ax * ax + ay * ay) ** 0.5
    cos = -1.0 if n == 0.0 else (wx * ax + wy * ay) / n
    return (reach <= R.SLOT_REACH and cos >= R.SLOT_ALIGN_COS, slot)


@pytest.mark.dotnet
@needs_oracle
def test_where_our_slot_rule_and_the_ladder_part_company() -> None:
    """15488 synthetic ends, and the exact shape of every disagreement.

    Three classes come out, and each has a cause that is readable in the source:

    ``the ladder connects where we refuse`` -- its own gate is ``num4 < 6f``, a
    SQUARED distance in world units, so it will drag an end up to 2.449 world
    units (1.95 tiles) onto a slot.  :data:`~flab2bp.dsp.rules.SLOT_REACH` is
    0.8, from ``CheckInserterDataLegal``.  Two different predicates in two
    different code paths, and the looser one is the ladder's.

    ``we accept where the ladder refuses`` -- the ladder requires BOTH
    ``Dot(axis, -slotForward) > 0.9702957`` and
    ``Dot((slot - farEnd).normalized, -slotForward) > 0.9702957``; that constant
    is ``cos 14``.  :data:`~flab2bp.dsp.rules.SLOT_ALIGN_COS` is ``cos 24``, and
    it is a DIFFERENT rule: 24 degrees is the ``TooSkew`` limit on a sorter's own
    end rotations, which ``layout.slots`` reuses as its slot-facing threshold.
    Nothing ties the two numbers together, and the ladder's is tighter.

    ``both connect, to different slots`` -- the ladder measures ``(slotPos -
    end).sqrMagnitude`` in THREE dimensions and keeps the strict minimum, first
    index winning a tie; we measure in the build plane and rank alignment ahead
    of distance.

    Every count is pinned.  A change to either model moves one of them.
    """
    cases, meta = _sweep()
    assert len(cases) == 15488
    tables = {str(i): O.slot_table(i) for i in SWEEP_TYPES}
    verdicts = O.ask(cases, tables=tables)
    assert [v.name for v in verdicts if v.error] == []

    tally: collections.Counter[str] = collections.Counter()
    for v, (item_id, yaw, end, other) in zip(verdicts, meta, strict=True):
        accept, slot = _ours(item_id, yaw, end, other)
        if v.connected and accept:
            tally["same slot" if slot == v.input_from_slot else "different slot"] += 1
        elif v.connected:
            tally["the ladder connects where we refuse"] += 1
        elif accept:
            tally["we accept where the ladder refuses"] += 1
        else:
            tally["both refuse"] += 1

    assert dict(tally) == {
        "both refuse": 14396,
        "the ladder connects where we refuse": 584,
        "same slot": 244,
        "we accept where the ladder refuses": 256,
        "different slot": 8,
    }


@pytest.mark.dotnet
@needs_oracle
def test_the_ladders_reach_gate_is_the_square_root_of_six() -> None:
    """``num4 < 6f`` on a SQUARED magnitude, so 2.449 world units, not 0.8.

    Walked in from far away along the axis a slot faces, the ladder starts
    connecting the moment the squared gap passes under six -- which pins the gate
    as a distance in world units and not in tiles.  Read as tiles it would be
    2.449 TILES and the transition would land somewhere else entirely.
    """
    item_id = 2303  # Assembling Machine Mk.III: slot 0 faces north off a 3x3
    table = {str(item_id): O.slot_table(item_id)}
    cand = O.machine_candidate(item_id, 0.0, (0.0, 0.0), obj_id=1, table=str(item_id))
    sx, sy, sz = S.slot_offset(item_id, 0.0, 0)
    # Straight out along +y from slot 0, one hundredth of a tile at a time.
    steps = [1.0 + 0.01 * i for i in range(300)]
    cases = [
        O.Case(
            name=f"{d:.2f}",
            lpos=O.unity_point(sx, sy + d),
            lpos2=O.unity_point(sx, sy + d + 1.0),
            output_obj_id=999,
            candidates=(cand,),
        )
        for d in steps
    ]
    verdicts = O.ask(cases, tables=table)
    connected = [d for d, v in zip(steps, verdicts, strict=True) if v.connected]
    assert connected, "nothing connected; the sweep missed the gate entirely"
    # The last distance that still connects, expressed as the world-unit gap the
    # ladder actually squares. `sz` is the slot's own height above the end.
    worst = max(connected)
    gap = R.world_gap(0.0, worst, sz)
    assert gap == pytest.approx(6.0**0.5, abs=0.02)
    # ... and the transition is a single one: everything nearer connects.
    assert connected == [d for d in steps if d <= worst + 1e-9]


@pytest.mark.dotnet
@needs_oracle
def test_a_tie_is_kept_by_whichever_came_first() -> None:
    """Both of the ladder's comparisons are strict, so a tie leaves the incumbent.

    ``sqrMagnitude < num8`` inside one candidate and ``num8 < num4`` across
    candidates.  Neither is reachable from a sweep -- an exact tie needs geometry
    built to produce one -- so both are constructed here, and both would flip if
    either comparison were written ``<=``.  The order the candidates arrive in is
    the order ``Physics.OverlapSphereNonAlloc`` filled the buffer, which is why
    :class:`flab2bp.bench.snaporacle.Case` treats it as significant.

    We break the same two ties the same way: :func:`~flab2bp.layout.slots.machine_slot`
    ranks on ``(aligned, distance, index)`` and ``min`` keeps the lowest index.
    """
    # A pair of slots the same distance from the end, straddling it. Forward is
    # +z for both, so a sorter arriving from the north satisfies the ladder's two
    # dots for each of them.
    mirrored = (
        O.SlotPose(pos=(-0.3, 0.0, 1.0), fwd=(0.0, 0.0, 1.0)),
        O.SlotPose(pos=(0.3, 0.0, 1.0), fwd=(0.0, 0.0, 1.0)),
    )
    twin = O.Candidate(kind="entity", obj_id=1, pos=O.unity_point(0.0, 0.0), yaw=0.0,
                       slot_poses=mirrored)
    # Two whole candidates at the same place, distinguishable only by objId.
    single = (O.SlotPose(pos=(0.0, 0.0, 1.0), fwd=(0.0, 0.0, 1.0)),)
    first = O.Candidate(kind="entity", obj_id=7, pos=O.unity_point(0.0, 0.0), yaw=0.0,
                        slot_poses=single)
    second = O.Candidate(kind="entity", obj_id=9, pos=O.unity_point(0.0, 0.0), yaw=0.0,
                         slot_poses=single)
    end = (0.0, 1.0 / colliders.GRID_ARC)
    verdicts = O.ask(
        [
            O.Case(
                name=name,
                lpos=O.unity_point(*end),
                lpos2=O.unity_point(end[0], end[1] + 1.0),
                output_obj_id=999,
                candidates=cands,
            )
            for name, cands in (
                ("slots", (twin,)),
                ("candidates", (first, second)),
                ("candidates-reversed", (second, first)),
            )
        ]
    )
    by_name = {v.name: v for v in verdicts}
    assert all(v.connected for v in verdicts), "nothing tied; the case proves nothing"
    # The two slots really are equidistant, so this pins the comparison and not
    # the geometry.
    assert by_name["slots"].input_from_slot == 0
    assert by_name["candidates"].input_obj_id == 7
    assert by_name["candidates-reversed"].input_obj_id == 9


@pytest.mark.dotnet
@needs_oracle
def test_a_blueprint_internal_peer_reaches_the_preview_branch() -> None:
    """The layer-18 arm of the loop, which is how a paste sees its own buildings.

    A building of the same paste is not an entity and has no collider data; it is
    a ``BuildPreviewModel`` on layer 18, and the ladder reads its slot table off
    ``buildPreview.desc.slotPoses`` instead of ``GetLocalSlots``.  The arm has its
    own copy of the scoring, so it is tested rather than assumed equivalent.
    """
    item_id = 2303
    table = {str(item_id): O.slot_table(item_id)}
    sx, sy, _sz = S.slot_offset(item_id, 0.0, 0)
    end = (sx, sy + 0.5)
    entity = O.machine_candidate(item_id, 0.0, (0.0, 0.0), obj_id=1, table=str(item_id))
    preview = O.machine_candidate(
        item_id, 0.0, (0.0, 0.0), obj_id=0, kind="preview", table=str(item_id)
    )
    made = O.ask(
        [
            O.Case(
                name=kind,
                lpos=O.unity_point(*end),
                lpos2=O.unity_point(end[0], end[1] + 1.0),
                output_obj_id=999,
                candidates=(cand,),
            )
            for kind, cand in (("entity", entity), ("preview", preview))
        ],
        tables=table,
    )
    as_entity, as_preview = made
    assert as_entity.connected and as_preview.connected
    assert as_entity.input_from_slot == as_preview.input_from_slot == 0
    assert as_preview.lpos == pytest.approx(as_entity.lpos)
    # The entity arm records an objId; the preview arm records the preview and
    # leaves inputObjId at zero. That difference is the game's, not ours.
    assert as_entity.input_obj_id == 1
    assert as_entity.input_preview == -1
    assert as_preview.input_obj_id == 0
    assert as_preview.input_preview == 0


@pytest.mark.dotnet
@needs_oracle
def test_a_prebuilt_belt_snaps_nothing_at_all() -> None:
    """``num5 < 0`` reaches neither arm of the belt branch, so ``flag3`` stays false.

    ``if (num5 > 0) { ... } else if (num5 >= 0) { }`` -- a PREBUILD belt is
    negative and falls through both, which leaves the end unsnapped and the
    preview ``NeedConn``.  It looks like an omission in the decompilation and is
    not: a built belt of the same geometry connects.
    """
    belt_pos = (0.0, 1.0)
    path = O.BeltPath(
        seg_index=0,
        seg_length=10,
        seg_pivot_offset=5,
        path_length=20,
        point_pos=tuple(O.unity_point(i - 10.0, 1.0) for i in range(21)),
        point_rot=tuple((0.0, 0.0, 0.0, 1.0) for _ in range(21)),
    )
    built = O.Candidate(
        kind="entity", obj_id=1, is_belt=True, pos=O.unity_point(*belt_pos), yaw=0.0, belt=path
    )
    prebuilt = O.Candidate(
        kind="prebuild", obj_id=1, is_belt=True, pos=O.unity_point(*belt_pos), yaw=0.0, belt=path
    )
    verdicts = O.ask(
        [
            O.Case(
                name=name,
                lpos=O.unity_point(0.0, 0.9),
                lpos2=O.unity_point(0.0, -0.5),
                output_obj_id=999,
                candidates=(cand,),
            )
            for name, cand in (("built", built), ("prebuilt", prebuilt))
        ]
    )
    as_built, as_prebuilt = verdicts
    assert [v.error for v in verdicts] == [None, None]
    assert as_built.connected, "the belt branch never fired; the case proves nothing"
    assert as_built.input_from_slot == R.BELT_SLOT
    assert not as_prebuilt.connected


# --- our own output, against the build the game made of it -----------------

_OURS = FIXTURES / "ours"


@pytest.mark.dotnet
@needs_oracle
@pytest.mark.skipif(
    not (_OURS / "sorter-collide-freeform.txt").is_file(),
    reason="needs tests/fixtures/ours/sorter-collide-freeform.txt",
)
def test_match_inserter_is_not_what_refused_our_five_sorters() -> None:
    """Our 352-building blueprint: every sorter end names a peer INSIDE it.

    ``BlueprintUtils`` line 1623 gives such an end its peer preview directly, and
    ``BuildTool_BlueprintPaste`` line 1795 runs ``MatchInserter`` only when that
    preview is null.  So the ladder never ran on any of these 76 ends, and it is
    not what made the game refuse five of them -- whatever did, it was not this.

    Stated as a test rather than a comment because it is a property of what we
    EMIT, and it would stop being true the moment we emitted a sorter reaching
    for something outside the blueprint.
    """
    bp = decode((_OURS / "sorter-collide-freeform.txt").read_text().strip())
    by_index = {b.index: b for b in bp.buildings}
    ends = [
        ref
        for b in bp.buildings
        if cat.is_sorter(b.item_id)
        for ref in (b.input_obj_idx, b.output_obj_idx)
    ]
    assert len(ends) == 76
    assert all(ref in by_index for ref in ends), "an end reaches outside the blueprint"
