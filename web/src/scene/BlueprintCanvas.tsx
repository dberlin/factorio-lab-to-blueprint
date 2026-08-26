import { Canvas } from '@react-three/fiber';
import { useEffect, useState } from 'react';
import { type Texture, TextureLoader } from 'three';
import { buildOverlays } from '../model/overlays';
import type { Atlas } from '../model/schemas';
import { assetPath, isAbortError, loadAtlas } from '../state/assets';
import { useBlueprint } from '../state/BlueprintProvider';
import { BeltChevrons } from './BeltChevrons';
import { BuildingInstances } from './BuildingInstances';
import { CameraRig } from './CameraRig';
import { CountLabels } from './CountLabels';
import { IconInstances } from './IconInstances';

export function BlueprintCanvas() {
  const { sceneModel, selectedIndex, select, catalog } = useBlueprint();
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  const [atlasTexture, setAtlasTexture] = useState<Texture | null>(null);
  useEffect(() => {
    // Both loads are cancelled on unmount. Without that, an in-flight request
    // outlives the component: React warns about setting state on an unmounted
    // tree, StrictMode's double-invoke leaks the first Texture, and a test
    // environment that aborts pending tasks at teardown (happy-dom >=20)
    // surfaces the abort as an unhandled DOMException.
    const controller = new AbortController();
    let cancelled = false;

    loadAtlas(controller.signal).then(
      (loaded) => {
        if (!cancelled) setAtlas(loaded);
      },
      (cause: unknown) => {
        if (!cancelled && !isAbortError(cause)) setAtlas(null);
      },
    );

    // Loaded here, outside <Canvas>, with a plain non-suspending callback —
    // not via r3f's useLoader inside the scene graph. useLoader suspends,
    // and a child of <Canvas> suspending with no ancestor <Suspense> stalls
    // <Canvas>'s own resize machinery (see IconInstances.tsx for the full
    // mechanism). Loading once here and passing the resolved texture down
    // as a prop avoids that entirely.
    new TextureLoader().load(
      assetPath('icons/atlas.png'),
      (texture) => {
        // Nobody will render it, so release the GPU handle rather than leak it.
        if (cancelled) texture.dispose();
        else setAtlasTexture(texture);
      },
      undefined,
      () => {
        if (!cancelled) setAtlasTexture(null);
      },
    );

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);
  if (!sceneModel) return <div className="canvas-empty">Load a blueprint to see it.</div>;

  const overlays = atlas ? buildOverlays(sceneModel, catalog, atlas) : null;

  return (
    <Canvas
      orthographic
      dpr={[1, 2]}
      className="canvas"
      // react-use-measure (which r3f uses to size the canvas) hands the SAME
      // debounced callback to both its ResizeObserver and its scroll listener,
      // and that debounce shares a single timer. r3f's default is
      // `{ scroll: true, debounce: { scroll: 50, resize: 0 } }`, so the canvas'
      // one and only ResizeObserver delivery — the initial observation, since
      // the container size never changes afterwards — is queued behind a 50ms
      // timer that any scroll event resets. A scroll (e.g. trackpad inertia in
      // the blueprint textarea) starves that timer forever and the canvas is
      // never sized at all. Dropping the debounce removes the timer, and
      // scroll tracking is unnecessary in a non-scrolling 100vh grid layout.
      resize={{ debounce: 0, scroll: false }}
    >
      <color attach="background" args={['#10141a']} />
      <hemisphereLight args={['#cfe3ff', '#2a2f38', 1.1]} />
      <directionalLight position={[40, 80, 30]} intensity={1.4} />
      <CameraRig model={sceneModel} />
      <BuildingInstances model={sceneModel} selectedIndex={selectedIndex} onSelect={select} />
      <BeltChevrons model={sceneModel} />
      {atlas && atlasTexture && overlays && (
        <>
          <IconInstances placements={overlays.icons} atlas={atlas} texture={atlasTexture} />
          <CountLabels placements={overlays.counts} />
        </>
      )}
      <gridHelper args={[400, 400, '#223', '#1a1f27']} />
    </Canvas>
  );
}
