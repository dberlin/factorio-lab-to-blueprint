"""Composite-key demand matching equals the `next()`-inside-a-comprehension scan.

The plan's line anchors (freeform.py:12111-12129 for `matches_demand`,
:9425 for `net_by_id`, :9372 for `role_members`) are stale at HEAD (Ruling
P-2) -- see `nets.py`'s module docstring for the real anchors this module was
built against, and the task-10 report (fix round 1) for what moved and what
the first round of review found wrong.

`matches_demand(candidate, demand)` -- item, kind and cell equality -- is
asked with a `next()` over EVERY prepared net, inside a comprehension over
every missing demand: O(missing x all_prepared_nets). Two more collections
carry a `net_by_id`-shaped dict, and one of those two also carries
`role_members`, keyed by the COMPOSITE `(cell, role)` (freeform.py:9368,
queried at :9889) -- NOT a bare role, which is why `in_role` here takes
both. One table with three indexes replaces these hand-built dicts rather
than adding a fourth.
"""

from __future__ import annotations

import random

from flab2bp.indexed import Nets


def _fixture(seed: int, count: int) -> list[tuple[int, str, str, tuple[int, int, int], str, str]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "gear", "circuit")
    kinds = ("input", "output")
    roles = ("src", "dst")
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


def test_in_role_equals_the_role_members_composite_grouping_in_input_order() -> None:
    """`role_members[cell, role]` is a composite key (freeform.py:9368-9376, :9889).

    A bare-role query cannot express this -- two different cells sharing a
    role must not be conflated, which is exactly what the first review round
    found the pre-fix `in_role(role)` got wrong.
    """
    rows = _fixture(seed=83, count=200)
    index = Nets.of(rows)
    cells = ((0, 0, 0), (3, 4, 0), (7, 7, 0))
    for role in ("src", "dst", "absent"):
        for cell in cells:
            brute = tuple(i for i, _it, _kd, cl, r, _payload in rows if r == role and cl == cell)
            assert index.in_role(cell, role) == brute, (cell, role)


def test_in_role_does_not_conflate_two_cells_sharing_a_role() -> None:
    """A regression pin for the exact defect the first review round found.

    `in_role("src")` on the pre-fix accessor would have returned every net
    in role "src" across every cell; the composite accessor must scope to
    one cell.
    """
    rows = [
        (1, "gear", "input", (0, 0, 0), "src", "net-1"),
        (2, "gear", "input", (5, 5, 0), "src", "net-2"),
    ]
    index = Nets.of(rows)
    assert index.in_role((0, 0, 0), "src") == (1,)
    assert index.in_role((5, 5, 0), "src") == (2,)


def test_a_net_in_two_roles_shares_one_id_and_one_payload_across_two_rows() -> None:
    """`role_members` gives every net a "dst" row and, if `net.src` is not
    None, a SECOND "src" row at a different cell (freeform.py:9370-9376) --
    so one net_id can legitimately appear on two rows sharing one payload.
    `ids()` must still answer that net_id once, not twice, and `by_id` must
    still answer the (identical) payload.
    """
    rows = [
        (7, "gear", "input", (1, 1, 0), "src", "net-7"),
        (7, "gear", "input", (2, 2, 0), "dst", "net-7"),
        (9, "circuit", "output", (3, 3, 0), "dst", "net-9"),
    ]
    index = Nets.of(rows)
    assert index.ids() == (7, 9)
    assert index.by_id(7) == "net-7"
    assert index.in_role((1, 1, 0), "src") == (7,)
    assert index.in_role((2, 2, 0), "dst") == (7,)


def test_an_empty_collection_answers_empty() -> None:
    index: Nets[int] = Nets.of(())
    assert index.ids() == ()
    assert index.matching_demand("gear", "input", (0, 0, 0)) == ()
    assert index.in_role((0, 0, 0), "src") == ()


