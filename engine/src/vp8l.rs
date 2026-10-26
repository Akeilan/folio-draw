//! WebP lossless (VP8L): the decoder (transforms, prefix codes, backward references, the
//! colour cache) and an encoder (subtract-green, LZ77 with hash chains, one set of prefix
//! codes). Pixels are 0xAARRGGBB while decoding.

// ------------------------------------------------------------------ bit reader

pub struct Bits<'a> {
    data: &'a [u8],
    pos: usize,
    buf: u64,
    n: u32,
}

impl<'a> Bits<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Bits { data, pos: 0, buf: 0, n: 0 }
    }

    fn fill(&mut self) {
        while self.n <= 56 {
            let b = if self.pos < self.data.len() { self.data[self.pos] } else { 0 };
            self.pos += 1;
            self.buf |= (b as u64) << self.n;
            self.n += 8;
        }
    }

    pub fn read(&mut self, k: u32) -> u32 {
        if k == 0 {
            return 0;
        }
        if self.n < k {
            self.fill();
        }
        let v = (self.buf & ((1u64 << k) - 1)) as u32;
        self.buf >>= k;
        self.n -= k;
        v
    }

    fn peek(&mut self, k: u32) -> u32 {
        if self.n < k {
            self.fill();
        }
        (self.buf & ((1u64 << k) - 1)) as u32
    }

    fn skip(&mut self, k: u32) {
        self.buf >>= k;
        self.n -= k;
    }

    fn past_end(&self) -> bool {
        self.pos > self.data.len() + 8
    }
}

// ------------------------------------------------------------------ prefix codes

const MAX_LEN: u32 = 15;
const TABLE_BITS: u32 = 8;

/// A canonical prefix code, looked up through a first-level table and a slow path.
struct Code {
    /// one symbol only: reading it takes no bits
    single: Option<u16>,
    /// first-level table: (symbol, length); length 0 = longer code, use the slow path
    table: Vec<(u16, u8)>,
    /// (code bit-reversed, length, symbol) for codes longer than TABLE_BITS
    long: Vec<(u32, u8, u16)>,
}

fn reverse(mut v: u32, len: u32) -> u32 {
    let mut r = 0;
    for _ in 0..len {
        r = (r << 1) | (v & 1);
        v >>= 1;
    }
    r
}

impl Code {
    fn from_lengths(lengths: &[u8]) -> Result<Code, String> {
        let used: Vec<usize> = (0..lengths.len()).filter(|&i| lengths[i] > 0).collect();
        if used.is_empty() {
            return Ok(Code { single: Some(0), table: vec![], long: vec![] });
        }
        if used.len() == 1 {
            return Ok(Code { single: Some(used[0] as u16), table: vec![], long: vec![] });
        }
        let mut count = [0u32; 16];
        for &l in lengths {
            if l > 0 {
                count[l as usize] += 1;
            }
        }
        // the lengths must make a complete code
        let mut left: i64 = 1;
        for l in 1..=15 {
            left = left * 2 - count[l] as i64;
            if left < 0 {
                return Err("WebP: bad prefix code".into());
            }
        }
        if left != 0 {
            return Err("WebP: incomplete prefix code".into());
        }
        let mut next = [0u32; 16];
        let mut code = 0u32;
        for l in 1..=15 {
            code = (code + count[l - 1]) << 1;
            next[l] = code;
        }
        let mut table = vec![(0u16, 0u8); 1 << TABLE_BITS];
        let mut long = Vec::new();
        for (sym, &l) in lengths.iter().enumerate() {
            if l == 0 {
                continue;
            }
            let c = next[l as usize];
            next[l as usize] += 1;
            let rc = reverse(c, l as u32);
            if l as u32 <= TABLE_BITS {
                let step = 1u32 << l;
                let mut i = rc;
                while i < (1 << TABLE_BITS) {
                    table[i as usize] = (sym as u16, l);
                    i += step;
                }
            } else {
                long.push((rc, l, sym as u16));
            }
        }
        Ok(Code { single: None, table, long })
    }

    fn read(&self, b: &mut Bits) -> Result<u16, String> {
        if let Some(s) = self.single {
            return Ok(s);
        }
        let v = b.peek(MAX_LEN);
        let (s, l) = self.table[(v & ((1 << TABLE_BITS) - 1)) as usize];
        if l > 0 {
            b.skip(l as u32);
            return Ok(s);
        }
        for &(rc, l, s) in &self.long {
            if v & ((1 << l) - 1) == rc {
                b.skip(l as u32);
                return Ok(s);
            }
        }
        Err("WebP: bad prefix code in data".into())
    }
}

const CODE_ORDER: [usize; 19] = [17, 18, 0, 1, 2, 3, 4, 5, 16, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];

