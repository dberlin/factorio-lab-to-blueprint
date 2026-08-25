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
