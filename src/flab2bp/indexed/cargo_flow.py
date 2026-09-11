"""Exact directed cargo allocation for hierarchy boundary and coater rates.

Capacities remain Fractions; unrated transport links are unbounded. Domain
operations retain insertion order and DiGraph's single edge per ordered pair,
so repeated reachability never duplicates supply, demand, or transport flow.
Both allocations retain Edmonds-Karp's existing deterministic path selection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence, Set
from fractions import Fraction
from typing import Literal

import networkx as nx

type CargoDestination = tuple[Literal["consumer", "coater", "tail"], int]
type _Node = str | tuple[str, int]


class BoundaryRateFlow:
    """Reserve internal consumption while assigning an exact boundary rate."""

    def __init__(
        self,
        supply: Mapping[int, Fraction],
        demand: Mapping[int, Fraction],
        *,
        puts_on: bool,
    ) -> None:
        self._graph: nx.DiGraph[_Node] = nx.DiGraph()
        self._puts_on: bool = puts_on
        self._graph.add_nodes_from(("source", "sink", "boundary"))
        for machine, rate in supply.items():
            self._graph.add_edge("source", ("producer", machine), capacity=rate)
        for machine, rate in demand.items():
            self._graph.add_edge(("consumer", machine), "sink", capacity=rate)

    def connect_lane(self, lane: int, machines: Iterable[int]) -> None:
        """Connect a boundary lane to its reachable producers or consumers."""
        if self._puts_on:
            self._graph.add_edge(("lane", lane), "boundary")
            for machine in machines:
                self._graph.add_edge(("producer", machine), ("lane", lane))
        else:
            self._graph.add_edge("boundary", ("lane", lane))
            for machine in machines:
                self._graph.add_edge(("lane", lane), ("consumer", machine))

    def set_boundary_rate(self, total: Fraction) -> None:
        if self._puts_on:
            self._graph.add_edge("boundary", "sink", capacity=total)
        else:
            self._graph.add_edge("source", "boundary", capacity=total)

    def connect_internal(self, producer: int, consumers: Iterable[int]) -> None:
        for consumer in consumers:
            self._graph.add_edge(("producer", producer), ("consumer", consumer))

    def allocate(self, lanes: Sequence[int]) -> tuple[Fraction, list[Fraction]]:
        """Return delivered demand and boundary lane rates in the requested order."""
        delivered: int | Fraction
        flow: dict[_Node, dict[_Node, int | Fraction]]
        delivered, flow = nx.maximum_flow(
            self._graph, "source", "sink", flow_func=nx.algorithms.flow.edmonds_karp
        )
        return Fraction(delivered), [
            Fraction(flow[("lane", lane)]["boundary"])
            if self._puts_on
            else Fraction(flow["boundary"][("lane", lane)])
            for lane in lanes
        ]


class SprayedCargoFlow:
    """Attribute constrained cargo supply to its first coater and final demand."""

    def __init__(self) -> None:
        self._graph: nx.DiGraph[_Node] = nx.DiGraph()
        self._graph.add_nodes_from(("source", "sink"))

    def require_consumer(self, machine: int, rate: Fraction) -> None:
        self._graph.add_edge(("consumer", machine), "sink", capacity=rate)

    def offer_producer(
        self, machine: int, rate: Fraction, destinations: Iterable[CargoDestination]
    ) -> None:
        producer = ("producer", machine)
        self._graph.add_edge("source", producer, capacity=rate)
        for destination in destinations:
            self._graph.add_edge(producer, destination)

    def offer_head(
        self, head: int, rate: Fraction, destinations: Iterable[CargoDestination]
    ) -> None:
        origin = ("head", head)
        self._graph.add_edge("source", origin, capacity=rate)
        for destination in destinations:
            self._graph.add_edge(origin, destination)

    def require_tail(self, tail: int, rate: Fraction) -> None:
        self._graph.add_edge(("tail", tail), "sink", capacity=rate)

    def connect_coater(self, coater: int, destinations: Iterable[CargoDestination]) -> None:
        origin = ("coater", coater)
        self._graph.add_node(origin)
        for destination in destinations:
            self._graph.add_edge(origin, destination)

    def allocate(
        self, coaters: Iterable[int], requested: Set[int]
    ) -> tuple[Fraction, dict[int, Fraction]]:
        """Return delivered demand and cargo each coater sends to sprayed consumers."""
        delivered: int | Fraction
        flow: dict[_Node, dict[_Node, int | Fraction]]
        delivered, flow = nx.maximum_flow(
            self._graph, "source", "sink", flow_func=nx.algorithms.flow.edmonds_karp
        )
        return Fraction(delivered), {
            coater: sum(
                (
                    Fraction(rate)
                    for destination, rate in flow[("coater", coater)].items()
                    if isinstance(destination, tuple)
                    and destination[0] == "consumer"
                    and destination[1] in requested
                ),
                Fraction(0),
            )
            for coater in coaters
        }
