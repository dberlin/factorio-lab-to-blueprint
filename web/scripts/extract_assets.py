# /// script
# requires-python = ">=3.11"
# dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI", "Pillow"]
# ///
"""Extract DSP game data into public/assets/ for the blueprint viewer.

Everything here comes from the user's own game install. MonoBehaviour typetrees
are NOT serialized in the release build, so they are generated from Managed/ --
Assembly-CSharp.dll alone cannot resolve netstandard / UnityEngine.CoreModule.

Usage: uv run scripts/extract_assets.py [GAME_DIR]
"""

from __future__ import annotations

import colorsys
import contextlib
import glob
import json
import os
import sys

import UnityPy
from PIL import Image
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

GAME = sys.argv[1] if len(sys.argv) > 1 else "/Users/dannyb/Downloads/Dyson Sphere Program"
DATA = os.path.join(GAME, "DSPGAME_Data")
if not os.path.isdir(DATA):
    DATA = GAME  # allow pointing directly at a DSPGAME_Data-shaped folder
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "assets")
# Second copy of items.json/recipes.json/models.json/tags.json, written
# alongside OUT. Tests may not read public/assets (gitignored build output)
# or touch the network, so tests/support/catalog.ts builds its Catalog from
# this snapshot instead. The fixture-level guard in classification.test.ts
# (0 untyped, 0 generic rows) is only meaningful if that snapshot tracks the
# catalog the app actually ships -- writing both copies from the same write()
# call is what makes a re-extraction's diff (or lack of one) trustworthy.
TEST_FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "catalog"
)
UNITY_VERSION = "2022.3.62f3c1"
ICON_CELL = 64

# Prefabs carry a per-type marker component rather than a single PrefabDesc,
# which is not serialised anywhere in the loose asset files. These are the
# types whose parameter blocks we decode.
DESC_TO_TYPE = {
    "StationDesc": "Station",
    "MonitorDesc": "Monitor",
    "StorageDesc": "Storage",
    "BattleBaseDesc": "BattleBase",
    "TankDesc": "Tank",
    "AssemblerDesc": "Assembler",
    "InserterDesc": "Inserter",
    "BeltDesc": "Belt",
    "EjectorDesc": "Ejector",
    "LabDesc": "Lab",
    "MarkerDesc": "Marker",
    "DispenserDesc": "Dispenser",
    "TurretDesc": "Turret",
    "SiloDesc": "Silo",
    "SplitterDesc": "Splitter",
    "MinerDesc": "Miner",
}

