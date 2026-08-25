var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf, __hasOwnProp = Object.prototype.hasOwnProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __require = /* @__PURE__ */ ((x) => typeof require < "u" ? require : typeof Proxy < "u" ? new Proxy(x, {
  get: (a, b) => (typeof require < "u" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require < "u") return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});
var __commonJS = (cb, mod) => function() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from == "object" || typeof from == "function")
    for (let key of __getOwnPropNames(from))
      !__hasOwnProp.call(to, key) && key !== except && __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: !0 }) : target,
  mod
));
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);

// node_modules/@protobufjs/aspromise/index.js
var require_aspromise = __commonJS({
  "node_modules/@protobufjs/aspromise/index.js"(exports, module) {
    "use strict";
    module.exports = asPromise;
    function asPromise(fn, ctx) {
      for (var params = new Array(arguments.length - 1), offset = 0, index = 2, pending = !0; index < arguments.length; )
        params[offset++] = arguments[index++];
      return new Promise(function(resolve, reject) {
        params[offset] = function(err) {
          if (pending)
            if (pending = !1, err)
              reject(err);
            else {
              for (var params2 = new Array(arguments.length - 1), offset2 = 0; offset2 < params2.length; )
                params2[offset2++] = arguments[offset2];
              resolve.apply(null, params2);
            }
        };
        try {
          fn.apply(ctx || null, params);
        } catch (err) {
          pending && (pending = !1, reject(err));
        }
      });
    }
  }
});

// node_modules/@protobufjs/base64/index.js
var require_base64 = __commonJS({
  "node_modules/@protobufjs/base64/index.js"(exports) {
    "use strict";
    var base64 = exports;
    base64.length = function(string) {
      var p = string.length;
      if (!p)
        return 0;
      for (var n = 0; --p % 4 > 1 && string.charAt(p) === "="; )
        ++n;
      return Math.ceil(string.length * 3) / 4 - n;
    };
    var b64 = new Array(64), s64 = new Array(123);
    for (i = 0; i < 64; )
      s64[b64[i] = i < 26 ? i + 65 : i < 52 ? i + 71 : i < 62 ? i - 4 : i - 59 | 43] = i++;
    var i;
    base64.encode = function(buffer, start, end) {
      for (var parts = null, chunk = [], i2 = 0, j = 0, t; start < end; ) {
        var b = buffer[start++];
        switch (j) {
          case 0:
            chunk[i2++] = b64[b >> 2], t = (b & 3) << 4, j = 1;
            break;
          case 1:
            chunk[i2++] = b64[t | b >> 4], t = (b & 15) << 2, j = 2;
            break;
          case 2:
            chunk[i2++] = b64[t | b >> 6], chunk[i2++] = b64[b & 63], j = 0;
            break;
        }
        i2 > 8191 && ((parts || (parts = [])).push(String.fromCharCode.apply(String, chunk)), i2 = 0);
      }
      return j && (chunk[i2++] = b64[t], chunk[i2++] = 61, j === 1 && (chunk[i2++] = 61)), parts ? (i2 && parts.push(String.fromCharCode.apply(String, chunk.slice(0, i2))), parts.join("")) : String.fromCharCode.apply(String, chunk.slice(0, i2));
    };
    var invalidEncoding = "invalid encoding";
    base64.decode = function(string, buffer, offset) {
      for (var start = offset, j = 0, t, i2 = 0; i2 < string.length; ) {
        var c = string.charCodeAt(i2++);
        if (c === 61 && j > 1)
          break;
        if ((c = s64[c]) === void 0)
          throw Error(invalidEncoding);
        switch (j) {
          case 0:
            t = c, j = 1;
            break;
          case 1:
            buffer[offset++] = t << 2 | (c & 48) >> 4, t = c, j = 2;
            break;
          case 2:
            buffer[offset++] = (t & 15) << 4 | (c & 60) >> 2, t = c, j = 3;
            break;
          case 3:
            buffer[offset++] = (t & 3) << 6 | c, j = 0;
            break;
        }
      }
      if (j === 1)
        throw Error(invalidEncoding);
      return offset - start;
    };
    base64.test = function(string) {
      return /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(string);
    };
  }
});

// node_modules/@protobufjs/eventemitter/index.js
var require_eventemitter = __commonJS({
  "node_modules/@protobufjs/eventemitter/index.js"(exports, module) {
    "use strict";
    module.exports = EventEmitter;
    function EventEmitter() {
      this._listeners = {};
    }
    EventEmitter.prototype.on = function(evt, fn, ctx) {
      return (this._listeners[evt] || (this._listeners[evt] = [])).push({
        fn,
        ctx: ctx || this
      }), this;
    };
    EventEmitter.prototype.off = function(evt, fn) {
      if (evt === void 0)
        this._listeners = {};
      else if (fn === void 0)
        this._listeners[evt] = [];
      else
        for (var listeners = this._listeners[evt], i = 0; i < listeners.length; )
          listeners[i].fn === fn ? listeners.splice(i, 1) : ++i;
      return this;
    };
    EventEmitter.prototype.emit = function(evt) {
      var listeners = this._listeners[evt];
      if (listeners) {
        for (var args = [], i = 1; i < arguments.length; )
          args.push(arguments[i++]);
        for (i = 0; i < listeners.length; )
          listeners[i].fn.apply(listeners[i++].ctx, args);
      }
      return this;
    };
  }
});

// node_modules/@protobufjs/float/index.js
var require_float = __commonJS({
  "node_modules/@protobufjs/float/index.js"(exports, module) {
    "use strict";
    module.exports = factory(factory);
    function factory(exports2) {
      return typeof Float32Array < "u" ? (function() {
        var f32 = new Float32Array([-0]), f8b = new Uint8Array(f32.buffer), le = f8b[3] === 128;
        function writeFloat_f32_cpy(val, buf, pos) {
          f32[0] = val, buf[pos] = f8b[0], buf[pos + 1] = f8b[1], buf[pos + 2] = f8b[2], buf[pos + 3] = f8b[3];
        }
        function writeFloat_f32_rev(val, buf, pos) {
          f32[0] = val, buf[pos] = f8b[3], buf[pos + 1] = f8b[2], buf[pos + 2] = f8b[1], buf[pos + 3] = f8b[0];
        }
        exports2.writeFloatLE = le ? writeFloat_f32_cpy : writeFloat_f32_rev, exports2.writeFloatBE = le ? writeFloat_f32_rev : writeFloat_f32_cpy;
        function readFloat_f32_cpy(buf, pos) {
          return f8b[0] = buf[pos], f8b[1] = buf[pos + 1], f8b[2] = buf[pos + 2], f8b[3] = buf[pos + 3], f32[0];
        }
        function readFloat_f32_rev(buf, pos) {
          return f8b[3] = buf[pos], f8b[2] = buf[pos + 1], f8b[1] = buf[pos + 2], f8b[0] = buf[pos + 3], f32[0];
        }
        exports2.readFloatLE = le ? readFloat_f32_cpy : readFloat_f32_rev, exports2.readFloatBE = le ? readFloat_f32_rev : readFloat_f32_cpy;
      })() : (function() {
        function writeFloat_ieee754(writeUint, val, buf, pos) {
          var sign = val < 0 ? 1 : 0;
          if (sign && (val = -val), val === 0)
            writeUint(1 / val > 0 ? (
              /* positive */
              0
            ) : (
              /* negative 0 */
              2147483648
            ), buf, pos);
          else if (isNaN(val))
            writeUint(2143289344, buf, pos);
          else if (val > 34028234663852886e22)
            writeUint((sign << 31 | 2139095040) >>> 0, buf, pos);
          else if (val < 11754943508222875e-54)
            writeUint((sign << 31 | Math.round(val / 1401298464324817e-60)) >>> 0, buf, pos);
          else {
            var exponent = Math.floor(Math.log(val) / Math.LN2), mantissa = Math.round(val * Math.pow(2, -exponent) * 8388608) & 8388607;
            writeUint((sign << 31 | exponent + 127 << 23 | mantissa) >>> 0, buf, pos);
          }
        }
        exports2.writeFloatLE = writeFloat_ieee754.bind(null, writeUintLE), exports2.writeFloatBE = writeFloat_ieee754.bind(null, writeUintBE);
        function readFloat_ieee754(readUint, buf, pos) {
          var uint = readUint(buf, pos), sign = (uint >> 31) * 2 + 1, exponent = uint >>> 23 & 255, mantissa = uint & 8388607;
          return exponent === 255 ? mantissa ? NaN : sign * (1 / 0) : exponent === 0 ? sign * 1401298464324817e-60 * mantissa : sign * Math.pow(2, exponent - 150) * (mantissa + 8388608);
        }
        exports2.readFloatLE = readFloat_ieee754.bind(null, readUintLE), exports2.readFloatBE = readFloat_ieee754.bind(null, readUintBE);
      })(), typeof Float64Array < "u" ? (function() {
        var f64 = new Float64Array([-0]), f8b = new Uint8Array(f64.buffer), le = f8b[7] === 128;
        function writeDouble_f64_cpy(val, buf, pos) {
          f64[0] = val, buf[pos] = f8b[0], buf[pos + 1] = f8b[1], buf[pos + 2] = f8b[2], buf[pos + 3] = f8b[3], buf[pos + 4] = f8b[4], buf[pos + 5] = f8b[5], buf[pos + 6] = f8b[6], buf[pos + 7] = f8b[7];
        }
        function writeDouble_f64_rev(val, buf, pos) {
          f64[0] = val, buf[pos] = f8b[7], buf[pos + 1] = f8b[6], buf[pos + 2] = f8b[5], buf[pos + 3] = f8b[4], buf[pos + 4] = f8b[3], buf[pos + 5] = f8b[2], buf[pos + 6] = f8b[1], buf[pos + 7] = f8b[0];
        }
        exports2.writeDoubleLE = le ? writeDouble_f64_cpy : writeDouble_f64_rev, exports2.writeDoubleBE = le ? writeDouble_f64_rev : writeDouble_f64_cpy;
        function readDouble_f64_cpy(buf, pos) {
          return f8b[0] = buf[pos], f8b[1] = buf[pos + 1], f8b[2] = buf[pos + 2], f8b[3] = buf[pos + 3], f8b[4] = buf[pos + 4], f8b[5] = buf[pos + 5], f8b[6] = buf[pos + 6], f8b[7] = buf[pos + 7], f64[0];
        }
        function readDouble_f64_rev(buf, pos) {
          return f8b[7] = buf[pos], f8b[6] = buf[pos + 1], f8b[5] = buf[pos + 2], f8b[4] = buf[pos + 3], f8b[3] = buf[pos + 4], f8b[2] = buf[pos + 5], f8b[1] = buf[pos + 6], f8b[0] = buf[pos + 7], f64[0];
        }
        exports2.readDoubleLE = le ? readDouble_f64_cpy : readDouble_f64_rev, exports2.readDoubleBE = le ? readDouble_f64_rev : readDouble_f64_cpy;
      })() : (function() {
        function writeDouble_ieee754(writeUint, off0, off1, val, buf, pos) {
          var sign = val < 0 ? 1 : 0;
          if (sign && (val = -val), val === 0)
            writeUint(0, buf, pos + off0), writeUint(1 / val > 0 ? (
              /* positive */
              0
            ) : (
              /* negative 0 */
              2147483648
            ), buf, pos + off1);
          else if (isNaN(val))
            writeUint(0, buf, pos + off0), writeUint(2146959360, buf, pos + off1);
          else if (val > 17976931348623157e292)
            writeUint(0, buf, pos + off0), writeUint((sign << 31 | 2146435072) >>> 0, buf, pos + off1);
          else {
            var mantissa;
            if (val < 22250738585072014e-324)
              mantissa = val / 5e-324, writeUint(mantissa >>> 0, buf, pos + off0), writeUint((sign << 31 | mantissa / 4294967296) >>> 0, buf, pos + off1);
            else {
              var exponent = Math.floor(Math.log(val) / Math.LN2);
              exponent === 1024 && (exponent = 1023), mantissa = val * Math.pow(2, -exponent), writeUint(mantissa * 4503599627370496 >>> 0, buf, pos + off0), writeUint((sign << 31 | exponent + 1023 << 20 | mantissa * 1048576 & 1048575) >>> 0, buf, pos + off1);
            }
          }
        }
        exports2.writeDoubleLE = writeDouble_ieee754.bind(null, writeUintLE, 0, 4), exports2.writeDoubleBE = writeDouble_ieee754.bind(null, writeUintBE, 4, 0);
        function readDouble_ieee754(readUint, off0, off1, buf, pos) {
          var lo = readUint(buf, pos + off0), hi = readUint(buf, pos + off1), sign = (hi >> 31) * 2 + 1, exponent = hi >>> 20 & 2047, mantissa = 4294967296 * (hi & 1048575) + lo;
          return exponent === 2047 ? mantissa ? NaN : sign * (1 / 0) : exponent === 0 ? sign * 5e-324 * mantissa : sign * Math.pow(2, exponent - 1075) * (mantissa + 4503599627370496);
        }
        exports2.readDoubleLE = readDouble_ieee754.bind(null, readUintLE, 0, 4), exports2.readDoubleBE = readDouble_ieee754.bind(null, readUintBE, 4, 0);
      })(), exports2;
    }
    function writeUintLE(val, buf, pos) {
      buf[pos] = val & 255, buf[pos + 1] = val >>> 8 & 255, buf[pos + 2] = val >>> 16 & 255, buf[pos + 3] = val >>> 24;
    }
    function writeUintBE(val, buf, pos) {
      buf[pos] = val >>> 24, buf[pos + 1] = val >>> 16 & 255, buf[pos + 2] = val >>> 8 & 255, buf[pos + 3] = val & 255;
    }
    function readUintLE(buf, pos) {
      return (buf[pos] | buf[pos + 1] << 8 | buf[pos + 2] << 16 | buf[pos + 3] << 24) >>> 0;
    }
    function readUintBE(buf, pos) {
      return (buf[pos] << 24 | buf[pos + 1] << 16 | buf[pos + 2] << 8 | buf[pos + 3]) >>> 0;
    }
  }
});

// node_modules/@protobufjs/inquire/index.js
var require_inquire = __commonJS({
  "node_modules/@protobufjs/inquire/index.js"(exports, module) {
    "use strict";
    module.exports = inquire;
    function inquire(moduleName) {
      try {
        if (typeof __require != "function")
          return null;
        var mod = __require(moduleName);
        return mod && (mod.length || Object.keys(mod).length) ? mod : null;
      } catch {
        return null;
      }
    }
  }
});

// node_modules/@protobufjs/utf8/index.js
var require_utf8 = __commonJS({
  "node_modules/@protobufjs/utf8/index.js"(exports) {
    "use strict";
    var utf8 = exports, replacementChar = "\uFFFD";
    utf8.length = function(string) {
      for (var len = 0, c = 0, i = 0; i < string.length; ++i)
        c = string.charCodeAt(i), c < 128 ? len += 1 : c < 2048 ? len += 2 : (c & 64512) === 55296 && (string.charCodeAt(i + 1) & 64512) === 56320 ? (++i, len += 4) : len += 3;
      return len;
    };
    utf8.read = function(buffer, start, end) {
      if (end - start < 1)
        return "";
      for (var str = "", i = start; i < end; ) {
        var t = buffer[i++];
        if (t <= 127)
          str += String.fromCharCode(t);
        else if (t >= 192 && t < 224) {
          var c2 = (t & 31) << 6 | buffer[i++] & 63;
          str += c2 >= 128 ? String.fromCharCode(c2) : replacementChar;
        } else if (t >= 224 && t < 240) {
          var c3 = (t & 15) << 12 | (buffer[i++] & 63) << 6 | buffer[i++] & 63;
          str += c3 >= 2048 ? String.fromCharCode(c3) : replacementChar;
        } else if (t >= 240) {
          var t2 = (t & 7) << 18 | (buffer[i++] & 63) << 12 | (buffer[i++] & 63) << 6 | buffer[i++] & 63;
          t2 < 65536 || t2 > 1114111 ? str += replacementChar : (t2 -= 65536, str += String.fromCharCode(55296 + (t2 >> 10)), str += String.fromCharCode(56320 + (t2 & 1023)));
        }
      }
      return str;
    };
    utf8.write = function(string, buffer, offset) {
      for (var start = offset, c1, c2, i = 0; i < string.length; ++i)
        c1 = string.charCodeAt(i), c1 < 128 ? buffer[offset++] = c1 : c1 < 2048 ? (buffer[offset++] = c1 >> 6 | 192, buffer[offset++] = c1 & 63 | 128) : (c1 & 64512) === 55296 && ((c2 = string.charCodeAt(i + 1)) & 64512) === 56320 ? (c1 = 65536 + ((c1 & 1023) << 10) + (c2 & 1023), ++i, buffer[offset++] = c1 >> 18 | 240, buffer[offset++] = c1 >> 12 & 63 | 128, buffer[offset++] = c1 >> 6 & 63 | 128, buffer[offset++] = c1 & 63 | 128) : (buffer[offset++] = c1 >> 12 | 224, buffer[offset++] = c1 >> 6 & 63 | 128, buffer[offset++] = c1 & 63 | 128);
      return offset - start;
    };
  }
});

// node_modules/@protobufjs/pool/index.js
var require_pool = __commonJS({
  "node_modules/@protobufjs/pool/index.js"(exports, module) {
    "use strict";
    module.exports = pool;
    function pool(alloc, slice, size) {
      var SIZE = size || 8192, MAX = SIZE >>> 1, slab = null, offset = SIZE;
      return function(size2) {
        if (size2 < 1 || size2 > MAX)
          return alloc(size2);
        offset + size2 > SIZE && (slab = alloc(SIZE), offset = 0);
        var buf = slice.call(slab, offset, offset += size2);
        return offset & 7 && (offset = (offset | 7) + 1), buf;
      };
    }
  }
});

// node_modules/protobufjs/src/util/longbits.js
var require_longbits = __commonJS({
  "node_modules/protobufjs/src/util/longbits.js"(exports, module) {
    "use strict";
    module.exports = LongBits;
    var util = require_minimal();
    function LongBits(lo, hi) {
      this.lo = lo >>> 0, this.hi = hi >>> 0;
    }
    var zero = LongBits.zero = new LongBits(0, 0);
    zero.toNumber = function() {
      return 0;
    };
    zero.zzEncode = zero.zzDecode = function() {
      return this;
    };
    zero.length = function() {
      return 1;
    };
    var zeroHash = LongBits.zeroHash = "\0\0\0\0\0\0\0\0";
    LongBits.fromNumber = function(value) {
      if (value === 0)
        return zero;
      var sign = value < 0;
      sign && (value = -value);
      var lo = value >>> 0, hi = (value - lo) / 4294967296 >>> 0;
      return sign && (hi = ~hi >>> 0, lo = ~lo >>> 0, ++lo > 4294967295 && (lo = 0, ++hi > 4294967295 && (hi = 0))), new LongBits(lo, hi);
    };
    LongBits.from = function(value) {
      if (typeof value == "number")
        return LongBits.fromNumber(value);
      if (util.isString(value))
        if (util.Long)
          value = util.Long.fromString(value);
        else
          return LongBits.fromNumber(parseInt(value, 10));
      return value.low || value.high ? new LongBits(value.low >>> 0, value.high >>> 0) : zero;
    };
    LongBits.prototype.toNumber = function(unsigned) {
      if (!unsigned && this.hi >>> 31) {
        var lo = ~this.lo + 1 >>> 0, hi = ~this.hi >>> 0;
        return lo || (hi = hi + 1 >>> 0), -(lo + hi * 4294967296);
      }
      return this.lo + this.hi * 4294967296;
    };
    LongBits.prototype.toLong = function(unsigned) {
      return util.Long ? new util.Long(this.lo | 0, this.hi | 0, !!unsigned) : { low: this.lo | 0, high: this.hi | 0, unsigned: !!unsigned };
    };
    var charCodeAt = String.prototype.charCodeAt;
    LongBits.fromHash = function(hash) {
      return hash === zeroHash ? zero : new LongBits(
        (charCodeAt.call(hash, 0) | charCodeAt.call(hash, 1) << 8 | charCodeAt.call(hash, 2) << 16 | charCodeAt.call(hash, 3) << 24) >>> 0,
        (charCodeAt.call(hash, 4) | charCodeAt.call(hash, 5) << 8 | charCodeAt.call(hash, 6) << 16 | charCodeAt.call(hash, 7) << 24) >>> 0
      );
    };
    LongBits.prototype.toHash = function() {
      return String.fromCharCode(
        this.lo & 255,
        this.lo >>> 8 & 255,
        this.lo >>> 16 & 255,
        this.lo >>> 24,
        this.hi & 255,
        this.hi >>> 8 & 255,
        this.hi >>> 16 & 255,
        this.hi >>> 24
      );
    };
    LongBits.prototype.zzEncode = function() {
      var mask = this.hi >> 31;
      return this.hi = ((this.hi << 1 | this.lo >>> 31) ^ mask) >>> 0, this.lo = (this.lo << 1 ^ mask) >>> 0, this;
    };
    LongBits.prototype.zzDecode = function() {
      var mask = -(this.lo & 1);
      return this.lo = ((this.lo >>> 1 | this.hi << 31) ^ mask) >>> 0, this.hi = (this.hi >>> 1 ^ mask) >>> 0, this;
    };
    LongBits.prototype.length = function() {
      var part0 = this.lo, part1 = (this.lo >>> 28 | this.hi << 4) >>> 0, part2 = this.hi >>> 24;
      return part2 === 0 ? part1 === 0 ? part0 < 16384 ? part0 < 128 ? 1 : 2 : part0 < 2097152 ? 3 : 4 : part1 < 16384 ? part1 < 128 ? 5 : 6 : part1 < 2097152 ? 7 : 8 : part2 < 128 ? 9 : 10;
    };
  }
});

