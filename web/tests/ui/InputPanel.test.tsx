import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { buildCatalog } from '../../src/model/catalog';
import { BlueprintProvider } from '../../src/state/BlueprintProvider';
import { InputPanel } from '../../src/ui/InputPanel';

const catalog = buildCatalog({
  items: [
    {
      id: 2001,
      name: 'Belt',
      iconName: 'belt-1',
      gridIndex: 1,
      modelIndex: 35,
      canBuild: true,
      color: 1,
    },
  ],
  models: { '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] } },
  recipes: [],
});

const setup = () =>
  render(
    <BlueprintProvider catalog={catalog}>
      <InputPanel />
    </BlueprintProvider>,
  );

test('pasting a blueprint loads it', () => {
  setup();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt',
    'utf8',
  ).trim();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('an invalid string shows an inline error', () => {
  setup();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: 'nope' } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.getByRole('alert')).toHaveTextContent(/BLUEPRINT:/i);
});

test('a Dyson sphere blueprint is rejected with a clear reason', () => {
  setup();
  const text = readFileSync('tests/fixtures/dyson-sphere-iridescent.txt', 'utf8').trim();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.getByRole('alert')).toHaveTextContent(/Dyson sphere/i);
});

test('dropping a .txt file loads its contents', async () => {
  setup();
  const text = readFileSync(
    'tests/fixtures/factory-quick-start-step-3-red-cube.txt',
    'utf8',
  ).trim();
  const file = new File([text], 'bp.txt', { type: 'text/plain' });
  const zone = screen.getByTestId('dropzone');

  fireEvent.drop(zone, { dataTransfer: { files: [file], types: ['Files'] } });

  const textarea = screen.getByLabelText(/blueprint string/i);
  await waitFor(() => expect(textarea).toHaveValue(text));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('dropping with no files does nothing', () => {
  setup();
  const zone = screen.getByTestId('dropzone');
  fireEvent.drop(zone, { dataTransfer: { files: [], types: ['Files'] } });
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByLabelText(/blueprint string/i)).toHaveValue('');
});

test('dropping an empty file shows an inline error', async () => {
  setup();
  const file = new File([], 'empty.txt', { type: 'text/plain' });
  const zone = screen.getByTestId('dropzone');
  fireEvent.drop(zone, { dataTransfer: { files: [file], types: ['Files'] } });
  expect(await screen.findByRole('alert')).toHaveTextContent(/empty/i);
});

test('the URL field is present and disabled while empty', () => {
  setup();
  const btn = screen.getByRole('button', { name: /fetch/i });
  expect(btn).toBeDisabled();
});

/** Runs `body` with a stubbed global fetch that answers every request with `page`. */
async function withFetchedPage(page: string, body: () => Promise<void>): Promise<void> {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(page, { status: 200 })) as unknown as typeof fetch;
  try {
    await body();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

// The real dysonsphereblueprints.com page, whose <textarea> escapes the payload
// delimiters as &quot;. Matching the raw body finds nothing, so before the
// decode step this reported "No blueprint string found on that page." for a
// page that plainly contains one.
test('fetching a URL whose page HTML-escapes the blueprint still loads it', async () => {
  setup();
  const page = readFileSync('tests/fixtures/page-heretical-smelter-block.html', 'utf8');
  const expected = readFileSync(
    'tests/fixtures/factory-heretical-smelter-block.txt',
    'utf8',
  ).trim();
  await withFetchedPage(page, async () => {
    fireEvent.change(screen.getByLabelText(/or url/i), {
      target: { value: 'https://www.dysonsphereblueprints.com/blueprints/x' },
    });
    fireEvent.click(screen.getByRole('button', { name: /fetch/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/blueprint string/i)).toHaveValue(expected);
    });
  });
  expect(screen.queryByRole('alert')).toBeNull();
});

test('a fetched page with no blueprint still reports that clearly', async () => {
  setup();
  await withFetchedPage('<html><body><p>no blueprint here</p></body></html>', async () => {
    fireEvent.change(screen.getByLabelText(/or url/i), { target: { value: 'https://x.test/' } });
    fireEvent.click(screen.getByRole('button', { name: /fetch/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No blueprint string found on that page.',
    );
  });
});

test('a failed URL fetch shows the server-provided reason, not a bare status code', async () => {
  setup();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(
      'Could not reach http://bad.invalid/: Unable to connect. Is the computer able to access the url?',
      { status: 502 },
    )) as unknown as typeof fetch;
  try {
    fireEvent.change(screen.getByLabelText(/or url/i), { target: { value: 'http://bad.invalid' } });
    fireEvent.click(screen.getByRole('button', { name: /fetch/i }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/unable to connect/i);
    expect(alert).not.toHaveTextContent(/^Could not fetch that URL: HTTP 502$/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