# Two prefabs legitimately carry two markers: the Orbital/Vein Collector is
# Miner + Station, and the Battlefield Analysis Base is BattleBase + Storage.
# The game's own export checks Station after Miner and BattleBase after
# Storage, so the later check wins. Mirror that rather than inventing a rule.
DESC_PRECEDENCE = {"Station": 1, "BattleBase": 1}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    managed = os.path.join(DATA, "Managed")
    if not os.path.isdir(managed):
        fail(f"{managed} not found. The whole Managed/ folder is required for typetrees.")

    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)
    os.makedirs(TEST_FIXTURES, exist_ok=True)

    gen = TypeTreeGenerator(UNITY_VERSION)
    gen.load_local_dll_folder(managed)

    res_path = os.path.join(DATA, "resources.assets")
    shared_path = os.path.join(DATA, "sharedassets0.assets")
    if not os.path.isfile(res_path):
        fail(f"{res_path} not found")

    env = UnityPy.load(res_path)

    # ---- proto sets -------------------------------------------------------
    protos: dict[str, dict] = {}
    want = {"ItemProtoSet", "ModelProtoSet", "RecipeProtoSet", "SignalProtoSet", "VeinProtoSet"}
    gonames: dict[int, str] = {}
    slot_objs = []
    desc_objs: list[tuple] = []
    power_objs: list = []

    for o in env.objects:
        if o.type.name == "GameObject":
            with contextlib.suppress(Exception):
                gonames[o.path_id] = o.read(check_read=False).m_Name
            continue
        if o.type.name != "MonoBehaviour":
            continue
        try:
            script = o.read(check_read=False).m_Script
            if not script:
                continue
            cls = script.read().m_ClassName
        except Exception:
            continue
        if cls in want and cls not in protos:
            protos[cls] = o.read_typetree(gen.get_nodes_up("Assembly-CSharp", cls))
        elif cls == "SlotConfig":
            slot_objs.append(o)
        elif cls in DESC_TO_TYPE:
            desc_objs.append((o, DESC_TO_TYPE[cls]))
        elif cls == "PowerDesc":
            power_objs.append(o)

    for cls in want:
        if cls not in protos:
            fail(f"{cls} not found in resources.assets")

    # ---- localization -----------------------------------------------------
    # Locale/ is a real folder in the game root, NOT inside the asset files.
    tr: dict[str, str] = {}
    locale_dir = os.path.join(GAME, "Locale", "1033")
    if not os.path.isdir(locale_dir):
        locale_dir = os.path.join(os.path.dirname(DATA), "Locale", "1033")
    locale_found = os.path.isdir(locale_dir)
    if locale_found:
        for p in glob.glob(os.path.join(locale_dir, "*.txt")):
            try:
                with open(p, encoding="utf-16") as locale_file:
                    lines = locale_file.read().splitlines()
            except Exception:
                continue
            for line in lines:
                c = line.split("\t")
                if len(c) >= 4 and c[0] and c[3]:
                    tr.setdefault(c[0], c[3])
        print(f"localization: {len(tr)} entries from {locale_dir}")
    else:
        print(
            "WARNING: Locale/1033 not found; names will stay in the source language",
            file=sys.stderr,
        )

    def en(name: str) -> str:
        return tr.get(name, name)

    # ---- boxes: SlotConfig joined to ModelProto by prefab name ------------
    sc_nodes = gen.get_nodes_up("Assembly-CSharp", "SlotConfig")
    by_prefab: dict[str, tuple[dict, dict]] = {}
    for o in slot_objs:
        try:
            tt = o.read_typetree(sc_nodes)
        except Exception:
            continue
        go = tt.get("m_GameObject") or {}
        nm = gonames.get(go.get("m_PathID"))
        if nm:
            by_prefab[nm] = (tt["selectCenter"], tt["selectSize"])

    # Same join as the boxes above: component -> GameObject name -> ModelProto
    # PrefabPath basename. 46 marker prefabs plus 4 derived from PowerDesc,
    # all 50 of which join to a ModelProto (asserted below).
    type_by_prefab: dict[str, str] = {}
    markers_by_prefab: dict[str, set[str]] = {}
    for o, type_name in desc_objs:
        try:
            go = o.read(check_read=False).m_GameObject
        except Exception:
            continue
        nm = gonames.get(go.path_id) if go else None
        if not nm:
            continue
        markers_by_prefab.setdefault(nm, set()).add(type_name)
        prev = type_by_prefab.get(nm)
        # Order-independent for the two known pairs, because one side of each
        # is in DESC_PRECEDENCE and the other is not. That is a property of
        # the data, not of this code -- `unresolvable` below asserts it.
        if prev is None or DESC_PRECEDENCE.get(type_name, 0) > DESC_PRECEDENCE.get(prev, 0):
            type_by_prefab[nm] = type_name

    ambiguous = sorted(nm for nm, ms in markers_by_prefab.items() if len(ms) > 1)

    # An ambiguity is only safe if DESC_PRECEDENCE gives it a UNIQUE winner.
    # Two markers of equal rank resolve to whichever `env.objects` happened to
    # yield first, which would mistype a building rather than merely leave it
    # untyped -- the one failure the MIN_MODELS_WITH_TYPE floor cannot see.
    unresolvable: list[str] = []
    for nm in ambiguous:
        ranks = sorted((DESC_PRECEDENCE.get(t, 0) for t in markers_by_prefab[nm]), reverse=True)
        if ranks[0] == ranks[1]:
            unresolvable.append(f"{nm} ({', '.join(sorted(markers_by_prefab[nm]))})")

    # Exactly four prefabs match, one per type, and they are mutually
    # exclusive: energy-exchanger, ray-receiver, fusion-reactor (fuelMask 4)
    # and geothermal-power-station. A marker component would be tidier, but
    # the game distinguishes these by PowerDesc fields and so must we.
    pd_nodes = gen.get_nodes_up("Assembly-CSharp", "PowerDesc")
    power_conflicts: list[str] = []
    for o in power_objs:
        try:
            d = o.read_typetree(pd_nodes)
            go = o.read(check_read=False).m_GameObject
        except Exception:
            continue
        nm = gonames.get(go.path_id) if go else None
        if not nm or nm in type_by_prefab:
            continue
        signals = [
            ("Exchanger", bool(d.get("exchanger"))),
            ("Gamma", bool(d.get("gamma"))),
            ("ArtificialStar", d.get("fuelMask") == 4),
            ("Geothermal", bool(d.get("geothermal"))),
        ]
        hits = [name for name, on in signals if on]
        # The if/elif ordering below would silently pick one of two truthy
        # signals. The marker join fails loudly on an unexpected ambiguity;
        # this must too, or a content patch that sets two fields mistypes a
        # building with nothing to catch it -- the MIN_MODELS_WITH_TYPE floor
        # detects undercounting, never mistyping.
        if len(hits) > 1:
            power_conflicts.append(f"{nm} ({', '.join(hits)})")
        if hits:
            type_by_prefab[nm] = hits[0]

    models: dict[str, dict] = {}
    model_prefabs: set[str] = set()
    for m in protos["ModelProtoSet"]["dataArray"]:
        prefab = (m.get("PrefabPath") or "").strip().rstrip("/").split("/")[-1]
        model_prefabs.add(prefab)
        if prefab in by_prefab:
            c, s = by_prefab[prefab]
            entry = {
                "prefab": prefab,
                "center": [round(c["x"], 4), round(c["y"], 4), round(c["z"], 4)],
                "size": [round(s["x"], 4), round(s["y"], 4), round(s["z"], 4)],
            }
            building_type = type_by_prefab.get(prefab)
            if building_type:
                entry["buildingType"] = building_type
            models[str(m["ID"])] = entry

    # ---- icons ------------------------------------------------------------
    items_raw = protos["ItemProtoSet"]["dataArray"]
    recipes_raw = protos["RecipeProtoSet"]["dataArray"]
    signals_raw = protos["SignalProtoSet"]["dataArray"]
    veins_raw = protos["VeinProtoSet"]["dataArray"]
    wanted_icons = {
        (r.get("IconPath") or "").split("/")[-1]
        for r in list(items_raw) + list(recipes_raw) + list(signals_raw) + list(veins_raw)
        if r.get("IconPath")
    }
    images: dict[str, Image.Image] = {}
    for path in [res_path, shared_path]:
        if not os.path.isfile(path):
            print(f"WARNING: {path} not found; skipping it as an icon source", file=sys.stderr)
            continue
        e = env if path == res_path else UnityPy.load(path)
        for o in e.objects:
            if o.type.name not in ("Texture2D", "Sprite"):
                continue
            try:
                d = o.read(check_read=False)
            except Exception:
                continue
            nm = getattr(d, "m_Name", "")
            if nm in wanted_icons and nm not in images:
                with contextlib.suppress(Exception):
                    images[nm] = d.image.convert("RGBA").resize((ICON_CELL, ICON_CELL))
    print(f"icons: {len(images)}/{len(wanted_icons)}")

    names = sorted(images)
    cols = 16
    rows = (len(names) + cols - 1) // cols
    atlas = Image.new("RGBA", (cols * ICON_CELL, max(rows, 1) * ICON_CELL), (0, 0, 0, 0))
    entries: dict[str, list[int]] = {}
    colors: dict[str, int] = {}
    for i, nm in enumerate(names):
        col, row = i % cols, i // cols
        atlas.paste(images[nm], (col * ICON_CELL, row * ICON_CELL))
        entries[nm] = [col, row]
        colors[nm] = dominant_color(images[nm])

    # ---- items / recipes (in memory; nothing written to disk yet) ---------
    items = []
    for it in items_raw:
        icon = (it.get("IconPath") or "").split("/")[-1]
        items.append(
            {
                "id": it["ID"],
                "name": en(it.get("Name") or ""),
                "iconName": icon,
                "gridIndex": it.get("GridIndex", 0),
                "modelIndex": it.get("ModelIndex", 0),
                "canBuild": bool(it.get("CanBuild")),
                "color": colors.get(icon, 0xDDDDDD),
            }
        )

    recipes = []
    for rc in recipes_raw:
        recipes.append(
            {
                "id": rc["ID"],
                "name": en(rc.get("Name") or ""),
                "iconName": (rc.get("IconPath") or "").split("/")[-1],
                "items": list(rc.get("Items") or []),
                "itemCounts": list(rc.get("ItemCounts") or []),
                "results": list(rc.get("Results") or []),
                "resultCounts": list(rc.get("ResultCounts") or []),
                "timeSpend": rc.get("TimeSpend", 0),
            }
        )

    buildable = [i for i in items if i["canBuild"]]
    missing = [i for i in buildable if str(i["modelIndex"]) not in models]

    # ---- tags: signal and vein icons for belt tags outside the item band --
    def basename(proto: dict) -> str:
        return (proto.get("IconPath") or "").split("/")[-1]

    tags = {
        "signals": {str(s["ID"]): basename(s) for s in signals_raw if basename(s)},
        "veins": {str(v["ID"]): basename(v) for v in veins_raw if basename(v)},
    }

    # ---- validate: assert this script's invariants before trusting the data ----
    # These are name-equality joins (GameObject name <-> prefab basename,
    # texture name <-> IconPath basename). A DSP patch that changes either
    # naming convention makes the join quietly come up empty -- no exception,
    # exit 0, degraded output. Catch that here instead of three layers down
    # in the viewer's zod validation or in a scene of grey cubes.
    validate(
        items=items,
        recipes=recipes,
        models=models,
        buildable=buildable,
        missing=missing,
        images=images,
        wanted_icons=wanted_icons,
        tr=tr,
        locale_found=locale_found,
        tags=tags,
        ambiguous=ambiguous,
        unresolvable=unresolvable,
        unjoined_types=sorted(set(type_by_prefab) - model_prefabs),
        power_conflicts=power_conflicts,
    )

    # ---- write output -------------------------------------------------
    atlas.save(os.path.join(OUT, "icons", "atlas.png"))
    write(
        os.path.join(OUT, "icons", "atlas.json"),
        {"cell": ICON_CELL, "cols": cols, "rows": max(rows, 1), "entries": entries},
    )
    write(os.path.join(OUT, "items.json"), items)
    write(os.path.join(OUT, "recipes.json"), recipes)
    write(os.path.join(OUT, "models.json"), models)
    write(os.path.join(OUT, "tags.json"), tags)

    # Second copy for tests/support/catalog.ts -- see the TEST_FIXTURES
    # comment above for why this write exists.
    write(os.path.join(TEST_FIXTURES, "items.json"), items)
    write(os.path.join(TEST_FIXTURES, "recipes.json"), recipes)
    write(os.path.join(TEST_FIXTURES, "models.json"), models)
    write(os.path.join(TEST_FIXTURES, "tags.json"), tags)

    # ---- report -----------------------------------------------------------
    print(f"items {len(items)}, recipes {len(recipes)}, models with boxes {len(models)}")
    print(f"buildable with box: {len(buildable) - len(missing)}/{len(buildable)}")
    for m in missing:
        # itemId 1131 (Foundation, modelIndex 0) is the terrain tool, not a
        # placed building, and correctly has no SlotConfig.
        print(f"  no box: itemId={m['id']} model={m['modelIndex']} {m['name']}")