// node_modules/protobufjs/src/util/minimal.js
var require_minimal = __commonJS({
  "node_modules/protobufjs/src/util/minimal.js"(exports) {
    "use strict";
    var util = exports;
    util.asPromise = require_aspromise();
    util.base64 = require_base64();
    util.EventEmitter = require_eventemitter();
    util.float = require_float();
    util.inquire = require_inquire();
    util.utf8 = require_utf8();
    util.pool = require_pool();
    util.LongBits = require_longbits();
    util.isNode = !!(typeof global < "u" && global && global.process && global.process.versions && global.process.versions.node);
    util.global = util.isNode && global || typeof window < "u" && window || typeof self < "u" && self || exports;
    util.emptyArray = Object.freeze ? Object.freeze([]) : (
      /* istanbul ignore next */
      []
    );
    util.emptyObject = Object.freeze ? Object.freeze({}) : (
      /* istanbul ignore next */
      {}
    );
    util.isInteger = Number.isInteger || /* istanbul ignore next */
    function(value) {
      return typeof value == "number" && isFinite(value) && Math.floor(value) === value;
    };
    util.isString = function(value) {
      return typeof value == "string" || value instanceof String;
    };
    util.isObject = function(value) {
      return value && typeof value == "object";
    };
    util.isset = /**
     * Checks if a property on a message is considered to be present.
     * @param {Object} obj Plain object or message instance
     * @param {string} prop Property name
     * @returns {boolean} `true` if considered to be present, otherwise `false`
     */
    util.isSet = function(obj, prop) {
      var value = obj[prop];
      return value != null && obj.hasOwnProperty(prop) ? typeof value != "object" || (Array.isArray(value) ? value.length : Object.keys(value).length) > 0 : !1;
    };
    util.Buffer = (function() {
      try {
        var Buffer2 = util.inquire("buffer").Buffer;
        return Buffer2.prototype.utf8Write ? Buffer2 : (
          /* istanbul ignore next */
          null
        );
      } catch {
        return null;
      }
    })();
    util._Buffer_from = null;
    util._Buffer_allocUnsafe = null;
    util.newBuffer = function(sizeOrArray) {
      return typeof sizeOrArray == "number" ? util.Buffer ? util._Buffer_allocUnsafe(sizeOrArray) : new util.Array(sizeOrArray) : util.Buffer ? util._Buffer_from(sizeOrArray) : typeof Uint8Array > "u" ? sizeOrArray : new Uint8Array(sizeOrArray);
    };
    util.Array = typeof Uint8Array < "u" ? Uint8Array : Array;
    util.Long = /* istanbul ignore next */
    util.global.dcodeIO && /* istanbul ignore next */
    util.global.dcodeIO.Long || /* istanbul ignore next */
    util.global.Long || util.inquire("long");
    util.key2Re = /^true|false|0|1$/;
    util.key32Re = /^-?(?:0|[1-9][0-9]*)$/;
    util.key64Re = /^(?:[\\x00-\\xff]{8}|-?(?:0|[1-9][0-9]*))$/;
    util.longToHash = function(value) {
      return value ? util.LongBits.from(value).toHash() : util.LongBits.zeroHash;
    };
    util.longFromHash = function(hash, unsigned) {
      var bits = util.LongBits.fromHash(hash);
      return util.Long ? util.Long.fromBits(bits.lo, bits.hi, unsigned) : bits.toNumber(!!unsigned);
    };
    function merge(dst, src, ifNotSet) {
      for (var keys = Object.keys(src), i = 0; i < keys.length; ++i)
        (dst[keys[i]] === void 0 || !ifNotSet) && keys[i] !== "__proto__" && (dst[keys[i]] = src[keys[i]]);
      return dst;
    }
    util.merge = merge;
    util.recursionLimit = 100;
    util.makeProp = function(obj, key) {
      Object.defineProperty(obj, key, {
        enumerable: !0,
        configurable: !0,
        writable: !0
      });
    };
    util.lcFirst = function(str) {
      return str.charAt(0).toLowerCase() + str.substring(1);
    };
    function newError(name) {
      function CustomError(message, properties) {
        if (!(this instanceof CustomError))
          return new CustomError(message, properties);
        Object.defineProperty(this, "message", { get: function() {
          return message;
        } }), Error.captureStackTrace ? Error.captureStackTrace(this, CustomError) : Object.defineProperty(this, "stack", { value: new Error().stack || "" }), properties && merge(this, properties);
      }
      return CustomError.prototype = Object.create(Error.prototype, {
        constructor: {
          value: CustomError,
          writable: !0,
          enumerable: !1,
          configurable: !0
        },
        name: {
          get: function() {
            return name;
          },
          set: void 0,
          enumerable: !1,
          // configurable: false would accurately preserve the behavior of
          // the original, but I'm guessing that was not intentional.
          // For an actual error subclass, this property would
          // be configurable.
          configurable: !0
        },
        toString: {
          value: function() {
            return this.name + ": " + this.message;
          },
          writable: !0,
          enumerable: !1,
          configurable: !0
        }
      }), CustomError;
    }
    util.newError = newError;
    util.ProtocolError = newError("ProtocolError");
    util.oneOfGetter = function(fieldNames) {
      for (var fieldMap = {}, i = 0; i < fieldNames.length; ++i)
        fieldMap[fieldNames[i]] = 1;
      return function() {
        for (var keys = Object.keys(this), i2 = keys.length - 1; i2 > -1; --i2)
          if (fieldMap[keys[i2]] === 1 && this[keys[i2]] !== void 0 && this[keys[i2]] !== null)
            return keys[i2];
      };
    };
    util.oneOfSetter = function(fieldNames) {
      return function(name) {
        for (var i = 0; i < fieldNames.length; ++i)
          fieldNames[i] !== name && delete this[fieldNames[i]];
      };
    };
    util.toJSONOptions = {
      longs: String,
      enums: String,
      bytes: String,
      json: !0
    };
    util._configure = function() {
      var Buffer2 = util.Buffer;
      if (!Buffer2) {
        util._Buffer_from = util._Buffer_allocUnsafe = null;
        return;
      }
      util._Buffer_from = Buffer2.from !== Uint8Array.from && Buffer2.from || /* istanbul ignore next */
      function(value, encoding) {
        return new Buffer2(value, encoding);
      }, util._Buffer_allocUnsafe = Buffer2.allocUnsafe || /* istanbul ignore next */
      function(size) {
        return new Buffer2(size);
      };
    };
  }
});

// node_modules/protobufjs/src/writer.js
var require_writer = __commonJS({
  "node_modules/protobufjs/src/writer.js"(exports, module) {
    "use strict";
    module.exports = Writer;
    var util = require_minimal(), BufferWriter, LongBits = util.LongBits, base64 = util.base64, utf8 = util.utf8;
    function Op(fn, len, val) {
      this.fn = fn, this.len = len, this.next = void 0, this.val = val;
    }
    function noop() {
    }
    function State(writer) {
      this.head = writer.head, this.tail = writer.tail, this.len = writer.len, this.next = writer.states;
    }
    function Writer() {
      this.len = 0, this.head = new Op(noop, 0, 0), this.tail = this.head, this.states = null;
    }
    var create = function() {
      return util.Buffer ? function() {
        return (Writer.create = function() {
          return new BufferWriter();
        })();
      } : function() {
        return new Writer();
      };
    };
    Writer.create = create();
    Writer.alloc = function(size) {
      return new util.Array(size);
    };
    util.Array !== Array && (Writer.alloc = util.pool(Writer.alloc, util.Array.prototype.subarray));
    Writer.prototype._push = function(fn, len, val) {
      return this.tail = this.tail.next = new Op(fn, len, val), this.len += len, this;
    };
    function writeByte(val, buf, pos) {
      buf[pos] = val & 255;
    }
    function writeVarint32(val, buf, pos) {
      for (; val > 127; )
        buf[pos++] = val & 127 | 128, val >>>= 7;
      buf[pos] = val;
    }
    function VarintOp(len, val) {
      this.len = len, this.next = void 0, this.val = val;
    }
    VarintOp.prototype = Object.create(Op.prototype);
    VarintOp.prototype.fn = writeVarint32;
    Writer.prototype.uint32 = function(value) {
      return this.len += (this.tail = this.tail.next = new VarintOp(
        (value = value >>> 0) < 128 ? 1 : value < 16384 ? 2 : value < 2097152 ? 3 : value < 268435456 ? 4 : 5,
        value
      )).len, this;
    };
    Writer.prototype.int32 = function(value) {
      return value < 0 ? this._push(writeVarint64, 10, LongBits.fromNumber(value)) : this.uint32(value);
    };
    Writer.prototype.sint32 = function(value) {
      return this.uint32((value << 1 ^ value >> 31) >>> 0);
    };
    function writeVarint64(val, buf, pos) {
      for (; val.hi; )
        buf[pos++] = val.lo & 127 | 128, val.lo = (val.lo >>> 7 | val.hi << 25) >>> 0, val.hi >>>= 7;
      for (; val.lo > 127; )
        buf[pos++] = val.lo & 127 | 128, val.lo = val.lo >>> 7;
      buf[pos++] = val.lo;
    }
    Writer.prototype.uint64 = function(value) {
      var bits = LongBits.from(value);
      return this._push(writeVarint64, bits.length(), bits);
    };
    Writer.prototype.int64 = Writer.prototype.uint64;
    Writer.prototype.sint64 = function(value) {
      var bits = LongBits.from(value).zzEncode();
      return this._push(writeVarint64, bits.length(), bits);
    };
    Writer.prototype.bool = function(value) {
      return this._push(writeByte, 1, value ? 1 : 0);
    };
    function writeFixed32(val, buf, pos) {
      buf[pos] = val & 255, buf[pos + 1] = val >>> 8 & 255, buf[pos + 2] = val >>> 16 & 255, buf[pos + 3] = val >>> 24;
    }
    Writer.prototype.fixed32 = function(value) {
      return this._push(writeFixed32, 4, value >>> 0);
    };
    Writer.prototype.sfixed32 = Writer.prototype.fixed32;
    Writer.prototype.fixed64 = function(value) {
      var bits = LongBits.from(value);
      return this._push(writeFixed32, 4, bits.lo)._push(writeFixed32, 4, bits.hi);
    };
    Writer.prototype.sfixed64 = Writer.prototype.fixed64;
    Writer.prototype.float = function(value) {
      return this._push(util.float.writeFloatLE, 4, value);
    };
    Writer.prototype.double = function(value) {
      return this._push(util.float.writeDoubleLE, 8, value);
    };
    var writeBytes = util.Array.prototype.set ? function(val, buf, pos) {
      buf.set(val, pos);
    } : function(val, buf, pos) {
      for (var i = 0; i < val.length; ++i)
        buf[pos + i] = val[i];
    };
    Writer.prototype.bytes = function(value) {
      var len = value.length >>> 0;
      if (!len)
        return this._push(writeByte, 1, 0);
      if (util.isString(value)) {
        var buf = Writer.alloc(len = base64.length(value));
        base64.decode(value, buf, 0), value = buf;
      }
      return this.uint32(len)._push(writeBytes, len, value);
    };
    Writer.prototype.string = function(value) {
      var len = utf8.length(value);
      return len ? this.uint32(len)._push(utf8.write, len, value) : this._push(writeByte, 1, 0);
    };
    Writer.prototype.fork = function() {
      return this.states = new State(this), this.head = this.tail = new Op(noop, 0, 0), this.len = 0, this;
    };
    Writer.prototype.reset = function() {
      return this.states ? (this.head = this.states.head, this.tail = this.states.tail, this.len = this.states.len, this.states = this.states.next) : (this.head = this.tail = new Op(noop, 0, 0), this.len = 0), this;
    };
    Writer.prototype.ldelim = function() {
      var head = this.head, tail = this.tail, len = this.len;
      return this.reset().uint32(len), len && (this.tail.next = head.next, this.tail = tail, this.len += len), this;
    };
    Writer.prototype.finish = function() {
      for (var head = this.head.next, buf = this.constructor.alloc(this.len), pos = 0; head; )
        head.fn(head.val, buf, pos), pos += head.len, head = head.next;
      return buf;
    };
    Writer._configure = function(BufferWriter_) {
      BufferWriter = BufferWriter_, Writer.create = create(), BufferWriter._configure();
    };
  }
});

// node_modules/protobufjs/src/writer_buffer.js
var require_writer_buffer = __commonJS({
  "node_modules/protobufjs/src/writer_buffer.js"(exports, module) {
    "use strict";
    module.exports = BufferWriter;
    var Writer = require_writer();
    (BufferWriter.prototype = Object.create(Writer.prototype)).constructor = BufferWriter;
    var util = require_minimal();
    function BufferWriter() {
      Writer.call(this);
    }
    BufferWriter._configure = function() {
      BufferWriter.alloc = util._Buffer_allocUnsafe, BufferWriter.writeBytesBuffer = util.Buffer && util.Buffer.prototype instanceof Uint8Array && util.Buffer.prototype.set.name === "set" ? function(val, buf, pos) {
        buf.set(val, pos);
      } : function(val, buf, pos) {
        if (val.copy)
          val.copy(buf, pos, 0, val.length);
        else for (var i = 0; i < val.length; )
          buf[pos++] = val[i++];
      };
    };
    BufferWriter.prototype.bytes = function(value) {
      util.isString(value) && (value = util._Buffer_from(value, "base64"));
      var len = value.length >>> 0;
      return this.uint32(len), len && this._push(BufferWriter.writeBytesBuffer, len, value), this;
    };
    function writeStringBuffer(val, buf, pos) {
      val.length < 40 ? util.utf8.write(val, buf, pos) : buf.utf8Write ? buf.utf8Write(val, pos) : buf.write(val, pos);
    }
    BufferWriter.prototype.string = function(value) {
      var len = util.Buffer.byteLength(value);
      return this.uint32(len), len && this._push(writeStringBuffer, len, value), this;
    };
    BufferWriter._configure();
  }
});

// node_modules/protobufjs/src/reader.js
var require_reader = __commonJS({
  "node_modules/protobufjs/src/reader.js"(exports, module) {
    "use strict";
    module.exports = Reader;
    var util = require_minimal(), BufferReader, LongBits = util.LongBits, utf8 = util.utf8;
    function indexOutOfRange(reader, writeLength) {
      return RangeError("index out of range: " + reader.pos + " + " + (writeLength || 1) + " > " + reader.len);
    }
    function Reader(buffer) {
      this.buf = buffer, this.pos = 0, this.len = buffer.length;
    }
    var create_array = typeof Uint8Array < "u" ? function(buffer) {
      if (buffer instanceof Uint8Array || Array.isArray(buffer))
        return new Reader(buffer);
      throw Error("illegal buffer");
    } : function(buffer) {
      if (Array.isArray(buffer))
        return new Reader(buffer);
      throw Error("illegal buffer");
    }, create = function() {
      return util.Buffer ? function(buffer) {
        return (Reader.create = function(buffer2) {
          return util.Buffer.isBuffer(buffer2) ? new BufferReader(buffer2) : create_array(buffer2);
        })(buffer);
      } : create_array;
    };
    Reader.create = create();
    Reader.prototype._slice = util.Array.prototype.subarray || /* istanbul ignore next */
    util.Array.prototype.slice;
    Reader.prototype.uint32 = /* @__PURE__ */ (function() {
      var value = 4294967295;
      return function() {
        if (value = (this.buf[this.pos] & 127) >>> 0, this.buf[this.pos++] < 128 || (value = (value | (this.buf[this.pos] & 127) << 7) >>> 0, this.buf[this.pos++] < 128) || (value = (value | (this.buf[this.pos] & 127) << 14) >>> 0, this.buf[this.pos++] < 128) || (value = (value | (this.buf[this.pos] & 127) << 21) >>> 0, this.buf[this.pos++] < 128) || (value = (value | (this.buf[this.pos] & 15) << 28) >>> 0, this.buf[this.pos++] < 128)) return value;
        if ((this.pos += 5) > this.len)
          throw this.pos = this.len, indexOutOfRange(this, 10);
        return value;
      };
    })();
    Reader.prototype.int32 = function() {
      return this.uint32() | 0;
    };
    Reader.prototype.sint32 = function() {
      var value = this.uint32();
      return value >>> 1 ^ -(value & 1) | 0;
    };
    function readLongVarint() {
      var bits = new LongBits(0, 0), i = 0;
      if (this.len - this.pos > 4) {
        for (; i < 4; ++i)
          if (bits.lo = (bits.lo | (this.buf[this.pos] & 127) << i * 7) >>> 0, this.buf[this.pos++] < 128)
            return bits;
        if (bits.lo = (bits.lo | (this.buf[this.pos] & 127) << 28) >>> 0, bits.hi = (bits.hi | (this.buf[this.pos] & 127) >> 4) >>> 0, this.buf[this.pos++] < 128)
          return bits;
        i = 0;
      } else {
        for (; i < 3; ++i) {
          if (this.pos >= this.len)
            throw indexOutOfRange(this);
          if (bits.lo = (bits.lo | (this.buf[this.pos] & 127) << i * 7) >>> 0, this.buf[this.pos++] < 128)
            return bits;
        }
        return bits.lo = (bits.lo | (this.buf[this.pos++] & 127) << i * 7) >>> 0, bits;
      }
      if (this.len - this.pos > 4) {
        for (; i < 5; ++i)
          if (bits.hi = (bits.hi | (this.buf[this.pos] & 127) << i * 7 + 3) >>> 0, this.buf[this.pos++] < 128)
            return bits;
      } else
        for (; i < 5; ++i) {
          if (this.pos >= this.len)
            throw indexOutOfRange(this);
          if (bits.hi = (bits.hi | (this.buf[this.pos] & 127) << i * 7 + 3) >>> 0, this.buf[this.pos++] < 128)
            return bits;
        }
      throw Error("invalid varint encoding");
    }
    Reader.prototype.bool = function() {
      return this.uint32() !== 0;
    };
    function readFixed32_end(buf, end) {
      return (buf[end - 4] | buf[end - 3] << 8 | buf[end - 2] << 16 | buf[end - 1] << 24) >>> 0;
    }
    Reader.prototype.fixed32 = function() {
      if (this.pos + 4 > this.len)
        throw indexOutOfRange(this, 4);
      return readFixed32_end(this.buf, this.pos += 4);
    };
    Reader.prototype.sfixed32 = function() {
      if (this.pos + 4 > this.len)
        throw indexOutOfRange(this, 4);
      return readFixed32_end(this.buf, this.pos += 4) | 0;
    };
    function readFixed64() {
      if (this.pos + 8 > this.len)
        throw indexOutOfRange(this, 8);
      return new LongBits(readFixed32_end(this.buf, this.pos += 4), readFixed32_end(this.buf, this.pos += 4));
    }
    Reader.prototype.float = function() {
      if (this.pos + 4 > this.len)
        throw indexOutOfRange(this, 4);
      var value = util.float.readFloatLE(this.buf, this.pos);
      return this.pos += 4, value;
    };
    Reader.prototype.double = function() {
      if (this.pos + 8 > this.len)
        throw indexOutOfRange(this, 4);
      var value = util.float.readDoubleLE(this.buf, this.pos);
      return this.pos += 8, value;
    };
    Reader.prototype.bytes = function() {
      var length = this.uint32(), start = this.pos, end = this.pos + length;
      if (end > this.len)
        throw indexOutOfRange(this, length);
      if (this.pos += length, Array.isArray(this.buf))
        return this.buf.slice(start, end);
      if (start === end) {
        var nativeBuffer = util.Buffer;
        return nativeBuffer ? nativeBuffer.alloc(0) : new this.buf.constructor(0);
      }
      return this._slice.call(this.buf, start, end);
    };
    Reader.prototype.string = function() {
      var bytes = this.bytes();
      return utf8.read(bytes, 0, bytes.length);
    };
    Reader.prototype.skip = function(length) {
      if (typeof length == "number") {
        if (this.pos + length > this.len)
          throw indexOutOfRange(this, length);
        this.pos += length;
      } else
        do
          if (this.pos >= this.len)
            throw indexOutOfRange(this);
        while (this.buf[this.pos++] & 128);
      return this;
    };
    Reader.recursionLimit = util.recursionLimit;
    Reader.prototype.skipType = function(wireType, depth) {
      if (depth === void 0 && (depth = 0), depth > Reader.recursionLimit)
        throw Error("maximum nesting depth exceeded");
      switch (wireType) {
        case 0:
          this.skip();
          break;
        case 1:
          this.skip(8);
          break;
        case 2:
          this.skip(this.uint32());
          break;
        case 3:
          for (; (wireType = this.uint32() & 7) !== 4; )
            this.skipType(wireType, depth + 1);
          break;
        case 5:
          this.skip(4);
          break;
        /* istanbul ignore next */
        default:
          throw Error("invalid wire type " + wireType + " at offset " + this.pos);
      }
      return this;
    };
    Reader._configure = function(BufferReader_) {
      BufferReader = BufferReader_, Reader.create = create(), BufferReader._configure();
      var fn = util.Long ? "toLong" : (
        /* istanbul ignore next */
        "toNumber"
      );
      util.merge(Reader.prototype, {
        int64: function() {
          return readLongVarint.call(this)[fn](!1);
        },
        uint64: function() {
          return readLongVarint.call(this)[fn](!0);
        },
        sint64: function() {
          return readLongVarint.call(this).zzDecode()[fn](!1);
        },
        fixed64: function() {
          return readFixed64.call(this)[fn](!0);
        },
        sfixed64: function() {
          return readFixed64.call(this)[fn](!1);
        }
      });
    };
  }
});

// node_modules/protobufjs/src/reader_buffer.js
var require_reader_buffer = __commonJS({
  "node_modules/protobufjs/src/reader_buffer.js"(exports, module) {
    "use strict";
    module.exports = BufferReader;
    var Reader = require_reader();
    (BufferReader.prototype = Object.create(Reader.prototype)).constructor = BufferReader;
    var util = require_minimal();
    function BufferReader(buffer) {
      Reader.call(this, buffer);
    }
    BufferReader._configure = function() {
      util.Buffer && (BufferReader.prototype._slice = util.Buffer.prototype.slice);
    };
    BufferReader.prototype.string = function() {
      var len = this.uint32();
      return this.buf.utf8Slice ? this.buf.utf8Slice(this.pos, this.pos = Math.min(this.pos + len, this.len)) : this.buf.toString("utf-8", this.pos, this.pos = Math.min(this.pos + len, this.len));
    };
    BufferReader._configure();
  }
});

// node_modules/protobufjs/src/rpc/service.js
var require_service = __commonJS({
  "node_modules/protobufjs/src/rpc/service.js"(exports, module) {
    "use strict";
    module.exports = Service;
    var util = require_minimal();
    (Service.prototype = Object.create(util.EventEmitter.prototype)).constructor = Service;
    function Service(rpcImpl, requestDelimited, responseDelimited) {
      if (typeof rpcImpl != "function")
        throw TypeError("rpcImpl must be a function");
      util.EventEmitter.call(this), this.rpcImpl = rpcImpl, this.requestDelimited = !!requestDelimited, this.responseDelimited = !!responseDelimited;
    }
    Service.prototype.rpcCall = function rpcCall(method, requestCtor, responseCtor, request, callback) {
      if (!request)
        throw TypeError("request must be specified");
      var self2 = this;
      if (!callback)
        return util.asPromise(rpcCall, self2, method, requestCtor, responseCtor, request);
      if (!self2.rpcImpl) {
        setTimeout(function() {
          callback(Error("already ended"));
        }, 0);
        return;
      }
      try {
        return self2.rpcImpl(
          method,
          requestCtor[self2.requestDelimited ? "encodeDelimited" : "encode"](request).finish(),
          function(err, response) {
            if (err)
              return self2.emit("error", err, method), callback(err);
            if (response === null) {
              self2.end(
                /* endedByRPC */
                !0
              );
              return;
            }
            if (!(response instanceof responseCtor))
              try {
                response = responseCtor[self2.responseDelimited ? "decodeDelimited" : "decode"](response);
              } catch (err2) {
                return self2.emit("error", err2, method), callback(err2);
              }
            return self2.emit("data", response, method), callback(null, response);
          }
        );
      } catch (err) {
        self2.emit("error", err, method), setTimeout(function() {
          callback(err);
        }, 0);
        return;
      }
    };
    Service.prototype.end = function(endedByRPC) {
      return this.rpcImpl && (endedByRPC || this.rpcImpl(null, null, null), this.rpcImpl = null, this.emit("end").off()), this;
    };
  }
});

// node_modules/protobufjs/src/rpc.js
var require_rpc = __commonJS({
  "node_modules/protobufjs/src/rpc.js"(exports) {
    "use strict";
    var rpc = exports;
    rpc.Service = require_service();
  }
});

// node_modules/protobufjs/src/roots.js
var require_roots = __commonJS({
  "node_modules/protobufjs/src/roots.js"(exports, module) {
    "use strict";
    module.exports = {};
  }
});

// node_modules/protobufjs/src/index-minimal.js
var require_index_minimal = __commonJS({
  "node_modules/protobufjs/src/index-minimal.js"(exports) {
    "use strict";
    var protobuf = exports;
    protobuf.build = "minimal";
    protobuf.Writer = require_writer();
    protobuf.BufferWriter = require_writer_buffer();
    protobuf.Reader = require_reader();
    protobuf.BufferReader = require_reader_buffer();
    protobuf.util = require_minimal();
    protobuf.rpc = require_rpc();
    protobuf.roots = require_roots();
    protobuf.configure = configure;
    function configure() {
      protobuf.util._configure(), protobuf.Writer._configure(protobuf.BufferWriter), protobuf.Reader._configure(protobuf.BufferReader);
    }
    configure();
  }
});

