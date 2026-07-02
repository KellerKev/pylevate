/**
 * PyLevate Baselib — Python builtins polyfill for compiled JS.
 * Provides Python-like builtins that the py2js compiler may reference.
 */

// range() — Python-compatible range generator
if (typeof globalThis.range === 'undefined') {
  globalThis.range = function range(start, stop, step) {
    if (stop === undefined) { stop = start; start = 0; }
    if (step === undefined) { step = start < stop ? 1 : -1; }
    const result = [];
    if (step > 0) {
      for (let i = start; i < stop; i += step) result.push(i);
    } else {
      for (let i = start; i > stop; i += step) result.push(i);
    }
    return result;
  };
}

// enumerate()
if (typeof globalThis.enumerate === 'undefined') {
  globalThis.enumerate = function enumerate(iterable, start = 0) {
    return iterable.map((item, i) => [i + start, item]);
  };
}

// zip()
if (typeof globalThis.zip === 'undefined') {
  globalThis.zip = function zip(...arrays) {
    const minLen = Math.min(...arrays.map(a => a.length));
    return Array.from({ length: minLen }, (_, i) => arrays.map(a => a[i]));
  };
}

// Python-style print
if (typeof globalThis.print === 'undefined') {
  globalThis.print = function print(...args) {
    console.log(...args);
  };
}

// len()
if (typeof globalThis.len === 'undefined') {
  globalThis.len = function len(obj) {
    if (obj == null) throw new TypeError("object has no len()");
    if (typeof obj.length === 'number') return obj.length;
    if (obj instanceof Map || obj instanceof Set) return obj.size;
    if (typeof obj === 'object') return Object.keys(obj).length;
    throw new TypeError("object has no len()");
  };
}

// isinstance()
if (typeof globalThis.isinstance === 'undefined') {
  globalThis.isinstance = function isinstance(obj, classOrTuple) {
    if (Array.isArray(classOrTuple)) {
      return classOrTuple.some(c => obj instanceof c);
    }
    return obj instanceof classOrTuple;
  };
}

// sorted()
if (typeof globalThis.sorted === 'undefined') {
  globalThis.sorted = function sorted(iterable, { key, reverse } = {}) {
    const arr = [...iterable];
    if (key) {
      arr.sort((a, b) => {
        const ka = key(a), kb = key(b);
        return ka < kb ? -1 : ka > kb ? 1 : 0;
      });
    } else {
      arr.sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
    }
    if (reverse) arr.reverse();
    return arr;
  };
}

// sum()
if (typeof globalThis.sum === 'undefined') {
  globalThis.sum = function sum(iterable, start = 0) {
    return iterable.reduce((acc, val) => acc + val, start);
  };
}

// abs()
if (typeof globalThis.abs === 'undefined') {
  globalThis.abs = Math.abs;
}

// min() / max() with key support
if (typeof globalThis.min === 'undefined') {
  globalThis.min = function min(...args) {
    const arr = args.length === 1 ? [...args[0]] : args;
    return arr.reduce((a, b) => a < b ? a : b);
  };
}
if (typeof globalThis.max === 'undefined') {
  globalThis.max = function max(...args) {
    const arr = args.length === 1 ? [...args[0]] : args;
    return arr.reduce((a, b) => a > b ? a : b);
  };
}

