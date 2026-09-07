# One blueprint per item

> "One by one, generate a blueprint that creates each item/building in the game
> as its output. See what bugs arise. Classify all the bugs by group and fix
> them. Repeat until we can build at least 1 of each item." -- the user,
> 2026-09-06.

Harness: `scripts/item_sweep.py` (with `tests/scripts/test_item_sweep.py`).
Rounds are numbered; every round keeps its own `sweep-<N>.jsonl`, and
`round-<N>/` holds the blueprint and the full CLI log for every item.

## Scope

The dataset has 486 `items`, but only three categories name a physical thing a
factory produces. `technologies` (107) and `upgrades` (199) are research rows
whose output is a token that never rides a belt -- the tier corpus excludes them
for the same reason -- and `effects` (6) are the proliferator module entries,
not items at all.

| | count |
|---|---|
| in scope (`components`, `buildings`, `buildings-alt`) | **174** |
| &nbsp;&nbsp;BUILD -- a craftable non-mining recipe exists | **151** |
| &nbsp;&nbsp;RAW -- extraction only | **14** |
| &nbsp;&nbsp;OTHER -- nothing in the dataset produces it | **9** |

### RAW (14) -- out of scope, with the reason

Each is produced only by an extraction recipe. A Mining Machine is placed on a
vein and a Water Pump on an ocean tile; neither is a factory block a blueprint
can carry, so there is nothing for this tool to lay out.

| item | only recipe | extractor |
|---|---|---|
| `iron-ore` | `iron-vein` | Mining Machine |
| `copper-ore` | `copper-vein` | Mining Machine |
| `stone` | `stone-vein` | Mining Machine |
| `coal` | `coal-vein` | Mining Machine |
| `silicon-ore` | `silicium-vein` | Mining Machine |
| `titanium-ore` | `titanium-vein` | Mining Machine |
| `kimberlite-ore` | `kimberlite-vein` | Mining Machine |
| `fractal-silicon` | `fractal-silicon-vein` | Mining Machine |
| `optical-grating-crystal` | `optical-grating-crystal-vein` | Mining Machine |
| `spiniform-stalagmite-crystal` | `spiniform-stalagmite-crystal-vein` | Mining Machine |
| `unipolar-magnet` | `unipolar-magnet-vein` | Mining Machine |
| `water` | `ocean` | Water Pump |
| `crude-oil` | `crude-oil-seep` | Oil Extractor |
| `fire-ice` | `ice-giant-gas-hydrate` | Orbital Collector |

`silicon-ore` deserves a note: it *does* have a second recipe (`silicon-ore`,
from stone), but that recipe is in the dataset's own
`defaults.excludedRecipes`, so no solver may choose it and the item is
extraction-only in practice.

### OTHER (9) -- in scope by category, produced by nothing

| item | why |
|---|---|
| `log`, `plant-fuel` | gathered from trees and plants; no recipe |
| `ray-receiver-pro` | `buildings-alt`: a display-only alternate form of the Ray Receiver, with no recipe of its own |
| `df-core-element`, `df-dark-fog-matrix`, `df-energy-shard`, `df-silicon-based-neuron`, `df-negentropy-singularity`, `df-matter-recombinator` | Dark Fog drops. `rates/candidates.py:356` refuses them outright: no normal DSP catalog identity, so derived solving cannot put one in a blueprint |

### The rate

A URL carries a rate and the rate decides how big the block is. Each BUILD item
gets the round-number rung nearest `1.5 x` one machine's output of the target
recipe, clamped to `[R, 6R]` -- one to six machines of the target recipe, biased
small so the block stays a block. The machine is `recipe.producers[0]`, which is
what a bare URL (carrying no `mmr` field) actually resolves to through
`rates/adjust.py::select_machine`. Every row records `target_machines = rate/R`
so the claim is checked rather than asserted; a unit test asserts it holds for
all 151.

## Rounds

<!-- filled in per round -->

## Groups

<!-- filled in after round 1 -->