// node_modules/@protobufjs/codegen/index.js
var require_codegen = __commonJS({
  "node_modules/@protobufjs/codegen/index.js"(exports, module) {
    "use strict";
    module.exports = codegen;
    var reservedRe = /^(?:do|if|in|for|let|new|try|var|case|else|enum|eval|false|null|this|true|void|with|break|catch|class|const|super|throw|while|yield|delete|export|import|public|return|static|switch|typeof|default|extends|finally|package|private|continue|debugger|function|arguments|interface|protected|implements|instanceof)$/;
    function codegen(functionParams, functionName) {
      typeof functionParams == "string" && (functionName = functionParams, functionParams = void 0);
      var body = [];
      function Codegen(formatStringOrScope) {
        if (typeof formatStringOrScope != "string") {
          var source = toString();
          if (codegen.verbose && console.log("codegen: " + source), source = "return " + source, formatStringOrScope) {
            for (var scopeKeys = Object.keys(formatStringOrScope), scopeParams = new Array(scopeKeys.length + 1), scopeValues = new Array(scopeKeys.length), scopeOffset = 0; scopeOffset < scopeKeys.length; )
              scopeParams[scopeOffset] = scopeKeys[scopeOffset], scopeValues[scopeOffset] = formatStringOrScope[scopeKeys[scopeOffset++]];
            return scopeParams[scopeOffset] = source, Function.apply(null, scopeParams).apply(null, scopeValues);
          }
          return Function(source)();
        }
        for (var formatParams = new Array(arguments.length - 1), formatOffset = 0; formatOffset < formatParams.length; )
          formatParams[formatOffset] = arguments[++formatOffset];
        if (formatOffset = 0, formatStringOrScope = formatStringOrScope.replace(/%([%dfijs])/g, function($0, $1) {
          var value = formatParams[formatOffset++];
          switch ($1) {
            case "d":
            case "f":
              return String(Number(value));
            case "i":
              return String(Math.floor(value));
            case "j":
              return JSON.stringify(value);
            case "s":
              return String(value);
          }
          return "%";
        }), formatOffset !== formatParams.length)
          throw Error("parameter count mismatch");
        return body.push(formatStringOrScope), Codegen;
      }
      function toString(functionNameOverride) {
        return "function " + safeFunctionName(functionNameOverride || functionName) + "(" + (functionParams && functionParams.join(",") || "") + `){
  ` + body.join(`
  `) + `
}`;
      }
      return Codegen.toString = toString, Codegen;
    }
    codegen.verbose = !1;
    function safeFunctionName(name) {
      return !name || (name = String(name).replace(/[^\w$]/g, ""), !name) ? "" : (/^\d/.test(name) && (name = "_" + name), reservedRe.test(name) ? name + "_" : name);
    }
  }
});

// node_modules/@protobufjs/fetch/index.js
var require_fetch = __commonJS({
  "node_modules/@protobufjs/fetch/index.js"(exports, module) {
    "use strict";
    module.exports = fetch;
    var asPromise = require_aspromise(), inquire = require_inquire(), fs = inquire("fs");
    function fetch(filename, options, callback) {
      return typeof options == "function" ? (callback = options, options = {}) : options || (options = {}), callback ? !options.xhr && fs && fs.readFile ? fs.readFile(filename, function(err, contents) {
        return err && typeof XMLHttpRequest < "u" ? fetch.xhr(filename, options, callback) : err ? callback(err) : callback(null, options.binary ? contents : contents.toString("utf8"));
      }) : fetch.xhr(filename, options, callback) : asPromise(fetch, this, filename, options);
    }
    fetch.xhr = function(filename, options, callback) {
      var xhr = new XMLHttpRequest();
      xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
          if (xhr.status !== 0 && xhr.status !== 200)
            return callback(Error("status " + xhr.status));
          if (options.binary) {
            var buffer = xhr.response;
            if (!buffer) {
              buffer = [];
              for (var i = 0; i < xhr.responseText.length; ++i)
                buffer.push(xhr.responseText.charCodeAt(i) & 255);
            }
            return callback(null, typeof Uint8Array < "u" ? new Uint8Array(buffer) : buffer);
          }
          return callback(null, xhr.responseText);
        }
      }, options.binary && ("overrideMimeType" in xhr && xhr.overrideMimeType("text/plain; charset=x-user-defined"), xhr.responseType = "arraybuffer"), xhr.open("GET", filename), xhr.send();
    };
  }
});

// node_modules/@protobufjs/path/index.js
var require_path = __commonJS({
  "node_modules/@protobufjs/path/index.js"(exports) {
    "use strict";
    var path = exports, isAbsolute = (
      /**
       * Tests if the specified path is absolute.
       * @param {string} path Path to test
       * @returns {boolean} `true` if path is absolute
       */
      path.isAbsolute = function(path2) {
        return /^(?:\/|\w+:)/.test(path2);
      }
    ), normalize = (
      /**
       * Normalizes the specified path.
       * @param {string} path Path to normalize
       * @returns {string} Normalized path
       */
      path.normalize = function(path2) {
        path2 = path2.replace(/\\/g, "/").replace(/\/{2,}/g, "/");
        var parts = path2.split("/"), absolute = isAbsolute(path2), prefix = "";
        absolute && (prefix = parts.shift() + "/");
        for (var i = 0; i < parts.length; )
          parts[i] === ".." ? i > 0 && parts[i - 1] !== ".." ? parts.splice(--i, 2) : absolute ? parts.splice(i, 1) : ++i : parts[i] === "." ? parts.splice(i, 1) : ++i;
        return prefix + parts.join("/");
      }
    );
    path.resolve = function(originPath, includePath, alreadyNormalized) {
      return alreadyNormalized || (includePath = normalize(includePath)), isAbsolute(includePath) ? includePath : (alreadyNormalized || (originPath = normalize(originPath)), (originPath = originPath.replace(/(?:\/|^)[^/]+$/, "")).length ? normalize(originPath + "/" + includePath) : includePath);
    };
  }
});

// node_modules/protobufjs/src/util/patterns.js
var require_patterns = __commonJS({
  "node_modules/protobufjs/src/util/patterns.js"(exports) {
    "use strict";
    var patterns = exports;
    patterns.numberRe = /^(?![eE])[0-9]*(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?$/;
    patterns.typeRefRe = /^(?:\.?[a-zA-Z_][a-zA-Z_0-9]*)(?:\.[a-zA-Z_][a-zA-Z_0-9]*)*$/;
    patterns.reservedRe = /^(?:do|if|in|for|let|new|try|var|case|else|enum|eval|false|null|this|true|void|with|break|catch|class|const|super|throw|while|yield|delete|export|import|public|return|static|switch|typeof|default|extends|finally|package|private|continue|debugger|function|arguments|interface|protected|implements|instanceof)$/;
    patterns.unsafePropertyRe = /^(?:__proto__|prototype|constructor)$/;
  }
});

// node_modules/protobufjs/src/namespace.js
var require_namespace = __commonJS({
  "node_modules/protobufjs/src/namespace.js"(exports, module) {
    "use strict";
    module.exports = Namespace;
    var ReflectionObject = require_object();
    ((Namespace.prototype = Object.create(ReflectionObject.prototype)).constructor = Namespace).className = "Namespace";
    var Field = require_field(), util = require_util(), OneOf = require_oneof(), Type, Service, Enum;
    Namespace.fromJSON = function(name, json, depth) {
      return depth = util.checkDepth(depth), new Namespace(name, json.options).addJSON(json.nested, depth);
    };
    function arrayToJSON(array, toJSONOptions) {
      if (array && array.length) {
        for (var obj = {}, i = 0; i < array.length; ++i)
          obj[array[i].name] = array[i].toJSON(toJSONOptions);
        return obj;
      }
    }
    Namespace.arrayToJSON = arrayToJSON;
    Namespace.isReservedId = function(reserved, id) {
      if (reserved) {
        for (var i = 0; i < reserved.length; ++i)
          if (typeof reserved[i] != "string" && reserved[i][0] <= id && reserved[i][1] > id)
            return !0;
      }
      return !1;
    };
    Namespace.isReservedName = function(reserved, name) {
      if (reserved) {
        for (var i = 0; i < reserved.length; ++i)
          if (reserved[i] === name)
            return !0;
      }
      return !1;
    };
    function Namespace(name, options) {
      ReflectionObject.call(this, name, options), this.nested = void 0, this._nestedArray = null, this._lookupCache = /* @__PURE__ */ Object.create(null), this._needsRecursiveFeatureResolution = !0, this._needsRecursiveResolve = !0;
    }
    function clearCache(namespace) {
      namespace._nestedArray = null, namespace._lookupCache = /* @__PURE__ */ Object.create(null);
      for (var parent = namespace; parent = parent.parent; )
        parent._lookupCache = /* @__PURE__ */ Object.create(null);
      return namespace;
    }
    Object.defineProperty(Namespace.prototype, "nestedArray", {
      get: function() {
        return this._nestedArray || (this._nestedArray = util.toArray(this.nested));
      }
    });
    Namespace.prototype.toJSON = function(toJSONOptions) {
      return util.toObject([
        "options",
        this.options,
        "nested",
        arrayToJSON(this.nestedArray, toJSONOptions)
      ]);
    };
    Namespace.prototype.addJSON = function(nestedJson, depth) {
      depth = util.checkDepth(depth);
      var ns = this;
      if (nestedJson)
        for (var names = Object.keys(nestedJson), i = 0, nested; i < names.length; ++i)
          nested = nestedJson[names[i]], ns.add(
            // most to least likely
            (nested.fields !== void 0 ? Type.fromJSON : nested.values !== void 0 ? Enum.fromJSON : nested.methods !== void 0 ? Service.fromJSON : nested.id !== void 0 ? Field.fromJSON : Namespace.fromJSON)(names[i], nested, depth + 1)
          );
      return this;
    };
    Namespace.prototype.get = function(name) {
      return this.nested && Object.prototype.hasOwnProperty.call(this.nested, name) ? this.nested[name] : null;
    };
    Namespace.prototype.getEnum = function(name) {
      if (this.nested && Object.prototype.hasOwnProperty.call(this.nested, name) && this.nested[name] instanceof Enum)
        return this.nested[name].values;
      throw Error("no such enum: " + name);
    };
    Namespace.prototype.add = function(object) {
      if (!(object instanceof Field && object.extend !== void 0 || object instanceof Type || object instanceof OneOf || object instanceof Enum || object instanceof Service || object instanceof Namespace))
        throw TypeError("object must be a valid nested object");
      if (object.name === "__proto__")
        return this;
      if (!this.nested)
        this.nested = {};
      else {
        var prev = this.get(object.name);
        if (prev)
          if (prev instanceof Namespace && object instanceof Namespace && !(prev instanceof Type || prev instanceof Service)) {
            for (var nested = prev.nestedArray, i = 0; i < nested.length; ++i)
              object.add(nested[i]);
            this.remove(prev), this.nested || (this.nested = {}), object.setOptions(prev.options, !0);
          } else
            throw Error("duplicate name '" + object.name + "' in " + this);
      }
      this.nested[object.name] = object, this instanceof Type || this instanceof Service || this instanceof Enum || this instanceof Field || object._edition || (object._edition = object._defaultEdition), this._needsRecursiveFeatureResolution = !0, this._needsRecursiveResolve = !0;
      for (var parent = this; parent = parent.parent; )
        parent._needsRecursiveFeatureResolution = !0, parent._needsRecursiveResolve = !0;
      return object.onAdd(this), clearCache(this);
    };
    Namespace.prototype.remove = function(object) {
      if (!(object instanceof ReflectionObject))
        throw TypeError("object must be a ReflectionObject");
      if (object.parent !== this)
        throw Error(object + " is not a member of " + this);
      return delete this.nested[object.name], Object.keys(this.nested).length || (this.nested = void 0), object.onRemove(this), clearCache(this);
    };
    Namespace.prototype.define = function(path, json) {
      if (util.isString(path))
        path = path.split(".");
      else if (!Array.isArray(path))
        throw TypeError("illegal path");
      if (path && path.length && path[0] === "")
        throw Error("path must be relative");
      for (var ptr = this; path.length > 0; ) {
        var part = path.shift();
        if (ptr.nested && ptr.nested[part]) {
          if (ptr = ptr.nested[part], !(ptr instanceof Namespace))
            throw Error("path conflicts with non-namespace objects");
        } else
          ptr.add(ptr = new Namespace(part));
      }
      return json && ptr.addJSON(json), ptr;
    };
    Namespace.prototype.resolveAll = function() {
      if (!this._needsRecursiveResolve) return this;
      this._resolveFeaturesRecursive(this._edition);
      var nested = this.nestedArray, i = 0;
      for (this.resolve(); i < nested.length; )
        nested[i] instanceof Namespace ? nested[i++].resolveAll() : nested[i++].resolve();
      return this._needsRecursiveResolve = !1, this;
    };
    Namespace.prototype._resolveFeaturesRecursive = function(edition) {
      return this._needsRecursiveFeatureResolution ? (this._needsRecursiveFeatureResolution = !1, edition = this._edition || edition, ReflectionObject.prototype._resolveFeaturesRecursive.call(this, edition), this.nestedArray.forEach((nested) => {
        nested._resolveFeaturesRecursive(edition);
      }), this) : this;
    };
    Namespace.prototype.lookup = function(path, filterTypes, parentAlreadyChecked) {
      if (typeof filterTypes == "boolean" ? (parentAlreadyChecked = filterTypes, filterTypes = void 0) : filterTypes && !Array.isArray(filterTypes) && (filterTypes = [filterTypes]), util.isString(path) && path.length) {
        if (path === ".")
          return this.root;
        path = path.split(".");
      } else if (!path.length)
        return this;
      var flatPath = path.join(".");
      if (path[0] === "")
        return this.root.lookup(path.slice(1), filterTypes);
      var found = this.root._fullyQualifiedObjects && this.root._fullyQualifiedObjects["." + flatPath];
      if (found && (!filterTypes || filterTypes.indexOf(found.constructor) > -1) || (found = this._lookupImpl(path, flatPath), found && (!filterTypes || filterTypes.indexOf(found.constructor) > -1)))
        return found;
      if (parentAlreadyChecked)
        return null;
      for (var current = this; current.parent; ) {
        if (found = current.parent._lookupImpl(path, flatPath), found && (!filterTypes || filterTypes.indexOf(found.constructor) > -1))
          return found;
        current = current.parent;
      }
      return null;
    };
    Namespace.prototype._lookupImpl = function(path, flatPath) {
      if (Object.prototype.hasOwnProperty.call(this._lookupCache, flatPath))
        return this._lookupCache[flatPath];
      var found = this.get(path[0]), exact = null;
      if (found)
        path.length === 1 ? exact = found : found instanceof Namespace && (path = path.slice(1), exact = found._lookupImpl(path, path.join(".")));
      else
        for (var i = 0; i < this.nestedArray.length; ++i)
          if (this._nestedArray[i] instanceof Namespace && (found = this._nestedArray[i]._lookupImpl(path, flatPath))) {
            exact = found;
            break;
          }
      return this._lookupCache[flatPath] = exact, exact;
    };
    Namespace.prototype.lookupType = function(path) {
      var found = this.lookup(path, [Type]);
      if (!found)
        throw Error("no such type: " + path);
      return found;
    };
    Namespace.prototype.lookupEnum = function(path) {
      var found = this.lookup(path, [Enum]);
      if (!found)
        throw Error("no such Enum '" + path + "' in " + this);
      return found;
    };
    Namespace.prototype.lookupTypeOrEnum = function(path) {
      var found = this.lookup(path, [Type, Enum]);
      if (!found)
        throw Error("no such Type or Enum '" + path + "' in " + this);
      return found;
    };
    Namespace.prototype.lookupService = function(path) {
      var found = this.lookup(path, [Service]);
      if (!found)
        throw Error("no such Service '" + path + "' in " + this);
      return found;
    };
    Namespace._configure = function(Type_, Service_, Enum_) {
      Type = Type_, Service = Service_, Enum = Enum_;
    };
  }
});

// node_modules/protobufjs/src/mapfield.js
var require_mapfield = __commonJS({
  "node_modules/protobufjs/src/mapfield.js"(exports, module) {
    "use strict";
    module.exports = MapField;
    var Field = require_field();
    ((MapField.prototype = Object.create(Field.prototype)).constructor = MapField).className = "MapField";
    var types = require_types(), util = require_util();
    function MapField(name, id, keyType, type, options, comment) {
      if (Field.call(this, name, id, type, void 0, void 0, options, comment), !util.isString(keyType))
        throw TypeError("keyType must be a string");
      this.keyType = keyType, this.resolvedKeyType = null, this.map = !0;
    }
    MapField.fromJSON = function(name, json) {
      return new MapField(name, json.id, json.keyType, json.type, json.options, json.comment);
    };
    MapField.prototype.toJSON = function(toJSONOptions) {
      var keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "keyType",
        this.keyType,
        "type",
        this.type,
        "id",
        this.id,
        "extend",
        this.extend,
        "options",
        this.options,
        "comment",
        keepComments ? this.comment : void 0
      ]);
    };
    MapField.prototype.resolve = function() {
      if (this.resolved)
        return this;
      if (types.mapKey[this.keyType] === void 0)
        throw Error("invalid key type: " + this.keyType);
      return Field.prototype.resolve.call(this);
    };
    MapField.d = function(fieldId, fieldKeyType, fieldValueType) {
      return typeof fieldValueType == "function" ? fieldValueType = util.decorateType(fieldValueType).name : fieldValueType && typeof fieldValueType == "object" && (fieldValueType = util.decorateEnum(fieldValueType).name), function(prototype, fieldName) {
        util.decorateType(prototype.constructor).add(new MapField(fieldName, fieldId, fieldKeyType, fieldValueType));
      };
    };
  }
});

// node_modules/protobufjs/src/method.js
var require_method = __commonJS({
  "node_modules/protobufjs/src/method.js"(exports, module) {
    "use strict";
    module.exports = Method;
    var ReflectionObject = require_object();
    ((Method.prototype = Object.create(ReflectionObject.prototype)).constructor = Method).className = "Method";
    var util = require_util();
    function Method(name, type, requestType, responseType, requestStream, responseStream, options, comment, parsedOptions) {
      if (util.isObject(requestStream) ? (options = requestStream, requestStream = responseStream = void 0) : util.isObject(responseStream) && (options = responseStream, responseStream = void 0), !(type === void 0 || util.isString(type)))
        throw TypeError("type must be a string");
      if (!util.isString(requestType))
        throw TypeError("requestType must be a string");
      if (!util.isString(responseType))
        throw TypeError("responseType must be a string");
      ReflectionObject.call(this, name, options), this.type = type || "rpc", this.requestType = requestType, this.requestStream = requestStream ? !0 : void 0, this.responseType = responseType, this.responseStream = responseStream ? !0 : void 0, this.resolvedRequestType = null, this.resolvedResponseType = null, this.comment = comment, this.parsedOptions = parsedOptions;
    }
    Method.fromJSON = function(name, json) {
      return new Method(name, json.type, json.requestType, json.responseType, json.requestStream, json.responseStream, json.options, json.comment, json.parsedOptions);
    };
    Method.prototype.toJSON = function(toJSONOptions) {
      var keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "type",
        this.type !== "rpc" && /* istanbul ignore next */
        this.type || void 0,
        "requestType",
        this.requestType,
        "requestStream",
        this.requestStream,
        "responseType",
        this.responseType,
        "responseStream",
        this.responseStream,
        "options",
        this.options,
        "comment",
        keepComments ? this.comment : void 0,
        "parsedOptions",
        this.parsedOptions
      ]);
    };
    Method.prototype.resolve = function() {
      return this.resolved ? this : (this.resolvedRequestType = this.parent.lookupType(this.requestType), this.resolvedResponseType = this.parent.lookupType(this.responseType), ReflectionObject.prototype.resolve.call(this));
    };
  }
});

// node_modules/protobufjs/src/service.js
var require_service2 = __commonJS({
  "node_modules/protobufjs/src/service.js"(exports, module) {
    "use strict";
    module.exports = Service;
    var Namespace = require_namespace();
    ((Service.prototype = Object.create(Namespace.prototype)).constructor = Service).className = "Service";
    var Method = require_method(), util = require_util(), rpc = require_rpc(), reservedRe = util.patterns.reservedRe;
    function Service(name, options) {
      Namespace.call(this, name, options), this.methods = {}, this._methodsArray = null;
    }
    Service.fromJSON = function(name, json, depth) {
      depth = util.checkDepth(depth);
      var service = new Service(name, json.options);
      if (json.methods)
        for (var names = Object.keys(json.methods), i = 0; i < names.length; ++i)
          service.add(Method.fromJSON(names[i], json.methods[names[i]]));
      return json.nested && service.addJSON(json.nested, depth), json.edition && (service._edition = json.edition), service.comment = json.comment, service._defaultEdition = "proto3", service;
    };
    Service.prototype.toJSON = function(toJSONOptions) {
      var inherited = Namespace.prototype.toJSON.call(this, toJSONOptions), keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "edition",
        this._editionToJSON(),
        "options",
        inherited && inherited.options || void 0,
        "methods",
        Namespace.arrayToJSON(this.methodsArray, toJSONOptions) || /* istanbul ignore next */
        {},
        "nested",
        inherited && inherited.nested || void 0,
        "comment",
        keepComments ? this.comment : void 0
      ]);
    };
    Object.defineProperty(Service.prototype, "methodsArray", {
      get: function() {
        return this._methodsArray || (this._methodsArray = util.toArray(this.methods));
      }
    });
    function clearCache(service) {
      return service._methodsArray = null, service;
    }
    Service.prototype.get = function(name) {
      return Object.prototype.hasOwnProperty.call(this.methods, name) ? this.methods[name] : Namespace.prototype.get.call(this, name);
    };
    Service.prototype.resolveAll = function() {
      if (!this._needsRecursiveResolve) return this;
      Namespace.prototype.resolve.call(this);
      for (var methods = this.methodsArray, i = 0; i < methods.length; ++i)
        methods[i].resolve();
      return this;
    };
    Service.prototype._resolveFeaturesRecursive = function(edition) {
      return this._needsRecursiveFeatureResolution ? (edition = this._edition || edition, Namespace.prototype._resolveFeaturesRecursive.call(this, edition), this.methodsArray.forEach((method) => {
        method._resolveFeaturesRecursive(edition);
      }), this) : this;
    };
    Service.prototype.add = function(object) {
      if (this.get(object.name))
        throw Error("duplicate name '" + object.name + "' in " + this);
      return object instanceof Method ? object.name === "__proto__" ? this : (this.methods[object.name] = object, object.parent = this, clearCache(this)) : Namespace.prototype.add.call(this, object);
    };
    Service.prototype.remove = function(object) {
      if (object instanceof Method) {
        if (this.methods[object.name] !== object)
          throw Error(object + " is not a member of " + this);
        return delete this.methods[object.name], object.parent = null, clearCache(this);
      }
      return Namespace.prototype.remove.call(this, object);
    };
    Service.prototype.create = function(rpcImpl, requestDelimited, responseDelimited) {
      for (var rpcService = new rpc.Service(rpcImpl, requestDelimited, responseDelimited), i = 0, method; i < /* initializes */
      this.methodsArray.length; ++i) {
        var methodName = util.lcFirst((method = this._methodsArray[i]).resolve().name).replace(/[^$\w_]/g, "");
        rpcService[methodName] = util.codegen(["r", "c"], reservedRe.test(methodName) ? methodName + "_" : methodName)("return this.rpcCall(m,q,s,r,c)")({
          m: method,
          q: method.resolvedRequestType.ctor,
          s: method.resolvedResponseType.ctor
        });
      }
      return rpcService;
    };
  }
});

