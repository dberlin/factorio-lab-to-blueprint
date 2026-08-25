import { useEffect, useState } from 'react';
import type { Catalog } from '../model/catalog';
import { BlueprintCanvas } from '../scene/BlueprintCanvas';
import { isAbortError, loadCatalog } from '../state/assets';
import { BlueprintProvider } from '../state/BlueprintProvider';
import { BomPanel } from './BomPanel';
import { InfoPanel } from './InfoPanel';
import { InputPanel } from './InputPanel';
import { Toolbar } from './Toolbar';
import './app.css';

export function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // The cancelled flag alone stops the state update but leaves the request
    // itself running; aborting it is what keeps an unmounted tree from holding
    // a live fetch open (and what stops happy-dom >=20 reporting the pending
    // task as an unhandled abort at teardown).
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

  if (error) return <main role="alert">{error}</main>;
  if (!catalog) return <main>Loading game data…</main>;

  return (
    <BlueprintProvider catalog={catalog}>
      <div className="layout">
        <Toolbar />
        <InputPanel />
        <BlueprintCanvas />
        <InfoPanel />
        <BomPanel />
      </div>
    </BlueprintProvider>
  );
}
