import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { InfoPanel } from '../../src/ui/InfoPanel';

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
  ],
  models: {
    '35': { prefab: 'b', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
    '62': { prefab: 'm', size: [3.2, 3.8, 3.2], center: [0, 1.9, 0] },
  },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Harness() {
  api = useBlueprint();
  return <InfoPanel />;
}

/**
 * Reads the <dd> that belongs to a given <dt>, so an assertion pins the value
 * a term actually renders rather than merely proving the static label exists.
 * (Matching on /yaw/i against the whole panel passes even if the rendered
 * angle is wrong, because the <dt>Yaw</dt> label is always present.)
 */
function valueFor(panel: HTMLElement, term: string): string {
  const dt = [...panel.querySelectorAll('dt')].find((n) => n.textContent?.trim() === term);
  if (!dt) throw new Error(`no <dt> labelled "${term}" in the info panel`);
  const dd = dt.nextElementSibling;
  if (dd?.tagName !== 'DD') throw new Error(`<dt>${term}</dt> is not followed by a <dd>`);
  return (dd.textContent ?? '').replace(/\s+/g, ' ').trim();
}

test('shows nothing until a building is selected', () => {
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
  expect(screen.queryByTestId('info')).toBeNull();
});

// Building 0 of the quick-start fixture, straight out of the parser:
//   itemId 2011, modelIndex 41, areaIndex 0
//   x 10.160543441772461, y 5.203408718109131, z -0.00037994611193425953
//   yaw 269.78863525390625
// InfoPanel rounds to 2dp, so those become 10.16 / 5.2 / 0 and 269.79.
// Catalog model 41 has size [1, 1, 1], so the footprint reads "1 × 1 × 1".
test('renders the selected building’s actual name, ids, position, yaw and footprint', () => {
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
  const first = api.blueprint!.buildings[0]!;
  act(() => api.select(first.index));

  const panel = screen.getByTestId('info');
  expect(panel.querySelector('h2')?.textContent).toBe('Sorter Mk.I');
  expect(valueFor(panel, 'Item / model')).toBe('2011 / 41');
  expect(valueFor(panel, 'Position')).toBe('10.16, 5.2, alt 0');
  expect(valueFor(panel, 'Yaw')).toBe('269.79°');
  expect(valueFor(panel, 'Area')).toBe('0');
  expect(valueFor(panel, 'Footprint')).toBe('1 × 1 × 1');
});

// The parameter rows are describeParameters' output; this pins that they reach
// the DOM as real dt/dd pairs, not just that the panel mentions a number.
test('renders describeParameters rows with their values', () => {
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
  const smelter = api.blueprint!.buildings.find((b) => b.itemId === 2302 && b.recipeId > 0);
  if (!smelter) throw new Error('fixture no longer contains an Arc Smelter with a recipe');
  act(() => api.select(smelter.index));

  const panel = screen.getByTestId('info');
  expect(panel.querySelector('h2')?.textContent).toBe('Arc Smelter');
  // Catalog model 62 is the smelter box: size [3.2, 3.8, 3.2].
  expect(valueFor(panel, 'Footprint')).toBe('3.2 × 3.8 × 3.2');
  // No recipes in this test catalog, so the id degrades to "#<id>" -- which is
  // exactly the row describeParameters is meant to emit.
  expect(valueFor(panel, 'Recipe')).toBe(`#${smelter.recipeId}`);
});