// node_modules/protobufjs/src/message.js
var require_message = __commonJS({
  "node_modules/protobufjs/src/message.js"(exports, module) {
    "use strict";
    module.exports = Message;
    var util = require_minimal();
    function Message(properties) {
      if (properties)
        for (var keys = Object.keys(properties), i = 0; i < keys.length; ++i) {
          var key = keys[i];
          key !== "__proto__" && (this[key] = properties[key]);
        }
    }
    Message.create = function(properties) {
      return this.$type.create(properties);
    };
    Message.encode = function(message, writer) {
      return this.$type.encode(message, writer);
    };
    Message.encodeDelimited = function(message, writer) {
      return this.$type.encodeDelimited(message, writer);
    };
    Message.decode = function(reader) {
      return this.$type.decode(reader);
    };
    Message.decodeDelimited = function(reader) {
      return this.$type.decodeDelimited(reader);
    };
    Message.verify = function(message) {
      return this.$type.verify(message);
    };
    Message.fromObject = function(object) {
      return this.$type.fromObject(object);
    };
    Message.toObject = function(message, options) {
      return this.$type.toObject(message, options);
    };
    Message.prototype.toJSON = function() {
      return this.$type.toObject(this, util.toJSONOptions);
    };
  }
});

// node_modules/protobufjs/src/decoder.js
var require_decoder = __commonJS({
  "node_modules/protobufjs/src/decoder.js"(exports, module) {
    "use strict";
    module.exports = decoder;
    var Enum = require_enum(), types = require_types(), util = require_util();
    function missing(field) {
      return "missing required '" + field.name + "'";
    }
    function decoder(mtype) {
      for (var gen = util.codegen(["r", "l", "e", "n"], mtype.name + "$decode")("if(!(r instanceof Reader))")("r=Reader.create(r)")("if(n===undefined)n=0")("if(n>Reader.recursionLimit)")('throw Error("maximum nesting depth exceeded")')("var c=l===undefined?r.len:r.pos+l,m=new this.ctor" + (mtype.fieldsArray.filter(function(field2) {
        return field2.map;
      }).length ? ",k,value" : ""))("while(r.pos<c){")("var t=r.uint32()")("if(t===e)")("break")("switch(t>>>3){"), i = 0; i < /* initializes */
      mtype.fieldsArray.length; ++i) {
        var field = mtype._fieldsArray[i].resolve(), type = field.resolvedType instanceof Enum ? "int32" : field.type, ref = "m" + util.safeProp(field.name);
        gen("case %i: {", field.id), field.map ? (gen("if(%s===util.emptyObject)", ref)("%s={}", ref)("var c2 = r.uint32()+r.pos"), types.defaults[field.keyType] !== void 0 ? gen("k=%j", types.defaults[field.keyType]) : gen("k=null"), types.defaults[type] !== void 0 ? gen("value=%j", types.defaults[type]) : gen("value=null"), gen("while(r.pos<c2){")("var tag2=r.uint32()")("switch(tag2>>>3){")("case 1: k=r.%s(); break", field.keyType)("case 2:"), types.basic[type] === void 0 ? gen("value=types[%i].decode(r,r.uint32(),undefined,n+1)", i) : gen("value=r.%s()", type), gen("break")("default:")("r.skipType(tag2&7,n)")("break")("}")("}"), types.long[field.keyType] !== void 0 ? gen('%s[typeof k==="object"?util.longToHash(k):k]=value', ref) : (field.keyType === "string" && gen('if(k==="__proto__")')("util.makeProp(%s,k)", ref), gen("%s[k]=value", ref))) : field.repeated ? (gen("if(!(%s&&%s.length))", ref, ref)("%s=[]", ref), types.packed[type] !== void 0 && gen("if((t&7)===2){")("var c2=r.uint32()+r.pos")("while(r.pos<c2)")("%s.push(r.%s())", ref, type)("}else"), types.basic[type] === void 0 ? gen(field.delimited ? "%s.push(types[%i].decode(r,undefined,((t&~7)|4),n+1))" : "%s.push(types[%i].decode(r,r.uint32(),undefined,n+1))", ref, i) : gen("%s.push(r.%s())", ref, type)) : types.basic[type] === void 0 ? gen(field.delimited ? "%s=types[%i].decode(r,undefined,((t&~7)|4),n+1)" : "%s=types[%i].decode(r,r.uint32(),undefined,n+1)", ref, i) : gen("%s=r.%s()", ref, type), gen("break")("}");
      }
      for (gen("default:")("r.skipType(t&7,n)")("break")("}")("}"), i = 0; i < mtype._fieldsArray.length; ++i) {
        var rfield = mtype._fieldsArray[i];
        rfield.required && gen("if(!m.hasOwnProperty(%j))", rfield.name)("throw util.ProtocolError(%j,{instance:m})", missing(rfield));
      }
      return gen("return m");
    }
  }
});

// node_modules/protobufjs/src/verifier.js
var require_verifier = __commonJS({
  "node_modules/protobufjs/src/verifier.js"(exports, module) {
    "use strict";
    module.exports = verifier;
    var Enum = require_enum(), util = require_util();
    function invalid(field, expected) {
      return field.name + ": " + expected + (field.repeated && expected !== "array" ? "[]" : field.map && expected !== "object" ? "{k:" + field.keyType + "}" : "") + " expected";
    }
    function genVerifyValue(gen, field, fieldIndex, ref) {
      if (field.resolvedType)
        if (field.resolvedType instanceof Enum) {
          gen("switch(%s){", ref)("default:")("return%j", invalid(field, "enum value"));
          for (var keys = Object.keys(field.resolvedType.values), j = 0; j < keys.length; ++j) gen("case %i:", field.resolvedType.values[keys[j]]);
          gen("break")("}");
        } else
          gen("{")("var e=types[%i].verify(%s,n+1);", fieldIndex, ref)("if(e)")("return%j+e", field.name + ".")("}");
      else
        switch (field.type) {
          case "int32":
          case "uint32":
          case "sint32":
          case "fixed32":
          case "sfixed32":
            gen("if(!util.isInteger(%s))", ref)("return%j", invalid(field, "integer"));
            break;
          case "int64":
          case "uint64":
          case "sint64":
          case "fixed64":
          case "sfixed64":
            gen("if(!util.isInteger(%s)&&!(%s&&util.isInteger(%s.low)&&util.isInteger(%s.high)))", ref, ref, ref, ref)("return%j", invalid(field, "integer|Long"));
            break;
          case "float":
          case "double":
            gen('if(typeof %s!=="number")', ref)("return%j", invalid(field, "number"));
            break;
          case "bool":
            gen('if(typeof %s!=="boolean")', ref)("return%j", invalid(field, "boolean"));
            break;
          case "string":
            gen("if(!util.isString(%s))", ref)("return%j", invalid(field, "string"));
            break;
          case "bytes":
            gen('if(!(%s&&typeof %s.length==="number"||util.isString(%s)))', ref, ref, ref)("return%j", invalid(field, "buffer"));
            break;
        }
      return gen;
    }
    function genVerifyKey(gen, field, ref) {
      switch (field.keyType) {
        case "int32":
        case "uint32":
        case "sint32":
        case "fixed32":
        case "sfixed32":
          gen("if(!util.key32Re.test(%s))", ref)("return%j", invalid(field, "integer key"));
          break;
        case "int64":
        case "uint64":
        case "sint64":
        case "fixed64":
        case "sfixed64":
          gen("if(!util.key64Re.test(%s))", ref)("return%j", invalid(field, "integer|Long key"));
          break;
        case "bool":
          gen("if(!util.key2Re.test(%s))", ref)("return%j", invalid(field, "boolean key"));
          break;
      }
      return gen;
    }
    function verifier(mtype) {
      var gen = util.codegen(["m", "n"], mtype.name + "$verify")('if(typeof m!=="object"||m===null)')("return%j", "object expected")("if(n===undefined)n=0")("if(n>util.recursionLimit)")("return%j", "maximum nesting depth exceeded"), oneofs = mtype.oneofsArray, seenFirstField = {};
      oneofs.length && gen("var p={}");
      for (var i = 0; i < /* initializes */
      mtype.fieldsArray.length; ++i) {
        var field = mtype._fieldsArray[i].resolve(), ref = "m" + util.safeProp(field.name);
        if (field.optional && gen("if(%s!=null&&m.hasOwnProperty(%j)){", ref, field.name), field.map)
          gen("if(!util.isObject(%s))", ref)("return%j", invalid(field, "object"))("var k=Object.keys(%s)", ref)("for(var i=0;i<k.length;++i){"), genVerifyKey(gen, field, "k[i]"), genVerifyValue(gen, field, i, ref + "[k[i]]")("}");
        else if (field.repeated)
          gen("if(!Array.isArray(%s))", ref)("return%j", invalid(field, "array"))("for(var i=0;i<%s.length;++i){", ref), genVerifyValue(gen, field, i, ref + "[i]")("}");
        else {
          if (field.partOf) {
            var oneofProp = util.safeProp(field.partOf.name);
            seenFirstField[field.partOf.name] === 1 && gen("if(p%s===1)", oneofProp)("return%j", field.partOf.name + ": multiple values"), seenFirstField[field.partOf.name] = 1, gen("p%s=1", oneofProp);
          }
          genVerifyValue(gen, field, i, ref);
        }
        field.optional && gen("}");
      }
      return gen("return null");
    }
  }
});

// node_modules/protobufjs/src/converter.js
var require_converter = __commonJS({
  "node_modules/protobufjs/src/converter.js"(exports) {
    "use strict";
    var converter = exports, Enum = require_enum(), util = require_util();
    function genValuePartial_fromObject(gen, field, fieldIndex, prop) {
      var defaultAlreadyEmitted = !1;
      if (field.resolvedType)
        if (field.resolvedType instanceof Enum) {
          gen("switch(d%s){", prop);
          for (var values = field.resolvedType.values, keys = Object.keys(values), i = 0; i < keys.length; ++i)
            values[keys[i]] === field.typeDefault && !defaultAlreadyEmitted && (gen("default:")('if(typeof(d%s)==="number"){m%s=d%s;break}', prop, prop, prop), field.repeated || gen("break"), defaultAlreadyEmitted = !0), gen("case%j:", keys[i])("case %i:", values[keys[i]])("m%s=%j", prop, values[keys[i]])("break");
          gen("}");
        } else gen('if(typeof d%s!=="object")', prop)("throw TypeError(%j)", field.fullName + ": object expected")("m%s=types[%i].fromObject(d%s,n+1)", prop, fieldIndex, prop);
      else {
        var isUnsigned = !1;
        switch (field.type) {
          case "double":
          case "float":
            gen("m%s=Number(d%s)", prop, prop);
            break;
          case "uint32":
          case "fixed32":
            gen("m%s=d%s>>>0", prop, prop);
            break;
          case "int32":
          case "sint32":
          case "sfixed32":
            gen("m%s=d%s|0", prop, prop);
            break;
          case "uint64":
            isUnsigned = !0;
          // eslint-disable-next-line no-fallthrough
          case "int64":
          case "sint64":
          case "fixed64":
          case "sfixed64":
            gen("if(util.Long)")("(m%s=util.Long.fromValue(d%s)).unsigned=%j", prop, prop, isUnsigned)('else if(typeof d%s==="string")', prop)("m%s=parseInt(d%s,10)", prop, prop)('else if(typeof d%s==="number")', prop)("m%s=d%s", prop, prop)('else if(typeof d%s==="object")', prop)("m%s=new util.LongBits(d%s.low>>>0,d%s.high>>>0).toNumber(%s)", prop, prop, prop, isUnsigned ? "true" : "");
            break;
          case "bytes":
            gen('if(typeof d%s==="string")', prop)("util.base64.decode(d%s,m%s=util.newBuffer(util.base64.length(d%s)),0)", prop, prop, prop)("else if(d%s.length >= 0)", prop)("m%s=d%s", prop, prop);
            break;
          case "string":
            gen("m%s=String(d%s)", prop, prop);
            break;
          case "bool":
            gen("m%s=Boolean(d%s)", prop, prop);
            break;
        }
      }
      return gen;
    }
    converter.fromObject = function(mtype) {
      var fields = mtype.fieldsArray, gen = util.codegen(["d", "n"], mtype.name + "$fromObject")("if(d instanceof this.ctor)")("return d")("if(n===undefined)n=0")("if(n>util.recursionLimit)")('throw Error("maximum nesting depth exceeded")');
      if (!fields.length) return gen("return new this.ctor");
      gen("var m=new this.ctor");
      for (var i = 0; i < fields.length; ++i) {
        var field = fields[i].resolve(), prop = util.safeProp(field.name);
        field.map ? (gen("if(d%s){", prop)('if(typeof d%s!=="object")', prop)("throw TypeError(%j)", field.fullName + ": object expected")("m%s={}", prop)("for(var ks=Object.keys(d%s),i=0;i<ks.length;++i){", prop), gen('if(ks[i]==="__proto__")')("util.makeProp(m%s,ks[i])", prop), genValuePartial_fromObject(
          gen,
          field,
          /* not sorted */
          i,
          prop + "[ks[i]]"
        )("}")("}")) : field.repeated ? (gen("if(d%s){", prop)("if(!Array.isArray(d%s))", prop)("throw TypeError(%j)", field.fullName + ": array expected")("m%s=[]", prop)("for(var i=0;i<d%s.length;++i){", prop), genValuePartial_fromObject(
          gen,
          field,
          /* not sorted */
          i,
          prop + "[i]"
        )("}")("}")) : (field.resolvedType instanceof Enum || gen("if(d%s!=null){", prop), genValuePartial_fromObject(
          gen,
          field,
          /* not sorted */
          i,
          prop
        ), field.resolvedType instanceof Enum || gen("}"));
      }
      return gen("return m");
    };
    function genValuePartial_toObject(gen, field, fieldIndex, prop) {
      if (field.resolvedType)
        field.resolvedType instanceof Enum ? gen("d%s=o.enums===String?(types[%i].values[m%s]===undefined?m%s:types[%i].values[m%s]):m%s", prop, fieldIndex, prop, prop, fieldIndex, prop, prop) : gen("d%s=types[%i].toObject(m%s,o)", prop, fieldIndex, prop);
      else {
        var isUnsigned = !1;
        switch (field.type) {
          case "double":
          case "float":
            gen("d%s=o.json&&!isFinite(m%s)?String(m%s):m%s", prop, prop, prop, prop);
            break;
          case "uint64":
            isUnsigned = !0;
          // eslint-disable-next-line no-fallthrough
          case "int64":
          case "sint64":
          case "fixed64":
          case "sfixed64":
            gen('if(typeof m%s==="number")', prop)("d%s=o.longs===String?String(m%s):m%s", prop, prop, prop)("else")("d%s=o.longs===String?util.Long.prototype.toString.call(m%s):o.longs===Number?new util.LongBits(m%s.low>>>0,m%s.high>>>0).toNumber(%s):m%s", prop, prop, prop, prop, isUnsigned ? "true" : "", prop);
            break;
          case "bytes":
            gen("d%s=o.bytes===String?util.base64.encode(m%s,0,m%s.length):o.bytes===Array?Array.prototype.slice.call(m%s):m%s", prop, prop, prop, prop, prop);
            break;
          default:
            gen("d%s=m%s", prop, prop);
            break;
        }
      }
      return gen;
    }
    converter.toObject = function(mtype) {
      var fields = mtype.fieldsArray.slice().sort(util.compareFieldsById);
      if (!fields.length)
        return util.codegen()("return {}");
      for (var gen = util.codegen(["m", "o"], mtype.name + "$toObject")("if(!o)")("o={}")("var d={}"), repeatedFields = [], mapFields = [], normalFields = [], i = 0; i < fields.length; ++i)
        fields[i].partOf || (fields[i].resolve().repeated ? repeatedFields : fields[i].map ? mapFields : normalFields).push(fields[i]);
      if (repeatedFields.length) {
        for (gen("if(o.arrays||o.defaults){"), i = 0; i < repeatedFields.length; ++i) gen("d%s=[]", util.safeProp(repeatedFields[i].name));
        gen("}");
      }
      if (mapFields.length) {
        for (gen("if(o.objects||o.defaults){"), i = 0; i < mapFields.length; ++i) gen("d%s={}", util.safeProp(mapFields[i].name));
        gen("}");
      }
      if (normalFields.length) {
        for (gen("if(o.defaults){"), i = 0; i < normalFields.length; ++i) {
          var field = normalFields[i], prop = util.safeProp(field.name);
          if (field.resolvedType instanceof Enum) gen("d%s=o.enums===String?%j:%j", prop, field.resolvedType.valuesById[field.typeDefault], field.typeDefault);
          else if (field.long) gen("if(util.Long){")("var n=new util.Long(%i,%i,%j)", field.typeDefault.low, field.typeDefault.high, field.typeDefault.unsigned)("d%s=o.longs===String?n.toString():o.longs===Number?n.toNumber():n", prop)("}else")("d%s=o.longs===String?%j:%i", prop, field.typeDefault.toString(), field.typeDefault.toNumber());
          else if (field.bytes) {
            var arrayDefault = Array.prototype.slice.call(field.typeDefault);
            gen("if(o.bytes===String)d%s=%j", prop, String.fromCharCode.apply(String, field.typeDefault))("else{")("d%s=%j", prop, arrayDefault)("if(o.bytes!==Array)d%s=util.newBuffer(d%s)", prop, prop)("}");
          } else gen("d%s=%j", prop, field.typeDefault);
        }
        gen("}");
      }
      var hasKs2 = !1;
      for (i = 0; i < fields.length; ++i) {
        var field = fields[i], index = mtype._fieldsArray.indexOf(field), prop = util.safeProp(field.name);
        field.map ? (hasKs2 || (hasKs2 = !0, gen("var ks2")), gen("if(m%s&&(ks2=Object.keys(m%s)).length){", prop, prop)("d%s={}", prop)("for(var j=0;j<ks2.length;++j){"), gen('if(ks2[j]==="__proto__")')("util.makeProp(d%s,ks2[j])", prop), genValuePartial_toObject(
          gen,
          field,
          /* sorted */
          index,
          prop + "[ks2[j]]"
        )("}")) : field.repeated ? (gen("if(m%s&&m%s.length){", prop, prop)("d%s=[]", prop)("for(var j=0;j<m%s.length;++j){", prop), genValuePartial_toObject(
          gen,
          field,
          /* sorted */
          index,
          prop + "[j]"
        )("}")) : (gen("if(m%s!=null&&m.hasOwnProperty(%j)){", prop, field.name), genValuePartial_toObject(
          gen,
          field,
          /* sorted */
          index,
          prop
        ), field.partOf && gen("if(o.oneofs)")("d%s=%j", util.safeProp(field.partOf.name), field.name)), gen("}");
      }
      return gen("return d");
    };
  }
});

// node_modules/protobufjs/src/wrappers.js
var require_wrappers = __commonJS({
  "node_modules/protobufjs/src/wrappers.js"(exports) {
    "use strict";
    var wrappers = exports, Message = require_message();
    wrappers[".google.protobuf.Any"] = {
      fromObject: function(object, depth) {
        if (object && object["@type"]) {
          var name = object["@type"].substring(object["@type"].lastIndexOf("/") + 1), type = this.lookup(name);
          if (type) {
            var type_url = object["@type"].charAt(0) === "." ? object["@type"].slice(1) : object["@type"];
            type_url.indexOf("/") === -1 && (type_url = "/" + type_url);
            var nextDepth = depth === void 0 ? 1 : depth + 1;
            return this.create({
              type_url,
              value: type.encode(type.fromObject(object, nextDepth)).finish()
            });
          }
        }
        return this.fromObject(object, depth);
      },
      toObject: function(message, options) {
        var googleApi = "type.googleapis.com/", prefix = "", name = "";
        if (options && options.json && message.type_url && message.value) {
          name = message.type_url.substring(message.type_url.lastIndexOf("/") + 1), prefix = message.type_url.substring(0, message.type_url.lastIndexOf("/") + 1);
          var type = this.lookup(name);
          type && (message = type.decode(message.value));
        }
        if (!(message instanceof this.ctor) && message instanceof Message) {
          var object = message.$type.toObject(message, options), messageName = message.$type.fullName[0] === "." ? message.$type.fullName.slice(1) : message.$type.fullName;
          return prefix === "" && (prefix = googleApi), name = prefix + messageName, object["@type"] = name, object;
        }
        return this.toObject(message, options);
      }
    };
  }
});

