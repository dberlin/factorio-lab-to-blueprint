import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';

const catalog = buildCatalog({
  items: [
    {
      id: 2001,
      name: 'Belt',
      iconName: 'belt-1',
      gridIndex: 1,
      modelIndex: 35,
      canBuild: true,
      color: 1,
    },
  ],
  models: { '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] } },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Probe() {
  api = useBlueprint();
  return (
    <div>
      <span data-testid="count">{api.blueprint?.buildings.length ?? -1}</span>
      <span data-testid="error">{api.error ?? ''}</span>
      <span data-testid="selected">{api.selectedIndex ?? -1}</span>
    </div>
  );
}

const renderProvider = () =>
  render(
    <BlueprintProvider catalog={catalog}>
      <Probe />
    </BlueprintProvider>,
  );

test('starts empty', () => {
  renderProvider();
  expect(screen.getByTestId('count')).toHaveTextContent('-1');
});

test('loads a real blueprint and derives a scene model', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));
  expect(screen.getByTestId('count')).toHaveTextContent('36');
  expect(api.sceneModel).not.toBeNull();
  expect(api.error).toBeNull();
});

test('surfaces a parse failure as a message instead of throwing', () => {
  renderProvider();
  act(() => api.load('not a blueprint'));
  expect(screen.getByTestId('error')).not.toHaveTextContent('');
  expect(api.blueprint).toBeNull();
});

test('selection is tracked and cleared when a new blueprint loads', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));
  act(() => api.select(3));
  expect(screen.getByTestId('selected')).toHaveTextContent('3');
  act(() => api.load(text));
  expect(screen.getByTestId('selected')).toHaveTextContent('-1');
});

test('a failed load after a successful one clears the stale blueprint, scene model, and selection', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));
  act(() => api.select(3));
  expect(api.blueprint).not.toBeNull();
  expect(api.sceneModel).not.toBeNull();

  act(() => api.load('not a blueprint'));

  expect(api.error).not.toBeNull();
  expect(api.blueprint).toBeNull();
  expect(api.sceneModel).toBeNull();
  expect(api.selectedIndex).toBeNull();
});

test('loading a different fixture derives a different scene model', () => {
  renderProvider();
  const small = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  const large = readFileSync('tests/fixtures/factory-quick-start-step-3-red-cube.txt', 'utf8');

  act(() => api.load(small));
  const smallInstanceCount = api.sceneModel?.instances.length;

  act(() => api.load(large));
  const largeInstanceCount = api.sceneModel?.instances.length;

  expect(smallInstanceCount).toBeDefined();
  expect(largeInstanceCount).toBeDefined();
  expect(largeInstanceCount).not.toBe(smallInstanceCount);
});
