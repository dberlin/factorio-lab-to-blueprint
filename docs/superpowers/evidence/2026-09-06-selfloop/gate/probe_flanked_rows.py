"""Measure the flanked family's row budget, per candidate, on whatever tree runs it.

`universe-matrix#37` is the only flanked plan in the corpus (spec §9 R2), and it
REFUSES on the branch, so the corpus audit cannot show its rows.  This probe
plans the strips directly -- no routing, no validation -- so the drain-row move
and the un-mixing can be counted on master and on the branch and reported
separately, as measured, instead of quoted from the design note.

Run with no arguments; it prints one block per candidate policy.
"""

from __future__ import annotations

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.freeform import plan_strips
from flab2bp.rates.candidates import CandidatePolicy, build_candidates


def _lane_items(lane: object) -> list[str]:
    """A lane is a ``tuple[str, ...]`` of item ids (`freeform.Strip.in_above`)."""
    if isinstance(lane, str):
        return [lane]
    if isinstance(lane, (tuple, list)):
        return [str(v) for v in lane]
    return [f"?{type(lane).__name__}"]


def main() -> None:
    entry = next(e for e in URL_CORPUS if e.url_id == "universe-matrix")
    data = load_vendored()
    request = parse_url(entry.url)
    for policy in (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.ALL_PRODUCTS,
        CandidatePolicy.OUTPUT_PRODUCTS,
    ):
        spec = build_candidates(data, request, candidate_policies=(policy,)).candidates[0]
        strips = plan_strips(spec)
        heights = [s.box_height for s in strips]
        print(f"== {policy.value} ==")
        print(f"strips {len(strips)}  tallest box_height {max(heights)}  total box_height {sum(heights)}")
        flanked = [s for s in strips if s.flank_outputs]
        print(f"flanked strips {len(flanked)}")
        seen: dict[str, int] = {}
        for s in flanked:
            above = [_lane_items(lane) for lane in s.in_above]
            below = [_lane_items(lane) for lane in s.in_below]
            block = (
                f"  {s.group_key} machines={s.machines} box_height={s.box_height} "
                f"width={s.width} drain_outermost={getattr(s, 'drain_outermost', 'ABSENT')}\n"
                f"    in_above {len(above)} lane(s): {above}\n"
                f"    in_below {len(below)} lane(s): {below}\n"
                f"    out_lanes {len(s.out_lanes)}"
            )
            seen[block] = seen.get(block, 0) + 1
        for block, count in seen.items():
            print(f"  x{count} identical:")
            print(block)
        print()


def counterfactual() -> None:
    """Separate the drain-row move from the un-mixing, by measurement.

    `_seat_inputs` rations `in_below` by `below_cap`.  With the drain innermost
    (master) the drain eats one of those rows, so the input budget is
    `below_cap - 1`; with `drain_outermost` it is the whole `below_cap`.  Run
    the seating both ways on the Matrix Lab's six ingredients and print what
    each returns -- that is the drain row's own contribution, measured.
    """
    from flab2bp.layout.freeform import _seat_inputs, _side_lane_caps

    items = (
        "antimatter",
        "electromagnetic-matrix",
        "energy-matrix",
        "gravity-matrix",
        "information-matrix",
        "structure-matrix",
    )
    # 2901 = matrix-lab, 5 band rows, yaw 0 -- the pose universe-matrix#37 uses.
    caps = _side_lane_caps(2901, 0.0, 5)
    print("== counterfactual: the drain row's own contribution ==")
    print(f"_side_lane_caps(2901, 0.0, 5) = {caps}")
    above_cap, below_cap = caps
    for label, cap in (
        (f"drain OUTERMOST (branch): below_cap={below_cap}", below_cap),
        (f"drain innermost (master's rationing): below_cap={below_cap - 1}", below_cap - 1),
    ):
        try:
            above, below = _seat_inputs(
                items, n_sinks=1, above_cap=above_cap, below_cap=cap, columns=3, flank_outputs=True
            )
        except ValueError as exc:
            print(f"  {label} -> REFUSES: {exc}")
            continue
        mixed = [lane for lane in (*above, *below) if len(lane) > 1]
        print(
            f"  {label} -> above {len(above)} lane(s) {[list(x) for x in above]}, "
            f"below {len(below)} lane(s) {[list(x) for x in below]}, "
            f"mixed lanes {len(mixed)}"
        )


if __name__ == "__main__":
    main()
    counterfactual()
