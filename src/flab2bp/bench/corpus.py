"""The bake-off corpus.

Twelve DSP URLs chosen by measuring the real recipe graph rather than guessing,
spanning 1 to ~955 machines and 1 to 42 distinct recipes.  Five entries have
trees touching the LP-ambiguous multi-producer items (the oil and hydrogen
chains), because those are the only place the MILP does work a plain recipe-tree
walk could not.

Machine counts are at the stated rate with the default machine rank, ceiling
rounded, mining excluded.  They are documentation, not assertions -- the dataset
upstream can move.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

_RANK = "arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
_FAST_RANK = "plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab"


class Tier(Enum):
    """Size class, which sets the solver time budget."""

    TRIVIAL = "trivial"
    SMALL = "small"
    MID = "mid"
    LARGE = "large"
    STRESS = "stress"

    @property
    def time_budget_s(self) -> float:
        return {
            Tier.TRIVIAL: 10.0,
            Tier.SMALL: 10.0,
            Tier.MID: 60.0,
            Tier.LARGE: 120.0,
            Tier.STRESS: 300.0,
        }[self]


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    url_id: str
    url: str
    tier: Tier
    #: Approximate machine count, for orientation in the report.
    machines: int
    #: Whether the tree touches an item with more than one producing recipe.
    multi_producer: bool = False
    note: str = ""


def _list_url(target: str, *, belt: str = "conveyor-belt-2", rank: str = _RANK) -> str:
    return f"https://factoriolab.github.io/dsp/list?o={target}*60&ibe={belt}&mmr={rank}&v=11"


URL_CORPUS: tuple[CorpusEntry, ...] = (
    CorpusEntry(
        "iron-ingot",
        _list_url("iron-ingot"),
        Tier.TRIVIAL,
        1,
        note="degenerate case: a single smelter, no belts between machines",
    ),
    CorpusEntry(
        "magnetic-coil",
        _list_url("magnetic-coil"),
        Tier.TRIVIAL,
        4,
        note="smallest real tree: three recipes, two raw inputs",
    ),
    CorpusEntry(
        "graphene",
        _list_url("graphene"),
        Tier.SMALL,
        6,
        note="chemical plants, differing footprint from assemblers",
    ),
    CorpusEntry(
        "electromagnetic-matrix",
        _list_url("electromagnetic-matrix"),
        Tier.SMALL,
        9,
        note="red science: exercises Matrix Lab's 6x6 footprint",
    ),
    CorpusEntry(
        "plastic",
        _list_url("plastic"),
        Tier.SMALL,
        11,
        multi_producer=True,
        note="oil chain: refined-oil has two producers, so the MILP must choose",
    ),
    CorpusEntry(
        "processor",
        _list_url("processor"),
        Tier.MID,
        21,
        note="three raw inputs converging, wide bus",
    ),
    CorpusEntry(
        "energy-matrix",
        _list_url("energy-matrix"),
        Tier.MID,
        22,
        multi_producer=True,
        note="hydrogen byproduct: tests surplus handling",
    ),
    CorpusEntry(
        "super-magnetic-ring",
        (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            f"&ibe=conveyor-belt-2&mmr={_RANK}"
            "&mps=proliferator-2-products&v=11"
        ),
        Tier.MID,
        58,
        note="the user's own example URL; the reference case for this project",
    ),
    CorpusEntry(
        "casimir-crystal",
        _list_url("casimir-crystal", belt="conveyor-belt-3"),
        Tier.LARGE,
        99,
        multi_producer=True,
        note="Mk.III belts, so lane splitting is rarer and packing dominates",
    ),
    CorpusEntry(
        "information-matrix",
        _list_url("information-matrix", belt="conveyor-belt-3"),
        Tier.LARGE,
        101,
        multi_producer=True,
        note="five raw inputs: the widest external-input boundary in the corpus",
    ),
    CorpusEntry(
        "quantum-chip",
        _list_url("quantum-chip", belt="conveyor-belt-3", rank=_FAST_RANK),
        Tier.STRESS,
        300,
        note="faster machine rank; exercises the machine-speed path",
    ),
    CorpusEntry(
        "universe-matrix",
        _list_url("universe-matrix", belt="conveyor-belt-3", rank=_FAST_RANK),
        Tier.STRESS,
        955,
        multi_producer=True,
        note="deepest real chain (depth 9); where a strategy stops scaling",
    ),
)


def entries_for(*tiers: Tier) -> tuple[CorpusEntry, ...]:
    wanted = set(tiers)
    return tuple(e for e in URL_CORPUS if e.tier in wanted)


def entry(url_id: str) -> CorpusEntry:
    for e in URL_CORPUS:
        if e.url_id == url_id:
            return e
    raise KeyError(f"no corpus entry {url_id!r}")
