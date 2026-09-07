import { type MachineLook, useBlueprint } from '../state/BlueprintProvider';

const MACHINE_LOOKS: MachineLook[] = ['ghosted', 'solid', 'hidden'];

export function Toolbar() {
  const { blueprint, sceneModel, stale, snapshotLabel, view, setView } = useBlueprint();
  if (!blueprint) return <header className="toolbar">No blueprint loaded</header>;

  const title = blueprint.header.shortDesc || '(untitled)';
  return (
    <header className="toolbar">
      {/* While a search snapshot is on the canvas, THIS is the label -- not
          the title above. `snapshotLabel` is non-null for exactly as long as
          the canvas shows a trace frame (BlueprintProvider.loadSnapshot),
          so replacing rather than merely prefacing the title is what stops
          a mid-search picture reading as a named result. `role="status"`
          announces each new caption as the poll updates it. */}
      {snapshotLabel ? (
        // `<output>` carries an implicit `status` role, so each new caption
        // is announced as the poll updates it -- no explicit `role` needed.
        <output className="trace-live" data-testid="trace-label">
          {snapshotLabel}
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
      {/* Both layers default on and are here to be turned off: a blueprint
          with hundreds of runs carries hundreds of numbers, and there are
          moments when the shapes alone are what you want to look at. */}
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