// node_modules/protobufjs/src/type.js
var require_type = __commonJS({
  "node_modules/protobufjs/src/type.js"(exports, module) {
    "use strict";
    module.exports = Type;
    var Namespace = require_namespace();
    ((Type.prototype = Object.create(Namespace.prototype)).constructor = Type).className = "Type";
    var Enum = require_enum(), OneOf = require_oneof(), Field = require_field(), MapField = require_mapfield(), Service = require_service2(), Message = require_message(), Reader = require_reader(), Writer = require_writer(), util = require_util(), encoder = require_encoder(), decoder = require_decoder(), verifier = require_verifier(), converter = require_converter(), wrappers = require_wrappers();
    function Type(name, options) {
      name = name.replace(/\W/g, ""), Namespace.call(this, name, options), this.fields = {}, this.oneofs = void 0, this.extensions = void 0, this.reserved = void 0, this.group = void 0, this._fieldsById = null, this._fieldsArray = null, this._oneofsArray = null, this._ctor = null;
    }
    Object.defineProperties(Type.prototype, {
      /**
       * Message fields by id.
       * @name Type#fieldsById
       * @type {Object.<number,Field>}
       * @readonly
       */
      fieldsById: {
        get: function() {
          if (this._fieldsById)
            return this._fieldsById;
          this._fieldsById = {};
          for (var names = Object.keys(this.fields), i = 0; i < names.length; ++i) {
            var field = this.fields[names[i]], id = field.id;
            if (this._fieldsById[id])
              throw Error("duplicate id " + id + " in " + this);
            this._fieldsById[id] = field;
          }
          return this._fieldsById;
        }
      },
      /**
       * Fields of this message as an array for iteration.
       * @name Type#fieldsArray
       * @type {Field[]}
       * @readonly
       */
      fieldsArray: {
        get: function() {
          return this._fieldsArray || (this._fieldsArray = util.toArray(this.fields));
        }
      },
      /**
       * Oneofs of this message as an array for iteration.
       * @name Type#oneofsArray
       * @type {OneOf[]}
       * @readonly
       */
      oneofsArray: {
        get: function() {
          return this._oneofsArray || (this._oneofsArray = util.toArray(this.oneofs));
        }
      },
      /**
       * The registered constructor, if any registered, otherwise a generic constructor.
       * Assigning a function replaces the internal constructor. If the function does not extend {@link Message} yet, its prototype will be setup accordingly and static methods will be populated. If it already extends {@link Message}, it will just replace the internal constructor.
       * @name Type#ctor
       * @type {Constructor<{}>}
       */
      ctor: {
        get: function() {
          return this._ctor || (this.ctor = Type.generateConstructor(this)());
        },
        set: function(ctor) {
          var prototype = ctor.prototype;
          prototype instanceof Message || ((ctor.prototype = new Message()).constructor = ctor, util.merge(ctor.prototype, prototype)), ctor.$type = ctor.prototype.$type = this, util.merge(ctor, Message, !0), this._ctor = ctor;
          for (var i = 0; i < /* initializes */
          this.fieldsArray.length; ++i)
            this._fieldsArray[i].resolve();
          var ctorProperties = {};
          for (i = 0; i < /* initializes */
          this.oneofsArray.length; ++i)
            ctorProperties[this._oneofsArray[i].resolve().name] = {
              get: util.oneOfGetter(this._oneofsArray[i].oneof),
              set: util.oneOfSetter(this._oneofsArray[i].oneof)
            };
          i && Object.defineProperties(ctor.prototype, ctorProperties);
        }
      }
    });
    Type.generateConstructor = function(mtype) {
      for (var gen = util.codegen(["p"], mtype.name), i = 0, field; i < mtype.fieldsArray.length; ++i)
        (field = mtype._fieldsArray[i]).map ? gen("this%s={}", util.safeProp(field.name)) : field.repeated && gen("this%s=[]", util.safeProp(field.name));
      return gen('if(p)for(var ks=Object.keys(p),i=0;i<ks.length;++i)if(p[ks[i]]!=null&&ks[i]!=="__proto__")')("this[ks[i]]=p[ks[i]]");
    };
    function clearCache(type) {
      return type._fieldsById = type._fieldsArray = type._oneofsArray = null, delete type.encode, delete type.decode, delete type.verify, type;
    }
    Type.fromJSON = function(name, json, depth) {
      depth = util.checkDepth(depth);
      var type = new Type(name, json.options);
      type.extensions = json.extensions, type.reserved = json.reserved;
      for (var names = Object.keys(json.fields), i = 0; i < names.length; ++i)
        type.add(
          (typeof json.fields[names[i]].keyType < "u" ? MapField.fromJSON : Field.fromJSON)(names[i], json.fields[names[i]])
        );
      if (json.oneofs)
        for (names = Object.keys(json.oneofs), i = 0; i < names.length; ++i)
          type.add(OneOf.fromJSON(names[i], json.oneofs[names[i]]));
      if (json.nested)
        for (names = Object.keys(json.nested), i = 0; i < names.length; ++i) {
          var nested = json.nested[names[i]];
          type.add(
            // most to least likely
            (nested.id !== void 0 ? Field.fromJSON : nested.fields !== void 0 ? Type.fromJSON : nested.values !== void 0 ? Enum.fromJSON : nested.methods !== void 0 ? Service.fromJSON : Namespace.fromJSON)(names[i], nested, depth + 1)
          );
        }
      return json.extensions && json.extensions.length && (type.extensions = json.extensions), json.reserved && json.reserved.length && (type.reserved = json.reserved), json.group && (type.group = !0), json.comment && (type.comment = json.comment), json.edition && (type._edition = json.edition), type._defaultEdition = "proto3", type;
    };
    Type.prototype.toJSON = function(toJSONOptions) {
      var inherited = Namespace.prototype.toJSON.call(this, toJSONOptions), keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "edition",
        this._editionToJSON(),
        "options",
        inherited && inherited.options || void 0,
        "oneofs",
        Namespace.arrayToJSON(this.oneofsArray, toJSONOptions),
        "fields",
        Namespace.arrayToJSON(this.fieldsArray.filter(function(obj) {
          return !obj.declaringField;
        }), toJSONOptions) || {},
        "extensions",
        this.extensions && this.extensions.length ? this.extensions : void 0,
        "reserved",
        this.reserved && this.reserved.length ? this.reserved : void 0,
        "group",
        this.group || void 0,
        "nested",
        inherited && inherited.nested || void 0,
        "comment",
        keepComments ? this.comment : void 0
      ]);
    };
    Type.prototype.resolveAll = function() {
      if (!this._needsRecursiveResolve) return this;
      Namespace.prototype.resolveAll.call(this);
      var oneofs = this.oneofsArray;
      for (i = 0; i < oneofs.length; )
        oneofs[i++].resolve();
      for (var fields = this.fieldsArray, i = 0; i < fields.length; )
        fields[i++].resolve();
      return this;
    };
    Type.prototype._resolveFeaturesRecursive = function(edition) {
      return this._needsRecursiveFeatureResolution ? (edition = this._edition || edition, Namespace.prototype._resolveFeaturesRecursive.call(this, edition), this.oneofsArray.forEach((oneof) => {
        oneof._resolveFeatures(edition);
      }), this.fieldsArray.forEach((field) => {
        field._resolveFeatures(edition);
      }), this) : this;
    };
    Type.prototype.get = function(name) {
      return Object.prototype.hasOwnProperty.call(this.fields, name) ? this.fields[name] : this.oneofs && Object.prototype.hasOwnProperty.call(this.oneofs, name) ? this.oneofs[name] : this.nested && Object.prototype.hasOwnProperty.call(this.nested, name) ? this.nested[name] : null;
    };
    Type.prototype.add = function(object) {
      if (this.get(object.name))
        throw Error("duplicate name '" + object.name + "' in " + this);
      if (object instanceof Field && object.extend === void 0) {
        if (this._fieldsById ? (
          /* istanbul ignore next */
          this._fieldsById[object.id]
        ) : this.fieldsById[object.id])
          throw Error("duplicate id " + object.id + " in " + this);
        if (this.isReservedId(object.id))
          throw Error("id " + object.id + " is reserved in " + this);
        if (this.isReservedName(object.name))
          throw Error("name '" + object.name + "' is reserved in " + this);
        return object.name === "__proto__" ? this : (object.parent && object.parent.remove(object), this.fields[object.name] = object, object.message = this, object.onAdd(this), clearCache(this));
      }
      return object instanceof OneOf ? object.name === "__proto__" ? this : (this.oneofs || (this.oneofs = {}), this.oneofs[object.name] = object, object.onAdd(this), clearCache(this)) : Namespace.prototype.add.call(this, object);
    };
    Type.prototype.remove = function(object) {
      if (object instanceof Field && object.extend === void 0) {
        if (!this.fields || this.fields[object.name] !== object)
          throw Error(object + " is not a member of " + this);
        return delete this.fields[object.name], object.parent = null, object.onRemove(this), clearCache(this);
      }
      if (object instanceof OneOf) {
        if (!this.oneofs || this.oneofs[object.name] !== object)
          throw Error(object + " is not a member of " + this);
        return delete this.oneofs[object.name], object.parent = null, object.onRemove(this), clearCache(this);
      }
      return Namespace.prototype.remove.call(this, object);
    };
    Type.prototype.isReservedId = function(id) {
      return Namespace.isReservedId(this.reserved, id);
    };
    Type.prototype.isReservedName = function(name) {
      return Namespace.isReservedName(this.reserved, name);
    };
    Type.prototype.create = function(properties) {
      return new this.ctor(properties);
    };
    Type.prototype.setup = function() {
      for (var fullName = this.fullName, types = [], i = 0; i < /* initializes */
      this.fieldsArray.length; ++i)
        types.push(this._fieldsArray[i].resolve().resolvedType);
      this.encode = encoder(this)({
        Writer,
        types,
        util
      }), this.decode = decoder(this)({
        Reader,
        types,
        util
      }), this.verify = verifier(this)({
        types,
        util
      }), this.fromObject = converter.fromObject(this)({
        types,
        util
      }), this.toObject = converter.toObject(this)({
        types,
        util
      });
      var wrapper = wrappers[fullName];
      if (wrapper) {
        var originalThis = Object.create(this);
        originalThis.fromObject = this.fromObject, this.fromObject = wrapper.fromObject.bind(originalThis), originalThis.toObject = this.toObject, this.toObject = wrapper.toObject.bind(originalThis);
      }
      return this;
    };
    Type.prototype.encode = function(message, writer) {
      return this.setup().encode(message, writer);
    };
    Type.prototype.encodeDelimited = function(message, writer) {
      return this.encode(message, writer && writer.len ? writer.fork() : writer).ldelim();
    };
    Type.prototype.decode = function(reader, length, end, depth) {
      return this.setup().decode(reader, length, end, depth);
    };
    Type.prototype.decodeDelimited = function(reader) {
      return reader instanceof Reader || (reader = Reader.create(reader)), this.decode(reader, reader.uint32());
    };
    Type.prototype.verify = function(message, depth) {
      return this.setup().verify(message, depth);
    };
    Type.prototype.fromObject = function(object, depth) {
      return this.setup().fromObject(object, depth);
    };
    Type.prototype.toObject = function(message, options) {
      return this.setup().toObject(message, options);
    };
    Type.d = function(typeName) {
      return function(target) {
        util.decorateType(target, typeName);
      };
    };
  }
});

// node_modules/protobufjs/src/root.js
var require_root = __commonJS({
  "node_modules/protobufjs/src/root.js"(exports, module) {
    "use strict";
    module.exports = Root;
    var Namespace = require_namespace();
    ((Root.prototype = Object.create(Namespace.prototype)).constructor = Root).className = "Root";
    var Field = require_field(), Enum = require_enum(), OneOf = require_oneof(), util = require_util(), Type, parse2, common;
    function Root(options) {
      Namespace.call(this, "", options), this.deferred = [], this.files = [], this._edition = "proto2", this._fullyQualifiedObjects = {};
    }
    Root.fromJSON = function(json, root, depth) {
      return depth = util.checkDepth(depth), root || (root = new Root()), json.options && root.setOptions(json.options), root.addJSON(json.nested, depth).resolveAll();
    };
    Root.prototype.resolvePath = util.path.resolve;
    Root.prototype.fetch = util.fetch;
    function SYNC() {
    }
    Root.prototype.load = function load(filename, options, callback) {
      typeof options == "function" && (callback = options, options = void 0);
      var self2 = this;
      if (!callback)
        return util.asPromise(load, self2, filename, options);
      var sync = callback === SYNC;
      function finish(err, root) {
        if (callback) {
          if (sync)
            throw err;
          root && root.resolveAll();
          var cb = callback;
          callback = null, cb(err, root);
        }
      }
      function getBundledFileName(filename2) {
        var idx = filename2.lastIndexOf("google/protobuf/");
        if (idx > -1) {
          var altname = filename2.substring(idx);
          if (altname in common) return altname;
        }
        return null;
      }
      function process(filename2, source) {
        try {
          if (util.isString(source) && source.charAt(0) === "{" && (source = JSON.parse(source)), !util.isString(source))
            self2.setOptions(source.options).addJSON(source.nested);
          else {
            parse2.filename = filename2;
            var parsed = parse2(source, self2, options), resolved2, i2 = 0;
            if (parsed.imports)
              for (; i2 < parsed.imports.length; ++i2)
                (resolved2 = getBundledFileName(parsed.imports[i2]) || self2.resolvePath(filename2, parsed.imports[i2])) && fetch(resolved2);
            if (parsed.weakImports)
              for (i2 = 0; i2 < parsed.weakImports.length; ++i2)
                (resolved2 = getBundledFileName(parsed.weakImports[i2]) || self2.resolvePath(filename2, parsed.weakImports[i2])) && fetch(resolved2, !0);
          }
        } catch (err) {
          finish(err);
        }
        !sync && !queued && finish(null, self2);
      }
      function fetch(filename2, weak) {
        if (filename2 = getBundledFileName(filename2) || filename2, !(self2.files.indexOf(filename2) > -1)) {
          if (self2.files.push(filename2), filename2 in common) {
            sync ? process(filename2, common[filename2]) : (++queued, setTimeout(function() {
              --queued, process(filename2, common[filename2]);
            }));
            return;
          }
          if (sync) {
            var source;
            try {
              source = util.fs.readFileSync(filename2).toString("utf8");
            } catch (err) {
              weak || finish(err);
              return;
            }
            process(filename2, source);
          } else
            ++queued, self2.fetch(filename2, function(err, source2) {
              if (--queued, !!callback) {
                if (err) {
                  weak ? queued || finish(null, self2) : finish(err);
                  return;
                }
                process(filename2, source2);
              }
            });
        }
      }
      var queued = 0;
      util.isString(filename) && (filename = [filename]);
      for (var i = 0, resolved; i < filename.length; ++i)
        (resolved = self2.resolvePath("", filename[i])) && fetch(resolved);
      return sync ? (self2.resolveAll(), self2) : (queued || finish(null, self2), self2);
    };
    Root.prototype.loadSync = function(filename, options) {
      if (!util.isNode)
        throw Error("not supported");
      return this.load(filename, options, SYNC);
    };
    Root.prototype.resolveAll = function() {
      if (!this._needsRecursiveResolve) return this;
      if (this.deferred.length)
        throw Error("unresolvable extensions: " + this.deferred.map(function(field) {
          return "'extend " + field.extend + "' in " + field.parent.fullName;
        }).join(", "));
      return Namespace.prototype.resolveAll.call(this);
    };
    var exposeRe = /^[A-Z]/;
    function tryHandleExtension(root, field) {
      var extendedType = field.parent.lookup(field.extend);
      if (extendedType) {
        var sisterField = new Field(field.fullName, field.id, field.type, field.rule, void 0, field.options);
        return extendedType.get(sisterField.name) || (sisterField.declaringField = field, field.extensionField = sisterField, extendedType.add(sisterField)), !0;
      }
      return !1;
    }
    Root.prototype._handleAdd = function(object) {
      if (object instanceof Field)
        /* an extension field (implies not part of a oneof) */
        object.extend !== void 0 && /* not already handled */
        !object.extensionField && (tryHandleExtension(this, object) || this.deferred.push(object));
      else if (object instanceof Enum)
        exposeRe.test(object.name) && (object.parent[object.name] = object.values);
      else if (!(object instanceof OneOf)) {
        if (object instanceof Type)
          for (var i = 0; i < this.deferred.length; )
            tryHandleExtension(this, this.deferred[i]) ? this.deferred.splice(i, 1) : ++i;
        for (var j = 0; j < /* initializes */
        object.nestedArray.length; ++j)
          this._handleAdd(object._nestedArray[j]);
        exposeRe.test(object.name) && (object.parent[object.name] = object);
      }
      (object instanceof Type || object instanceof Enum || object instanceof Field) && (this._fullyQualifiedObjects[object.fullName] = object);
    };
    Root.prototype._handleRemove = function(object) {
      if (object instanceof Field) {
        if (
          /* an extension field */
          object.extend !== void 0
        )
          if (
            /* already handled */
            object.extensionField
          )
            object.extensionField.parent.remove(object.extensionField), object.extensionField = null;
          else {
            var index = this.deferred.indexOf(object);
            index > -1 && this.deferred.splice(index, 1);
          }
      } else if (object instanceof Enum)
        exposeRe.test(object.name) && delete object.parent[object.name];
      else if (object instanceof Namespace) {
        for (var i = 0; i < /* initializes */
        object.nestedArray.length; ++i)
          this._handleRemove(object._nestedArray[i]);
        exposeRe.test(object.name) && delete object.parent[object.name];
      }
      delete this._fullyQualifiedObjects[object.fullName];
    };
    Root._configure = function(Type_, parse_, common_) {
      Type = Type_, parse2 = parse_, common = common_;
    };
  }
});

// node_modules/protobufjs/src/util.js
var require_util = __commonJS({
  "node_modules/protobufjs/src/util.js"(exports, module) {
    "use strict";
    var util = module.exports = require_minimal(), roots = require_roots(), Type, Enum;
    util.codegen = require_codegen();
    util.fetch = require_fetch();
    util.path = require_path();
    util.patterns = require_patterns();
    var reservedRe = util.patterns.reservedRe, unsafePropertyRe = util.patterns.unsafePropertyRe;
    util.fs = util.inquire("fs");
    util.checkDepth = function(depth) {
      if (depth === void 0 && (depth = 0), depth > util.recursionLimit)
        throw Error("max depth exceeded");
      return depth;
    };
    util.toArray = function(object) {
      if (object) {
        for (var keys = Object.keys(object), array = new Array(keys.length), index = 0; index < keys.length; )
          array[index] = object[keys[index++]];
        return array;
      }
      return [];
    };
    util.toObject = function(array) {
      for (var object = {}, index = 0; index < array.length; ) {
        var key = array[index++], val = array[index++];
        val !== void 0 && (object[key] = val);
      }
      return object;
    };
    util.isReserved = function(name) {
      return reservedRe.test(name);
    };
    util.safeProp = function(prop) {
      return !/^[$\w_]+$/.test(prop) || reservedRe.test(prop) ? "[" + JSON.stringify(prop) + "]" : "." + prop;
    };
    util.ucFirst = function(str) {
      return str.charAt(0).toUpperCase() + str.substring(1);
    };
    var camelCaseRe = /_([a-z])/g;
    util.camelCase = function(str) {
      return str.substring(0, 1) + str.substring(1).replace(camelCaseRe, function($0, $1) {
        return $1.toUpperCase();
      });
    };
    util.compareFieldsById = function(a, b) {
      return a.id - b.id;
    };
    util.decorateType = function(ctor, typeName) {
      if (ctor.$type)
        return typeName && ctor.$type.name !== typeName && (util.decorateRoot.remove(ctor.$type), ctor.$type.name = typeName, util.decorateRoot.add(ctor.$type)), ctor.$type;
      Type || (Type = require_type());
      var type = new Type(typeName || ctor.name);
      return util.decorateRoot.add(type), type.ctor = ctor, Object.defineProperty(ctor, "$type", { value: type, enumerable: !1 }), Object.defineProperty(ctor.prototype, "$type", { value: type, enumerable: !1 }), type;
    };
    var decorateEnumIndex = 0;
    util.decorateEnum = function(object) {
      if (object.$type)
        return object.$type;
      Enum || (Enum = require_enum());
      var enm = new Enum("Enum" + decorateEnumIndex++, object);
      return util.decorateRoot.add(enm), Object.defineProperty(object, "$type", { value: enm, enumerable: !1 }), enm;
    };
    util.setProperty = function(dst, path, value, ifNotSet) {
      function setProp(dst2, path2, value2) {
        var part = path2.shift();
        if (unsafePropertyRe.test(part))
          return dst2;
        if (path2.length > 0)
          dst2[part] = setProp(dst2[part] || {}, path2, value2);
        else {
          var prevValue = dst2[part];
          if (prevValue && ifNotSet)
            return dst2;
          prevValue && (value2 = [].concat(prevValue).concat(value2)), dst2[part] = value2;
        }
        return dst2;
      }
      if (typeof dst != "object")
        throw TypeError("dst must be an object");
      if (!path)
        throw TypeError("path must be specified");
      return path = path.split("."), setProp(dst, path, value);
    };
    Object.defineProperty(util, "decorateRoot", {
      get: function() {
        return roots.decorated || (roots.decorated = new (require_root())());
      }
    });
  }
});

// node_modules/protobufjs/src/types.js
var require_types = __commonJS({
  "node_modules/protobufjs/src/types.js"(exports) {
    "use strict";
    var types = exports, util = require_util(), s = [
      "double",
      // 0
      "float",
      // 1
      "int32",
      // 2
      "uint32",
      // 3
      "sint32",
      // 4
      "fixed32",
      // 5
      "sfixed32",
      // 6
      "int64",
      // 7
      "uint64",
      // 8
      "sint64",
      // 9
      "fixed64",
      // 10
      "sfixed64",
      // 11
      "bool",
      // 12
      "string",
      // 13
      "bytes"
      // 14
    ];
    function bake(values, offset) {
      var i = 0, o = /* @__PURE__ */ Object.create(null);
      for (offset |= 0; i < values.length; ) o[s[i + offset]] = values[i++];
      return o;
    }
    types.basic = bake([
      /* double   */
      1,
      /* float    */
      5,
      /* int32    */
      0,
      /* uint32   */
      0,
      /* sint32   */
      0,
      /* fixed32  */
      5,
      /* sfixed32 */
      5,
      /* int64    */
      0,
      /* uint64   */
      0,
      /* sint64   */
      0,
      /* fixed64  */
      1,
      /* sfixed64 */
      1,
      /* bool     */
      0,
      /* string   */
      2,
      /* bytes    */
      2
    ]);
    types.defaults = bake([
      /* double   */
      0,
      /* float    */
      0,
      /* int32    */
      0,
      /* uint32   */
      0,
      /* sint32   */
      0,
      /* fixed32  */
      0,
      /* sfixed32 */
      0,
      /* int64    */
      0,
      /* uint64   */
      0,
      /* sint64   */
      0,
      /* fixed64  */
      0,
      /* sfixed64 */
      0,
      /* bool     */
      !1,
      /* string   */
      "",
      /* bytes    */
      util.emptyArray,
      /* message  */
      null
    ]);
    types.long = bake([
      /* int64    */
      0,
      /* uint64   */
      0,
      /* sint64   */
      0,
      /* fixed64  */
      1,
      /* sfixed64 */
      1
    ], 7);
    types.mapKey = bake([
      /* int32    */
      0,
      /* uint32   */
      0,
      /* sint32   */
      0,
      /* fixed32  */
      5,
      /* sfixed32 */
      5,
      /* int64    */
      0,
      /* uint64   */
      0,
      /* sint64   */
      0,
      /* fixed64  */
      1,
      /* sfixed64 */
      1,
      /* bool     */
      0,
      /* string   */
      2
    ], 2);
    types.packed = bake([
      /* double   */
      1,
      /* float    */
      5,
      /* int32    */
      0,
      /* uint32   */
      0,
      /* sint32   */
      0,
      /* fixed32  */
      5,
      /* sfixed32 */
      5,
      /* int64    */
      0,
      /* uint64   */
      0,
      /* sint64   */
      0,
      /* fixed64  */
      1,
      /* sfixed64 */
      1,
      /* bool     */
      0
    ]);
  }
});

