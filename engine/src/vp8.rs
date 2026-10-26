//! WebP lossy (a VP8 key frame, RFC 6386): the boolean decoder, frame header, modes and
//! coefficients, intra prediction, the inverse transforms, the loop filter, and YUV to RGB
//! with smooth ("fancy") chroma upsampling.

use crate::vp8_tables::{AC_QUANT, COEFF_PROBS, COEFF_UPDATE_PROBS, DC_QUANT, KEYFRAME_BPRED_MODE_PROBS, PROB_DCT_CAT};

// ------------------------------------------------------------------ boolean decoder

struct BoolDec<'a> {
    d: &'a [u8],
    pos: usize,
    value: u32,
    range: u32,
    bits: i32,
}

impl<'a> BoolDec<'a> {
    fn new(d: &'a [u8]) -> Self {
        let mut b = BoolDec { d, pos: 0, value: 0, range: 255, bits: -8 };
        // two bytes up front
        b.value = (b.byte() << 8) | b.byte();
        b.bits = 0;
        b
    }

    fn byte(&mut self) -> u32 {
        let v = if self.pos < self.d.len() { self.d[self.pos] } else { 0 };
        self.pos += 1;
        v as u32
    }

    fn bool(&mut self, prob: u8) -> bool {
        let split = 1 + (((self.range - 1) * prob as u32) >> 8);
        let big = split << 8;
        let r = if self.value >= big {
            self.range -= split;
            self.value -= big;
            true
        } else {
            self.range = split;
            false
        };
        while self.range < 128 {
            self.value <<= 1;
            self.range <<= 1;
            self.bits += 1;
            if self.bits == 8 {
                self.bits = 0;
                self.value |= self.byte();
            }
        }
        r
    }

    fn lit(&mut self, n: u32) -> u32 {
        let mut v = 0;
        for _ in 0..n {
            v = (v << 1) | self.bool(128) as u32;
        }
        v
    }

    fn flag(&mut self) -> bool {
        self.bool(128)
    }

    /// An n-bit magnitude then a sign, when its presence flag is set.
    fn opt_signed(&mut self, n: u32) -> i32 {
        if !self.flag() {
            return 0;
        }
        let v = self.lit(n) as i32;
        if self.flag() { -v } else { v }
    }

    fn tree(&mut self, tree: &[i8], probs: &[u8]) -> i8 {
        let mut i = 0usize;
        loop {
            let b = self.bool(probs[i >> 1]) as usize;
            let n = tree[i + b];
            if n <= 0 {
                return -n;
            }
            i = n as usize;
        }
    }
}

// ------------------------------------------------------------------ modes

const DC: i8 = 0;
const V: i8 = 1;
const H: i8 = 2;
const TM: i8 = 3;
const B: i8 = 4;

// sub-block modes
const B_DC: i8 = 0;
const B_TM: i8 = 1;
const B_VE: i8 = 2;
const B_HE: i8 = 3;
const B_LD: i8 = 4;
const B_RD: i8 = 5;
const B_VR: i8 = 6;
const B_VL: i8 = 7;
const B_HD: i8 = 8;
const B_HU: i8 = 9;

const YMODE_TREE: [i8; 8] = [-B, 2, 4, 6, -DC, -V, -H, -TM];
const YMODE_PROBS: [u8; 4] = [145, 156, 163, 128];
const UVMODE_TREE: [i8; 6] = [-DC, 2, -V, 4, -H, -TM];
const UVMODE_PROBS: [u8; 3] = [142, 114, 183];
const BMODE_TREE: [i8; 18] = [-B_DC, 2, -B_TM, 4, -B_VE, 6, 8, 12, -B_HE, 10, -B_RD, -B_VR, -B_LD, 14, -B_VL, 16, -B_HD, -B_HU];
const SEGMENT_TREE: [i8; 6] = [2, 4, -0, -1, -2, -3];

// tokens
const EOB: i8 = 11;
const TOKEN_TREE: [i8; 22] = [-EOB, 2, -0, 4, -1, 6, 8, 12, -2, 10, -3, -4, 14, 16, -5, -6, 18, 20, -7, -8, -9, -10];
const CAT_BASE: [i32; 6] = [5, 7, 11, 19, 35, 67];
const ZIGZAG: [usize; 16] = [0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15];
const BANDS: [usize; 17] = [0, 1, 2, 3, 6, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 7, 0];

#[derive(Clone, Copy, Default)]
struct Quant {
    y_dc: i32,
    y_ac: i32,
    y2_dc: i32,
    y2_ac: i32,
    uv_dc: i32,
    uv_ac: i32,
}

#[derive(Clone, Copy)]
struct Mb {
    ymode: i8,
    uvmode: i8,
    bmodes: [i8; 16],
    segment: usize,
    skip: bool,
    has_coeffs: bool,
}

struct Header {
    segmentation: bool,
    seg_absolute: bool,
    seg_quant: [i32; 4],
    seg_lf: [i32; 4],
    seg_probs: [u8; 3],
    update_map: bool,
    simple_filter: bool,
    filter_level: i32,
    sharpness: i32,
    lf_adjust: bool,
    ref_delta0: i32,
    mode_delta0: i32,
    quants: [Quant; 4],
    probs: [[[[u8; 11]; 3]; 8]; 4],
    skip_prob: Option<u8>,
}

fn q(table: &[i16; 128], i: i32) -> i32 {
    table[i.clamp(0, 127) as usize] as i32
}

