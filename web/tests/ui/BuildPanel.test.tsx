import { afterEach, expect, test } from '@rstest/core';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { BuildPanel } from '../../src/ui/BuildPanel';
import { A_BLUEPRINT, aJob, aResult, restoreFetch, serving } from '../support/build';
import { realCatalog } from '../support/catalog';

afterEach(restoreFetch);

/** Reports what the provider was handed, so auto-render can be asserted on. */
function Probe() {
  const { blueprint } = useBlueprint();
  return <span data-testid="loaded">{blueprint ? blueprint.buildings.length : 'none'}</span>;
}

const mount = () =>
  render(
    <BlueprintProvider catalog={realCatalog}>
      <BuildPanel />
      <Probe />
    </BlueprintProvider>,
  );

function build(url = 'https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11') {
  fireEvent.change(screen.getByLabelText('FactorioLab URL'), { target: { value: url } });
  fireEvent.click(screen.getByRole('button', { name: 'Build' }));
}

test('build is disabled until there is a URL', () => {
  mount();
  expect(screen.getByRole('button', { name: 'Build' })).toBeDisabled();
});

test('automatic flow fetch is off by default and is submitted when selected', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  const fetchFlow = screen.getByRole('checkbox', {
    name: 'Fetch FactorioLab flow automatically',
  });
  expect(fetchFlow).not.toBeChecked();

  fireEvent.click(fetchFlow);
  build();
  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.fetch_flow).toBe(true);
  expect(body.flow).toBe('');
});

test('automatic fetch and supplied CSV cannot both be selected', () => {
  mount();
  const fetchFlow = screen.getByRole('checkbox', {
    name: 'Fetch FactorioLab flow automatically',
  });
  const text = screen.getByTestId('flow-text');
  const file = screen.getByTestId('flow-file');

  fireEvent.change(text, { target: { value: 'Recipes\nid,name\n' } });
  expect(fetchFlow).toBeDisabled();
  expect(text).toHaveValue('Recipes\nid,name\n');

  fireEvent.change(text, { target: { value: '' } });
  fireEvent.click(fetchFlow);
  expect(text).toBeDisabled();
  expect(file).toBeDisabled();
});

test('a file read that finishes after automatic fetch was selected remains mutually exclusive', async () => {
  mount();
  const fetchFlow = screen.getByRole('checkbox', {
    name: 'Fetch FactorioLab flow automatically',
  });
  const text = screen.getByTestId('flow-text');
  const fileInput = screen.getByTestId('flow-file');
  const file = new File([''], 'flow.csv', { type: 'text/csv' });
  let finishRead = (_value: string) => {};
  Object.defineProperty(file, 'text', {
    value: () =>
      new Promise<string>((resolve) => {
        finishRead = resolve;
      }),
  });

  fireEvent.change(fileInput, { target: { files: [file] } });
  fireEvent.click(fetchFlow);
  expect(fetchFlow).toBeChecked();

  await act(async () => finishRead('Recipes\nid,name\n'));
  expect(fetchFlow).not.toBeChecked();
  expect(text).toHaveValue('Recipes\nid,name\n');
});

test('a finished build shows the string and renders it without a second click', async () => {
  serving({ status: 202, body: aJob({ result: aResult({ blueprint: A_BLUEPRINT }) }) });
  mount();
  build();

  await waitFor(() => expect(screen.getByTestId('blueprint-string')).toHaveValue(A_BLUEPRINT));
  // The point of having the viewer in the same page: no copy-paste step.
  await waitFor(() => expect(screen.getByTestId('loaded')).not.toHaveTextContent('none'));
});

test('an unpinned report offers both automatic fetch and a supplied flow', async () => {
  serving({ status: 202, body: aJob({ result: aResult({ flow_pinned: false }) }) });
  mount();
  build();

  const report = await screen.findByTestId('build-report');
  expect(report).toHaveTextContent('Select automatic flow fetch above');
  expect(report).toHaveTextContent('paste or upload a flow export');
  expect(report).not.toHaveTextContent('is not offered here');
});

test('a refusal is shown as a result, with one line per pair', async () => {
  serving({
    status: 202,
    body: aJob({
      state: 'refused',
      result: null,
      refusal: {
        message: 'no valid layout for no-proliferator after 2s',
        attempts: [
          {
            candidate: 'no-proliferator',
            strategy: 'sequence-pair',
            reason: 'too tall; exact projection failed',
            projection_failures: [
              {
                band: 160,
                check: 'geom.collide',
                buildings: [4, 9],
                detail: 'first collision; left machine; right machine',
              },
              {
                band: 200,
                check: 'game.power_too_close',
                buildings: [2, 7],
                detail: 'power envelopes; north; south',
              },
            ],
          },
          {
            candidate: 'max-proliferation',
            strategy: 'freeform',
            reason: 'unroutable',
            projection_failures: [],
          },
        ],
      },
    }),
  });
  mount();
  build();

  const refusal = await screen.findByTestId('refusal');
  expect(refusal).toHaveTextContent(
    'sequence-pair / no-proliferator: too tall; exact projection failed',
  );
  expect(refusal).toHaveTextContent(
    'band 160 — geom.collide — buildings 4, 9 — first collision; left machine; right machine',
  );
  expect(refusal).toHaveTextContent(
    'band 200 — game.power_too_close — buildings 2, 7 — power envelopes; north; south',
  );
  expect(refusal).toHaveTextContent('freeform / max-proliferation: unroutable');
  // Not an alert: a refusal is an answer, and nothing should announce a failure.
  expect(screen.queryByRole('alert')).toBeNull();
});

