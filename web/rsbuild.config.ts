import { defineConfig } from '@rsbuild/core';
import { pluginReact } from '@rsbuild/plugin-react';
import { handleProxyRequest } from './src/server/proxy';

export default defineConfig({
  plugins: [pluginReact({ reactCompiler: true })],
  html: { template: './index.html' },
  source: { entry: { index: './src/index.tsx' } },
  server: {
    // Mirrors server.ts: the /api/fetch handler below is an open relay to any
    // http(s) URL, so neither server should be reachable from the LAN.
    host: '127.0.0.1',
    // The dev server answers /api/fetch itself. A `server.proxy` entry cannot
    // work here: rsbuild's dev server also defaults to port 3000, so proxying
    // /api/fetch to localhost:3000 aimed the dev server back at itself and
    // every URL load hung until it timed out.
    setup: ({ server }) => {
      server.middlewares.use((req, res, next) => {
        handleProxyRequest(req.url ?? '/')
          .then(async (response) => {
            if (!response) return next();
            res.statusCode = response.status;
            const type = response.headers.get('content-type');
            if (type) res.setHeader('content-type', type);
            res.end(await response.text());
          })
          .catch(next);
      });
    },
  },
});
