/**
 * Live tail of a traced build. Polls its own cursor at {@link TRACE_POLL_MS}
 * — deliberately not the job poll's 300 ms → 2 s backoff, which exists to
 * keep a five-minute build from making 300 requests and is the opposite of
 * what a live tail wants.
 *
 * A shown frame is never mistaken for a pasteable result: the caption always
 * reads `TRACE · …` and `BlueprintProvider.snapshotLabel` stays non-null for
 * as long as one is on the canvas.
 */
import { useEffect, useState } from 'react';
import { pollTrace, TRACE_POLL_MS, type TraceFrame } from '../api/trace';
import { traceFrameLabel, traceFrameToBlueprint } from '../model/traceScene';
import { useBlueprint } from '../state/BlueprintProvider';

export function TracePanel({ jobId, active }: { jobId: string; active: boolean }) {
  const { loadSnapshot } = useBlueprint();
  const [frames, setFrames] = useState<TraceFrame[]>([]);
  const [dropped, setDropped] = useState(0);
  const [tailing, setTailing] = useState(true);

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

  const newest = frames[frames.length - 1];
  useEffect(() => {
    if (tailing && newest) loadSnapshot(traceFrameToBlueprint(newest), traceFrameLabel(newest));
  }, [tailing, newest, loadSnapshot]);

  if (!newest) {
    return (
      <section className="trace-panel" data-testid="trace-panel">
        <p className="note">Waiting for the first search snapshot…</p>
      </section>
    );
  }

  return (
    <section className="trace-panel" data-testid="trace-panel">
      <div className="row">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={tailing}
            onChange={(event) => setTailing(event.target.checked)}
          />
          Tail live
        </label>
        <span className="note" data-testid="trace-count">
          {frames.length} snapshot{frames.length === 1 ? '' : 's'} seen
        </span>
        {dropped > 0 && (
          <span className="note warn" data-testid="trace-dropped">
            {dropped} frame{dropped === 1 ? '' : 's'} dropped
          </span>
        )}
      </div>
      {/* This caption, and only this caption, ever names what is on the
          canvas while a snapshot is showing — there is no other route to a
          copyable string here. */}
      <p className="trace-caption" data-testid="trace-caption">
        {traceFrameLabel(newest)}
      </p>
      <dl className="trace-meta" data-testid="trace-meta">
        <div>
          <dt>Strategy</dt>
          <dd>{newest.strategy}</dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd>{newest.candidate}</dd>
        </div>
        <div>
          <dt>Phase</dt>
          <dd>{newest.phase}</dd>
        </div>
        <div>
          <dt>Area</dt>
          <dd>{newest.area ?? '—'}</dd>
        </div>
        <div>
          <dt>Belt tiles</dt>
          <dd>{newest.belt_tiles ?? '—'}</dd>
        </div>
      </dl>
    </section>
  );
}
