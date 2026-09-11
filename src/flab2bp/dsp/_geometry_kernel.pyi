from collections.abc import Callable, Sequence

from flab2bp.dsp.colliders import Box, Preview, Vec3
from flab2bp.indexed.belt_overlap import Cell

def obb_overlap(a: Box, b: Box) -> bool: ...
def any_box_overlap(queries: Sequence[Box], targets: Sequence[Box]) -> bool: ...
def sphere_box_overlap(centre: Vec3, radius: float, box: Box) -> bool: ...
def sphere_box_candidates(
    centre: Vec3, radius: float, targets: Sequence[Sequence[Box]], candidates: Sequence[int]
) -> list[int]: ...

class ProjectedBeltProbe:
    def __init__(
        self,
        anchor: float,
        latitude_step: float,
        longitude_step: float,
        radius: float,
        lift: float,
        rotated: bool,
    ) -> None: ...
    def __call__(self, x: float, y: float, z: float) -> Vec3: ...

class ProjectedBeltScan:
    def __init__(
        self,
        probe: ProjectedBeltProbe,
        radius: float,
        targets: Sequence[Sequence[Box]],
        cells: Sequence[Sequence[Cell]],
        target_indices: Sequence[int],
    ) -> None: ...
    def scan(
        self,
        previews: Sequence[Preview],
        start: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, tuple[int, ...]]:
        """Scan up to 256 previews, stopping on the first raw-hit belt.

        Return the next preview offset and sorted original target indices;
        nonempty hits belong to preview ``next_offset - 1``.
        """
        ...