fn parse_header(bd: &mut BoolDec) -> Header {
    let _color_space = bd.flag();
    let _clamp = bd.flag();
    let mut hd = Header {
        segmentation: false,
        seg_absolute: false,
        seg_quant: [0; 4],
        seg_lf: [0; 4],
        seg_probs: [255; 3],
        update_map: false,
        simple_filter: false,
        filter_level: 0,
        sharpness: 0,
        lf_adjust: false,
        ref_delta0: 0,
        mode_delta0: 0,
        quants: [Quant::default(); 4],
        probs: COEFF_PROBS,
        skip_prob: None,
    };
    hd.segmentation = bd.flag();
    if hd.segmentation {
        hd.update_map = bd.flag();
        let update_data = bd.flag();
        if update_data {
            hd.seg_absolute = bd.flag();
            for i in 0..4 {
                hd.seg_quant[i] = bd.opt_signed(7);
            }
            for i in 0..4 {
                hd.seg_lf[i] = bd.opt_signed(6);
            }
        }
        if hd.update_map {
            for i in 0..3 {
                hd.seg_probs[i] = if bd.flag() { bd.lit(8) as u8 } else { 255 };
            }
        }
    }
    hd.simple_filter = bd.flag();
    hd.filter_level = bd.lit(6) as i32;
    hd.sharpness = bd.lit(3) as i32;
    hd.lf_adjust = bd.flag();
    if hd.lf_adjust && bd.flag() {
        for i in 0..4 {
            let v = bd.opt_signed(6);
            if i == 0 {
                hd.ref_delta0 = v;
            }
        }
        for i in 0..4 {
            let v = bd.opt_signed(6);
            if i == 0 {
                hd.mode_delta0 = v;
            }
        }
    }
    hd
}

struct Frame {
    // planes with their reconstructed pixels (whole macroblocks)
    y: Vec<u8>,
    u: Vec<u8>,
    v: Vec<u8>,
    mbw: usize,
}

// ------------------------------------------------------------------ the decode

pub fn is_vp8(d: &[u8]) -> bool {
    d.len() >= 10 && d[0] & 1 == 0 && d[3] == 0x9d && d[4] == 0x01 && d[5] == 0x2a
}

/// A VP8 key frame: (width, height, RGBA with opaque alpha).
pub fn decode(d: &[u8]) -> Result<(usize, usize, Vec<u8>), String> {
    let f = decode_yuv(d)?;
    let (w, h) = (f.0, f.1);
    Ok((w, h, yuv_to_rgba(&f.2, w, h)))
}

