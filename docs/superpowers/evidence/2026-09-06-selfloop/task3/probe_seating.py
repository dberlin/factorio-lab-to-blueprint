"""Measure the Matrix Lab seating: caps, `_seat_inputs`, and the flanked plan.

Run in-tree.  Prints the same numbers the task brief quotes, so a reader can
re-take the measurement rather than trust the report.
"""

from __future__ import annotations

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout import slots
from flab2bp.layout.freeform import _seat_inputs, _side_lane_caps, plan_strips
from flab2bp.layout.strip_variants import _logical_strip_plans
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates


def corpus_specs(url_id: str) -> list:
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    return list(
        build_candidates(
            load_vendored(),
            parse_url(entry.url),
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        ).candidates
    )


def main() -> None:
    print("== geometry ==")
    print("SORTER_MAX_REACH", catalog.SORTER_MAX_REACH)
    print("_side_lane_caps(2901, 0.0, 5)", _side_lane_caps(2901, 0.0, 5))
    probe = slots.probe_building(2901, 0.0)
    for lane_y in (-1, -2, -3, -4, 5, 6, 7, 8):
        print(f"  attachable_columns lane_y={lane_y:>3}", len(slots.attachable_columns(probe, lane_y)))

    print("== _seat_inputs ==")
    six = ("a", "b", "c", "d", "e", "f")
    for caps, flank in (((3, 3), True), ((3, 3), False), ((3, 4), True)):
        try:
            out = _seat_inputs(
                six, 1, caps[0], caps[1], max_per_lane=5, columns=3, flank_outputs=flank
            )
        except ValueError as exc:
            out = f"ValueError {exc}"
        print(f"  caps={caps} flank={flank} -> {out}")

    print("== flanked plans in the corpus spec candidates ==")
    for index, spec in enumerate(corpus_specs("universe-matrix")):
        plans = _logical_strip_plans(spec)
        flanked = [p for p in plans if p.flank_outputs]
        print(f"  candidate {index} label={spec.label!r} plans={len(plans)} flanked={len(flanked)}")
        for plan in flanked:
            print(f"    FLANK {plan.group_key}#{plan.shard_index} item_id={plan.item_id}")
            print(f"      above {plan.in_above}")
            print(f"      below {plan.in_below}")
            print(f"      out   {plan.out_lanes}")

    print("== flanked strips from plan_strips (candidate 0) ==")
    spec = corpus_specs("universe-matrix")[0]
    for strip in plan_strips(spec):
        if not strip.flank_outputs:
            continue
        print(
            f"  {strip.group_key} box_height={strip.box_height} width={strip.width} "
            f"ph={strip.ph} above={len(strip.in_above)} below={len(strip.in_below)} "
            f"outs={len(strip.out_lanes)}"
        )
        print(f"    in_above {strip.in_above}")
        print(f"    in_below {strip.in_below}")
        print(f"    first_row_below_band {strip.first_row_below_band}")
        for k in range(len(strip.out_lanes)):
            row = strip.row_of_output(k)
            print(f"    out {k} row {row} sorter_span {strip.sorter_span(row)}")
        for lane in strip.in_below:
            row = strip.row_of_input(lane[0])
            print(f"    below lane {lane} row {row} sorter_span {strip.sorter_span(row)}")
        for lane in strip.in_above:
            row = strip.row_of_input(lane[0])
            print(f"    above lane {lane} row {row} sorter_span {strip.sorter_span(row)}")


if __name__ == "__main__":
    main()
