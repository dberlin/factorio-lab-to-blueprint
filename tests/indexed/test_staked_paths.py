"""The maintained index equals `_leaning`'s from-scratch rebuild, always.

`_leaning` (freeform.py:10289-10359) rebuilds `touch` and `sole` from every
staked path's endpoints on EVERY call, once per stranded net inside `_repair`'s
loop, which itself runs per routing round per candidate pack per candidate
height. `paths` is rewritten under it the whole time -- `paths[index] = path` in
`_stake` (freeform.py:9925) and `paths.pop(index)` in `_unstake` (:9962) -- so
the staleness test is the point of this file, not a formality.
"""

from __future__ import annotations

import random

from flab2bp.indexed import StakedPaths

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int, int]


def _brute_touch(paths: dict[int, tuple[Cell, ...]]) -> dict[Cell, set[int]]:
    touch: dict[Cell, set[int]] = {}
    for other, path in paths.items():
        for end in (path[0], path[-1]):
            for dx, dy in _STEPS:
                beside = (end[0] + dx, end[1] + dy, end[2])
                touch.setdefault(beside, set()).add(other)
    return touch


def _brute_sole(
    paths: dict[int, tuple[Cell, ...]],
    owner: dict[Cell, int],
) -> dict[int, set[int]]:
    sole: dict[int, set[int]] = {}
    for other, path in paths.items():
        for end in (path[0], path[-1]):
            near: set[int] = set()
            for dx, dy in _STEPS:
                beside = (end[0] + dx, end[1] + dy, end[2])
                held = owner.get(beside)
                if held is not None and held != other:
                    near.add(held)
            if len(near) == 1:
                sole.setdefault(other, set()).update(near)
    return sole


def _random_path(rng: random.Random) -> tuple[Cell, ...]:
    x, y, z = rng.randrange(20), rng.randrange(20), rng.randrange(2)
    out = [(x, y, z)]
    for _ in range(rng.randrange(1, 6)):
        dx, dy = rng.choice(_STEPS)
        x, y = x + dx, y + dy
        out.append((x, y, z))
    return tuple(out)


def test_beside_equals_the_from_scratch_touch_map_after_every_mutation() -> None:
    rng = random.Random(51)
    index = StakedPaths(_STEPS)
    live: dict[int, tuple[Cell, ...]] = {}
    for step in range(400):
        if live and rng.random() < 0.35:
            victim = rng.choice(sorted(live))
            index.unstake(victim)
            del live[victim]
        else:
            net = step
            path = _random_path(rng)
            index.stake(net, path)
            live[net] = path
        brute = _brute_touch(live)
        for cell, expected in brute.items():
            assert index.beside(cell) == frozenset(expected), (step, cell)
            assert index.beside_in_scan_order(cell) == tuple(expected), (step, cell)
        assert index.nets() == tuple(sorted(live)), step


def test_beside_forgets_a_cell_entirely_once_its_last_net_is_unstaked() -> None:
    index = StakedPaths(_STEPS)
    index.stake(1, ((5, 5, 0), (6, 5, 0)))
    assert index.beside((4, 5, 0)) == frozenset({1})
    index.unstake(1)
    assert index.beside((4, 5, 0)) == frozenset()


def test_restaking_the_same_net_replaces_rather_than_accumulates() -> None:
    index = StakedPaths(_STEPS)
    index.stake(1, ((5, 5, 0), (6, 5, 0)))
    index.stake(1, ((9, 9, 0), (10, 9, 0)))
    assert index.beside((4, 5, 0)) == frozenset()
    assert index.beside((8, 9, 0)) == frozenset({1})
    assert index.path(1) == ((9, 9, 0), (10, 9, 0))


def test_sole_neighbours_equals_the_from_scratch_sole_map() -> None:
    rng = random.Random(52)
    index = StakedPaths(_STEPS)
    live: dict[int, tuple[Cell, ...]] = {}
    for net in range(60):
        path = _random_path(rng)
        index.stake(net, path)
        live[net] = path
    owner: dict[Cell, int] = {}
    for net, path in live.items():
        for cell in path:
            owner[cell] = net
    brute = _brute_sole(live, owner)
    for net in live:
        assert index.sole_neighbours(net, owner) == frozenset(brute.get(net, set())), net


def test_position_in_equals_tuple_index_and_answers_none_when_absent() -> None:
    index = StakedPaths(_STEPS)
    path = ((1, 1, 0), (2, 1, 0), (3, 1, 0), (1, 1, 0))
    index.stake(7, path)
    for cell in path:
        assert index.position_in(7, cell) == path.index(cell)
    assert index.position_in(7, (9, 9, 9)) is None
    assert index.position_in(999, (1, 1, 0)) is None


def test_stake_accepts_an_empty_path_without_raising() -> None:
    """Ruling P-26: master's `paths[index] = path` (freeform.py:9925) accepts
    anything, including an empty path -- Task 26's conversion calls `stake`
    with no guard. `stake` must not raise here, unlike the plan's draft.
    """
    index = StakedPaths(_STEPS)
    index.stake(3, ())
    assert index.nets() == (3,)
    assert index.path(3) == ()
    assert index.beside((0, 0, 0)) == frozenset()
    assert index.sole_neighbours(3, {}) == frozenset()
    assert index.position_in(3, (0, 0, 0)) is None
    index.unstake(3)
    assert index.nets() == ()


def test_linked_heads_drop_replaced_and_unstaked_taps_only() -> None:
    index = StakedPaths(_STEPS)
    shared = ((1, 1, 0), (2, 1, 0))
    index.stake(1, shared, linked_head=True)
    index.stake(2, shared, linked_head=True)
    index.stake(3, ((9, 9, 0),))
    assert index.linked_heads() == frozenset({shared[0]})
    index.unstake(1)
    assert index.linked_heads() == frozenset({shared[0]})
    index.stake(2, ((4, 4, 0),))
    assert index.linked_heads() == frozenset()


def test_ordered_snapshot_restores_replaced_and_reinserted_paths() -> None:
    paths = StakedPaths(_STEPS)
    repeated = ((0, 0, 0), (1, 0, 0), (0, 0, 0))
    paths.stake(8, repeated, linked_head=True)
    paths.stake(3, ((0, 2, 0),))
    paths.stake(8, repeated, linked_head=True)
    assert tuple(paths) == (8, 3)
    saved = paths.snapshot()
    scan = paths.beside_in_scan_order((0, 1, 0))

    paths.unstake(8)
    paths.stake(8, ((9, 9, 0),))
    paths.stake(5, ())
    paths.restore(saved)

    assert tuple(paths.items()) == ((8, repeated), (3, ((0, 2, 0),)))
    assert paths.beside_in_scan_order((0, 1, 0)) == scan
    assert paths.linked_heads() == frozenset({(0, 0, 0)})
    assert paths.position_in(8, (0, 0, 0)) == 0
    assert paths.nets() == (3, 8)
