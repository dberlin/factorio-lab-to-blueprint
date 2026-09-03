/**
 * Fixtures shaped like what `flab2bp.web.payload.describe` actually emits.
 *
 * Hand-written rather than captured, but the zod schema in `src/api/build.ts`
 * parses every response, so a fixture that drifts from the Python payload fails
 * the same way a real response would.
 */
import { readFileSync } from 'node:fs';
import type { Attempt, AttemptDetail, BuildResult, Job } from '../../src/api/build';

/**
 * A real DSP blueprint string, so a test that hands one to the renderer is
 * exercising the render rather than a parse failure.
 */
export const A_BLUEPRINT = readFileSync(
  'tests/fixtures/new-planet-establishment-polar-buildings-calldown-for-mass-production.txt',
  'utf8',
).trim();

/** A second real blueprint whose parsed model is visibly distinct in selection tests. */
export const B_BLUEPRINT = readFileSync(
  'tests/fixtures/factory-quick-start-step-3-red-cube.txt',
  'utf8',
).trim();

export function anAttemptDetail(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    machines: 9,
    buildings: 42,
    primary_band: 160,
    certified_bands: [160, 200],
    title: 'electromagnetic-matrix 60/min',
    outputs: { 'electromagnetic-matrix': { exact: '1', per_minute: 60 } },
    external_inputs: { 'magnetic-coil': { exact: '5/6', per_minute: 50 } },
    input_markers: 1,
    unmarked_inputs: [],
    belt_tiers: {
      floor: 'conveyor-belt-1',
      ceiling: 'conveyor-belt-1',
      runs_upgraded: 0,
      upgrade_tiers: [],
    },
    report: { ok: true, checks_run: ['power'], skipped: [], errors: [], warnings: [] },
    ...overrides,
  };
}

export function anAttempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    candidate: 'no-proliferator',
    strategy: 'freeform',
    area: 575,
    ok: true,
    errors: 0,
    chosen: true,
    blueprint: A_BLUEPRINT,
    detail: anAttemptDetail(),
    ...overrides,
  };
}

export function aResult(overrides: Partial<BuildResult> = {}): BuildResult {
  const blueprint = overrides.blueprint === undefined ? A_BLUEPRINT : overrides.blueprint;
  const base: Omit<BuildResult, 'attempts'> = {
    blueprint,
    valid: true,
    strategy: 'freeform',
    candidate: 'no-proliferator',
    machines: 9,
    area: 575,
    primary_band: 160,
    certified_bands: [160, 200],
    buildings: 42,
    title: 'electromagnetic-matrix 60/min',
    description: 'flab2bp freeform layout',
    outputs: { 'electromagnetic-matrix': { exact: '1', per_minute: 60 } },
    external_inputs: { 'magnetic-coil': { exact: '5/6', per_minute: 50 } },
    input_markers: 1,
    unmarked_inputs: [] as string[],
    flow_pinned: false,
    flow_findings: [] as string[],
    belt_rules: { max_z: 26.55, lab_level: 9, vertical_construction: true, from_url: false },
    belt_tiers: {
      floor: 'conveyor-belt-1',
      ceiling: 'conveyor-belt-1',
      runs_upgraded: 0,
      upgrade_tiers: [],
    },
    refused: [] as BuildResult['refused'],
    report: { ok: true, checks_run: ['power'], skipped: [], errors: [], warnings: [] },
  };
  const merged: Omit<BuildResult, 'attempts'> = { ...base, ...overrides };
  // The top level describes the chosen attempt, so the fixture keeps them
  // equal — exactly what `flab2bp.web.payload.describe` emits.
  return {
    ...merged,
    attempts: [
      anAttempt({
        blueprint,
        area: merged.area,
        detail: anAttemptDetail({
          machines: merged.machines,
          buildings: merged.buildings,
          primary_band: merged.primary_band,
          certified_bands: merged.certified_bands,
          title: merged.title,
          outputs: merged.outputs,
          external_inputs: merged.external_inputs,
          input_markers: merged.input_markers,
          unmarked_inputs: merged.unmarked_inputs,
          belt_tiers: merged.belt_tiers,
          report: merged.report,
        }),
      }),
    ],
  };
}

export interface Scripted {
  status?: number;
  body: unknown;
}

const realFetch = globalThis.fetch;

/**
 * Scripts `fetch`, answering each call with the next response and repeating the
 * last one thereafter — which is what a poll loop needs.  Returns the calls, so
 * a test can assert what was sent as well as what came back.
 */
export function serving(...responses: Scripted[]): Array<{ url: string; init?: RequestInit }> {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let index = 0;
  const scriptedFetch = Object.assign(
    (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]): Promise<Response> => {
      const url = input instanceof Request ? input.url : input.toString();
      calls.push({ url, init });
      const next = responses[Math.min(index++, responses.length - 1)];
      if (!next) throw new Error('serving() was given no responses');
      return Promise.resolve(
        new Response(typeof next.body === 'string' ? next.body : JSON.stringify(next.body), {
          status: next.status ?? 200,
          headers: { 'content-type': 'application/json' },
        }),
      );
    },
    { preconnect: realFetch.preconnect },
  ) satisfies typeof fetch;
  globalThis.fetch = scriptedFetch;
  return calls;
}

export function restoreFetch(): void {
  globalThis.fetch = realFetch;
}

export function aJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'abc123',
    state: 'done',
    elapsed_s: 1.2,
    solver_ceiling_s: 6,
    progress: null,
    settled: [],
    result: aResult(),
    refusal: null,
    error: null,
    ...overrides,
  };
}
