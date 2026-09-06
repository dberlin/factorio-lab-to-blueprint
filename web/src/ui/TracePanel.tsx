/**
 * Live tail of a traced build. Polls its own cursor at {@link TRACE_POLL_MS}
 * — deliberately not the job poll's 300 ms → 2 s backoff, which exists to
 * keep a five-minute build from making 300 requests and is the opposite of
 * what a live tail wants.
 *
 * A shown frame is never mistaken for a pasteable result: the caption always
 * reads `TRACE · …` and `BlueprintProvider.snapshotLabel` stays non-null for
 * as long as one is on the canvas.
 *
 * This is the timeline: a scrubber over the buffered frames, a live-tail
 * toggle that pins to the newest one, one lane per racing strategy on a
 * shared time axis, and the per-frame metadata table. task-11-addendum.md
 * (controller rulings) governs where it disagrees with the original brief;
 * see the comments below for each place that applies.
 */
import { useEffect, useId, useState, type KeyboardEvent } from 'react';
import { pollTrace, TRACE_POLL_MS, type TraceFrame } from '../api/trace';
import { traceFrameLabel, traceFrameToBlueprint } from '../model/traceScene';
import { useBlueprint } from '../state/BlueprintProvider';

export function TracePanel({ jobId, active }: { jobId: string; active: boolean }) {
  const { loadSnapshot, setTraceFrame, traceShow, setTraceShow } = useBlueprint();
  const [frames, setFrames] = useState<TraceFrame[]>([]);
  const [dropped, setDropped] = useState(0);
  const [tailing, setTailing] = useState(true);
  // The frame the scrubber is pinned to while `tailing` is false, tracked by
  // `seq` rather than array index. The held-frames buffer is capped
  // (`slice(-256)` below) and trims from the front, so an index recorded
  // before a trim would silently point at a different, newer frame after
  // one — a plain `useState<number>` index would misreport the very thing
  // this panel exists to show honestly. `null` while there is nothing
  // pinned yet (before the first manual scrub).
  const [pinnedSeq, setPinnedSeq] = useState<number | null>(null);
  const snapshotId = useId();

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    // -1: the first poll asks for every frame the ring still holds. `from` is
    // exclusive, so this is the one place a sentinel below the lowest
    // possible `seq` belongs — every later call passes the server's own
    // `next` straight back, with no arithmetic on it.
    let cursor = -1;
    let stopped = false;
    (async () => {
      while (!stopped) {
        const page = await pollTrace(jobId, cursor, controller.signal);
        // Aborting the in-flight request is not enough on its own: an abort
        // can lose the race against a response that already arrived (e.g. a
        // real build's `load()` settles the job and this effect is cleaned
        // up between the fetch resolving and this line running). Checking
        // `stopped` again here, immediately before touching any state, is
        // what actually stops a frame from a poll that was told to stop from
        // repainting over a fresh real result.
        if (stopped) return;
        cursor = page.next;
        // This total folds three counters together (server.py): the
        // parent-side ring's own evictions, stage-1 overflow, and each raced
        // arm's `TraceChannel` drops. A raced arm's share only lands once
        // that arm settles, so a figure read mid-run is legitimately partial
        // — never presented below as a final count (task-11-addendum.md
        // Ruling 4).
        setDropped(page.dropped);
        if (page.frames.length > 0) {
          setFrames((held) => [...held, ...page.frames].slice(-256));
        }
        if (page.complete) return;
        await new Promise((resolve) => setTimeout(resolve, TRACE_POLL_MS));
      }
    })().catch(() => undefined);
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [jobId, active]);

  const lastIndex = frames.length - 1;
  // Derived during render, not state: `pinnedSeq` can point at a frame the
  // 256-frame ring has since dropped (see the comment on the state above),
  // in which case there is nothing sensible to show but the newest frame.
  const pinnedIndex = pinnedSeq === null ? -1 : frames.findIndex((f) => f.seq === pinnedSeq);
  const selectedIndex = tailing || pinnedIndex === -1 ? lastIndex : pinnedIndex;
  const shown = frames[selectedIndex];

  useEffect(() => {
    if (shown) {
      loadSnapshot(traceFrameToBlueprint(shown), traceFrameLabel(shown));
      // Kept alongside the reconstructed Blueprint, not inside it: the
      // overlays read stranded/no_goods straight off the frame, and a
      // Blueprint has nowhere to carry either.
      setTraceFrame(shown);
    }
  }, [shown, loadSnapshot, setTraceFrame]);

  if (!shown) {
    return (
      <section className="trace-panel" data-testid="trace-panel">
        <p className="note">Waiting for the first search snapshot…</p>
      </section>
    );
  }

  function jumpTo(index: number) {
    const clamped = Math.min(Math.max(index, 0), lastIndex);
    setTailing(false);
    setPinnedSeq(frames[clamped]?.seq ?? null);
  }

  function onScrubKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case 'ArrowLeft':
      case 'ArrowDown':
        event.preventDefault();
        jumpTo(selectedIndex - 1);
        break;
      case 'ArrowRight':
      case 'ArrowUp':
        event.preventDefault();
        jumpTo(selectedIndex + 1);
        break;
      case 'Home':
        event.preventDefault();
        jumpTo(0);
        break;
      case 'End':
        event.preventDefault();
        jumpTo(lastIndex);
        break;
      default:
        break;
    }
  }

  // One lane per strategy, on a shared `t` axis (spec G5; moved into this
  // task by task-11-addendum.md Ruling 1 — Task 8 shipped the racing
  // backend but deliberately left this view unbuilt). Sort and position
  // ticks by `frame.t` — the child-originated creation time stamped at
  // construction — never by `seq` or array order: `seq` is assignment order
  // at the parent, which is NOT the order two raced children actually
  // produced events in (Ruling 2). Getting this backwards is exactly the
  // defect class this branch has already had to fix three times.
  const strategies = Array.from(new Set(frames.map((f) => f.strategy)));
  const times = frames.map((f) => f.t);
  const tMin = Math.min(...times);
  // Guards the single-frame / all-simultaneous case: with only one instant
  // buffered, `tMax - tMin` is 0 and would divide the tick position by zero.
  const tSpan = Math.max(...times) - tMin || 1;
  const lanes = strategies.map((strategy) => ({
    strategy,
    ticks: frames
      .filter((f) => f.strategy === strategy)
      .slice()
      .sort((a, b) => a.t - b.t),
  }));
  // G6 (a round × block grid for the `hierarchical` strategy) is explicitly
  // NOT built here: `src/flab2bp/layout/hierarchy/` does not exist on this
  // branch, so nothing can emit a frame with `strategy === 'hierarchical'`
  // yet, and a grid for frames that cannot exist would be dead UI no test
  // can exercise against real data (task-11-addendum.md Ruling 3). The lane
  // view above is where that follow-on lands once hierarchical merges.

  return (
    <section className="trace-panel" data-testid="trace-panel">
      <div className="row">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={tailing}
            onChange={(event) => setTailing(event.target.checked)}
          />
          Live tail
        </label>
        <span className="note" data-testid="trace-count">
          {frames.length} snapshot{frames.length === 1 ? '' : 's'} seen
        </span>
        {dropped > 0 && (
          // An `<output>`, per the canvas caption's precedent (Toolbar.tsx):
          // this updates on every poll, and `<output>` carries an implicit
          // `status` role so a screen reader announces the new count rather
          // than being spammed by an `aria-live` region on every tick.
          //
          // Worded to state the count plainly without either dishonesty
          // Ruling 4 warns against: it does not claim finality (a raced
          // arm's share lands only at settlement, so this can still be a
          // partial mid-run figure), and it does not imply every drop is
          // congestion (`TraceChannel.offer` catches broadly, so a
          // structurally unsendable event increments the same counter).
          <output className="note warn" data-testid="trace-dropped">
            {dropped} snapshot(s) dropped — folds the parent-side ring with each raced arm's own
            drops (added once that arm settles); not every drop means congestion.
          </output>
        )}
      </div>
      <div className="row trace-scrubber">
        <label htmlFor={snapshotId}>Snapshot</label>
        <input
          id={snapshotId}
          type="range"
          min={0}
          max={Math.max(lastIndex, 0)}
          value={selectedIndex}
          onChange={(event) => jumpTo(Number(event.target.value))}
          onKeyDown={onScrubKeyDown}
        />
        <span className="note">
          {selectedIndex + 1} / {frames.length}
        </span>
      </div>
      <div className="trace-lanes" data-testid="trace-lanes">
        {lanes.map(({ strategy, ticks }) => (
          <div className="trace-lane" key={strategy} data-testid={`trace-lane-${strategy}`}>
            <span className="trace-lane-label">{strategy}</span>
            <div className="trace-lane-track">
              {ticks.map((frame) => (
                <span
                  key={frame.seq}
                  className={
                    'trace-tick' +
                    ` trace-tick-${frame.phase}` +
                    (frame.incumbent ? ' trace-tick-incumbent' : '') +
                    (frame.seq === shown.seq ? ' trace-tick-selected' : '')
                  }
                  style={{ left: `${((frame.t - tMin) / tSpan) * 100}%` }}
                  title={`${frame.strategy} · ${frame.phase} · t=${frame.t.toFixed(3)}`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="row">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={traceShow.stranded}
            data-testid="trace-show-stranded"
            onChange={(event) => setTraceShow({ ...traceShow, stranded: event.target.checked })}
          />
          Stranded nets
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={traceShow.noGoods}
            data-testid="trace-show-no-goods"
            onChange={(event) => setTraceShow({ ...traceShow, noGoods: event.target.checked })}
          />
          {/* Visible without hovering, per review round 1 IMPORTANT 1: the
              canvas box this toggle draws is an index-based placeholder, not
              a to-scale footprint -- this label is the in-UI signal that
              stops it being read as real geometry. Kept verbatim
              (task-11-addendum.md Ruling 5). */}
          No-goods (approximate — index-based, not to scale)
        </label>
      </div>
      {/* This caption, and only this caption, ever names what is on the
          canvas while a snapshot is showing — there is no other route to a
          copyable string here. */}
      <p className="trace-caption" data-testid="trace-caption">
        {traceFrameLabel(shown)}
      </p>
      <dl className="trace-meta" data-testid="trace-meta">
        <div>
          <dt>Strategy</dt>
          <dd>{shown.strategy}</dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd>{shown.candidate}</dd>
        </div>
        <div>
          <dt>Phase</dt>
          <dd>{shown.phase}</dd>
        </div>
        <div>
          <dt>Height</dt>
          <dd>{shown.height ?? '—'}</dd>
        </div>
        <div>
          <dt>Arrangement</dt>
          <dd>{shown.arrangement ?? '—'}</dd>
        </div>
        <div>
          <dt>Restart</dt>
          <dd>{shown.restart ?? '—'}</dd>
        </div>
        <div>
          <dt>Stage</dt>
          <dd>{shown.stage ?? '—'}</dd>
        </div>
        <div>
          <dt>Island</dt>
          <dd>{shown.island ?? '—'}</dd>
        </div>
        <div>
          <dt>Round</dt>
          <dd>{shown.round ?? '—'}</dd>
        </div>
        <div>
          <dt>Block</dt>
          <dd>{shown.block ?? '—'}</dd>
        </div>
        <div>
          <dt>Area</dt>
          <dd>{shown.area ?? '—'}</dd>
        </div>
        <div>
          <dt>Belt tiles</dt>
          <dd>{shown.belt_tiles ?? '—'}</dd>
        </div>
        <div>
          <dt>Incumbent</dt>
          <dd>{shown.incumbent ? 'yes' : 'no'}</dd>
        </div>
        <div>
          <dt>Reason</dt>
          <dd>{shown.reason ?? '—'}</dd>
        </div>
        <div>
          <dt>Stranded</dt>
          {/* A count, not geometry: the canvas overlay (toggle above) draws
              the actual boxes when it is on; this row keeps the count
              legible even while that toggle is off. */}
          <dd data-testid="trace-stranded">
            {shown.stranded.length === 0 ? '—' : shown.stranded.length}
          </dd>
        </div>
        <div>
          <dt>No-goods</dt>
          {/* Text, not geometry: unambiguous even where the canvas box is
              only an approximate placeholder (review round 1 IMPORTANT 1).
              Kept verbatim (task-11-addendum.md Ruling 5). */}
          <dd data-testid="trace-no-goods">
            {shown.no_goods.length === 0
              ? '—'
              : shown.no_goods.map((strips) => `[${strips.join(', ')}]`).join(', ')}
          </dd>
        </div>
      </dl>
      {shown.truncated && (
        <p className="note">Buildings sampled: this placement is over the frame cap.</p>
      )}
    </section>
  );
}
