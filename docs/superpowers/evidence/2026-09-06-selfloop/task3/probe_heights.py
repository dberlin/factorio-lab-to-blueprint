"""Re-derive `test_the_schedule_replaces_the_over_band_height_with_the_boundary`.

Prints the `universe-matrix/no-proliferator` strip count, the unmodified
candidate-height schedule, and the schedule once the tallest height's greedy
seed is widened to R1's historical 258 -- the two numbers that test pins.
"""

from __future__ import annotations

from dataclasses import replace

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import plan_strips
from flab2bp.rates.candidates import CandidatePolicy, build_candidates


def main() -> None:
    entry = next(e for e in URL_CORPUS if e.url_id == "universe-matrix")
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    ).candidates[0]
    strips = plan_strips(spec)
    print("strips", len(strips))
    flanked = [s for s in strips if s.flank_outputs]
    print(
        "flanked strips",
        len(flanked),
        [(s.group_key, s.machines, s.box_height, s.width, s.drain_outermost) for s in flanked],
    )
    base = freeform._band_policy_candidate_heights(strips, BandPolicy("portable"))
    print("unmodified schedule", base)

    real_greedy_pack = freeform._greedy_pack
    tallest = max(base)

    def widened(strips_: list, height: int) -> freeform._Pack:
        pack = real_greedy_pack(strips_, height)
        if height != tallest:
            return pack
        box_rights = {
            index: pack.at[index][0] - strip.west_channel + freeform._box(strip)[0]
            for index, strip in enumerate(strips_)
        }
        rightmost = max(box_rights, key=box_rights.__getitem__)
        realized_width, _ = freeform._realized_pack_outline(strips_, pack)
        at = dict(pack.at)
        x, y = at[rightmost]
        added = 258 - realized_width
        at[rightmost] = (x + added, y)
        print(f"  tallest={tallest} realized_width={realized_width} added={added}")
        return replace(pack, at=at, width=pack.width + added)

    freeform._greedy_pack = widened  # type: ignore[assignment]
    try:
        widened_schedule = freeform._band_policy_candidate_heights(strips, BandPolicy("portable"))
    finally:
        freeform._greedy_pack = real_greedy_pack  # type: ignore[assignment]
    print("widened schedule", widened_schedule)


if __name__ == "__main__":
    main()
