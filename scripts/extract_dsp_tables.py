# /// script
# requires-python = ">=3.14"
# dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI"]
# ///
"""Extract the current DSP recipe and item tables from a game install.

    uv run scripts/extract_dsp_tables.py [GAME_DIR]

Writes ``src/flab2bp/dsp/data/{recipes,items}.json``, which
``flab2bp.dsp.catalog`` maps FactorioLab ids onto.

This was written to chase a suspected staleness bug and DISPROVED it, which is
worth recording so nobody re-runs the same hunt.  A URL failed with "no DSP
recipe id known for 'accumulator-full'", and the tables looked stale -- copied
from the viewer's fixtures, only 161 recipes and 174 items, with Dark Fog
apparently missing.  They were not stale.  ``resources.assets`` holds exactly one
``ItemProtoSet`` (174 entries) and one ``RecipeProtoSet`` (161), and 161 is the
complete recipe set the game ships.  The Dark Fog turrets were already there as
items 3001-3010.

The real cause was name mapping: ``storage-1`` is DSP's "Depot Mk.I",
``sorter-4`` is "Pile Sorter", and ``accumulator-full`` is not a craft at all but
an Energy Exchanger mode.  Those are handled by the alias tables in
``dsp/catalog.py``, not here.

So this script is a maintenance tool for when the game does update, not a fix.
Its value is that re-running it on a current install and getting an unchanged
diff is proof the tables track the game.

MonoBehaviour typetrees are not serialised in the release build, so they are
generated from ``Managed/`` -- ``Assembly-CSharp.dll`` alone cannot resolve
netstandard / UnityEngine.CoreModule.  Display names live in ``Locale/1033``,
which is a real folder in the game root rather than inside the asset bundles;
without it every name stays in the source language and nothing maps.

Schema matches what was there before.  ``color`` is the one field this cannot
regenerate -- the viewer derives it by rasterising every icon, which needs Pillow
and a scan of every Texture2D -- so existing colours are PRESERVED rather than
overwritten with a placeholder.  Nothing here reads the field, but replacing real
data with a constant is still a loss, and it would show up as a 174-row diff on
every run, drowning out the changes that matter.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

UNITY_VERSION = "2022.3.62f3c1"
#: The viewer's fallback for an icon it could not rasterise. See module docstring.
DEFAULT_COLOR = 0xDDDDDD

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "src", "flab2bp", "dsp", "data")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_english(game_dir: str, data_dir: str) -> dict[str, str]:
    """Source-language name -> English, from Locale/1033.

    Fatal if absent: `_kebab` turns display names into FactorioLab ids, so
    untranslated names would silently produce a table that maps almost nothing.
    """
    locale = os.path.join(game_dir, "Locale", "1033")
    if not os.path.isdir(locale):
        locale = os.path.join(os.path.dirname(data_dir), "Locale", "1033")
    if not os.path.isdir(locale):
        fail(f"{locale} not found; without it names stay in the source language")

    tr: dict[str, str] = {}
    for path in glob.glob(os.path.join(locale, "*.txt")):
        try:
            with open(path, encoding="utf-16") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for line in lines:
            cells = line.split("\t")
            if len(cells) >= 4 and cells[0] and cells[3]:
                tr.setdefault(cells[0], cells[3])
    if not tr:
        fail(f"{locale} yielded no translations")
    print(f"localization: {len(tr)} entries")
    return tr


def load_existing_colors(path: str) -> dict[int, int]:
    """Icon colours already on disk, so a re-extraction does not discard them."""
    try:
        with open(path, encoding="utf-8") as fh:
            return {int(i["id"]): int(i["color"]) for i in json.load(fh) if "color" in i}
    except OSError, ValueError, KeyError:
        return {}


def read_proto_sets(data_dir: str, wanted: set[str]) -> dict[str, dict]:
    managed = os.path.join(data_dir, "Managed")
    if not os.path.isdir(managed):
        fail(f"{managed} not found. The whole Managed/ folder is required for typetrees.")

    res = os.path.join(data_dir, "resources.assets")
    if not os.path.isfile(res):
        fail(f"{res} not found")

    gen = TypeTreeGenerator(UNITY_VERSION)
    gen.load_local_dll_folder(managed)
    env = UnityPy.load(res)

    protos: dict[str, dict] = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            script = obj.read(check_read=False).m_Script
            if not script:
                continue
            cls = script.read().m_ClassName
        except Exception:  # noqa: BLE001 - a stray unreadable object must not abort the scan
            continue
        if cls in wanted and cls not in protos:
            protos[cls] = obj.read_typetree(gen.get_nodes_up("Assembly-CSharp", cls))

    for cls in wanted:
        if cls not in protos:
            fail(f"{cls} not found in resources.assets")
    return protos


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "/Users/dannyb/Downloads/Dyson Sphere Program"
    data_dir = os.path.join(game, "DSPGAME_Data")
    if not os.path.isdir(data_dir):
        data_dir = game

    tr = load_english(game, data_dir)
    protos = read_proto_sets(data_dir, {"ItemProtoSet", "RecipeProtoSet"})

    def en(name: str) -> str:
        return tr.get(name, name)

    existing_colors = load_existing_colors(os.path.join(OUT, "items.json"))
    items = [
        {
            "id": it["ID"],
            "name": en(it.get("Name") or ""),
            "iconName": (it.get("IconPath") or "").split("/")[-1],
            "gridIndex": it.get("GridIndex", 0),
            "modelIndex": it.get("ModelIndex", 0),
            "canBuild": bool(it.get("CanBuild")),
            "color": existing_colors.get(it["ID"], DEFAULT_COLOR),
        }
        for it in protos["ItemProtoSet"]["dataArray"]
    ]
    fresh = sum(1 for it in items if it["id"] not in existing_colors)
    if fresh:
        print(f"note: {fresh} new item(s) have no icon colour; using the default")
    recipes = [
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
        for rc in protos["RecipeProtoSet"]["dataArray"]
    ]

    # A silently truncated proto set would produce a table that looks fine and
    # maps almost nothing. The floors sit just under the counts a current
    # install yields (174 items, 161 recipes), so a real update raises them and
    # a truncated read trips the guard.
    if len(items) < 170:
        fail(f"only {len(items)} items; the proto set looks truncated")
    if len(recipes) < 155:
        fail(f"only {len(recipes)} recipes; the proto set looks truncated")

    os.makedirs(OUT, exist_ok=True)
    for name, payload in (("items.json", items), ("recipes.json", recipes)):
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as fh:
            # Compact, matching what is on disk: a re-extraction against an
            # unchanged install should produce a zero diff, which is the whole
            # signal this script offers.
            json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)
        print(f"wrote {len(payload):>4} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
