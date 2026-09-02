import { afterEach, expect, test } from '@rstest/core';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { BuildPanel } from '../../src/ui/BuildPanel';
import { parseBlueprint } from '../../src/format';
import {
  A_BLUEPRINT,
  B_BLUEPRINT,
  aJob,
  anAttempt,
  anAttemptDetail,
  aResult,
  restoreFetch,
  serving,
} from '../support/build';
import { realCatalog } from '../support/catalog';

afterEach(restoreFetch);

/** Reports the exact parsed blueprint handed to the viewer state. */
function Probe() {
  const { blueprint } = useBlueprint();
  return (
    <span data-testid="loaded" data-blueprint-title={blueprint?.header.shortDesc ?? ''}>
      {blueprint ? blueprint.buildings.length : 'none'}
    </span>
  );
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

function candidateResult(chosenBlueprint = A_BLUEPRINT, alternativeBlueprint = B_BLUEPRINT) {
  return {
    ...aResult({ blueprint: chosenBlueprint }),
    attempts: [
      anAttempt({ blueprint: chosenBlueprint }),
      anAttempt({
        candidate: 'all-products',
        strategy: 'sequence-pair',
        area: 640,
        chosen: false,
        blueprint: alternativeBlueprint,
        detail: anAttemptDetail({
          machines: 13,
          buildings: 51,
          primary_band: 200,
          certified_bands: [200],
          title: 'electromagnetic-matrix 60/min (all products)',
          external_inputs: {
            'magnetic-coil': { exact: '5/6', per_minute: 50 },
            'proliferator-mk-iii': { exact: '1', per_minute: 60 },
          },
          input_markers: 2,
        }),
      }),
      anAttempt({
        candidate: 'output-products',
        strategy: 'freeform',
        area: 490,
        ok: false,
        errors: 1,
        chosen: false,
        blueprint: null,
      }),
    ],
  };
}

test('build is disabled until there is a URL', () => {
  mount();
  expect(screen.getByRole('button', { name: 'Build' })).toBeDisabled();
});

test('the Name input exposes the game title limit to the browser', () => {
  mount();
  const name = screen.getByRole('textbox', { name: 'Name' });

  expect(name).toHaveAttribute('maxlength', '60');
  expect((name as HTMLInputElement).maxLength).toBe(60);
});

test('candidate policies are all checked in presentation order by default', () => {
  mount();
  const group = screen.getByRole('group', { name: 'Candidate policies' });
  const allProducts = within(group).getByRole('checkbox', { name: 'all-products' });
  const outputProducts = within(group).getByRole('checkbox', { name: 'output-products' });
  const noProliferator = within(group).getByRole('checkbox', { name: 'no-proliferator' });

  expect(within(group).getAllByRole('checkbox')).toEqual([
    allProducts,
    outputProducts,
    noProliferator,
  ]);
  expect(allProducts).toBeChecked();
  expect(outputProducts).toBeChecked();
  expect(noProliferator).toBeChecked();
});

test('an exact candidate policy subset is submitted in presentation order', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  const group = screen.getByRole('group', { name: 'Candidate policies' });
  fireEvent.click(within(group).getByRole('checkbox', { name: 'output-products' }));
  fireEvent.click(within(group).getByRole('checkbox', { name: 'no-proliferator' }));
  build();

  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.candidate_policies).toEqual(['all-products']);
  expect(body).not.toHaveProperty('candidates');
});

test('empty candidate policy selection disables Build and shows inline validation', () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  fireEvent.change(screen.getByLabelText('FactorioLab URL'), {
    target: { value: 'https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11' },
  });
  const group = screen.getByRole('group', { name: 'Candidate policies' });
  for (const checkbox of within(group).getAllByRole('checkbox')) {
    fireEvent.click(checkbox);
  }

  expect(screen.getByRole('button', { name: 'Build' })).toBeDisabled();
  expect(screen.getByText('Select at least one candidate policy.')).toHaveAttribute(
    'aria-live',
    'polite',
  );
  expect(calls).toHaveLength(0);
});