fn decode_yuv(d: &[u8]) -> Result<(usize, usize, Frame), String> {
    if d.len() < 10 {
        return Err("WebP: truncated lossy image".into());
    }
    let tag = d[0] as u32 | (d[1] as u32) << 8 | (d[2] as u32) << 16;
    if tag & 1 != 0 {
        return Err("WebP: not a key frame".into());
    }
    let first_size = (tag >> 5) as usize;
    if d[3] != 0x9d || d[4] != 0x01 || d[5] != 0x2a {
        return Err("WebP: bad lossy start code".into());
    }
    let w = (d[6] as usize | (d[7] as usize) << 8) & 0x3fff;
    let h = (d[8] as usize | (d[9] as usize) << 8) & 0x3fff;
    if w == 0 || h == 0 {
        return Err("WebP: empty picture".into());
    }
    if w * h > 100_000_000 {
        return Err("WebP: image is too large".into());
    }
    let p0 = 10;
    if p0 + first_size > d.len() {
        return Err("WebP: truncated first partition".into());
    }
    let mut bd = BoolDec::new(&d[p0..p0 + first_size]);
    let mut hd = parse_header(&mut bd);
    // DCT token partitions
    let nparts = 1usize << bd.lit(2);
    let mut parts = Vec::with_capacity(nparts);
    let sizes_at = p0 + first_size;
    let mut at = sizes_at + 3 * (nparts - 1);
    if at > d.len() {
        return Err("WebP: truncated partitions".into());
    }
    for k in 0..nparts {
        let size = if k + 1 < nparts {
            let o = sizes_at + 3 * k;
            d[o] as usize | (d[o + 1] as usize) << 8 | (d[o + 2] as usize) << 16
        } else {
            d.len().saturating_sub(at)
        };
        let end = (at + size).min(d.len());
        parts.push(BoolDec::new(&d[at.min(d.len())..end]));
        at = end;
    }
    // quantisers
    let base = bd.lit(7) as i32;
    let ydc_d = bd.opt_signed(4);
    let y2dc_d = bd.opt_signed(4);
    let y2ac_d = bd.opt_signed(4);
    let uvdc_d = bd.opt_signed(4);
    let uvac_d = bd.opt_signed(4);
    for s in 0..4 {
        let qi = if hd.segmentation { if hd.seg_absolute { hd.seg_quant[s] } else { base + hd.seg_quant[s] } } else { base };
        hd.quants[s] = Quant {
            y_dc: q(&DC_QUANT, qi + ydc_d),
            y_ac: q(&AC_QUANT, qi),
            y2_dc: q(&DC_QUANT, qi + y2dc_d) * 2,
            y2_ac: (q(&AC_QUANT, qi + y2ac_d) * 155 / 100).max(8),
            uv_dc: q(&DC_QUANT, qi + uvdc_d).min(132),
            uv_ac: q(&AC_QUANT, qi + uvac_d),
        };
    }
    let _refresh_probs = bd.flag();
    for i in 0..4 {
        for j in 0..8 {
            for k in 0..3 {
                for l in 0..11 {
                    if bd.bool(COEFF_UPDATE_PROBS[i][j][k][l]) {
                        hd.probs[i][j][k][l] = bd.lit(8) as u8;
                    }
                }
            }
        }
    }
    hd.skip_prob = if bd.flag() { Some(bd.lit(8) as u8) } else { None };

    let mbw = (w + 15) / 16;
    let mbh = (h + 15) / 16;
    let mut fr = Frame { y: vec![0; mbw * 16 * mbh * 16], u: vec![0; mbw * 8 * mbh * 8], v: vec![0; mbw * 8 * mbh * 8], mbw };
    // what intra prediction reads: the row above (unfiltered), and the column to the left
    let mut top_y = vec![127u8; mbw * 16 + 4];
    let mut top_u = vec![127u8; mbw * 8];
    let mut top_v = vec![127u8; mbw * 8];
    let mut top_bmodes = vec![[B_DC; 4]; mbw];
    // non-zero contexts: [y2, y0..y3, u0, u1, v0, v1]
    let mut top_nz = vec![[0u8; 9]; mbw];
    for mby in 0..mbh {
        let mut left_y = [129u8; 17]; // [0] is the pixel above-left
        let mut left_u = [129u8; 9];
        let mut left_v = [129u8; 9];
        let mut left_bmodes = [B_DC; 4];
        let mut left_nz = [0u8; 9];
        let part = &mut parts[mby % nparts];
        let mut row_mbs: Vec<Mb> = Vec::with_capacity(mbw);
        for mbx in 0..mbw {
            // ---- modes (first partition)
            let segment = if hd.segmentation && hd.update_map { bd.tree(&SEGMENT_TREE, &hd.seg_probs) as usize } else { 0 };
            let skip = match hd.skip_prob {
                Some(p) => bd.bool(p),
                None => false,
            };
            let ymode = bd.tree(&YMODE_TREE, &YMODE_PROBS);
            let mut bmodes = [B_DC; 16];
            if ymode == B {
                for sy in 0..4 {
                    for sx in 0..4 {
                        let above = if sy == 0 { top_bmodes[mbx][sx] } else { bmodes[(sy - 1) * 4 + sx] };
                        let left = if sx == 0 { left_bmodes[sy] } else { bmodes[sy * 4 + sx - 1] };
                        bmodes[sy * 4 + sx] = bd.tree(&BMODE_TREE, &KEYFRAME_BPRED_MODE_PROBS[above as usize][left as usize]);
                    }
                }
            } else {
                let m = match ymode {
                    V => B_VE,
                    H => B_HE,
                    TM => B_TM,
                    _ => B_DC,
                };
                bmodes = [m; 16];
            }
            for k in 0..4 {
                top_bmodes[mbx][k] = bmodes[12 + k];
                left_bmodes[k] = bmodes[k * 4 + 3];
            }
            let uvmode = bd.tree(&UVMODE_TREE, &UVMODE_PROBS);
            let qn = hd.quants[segment];
            // ---- coefficients (this row's partition)
            let mut coeffs = [0i32; 384];
            let mut has_coeffs = false;
            if !skip {
                has_coeffs = read_residuals(part, &hd.probs, ymode, &qn, &mut coeffs, &mut top_nz[mbx], &mut left_nz);
            } else {
                // a skipped macroblock leaves zero contexts (the Y2 one only when it has Y2)
                let keep_y2 = ymode == B;
                for k in 0..9 {
                    if k == 0 && keep_y2 {
                        continue;
                    }
                    top_nz[mbx][k] = 0;
                    left_nz[k] = 0;
                }
            }
            let mb = Mb { ymode, uvmode, bmodes, segment, skip, has_coeffs };
            // ---- prediction and residue
            reconstruct_luma(&mut fr, mbx, mby, &mb, &coeffs, &mut top_y, &mut left_y);
            reconstruct_chroma(&mut fr, mbx, mby, &mb, &coeffs, &mut top_u, &mut left_u, &mut top_v, &mut left_v);
            row_mbs.push(mb);
        }
        // ---- loop filter for this row (prediction already used unfiltered pixels)
        for (mbx, mb) in row_mbs.iter().enumerate() {
            loop_filter(&mut fr, &hd, mbx, mby, mb);
        }
    }
    Ok((w, h, fr))
}

fn read_block(bd: &mut BoolDec, probs: &[[[u8; 11]; 3]; 8], first: usize, ctx: usize, dcq: i32, acq: i32, out: &mut [i32]) -> bool {
    let mut ctx = ctx;
    let mut after_zero = false;
    let mut any = false;
    let mut i = first;
    while i < 16 {
        let p = &probs[BANDS[i]][ctx];
        if !after_zero && !bd.bool(p[0]) {
            break; // end of block
        }
        if !bd.bool(p[1]) {
            // a zero
            after_zero = true;
            ctx = 0;
            any = true;
            i += 1;
            continue;
        }
        // the rest of the token tree, from the node after "not zero"
        let mut n = 4usize;
        let tok = loop {
            let b = bd.bool(p[n >> 1]) as usize;
            let t = TOKEN_TREE[n + b];
            if t <= 0 {
                break -t;
            }
            n = t as usize;
        };
        let mut v: i32 = match tok {
            1..=4 => tok as i32,
            5..=10 => {
                let cat = (tok - 5) as usize;
                let mut extra = 0i32;
                for &pp in PROB_DCT_CAT[cat].iter() {
                    if pp == 0 {
                        break;
                    }
                    extra = extra * 2 + bd.bool(pp) as i32;
                }
                CAT_BASE[cat] + extra
            }
            _ => 0,
        };
        ctx = if v == 0 { 0 } else if v == 1 { 1 } else { 2 };
        if bd.flag() {
            v = -v;
        }
        let z = ZIGZAG[i];
        out[z] = v * if z > 0 { acq } else { dcq };
        after_zero = false;
        any = true;
        i += 1;
    }
    any
}

