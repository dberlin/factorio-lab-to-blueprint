import { computeBom } from '../model/bom';
import { useBlueprint } from '../state/BlueprintProvider';

export function BomPanel() {
  const { blueprint, catalog } = useBlueprint();
  if (!blueprint) return null;

  // Derived during render; the React Compiler memoizes it.
  const bom = computeBom(blueprint, catalog);

  return (
    <aside className="bom" data-testid="bom">
      <h2>Buildings</h2>
      <table>
        <tbody>
          {bom.buildings.map((e) => (
            <tr key={e.itemId}>
              <td>{e.count}</td>
              <td>{e.name}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {bom.rawMaterials.length > 0 && (
        <>
          <h2>Raw materials</h2>
          <table>
            <tbody>
              {bom.rawMaterials.map((e) => (
                <tr key={e.itemId}>
                  <td>{e.count}</td>
                  <td>{e.name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {bom.assumedRecipes.length > 0 && (
        <p className="note">
          Raw cost assumes the default recipe for {bom.assumedRecipes.length} item(s) that have
          alternatives.
        </p>
      )}
    </aside>
  );
}
