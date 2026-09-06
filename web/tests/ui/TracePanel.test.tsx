import { afterEach, expect, rstest, test } from '@rstest/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { TraceFrame } from '../../src/api/trace';
import { TRACE_POLL_MS } from '../../src/api/trace';
import type { Blueprint } from '../../src/format/types';
import { TracePanel } from '../../src/ui/TracePanel';
import { restoreFetch, serving } from '../support/build';

afterEach(restoreFetch);
afterEach(() => {
  onSnapshot = () => {};
});

const loadSnapshotCalls: Array<{ bp: Blueprint; label: string }> = [];
// Relayed to per-test callbacks by `Harness` below, so an individual test can
// observe just its own snapshot loads without reaching into the shared
// `loadSnapshotCalls` log (which every test in this file still appends to,
// unchanged, for the tests above that already rely on it).
let onSnapshot: (bp: Blueprint, label: string) => void = () => {};

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => ({
    loadSnapshot: (bp: Blueprint, label: string) => {
      loadSnapshotCalls.push({ bp, label });
      onSnapshot(bp, label);
    },
    setTraceFrame: () => {},
    traceShow: { stranded: true, noGoods: true },
    setTraceShow: () => {},
  }),
}));

const FRAME: TraceFrame = {
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

/**
 * A `TracePanel` fed directly from a scripted response, so timeline tests can
 * hand it exact frames rather than reconstructing a poll sequence. `dropped`
 * and `onLoadSnapshot` are per-test hooks: the latter is relayed through the
 * mocked `useBlueprint` above so a test observes only its own loads.
 */
function Harness({
  frames,
  dropped = 0,
  onLoadSnapshot,
}: {
  frames: TraceFrame[];
  dropped?: number;
  onLoadSnapshot?: (bp: Blueprint, label: string) => void;
}) {
  onSnapshot = onLoadSnapshot ?? (() => {});
  serving({ body: { frames, next: frames.at(-1)?.seq ?? -1, dropped, complete: true } });
  return <TracePanel jobId="trace-harness" active={true} />;
}

/** Three frames from one strategy, `seq` and `t` both increasing -- fine for
    scrubber/keyboard/metadata tests, which do not depend on the two ever
    disagreeing (see `racedFrames` below for the case that does). */
const threeFrames: TraceFrame[] = [1, 2, 3].map((n) => ({
  ...FRAME,
  seq: n,
  t: n,
  phase: n === 3 ? 'incumbent' : n === 2 ? 'routed' : 'packed',
  incumbent: n === 3,
}));

/**
 * Two strategies racing, with `seq` and `t` deliberately DISAGREEING within
 * the `freeform` arm: `seq: 1` (t=30) was assigned at the parent before
 * `seq: 3` (t=20), but happened LATER in real time. This is exactly the
 * scenario task-11-addendum.md Ruling 2 warns about -- a lane sorted by
 * `seq` or array order would show these two ticks backwards.
 */
const racedFrames: TraceFrame[] = [
  { ...FRAME, seq: 1, t: 30, strategy: 'freeform', phase: 'packed', incumbent: false },
  { ...FRAME, seq: 2, t: 10, strategy: 'sequence-pair', phase: 'routed', incumbent: false },
  { ...FRAME, seq: 3, t: 20, strategy: 'freeform', phase: 'incumbent', incumbent: true },
];

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

test('unmounting mid-poll stops the loop and makes no further requests', async () => {
  const calls = serving(
    { body: { frames: [FRAME], next: 1, dropped: 0, complete: false } },
    { body: { frames: [FRAME], next: 2, dropped: 0, complete: false } },
  );

  const { unmount } = render(<TracePanel jobId="abc123" active={true} />);
  await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));

  unmount();
  const callsAtUnmount = calls.length;

  // Long enough to span several TRACE_POLL_MS intervals if the loop were
  // still running unattended after unmount.
  await new Promise((resolve) => setTimeout(resolve, TRACE_POLL_MS * 3));

  expect(calls.length).toBe(callsAtUnmount);
});