fn read_residuals(bd: &mut BoolDec, probs: &[[[[u8; 11]; 3]; 8]; 4], ymode: i8, qn: &Quant, coeffs: &mut [i32; 384], top: &mut [u8; 9], left: &mut [u8; 9]) -> bool {
    let mut any = false;
    let mut first = 0;
    let ytype;
    if ymode != B {
        let mut y2 = [0i32; 16];
        let ctx = (top[0] + left[0]) as usize;
        let n = read_block(bd, &probs[1], 0, ctx, qn.y2_dc, qn.y2_ac, &mut y2);
        top[0] = n as u8;
        left[0] = n as u8;
        any |= n;
        iwht(&mut y2);
        for k in 0..16 {
            coeffs[k * 16] = y2[k];
        }
        first = 1;
        ytype = 0;
    } else {
        ytype = 3;
    }
    for sy in 0..4 {
        for sx in 0..4 {
            let ctx = (top[1 + sx] + left[1 + sy]) as usize;
            let k = sy * 4 + sx;
            let n = read_block(bd, &probs[ytype], first, ctx, qn.y_dc, qn.y_ac, &mut coeffs[k * 16..k * 16 + 16]);
            top[1 + sx] = n as u8;
            left[1 + sy] = n as u8;
            any |= n;
        }
    }
    for (pl, base) in [(0usize, 16usize), (1, 20)] {
        for sy in 0..2 {
            for sx in 0..2 {
                let ti = 5 + pl * 2 + sx;
                let li = 5 + pl * 2 + sy;
                let ctx = (top[ti] + left[li]) as usize;
                let k = base + sy * 2 + sx;
                let n = read_block(bd, &probs[2], 0, ctx, qn.uv_dc, qn.uv_ac, &mut coeffs[k * 16..k * 16 + 16]);
                top[ti] = n as u8;
                left[li] = n as u8;
                any |= n;
            }
        }
    }
    any
}

// ------------------------------------------------------------------ transforms

fn iwht(b: &mut [i32; 16]) {
    let mut t = [0i32; 16];
    for i in 0..4 {
        let a1 = b[i] + b[12 + i];
        let b1 = b[4 + i] + b[8 + i];
        let c1 = b[4 + i] - b[8 + i];
        let d1 = b[i] - b[12 + i];
        t[i] = a1 + b1;
        t[4 + i] = c1 + d1;
        t[8 + i] = a1 - b1;
        t[12 + i] = d1 - c1;
    }
    for i in 0..4 {
        let r = &t[i * 4..i * 4 + 4];
        let a1 = r[0] + r[3];
        let b1 = r[1] + r[2];
        let c1 = r[1] - r[2];
        let d1 = r[0] - r[3];
        b[i * 4] = (a1 + b1 + 3) >> 3;
        b[i * 4 + 1] = (c1 + d1 + 3) >> 3;
        b[i * 4 + 2] = (a1 - b1 + 3) >> 3;
        b[i * 4 + 3] = (d1 - c1 + 3) >> 3;
    }
}

fn idct_add(c: &[i32], dst: &mut [u8], at: usize, stride: usize) {
    const K1: i64 = 20091; // cos(pi/8)*sqrt(2) - 1, in 16 bits
    const K2: i64 = 35468; // sin(pi/8)*sqrt(2)
    if c.iter().all(|&v| v == 0) {
        return;
    }
    let mut t = [0i64; 16];
    for i in 0..4 {
        let (c0, c1, c2, c3) = (c[i] as i64, c[4 + i] as i64, c[8 + i] as i64, c[12 + i] as i64);
        let a = c0 + c2;
        let b = c0 - c2;
        let cc = ((c1 * K2) >> 16) - (c3 + ((c3 * K1) >> 16));
        let dd = (c1 + ((c1 * K1) >> 16)) + ((c3 * K2) >> 16);
        t[i] = a + dd;
        t[4 + i] = b + cc;
        t[8 + i] = b - cc;
        t[12 + i] = a - dd;
    }
    for r in 0..4 {
        let (c0, c1, c2, c3) = (t[r * 4], t[r * 4 + 1], t[r * 4 + 2], t[r * 4 + 3]);
        let a = c0 + c2;
        let b = c0 - c2;
        let cc = ((c1 * K2) >> 16) - (c3 + ((c3 * K1) >> 16));
        let dd = (c1 + ((c1 * K1) >> 16)) + ((c3 * K2) >> 16);
        let out = [(a + dd + 4) >> 3, (b + cc + 4) >> 3, (b - cc + 4) >> 3, (a - dd + 4) >> 3];
        for (k, &o) in out.iter().enumerate() {
            let p = &mut dst[at + r * stride + k];
            *p = (*p as i64 + o).clamp(0, 255) as u8;
        }
    }
}

// ------------------------------------------------------------------ prediction

fn avg2(a: u8, b: u8) -> u8 {
    ((a as u16 + b as u16 + 1) >> 1) as u8
}

fn avg3(a: u8, b: u8, c: u8) -> u8 {
    ((a as u16 + 2 * b as u16 + c as u16 + 2) >> 2) as u8
}

