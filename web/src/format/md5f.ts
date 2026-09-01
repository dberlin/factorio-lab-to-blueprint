/**
 * DSP's MD5 variant ("MD5F"). Identical to RFC 1321 MD5 except:
 * - Two of the four init constants have swapped nibbles:
 *   B: 0xEFCDAB89 -> 0xEFDCAB89
 *   D: 0x10325476 -> 0x10325746
 * - Eight of the 64 round constants are altered (cannot be computed from Math.sin)
 * Padding and shifts are standard.
 */

const S = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14,
  20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6,
  10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

/**
 * MD5F's round constants. These are the standard MD5 sine-derived constants
 * EXCEPT for eight entries (marked below), so they cannot be computed from
 * Math.sin and must be hardcoded. These values reproduce the embedded
 * checksums of all 11 blueprint fixtures.
 */
const T = new Uint32Array([
  0xd76aa478,
  0xe8d7b756,
  0x242070db,
  0xc1bdceee, // [1] altered
  0xf57c0faf,
  0x4787c62a,
  0xa8304623,
  0xfd469501,
  0x698098d8,
  0x8b44f7af,
  0xffff5bb1,
  0x895cd7be,
  0x6b9f1122,
  0xfd987193,
  0xa679438e,
  0x39b40821, // [12], [15] altered
  0xf61e2562,
  0xc040b340,
  0x265e5a51,
  0xc9b6c7aa,
  0xd62f105d,
  0x02443453,
  0xd8a1e681,
  0xe7d3fbc8, // [21] altered
  0x21f1cde6,
  0xc33707d6,
  0xf4d50d87,
  0x475a14ed, // [24], [27] altered
  0xa9e3e905,
  0xfcefa3f8,
  0x676f02d9,
  0x8d2a4c8a,
  0xfffa3942,
  0x8771f681,
  0x6d9d6122,
  0xfde5380c,
  0xa4beea44,
  0x4bdecfa9,
  0xf6bb4b60,
  0xbebfbc70,
  0x289b7ec6,
  0xeaa127fa,
  0xd4ef3085,
  0x04881d05,
  0xd9d4d039,
  0xe6db99e5,
  0x1fa27cf8,
  0xc4ac5665,
  0xf4292244,
  0x432aff97,
  0xab9423a7,
  0xfc93a039,
  0x655b59c3,
  0x8f0ccc92,
  0xffeff47d,
  0x85845dd1,
  0x6fa87e4f,
  0xfe2ce6e0,
  0xa3014314,
  0x4e0811a1,
  0xf7537e82,
  0xbd3af235,
  0x2ad7d2bb,
  0xeb86d391,
]);

const rotl = (x: number, c: number) => (x << c) | (x >>> (32 - c));

export function md5f(input: Uint8Array): string {
  const bitLen = input.length * 8;
  const padded = new Uint8Array((((input.length + 8) >> 6) + 1) << 6);
  padded.set(input);
  padded[input.length] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, bitLen >>> 0, true);
  dv.setUint32(padded.length - 4, Math.floor(bitLen / 4294967296), true);

  let a0 = 0x67452301;
  let b0 = 0xefdcab89; // MD5F (standard MD5 is 0xEFCDAB89)
  let c0 = 0x98badcfe;
  let d0 = 0x10325746; // MD5F (standard MD5 is 0x10325476)

  const M = new Uint32Array(16);
  for (let chunk = 0; chunk < padded.length; chunk += 64) {
    for (let i = 0; i < 16; i++) M[i] = dv.getUint32(chunk + i * 4, true);

    let a = a0;
    let b = b0;
    let c = c0;
    let d = d0;

    for (let i = 0; i < 64; i++) {
      let f: number;
      let g: number;
      if (i < 16) {
        f = (b & c) | (~b & d);
        g = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        g = (5 * i + 1) % 16;
      } else if (i < 48) {
        f = b ^ c ^ d;
        g = (3 * i + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        g = (7 * i) % 16;
      }
      const tmp = d;
      d = c;
      c = b;
      // oxlint-disable-next-line typescript/no-non-null-assertion -- required by noUncheckedIndexedAccess
      b = (b + rotl((a + f + T[i]! + M[g]!) | 0, S[i]!)) | 0;
      a = tmp;
    }

    a0 = (a0 + a) | 0;
    b0 = (b0 + b) | 0;
    c0 = (c0 + c) | 0;
    d0 = (d0 + d) | 0;
  }

  const out = new DataView(new ArrayBuffer(16));
  out.setUint32(0, a0 >>> 0, true);
  out.setUint32(4, b0 >>> 0, true);
  out.setUint32(8, c0 >>> 0, true);
  out.setUint32(12, d0 >>> 0, true);

  let hex = '';
  for (let i = 0; i < 16; i++) hex += out.getUint8(i).toString(16).padStart(2, '0');
  return hex.toUpperCase();
}
