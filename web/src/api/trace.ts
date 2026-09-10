/**
 * The client half of the trace endpoint — poll with a cursor, parse with zod.
 *
 * A cursor rather than SSE, deliberately: `Handler._send` (server.py) writes a
 * whole body with a Content-Length, an SSE connection would pin a
 * ThreadingHTTPServer thread for a whole build, and — the part that matters —
 * a cursor is REPLAYABLE. Reopening the tab or scrubbing backwards re-reads
 * the ring at any offset; a stream cannot be rewound.
 *
 * Cursor contract (fixed during Task 4, authoritative over any older prose):
 * `from` is EXCLUSIVE (`seq > cursor`). `next` is the highest `seq` returned,
 * NOT that plus one. When nothing is new, `next` is the caller's cursor
 * unchanged. So a client passes `next` straight back as `from` and receives
 * every frame exactly once — no `± 1` anywhere in this file.
 *
 * Free of React and three.js, per web/tests/architecture.test.ts.
 */
import { z } from 'zod';
import { ExplicitStrategy } from './build';

/** Ten positional numbers, in `TRACE_BUILDING_FIELDS` order (web/trace.py):
    item_id, model_index, x, y, z, yaw, recipe_id, filter_id, output_obj,
    input_obj. Targets are dense row indexes even in sampled frames; omitted
    targets and `None` are encoded as `-1`. */
export const TraceBuildingRow = z.tuple([
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
  z.number(),
]);

export const TracePhase = z.enum([
  'packed',
  'routed',
  'certified',
  'incumbent',
  'refused',
  'block',
  'recut',
  'composed',
]);

export const TraceFrame = z.object({
  seq: z.number(),
  t: z.number(),
  strategy: ExplicitStrategy,
  candidate: z.string(),
  phase: TracePhase,
  height: z.number().nullable(),
  arrangement: z.number().nullable(),
  restart: z.number().nullable(),
  stage: z.number().nullable(),
  island: z.number().nullable(),
  round: z.number().nullable(),
  block: z.number().nullable(),
  area: z.number().nullable(),
  belt_tiles: z.number().nullable(),
  incumbent: z.boolean(),
  reason: z.string().nullable(),
  bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  buildings: z.array(TraceBuildingRow),
  truncated: z.boolean(),
  stranded: z.array(z.tuple([z.number(), z.number(), z.number(), z.number()])),
  no_goods: z.array(z.array(z.number())),
});

export const TracePage = z.object({
  frames: z.array(TraceFrame),
  next: z.number(),
  /** Genuine loss only: stage-1 overflow at the parent, plus each raced arm's
      own channel drops (folded in once that arm settles). Never the ring's
      own eviction — see `evicted`. */
  dropped: z.number(),
  /** The ring's OWN eviction of its oldest frames past its bound — a rolling
      window doing its job, not data the search lost. Reported separately
      from `dropped` so a healthy build past the window size is never told it
      lost data. `.default(0)` covers callers/fixtures predating this field. */
  evicted: z.number().default(0),
  /** The collector has closed publication and this cursor has no unread frames.
      Solver job completion alone never ends trace polling. */
  complete: z.boolean(),
});

export type TraceFrame = z.infer<typeof TraceFrame>;
export type TracePage = z.infer<typeof TracePage>;

const TraceFailure = z.object({ error: z.string() });
export type TracePhase = z.infer<typeof TracePhase>;

/** One trace poll. `from` is exclusive; pass the returned `next` straight
    back on the next call — never adjust it. */
export async function pollTrace(
  id: string,
  from: number,
  signal?: AbortSignal,
): Promise<TracePage> {
  const response = await fetch(`/api/build/${encodeURIComponent(id)}/trace?from=${from}`, {
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body: unknown = await response.json();
  const failure = TraceFailure.safeParse(body);
  if (failure.success) throw new Error(failure.data.error);
  return TracePage.parse(body);
}

/** Live-tail cadence. Fixed, not the job poll's backoff (build.ts): that
    backoff exists to keep a five-minute build from making 300 requests, which
    is the opposite of what a live tail wants. No UI control, no slider — the
    sample intervals are named constants, fixed in v1. */
export const TRACE_POLL_MS = 250;