test('power is always on and has no selector', () => {
  mount();
  expect(screen.queryByRole('checkbox', { name: /Tesla Towers/i })).not.toBeInTheDocument();
  expect(screen.queryByText(/--no-power/i)).not.toBeInTheDocument();
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

test('candidate rows select the blueprint string, viewer model, and copy source', async () => {
  const result = candidateResult();
  serving({ status: 202, body: { ...aJob(), result } });
  const copied: string[] = [];
  const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: (text: string) => {
        copied.push(text);
        return Promise.resolve();
      },
    },
  });
  mount();
  build();

  const chosen = await screen.findByRole('row', {
    name: /no-proliferator freeform 575 0/i,
  });
  const alternative = screen.getByRole('row', {
    name: /all-products sequence-pair 640 0/i,
  });
  expect(chosen).toHaveAttribute('aria-selected', 'true');
  expect(alternative).toHaveAttribute('aria-selected', 'false');
  expect(screen.getByTestId('blueprint-string')).toHaveValue(A_BLUEPRINT);
  expect(screen.getByTestId('loaded')).toHaveAttribute(
    'data-blueprint-title',
    parseBlueprint(A_BLUEPRINT).header.shortDesc,
  );

  fireEvent.click(alternative);

  expect(chosen).toHaveAttribute('aria-selected', 'false');
  expect(alternative).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByTestId('blueprint-string')).toHaveValue(B_BLUEPRINT);
  expect(screen.getByTestId('loaded')).toHaveAttribute(
    'data-blueprint-title',
    parseBlueprint(B_BLUEPRINT).header.shortDesc,
  );
  // The report above the table follows the selection too, not just the string.
  expect(screen.getByTestId('report-title')).toHaveTextContent('(all products)');
  expect(screen.getByTestId('blueprint-title')).toHaveTextContent(
    'electromagnetic-matrix 60/min (all products)',
  );
  expect(screen.getByText('Showing').nextElementSibling).toHaveTextContent(
    'sequence-pair / all-products',
  );
  expect(screen.getByText('Machines').nextElementSibling).toHaveTextContent('13');
  expect(screen.getByText('Area').nextElementSibling).toHaveTextContent('640 tiles');
  expect(screen.getByText('Belt in').nextElementSibling).toHaveTextContent('proliferator-mk-iii');
  fireEvent.click(screen.getByRole('button', { name: 'Copy blueprint string' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument());
  expect(copied).toEqual([B_BLUEPRINT]);
  expect(alternative).toHaveAttribute('aria-selected', 'true');

  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
  else Reflect.deleteProperty(navigator, 'clipboard');
});

test('a clipboard completion cannot report success for a newly selected candidate', async () => {
  serving({ status: 202, body: { ...aJob(), result: candidateResult() } });
  let finishCopy = () => {};
  const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: () =>
        new Promise<void>((resolve) => {
          finishCopy = resolve;
        }),
    },
  });
  mount();
  build();

  await screen.findByRole('row', {
    name: /no-proliferator freeform 575 0/i,
  });
  fireEvent.click(screen.getByRole('button', { name: 'Copy blueprint string' }));
  fireEvent.click(
    screen.getByRole('row', {
      name: /all-products sequence-pair 640 0/i,
    }),
  );
  await act(async () => finishCopy());

  expect(screen.getByRole('button', { name: 'Copy blueprint string' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument();
  expect(screen.getByTestId('blueprint-string')).toHaveValue(B_BLUEPRINT);

  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
  else Reflect.deleteProperty(navigator, 'clipboard');
});

test('candidate rows support keyboard selection and unavailable blueprints cannot be selected', async () => {
  serving({ status: 202, body: { ...aJob(), result: candidateResult() } });
  mount();
  build();

  const chosen = await screen.findByRole('row', {
    name: /no-proliferator freeform 575 0/i,
  });
  const alternative = screen.getByRole('row', {
    name: /all-products sequence-pair 640 0/i,
  });
  const unavailable = screen.getByRole('row', {
    name: /output-products freeform 490 1/i,
  });

  fireEvent.keyDown(alternative, { key: 'Enter' });
  expect(alternative).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByTestId('blueprint-string')).toHaveValue(B_BLUEPRINT);

  expect(unavailable).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(unavailable);
  fireEvent.keyDown(unavailable, { key: 'Enter' });
  expect(alternative).toHaveAttribute('aria-selected', 'true');
  expect(unavailable).toHaveAttribute('aria-selected', 'false');
  expect(screen.getByTestId('blueprint-string')).toHaveValue(B_BLUEPRINT);

  fireEvent.keyDown(chosen, { key: ' ' });
  expect(chosen).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByTestId('blueprint-string')).toHaveValue(A_BLUEPRINT);
});