/// A work area: a row of pixels above (with 4 beyond for 4x4 prediction), a column on the
/// left, the corner, and the block itself, all in one grid of `stride` columns.
fn predict_block(ws: &mut [u8], stride: usize, size: usize, mode: i8, have_above: bool, have_left: bool) {
    let at = |r: usize, c: usize| r * stride + c; // r, c from the corner (0, 0)
    match mode {
        DC => {
            let mut sum = 0u32;
            let mut n = 0;
            if have_above {
                for c in 1..=size {
                    sum += ws[at(0, c)] as u32;
                }
                n += size;
            }
            if have_left {
                for r in 1..=size {
                    sum += ws[at(r, 0)] as u32;
                }
                n += size;
            }
            let v = if n == 0 { 128 } else { ((sum + n as u32 / 2) / n as u32) as u8 };
            for r in 1..=size {
                for c in 1..=size {
                    ws[at(r, c)] = v;
                }
            }
        }
        V => {
            for r in 1..=size {
                for c in 1..=size {
                    ws[at(r, c)] = ws[at(0, c)];
                }
            }
        }
        H => {
            for r in 1..=size {
                let v = ws[at(r, 0)];
                for c in 1..=size {
                    ws[at(r, c)] = v;
                }
            }
        }
        _ => {
            // TrueMotion
            let p = ws[at(0, 0)] as i32;
            for r in 1..=size {
                let l = ws[at(r, 0)] as i32;
                for c in 1..=size {
                    ws[at(r, c)] = (l + ws[at(0, c)] as i32 - p).clamp(0, 255) as u8;
                }
            }
        }
    }
}

/// One 4x4 sub-block predicted in place at (r0, c0) of the work area (its top-left pixel).
fn predict_sub(ws: &mut [u8], stride: usize, r0: usize, c0: usize, mode: i8) {
    // edge: L3 L2 L1 L0 P A0 A1 A2 A3 A4 A5 A6 A7
    let mut e = [0u8; 13];
    for k in 0..4 {
        e[3 - k] = ws[(r0 + k) * stride + c0 - 1];
    }
    e[4] = ws[(r0 - 1) * stride + c0 - 1];
    for k in 0..8 {
        e[5 + k] = ws[(r0 - 1) * stride + c0 + k];
    }
    let (l, p, a) = ([e[3], e[2], e[1], e[0]], e[4], &e[5..13]);
    let mut b = [[0u8; 4]; 4];
    match mode {
        B_DC => {
            let s: u32 = a[..4].iter().map(|&v| v as u32).sum::<u32>() + l.iter().map(|&v| v as u32).sum::<u32>();
            b = [[((s + 4) >> 3) as u8; 4]; 4];
        }
        B_TM => {
            for r in 0..4 {
                for c in 0..4 {
                    b[r][c] = (l[r] as i32 + a[c] as i32 - p as i32).clamp(0, 255) as u8;
                }
            }
        }
        B_VE => {
            let row = [avg3(p, a[0], a[1]), avg3(a[0], a[1], a[2]), avg3(a[1], a[2], a[3]), avg3(a[2], a[3], a[4])];
            b = [row; 4];
        }
        B_HE => {
            let col = [avg3(p, l[0], l[1]), avg3(l[0], l[1], l[2]), avg3(l[1], l[2], l[3]), avg3(l[2], l[3], l[3])];
            for r in 0..4 {
                b[r] = [col[r]; 4];
            }
        }
        B_LD => {
            for r in 0..4 {
                for c in 0..4 {
                    let i = r + c;
                    b[r][c] = if i == 6 { avg3(a[6], a[7], a[7]) } else { avg3(a[i], a[i + 1], a[i + 2]) };
                }
            }
        }
        B_RD => {
            // along the edge from the bottom of the left column round to the top right
            for r in 0..4 {
                for c in 0..4 {
                    let i = 3 - r + c; // index into e[0..9]
                    b[r][c] = avg3(e[i], e[i + 1], e[i + 2]);
                }
            }
        }
        B_VR => {
            b[3][0] = avg3(e[1], e[2], e[3]);
            b[2][0] = avg3(e[2], e[3], e[4]);
            b[3][1] = avg3(e[3], e[4], e[5]);
            b[1][0] = b[3][1];
            b[2][1] = avg2(e[4], e[5]);
            b[0][0] = b[2][1];
            b[3][2] = avg3(e[4], e[5], e[6]);
            b[1][1] = b[3][2];
            b[2][2] = avg2(e[5], e[6]);
            b[0][1] = b[2][2];
            b[3][3] = avg3(e[5], e[6], e[7]);
            b[1][2] = b[3][3];
            b[2][3] = avg2(e[6], e[7]);
            b[0][2] = b[2][3];
            b[1][3] = avg3(e[6], e[7], e[8]);
            b[0][3] = avg2(e[7], e[8]);
        }
        B_VL => {
            b[0][0] = avg2(a[0], a[1]);
            b[1][0] = avg3(a[0], a[1], a[2]);
            b[2][0] = avg2(a[1], a[2]);
            b[0][1] = b[2][0];
            b[1][1] = avg3(a[1], a[2], a[3]);
            b[3][0] = b[1][1];
            b[2][1] = avg2(a[2], a[3]);
            b[0][2] = b[2][1];
            b[3][1] = avg3(a[2], a[3], a[4]);
            b[1][2] = b[3][1];
            b[2][2] = avg2(a[3], a[4]);
            b[0][3] = b[2][2];
            b[3][2] = avg3(a[3], a[4], a[5]);
            b[1][3] = b[3][2];
            b[2][3] = avg3(a[4], a[5], a[6]);
            b[3][3] = avg3(a[5], a[6], a[7]);
        }
        B_HD => {
            b[3][0] = avg2(e[0], e[1]);
            b[3][1] = avg3(e[0], e[1], e[2]);
            b[2][0] = avg2(e[1], e[2]);
            b[3][2] = b[2][0];
            b[2][1] = avg3(e[1], e[2], e[3]);
            b[3][3] = b[2][1];
            b[2][2] = avg2(e[2], e[3]);
            b[1][0] = b[2][2];
            b[2][3] = avg3(e[2], e[3], e[4]);
            b[1][1] = b[2][3];
            b[1][2] = avg2(e[3], e[4]);
            b[0][0] = b[1][2];
            b[1][3] = avg3(e[3], e[4], e[5]);
            b[0][1] = b[1][3];
            b[0][2] = avg3(e[4], e[5], e[6]);
            b[0][3] = avg3(e[5], e[6], e[7]);
        }
        _ => {
            // B_HU
            b[0][0] = avg2(l[0], l[1]);
            b[0][1] = avg3(l[0], l[1], l[2]);
            b[0][2] = avg2(l[1], l[2]);
            b[1][0] = b[0][2];
            b[0][3] = avg3(l[1], l[2], l[3]);
            b[1][1] = b[0][3];
            b[1][2] = avg2(l[2], l[3]);
            b[2][0] = b[1][2];
            b[1][3] = avg3(l[2], l[3], l[3]);
            b[2][1] = b[1][3];
            b[2][2] = l[3];
            b[2][3] = l[3];
            b[3] = [l[3]; 4];
        }
    }
    for r in 0..4 {
        for c in 0..4 {
            ws[(r0 + r) * stride + c0 + c] = b[r][c];
        }
    }
}