fn read_code(b: &mut Bits, alphabet: usize) -> Result<Code, String> {
    let mut lengths = vec![0u8; alphabet];
    if b.read(1) == 1 {
        // simple: one or two symbols
        let n = b.read(1) + 1;
        let first_bits = if b.read(1) == 1 { 8 } else { 1 };
        let s0 = b.read(first_bits) as usize;
        if s0 >= alphabet {
            return Err("WebP: bad simple code".into());
        }
        lengths[s0] = 1;
        if n == 2 {
            let s1 = b.read(8) as usize;
            if s1 >= alphabet {
                return Err("WebP: bad simple code".into());
            }
            lengths[s1] = 1;
            if s0 == s1 {
                lengths[s0] = 0;
                return Ok(Code { single: Some(s0 as u16), table: vec![], long: vec![] });
            }
        } else {
            return Ok(Code { single: Some(s0 as u16), table: vec![], long: vec![] });
        }
        return Code::from_lengths(&lengths);
    }
    let ncl = b.read(4) as usize + 4;
    if ncl > 19 {
        return Err("WebP: bad code length count".into());
    }
    let mut cl = [0u8; 19];
    for &o in CODE_ORDER.iter().take(ncl) {
        cl[o] = b.read(3) as u8;
    }
    let clc = Code::from_lengths(&cl)?;
    let max_symbol = if b.read(1) == 1 {
        let lb = 2 + 2 * b.read(3);
        let m = 2 + b.read(lb) as usize;
        if m > alphabet {
            return Err("WebP: bad max symbol".into());
        }
        m
    } else {
        alphabet
    };
    let mut prev = 8u8;
    let mut i = 0;
    let mut symbols = 0;
    while i < alphabet && symbols < max_symbol {
        let c = clc.read(b)?;
        symbols += 1;
        match c {
            0..=15 => {
                lengths[i] = c as u8;
                if c != 0 {
                    prev = c as u8;
                }
                i += 1;
            }
            16 => {
                let r = 3 + b.read(2) as usize;
                if i + r > alphabet {
                    return Err("WebP: bad code lengths".into());
                }
                for _ in 0..r {
                    lengths[i] = prev;
                    i += 1;
                }
            }
            17 | 18 => {
                let r = if c == 17 { 3 + b.read(3) as usize } else { 11 + b.read(7) as usize };
                if i + r > alphabet {
                    return Err("WebP: bad code lengths".into());
                }
                i += r;
            }
            _ => return Err("WebP: bad code length symbol".into()),
        }
        if b.past_end() {
            return Err("WebP: truncated".into());
        }
    }
    Code::from_lengths(&lengths)
}

struct Group {
    codes: Vec<Code>, // green+length+cache, red, blue, alpha, distance
}

// ------------------------------------------------------------------ the image data

const DISTANCE_MAP: [(i8, i8); 120] = [
    (0, 1), (1, 0), (1, 1), (-1, 1), (0, 2), (2, 0), (1, 2), (-1, 2),
    (2, 1), (-2, 1), (2, 2), (-2, 2), (0, 3), (3, 0), (1, 3), (-1, 3),
    (3, 1), (-3, 1), (2, 3), (-2, 3), (3, 2), (-3, 2), (0, 4), (4, 0),
    (1, 4), (-1, 4), (4, 1), (-4, 1), (3, 3), (-3, 3), (2, 4), (-2, 4),
    (4, 2), (-4, 2), (0, 5), (3, 4), (-3, 4), (4, 3), (-4, 3), (5, 0),
    (1, 5), (-1, 5), (5, 1), (-5, 1), (2, 5), (-2, 5), (5, 2), (-5, 2),
    (4, 4), (-4, 4), (3, 5), (-3, 5), (5, 3), (-5, 3), (0, 6), (6, 0),
    (1, 6), (-1, 6), (6, 1), (-6, 1), (2, 6), (-2, 6), (6, 2), (-6, 2),
    (4, 5), (-4, 5), (5, 4), (-5, 4), (3, 6), (-3, 6), (6, 3), (-6, 3),
    (0, 7), (7, 0), (1, 7), (-1, 7), (5, 5), (-5, 5), (7, 1), (-7, 1),
    (4, 6), (-4, 6), (6, 4), (-6, 4), (2, 7), (-2, 7), (7, 2), (-7, 2),
    (3, 7), (-3, 7), (7, 3), (-7, 3), (5, 6), (-5, 6), (6, 5), (-6, 5),
    (8, 0), (4, 7), (-4, 7), (7, 4), (-7, 4), (8, 1), (8, 2), (6, 6),
    (-6, 6), (8, 3), (5, 7), (-5, 7), (7, 5), (-7, 5), (8, 4), (6, 7),
    (-6, 7), (7, 6), (-7, 6), (8, 5), (7, 7), (-7, 7), (8, 6), (8, 7),
];

