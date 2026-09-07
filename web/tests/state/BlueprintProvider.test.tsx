import { readFileSync } from 'node:fs';
import { afterEach, expect, test } from '@rstest/core';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { TraceFrame } from '../../src/api/trace';
import type { Blueprint } from '../../src/format/types';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { TracePanel } from '../../src/ui/TracePanel';
import { restoreFetch, serving } from '../support/build';

afterEach(restoreFetch);

/** A hand-built snapshot, the same shape `traceFrameToBlueprint` produces --
    never parsed from a string, so a test can prove `loadSnapshot` never
    routes through `parseBlueprint` by checking object identity survives. */
const SNAPSHOT: Blueprint = {
  header: {
    headerVersion: 0,
    layout: 10,
    icons: [],
    timestamp: 0n,
    gameVersion: '0.0.0.0',
    shortDesc: '',
    author: 'flab2bp-trace',
    customVersion: '',
    attributes: [],
    description: '',
  },
  hashValid: false,
  version: 1,
  cursorOffsetX: 0,
  cursorOffsetY: 0,
  cursorTargetArea: 0,
  dragBoxSizeX: 1,
  dragBoxSizeY: 1,
  primaryAreaIdx: 0,
  patch: null,
  areas: [
    {
      index: 0,
      parentIndex: -1,
      tropicAnchor: 0,
      areaSegments: 0,
      anchorLocalOffsetX: 0,
      anchorLocalOffsetY: 0,
      width: 1,
      height: 1,
    },
  ],
  buildings: [],
};

/** A hand-built trace frame, for the overlay-state tests below -- never
    polled, so a test can prove `setTraceFrame` and `load`'s clearing of it
    are wired without a network round trip. */
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

test('loadSnapshot sets a non-null snapshotLabel, leaves `stale` untouched, and never parses', () => {
  renderProvider();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));
  act(() => api.markStale());
  expect(api.stale).toBe(true);
  expect(api.snapshotLabel).toBeNull();

  act(() => api.loadSnapshot(SNAPSHOT, 'TRACE · freeform · all-products · incumbent'));

  expect(api.snapshotLabel).toBe('TRACE · freeform · all-products · incumbent');
  // `stale` is exactly what it was before -- loadSnapshot is not `load`, and
  // does not touch it either way (Ruling 5, task-5-addendum.md).
  expect(api.stale).toBe(true);
  // Reference equality: if this had gone through `parseBlueprint` it could
  // not possibly be the same object `loadSnapshot` was handed -- `parseBlueprint`
  // takes a string and builds a fresh Blueprint from binary data, it does not
  // (and could not) return the exact object passed in.
  expect(api.blueprint).toBe(SNAPSHOT);
});

test('a real load after a snapshot clears snapshotLabel back to null', () => {
  renderProvider();
  act(() => api.loadSnapshot(SNAPSHOT, 'TRACE · freeform · all-products · incumbent'));
  expect(api.snapshotLabel).not.toBeNull();

  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));

  expect(api.snapshotLabel).toBeNull();
  expect(api.blueprint).not.toBe(SNAPSHOT);
  expect(api.blueprint?.buildings.length).toBe(36);
});

test('traceFrame and traceShow start with sane defaults', () => {
  renderProvider();
  expect(api.traceFrame).toBeNull();
  // Both layers on: an operator who has never touched the toggles should see
  // everything a trace can show, not a quietly-hidden layer.
  expect(api.traceShow).toEqual({ stranded: true, noGoods: true });
});

test('setTraceFrame and setTraceShow update state directly', () => {
  renderProvider();
  act(() => api.setTraceFrame(A_TRACE_FRAME));
  expect(api.traceFrame).toBe(A_TRACE_FRAME);

  act(() => api.setTraceShow({ stranded: false, noGoods: true }));
  expect(api.traceShow).toEqual({ stranded: false, noGoods: true });
});

test('a real load clears a stale traceFrame -- what stops an old search overlay surviving into a real result', () => {
  renderProvider();
  act(() => api.setTraceFrame(A_TRACE_FRAME));
  expect(api.traceFrame).not.toBeNull();

  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  );
  act(() => api.load(text));

  expect(api.traceFrame).toBeNull();
});

test("TracePanel's tailing effect feeds the newest polled frame into the real provider's traceFrame", async () => {
  serving({ body: { frames: [A_TRACE_FRAME], next: 1, dropped: 0, complete: true } });

  render(
    <BlueprintProvider catalog={catalog}>
      <Probe />
      <TracePanel jobId="abc123" active={true} />
    </BlueprintProvider>,
  );

  // Not the mocked `useBlueprint` `TracePanel.test.tsx` uses -- this is the
  // real provider, so a passing assertion here is coverage of the actual
  // wiring between the poll loop and `setTraceFrame`, not of a stand-in.
  await waitFor(() => expect(api.traceFrame).not.toBeNull());
  expect(api.traceFrame?.no_goods).toEqual([[3, 7]]);
});
