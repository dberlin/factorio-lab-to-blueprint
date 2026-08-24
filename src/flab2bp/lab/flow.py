"""FactorioLab's own solved flow, read from its JSON export.

FactorioLab's flow view has a "download as JSON" button (``Exporter.flowToJson``
in ``src/exporter/exporter.ts``).  It writes the graph FactorioLab solved, and
the thing we take from it is the **recipe selection**: which recipe the player's
own settings chose to make each item.  That decision is theirs, and re-deriving
it is what this module exists to stop.  Measured on the corpus, 17 items have
more than one permitted producer and **16 of those choices move the blueprint's
input/output boundary** -- which is how a flow containing no stone produced a
blueprint asking the player to belt stone in.

What the file actually is
-------------------------

Read off FactorioLab's own source (``src/flow/flow-builder.ts``,
``FlowBuilder.buildGraph``) rather than inferred from a sample::

    {"nodes": [{"id": "r|graphene-advanced", "name": ..., "text": "1", ...},
               {"id": "i|fire-ice", ...}],
     "links": [{"source": "i|fire-ice", "target": "r|graphene-advanced",
                "text": "60/m", "value": 5, "color": ...}]}

Node ids are ``<kind>|<id>`` with five kinds: ``i`` an item, ``r`` a recipe,
``m`` a recipe *objective*, ``s`` an item's surplus, ``o`` an item's output.

**Only the recipe nodes are trustworthy, and only as a set of ids.**  Everything
else in this file is a Sankey diagram, and the diagram is not the flow:

* ``link.value`` is a **float** -- ``Rational.toNumber()`` -- and it is not even
  a rate.  It is scaled to 1/10 for fluids, floored at ``MIN_LINK_VALUE = 1e-10``
  when it would be zero, and its *meaning* is whatever the viewer's ``linkSize``
  preference says: items, belts, machines, or a percentage.
* ``node.text`` and ``link.text`` are **display strings**:
  ``toLocaleString(precision)``, rounded to the viewer's column-precision
  preference, locale-formatted, with a rate suffix appended.
* **Item nodes are deleted.**  ``buildGraph`` prunes any item node with a single
  source or a single target and re-points the links around it, so the item set
  in the file is incomplete by design -- an external input feeding one recipe is
  exactly the shape that gets pruned.  The ``hideExcluded`` preference removes
  more.  Recipe nodes are never pruned (the filter tests ``id.startsWith('i')``),
  which is why the selection survives when nothing else does.
* **There is no URL in the file.**  ``flowToJson`` writes
  ``JSON.stringify(flowData)`` and nothing else, so unlike the CSV export --
  whose first line is ``window.location.href`` -- this file carries no record of
  what produced it.  :func:`verify_against_request` substitutes what provenance
  can still be established structurally; see its docstring for what that does
  and does not catch.

So: **the selection comes from this file and every magnitude is re-derived
exactly.**  Every rate in this program is a ``Fraction`` because belts are sized
from them and the validator checks capacity exactly; a float in that path ships
a blueprint that quietly misses its rate, which is the worst failure available
here.  Nothing numeric from this file is ever used as a rate.

How the selection is applied
----------------------------

:func:`pin_request` rewrites the request's recipe-exclusion set to "every recipe
FactorioLab did not choose".  That is the existing, well-understood lever --
``solve._excluded_recipes`` already treats the URL's exclusion set as
authoritative, "the state of FactorioLab's UI, not a delta" -- so pinning
introduces no new concept in the rate solver, and nothing changes at all for a
build that supplies no flow file.  An item whose only chosen producer is
mining-flagged still falls out as an external input, for the reason it always
did: ``_buildable_producers`` cuts the 22 mining recipes because extraction
happens outside the blueprint.

There is no fallback.  Absent, malformed, inconsistent with the URL, or naming a
recipe we cannot build: this module raises.  Silently re-deriving the selection
is the behaviour it exists to remove.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest, ObjectiveType

__all__ = [
    "FlowError",
    "FlowFormatError",
    "FlowNode",
    "FlowProvenanceError",
    "FlowSelection",
    "FlowSelectionError",
    "compare_selection",
    "load_flow",
    "parse_flow_json",
    "pin_request",
    "pinned_exclusions",
    "verify_against_request",
]


class FlowError(ValueError):
    """Base class for every refusal in this module.

    Derives from ``ValueError`` so the CLI reports it as a bad input (exit 2)
    rather than as a layout failure.  Every subclass means "refuse"; none of
    them means "carry on without the flow".
    """


class FlowFormatError(FlowError):
    """The file is not a FactorioLab flow export, or is damaged."""


class FlowProvenanceError(FlowError):
    """The flow cannot have come from the URL being built."""


class FlowSelectionError(FlowError):
    """The flow names a recipe this program cannot build."""


#: ``i`` item, ``r`` recipe, ``m`` recipe objective, ``s`` surplus, ``o`` output.
#: From ``FlowBuilder.buildGraph``; a node id outside this set means the format
#: has moved and every id we read out of the file is a guess.
_KINDS: Final = frozenset({"i", "r", "m", "s", "o"})

#: The two kinds that name a recipe.  ``m`` is a recipe *objective* -- the player
#: asked for N machines of it directly -- and it is as much a selection as ``r``.
_RECIPE_KINDS: Final = frozenset({"r", "m"})


@dataclass(frozen=True, slots=True)
class FlowNode:
    """One node of the exported Sankey graph."""

    kind: str
    #: The item or recipe id, i.e. the node id with its ``<kind>|`` prefix off.
    ref_id: str
    #: The node's DISPLAY label -- rounded, locale-formatted, suffixed.  Kept so
    #: a report can quote what FactorioLab showed the player.  Never a rate.
    text: str = ""
    #: ``icon.id``, which for a recipe node with a machine set is that machine's
    #: item id and otherwise is the recipe's own id.  Only trusted when it
    #: resolves to a machine in our dataset; see :meth:`FlowSelection.machines`.
    icon_id: str = ""

    @property
    def node_id(self) -> str:
        return f"{self.kind}|{self.ref_id}"


@dataclass(frozen=True, slots=True)
class FlowSelection:
    """A parsed FactorioLab flow export.

    Deliberately holds no magnitudes.  The file's numbers are display values and
    render sizes, and promoting one of them to a rate is the single thing this
    module must never do.
    """

    nodes: tuple[FlowNode, ...]
    #: ``(source node id, target node id)`` pairs, for reporting only.
    links: tuple[tuple[str, str], ...] = ()

    @property
    def chosen_recipe_ids(self) -> frozenset[str]:
        """Every recipe FactorioLab's flow runs.

        A SET, deliberately, not an item->recipe map.  A recipe is drawn at the
        node for the item it is keyed to, but it also produces that node's
        byproducts -- ``graphene-advanced`` makes graphene *and* hydrogen, and
        hydrogen has no recipe node of its own.  Pinning per item would strike
        out the recipe that supplies the byproduct.
        """
        return frozenset(n.ref_id for n in self.nodes if n.kind in _RECIPE_KINDS)

    @property
    def item_ids(self) -> frozenset[str]:
        """Items with a node.

        **Incomplete by design** -- ``buildGraph`` prunes item nodes that have a
        single source or a single target, which is precisely the shape of an
        external input feeding one recipe.  Never test membership of this set to
        decide whether an item is absent from the flow; a miss proves nothing.
        """
        return frozenset(n.ref_id for n in self.nodes if n.kind == "i")

    @property
    def surplus_item_ids(self) -> frozenset[str]:
        """Items produced and not consumed.  A byproduct is never a demand."""
        return frozenset(n.ref_id for n in self.nodes if n.kind == "s")

    @property
    def output_item_ids(self) -> frozenset[str]:
        """Items the flow delivers to an objective."""
        return frozenset(n.ref_id for n in self.nodes if n.kind == "o")

    def machines(self, data: Dataset) -> dict[str, str]:
        """Recipe id -> the machine FactorioLab drew it in, where recoverable.

        ``buildGraph`` sets a recipe node's icon to the *machine's* icon when a
        machine is set and to the recipe's own icon otherwise, so ``icon.id`` is
        a machine id or a recipe id and there is no flag saying which.  Rather
        than guess, this accepts the value only when the dataset resolves it as
        a machine -- self-verifying, and simply empty when it cannot be
        established.  Used for reporting; the machine we build in comes from
        ``select_machine``.
        """
        out: dict[str, str] = {}
        for node in self.nodes:
            if node.kind not in _RECIPE_KINDS or not node.icon_id:
                continue
            if node.icon_id != node.ref_id and data.get_machine(node.icon_id) is not None:
                out[node.ref_id] = node.icon_id
        return out


def _node_id(raw: object, where: str) -> tuple[str, str]:
    if not isinstance(raw, str) or "|" not in raw:
        raise FlowFormatError(
            f"{where}: node id {raw!r} is not '<kind>|<id>'. FactorioLab writes "
            "'i|<item>', 'r|<recipe>', 'm|<recipe>', 's|<item>' or 'o|<item>'."
        )
    kind, _, ref = raw.partition("|")
    if kind not in _KINDS:
        raise FlowFormatError(
            f"{where}: node id {raw!r} has kind {kind!r}, which FactorioLab's "
            f"flow export does not emit. Known kinds are {sorted(_KINDS)}."
        )
    if not ref:
        raise FlowFormatError(f"{where}: node id {raw!r} names nothing after the '|'")
    return kind, ref


def _text(raw: object) -> str:
    return raw if isinstance(raw, str) else ""


def parse_flow_json(text: str) -> FlowSelection:
    """Parse a FactorioLab flow export.  Raises :class:`FlowFormatError`.

    Nothing here is lenient about structure.  A file whose shape is not the one
    documented above is refused rather than parsed as far as it goes: if the
    format has moved, every id read out of it is a guess, and a guessed recipe
    selection is exactly the silent wrong answer this module removes.
    """
    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FlowFormatError(f"not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise FlowFormatError(
            f"expected a JSON object with 'nodes' and 'links', got {type(raw).__name__}"
        )
    if not isinstance(raw.get("nodes"), list):
        raise FlowFormatError(
            "no 'nodes' array. FactorioLab's flow export is "
            '{"nodes": [...], "links": [...]}; this is a different file.'
        )

    nodes: list[FlowNode] = []
    for index, entry in enumerate(raw["nodes"]):
        where = f"nodes[{index}]"
        if not isinstance(entry, dict):
            raise FlowFormatError(f"{where} is not an object")
        kind, ref = _node_id(entry.get("id"), where)
        icon = entry.get("icon")
        nodes.append(
            FlowNode(
                kind=kind,
                ref_id=ref,
                text=_text(entry.get("text")),
                icon_id=_text(icon.get("id")) if isinstance(icon, dict) else "",
            )
        )

    links: list[tuple[str, str]] = []
    for index, entry in enumerate(raw.get("links") or []):
        where = f"links[{index}]"
        if not isinstance(entry, dict):
            raise FlowFormatError(f"{where} is not an object")
        _node_id(entry.get("source"), where)
        _node_id(entry.get("target"), where)
        links.append((str(entry["source"]), str(entry["target"])))

    selection = FlowSelection(nodes=tuple(nodes), links=tuple(links))
    if not selection.chosen_recipe_ids:
        raise FlowFormatError(
            "the export contains no recipe nodes, so it states no recipe "
            "selection and there is nothing to pin. Download the JSON from the "
            "flow view after it has finished solving."
        )
    return selection


def load_flow(path: Path) -> FlowSelection:
    """Read and parse a FactorioLab flow export."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FlowFormatError(f"cannot read flow export {str(path)!r}: {exc}") from exc
    return parse_flow_json(text)