// node_modules/protobufjs/src/field.js
var require_field = __commonJS({
  "node_modules/protobufjs/src/field.js"(exports, module) {
    "use strict";
    module.exports = Field;
    var ReflectionObject = require_object();
    ((Field.prototype = Object.create(ReflectionObject.prototype)).constructor = Field).className = "Field";
    var Enum = require_enum(), types = require_types(), util = require_util(), Type, ruleRe = /^required|optional|repeated$/;
    Field.fromJSON = function(name, json) {
      var field = new Field(name, json.id, json.type, json.rule, json.extend, json.options, json.comment);
      return json.edition && (field._edition = json.edition), field._defaultEdition = "proto3", field;
    };
    function Field(name, id, type, rule, extend, options, comment) {
      if (util.isObject(rule) ? (comment = extend, options = rule, rule = extend = void 0) : util.isObject(extend) && (comment = options, options = extend, extend = void 0), ReflectionObject.call(this, name, options), !util.isInteger(id) || id < 0)
        throw TypeError("id must be a non-negative integer");
      if (!util.isString(type))
        throw TypeError("type must be a string");
      if (rule !== void 0 && !ruleRe.test(rule = rule.toString().toLowerCase()))
        throw TypeError("rule must be a string rule");
      if (extend !== void 0 && !util.isString(extend))
        throw TypeError("extend must be a string");
      rule === "proto3_optional" && (rule = "optional"), this.rule = rule && rule !== "optional" ? rule : void 0, this.type = type, this.id = id, this.extend = extend || void 0, this.repeated = rule === "repeated", this.map = !1, this.message = null, this.partOf = null, this.typeDefault = null, this.defaultValue = null, this.long = util.Long ? types.long[type] !== void 0 : (
        /* istanbul ignore next */
        !1
      ), this.bytes = type === "bytes", this.resolvedType = null, this.extensionField = null, this.declaringField = null, this.comment = comment;
    }
    Object.defineProperty(Field.prototype, "required", {
      get: function() {
        return this._features.field_presence === "LEGACY_REQUIRED";
      }
    });
    Object.defineProperty(Field.prototype, "optional", {
      get: function() {
        return !this.required;
      }
    });
    Object.defineProperty(Field.prototype, "delimited", {
      get: function() {
        return this.resolvedType instanceof Type && this._features.message_encoding === "DELIMITED";
      }
    });
    Object.defineProperty(Field.prototype, "packed", {
      get: function() {
        return this._features.repeated_field_encoding === "PACKED";
      }
    });
    Object.defineProperty(Field.prototype, "hasPresence", {
      get: function() {
        return this.repeated || this.map ? !1 : this.partOf || // oneofs
        this.declaringField || this.extensionField || // extensions
        this._features.field_presence !== "IMPLICIT";
      }
    });
    Field.prototype.setOption = function(name, value, ifNotSet) {
      return ReflectionObject.prototype.setOption.call(this, name, value, ifNotSet);
    };
    Field.prototype.toJSON = function(toJSONOptions) {
      var keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "edition",
        this._editionToJSON(),
        "rule",
        this.rule !== "optional" && this.rule || void 0,
        "type",
        this.type,
        "id",
        this.id,
        "extend",
        this.extend,
        "options",
        this.options,
        "comment",
        keepComments ? this.comment : void 0
      ]);
    };
    Field.prototype.resolve = function() {
      if (this.resolved)
        return this;
      if ((this.typeDefault = types.defaults[this.type]) === void 0 ? (this.resolvedType = (this.declaringField ? this.declaringField.parent : this.parent).lookupTypeOrEnum(this.type), this.resolvedType instanceof Type ? this.typeDefault = null : this.typeDefault = this.resolvedType.values[Object.keys(this.resolvedType.values)[0]]) : this.options && this.options.proto3_optional && (this.typeDefault = null), this.options && this.options.default != null && (this.typeDefault = this.options.default, this.resolvedType instanceof Enum && typeof this.typeDefault == "string" && (this.typeDefault = this.resolvedType.values[this.typeDefault])), this.options && (this.options.packed !== void 0 && this.resolvedType && !(this.resolvedType instanceof Enum) && delete this.options.packed, Object.keys(this.options).length || (this.options = void 0)), this.long)
        this.typeDefault = util.Long.fromNumber(this.typeDefault, this.type.charAt(0) === "u"), Object.freeze && Object.freeze(this.typeDefault);
      else if (this.bytes && typeof this.typeDefault == "string") {
        var buf;
        util.base64.test(this.typeDefault) ? util.base64.decode(this.typeDefault, buf = util.newBuffer(util.base64.length(this.typeDefault)), 0) : util.utf8.write(this.typeDefault, buf = util.newBuffer(util.utf8.length(this.typeDefault)), 0), this.typeDefault = buf;
      }
      return this.map ? this.defaultValue = util.emptyObject : this.repeated ? this.defaultValue = util.emptyArray : this.defaultValue = this.typeDefault, this.parent instanceof Type && (this.parent.ctor.prototype[this.name] = this.defaultValue), ReflectionObject.prototype.resolve.call(this);
    };
    Field.prototype._inferLegacyProtoFeatures = function(edition) {
      if (edition !== "proto2" && edition !== "proto3")
        return {};
      var features = {};
      if (this.rule === "required" && (features.field_presence = "LEGACY_REQUIRED"), this.parent && types.defaults[this.type] === void 0) {
        var type = this.parent.get(this.type.split(".").pop());
        type && type instanceof Type && type.group && (features.message_encoding = "DELIMITED");
      }
      return this.getOption("packed") === !0 ? features.repeated_field_encoding = "PACKED" : this.getOption("packed") === !1 && (features.repeated_field_encoding = "EXPANDED"), features;
    };
    Field.prototype._resolveFeatures = function(edition) {
      return ReflectionObject.prototype._resolveFeatures.call(this, this._edition || edition);
    };
    Field.d = function(fieldId, fieldType, fieldRule, defaultValue) {
      return typeof fieldType == "function" ? fieldType = util.decorateType(fieldType).name : fieldType && typeof fieldType == "object" && (fieldType = util.decorateEnum(fieldType).name), function(prototype, fieldName) {
        util.decorateType(prototype.constructor).add(new Field(fieldName, fieldId, fieldType, fieldRule, { default: defaultValue }));
      };
    };
    Field._configure = function(Type_) {
      Type = Type_;
    };
  }
});

// node_modules/protobufjs/src/oneof.js
var require_oneof = __commonJS({
  "node_modules/protobufjs/src/oneof.js"(exports, module) {
    "use strict";
    module.exports = OneOf;
    var ReflectionObject = require_object();
    ((OneOf.prototype = Object.create(ReflectionObject.prototype)).constructor = OneOf).className = "OneOf";
    var Field = require_field(), util = require_util();
    function OneOf(name, fieldNames, options, comment) {
      if (Array.isArray(fieldNames) || (options = fieldNames, fieldNames = void 0), ReflectionObject.call(this, name, options), !(fieldNames === void 0 || Array.isArray(fieldNames)))
        throw TypeError("fieldNames must be an Array");
      this.oneof = fieldNames || [], this.fieldsArray = [], this.comment = comment;
    }
    OneOf.fromJSON = function(name, json) {
      return new OneOf(name, json.oneof, json.options, json.comment);
    };
    OneOf.prototype.toJSON = function(toJSONOptions) {
      var keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "options",
        this.options,
        "oneof",
        this.oneof,
        "comment",
        keepComments ? this.comment : void 0
      ]);
    };
    function addFieldsToParent(oneof) {
      if (oneof.parent)
        for (var i = 0; i < oneof.fieldsArray.length; ++i)
          oneof.fieldsArray[i].parent || oneof.parent.add(oneof.fieldsArray[i]);
    }
    OneOf.prototype.add = function(field) {
      if (!(field instanceof Field))
        throw TypeError("field must be a Field");
      return field.parent && field.parent !== this.parent && field.parent.remove(field), this.oneof.push(field.name), this.fieldsArray.push(field), field.partOf = this, addFieldsToParent(this), this;
    };
    OneOf.prototype.remove = function(field) {
      if (!(field instanceof Field))
        throw TypeError("field must be a Field");
      var index = this.fieldsArray.indexOf(field);
      if (index < 0)
        throw Error(field + " is not a member of " + this);
      return this.fieldsArray.splice(index, 1), index = this.oneof.indexOf(field.name), index > -1 && this.oneof.splice(index, 1), field.partOf = null, this;
    };
    OneOf.prototype.onAdd = function(parent) {
      ReflectionObject.prototype.onAdd.call(this, parent);
      for (var self2 = this, i = 0; i < this.oneof.length; ++i) {
        var field = parent.get(this.oneof[i]);
        field && !field.partOf && (field.partOf = self2, self2.fieldsArray.push(field));
      }
      addFieldsToParent(this);
    };
    OneOf.prototype.onRemove = function(parent) {
      for (var i = 0, field; i < this.fieldsArray.length; ++i)
        (field = this.fieldsArray[i]).parent && field.parent.remove(field);
      ReflectionObject.prototype.onRemove.call(this, parent);
    };
    Object.defineProperty(OneOf.prototype, "isProto3Optional", {
      get: function() {
        if (this.fieldsArray == null || this.fieldsArray.length !== 1)
          return !1;
        var field = this.fieldsArray[0];
        return field.options != null && field.options.proto3_optional === !0;
      }
    });
    OneOf.d = function() {
      for (var fieldNames = new Array(arguments.length), index = 0; index < arguments.length; )
        fieldNames[index] = arguments[index++];
      return function(prototype, oneofName) {
        util.decorateType(prototype.constructor).add(new OneOf(oneofName, fieldNames)), Object.defineProperty(prototype, oneofName, {
          get: util.oneOfGetter(fieldNames),
          set: util.oneOfSetter(fieldNames)
        });
      };
    };
  }
});

// node_modules/protobufjs/src/object.js
var require_object = __commonJS({
  "node_modules/protobufjs/src/object.js"(exports, module) {
    "use strict";
    module.exports = ReflectionObject;
    ReflectionObject.className = "ReflectionObject";
    var OneOf = require_oneof(), util = require_util(), Root, editions2023Defaults = { enum_type: "OPEN", field_presence: "EXPLICIT", json_format: "ALLOW", message_encoding: "LENGTH_PREFIXED", repeated_field_encoding: "PACKED", utf8_validation: "VERIFY" }, proto2Defaults = { enum_type: "CLOSED", field_presence: "EXPLICIT", json_format: "LEGACY_BEST_EFFORT", message_encoding: "LENGTH_PREFIXED", repeated_field_encoding: "EXPANDED", utf8_validation: "NONE" }, proto3Defaults = { enum_type: "OPEN", field_presence: "IMPLICIT", json_format: "ALLOW", message_encoding: "LENGTH_PREFIXED", repeated_field_encoding: "PACKED", utf8_validation: "VERIFY" };
    function ReflectionObject(name, options) {
      if (!util.isString(name))
        throw TypeError("name must be a string");
      if (options && !util.isObject(options))
        throw TypeError("options must be an object");
      this.options = options, this.parsedOptions = null, this.name = name, this._edition = null, this._defaultEdition = "proto2", this._features = {}, this._featuresResolved = !1, this.parent = null, this.resolved = !1, this.comment = null, this.filename = null;
    }
    Object.defineProperties(ReflectionObject.prototype, {
      /**
       * Reference to the root namespace.
       * @name ReflectionObject#root
       * @type {Root}
       * @readonly
       */
      root: {
        get: function() {
          for (var ptr = this; ptr.parent !== null; )
            ptr = ptr.parent;
          return ptr;
        }
      },
      /**
       * Full name including leading dot.
       * @name ReflectionObject#fullName
       * @type {string}
       * @readonly
       */
      fullName: {
        get: function() {
          for (var path = [this.name], ptr = this.parent; ptr; )
            path.unshift(ptr.name), ptr = ptr.parent;
          return path.join(".");
        }
      }
    });
    ReflectionObject.prototype.toJSON = /* istanbul ignore next */
    function() {
      throw Error();
    };
    ReflectionObject.prototype.onAdd = function(parent) {
      this.parent && this.parent !== parent && this.parent.remove(this), this.parent = parent, this.resolved = !1;
      var root = parent.root;
      root instanceof Root && root._handleAdd(this);
    };
    ReflectionObject.prototype.onRemove = function(parent) {
      var root = parent.root;
      root instanceof Root && root._handleRemove(this), this.parent = null, this.resolved = !1;
    };
    ReflectionObject.prototype.resolve = function() {
      return this.resolved ? this : (this.root instanceof Root && (this.resolved = !0), this);
    };
    ReflectionObject.prototype._resolveFeaturesRecursive = function(edition) {
      return this._resolveFeatures(this._edition || edition);
    };
    ReflectionObject.prototype._resolveFeatures = function(edition) {
      if (!this._featuresResolved) {
        var defaults = {};
        if (!edition)
          throw new Error("Unknown edition for " + this.fullName);
        var protoFeatures = Object.assign(
          this.options ? Object.assign({}, this.options.features) : {},
          this._inferLegacyProtoFeatures(edition)
        );
        if (this._edition) {
          if (edition === "proto2")
            defaults = Object.assign({}, proto2Defaults);
          else if (edition === "proto3")
            defaults = Object.assign({}, proto3Defaults);
          else if (edition === "2023")
            defaults = Object.assign({}, editions2023Defaults);
          else
            throw new Error("Unknown edition: " + edition);
          this._features = Object.assign(defaults, protoFeatures || {}), this._featuresResolved = !0;
          return;
        }
        if (this.partOf instanceof OneOf) {
          var lexicalParentFeaturesCopy = Object.assign({}, this.partOf._features);
          this._features = Object.assign(lexicalParentFeaturesCopy, protoFeatures || {});
        } else if (!this.declaringField)
          if (this.parent) {
            var parentFeaturesCopy = Object.assign({}, this.parent._features);
            this._features = Object.assign(parentFeaturesCopy, protoFeatures || {});
          } else
            throw new Error("Unable to find a parent for " + this.fullName);
        this.extensionField && (this.extensionField._features = this._features), this._featuresResolved = !0;
      }
    };
    ReflectionObject.prototype._inferLegacyProtoFeatures = function() {
      return {};
    };
    ReflectionObject.prototype.getOption = function(name) {
      if (this.options)
        return this.options[name];
    };
    ReflectionObject.prototype.setOption = function(name, value, ifNotSet) {
      return name === "__proto__" ? this : (this.options || (this.options = {}), /^features\./.test(name) ? util.setProperty(this.options, name, value, ifNotSet) : (!ifNotSet || this.options[name] === void 0) && (this.getOption(name) !== value && (this.resolved = !1), this.options[name] = value), this);
    };
    ReflectionObject.prototype.setParsedOption = function(name, value, propName) {
      if (name === "__proto__")
        return this;
      this.parsedOptions || (this.parsedOptions = []);
      var parsedOptions = this.parsedOptions;
      if (propName) {
        var opt = parsedOptions.find(function(opt2) {
          return Object.prototype.hasOwnProperty.call(opt2, name);
        });
        if (opt) {
          var newValue = opt[name];
          util.setProperty(newValue, propName, value);
        } else
          opt = {}, opt[name] = util.setProperty({}, propName, value), parsedOptions.push(opt);
      } else {
        var newOpt = {};
        newOpt[name] = value, parsedOptions.push(newOpt);
      }
      return this;
    };
    ReflectionObject.prototype.setOptions = function(options, ifNotSet) {
      if (options)
        for (var keys = Object.keys(options), i = 0; i < keys.length; ++i)
          this.setOption(keys[i], options[keys[i]], ifNotSet);
      return this;
    };
    ReflectionObject.prototype.toString = function() {
      var className = this.constructor.className, fullName = this.fullName;
      return fullName.length ? className + " " + fullName : className;
    };
    ReflectionObject.prototype._editionToJSON = function() {
      if (!(!this._edition || this._edition === "proto3"))
        return this._edition;
    };
    ReflectionObject._configure = function(Root_) {
      Root = Root_;
    };
  }
});

// node_modules/protobufjs/src/enum.js
var require_enum = __commonJS({
  "node_modules/protobufjs/src/enum.js"(exports, module) {
    "use strict";
    module.exports = Enum;
    var ReflectionObject = require_object();
    ((Enum.prototype = Object.create(ReflectionObject.prototype)).constructor = Enum).className = "Enum";
    var Namespace = require_namespace(), util = require_util();
    function Enum(name, values, options, comment, comments, valuesOptions) {
      if (ReflectionObject.call(this, name, options), values && typeof values != "object")
        throw TypeError("values must be an object");
      if (this.valuesById = {}, this.values = Object.create(this.valuesById), this.comment = comment, this.comments = comments || {}, this.valuesOptions = valuesOptions, this._valuesFeatures = {}, this.reserved = void 0, values)
        for (var keys = Object.keys(values), i = 0; i < keys.length; ++i)
          keys[i] !== "__proto__" && typeof values[keys[i]] == "number" && (this.valuesById[this.values[keys[i]] = values[keys[i]]] = keys[i]);
    }
    Enum.prototype._resolveFeatures = function(edition) {
      return edition = this._edition || edition, ReflectionObject.prototype._resolveFeatures.call(this, edition), Object.keys(this.values).forEach((key) => {
        var parentFeaturesCopy = Object.assign({}, this._features);
        this._valuesFeatures[key] = Object.assign(parentFeaturesCopy, this.valuesOptions && this.valuesOptions[key] && this.valuesOptions[key].features);
      }), this;
    };
    Enum.fromJSON = function(name, json) {
      var enm = new Enum(name, json.values, json.options, json.comment, json.comments);
      return enm.reserved = json.reserved, json.edition && (enm._edition = json.edition), enm._defaultEdition = "proto3", enm;
    };
    Enum.prototype.toJSON = function(toJSONOptions) {
      var keepComments = toJSONOptions ? !!toJSONOptions.keepComments : !1;
      return util.toObject([
        "edition",
        this._editionToJSON(),
        "options",
        this.options,
        "valuesOptions",
        this.valuesOptions,
        "values",
        this.values,
        "reserved",
        this.reserved && this.reserved.length ? this.reserved : void 0,
        "comment",
        keepComments ? this.comment : void 0,
        "comments",
        keepComments ? this.comments : void 0
      ]);
    };
    Enum.prototype.add = function(name, id, comment, options) {
      if (!util.isString(name))
        throw TypeError("name must be a string");
      if (!util.isInteger(id))
        throw TypeError("id must be an integer");
      if (name === "__proto__")
        return this;
      if (this.values[name] !== void 0)
        throw Error("duplicate name '" + name + "' in " + this);
      if (this.isReservedId(id))
        throw Error("id " + id + " is reserved in " + this);
      if (this.isReservedName(name))
        throw Error("name '" + name + "' is reserved in " + this);
      if (this.valuesById[id] !== void 0) {
        if (!(this.options && this.options.allow_alias))
          throw Error("duplicate id " + id + " in " + this);
        this.values[name] = id;
      } else
        this.valuesById[this.values[name] = id] = name;
      return options && (this.valuesOptions === void 0 && (this.valuesOptions = {}), this.valuesOptions[name] = options || null), this.comments[name] = comment || null, this;
    };
    Enum.prototype.remove = function(name) {
      if (!util.isString(name))
        throw TypeError("name must be a string");
      var val = this.values[name];
      if (val == null)
        throw Error("name '" + name + "' does not exist in " + this);
      return delete this.valuesById[val], delete this.values[name], delete this.comments[name], this.valuesOptions && delete this.valuesOptions[name], this;
    };
    Enum.prototype.isReservedId = function(id) {
      return Namespace.isReservedId(this.reserved, id);
    };
    Enum.prototype.isReservedName = function(name) {
      return Namespace.isReservedName(this.reserved, name);
    };
  }
});

// node_modules/protobufjs/src/encoder.js
var require_encoder = __commonJS({
  "node_modules/protobufjs/src/encoder.js"(exports, module) {
    "use strict";
    module.exports = encoder;
    var Enum = require_enum(), types = require_types(), util = require_util();
    function genTypePartial(gen, field, fieldIndex, ref) {
      return field.delimited ? gen("types[%i].encode(%s,w.uint32(%i)).uint32(%i)", fieldIndex, ref, (field.id << 3 | 3) >>> 0, (field.id << 3 | 4) >>> 0) : gen("types[%i].encode(%s,w.uint32(%i).fork()).ldelim()", fieldIndex, ref, (field.id << 3 | 2) >>> 0);
    }
    function encoder(mtype) {
      for (var gen = util.codegen(["m", "w"], mtype.name + "$encode")("if(!w)")("w=Writer.create()"), i, ref, fields = (
        /* initializes */
        mtype.fieldsArray.slice().sort(util.compareFieldsById)
      ), i = 0; i < fields.length; ++i) {
        var field = fields[i].resolve(), index = mtype._fieldsArray.indexOf(field), type = field.resolvedType instanceof Enum ? "int32" : field.type, wireType = types.basic[type];
        ref = "m" + util.safeProp(field.name), field.map ? (gen("if(%s!=null&&Object.hasOwnProperty.call(m,%j)){", ref, field.name)("for(var ks=Object.keys(%s),i=0;i<ks.length;++i){", ref)("w.uint32(%i).fork().uint32(%i).%s(ks[i])", (field.id << 3 | 2) >>> 0, 8 | types.mapKey[field.keyType], field.keyType), wireType === void 0 ? gen("types[%i].encode(%s[ks[i]],w.uint32(18).fork()).ldelim().ldelim()", index, ref) : gen(".uint32(%i).%s(%s[ks[i]]).ldelim()", 16 | wireType, type, ref), gen("}")("}")) : field.repeated ? (gen("if(%s!=null&&%s.length){", ref, ref), field.packed && types.packed[type] !== void 0 ? gen("w.uint32(%i).fork()", (field.id << 3 | 2) >>> 0)("for(var i=0;i<%s.length;++i)", ref)("w.%s(%s[i])", type, ref)("w.ldelim()") : (gen("for(var i=0;i<%s.length;++i)", ref), wireType === void 0 ? genTypePartial(gen, field, index, ref + "[i]") : gen("w.uint32(%i).%s(%s[i])", (field.id << 3 | wireType) >>> 0, type, ref)), gen("}")) : (field.optional && gen("if(%s!=null&&Object.hasOwnProperty.call(m,%j))", ref, field.name), wireType === void 0 ? genTypePartial(gen, field, index, ref) : gen("w.uint32(%i).%s(%s)", (field.id << 3 | wireType) >>> 0, type, ref));
      }
      return gen("return w");
    }
  }
});

// node_modules/protobufjs/src/index-light.js
var require_index_light = __commonJS({
  "node_modules/protobufjs/src/index-light.js"(exports, module) {
    "use strict";
    var protobuf = module.exports = require_index_minimal();
    protobuf.build = "light";
    function load(filename, root, callback) {
      return typeof root == "function" ? (callback = root, root = new protobuf.Root()) : root || (root = new protobuf.Root()), root.load(filename, callback);
    }
    protobuf.load = load;
    function loadSync(filename, root) {
      return root || (root = new protobuf.Root()), root.loadSync(filename);
    }
    protobuf.loadSync = loadSync;
    protobuf.encoder = require_encoder();
    protobuf.decoder = require_decoder();
    protobuf.verifier = require_verifier();
    protobuf.converter = require_converter();
    protobuf.ReflectionObject = require_object();
    protobuf.Namespace = require_namespace();
    protobuf.Root = require_root();
    protobuf.Enum = require_enum();
    protobuf.Type = require_type();
    protobuf.Field = require_field();
    protobuf.OneOf = require_oneof();
    protobuf.MapField = require_mapfield();
    protobuf.Service = require_service2();
    protobuf.Method = require_method();
    protobuf.Message = require_message();
    protobuf.wrappers = require_wrappers();
    protobuf.types = require_types();
    protobuf.util = require_util();
    protobuf.ReflectionObject._configure(protobuf.Root);
    protobuf.Namespace._configure(protobuf.Type, protobuf.Service, protobuf.Enum);
    protobuf.Root._configure(protobuf.Type);
    protobuf.Field._configure(protobuf.Type);
  }
});

