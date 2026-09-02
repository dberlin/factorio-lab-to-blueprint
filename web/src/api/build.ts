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
import latitudeBands from '../../../src/flab2bp/dsp/data/latitude_bands.json';

const BandDimension = z.object({
  height: z.number().int().positive(),
  width: z.number().int().positive(),
});

/** Canonical request values and labels, derived from the backend's band table. */
export const BAND_OPTIONS = BandDimension.array()
  .parse(latitudeBands)
  .map(({ height, width }) => ({
    value: `${height}x${width}`,
    label: `${height} × ${width} (height × width)`,
  }));

/** Latitude-band policy accepted consistently by Python, CLI, and web. */
export const BandSelection = z.enum(['portable', ...BAND_OPTIONS.map(({ value }) => value)]);

/** Strategies accepted on every build request. */
export const RequestStrategy = z.enum(['best', 'freeform', 'sequence-pair']);

/** Strategies the server may report for an actual layout attempt or result. */
export const ExplicitStrategy = z.enum(['freeform', 'sequence-pair']);

export const ProliferatorTier = z.enum(['auto', 'none', '1', '2', '3']);

/** Named candidate policies accepted by the rate solver, in backend canonical order. */
export const CandidatePolicy = z.enum(['no-proliferator', 'all-products', 'output-products']);

const CandidatePolicySelection = z
  .array(CandidatePolicy)
  .nonempty('Select at least one candidate policy.')
  .refine((policies) => new Set(policies).size === policies.length, {
    message: 'Candidate policies must not contain duplicates.',
  });

/** Both forms of a rate: the exact one, and the one a player reads. */
const Rate = z.object({ exact: z.string(), per_minute: z.number() });

const Finding = z.object({ check: z.string(), message: z.string() });
export const ProjectionFailure = z.object({
  band: z.number(),
  check: z.string(),
  buildings: z.array(z.number()),
  detail: z.string(),
});

export const AttemptFailure = z.object({
  candidate: z.string(),
  strategy: ExplicitStrategy.nullable(),
  reason: z.string(),
  projection_failures: z.array(ProjectionFailure),
});

const Report = z.object({
  ok: z.boolean(),
  checks_run: z.array(z.string()),
  skipped: z.array(z.string()),
  errors: z.array(Finding),
  warnings: z.array(Finding),
});

/** The floor FactorioLab chose, the ceiling the save allows, and what was raised. */
const BeltTiers = z.object({
  floor: z.string(),
  ceiling: z.string(),
  runs_upgraded: z.number(),
  upgrade_tiers: z.array(z.string()),
});

/**
 * One candidate's own facts. The report panel describes the SELECTED attempt,
 * so every attempt carries its own boundary — what it belts in, what it makes,
 * what it costs — rather than inheriting the winner's.
 */
const AttemptDetail = z.object({
  machines: z.number(),
  buildings: z.number(),
  primary_band: z.number(),
  certified_bands: z.array(z.number()),
  title: z.string(),
  outputs: z.record(z.string(), Rate),
  external_inputs: z.record(z.string(), Rate),
  input_markers: z.number(),
  unmarked_inputs: z.array(z.string()),
  belt_tiers: BeltTiers,
  report: Report,
});

const Attempt = z.object({
  candidate: z.string(),
  strategy: ExplicitStrategy,
  area: z.number(),
  ok: z.boolean(),
  errors: z.number(),
  chosen: z.boolean(),
  /** Withheld for an invalid attempt unless allow_invalid was requested. */
  blueprint: z.string().nullable(),
  detail: AttemptDetail,
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
  primary_band: z.number(),
  certified_bands: z.array(z.number()),
  valid: z.boolean(),
  strategy: ExplicitStrategy,
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
  belt_tiers: BeltTiers,
  refused: z.array(AttemptFailure),
  report: Report,
  attempts: z.array(Attempt),
});

/** A refusal: which pairs were tried and each exact projection failure. */
const Refusal = z.object({ message: z.string(), attempts: z.array(AttemptFailure) });

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
  strategy: ExplicitStrategy,
  phase: z.enum(['started', 'laid-out', 'refused']),
  area: z.number().nullable(),
  ok: z.boolean().nullable(),
  reason: z.string().nullable(),
  projection_failures: z.array(ProjectionFailure),
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
export type ProjectionFailure = z.infer<typeof ProjectionFailure>;
export type AttemptDetail = z.infer<typeof AttemptDetail>;
export type AttemptFailure = z.infer<typeof AttemptFailure>;

export const BuildOptions = z
  .object({
    url: z.string(),
    strategy: RequestStrategy,
    candidate_policies: CandidatePolicySelection,
    budget_s: z.number(),
    proliferator_tier: ProliferatorTier,
    band: BandSelection,
    name: z.string(),
    allow_invalid: z.boolean(),
    fetch_flow: z.boolean(),
    /** A FactorioLab flow export's CSV text. Empty means the recipe selection is
      derived rather than pinned, which the report says out loud. */
    flow: z.string(),
  })
  .strict();

export type BandSelection = z.infer<typeof BandSelection>;
export type CandidatePolicy = z.infer<typeof CandidatePolicy>;
export type BuildOptions = z.infer<typeof BuildOptions>;
export type RequestStrategy = z.infer<typeof RequestStrategy>;
export type ExplicitStrategy = z.infer<typeof ExplicitStrategy>;
export type ProliferatorTier = z.infer<typeof ProliferatorTier>;

export const DEFAULT_OPTIONS: BuildOptions = {
  url: '',
  strategy: 'best',
  candidate_policies: ['all-products', 'output-products', 'no-proliferator'],
  budget_s: 15,
  proliferator_tier: 'auto',
  name: '',
  band: 'portable',
  // Off by default, exactly as the CLI has it: a blueprint that pastes cleanly
  // and then does not run is the worst outcome available here.
  allow_invalid: false,
  fetch_flow: false,
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
      return String(parsed.error);
    }
  } catch {
    // Not JSON; the body is already the best message available.
  }
  return text.trim() || `HTTP ${response.status}`;
}

/** Submits a build. Resolves once it has an id, NOT once it has a blueprint. */
export async function submitBuild(options: BuildOptions, signal?: AbortSignal): Promise<Job> {
  const request = BuildOptions.parse(options);
  const response = await fetch('/api/build', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request),
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
