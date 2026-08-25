import { afterEach, expect, test } from '@rstest/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

test('a finished build shows the string and renders it without a second click', async () => {
  serving({ status: 202, body: aJob({ result: aResult({ blueprint: A_BLUEPRINT }) }) });
  mount();
  build();

  await waitFor(() => expect(screen.getByTestId('blueprint-string')).toHaveValue(A_BLUEPRINT));
  // The point of having the viewer in the same page: no copy-paste step.
  await waitFor(() => expect(screen.getByTestId('loaded')).not.toHaveTextContent('none'));
});

test('a refusal is shown as a result, with one line per pair', async () => {
  serving({
    status: 202,
    body: aJob({
      state: 'refused',
      result: null,
      refusal: {
        message: 'no valid layout for no-proliferator after 2s',
        reasons: ['spine/no-proliferator: too tall', 'freeform/no-proliferator: unroutable'],
      },
    }),
  });
  mount();
  build();

  const refusal = await screen.findByTestId('refusal');
  expect(refusal).toHaveTextContent('spine/no-proliferator: too tall');
  expect(refusal).toHaveTextContent('freeform/no-proliferator: unroutable');
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
    { body: aJob({ state: 'running', result: null, elapsed_s: 3.5, solver_ceiling_s: 12 }) },
    { body: aJob() },
  );
  mount();
  build();

  await waitFor(() => expect(screen.getByTestId('progress')).toHaveTextContent('2 build(s) ahead'));
  await waitFor(() => expect(screen.getByTestId('progress')).toHaveTextContent('3.5s elapsed'));
});

test('the time it warns about is the product, not the per-layout budget', () => {
  mount();
  // Defaults: 3 candidates x best (2 strategies) x 2s.
  expect(screen.getByText(/up to 12s of solving/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'spine' } });
  expect(screen.getByText(/up to 6s of solving/)).toBeInTheDocument();
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
  // Two settled, a third in flight: the bar is 2/6 because two pairs are DONE,
  // not because a third of some clock has passed.
  serving(
    {
      status: 202,
      body: aJob({
        state: 'running',
        result: null,
        elapsed_s: 9,
        solver_ceiling_s: 60,
        progress: {
          index: 3,
          total: 6,
          candidate: 'max-proliferation',
          strategy: 'spine',
          phase: 'started',
          area: null,
          ok: null,
          reason: null,
        },
        settled: [
          {
            index: 1,
            total: 6,
            candidate: 'no-proliferator',
            strategy: 'spine',
            phase: 'refused',
            area: null,
            ok: null,
            reason: 'nothing fits under the belt ceiling',
          },
          {
            index: 2,
            total: 6,
            candidate: 'no-proliferator',
            strategy: 'freeform',
            phase: 'laid-out',
            area: 2006,
            ok: true,
            reason: null,
          },
        ],
      }),
    },
    { status: 200, body: aJob() },
  );
  mount();
  build();

  const progress = await screen.findByTestId('progress');
  expect(progress).toHaveTextContent('Laying out 3 of 6: max-proliferation / spine');
  // The pair that gave up stays on screen while the next one runs.
  expect(screen.getByTestId('settled')).toHaveTextContent(
    'no layout — nothing fits under the belt ceiling',
  );
  expect(screen.getByTestId('settled')).toHaveTextContent('2006 tiles, valid');
  expect(progress.querySelector('.fill')).toHaveStyle({ width: '33.3%' });
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
