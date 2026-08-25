import { createContext, type ReactNode, useContext, useState } from 'react';
import { type Blueprint, parseBlueprint } from '../format';
import type { Catalog } from '../model/catalog';
import { buildSceneModel, type SceneModel } from '../model/layout';

export interface BlueprintState {
  blueprint: Blueprint | null;
  sceneModel: SceneModel | null;
  catalog: Catalog;
  error: string | null;
  selectedIndex: number | null;
  load(text: string): void;
  select(index: number | null): void;
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

  // Derived during render. Do NOT move this into state or an effect; the React
  // Compiler memoizes it, and buildSceneModel is pure.
  const sceneModel = blueprint ? buildSceneModel(blueprint, catalog) : null;

  const load = (text: string) => {
    try {
      setBlueprint(parseBlueprint(text));
      setError(null);
    } catch (cause) {
      setBlueprint(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
    setSelectedIndex(null);
  };

  const value: BlueprintState = {
    blueprint,
    sceneModel,
    catalog,
    error,
    selectedIndex,
    load,
    select: setSelectedIndex,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBlueprint(): BlueprintState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBlueprint must be used inside <BlueprintProvider>');
  return v;
}
