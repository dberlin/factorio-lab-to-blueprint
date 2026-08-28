import { afterEach, expect, test } from '@rstest/core';
import {
  BuildOptions,
  BuildRequestError,
  DEFAULT_OPTIONS,
  isSettled,
  pollBuild,
  runBuild,
  submitBuild,
} from '../../src/api/build';
import { aJob, aResult, restoreFetch, serving } from '../support/build';

afterEach(restoreFetch);

test('submit posts sequence-pair with its exact wire spelling', async () => {
  const calls = serving({ status: 202, body: aJob({ state: 'queued', result: null }) });
  const job = await submitBuild({
    ...DEFAULT_OPTIONS,
    url: 'https://example.invalid/x',
    strategy: 'sequence-pair',
  });

  expect(job.state).toBe('queued');
  expect(calls[0]?.url).toBe('/api/build');
  const body = BuildOptions.parse(JSON.parse(String(calls[0]?.init?.body)));
  expect(body.url).toBe('https://example.invalid/x');
  expect(body.strategy).toBe('sequence-pair');
  expect(body.proliferator_tier).toBe('auto');

  await submitBuild({ ...DEFAULT_OPTIONS, proliferator_tier: '1' });
  const explicit = BuildOptions.parse(JSON.parse(String(calls[1]?.init?.body)));
  expect(explicit.proliferator_tier).toBe('1');
});

test('submit rejects an unknown strategy before making a request', async () => {
  const calls = serving({ status: 202, body: aJob() });
  const pending = Reflect.apply(submitBuild, undefined, [
    { ...DEFAULT_OPTIONS, strategy: 'unknown' },
  ]);
  await expect(pending).rejects.toThrow();
  expect(calls).toHaveLength(0);
});

test('a 400 becomes a BuildRequestError carrying the reason', async () => {
  serving({ status: 400, body: { error: "'url' is required" } });
  await expect(submitBuild(DEFAULT_OPTIONS)).rejects.toThrow(BuildRequestError);
  serving({ status: 400, body: { error: "'url' is required" } });
  await expect(submitBuild(DEFAULT_OPTIONS)).rejects.toThrow("'url' is required");
});

test('an unknown job id is an error, not a silent null', async () => {
  serving({ status: 404, body: { error: 'no such job' } });
  await expect(pollBuild('nope')).rejects.toThrow('no such job');
});

test('a payload that has drifted from the schema is rejected rather than rendered', async () => {
  // The whole reason the response is parsed and not cast: a missing field
  // would otherwise reach the renderer as `undefined` and read as a bad
  // blueprint rather than as a version mismatch.
  serving({ status: 200, body: { id: 'x', state: 'done' } });
  await expect(pollBuild('x')).rejects.toThrow();
});

test('response strategies are limited to active explicit web choices', async () => {
  serving({
    status: 200,
    body: { ...aJob(), result: { ...aResult(), strategy: 'unknown' } },
  });
  await expect(pollBuild('x')).rejects.toThrow();
});

test('sequence-pair is accepted as an explicit response strategy', async () => {
  const result = aResult({
    strategy: 'sequence-pair',
    attempts: [
      {
        candidate: 'no-proliferator',
        strategy: 'sequence-pair',
        area: 575,
        ok: true,
        errors: 0,
        chosen: true,
      },
    ],
  });
  serving({ status: 200, body: aJob({ result }) });
  const job = await pollBuild('x');
  expect(job.result?.strategy).toBe('sequence-pair');
});

test('runBuild polls until the job settles and reports every snapshot', async () => {
  serving(
    { status: 202, body: aJob({ state: 'queued', result: null, elapsed_s: 0 }) },
    { body: aJob({ state: 'running', result: null, elapsed_s: 0.4 }) },
    { body: aJob({ state: 'done' }) },
  );

  const seen: string[] = [];
  const settled = await runBuild({ ...DEFAULT_OPTIONS, url: 'x' }, (job) => seen.push(job.state));

  expect(seen).toEqual(['queued', 'running', 'done']);
  expect(settled.result?.blueprint).toBeTruthy();
});

test('a refusal settles the job like any other answer', async () => {
  serving({
    status: 202,
    body: aJob({
      state: 'refused',
      result: null,
      refusal: { message: 'no valid layout', reasons: ['freeform/a: too tall'] },
    }),
  });
  const settled = await runBuild({ ...DEFAULT_OPTIONS, url: 'x' }, () => {});
  expect(settled.state).toBe('refused');
  expect(settled.refusal?.reasons).toEqual(['freeform/a: too tall']);
});

test('aborting stops the poll loop', async () => {
  serving({ status: 202, body: aJob({ state: 'running', result: null }) });
  const controller = new AbortController();
  const pending = runBuild(
    { ...DEFAULT_OPTIONS, url: 'x' },
    () => controller.abort(),
    controller.signal,
  );
  await expect(pending).rejects.toBeDefined();
});

test('isSettled agrees with the states the server can end in', () => {
  expect(isSettled(aJob({ state: 'queued' }))).toBe(false);
  expect(isSettled(aJob({ state: 'running' }))).toBe(false);
  for (const state of ['done', 'refused', 'error'] as const) {
    expect(isSettled(aJob({ state }))).toBe(true);
  }
});

test('an invalid build carries a null blueprint, not a missing field', async () => {
  serving({
    status: 202,
    body: aJob({
      result: aResult({
        blueprint: null,
        valid: false,
        report: {
          ok: false,
          checks_run: ['power'],
          skipped: [],
          errors: [{ check: 'power', message: 'a machine has no tower in range' }],
          warnings: [],
        },
      }),
    }),
  });
  const settled = await runBuild({ ...DEFAULT_OPTIONS, url: 'x' }, () => {});
  expect(settled.result?.blueprint).toBeNull();
  expect(settled.result?.valid).toBe(false);
});
