# /// script
# requires-python = ">=3.11"
# dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI"]
# ///
"""Extract every building's BUILD COLLIDERS from a game install.

    uv run scripts/extract_dsp_colliders.py [GAME_DIR]

Writes ``src/flab2bp/dsp/data/colliders.json``: ``modelIndex -> [{pos, ext, q}]``,
the exact ``PrefabDesc.buildColliders`` array the game tests for
``EBuildCondition.Collide``.  See ``flab2bp.dsp.colliders`` for what consumes it.

WHY THIS EXISTS RATHER THAN ``blueprintBoxSize``
------------------------------------------------
``buildings.json`` carries ``blueprintBoxSize``, and the game derives THAT from a
collider rather than the other way round (``PrefabDesc.ReadPrefab``, decompiled
line 217456)::

    blueprintBoxSize = new Vector2(buildCollider.ext.x * 2f, buildCollider.ext.z * 2f);

``buildCollider`` is the LAST Build box found -- and when a prefab has more than
two Build boxes that last one is precisely the one EXCLUDED from
``buildColliders`` (lines 217212-217248).  So for every multi-collider building
``blueprintBoxSize`` describes a box the collision test never uses.  A Spray
Coater is the clearest case: its ``blueprintBoxSize`` is 0.7 x 2.0, but the box
actually tested is 0.7 x 3.5.

EXTRACTION RULES, ALL FROM ``PrefabDesc.ReadPrefab``
----------------------------------------------------
* Colliders come from ``colliderPrefab.GetComponentsInChildren<Collider>(true)``
  (line 217145) -- depth-first over the transform hierarchy, components in the
  GameObject's own ``m_Component`` order.  That ordering is load-bearing: it
  decides which box is dropped.
* ``ColliderData.InitFromCollider`` (line 28828) tags usage from ``isTrigger``::

      int num = (collider.isTrigger ? ((!independent) ? 1 : 2) : 0) << 29;

  and ``isForBuild`` is ``usage == 1``.  Every building prefab here loads through
  the one-argument ``PrefabDesc`` constructor (no ``<path>-cl`` sibling asset),
  so ``independent`` is false and **a Build collider is a trigger BoxCollider**.
* ``pos`` is ``transform.TransformPoint(box.center)`` and ``q`` is
  ``transform.rotation`` -- both relative to the prefab root.  ``ext`` is
  ``box.size * 0.5`` and is deliberately NOT scaled by the transform, matching
  the game.

VALIDATION
----------
For the 44 of 61 catalog prefabs with at most two Build boxes, recomputing
``blueprintBoxSize`` from the extracted ``buildCollider`` reproduces
``buildings.json`` to within 0.012.  The 16 that differ all have three or more
Build boxes, where the two tables disagree about component order; on those,
``buildings.json`` is internally inconsistent (it gives the Planetary and
Interstellar Logistics Stations, whose collider sets are identical, different
values) so it cannot arbitrate.  The tie is broken by the negative control in
``tests/dsp/test_colliders.py`` instead.
"""

from __future__ import annotations

import json
import os
import sys

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

