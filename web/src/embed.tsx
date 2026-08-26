/**
 * The viewer half of the app, mountable into a page that is not this app.
 *
 * The client-side arm is a hand-written static page — it has to be, since its
 * whole claim is that no server solves anything — but it was showing its
 * results in a flat SVG while the server arm showed the real 3D viewer. Two
 * arms that exist to be compared cannot differ in what they draw, or the
 * comparison measures the drawing.
 *
 * So the viewer is exported rather than reimplemented: the same
 * `BlueprintProvider`, `Toolbar`, `BlueprintCanvas`, `InfoPanel` and
 * `BomPanel` the server arm renders, mounted by a global instead of by
 * `index.tsx`. What each arm SOLVES is the difference under test; what each
 * arm DRAWS is now literally the same code.
 *
 *     await window.flab2bpViewer.mount(el, { assetBase: './dist/assets' });
 *     window.flab2bpViewer.load(blueprintString);
 */
import { useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Catalog } from './model/catalog';
import { BlueprintCanvas } from './scene/BlueprintCanvas';
import { isAbortError, loadCatalog, setAssetBase } from './state/assets';
import { BlueprintProvider, useBlueprint } from './state/BlueprintProvider';
import { BomPanel } from './ui/BomPanel';
import { InfoPanel } from './ui/InfoPanel';
import { Toolbar } from './ui/Toolbar';
import './ui/app.css';

/** Set by <Bridge/> once the tree is live; the page calls it to load a string. */
let loadIntoTree: ((text: string) => void) | null = null;
let pending: string | null = null;

function Bridge() {
  const { load } = useBlueprint();
  useEffect(() => {
    loadIntoTree = load;
    // A blueprint handed over before React finished mounting is not an error —
    // the page solves and the tree boots concurrently. Hold it and apply it
    // here rather than dropping it and rendering an empty canvas.
    if (pending !== null) {
      load(pending);
      pending = null;
    }
    return () => {
      loadIntoTree = null;
    };
  }, [load]);
  return null;
}

function EmbeddedViewer() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    loadCatalog(controller.signal).then(
      (c) => {
        if (!cancelled) setCatalog(c);
      },
      (e: unknown) => {
        if (cancelled || isAbortError(e)) return;
        setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  if (error) return <div role="alert">{error}</div>;
  if (!catalog) return <div>Loading game data…</div>;

  return (
    <BlueprintProvider catalog={catalog}>
      <Bridge />
      <div className="layout embedded">
        <Toolbar />
        <BlueprintCanvas />
        <InfoPanel />
        <BomPanel />
      </div>
    </BlueprintProvider>
  );
}

let root: Root | null = null;

export interface ViewerHandle {
  mount(el: HTMLElement, options?: { assetBase?: string }): void;
  load(text: string): void;
  ready(): boolean;
}

const handle: ViewerHandle = {
  mount(el, options) {
    if (options?.assetBase) setAssetBase(options.assetBase);
    // No StrictMode. Its deliberate double-invoke is a development aid for the
    // app's own tree; here it would mount, tear down and remount a WebGL
    // context inside somebody else's page for no benefit.
    root ??= createRoot(el);
    root.render(<EmbeddedViewer />);
  },
  load(text) {
    if (loadIntoTree) loadIntoTree(text);
    else pending = text;
  },
  ready() {
    return loadIntoTree !== null;
  },
};

declare global {
  interface Window {
    flab2bpViewer?: ViewerHandle;
  }
}

window.flab2bpViewer = handle;