// node_modules/protobufjs/src/tokenize.js
var require_tokenize = __commonJS({
  "node_modules/protobufjs/src/tokenize.js"(exports, module) {
    "use strict";
    module.exports = tokenize;
    var delimRe = /[\s{}=;:[\],'"()<>]/g, stringDoubleRe = /(?:"([^"\\]*(?:\\.[^"\\]*)*)")/g, stringSingleRe = /(?:'([^'\\]*(?:\\.[^'\\]*)*)')/g, setCommentRe = /^ *[*/]+ */, setCommentAltRe = /^\s*\*?\/*/, setCommentSplitRe = /\n/g, whitespaceRe = /\s/, unescapeRe = /\\(.?)/g, unescapeMap = {
      0: "\0",
      r: "\r",
      n: `
`,
      t: "	"
    };
    function unescape(str) {
      return str.replace(unescapeRe, function($0, $1) {
        switch ($1) {
          case "\\":
          case "":
            return $1;
          default:
            return unescapeMap[$1] || "";
        }
      });
    }
    tokenize.unescape = unescape;
    function tokenize(source, alternateCommentMode) {
      source = source.toString();
      var offset = 0, length = source.length, line = 1, lastCommentLine = 0, comments = {}, stack = [], stringDelim = null;
      function illegal(subject) {
        return Error("illegal " + subject + " (line " + line + ")");
      }
      function readString() {
        var re = stringDelim === "'" ? stringSingleRe : stringDoubleRe;
        re.lastIndex = offset - 1;
        var match = re.exec(source);
        if (!match)
          throw illegal("string");
        return offset = re.lastIndex, push(stringDelim), stringDelim = null, unescape(match[1]);
      }
      function charAt(pos) {
        return source.charAt(pos);
      }
      function setComment(start, end, isLeading) {
        var comment = {
          type: source.charAt(start++),
          lineEmpty: !1,
          leading: isLeading
        }, lookback;
        alternateCommentMode ? lookback = 2 : lookback = 3;
        var commentOffset = start - lookback, c;
        do
          if (--commentOffset < 0 || (c = source.charAt(commentOffset)) === `
`) {
            comment.lineEmpty = !0;
            break;
          }
        while (c === " " || c === "	");
        for (var lines = source.substring(start, end).split(setCommentSplitRe), i = 0; i < lines.length; ++i)
          lines[i] = lines[i].replace(alternateCommentMode ? setCommentAltRe : setCommentRe, "").trim();
        comment.text = lines.join(`
`).trim(), comments[line] = comment, lastCommentLine = line;
      }
      function isDoubleSlashCommentLine(startOffset) {
        var endOffset = findEndOfLine(startOffset), lineText = source.substring(startOffset, endOffset), isComment = /^\s*\/\//.test(lineText);
        return isComment;
      }
      function findEndOfLine(cursor) {
        for (var endOffset = cursor; endOffset < length && charAt(endOffset) !== `
`; )
          endOffset++;
        return endOffset;
      }
      function next() {
        if (stack.length > 0)
          return stack.shift();
        if (stringDelim)
          return readString();
        var repeat, prev, curr, start, isDoc, isLeadingComment = offset === 0;
        do {
          if (offset === length)
            return null;
          for (repeat = !1; whitespaceRe.test(curr = charAt(offset)); )
            if (curr === `
` && (isLeadingComment = !0, ++line), ++offset === length)
              return null;
          if (charAt(offset) === "/") {
            if (++offset === length)
              throw illegal("comment");
            if (charAt(offset) === "/")
              if (alternateCommentMode) {
                if (start = offset, isDoc = !1, isDoubleSlashCommentLine(offset - 1)) {
                  isDoc = !0;
                  do
                    if (offset = findEndOfLine(offset), offset === length || (offset++, !isLeadingComment))
                      break;
                  while (isDoubleSlashCommentLine(offset));
                } else
                  offset = Math.min(length, findEndOfLine(offset) + 1);
                isDoc && (setComment(start, offset, isLeadingComment), isLeadingComment = !0), line++, repeat = !0;
              } else {
                for (isDoc = charAt(start = offset + 1) === "/"; charAt(++offset) !== `
`; )
                  if (offset === length)
                    return null;
                ++offset, isDoc && (setComment(start, offset - 1, isLeadingComment), isLeadingComment = !0), ++line, repeat = !0;
              }
            else if ((curr = charAt(offset)) === "*") {
              start = offset + 1, isDoc = alternateCommentMode || charAt(start) === "*";
              do {
                if (curr === `
` && ++line, ++offset === length)
                  throw illegal("comment");
                prev = curr, curr = charAt(offset);
              } while (prev !== "*" || curr !== "/");
              ++offset, isDoc && (setComment(start, offset - 2, isLeadingComment), isLeadingComment = !0), repeat = !0;
            } else
              return "/";
          }
        } while (repeat);
        var end = offset;
        delimRe.lastIndex = 0;
        var delim = delimRe.test(charAt(end++));
        if (!delim)
          for (; end < length && !delimRe.test(charAt(end)); )
            ++end;
        var token = source.substring(offset, offset = end);
        return (token === '"' || token === "'") && (stringDelim = token), token;
      }
      function push(token) {
        stack.push(token);
      }
      function peek() {
        if (!stack.length) {
          var token = next();
          if (token === null)
            return null;
          push(token);
        }
        return stack[0];
      }
      function skip(expected, optional) {
        var actual = peek(), equals = actual === expected;
        if (equals)
          return next(), !0;
        if (!optional)
          throw illegal("token '" + actual + "', '" + expected + "' expected");
        return !1;
      }
      function cmnt(trailingLine) {
        var ret = null, comment;
        return trailingLine === void 0 ? (comment = comments[line - 1], delete comments[line - 1], comment && (alternateCommentMode || comment.type === "*" || comment.lineEmpty) && (ret = comment.leading ? comment.text : null)) : (lastCommentLine < trailingLine && peek(), comment = comments[trailingLine], delete comments[trailingLine], comment && !comment.lineEmpty && (alternateCommentMode || comment.type === "/") && (ret = comment.leading ? null : comment.text)), ret;
      }
      return Object.defineProperty({
        next,
        peek,
        push,
        skip,
        cmnt
      }, "line", {
        get: function() {
          return line;
        }
      });
    }
  }
});

// node_modules/protobufjs/src/parse.js
var require_parse = __commonJS({
  "node_modules/protobufjs/src/parse.js"(exports, module) {
    "use strict";
    module.exports = parse2;
    parse2.filename = null;
    parse2.defaults = { keepCase: !1 };
    var tokenize = require_tokenize(), Root = require_root(), Type = require_type(), Field = require_field(), MapField = require_mapfield(), OneOf = require_oneof(), Enum = require_enum(), Service = require_service2(), Method = require_method(), ReflectionObject = require_object(), types = require_types(), util = require_util(), base10Re = /^[1-9][0-9]*$/, base10NegRe = /^-?[1-9][0-9]*$/, base16Re = /^0[x][0-9a-fA-F]+$/, base16NegRe = /^-?0[x][0-9a-fA-F]+$/, base8Re = /^0[0-7]+$/, base8NegRe = /^-?0[0-7]+$/, numberRe = util.patterns.numberRe, nameRe = /^[a-zA-Z_][a-zA-Z_0-9]*$/, typeRefRe = util.patterns.typeRefRe;
    function parse2(source, root, options) {
      root instanceof Root || (options = root, root = new Root()), options || (options = parse2.defaults);
      var preferTrailingComment = options.preferTrailingComment || !1, tn = tokenize(source, options.alternateCommentMode || !1), next = tn.next, push = tn.push, peek = tn.peek, skip = tn.skip, cmnt = tn.cmnt, head = !0, pkg, imports, weakImports, edition = "proto2", ptr = root, topLevelObjects = [], topLevelOptions = {}, applyCase = options.keepCase ? function(name) {
        return name;
      } : util.camelCase;
      function resolveFileFeatures() {
        topLevelObjects.forEach((obj) => {
          obj._edition = edition, Object.keys(topLevelOptions).forEach((opt) => {
            obj.getOption(opt) === void 0 && obj.setOption(opt, topLevelOptions[opt], !0);
          });
        });
      }
      function illegal(token2, name, insideTryCatch) {
        var filename = parse2.filename;
        return insideTryCatch || (parse2.filename = null), Error("illegal " + (name || "token") + " '" + token2 + "' (" + (filename ? filename + ", " : "") + "line " + tn.line + ")");
      }
      function readString() {
        var values = [], token2;
        do {
          if ((token2 = next()) !== '"' && token2 !== "'")
            throw illegal(token2);
          values.push(next()), skip(token2), token2 = peek();
        } while (token2 === '"' || token2 === "'");
        return values.join("");
      }
      function readValue(acceptTypeRef) {
        var token2 = next();
        switch (token2) {
          case "'":
          case '"':
            return push(token2), readString();
          case "true":
          case "TRUE":
            return !0;
          case "false":
          case "FALSE":
            return !1;
        }
        try {
          return parseNumber(
            token2,
            /* insideTryCatch */
            !0
          );
        } catch {
          if (acceptTypeRef && typeRefRe.test(token2))
            return token2;
          throw illegal(token2, "value");
        }
      }
      function readRanges(target, acceptStrings) {
        var token2, start;
        do
          if (acceptStrings && ((token2 = peek()) === '"' || token2 === "'")) {
            var str = readString();
            if (target.push(str), edition >= 2023)
              throw illegal(str, "id");
          } else
            try {
              target.push([start = parseId(next()), skip("to", !0) ? parseId(next()) : start]);
            } catch (err) {
              if (acceptStrings && typeRefRe.test(token2) && edition >= 2023)
                target.push(token2);
              else
                throw err;
            }
        while (skip(",", !0));
        var dummy = { options: void 0 };
        dummy.setOption = function(name, value) {
          this.options === void 0 && (this.options = {}), this.options[name] = value;
        }, ifBlock(
          dummy,
          function(token3) {
            if (token3 === "option")
              parseOption(dummy, token3), skip(";");
            else
              throw illegal(token3);
          },
          function() {
            parseInlineOptions(dummy);
          }
        );
      }
      function parseNumber(token2, insideTryCatch) {
        var sign = 1;
        switch (token2.charAt(0) === "-" && (sign = -1, token2 = token2.substring(1)), token2) {
          case "inf":
          case "INF":
          case "Inf":
            return sign * (1 / 0);
          case "nan":
          case "NAN":
          case "Nan":
          case "NaN":
            return NaN;
          case "0":
            return 0;
        }
        if (base10Re.test(token2))
          return sign * parseInt(token2, 10);
        if (base16Re.test(token2))
          return sign * parseInt(token2, 16);
        if (base8Re.test(token2))
          return sign * parseInt(token2, 8);
        if (numberRe.test(token2))
          return sign * parseFloat(token2);
        throw illegal(token2, "number", insideTryCatch);
      }
      function parseId(token2, acceptNegative) {
        switch (token2) {
          case "max":
          case "MAX":
          case "Max":
            return 536870911;
          case "0":
            return 0;
        }
        if (!acceptNegative && token2.charAt(0) === "-")
          throw illegal(token2, "id");
        if (base10NegRe.test(token2))
          return parseInt(token2, 10);
        if (base16NegRe.test(token2))
          return parseInt(token2, 16);
        if (base8NegRe.test(token2))
          return parseInt(token2, 8);
        throw illegal(token2, "id");
      }
      function parsePackage() {
        if (pkg !== void 0)
          throw illegal("package");
        if (pkg = next(), !typeRefRe.test(pkg))
          throw illegal(pkg, "name");
        ptr = ptr.define(pkg), skip(";");
      }
      function parseImport() {
        var token2 = peek(), whichImports;
        switch (token2) {
          case "weak":
            whichImports = weakImports || (weakImports = []), next();
            break;
          case "public":
            next();
          // eslint-disable-next-line no-fallthrough
          default:
            whichImports = imports || (imports = []);
            break;
        }
        token2 = readString(), skip(";"), whichImports.push(token2);
      }
      function parseSyntax() {
        if (skip("="), edition = readString(), edition < 2023)
          throw illegal(edition, "syntax");
        skip(";");
      }
      function parseEdition() {
        if (skip("="), edition = readString(), !["2023"].includes(edition))
          throw illegal(edition, "edition");
        skip(";");
      }
      function parseCommon(parent, token2, depth) {
        switch (depth = util.checkDepth(depth), token2) {
          case "option":
            return parseOption(parent, token2), skip(";"), !0;
          case "message":
            return parseType(parent, token2, depth + 1), !0;
          case "enum":
            return parseEnum(parent, token2), !0;
          case "service":
            return parseService(parent, token2, depth + 1), !0;
          case "extend":
            return parseExtension(parent, token2, depth), !0;
        }
        return !1;
      }
      function ifBlock(obj, fnIf, fnElse) {
        var trailingLine = tn.line;
        if (obj && (typeof obj.comment != "string" && (obj.comment = cmnt()), obj.filename = parse2.filename), skip("{", !0)) {
          for (var token2; (token2 = next()) !== "}"; )
            fnIf(token2);
          skip(";", !0);
        } else
          fnElse && fnElse(), skip(";"), obj && (typeof obj.comment != "string" || preferTrailingComment) && (obj.comment = cmnt(trailingLine) || obj.comment);
      }
      function parseType(parent, token2, depth) {
        if (depth = util.checkDepth(depth), !nameRe.test(token2 = next()))
          throw illegal(token2, "type name");
        var type = new Type(token2);
        ifBlock(type, function(token3) {
          if (!parseCommon(type, token3, depth))
            switch (token3) {
              case "map":
                parseMapField(type, token3);
                break;
              case "required":
                if (edition !== "proto2")
                  throw illegal(token3);
              /* eslint-disable no-fallthrough */
              case "repeated":
                parseField(type, token3, void 0, depth + 1);
                break;
              case "optional":
                if (edition === "proto3")
                  parseField(type, "proto3_optional", void 0, depth + 1);
                else {
                  if (edition !== "proto2")
                    throw illegal(token3);
                  parseField(type, "optional", void 0, depth + 1);
                }
                break;
              case "oneof":
                parseOneOf(type, token3, depth + 1);
                break;
              case "extensions":
                readRanges(type.extensions || (type.extensions = []));
                break;
              case "reserved":
                readRanges(type.reserved || (type.reserved = []), !0);
                break;
              default:
                if (edition === "proto2" || !typeRefRe.test(token3))
                  throw illegal(token3);
                push(token3), parseField(type, "optional", void 0, depth + 1);
                break;
            }
        }), parent.add(type), parent === ptr && topLevelObjects.push(type);
      }
      function parseField(parent, rule, extend, depth) {
        var type = next();
        if (type === "group") {
          parseGroup(parent, rule, depth);
          return;
        }
        for (; type.endsWith(".") || peek().startsWith("."); )
          type += next();
        if (!typeRefRe.test(type))
          throw illegal(type, "type");
        var name = next();
        if (!nameRe.test(name))
          throw illegal(name, "name");
        name = applyCase(name), skip("=");
        var field = new Field(name, parseId(next()), type, rule, extend);
        if (ifBlock(field, function(token2) {
          if (token2 === "option")
            parseOption(field, token2), skip(";");
          else
            throw illegal(token2);
        }, function() {
          parseInlineOptions(field);
        }), rule === "proto3_optional") {
          var oneof = new OneOf("_" + name);
          field.setOption("proto3_optional", !0), oneof.add(field), parent.add(oneof);
        } else
          parent.add(field);
        parent === ptr && topLevelObjects.push(field);
      }
      function parseGroup(parent, rule, depth) {
        if (depth = util.checkDepth(depth), edition >= 2023)
          throw illegal("group");
        var name = next();
        if (!nameRe.test(name))
          throw illegal(name, "name");
        var fieldName = util.lcFirst(name);
        name === fieldName && (name = util.ucFirst(name)), skip("=");
        var id = parseId(next()), type = new Type(name);
        type.group = !0;
        var field = new Field(fieldName, id, name, rule);
        field.filename = parse2.filename, ifBlock(type, function(token2) {
          switch (token2) {
            case "option":
              parseOption(type, token2), skip(";");
              break;
            case "required":
            case "repeated":
              parseField(type, token2, void 0, depth + 1);
              break;
            case "optional":
              edition === "proto3" ? parseField(type, "proto3_optional", void 0, depth + 1) : parseField(type, "optional", void 0, depth + 1);
              break;
            case "message":
              parseType(type, token2, depth + 1);
              break;
            case "enum":
              parseEnum(type, token2);
              break;
            case "reserved":
              readRanges(type.reserved || (type.reserved = []), !0);
              break;
            /* istanbul ignore next */
            default:
              throw illegal(token2);
          }
        }), parent.add(type).add(field);
      }
      function parseMapField(parent) {
        skip("<");
        var keyType = next();
        if (types.mapKey[keyType] === void 0)
          throw illegal(keyType, "type");
        skip(",");
        var valueType = next();
        if (!typeRefRe.test(valueType))
          throw illegal(valueType, "type");
        skip(">");
        var name = next();
        if (!nameRe.test(name))
          throw illegal(name, "name");
        skip("=");
        var field = new MapField(applyCase(name), parseId(next()), keyType, valueType);
        ifBlock(field, function(token2) {
          if (token2 === "option")
            parseOption(field, token2), skip(";");
          else
            throw illegal(token2);
        }, function() {
          parseInlineOptions(field);
        }), parent.add(field);
      }
      function parseOneOf(parent, token2, depth) {
        if (!nameRe.test(token2 = next()))
          throw illegal(token2, "name");
        var oneof = new OneOf(applyCase(token2));
        ifBlock(oneof, function(token3) {
          token3 === "option" ? (parseOption(oneof, token3), skip(";")) : (push(token3), parseField(oneof, "optional", void 0, depth));
        }), parent.add(oneof);
      }
      function parseEnum(parent, token2) {
        if (!nameRe.test(token2 = next()))
          throw illegal(token2, "name");
        var enm = new Enum(token2);
        ifBlock(enm, function(token3) {
          switch (token3) {
            case "option":
              parseOption(enm, token3), skip(";");
              break;
            case "reserved":
              readRanges(enm.reserved || (enm.reserved = []), !0), enm.reserved === void 0 && (enm.reserved = []);
              break;
            default:
              parseEnumValue(enm, token3);
          }
        }), parent.add(enm), parent === ptr && topLevelObjects.push(enm);
      }
      function parseEnumValue(parent, token2) {
        if (!nameRe.test(token2))
          throw illegal(token2, "name");
        skip("=");
        var value = parseId(next(), !0), dummy = {
          options: void 0
        };
        dummy.getOption = function(name) {
          return this.options[name];
        }, dummy.setOption = function(name, value2) {
          ReflectionObject.prototype.setOption.call(dummy, name, value2);
        }, dummy.setParsedOption = function() {
        }, ifBlock(dummy, function(token3) {
          if (token3 === "option")
            parseOption(dummy, token3), skip(";");
          else
            throw illegal(token3);
        }, function() {
          parseInlineOptions(dummy);
        }), parent.add(token2, value, dummy.comment, dummy.parsedOptions || dummy.options);
      }
      function parseOption(parent, token2) {
        var option, propName, isOption = !0;
        for (token2 === "option" && (token2 = next()); token2 !== "="; ) {
          if (token2 === "(") {
            var parensValue = next();
            skip(")"), token2 = "(" + parensValue + ")";
          }
          if (isOption) {
            if (isOption = !1, token2.includes(".") && !token2.includes("(")) {
              var tokens = token2.split(".");
              option = tokens[0] + ".", token2 = tokens[1];
              continue;
            }
            option = token2;
          } else
            propName = propName ? propName += token2 : token2;
          token2 = next();
        }
        var name = propName ? option.concat(propName) : option, optionValue = parseOptionValue(parent, name);
        propName = propName && propName[0] === "." ? propName.slice(1) : propName, option = option && option[option.length - 1] === "." ? option.slice(0, -1) : option, setParsedOption(parent, option, optionValue, propName);
      }
      function parseOptionValue(parent, name, depth) {
        if (depth = util.checkDepth(depth), skip("{", !0)) {
          for (var objectResult = {}; !skip("}", !0); ) {
            if (!nameRe.test(token = next()))
              throw illegal(token, "name");
            if (token === null)
              throw illegal(token, "end of input");
            var value, propName = token;
            if (skip(":", !0), peek() === "{")
              value = parseOptionValue(parent, name + "." + token, depth + 1);
            else if (peek() === "[") {
              value = [];
              var lastValue;
              if (skip("[", !0)) {
                do
                  lastValue = readValue(!0), value.push(lastValue);
                while (skip(",", !0));
                skip("]"), typeof lastValue < "u" && setOption(parent, name + "." + token, lastValue);
              }
            } else
              value = readValue(!0), setOption(parent, name + "." + token, value);
            var prevValue = objectResult[propName];
            prevValue && (value = [].concat(prevValue).concat(value)), propName !== "__proto__" && (objectResult[propName] = value), skip(",", !0), skip(";", !0);
          }
          return objectResult;
        }
        var simpleValue = readValue(!0);
        return setOption(parent, name, simpleValue), simpleValue;
      }
      function setOption(parent, name, value) {
        if (ptr === parent && /^features\./.test(name)) {
          topLevelOptions[name] = value;
          return;
        }
        parent.setOption && parent.setOption(name, value);
      }
      function setParsedOption(parent, name, value, propName) {
        parent.setParsedOption && parent.setParsedOption(name, value, propName);
      }
      function parseInlineOptions(parent) {
        if (skip("[", !0)) {
          do
            parseOption(parent, "option");
          while (skip(",", !0));
          skip("]");
        }
        return parent;
      }
      function parseService(parent, token2, depth) {
        if (depth = util.checkDepth(depth), !nameRe.test(token2 = next()))
          throw illegal(token2, "service name");
        var service = new Service(token2);
        ifBlock(service, function(token3) {
          if (!parseCommon(service, token3, depth))
            if (token3 === "rpc")
              parseMethod(service, token3);
            else
              throw illegal(token3);
        }), parent.add(service), parent === ptr && topLevelObjects.push(service);
      }
      function parseMethod(parent, token2) {
        var commentText = cmnt(), type = token2;
        if (!nameRe.test(token2 = next()))
          throw illegal(token2, "name");
        var name = token2, requestType, requestStream, responseType, responseStream;
        if (skip("("), skip("stream", !0) && (requestStream = !0), !typeRefRe.test(token2 = next()) || (requestType = token2, skip(")"), skip("returns"), skip("("), skip("stream", !0) && (responseStream = !0), !typeRefRe.test(token2 = next())))
          throw illegal(token2);
        responseType = token2, skip(")");
        var method = new Method(name, type, requestType, responseType, requestStream, responseStream);
        method.comment = commentText, ifBlock(method, function(token3) {
          if (token3 === "option")
            parseOption(method, token3), skip(";");
          else
            throw illegal(token3);
        }), parent.add(method);
      }
      function parseExtension(parent, token2, depth) {
        if (!typeRefRe.test(token2 = next()))
          throw illegal(token2, "reference");
        var reference = token2;
        ifBlock(null, function(token3) {
          switch (token3) {
            case "required":
            case "repeated":
              parseField(parent, token3, reference, depth + 1);
              break;
            case "optional":
              edition === "proto3" ? parseField(parent, "proto3_optional", reference, depth + 1) : parseField(parent, "optional", reference, depth + 1);
              break;
            default:
              if (edition === "proto2" || !typeRefRe.test(token3))
                throw illegal(token3);
              push(token3), parseField(parent, "optional", reference, depth + 1);
              break;
          }
        });
      }
      for (var token; (token = next()) !== null; )
        switch (token) {
          case "package":
            if (!head)
              throw illegal(token);
            parsePackage();
            break;
          case "import":
            if (!head)
              throw illegal(token);
            parseImport();
            break;
          case "syntax":
            if (!head)
              throw illegal(token);
            parseSyntax();
            break;
          case "edition":
            if (!head)
              throw illegal(token);
            parseEdition();
            break;
          case "option":
            parseOption(ptr, token), skip(";", !0);
            break;
          default:
            if (parseCommon(ptr, token, 0)) {
              head = !1;
              continue;
            }
            throw illegal(token);
        }
      return resolveFileFeatures(), parse2.filename = null, {
        package: pkg,
        imports,
        weakImports,
        root
      };
    }
  }
});

