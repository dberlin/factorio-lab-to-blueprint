/* Cross-origin isolation via service worker.
 *
 * GitHub Pages cannot send COOP/COEP response headers, and without cross-origin
 * isolation SharedArrayBuffer is unavailable -- which makes the or-tools-wasm
 * CP-SAT runtime hang forever on its pthread pool. A service worker can add the
 * headers on the client side, which is the only route to isolation on a static
 * host. Cost: the first visit must register the worker and then RELOAD before
 * anything can solve.
 *
 * Adapted from the well-known coi-serviceworker pattern.
 */
if (typeof window === 'undefined') {
  // ---- service worker side ----
  self.addEventListener('install', () => self.skipWaiting());
  self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

  self.addEventListener('fetch', (event) => {
    const r = event.request;
    if (r.cache === 'only-if-cached' && r.mode !== 'same-origin') return;

    event.respondWith(
      fetch(r)
        .then((response) => {
          if (response.status === 0) return response;
          const headers = new Headers(response.headers);
          headers.set('Cross-Origin-Embedder-Policy', 'require-corp');
          headers.set('Cross-Origin-Opener-Policy', 'same-origin');
          headers.set('Cross-Origin-Resource-Policy', 'cross-origin');
          return new Response(response.body, {
            status: response.status,
            statusText: response.statusText,
            headers,
          });
        })
        .catch((e) => console.error(e))
    );
  });
} else {
  // ---- page side ----
  (() => {
    if (window.crossOriginIsolated) return;
    if (!window.isSecureContext) {
      console.error('coi: not a secure context; service workers unavailable');
      return;
    }
    if (!navigator.serviceWorker) {
      console.error('coi: no serviceWorker support');
      return;
    }
    navigator.serviceWorker
      .register(window.document.currentScript.src)
      .then((registration) => {
        registration.addEventListener('updatefound', () => window.location.reload());
        if (registration.active && !navigator.serviceWorker.controller) {
          window.location.reload();
        }
      })
      .catch((err) => console.error('coi: registration failed', err));
  })();
}
