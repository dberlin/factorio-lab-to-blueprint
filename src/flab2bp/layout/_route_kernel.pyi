from array import array
from collections.abc import Callable

def astar_flat(
    flags: bytearray,
    hist: array[float],
    pressure: float,
    alt_flat: array[int],
    band_count: int,
    goal_flag: bytearray,
    goal_columns: array[int],
    exact_goals: bool,
    goal_box: tuple[int, int, int, int],
    starts: array[int],
    gh: int,
    xstep: int,
    levels: int,
    level_toll: array[float],
    max_expansions: int,
    budget_left: int,
    deadline_every: int,
    deadline: float | None,
    expired: Callable[[float | None], bool],
) -> tuple[array[int] | None, int, int, array[int], int]:
    """(path indices with via cells spliced, oldest first, or None;
    expansions; exit kind 0 found / 1 budget / 2 sealed;
    settled cell indices in index order when sealed, else empty;
    budget_left after the same write-back rules as the Python loop)."""

def relaxed_search_flat(
    flags: bytearray,
    present: array[float],
    history: array[float],
    weight: float,
    transitions_target: array[int],
    transitions_via: array[int],
    transitions_cost: array[float],
    starts: array[int],
    goals: array[int],
    goal_xy: array[int],
    gh: int,
    levels: int,
    budget: int,
    cancelled: Callable[[], bool] | None,
) -> tuple[array[int] | None, int, bool, bool]:
    """(path indices with via cells spliced, oldest first, or None;
    expansions; whether the budget stopped the search; whether it was
    cancelled).  ``present`` is dense and pre-multiplied by ``_PRESENT_COST``;
    ``history`` is dense or zero-length; the three transition buffers hold, per
    level, a count slot followed by that level's entries, and only
    ``transitions_target`` carries the count -- the slot is padding in the
    other two; ``goals`` is sorted and ``goal_xy`` holds its local (x, y) pairs
    in the same order."""
