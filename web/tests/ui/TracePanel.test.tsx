import { afterEach, expect, test } from '@rstest/core';
import { fireEvent, render as renderUI, screen, waitFor } from '@testing-library/react';
import type { TraceFrame } from '../../src/api/trace';
import { TRACE_POLL_MS } from '../../src/api/trace';
import type { Blueprint } from '../../src/format/types';
import { TracePanel } from '../../src/ui/TracePanel';
import { restoreFetch, serving } from '../support/build';
import { useEffect, type ReactNode } from 'react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { realCatalog } from '../support/catalog';

afterEach(restoreFetch);
afterEach(() => {
  onSnapshot = () => {};
  displayedSnapshots.length = 0;
});

const displayedSnapshots: Array<{ bp: Blueprint; label: string }> = [];
// Observe actual displayed documents, rather than substituting publication callbacks.
let onSnapshot: (bp: Blueprint, label: string) => void = () => {};

function DisplayedSnapshot() {
  const { document } = useBlueprint();
  useEffect(() => {
    if (document?.kind === 'trace') {
      displayedSnapshots.push({ bp: document.blueprint, label: document.label });
      onSnapshot(document.blueprint, document.label);
    }
  }, [document]);
  return (
    <output data-testid="displayed-trace">
      {document?.kind === 'trace' ? document.label : ''}
    </output>
  );
}

function render(children: ReactNode) {
  return renderUI(
    <BlueprintProvider catalog={realCatalog}>
      {children}
      <DisplayedSnapshot />
    </BlueprintProvider>,
  );
}

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

/** Timeline fixtures are polled by the real panel and published by the real provider. */
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
  return <TracePanel jobId="trace-harness" generation={0} active={true} />;
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

  render(<TracePanel jobId="abc123" generation={0} active={true} />);

  await waitFor(() => expect(displayedSnapshots.at(-1)?.bp.buildings[0]?.itemId).toBe(2001));

  expect(calls[0]?.url).toContain('/api/build/abc123/trace?from=-1');
  const call = displayedSnapshots.at(-1);
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

  render(<TracePanel jobId="abc123" generation={0} active={true} />);

  await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));

  expect(calls[0]?.url).toContain('from=-1');
  // The endpoint's cursor contract (task-5 orchestrator brief): `from` is
  // exclusive and `next` is the highest seq returned, unchanged when nothing
  // is new -- so the client passes it straight back, no `+ 1` anywhere.
  expect(calls[1]?.url).toContain('from=5');
});

test('an empty open page does not hide the delayed final frame from the scrubber', async () => {
  const first = { ...FRAME, seq: 0, t: 0, phase: 'packed' as const, incumbent: false };
  const final = { ...FRAME, seq: 1, t: 1, candidate: 'final-drain' };
  const calls = serving(
    { body: { frames: [first], next: 0, dropped: 0, complete: false } },
    { body: { frames: [], next: 0, dropped: 0, complete: false } },
    { body: { frames: [final], next: 1, dropped: 0, complete: false } },
    { body: { frames: [], next: 1, dropped: 0, complete: true } },
  );
  const snapshots: string[] = [];
  onSnapshot = (_bp, label) => snapshots.push(label);
  render(<TracePanel jobId="terminal-job" generation={0} active={true} />);

  await waitFor(() => expect(calls).toHaveLength(4), { timeout: 3000 });
  const scrubber = screen.getByRole('slider');
  fireEvent.keyDown(scrubber, { key: 'Home' });
  await waitFor(() => expect(snapshots.at(-1)).toContain('packed'));
  fireEvent.keyDown(scrubber, { key: 'End' });
  await waitFor(() => expect(snapshots.at(-1)).toContain('final-drain'));
  expect(calls.map((call) => call.url.split('from=')[1])).toEqual(['-1', '0', '0', '1']);
});

test('does nothing while inactive', async () => {
  const calls = serving({ body: { frames: [], next: -1, dropped: 0, complete: true } });

  render(<TracePanel jobId="abc123" generation={0} active={false} />);
  await new Promise((resolve) => setTimeout(resolve, 20));

  expect(calls).toHaveLength(0);
});

