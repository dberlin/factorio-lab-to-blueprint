import { useId, useState } from 'react';
import { findBlueprintString } from '../format';
import { useBlueprint } from '../state/BlueprintProvider';

export function InputPanel() {
  const { load, error, blueprint } = useBlueprint();
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const textId = useId();
  const urlId = useId();

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (file.size === 0) {
      setFetchError(`"${file.name}" is empty.`);
      return;
    }
    file
      .text()
      .then((t) => {
        setFetchError(null);
        setText(t.trim());
        load(t.trim());
      })
      .catch((e: unknown) => {
        setFetchError(
          `Could not read "${file.name}": ${e instanceof Error ? e.message : String(e)}`,
        );
      });
  };

  const fetchUrl = async () => {
    setBusy(true);
    setFetchError(null);
    try {
      const r = await fetch(`/api/fetch?url=${encodeURIComponent(url)}`);
      if (!r.ok) {
        const reason = (await r.text()).trim() || `HTTP ${r.status}`;
        setFetchError(`Could not fetch that URL: ${reason}`);
        return;
      }
      const found = findBlueprintString(await r.text());
      if (!found) {
        setFetchError('No blueprint string found on that page.');
        return;
      }
      setText(found);
      load(found);
    } catch (e: unknown) {
      setFetchError(`Could not fetch that URL: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: drop target is a convenience over the paste/URL fallbacks below, not the only way to load a blueprint
    <section
      className="input-panel"
      data-testid="dropzone"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <label htmlFor={textId}>Blueprint string</label>
      <textarea
        id={textId}
        value={text}
        spellCheck={false}
        placeholder="BLUEPRINT:0,10,…  — or drop a .txt file here"
        onChange={(e) => setText(e.target.value)}
      />
      <div className="row">
        <button
          type="button"
          onClick={() => {
            setFetchError(null);
            load(text.trim());
          }}
          disabled={!text.trim()}
        >
          Load
        </button>
        <label htmlFor={urlId}>or URL</label>
        <input
          id={urlId}
          value={url}
          placeholder="https://www.dysonsphereblueprints.com/blueprints/…"
          onChange={(e) => setUrl(e.target.value)}
        />
        <button type="button" onClick={fetchUrl} disabled={!url.trim() || busy}>
          {busy ? 'Fetching…' : 'Fetch'}
        </button>
      </div>
      {/* Only one alert is ever shown: a fresh fetchError always supersedes a stale parse
          error (and vice versa, since load() clears fetchError), so the two channels never
          display contradictory messages at once. */}
      {(fetchError ?? error) && (
        <p role="alert" className="error">
          {fetchError ?? error}
        </p>
      )}
      {blueprint && !blueprint.hashValid && (
        <p className="warn">
          Checksum mismatch — rendering anyway. Some third-party tools emit unhashed strings.
        </p>
      )}
    </section>
  );
}