# Floors set a bit below the known-good values (174 items, 161 recipes, 67
# models with boxes, 62/63 buildable-with-box, 188/188 icons, 6229 localization
# entries) so a legitimate future content patch that adds items doesn't trip
# these, but a name-equality-join collapse (the quiet failure mode) does.
MIN_ITEMS = 170
MIN_RECIPES = 150
MIN_MODELS_WITH_BOXES = 60
MAX_BUILDABLE_WITHOUT_BOX = 2  # known gap today: itemId=1131 Foundation
MIN_LOCALIZATION_ENTRIES = 6000
MIN_MODELS_WITH_TYPE = 48


def validate(
    *,
    items: list[dict],
    recipes: list[dict],
    models: dict[str, dict],
    buildable: list[dict],
    missing: list[dict],
    images: dict[str, Image.Image],
    wanted_icons: set[str],
    tr: dict[str, str],
    locale_found: bool,
    tags: dict[str, dict[str, str]],
    ambiguous: list[str],
    unresolvable: list[str],
    unjoined_types: list[str],
    power_conflicts: list[str],
) -> None:
    """Assert extraction invariants and exit non-zero on violation.

    The SlotConfig<->ModelProto join and the icon-name match are both keyed
    on string equality (GameObject name vs. prefab basename; texture name vs.
    IconPath basename). If a future DSP patch changes a naming convention,
    nothing raises on its own -- the names just stop matching, the script
    exits 0, and it writes degraded output (e.g. far fewer than 67 model
    boxes) that only gets noticed downstream. This function is the guard
    against that.
    """
    problems: list[str] = []

    def floor(actual: int, minimum: int, label: str) -> None:
        if actual < minimum:
            problems.append(f"{label}: got {actual}, expected at least {minimum}")

    floor(len(items), MIN_ITEMS, "items")
    floor(len(recipes), MIN_RECIPES, "recipes")
    floor(len(models), MIN_MODELS_WITH_BOXES, "models with boxes")

    typed = [k for k, v in models.items() if v.get("buildingType")]
    floor(len(typed), MIN_MODELS_WITH_TYPE, "models with a building type")

    # Two separate alarms, because they catch different things.
    #
    # The count fires when a NEW ambiguity appears at all. Almost every type
    # ranks 0 in DESC_PRECEDENCE, so a brand-new pair like {Station, Belt}
    # has a unique winner and would slip past the identity check below with
    # no rule ever authored for it.
    if len(ambiguous) > 2:
        problems.append(
            f"{len(ambiguous)} prefabs carry more than one *Desc marker "
            f"({ambiguous}); only the Orbital Collector and Battlefield "
            "Analysis Base are known to, so a new ambiguity needs a "
            "precedence rule in DESC_PRECEDENCE before it can be trusted."
        )

    # The identity check fires when an ambiguity has NO unique winner, which
    # the count alone never detected: two markers of equal rank resolve to
    # whichever `env.objects` yielded first, mistyping a building rather than
    # merely leaving it untyped -- the one failure MIN_MODELS_WITH_TYPE
    # cannot see.
    if unresolvable:
        problems.append(
            f"{len(unresolvable)} prefabs carry two *Desc markers of equal "
            f"precedence ({unresolvable}); which one wins depends on asset "
            "read order, so each needs a rule in DESC_PRECEDENCE before its "
            "building type can be trusted."
        )

    # The floor above counts typed models, so it detects a join that comes up
    # short -- but only after 2 of 50 have already vanished. This catches the
    # first prefab whose name stops matching a ModelProto, which is the actual
    # failure mode when DSP renames an asset.
    if unjoined_types:
        problems.append(
            f"{len(unjoined_types)} *Desc prefabs match no ModelProto "
            f"PrefabPath basename ({unjoined_types}); the marker<->ModelProto "
            "name join has broken and those buildings would silently lose "
            "their type."
        )
    if power_conflicts:
        problems.append(
            f"{len(power_conflicts)} power prefabs set more than one type "
            f"signal ({power_conflicts}); the exchanger/gamma/fuelMask/"
            "geothermal fields are assumed mutually exclusive, and the "
            "if/elif chain would silently pick one."
        )

    if len(missing) > MAX_BUILDABLE_WITHOUT_BOX:
        problems.append(
            f"buildable items without a box: got {len(missing)}, expected at "
            f"most {MAX_BUILDABLE_WITHOUT_BOX} "
            f"({len(buildable) - len(missing)}/{len(buildable)} have a box) "
            "-- the SlotConfig<->ModelProto prefab-name join likely broke"
        )

    if len(images) != len(wanted_icons):
        sample = ", ".join(sorted(wanted_icons - set(images))[:10])
        problems.append(
            f"icons: got {len(images)}/{len(wanted_icons)} wanted, expected "
            f"{len(wanted_icons)}/{len(wanted_icons)} "
            f"-- an icon source likely moved or was renamed; missing e.g. [{sample}]"
        )

    if locale_found:
        floor(len(tr), MIN_LOCALIZATION_ENTRIES, "localization entries")

    floor(len(tags["signals"]), 39, "signal tag icons")
    floor(len(tags["veins"]), 14, "vein tag icons")

    if problems:
        print(
            "ERROR: extraction failed invariant checks -- likely a DSP data "
            "format change broke one of the name-equality joins:",
            file=sys.stderr,
        )
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)


