import { useBlueprint } from '../state/BlueprintProvider';

export function Toolbar() {
  const { blueprint, sceneModel } = useBlueprint();
  if (!blueprint) return <header className="toolbar">No blueprint loaded</header>;

  const title = blueprint.header.shortDesc || '(untitled)';
  return (
    <header className="toolbar">
      <strong>{title}</strong>
      <span>{blueprint.buildings.length} buildings</span>
      <span>{blueprint.areas.length} area(s)</span>
      <span>game {blueprint.header.gameVersion}</span>
      {sceneModel && sceneModel.unknownItemIds.length > 0 && (
        <span className="warn">{sceneModel.unknownItemIds.length} unknown item type(s)</span>
      )}
      {sceneModel && sceneModel.unresolvedTagIds.length > 0 && (
        <span className="warn">{sceneModel.unresolvedTagIds.length} unrecognised belt tag(s)</span>
      )}
      <span className="hint">Q/E rotate · O toggle orbit · scroll zoom</span>
    </header>
  );
}
