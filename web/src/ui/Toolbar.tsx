import { type MachineLook, useBlueprint } from '../state/BlueprintProvider';

const MACHINE_LOOKS: MachineLook[] = ['ghosted', 'solid', 'hidden'];

export function Toolbar() {
  const { document, blueprint, sceneModel, stale, view, setView } = useBlueprint();
  if (!blueprint) return <header className="toolbar">No blueprint loaded</header>;

  const title = blueprint.header.shortDesc || '(untitled)';
  return (
    <header className="toolbar">
      {/* Provenance comes from the same document as the rendered buildings. */}
      {document?.kind === 'trace' ? (
        // `<output>` carries an implicit `status` role, so each new caption
        // is announced as the poll updates it -- no explicit `role` needed.
        <output className="trace-live" data-testid="trace-label">
          {document.label}
        </output>
      ) : (
        <strong>{title}</strong>
      )}
      {/* The last build produced no blueprint, so this is the one before it.
          Without this the toolbar names a build that was superseded by a
          refusal, which reads as though the refusal had not happened. */}
      {stale && (
        <span className="warn" data-testid="stale-blueprint">
          previous build — the last one produced no blueprint
        </span>
      )}
      <span>{blueprint.buildings.length} buildings</span>
      <span>{blueprint.areas.length} area(s)</span>
      <span>game {blueprint.header.gameVersion}</span>
      {sceneModel && sceneModel.unknownItemIds.length > 0 && (
        <span className="warn">{sceneModel.unknownItemIds.length} unknown item type(s)</span>
      )}
      {sceneModel && sceneModel.unresolvedTagIds.length > 0 && (
        <span className="warn">{sceneModel.unresolvedTagIds.length} unrecognised belt tag(s)</span>
      )}
      {/* All three layers default on and are here to be turned off: a
          blueprint with hundreds of runs carries hundreds of numbers and an
          inferred item at nearly every lane end, and there are moments when
          the shapes alone are what you want to look at. */}
      <label className="toggle">
        <input
          type="checkbox"
          checked={view.beltLabels}
          onChange={(e) => setView({ ...view, beltLabels: e.target.checked })}
        />
        belt numbers
      </label>
      <label className="toggle">
        <input
          type="checkbox"
          checked={view.sorterTies}
          onChange={(e) => setView({ ...view, sorterTies: e.target.checked })}
        />
        sorter ties
      </label>
      <label className="toggle">
        <input
          type="checkbox"
          checked={view.endpointIcons}
          onChange={(e) => setView({ ...view, endpointIcons: e.target.checked })}
        />
        endpoint icons
      </label>
      <label className="toggle">
        machines
        <select
          value={view.machines}
          onChange={(e) => setView({ ...view, machines: e.target.value as MachineLook })}
        >
          {MACHINE_LOOKS.map((look) => (
            <option key={look} value={look}>
              {look}
            </option>
          ))}
        </select>
      </label>
      <span className="hint">Q/E rotate · O top-down · drag orbit · scroll zoom</span>
    </header>
  );
}
