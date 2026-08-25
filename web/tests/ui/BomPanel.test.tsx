import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { BomPanel } from '../../src/ui/BomPanel';

const catalog = buildCatalog({
  items: [
    {
      id: 2001,
      name: 'Conveyor Belt Mk.I',
      iconName: 'belt-1',
      gridIndex: 1,
      modelIndex: 35,
      canBuild: true,
      color: 1,
    },
    {
      id: 2011,
      name: 'Sorter Mk.I',
      iconName: 'sorter-1',
      gridIndex: 2,
      modelIndex: 41,
      canBuild: true,
      color: 2,
    },
    {
      id: 2302,
      name: 'Arc Smelter',
      iconName: 'smelter',
      gridIndex: 3,
      modelIndex: 62,
      canBuild: true,
      color: 3,
    },
    {
      id: 2201,
      name: 'Tesla Tower',
      iconName: 'tesla',
      gridIndex: 4,
      modelIndex: 44,
      canBuild: true,
      color: 4,
    },
  ],
  models: {
    '35': { prefab: 'b', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
    '62': { prefab: 'm', size: [3.2, 3.8, 3.2], center: [0, 1.9, 0] },
    '44': { prefab: 't', size: [1.25, 6, 1.25], center: [0, 3, 0] },
  },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Harness() {
  api = useBlueprint();
  return <BomPanel />;
}

test('lists building counts for a real blueprint', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <Harness />
    </BlueprintProvider>,
  );
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));

  // This fixture is 16 belts, 11 sorters, 3 smelters, 2 tesla towers.
  const panel = screen.getByTestId('bom');
  expect(panel).toHaveTextContent('Conveyor Belt Mk.I');
  expect(panel).toHaveTextContent('16');
});

test('renders nothing with no blueprint loaded', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <BomPanel />
    </BlueprintProvider>,
  );
  expect(screen.queryByTestId('bom')).toBeNull();
});
