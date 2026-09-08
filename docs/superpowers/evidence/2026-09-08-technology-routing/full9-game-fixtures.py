"""Extract actual regenerated coater neighborhoods for the shipped-method oracle."""
import hashlib
import json
from pathlib import Path

from flab2bp.dsp import catalog, codec
from flab2bp.layout import slots

EVIDENCE = Path(__file__).resolve().parent
text = (EVIDENCE / 'factory-full9-r1.blueprint.txt').read_text().strip()
blueprint = codec.decode(text)
assert blueprint.hash_valid
buildings = {building.index: building for building in blueprint.buildings}
belts = [building for building in blueprint.buildings if catalog.is_belt(building.item_id)]
by_cell = {}
predecessors = {}
for belt in belts:
    by_cell.setdefault((round(belt.x, 5), round(belt.y, 5), round(belt.z, 5)), []).append(belt)
    if belt.output_obj_idx >= 0:
        predecessors.setdefault(belt.output_obj_idx, []).append(belt)


def belt_at(cell):
    matches = by_cell.get(tuple(round(value, 5) for value in cell), ())
    if len(matches) != 1:
        raise RuntimeError(f'Expected one actual belt at {cell}, found {len(matches)}')
    return matches[0]


def position(building):
    return [building.x, building.y, building.z]


rows = []
for coater in blueprint.buildings:
    if coater.item_id != catalog.SPRAY_COATER_ID:
        continue
    x, y = round(coater.x), round(coater.y)
    assert (coater.x, coater.y) == (x, y)
    drop_cell = slots.addon_supply_cell(
        coater.item_id, x=x, y=y, z=round(coater.z), yaw=coater.yaw, area=1
    )
    drop = belt_at(drop_cell)
    incoming = predecessors.get(drop.index, ())
    if len(incoming) != 1 or drop.output_obj_idx >= 0:
        raise RuntimeError(f'Coater {coater.index} does not have one terminal supply predecessor')
    dx, dy = slots.to_world((0.0, 1.0), coater.yaw)
    exit_belt = belt_at((coater.x + 2 * dx, coater.y + 2 * dy, coater.z))
    exit_inputs = predecessors.get(exit_belt.index, ())
    if not exit_inputs or exit_belt.output_obj_idx not in buildings:
        raise RuntimeError(f'Coater {coater.index} has incomplete actual exit connectivity')
    for exit_input in exit_inputs:
        rows.append({
            'index': coater.index, 'dropIndex': drop.index, 'exitIndex': exit_belt.index,
            'coater': [*position(coater), coater.yaw], 'drop': position(drop),
            'approach': position(incoming[0]), 'exit': position(exit_belt),
            'exitInput': position(exit_input), 'exitOutput': position(buildings[exit_belt.output_obj_idx]),
        })
(EVIDENCE / 'full9-regenerated-game-fixtures-r1.json').write_text(json.dumps(rows, indent=2) + '\n')
metadata = {
    'blueprint_sha256': hashlib.sha256(text.encode()).hexdigest(),
    'hash_valid': blueprint.hash_valid, 'buildings': len(blueprint.buildings),
    'coaters': len({row['index'] for row in rows}), 'neighborhoods': len(rows),
    'scope': 'Actual regenerated adjacency, four equatorial rotations; not Unity Physics or live cursor',
}
(EVIDENCE / 'full9-regenerated-game-fixtures-r1.metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata))
