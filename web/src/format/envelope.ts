import { gunzipSync } from 'fflate';
import { md5f } from './md5f';
import type { BlueprintHeader } from './types';

export class BlueprintFormatError extends Error {}

export interface Envelope {
  header: BlueprintHeader;
  payload: Uint8Array;
  hashValid: boolean;
}

const FACTORY_PREFIX = 'BLUEPRINT:';
const DYSON_PREFIX = 'DYBP:';

function int(value: string | undefined, what: string): number {
  const n = Number(value);
  if (!Number.isFinite(n)) throw new BlueprintFormatError(`${what} is not a number: ${value}`);
  return n;
}

function big(value: string | undefined, what: string): bigint {
  try {
    return BigInt(value ?? '0');
  } catch {
    throw new BlueprintFormatError(`${what} is not an integer: ${value}`);
  }
}

const decode = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function parseEnvelope(text: string): Envelope {
  const raw = text.trim();

  if (raw.startsWith(DYSON_PREFIX)) {
    throw new BlueprintFormatError(
      'This is a Dyson sphere blueprint (DYBP). Only factory blueprints are supported.',
    );
  }
  if (!raw.startsWith(FACTORY_PREFIX)) {
    throw new BlueprintFormatError('Not a blueprint string (expected it to start with BLUEPRINT:)');
  }

  const firstQuote = raw.indexOf('"');
  const lastQuote = raw.lastIndexOf('"');
  if (firstQuote < 0 || lastQuote <= firstQuote) {
    throw new BlueprintFormatError('Malformed blueprint: missing the quoted payload section');
  }

  // The hash covers everything up to but NOT including the closing quote.
  const hashValid =
    md5f(new TextEncoder().encode(raw.slice(0, lastQuote))) ===
    raw
      .slice(lastQuote + 1)
      .trim()
      .toUpperCase();

  const cells = raw.slice(FACTORY_PREFIX.length, firstQuote).split(',');
  const headerVersion = int(cells[0], 'header version');

  // headerVersion 0 -> 12 fields; headerVersion 1 -> 15 fields.
  const header: BlueprintHeader = {
    headerVersion,
    layout: int(cells[1], 'layout'),
    icons: [2, 3, 4, 5, 6].map((i) => int(cells[i], `icon ${i - 2}`)),
    timestamp: big(cells[8], 'timestamp'),
    gameVersion: cells[9] ?? '',
    shortDesc: decode(cells[10] ?? ''),
    author: headerVersion >= 1 ? decode(cells[11] ?? '') : '',
    customVersion: headerVersion >= 1 ? decode(cells[12] ?? '') : '',
    attributes:
      headerVersion >= 1
        ? decode(cells[13] ?? '')
            .split(';')
            .filter(Boolean)
        : [],
    description: decode((headerVersion >= 1 ? cells[14] : cells[11]) ?? ''),
  };

  const b64 = raw.slice(firstQuote + 1, lastQuote);
  let payload: Uint8Array;
  try {
    const bin = atob(b64);
    const gz = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) gz[i] = bin.charCodeAt(i);
    payload = gunzipSync(gz);
  } catch (cause) {
    throw new BlueprintFormatError(`Could not decode the blueprint payload: ${String(cause)}`);
  }

  return { header, payload, hashValid };
}
