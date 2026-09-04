# /// script
# requires-python = ">=3.14"
# dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI"]
# ///
"""Extract the current DSP recipe, item and cargo-stacking tables from a game install.

    uv run scripts/extract_dsp_tables.py [GAME_DIR]

Writes ``src/flab2bp/dsp/data/{recipes,items,stacking_techs}.json``, which
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

``stacking_techs.json`` is the provenance for ``data/stacking.json``: the
research rows that move a sorter's cargo stacking, selected by the unlock
function ids ``GameHistoryData.UnlockTechFunction`` itself switches on rather
than by an English name, so the selection survives a localisation change.  The
name hints are a CHECK on that id filter, never the filter itself -- see
``stacking_techs``.

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

#: ``UnlockFunctions`` values that ``GameHistoryData.UnlockTechFunction``
#: (Assembly-CSharp, GameHistoryData.cs:1795) routes to a sorter cargo-stacking
#: field::
#:
#:     case 14: inserterStackCountObsolete = num;   (:1848)
#:     case 39: inserterStackOutput        = num;   (:1943)
#:     case 40: inserterBidirectional      = true;  (:1947)
#:     case 41: inserterStackInput         = num;   (:1951)
#:
#: These four ids ARE the definition of "a tech that changes sorter stacking".
STACK_UNLOCK_FUNCTIONS = frozenset({14, 39, 40, 41})

#: A cross-check on the id filter, not a second filter.  If a display name
#: mentions one of these and the id filter did not already select the tech, the
#: id list above has gone stale and the run fails rather than writing a table
#: that quietly lost a research ladder.  The reverse -- an id-selected tech
#: whose name mentions neither -- is expected and only noted: DSP names the
#: Pile Sorter unlock "Sorter Cargo Integration".
STACK_TECH_NAME_HINTS = ("Cargo Stacking", "Pile Sorter")

#: Exactly the ``TechProto`` fields the stacking facts are derived from.
#:
#: ``IsObsolete`` is load-bearing, not decoration: it is what hides a tech from
#: the tree (``UITechNode.cs:914``, ``:1289``, ``:1483``, ``:1487``) and from
#: the unlock-everything achievement (``ACH_UnlockAllTech.cs:37``).  On 0.10.34
#: it is the whole reason the five-level Sorter Cargo Stacking ladder counts
#: for nothing while the six-level Pile Sorter Upgrade ladder is the live one.
#: Leave it out and a patch that un-obsoleted the old ladder would land here as
#: a zero-diff re-extraction.
STACK_TECH_FIELDS = (
    "ID",
    "Name",
    "Level",
    "MaxLevel",
    "IsObsolete",
    "UnlockFunctions",
    "UnlockValues",
    "UnlockRecipes",
    "PropertyOverrideItems",
)


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


def stacking_techs(techs: list[dict], tr: dict[str, str]) -> list[dict]:
    """Every research row that moves a sorter's cargo stacking.

    Selected by ``UnlockFunctions``, cross-checked by display name.  A tech the
    NAME finds and the id filter did not is fatal: it means ``UnlockTechFunction``
    grew a case and ``STACK_UNLOCK_FUNCTIONS`` is stale, and a silently short
    table here would flatten a whole research ladder into "no such level".
    """

    def en(name: str) -> str:
        return tr.get(name, name)

    def named(tech: dict) -> bool:
        labels = (tech.get("Name") or "", en(tech.get("Name") or ""))
        return any(hint in label for hint in STACK_TECH_NAME_HINTS for label in labels)

    by_id = {t["ID"] for t in techs if set(t.get("UnlockFunctions") or []) & STACK_UNLOCK_FUNCTIONS}
    by_name = {t["ID"] for t in techs if named(t)}
    if by_name - by_id:
        fail(
            f"techs {sorted(by_name - by_id)} are named for cargo stacking but carry none "
            f"of UnlockFunctions {sorted(STACK_UNLOCK_FUNCTIONS)}; the id filter is stale"
        )
    if by_id - by_name:
        print(f"note: id-selected techs the name hints do not reach: {sorted(by_id - by_name)}")

    rows = [
        {**{f: t[f] for f in STACK_TECH_FIELDS}, "englishName": en(t.get("Name") or "")}
        for t in techs
        if t["ID"] in by_id
    ]
    rows.sort(key=lambda r: r["ID"])
    # 0.10.34 ships twelve: Sorter Cargo Stacking 1-5, Sorter Cargo Integration,
    # and Pile Sorter Upgrade 1-6.  The floor sits under that so a real update
    # raises it and a truncated read trips the guard.
    if len(rows) < 6:
        fail(f"only {len(rows)} cargo-stacking techs; the proto set looks truncated")
    return rows


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "/Users/dannyb/Downloads/Dyson Sphere Program"
    data_dir = os.path.join(game, "DSPGAME_Data")
    if not os.path.isdir(data_dir):
        data_dir = game

    tr = load_english(game, data_dir)
    protos = read_proto_sets(data_dir, {"ItemProtoSet", "RecipeProtoSet", "TechProtoSet"})

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

    techs = stacking_techs(protos["TechProtoSet"]["dataArray"], tr)

    os.makedirs(OUT, exist_ok=True)
    for name, payload in (
        ("items.json", items),
        ("recipes.json", recipes),
        ("stacking_techs.json", techs),
    ):
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
