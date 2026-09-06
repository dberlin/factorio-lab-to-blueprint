import { createContext, type ReactNode, useContext, useState } from 'react';
import type { TraceFrame } from '../api/trace';
import { type Blueprint, parseBlueprint } from '../format';
import type { Catalog } from '../model/catalog';
import { buildSceneModel, type SceneModel } from '../model/layout';

/** Which trace overlay layers are on. Independent toggles (task-10-addendum.md
    Ruling 4): a layer contributes nothing when off, regardless of the other. */
export interface TraceOverlayShow {
  stranded: boolean;
  noGoods: boolean;
}

export interface BlueprintState {
  blueprint: Blueprint | null;
  sceneModel: SceneModel | null;
  catalog: Catalog;
  error: string | null;
  selectedIndex: number | null;
  /** True when what is rendered is NOT the outcome of the last build — a build
      that refused or errored leaves the previous blueprint on the canvas,
      because throwing away the thing you were looking at is worse. The label
      above it must not go on claiming to name the current result. */
  stale: boolean;
  /** Non-null exactly while a SEARCH SNAPSHOT is on the canvas. A snapshot is
      a picture of a search state: it was never encoded, never validated, and
      must never be mistaken for something pasteable. */
  snapshotLabel: string | null;
  /** The frame the canvas' overlays are drawn from -- `null` off a real load
      (see `load`) and while no trace has produced one yet. */
  traceFrame: TraceFrame | null;
  traceShow: TraceOverlayShow;
  load(text: string): void;
  loadSnapshot(bp: Blueprint, label: string): void;
  setTraceFrame(frame: TraceFrame | null): void;
  setTraceShow(show: TraceOverlayShow): void;
  select(index: number | null): void;
  markStale(): void;
}

const Ctx = createContext<BlueprintState | null>(null);

export function BlueprintProvider({
  catalog,
  children,
}: {
  catalog: Catalog;
  children: ReactNode;
}) {
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [stale, setStale] = useState(false);
  const [snapshotLabel, setSnapshotLabel] = useState<string | null>(null);
  const [traceFrame, setTraceFrame] = useState<TraceFrame | null>(null);
  const [traceShow, setTraceShow] = useState<TraceOverlayShow>({
    stranded: true,
    noGoods: true,
  });

  // Derived during render. Do NOT move this into state or an effect; the React
  // Compiler memoizes it, and buildSceneModel is pure.
  const sceneModel = blueprint ? buildSceneModel(blueprint, catalog) : null;

  const load = (text: string) => {
    setStale(false);
    // A real load replaces whatever search snapshot was on the canvas -- this
    // is a validated result, not a picture of the search that found it.
    setSnapshotLabel(null);
    setTraceFrame(null);
    try {
      setBlueprint(parseBlueprint(text));
      setError(null);
    } catch (cause) {
      setBlueprint(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
    setSelectedIndex(null);
  };

  // Takes an already-built Blueprint -- never `parseBlueprint`, never a
  // pasted string -- and leaves `stale` alone (Ruling 5, task-5-addendum.md):
  // a non-null `snapshotLabel` alongside the existing `stale` machinery is
  // what stops a trace frame being mistaken for a real result.
  const loadSnapshot = (bp: Blueprint, label: string) => {
    setBlueprint(bp);
    setSnapshotLabel(label);
  };

  const value: BlueprintState = {
    blueprint,
    sceneModel,
    catalog,
    error,
    selectedIndex,
    // Nothing loaded is not stale, it is empty; the canvas says so itself.
    stale: stale && blueprint !== null,
    snapshotLabel,
    traceFrame,
    traceShow,
    load,
    loadSnapshot,
    setTraceFrame,
    setTraceShow,
    select: setSelectedIndex,
    markStale: () => setStale(true),
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBlueprint(): BlueprintState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBlueprint must be used inside <BlueprintProvider>');
  return v;
}
