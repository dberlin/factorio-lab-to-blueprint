/**
 * The client half of `flab2bp.web` — submit a build, then poll it.
 *
 * A build is seconds to minutes, so there is no request here that waits for
 * one. `submitBuild` returns as soon as the job has an id; `pollBuild` reports
 * where it is until it settles.
 *
 * The response is parsed through zod rather than cast. The Python and the
 * TypeScript describe the same object in two places, and a schema is the only
 * thing that notices when one of them changes and the other does not — a cast
 * would hand `undefined` to the renderer and blame the blueprint.
 *
 * Deliberately free of React and three.js, so it can be tested without either.
 */
import { z } from 'zod';

/** Both forms of a rate: the exact one, and the one a player reads. */
const Rate = z.object({ exact: z.string(), per_minute: z.number() });

const Finding = z.object({ check: z.string(), message: z.string() });

const Attempt = z.object({
  candidate: z.string(),
  strategy: z.string(),
  area: z.number(),
  ok: z.boolean(),
  errors: z.number(),
  chosen: z.boolean(),
});

/** How high a belt may go here, and whether that was read or assumed. */
const BeltRules = z.object({
  max_z: z.number(),
  lab_level: z.number(),
  vertical_construction: z.boolean(),
  from_url: z.boolean(),
});

const BuildResult = z.object({
  /** Null when validation failed and the caller did not pass allow_invalid. */
  blueprint: z.string().nullable(),
  valid: z.boolean(),
  strategy: z.string(),
  candidate: z.string(),
  machines: z.number(),
  area: z.number(),
  buildings: z.number(),
  title: z.string(),
  description: z.string(),
  outputs: z.record(z.string(), Rate),
  external_inputs: z.record(z.string(), Rate),
  input_markers: z.number(),
  unmarked_inputs: z.array(z.string()),
  flow_pinned: z.boolean(),
  flow_findings: z.array(z.string()),
  belt_rules: BeltRules.nullable(),
  refused: z.array(z.string()),
  report: z.object({
    ok: z.boolean(),
    checks_run: z.array(z.string()),
    skipped: z.array(z.string()),
    errors: z.array(Finding),
    warnings: z.array(Finding),
  }),
  attempts: z.array(Attempt),
});

/** A refusal: which pairs were tried, and why each gave up. */
const Refusal = z.object({ message: z.string(), reasons: z.array(z.string()) });

/**
 * One (candidate, strategy) pair, as `pipeline.build` starts it and as it
 * settles. This is real progress rather than elapsed time — the pipeline says
 * which pair it is on, so the bar moves when work finishes, not when the clock
 * does.
 */
const Step = z.object({
  index: z.number(),
  total: z.number(),
  candidate: z.string(),
  strategy: z.string(),
  phase: z.enum(['started', 'laid-out', 'refused']),
  area: z.number().nullable(),
  ok: z.boolean().nullable(),
  reason: z.string().nullable(),
});

const Job = z.object({
  id: z.string(),
  state: z.enum(['queued', 'running', 'done', 'refused', 'error']),
  elapsed_s: z.number(),
  /** A ceiling on solver time, not a promise of a finish time. */
  solver_ceiling_s: z.number(),
  queue_position: z.number().optional(),
  /** Null until the first layout starts: the URL parse and the rate solve
      come first, and nothing knows how long those take. */
  progress: Step.nullable(),
  /** Pairs that have already ended, newest last. */
  settled: z.array(Step),
  result: BuildResult.nullable(),
  refusal: Refusal.nullable(),
  error: z.string().nullable(),
});

export type Job = z.infer<typeof Job>;
export type Step = z.infer<typeof Step>;
export type BuildResult = z.infer<typeof BuildResult>;
export type Refusal = z.infer<typeof Refusal>;
export type Attempt = z.infer<typeof Attempt>;

export interface BuildOptions {
  url: string;
  strategy: 'best' | 'spine' | 'freeform';
  candidates: number;
  budget_s: number;
  power: boolean;
  name: string;
  allow_invalid: boolean;
  /** A FactorioLab flow export's CSV text. Empty means the recipe selection is
      derived rather than pinned, which the report says out loud. */
  flow: string;
}

export const DEFAULT_OPTIONS: BuildOptions = {
  url: '',
  strategy: 'best',
  candidates: 3,
  budget_s: 2,
  power: true,
  name: '',
  // Off by default, exactly as the CLI has it: a blueprint that pastes cleanly
  // and then does not run is the worst outcome available here.
  allow_invalid: false,
  flow: '',
};

/** A job has settled when it will never change again. */
export function isSettled(job: Job): boolean {
  return job.state === 'done' || job.state === 'refused' || job.state === 'error';
}

/** The server said no before anything was attempted — a bad request, not a refusal. */
export class BuildRequestError extends Error {}

async function reason(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && 'error' in parsed) {
      return String((parsed as { error: unknown }).error);
    }
  } catch {
    // Not JSON; the body is already the best message available.
  }
  return text.trim() || `HTTP ${response.status}`;
}

/** Submits a build. Resolves once it has an id, NOT once it has a blueprint. */
export async function submitBuild(options: BuildOptions, signal?: AbortSignal): Promise<Job> {
  const response = await fetch('/api/build', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(options),
    signal,
  });
  if (!response.ok) throw new BuildRequestError(await reason(response));
  return Job.parse(await response.json());
}

/** One poll. Throws if the job is unknown — it may have aged out of the history. */
export async function pollBuild(id: string, signal?: AbortSignal): Promise<Job> {
  const response = await fetch(`/api/build/${encodeURIComponent(id)}`, { signal });
  if (!response.ok) throw new BuildRequestError(await reason(response));
  return Job.parse(await response.json());
}

/** First poll delay, and the ceiling it backs off to, in milliseconds. */
const FIRST_POLL_MS = 300;
const MAX_POLL_MS = 2000;

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    // Checked before the listener is attached: an `abort` that already happened
    // fires no event, so a signal aborted during the previous poll would
    // otherwise be ignored and the loop would sleep out its full delay.
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });

/**
 * Submits and then polls until the job settles, reporting each snapshot.
 *
 * Backs off from {@link FIRST_POLL_MS} to {@link MAX_POLL_MS}: a small build
 * settles in under a second and should not wait two, while a five-minute one
 * does not need three hundred polls to say it is still solving.
 */
export async function runBuild(
  options: BuildOptions,
  onProgress: (job: Job) => void,
  signal?: AbortSignal,
): Promise<Job> {
  let job = await submitBuild(options, signal);
  onProgress(job);
  let delay = FIRST_POLL_MS;
  while (!isSettled(job)) {
    await wait(delay, signal);
    delay = Math.min(delay * 1.5, MAX_POLL_MS);
    job = await pollBuild(job.id, signal);
    onProgress(job);
  }
  return job;
}
