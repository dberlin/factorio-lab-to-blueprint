/** Little-endian reader over a byte buffer. Every read is bounds-checked. */
export class BinaryReader {
  offset = 0;
  private readonly view: DataView;
  private readonly bytes: Uint8Array;

  constructor(bytes: Uint8Array) {
    this.bytes = bytes;
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  }

  get remaining(): number {
    return this.view.byteLength - this.offset;
  }

  private need(n: number): number {
    const at = this.offset;
    if (at + n > this.view.byteLength) {
      throw new RangeError(
        `read of ${n} byte(s) at offset ${at} exceeds buffer length ${this.view.byteLength}`,
      );
    }
    this.offset = at + n;
    return at;
  }

  skip(n: number): void {
    this.need(n);
  }

  i8(): number {
    return this.view.getInt8(this.need(1));
  }
  u8(): number {
    return this.view.getUint8(this.need(1));
  }
  i16(): number {
    return this.view.getInt16(this.need(2), true);
  }
  u16(): number {
    return this.view.getUint16(this.need(2), true);
  }
  i32(): number {
    return this.view.getInt32(this.need(4), true);
  }
  u32(): number {
    return this.view.getUint32(this.need(4), true);
  }
  f32(): number {
    return this.view.getFloat32(this.need(4), true);
  }

  /** 7-bit encoded length, as written by C# BinaryWriter. */
  leb(): number {
    let result = 0;
    let shift = 0;
    for (let i = 0; i < 5; i++) {
      const b = this.u8();
      // Multiply rather than shift: `<<` is 32-bit signed and overflows to a
      // negative length on the 5th byte, which would slip past every bounds check.
      result += (b & 0x7f) * 2 ** shift;
      if ((b & 0x80) === 0) {
        if (result < 0 || result > 0x7fffffff) {
          throw new RangeError(`LEB128 length out of range: ${result}`);
        }
        return result;
      }
      shift += 7;
    }
    throw new RangeError('LEB128 length is too long (more than 5 bytes)');
  }

  /** C# BinaryWriter.Write(string): LEB128 byte length then UTF-8. */
  string(): string {
    const len = this.leb();
    const at = this.need(len);
    return new TextDecoder().decode(this.bytes.subarray(at, at + len));
  }
}