def pinned_exclusions(data: Dataset, flow: FlowSelection) -> frozenset[str]:
    """Every recipe in the dataset that FactorioLab's flow does NOT run.

    This is the pin, expressed in the one vocabulary the rate solver already
    treats as authoritative.  ``solve._excluded_recipes`` takes the request's
    exclusion set whole and ``_buildable_producers`` then offers the MILP only
    what survives, so excluding the complement of the chosen set leaves exactly
    one producer per item: FactorioLab's.
    """
    chosen = flow.chosen_recipe_ids
    known = {r.id for r in data.recipes}
    unknown = sorted(chosen - known)
    if unknown:
        raise FlowSelectionError(
            f"the flow runs {unknown!r}, which this dataset does not define. "
            "Either the export came from a different mod, or our vendored "
            "dataset is older than FactorioLab's."
        )
    return frozenset(known - chosen)


def verify_against_request(flow: FlowSelection, data: Dataset, request: LabRequest) -> None:
    """Establish, as far as the file allows, that this flow is the URL's flow.

    **The JSON export carries no URL.**  The CSV export's first line is
    ``window.location.href``; ``flowToJson`` writes the graph and nothing else.
    So the direct provenance check -- "this file says it came from a different
    address" -- is not available here, and what follows is a structural
    substitute.

    What it catches:

    * a flow running a recipe the URL's own settings **forbid**, which is what a
      stale export looks like after the player toggles a recipe off;
    * a flow that cannot make what the URL **asks for**, which is what a stale
      export looks like after the player changes the objective;
    * a flow that **builds** an item the URL declares as an ``Input``, i.e. one
      the player supplies from outside.

    What it cannot catch: any settings change that leaves the recipe selection
    intact -- a different belt, a different machine rank, a different objective
    *rate*.  Those alter the blueprint without altering this file, and no check
    on this file can see them.  The CSV export is the one that carries the URL.
    """
    chosen = flow.chosen_recipe_ids
    # Only an EXPLICIT exclusion set can contradict the flow.  Absence is not
    # emptiness: a URL that says nothing about recipes leaves us falling back to
    # the mod's defaults, and those are our guess at the player's state, not the
    # player's state.  The flow export IS that state, so it outranks the
    # defaults -- and it must, since `graphene-advanced` and `fire-ice-vein` are
    # both default-excluded in DSP and both are ordinary player choices.
    # Checking against the defaults here re-created `60d5f0f` exactly: our
    # defaults overruling a selection the player had made.
    if request.excluded_recipe_ids is not None:
        forbidden = sorted(chosen & frozenset(request.excluded_recipe_ids))
        if forbidden:
            raise FlowProvenanceError(
                f"the flow runs {forbidden!r}, which this URL's own settings "
                "exclude. The export is stale or came from different settings; "
                "re-download it from the URL you are building."
            )

    producible = {
        item
        for recipe_id in chosen
        if (recipe := data.get_recipe(recipe_id)) is not None and not recipe.is_technology
        for item in recipe.outputs
    }
    wanted = {
        o.target_id
        for o in request.objectives
        if o.type is ObjectiveType.Output and not o.is_recipe_objective
    }
    unreachable = sorted(wanted - producible)
    if unreachable:
        raise FlowProvenanceError(
            f"this URL asks for {unreachable!r}, which the flow does not produce. "
            "The export is for a different objective; re-download it from the URL "
            "you are building."
        )

    supplied = {
        o.target_id
        for o in request.objectives
        if o.type is ObjectiveType.Input and not o.is_recipe_objective
    }
    contradicted = sorted(supplied & producible)
    if contradicted:
        raise FlowProvenanceError(
            f"this URL supplies {contradicted!r} from outside, but the flow builds "
            "it. The export predates that Input objective; re-download it."
        )


