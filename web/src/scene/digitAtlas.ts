import { CanvasTexture, type WebGLProgramParametersWithUniforms } from 'three';

const DIGIT_CELL = 64;
export const DIGIT_COLS = 10;

/**
 * A 10-cell strip of digit glyphs, drawn at runtime.
 *
 * Digits are not game data, so generating them here keeps the asset extractor
 * untouched and adds no font file to the repo. Shared by the belt-tag counts
 * and the belt-run numbers: both draw digits as instanced quads that index one
 * cell of this strip, so they must agree on the cell count and the layout.
 */
export function makeDigitTexture(): CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = DIGIT_CELL * DIGIT_COLS;
  canvas.height = DIGIT_CELL;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error(
      'makeDigitTexture: canvas 2D context unavailable, so the digit glyph strip cannot be ' +
        'drawn -- every belt count would silently render as nothing.',
    );
  }
  ctx.fillStyle = '#ffffff';
  ctx.font = `bold ${DIGIT_CELL * 0.8}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let d = 0; d < DIGIT_COLS; d++) {
    ctx.fillText(String(d), d * DIGIT_CELL + DIGIT_CELL / 2, DIGIT_CELL / 2);
  }
  return new CanvasTexture(canvas);
}

/**
 * Rewrites a material's shader to sample one cell of the digit strip, chosen
 * per instance by the `digitOffset` attribute (the digit's value / 10).
 *
 * Single-row strip, so only u is offset; unlike the icon atlas there is no
 * multi-row flipY correction to undo here.
 */
export function patchDigitShader(shader: WebGLProgramParametersWithUniforms): void {
  shader.vertexShader = shader.vertexShader
    .replace(
      '#include <common>',
      `#include <common>\nattribute float digitOffset;\nvarying float vDigit;`,
    )
    .replace('#include <uv_vertex>', `#include <uv_vertex>\nvDigit = digitOffset;`);
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', `#include <common>\nvarying float vDigit;`)
    .replace(
      '#include <map_fragment>',
      `vec2 digitUv = vec2( vDigit + vMapUv.x * ${1 / DIGIT_COLS}, vMapUv.y );
       vec4 sampled = texture2D( map, digitUv );
       if ( sampled.a < 0.1 ) discard;
       diffuseColor *= sampled;`,
    );
}
