/* A QR code, so getting Thea onto a phone is a scan and not a password.
 *
 * Why this exists at all: the honest install path for the phone is "open
 * https://<his tailnet name>/interface/thea.html?token=<the code he minted>",
 * and that is a sentence nobody types on glass correctly. He points the
 * camera at his own screen once and the phone is on the tailnet URL, already
 * linked, one tap from Add to Home Screen.
 *
 * Byte mode, error correction level M, versions 1-15 — enough for any
 * tailnet URL with a token on it. No network, no library, no build step.
 *
 * Verified against a real encoder rather than by eye: tests/test_the_qr_code_scans.py
 * renders this in Chromium and compares every module of every matrix with
 * `segno`. A QR that does not scan is worse than no QR, and looking at one
 * tells you nothing.
 */
window.TheaQR = (() => {
  "use strict";

  // ---- GF(256), primitive polynomial 0x11D -------------------------------
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  (function tables() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();

  const mul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

  function generator(n) {
    let poly = [1];
    for (let i = 0; i < n; i++) {
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= mul(poly[j], EXP[i]);
      }
      poly = next;
    }
    return poly;
  }

  function ecc(data, n) {
    const gen = generator(n);
    const rest = new Array(n).fill(0);
    for (const byte of data) {
      const factor = byte ^ rest[0];
      rest.shift();
      rest.push(0);
      for (let i = 0; i < n; i++) rest[i] ^= mul(gen[i + 1], factor);
    }
    return rest;
  }

  // ---- the version tables, level M ---------------------------------------
  //: version -> [ec codewords per block, blocks in group 1, data codewords
  //: in each, blocks in group 2, data codewords in each]
  const BLOCKS_M = {
    1: [10, 1, 16, 0, 0], 2: [16, 1, 28, 0, 0], 3: [26, 1, 44, 0, 0],
    4: [18, 2, 32, 0, 0], 5: [24, 2, 43, 0, 0], 6: [16, 4, 27, 0, 0],
    7: [18, 4, 31, 0, 0], 8: [22, 2, 38, 2, 39], 9: [22, 3, 36, 2, 37],
    10: [26, 4, 43, 1, 44], 11: [30, 1, 50, 4, 51], 12: [22, 6, 36, 2, 37],
    13: [22, 8, 37, 1, 38], 14: [24, 4, 40, 5, 41], 15: [24, 5, 41, 5, 42],
  };
  //: version -> alignment pattern centre coordinates
  const ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
    11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66],
    15: [6, 26, 48, 70],
  };
  const EC_M = 0b00;   // level M's own two bits, for the format information

  const countBits = (version) => (version < 10 ? 8 : 16);
  const dataCodewords = (version) => {
    const [, g1, d1, g2, d2] = BLOCKS_M[version];
    return g1 * d1 + g2 * d2;
  };

  function pickVersion(byteLength) {
    for (let v = 1; v <= 15; v++) {
      const room = dataCodewords(v) * 8 - 4 - countBits(v);
      if (byteLength * 8 <= room) return v;
    }
    throw new Error("too long for a QR code");
  }

  // ---- the bit stream -----------------------------------------------------
  function codewords(bytes, version) {
    const bits = [];
    const push = (value, width) => {
      for (let i = width - 1; i >= 0; i--) bits.push((value >> i) & 1);
    };
    push(0b0100, 4);                       // byte mode
    push(bytes.length, countBits(version));
    for (const b of bytes) push(b, 8);
    const capacity = dataCodewords(version) * 8;
    for (let i = 0; i < 4 && bits.length < capacity; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const out = [];
    for (let i = 0; i < bits.length; i += 8) {
      out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
    }
    return out;
  }

  /* Short messages are padded with the spec's alternating 0xEC / 0x11 — not
   * zeros, which a decoder reads as more data. */
  function padded(bytes, version) {
    const out = codewords(bytes, version);
    const want = dataCodewords(version);
    const pad = [0xec, 0x11];
    let i = 0;
    while (out.length < want) out.push(pad[i++ % 2]);
    return out;
  }

  /* Data and error correction are INTERLEAVED across blocks — block 1's
   * first codeword, block 2's first, and so on. Getting this wrong produces
   * a picture that looks exactly like a QR code and decodes to nothing. */
  function interleave(data, version) {
    const [ecLen, g1, d1, g2, d2] = BLOCKS_M[version];
    const blocks = [];
    let at = 0;
    for (let i = 0; i < g1; i++) { blocks.push(data.slice(at, at + d1)); at += d1; }
    for (let i = 0; i < g2; i++) { blocks.push(data.slice(at, at + d2)); at += d2; }
    const checks = blocks.map((b) => ecc(b, ecLen));
    const out = [];
    const longest = Math.max(...blocks.map((b) => b.length));
    for (let i = 0; i < longest; i++) {
      for (const block of blocks) if (i < block.length) out.push(block[i]);
    }
    for (let i = 0; i < ecLen; i++) for (const check of checks) out.push(check[i]);
    return out;
  }

  // ---- the matrix ---------------------------------------------------------
  function blank(size) {
    const m = [], used = [];
    for (let r = 0; r < size; r++) {
      m.push(new Array(size).fill(0));
      used.push(new Array(size).fill(false));
    }
    return { m, used };
  }

  function functionPatterns(grid, version) {
    const { m, used } = grid;
    const size = m.length;
    const set = (r, c, v) => { m[r][c] = v; used[r][c] = true; };

    const finder = (top, left) => {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          const rr = top + r, cc = left + c;
          if (rr < 0 || cc < 0 || rr >= size || cc >= size) continue;
          const on = (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
                     (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
                     (r >= 2 && r <= 4 && c >= 2 && c <= 4);
          set(rr, cc, on ? 1 : 0);
        }
      }
    };
    finder(0, 0); finder(0, size - 7); finder(size - 7, 0);

    for (let i = 8; i < size - 8; i++) {
      const on = i % 2 === 0 ? 1 : 0;
      set(6, i, on); set(i, 6, on);
    }

    // The three corners that would land on a finder are skipped BY POSITION.
    // Skipping "anything already used" instead quietly drops the alignment
    // pattern that sits on the timing line from version 7 up, and every data
    // module after it moves one place.
    const centres = ALIGN[version];
    const last = centres.length - 1;
    for (let ri = 0; ri <= last; ri++) {
      for (let ci = 0; ci <= last; ci++) {
        if ((ri === 0 && ci === 0) || (ri === 0 && ci === last) || (ri === last && ci === 0)) continue;
        const r = centres[ri], c = centres[ci];
        for (let dr = -2; dr <= 2; dr++) {
          for (let dc = -2; dc <= 2; dc++) {
            const on = Math.max(Math.abs(dr), Math.abs(dc)) !== 1 ? 1 : 0;
            set(r + dr, c + dc, on);
          }
        }
      }
    }

    set(size - 8, 8, 1);                           // the dark module

    // format information: reserved here, written after the mask is chosen
    for (let i = 0; i < 9; i++) {
      if (!used[8][i] || i === 6) used[8][i] = true;
      if (!used[i][8] || i === 6) used[i][8] = true;
    }
    for (let i = 0; i < 8; i++) {
      used[8][size - 1 - i] = true;
      used[size - 1 - i][8] = true;
    }
    if (version >= 7) {
      for (let i = 0; i < 6; i++) {
        for (let j = 0; j < 3; j++) {
          used[size - 11 + j][i] = true;
          used[i][size - 11 + j] = true;
        }
      }
    }
  }

  function placeData(grid, stream) {
    const { m, used } = grid;
    const size = m.length;
    let bit = 0;
    const next = () => {
      const byte = stream[bit >> 3];
      const value = byte === undefined ? 0 : (byte >> (7 - (bit & 7))) & 1;
      bit++;
      return value;
    };
    let upward = true;
    for (let right = size - 1; right > 0; right -= 2) {
      if (right === 6) right = 5;                  // the vertical timing line
      for (let step = 0; step < size; step++) {
        const row = upward ? size - 1 - step : step;
        for (const col of [right, right - 1]) {
          if (used[row][col]) continue;
          m[row][col] = next();
        }
      }
      upward = !upward;
    }
  }

  const MASKS = [
    (r, c) => (r + c) % 2 === 0,
    (r) => r % 2 === 0,
    (r, c) => c % 3 === 0,
    (r, c) => (r + c) % 3 === 0,
    (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
    (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
    (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
    (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
  ];

  function formatBits(mask) {
    let value = (EC_M << 3) | mask;
    let bch = value << 10;
    for (let i = 14; i >= 10; i--) {
      if ((bch >> i) & 1) bch ^= 0b10100110111 << (i - 10);
    }
    return ((value << 10) | bch) ^ 0b101010000010010;
  }

  function versionBits(version) {
    let bch = version << 12;
    for (let i = 17; i >= 12; i--) {
      if ((bch >> i) & 1) bch ^= 0b1111100100101 << (i - 12);
    }
    return (version << 12) | bch;
  }

  /* The fifteen format bits, twice, in the two shapes the spec gives them.
   * Written as (row, column) — the reference implementations say (x, y) and
   * transposing them produces a symbol that is the right size, the right
   * version and unreadable. */
  function writeFormat(m, mask) {
    const size = m.length;
    const bits = formatBits(mask);
    const at = (i) => (bits >> i) & 1;
    for (let i = 0; i <= 5; i++) m[i][8] = at(i);
    m[7][8] = at(6);
    m[8][8] = at(7);
    m[8][7] = at(8);
    for (let i = 9; i <= 14; i++) m[8][14 - i] = at(i);
    for (let i = 0; i <= 7; i++) m[8][size - 1 - i] = at(i);
    for (let i = 8; i <= 14; i++) m[size - 15 + i][8] = at(i);
    m[size - 8][8] = 1;                            // the dark module, always
  }

  function writeVersion(m, version) {
    if (version < 7) return;
    const size = m.length;
    const bits = versionBits(version);
    for (let i = 0; i < 18; i++) {
      const bit = (bits >> i) & 1;
      const r = Math.floor(i / 3), c = i % 3;
      m[r][size - 11 + c] = bit;
      m[size - 11 + c][r] = bit;
    }
  }

  function penalty(m) {
    const size = m.length;
    let score = 0;
    const run = (get) => {
      for (let a = 0; a < size; a++) {
        let length = 1;
        for (let b = 1; b < size; b++) {
          if (get(a, b) === get(a, b - 1)) {
            length++;
          } else {
            if (length >= 5) score += 3 + (length - 5);
            length = 1;
          }
        }
        if (length >= 5) score += 3 + (length - 5);
      }
    };
    run((r, c) => m[r][c]);
    run((c, r) => m[r][c]);
    for (let r = 0; r < size - 1; r++) {
      for (let c = 0; c < size - 1; c++) {
        const v = m[r][c];
        if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) score += 3;
      }
    }
    // A finder-like 1:1:3:1:1 run with a light margin on one side of it —
    // the 2015 wording, which is what a real encoder scores. The older
    // "match these eleven modules" shortcut scores differently and picks a
    // different mask, which is how a symbol that is perfectly valid stops
    // being comparable to anybody else's.
    const PATTERN = [1, 0, 1, 1, 1, 0, 1];
    const at = (seq, i) => {
      for (let k = 0; k < 7; k++) if (seq[i + k] !== PATTERN[k]) return false;
      return true;
    };
    const finderLike = (seq) => {
      let count = 0;
      for (let i = 0; i + 7 <= size;) {
        if (!at(seq, i)) { i++; continue; }
        const clear = (from, to) => {
          for (let k = Math.max(from, 0); k < Math.min(to, size); k++) if (seq[k]) return false;
          return true;
        };
        if (i === 0 || i === size - 7 || clear(i - 4, i) || clear(i + 7, i + 11)) {
          count += 40;
          i += 7;
        } else {
          i += 4;
        }
      }
      return count;
    };
    for (let i = 0; i < size; i++) {
      score += finderLike(m[i]);
      score += finderLike(m.map((row) => row[i]));
    }
    let dark = 0;
    for (const row of m) for (const v of row) dark += v;
    const percent = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(percent - 50) / 5) * 10;
    return score;
  }

  /** The finished modules, as rows of 0/1. `only` forces one mask, which
   *  exists so the test can separate "the encoder is right" from "the mask
   *  chosen is the one the spec's penalty rules choose". */
  function matrix(text, only) {
    const bytes = Array.from(new TextEncoder().encode(String(text)));
    const version = pickVersion(bytes.length);
    const stream = interleave(padded(bytes, version), version);
    const size = version * 4 + 17;
    let best = null;
    for (let mask = 0; mask < 8; mask++) {
      if (only !== undefined && only !== null && mask !== only) continue;
      const grid = blank(size);
      functionPatterns(grid, version);
      placeData(grid, stream);
      for (let r = 0; r < size; r++) {
        for (let c = 0; c < size; c++) {
          if (!grid.used[r][c] && MASKS[mask](r, c)) grid.m[r][c] ^= 1;
        }
      }
      writeFormat(grid.m, mask);
      writeVersion(grid.m, version);
      const score = penalty(grid.m);
      if (best === null || score < best.score) best = { score, m: grid.m };
    }
    return best.m;
  }

  /** The same thing as an <svg> string, with the quiet zone the spec wants. */
  function svg(text, { quiet = 4, dark = "#0a0b0e", light = "#f0ece4" } = {}) {
    const m = matrix(text);
    const size = m.length + quiet * 2;
    let path = "";
    for (let r = 0; r < m.length; r++) {
      for (let c = 0; c < m.length; c++) {
        if (m[r][c]) path += `M${c + quiet} ${r + quiet}h1v1h-1z`;
      }
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" ` +
      `shape-rendering="crispEdges" role="img" aria-label="Link to open Thea on your phone">` +
      `<rect width="${size}" height="${size}" fill="${light}"/>` +
      `<path fill="${dark}" d="${path}"/></svg>`;
  }

  return { matrix, svg };
})();
