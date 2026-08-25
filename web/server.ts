/** Serves the built app (including copied assets under dist/assets/) and proxies blueprint URLs. */
import { handleProxyRequest } from './src/server/proxy';

const PORT = Number(process.env.PORT ?? 3000);

Bun.serve({
  port: PORT,
  hostname: '127.0.0.1',
  async fetch(req) {
    const proxied = await handleProxyRequest(req.url);
    if (proxied) return proxied;

    const rel = new URL(req.url).pathname.slice(1) || 'index.html';
    const file = Bun.file(`dist/${rel}`);
    if (await file.exists()) return new Response(file);

    return new Response(Bun.file('dist/index.html'));
  },
});

console.log(`http://localhost:${PORT}`);
