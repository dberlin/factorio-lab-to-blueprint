"""Stage 2-3: objectives in, candidate ``BuildSpec``s out.

Exact rational arithmetic throughout; no geometry reasoning lives here.
"""

from flab2bp.rates.adjust import (
    AdjustedRecipe,
    ProliferatorTier,
    adjust,
    available_modes,
    machine_footprint,
    select_machine,
)
from flab2bp.rates.candidates import (
    build_candidates,
    lanes_requiring_split,
)
from flab2bp.rates.solve import (
    InfeasibleError,
    RateSolution,
    SolvedGroup,
    UnsupportedObjectiveError,
    solve,
    target_producer_ids,
    target_rates,
)

__all__ = [
    "AdjustedRecipe",
    "InfeasibleError",
    "ProliferatorTier",
    "RateSolution",
    "SolvedGroup",
    "UnsupportedObjectiveError",
    "adjust",
    "available_modes",
    "build_candidates",
    "lanes_requiring_split",
    "machine_footprint",
    "select_machine",
    "solve",
    "target_producer_ids",
    "target_rates",
]
