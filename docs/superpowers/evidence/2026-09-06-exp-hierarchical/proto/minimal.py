"""Isolate the block the mall's decomposition could not place.

    uv run python docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/minimal.py

`mall/all-products` refuses even after being cut into 50 blocks, and every
refusing block is 6 or 11 machines.  The smallest of them is one recipe:

    6 x copper-ingot in a negentropy-smelter, copper-ore in (sprayed),
    proliferator-3 in, copper-ingot out, belt_stack 4, piler unlocked.

This rebuilds exactly that spec from the mall's own groups and hands it to both
placers at several budgets, then repeats it with the URL's cargo stack lowered to
1 and with the spray removed.  It is the difference between "hierarchy is not
enough for the mall" and "the mall's leaves are a placer bug", and it decides
which of those the evidence says.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import specs as specs_mod  # noqa: E402

from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.pipeline import _new_layout  # noqa: E402
from flab2bp.spec import BuildSpec  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "out"


def _variant(spec: BuildSpec, recipe: str, count: int, **overrides: object) -> BuildSpec:
    group = next(g for g in spec.groups if g.recipe_id == recipe)
    group = group.model_copy(update={"count": count})
    inputs = {item: rate * count for item, rate in group.inputs_per_machine.items()}
    outputs = {item: rate * count for item, rate in group.outputs_per_machine.items()}
    spray = {i: True for i in spec.spray_lanes if i in inputs} if group.is_proliferated else {}
    if spray:
        for item, rate in spec.external_inputs.items():
            if item.startswith("proliferator"):
                inputs[item] = rate / spec.machine_count * count
    data = spec.model_dump()
    data.update(
        {
            "groups": (group,),
            "external_inputs": inputs,
            "outputs": outputs,
            "surplus_outputs": {},
            "spray_lanes": spray,
            "lanes_requiring_split": frozenset(),
            "belt_required_edges": frozenset(),
            "coproduct_buffer_proofs": (),
            "label": f"minimal-{recipe}",
        }
    )
    data.update(overrides)
    return BuildSpec(**data)


def main() -> None:
    loaded = specs_mod.load("mall", "all-products")
    spec = loaded.spec
    rows: list[dict[str, object]] = []
    cases = {
        "as-decomposed (belt_stack 4, sprayed)": {},
        "belt_stack 1": {"belt_stack": 1},
        "no piler": {"piler_unlocked": False},
        "belt_stack 1 + no piler": {"belt_stack": 1, "piler_unlocked": False},
        "unsprayed": {"spray_lanes": {}},
    }
    for name, overrides in cases.items():
        sub = _variant(spec, "copper-ingot", 6, **overrides)
        if overrides.get("spray_lanes") == {}:
            sub = sub.model_copy(
                update={"groups": (sub.groups[0].model_copy(update={"proliferator_mode": "none"}),)}
            )
        for strategy in ("freeform", "sequence-pair"):
            for budget in (12.0, 60.0):
                layout = _new_layout(
                    strategy,  # type: ignore[arg-type]
                    belt_vertical_construction=loaded.belt_rules.vertical_construction,
                    sequence_islands=1,
                    band_policy=BandPolicy.parse("portable"),
                    workers=8,
                )
                started = time.monotonic()
                try:
                    placement = layout.lay_out(sub, time_budget_s=budget)
                    verdict = "OK"
                    area: int | None = placement.area
                except NoValidLayout as exc:
                    verdict = f"REFUSED: {exc.reason}"[:300]
                    area = None
                except Exception as exc:  # noqa: BLE001
                    verdict = f"CRASH: {type(exc).__name__}: {exc}"[:300]
                    area = None
                rows.append(
                    {
                        "case": name,
                        "strategy": strategy,
                        "budget_s": budget,
                        "wall_s": round(time.monotonic() - started, 2),
                        "area": area,
                        "verdict": verdict,
                    }
                )
                print(json.dumps(rows[-1]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "minimal-block.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