def dominant_color(img: Image.Image) -> int:
    """Saturation-weighted average colour of the icon's opaque pixels.

    DSP icons are drawn mostly as a dark outline plus a light highlight over
    a transparent background. A histogram mode (or any unweighted average)
    is dominated by those near-black/near-white pixels, collapsing distinct
    items -- belts, assemblers, sorters, matrix labs, tesla towers -- onto
    the same handful of greys, even though each item clearly reads as a
    different colour to a human eye.

    Instead, weight each pixel by its HLS saturation, additionally scaled
    down toward the lightness extremes (near 0 = black, near 1 = white):
    HLS saturation alone is a poor proxy for perceived colourfulness right
    at those extremes (a near-black pixel with a 1-in-255 channel skew can
    register a high "saturation" despite carrying no real hue information).
    That combined weight lets an icon's actual tint -- e.g. a belt's
    orange/teal/blue -- dominate the average while outline and highlight
    pixels contribute almost nothing.
    """
    weighted_r = weighted_g = weighted_b = 0.0
    total_weight = 0.0
    for r, g, b, a in img.getdata():
        if a <= 128:
            continue
        _hue, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        midtone = 1 - abs(2 * lightness - 1)
        weight = saturation * midtone
        if weight <= 0:
            continue
        weighted_r += r * weight
        weighted_g += g * weight
        weighted_b += b * weight
        total_weight += weight
    if total_weight <= 0:
        return 0xDDDDDD
    r = round(weighted_r / total_weight)
    g = round(weighted_g / total_weight)
    b = round(weighted_b / total_weight)
    return (r << 16) | (g << 8) | b


def write(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