test('a bad URL is an error, and is distinct from a refusal', async () => {
  serving({
    status: 202,
    body: aJob({ state: 'error', result: null, error: 'that is not a FactorioLab URL' }),
  });
  mount();
  build('nonsense');

  expect(await screen.findByRole('alert')).toHaveTextContent('that is not a FactorioLab URL');
  expect(screen.queryByTestId('refusal')).toBeNull();
});

test('a 400 from the server is shown rather than swallowed', async () => {
  serving({ status: 400, body: { error: "'candidates' must be an integer from 1 to 8" } });
  mount();
  build();
  expect(await screen.findByRole('alert')).toHaveTextContent("'candidates' must be an integer");
});

test('an invalid build withholds the string and offers it explicitly', async () => {
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
  mount();
  build();

  await screen.findByTestId('validation-errors');
  expect(screen.queryByTestId('blueprint-string')).toBeNull();
  // Nothing was rendered either: an invalid layout is not shown as if it works.
  expect(screen.getByTestId('loaded')).toHaveTextContent('none');
  expect(screen.getByRole('button', { name: /Build it anyway/ })).toBeInTheDocument();
});

test('progress says where the job is while it is still running', async () => {
  serving(
    { status: 202, body: aJob({ state: 'queued', result: null, queue_position: 2 }) },
    { body: aJob({ state: 'running', result: null, elapsed_s: 3.5, solver_ceiling_s: 6 }) },
    { body: aJob() },
  );
  mount();
  build();

  await waitFor(() => expect(screen.getByTestId('progress')).toHaveTextContent('2 build(s) ahead'));
  await waitFor(() => expect(screen.getByTestId('progress')).toHaveTextContent('3.5s elapsed'));
});

test('latitude band defaults to portable and submits a changed selection', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  const band = screen.getByLabelText('Latitude band');
  expect(band).toHaveValue('portable');
  expect(band).toHaveTextContent('Portable (smallest + up to two wider)');

  fireEvent.change(band, { target: { value: '160' } });
  build();

  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.band).toBe('160');
});

test('the strategy choices are exactly the production strategy set', () => {
  mount();
  const strategy = screen.getByLabelText('Strategy');
  expect(strategy).toHaveTextContent('best');
  expect(strategy).toHaveTextContent('freeform');
  expect(strategy).toHaveTextContent('sequence-pair');
});

test('proliferator tier exposes auto and every spray tier', () => {
  mount();
  const tier = screen.getByLabelText('Proliferator tier');
  expect(tier).toHaveTextContent('URL selection');
  expect(tier).toHaveTextContent('None');
  expect(tier).toHaveTextContent('Mk.I');
  expect(tier).toHaveTextContent('Mk.II');
  expect(tier).toHaveTextContent('Mk.III');
});

test.each([
  ['None', 'none'],
  ['Mk.II', '2'],
  ['Mk.III', '3'],
])('submits an explicit %s proliferation tier', async (_label, tier) => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  fireEvent.change(screen.getByLabelText('Proliferator tier'), {
    target: { value: tier },
  });
  build();

  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.proliferator_tier).toBe(tier);
});

test('the budget copy matches the two active best strategies', () => {
  mount();
  // Defaults: 3 candidates x 2 active production strategies x 15s.
  expect(screen.getByText(/up to 90s of solving/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Strategy'), {
    target: { value: 'sequence-pair' },
  });
  expect(screen.getByText(/up to 45s of solving/)).toBeInTheDocument();
});

test('the blueprint title is what the game will show, and it names the product', async () => {
  serving({
    status: 202,
    body: aJob({ result: aResult({ title: 'space-warper 10/min (max prolif)' }) }),
  });
  mount();
  build();

  await waitFor(() =>
    expect(screen.getByTestId('blueprint-title')).toHaveTextContent(
      'space-warper 10/min (max prolif)',
    ),
  );
});

test('the copy button says what it copies', async () => {
  serving({ status: 202, body: aJob({ result: aResult({ blueprint: A_BLUEPRINT }) }) });
  mount();
  build();

  const button = await screen.findByRole('button', { name: 'Copy blueprint string' });
  expect(button).toBeInTheDocument();
});