fn prefix_value(b: &mut Bits, prefix: u32) -> u32 {
    if prefix < 4 {
        return prefix + 1;
    }
    let extra = (prefix - 2) >> 1;
    let offset = (2 + (prefix & 1)) << extra;
    offset + b.read(extra) + 1
}

fn div_round_up(v: usize, bits: u32) -> usize {
    (v + (1 << bits) - 1) >> bits
}

/// Entropy-coded pixels of a w x h image (the main image when `main`, else a sub-image).
fn read_pixels(b: &mut Bits, w: usize, h: usize, main: bool) -> Result<Vec<u32>, String> {
    let cache_bits = if b.read(1) == 1 {
        let c = b.read(4);
        if !(1..=11).contains(&c) {
            return Err("WebP: bad colour cache".into());
        }
        c
    } else {
        0
    };
    let mut meta_bits = 0;
    let mut meta: Option<Vec<u32>> = None;
    let mut ngroups = 1;
    if main && b.read(1) == 1 {
        meta_bits = b.read(3) + 2;
        let mw = div_round_up(w, meta_bits);
        let mh = div_round_up(h, meta_bits);
        let img = read_pixels(b, mw, mh, false)?;
        let m: Vec<u32> = img.iter().map(|p| (p >> 8) & 0xffff).collect();
        ngroups = m.iter().copied().max().unwrap_or(0) as usize + 1;
        meta = Some(m);
    }
    let cache_size = if cache_bits > 0 { 1usize << cache_bits } else { 0 };
    let mut groups = Vec::with_capacity(ngroups);
    for _ in 0..ngroups {
        let sizes = [256 + 24 + cache_size, 256, 256, 256, 40];
        let mut codes = Vec::with_capacity(5);
        for &s in &sizes {
            codes.push(read_code(b, s)?);
        }
        groups.push(Group { codes });
    }
    let n = w * h;
    let mut px = vec![0u32; n];
    let mut cache = vec![0u32; cache_size];
    let mut last_cached = 0usize;
    let mw = if meta_bits > 0 { div_round_up(w, meta_bits) } else { 1 };
    let mut i = 0usize;
    let group_at = |i: usize| -> usize {
        match &meta {
            Some(m) => {
                let (x, y) = (i % w, i / w);
                m[(y >> meta_bits) * mw + (x >> meta_bits)] as usize
            }
            None => 0,
        }
    };
    while i < n {
        let g = &groups[group_at(i)];
        let s = g.codes[0].read(b)? as u32;
        if s < 256 {
            let red = g.codes[1].read(b)? as u32;
            let blue = g.codes[2].read(b)? as u32;
            let alpha = g.codes[3].read(b)? as u32;
            px[i] = (alpha << 24) | (red << 16) | (s << 8) | blue;
            i += 1;
        } else if s < 256 + 24 {
            let len = prefix_value(b, s - 256) as usize;
            let dsym = g.codes[4].read(b)? as u32;
            let dcode = prefix_value(b, dsym) as usize;
            let dist = if dcode > 120 {
                dcode - 120
            } else {
                let (dx, dy) = DISTANCE_MAP[dcode - 1];
                let d = dx as i64 + dy as i64 * w as i64;
                if d < 1 { 1 } else { d as usize }
            };
            if dist > i || i + len > n {
                return Err("WebP: bad backward reference".into());
            }
            for k in 0..len {
                px[i + k] = px[i + k - dist];
            }
            i += len;
        } else {
            let ci = (s - 256 - 24) as usize;
            if ci >= cache_size {
                return Err("WebP: bad colour cache index".into());
            }
            // the cache holds everything decoded so far
            while last_cached < i {
                let p = px[last_cached];
                cache[((0x1e35a7bdu32.wrapping_mul(p)) >> (32 - cache_bits)) as usize] = p;
                last_cached += 1;
            }
            px[i] = cache[ci];
            i += 1;
        }
        if cache_size > 0 {
            while last_cached < i {
                let p = px[last_cached];
                cache[((0x1e35a7bdu32.wrapping_mul(p)) >> (32 - cache_bits)) as usize] = p;
                last_cached += 1;
            }
        }
        if b.past_end() {
            return Err("WebP: truncated image data".into());
        }
    }
    Ok(px)
}

// ------------------------------------------------------------------ transforms

enum Transform {
    Predictor { bits: u32, data: Vec<u32> },
    Color { bits: u32, data: Vec<u32> },
    SubtractGreen,
    Indexing { width_bits: u32, palette: Vec<u32> },
}