// int() / float() / str() / bool()
if (typeof globalThis.int === 'undefined') {
  globalThis.int = function int(x, base) {
    if (base !== undefined) return parseInt(x, base);
    return parseInt(x, 10);
  };
}
if (typeof globalThis.float === 'undefined') {
  globalThis.float = parseFloat;
}
if (typeof globalThis.str === 'undefined') {
  globalThis.str = function str(x) { return String(x); };
}
if (typeof globalThis.bool === 'undefined') {
  globalThis.bool = function bool(x) { return globalThis.__truthy(x); };
}
// Python-style truthiness: empty collections are FALSY (unlike JS). The compiler
// wraps every boolean-context test in __truthy(...).
if (typeof globalThis.__truthy === 'undefined') {
  globalThis.__truthy = function __truthy(x) {
    if (x === null || x === undefined || x === false || x === 0 || x === '') return false;
    if (typeof x !== 'object') return Boolean(x);
    if (Array.isArray(x)) return x.length > 0;
    if (x instanceof Set || x instanceof Map) return x.size > 0;
    if (x.constructor === Object) return Object.keys(x).length > 0;  // dict literal
    return true;  // class instances (Component/Sprite/Group/…) are truthy
  };
}

// dict / list / tuple helpers
if (typeof globalThis.dict === 'undefined') {
  globalThis.dict = function dict(entries) {
    if (!entries) return {};
    return Object.fromEntries(entries);
  };
}
if (typeof globalThis.list === 'undefined') {
  globalThis.list = function list(iterable) {
    return [...iterable];
  };
}
if (typeof globalThis.tuple === 'undefined') {
  globalThis.tuple = function tuple(iterable) {
    return Object.freeze([...iterable]);
  };
}

// hasattr / getattr / setattr
if (typeof globalThis.hasattr === 'undefined') {
  globalThis.hasattr = function hasattr(obj, name) {
    return name in obj;
  };
}
if (typeof globalThis.getattr === 'undefined') {
  globalThis.getattr = function getattr(obj, name, defaultVal) {
    if (name in obj) return obj[name];
    if (arguments.length >= 3) return defaultVal;
    throw new Error(`AttributeError: '${typeof obj}' object has no attribute '${name}'`);
  };
}
if (typeof globalThis.setattr === 'undefined') {
  globalThis.setattr = function setattr(obj, name, value) {
    obj[name] = value;
  };
}

// type()
if (typeof globalThis.type === 'undefined') {
  globalThis.type = function type(obj) {
    return obj?.constructor || typeof obj;
  };
}

// __slice — Python slice with step (handles negatives, e.g. arr[::-1]).
if (typeof globalThis.__slice === 'undefined') {
  globalThis.__slice = function __slice(seq, start, stop, step) {
    const isStr = typeof seq === 'string';
    const n = seq.length;
    step = (step === undefined || step === null) ? 1 : step;
    if (step === 0) throw new Error('ValueError: slice step cannot be zero');
    let lo, hi;
    if (step > 0) {
      lo = (start === undefined || start === null) ? 0 : (start < 0 ? Math.max(n + start, 0) : Math.min(start, n));
      hi = (stop === undefined || stop === null) ? n : (stop < 0 ? Math.max(n + stop, 0) : Math.min(stop, n));
    } else {
      lo = (start === undefined || start === null) ? n - 1 : (start < 0 ? Math.max(n + start, -1) : Math.min(start, n - 1));
      hi = (stop === undefined || stop === null) ? -1 : (stop < 0 ? Math.max(n + stop, -1) : Math.min(stop, n - 1));
    }
    const out = [];
    if (step > 0) { for (let i = lo; i < hi; i += step) out.push(seq[i]); }
    else { for (let i = lo; i > hi; i += step) out.push(seq[i]); }
    return isStr ? out.join('') : out;
  };
}

// __iter — coerce a comprehension's iterable to a real array so `.filter/.map`
// work on Groups/Sets/strings/dicts (a sprite Group is iterable but has no
// .filter; a dict iterates its keys).
if (typeof globalThis.__iter === 'undefined') {
  globalThis.__iter = function __iter(x) {
    if (x === null || x === undefined) return [];
    if (Array.isArray(x)) return x;
    if (typeof x === 'string') return Array.from(x);
    if (typeof x[Symbol.iterator] === 'function') return Array.from(x);  // Group/Set/Map
    if (typeof x === 'object') return Object.keys(x);                    // dict → keys
    return Array.from(x);
  };
}

