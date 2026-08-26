"""Drive the C# transcription of ``MatchInserter`` and read its verdicts back.

The oracle itself lives in ``oracle/`` and is C#: ``BuildTool_BlueprintPaste``'s
snap ladder copied out of the decompiled shipped assembly and compiled against
the game's own ``Assembly-CSharp.dll``, so the arithmetic that decides which slot
a sorter snaps to is the game's rather than a paraphrase of it.

WHAT A COMPARISON AGAINST IT PROVES
-----------------------------------
That our port of the LADDER is faithful -- the thresholds, the ordering, the
tie-breaks, the refusals.  Nothing more.  The game finds its candidates with
``Physics.OverlapSphereNonAlloc`` against a live PhysX scene, and that query
cannot be run outside the game; here the candidate set is an INPUT.  So a
disagreement is a real defect in our ladder, and agreement says nothing about
whether we predict the right candidate set -- which is a separate question,
answerable only against the real scene.

Everything degrades to a clean skip when ``dotnet`` or the game install is
absent, and :func:`unavailable_reason` names exactly which.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders
from flab2bp.dsp.rules import WORLD_UNITS_PER_LEVEL

__all__ = [
    "BeltPath",
    "Candidate",
    "Case",
    "OracleUnavailable",
    "SlotPose",
    "Step",
    "Verdict",
    "ask",
    "dotnet_available",
    "game_managed_dir",
    "machine_candidate",
    "oracle_available",
    "selftest",
    "unavailable_reason",
    "unity_point",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROJECT = _REPO_ROOT / "oracle" / "SnapOracle.csproj"
_BUILT = _REPO_ROOT / "oracle" / "bin" / "Release" / "net10.0" / "snaporacle.dll"

#: Where a default Steam install on this machine keeps the managed assemblies.
#: ``$DSP_MANAGED`` overrides it, the way ``$DSP_VIEWER_PATH`` overrides the
#: viewer checkout in :mod:`flab2bp.bench.crossvalidate`.
_DEFAULT_MANAGED = Path.home() / "Dyson Sphere Program" / "DSPGAME_Data" / "Managed"

#: The two assemblies the oracle compiles against.  Both are the SHIPPED game's;
#: neither is vendored into this repository.
_NEEDED = ("Assembly-CSharp.dll", "UnityEngine.CoreModule.dll")


class OracleUnavailable(RuntimeError):
    """Raised only when the caller demanded strictness."""


def dotnet_available() -> bool:
    return shutil.which("dotnet") is not None


def game_managed_dir() -> Path | None:
    """The game's ``Managed/`` directory, or ``None`` if it is not installed."""
    override = os.environ.get("DSP_MANAGED")
    candidate = Path(override) if override else _DEFAULT_MANAGED
    if all((candidate / dll).is_file() for dll in _NEEDED):
        return candidate
    return None


def unavailable_reason() -> str | None:
    """Why the oracle cannot run here, phrased for a skip message."""
    missing = []
    if not dotnet_available():
        missing.append("the `dotnet` SDK")
    if game_managed_dir() is None:
        missing.append(
            f"a Dyson Sphere Program install carrying {' and '.join(_NEEDED)} "
            f"(looked in {_DEFAULT_MANAGED}; set DSP_MANAGED)"
        )
    if not _PROJECT.is_file():
        missing.append(f"the oracle project at {_PROJECT}")
    if not missing:
        return None
    return "the C# snap oracle needs " + " and ".join(missing)


def oracle_available() -> bool:
    return unavailable_reason() is None


# --- the wire format -------------------------------------------------------
#
# Positions are Unity world units in Unity axes (`+y` up, `+z` "north"), NOT
# this project's tile grid.  `unity_point` is the only place that conversion
# happens, so the C# side stays free of anything of ours.


