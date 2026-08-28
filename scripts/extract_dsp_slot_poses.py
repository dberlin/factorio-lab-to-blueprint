# /// script
# requires-python = ">=3.14"
# dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI"]
# ///
"""Extract every building's ``PrefabDesc.slotPoses`` from a game install.

    uv run scripts/extract_dsp_slot_poses.py [GAME_DIR]

Writes ``src/flab2bp/dsp/data/slot_poses.json``: for each prefab, the local
model-space pose of every sorter slot the game defines on it.

WHY THIS EXISTS
---------------
``CheckInserterDataLegal`` -- the game's own predicate for "is this sorter's
data legal", ported into ``layout.validate`` as ``game.inserter_data`` -- reads
``PrefabDesc.slotPoses[slot]``, transforms it by the machine's pose, and rejects
the sorter when its end lands further than 0.8 from the result.  Without the
real poses that check cannot run, and we were left inferring the slot ring from
seven observed buildings.

``buildings.json`` already carries a ``slots`` array, and it is NOT this.  In
``PrefabDesc.ReadPrefab`` the game reads ONE component::

    SlotConfig sc = prefab.GetComponentInChildren<SlotConfig>(true);
    portPoses = sc.slotPoses   // fluid / belt ports
    slotPoses = sc.insertPoses // where a sorter may attach

Whatever produced ``buildings.json`` took ``SlotConfig.slotPoses`` -- the fluid
ports -- and called them "slots".  That is why an Assembling Machine came out
with none while the Storage Tank came out with four, and why nothing in this
repo could say where a sorter is allowed to touch a Chemical Plant.  The name
collision is the whole bug: the field a sorter's slot index means is
``insertPoses``.

The poses are Unity ``Transform.position`` / ``.rotation`` -- WORLD space inside
the prefab, which is model-local space for the placed building.  Model space is
Unity's: ``+x`` right, ``+y`` up (away from the planet), ``+z`` forward.  The
mapping onto our tile grid is asserted against the 1288-sorter corpus by
``tests/layout/test_game_slot_poses.py``; nothing here assumes it.

Values are rounded to 4 decimals.  The poses are authored on a 0.4-tile lattice
and the float32 they are stored in carries about 7 digits, so 4 keeps every
distinction the game makes and stops meaningless last-bit churn from showing up
as a diff on re-extraction.
"""

from __future__ import annotations

import json
import os
import sys

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

UNITY_VERSION = "2022.3.62f3c1"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "src", "flab2bp", "dsp", "data")