test('unmounting mid-poll stops the loop and makes no further requests', async () => {
  const calls = serving(
    { body: { frames: [FRAME], next: 1, dropped: 0, complete: false } },
    { body: { frames: [FRAME], next: 2, dropped: 0, complete: false } },
  );

  const { unmount } = render(<TracePanel jobId="abc123" generation={0} active={true} />);
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

  const before = displayedSnapshots.length;
  const { unmount } = render(<TracePanel jobId="abc123" generation={0} active={true} />);

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

  expect(displayedSnapshots.length).toBe(before);
});

// ---- I5: the poll loop tolerates transient failures rather than dying ----

test('a transient poll failure is retried, not treated as the permanent end of the live tail', async () => {
  const before = displayedSnapshots.length;
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    if (calls === 1) return new Response('boom', { status: 500 });
    return new Response(
      JSON.stringify({ frames: [FRAME], next: 1, dropped: 0, evicted: 0, complete: true }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  }) as unknown as typeof fetch;

  render(<TracePanel jobId="abc123" generation={0} active={true} />);

  await waitFor(() => expect(displayedSnapshots.length).toBeGreaterThan(before));
  expect(calls).toBeGreaterThanOrEqual(2);
  expect(screen.queryByTestId('trace-poll-stopped')).toBeNull();
});

test('the poll loop says so once it gives up after repeated consecutive failures', async () => {
  globalThis.fetch = (async () => new Response('boom', { status: 500 })) as unknown as typeof fetch;

  render(<TracePanel jobId="abc123" generation={0} active={true} />);

  // "Live tail" must not be left reading as live over a frame count that has
  // quietly stopped moving -- the loop says it gave up.
  expect(await screen.findByTestId('trace-poll-stopped', {}, { timeout: 5000 })).toHaveTextContent(
    /live tail stopped/i,
  );
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

test('a pinned snapshot that ages out of the buffered window says so, rather than silently tracking newest', async () => {
  // #16: the client buffers at most 256 frames (`.slice(-256)`); a flood of
  // new ones can push a pinned frame out of that window entirely.
  const first = { ...FRAME, seq: 1, t: 1 };
  const flood: TraceFrame[] = Array.from({ length: 260 }, (_, i) => ({
    ...FRAME,
    seq: i + 2,
    t: i + 2,
  }));
  const calls = serving(
    { body: { frames: [first], next: 1, dropped: 0, evicted: 0, complete: false } },
    {
      body: {
        frames: flood,
        next: flood.at(-1)?.seq ?? 1,
        dropped: 0,
        evicted: 0,
        complete: true,
      },
    },
  );

  render(<TracePanel jobId="abc123" generation={0} active={true} />);
  const slider = await screen.findByRole('slider', { name: /snapshot/i });

  // Pin the only frame delivered so far.
  fireEvent.keyDown(slider, { key: 'Home' });
  expect(screen.getByRole('checkbox', { name: /live tail/i })).not.toBeChecked();
  expect(screen.queryByTestId('trace-pin-expired')).toBeNull();

  // The flood arrives and evicts the pinned frame from the client's window.
  await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));
  expect(await screen.findByTestId('trace-pin-expired', {}, { timeout: 2000 })).toHaveTextContent(
    /pinned snapshot expired/i,
  );
});

test("the ring's own eviction is informational, not a warning -- a healthy build is not told it lost data", async () => {
  serving({ body: { frames: [FRAME], next: 1, dropped: 0, evicted: 12, complete: true } });

  render(<TracePanel jobId="abc123" generation={0} active={true} />);

  const evictedNote = await screen.findByTestId('trace-evicted');
  expect(evictedNote).toHaveTextContent('12 older snapshots rolled off the buffered window.');
  expect(evictedNote.tagName.toLowerCase()).not.toBe('output');
  expect(evictedNote.className).not.toMatch(/warn/);
  expect(screen.queryByTestId('trace-dropped')).toBeNull();
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
