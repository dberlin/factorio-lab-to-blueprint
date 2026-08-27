import { defineConfig } from '@rsbuild/core';
import { pluginReact } from '@rsbuild/plugin-react';

/**
 * Where `flab2bp-web` is listening. The dev server proxies the API to it rather
 * than answering it: the solver is Python, and there is no version of this that
 * does not need that process running.
 */
const API = process.env.FLAB2BP_API ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [pluginReact({ reactCompiler: true })],
  html: { template: './index.html' },
  source: {
    entry: {
      index: './src/index.tsx',
    },
  },
  server: {
    // The API it proxies to will spend every core on a CP-SAT solve for anyone
    // who asks, and /api/fetch is an open relay to any http(s) URL. Neither
    // this nor the Python server should be reachable from the LAN.
    host: '127.0.0.1',
    // Not 3000: that is the standalone viewer's port, and running both at once
    // while working on the two halves is normal.
    port: 3001,
    strictPort: true,
    // `/api/fetch` used to be answered here, by importing the viewer's own
    // proxy.ts into this config. It now lives in the Python server alongside
    // `/api/build`, so that the built app served by `flab2bp-web` and the app
    // served by `rsbuild dev` are talking to exactly the same endpoints. One
    // implementation, one place it can be wrong.
    proxy: { '/api': API },
  },
});