fn reconstruct_luma(fr: &mut Frame, mbx: usize, mby: usize, mb: &Mb, coeffs: &[i32; 384], top: &mut [u8], left: &mut [u8; 17]) {
    const S: usize = 1 + 16 + 4;
    let mut ws = [0u8; S * 17];
    // above (and 4 beyond), left, corner
    if mby == 0 {
        for c in 1..S {
            ws[c] = 127;
        }
    } else {
        ws[1..17].copy_from_slice(&top[mbx * 16..mbx * 16 + 16]);
        if mbx + 1 == fr.mbw {
            let last = top[mbx * 16 + 15];
            for c in 17..S {
                ws[c] = last;
            }
        } else {
            ws[17..S].copy_from_slice(&top[mbx * 16 + 16..mbx * 16 + 20]);
        }
    }
    // the sub-blocks on the right read the macroblock's above-right pixels on every row of them
    for r in [4usize, 8, 12] {
        for c in 17..S {
            ws[r * S + c] = ws[c];
        }
    }
    for r in 0..16 {
        ws[(r + 1) * S] = if mbx == 0 { 129 } else { left[1 + r] };
    }
    ws[0] = if mby == 0 { 127 } else if mbx == 0 { 129 } else { left[0] };
    if mb.ymode == B {
        for sy in 0..4 {
            for sx in 0..4 {
                let k = sy * 4 + sx;
                predict_sub(&mut ws, S, 1 + sy * 4, 1 + sx * 4, mb.bmodes[k]);
                idct_add(&coeffs[k * 16..k * 16 + 16], &mut ws, (1 + sy * 4) * S + 1 + sx * 4, S);
            }
        }
    } else {
        predict_block(&mut ws, S, 16, mb.ymode, mby > 0, mbx > 0);
        for k in 0..16 {
            let (sy, sx) = (k / 4, k % 4);
            idct_add(&coeffs[k * 16..k * 16 + 16], &mut ws, (1 + sy * 4) * S + 1 + sx * 4, S);
        }
    }
    // what the next macroblocks read
    left[0] = ws[16];
    for r in 0..16 {
        left[1 + r] = ws[(r + 1) * S + 16];
    }
    top[mbx * 16..mbx * 16 + 16].copy_from_slice(&ws[16 * S + 1..16 * S + 17]);
    let yw = fr.mbw * 16;
    for r in 0..16 {
        let o = (mby * 16 + r) * yw + mbx * 16;
        fr.y[o..o + 16].copy_from_slice(&ws[(r + 1) * S + 1..(r + 1) * S + 17]);
    }
}

#[allow(clippy::too_many_arguments)]
fn reconstruct_chroma(fr: &mut Frame, mbx: usize, mby: usize, mb: &Mb, coeffs: &[i32; 384], top_u: &mut [u8], left_u: &mut [u8; 9], top_v: &mut [u8], left_v: &mut [u8; 9]) {
    const S: usize = 9;
    let cw = fr.mbw * 8;
    for (plane, base) in [(0usize, 16usize), (1, 20)] {
        let (top, left) = if plane == 0 { (&mut *top_u, &mut *left_u) } else { (&mut *top_v, &mut *left_v) };
        let mut ws = [0u8; S * S];
        if mby == 0 {
            for c in 1..S {
                ws[c] = 127;
            }
        } else {
            ws[1..9].copy_from_slice(&top[mbx * 8..mbx * 8 + 8]);
        }
        for r in 0..8 {
            ws[(r + 1) * S] = if mbx == 0 { 129 } else { left[1 + r] };
        }
        ws[0] = if mby == 0 { 127 } else if mbx == 0 { 129 } else { left[0] };
        predict_block(&mut ws, S, 8, mb.uvmode, mby > 0, mbx > 0);
        for k in 0..4 {
            let (sy, sx) = (k / 2, k % 2);
            let ci = base + k;
            idct_add(&coeffs[ci * 16..ci * 16 + 16], &mut ws, (1 + sy * 4) * S + 1 + sx * 4, S);
        }
        left[0] = ws[8];
        for r in 0..8 {
            left[1 + r] = ws[(r + 1) * S + 8];
        }
        top[mbx * 8..mbx * 8 + 8].copy_from_slice(&ws[8 * S + 1..8 * S + 9]);
        let dst = if plane == 0 { &mut fr.u } else { &mut fr.v };
        for r in 0..8 {
            let o = (mby * 8 + r) * cw + mbx * 8;
            dst[o..o + 8].copy_from_slice(&ws[(r + 1) * S + 1..(r + 1) * S + 9]);
        }
    }
}