UNITY_VERSION = "2022.3.62f3c1"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "src", "flab2bp", "dsp", "data", "colliders.json")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def qmul(a, b):  # noqa: ANN001, ANN201
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def qrot(q, v):  # noqa: ANN001, ANN201
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "/home/dannyb/Dyson Sphere Program"
    data_dir = os.path.join(game, "DSPGAME_Data")
    if not os.path.isdir(data_dir):
        data_dir = game
    managed = os.path.join(data_dir, "Managed")
    res = os.path.join(data_dir, "resources.assets")
    if not os.path.isdir(managed):
        fail(f"{managed} not found; the whole Managed/ folder is required for typetrees")
    if not os.path.isfile(res):
        fail(f"{res} not found")

    gen = TypeTreeGenerator(UNITY_VERSION)
    gen.load_local_dll_folder(managed)
    env = UnityPy.load(res)

    gos: dict[int, dict] = {}
    trs: dict[int, dict] = {}
    boxes: dict[int, dict] = {}
    others: set[int] = set()
    model_set: dict | None = None
    for obj in env.objects:
        name = obj.type.name
        if name == "GameObject":
            gos[obj.path_id] = obj.read_typetree()
        elif name == "Transform":
            trs[obj.path_id] = obj.read_typetree()
        elif name == "BoxCollider":
            boxes[obj.path_id] = obj.read_typetree()
        elif name in ("SphereCollider", "CapsuleCollider", "MeshCollider", "TerrainCollider"):
            others.add(obj.path_id)
        elif name == "MonoBehaviour" and model_set is None:
            try:
                script = obj.read(check_read=False).m_Script
                if script and script.read().m_ClassName == "ModelProtoSet":
                    nodes = gen.get_nodes_up("Assembly-CSharp", "ModelProtoSet")
                    model_set = obj.read_typetree(nodes)
            except Exception:  # noqa: BLE001 - a stray unreadable object must not abort the scan
                continue
    if model_set is None:
        fail("ModelProtoSet not found in resources.assets")

    roots: dict[str, list[int]] = {}
    for pid, t in trs.items():
        if t["m_Father"]["m_PathID"] == 0:
            roots.setdefault(gos[t["m_GameObject"]["m_PathID"]]["m_Name"], []).append(pid)

    def walk(root: int) -> list[tuple[int, tuple, tuple, tuple]]:
        out: list[tuple[int, tuple, tuple, tuple]] = []

        def rec(pid: int, pp: tuple, pr: tuple, ps: tuple) -> None:
            t = trs[pid]
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            lpv = (lp["x"] * ps[0], lp["y"] * ps[1], lp["z"] * ps[2])
            wp = tuple(a + b for a, b in zip(pp, qrot(pr, lpv), strict=True))
            wr = qmul(pr, (lr["x"], lr["y"], lr["z"], lr["w"]))
            ws = (ps[0] * ls["x"], ps[1] * ls["y"], ps[2] * ls["z"])
            out.append((pid, wp, wr, ws))
            for ch in t["m_Children"]:
                rec(ch["m_PathID"], wp, wr, ws)

        rec(root, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        return out

    def colliders_of(root: int) -> list[dict]:
        """GetComponentsInChildren<Collider>(includeInactive: true) order."""
        out: list[dict] = []
        for pid, wp, wr, ws in walk(root):
            gpid = trs[pid]["m_GameObject"]["m_PathID"]
            for comp in gos[gpid]["m_Component"]:
                cp = comp["component"]["m_PathID"] if "component" in comp else comp["m_PathID"]
                if cp in boxes:
                    bc = boxes[cp]
                    c, s = bc["m_Center"], bc["m_Size"]
                    r = qrot(wr, (c["x"] * ws[0], c["y"] * ws[1], c["z"] * ws[2]))
                    out.append(
                        {
                            "box": True,
                            "trigger": bool(bc["m_IsTrigger"]),
                            "pos": [wp[i] + r[i] for i in range(3)],
                            "ext": [s["x"] / 2, s["y"] / 2, s["z"] / 2],
                            "q": list(wr),
                        }
                    )
                elif cp in others:
                    out.append({"box": False, "trigger": False})
        return out

    table: dict[str, list[dict]] = {}
    for proto in model_set["dataArray"]:
        prefab = (proto.get("PrefabPath") or "").split("/")[-1]
        if not prefab or prefab not in roots:
            continue
        best: list[dict] | None = None
        for root in roots[prefab]:
            cols = colliders_of(root)
            if any(c["trigger"] and c["box"] for c in cols) and (
                best is None or len(cols) > len(best)
            ):
                best = cols
        if best is None:
            continue
        build = [i for i, c in enumerate(best) if c["trigger"] and c["box"]]
        # PrefabDesc.ReadPrefab lines 217223-217248: one box -> [1], two -> [2],
        # three or more -> the FIRST n-1, the last being shrunk to 0.1 and dropped.
        keep = 1 if len(build) == 1 else (2 if len(build) == 2 else len(build) - 1)
        table[str(proto["ID"])] = [
            {
                "pos": [round(v, 6) for v in best[i]["pos"]],
                "ext": [round(v, 6) for v in best[i]["ext"]],
                "q": [round(v, 6) for v in best[i]["q"]],
            }
            for i in build[:keep]
        ]

    # A current install yields 252.  The floor sits just under it, so a real
    # update raises the count and a truncated read trips the guard.
    if len(table) < 240:
        fail(f"only {len(table)} models carry a build collider; the scan looks truncated")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(table, fh, separators=(",", ":"), sort_keys=True)
    print(f"wrote {len(table)} models -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
