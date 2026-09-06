import { afterEach, expect, rstest, test } from '@rstest/core';
import { render, waitFor } from '@testing-library/react';
import type { Blueprint } from '../../src/format/types';
import { TracePanel } from '../../src/ui/TracePanel';
import { restoreFetch, serving } from '../support/build';

afterEach(restoreFetch);

const loadSnapshotCalls: Array<{ bp: Blueprint; label: string }> = [];

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => ({
    loadSnapshot: (bp: Blueprint, label: string) => {
      loadSnapshotCalls.push({ bp, label });
    },
  }),
}));

const FRAME = {
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
  no_goods: [],
  buildings: [[2001, 35, 0, 0, 0, 0, 61, 0, 1, -1]],
};

test('polls the trace endpoint and loads the newest incumbent as a labeled snapshot', async () => {
  const calls = serving({ body: { frames: [FRAME], next: 1, dropped: 0, complete: true } });

  render(<TracePanel jobId="abc123" active={true} />);

  await waitFor(() => expect(loadSnapshotCalls.length).toBeGreaterThan(0));

  expect(calls[0]?.url).toContain('/api/build/abc123/trace?from=-1');
  const call = loadSnapshotCalls[0];
  // Never pasteable: the label is present the whole time a snapshot is
  // shown, and no blueprint string appears anywhere on the frame's model.
  expect(call?.label).toContain('TRACE');
  expect(call?.label).toContain('freeform');
  expect(call?.bp.buildings).toHaveLength(1);
  expect(call?.bp.hashValid).toBe(false);
});

test('passes the returned cursor straight back as `from`, with no off-by-one', async () => {
  const calls = serving(
    { body: { frames: [FRAME], next: 5, dropped: 0, complete: false } },
    { body: { frames: [], next: 5, dropped: 0, complete: true } },
  );

  render(<TracePanel jobId="abc123" active={true} />);

  await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));

  expect(calls[0]?.url).toContain('from=-1');
  // The endpoint's cursor contract (task-5 orchestrator brief): `from` is
  // exclusive and `next` is the highest seq returned, unchanged when nothing
  // is new -- so the client passes it straight back, no `+ 1` anywhere.
  expect(calls[1]?.url).toContain('from=5');
});

test('does nothing while inactive', async () => {
  const calls = serving({ body: { frames: [], next: -1, dropped: 0, complete: true } });

  render(<TracePanel jobId="abc123" active={false} />);
  await new Promise((resolve) => setTimeout(resolve, 20));

  expect(calls).toHaveLength(0);
});
