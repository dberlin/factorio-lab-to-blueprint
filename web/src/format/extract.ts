/**
 * Finding a blueprint string inside a fetched web page.
 *
 * Blueprint sites embed the string in a `<textarea>`, which means the HTML
 * serialiser escapes it: the two quotes that delimit the gzip payload arrive as
 * `&quot;`, not `"`. Matching the raw body therefore fails on the one site the
 * URL input actually targets, so the body is entity-decoded before matching.
 */

/**
 * The shape of a blueprint string:
 *   BLUEPRINT:<csv header>"<base64 payload>"<32 hex MD5F digest>
 * The header is percent-encoded and the payload is base64, so neither can
 * legally contain a `"` -- which is what makes the quote-delimited match safe.
 */
const BLUEPRINT = /BLUEPRINT:[^"]*"[^"]*"[0-9A-Fa-f]{32}/;

const NAMED_ENTITIES: Record<string, string> = {
  quot: '"',
  apos: "'",
  amp: '&',
  lt: '<',
  gt: '>',
  nbsp: ' ',
};

const ENTITY = /&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g;

/**
 * Decodes HTML entities in a single left-to-right pass.
 *
 * Single-pass is the point, not an optimisation. Decoding `&amp;` in a separate
 * sweep -- in any order -- turns the literal text `&amp;quot;` into `&quot;` and
 * then into a spurious `"`, which would split a blueprint string in the wrong
 * place. Because `replace` resumes scanning *after* each match, `&amp;quot;`
 * here yields `&quot;` and stops, which is the correct single decoding step.
 *
 * Unknown entities are left verbatim rather than dropped, so nothing in the
 * payload can be silently deleted.
 */
export function decodeHtmlEntities(text: string): string {
  return text.replace(ENTITY, (whole, body: string) => {
    if (body.startsWith('#')) {
      const hex = body[1] === 'x' || body[1] === 'X';
      const code = Number.parseInt(hex ? body.slice(2) : body.slice(1), hex ? 16 : 10);
      if (!Number.isInteger(code) || code < 0 || code > 0x10ffff) return whole;
      return String.fromCodePoint(code);
    }
    return NAMED_ENTITIES[body.toLowerCase()] ?? whole;
  });
}

/**
 * Extracts the first blueprint string from a fetched body, or null if there is
 * none.
 *
 * The raw body is tried first so a plain `.txt` URL -- already literal quotes,
 * no markup -- is returned byte-for-byte without going through the decoder.
 * Only if that fails is the body entity-decoded and retried, and the substring
 * returned is taken from whichever form matched, so the captured string is
 * always internally consistent.
 */
export function findBlueprintString(body: string): string | null {
  return BLUEPRINT.exec(body)?.[0] ?? BLUEPRINT.exec(decodeHtmlEntities(body))?.[0] ?? null;
}
