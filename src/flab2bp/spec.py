"""The frozen boundary between rate reasoning and geometry.

Everything upstream of this module is arithmetic on rationals with no notion of
space.  Everything downstream is geometry with no notion of rates.  ``BuildSpec``
is the only thing that crosses.

These are pydantic models rather than dataclasses, deliberately and only here.
A ``BuildSpec`` is built three or four times per run, so validation is free; the
geometry types it feeds are built ~9,000 times per layout call and stay as
``slots=True`` dataclasses for that reason.  What pydantic buys is enforcement of
the invariants this docstring used to merely assert -- notably that no machine
demands an item nothing supplies, which was documented and unchecked.

``Fraction`` is supported natively and exactly (``"16.5"`` parses to ``33/2``,
not a float), so the exactness guarantee survives the boundary.
"""

from __future__ import annotations

from enum import StrEnum
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, Field, model_validator

# `layout.base` imports only the standard library at runtime -- `BuildSpec`
# itself is under TYPE_CHECKING there -- so this is not a cycle.  The refusal
# `planning_stack` raises is a LAYOUT refusal (design 5.3) and must be the same
# exception every other layout refusal is, or the pipeline would report it
# differently for no reason a user could see.
from flab2bp.layout.base import NoValidLayout


class ProliferatorMode(StrEnum):
    """How a recipe's inputs are sprayed, if at all.

    Spray is applied to items *on a belt* by a Spray Coater and does not survive
    crafting, so a proliferated recipe requires its own inputs to arrive belted.
    That makes proliferation and direct insertion mutually exclusive on any given
    edge -- the single most important interaction in the layout stage.
    """

    NONE = "none"
    #: Extra products.  Gated by the dataset's ``limitations.productivity``
    #: whitelist, so it is not legal for every recipe.  Compounds upstream: more
    #: output per craft means less input demand all the way down the chain.
    PRODUCTS = "products"
    #: Production speedup.  Always legal.  Cuts machines at this step only.
    SPEED = "speed"


#: The largest cargo stack DSP will ever put on a belt, and so the ceiling on
#: every stack this module carries.  It is ``dsp.catalog.PILER_MAX_STACK``,
#: pinned from ``Assembly-CSharp`` (``PilerComponent.cs:195-207``).  Spelt out
#: here rather than imported because this module is the rates/geometry boundary
#: and deliberately imports nothing from ``flab2bp``; ``tests/test_spec.py``
#: asserts the two are equal, so drift is a failing test, not a silent lie.
MAX_CARGO_STACK = 4

#: The stacks one or more Automatic Pilers in series can reach from an
#: unstacked lane.  A piler DOUBLES its input, capped at ``MAX_CARGO_STACK``
#: (``catalog.PILER_SINGLE_PASS`` is False: the Pile branch merges at most the
#: two cargos it has cached), so 3 is NOT reachable and must never be planned
#: as a piler target.  ``layout/piling.py`` imports this rather than
#: redefining it, so the merge tree and the plan cannot disagree.
PILER_LADDER = (1, 2, 4)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BeltTier(_Frozen):
    """One belt the build may use, by FactorioLab id and throughput."""

    item_id: str
    items_per_second: Fraction = Field(gt=0)


class MachineGroup(_Frozen):
    """``count`` machines all running ``recipe_id`` under the same settings."""

    recipe_id: str
    machine_item_id: str
    count: int = Field(gt=0)
    proliferator_mode: ProliferatorMode = ProliferatorMode.NONE
    #: Items per second one machine of this group consumes, by item id.
    inputs_per_machine: dict[str, Fraction] = Field(default_factory=dict)
    #: Items per second one machine of this group produces, by item id.
    outputs_per_machine: dict[str, Fraction] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _rates_are_positive(self) -> MachineGroup:
        for label, rates in (
            ("inputs_per_machine", self.inputs_per_machine),
            ("outputs_per_machine", self.outputs_per_machine),
        ):
            for item, rate in rates.items():
                if rate <= 0:
                    raise ValueError(
                        f"{self.recipe_id}: {label}[{item!r}] is {rate}; a rate of zero or "
                        "less is a bug upstream, not a machine that consumes nothing"
                    )
        return self

    @property
    def is_proliferated(self) -> bool:
        return self.proliferator_mode is not ProliferatorMode.NONE


