"""Composite-key demand matching equals the `next()`-inside-a-comprehension scan.

The plan's line anchors (freeform.py:12111-12129 for `matches_demand`,
:9425 for `net_by_id`, :9372 for `role_members`) are stale at HEAD (Ruling
P-2) -- see `nets.py`'s module docstring for the real anchors this module was
built against, and the task-10 report for what moved.

`matches_demand(candidate, demand)` -- item, kind and cell equality -- is
asked with a `next()` over EVERY prepared net, inside a comprehension over
every missing demand: O(missing x all_prepared_nets). The same collection
family is separately keyed by id (`net_by_id`, two call sites) and by role
(`role_members`, one call site), which is why one table with three indexes
replaces three hand-built dicts rather than adding a fourth.
"""

from __future__ import annotations

import random

from flab2bp.indexed import Nets


def _fixture(seed: int, count: int) -> list[tuple[int, str, str, tuple[int, int, int], str, str]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "gear", "circuit")
    kinds = ("input", "output")
    roles = ("producer", "consumer", "external")
    return [
        (
            i,
            rng.choice(items),
            rng.choice(kinds),
            (rng.randrange(8), rng.randrange(8), 0),
            rng.choice(roles),
            f"net-{i}",
        )
        for i in range(count)
    ]


def test_matching_demand_equals_the_brute_force_triple_predicate() -> None:
    rows = _fixture(seed=81, count=300)
    index = Nets.of(rows)
    for item in ("iron-ingot", "gear", "circuit", "absent"):
        for kind in ("input", "output"):
            for cell in ((0, 0, 0), (3, 4, 0), (7, 7, 0)):
                brute = tuple(
                    payload
                    for _i, it, kd, cl, _role, payload in rows
                    if it == item and kd == kind and cl == cell
                )
                assert index.matching_demand(item, kind, cell) == brute, (item, kind, cell)


def test_by_id_equals_the_net_by_id_dict_and_answers_none_when_absent() -> None:
    rows = _fixture(seed=82, count=100)
    index = Nets.of(rows)
    for net_id, _it, _kd, _cl, _role, payload in rows:
        assert index.by_id(net_id) == payload
    assert index.by_id(9999) is None


def test_in_role_equals_the_role_members_grouping_in_input_order() -> None:
    rows = _fixture(seed=83, count=200)
    index = Nets.of(rows)
    for role in ("producer", "consumer", "external", "absent"):
        brute = tuple(i for i, _it, _kd, _cl, r, _payload in rows if r == role)
        assert index.in_role(role) == brute, role


def test_an_empty_collection_answers_empty() -> None:
    index = Nets.of(())
    assert index.ids() == ()
    assert index.matching_demand("gear", "input", (0, 0, 0)) == ()
    assert index.in_role("producer") == ()


def test_ids_reflects_insertion_order_not_ascending_net_id() -> None:
    """Order is byte-identity (Ruling: task-10 dispatch): pin it rather than assume it.

    Rows are handed to `Nets.of` out of ascending net-id order on purpose;
    `ids()` must echo the given order, not littletable's own bucket order and
    not a numeric sort, since the router's per-net loop order reaches the
    blueprint.
    """
    rows = [
        (5, "gear", "input", (0, 0, 0), "producer", "net-5"),
        (1, "gear", "input", (0, 0, 0), "producer", "net-1"),
        (3, "gear", "input", (0, 0, 0), "producer", "net-3"),
    ]
    index = Nets.of(rows)
    assert index.ids() == (5, 1, 3)
    assert index.in_role("producer") == (5, 1, 3)
