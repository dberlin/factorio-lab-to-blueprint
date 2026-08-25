import { expect, rstest, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import type { Blueprint, BlueprintBuilding } from '../../src/format';
import type { BeltRun } from '../../src/model/beltGraph';
import { buildCatalog } from '../../src/model/catalog';
import type { SceneModel } from '../../src/model/layout';
import { InfoPanel } from '../../src/ui/InfoPanel';

// tests/ui/InfoPanel.test.tsx exercises the real BlueprintProvider end to
// end, parsing an actual BLUEPRINT: fixture. Reaching a station whose raw
// parameter block populates two named storage slots needs a hand-built
// 2048-word array (mirroring tests/model/params.test.ts's station
// fixtures), which is impractical to hand-encode into a real blueprint
// string. So this file mocks useBlueprint directly -- the same pattern as
// tests/ui/BomPanel.coverage.test.tsx and tests/ui/Toolbar.test.tsx.
let current: {
  blueprint: Blueprint | null;
  catalog: ReturnType<typeof buildCatalog>;
  selectedIndex: number | null;
  sceneModel: SceneModel | null;
};

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => current,
}));

const catalog = buildCatalog({
  items: [
    {
      id: 2104,
      name: 'Interstellar Logistics Station',
      iconName: 'ils',
      gridIndex: 1,
      modelIndex: 50,
      canBuild: true,
      color: 0x6f9fd8,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-ingot',
      gridIndex: 2,
      modelIndex: 0,
      canBuild: false,
      color: 0xb0a08c,
    },
  ],
  models: {
    '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
  },
  recipes: [],
});

function station(parameters: number[]): BlueprintBuilding {
  return {
    index: 0,
    areaIndex: 0,
    itemId: 2104,
    modelIndex: 50,
    x: 0,
    y: 0,
    z: 0,
    x2: 0,
    y2: 0,
    z2: 0,
    yaw: 0,
    yaw2: 0,
    tilt: 0,
    tilt2: 0,
    pitch: 0,
    pitch2: 0,
    outputObjIdx: -1,
    inputObjIdx: -1,
    outputToSlot: 0,
    inputFromSlot: 0,
    outputFromSlot: 0,
    inputToSlot: 0,
    outputOffset: 0,
    inputOffset: 0,
    recipeId: 0,
    filterId: 0,
    parameters,
    content: null,
  };
}

test('renders every decoded parameter row, including repeats of a kind', () => {
  // Two station storage slots produce two distinct labelled rows; keying by
  // label alone would collide if the decoder ever emitted duplicates.
  const p = new Array(2048).fill(0);
  p[0] = 1101; // slot 1 item
  p[1] = 1; // slot 1 localLogic: supply
  p[3] = 100; // slot 1 max
  p[6] = 1101; // slot 2 item
  p[7] = 1; // slot 2 localLogic: supply
  p[9] = 200; // slot 2 max

  current = {
    blueprint: { buildings: [station(p)] } as unknown as Blueprint,
    catalog,
    selectedIndex: 0,
    sceneModel: null,
  };

  render(<InfoPanel />);
  const panel = screen.getByTestId('info');
  expect(panel.textContent).toContain('Supplies 1');
  expect(panel.textContent).toContain('Supplies 2');
});

function belt(index: number): BlueprintBuilding {
  return {
    index,
    areaIndex: 0,
    itemId: 2001,
    modelIndex: 35,
    x: 0,
    y: 0,
    z: 0,
    x2: 0,
    y2: 0,
    z2: 0,
    yaw: 0,
    yaw2: 0,
    tilt: 0,
    tilt2: 0,
    pitch: 0,
    pitch2: 0,
    outputObjIdx: -1,
    inputObjIdx: -1,
    outputToSlot: 0,
    inputFromSlot: 0,
    outputFromSlot: 0,
    inputToSlot: 0,
    outputOffset: 0,
    inputOffset: 0,
    recipeId: 0,
    filterId: 0,
    parameters: [],
    content: null,
  };
}

test('an inferred row is marked as inferred in the panel', () => {
  const runs: BeltRun[] = [
    {
      belts: [0],
      freeInput: true,
      freeOutput: true,
      cyclic: false,
      carried: [1101],
      hasExplicitTag: false,
    },
  ];

  current = {
    blueprint: { buildings: [belt(0)] } as unknown as Blueprint,
    catalog,
    selectedIndex: 0,
    sceneModel: { beltRuns: runs } as unknown as SceneModel,
  };

  render(<InfoPanel />);
  const dd = screen.getByText('Iron Ingot').closest('dd');
  expect(dd?.className).toContain('inferred');
  expect(dd?.textContent).toContain('(inferred)');
});
