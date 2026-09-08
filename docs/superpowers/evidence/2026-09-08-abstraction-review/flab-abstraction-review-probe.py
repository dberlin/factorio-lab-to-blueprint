import json
from fractions import Fraction
from types import SimpleNamespace
from flab2bp.dsp import catalog
from flab2bp.layout import freeform, markers, validate
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.buildings import MutableBuildings
from flab2bp.layout.hierarchy.contracts import boundary_lanes
from flab2bp.spec import BuildSpec


def building(name, x, **kwargs):
    item_id = catalog.item_id(name)
    return PlacedBuilding(item_id=item_id, model_index=catalog.building(item_id).model_index, x=x, y=0, **kwargs)


# Real emitted link convention: the piler is named by incoming.output_obj
# and outgoing.input_obj; the piler itself has no forward output_obj.
chain = Placement(buildings=(
    building('assembling-machine-1', 0, recipe_id=1),
    building('sorter-1', 1, input_obj=0, output_obj=2, carries_item='gear'),
    building('conveyor-belt-1', 2, output_obj=3, carries_item='gear'),
    building('automatic-piler', 3),
    building('conveyor-belt-1', 4, input_obj=3, carries_item='gear'),
))
spec = BuildSpec(groups=(), outputs={'gear': Fraction(1)})
tails, heads = boundary_lanes(chain, spec, 0)

cycle = Placement(buildings=(
    building('conveyor-belt-1', 0, output_obj=1, carries_item='gear'),
    building('automatic-piler', 1),
    building('conveyor-belt-1', 2, input_obj=1, output_obj=0, carries_item='gear'),
))
canvas = SimpleNamespace(buildings=MutableBuildings(cycle.buildings))
report = validate.validate(cycle, only=('belt.acyclic',), expect_power=False)
result = {
    'scope': 'logical transport graph fixtures, not physical paste validation',
    'boundary': {
        'expected_output_tail': 4,
        'marker_output_tails': markers.output_belt_tails(chain),
        'marker_input_heads': markers.input_belt_heads(chain),
        'hierarchy_output_tails': [tail.building for tail in tails],
        'hierarchy_input_heads': [head.building for head in heads],
    },
    'cycle': {
        'leads_back': freeform._leads_back(canvas, 0, {2}),
        'committed_path_closes_cycle': freeform._committed_path_closes_cycle(canvas, [0]),
        'validator_errors': [{'check': finding.check, 'message': finding.message} for finding in report.errors],
    },
}
assert result['boundary']['marker_output_tails'] == []
assert 4 in result['boundary']['marker_input_heads']
assert result['boundary']['hierarchy_output_tails'] == []
assert not result['cycle']['leads_back']
assert not result['cycle']['committed_path_closes_cycle']
assert any(f.check == 'belt.acyclic' for f in report.errors)
print(json.dumps(result, indent=2))