def test_ids_reflects_insertion_order_not_ascending_net_id() -> None:
    """Order is byte-identity (Ruling: task-10 dispatch): pin it rather than assume it.

    Rows are handed to `Nets.of` out of ascending net-id order on purpose;
    `ids()` must echo the given order, not littletable's own bucket order and
    not a numeric sort, since the router's per-net loop order reaches the
    blueprint.
    """
    rows = [
        (5, "gear", "input", (0, 0, 0), "src", "net-5"),
        (1, "gear", "input", (0, 0, 0), "src", "net-1"),
        (3, "gear", "input", (0, 0, 0), "src", "net-3"),
    ]
    index = Nets.of(rows)
    assert index.ids() == (5, 1, 3)
    assert index.in_role((0, 0, 0), "src") == (5, 1, 3)


def test_stable_net_ids_keep_role_and_payload_order() -> None:
    from flab2bp.layout.route_feedback import NetId, NetRole

    first = NetId(0, 1, "gear", NetRole.INTERNAL, 0)
    second = NetId(2, 1, "gear", NetRole.INTERNAL, 1)
    rows = [
        (first, "gear", "", (9, 0, 0), "src", "first"),
        (first, "gear", "", (1, 0, 0), "dst", "first"),
        (second, "gear", "", (1, 0, 0), "dst", "second"),
    ]
    index = Nets.of(rows)

    assert index.ids() == (first, second)
    assert index.by_id(first) == "first"
    assert index.roles_of(first) == (((9, 0, 0), "src"), ((1, 0, 0), "dst"))
    assert index.payloads_in_role((1, 0, 0), "dst") == ("first", "second")


def test_replacing_phase_endpoints_preserves_old_queries_and_payload_identity() -> None:
    from dataclasses import FrozenInstanceError, replace

    import pytest

    from flab2bp.layout.route_feedback import NetId, NetRole
    from flab2bp.layout.routing_domain import _Net, _Port

    net_id = NetId(0, 1, "gear", NetRole.INTERNAL, 0)
    first = _Net(_Port(0, 0, 0), _Port(1, 4, 0), "gear", net_id=net_id)

    def phase(net: _Net) -> Nets[NetId]:
        return Nets.of(
            (net_id, net.item, kind, (port.x, port.y, port.z), role, net)
            for port, kind, role in (
                (net.source, "departure", "src"),
                (net.dst, "arrival", "dst"),
            )
        )

    old = phase(first)
    with pytest.raises(FrozenInstanceError):
        first.dst = _Port(2, 8, 0)  # type: ignore[misc]
    replacement = replace(first, dst=_Port(2, 8, 0))
    new = phase(replacement)

    assert old.in_role((4, 0, 0), "dst") == (net_id,)
    assert old.in_role((8, 0, 0), "dst") == ()
    assert new.in_role((4, 0, 0), "dst") == ()
    assert new.matching_demand("gear", "arrival", (8, 0, 0))[0] is replacement
    assert old.by_id(net_id) is first
    assert old.payloads_in_role((0, 0, 0), "src")[0] is first
    assert old.payloads_in_role((4, 0, 0), "dst")[0] is first
    assert new.payloads_in_role((0, 0, 0), "src")[0] is replacement
    assert old.ids() == new.ids() == (net_id,)


def test_role_rows_preserve_duplicates_and_live_payload_state_across_phases() -> None:
    first = {"served": False}
    second = {"served": True}
    cell = (3, 4, 0)
    rows = [
        (7, "gear", "input", cell, "src", first),
        (2, "gear", "input", cell, "src", second),
        (7, "gear", "input", cell, "src", first),
    ]
    old = Nets.of(iter(rows))
    assert old.payloads_in_role(cell, "src") == (first, second, first)

    first["served"] = True
    rows.pop(0)
    fresh = Nets.of(iter(rows))
    assert all(payload["served"] for payload in old.payloads_in_role(cell, "src"))
    assert tuple(id(payload) for payload in old.payloads_in_role(cell, "src")) == (
        id(first),
        id(second),
        id(first),
    )
    assert tuple(id(payload) for payload in fresh.payloads_in_role(cell, "src")) == (
        id(second),
        id(first),
    )
    assert old.payloads_in_role(cell, "dst") == ()
