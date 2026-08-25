import { expect, test } from '@rstest/core';
import { handleProxyRequest, proxyBlueprintUrl } from '../../src/server/proxy';

/**
 * Swaps in a fake global fetch for the duration of `body`, so the upstream
 * branches can be exercised without touching the network.
 */
async function withFetch(
  fake: (input: URL | RequestInfo, init?: RequestInit) => Promise<Response>,
  body: () => Promise<void>,
): Promise<void> {
  const real = globalThis.fetch;
  globalThis.fetch = fake as typeof globalThis.fetch;
  try {
    await body();
  } finally {
    globalThis.fetch = real;
  }
}

test('a string that is not a URL at all is rejected', async () => {
  const r = await proxyBlueprintUrl('not a url');
  expect(r.status).toBe(400);
  expect(await r.text()).toBe('Invalid url');
});

test('only http and https are allowed', async () => {
  for (const target of ['file:///etc/passwd', 'data:text/plain,hi', 'ftp://example.com/x']) {
    const r = await proxyBlueprintUrl(target);
    expect(r.status).toBe(400);
    expect(await r.text()).toBe('Only http/https are allowed');
  }
});

test('http and https both get through to the upstream fetch', async () => {
  const seen: string[] = [];
  await withFetch(
    async (input) => {
      seen.push(String(input));
      return new Response('BLUEPRINT:0,10,...', { status: 200 });
    },
    async () => {
      for (const target of ['http://example.com/a', 'https://example.com/b']) {
        const r = await proxyBlueprintUrl(target);
        expect(r.status).toBe(200);
        expect(await r.text()).toBe('BLUEPRINT:0,10,...');
      }
    },
  );
  expect(seen).toEqual(['http://example.com/a', 'https://example.com/b']);
});

test("the upstream's status is passed through, not flattened to 200", async () => {
  await withFetch(
    async () => new Response('Not Found', { status: 404 }),
    async () => {
      const r = await proxyBlueprintUrl('https://example.com/missing');
      expect(r.status).toBe(404);
    },
  );
});

// A network failure must surface as a clean 502 carrying the real reason.
// Letting it throw hands Bun's ~67KB HTML debug overlay to the client, which
// InputPanel would then show as the "error message".
test('an unreachable upstream yields a 502 with the real reason', async () => {
  await withFetch(
    () => Promise.reject(new Error('Unable to connect. Is the computer able to access the url?')),
    async () => {
      const r = await proxyBlueprintUrl('http://no-such-host.invalid/');
      expect(r.status).toBe(502);
      expect(r.headers.get('content-type')).toBe('text/plain; charset=utf-8');
      expect(await r.text()).toBe(
        'Could not reach http://no-such-host.invalid/: Unable to connect. Is the computer able to access the url?',
      );
    },
  );
});

test('a non-Error rejection still produces a readable 502', async () => {
  await withFetch(
    () => Promise.reject('boom'),
    async () => {
      const r = await proxyBlueprintUrl('https://example.com/');
      expect(r.status).toBe(502);
      expect(await r.text()).toContain('boom');
    },
  );
});

test('the response is always plain text so the client can scan it', async () => {
  await withFetch(
    async () => new Response('<html>x</html>', { headers: { 'content-type': 'text/html' } }),
    async () => {
      const r = await proxyBlueprintUrl('https://example.com/');
      expect(r.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    },
  );
});

// handleProxyRequest is the piece both servers mount, so its routing decision
// is what keeps /api/fetch from swallowing the app's own requests.
test('a request for any other path falls through', async () => {
  for (const path of ['/', '/index.html', '/assets/items.json', '/api/fetch/extra']) {
    expect(await handleProxyRequest(path)).toBeUndefined();
  }
});

test('/api/fetch without a url parameter is a 400, not a fall-through', async () => {
  const r = await handleProxyRequest('/api/fetch');
  expect(r?.status).toBe(400);
  expect(await r?.text()).toBe('Missing url');
});

test('handleProxyRequest routes the url parameter into the allowlist check', async () => {
  const r = await handleProxyRequest(`/api/fetch?url=${encodeURIComponent('file:///etc/passwd')}`);
  expect(r?.status).toBe(400);
  expect(await r?.text()).toBe('Only http/https are allowed');
});

test('an absolute request url works as well as a relative one', async () => {
  await withFetch(
    async () => new Response('ok'),
    async () => {
      const r = await handleProxyRequest(
        `http://127.0.0.1:3000/api/fetch?url=${encodeURIComponent('https://example.com/')}`,
      );
      expect(r?.status).toBe(200);
      expect(await r?.text()).toBe('ok');
    },
  );
});