test('a build that has reached the layout loop counts pairs, not seconds', async () => {
  // Two settled, a third in flight: the bar is 2/3 because two pairs are DONE,
  // not because two thirds of some clock has passed.
  serving(
    {
      status: 202,
      body: aJob({
        state: 'running',
        result: null,
        elapsed_s: 9,
        solver_ceiling_s: 6,
        progress: {
          index: 3,
          total: 3,
          candidate: 'max-proliferation',
          strategy: 'freeform',
          phase: 'started',
          area: null,
          ok: null,
          reason: null,
          projection_failures: [],
        },
        settled: [
          {
            index: 1,
            total: 3,
            candidate: 'no-proliferator',
            strategy: 'freeform',
            phase: 'refused',
            area: null,
            ok: null,
            reason: 'nothing fits under the belt ceiling',
            projection_failures: [
              {
                band: 160,
                check: 'geom.collide',
                buildings: [4, 9],
                detail: 'blocked; west; east',
              },
            ],
          },
          {
            index: 2,
            total: 3,
            candidate: 'max-proliferation',
            strategy: 'freeform',
            phase: 'laid-out',
            area: 2006,
            ok: true,
            reason: null,
            projection_failures: [],
          },
        ],
      }),
    },
    { status: 200, body: aJob() },
  );
  mount();
  build();

  const progress = await screen.findByTestId('progress');
  expect(progress).toHaveTextContent('Laying out 3 of 3: max-proliferation / freeform');
  // The pair that gave up stays on screen while the next one runs.
  expect(screen.getByTestId('settled')).toHaveTextContent(
    'no layout — nothing fits under the belt ceiling',
  );
  expect(screen.getByTestId('settled')).toHaveTextContent(
    'band 160 — geom.collide — buildings 4, 9 — blocked; west; east',
  );
  expect(screen.getByTestId('settled')).toHaveTextContent('2006 tiles, valid');
  expect(progress.querySelector('.fill')).toHaveStyle({ width: '66.7%' });
});

test('before the layout loop starts there is nothing to count, and it says so', async () => {
  serving(
    {
      status: 202,
      body: aJob({ state: 'running', result: null, elapsed_s: 2, progress: null, settled: [] }),
    },
    { status: 200, body: aJob() },
  );
  mount();
  build();

  const progress = await screen.findByTestId('progress');
  expect(progress).toHaveTextContent('Reading the URL and solving the rates');
});

test('warnings from a VALID build are shown, not swallowed by the string being emitted', async () => {
  serving({
    status: 202,
    body: aJob({
      result: aResult({
        report: {
          ok: true,
          checks_run: ['belt.termination'],
          skipped: [],
          errors: [],
          warnings: [
            {
              check: 'belt.termination',
              message: 'belt run 14 runs 118 tiles and never terminates',
            },
            {
              check: 'flow.external_entry_points',
              message: "'copper-ingot' is belted in at 2 separate lanes",
            },
          ],
        },
      }),
    }),
  });
  mount();
  build();

  const warnings = await screen.findByTestId('validation-warnings');
  expect(warnings).toHaveTextContent('2 warning(s)');
  expect(warnings).toHaveTextContent('belt run 14 runs 118 tiles and never terminates');
  expect(warnings).toHaveTextContent("'copper-ingot' is belted in at 2 separate lanes");
});

/**
 * A refusal keeps the previous blueprint on the canvas, which is right —
 * clearing it would throw away the thing you were looking at. What is not
 * right is the label above it going on naming a result that a refusal has
 * since superseded, so the provider marks it stale and the Toolbar says so.
 */
test('a refusal marks the blueprint on screen as the previous build', async () => {
  const Staleness = () => {
    const { stale, blueprint } = useBlueprint();
    return (
      <span data-testid="staleness">{blueprint ? (stale ? 'stale' : 'current') : 'empty'}</span>
    );
  };
  render(
    <BlueprintProvider catalog={realCatalog}>
      <BuildPanel />
      <Staleness />
    </BlueprintProvider>,
  );

  serving({ status: 202, body: aJob({ result: aResult({ blueprint: A_BLUEPRINT }) }) });
  build();
  await waitFor(() => expect(screen.getByTestId('staleness')).toHaveTextContent('current'));

  restoreFetch();
  serving({
    status: 202,
    body: aJob({
      state: 'refused',
      result: null,
      refusal: {
        message: 'no valid layout',
        attempts: [
          {
            candidate: 'x',
            strategy: 'freeform',
            reason: 'unroutable',
            projection_failures: [],
          },
        ],
      },
    }),
  });
  build();
  await screen.findByTestId('refusal');
  // Still rendered — and no longer claiming to be the current result.
  await waitFor(() => expect(screen.getByTestId('staleness')).toHaveTextContent('stale'));
});
