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
