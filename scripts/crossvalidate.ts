/**
 * Cross-validation bridge: our blueprint strings, the viewer's decoder.
 *
 * The dsp-blueprint-viewer is a genuinely independent implementation, so it
 * catches encoder bugs our own Python decoder would share by construction --
 * most importantly the centre-vs-corner `localOffset` convention, which the
 * `bounds` field below is what actually pins down.
 *
 * Usage:  bun scripts/crossvalidate.ts <viewer-root>
 *         stdin:  one blueprint string per line
 *         stdout: one JSON object per line, in the same order
 *
 * One subprocess handles the whole batch; spawning bun per blueprint would cost
 * more than the parsing does.
 */

export {};

/** The subset of the viewer's `BlueprintBuilding` this bridge reads. */
interface ViewerBuilding {
  itemId: number;
  x: number;
  y: number;
  z: number;
}

interface ViewerBlueprint {
  buildings?: ViewerBuilding[];
  areas?: unknown[];
  header?: { headerVersion?: number };
}

const viewerRoot = process.argv[2];
if (!viewerRoot) {
  console.error("usage: bun scripts/crossvalidate.ts <viewer-root>");
  process.exit(2);
}

const { parseBlueprint } = await import(`${viewerRoot}/src/format/index.ts`);

interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
}

const input: string = await Bun.stdin.text();
const lines: string[] = input
  .split("\n")
  .map((l: string) => l.trim())
  .filter((l: string) => l.length > 0);

for (const line of lines) {
  try {
    const bp = parseBlueprint(line) as ViewerBlueprint;
    const buildings: ViewerBuilding[] = bp.buildings ?? [];

    const itemIds: Record<string, number> = {};
    for (const b of buildings) {
      const key = String(b.itemId);
      itemIds[key] = (itemIds[key] ?? 0) + 1;
    }

    // The viewer stores local offsets FLAT on the building (x/y/z), not nested
    // under a `localOffset` object.
    let bounds: Bounds | null = null;
    if (buildings.length > 0) {
      const xs: number[] = buildings.map((b: ViewerBuilding) => b.x);
      const ys: number[] = buildings.map((b: ViewerBuilding) => b.y);
      const zs: number[] = buildings.map((b: ViewerBuilding) => b.z);
      bounds = {
        minX: Math.min(...xs),
        maxX: Math.max(...xs),
        minY: Math.min(...ys),
        maxY: Math.max(...ys),
        minZ: Math.min(...zs),
        maxZ: Math.max(...zs),
      };
    }

    console.log(
      JSON.stringify({
        ok: true,
        // parseBlueprint throws on checksum mismatch, so reaching here means
        // the independent implementation accepted our MD5F.
        hashValid: true,
        buildings: buildings.length,
        areas: (bp.areas ?? []).length,
        version: bp.header?.headerVersion ?? null,
        itemIds,
        bounds,
      }),
    );
  } catch (err) {
    console.log(
      JSON.stringify({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      }),
    );
  }
}