fn add_px(a: u32, b: u32) -> u32 {
    let ag = (a & 0xff00ff00).wrapping_add(b & 0xff00ff00) & 0xff00ff00;
    let rb = (a & 0x00ff00ff).wrapping_add(b & 0x00ff00ff) & 0x00ff00ff;
    ag | rb
}

fn avg2(a: u32, b: u32) -> u32 {
    (((a ^ b) & 0xfefefefe) >> 1) + (a & b)
}

fn ch(p: u32, s: u32) -> i32 {
    ((p >> s) & 0xff) as i32
}

fn select(l: u32, t: u32, tl: u32) -> u32 {
    let mut pl = 0;
    let mut pt = 0;
    for s in [24, 16, 8, 0] {
        let p = ch(l, s) + ch(t, s) - ch(tl, s);
        pl += (p - ch(l, s)).abs();
        pt += (p - ch(t, s)).abs();
    }
    if pl < pt { l } else { t }
}

fn clamp_full(a: u32, b: u32, c: u32) -> u32 {
    let mut out = 0;
    for s in [24, 16, 8, 0] {
        out |= ((ch(a, s) + ch(b, s) - ch(c, s)).clamp(0, 255) as u32) << s;
    }
    out
}

fn clamp_half(a: u32, b: u32) -> u32 {
    let mut out = 0;
    for s in [24, 16, 8, 0] {
        let (x, y) = (ch(a, s), ch(b, s));
        out |= ((x + (x - y) / 2).clamp(0, 255) as u32) << s;
    }
    out
}

fn predict(mode: u32, px: &[u32], i: usize, w: usize) -> u32 {
    let l = px[i - 1];
    let t = px[i - w];
    let tl = px[i - w - 1];
    // the pixel to the top right of the last column is the first of this row
    let tr = px[i - w + 1];
    match mode {
        0 => 0xff000000,
        1 => l,
        2 => t,
        3 => tr,
        4 => tl,
        5 => avg2(avg2(l, tr), t),
        6 => avg2(l, tl),
        7 => avg2(l, t),
        8 => avg2(tl, t),
        9 => avg2(t, tr),
        10 => avg2(avg2(l, tl), avg2(t, tr)),
        11 => select(l, t, tl),
        12 => clamp_full(l, t, tl),
        13 => clamp_half(avg2(l, t), tl),
        _ => 0xff000000,
    }
}

fn delta(t: u32, c: u32) -> u32 {
    (((t as u8 as i8 as i32) * (c as u8 as i8 as i32)) >> 5) as u32
}

fn undo_transforms(px: &mut Vec<u32>, w: usize, h: usize, ts: &[Transform], ws: &[usize]) {
    for (k, t) in ts.iter().enumerate().rev() {
        let tw = ws[k];
        match t {
            Transform::Predictor { bits, data } => {
                let bw = div_round_up(tw, *bits);
                for y in 0..h {
                    for x in 0..tw {
                        let i = y * tw + x;
                        let pred = if y == 0 {
                            if x == 0 { 0xff000000 } else { px[i - 1] }
                        } else if x == 0 {
                            px[i - tw]
                        } else {
                            let mode = (data[(y >> bits) * bw + (x >> bits)] >> 8) & 0xf;
                            predict(mode, px, i, tw)
                        };
                        px[i] = add_px(px[i], pred);
                    }
                }
            }
            Transform::Color { bits, data } => {
                let bw = div_round_up(tw, *bits);
                for y in 0..h {
                    for x in 0..tw {
                        let e = data[(y >> bits) * bw + (x >> bits)];
                        let (r2b, g2b, g2r) = ((e >> 16) & 0xff, (e >> 8) & 0xff, e & 0xff);
                        let p = px[y * tw + x];
                        let g = (p >> 8) & 0xff;
                        let r = (((p >> 16) & 0xff).wrapping_add(delta(g2r, g))) & 0xff;
                        let bl = ((p & 0xff).wrapping_add(delta(g2b, g)).wrapping_add(delta(r2b, r))) & 0xff;
                        px[y * tw + x] = (p & 0xff00ff00) | (r << 16) | bl;
                    }
                }
            }
            Transform::SubtractGreen => {
                for p in px.iter_mut() {
                    let g = (*p >> 8) & 0xff;
                    let r = (((*p >> 16) & 0xff) + g) & 0xff;
                    let b = ((*p & 0xff) + g) & 0xff;
                    *p = (*p & 0xff00ff00) | (r << 16) | b;
                }
            }
            Transform::Indexing { width_bits, palette } => {
                // the packed width is the transform's input width; the output is the next width out
                let out_w = if k == 0 { w } else { ws[k - 1] };
                let per = 1usize << width_bits;
                let bits_per = 8 >> width_bits;
                let mask = (1u32 << bits_per) - 1;
                let mut out = vec![0u32; out_w * h];
                for y in 0..h {
                    for x in 0..out_w {
                        let packed = (px[y * tw + x / per] >> 8) & 0xff;
                        let idx = if *width_bits == 0 { packed } else { (packed >> ((x % per) * bits_per)) & mask };
                        out[y * out_w + x] = palette.get(idx as usize).copied().unwrap_or(0);
                    }
                }
                *px = out;
            }
        }
    }
}

