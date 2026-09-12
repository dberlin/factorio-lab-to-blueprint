from collections.abc import Callable, Collection

from flab2bp.layout.route_feedback import Cell

class JunctionNeighborhood:
    """Immutable planned coordinates, scoped to one unmodified frontier."""

    def __init__(
        self,
        planned: Collection[Cell],
        *,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None: ...
    def nearby(self, cell: Cell) -> tuple[Cell, ...]: ...
    @property
    def storage_bytes(self) -> int: ...