def pin_request(request: LabRequest, data: Dataset, flow: FlowSelection) -> LabRequest:
    """Return ``request`` with the recipe selection pinned to ``flow``.

    Verifies first: a flow that cannot be this URL's is refused rather than
    pinned, because pinning it would produce a blueprint that is internally
    consistent and answers the wrong question.
    """
    verify_against_request(flow, data, request)
    return replace(request, excluded_recipe_ids=set(pinned_exclusions(data, flow)))


def compare_selection(
    flow: FlowSelection,
    data: Dataset,
    *,
    built: Mapping[str, str],
) -> tuple[str, ...]:
    """Name every way our build's recipe set differs from FactorioLab's.

    ``built`` maps recipe id to the machine item id we chose.  With the request
    pinned this should return nothing, so anything it does return is a leak in
    the pin and is worth reporting rather than absorbing.

    Machine *counts* are deliberately not compared.  The export carries them
    only as rounded display text, and a check against a rounded number either
    passes vacuously or raises a false alarm -- neither is worth having.  The
    machine *choice* is compared where the export makes it recoverable.
    """
    findings: list[str] = []
    chosen = flow.chosen_recipe_ids
    for recipe_id in sorted(set(built) - chosen):
        findings.append(f"{recipe_id}: we build it; the flow does not run it")
    for recipe_id in sorted(chosen - set(built)):
        recipe = data.get_recipe(recipe_id)
        if recipe is not None and (recipe.is_mining or recipe.is_technology):
            continue  # extraction happens outside; its output is an input belt
        findings.append(f"{recipe_id}: the flow runs it; we build none")
    drawn = flow.machines(data)
    for recipe_id, machine_id in sorted(built.items()):
        want = drawn.get(recipe_id)
        if want is not None and want != machine_id:
            findings.append(f"{recipe_id}: built in {machine_id!r} here, {want!r} in the flow")
    return tuple(findings)
