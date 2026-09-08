import { useId, useState } from 'react';
import { findBlueprintString } from '../format';
import { useBlueprint } from '../state/BlueprintProvider';

export function InputPanel() {
  const { beginPublication, publishArtifact, failPublication, error, document } = useBlueprint();
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const textId = useId();
  const urlId = useId();

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const generation = beginPublication();
    if (file.size === 0) {
      failPublication(`"${file.name}" is empty.`, generation);
      return;
    }
    file
      .text()
      .then((t) => {
        if (publishArtifact(t.trim(), generation)) {
          setText(t.trim());
        }
      })
      .catch((e: unknown) => {
        failPublication(
          `Could not read "${file.name}": ${e instanceof Error ? e.message : String(e)}`,
          generation,
        );
      });
  };

  const fetchUrl = async () => {
    const generation = beginPublication();
    setBusy(true);
    try {
      const r = await fetch(`/api/fetch?url=${encodeURIComponent(url)}`);
      if (!r.ok) {
        const reason = (await r.text()).trim() || `HTTP ${r.status}`;
        failPublication(`Could not fetch that URL: ${reason}`, generation);
        return;
      }
      const found = findBlueprintString(await r.text());
      if (!found) {
        failPublication('No blueprint string found on that page.', generation);
        return;
      }
      if (publishArtifact(found, generation)) setText(found);
    } catch (e: unknown) {
      failPublication(
        `Could not fetch that URL: ${e instanceof Error ? e.message : String(e)}`,
        generation,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- not the only input method
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
            publishArtifact(text.trim(), beginPublication());
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
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {document?.kind === 'artifact' && !document.blueprint.hashValid && (
        <p className="warn">
          Checksum mismatch — rendering anyway. Some third-party tools emit unhashed strings.
        </p>
      )}
    </section>
  );
}