class CoproductBufferProof(_Frozen):
    """A game-backed finite buffer that enables one atomic consumer batch."""

    item_id: str
    producer_recipe_id: str
    consumer_recipe_id: str
    producer_batch: Fraction = Field(gt=0)
    consumer_batch: Fraction = Field(gt=0)
    required_capacity: Fraction = Field(gt=0)
    intrinsic_capacity: Fraction = Field(gt=0)


class BuildSpec(_Frozen):
    """One complete, self-consistent thing to build.

    Invariants enforced at construction:

    * ``count`` is a positive integer -- rounding up already happened, so the
      build over-produces slightly rather than missing the objective.
    * All rates are positive exact ``Fraction``s.  No float ever reaches geometry.
    * Every item consumed by some group is either produced by another group or
      appears in ``external_inputs``.  There are no dangling demands.

    That last check runs only when the spec claims to be complete, i.e. it
    declares external inputs or outputs.  A spec with neither is a fragment --
    hand-built test material for the layout stage -- and is left alone.
    """

    groups: tuple[MachineGroup, ...]
    #: Items belted in at the boundary -- ores, water, oil, proliferator.
    external_inputs: dict[str, Fraction] = Field(default_factory=dict)
    #: The target item(s) belted out, at the achieved rate.
    outputs: dict[str, Fraction] = Field(default_factory=dict)
    #: Unavoidable non-target production that must also leave the block.
    surplus_outputs: dict[str, Fraction] = Field(default_factory=dict)
    #: The belt FactorioLab chose (``ibe``).  The FLOOR: no emitted belt is
    #: ever slower, and a run that fits it keeps it.
    belt_item_id: str = "conveyor-belt-1"
    belt_items_per_second: Fraction = Field(default=Fraction(6), gt=0)
    #: Faster belts the save can build, slowest first.  Empty means the floor
    #: is also the ceiling -- what every hand-built spec gets.  The layout
    #: sizes lanes against the fastest of these and raises a run to the
    #: cheapest one that carries its measured demand; see
    #: ``layout/belt_tiers.py``.
    belt_upgrades: tuple[BeltTier, ...] = ()
    #: Sorter tiers the save can build, slowest first.  Every tier by default
    #: so a spec built without a request keeps today's behaviour.
    sorter_item_ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4")
    #: FactorioLab's belt stack (``ist``): the cargo stack the player's bus
    #: carries.  1 when the URL says nothing.  Never above 4, the game's
    #: largest pile (``catalog.PILER_MAX_STACK``).
    belt_stack: int = Field(default=1, ge=1, le=MAX_CARGO_STACK)
    #: Largest stack each sorter TIER can PICK off a belt and PLACE onto one,
    #: aligned with ``sorter_item_ids``.  Never per item: DSP decides a stack
    #: from the sorter's grade and the researched Pile Sorter Upgrade level.
    #: The defaults are that table's level-0 row -- Sorter Mk.I to Mk.III at 1
    #: forever, an unresearched Pile Sorter picking 2 and placing 1.  They only
    #: matter when ``belt_stack > 1``: every stack the planner and validator
    #: derive is 1 when the URL does not stack (design rule 1), so a hand-built
    #: spec behaves as today.
    sorter_pick_stacks: tuple[int, ...] = (1, 1, 1, 2)
    sorter_place_stacks: tuple[int, ...] = (1, 1, 1, 1)
    #: Whether the save can build an Automatic Piler.  The same technology
    #: (``integrated-logistics-system``) unlocks the piler and the Pile Sorter,
    #: so this is False exactly when nothing in the save stacks at all.
    piler_unlocked: bool = False
    #: What this candidate optimises, for the bake-off report.
    label: str = ""

    #: ``(producer_recipe_id, consumer_recipe_id)`` edges that MUST travel on a
    #: belt because the consumer is proliferated and spray is applied by a
    #: belt-mounted coater.  This is the only channel through which the
    #: proliferation decision constrains geometry, and it is a correctness
    #: constraint, not a hint: direct-inserting one of these edges yields a
    #: blueprint that pastes cleanly and then silently under-produces.
    belt_required_edges: frozenset[tuple[str, str]] = Field(default_factory=frozenset)

    #: Lanes needing a Spray Coater, by the item they carry. ``True`` marks a
    #: lane that exists anyway, such as an external input belt.
    spray_lanes: dict[str, bool] = Field(default_factory=dict)

    #: Items whose lane must be physically SPLIT in two, because the same item
    #: feeds both a proliferated and an unproliferated consumer. Spraying a
    #: shared lane would proliferate the unproliferated consumer's input too,
    #: silently over-producing it and desyncing the build from these rates.
    lanes_requiring_split: frozenset[str] = Field(default_factory=frozenset)

    #: Startup-liveness certificates derived from exact recipe batches and the
    #: selected machine's game-defined internal output capacity.
    coproduct_buffer_proofs: tuple[CoproductBufferProof, ...] = ()

    @model_validator(mode="after")
    def _tiers_are_ordered(self) -> BuildSpec:
        previous = self.belt_items_per_second
        for tier in self.belt_upgrades:
            if tier.items_per_second <= previous:
                raise ValueError(
                    f"{self.label or 'spec'}: belt upgrade {tier.item_id!r} at "
                    f"{tier.items_per_second}/s is not faster than the tier before it "
                    f"({previous}/s); upgrades must be strictly faster than the floor "
                    "and listed slowest first"
                )
            previous = tier.items_per_second
        if not self.sorter_item_ids:
            raise ValueError(
                f"{self.label or 'spec'}: no sorter tier is allowed; a build with no "
                "sorter at all cannot feed a machine"
            )
        return self

    @model_validator(mode="after")
    def _stacks_align(self) -> BuildSpec:
        """A stack tuple is a value PER TIER, so it is as long as the tiers.

        A save without the Pile Sorter has three tiers, not four, so nothing
        downstream may index these by a hard-coded tier number -- only by
        position within ``sorter_item_ids`` or by ``[-1]`` for the fastest.
        A mismatch here would silently mis-attribute one tier's stack to
        another, which produces a plan that pastes and under-produces.
        """
        tiers = len(self.sorter_item_ids)
        for name, stacks in (
            ("sorter_pick_stacks", self.sorter_pick_stacks),
            ("sorter_place_stacks", self.sorter_place_stacks),
        ):
            if len(stacks) != tiers:
                raise ValueError(
                    f"{self.label or 'spec'}: {name} has {len(stacks)} entries but "
                    f"there are {tiers} sorter tiers {list(self.sorter_item_ids)}; "
                    "a stack is a value per tier and is read by position"
                )
            for stack in stacks:
                if not 1 <= stack <= MAX_CARGO_STACK:
                    raise ValueError(
                        f"{self.label or 'spec'}: {name} entry {stack} is outside "
                        f"1..{MAX_CARGO_STACK}; a cargo holds at least one item and "
                        "never more than the game's largest pile"
                    )
        return self

    @model_validator(mode="after")
    def _no_dangling_demand(self) -> BuildSpec:
        if not self.external_inputs and not self.outputs:
            return self  # a fragment, not a claim of completeness
        produced = {item for g in self.groups for item in g.outputs_per_machine}
        supplied = produced | set(self.external_inputs)
        missing = {
            item
            for g in self.groups
            for item in g.inputs_per_machine
            if item not in supplied
        }
        if missing:
            raise ValueError(
                f"{self.label or 'spec'}: nothing supplies {sorted(missing)}. Every "
                "consumed item must be produced by a group or listed in "
                "external_inputs, or the build starves on paste."
            )
        return self

    @model_validator(mode="after")
    def _spraying_needs_proliferator(self) -> BuildSpec:
        """Spraying without a proliferator supply is an unsatisfiable spec.

        Spray is applied by a belt-mounted Spray Coater, and a coater consumes
        proliferator like any other machine consumes an ingredient.  Proliferator
        is never produced inside the block, so it has to arrive on an input belt
        -- which is exactly the rule the user set at the outset: any
        proliferation must take proliferator as input.

        Caught here rather than in a layout strategy because it is the same
        class as ``_no_dangling_demand`` above: a demand nothing supplies. A
        strategy asked to satisfy it can only emit coaters that never spray,
        which pastes cleanly and then quietly under-produces every sprayed
        recipe -- and it did, until ``lay_out`` began checking its own work and
        turned it into a refusal nobody could explain.
        """
        if not self.spray_lanes:
            return self
        if not any(i.startswith("proliferator") for i in self.external_inputs):
            raise ValueError(
                f"{self.label or 'spec'}: sprays {sorted(self.spray_lanes)} but no "
                "proliferator is listed in external_inputs. Spray comes from a "
                "belt-mounted Spray Coater, which has to be fed like any other "
                "machine, and proliferator is never made inside the block."
            )
        return self

    @property
    def machine_count(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def is_proliferated(self) -> bool:
        return any(g.is_proliferated for g in self.groups)

    @property
    def belt_tiers(self) -> tuple[BeltTier, ...]:
        """Every belt the build may use, floor first."""
        floor = BeltTier(item_id=self.belt_item_id, items_per_second=self.belt_items_per_second)
        return (floor, *self.belt_upgrades)

    @property
    def lane_capacity(self) -> Fraction:
        """Items/second the fastest allowed belt sustains: the planner's bound."""
        if self.belt_upgrades:
            return self.belt_upgrades[-1].items_per_second
        return self.belt_items_per_second

    @property
    def max_stack(self) -> int:
        """The largest stack any lane may be planned at.

        4 with a piler, else what the save's sorters can PLACE.  A piler
        reaches 4 from any belt, but not in one pass -- ``PILER_SINGLE_PASS``
        is False, so a lane coming off an unstacked belt needs two in series.
        That is Deliverable C's cost, not a lower ceiling: this is the ceiling.
        """
        if self.piler_unlocked:
            return MAX_CARGO_STACK
        return max(self.sorter_place_stacks)

    def planning_stack(self, item: str, *, external: bool | None = None) -> int:
        """The cargo stack the planner may assume for a lane of ``item`` (design 5.3).

        1 when the URL does not stack, so an ``ist=1`` save -- which is every
        corpus URL -- is planned exactly as it was before any of this existed.

        An external input arrives at the bus stack whatever the consumer can do
        about it; a produced item leaves at what the fastest allowed sorter
        PLACES.  Either is REFUSED, never lowered, when that same sorter cannot
        pick it: a lowered plan would still be fed the stacked belt and would
        starve on a lane it thought was smaller.  A produced lane may then be
        RAISED by pilers, but only along :data:`PILER_LADDER` and only as far
        as the sink can pick, because piling is elective and a piler doubles.

        ``external`` overrides the spec's own classification when the caller
        knows better -- a boundary OUTPUT lane is "produced" even for an item
        the spec also belts in.
        """
        if self.belt_stack == 1:
            return 1
        is_external = item in self.external_inputs if external is None else external
        # The fastest allowed tier's row is the ceiling of what ANY tier can
        # promise; with the game's table that tier is the Pile Sorter whenever
        # anything stacks at all, and every slower tier is 1 at every level.
        pick = self.sorter_pick_stacks[-1]
        place = self.sorter_place_stacks[-1]
        if is_external:
            stack = self.belt_stack
            if any(item in group.outputs_per_machine for group in self.groups):
                # Fed from the bus AND from an internal producer
                # (universe-matrix's hydrogen is the corpus case): the lane also
                # carries what the producer's sorter places, and a merge is
                # judged at its minimum (design 5.5), so plan the smaller.
                stack = min(stack, place)
        else:
            stack = place
        if stack > pick:
            # Name research the player can actually reach.  `pile-sorter-1`'s
            # only prerequisite IS `integrated-logistics-system`, so telling a
            # save with no Pile Sorter to research the upgrade ladder is dead
            # advice; it needs the unlock first.
            missing = (
                "research Integrated Logistics System to unlock the Pile Sorter"
                if "sorter-4" not in self.sorter_item_ids
                else "research Pile Sorter Upgrade (the Sorter Cargo Stacking ladder is "
                "obsolete and grants nothing)"
            )
            raise NoValidLayout(
                f"{self.label or 'spec'}: {item!r} travels at stack {stack} but the fastest "
                f"sorter this save can build ({self.sorter_item_ids[-1]}) can pick only "
                f"{pick}; {missing}, or lower the URL's belt stack",
                spec_label=self.label,
                budget_s=0.0,
                attempt_reasons=(),
                attempt_failures=(),
                projection_failures=(),
            )
        if not is_external and self.piler_unlocked:
            # Elective, so it only ever RAISES: a lane already above every rung
            # the sink can pick keeps what its sorter placed.
            reachable = max(rung for rung in PILER_LADDER if rung <= min(self.max_stack, pick))
            stack = max(stack, reachable)
        return stack


class BuildSpecSet(_Frozen):
    """Several valid ways to build the same objective.

    Proliferation trades against direct insertion in a way the rate stage cannot
    see, because the cost is spatial.  Rather than guess, the rate stage emits
    candidates and the layout stage lays out each and keeps the smallest.
    """

    candidates: tuple[BuildSpec, ...] = Field(min_length=1)