// More Python builtins (previously undefined at runtime).
if (typeof globalThis.ord === 'undefined') {
  globalThis.ord = function ord(c) { return String(c).codePointAt(0); };
}
if (typeof globalThis.chr === 'undefined') {
  globalThis.chr = function chr(n) { return String.fromCodePoint(n); };
}
if (typeof globalThis.hex === 'undefined') {
  globalThis.hex = function hex(n) { return (n < 0 ? '-0x' + (-n).toString(16) : '0x' + n.toString(16)); };
}
if (typeof globalThis.bin === 'undefined') {
  globalThis.bin = function bin(n) { return (n < 0 ? '-0b' + (-n).toString(2) : '0b' + n.toString(2)); };
}
if (typeof globalThis.oct === 'undefined') {
  globalThis.oct = function oct(n) { return (n < 0 ? '-0o' + (-n).toString(8) : '0o' + n.toString(8)); };
}
if (typeof globalThis.divmod === 'undefined') {
  globalThis.divmod = function divmod(a, b) { return [Math.floor(a / b), ((a % b) + b) % b]; };
}
if (typeof globalThis.repr === 'undefined') {
  globalThis.repr = function repr(x) {
    if (typeof x === 'string') return "'" + x.replace(/'/g, "\\'") + "'";
    try { return JSON.stringify(x); } catch (e) { return String(x); }
  };
}
// round() with optional ndigits (banker's-rounding-agnostic; matches common use).
if (typeof globalThis.round === 'undefined') {
  globalThis.round = function round(x, ndigits) {
    if (ndigits === undefined) return Math.round(x);
    const f = Math.pow(10, ndigits);
    return Math.round(x * f) / f;
  };
}

// random module shim
if (typeof globalThis.random === 'undefined') {
  globalThis.random = {
    randrange(start, stop) {
      if (stop === undefined) { stop = start; start = 0; }
      return Math.floor(Math.random() * (stop - start)) + start;
    },
    randint(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a; },
    random() { return Math.random(); },
    choice(arr) { return arr[Math.floor(Math.random() * arr.length)]; },
    shuffle(arr) {
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }
      return arr;
    },
    uniform(a, b) { return a + Math.random() * (b - a); },
  };
}

// math module shim — Python-style (lowercase constants + common functions).
// `math = Math` left `math.pi`/`math.e` undefined (JS uses Math.PI/Math.E) and
// omitted radians/degrees/hypot/etc.
if (typeof globalThis.math === 'undefined') {
  globalThis.math = {
    pi: Math.PI, e: Math.E, tau: Math.PI * 2, inf: Infinity, nan: NaN,
    sin: Math.sin, cos: Math.cos, tan: Math.tan,
    asin: Math.asin, acos: Math.acos, atan: Math.atan, atan2: Math.atan2,
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    sqrt: Math.sqrt, pow: Math.pow, exp: Math.exp,
    log: (x, base) => (base === undefined ? Math.log(x) : Math.log(x) / Math.log(base)),
    log2: Math.log2, log10: Math.log10,
    floor: Math.floor, ceil: Math.ceil, trunc: Math.trunc,
    fabs: Math.abs, hypot: Math.hypot,
    copysign: (x, y) => ((y < 0 || Object.is(y, -0)) ? -Math.abs(x) : Math.abs(x)),
    radians: (d) => (d * Math.PI) / 180, degrees: (r) => (r * 180) / Math.PI,
    fmod: (a, b) => a % b,
    isnan: Number.isNaN, isfinite: Number.isFinite,
    isinf: (x) => x === Infinity || x === -Infinity,
    gcd: (a, b) => { a = Math.abs(a); b = Math.abs(b); while (b) { [a, b] = [b, a % b]; } return a; },
    factorial: (n) => { let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; },
    dist: (p, q) => Math.hypot(...p.map((v, i) => v - q[i])),
  };
}