/// A VP8L image stream (after its 5-byte header when `headerless` is false the header is read).
pub fn decode_stream(data: &[u8], w: usize, h: usize) -> Result<Vec<u32>, String> {
    let mut b = Bits::new(data);
    let mut ts = Vec::new();
    let mut cur_w = w;
    let mut seen = [false; 4];
    while b.read(1) == 1 {
        let kind = b.read(2) as usize;
        if seen[kind] {
            return Err("WebP: a transform used twice".into());
        }
        seen[kind] = true;
        match kind {
            0 | 1 => {
                let bits = b.read(3) + 2;
                let data = read_pixels(&mut b, div_round_up(cur_w, bits), div_round_up(h, bits), false)?;
                ts.push(if kind == 0 { Transform::Predictor { bits, data } } else { Transform::Color { bits, data } });
            }
            2 => ts.push(Transform::SubtractGreen),
            _ => {
                let n = b.read(8) as usize + 1;
                let mut pal = read_pixels(&mut b, n, 1, false)?;
                for i in 1..n {
                    pal[i] = add_px(pal[i], pal[i - 1]);
                }
                let width_bits = if n <= 2 { 3 } else if n <= 4 { 2 } else if n <= 16 { 1 } else { 0 };
                cur_w = div_round_up(cur_w, width_bits);
                ts.push(Transform::Indexing { width_bits, palette: pal });
            }
        }
    }
    // the widths each transform reads from (indexing narrows what follows it)
    let mut ws = Vec::with_capacity(ts.len());
    let mut wcur = w;
    for t in &ts {
        if let Transform::Indexing { width_bits, .. } = t {
            wcur = div_round_up(wcur, *width_bits);
        }
        ws.push(wcur);
    }
    let mut px = read_pixels(&mut b, cur_w, h, true)?;
    undo_transforms(&mut px, w, h, &ts, &ws);
    Ok(px)
}

pub fn is_vp8l(d: &[u8]) -> bool {
    d.len() >= 5 && d[0] == 0x2f
}

/// A VP8L chunk: (width, height, RGBA).
pub fn decode(d: &[u8]) -> Result<(usize, usize, Vec<u8>), String> {
    if !is_vp8l(d) {
        return Err("WebP: not a lossless image".into());
    }
    let mut b = Bits::new(&d[1..]);
    let w = b.read(14) as usize + 1;
    let h = b.read(14) as usize + 1;
    if w * h > 100_000_000 {
        return Err("WebP: image is too large".into());
    }
    let _alpha = b.read(1);
    if b.read(3) != 0 {
        return Err("WebP: unknown lossless version".into());
    }
    let px = decode_stream(&d[5..], w, h)?;
    Ok((w, h, to_rgba(&px)))
}

