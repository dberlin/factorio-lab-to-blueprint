/**
 * The `/api/fetch` blueprint-URL proxy, shared by the production server
 * (`server.ts`) and the rsbuild dev server (`rsbuild.config.ts`).
 *
 * Blueprint pages are on third-party sites, so the browser cannot fetch them
 * directly (CORS). This runs server-side and returns the page body as plain
 * text for the client to scan for a `BLUEPRINT:` string.
 *
 * Deliberately dependency-free: no React, no three.js, no framework imports,
 * so it can be pulled into a build config as easily as into a Bun server.
 */

/**
 * Fetches `target` on the caller's behalf and returns the page as plain text.
 *
 * Bad input yields 400, an unreachable upstream yields a clean 502 carrying
 * the real reason; the upstream's own status is otherwise passed through.
 */
export async function proxyBlueprintUrl(target: string): Promise<Response> {
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return new Response('Invalid url', { status: 400 });
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return new Response('Only http/https are allowed', { status: 400 });
  }
  // Known limitation: fetch() follows redirects, so a redirect from an allowed
  // http(s) URL to a local address (e.g. http://127.0.0.1:<port>) is still
  // reachable — but only from this machine, since both servers that mount this
  // handler bind to 127.0.0.1. Accepted for a personal tool; not hardened
  // against SSRF from the local machine to itself.
  let upstream: Response;
  try {
    upstream = await fetch(parsed, { headers: { 'user-agent': 'dsp-blueprint-viewer' } });
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause);
    return new Response(`Could not reach ${parsed.href}: ${reason}`, {
      status: 502,
      headers: { 'content-type': 'text/plain; charset=utf-8' },
    });
  }
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

/**
 * Resolves an `/api/fetch` request URL to a response, or `undefined` when the
 * path is not the proxy endpoint (so a host can fall through to its own
 * routing). `requestUrl` may be relative — the base is only used for parsing.
 */
export async function handleProxyRequest(requestUrl: string): Promise<Response | undefined> {
  const url = new URL(requestUrl, 'http://localhost');
  if (url.pathname !== '/api/fetch') return undefined;
  const target = url.searchParams.get('url');
  return target ? proxyBlueprintUrl(target) : new Response('Missing url', { status: 400 });
}
