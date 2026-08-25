import { Fragment } from 'react';
import { describeInferred, describeParameters } from '../model/params';
import { useBlueprint } from '../state/BlueprintProvider';

const round = (n: number) => Math.round(n * 100) / 100;

export function InfoPanel() {
  const { blueprint, catalog, selectedIndex, sceneModel } = useBlueprint();
  if (!blueprint || selectedIndex === null) return null;

  const b = blueprint.buildings[selectedIndex];
  if (!b) return null;

  const item = catalog.item(b.itemId);
  // Same key order as buildSceneModel: the record's own modelIndex wins, so
  // the reported footprint always matches the box actually drawn.
  const box = catalog.model(b.modelIndex) ?? catalog.boxForItem(b.itemId);

  const rows = [
    ...describeParameters(b, catalog),
    ...(sceneModel ? describeInferred(b, blueprint, sceneModel.beltRuns, catalog) : []),
  ];

  return (
    <aside className="info" data-testid="info">
      <h2>{item?.name ?? `Item ${b.itemId}`}</h2>
      <dl>
        <dt>Item / model</dt>
        <dd>
          {b.itemId} / {b.modelIndex}
        </dd>
        <dt>Position</dt>
        <dd>
          {round(b.x)}, {round(b.y)}, alt {round(b.z)}
        </dd>
        <dt>Yaw</dt>
        <dd>{round(b.yaw)}°</dd>
        <dt>Area</dt>
        <dd>{b.areaIndex}</dd>
        {box && (
          <>
            <dt>Footprint</dt>
            <dd>{box.size.map(round).join(' × ')}</dd>
          </>
        )}
        {rows.map((row, i) => (
          // Rows are freshly derived from a pure function every render (never
          // reordered independent of content); combining the index with the
          // label keeps keys unique even if a future decoder emits duplicates.
          // biome-ignore lint/suspicious/noArrayIndexKey: see comment above
          <Fragment key={`${i}-${row.label}`}>
            <dt>{row.label}</dt>
            <dd className={row.inferred ? 'inferred' : undefined}>
              {row.value}
              {row.inferred && <span className="inferred-tag"> (inferred)</span>}
            </dd>
          </Fragment>
        ))}
      </dl>
    </aside>
  );
}
