import { createContext, type ReactNode, useCallback, useContext, useRef, useState } from 'react';
import type { TraceFrame } from '../api/trace';
import { type Blueprint, parseBlueprint } from '../format';
import type { Catalog } from '../model/catalog';
import { buildSceneModel, type SceneModel } from '../model/layout';
import { traceFrameLabel, traceFrameToBlueprint } from '../model/traceScene';

/** How the machines are drawn. Ghosted by default: the belts, their numbers
    and the sorters that serve them all sit at ground level, and a solid
    machine block hides most of them -- 73% of the heretical smelter block's
    footprint is machine. Solid is one click away for anyone who wants it. */
export type MachineLook = 'solid' | 'ghosted' | 'hidden';

/** Layers the viewer can quiet on a busy blueprint. All default on. */
export interface ViewOptions {
  /** The run number drawn on each strip. */
  beltLabels: boolean;
  /** The sorter direction markings and the tie lines to off-port ends. */
  sorterTies: boolean;
  /** The inferred item icon at each free belt-run end. */
  endpointIcons: boolean;
  machines: MachineLook;
}

/** Which trace overlay layers are on. Independent toggles (task-10-addendum.md
    Ruling 4): a layer contributes nothing when off, regardless of the other. */
export interface TraceOverlayShow {
  stranded: boolean;
  noGoods: boolean;
}

export type ArtifactSource = { kind: 'import' } | { kind: 'build'; jobId: string };

export type DisplayedDocument =
  | {
      kind: 'artifact';
      generation: number;
      blueprint: Blueprint;
      text: string;
      source: ArtifactSource;
    }
  | {
      kind: 'trace';
      generation: number;
      blueprint: Blueprint;
      frame: TraceFrame;
      label: string;
      jobId: string;
    };

interface DisplayState {
  document: DisplayedDocument | null;
  error: string | null;
  selectedIndex: number | null;
  stale: boolean;
}

export interface BlueprintState {
  document: DisplayedDocument | null;
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
  /** Derived from the displayed trace document; absent for encoded artifacts. */
  traceFrame: TraceFrame | null;
  traceShow: TraceOverlayShow;
  view: ViewOptions;
  setView(view: ViewOptions): void;
  beginPublication(): number;
  publishArtifact(text: string, generation: number, source?: ArtifactSource): boolean;
  failPublication(message: string, generation: number): void;
  publishTrace(frame: TraceFrame, jobId: string, generation: number): boolean;
  selectTrace(frame: TraceFrame, jobId: string): number;
  setTraceShow(show: TraceOverlayShow): void;
  select(index: number | null): void;
  markStale(generation: number): void;
}

const Ctx = createContext<BlueprintState | null>(null);

export function BlueprintProvider({
  catalog,
  children,
}: {
  catalog: Catalog;
  children: ReactNode;
}) {
  const [display, setDisplay] = useState<DisplayState>({
    document: null,
    error: null,
    selectedIndex: null,
    stale: false,
  });
  // Async producers hold tokens, not setters. Ref admission is synchronous even
  // when React batches a manual selection and an older completion together.
  const authority = useRef({ generation: 0, automaticTrace: true });
  const [traceShow, setTraceShow] = useState<TraceOverlayShow>({
    stranded: true,
    noGoods: true,
  });
  const [view, setView] = useState<ViewOptions>({
    beltLabels: true,
    sorterTies: true,
    endpointIcons: true,
    machines: 'ghosted',
  });

  const beginPublication = useCallback(() => {
    const generation = authority.current.generation + 1;
    authority.current = { generation, automaticTrace: true };
    return generation;
  }, []);

  const publishArtifact = useCallback(
    (text: string, generation: number, source: ArtifactSource = { kind: 'import' }) => {
      if (generation !== authority.current.generation) return false;
      authority.current.automaticTrace = false;
      try {
        const blueprint = parseBlueprint(text);
        setDisplay({
          document: { kind: 'artifact', generation, blueprint, text, source },
          error: null,
          selectedIndex: null,
          stale: false,
        });
      } catch (cause) {
        setDisplay({
          document: null,
          error: cause instanceof Error ? cause.message : String(cause),
          selectedIndex: null,
          stale: false,
        });
      }
      return true;
    },
    [],
  );

  const failPublication = useCallback((error: string, generation: number) => {
    if (generation === authority.current.generation) {
      setDisplay((previous) => ({ ...previous, error }));
    }
  }, []);

  const publishTrace = useCallback((frame: TraceFrame, jobId: string, generation: number) => {
    if (generation !== authority.current.generation || !authority.current.automaticTrace)
      return false;
    const document: DisplayedDocument = {
      kind: 'trace',
      generation,
      jobId,
      frame,
      blueprint: traceFrameToBlueprint(frame),
      label: traceFrameLabel(frame),
    };
    setDisplay({ document, error: null, selectedIndex: null, stale: false });
    return true;
  }, []);

  const selectTrace = useCallback(
    (frame: TraceFrame, jobId: string) => {
      const generation = beginPublication();
      publishTrace(frame, jobId, generation);
      return generation;
    },
    [beginPublication, publishTrace],
  );

  const select = useCallback((selectedIndex: number | null) => {
    setDisplay((previous) => ({ ...previous, selectedIndex }));
  }, []);
  const markStale = useCallback((generation: number) => {
    if (generation === authority.current.generation) {
      setDisplay((previous) => ({ ...previous, stale: previous.document !== null }));
    }
  }, []);

  const { document, error, selectedIndex, stale } = display;
  const blueprint = document?.blueprint ?? null;
  // Derived, not another publication authority. The React Compiler memoizes it.
  const sceneModel = blueprint ? buildSceneModel(blueprint, catalog) : null;

  const value: BlueprintState = {
    document,
    blueprint,
    sceneModel,
    catalog,
    error,
    selectedIndex,
    stale,
    snapshotLabel: document?.kind === 'trace' ? document.label : null,
    traceFrame: document?.kind === 'trace' ? document.frame : null,
    traceShow,
    view,
    setView,
    beginPublication,
    publishArtifact,
    failPublication,
    publishTrace,
    selectTrace,
    setTraceShow,
    select,
    markStale,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBlueprint(): BlueprintState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBlueprint must be used inside <BlueprintProvider>');
  return v;
}
