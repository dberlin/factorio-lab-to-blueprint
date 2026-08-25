import { expect, rstest, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import type { Blueprint } from '../../src/format';
import { buildCatalog } from '../../src/model/catalog';
import { BomPanel } from '../../src/ui/BomPanel';

// BomPanel.test.tsx builds a catalog with `recipes: []`, so
// `catalog.recipesProducing()` always returns [] and `computeBom`'s `expand()`
// takes the "raw" branch immediately for every building. That leaves
// `rawMaterials` and `assumedRecipes` — and the JSX branches that render
// them — completely unexercised. These tests close that gap by mocking
// `useBlueprint` directly (the same pattern as
// tests/scene/canvas-resize.test.tsx) so we can hand a real recipe graph to
// BomPanel without needing to hand-encode a `BLUEPRINT:` string.
let current: { blueprint: Blueprint | null; catalog: ReturnType<typeof buildCatalog> };

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => current,
}));

const bp = (buildings: Array<{ itemId: number }>): Blueprint =>
  ({ buildings }) as unknown as Blueprint;

// Iron Ore -> Iron Ingot -> Gear -> Assembler, mirroring the recipe graph in
// tests/model/bom.test.ts. Every item here has exactly one producing recipe
// (or none, for the raw ore), so this catalog alone should never surface the
// assumed-recipe note.
const noAlternativesCatalog = buildCatalog({
  items: [
    {
      id: 1001,
      name: 'Iron Ore',
      iconName: 'iron-ore',
      gridIndex: 1,
      modelIndex: 0,
      canBuild: false,
      color: 1,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      gridIndex: 2,
      modelIndex: 0,
      canBuild: false,
      color: 2,
    },
    {
      id: 1201,
      name: 'Gear',
      iconName: 'gear',
      gridIndex: 3,
      modelIndex: 0,
      canBuild: false,
      color: 3,
    },
    {
      id: 2303,
      name: 'Assembler',
      iconName: 'assembler-1',
      gridIndex: 4,
      modelIndex: 65,
      canBuild: true,
      color: 4,
    },
  ],
  models: { '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] } },
  recipes: [
    {
      id: 1,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 2,
      name: 'Gear',
      iconName: 'gear',
      items: [1101],
      itemCounts: [1],
      results: [1201],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 3,
      name: 'Assembler',
      iconName: 'assembler-1',
      items: [1101, 1201],
      itemCounts: [4, 8],
      results: [2303],
      resultCounts: [1],
      timeSpend: 120,
    },
  ],
});

// Same graph, but Gear has a second producing recipe (id 9, lowest id 2
// still wins), so exactly one item — Gear — has alternatives.
const oneAlternativeCatalog = buildCatalog({
  items: noAlternativesCatalog.allItems(),
  models: { '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] } },
  recipes: [
    {
      id: 1,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 2,
      name: 'Gear',
      iconName: 'gear',
      items: [1101],
      itemCounts: [1],
      results: [1201],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 9,
      name: 'Gear (alt)',
      iconName: 'gear',
      items: [1101],
      itemCounts: [2],
      results: [1201],
      resultCounts: [3],
      timeSpend: 30,
    },
    {
      id: 3,
      name: 'Assembler',
      iconName: 'assembler-1',
      items: [1101, 1201],
      itemCounts: [4, 8],
      results: [2303],
      resultCounts: [1],
      timeSpend: 120,
    },
  ],
});

test('renders the raw materials section with a hand-computed total', () => {
  // 1 Assembler directly needs 4 Iron Ingot + 8 Gear.
  // Each Gear needs 1 Iron Ingot (recipe id 2) -> 8 Gear = +8 Iron Ingot.
  // Total Iron Ingot = 4 + 8 = 12.
  // Each Iron Ingot needs 1 Iron Ore (recipe id 1) -> 12 Iron Ingot = 12 Iron Ore.
  current = { blueprint: bp([{ itemId: 2303 }]), catalog: noAlternativesCatalog };

  render(<BomPanel />);
  const panel = screen.getByTestId('bom');
  expect(panel).toHaveTextContent('Raw materials');
  expect(panel).toHaveTextContent('Iron Ore');
  expect(panel).toHaveTextContent('12');
});

test('shows the assumed-recipe note when an item has more than one producing recipe', () => {
  current = { blueprint: bp([{ itemId: 2303 }]), catalog: oneAlternativeCatalog };

  render(<BomPanel />);
  const panel = screen.getByTestId('bom');
  expect(panel).toHaveTextContent(
    'Raw cost assumes the default recipe for 1 item(s) that have alternatives.',
  );
});

test('omits the assumed-recipe note when no item has alternatives', () => {
  current = { blueprint: bp([{ itemId: 2303 }]), catalog: noAlternativesCatalog };

  render(<BomPanel />);
  const panel = screen.getByTestId('bom');
  expect(panel.querySelector('.note')).toBeNull();
  expect(screen.queryByText(/assumes the default recipe/)).toBeNull();
});
