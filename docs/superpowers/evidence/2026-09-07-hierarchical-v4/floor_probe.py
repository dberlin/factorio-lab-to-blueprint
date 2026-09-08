"""Solve one partitioned block at one budget, with one arm, and report.

No monkeypatching: this calls the same ``partition.initial_partition`` /
``partition.sub_spec`` / ``SequencePairLayout.lay_out`` the strategy calls,
at the same ``STRIP_CAP_DEFAULT``, so a refusal here is the refusal a block
would get in a build -- minus the pool, which is what makes it cheap enough
to sweep.

Verified against the real tree before the sweep ran (Task 6, 2026-09-07);
every one of these is a deviation from the brief's assumed shapes:

* There is no ``flab2bp.pipeline.spec_for``. The real production call --
  used verbatim by ``docs/superpowers/evidence/2026-09-06-exp-trunk/spread.py``'s
  own ``spec_for`` helper, and internally by ``pipeline.build`` -- is
  ``build_candidates(load_vendored(), parse_url(url),
  candidate_policies=(policy,)).candidates[0]``.
* ``SequencePairLayout`` lives in ``flab2bp.layout.sequence_solver``, not
  ``flab2bp.layout.sequence_pair`` (that module holds lower-level pieces:
  ``SequencePair``, ``GapProfile``, etc., not the layout backend).
* ``SequencePairLayout.__init__`` has no ``time_budget_s`` parameter. The
  budget is a ``lay_out(spec, *, time_budget_s=...)`` argument, exactly as
  ``hierarchy.strategy._block_layout`` / ``_solve_block`` call it. This probe
  also passes ``islands=1``, matching ``_block_layout``'s block-arm
  construction exactly.
* ``BandPolicy`` has no ``.portable()`` classmethod. The real call, used
  verbatim by ``hierarchy.strategy._block_layout``, is
  ``BandPolicy.parse("portable")``.
* ``CandidatePolicy`` lives in ``flab2bp.rates.candidates``, not
  ``flab2bp.spec`` (which holds ``BuildSpec`` et al., not the policy enum).
* ``Unit``'s recipe attribute is ``.recipe``, not ``.recipe_id``.

Fix round 1 (review, 2026-09-07) also caught that ``Placement`` DOES have an
``.area`` property (``base.py:555-561`` -- it falls back to building-bounds
area when ``frame`` is ``None``, which is strictly more informative than the
frame-only computation this script used to do by hand); it is used directly
below. And that ``belt_vertical_construction`` -- left at
``SequencePairLayout``'s default of ``True`` in the first pass -- is derived
here from the swept URL exactly as production does
(``pipeline.py:913``: ``belt_vertical_construction=belt_rules.vertical_construction``,
via ``lab.techs.belt_rules_for_url``), rather than assumed, so a future
re-measure on a URL whose technology list changes that flag will not silently
diverge from the build it claims to reproduce.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from flab2bp.lab.data import load_vendored
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.hierarchy.partition import initial_partition, sub_spec
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import CandidatePolicy, build_candidates


def main(argv: list[str]) -> int:
    out, url, policy_name, block_index, budget_s = (
        Path(argv[0]),
        argv[1],
        argv[2],
        int(argv[3]),
        float(argv[4]),
    )
    spec = build_candidates(
        load_vendored(),
        parse_url(url),
        candidate_policies=(CandidatePolicy[policy_name],),
    ).candidates[0]
    belt_rules = belt_rules_for_url(url)
    partitioned = initial_partition(spec)
    block = partitioned.blocks[block_index]
    sub = sub_spec(spec, block, block_index)
    started = time.monotonic()
    record: dict[str, object] = {
        "block": block_index,
        "budget_s": budget_s,
        "recipes": sorted({unit.recipe for unit in block}),
    }
    try:
        placement = SequencePairLayout(
            band_policy=BandPolicy.parse("portable"),
            belt_vertical_construction=belt_rules.vertical_construction,
            islands=1,
        ).lay_out(sub, time_budget_s=budget_s)
        record |= {
            "ok": True,
            "frame": (
                None
                if placement.frame is None
                else {"width": placement.frame.width, "height": placement.frame.height}
            ),
            "area": placement.area,
        }
    except NoValidLayout as refusal:
        record |= {"ok": False, "verdict": str(refusal)[:600]}
    record["wall_s"] = round(time.monotonic() - started, 3)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
