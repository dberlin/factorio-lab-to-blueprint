"""Throwaway probe: dump the rate solution and BuildSpec for the self-loop URL.

Run with:
    uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_spec.py
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.lab.data import load_dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import build_candidates
from flab2bp.rates.solve import solve

URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi"
    "WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK"
    "loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"
)


def f(x: Fraction) -> str:
    return f"{x} ({float(x):.4f}/s)"


def main() -> None:
    data = load_dataset()
    request = parse_url(URL)
    print("== LabRequest ==")
    print("objectives:", request.objectives)
    print("belt_id:", request.belt_id)
    print("proliferator/items:", {k: v for k, v in request.items.items()})
    print("recipes pinned:", list(request.recipes)[:20])
    print()

    specs = build_candidates(data, request)
    for spec in specs.candidates:
        print("=" * 72)
        print("candidate label:", spec.label)
        print("machines:", spec.machine_count)
        for g in spec.groups:
            print(
                f"  group recipe={g.recipe_id} machine={g.machine_item_id} n={g.count} "
                f"mode={g.proliferator_mode}"
            )
            for k, v in sorted(g.inputs_per_machine.items()):
                print(f"     in  {k:24s} {f(v)}  total {f(v * g.count)}")
            for k, v in sorted(g.outputs_per_machine.items()):
                print(f"     out {k:24s} {f(v)}  total {f(v * g.count)}")
            both = set(g.inputs_per_machine) & set(g.outputs_per_machine)
            if both:
                for item in sorted(both):
                    net = g.outputs_per_machine[item] - g.inputs_per_machine[item]
                    print(f"     SELF-LOOP {item}: net per machine {f(net)}")
        print("  external_inputs:", {k: str(v) for k, v in spec.external_inputs.items()})
        print("  outputs:", {k: str(v) for k, v in spec.outputs.items()})
        print("  surplus_outputs:", {k: str(v) for k, v in spec.surplus_outputs.items()})
        print("  spray_lanes:", spec.spray_lanes)
        print("  lanes_requiring_split:", sorted(spec.lanes_requiring_split))
        print("  belt_required_edges:", sorted(spec.belt_required_edges))
        print("  coproduct_buffer_proofs:", spec.coproduct_buffer_proofs)
        print("  belt:", spec.belt_item_id, f(spec.belt_items_per_second))
        print("  lane_capacity:", f(spec.lane_capacity))

    print()
    print("== raw RateSolution (default objective) ==")
    sol = solve(data, request)
    print("external_inputs:", {k: str(v) for k, v in sol.external_inputs.items()})
    print("outputs:", {k: str(v) for k, v in sol.outputs.items()})
    print("surplus:", {k: str(v) for k, v in sol.surplus.items()})
    for g in sol.groups:
        print(f"  {g.recipe_id} x{g.machines} inputs={ {k: str(v) for k, v in g.inputs.items()} }")
        print(f"      outputs={ {k: str(v) for k, v in g.outputs.items()} }")


if __name__ == "__main__":
    main()
