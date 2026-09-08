/**
 * Task 6, step 2: find the belts under/around each coater in a saved `placed`
 * blueprint and report the run boundaries buildBeltRuns actually produces.
 *
 * A coater's addon body sits at the SAME (x, y) as the node's third belt
 * tile ("n2"), per `_emit_coater_node`/`_coater_node_site_is_clear` in
 * `src/flab2bp/layout/freeform.py` (`seat_x = ox + 1 + half_span`, half_span
 * 1 for the coater's 3-tile footprint centred on n2). So: find the belt at
 * the coater's own (x, y), walk one step back and two forward along the
 * blueprint's own link graph to recover n0..n3, then look up which
 * buildBeltRuns run each of those four belt indices landed in.
 *
 * Usage (from web/): bun run <this-file> "$PWD" <blueprint-file> [...more files]
 */
import { readFileSync } from 'node:fs';

const WEB = process.argv[2] as string;
const files = process.argv.slice(3);

const { parseBlueprint } = await import(`${WEB}/src/format/index.ts`);
const { buildBeltRuns, beltSuccessors, isBelt } = await import(`${WEB}/src/model/beltGraph.ts`);

for (const file of files) {
  const bp = parseBlueprint(readFileSync(file, 'utf8').trim());
  const byIndex = new Map(bp.buildings.map((b: any) => [b.index, b]));
  const byPos = new Map<string, any>();
  for (const b of bp.buildings) if (isBelt(b.itemId)) byPos.set(`${b.x},${b.y},${b.z}`, b);

  const runs = buildBeltRuns(bp);
  const runIndexOf = new Map<number, number>();
  runs.forEach((r, ri) => r.belts.forEach((bi) => runIndexOf.set(bi, ri)));

  const next = beltSuccessors(bp);
  const inboundCount = new Map<number, number>();
  for (const t of next.values()) inboundCount.set(t, (inboundCount.get(t) ?? 0) + 1);

  const coaters = bp.buildings.filter((b: any) => b.itemId === 2313);
  console.log(`\n=== ${file.split('/').pop()} — ${coaters.length} coater(s), ${runs.length} run(s) total ===`);

  let reported = 0;
  for (const c of coaters) {
    const n2 = byPos.get(`${c.x},${c.y},${c.z}`);
    if (!n2) {
      console.log(`  coater#${c.index}@(${c.x},${c.y},${c.z}) -- NO BELT AT ITS OWN TILE`);
      continue;
    }
    // Walk back one from n2 to find n1 (n1 -> n2 must hold if this is the node).
    let n1: any = undefined;
    for (const b of bp.buildings) {
      if (isBelt(b.itemId) && next.get(b.index) === n2.index) n1 = byIndex.get(b.index);
    }
    const n1v = n1 as any;
    const n0 = n1v ? [...bp.buildings].find((b: any) => isBelt(b.itemId) && next.get(b.index) === n1v.index) : undefined;
    const n3 = next.has(n2.index) ? byIndex.get(next.get(n2.index) as number) : undefined;

    const tile = (b: any, label: string) => {
      if (!b) return `${label}=<missing>`;
      const ri = runIndexOf.get(b.index);
      return `${label}#${b.index}@(${b.x},${b.y},${b.z}) inbound=${inboundCount.get(b.index) ?? 0} run=${ri}`;
    };

    console.log(`  coater#${c.index}@(${c.x},${c.y},${c.z}):`);
    console.log(`    ${tile(n0, 'n0')}`);
    console.log(`    ${tile(n1v, 'n1')}`);
    console.log(`    ${tile(n2, 'n2')}`);
    console.log(`    ${tile(n3, 'n3')}`);
    const runsSeen = new Set([n0, n1v, n2, n3].filter(Boolean).map((b: any) => runIndexOf.get(b.index)));
    console.log(`    -> n1,n2,n3 in one run: ${runIndexOf.get(n1v?.index) === runIndexOf.get(n2.index) && runIndexOf.get(n2.index) === runIndexOf.get(n3?.index)}; distinct runs across n0..n3: ${runsSeen.size}`);
    reported += 1;
  }
  console.log(`  (reported ${reported}/${coaters.length} coaters)`);
}