@dataclass(frozen=True, slots=True)
class SlotPose:
    """One entry of ``PrefabDesc.slotPoses``, in the building's own frame."""

    pos: tuple[float, float, float]
    #: ``Pose.forward``.  The rotation is rebuilt from it by the game's own
    #: ``Maths.LookRotation``; see the note in ``oracle/Model.cs``.
    fwd: tuple[float, float, float] | None = None
    rot: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class BeltPath:
    """The ``CargoPath`` fields the belt branch of the ladder reads."""

    seg_index: int
    seg_length: int
    seg_pivot_offset: int
    path_length: int
    point_pos: tuple[tuple[float, float, float], ...]
    point_rot: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One collider the sphere query is taken to have returned.

    ``kind`` is what the physics layer would have said about it: ``entity`` and
    ``prebuild`` resolve through ``GetColliderData``, ``preview`` is another
    building of the same paste sitting on layer 18, ``othertype`` is collider
    data the ladder skips, and ``other`` is a collider that resolves to nothing.
    """

    kind: str
    pos: tuple[float, float, float]
    obj_id: int = 0
    is_belt: bool = False
    yaw: float | None = None
    rot: tuple[float, float, float, float] | None = None
    bp_pos: tuple[float, float, float] | None = None
    bp_rot: tuple[float, float, float, float] | None = None
    slot_poses: tuple[SlotPose, ...] = ()
    #: A key into the shared slot-table library, used instead of ``slot_poses``.
    #: A dense sweep asks the same building thousands of times and its twelve
    #: poses are the bulk of every case; naming the table once keeps that
    #: affordable and changes nothing the ladder sees.
    slot_table: str | None = None
    belt: BeltPath | None = None


@dataclass(frozen=True, slots=True)
class Case:
    """One call to ``MatchInserter``: a sorter's two ends and its candidate set."""

    name: str
    lpos: tuple[float, float, float]
    lpos2: tuple[float, float, float]
    yaw: float = 0.0
    yaw2: float = 0.0
    input_obj_id: int = 0
    output_obj_id: int = 0
    input_preview: int = -1
    output_preview: int = -1
    candidates: tuple[Candidate, ...] = ()