// ------------------------------------------------------------------ loop filter

fn s8(v: u8) -> i32 {
    v as i32 - 128
}

fn u8c(v: i32) -> u8 {
    (v.clamp(-128, 127) + 128) as u8
}

fn c8(v: i32) -> i32 {
    v.clamp(-128, 127)
}

/// The pixels across an edge: p3 p2 p1 p0 | q0 q1 q2 q3, at `at` (q0) stepping by `step`.
struct Edge<'a> {
    px: &'a mut [u8],
    at: usize,
    step: isize,
}

impl Edge<'_> {
    fn g(&self, k: isize) -> u8 {
        self.px[(self.at as isize + k * self.step) as usize]
    }
    fn s(&mut self, k: isize, v: u8) {
        let i = (self.at as isize + k * self.step) as usize;
        self.px[i] = v;
    }
    fn simple_ok(&self, limit: i32) -> bool {
        (self.g(-1) as i32 - self.g(0) as i32).abs() * 2 + (self.g(-2) as i32 - self.g(1) as i32).abs() / 2 <= limit
    }
    fn normal_ok(&self, interior: i32, edge: i32) -> bool {
        self.simple_ok(edge)
            && (self.g(-4) as i32 - self.g(-3) as i32).abs() <= interior
            && (self.g(-3) as i32 - self.g(-2) as i32).abs() <= interior
            && (self.g(-2) as i32 - self.g(-1) as i32).abs() <= interior
            && (self.g(3) as i32 - self.g(2) as i32).abs() <= interior
            && (self.g(2) as i32 - self.g(1) as i32).abs() <= interior
            && (self.g(1) as i32 - self.g(0) as i32).abs() <= interior
    }
    fn hev(&self, t: i32) -> bool {
        (self.g(-2) as i32 - self.g(-1) as i32).abs() > t || (self.g(1) as i32 - self.g(0) as i32).abs() > t
    }
    /// The common adjustment of p0 and q0; returns a.
    fn common(&mut self, outer: bool) -> i32 {
        let (p1, p0, q0, q1) = (s8(self.g(-2)), s8(self.g(-1)), s8(self.g(0)), s8(self.g(1)));
        let a = c8((if outer { c8(p1 - q1) } else { 0 }) + 3 * (q0 - p0));
        let b = c8(a + 3) >> 3;
        let a = c8(a + 4) >> 3;
        self.s(0, u8c(q0 - a));
        self.s(-1, u8c(p0 + b));
        a
    }
    fn simple(&mut self, limit: i32) {
        if self.simple_ok(limit) {
            self.common(true);
        }
    }
    fn subblock(&mut self, hev_t: i32, interior: i32, edge: i32) {
        if self.normal_ok(interior, edge) {
            let hv = self.hev(hev_t);
            let a = (self.common(hv) + 1) >> 1;
            if !hv {
                let (q1, p1) = (s8(self.g(1)), s8(self.g(-2)));
                self.s(1, u8c(q1 - a));
                self.s(-2, u8c(p1 + a));
            }
        }
    }
    fn macroblock(&mut self, hev_t: i32, interior: i32, edge: i32) {
        if self.normal_ok(interior, edge) {
            if !self.hev(hev_t) {
                let (p2, p1, p0, q0, q1, q2) = (s8(self.g(-3)), s8(self.g(-2)), s8(self.g(-1)), s8(self.g(0)), s8(self.g(1)), s8(self.g(2)));
                let w = c8(c8(p1 - q1) + 3 * (q0 - p0));
                let a = c8((27 * w + 63) >> 7);
                self.s(0, u8c(q0 - a));
                self.s(-1, u8c(p0 + a));
                let a = c8((18 * w + 63) >> 7);
                self.s(1, u8c(q1 - a));
                self.s(-2, u8c(p1 + a));
                let a = c8((9 * w + 63) >> 7);
                self.s(2, u8c(q2 - a));
                self.s(-3, u8c(p2 + a));
            } else {
                self.common(true);
            }
        }
    }
}