// node_modules/protobufjs/src/common.js
var require_common = __commonJS({
  "node_modules/protobufjs/src/common.js"(exports, module) {
    "use strict";
    module.exports = common;
    var commonRe = /\/|\./;
    function common(name, json) {
      commonRe.test(name) || (name = "google/protobuf/" + name + ".proto", json = { nested: { google: { nested: { protobuf: { nested: json } } } } }), common[name] = json;
    }
    common("any", {
      /**
       * Properties of a google.protobuf.Any message.
       * @interface IAny
       * @type {Object}
       * @property {string} [typeUrl]
       * @property {Uint8Array} [bytes]
       * @memberof common
       */
      Any: {
        fields: {
          type_url: {
            type: "string",
            id: 1
          },
          value: {
            type: "bytes",
            id: 2
          }
        }
      }
    });
    var timeType;
    common("duration", {
      /**
       * Properties of a google.protobuf.Duration message.
       * @interface IDuration
       * @type {Object}
       * @property {number|Long} [seconds]
       * @property {number} [nanos]
       * @memberof common
       */
      Duration: timeType = {
        fields: {
          seconds: {
            type: "int64",
            id: 1
          },
          nanos: {
            type: "int32",
            id: 2
          }
        }
      }
    });
    common("timestamp", {
      /**
       * Properties of a google.protobuf.Timestamp message.
       * @interface ITimestamp
       * @type {Object}
       * @property {number|Long} [seconds]
       * @property {number} [nanos]
       * @memberof common
       */
      Timestamp: timeType
    });
    common("empty", {
      /**
       * Properties of a google.protobuf.Empty message.
       * @interface IEmpty
       * @memberof common
       */
      Empty: {
        fields: {}
      }
    });
    common("struct", {
      /**
       * Properties of a google.protobuf.Struct message.
       * @interface IStruct
       * @type {Object}
       * @property {Object.<string,IValue>} [fields]
       * @memberof common
       */
      Struct: {
        fields: {
          fields: {
            keyType: "string",
            type: "Value",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.Value message.
       * @interface IValue
       * @type {Object}
       * @property {string} [kind]
       * @property {0} [nullValue]
       * @property {number} [numberValue]
       * @property {string} [stringValue]
       * @property {boolean} [boolValue]
       * @property {IStruct} [structValue]
       * @property {IListValue} [listValue]
       * @memberof common
       */
      Value: {
        oneofs: {
          kind: {
            oneof: [
              "nullValue",
              "numberValue",
              "stringValue",
              "boolValue",
              "structValue",
              "listValue"
            ]
          }
        },
        fields: {
          nullValue: {
            type: "NullValue",
            id: 1
          },
          numberValue: {
            type: "double",
            id: 2
          },
          stringValue: {
            type: "string",
            id: 3
          },
          boolValue: {
            type: "bool",
            id: 4
          },
          structValue: {
            type: "Struct",
            id: 5
          },
          listValue: {
            type: "ListValue",
            id: 6
          }
        }
      },
      NullValue: {
        values: {
          NULL_VALUE: 0
        }
      },
      /**
       * Properties of a google.protobuf.ListValue message.
       * @interface IListValue
       * @type {Object}
       * @property {Array.<IValue>} [values]
       * @memberof common
       */
      ListValue: {
        fields: {
          values: {
            rule: "repeated",
            type: "Value",
            id: 1
          }
        }
      }
    });
    common("wrappers", {
      /**
       * Properties of a google.protobuf.DoubleValue message.
       * @interface IDoubleValue
       * @type {Object}
       * @property {number} [value]
       * @memberof common
       */
      DoubleValue: {
        fields: {
          value: {
            type: "double",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.FloatValue message.
       * @interface IFloatValue
       * @type {Object}
       * @property {number} [value]
       * @memberof common
       */
      FloatValue: {
        fields: {
          value: {
            type: "float",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.Int64Value message.
       * @interface IInt64Value
       * @type {Object}
       * @property {number|Long} [value]
       * @memberof common
       */
      Int64Value: {
        fields: {
          value: {
            type: "int64",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.UInt64Value message.
       * @interface IUInt64Value
       * @type {Object}
       * @property {number|Long} [value]
       * @memberof common
       */
      UInt64Value: {
        fields: {
          value: {
            type: "uint64",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.Int32Value message.
       * @interface IInt32Value
       * @type {Object}
       * @property {number} [value]
       * @memberof common
       */
      Int32Value: {
        fields: {
          value: {
            type: "int32",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.UInt32Value message.
       * @interface IUInt32Value
       * @type {Object}
       * @property {number} [value]
       * @memberof common
       */
      UInt32Value: {
        fields: {
          value: {
            type: "uint32",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.BoolValue message.
       * @interface IBoolValue
       * @type {Object}
       * @property {boolean} [value]
       * @memberof common
       */
      BoolValue: {
        fields: {
          value: {
            type: "bool",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.StringValue message.
       * @interface IStringValue
       * @type {Object}
       * @property {string} [value]
       * @memberof common
       */
      StringValue: {
        fields: {
          value: {
            type: "string",
            id: 1
          }
        }
      },
      /**
       * Properties of a google.protobuf.BytesValue message.
       * @interface IBytesValue
       * @type {Object}
       * @property {Uint8Array} [value]
       * @memberof common
       */
      BytesValue: {
        fields: {
          value: {
            type: "bytes",
            id: 1
          }
        }
      }
    });
    common("field_mask", {
      /**
       * Properties of a google.protobuf.FieldMask message.
       * @interface IDoubleValue
       * @type {Object}
       * @property {number} [value]
       * @memberof common
       */
      FieldMask: {
        fields: {
          paths: {
            rule: "repeated",
            type: "string",
            id: 1
          }
        }
      }
    });
    common.get = function(file) {
      return common[file] || null;
    };
  }
});

// node_modules/protobufjs/src/index.js
var require_src = __commonJS({
  "node_modules/protobufjs/src/index.js"(exports, module) {
    "use strict";
    var protobuf = module.exports = require_index_light();
    protobuf.build = "full";
    protobuf.tokenize = require_tokenize();
    protobuf.parse = require_parse();
    protobuf.common = require_common();
    protobuf.Root._configure(protobuf.Type, protobuf.parse, protobuf.common);
  }
});

// node_modules/protobufjs/index.js
var require_protobufjs = __commonJS({
  "node_modules/protobufjs/index.js"(exports, module) {
    "use strict";
    module.exports = require_src();
  }
});

// ../javascript/lib/mp_solver_api.ts
var protobufModule = __toESM(require_protobufjs(), 1);
import { loadMPSolverRuntime } from "./runtime_loader.js";
import {
  isWorkerBridgeAvailable as isGenericWorkerBridgeAvailable,
  isWorkerBridgeEnabled as isGenericWorkerBridgeEnabled,
  nextWorkerBridgeRequestId,
  postWorkerRequest,
  setWorkerBridgeEnabled as setGenericWorkerBridgeEnabled,
  shouldUseWorkerBridge
} from "./worker_bridge.js";
var mpSolverModulePromise = null, mpSolverModule = null, mpSolverExports = null;
function isMPSolverWorkerBridgeRuntimeAvailable() {
  return isGenericWorkerBridgeAvailable();
}
function shouldUseMPSolverBridge() {
  return isMPSolverWorkerBridgeRuntimeAvailable() && shouldUseWorkerBridge();
}
function stringBytes(value) {
  return new TextEncoder().encode(`${value}\0`);
}
function wrap(module, name, returnType, argTypes) {
  return module.cwrap(name, returnType, argTypes);
}
function createMpSolverExports(module) {
  return {
    solverInfinity: wrap(module, "mp_solver_infinity", "number", []),
    solverSupportsProblemType: wrap(module, "mp_solver_supports_problem_type", "number", ["number"]),
    solverCreate: wrap(module, "mp_solver_create", "number", ["number", "number"]),
    solverCreateSolver: wrap(module, "mp_solver_create_solver", "number", ["number"]),
    solverParseSolverType: wrap(module, "mp_solver_parse_solver_type", "number", ["number"]),
    solverName: wrap(module, "mp_solver_name", "number", ["number"]),
    solverProblemType: wrap(module, "mp_solver_problem_type", "number", ["number"]),
    solverIsMip: wrap(module, "mp_solver_is_mip", "number", ["number"]),
    solverClear: wrap(module, "mp_solver_clear", void 0, ["number"]),
    solverDelete: wrap(module, "mp_solver_delete", void 0, ["number"]),
    solverVariable: wrap(module, "mp_solver_variable", "number", ["number", "number"]),
    solverLookupVariable: wrap(module, "mp_solver_lookup_variable", "number", ["number", "number"]),
    solverVar: wrap(module, "mp_solver_var", "number", ["number", "number", "number", "number", "number"]),
    solverNumVar: wrap(module, "mp_solver_num_var", "number", ["number", "number", "number", "number"]),
    solverIntVar: wrap(module, "mp_solver_int_var", "number", ["number", "number", "number", "number"]),
    solverBoolVar: wrap(module, "mp_solver_bool_var", "number", ["number", "number"]),
    solverConstraint: wrap(module, "mp_solver_constraint", "number", ["number", "number"]),
    solverLookupConstraint: wrap(module, "mp_solver_lookup_constraint", "number", ["number", "number"]),
    solverRowConstraint: wrap(module, "mp_solver_row_constraint", "number", ["number", "number", "number", "number"]),
    solverUnboundedRowConstraint: wrap(module, "mp_solver_unbounded_row_constraint", "number", ["number", "number"]),
    constraintClear: wrap(module, "mp_constraint_clear", void 0, ["number"]),
    constraintSetCoefficient: wrap(module, "mp_constraint_set_coefficient", void 0, ["number", "number", "number"]),
    constraintGetCoefficient: wrap(module, "mp_constraint_get_coefficient", "number", ["number", "number"]),
    constraintName: wrap(module, "mp_constraint_name", "number", ["number"]),
    constraintIndex: wrap(module, "mp_constraint_index", "number", ["number"]),
    constraintLb: wrap(module, "mp_constraint_lb", "number", ["number"]),
    constraintUb: wrap(module, "mp_constraint_ub", "number", ["number"]),
    constraintSetLb: wrap(module, "mp_constraint_set_lb", void 0, ["number", "number"]),
    constraintSetUb: wrap(module, "mp_constraint_set_ub", void 0, ["number", "number"]),
    constraintSetBounds: wrap(module, "mp_constraint_set_bounds", void 0, ["number", "number", "number"]),
    constraintDualValue: wrap(module, "mp_constraint_dual_value", "number", ["number"]),
    constraintBasisStatus: wrap(module, "mp_constraint_basis_status", "number", ["number"]),
    constraintIsLazy: wrap(module, "mp_constraint_is_lazy", "number", ["number"]),
    constraintSetIsLazy: wrap(module, "mp_constraint_set_is_lazy", void 0, ["number", "number"]),
    objectiveClear: wrap(module, "mp_objective_clear", void 0, ["number"]),
    objectiveSetCoefficient: wrap(module, "mp_objective_set_coefficient", void 0, ["number", "number", "number"]),
    objectiveGetCoefficient: wrap(module, "mp_objective_get_coefficient", "number", ["number", "number"]),
    objectiveSetOffset: wrap(module, "mp_objective_set_offset", void 0, ["number", "number"]),
    objectiveOffset: wrap(module, "mp_objective_offset", "number", ["number"]),
    objectiveAddOffset: wrap(module, "mp_objective_add_offset", void 0, ["number", "number"]),
    objectiveSetOptimizationDirection: wrap(module, "mp_objective_set_optimization_direction", void 0, ["number", "number"]),
    objectiveSetMinimization: wrap(module, "mp_objective_set_minimization", void 0, ["number"]),
    objectiveSetMaximization: wrap(module, "mp_objective_set_maximization", void 0, ["number"]),
    objectiveValue: wrap(module, "mp_objective_value", "number", ["number"]),
    objectiveBestBound: wrap(module, "mp_objective_best_bound", "number", ["number"]),
    objectiveMaximization: wrap(module, "mp_objective_maximization", "number", ["number"]),
    objectiveMinimization: wrap(module, "mp_objective_minimization", "number", ["number"]),
    solverExportModelProto: wrap(module, "mp_solver_export_model_proto", "number", ["number", "number"]),
    solverExportModelRequestProto: wrap(module, "mp_solver_export_model_request_proto", "number", ["number", "number", "number", "number", "number", "number"]),
    solverLoadSolutionProto: wrap(module, "mp_solver_load_solution_proto", "number", ["number", "number", "number", "number"]),
    solverVerifySolution: wrap(module, "mp_solver_verify_solution", "number", ["number", "number", "number"]),
    solverReset: wrap(module, "mp_solver_reset", void 0, ["number"]),
    solverInterruptSolve: wrap(module, "mp_solver_interrupt_solve", "number", ["number"]),
    solverNextSolution: wrap(module, "mp_solver_next_solution", "number", ["number"]),
    solverEnableOutput: wrap(module, "mp_solver_enable_output", void 0, ["number"]),
    solverSuppressOutput: wrap(module, "mp_solver_suppress_output", void 0, ["number"]),
    solverOutputIsEnabled: wrap(module, "mp_solver_output_is_enabled", "number", ["number"]),
    solverSetTimeLimit: wrap(module, "mp_solver_set_time_limit", void 0, ["number", "bigint"]),
    solverTimeLimit: wrap(module, "mp_solver_time_limit", "bigint", ["number"]),
    solverSetNumThreads: wrap(module, "mp_solver_set_num_threads", "number", ["number", "number"]),
    solverGetNumThreads: wrap(module, "mp_solver_get_num_threads", "number", ["number"]),
    solverSetSolverSpecificParametersAsString: wrap(module, "mp_solver_set_solver_specific_parameters_as_string", "number", ["number", "number"]),
    solverGetSolverSpecificParametersAsString: wrap(module, "mp_solver_get_solver_specific_parameters_as_string", "number", ["number"]),
    solverSolverVersion: wrap(module, "mp_solver_solver_version", "number", ["number"]),
    solverExportModelAsLpFormat: wrap(module, "mp_solver_export_model_as_lp_format", "number", ["number", "number"]),
    solverExportModelAsMpsFormat: wrap(module, "mp_solver_export_model_as_mps_format", "number", ["number", "number", "number"]),
    solverConstraintActivity: wrap(module, "mp_solver_constraint_activity", "number", ["number", "number"]),
    solverComputeExactConditionNumber: wrap(module, "mp_solver_compute_exact_condition_number", "number", ["number"]),
    solverSetHint: wrap(module, "mp_solver_set_hint", void 0, ["number", "number", "number", "number"]),
    lastStringResult: wrap(module, "mp_last_string_result", "number", []),
    solverNumVariables: wrap(module, "mp_solver_num_variables", "number", ["number"]),
    solverNumConstraints: wrap(module, "mp_solver_num_constraints", "number", ["number"]),
    solverWallTime: wrap(module, "mp_solver_wall_time", "bigint", ["number"]),
    solverIterations: wrap(module, "mp_solver_iterations", "bigint", ["number"]),
    solverNodes: wrap(module, "mp_solver_nodes", "bigint", ["number"]),
    variableName: wrap(module, "mp_variable_name", "number", ["number"]),
    variableIndex: wrap(module, "mp_variable_index", "number", ["number"]),
    variableSolutionValue: wrap(module, "mp_variable_solution_value", "number", ["number"]),
    variableUnroundedSolutionValue: wrap(module, "mp_variable_unrounded_solution_value", "number", ["number"]),
    variableReducedCost: wrap(module, "mp_variable_reduced_cost", "number", ["number"]),
    variableBasisStatus: wrap(module, "mp_variable_basis_status", "number", ["number"]),
    variableLb: wrap(module, "mp_variable_lb", "number", ["number"]),
    variableUb: wrap(module, "mp_variable_ub", "number", ["number"]),
    variableInteger: wrap(module, "mp_variable_integer", "number", ["number"]),
    variableSetInteger: wrap(module, "mp_variable_set_integer", void 0, ["number", "number"]),
    variableSetLb: wrap(module, "mp_variable_set_lb", void 0, ["number", "number"]),
    variableSetUb: wrap(module, "mp_variable_set_ub", void 0, ["number", "number"]),
    variableSetBounds: wrap(module, "mp_variable_set_bounds", void 0, ["number", "number", "number"]),
    variableBranchingPriority: wrap(module, "mp_variable_branching_priority", "number", ["number"]),
    variableSetBranchingPriority: wrap(module, "mp_variable_set_branching_priority", void 0, ["number", "number"]),
    parametersCreate: wrap(module, "mp_solver_parameters_create", "number", []),
    parametersDelete: wrap(module, "mp_solver_parameters_delete", void 0, ["number"]),
    parametersSetDoubleParam: wrap(module, "mp_solver_parameters_set_double_param", void 0, ["number", "number", "number"]),
    parametersGetDoubleParam: wrap(module, "mp_solver_parameters_get_double_param", "number", ["number", "number"]),
    parametersResetDoubleParam: wrap(module, "mp_solver_parameters_reset_double_param", void 0, ["number", "number"]),
    parametersSetIntegerParam: wrap(module, "mp_solver_parameters_set_integer_param", void 0, ["number", "number", "number"]),
    parametersGetIntegerParam: wrap(module, "mp_solver_parameters_get_integer_param", "number", ["number", "number"]),
    parametersResetIntegerParam: wrap(module, "mp_solver_parameters_reset_integer_param", void 0, ["number", "number"]),
    parametersReset: wrap(module, "mp_solver_parameters_reset", void 0, ["number"])
  };
}
async function loadMpSolverModule() {
  return mpSolverModulePromise ?? (mpSolverModulePromise = loadMPSolverRuntime()), mpSolverModule = await mpSolverModulePromise, mpSolverExports ?? (mpSolverExports = createMpSolverExports(mpSolverModule)), mpSolverModule;
}
function getMpSolverModule() {
  if (!mpSolverModule)
    throw new Error("MPSolver API is not initialized. Call await initMPSolver() before constructing MPSolver objects.");
  return mpSolverModule;
}
async function withCStringAsync(module, value, fn) {
  let bytes = stringBytes(value), ptr = module._malloc(bytes.byteLength);
  module.HEAPU8.set(bytes, ptr);
  try {
    return await fn(ptr);
  } finally {
    module._free(ptr);
  }
}
function readCString(module, ptr) {
  return ptr === 0 ? "" : module.UTF8ToString(ptr);
}
async function initKnapsack() {
  shouldUseMPSolverBridge() || await loadMpSolverModule();
}
function isMPSolverWorkerBridgeAvailable() {
  return isMPSolverWorkerBridgeRuntimeAvailable();
}
function setMPSolverWorkerBridgeEnabled(enabled) {
  setGenericWorkerBridgeEnabled(enabled);
}
function isMPSolverWorkerBridgeEnabled() {
  return isGenericWorkerBridgeEnabled() && isMPSolverWorkerBridgeRuntimeAvailable();
}
var KnapsackSolverType = /* @__PURE__ */ ((KnapsackSolverType2) => (KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_BRUTE_FORCE_SOLVER = 0] = "KNAPSACK_BRUTE_FORCE_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_64ITEMS_SOLVER = 1] = "KNAPSACK_64ITEMS_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER = 2] = "KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER = 3] = "KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER = 5] = "KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER = 6] = "KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER = 7] = "KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER = 8] = "KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_DIVIDE_AND_CONQUER_SOLVER = 9] = "KNAPSACK_DIVIDE_AND_CONQUER_SOLVER", KnapsackSolverType2[KnapsackSolverType2.KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER = 10] = "KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER", KnapsackSolverType2))(KnapsackSolverType || {});
function copyFloat64ToHeap(module, values) {
  if (!values.length) return 0;
  let ptr = module._malloc(values.length * Float64Array.BYTES_PER_ELEMENT);
  return new Float64Array(module.HEAPU8.buffer, ptr, values.length).set(values), ptr;
}
function flattenKnapsackWeights(weights, itemCount) {
  let flattened = [];
  for (let dimension of weights) {
    if (dimension.length !== itemCount)
      throw new Error("KnapsackSolver.init: each weight dimension must match profits length.");
    flattened.push(...dimension);
  }
  return flattened;
}
function parseKnapsackResult(serialized) {
  let result = JSON.parse(serialized);
  if (!result.ok)
    throw new Error(result.error || "KnapsackSolver.solve: native solve failed.");
  return result;
}
async function solveKnapsackDirect(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities) {
  let module = await loadMpSolverModule(), flattenedWeights = flattenKnapsackWeights(weights, profits.length), profitsPtr = copyFloat64ToHeap(module, profits), weightsPtr = copyFloat64ToHeap(module, flattenedWeights), capacitiesPtr = copyFloat64ToHeap(module, capacities);
  try {
    return await withCStringAsync(module, name, async (namePtr) => {
      let resultPtr = await module.ccall(
        "knapsack_solve_serialized",
        "number",
        ["number", "number", "number", "number", "number", "number", "number", "number", "number"],
        [
          solverType,
          namePtr,
          useReduction ? 1 : 0,
          timeLimitSeconds,
          profitsPtr,
          profits.length,
          weightsPtr,
          weights.length,
          capacitiesPtr
        ],
        { async: !0 }
      );
      return parseKnapsackResult(readCString(module, resultPtr));
    });
  } finally {
    profitsPtr && module._free(profitsPtr), weightsPtr && module._free(weightsPtr), capacitiesPtr && module._free(capacitiesPtr);
  }
}
async function solveKnapsack(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities) {
  if (shouldUseMPSolverBridge()) {
    let response = await postWorkerRequest({
      type: "knapsackSolve",
      id: nextWorkerBridgeRequestId(),
      solverType,
      name,
      useReduction,
      timeLimitSeconds,
      profits,
      weights,
      capacities
    });
    return parseKnapsackResult(response.result);
  }
  return solveKnapsackDirect(solverType, name, useReduction, timeLimitSeconds, profits, weights, capacities);
}
var KnapsackSolver = class {
  constructor(solverType, solverName) {
    __publicField(this, "solverType", solverType);
    __publicField(this, "solverName", solverName);
    __publicField(this, "profits", []);
    __publicField(this, "weights", []);
    __publicField(this, "capacities", []);
    __publicField(this, "useReduction", !0);
    __publicField(this, "timeLimitSeconds", 0);
    __publicField(this, "solutionContains", []);
    __publicField(this, "solutionOptimal", !1);
    shouldUseMPSolverBridge() || getMpSolverModule();
  }
  init(profits, weights, capacities) {
    if (weights.length !== capacities.length)
      throw new Error("KnapsackSolver.init: weights dimensions must match capacities length.");
    flattenKnapsackWeights(weights, profits.length), this.profits = [...profits], this.weights = weights.map((dimension) => [...dimension]), this.capacities = [...capacities], this.solutionContains = [], this.solutionOptimal = !1;
  }
  Init(profits, weights, capacities) {
    this.init(profits, weights, capacities);
  }
  async solve() {
    let result = await solveKnapsack(
      this.solverType,
      this.solverName,
      this.useReduction,
      this.timeLimitSeconds,
      this.profits,
      this.weights,
      this.capacities
    );
    return this.solutionContains = result.contains ?? [], this.solutionOptimal = result.optimal === !0, Number(result.profit ?? 0);
  }
  Solve() {
    return this.solve();
  }
  best_solution_contains(itemId) {
    return this.solutionContains[itemId] === !0;
  }
  BestSolutionContains(itemId) {
    return this.best_solution_contains(itemId);
  }
  is_solution_optimal() {
    return this.solutionOptimal;
  }
  IsSolutionOptimal() {
    return this.is_solution_optimal();
  }
  set_use_reduction(useReduction) {
    this.useReduction = useReduction;
  }
  SetUseReduction(useReduction) {
    this.set_use_reduction(useReduction);
  }
  set_time_limit(timeLimitSeconds) {
    this.timeLimitSeconds = timeLimitSeconds;
  }
  SetTimeLimit(timeLimitSeconds) {
    this.set_time_limit(timeLimitSeconds);
  }
  getName() {
    return this.solverName;
  }
  GetName() {
    return this.getName();
  }
};
__publicField(KnapsackSolver, "SolverType", KnapsackSolverType), __publicField(KnapsackSolver, "KNAPSACK_BRUTE_FORCE_SOLVER", 0 /* KNAPSACK_BRUTE_FORCE_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_64ITEMS_SOLVER", 1 /* KNAPSACK_64ITEMS_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER", 2 /* KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER", 3 /* KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER", 5 /* KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER", 6 /* KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER", 7 /* KNAPSACK_MULTIDIMENSION_XPRESS_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER", 8 /* KNAPSACK_MULTIDIMENSION_CPLEX_MIP_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_DIVIDE_AND_CONQUER_SOLVER", 9 /* KNAPSACK_DIVIDE_AND_CONQUER_SOLVER */), __publicField(KnapsackSolver, "KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER", 10 /* KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER */);

// ../javascript/lib/knapsack.ts
import { terminateWorkerBridge } from "./worker_bridge.js";
import { terminateLoadedRuntimeThreads } from "./runtime_loader.js";
export {
  KnapsackSolver,
  KnapsackSolverType,
  initKnapsack,
  isMPSolverWorkerBridgeAvailable as isWorkerBridgeAvailable,
  isMPSolverWorkerBridgeEnabled as isWorkerBridgeEnabled,
  setMPSolverWorkerBridgeEnabled as setWorkerBridgeEnabled,
  terminateLoadedRuntimeThreads,
  terminateWorkerBridge
};