test('a new result resets selection to its best available candidate', async () => {
  const replacement = {
    ...aResult({
      blueprint: A_BLUEPRINT,
      candidate: 'output-products',
      strategy: 'sequence-pair',
    }),
    attempts: [
      anAttempt({
        candidate: 'output-products',
        strategy: 'sequence-pair',
        area: 420,
        blueprint: A_BLUEPRINT,
      }),
      anAttempt({
        candidate: 'no-proliferator',
        strategy: 'freeform',
        area: 460,
        ok: false,
        errors: 1,
        chosen: false,
        blueprint: null,
      }),
    ],
  };
  serving(
    { status: 202, body: { ...aJob(), result: candidateResult() } },
    { status: 202, body: { ...aJob(), id: 'replacement', result: replacement } },
  );
  mount();
  build();

  const alternative = await screen.findByRole('row', {
    name: /all-products sequence-pair 640 0/i,
  });
  fireEvent.click(alternative);
  expect(screen.getByTestId('blueprint-string')).toHaveValue(B_BLUEPRINT);

  build('https://factoriolab.github.io/dsp/flow?o=processor*60&v=11');

  await waitFor(() =>
    expect(
      screen.getByRole('row', { name: /output-products sequence-pair 420 0/i }),
    ).toHaveAttribute('aria-selected', 'true'),
  );
  expect(screen.getByTestId('blueprint-string')).toHaveValue(A_BLUEPRINT);
  expect(
    within(screen.getByRole('table', { name: 'Candidate blueprints' })).queryByText('all-products'),
  ).not.toBeInTheDocument();
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
          {
            candidate: 'direct-spec',
            strategy: null,
            reason: 'request has no legal layout',
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
  expect(refusal).toHaveTextContent('direct-spec: request has no legal layout');
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

test('latitude band selector exposes every authoritative height by width option', () => {
  mount();
  const band = screen.getByLabelText<HTMLSelectElement>('Latitude band');
  expect(Array.from(band.options, (option) => [option.value, option.text])).toEqual([
    ['portable', 'Portable (smallest + up to two wider)'],
    ['5x20', '5 × 20 (height × width)'],
    ['5x40', '5 × 40 (height × width)'],
    ['5x80', '5 × 80 (height × width)'],
    ['5x100', '5 × 100 (height × width)'],
    ['10x160', '10 × 160 (height × width)'],
    ['10x200', '10 × 200 (height × width)'],
    ['15x300', '15 × 300 (height × width)'],
    ['15x400', '15 × 400 (height × width)'],
    ['25x500', '25 × 500 (height × width)'],
    ['25x600', '25 × 600 (height × width)'],
    ['50x800', '50 × 800 (height × width)'],
    ['160x1000', '160 × 1000 (height × width)'],
  ]);
});

test.each(['50x800', '160x1000'])(
  'latitude band %s reaches the build request unchanged',
  async (selection) => {
    const calls = serving({ status: 202, body: aJob() });
    mount();
    const band = screen.getByLabelText('Latitude band');
    expect(band).toHaveValue('portable');

    fireEvent.change(band, { target: { value: selection } });
    build();

    await waitFor(() => expect(calls).toHaveLength(1));
    const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
    expect(body.band).toBe(selection);
  },
);

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

test('the budget copy follows selected and pinned effective candidates', () => {
  mount();
  // Defaults: 3 candidates x 2 active production strategies x 15s.
  expect(screen.getByText(/up to 90s of solving/)).toBeInTheDocument();

  const group = screen.getByRole('group', { name: 'Candidate policies' });
  fireEvent.click(within(group).getByRole('checkbox', { name: 'output-products' }));
  fireEvent.click(within(group).getByRole('checkbox', { name: 'no-proliferator' }));
  expect(screen.getByText(/1 candidate × 2 strategies × 15s/)).toBeInTheDocument();
  expect(screen.getByText(/up to 30s of solving/)).toBeInTheDocument();

  fireEvent.click(within(group).getByRole('checkbox', { name: 'output-products' }));
  fireEvent.click(within(group).getByRole('checkbox', { name: 'no-proliferator' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Fetch FactorioLab flow automatically' }));
  expect(screen.getByText(/1 candidate × 2 strategies × 15s/)).toBeInTheDocument();
  expect(screen.getByText(/up to 30s of solving/)).toBeInTheDocument();
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
