import { readFileSync } from 'node:fs';
import { afterEach, expect, test } from '@rstest/core';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { TraceFrame } from '../../src/api/trace';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { TracePanel } from '../../src/ui/TracePanel';
import { restoreFetch, serving } from '../support/build';
import { InputPanel } from '../../src/ui/InputPanel';

afterEach(restoreFetch);

const A_TRACE_FRAME: TraceFrame = {
  seq: 1,
  t: 0.5,
  strategy: 'freeform',
  candidate: 'all-products',
  phase: 'incumbent',
  height: 34,
  arrangement: 2,
  restart: null,
  stage: null,
  island: null,
  round: null,
  block: null,
  area: 12,
  belt_tiles: 2,
  incumbent: true,
  reason: null,
  bounds: [0, 0, 3, 3],
  truncated: false,
  stranded: [],
  no_goods: [[3, 7]],
  buildings: [[2001, 35, 0, 0, 0, 0, 61, 0, 1, -1]],
};

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
  act(() => api.publishArtifact(text, api.beginPublication()));
  expect(screen.getByTestId('count')).toHaveTextContent('36');
  expect(api.sceneModel).not.toBeNull();
  expect(api.error).toBeNull();
});

test('surfaces a parse failure as a message instead of throwing', () => {
  renderProvider();
  act(() => api.publishArtifact('not a blueprint', api.beginPublication()));
  expect(screen.getByTestId('error')).not.toHaveTextContent('');
  expect(api.blueprint).toBeNull();
});

test('selection is tracked and cleared when a new blueprint loads', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.publishArtifact(text, api.beginPublication()));
  act(() => api.select(3));
  expect(screen.getByTestId('selected')).toHaveTextContent('3');
  act(() => api.publishArtifact(text, api.beginPublication()));
  expect(screen.getByTestId('selected')).toHaveTextContent('-1');
});

test('a failed load after a successful one clears the stale blueprint, scene model, and selection', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.publishArtifact(text, api.beginPublication()));
  act(() => api.select(3));
  expect(api.blueprint).not.toBeNull();
  expect(api.sceneModel).not.toBeNull();

  act(() => api.publishArtifact('not a blueprint', api.beginPublication()));

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

  act(() => api.publishArtifact(small, api.beginPublication()));
  const smallInstanceCount = api.sceneModel?.instances.length;

  act(() => api.publishArtifact(large, api.beginPublication()));
  const largeInstanceCount = api.sceneModel?.instances.length;

  expect(smallInstanceCount).toBeDefined();
  expect(largeInstanceCount).toBeDefined();
  expect(largeInstanceCount).not.toBe(smallInstanceCount);
});

test('a real load after a snapshot clears snapshotLabel back to null', () => {
  renderProvider();
  act(() => api.selectTrace(A_TRACE_FRAME, 'trace'));
  expect(api.snapshotLabel).not.toBeNull();

  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.publishArtifact(text, api.beginPublication()));

  expect(api.snapshotLabel).toBeNull();
  expect(api.document?.kind).toBe('artifact');
  expect(api.blueprint?.buildings.length).toBe(36);
});

test('a real load clears a stale traceFrame -- what stops an old search overlay surviving into a real result', () => {
  renderProvider();
  act(() => api.selectTrace(A_TRACE_FRAME, 'trace'));
  expect(api.traceFrame).not.toBeNull();

  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.publishArtifact(text, api.beginPublication()));

  expect(api.traceFrame).toBeNull();
});

test("TracePanel's tailing effect feeds the newest polled frame into the real provider's traceFrame", async () => {
  serving({ body: { frames: [A_TRACE_FRAME], next: 1, dropped: 0, complete: true } });

  render(
    <BlueprintProvider catalog={catalog}>
      <Probe />
      <TracePanel jobId="abc123" generation={0} active={true} />
    </BlueprintProvider>,
  );

  // Real collection and display: overlay facts belong to the shown document.
  await waitFor(() => expect(api.traceFrame).not.toBeNull());
  expect(api.traceFrame?.no_goods).toEqual([[3, 7]]);
});

test('explicit trace selection atomically clears prior parse error and entity selection without checksum warning', async () => {
  serving({ body: { frames: [A_TRACE_FRAME], next: 1, dropped: 0, complete: true } });
  render(
    <BlueprintProvider catalog={catalog}>
      <Probe />
      <InputPanel />
      <TracePanel jobId="abc123" generation={0} active={true} />
    </BlueprintProvider>,
  );
  await screen.findByLabelText('Snapshot');
  act(() => {
    api.publishArtifact('not a blueprint', api.beginPublication());
    api.select(27);
  });
  fireEvent.keyDown(screen.getByLabelText('Snapshot'), { key: 'Home' });
  await waitFor(() => expect(api.blueprint?.buildings[0]?.itemId).toBe(2001));
  expect(api.selectedIndex).toBeNull();
  expect(api.error).toBeNull();
  expect(screen.queryByText(/Checksum mismatch/)).toBeNull();
});