@dataclass(frozen=True, slots=True)
class Step:
    """One turn of the ladder's loop, as it happened."""

    side: str
    num4: float
    num5: int
    num6: int
    preview: int
    flag4: bool
    flag3: bool
    scores: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the ladder decided for one case."""

    name: str
    condition: str
    lpos: tuple[float, float, float]
    lpos2: tuple[float, float, float]
    lrot: tuple[float, float, float, float]
    lrot2: tuple[float, float, float, float]
    input_obj_id: int
    output_obj_id: int
    input_preview: int
    output_preview: int
    input_from_slot: int
    input_to_slot: int
    input_offset: int
    output_from_slot: int
    output_to_slot: int
    output_offset: int
    trace: tuple[Step, ...] = ()
    error: str | None = None

    @property
    def connected(self) -> bool:
        return self.condition == "Ok"


# --- our grid, in the game's units -----------------------------------------


def unity_point(x: float, y: float, level: float = 0.0) -> tuple[float, float, float]:
    """A tile coordinate as a Unity world point, on a flat tangent frame.

    ``(east tiles, north tiles, altitude levels)`` becomes Unity's
    ``(x, y, z)`` with ``+y`` up and ``+z`` north, scaled by the same
    :data:`~flab2bp.dsp.colliders.GRID_ARC` and
    :data:`~flab2bp.dsp.rules.WORLD_UNITS_PER_LEVEL` that
    :func:`~flab2bp.dsp.rules.world_gap` uses.

    THE FRAME IS FLAT AND THE PLANET IS NOT.  A real ``lpos`` sits on a sphere of
    radius 200, so a blueprint's tiles curve away from any tangent plane.  This
    is deliberate: our own model is flat everywhere, so feeding the oracle the
    same flat frame isolates the LADDER's arithmetic from the projection, which
    is a separate question and not one this comparison can settle.  The one place
    curvature enters the ladder itself is the belt branch's
    ``vector4 -= vector4.normalized * 0.15f``, which is why a caller exercising
    that branch must place its geometry on a real sphere instead.
    """
    return (x * colliders.GRID_ARC, level * WORLD_UNITS_PER_LEVEL, y * colliders.GRID_ARC)


def machine_candidate(
    item_id: int,
    yaw: float,
    centre: tuple[float, float],
    *,
    obj_id: int = 0,
    kind: str = "entity",
    level: float = 0.0,
    table: str | None = None,
) -> Candidate:
    """A building of ``item_id`` at ``centre`` tiles, with its real slot table.

    The slot poses come from :attr:`flab2bp.dsp.catalog.Building.slot_poses`,
    which is the game's own ``PrefabDesc.slotPoses`` extracted from the install --
    so the geometry the oracle scores is the geometry the game would score.  They
    are mapped back out of our grid axes into Unity's, undoing exactly the
    permutation :class:`~flab2bp.dsp.catalog.SlotPose` documents.
    """
    return Candidate(
        kind=kind,
        obj_id=obj_id,
        pos=unity_point(centre[0], centre[1], level),
        yaw=yaw,
        slot_poses=() if table else slot_table(item_id),
        slot_table=table,
    )


# --- running it ------------------------------------------------------------


def _payload(case: Case) -> dict[str, Any]:
    def slot(p: SlotPose) -> dict[str, Any]:
        out: dict[str, Any] = {"pos": list(p.pos)}
        if p.rot is not None:
            out["rot"] = list(p.rot)
        if p.fwd is not None:
            out["fwd"] = list(p.fwd)
        return out

    def cand(c: Candidate) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": c.kind,
            "objId": c.obj_id,
            "isBelt": c.is_belt,
            "pos": list(c.pos),
            "slotPoses": [slot(p) for p in c.slot_poses],
        }
        if c.rot is not None:
            out["rot"] = list(c.rot)
        if c.yaw is not None:
            out["yaw"] = c.yaw
        if c.bp_pos is not None:
            out["bpPos"] = list(c.bp_pos)
        if c.bp_rot is not None:
            out["bpRot"] = list(c.bp_rot)
        if c.slot_table is not None:
            out["slotTable"] = c.slot_table
        if c.belt is not None:
            out["belt"] = {
                "segIndex": c.belt.seg_index,
                "segLength": c.belt.seg_length,
                "segPivotOffset": c.belt.seg_pivot_offset,
                "pathLength": c.belt.path_length,
                "pointPos": [list(p) for p in c.belt.point_pos],
                "pointRot": [list(q) for q in c.belt.point_rot],
            }
        return out

    return {
        "name": case.name,
        "lpos": list(case.lpos),
        "lpos2": list(case.lpos2),
        "yaw": case.yaw,
        "yaw2": case.yaw2,
        "inputObjId": case.input_obj_id,
        "outputObjId": case.output_obj_id,
        "inputPreview": case.input_preview,
        "outputPreview": case.output_preview,
        "candidates": [cand(c) for c in case.candidates],
    }


def _step(raw: dict[str, Any]) -> Step:
    return Step(
        side=raw["side"],
        num4=raw["num4"],
        num5=raw["num5"],
        num6=raw["num6"],
        preview=raw["preview"],
        flag4=raw["flag4"],
        flag3=raw["flag3"],
        scores=tuple(raw.get("scores") or ()),
    )


def _verdict(raw: dict[str, Any]) -> Verdict:
    def vec(key: str) -> tuple[float, float, float]:
        v = raw.get(key) or [0.0, 0.0, 0.0]
        return (v[0], v[1], v[2])

    def quat(key: str) -> tuple[float, float, float, float]:
        v = raw.get(key) or [0.0, 0.0, 0.0, 1.0]
        return (v[0], v[1], v[2], v[3])

    return Verdict(
        name=raw["name"],
        condition=raw.get("condition", ""),
        lpos=vec("lpos"),
        lpos2=vec("lpos2"),
        lrot=quat("lrot"),
        lrot2=quat("lrot2"),
        input_obj_id=raw.get("inputObjId", 0),
        output_obj_id=raw.get("outputObjId", 0),
        input_preview=raw.get("inputPreview", -1),
        output_preview=raw.get("outputPreview", -1),
        input_from_slot=raw.get("inputFromSlot", 0),
        input_to_slot=raw.get("inputToSlot", 0),
        input_offset=raw.get("inputOffset", 0),
        output_from_slot=raw.get("outputFromSlot", 0),
        output_to_slot=raw.get("outputToSlot", 0),
        output_offset=raw.get("outputOffset", 0),
        trace=tuple(_step(s) for s in (raw.get("trace") or ())),
        error=raw.get("error"),
    )


def _build(timeout_s: float) -> Path:
    """Compile the oracle, once.  Warnings are errors; a failure is not hidden."""
    managed = game_managed_dir()
    if managed is None or not _PROJECT.is_file():
        raise OracleUnavailable(unavailable_reason() or "the oracle cannot be built")
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "dotnet",
            "build",
            str(_PROJECT),
            "-c",
            "Release",
            "--nologo",
            "-v",
            "q",
            f"-p:DspManaged={managed}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0 or not _BUILT.is_file():
        raise OracleUnavailable(
            f"building the oracle failed ({proc.returncode}):\n{proc.stdout[-2000:]}"
        )
    return _BUILT


def _run(args: list[str], stdin: str, timeout_s: float) -> subprocess.CompletedProcess[str]:
    dll = _build(timeout_s)
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["dotnet", str(dll), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def selftest(*, timeout_s: float = 200.0) -> list[str]:
    """Check the two substituted ``Quaternion`` members against shipped game code.

    Returns the failures; empty means both agree with what
    ``Maths.LookRotation`` and ``Maths.Forward`` -- real, managed, shipped --
    compute for the same rotations.
    """
    proc = _run(["--selftest"], "", timeout_s)
    if not proc.stdout.strip():
        raise OracleUnavailable(f"selftest produced nothing: {proc.stderr[-2000:]}")
    parsed: dict[str, Any] = json.loads(proc.stdout)
    failures: list[str] = list(parsed.get("failures") or ())
    return failures


def slot_table(item_id: int) -> tuple[SlotPose, ...]:
    """``PrefabDesc.slotPoses`` for ``item_id``, in Unity axes.

    The game's own table, extracted from the install by
    ``scripts/extract_dsp_slot_poses.py`` and served by
    :attr:`flab2bp.dsp.catalog.Building.slot_poses` -- mapped back out of our grid
    axes into Unity's, undoing exactly the permutation
    :class:`~flab2bp.dsp.catalog.SlotPose` documents.
    """
    return tuple(
        SlotPose(pos=(p.dx, p.dz, p.dy), fwd=(p.fx, p.fz, p.fy))
        for p in cat.building(item_id).slot_poses
    )


def ask(
    cases: list[Case],
    *,
    tables: dict[str, tuple[SlotPose, ...]] | None = None,
    timeout_s: float = 200.0,
) -> list[Verdict]:
    """Run every case through the transcribed ladder, one subprocess for all.

    A case whose transcription raised comes back with ``error`` set rather than
    silently dropped; callers must treat that as a failure, not as agreement.
    """
    if not cases:
        return []
    payload = json.dumps(
        {
            "slotTables": {
                k: [
                    {"pos": list(p.pos), **({"fwd": list(p.fwd)} if p.fwd else {})}
                    for p in v
                ]
                for k, v in (tables or {}).items()
            },
            "cases": [_payload(c) for c in cases],
        }
    )
    proc = _run([], payload, timeout_s)
    if proc.returncode != 0:
        raise OracleUnavailable(
            f"the oracle exited {proc.returncode}: {proc.stderr[-2000:]}"
        )
    raw: list[dict[str, Any]] = json.loads(proc.stdout)
    if len(raw) != len(cases):
        raise OracleUnavailable(
            f"asked for {len(cases)} verdicts and got {len(raw)}"
        )
    return [_verdict(r) for r in raw]


# --- reading the answers back into our own units ---------------------------


def to_tiles(p: tuple[float, float, float]) -> tuple[float, float, float]:
    """The inverse of :func:`unity_point`: Unity world point back to our grid."""
    return (
        p[0] / colliders.GRID_ARC,
        p[2] / colliders.GRID_ARC,
        p[1] / WORLD_UNITS_PER_LEVEL,
    )


def tile_gap(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Straight-line distance between two Unity world points, in WORLD UNITS."""
    return math.dist(a, b)


@dataclass(frozen=True, slots=True)
class Disagreement:
    """One case where our model and the game's ladder answered differently."""

    case: str
    what: str
    ours: str
    game: str
    detail: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.case}: {self.what} -- ours {self.ours}, game {self.game}"