test('a response that arrives after polling has been told to stop is discarded, not applied', async () => {
  // A hand-controlled fetch, so the response can be made to arrive AFTER
  // unmount -- the exact race `controller.abort()` alone cannot win, because
  // an abort cannot cancel a response that has already come back on the wire.
  let resolveFetch: ((response: Response) => void) | undefined;
  const pending = new Promise<Response>((resolve) => {
    resolveFetch = resolve;
  });
  globalThis.fetch = (() => pending) as unknown as typeof fetch;

  const before = loadSnapshotCalls.length;
  const { unmount } = render(<TracePanel jobId="abc123" active={true} />);

  // Stop the panel -- mirroring `active` flipping to false the instant a real
  // build settles -- WHILE the request is still in flight.
  unmount();

  resolveFetch?.(
    new Response(JSON.stringify({ frames: [FRAME], next: 1, dropped: 0, complete: false }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  );
  await pending;
  // Give the poll loop's continuation a tick to run, and to prove it applies
  // nothing: this is what would repaint a stale trace frame over a fresh
  // real result if the apply step were not itself guarded.
  await new Promise((resolve) => setTimeout(resolve, 10));

  expect(loadSnapshotCalls.length).toBe(before);
});

// ---- Task 11: scrubber, live tail, lanes, dropped-frame honesty, metadata ----

test('scrubbing turns the live tail off and loads the scrubbed frame', async () => {
  const loaded: string[] = [];
  render(<Harness frames={threeFrames} onLoadSnapshot={(_bp, label) => loaded.push(label)} />);

  await waitFor(() => expect(loaded.length).toBeGreaterThan(0));
  expect(screen.getByRole('checkbox', { name: /live tail/i })).toBeChecked();

  fireEvent.change(screen.getByRole('slider', { name: /snapshot/i }), { target: { value: '0' } });
  expect(screen.getByRole('checkbox', { name: /live tail/i })).not.toBeChecked();
  expect(loaded.at(-1)).toContain('TRACE · freeform');
});

test('arrow keys step one frame at a time', async () => {
  render(<Harness frames={threeFrames} />);
  const slider = await screen.findByRole('slider', { name: /snapshot/i });

  fireEvent.keyDown(slider, { key: 'ArrowLeft' });
  expect(slider).toHaveValue('1');
});

test('Home and End jump to the first and last buffered frame', async () => {
  render(<Harness frames={threeFrames} />);
  const slider = await screen.findByRole('slider', { name: /snapshot/i });

  fireEvent.keyDown(slider, { key: 'Home' });
  expect(slider).toHaveValue('0');

  fireEvent.keyDown(slider, { key: 'End' });
  expect(slider).toHaveValue(String(threeFrames.length - 1));
});

test('re-checking live tail jumps back to the newest frame', async () => {
  render(<Harness frames={threeFrames} />);
  const slider = await screen.findByRole('slider', { name: /snapshot/i });
  const tail = screen.getByRole('checkbox', { name: /live tail/i });

  fireEvent.keyDown(slider, { key: 'Home' });
  expect(slider).toHaveValue('0');
  expect(tail).not.toBeChecked();

  fireEvent.click(tail);
  expect(tail).toBeChecked();
  expect(slider).toHaveValue(String(threeFrames.length - 1));
});

test('dropped frames are stated rather than hidden', async () => {
  render(<Harness frames={threeFrames} dropped={7} />);
  // A gappy timeline that does not say it is gappy reads as a search that
  // stalled, which is a different bug from the one that happened.
  expect(await screen.findByText(/7 snapshot\(s\) dropped/i)).toBeInTheDocument();
});

test('the dropped count neither claims finality nor implies every drop is congestion', async () => {
  // task-11-addendum.md Ruling 4: a raced arm's share only lands at
  // settlement (so a mid-run figure is not final), and `TraceChannel.offer`
  // catches broadly, so a structurally unsendable event increments the same
  // counter as a real ring eviction (so a drop is not always congestion).
  render(<Harness frames={threeFrames} dropped={3} />);
  const message = await screen.findByText(/3 snapshot\(s\) dropped/i);
  expect(message.textContent).toMatch(/settle/i);
  expect(message.textContent).toMatch(/not every drop/i);
});

test('the metadata table names every field the frame carries', async () => {
  render(<Harness frames={threeFrames} />);
  await screen.findByTestId('trace-meta');
  for (const label of ['strategy', 'candidate', 'phase', 'height', 'area', 'belt tiles']) {
    expect(screen.getByText(new RegExp(label, 'i'))).toBeInTheDocument();
  }
});

test('the metadata table reports a stranded-net count', async () => {
  const frame: TraceFrame = {
    ...threeFrames[0]!,
    stranded: [
      [0, 0, 1, 1],
      [2, 2, 3, 3],
    ],
  };
  render(<Harness frames={[frame]} />);
  expect(await screen.findByTestId('trace-stranded')).toHaveTextContent('2');
});

test("Task 10's no-goods row and its approximate-geometry label survive verbatim", async () => {
  render(<Harness frames={threeFrames} />);
  await screen.findByTestId('trace-meta');
  // Permanent row, `—` when there are none (task-10, kept unchanged by
  // task-11-addendum.md Ruling 5).
  expect(screen.getByTestId('trace-no-goods')).toHaveTextContent('—');
  // The exact label wording is the fix for a truthfulness finding: the
  // canvas box this toggle draws is index-based, not to scale.
  expect(
    screen.getByText('No-goods (approximate — index-based, not to scale)'),
  ).toBeInTheDocument();
});

test('a truncated frame says so', async () => {
  render(<Harness frames={[{ ...threeFrames[0]!, truncated: true }]} />);
  expect(await screen.findByText(/sampled/i)).toBeInTheDocument();
});

test('racing strategies each get their own lane (spec G5)', async () => {
  render(<Harness frames={racedFrames} />);
  expect(await screen.findByTestId('trace-lane-freeform')).toBeInTheDocument();
  expect(screen.getByTestId('trace-lane-sequence-pair')).toBeInTheDocument();
});

test('lane ticks are ordered and positioned by frame.t, never by seq or arrival order', async () => {
  render(<Harness frames={racedFrames} />);
  const lane = await screen.findByTestId('trace-lane-freeform');
  const ticks = lane.querySelectorAll('.trace-tick');
  expect(ticks).toHaveLength(2);

  // `seq: 3` (t=20) happened before `seq: 1` (t=30) in real time, even
  // though `seq: 1` was assigned first at the parent -- sorting by `seq` or
  // by array order would render these backwards.
  expect(ticks[0]?.getAttribute('title')).toContain('incumbent');
  expect(ticks[1]?.getAttribute('title')).toContain('packed');

  // Positioned on the SAME axis as the other lane: tMin/tMax span all
  // buffered frames (10..30), not just this lane's own two.
  const positions = Array.from(ticks).map((tick) => (tick as HTMLElement).style.left);
  expect(positions).toEqual(['50%', '100%']);
});