#: Prefabs that must come back with slot poses. Every one is a production
#: building we place, and a run that loses them would otherwise write a
#: plausible-looking file that silently disables the check that needs it.
REQUIRED = {
    "assembler-mk-1",
    "assembler-mk-2",
    "assembler-mk-3",
    "smelter",
    "smelter-2",
    "smelter-3",
    "chemical-plant",
    "oil-refinery",
    "lab",
    "storage-1",
}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def qmul(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def qrot(q: tuple[float, float, float, float], v: tuple[float, float, float]):
    """``q * v``, the Unity quaternion-times-vector product."""
    x, y, z, w = q
    vx, vy, vz = v
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def local_trs(tr) -> tuple[tuple, tuple, tuple]:
    p, r, s = tr.m_LocalPosition, tr.m_LocalRotation, tr.m_LocalScale
    return (
        (float(p.x), float(p.y), float(p.z)),
        (float(r.x), float(r.y), float(r.z), float(r.w)),
        (float(s.x), float(s.y), float(s.z)),
    )


def chain_to_root(tr, objs) -> list:
    """``tr`` and every ancestor, root first."""
    out = [tr]
    while True:
        f = out[-1].m_Father
        if not f or f.path_id == 0:
            break
        nxt = objs.get(f.path_id)
        if nxt is None:
            fail("a Transform's parent is outside resources.assets")
        out.append(nxt.read())
    out.reverse()
    return out


def world_pose(tr, objs) -> tuple[tuple, tuple]:
    """Unity ``Transform.position`` / ``.rotation`` for a transform in a prefab.

    Composed the way Unity does, parent scale included: a child's offset is
    scaled by its parent before being rotated into place.
    """
    pos = (0.0, 0.0, 0.0)
    rot = (0.0, 0.0, 0.0, 1.0)
    scale = (1.0, 1.0, 1.0)
    for node in chain_to_root(tr, objs):
        lp, lr, ls = local_trs(node)
        scaled = (lp[0] * scale[0], lp[1] * scale[1], lp[2] * scale[2])
        turned = qrot(rot, scaled)
        pos = (pos[0] + turned[0], pos[1] + turned[1], pos[2] + turned[2])
        rot = qmul(rot, lr)
        scale = (scale[0] * ls[0], scale[1] * ls[1], scale[2] * ls[2])
    return pos, rot


def root_name(tr, objs) -> str:
    root = chain_to_root(tr, objs)[0]
    go = objs.get(root.m_GameObject.path_id)
    return go.read().m_Name if go else "?"


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "/home/dannyb/Dyson Sphere Program"
    data_dir = os.path.join(game, "DSPGAME_Data")
    if not os.path.isdir(data_dir):
        data_dir = game
    managed = os.path.join(data_dir, "Managed")
    if not os.path.isdir(managed):
        fail(f"{managed} not found. The whole Managed/ folder is required for typetrees.")
    res = os.path.join(data_dir, "resources.assets")
    if not os.path.isfile(res):
        fail(f"{res} not found")

    gen = TypeTreeGenerator(UNITY_VERSION)
    gen.load_local_dll_folder(managed)
    nodes = gen.get_nodes_up("Assembly-CSharp", "SlotConfig")

    env = UnityPy.load(res)
    objs = {o.path_id: o for o in env.objects}
    print(f"resources.assets: {len(objs)} objects")

    # Only building prefabs are wanted. resources.assets also holds scenery and
    # enemy-unit prefabs that carry a SlotConfig of their own, and some of those
    # share a root name with each other.
    with open(os.path.join(OUT, "buildings.json"), encoding="utf-8") as fh:
        prefabs = {row["prefab"] for row in json.load(fh)}

    found: dict[str, dict] = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            script = obj.read(check_read=False).m_Script
            if not script or script.read().m_ClassName != "SlotConfig":
                continue
        except Exception:  # noqa: BLE001 - a stray unreadable object must not abort the scan
            continue
        tree = obj.read_typetree(nodes)
        inserts = tree.get("insertPoses") or []
        ports = tree.get("slotPoses") or []
        if not inserts and not ports and not tree.get("addonAreaCenter"):
            continue
        holder = objs.get(tree["m_GameObject"]["m_PathID"])
        if holder is None:
            continue
        holder_tr = None
        for comp in holder.read().m_Components:
            c = objs.get(comp.path_id)
            if c is not None and c.type.name in ("Transform", "RectTransform"):
                holder_tr = c.read()
                break
        if holder_tr is None:
            continue
        name = root_name(holder_tr, objs)
        if name not in prefabs:
            continue

        def poses(ptrs, who: str = name) -> list[dict]:
            out = []
            for ptr in ptrs:
                t = objs.get(ptr["m_PathID"])
                if t is None:
                    fail(f"{who}: a pose Transform is missing from resources.assets")
                p, r = world_pose(t.read(), objs)
                # `fwd` is `Pose.forward` -- the direction the game tests a
                # sorter's approach against -- resolved here so nothing
                # downstream needs quaternion arithmetic to use the table.
                out.append(
                    {
                        "pos": [round(v, 4) for v in p],
                        "fwd": [round(v, 6) for v in qrot(r, (0.0, 0.0, 1.0))],
                    }
                )
            return out

        # `addonAreaCenter` is a plain Vector3[] on the component, and
        # `PrefabDesc.addonAreaPoses[n]` is built straight from it. It is where
        # the game LOOKS for the belts an addon attaches to: on build it takes
        # the nearest belt within 1.0 of each area and writes the connection
        # itself, which is why a Spray Coater in a blueprint carries no
        # connection of its own. Area 0 is the cargo belt it sprays, area 1 the
        # proliferator supply.
        areas = [
            [round(v, 4) for v in (a["x"], a["y"], a["z"])]
            for a in (tree.get("addonAreaCenter") or [])
        ]
        entry = {
            "slotPoses": poses(inserts),
            "portPoses": poses(ports),
            "addonAreas": areas,
        }
        prev = found.get(name)
        if prev is not None and prev != entry:
            # Every building prefab carries exactly ONE SlotConfig, on its root,
            # and the game reads it with GetComponentInChildren -- so two that
            # disagree would mean the one we picked is arbitrary and the table is
            # not reproducible. Scene copies of a prefab share its name and its
            # values, which is why identical duplicates are simply kept.
            fail(f"{name} has two SlotConfig components that disagree")
        found[name] = entry

    table = dict(sorted(found.items()))

    missing = sorted(p for p in REQUIRED if not table.get(p, {}).get("slotPoses"))
    if missing:
        fail(f"no slot poses extracted for {missing}; the scan is not finding SlotConfig")

    path = os.path.join(OUT, "slot_poses.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(table, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")
    n = sum(len(e["slotPoses"]) for e in table.values())
    with_slots = sum(1 for e in table.values() if e["slotPoses"])
    print(f"wrote {with_slots} prefabs with slots ({n} poses) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