pub fn to_rgba(px: &[u32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(px.len() * 4);
    for &p in px {
        out.extend_from_slice(&[(p >> 16) as u8, (p >> 8) as u8, p as u8, (p >> 24) as u8]);
    }
    out
}

// ------------------------------------------------------------------ the encoder

struct BitWriter {
    out: Vec<u8>,
    buf: u64,
    n: u32,
}

impl BitWriter {
    fn new() -> Self {
        BitWriter { out: Vec::new(), buf: 0, n: 0 }
    }
    fn put(&mut self, v: u32, k: u32) {
        if k == 0 {
            return;
        }
        self.buf |= (v as u64 & ((1u64 << k) - 1)) << self.n;
        self.n += k;
        while self.n >= 8 {
            self.out.push(self.buf as u8);
            self.buf >>= 8;
            self.n -= 8;
        }
    }
    fn finish(mut self) -> Vec<u8> {
        if self.n > 0 {
            self.out.push(self.buf as u8);
        }
        self.out
    }
}

/// Huffman code lengths for the symbol counts, at most `limit` long (counts are flattened
/// and the code built again until it fits, which keeps it complete).
fn code_lengths(freq: &[u32], limit: u8) -> Vec<u8> {
    let n = freq.len();
    let used: Vec<usize> = (0..n).filter(|&i| freq[i] > 0).collect();
    let mut lens = vec![0u8; n];
    if used.is_empty() {
        return lens;
    }
    if used.len() == 1 {
        lens[used[0]] = 1;
        return lens;
    }
    let mut f: Vec<u64> = freq.iter().map(|&v| v as u64).collect();
    loop {
        // repeatedly join the two lightest (a heap by sorting; alphabets are small)
        let mut weights: Vec<(u64, usize)> = used.iter().map(|&s| (f[s], s)).collect();
        let mut parent: Vec<usize> = vec![usize::MAX; 2 * used.len()];
        let mut nodes: Vec<u64> = Vec::new();
        let mut heap: std::collections::BinaryHeap<std::cmp::Reverse<(u64, usize)>> = std::collections::BinaryHeap::new();
        for (k, w) in weights.iter_mut().enumerate() {
            nodes.push(w.0);
            heap.push(std::cmp::Reverse((w.0, k)));
        }
        while heap.len() > 1 {
            let std::cmp::Reverse((wa, a)) = heap.pop().unwrap();
            let std::cmp::Reverse((wb, b)) = heap.pop().unwrap();
            let k = nodes.len();
            nodes.push(wa + wb);
            parent[a] = k;
            parent[b] = k;
            heap.push(std::cmp::Reverse((wa + wb, k)));
        }
        let mut max = 0;
        for (k, &s) in used.iter().enumerate() {
            let mut d = 0;
            let mut x = k;
            while parent[x] != usize::MAX {
                x = parent[x];
                d += 1;
            }
            lens[s] = d as u8;
            max = max.max(d);
        }
        if max <= limit as usize {
            return lens;
        }
        for &s in &used {
            f[s] = (f[s] >> 1) | 1;
        }
    }
}

fn canonical_codes(lens: &[u8]) -> Vec<u32> {
    let mut count = [0u32; 16];
    for &l in lens {
        if l > 0 {
            count[l as usize] += 1;
        }
    }
    let mut next = [0u32; 16];
    let mut code = 0;
    for l in 1..16 {
        code = (code + count[l - 1]) << 1;
        next[l] = code;
    }
    lens.iter().map(|&l| {
        if l == 0 {
            0
        } else {
            let c = next[l as usize];
            next[l as usize] += 1;
            reverse(c, l as u32)
        }
    }).collect()
}

/// Write one prefix code (as the decoder reads it) and give back its codes.
fn write_code(w: &mut BitWriter, freq: &[u32]) -> (Vec<u8>, Vec<u32>) {
    let used: Vec<usize> = (0..freq.len()).filter(|&i| freq[i] > 0).collect();
    if used.len() <= 2 && used.iter().all(|&s| s < 256) {
        // simple code
        w.put(1, 1);
        let syms: Vec<usize> = if used.is_empty() { vec![0] } else { used.clone() };
        w.put(syms.len() as u32 - 1, 1);
        if syms[0] < 2 {
            w.put(0, 1);
            w.put(syms[0] as u32, 1);
        } else {
            w.put(1, 1);
            w.put(syms[0] as u32, 8);
        }
        if syms.len() == 2 {
            w.put(syms[1] as u32, 8);
        }
        let mut lens = vec![0u8; freq.len()];
        if syms.len() == 2 {
            lens[syms[0]] = 1;
            lens[syms[1]] = 1;
        }
        let codes = canonical_codes(&lens);
        return (lens, codes);
    }
    let lens = code_lengths(freq, 15);
    // one symbol takes no bits to read, whatever length is written for it
    let emit_lens: Vec<u8> = if used.len() == 1 { vec![0u8; lens.len()] } else { lens.clone() };
    // the lengths themselves, with zero runs (17, 18) and repeats (16)
    let mut toks: Vec<(u8, u32, u32)> = Vec::new(); // (symbol, extra value, extra bits)
    let mut i = 0;
    let last = lens.iter().rposition(|&l| l > 0).map(|p| p + 1).unwrap_or(0);
    let mut prev = 8u8;
    while i < last {
        let l = lens[i];
        let mut run = 1;
        while i + run < last && lens[i + run] == l {
            run += 1;
        }
        if l == 0 && run >= 3 {
            let mut r = run;
            while r >= 3 {
                if r >= 11 {
                    let k = r.min(138);
                    toks.push((18, (k - 11) as u32, 7));
                    r -= k;
                } else {
                    let k = r.min(10);
                    toks.push((17, (k - 3) as u32, 3));
                    r -= k;
                }
            }
            for _ in 0..r {
                toks.push((0, 0, 0));
            }
            i += run;
            continue;
        }
        if l != 0 && l == prev && run >= 3 {
            let mut r = run;
            while r >= 3 {
                let k = r.min(6);
                toks.push((16, (k - 3) as u32, 2));
                r -= k;
            }
            for _ in 0..r {
                toks.push((l, 0, 0));
            }
            i += run;
            continue;
        }
        toks.push((l, 0, 0));
        if l != 0 {
            prev = l;
        }
        i += 1;
    }
    let mut cfreq = [0u32; 19];
    for t in &toks {
        cfreq[t.0 as usize] += 1;
    }
    let mut clens = code_lengths(&cfreq, 7);
    if clens.iter().filter(|&&l| l > 0).count() == 1 {
        // a one-symbol code-length code still needs a length the decoder accepts
        let s = clens.iter().position(|&l| l > 0).unwrap();
        let other = if s == 0 { 1 } else { 0 };
        clens[other] = 1;
        clens[s] = 1;
    }
    let ccodes = canonical_codes(&clens);
    let mut ncl = 19;
    while ncl > 4 && clens[CODE_ORDER[ncl - 1]] == 0 {
        ncl -= 1;
    }
    w.put(0, 1);
    w.put(ncl as u32 - 4, 4);
    for &o in CODE_ORDER.iter().take(ncl) {
        w.put(clens[o] as u32, 3);
    }
    // how many length symbols follow (the rest are zero)
    if last < freq.len() {
        let n_syms = toks.len();
        if n_syms >= 2 {
            let need = n_syms - 2;
            let mut lb = 2;
            while (1usize << lb) <= need {
                lb += 2;
            }
            if lb <= 16 {
                w.put(1, 1);
                w.put((lb - 2) / 2, 3);
                w.put(need as u32, lb);
            } else {
                w.put(0, 1);
                toks.extend(std::iter::repeat((0u8, 0u32, 0u32)).take(freq.len() - last));
            }
        } else {
            w.put(0, 1);
            toks.extend(std::iter::repeat((0u8, 0u32, 0u32)).take(freq.len() - last));
        }
    } else {
        w.put(0, 1);
    }
    for (s, v, b) in toks {
        w.put(ccodes[s as usize], clens[s as usize] as u32);
        w.put(v, b);
    }
    let codes = canonical_codes(&lens);
    (emit_lens, codes)
}

fn prefix_encode(v: u32) -> (u32, u32, u32) {
    // value >= 1 -> (prefix symbol, extra bits count, extra value)
    let d = v - 1;
    if d < 4 {
        return (d, 0, 0);
    }
    let hb = 31 - d.leading_zeros();
    let second = (d >> (hb - 1)) & 1;
    let extra = hb - 1;
    let prefix = 2 * hb + second;
    (prefix, extra, d & ((1 << extra) - 1))
}

enum Sym {
    Lit(u32),
    Copy { len: u32, dist: u32 },
}

fn lz77(px: &[u32]) -> Vec<Sym> {
    const HASH_BITS: u32 = 16;
    const WINDOW: usize = (1 << 20) - 120;
    const MAX_LEN: usize = 4096;
    const CHAIN: usize = 32;
    let n = px.len();
    let mut head = vec![usize::MAX; 1 << HASH_BITS];
    let mut prev = vec![usize::MAX; n];
    let hash = |i: usize| -> usize {
        let a = px[i].wrapping_mul(0x9E3779B1) ^ px[i + 1].wrapping_mul(0x85EBCA6B);
        (a >> (32 - HASH_BITS)) as usize
    };
    let mut out = Vec::new();
    let mut i = 0;
    while i < n {
        let mut best_len = 0;
        let mut best_dist = 0;
        if i + 1 < n {
            let h = hash(i);
            let mut cand = head[h];
            let mut tries = 0;
            while cand != usize::MAX && tries < CHAIN && i - cand <= WINDOW {
                let mut l = 0;
                while i + l < n && l < MAX_LEN && px[cand + l] == px[i + l] {
                    l += 1;
                }
                if l > best_len {
                    best_len = l;
                    best_dist = i - cand;
                }
                cand = prev[cand];
                tries += 1;
            }
        }
        let take = if best_len >= 3 { best_len } else { 1 };
        for k in i..(i + take).min(n.saturating_sub(1)) {
            let h = hash(k);
            prev[k] = head[h];
            head[h] = k;
        }
        if best_len >= 3 {
            out.push(Sym::Copy { len: best_len as u32, dist: best_dist as u32 });
        } else {
            out.push(Sym::Lit(px[i]));
        }
        i += take;
    }
    out
}

/// An RGBA image as a VP8L chunk payload (lossless).
pub fn encode(w: usize, h: usize, rgba: &[u8]) -> Vec<u8> {
    let mut px: Vec<u32> = rgba.chunks_exact(4).map(|p| {
        ((p[3] as u32) << 24) | ((p[0] as u32) << 16) | ((p[1] as u32) << 8) | p[2] as u32
    }).collect();
    // fully transparent pixels: colour doesn't matter, so make them alike (compresses better)
    for p in px.iter_mut() {
        if *p >> 24 == 0 {
            *p = 0;
        }
    }
    let has_alpha = px.iter().any(|p| p >> 24 != 0xff);
    // subtract green
    for p in px.iter_mut() {
        let g = (*p >> 8) & 0xff;
        let r = (((*p >> 16) & 0xff).wrapping_sub(g)) & 0xff;
        let b = ((*p & 0xff).wrapping_sub(g)) & 0xff;
        *p = (*p & 0xff00ff00) | (r << 16) | b;
    }
    let syms = lz77(&px);
    let mut f = [vec![0u32; 280], vec![0u32; 256], vec![0u32; 256], vec![0u32; 256], vec![0u32; 40]];
    for s in &syms {
        match s {
            Sym::Lit(p) => {
                f[0][((p >> 8) & 0xff) as usize] += 1;
                f[1][((p >> 16) & 0xff) as usize] += 1;
                f[2][(p & 0xff) as usize] += 1;
                f[3][(p >> 24) as usize] += 1;
            }
            Sym::Copy { len, dist } => {
                f[0][256 + prefix_encode(*len).0 as usize] += 1;
                f[4][prefix_encode(dist + 120).0 as usize] += 1;
            }
        }
    }
    let mut wr = BitWriter::new();
    wr.put(0x2f, 8);
    wr.put(w as u32 - 1, 14);
    wr.put(h as u32 - 1, 14);
    wr.put(has_alpha as u32, 1);
    wr.put(0, 3);
    // one transform: subtract green
    wr.put(1, 1);
    wr.put(2, 2);
    wr.put(0, 1); // no more transforms
    wr.put(0, 1); // no colour cache
    wr.put(0, 1); // no meta prefix codes
    let mut tabs = Vec::new();
    for fr in &f {
        tabs.push(write_code(&mut wr, fr));
    }
    for s in &syms {
        match s {
            Sym::Lit(p) => {
                let g = ((p >> 8) & 0xff) as usize;
                let r = ((p >> 16) & 0xff) as usize;
                let b = (p & 0xff) as usize;
                let a = (p >> 24) as usize;
                wr.put(tabs[0].1[g], tabs[0].0[g] as u32);
                wr.put(tabs[1].1[r], tabs[1].0[r] as u32);
                wr.put(tabs[2].1[b], tabs[2].0[b] as u32);
                wr.put(tabs[3].1[a], tabs[3].0[a] as u32);
            }
            Sym::Copy { len, dist } => {
                let (p, eb, ev) = prefix_encode(*len);
                let s = 256 + p as usize;
                wr.put(tabs[0].1[s], tabs[0].0[s] as u32);
                wr.put(ev, eb);
                let (p, eb, ev) = prefix_encode(dist + 120);
                wr.put(tabs[4].1[p as usize], tabs[4].0[p as usize] as u32);
                wr.put(ev, eb);
            }
        }
    }
    wr.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roundtrip(w: usize, h: usize, rgba: &[u8]) {
        let enc = encode(w, h, rgba);
        let (w2, h2, back) = decode(&enc).unwrap();
        assert_eq!((w2, h2), (w, h));
        for (i, (a, b)) in rgba.chunks_exact(4).zip(back.chunks_exact(4)).enumerate() {
            if a[3] == 0 {
                assert_eq!(b[3], 0, "pixel {}", i);
            } else {
                assert_eq!(a, b, "pixel {}", i);
            }
        }
    }

    #[test]
    fn lossless_roundtrips() {
        roundtrip(1, 1, &[10, 20, 30, 255]);
        roundtrip(3, 2, &[1, 2, 3, 255, 1, 2, 3, 255, 9, 9, 9, 0, 255, 0, 0, 128, 0, 0, 0, 255, 7, 7, 7, 7]);
        let mut big = Vec::new();
        for y in 0..97 {
            for x in 0..131 {
                big.extend_from_slice(&[(x * 2) as u8, (y * 3) as u8, ((x ^ y) & 0xff) as u8, if (x / 10 + y / 10) % 3 == 0 { 0 } else { 255 }]);
            }
        }
        roundtrip(131, 97, &big);
        let flat = vec![200u8; 64 * 64 * 4];
        roundtrip(64, 64, &flat);
        let enc = encode(64, 64, &flat);
        assert!(enc.len() < 200, "a flat picture is small: {}", enc.len());
    }

    #[test]
    fn prefix_values() {
        for v in 1..5000u32 {
            let (p, eb, ev) = prefix_encode(v);
            let mut wr = BitWriter::new();
            wr.put(ev, eb);
            let bytes = wr.finish();
            let mut b = Bits::new(&bytes);
            assert_eq!(prefix_value(&mut b, p), v);
        }
    }
}
