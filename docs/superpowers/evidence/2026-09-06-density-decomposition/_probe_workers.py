"""Prove the spike switches reach a forkserver pool child (throwaway probe)."""

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor


def probe(_):
    from flab2bp.layout import freeform
    from flab2bp.layout.band_policy import BandPolicy

    layout = freeform.FreeformLayout(band_policy=BandPolicy("portable"), workers=2)
    return (
        mp.get_start_method(),
        layout.direct_insert,
        freeform._merge_frontier.__name__,
        freeform._plan_shared_external_inputs.__name__,
    )


if __name__ == "__main__":
    print("parent:", mp.get_start_method())
    with ProcessPoolExecutor(max_workers=2) as pool:
        print("child:", list(pool.map(probe, [0]))[0])
