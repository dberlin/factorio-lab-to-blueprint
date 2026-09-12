"""Identity and accounting of the production geometric routing engine."""

from typing import Literal


def selected_backend() -> Literal["geometric"]:
    """All detailed and relaxed production searches use interval wavefronts."""
    return "geometric"
