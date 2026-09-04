"""Rewrite the ``power`` block of ``dsp/data/buildings.json`` from the game.

WHY THIS SCRIPT EXISTS
----------------------
``buildings.json`` already carried three fields off the prefab's ``PowerDesc``
component -- ``node``, ``connectDistance``, ``coverRadius`` -- and nothing said
where they came from.  ``EBuildCondition.PowerTooClose`` needs three MORE fields
from the same component, and the tier the rule picks is decided by them::

    BuildTool_BlueprintPaste.cs:2527
        if (buildPreview2.desc.isPowerNode && !buildPreview2.desc.isAccumulator)
    BuildTool_BlueprintPaste.cs:2547
        float num37 = (geothermal ? 144f : (windForcedPower ? 110.25f : 12.25f));

``PrefabDesc.cs:1438-1453`` reads every one of them off the same component::

    isPowerNode     = componentInChildren23.node;
    isPowerGen      = componentInChildren23.generator;
    windForcedPower = componentInChildren23.wind;
    geothermal      = componentInChildren23.geothermal;
    isAccumulator   = componentInChildren23.accumulator;

so hand-writing "the wind one is 2203" in Python would be a guess wearing a
citation's clothes: it happens to be right, and nothing would notice when a
patch adds a second wind generator.  This reads the shipped prefabs instead.

``componentInChildren23`` is ``prefab.GetComponentInChildren<PowerDesc>(true)``
(``PrefabDesc.cs:1283``), so the walk below is breadth-first from the prefab
root and takes the first ``PowerDesc`` it meets -- Unity's own order.

USAGE
-----
``uv run --with UnityPy --with TypeTreeGeneratorAPI python
scripts/extract_dsp_power.py ["/path/to/Dyson Sphere Program"]``

It rewrites ``power`` in place and leaves every other field alone, so a
re-extraction against an unchanged install produces a zero diff.
"""

from __future__ import annotations

import json
import os
import sys

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

UNITY_VERSION = "2022.3.62f3c1"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "src", "flab2bp", "dsp", "data", "buildings.json")

#: What ends up in ``buildings.json``: the key on the left, the ``PowerDesc``
#: field it reads on the right, and whether it is a flag.  ``generator`` is
#: deliberately absent -- see ``dsp.rules.power_node_condition`` for why
#: ``isPowerGen`` cannot change any verdict the ladder reaches.
FIELDS = (
    ("node", "node", True),  # isPowerNode
    ("connectDistance", "connectDistance", False),
    ("coverRadius", "coverRadius", False),
    ("wind", "wind", True),  # windForcedPower
    ("geothermal", "geothermal", True),
    ("accumulator", "accumulator", True),  # isAccumulator
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


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
    powers: dict[int, dict] = {}
    nodes = None
    for obj in env.objects:
        name = obj.type.name
        if name == "GameObject":
            gos[obj.path_id] = obj.read_typetree()
        elif name == "Transform":
            trs[obj.path_id] = obj.read_typetree()
        elif name == "MonoBehaviour":
            try:
                script = obj.read(check_read=False).m_Script
                if not script or script.read().m_ClassName != "PowerDesc":
                    continue
            except Exception:  # noqa: BLE001 - a stray unreadable object must not abort
                continue
            if nodes is None:
                nodes = gen.get_nodes_up("Assembly-CSharp", "PowerDesc")
            powers[obj.path_id] = obj.read_typetree(nodes)
    if not powers:
        fail("no PowerDesc component found in resources.assets")

    roots: dict[str, list[int]] = {}
    for pid, t in trs.items():
        if t["m_Father"]["m_PathID"] == 0:
            roots.setdefault(gos[t["m_GameObject"]["m_PathID"]]["m_Name"], []).append(pid)

    def power_of(prefab: str) -> dict | None:
        """``GetComponentInChildren<PowerDesc>(includeInactive: true)``."""
        for root in roots.get(prefab, []):
            queue = [root]
            while queue:
                pid = queue.pop(0)
                gpid = trs[pid]["m_GameObject"]["m_PathID"]
                for comp in gos[gpid]["m_Component"]:
                    cp = comp["component"]["m_PathID"] if "component" in comp else comp["m_PathID"]
                    if cp in powers:
                        return powers[cp]
                queue.extend(ch["m_PathID"] for ch in trs[pid]["m_Children"])
        return None

    with open(OUT, encoding="utf-8") as fh:
        rows = json.load(fh)

    changed = 0
    for row in rows:
        desc = power_of(row["prefab"])
        # `null` for anything that is not a NODE, which is the convention the
        # table already used: a Chemical Plant carries a PowerDesc too (it is a
        # power CONSUMER) and the table wrote `null` for it.  `catalog._load`
        # reads `null` as `{}`, and every rule keyed on this block --
        # `power.coverage`, `power.connectivity`, `game.power_too_close` --
        # starts from `isPowerNode`, so a consumer's block would be dead weight.
        block = None
        if desc is not None and desc["node"]:
            block = {key: bool(desc[src]) if flag else desc[src] for key, src, flag in FIELDS}
        if row.get("power", "absent") != block:
            changed += 1
        row["power"] = block

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"{changed} row(s) changed -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
