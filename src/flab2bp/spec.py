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


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
    belt_item_id: str = "conveyor-belt-1"
    belt_items_per_second: Fraction = Field(default=Fraction(6), gt=0)
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


class BuildSpecSet(_Frozen):
    """Several valid ways to build the same objective.

    Proliferation trades against direct insertion in a way the rate stage cannot
    see, because the cost is spatial.  Rather than guess, the rate stage emits
    candidates and the layout stage lays out each and keeps the smallest.
    """

    candidates: tuple[BuildSpec, ...] = Field(min_length=1)