fn loop_filter(fr: &mut Frame, hd: &Header, mbx: usize, mby: usize, mb: &Mb) {
    if hd.filter_level == 0 {
        return;
    }
    let mut level = hd.filter_level;
    if hd.segmentation {
        level = if hd.seg_absolute { hd.seg_lf[mb.segment] } else { level + hd.seg_lf[mb.segment] };
    }
    level = level.clamp(0, 63);
    if hd.lf_adjust {
        level += hd.ref_delta0;
        if mb.ymode == B {
            level += hd.mode_delta0;
        }
    }
    let level = level.clamp(0, 63);
    if level == 0 {
        return;
    }
    let mut interior = level;
    if hd.sharpness > 0 {
        interior >>= if hd.sharpness > 4 { 2 } else { 1 };
        interior = interior.min(9 - hd.sharpness);
    }
    let interior = interior.max(1);
    let hev_t = if level >= 40 { 2 } else if level >= 15 { 1 } else { 0 };
    let mb_edge = (level + 2) * 2 + interior;
    let sub_edge = level * 2 + interior;
    let inner = mb.ymode == B || !mb.skip || mb.has_coeffs;
    let inner = inner && (mb.ymode == B || mb.has_coeffs);
    let yw = fr.mbw * 16;
    let cw = fr.mbw * 8;
    let (x0, y0) = (mbx * 16, mby * 16);
    let (cx0, cy0) = (mbx * 8, mby * 8);
    // the left edge, then inner vertical edges, then the top edge, then inner horizontal edges
    if mbx > 0 {
        for r in 0..16 {
            let mut e = Edge { px: &mut fr.y, at: (y0 + r) * yw + x0, step: 1 };
            if hd.simple_filter { e.simple(mb_edge) } else { e.macroblock(hev_t, interior, mb_edge) }
        }
        if !hd.simple_filter {
            for r in 0..8 {
                for plane in [&mut fr.u, &mut fr.v] {
                    Edge { px: plane, at: (cy0 + r) * cw + cx0, step: 1 }.macroblock(hev_t, interior, mb_edge);
                }
            }
        }
    }
    if inner {
        for c in [4usize, 8, 12] {
            for r in 0..16 {
                let mut e = Edge { px: &mut fr.y, at: (y0 + r) * yw + x0 + c, step: 1 };
                if hd.simple_filter { e.simple(sub_edge) } else { e.subblock(hev_t, interior, sub_edge) }
            }
        }
        if !hd.simple_filter {
            for r in 0..8 {
                for plane in [&mut fr.u, &mut fr.v] {
                    Edge { px: plane, at: (cy0 + r) * cw + cx0 + 4, step: 1 }.subblock(hev_t, interior, sub_edge);
                }
            }
        }
    }
    if mby > 0 {
        for c in 0..16 {
            let mut e = Edge { px: &mut fr.y, at: y0 * yw + x0 + c, step: yw as isize };
            if hd.simple_filter { e.simple(mb_edge) } else { e.macroblock(hev_t, interior, mb_edge) }
        }
        if !hd.simple_filter {
            for c in 0..8 {
                for plane in [&mut fr.u, &mut fr.v] {
                    Edge { px: plane, at: cy0 * cw + cx0 + c, step: cw as isize }.macroblock(hev_t, interior, mb_edge);
                }
            }
        }
    }
    if inner {
        for r in [4usize, 8, 12] {
            for c in 0..16 {
                let mut e = Edge { px: &mut fr.y, at: (y0 + r) * yw + x0 + c, step: yw as isize };
                if hd.simple_filter { e.simple(sub_edge) } else { e.subblock(hev_t, interior, sub_edge) }
            }
        }
        if !hd.simple_filter {
            for c in 0..8 {
                for plane in [&mut fr.u, &mut fr.v] {
                    Edge { px: plane, at: (cy0 + 4) * cw + cx0 + c, step: cw as isize }.subblock(hev_t, interior, sub_edge);
                }
            }
        }
    }
}

// ------------------------------------------------------------------ colour

fn mulhi(v: u8, k: i32) -> i32 {
    (v as i32 * k) >> 8
}

fn clip6(v: i32) -> u8 {
    (v >> 6).clamp(0, 255) as u8
}

fn yuv_px(y: u8, u: u8, v: u8) -> [u8; 3] {
    [
        clip6(mulhi(y, 19077) + mulhi(v, 26149) - 14234),
        clip6(mulhi(y, 19077) - mulhi(u, 6419) - mulhi(v, 13320) + 8708),
        clip6(mulhi(y, 19077) + mulhi(u, 33050) - 17685),
    ]
}

/// Chroma upsampled smoothly: each pixel takes 9/16 of its nearest chroma sample, 3/16 of the
/// two beside it and 1/16 of the diagonal one.
fn yuv_to_rgba(fr: &Frame, w: usize, h: usize) -> Vec<u8> {
    let yw = fr.mbw * 16;
    let cw = fr.mbw * 8;
    let (chw, chh) = ((w + 1) / 2, (h + 1) / 2);
    let mut out = vec![0u8; w * h * 4];
    let sample = |pl: &[u8], x: usize, y: usize| -> i32 { pl[y * cw + x] as i32 };
    for y in 0..h {
        let cy = y / 2;
        let cy2 = if y % 2 == 0 { cy.saturating_sub(1) } else { (cy + 1).min(chh - 1) };
        let (cy2, cy) = if y == 0 { (0, 0) } else { (cy2, cy) };
        for x in 0..w {
            let cx = x / 2;
            let cx2 = if x % 2 == 0 { cx.saturating_sub(1) } else { (cx + 1).min(chw - 1) };
            let up = |pl: &[u8]| -> u8 {
                let v = 9 * sample(pl, cx, cy) + 3 * sample(pl, cx2, cy) + 3 * sample(pl, cx, cy2) + sample(pl, cx2, cy2);
                ((v + 8) >> 4) as u8
            };
            let (u, v) = (up(&fr.u), up(&fr.v));
            let rgb = yuv_px(fr.y[y * yw + x], u, v);
            let o = (y * w + x) * 4;
            out[o..o + 3].copy_from_slice(&rgb);
            out[o + 3] = 255;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transforms() {
        // a DC-only block spreads evenly
        let mut c = [0i32; 16];
        c[0] = 80;
        let mut px = [100u8; 16];
        idct_add(&c, &mut px, 0, 4);
        assert!(px.iter().all(|&v| v == 110), "{:?}", px);
        let mut w = [0i32; 16];
        w[0] = 24;
        iwht(&mut w);
        assert!(w.iter().all(|&v| v == 3), "{:?}", w);
    }

    #[test]
    fn colours() {
        assert_eq!(yuv_px(235, 128, 128), [255, 255, 255]);
        let k = yuv_px(16, 128, 128);
        assert!(k.iter().all(|&v| v <= 1), "{:?}", k);
    }
}
