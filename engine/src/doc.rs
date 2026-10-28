//! The Folio Draw document model: layers of straight-alpha RGBA, compositing with blend
//! modes, a floating selection, a selection mask, tile-based undo and every drawing tool.

use std::collections::HashMap;

pub const TILE: usize = 64;
pub const UNDO_BYTES_LIMIT: usize = 1536 << 20;
pub const UNDO_STEPS_LIMIT: usize = 200;

pub const BLEND_NORMAL: u8 = 0;
pub const BLEND_MULTIPLY: u8 = 1;
pub const BLEND_SCREEN: u8 = 2;
pub const BLEND_OVERLAY: u8 = 3;
pub const BLEND_DARKEN: u8 = 4;
pub const BLEND_LIGHTEN: u8 = 5;
pub const BLEND_DIFFERENCE: u8 = 6;
pub const BLEND_ADD: u8 = 7;
pub const BLEND_COUNT: u8 = 8;

pub const TOOL_BRUSH: u8 = 0;
pub const TOOL_PENCIL: u8 = 1;
pub const TOOL_ERASER: u8 = 2;
pub const TOOL_AIRBRUSH: u8 = 3;
pub const TOOL_CALLIGRAPHY: u8 = 4;
pub const TOOL_CALLIGRAPHY2: u8 = 5;
pub const TOOL_MARKER: u8 = 6;

#[derive(Clone)]
pub struct Layer {
    pub id: u32,
    pub name: String,
    pub px: Vec<u8>,
    pub opacity: f32,
    pub visible: bool,
    pub blend: u8,
    /// Animation frame duration in milliseconds (GIF frames); 0 = not set.
    pub delay_ms: u32,
    /// A text layer: what it was typed with (the app's own description, JSON); empty for pixels.
    pub text: String,
}

pub struct Float {
    pub src: Vec<u8>,
    pub sw: usize,
    pub sh: usize,
    pub x: i32,
    pub y: i32,
    pub w: usize,
    pub h: usize,
    pub cur: Vec<u8>,
    pub lifted: Option<u64>,
}

impl Float {
    pub(crate) fn refresh(&mut self) {
        self.cur = if self.w == self.sw && self.h == self.sh {
            self.src.clone()
        } else {
            resample(&self.src, self.sw, self.sh, self.w, self.h, true)
        };
    }
    pub(crate) fn rect(&self) -> (i64, i64, i64, i64) {
        (self.x as i64, self.y as i64, self.x as i64 + self.w as i64, self.y as i64 + self.h as i64)
    }
}

pub enum UndoKind {
    Tiles { layer_id: u32, tiles: Vec<(u32, Vec<u8>)> },
    Full { w: usize, h: usize, layers: Vec<Layer>, active: usize },
    Structure { order: Vec<u32>, active: usize, pool: Vec<Layer>, mods: Vec<(u32, Vec<u8>)> },
    Props { layer_id: u32, name: String, opacity: f32, visible: bool, blend: u8, delay_ms: u32 },
    /// A text layer typed again (or turned into pixels): its pixels and description before.
    Text { layer_id: u32, text: String, px: Vec<u8> },
}

pub struct UndoStep {
    pub id: u64,
    pub kind: UndoKind,
    pub bytes: usize,
    /// what the step did, for the History panel (set by the program after the step)
    pub label: String,
}

pub struct OpState {
    pub layer_id: u32,
    pub tiles: HashMap<u32, Vec<u8>>,
}

pub struct Stroke {
    tool: u8,
    size: f32,
    hard: f32,
    col: [f32; 4],
    last: Option<(f32, f32)>,
    carry: f32,
    bbox: Option<(usize, usize, usize, usize)>,
    rng: u64,
    // pen dynamics: how much pressure drives size and opacity (0..1), and whether tilt turns the nib
    pk_size: f32,
    pk_op: f32,
    tilt_nib: bool,
    pres: f32,
    last_pres: f32,
    tilt: (f32, f32),
    cur_pres: f32,
}

pub struct Doc {
    pub w: usize,
    pub h: usize,
    pub layers: Vec<Layer>,
    pub active: usize,
    next_id: u32,
    pub comp: Vec<u8>,
    dirty: Option<(usize, usize, usize, usize)>,
    pub sel: Option<Vec<u8>>,
    pub float: Option<Float>,
    undo: Vec<UndoStep>,
    redo: Vec<UndoStep>,
    undo_bytes: usize,
    next_step: u64,
    op: Option<OpState>,
    /// An adjustment being previewed on a floating selection: its pixels before.
    pub(crate) adj_float: Option<Vec<u8>>,
    pub(crate) adj_open: bool,
    /// Copy, Transparent selection and Fill look at every visible layer, not the active one.
    pub sample_all: bool,
    /// How the next selection combines with the current one: 0 replace, 1 add, 2 subtract,
    /// 3 intersect. Reset to replace after each selection.
    pub sel_mode: u8,
    stroke: Option<Stroke>,
    mask: Vec<u8>,
    pub changes: u64,
    /// Frames view: show only the active layer (display only; saving is unaffected).
    pub solo: bool,
    /// GIF loop count: -1 = play once (no loop extension), 0 = forever, n = repeat n times.
    pub gif_loop: i32,
    /// Set when an animation had more frames than memory allows; the rest were skipped.
    pub frames_truncated: bool,
    pub clip: Vec<u8>,
    pub clip_w: usize,
    pub clip_h: usize,
    /// An embroidery document: its settings (hoop, machine, fabric...), the app's JSON; empty otherwise.
    pub emb: String,
    /// Something the opener should tell the user about how the file came in (e.g. "psd-adjustments").
    pub note: String,
}

// ------------------------------------------------------------------ pixel math

#[inline]
fn load(p: &[u8]) -> [f32; 4] {
    [p[0] as f32 / 255.0, p[1] as f32 / 255.0, p[2] as f32 / 255.0, p[3] as f32 / 255.0]
}
#[inline]
fn store(p: &mut [u8], c: [f32; 4]) {
    if c[3] <= 0.0 {
        p.copy_from_slice(&[0, 0, 0, 0]);
        return;
    }
    for k in 0..4 {
        p[k] = (c[k].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
    }
}
/// Straight-alpha source-over.
#[inline]
fn over(d: [f32; 4], s: [f32; 4]) -> [f32; 4] {
    let sa = s[3];
    if sa <= 0.0 {
        return d;
    }
    let da = d[3];
    let oa = sa + da * (1.0 - sa);
    if oa <= 1e-6 {
        return [0.0; 4];
    }
    let k = da * (1.0 - sa);
    [(s[0] * sa + d[0] * k) / oa, (s[1] * sa + d[1] * k) / oa, (s[2] * sa + d[2] * k) / oa, oa]
}

#[inline]
fn blend_ch(mode: u8, b: f32, s: f32) -> f32 {
    match mode {
        BLEND_MULTIPLY => b * s,
        BLEND_SCREEN => b + s - b * s,
        BLEND_OVERLAY => {
            if b <= 0.5 {
                2.0 * b * s
            } else {
                1.0 - 2.0 * (1.0 - b) * (1.0 - s)
            }
        }
        BLEND_DARKEN => b.min(s),
        BLEND_LIGHTEN => b.max(s),
        BLEND_DIFFERENCE => (b - s).abs(),
        BLEND_ADD => (b + s).min(1.0),
        _ => s,
    }
}

/// Separable resampling in premultiplied space. `smooth` = tent filter that widens when
/// shrinking (area-correct), otherwise nearest neighbour.
pub fn resample(src: &[u8], sw: usize, sh: usize, dw: usize, dh: usize, smooth: bool) -> Vec<u8> {
    let mut out = vec![0u8; dw * dh * 4];
    if sw == 0 || sh == 0 || dw == 0 || dh == 0 {
        return out;
    }
    if !smooth {
        for y in 0..dh {
            let sy = ((y as f64 + 0.5) * sh as f64 / dh as f64) as usize;
            let sy = sy.min(sh - 1);
            for x in 0..dw {
                let sx = (((x as f64 + 0.5) * sw as f64 / dw as f64) as usize).min(sw - 1);
                out[(y * dw + x) * 4..(y * dw + x) * 4 + 4].copy_from_slice(&src[(sy * sw + sx) * 4..(sy * sw + sx) * 4 + 4]);
            }
        }
        return out;
    }
    fn weights(sn: usize, dn: usize) -> Vec<(usize, Vec<f32>)> {
        let scale = dn as f32 / sn as f32;
        let support = if scale < 1.0 { 1.0 / scale } else { 1.0 };
        (0..dn)
            .map(|i| {
                let c = (i as f32 + 0.5) / scale - 0.5;
                let lo = (c - support).floor() as i64;
                let hi = (c + support).ceil() as i64;
                let first = lo.max(0) as usize;
                let mut ws = Vec::new();
                let mut total = 0.0;
                for j in lo..=hi {
                    let wgt = (1.0 - ((j as f32 - c).abs() / support)).max(0.0);
                    let jj = j.clamp(0, sn as i64 - 1) as usize;
                    if wgt > 0.0 {
                        let idx = jj - first;
                        if ws.len() <= idx {
                            ws.resize(idx + 1, 0.0);
                        }
                        ws[idx] += wgt;
                        total += wgt;
                    }
                }
                if total > 0.0 {
                    for v in ws.iter_mut() {
                        *v /= total;
                    }
                }
                (first, ws)
            })
            .collect()
    }
    let wx = weights(sw, dw);
    let wy = weights(sh, dh);
    // premultiply source
    let pre: Vec<f32> = src
        .chunks_exact(4)
        .flat_map(|p| {
            let a = p[3] as f32 / 255.0;
            [p[0] as f32 / 255.0 * a, p[1] as f32 / 255.0 * a, p[2] as f32 / 255.0 * a, a]
        })
        .collect();
    let mut tmp = vec![0f32; dw * sh * 4];
    for y in 0..sh {
        for (x, (first, ws)) in wx.iter().enumerate() {
            let mut acc = [0f32; 4];
            for (k, &wg) in ws.iter().enumerate() {
                let s = (y * sw + first + k) * 4;
                for c in 0..4 {
                    acc[c] += pre[s + c] * wg;
                }
            }
            tmp[(y * dw + x) * 4..(y * dw + x) * 4 + 4].copy_from_slice(&acc);
        }
    }
    for (y, (first, ws)) in wy.iter().enumerate() {
        for x in 0..dw {
            let mut acc = [0f32; 4];
            for (k, &wg) in ws.iter().enumerate() {
                let s = ((first + k) * dw + x) * 4;
                for c in 0..4 {
                    acc[c] += tmp[s + c] * wg;
                }
            }
            let o = (y * dw + x) * 4;
            let a = acc[3];
            if a > 1e-6 {
                store(&mut out[o..o + 4], [acc[0] / a, acc[1] / a, acc[2] / a, a]);
            }
        }
    }
    out
}

// ------------------------------------------------------------------ polygon rasterising

pub type Pt = (f32, f32);

/// Non-zero-winding coverage of a set of contours inside the box (bx,by,bw,bh).
pub fn poly_coverage(contours: &[Vec<Pt>], bx: i64, by: i64, bw: usize, bh: usize, aa: bool) -> Vec<f32> {
    let mut cov = vec![0f32; bw * bh];
    let mut edges: Vec<(f32, f32, f32, f32, i32)> = Vec::new();
    for c in contours {
        let n = c.len();
        if n < 2 {
            continue;
        }
        for i in 0..n {
            let a = c[i];
            let b = c[(i + 1) % n];
            if (a.1 - b.1).abs() < 1e-9 {
                continue;
            }
            if a.1 < b.1 {
                edges.push((a.0, a.1, b.0, b.1, 1));
            } else {
                edges.push((b.0, b.1, a.0, a.1, -1));
            }
        }
    }
    if edges.is_empty() {
        return cov;
    }
    edges.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
    let samples = if aa { 5 } else { 1 };
    let wgt = 1.0 / samples as f32;
    let mut xs: Vec<(f32, i32)> = Vec::new();
    let start_idx = 0usize;
    for row in 0..bh {
        let row_off = row * bw;
        for s in 0..samples {
            let sy = by as f32 + row as f32 + (s as f32 + 0.5) / samples as f32;
            xs.clear();
            for e in &edges[start_idx..] {
                if e.1 > sy {
                    break;
                }
                if sy < e.3 {
                    let x = e.0 + (sy - e.1) * (e.2 - e.0) / (e.3 - e.1);
                    xs.push((x, e.4));
                }
            }
            if xs.len() < 2 {
                continue;
            }
            xs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            let mut wind = 0;
            let mut span_start = 0f32;
            for &(x, d) in &xs {
                let was = wind;
                wind += d;
                if was == 0 && wind != 0 {
                    span_start = x;
                } else if was != 0 && wind == 0 {
                    add_span(&mut cov[row_off..row_off + bw], span_start - bx as f32, x - bx as f32, wgt, aa);
                }
            }
        }
    }
    for v in cov.iter_mut() {
        if *v > 1.0 {
            *v = 1.0;
        }
    }
    cov
}

#[inline]
fn add_span(row: &mut [f32], a: f32, b: f32, w: f32, aa: bool) {
    let n = row.len() as f32;
    if !aa {
        let i0 = (a - 0.5).ceil().max(0.0) as usize;
        let i1 = ((b - 0.5).ceil().min(n)).max(0.0) as usize;
        for v in row.iter_mut().take(i1).skip(i0) {
            *v += w;
        }
        return;
    }
    let a = a.clamp(0.0, n);
    let b = b.clamp(0.0, n);
    if b <= a {
        return;
    }
    let ia = a.floor() as usize;
    let ib = b.floor() as usize;
    if ia == ib {
        if ia < row.len() {
            row[ia] += (b - a) * w;
        }
        return;
    }
    row[ia] += (ia as f32 + 1.0 - a) * w;
    for v in row.iter_mut().take(ib).skip(ia + 1) {
        *v += w;
    }
    if ib < row.len() {
        row[ib] += (b - ib as f32) * w;
    }
}

fn signed_area(c: &[Pt]) -> f32 {
    let n = c.len();
    let mut a = 0.0;
    for i in 0..n {
        let p = c[i];
        let q = c[(i + 1) % n];
        a += p.0 * q.1 - q.0 * p.1;
    }
    a * 0.5
}

fn orient(mut c: Vec<Pt>) -> Vec<Pt> {
    if signed_area(&c) < 0.0 {
        c.reverse();
    }
    c
}

fn circle(cx: f32, cy: f32, r: f32) -> Vec<Pt> {
    let n = ((r * 6.3).ceil() as usize).clamp(8, 96);
    (0..n)
        .map(|i| {
            let t = i as f32 / n as f32 * std::f32::consts::TAU;
            (cx + r * t.cos(), cy + r * t.sin())
        })
        .collect()
}

/// Build the outline of a stroked path as contours to fill with non-zero winding.
/// Closed paths get mitred joins (bevel past a limit); open paths get round joins and caps.
pub fn stroke_contours(pts: &[Pt], closed: bool, width: f32) -> Vec<Vec<Pt>> {
    let hw = (width * 0.5).max(0.35);
    let mut p: Vec<Pt> = Vec::with_capacity(pts.len());
    for &q in pts {
        if p.last().map_or(true, |l: &Pt| (l.0 - q.0).abs() > 1e-4 || (l.1 - q.1).abs() > 1e-4) {
            p.push(q);
        }
    }
    if closed && p.len() > 2 {
        let (f, l) = (p[0], *p.last().unwrap());
        if (f.0 - l.0).abs() < 1e-4 && (f.1 - l.1).abs() < 1e-4 {
            p.pop();
        }
    }
    let mut out = Vec::new();
    if p.len() == 1 {
        out.push(orient(circle(p[0].0, p[0].1, hw)));
        return out;
    }
    let n = p.len();
    let segs = if closed { n } else { n - 1 };
    let normal = |a: Pt, b: Pt| -> Pt {
        let (dx, dy) = (b.0 - a.0, b.1 - a.1);
        let l = (dx * dx + dy * dy).sqrt().max(1e-6);
        (-dy / l * hw, dx / l * hw)
    };
    for i in 0..segs {
        let a = p[i];
        let b = p[(i + 1) % n];
        let nm = normal(a, b);
        out.push(orient(vec![(a.0 + nm.0, a.1 + nm.1), (b.0 + nm.0, b.1 + nm.1), (b.0 - nm.0, b.1 - nm.1), (a.0 - nm.0, a.1 - nm.1)]));
    }
    // joins
    let join_range: Vec<usize> = if closed { (0..n).collect() } else { (1..n - 1).collect() };
    for i in join_range {
        let prev = p[(i + n - 1) % n];
        let v = p[i];
        let next = p[(i + 1) % n];
        if !closed {
            out.push(orient(circle(v.0, v.1, hw)));
            continue;
        }
        let n1 = normal(prev, v);
        let n2 = normal(v, next);
        let cross = (v.0 - prev.0) * (next.1 - v.1) - (v.1 - prev.1) * (next.0 - v.0);
        // outer side is opposite the turn direction
        let s = if cross > 0.0 { -1.0 } else { 1.0 };
        let o1 = (v.0 + n1.0 * s, v.1 + n1.1 * s);
        let o2 = (v.0 + n2.0 * s, v.1 + n2.1 * s);
        let (mx, my) = (n1.0 + n2.0, n1.1 + n2.1);
        let ml2 = mx * mx + my * my;
        let dot = (n1.0 * n2.0 + n1.1 * n2.1) / (hw * hw);
        if ml2 > 1e-9 && dot > -0.75 {
            // miter length factor 1/cos(theta/2)
            let k = 2.0 * hw * hw / ml2;
            let m = (v.0 + mx * k * s, v.1 + my * k * s);
            out.push(orient(vec![v, o1, m, o2]));
        } else {
            out.push(orient(vec![v, o1, o2]));
        }
    }
    if !closed {
        out.push(orient(circle(p[0].0, p[0].1, hw)));
        out.push(orient(circle(p[n - 1].0, p[n - 1].1, hw)));
    }
    out
}

fn contours_bbox(cs: &[Vec<Pt>]) -> (f32, f32, f32, f32) {
    let (mut x0, mut y0, mut x1, mut y1) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for c in cs {
        for &(x, y) in c {
            x0 = x0.min(x);
            y0 = y0.min(y);
            x1 = x1.max(x);
            y1 = y1.max(y);
        }
    }
    (x0, y0, x1, y1)
}

// ------------------------------------------------------------------ document

impl Doc {
    pub fn new(w: usize, h: usize, fill: [u8; 4]) -> Doc {
        let mut px = vec![0u8; w * h * 4];
        if fill[3] > 0 {
            for p in px.chunks_exact_mut(4) {
                p.copy_from_slice(&fill);
            }
        }
        let mut d = Doc::empty(w, h);
        d.layers.push(Layer { id: 1, name: "Background".into(), px, opacity: 1.0, visible: true, blend: 0, delay_ms: 0, text: String::new() });
        d.next_id = 2;
        d
    }

    pub fn empty(w: usize, h: usize) -> Doc {
        Doc {
            w,
            h,
            layers: Vec::new(),
            active: 0,
            next_id: 1,
            comp: vec![0u8; w * h * 4],
            dirty: Some((0, 0, w, h)),
            sel: None,
            float: None,
            undo: Vec::new(),
            redo: Vec::new(),
            undo_bytes: 0,
            next_step: 1,
            op: None,
            adj_float: None,
            adj_open: false,
            sample_all: false,
            sel_mode: 0,
            stroke: None,
            mask: Vec::new(),
            changes: 0,
            solo: false,
            gif_loop: 0,
            frames_truncated: false,
            clip: Vec::new(),
            clip_w: 0,
            clip_h: 0,
            emb: String::new(),
            note: String::new(),
        }
    }

    pub fn from_rgba(w: usize, h: usize, px: Vec<u8>, name: &str) -> Doc {
        let mut d = Doc::empty(w, h);
        d.layers.push(Layer { id: 1, name: name.into(), px, opacity: 1.0, visible: true, blend: 0, delay_ms: 0, text: String::new() });
        d.next_id = 2;
        d
    }

    pub fn push_layer(&mut self, name: &str, px: Vec<u8>, opacity: f32, visible: bool, blend: u8) {
        let id = self.next_id;
        self.next_id += 1;
        self.layers.push(Layer { id, name: name.into(), px, opacity, visible, blend, delay_ms: 0, text: String::new() });
        self.mark_all();
    }

    pub fn layer_idx(&self, id: u32) -> Option<usize> {
        self.layers.iter().position(|l| l.id == id)
    }

    fn tiles_x(&self) -> usize {
        (self.w + TILE - 1) / TILE
    }

    fn tile_rect(&self, key: u32) -> (usize, usize, usize, usize) {
        let tx = key as usize % self.tiles_x();
        let ty = key as usize / self.tiles_x();
        let x0 = tx * TILE;
        let y0 = ty * TILE;
        (x0, y0, (x0 + TILE).min(self.w), (y0 + TILE).min(self.h))
    }

    pub fn mark_dirty(&mut self, x0: i64, y0: i64, x1: i64, y1: i64) {
        let x0 = x0.clamp(0, self.w as i64) as usize;
        let y0 = y0.clamp(0, self.h as i64) as usize;
        let x1 = x1.clamp(0, self.w as i64) as usize;
        let y1 = y1.clamp(0, self.h as i64) as usize;
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        self.dirty = Some(match self.dirty {
            None => (x0, y0, x1, y1),
            Some((a, b, c, d)) => (a.min(x0), b.min(y0), c.max(x1), d.max(y1)),
        });
    }

    pub fn mark_all(&mut self) {
        self.dirty = Some((0, 0, self.w, self.h));
    }

    // -------------------------------------------------------------- compositing

    /// What the canvas shows (honours frames view).
    pub fn composite_pixel(&self, x: usize, y: usize) -> [f32; 4] {
        self.composite_at(x, y, self.solo)
    }

    /// The real picture: every visible layer, regardless of frames view.
    pub fn composite_true(&self, x: usize, y: usize) -> [f32; 4] {
        self.composite_at(x, y, false)
    }

    fn composite_at(&self, x: usize, y: usize, solo: bool) -> [f32; 4] {
        let mut acc = [0f32; 4]; // premultiplied backdrop
        let i = (y * self.w + x) * 4;
        for (li, l) in self.layers.iter().enumerate() {
            if solo {
                if li != self.active {
                    continue;
                }
            } else if !l.visible || l.opacity <= 0.0 {
                continue;
            }
            let raw_a = l.px[i + 3];
            let has_float = li == self.active && self.float.is_some();
            if raw_a == 0 && !has_float {
                continue;
            }
            if raw_a == 255 && l.opacity >= 1.0 && l.blend == BLEND_NORMAL && !has_float {
                // opaque normal pixel fully replaces the backdrop
                let p = &l.px[i..i + 4];
                acc = [p[0] as f32 / 255.0, p[1] as f32 / 255.0, p[2] as f32 / 255.0, 1.0];
                continue;
            }
            let mut s = load(&l.px[i..i + 4]);
            if li == self.active {
                if let Some(f) = &self.float {
                    let fx = x as i64 - f.x as i64;
                    let fy = y as i64 - f.y as i64;
                    if fx >= 0 && fy >= 0 && (fx as usize) < f.w && (fy as usize) < f.h {
                        let o = (fy as usize * f.w + fx as usize) * 4;
                        s = over(s, load(&f.cur[o..o + 4]));
                    }
                }
            }
            let sa = s[3] * l.opacity;
            if sa <= 0.0 {
                continue;
            }
            let (mut cr, mut cg, mut cb) = (s[0], s[1], s[2]);
            if l.blend != BLEND_NORMAL && acc[3] > 0.0 {
                let ba = acc[3];
                let bc = [acc[0] / ba, acc[1] / ba, acc[2] / ba];
                cr = (1.0 - ba) * s[0] + ba * blend_ch(l.blend, bc[0], s[0]);
                cg = (1.0 - ba) * s[1] + ba * blend_ch(l.blend, bc[1], s[1]);
                cb = (1.0 - ba) * s[2] + ba * blend_ch(l.blend, bc[2], s[2]);
            }
            let k = 1.0 - sa;
            acc = [cr * sa + acc[0] * k, cg * sa + acc[1] * k, cb * sa + acc[2] * k, sa + acc[3] * k];
        }
        acc
    }

    /// Recomposite the dirty region into the cairo ARGB32 (premultiplied BGRA) buffer.
    /// Works a row at a time; rows touched by a floating selection use the exact
    /// per-pixel path.
    pub fn comp_update(&mut self) -> Option<(usize, usize, usize, usize)> {
        let (x0, y0, x1, y1) = self.dirty.take()?;
        let n = x1 - x0;
        let mut lut = [0f32; 256];
        for (i, v) in lut.iter_mut().enumerate() {
            *v = i as f32 / 255.0;
        }
        let mut acc = vec![[0f32; 4]; n];
        let float_rows = self.float.as_ref().map(|f| (f.y as i64, f.y as i64 + f.h as i64));
        let w = self.w;
        for y in y0..y1 {
            let o_row = (y * w + x0) * 4;
            if let Some((fy0, fy1)) = float_rows {
                if (y as i64) >= fy0 && (y as i64) < fy1 {
                    for x in x0..x1 {
                        let a = self.composite_pixel(x, y);
                        let o = (y * w + x) * 4;
                        let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
                        self.comp[o] = q(a[2]);
                        self.comp[o + 1] = q(a[1]);
                        self.comp[o + 2] = q(a[0]);
                        self.comp[o + 3] = q(a[3]);
                    }
                    continue;
                }
            }
            for v in acc.iter_mut() {
                *v = [0.0; 4];
            }
            for (li, l) in self.layers.iter().enumerate() {
                if self.solo {
                    if li != self.active {
                        continue;
                    }
                } else if !l.visible || l.opacity <= 0.0 {
                    continue;
                }
                let row = &l.px[o_row..o_row + n * 4];
                let simple = l.opacity >= 1.0 && l.blend == BLEND_NORMAL;
                for (k, p) in row.chunks_exact(4).enumerate() {
                    let a8 = p[3];
                    if a8 == 0 {
                        continue;
                    }
                    let d = &mut acc[k];
                    if a8 == 255 && simple {
                        *d = [lut[p[0] as usize], lut[p[1] as usize], lut[p[2] as usize], 1.0];
                        continue;
                    }
                    let sa = lut[a8 as usize] * l.opacity;
                    let (sr, sg, sb) = (lut[p[0] as usize], lut[p[1] as usize], lut[p[2] as usize]);
                    let (mut cr, mut cg, mut cb) = (sr, sg, sb);
                    if l.blend != BLEND_NORMAL && d[3] > 0.0 {
                        let ba = d[3];
                        let bc = [d[0] / ba, d[1] / ba, d[2] / ba];
                        cr = (1.0 - ba) * sr + ba * blend_ch(l.blend, bc[0], sr);
                        cg = (1.0 - ba) * sg + ba * blend_ch(l.blend, bc[1], sg);
                        cb = (1.0 - ba) * sb + ba * blend_ch(l.blend, bc[2], sb);
                    }
                    let kk = 1.0 - sa;
                    *d = [cr * sa + d[0] * kk, cg * sa + d[1] * kk, cb * sa + d[2] * kk, sa + d[3] * kk];
                }
            }
            let out = &mut self.comp[o_row..o_row + n * 4];
            for (k, c) in out.chunks_exact_mut(4).enumerate() {
                let a = acc[k];
                c[0] = (a[2].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
                c[1] = (a[1].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
                c[2] = (a[0].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
                c[3] = (a[3].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
            }
        }
        Some((x0, y0, x1, y1))
    }

    /// Flattened image, straight RGBA.
    pub fn flatten_rgba(&self) -> Vec<u8> {
        let mut out = vec![0u8; self.w * self.h * 4];
        for y in 0..self.h {
            for x in 0..self.w {
                let a = self.composite_true(x, y);
                let o = (y * self.w + x) * 4;
                if a[3] > 0.0 {
                    store(&mut out[o..o + 4], [a[0] / a[3], a[1] / a[3], a[2] / a[3], a[3]]);
                }
            }
        }
        out
    }

    // -------------------------------------------------------------- undo machinery

    fn new_step_id(&mut self) -> u64 {
        self.next_step += 1;
        self.next_step
    }

    fn push_undo(&mut self, kind: UndoKind) -> u64 {
        let bytes = step_bytes(&kind);
        let id = self.new_step_id();
        self.undo.push(UndoStep { id, kind, bytes, label: String::new() });
        self.undo_bytes += bytes;
        self.redo.clear();
        self.changes += 1;
        while self.undo.len() > 1 && (self.undo_bytes > UNDO_BYTES_LIMIT || self.undo.len() > UNDO_STEPS_LIMIT) {
            let s = self.undo.remove(0);
            self.undo_bytes -= s.bytes;
        }
        id
    }

    pub fn op_begin(&mut self) {
        if self.op.is_some() || self.layers.is_empty() {
            return;
        }
        if !self.layers[self.active].text.is_empty() {
            // painting on a text layer turns it into an ordinary one (its own undo step)
            let i = self.active;
            self.text_layer_set(i, "", None);
        }
        let id = self.layers[self.active].id;
        self.op = Some(OpState { layer_id: id, tiles: HashMap::new() });
    }

    /// Back up every tile of the op's layer touched by the rect before it is modified.
    pub fn touch(&mut self, x0: i64, y0: i64, x1: i64, y1: i64) {
        let x0 = x0.clamp(0, self.w as i64) as usize;
        let y0 = y0.clamp(0, self.h as i64) as usize;
        let x1 = x1.clamp(0, self.w as i64) as usize;
        let y1 = y1.clamp(0, self.h as i64) as usize;
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        let Some(op) = self.op.as_mut() else { return };
        let Some(li) = self.layers.iter().position(|l| l.id == op.layer_id) else { return };
        let tx_n = (self.w + TILE - 1) / TILE;
        let px = &self.layers[li].px;
        for ty in y0 / TILE..=(y1 - 1) / TILE {
            for tx in x0 / TILE..=(x1 - 1) / TILE {
                let key = (ty * tx_n + tx) as u32;
                op.tiles.entry(key).or_insert_with(|| {
                    let (a, b) = (tx * TILE, ty * TILE);
                    let (c, d) = ((a + TILE).min(self.w), (b + TILE).min(self.h));
                    let mut t = Vec::with_capacity((c - a) * (d - b) * 4);
                    for y in b..d {
                        t.extend_from_slice(&px[(y * self.w + a) * 4..(y * self.w + c) * 4]);
                    }
                    t
                });
            }
        }
    }

    /// Restore every backed-up tile (live previews redraw from scratch on top of this).
    pub fn op_restore(&mut self) {
        let Some(op) = self.op.take() else { return };
        if let Some(li) = self.layer_idx(op.layer_id) {
            for (key, data) in &op.tiles {
                let (a, b, c, d) = self.tile_rect(*key);
                let rw = (c - a) * 4;
                for (r, y) in (b..d).enumerate() {
                    let o = (y * self.w + a) * 4;
                    self.layers[li].px[o..o + rw].copy_from_slice(&data[r * rw..(r + 1) * rw]);
                }
                self.mark_dirty(a as i64, b as i64, c as i64, d as i64);
            }
        }
        self.op = Some(op);
    }

    pub fn op_end(&mut self) -> Option<u64> {
        let op = self.op.take()?;
        if op.tiles.is_empty() {
            return None;
        }
        let tiles: Vec<(u32, Vec<u8>)> = op.tiles.into_iter().collect();
        Some(self.push_undo(UndoKind::Tiles { layer_id: op.layer_id, tiles }))
    }

    pub fn op_cancel(&mut self) {
        self.op_restore();
        self.op = None;
    }

    pub fn can_undo(&self) -> bool {
        !self.undo.is_empty() || self.float.is_some()
    }
    pub fn can_redo(&self) -> bool {
        !self.redo.is_empty() && self.float.is_none()
    }

    /// The steps that can be undone (oldest first) and redone (next first), by label.
    pub fn history(&self) -> (Vec<&str>, Vec<&str>) {
        (self.undo.iter().map(|s| s.label.as_str()).collect(), self.redo.iter().rev().map(|s| s.label.as_str()).collect())
    }

    /// Names the newest step if it has no name yet.
    pub fn label_last(&mut self, label: &str) {
        if let Some(s) = self.undo.last_mut() {
            if s.label.is_empty() {
                s.label = label.to_string();
            }
        }
    }

    pub fn undo(&mut self) -> bool {
        self.finish_pending();
        if let Some(f) = self.float.take() {
            let (a, b, c, d) = f.rect();
            self.mark_dirty(a, b, c, d);
            if let Some(id) = f.lifted {
                if self.undo.last().map(|s| s.id) == Some(id) {
                    let s = self.undo.pop().unwrap();
                    self.undo_bytes -= s.bytes;
                    let _ = self.apply_step(s.kind);
                    self.changes += 1;
                }
            }
            return true;
        }
        let Some(s) = self.undo.pop() else { return false };
        self.undo_bytes -= s.bytes;
        let rev = self.apply_step(s.kind);
        let bytes = step_bytes(&rev);
        self.redo.push(UndoStep { id: s.id, kind: rev, bytes, label: s.label });
        self.changes += 1;
        true
    }

    pub fn redo(&mut self) -> bool {
        self.finish_pending();
        if self.float.is_some() {
            return false;
        }
        let Some(s) = self.redo.pop() else { return false };
        let rev = self.apply_step(s.kind);
        let bytes = step_bytes(&rev);
        self.undo_bytes += bytes;
        self.undo.push(UndoStep { id: s.id, kind: rev, bytes, label: s.label });
        self.changes += 1;
        true
    }

    pub(crate) fn finish_pending(&mut self) {
        if self.stroke.is_some() {
            self.stroke_end();
        }
        if self.op.is_some() {
            self.op_end();
        }
    }

    /// Apply a step and return its inverse.
    fn apply_step(&mut self, kind: UndoKind) -> UndoKind {
        match kind {
            UndoKind::Tiles { layer_id, tiles } => {
                let mut rev = Vec::with_capacity(tiles.len());
                if let Some(li) = self.layer_idx(layer_id) {
                    for (key, data) in tiles {
                        let (a, b, c, d) = self.tile_rect(key);
                        let rw = (c - a) * 4;
                        let mut cur = Vec::with_capacity(data.len());
                        for (r, y) in (b..d).enumerate() {
                            let o = (y * self.w + a) * 4;
                            cur.extend_from_slice(&self.layers[li].px[o..o + rw]);
                            self.layers[li].px[o..o + rw].copy_from_slice(&data[r * rw..(r + 1) * rw]);
                        }
                        rev.push((key, cur));
                        self.mark_dirty(a as i64, b as i64, c as i64, d as i64);
                    }
                }
                UndoKind::Tiles { layer_id, tiles: rev }
            }
            UndoKind::Full { w, h, layers, active } => {
                let cur = UndoKind::Full { w: self.w, h: self.h, layers: std::mem::take(&mut self.layers), active: self.active };
                self.w = w;
                self.h = h;
                self.layers = layers;
                self.active = active.min(self.layers.len().saturating_sub(1));
                self.resized();
                cur
            }
            UndoKind::Structure { order, active, mut pool, mods } => {
                let mut new_mods = Vec::new();
                for (id, px) in mods {
                    if let Some(li) = self.layer_idx(id) {
                        let old = std::mem::replace(&mut self.layers[li].px, px);
                        new_mods.push((id, old));
                    }
                }
                let cur_order: Vec<u32> = self.layers.iter().map(|l| l.id).collect();
                let cur_active = self.active;
                let mut current: Vec<Layer> = std::mem::take(&mut self.layers);
                let mut stack = Vec::with_capacity(order.len());
                for id in &order {
                    if let Some(p) = current.iter().position(|l| l.id == *id) {
                        stack.push(current.remove(p));
                    } else if let Some(p) = pool.iter().position(|l| l.id == *id) {
                        stack.push(pool.remove(p));
                    }
                }
                self.layers = stack;
                self.active = active.min(self.layers.len().saturating_sub(1));
                self.mark_all();
                UndoKind::Structure { order: cur_order, active: cur_active, pool: current, mods: new_mods }
            }
            UndoKind::Text { layer_id, text, px } => {
                if let Some(li) = self.layer_idx(layer_id) {
                    let l = &mut self.layers[li];
                    let rev = UndoKind::Text { layer_id, text: std::mem::replace(&mut l.text, text), px: std::mem::replace(&mut l.px, px) };
                    self.mark_all();
                    rev
                } else {
                    UndoKind::Text { layer_id, text, px }
                }
            }
            UndoKind::Props { layer_id, name, opacity, visible, blend, delay_ms } => {
                if let Some(li) = self.layer_idx(layer_id) {
                    let l = &mut self.layers[li];
                    let rev = UndoKind::Props {
                        layer_id,
                        name: std::mem::replace(&mut l.name, name),
                        opacity: l.opacity,
                        visible: l.visible,
                        blend: l.blend,
                        delay_ms: l.delay_ms,
                    };
                    l.opacity = opacity;
                    l.visible = visible;
                    l.blend = blend;
                    l.delay_ms = delay_ms;
                    self.mark_all();
                    rev
                } else {
                    UndoKind::Props { layer_id, name, opacity, visible, blend, delay_ms }
                }
            }
        }
    }

    fn resized(&mut self) {
        self.comp = vec![0u8; self.w * self.h * 4];
        self.mask = Vec::new();
        self.sel = None;
        self.float = None;
        self.op = None;
        self.stroke = None;
        self.mark_all();
    }

    fn snapshot_full(&mut self) {
        let kind = UndoKind::Full { w: self.w, h: self.h, layers: self.layers.clone(), active: self.active };
        self.push_undo(kind);
        // the whole picture changes shape: text layers become their pixels (undo brings them back)
        for l in self.layers.iter_mut() {
            l.text.clear();
        }
    }

    // -------------------------------------------------------------- selection helpers

    #[inline]
    pub(crate) fn sel_at(&self, i: usize) -> f32 {
        match &self.sel {
            Some(m) => m[i] as f32 / 255.0,
            None => 1.0,
        }
    }

    pub fn sel_bounds(&self) -> Option<(usize, usize, usize, usize)> {
        let m = self.sel.as_ref()?;
        let (mut x0, mut y0, mut x1, mut y1) = (usize::MAX, usize::MAX, 0, 0);
        for y in 0..self.h {
            let row = &m[y * self.w..(y + 1) * self.w];
            if let Some(first) = row.iter().position(|&v| v > 0) {
                let last = row.iter().rposition(|&v| v > 0).unwrap();
                x0 = x0.min(first);
                x1 = x1.max(last + 1);
                y0 = y0.min(y);
                y1 = y1.max(y + 1);
            }
        }
        if x1 == 0 {
            None
        } else {
            Some((x0, y0, x1, y1))
        }
    }

    /// A new selection mask, combined with the current selection by sel_mode.
    fn set_sel(&mut self, m: Vec<u8>) {
        let mode = std::mem::replace(&mut self.sel_mode, 0);
        let out = match (mode, self.sel.take()) {
            (1, Some(mut a)) => {
                for (x, b) in a.iter_mut().zip(m.iter()) {
                    *x = (*x).max(*b);
                }
                a
            }
            (2, Some(mut a)) => {
                for (x, b) in a.iter_mut().zip(m.iter()) {
                    *x = ((*x as u32 * (255 - *b as u32) + 127) / 255) as u8;
                }
                a
            }
            (2, None) => vec![0; self.w * self.h],
            (3, Some(mut a)) => {
                for (x, b) in a.iter_mut().zip(m.iter()) {
                    *x = (*x).min(*b);
                }
                a
            }
            (3, None) => vec![0; self.w * self.h],
            _ => m,
        };
        self.sel = if out.iter().any(|&v| v > 0) { Some(out) } else { None };
    }

    pub fn sel_rect(&mut self, x: i64, y: i64, w: i64, h: i64) {
        self.commit_float();
        let mut m = vec![0u8; self.w * self.h];
        let x0 = x.clamp(0, self.w as i64) as usize;
        let y0 = y.clamp(0, self.h as i64) as usize;
        let x1 = (x + w).clamp(0, self.w as i64) as usize;
        let y1 = (y + h).clamp(0, self.h as i64) as usize;
        if x1 > x0 && y1 > y0 {
            for yy in y0..y1 {
                m[yy * self.w + x0..yy * self.w + x1].fill(255);
            }
        }
        self.set_sel(m);
    }

    pub fn sel_poly(&mut self, pts: &[Pt]) {
        self.commit_float();
        let mut m = vec![0u8; self.w * self.h];
        let cov = poly_coverage(&[pts.to_vec()], 0, 0, self.w, self.h, true);
        for (d, c) in m.iter_mut().zip(cov.iter()) {
            *d = (c * 255.0 + 0.5) as u8;
        }
        self.set_sel(m);
    }

    /// Magic wand: the pixels of about the colour at (x, y) — joined to it when contiguous,
    /// anywhere on the layer (or the visible picture, with sample_all) otherwise. tol 0..255.
    pub fn sel_magic(&mut self, x: i64, y: i64, tol: u8, contiguous: bool) {
        self.commit_float();
        let (w, h) = (self.w, self.h);
        if x < 0 || y < 0 || x >= w as i64 || y >= h as i64 || self.layers.is_empty() {
            self.sel_mode = 0;
            return;
        }
        let merged = if self.sample_all && self.layers.len() > 1 { Some(self.flatten_rgba()) } else { None };
        let px: &[u8] = match &merged {
            Some(v) => v,
            None => &self.layers[self.active].px,
        };
        let pre = |p: &[u8]| -> [i32; 4] {
            let a = p[3] as i32;
            [p[0] as i32 * a / 255, p[1] as i32 * a / 255, p[2] as i32 * a / 255, a]
        };
        let target = pre(&px[(y as usize * w + x as usize) * 4..][..4]);
        let tol = tol as i32;
        let matches = |i: usize| -> bool {
            let p = pre(&px[i * 4..i * 4 + 4]);
            (0..4).all(|k| (p[k] - target[k]).abs() <= tol)
        };
        let mut m = vec![0u8; w * h];
        if !contiguous {
            for (i, v) in m.iter_mut().enumerate() {
                if matches(i) {
                    *v = 255;
                }
            }
        } else {
            let mut stack = vec![(x as usize, y as usize)];
            while let Some((sx, sy)) = stack.pop() {
                let row = sy * w;
                if m[row + sx] != 0 || !matches(row + sx) {
                    continue;
                }
                let mut l = sx;
                while l > 0 && m[row + l - 1] == 0 && matches(row + l - 1) {
                    l -= 1;
                }
                let mut r = sx;
                while r + 1 < w && m[row + r + 1] == 0 && matches(row + r + 1) {
                    r += 1;
                }
                m[row + l..=row + r].fill(255);
                for ny in [sy.wrapping_sub(1), sy + 1] {
                    if ny >= h {
                        continue;
                    }
                    let nrow = ny * w;
                    let mut i = l;
                    while i <= r {
                        if m[nrow + i] == 0 && matches(nrow + i) {
                            stack.push((i, ny));
                            while i <= r && m[nrow + i] == 0 && matches(nrow + i) {
                                i += 1;
                            }
                        }
                        i += 1;
                    }
                }
            }
        }
        self.set_sel(m);
    }

    /// Remove pixels close to `key` on the active layer from the selection
    /// (used by "transparent selection" so background-coloured pixels stay behind).
    pub fn sel_exclude_color(&mut self, key: [u8; 4], tol: u8) {
        if self.sel.is_none() || self.layers.is_empty() {
            return;
        }
        let merged = if self.sample_all && self.layers.len() > 1 { Some(self.flatten_rgba()) } else { None };
        let Some(m) = self.sel.as_mut() else { return };
        let px: &[u8] = match &merged {
            Some(v) => v,
            None => &self.layers[self.active].px,
        };
        for (i, v) in m.iter_mut().enumerate() {
            if *v == 0 {
                continue;
            }
            let p = &px[i * 4..i * 4 + 4];
            let same = if key[3] == 0 {
                p[3] == 0
            } else {
                p[3] > 0 && (0..3).all(|k| (p[k] as i32 - key[k] as i32).abs() <= tol as i32) && (p[3] as i32 - key[3] as i32).abs() <= tol as i32
            };
            if same {
                *v = 0;
            }
        }
        if m.iter().all(|&v| v == 0) {
            self.sel = None;
        }
    }

    /// The selection's outline as pixel-edge segments (x0, y0, x1, y1), runs joined, for drawing
    /// marching ants round any shape of selection. Pixels at half coverage or more count.
    pub fn sel_outline(&self) -> Vec<i32> {
        let Some(m) = self.sel.as_ref() else { return Vec::new() };
        let (w, h) = (self.w, self.h);
        let on = |x: i64, y: i64| x >= 0 && y >= 0 && (x as usize) < w && (y as usize) < h && m[y as usize * w + x as usize] >= 128;
        let mut out = Vec::new();
        // horizontal edges: between row y-1 and row y
        for y in 0..=h as i64 {
            let mut x = 0i64;
            while x < w as i64 {
                if on(x, y - 1) != on(x, y) {
                    let s = x;
                    let up = on(x, y - 1);
                    while x < w as i64 && on(x, y - 1) != on(x, y) && on(x, y - 1) == up {
                        x += 1;
                    }
                    out.extend_from_slice(&[s as i32, y as i32, x as i32, y as i32]);
                } else {
                    x += 1;
                }
            }
        }
        // vertical edges: between column x-1 and column x
        for x in 0..=w as i64 {
            let mut y = 0i64;
            while y < h as i64 {
                if on(x - 1, y) != on(x, y) {
                    let s = y;
                    let left = on(x - 1, y);
                    while y < h as i64 && on(x - 1, y) != on(x, y) && on(x - 1, y) == left {
                        y += 1;
                    }
                    out.extend_from_slice(&[x as i32, s as i32, x as i32, y as i32]);
                } else {
                    y += 1;
                }
            }
        }
        out
    }

    pub fn sel_all(&mut self) {
        self.commit_float();
        self.sel = Some(vec![255u8; self.w * self.h]);
    }

    pub fn sel_none(&mut self) {
        self.commit_float();
        self.sel = None;
    }

    pub fn sel_invert(&mut self) {
        self.commit_float();
        match self.sel.as_mut() {
            Some(m) => {
                for v in m.iter_mut() {
                    *v = 255 - *v;
                }
                if m.iter().all(|&v| v == 0) {
                    self.sel = None;
                }
            }
            None => self.sel = Some(vec![255u8; self.w * self.h]),
        }
    }

    /// Delete selected pixels (to transparent) on the active layer, or drop the float.
    pub fn sel_delete(&mut self) -> bool {
        if let Some(f) = self.float.take() {
            let (a, b, c, d) = f.rect();
            self.mark_dirty(a, b, c, d);
            return true;
        }
        let Some((x0, y0, x1, y1)) = self.sel_bounds() else { return false };
        self.finish_pending();
        self.op_begin();
        self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        let li = self.active;
        for y in y0..y1 {
            for x in x0..x1 {
                let i = y * self.w + x;
                let s = self.sel_at(i);
                if s > 0.0 {
                    let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                    let a = p[3] as f32 * (1.0 - s);
                    p[3] = (a + 0.5) as u8;
                    if p[3] == 0 {
                        p.copy_from_slice(&[0, 0, 0, 0]);
                    }
                }
            }
        }
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        self.op_end();
        true
    }

    // -------------------------------------------------------------- floating selection

    pub fn float_lift(&mut self, cut: bool) -> bool {
        if self.float.is_some() {
            return true;
        }
        self.finish_pending();
        let Some((x0, y0, x1, y1)) = self.sel_bounds() else { return false };
        if !self.layers.is_empty() && !self.layers[self.active].text.is_empty() {
            let i = self.active;
            self.text_layer_set(i, "", None);
        }
        let (fw, fh) = (x1 - x0, y1 - y0);
        let li = self.active;
        let mut src = vec![0u8; fw * fh * 4];
        for y in y0..y1 {
            for x in x0..x1 {
                let i = y * self.w + x;
                let s = self.sel_at(i);
                let p = &self.layers[li].px[i * 4..i * 4 + 4];
                let o = ((y - y0) * fw + (x - x0)) * 4;
                let a = (p[3] as f32 * s + 0.5) as u8;
                if a > 0 {
                    src[o..o + 4].copy_from_slice(&[p[0], p[1], p[2], a]);
                }
            }
        }
        let mut lifted = None;
        if cut {
            self.op_begin();
            self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
            for y in y0..y1 {
                for x in x0..x1 {
                    let i = y * self.w + x;
                    let s = self.sel_at(i);
                    if s > 0.0 {
                        let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                        p[3] = (p[3] as f32 * (1.0 - s) + 0.5) as u8;
                        if p[3] == 0 {
                            p.copy_from_slice(&[0, 0, 0, 0]);
                        }
                    }
                }
            }
            lifted = self.op_end();
        }
        self.sel = None;
        let mut f = Float { src, sw: fw, sh: fh, x: x0 as i32, y: y0 as i32, w: fw, h: fh, cur: Vec::new(), lifted };
        f.refresh();
        self.float = Some(f);
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        true
    }

    pub fn float_from_rgba(&mut self, w: usize, h: usize, px: Vec<u8>, x: i32, y: i32) {
        self.finish_pending();
        self.commit_float();
        self.sel = None;
        let mut f = Float { src: px, sw: w, sh: h, x, y, w, h, cur: Vec::new(), lifted: None };
        f.refresh();
        let (a, b, c, d) = f.rect();
        self.float = Some(f);
        self.mark_dirty(a, b, c, d);
    }

    pub fn float_set_rect(&mut self, x: i32, y: i32, w: usize, h: usize) {
        let Some(mut f) = self.float.take() else { return };
        let (a, b, c, d) = f.rect();
        self.mark_dirty(a, b, c, d);
        let resized = w.max(1) != f.w || h.max(1) != f.h;
        f.x = x;
        f.y = y;
        f.w = w.max(1);
        f.h = h.max(1);
        if resized {
            f.refresh();
        }
        let (a, b, c, d) = f.rect();
        self.float = Some(f);
        self.mark_dirty(a, b, c, d);
    }

    /// kind: 0 flip H, 1 flip V, 2 rotate 90 CW, 3 rotate 180, 4 rotate 90 CCW
    pub fn float_transform(&mut self, kind: u8) {
        let Some(mut f) = self.float.take() else { return };
        let (a, b, c, d) = f.rect();
        self.mark_dirty(a, b, c, d);
        let (src, sw, sh) = transform_px(&f.src, f.sw, f.sh, kind);
        let (nw, nh) = if kind == 2 || kind == 4 { (f.h, f.w) } else { (f.w, f.h) };
        // rotate about the centre
        let cx = f.x as f32 + f.w as f32 / 2.0;
        let cy = f.y as f32 + f.h as f32 / 2.0;
        f.src = src;
        f.sw = sw;
        f.sh = sh;
        f.w = nw;
        f.h = nh;
        f.x = (cx - nw as f32 / 2.0).round() as i32;
        f.y = (cy - nh as f32 / 2.0).round() as i32;
        f.refresh();
        let (a, b, c, d) = f.rect();
        self.float = Some(f);
        self.mark_dirty(a, b, c, d);
    }

    /// Rotate the floating selection by any angle (degrees, clockwise) about its centre.
    pub fn float_rotate(&mut self, deg: f32, smooth: bool) {
        let Some(mut f) = self.float.take() else { return };
        let (a, b, c, d) = f.rect();
        self.mark_dirty(a, b, c, d);
        let (px, nw, nh) = rotate_px(&f.cur, f.w, f.h, deg, smooth, None);
        let cx = f.x as f32 + f.w as f32 / 2.0;
        let cy = f.y as f32 + f.h as f32 / 2.0;
        f.src = px;
        f.sw = nw;
        f.sh = nh;
        f.w = nw;
        f.h = nh;
        f.x = (cx - nw as f32 / 2.0).round() as i32;
        f.y = (cy - nh as f32 / 2.0).round() as i32;
        f.refresh();
        let (a, b, c, d) = f.rect();
        self.float = Some(f);
        self.mark_dirty(a, b, c, d);
    }

    /// Make pixels close to `key` transparent in the float ("transparent selection").
    pub fn float_color_key(&mut self, key: [u8; 4], tol: u8) {
        let Some(f) = self.float.as_mut() else { return };
        for p in f.src.chunks_exact_mut(4) {
            let d = (0..3).map(|k| (p[k] as i32 - key[k] as i32).abs()).max().unwrap();
            if d <= tol as i32 {
                p.copy_from_slice(&[0, 0, 0, 0]);
            }
        }
        f.refresh();
        let (a, b, c, d) = f.rect();
        self.mark_dirty(a, b, c, d);
    }

    pub fn commit_float(&mut self) {
        let Some(f) = self.float.take() else { return };
        self.finish_pending();
        // fold a preceding "lift" into this step so move = one undo
        let mut tiles: HashMap<u32, Vec<u8>> = HashMap::new();
        let mut carried = String::new();
        if let Some(id) = f.lifted {
            if self.undo.last().map(|s| s.id) == Some(id) {
                let s = self.undo.pop().unwrap();
                self.undo_bytes -= s.bytes;
                carried = s.label.clone();
                self.changes = self.changes.saturating_sub(1);
                if let UndoKind::Tiles { tiles: t, .. } = s.kind {
                    tiles = t.into_iter().collect();
                }
            }
        }
        if self.layers.is_empty() {
            return;
        }
        let id = self.layers[self.active].id;
        self.op = Some(OpState { layer_id: id, tiles });
        let (fx0, fy0, fx1, fy1) = f.rect();
        self.touch(fx0, fy0, fx1, fy1);
        let li = self.active;
        for fy in 0..f.h {
            let y = f.y as i64 + fy as i64;
            if y < 0 || y >= self.h as i64 {
                continue;
            }
            for fx in 0..f.w {
                let x = f.x as i64 + fx as i64;
                if x < 0 || x >= self.w as i64 {
                    continue;
                }
                let s = load(&f.cur[(fy * f.w + fx) * 4..(fy * f.w + fx) * 4 + 4]);
                if s[3] <= 0.0 {
                    continue;
                }
                let o = (y as usize * self.w + x as usize) * 4;
                let d = load(&self.layers[li].px[o..o + 4]);
                store(&mut self.layers[li].px[o..o + 4], over(d, s));
            }
        }
        self.mark_dirty(fx0, fy0, fx1, fy1);
        if self.op_end().is_some() {
            let name = if !carried.is_empty() { carried } else if f.lifted.is_some() { "Move selection".into() } else { "Paste".into() };
            if let Some(s) = self.undo.last_mut() {
                if s.label.is_empty() {
                    s.label = name;
                }
            }
        }
    }

    pub fn float_discard(&mut self) {
        if let Some(f) = self.float.take() {
            let (a, b, c, d) = f.rect();
            self.mark_dirty(a, b, c, d);
        }
    }

    /// Prepare the clipboard buffer: the float, or the selection on the active layer.
    pub fn clip_extract(&mut self) -> bool {
        if let Some(f) = &self.float {
            self.clip = f.cur.clone();
            self.clip_w = f.w;
            self.clip_h = f.h;
            return true;
        }
        let Some((x0, y0, x1, y1)) = self.sel_bounds() else { return false };
        let (w, h) = (x1 - x0, y1 - y0);
        let mut out = vec![0u8; w * h * 4];
        let li = self.active;
        let merged = if self.sample_all && self.layers.len() > 1 { Some(self.flatten_rgba()) } else { None };
        let src: &[u8] = match &merged {
            Some(m) => m,
            None => &self.layers[li].px,
        };
        for y in y0..y1 {
            for x in x0..x1 {
                let i = y * self.w + x;
                let s = self.sel_at(i);
                let p = &src[i * 4..i * 4 + 4];
                let a = (p[3] as f32 * s + 0.5) as u8;
                if a > 0 {
                    let o = ((y - y0) * w + (x - x0)) * 4;
                    out[o..o + 4].copy_from_slice(&[p[0], p[1], p[2], a]);
                }
            }
        }
        self.clip = out;
        self.clip_w = w;
        self.clip_h = h;
        true
    }

    // -------------------------------------------------------------- strokes

    pub fn stroke_begin(&mut self, tool: u8, size: f32, hardness: f32, col: [u8; 4]) {
        self.commit_float();
        self.finish_pending();
        if self.layers.is_empty() {
            return;
        }
        if self.mask.len() != self.w * self.h {
            self.mask = vec![0u8; self.w * self.h];
        }
        let mut c = [col[0] as f32 / 255.0, col[1] as f32 / 255.0, col[2] as f32 / 255.0, col[3] as f32 / 255.0];
        if tool == TOOL_MARKER {
            c[3] *= 0.5;
        }
        if tool == TOOL_ERASER {
            c = [0.0, 0.0, 0.0, 1.0];
        }
        self.op_begin();
        self.stroke = Some(Stroke {
            tool,
            size: size.clamp(1.0, 500.0),
            hard: hardness.clamp(0.0, 1.0),
            col: c,
            last: None,
            carry: 0.0,
            bbox: None,
            rng: 0x9E37_79B9_7F4A_7C15 ^ (self.changes.wrapping_mul(2654435761)),
            pk_size: 0.0,
            pk_op: 0.0,
            tilt_nib: false,
            pres: 1.0,
            last_pres: 1.0,
            tilt: (0.0, 0.0),
            cur_pres: 1.0,
        });
    }

    /// How strongly pen pressure drives size and opacity for the stroke in progress.
    pub fn stroke_dynamics(&mut self, size_k: f32, op_k: f32, tilt_nib: bool) {
        if let Some(s) = self.stroke.as_mut() {
            s.pk_size = size_k.clamp(0.0, 1.0);
            s.pk_op = op_k.clamp(0.0, 1.0);
            s.tilt_nib = tilt_nib;
        }
    }

    /// Pen state for the next stroke_to: pressure 0..1, tilt -1..1 on each axis.
    pub fn stroke_pen(&mut self, pressure: f32, tx: f32, ty: f32) {
        if let Some(s) = self.stroke.as_mut() {
            let p = if pressure.is_finite() { pressure.clamp(0.0, 1.0) } else { 1.0 };
            if s.last.is_none() {
                s.last_pres = p;
            }
            s.pres = p;
            s.tilt = (if tx.is_finite() { tx.clamp(-1.0, 1.0) } else { 0.0 }, if ty.is_finite() { ty.clamp(-1.0, 1.0) } else { 0.0 });
        }
    }

    pub fn stroke_to(&mut self, x: f32, y: f32) {
        let Some(st) = self.stroke.as_ref() else { return };
        let tool = st.tool;
        let size = st.size;
        let spacing = match tool {
            TOOL_PENCIL | TOOL_CALLIGRAPHY | TOOL_CALLIGRAPHY2 => 0.5,
            TOOL_AIRBRUSH => (size * 0.35).max(1.0),
            _ => (size * 0.1).max(0.5),
        };
        let (p0, p1) = (st.last_pres, st.pres);
        match st.last {
            None => {
                self.set_dab_pres(p1);
                self.dab(x, y);
                if let Some(s) = self.stroke.as_mut() {
                    s.last = Some((x, y));
                    s.carry = 0.0;
                    s.last_pres = p1;
                }
            }
            Some((lx, ly)) => {
                let (dx, dy) = (x - lx, y - ly);
                let dist = (dx * dx + dy * dy).sqrt();
                if dist < 1e-6 {
                    if tool == TOOL_AIRBRUSH {
                        self.set_dab_pres(p1);
                        self.dab(x, y);
                    }
                    if let Some(s) = self.stroke.as_mut() {
                        s.last_pres = p1;
                    }
                    return;
                }
                let mut t = spacing - st.carry;
                while t <= dist {
                    let f = t / dist;
                    self.set_dab_pres(p0 + (p1 - p0) * f);
                    self.dab(lx + dx * f, ly + dy * f);
                    t += spacing;
                }
                let carry = dist - (t - spacing);
                if let Some(s) = self.stroke.as_mut() {
                    s.carry = carry;
                    s.last = Some((x, y));
                    s.last_pres = p1;
                }
            }
        }
    }

    pub fn stroke_end(&mut self) {
        if let Some(st) = self.stroke.take() {
            if let Some((x0, y0, x1, y1)) = st.bbox {
                for y in y0..y1 {
                    self.mask[y * self.w + x0..y * self.w + x1].fill(0);
                }
            }
        }
        self.op_end();
    }

    fn set_dab_pres(&mut self, p: f32) {
        if let Some(s) = self.stroke.as_mut() {
            s.cur_pres = p;
        }
    }

    fn dab(&mut self, cx: f32, cy: f32) {
        let (tool, size, hard, flow, nib) = {
            let s = self.stroke.as_ref().unwrap();
            let p = s.cur_pres;
            let size = (s.size * (1.0 - s.pk_size * (1.0 - p))).max(1.0);
            let flow = (1.0 - s.pk_op * (1.0 - p)).clamp(0.0, 1.0);
            let tl = (s.tilt.0 * s.tilt.0 + s.tilt.1 * s.tilt.1).sqrt();
            let nib = if s.tilt_nib && tl > 0.1 { Some(s.tilt.1.atan2(s.tilt.0)) } else { None };
            (s.tool, size, s.hard, flow, nib)
        };
        if flow <= 0.0 {
            return;
        }
        let r = size * 0.5;
        let ext = r + 2.0;
        let x0 = ((cx - ext).floor() as i64).clamp(0, self.w as i64) as usize;
        let y0 = ((cy - ext).floor() as i64).clamp(0, self.h as i64) as usize;
        let x1 = ((cx + ext).ceil() as i64 + 1).clamp(0, self.w as i64) as usize;
        let y1 = ((cy + ext).ceil() as i64 + 1).clamp(0, self.h as i64) as usize;
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        let w = self.w;
        match tool {
            TOOL_PENCIL => {
                if size <= 1.5 {
                    let (px, py) = (cx.floor() as i64, cy.floor() as i64);
                    if px >= 0 && py >= 0 && (px as usize) < self.w && (py as usize) < self.h {
                        { let m = &mut self.mask[py as usize * w + px as usize]; *m = (*m).max((255.0 * flow + 0.5) as u8); }
                    }
                } else {
                    let ccx = cx.floor() + 0.5;
                    let ccy = cy.floor() + 0.5;
                    let rr = r * r;
                    for y in y0..y1 {
                        for x in x0..x1 {
                            let dx = x as f32 + 0.5 - ccx;
                            let dy = y as f32 + 0.5 - ccy;
                            if dx * dx + dy * dy <= rr {
                                let m = &mut self.mask[y * w + x];
                                *m = (*m).max((255.0 * flow + 0.5) as u8);
                            }
                        }
                    }
                }
            }
            TOOL_AIRBRUSH => {
                let n = ((size * size) * 0.06).clamp(6.0, 600.0) as usize;
                let st = self.stroke.as_mut().unwrap();
                for _ in 0..n {
                    st.rng ^= st.rng << 13;
                    st.rng ^= st.rng >> 7;
                    st.rng ^= st.rng << 17;
                    let u = (st.rng & 0xffff) as f32 / 65535.0;
                    let v = ((st.rng >> 16) & 0xffff) as f32 / 65535.0;
                    let rad = r * u.sqrt();
                    let ang = v * std::f32::consts::TAU;
                    let px = (cx + rad * ang.cos()).floor() as i64;
                    let py = (cy + rad * ang.sin()).floor() as i64;
                    if px >= 0 && py >= 0 && (px as usize) < self.w && (py as usize) < self.h {
                        let m = &mut self.mask[py as usize * w + px as usize];
                        *m = m.saturating_add((90.0 * flow) as u8);
                    }
                }
            }
            _ => {
                let (ca, sa) = match (tool, nib) {
                    (TOOL_CALLIGRAPHY | TOOL_CALLIGRAPHY2, Some(a)) => (a.cos(), a.sin()),
                    (TOOL_CALLIGRAPHY, None) => ((-45f32).to_radians().cos(), (-45f32).to_radians().sin()),
                    (TOOL_CALLIGRAPHY2, None) => (45f32.to_radians().cos(), 45f32.to_radians().sin()),
                    _ => (1.0, 0.0),
                };
                let thin = (size / 6.0).max(0.8);
                for y in y0..y1 {
                    for x in x0..x1 {
                        let dx = x as f32 + 0.5 - cx;
                        let dy = y as f32 + 0.5 - cy;
                        let cov = match tool {
                            TOOL_CALLIGRAPHY | TOOL_CALLIGRAPHY2 => {
                                let u = dx * ca + dy * sa;
                                let v = -dx * sa + dy * ca;
                                let (a, b) = (r.max(0.6), thin * 0.5);
                                let f = ((u / a).powi(2) + (v / b).powi(2)).sqrt();
                                if f < 1e-6 {
                                    1.0
                                } else {
                                    let g = ((u / (a * a)).powi(2) + (v / (b * b)).powi(2)).sqrt() / f;
                                    (0.5 - (f - 1.0) / g).clamp(0.0, 1.0)
                                }
                            }
                            TOOL_MARKER => {
                                ((r - dx.abs() + 0.5).clamp(0.0, 1.0)) * ((r * 0.6 - dy.abs() + 0.5).clamp(0.0, 1.0))
                            }
                            _ => {
                                let d = (dx * dx + dy * dy).sqrt();
                                let rr = r.max(0.5);
                                if hard >= 0.99 || rr < 1.5 {
                                    (rr - d + 0.5).clamp(0.0, 1.0)
                                } else {
                                    let inner = rr * hard;
                                    if d <= inner {
                                        1.0
                                    } else {
                                        let t = ((d - inner) / (rr - inner + 0.5)).clamp(0.0, 1.0);
                                        1.0 - t * t * (3.0 - 2.0 * t)
                                    }
                                }
                            }
                        };
                        if cov > 0.0 {
                            let m = &mut self.mask[y * w + x];
                            let v = (cov * flow * 255.0 + 0.5) as u8;
                            if v > *m {
                                *m = v;
                            }
                        }
                    }
                }
            }
        }
        if let Some(st) = self.stroke.as_mut() {
            st.bbox = Some(match st.bbox {
                None => (x0, y0, x1, y1),
                Some((a, b, c, d)) => (a.min(x0), b.min(y0), c.max(x1), d.max(y1)),
            });
        }
        self.stroke_apply(x0, y0, x1, y1);
    }

    fn stroke_apply(&mut self, x0: usize, y0: usize, x1: usize, y1: usize) {
        self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        let (tool, col) = {
            let s = self.stroke.as_ref().unwrap();
            (s.tool, s.col)
        };
        let w = self.w;
        let tx_n = self.tiles_x();
        let Some(op) = self.op.as_ref() else { return };
        let Some(li) = self.layers.iter().position(|l| l.id == op.layer_id) else { return };
        let layer = &mut self.layers[li].px;
        let sel = self.sel.as_ref();
        for ty in y0 / TILE..=(y1 - 1) / TILE {
            for tx in x0 / TILE..=(x1 - 1) / TILE {
                let key = (ty * tx_n + tx) as u32;
                let Some(orig) = op.tiles.get(&key) else { continue };
                let tx0 = tx * TILE;
                let ty0 = ty * TILE;
                let tw = (tx0 + TILE).min(w) - tx0;
                let ix0 = x0.max(tx0);
                let ix1 = x1.min(tx0 + tw);
                let iy0 = y0.max(ty0);
                let iy1 = y1.min(ty0 + TILE);
                for y in iy0..iy1 {
                    for x in ix0..ix1 {
                        let i = y * w + x;
                        let mut m = self.mask[i] as f32 / 255.0;
                        if let Some(sm) = sel {
                            m *= sm[i] as f32 / 255.0;
                        }
                        let oo = ((y - ty0) * tw + (x - tx0)) * 4;
                        let o = load(&orig[oo..oo + 4]);
                        let res = if tool == TOOL_ERASER {
                            [o[0], o[1], o[2], o[3] * (1.0 - m)]
                        } else {
                            over(o, [col[0], col[1], col[2], col[3] * m])
                        };
                        store(&mut layer[i * 4..i * 4 + 4], res);
                    }
                }
            }
        }
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
    }

    // -------------------------------------------------------------- shapes, fills, text

    /// Render a path onto the active layer within the current op.
    /// mode bit0 = outline, bit1 = fill.
    pub fn shape(&mut self, pts: &[Pt], closed: bool, width: f32, outline: [u8; 4], fill: [u8; 4], mode: u32, aa: bool) {
        if pts.is_empty() || self.layers.is_empty() {
            return;
        }
        let own_op = self.op.is_none();
        if own_op {
            self.commit_float();
            self.op_begin();
        }
        let do_fill = mode & 2 != 0 && closed && pts.len() >= 3;
        let do_line = mode & 1 != 0;
        let fill_c: Vec<Vec<Pt>> = if do_fill { vec![pts.to_vec()] } else { Vec::new() };
        let line_c: Vec<Vec<Pt>> = if do_line { stroke_contours(pts, closed, width) } else { Vec::new() };
        let mut all = fill_c.clone();
        all.extend(line_c.iter().cloned());
        if all.is_empty() {
            return;
        }
        let (bx0, by0, bx1, by1) = contours_bbox(&all);
        let x0 = ((bx0.floor() as i64) - 1).clamp(0, self.w as i64);
        let y0 = ((by0.floor() as i64) - 1).clamp(0, self.h as i64);
        let x1 = ((bx1.ceil() as i64) + 2).clamp(0, self.w as i64);
        let y1 = ((by1.ceil() as i64) + 2).clamp(0, self.h as i64);
        if x1 <= x0 || y1 <= y0 {
            return;
        }
        let (bw, bh) = ((x1 - x0) as usize, (y1 - y0) as usize);
        let fcov = if do_fill { poly_coverage(&fill_c, x0, y0, bw, bh, aa) } else { Vec::new() };
        let lcov = if do_line { poly_coverage(&line_c, x0, y0, bw, bh, aa) } else { Vec::new() };
        self.touch(x0, y0, x1, y1);
        let fc = load(&fill);
        let lc = load(&outline);
        let li = self.active;
        for yy in 0..bh {
            for xx in 0..bw {
                let x = x0 as usize + xx;
                let y = y0 as usize + yy;
                let i = y * self.w + x;
                let s = self.sel_at(i);
                if s <= 0.0 {
                    continue;
                }
                let k = yy * bw + xx;
                let mut d = load(&self.layers[li].px[i * 4..i * 4 + 4]);
                let mut changed = false;
                if do_fill && fcov[k] > 0.0 {
                    d = over(d, [fc[0], fc[1], fc[2], fc[3] * fcov[k] * s]);
                    changed = true;
                }
                if do_line && lcov[k] > 0.0 {
                    d = over(d, [lc[0], lc[1], lc[2], lc[3] * lcov[k] * s]);
                    changed = true;
                }
                if changed {
                    store(&mut self.layers[li].px[i * 4..i * 4 + 4], d);
                }
            }
        }
        self.mark_dirty(x0, y0, x1, y1);
        if own_op {
            self.op_end();
        }
    }

    /// Composite a cairo ARGB32 premultiplied bitmap onto the active layer within the op.
    pub fn blit_premul(&mut self, x: i64, y: i64, w: usize, h: usize, data: &[u8], stride: usize) {
        if self.layers.is_empty() {
            return;
        }
        let own_op = self.op.is_none();
        if own_op {
            self.commit_float();
            self.op_begin();
        }
        self.touch(x, y, x + w as i64, y + h as i64);
        let li = self.active;
        for yy in 0..h {
            let ty = y + yy as i64;
            if ty < 0 || ty >= self.h as i64 {
                continue;
            }
            for xx in 0..w {
                let tx = x + xx as i64;
                if tx < 0 || tx >= self.w as i64 {
                    continue;
                }
                let p = &data[yy * stride + xx * 4..yy * stride + xx * 4 + 4];
                let a = p[3] as f32 / 255.0;
                if a <= 0.0 {
                    continue;
                }
                let i = ty as usize * self.w + tx as usize;
                let s = self.sel_at(i);
                if s <= 0.0 {
                    continue;
                }
                let src = [p[2] as f32 / 255.0 / a, p[1] as f32 / 255.0 / a, p[0] as f32 / 255.0 / a, a * s];
                let d = load(&self.layers[li].px[i * 4..i * 4 + 4]);
                store(&mut self.layers[li].px[i * 4..i * 4 + 4], over(d, src));
            }
        }
        self.mark_dirty(x, y, x + w as i64, y + h as i64);
        if own_op {
            self.op_end();
        }
    }

    /// Scanline flood fill on the active layer. A fully transparent colour clears the region.
    pub fn flood_fill(&mut self, x: i64, y: i64, col: [u8; 4], tol: u8) -> bool {
        self.commit_float();
        self.finish_pending();
        if x < 0 || y < 0 || x >= self.w as i64 || y >= self.h as i64 || self.layers.is_empty() {
            return false;
        }
        let (w, h) = (self.w, self.h);
        let li = self.active;
        let pre = |p: &[u8]| -> [i32; 4] {
            let a = p[3] as i32;
            [p[0] as i32 * a / 255, p[1] as i32 * a / 255, p[2] as i32 * a / 255, a]
        };
        let start = (y as usize * w + x as usize) * 4;
        if self.sel_at(y as usize * w + x as usize) <= 0.0 {
            return false;
        }
        let merged = if self.sample_all && self.layers.len() > 1 { Some(self.flatten_rgba()) } else { None };
        let px: &[u8] = match &merged {
            Some(v) => v,
            None => &self.layers[li].px,
        };
        let target = pre(&px[start..start + 4]);
        let tol = tol as i32;
        let sel = self.sel.as_ref();
        let matches = |i: usize| -> bool {
            if let Some(m) = sel {
                if m[i] == 0 {
                    return false;
                }
            }
            let p = pre(&px[i * 4..i * 4 + 4]);
            (0..4).all(|k| (p[k] - target[k]).abs() <= tol)
        };
        let mut region = vec![false; w * h];
        let mut stack: Vec<(usize, usize)> = vec![(x as usize, y as usize)];
        let (mut bx0, mut by0, mut bx1, mut by1) = (w, h, 0usize, 0usize);
        while let Some((sx, sy)) = stack.pop() {
            let row = sy * w;
            if region[row + sx] || !matches(row + sx) {
                continue;
            }
            let mut l = sx;
            while l > 0 && !region[row + l - 1] && matches(row + l - 1) {
                l -= 1;
            }
            let mut r = sx;
            while r + 1 < w && !region[row + r + 1] && matches(row + r + 1) {
                r += 1;
            }
            for i in l..=r {
                region[row + i] = true;
            }
            bx0 = bx0.min(l);
            bx1 = bx1.max(r + 1);
            by0 = by0.min(sy);
            by1 = by1.max(sy + 1);
            for ny in [sy.wrapping_sub(1), sy + 1] {
                if ny >= h {
                    continue;
                }
                let nrow = ny * w;
                let mut i = l;
                while i <= r {
                    if !region[nrow + i] && matches(nrow + i) {
                        stack.push((i, ny));
                        while i <= r && !region[nrow + i] && matches(nrow + i) {
                            i += 1;
                        }
                    } else {
                        i += 1;
                    }
                }
            }
        }
        if bx1 <= bx0 {
            return false;
        }
        self.op_begin();
        self.touch(bx0 as i64, by0 as i64, bx1 as i64, by1 as i64);
        let c = load(&col);
        for yy in by0..by1 {
            for xx in bx0..bx1 {
                let i = yy * w + xx;
                if !region[i] {
                    continue;
                }
                let s = self.sel_at(i);
                let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                let d = load(p);
                let res = if col[3] == 0 { [d[0], d[1], d[2], d[3] * (1.0 - s)] } else { over(d, [c[0], c[1], c[2], c[3] * s]) };
                store(p, res);
            }
        }
        self.mark_dirty(bx0 as i64, by0 as i64, bx1 as i64, by1 as i64);
        self.op_end();
        true
    }

    pub fn pick(&self, x: i64, y: i64, all: bool) -> [u8; 4] {
        if x < 0 || y < 0 || x >= self.w as i64 || y >= self.h as i64 || self.layers.is_empty() {
            return [0, 0, 0, 0];
        }
        let (x, y) = (x as usize, y as usize);
        if all {
            let a = self.composite_pixel(x, y);
            let mut out = [0u8; 4];
            if a[3] > 0.0 {
                store(&mut out, [a[0] / a[3], a[1] / a[3], a[2] / a[3], a[3]]);
            }
            out
        } else {
            let i = (y * self.w + x) * 4;
            let p = &self.layers[self.active].px[i..i + 4];
            [p[0], p[1], p[2], p[3]]
        }
    }

    /// Remove Background: cut the subject of the active layer (or of the selection) out of its background.
    /// Returns false when there was nothing to remove.
    pub fn remove_background(&mut self) -> bool {
        self.commit_float();
        self.finish_pending();
        if self.layers.is_empty() {
            return false;
        }
        let (x0, y0, x1, y1) = self.sel_bounds().unwrap_or((0, 0, self.w, self.h));
        let (bw, bh) = (x1 - x0, y1 - y0);
        if bw < 3 || bh < 3 {
            return false;
        }
        let li = self.active;
        let mut sub = Vec::with_capacity(bw * bh * 4);
        for y in y0..y1 {
            let o = (y * self.w + x0) * 4;
            sub.extend_from_slice(&self.layers[li].px[o..o + bw * 4]);
        }
        // outside the selection counts as background, so a lasso round the subject works as in Paint
        let has_sel = self.sel.is_some();
        if has_sel {
            for y in 0..bh {
                for x in 0..bw {
                    if self.sel_at((y + y0) * self.w + x + x0) < 0.5 {
                        sub[(y * bw + x) * 4 + 3] = 0;
                    }
                }
            }
        }
        let alpha = crate::cutout::subject_alpha(&sub, bw, bh);
        if alpha.iter().zip(sub.chunks_exact(4)).all(|(&a, p)| a > 0 || p[3] < 16) {
            return false;
        }
        self.op_begin();
        self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        for y in 0..bh {
            for x in 0..bw {
                let i = (y + y0) * self.w + x + x0;
                let s = self.sel_at(i);
                if s <= 0.0 {
                    continue;
                }
                let k = alpha[y * bw + x] as f32 / 255.0;
                let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                let f = 1.0 - s * (1.0 - k);
                if f < 1.0 {
                    // the layer stores premultiplied-free RGBA: only alpha changes
                    p[3] = (p[3] as f32 * f + 0.5) as u8;
                }
            }
        }
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        self.op_end();
        true
    }

    pub fn invert_colors(&mut self) {
        if let Some(f) = self.float.as_mut() {
            for p in f.src.chunks_exact_mut(4) {
                if p[3] > 0 {
                    p[0] = 255 - p[0];
                    p[1] = 255 - p[1];
                    p[2] = 255 - p[2];
                }
            }
            f.refresh();
            let (a, b, c, d) = f.rect();
            self.mark_dirty(a, b, c, d);
            return;
        }
        self.finish_pending();
        let (x0, y0, x1, y1) = self.sel_bounds().unwrap_or((0, 0, self.w, self.h));
        self.op_begin();
        self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        let li = self.active;
        for y in y0..y1 {
            for x in x0..x1 {
                let i = y * self.w + x;
                let s = self.sel_at(i);
                if s <= 0.0 {
                    continue;
                }
                let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                if p[3] == 0 {
                    continue;
                }
                for k in 0..3 {
                    let v = p[k] as f32;
                    p[k] = (v + (255.0 - 2.0 * v) * s + 0.5) as u8;
                }
            }
        }
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        self.op_end();
    }

    // -------------------------------------------------------------- layers

    /// The pixels of a text layer: `block` (premultiplied BGRA, cairo's) placed at x, y on an
    /// otherwise clear layer.
    fn text_pixels(&self, x: i64, y: i64, bw: usize, bh: usize, block: &[u8], stride: usize) -> Vec<u8> {
        let mut px = vec![0u8; self.w * self.h * 4];
        for r in 0..bh {
            let yy = y + r as i64;
            if yy < 0 || yy >= self.h as i64 {
                continue;
            }
            for c in 0..bw {
                let xx = x + c as i64;
                if xx < 0 || xx >= self.w as i64 {
                    continue;
                }
                let s = &block[r * stride + c * 4..r * stride + c * 4 + 4];
                let a = s[3];
                if a == 0 {
                    continue;
                }
                let o = (yy as usize * self.w + xx as usize) * 4;
                let un = |v: u8| ((v as u32 * 255 + a as u32 / 2) / a as u32).min(255) as u8;
                px[o..o + 4].copy_from_slice(&[un(s[2]), un(s[1]), un(s[0]), a]);
            }
        }
        px
    }

    /// A new text layer above the active one, holding the typed text (one undo step).
    pub fn text_layer_add(&mut self, name: &str, text: &str, x: i64, y: i64, bw: usize, bh: usize, block: &[u8], stride: usize) -> usize {
        self.commit_float();
        self.finish_pending();
        let (order, act) = (self.order(), self.active);
        let id = self.next_id;
        self.next_id += 1;
        let pos = if self.layers.is_empty() { 0 } else { self.active + 1 };
        let delay = self.layers.get(self.active).map_or(0, |l| l.delay_ms);
        let px = self.text_pixels(x, y, bw, bh, block, stride);
        self.layers.insert(pos, Layer { id, name: name.into(), px, opacity: 1.0, visible: true, blend: 0, delay_ms: delay, text: text.into() });
        self.active = pos;
        self.structure_step(order, act, Vec::new(), Vec::new());
        pos
    }

    /// A text layer typed again: new pixels and description (one undo step). An empty
    /// description with no block turns it into an ordinary layer, its pixels kept.
    pub fn text_layer_set(&mut self, i: usize, text: &str, block: Option<(i64, i64, usize, usize, &[u8], usize)>) {
        if i >= self.layers.len() {
            return;
        }
        self.commit_float();
        self.finish_pending();
        let new_px = match block {
            Some((x, y, bw, bh, b, st)) => self.text_pixels(x, y, bw, bh, b, st),
            None => self.layers[i].px.clone(),
        };
        let l = &mut self.layers[i];
        let old_px = std::mem::replace(&mut l.px, new_px);
        let old_text = std::mem::replace(&mut l.text, text.to_string());
        let id = l.id;
        self.push_undo(UndoKind::Text { layer_id: id, text: old_text, px: old_px });
        self.mark_all();
    }

    fn structure_step(&mut self, order: Vec<u32>, active: usize, pool: Vec<Layer>, mods: Vec<(u32, Vec<u8>)>) {
        self.push_undo(UndoKind::Structure { order, active, pool, mods });
        self.mark_all();
    }

    fn order(&self) -> Vec<u32> {
        self.layers.iter().map(|l| l.id).collect()
    }

    pub fn layer_add(&mut self, name: &str) -> usize {
        self.commit_float();
        self.finish_pending();
        let (order, act) = (self.order(), self.active);
        let id = self.next_id;
        self.next_id += 1;
        let pos = if self.layers.is_empty() { 0 } else { self.active + 1 };
        let delay = self.layers.get(self.active).map_or(0, |l| l.delay_ms);
        self.layers.insert(pos, Layer { id, name: name.into(), px: vec![0u8; self.w * self.h * 4], opacity: 1.0, visible: true, blend: 0, delay_ms: delay, text: String::new() });
        self.active = pos;
        self.structure_step(order, act, Vec::new(), Vec::new());
        pos
    }

    pub fn layer_duplicate(&mut self) -> usize {
        self.commit_float();
        self.finish_pending();
        if self.layers.is_empty() {
            return 0;
        }
        let (order, act) = (self.order(), self.active);
        let mut l = self.layers[self.active].clone();
        l.id = self.next_id;
        self.next_id += 1;
        l.name = format!("{} copy", l.name);
        self.layers.insert(self.active + 1, l);
        self.active += 1;
        self.structure_step(order, act, Vec::new(), Vec::new());
        self.active
    }

    pub fn layer_delete(&mut self) -> bool {
        self.commit_float();
        self.finish_pending();
        if self.layers.len() <= 1 {
            return false;
        }
        let (order, act) = (self.order(), self.active);
        let removed = self.layers.remove(self.active);
        if self.active >= self.layers.len() {
            self.active = self.layers.len() - 1;
        }
        self.structure_step(order, act, vec![removed], Vec::new());
        true
    }

    pub fn layer_move(&mut self, from: usize, to: usize) -> bool {
        self.commit_float();
        self.finish_pending();
        if from >= self.layers.len() || to >= self.layers.len() || from == to {
            return false;
        }
        let (order, act) = (self.order(), self.active);
        let l = self.layers.remove(from);
        self.layers.insert(to, l);
        if self.active == from {
            self.active = to;
        } else if from < self.active && to >= self.active {
            self.active -= 1;
        } else if from > self.active && to <= self.active {
            self.active += 1;
        }
        self.structure_step(order, act, Vec::new(), Vec::new());
        true
    }

    /// Merge the active layer into the one below it, honouring opacity and blend mode.
    pub fn layer_merge_down(&mut self) -> bool {
        self.commit_float();
        self.finish_pending();
        if self.active == 0 || self.active >= self.layers.len() {
            return false;
        }
        let (order, act) = (self.order(), self.active);
        let upper = self.layers.remove(self.active);
        let li = self.active - 1;
        let old_px = self.layers[li].px.clone();
        let lower_id = self.layers[li].id;
        if upper.visible {
            let lower = &mut self.layers[li];
            for (d, s) in lower.px.chunks_exact_mut(4).zip(upper.px.chunks_exact(4)) {
                let sc = load(s);
                let sa = sc[3] * upper.opacity;
                if sa <= 0.0 {
                    continue;
                }
                let dc = load(d);
                let (mut cr, mut cg, mut cb) = (sc[0], sc[1], sc[2]);
                if upper.blend != BLEND_NORMAL && dc[3] > 0.0 {
                    let ba = dc[3];
                    cr = (1.0 - ba) * sc[0] + ba * blend_ch(upper.blend, dc[0], sc[0]);
                    cg = (1.0 - ba) * sc[1] + ba * blend_ch(upper.blend, dc[1], sc[1]);
                    cb = (1.0 - ba) * sc[2] + ba * blend_ch(upper.blend, dc[2], sc[2]);
                }
                store(d, over(dc, [cr, cg, cb, sa]));
            }
        }
        self.active = li;
        self.structure_step(order, act, vec![upper], vec![(lower_id, old_px)]);
        true
    }

    pub fn flatten(&mut self) {
        self.commit_float();
        self.finish_pending();
        if self.layers.len() <= 1 && self.layers.first().map_or(true, |l| l.visible && l.opacity >= 1.0 && l.blend == 0) {
            return;
        }
        let (order, act) = (self.order(), self.active);
        let px = self.flatten_rgba();
        let old = std::mem::take(&mut self.layers);
        let id = self.next_id;
        self.next_id += 1;
        self.layers.push(Layer { id, name: "Background".into(), px, opacity: 1.0, visible: true, blend: 0, delay_ms: 0, text: String::new() });
        self.active = 0;
        self.structure_step(order, act, old, Vec::new());
    }

    pub fn layer_set_props(&mut self, i: usize, name: Option<String>, opacity: f32, visible: bool, blend: u8, delay_ms: u32, record: bool) {
        if i >= self.layers.len() {
            return;
        }
        if record {
            let l = &self.layers[i];
            let kind = UndoKind::Props { layer_id: l.id, name: l.name.clone(), opacity: l.opacity, visible: l.visible, blend: l.blend, delay_ms: l.delay_ms };
            self.push_undo(kind);
        } else {
            self.changes += 1;
        }
        let l = &mut self.layers[i];
        if let Some(n) = name {
            l.name = n;
        }
        l.opacity = opacity.clamp(0.0, 1.0);
        l.visible = visible;
        l.blend = blend.min(BLEND_COUNT - 1);
        l.delay_ms = delay_ms.min(655_350);
        self.mark_all();
    }

    pub fn set_active(&mut self, i: usize) {
        if i < self.layers.len() && i != self.active {
            self.commit_float();
            self.finish_pending();
            self.active = i;
            if self.solo {
                self.mark_all();
            }
        }
    }

    pub fn layer_thumb(&self, i: usize, tw: usize, th: usize) -> Vec<u8> {
        let mut out = vec![0u8; tw * th * 4];
        if i >= self.layers.len() || tw == 0 || th == 0 {
            return out;
        }
        let px = &self.layers[i].px;
        for y in 0..th {
            for x in 0..tw {
                let mut acc = [0u32; 4];
                for sy in 0..2 {
                    for sx in 0..2 {
                        let fx = ((x as f32 + 0.25 + sx as f32 * 0.5) * self.w as f32 / tw as f32) as usize;
                        let fy = ((y as f32 + 0.25 + sy as f32 * 0.5) * self.h as f32 / th as f32) as usize;
                        let o = (fy.min(self.h - 1) * self.w + fx.min(self.w - 1)) * 4;
                        let a = px[o + 3] as u32;
                        acc[0] += px[o + 2] as u32 * a / 255;
                        acc[1] += px[o + 1] as u32 * a / 255;
                        acc[2] += px[o] as u32 * a / 255;
                        acc[3] += a;
                    }
                }
                let o = (y * tw + x) * 4;
                for k in 0..4 {
                    out[o + k] = (acc[k] / 4) as u8;
                }
            }
        }
        out
    }

    // -------------------------------------------------------------- whole-image operations

    /// kind: 0 flip H, 1 flip V, 2 rotate 90 CW, 3 rotate 180, 4 rotate 90 CCW
    pub fn image_transform(&mut self, kind: u8) {
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        let (w, h) = (self.w, self.h);
        for l in self.layers.iter_mut() {
            let (px, _, _) = transform_px(&l.px, w, h, kind);
            l.px = px;
        }
        if kind == 2 || kind == 4 {
            self.w = h;
            self.h = w;
        }
        self.resized();
    }

    /// Rotate every layer by any angle (degrees, clockwise), growing the canvas to fit.
    /// `bg` fills the uncovered corners of the bottom layer; None leaves them transparent.
    pub fn image_rotate(&mut self, deg: f32, smooth: bool, bg: Option<[u8; 4]>) {
        let n = deg.rem_euclid(360.0);
        if n < 1e-3 || n > 360.0 - 1e-3 {
            return;
        }
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        let (w, h) = (self.w, self.h);
        let (mut nw, mut nh) = (w, h);
        for (i, l) in self.layers.iter_mut().enumerate() {
            let (px, a, b) = rotate_px(&l.px, w, h, deg, smooth, if i == 0 { bg } else { None });
            l.px = px;
            nw = a;
            nh = b;
        }
        self.w = nw;
        self.h = nh;
        self.resized();
    }

    pub fn image_resize(&mut self, nw: usize, nh: usize, smooth: bool) {
        if nw == 0 || nh == 0 || (nw == self.w && nh == self.h) {
            return;
        }
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        for l in self.layers.iter_mut() {
            l.px = resample(&l.px, self.w, self.h, nw, nh, smooth);
        }
        self.w = nw;
        self.h = nh;
        self.resized();
    }

    /// Skew by angles in degrees (horizontal then vertical), growing the canvas to fit.
    pub fn image_skew(&mut self, ax: f32, ay: f32) {
        if ax.abs() < 1e-3 && ay.abs() < 1e-3 {
            return;
        }
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        let tx = ax.to_radians().tan();
        let ty = ay.to_radians().tan();
        let (w, h) = (self.w, self.h);
        let nw = w + (h as f32 * tx.abs()).ceil() as usize;
        let off_x = if tx < 0.0 { h as f32 * -tx } else { 0.0 };
        let nh = h + (nw as f32 * ty.abs()).ceil() as usize;
        let off_y = if ty < 0.0 { nw as f32 * -ty } else { 0.0 };
        for l in self.layers.iter_mut() {
            // horizontal shear: row y shifted by y*tx
            let mut a = vec![0u8; nw * h * 4];
            for y in 0..h {
                let shift = (y as f32 + 0.5) * tx + off_x;
                for x in 0..nw {
                    let sx = x as f32 - shift;
                    sample_lin_row(&l.px, w, y, sx, &mut a[(y * nw + x) * 4..(y * nw + x) * 4 + 4]);
                }
            }
            // vertical shear: column x shifted by x*ty
            let mut b = vec![0u8; nw * nh * 4];
            for x in 0..nw {
                let shift = (x as f32 + 0.5) * ty + off_y;
                for y in 0..nh {
                    let sy = y as f32 - shift;
                    let f = sy.floor();
                    let t = sy - f;
                    let y0 = f as i64;
                    let get = |yy: i64| -> [f32; 4] {
                        if yy < 0 || yy >= h as i64 {
                            [0.0; 4]
                        } else {
                            let o = (yy as usize * nw + x) * 4;
                            let p = load(&a[o..o + 4]);
                            [p[0] * p[3], p[1] * p[3], p[2] * p[3], p[3]]
                        }
                    };
                    let p0 = get(y0);
                    let p1 = get(y0 + 1);
                    let m: Vec<f32> = (0..4).map(|k| p0[k] * (1.0 - t) + p1[k] * t).collect();
                    if m[3] > 1e-6 {
                        let o = (y * nw + x) * 4;
                        store(&mut b[o..o + 4], [m[0] / m[3], m[1] / m[3], m[2] / m[3], m[3]]);
                    }
                }
            }
            l.px = b;
        }
        self.w = nw;
        self.h = nh;
        self.resized();
    }

    /// Change canvas size; anchor (0..1, 0..1) decides where the old image sits.
    pub fn canvas_size(&mut self, nw: usize, nh: usize, ax: f32, ay: f32) {
        if nw == 0 || nh == 0 || (nw == self.w && nh == self.h) {
            return;
        }
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        let ox = ((nw as f32 - self.w as f32) * ax).round() as i64;
        let oy = ((nh as f32 - self.h as f32) * ay).round() as i64;
        for l in self.layers.iter_mut() {
            l.px = crop_px(&l.px, self.w, self.h, -ox, -oy, nw, nh);
        }
        self.w = nw;
        self.h = nh;
        self.resized();
    }

    pub fn crop(&mut self, x: i64, y: i64, w: usize, h: usize) {
        if w == 0 || h == 0 {
            return;
        }
        self.commit_float();
        self.finish_pending();
        self.snapshot_full();
        for l in self.layers.iter_mut() {
            l.px = crop_px(&l.px, self.w, self.h, x, y, w, h);
        }
        self.w = w;
        self.h = h;
        self.resized();
    }

    pub fn crop_to_selection(&mut self) -> bool {
        if let Some(f) = &self.float {
            let (x, y, w, h) = (f.x as i64, f.y as i64, f.w, f.h);
            self.commit_float();
            self.crop(x, y, w, h);
            return true;
        }
        let Some((x0, y0, x1, y1)) = self.sel_bounds() else { return false };
        // pixels outside a non-rectangular selection become transparent
        let sel = self.sel.clone();
        let orig_w = self.w;
        self.crop(x0 as i64, y0 as i64, x1 - x0, y1 - y0);
        if let Some(m) = sel {
            let (ow, oh) = (self.w, self.h);
            for l in self.layers.iter_mut() {
                for y in 0..oh {
                    for x in 0..ow {
                        let s = m[(y + y0) * orig_w + x + x0];
                        if s < 255 {
                            let p = &mut l.px[(y * ow + x) * 4..(y * ow + x) * 4 + 4];
                            p[3] = (p[3] as u32 * s as u32 / 255) as u8;
                            if p[3] == 0 {
                                p.copy_from_slice(&[0, 0, 0, 0]);
                            }
                        }
                    }
                }
            }
            self.mark_all();
        }
        true
    }

}

fn sample_lin_row(px: &[u8], w: usize, y: usize, sx: f32, out: &mut [u8]) {
    let f = (sx - 0.5).floor();
    let t = sx - 0.5 - f;
    let x0 = f as i64;
    let get = |xx: i64| -> [f32; 4] {
        if xx < 0 || xx >= w as i64 {
            [0.0; 4]
        } else {
            let o = (y * w + xx as usize) * 4;
            let p = load(&px[o..o + 4]);
            [p[0] * p[3], p[1] * p[3], p[2] * p[3], p[3]]
        }
    };
    let p0 = get(x0);
    let p1 = get(x0 + 1);
    let m: Vec<f32> = (0..4).map(|k| p0[k] * (1.0 - t) + p1[k] * t).collect();
    if m[3] > 1e-6 {
        store(out, [m[0] / m[3], m[1] / m[3], m[2] / m[3], m[3]]);
    }
}

pub fn crop_px(px: &[u8], w: usize, h: usize, x: i64, y: i64, nw: usize, nh: usize) -> Vec<u8> {
    let mut out = vec![0u8; nw * nh * 4];
    for yy in 0..nh {
        let sy = y + yy as i64;
        if sy < 0 || sy >= h as i64 {
            continue;
        }
        let sx0 = x.max(0);
        let sx1 = (x + nw as i64).min(w as i64);
        if sx1 <= sx0 {
            continue;
        }
        let dx0 = (sx0 - x) as usize;
        let n = (sx1 - sx0) as usize * 4;
        let so = (sy as usize * w + sx0 as usize) * 4;
        let doff = (yy * nw + dx0) * 4;
        out[doff..doff + n].copy_from_slice(&px[so..so + n]);
    }
    out
}

/// The size of a w x h image rotated by `deg`.
pub fn rotated_size(w: usize, h: usize, deg: f32) -> (usize, usize) {
    let n = deg.rem_euclid(360.0);
    for (k, a) in [0.0f32, 90.0, 180.0, 270.0, 360.0].iter().enumerate() {
        if (n - a).abs() < 1e-3 {
            return if k % 2 == 1 { (h, w) } else { (w, h) };
        }
    }
    let t = n.to_radians();
    let (c, s) = (t.cos().abs(), t.sin().abs());
    let nw = (w as f32 * c + h as f32 * s - 1e-3).ceil().max(1.0) as usize;
    let nh = (w as f32 * s + h as f32 * c - 1e-3).ceil().max(1.0) as usize;
    (nw, nh)
}

/// Rotate pixels by any angle (degrees, clockwise on screen) into the bounding box of the result.
/// Quarter turns are exact; other angles sample bilinearly in premultiplied space (or nearest
/// neighbour when `smooth` is off). Uncovered pixels are transparent, or `bg` when given.
pub fn rotate_px(px: &[u8], w: usize, h: usize, deg: f32, smooth: bool, bg: Option<[u8; 4]>) -> (Vec<u8>, usize, usize) {
    let n = deg.rem_euclid(360.0);
    let quarter = [(0.0f32, 255u8), (90.0, 2), (180.0, 3), (270.0, 4), (360.0, 255)];
    for (a, kind) in quarter {
        if (n - a).abs() < 1e-3 {
            return if kind == 255 { (px.to_vec(), w, h) } else { transform_px(px, w, h, kind) };
        }
    }
    let (nw, nh) = rotated_size(w, h, n);
    let t = n.to_radians();
    let (c, s) = (t.cos(), t.sin());
    let (cx, cy) = (w as f32 / 2.0, h as f32 / 2.0);
    let (ncx, ncy) = (nw as f32 / 2.0, nh as f32 / 2.0);
    let get = |x: i64, y: i64| -> [f32; 4] {
        if x < 0 || y < 0 || x >= w as i64 || y >= h as i64 {
            return [0.0; 4];
        }
        let p = load(&px[(y as usize * w + x as usize) * 4..][..4]);
        [p[0] * p[3], p[1] * p[3], p[2] * p[3], p[3]]
    };
    let bgf = bg.map(|b| load(&b));
    let mut out = vec![0u8; nw * nh * 4];
    for y in 0..nh {
        let dy = y as f32 + 0.5 - ncy;
        for x in 0..nw {
            let dx = x as f32 + 0.5 - ncx;
            // inverse rotation: destination -> source
            let sx = c * dx + s * dy + cx;
            let sy = -s * dx + c * dy + cy;
            let m = if smooth {
                let fx = sx - 0.5;
                let fy = sy - 0.5;
                let x0 = fx.floor();
                let y0 = fy.floor();
                let (tx, ty) = (fx - x0, fy - y0);
                let (x0, y0) = (x0 as i64, y0 as i64);
                let p00 = get(x0, y0);
                let p10 = get(x0 + 1, y0);
                let p01 = get(x0, y0 + 1);
                let p11 = get(x0 + 1, y0 + 1);
                let mut m = [0.0f32; 4];
                for k in 0..4 {
                    let top = p00[k] * (1.0 - tx) + p10[k] * tx;
                    let bot = p01[k] * (1.0 - tx) + p11[k] * tx;
                    m[k] = top * (1.0 - ty) + bot * ty;
                }
                m
            } else {
                get(sx.floor() as i64, sy.floor() as i64)
            };
            let o = (y * nw + x) * 4;
            let mut col = if m[3] > 1e-6 { [m[0] / m[3], m[1] / m[3], m[2] / m[3], m[3]] } else { [0.0; 4] };
            if let Some(b) = bgf {
                // source-over onto the fill colour
                let a = col[3];
                let ba = b[3] * (1.0 - a);
                let oa = a + ba;
                if oa > 1e-6 {
                    col = [
                        (col[0] * a + b[0] * ba) / oa,
                        (col[1] * a + b[1] * ba) / oa,
                        (col[2] * a + b[2] * ba) / oa,
                        oa,
                    ];
                }
            }
            if col[3] > 1e-6 {
                store(&mut out[o..o + 4], col);
            }
        }
    }
    (out, nw, nh)
}

/// kind: 0 flip H, 1 flip V, 2 rotate 90 CW, 3 rotate 180, 4 rotate 90 CCW
pub fn transform_px(px: &[u8], w: usize, h: usize, kind: u8) -> (Vec<u8>, usize, usize) {
    let (nw, nh) = if kind == 2 || kind == 4 { (h, w) } else { (w, h) };
    let mut out = vec![0u8; w * h * 4];
    for y in 0..h {
        for x in 0..w {
            let (dx, dy) = match kind {
                0 => (w - 1 - x, y),
                1 => (x, h - 1 - y),
                2 => (h - 1 - y, x),
                3 => (w - 1 - x, h - 1 - y),
                _ => (y, w - 1 - x),
            };
            let s = (y * w + x) * 4;
            let d = (dy * nw + dx) * 4;
            out[d..d + 4].copy_from_slice(&px[s..s + 4]);
        }
    }
    (out, nw, nh)
}

fn step_bytes(k: &UndoKind) -> usize {
    64 + match k {
        UndoKind::Tiles { tiles, .. } => tiles.iter().map(|t| t.1.len() + 16).sum(),
        UndoKind::Full { layers, .. } => layers.iter().map(|l| l.px.len()).sum(),
        UndoKind::Structure { pool, mods, .. } => pool.iter().map(|l| l.px.len()).sum::<usize>() + mods.iter().map(|m| m.1.len()).sum::<usize>(),
        UndoKind::Text { px, text, .. } => px.len() + text.len(),
        UndoKind::Props { name, .. } => name.len(),
    }
}

#[cfg(test)]
mod tests {

    #[test]
    fn magic_wand_and_selection_modes() {
        // left half red, right half blue, a red dot inside the blue
        let (w, h) = (20usize, 10usize);
        let mut px = vec![0u8; w * h * 4];
        for y in 0..h {
            for x in 0..w {
                let c = if x < 10 || (x == 15 && y == 5) { [200, 20, 20, 255] } else { [20, 20, 200, 255] };
                px[(y * w + x) * 4..][..4].copy_from_slice(&c);
            }
        }
        let mut d = Doc::from_rgba(w, h, px, "t");
        let count = |d: &Doc| d.sel.as_ref().map_or(0, |m| m.iter().filter(|&&v| v == 255).count());
        d.sel_magic(2, 2, 10, true);
        assert_eq!(count(&d), 100, "contiguous: the red half only");
        d.sel_magic(2, 2, 10, false);
        assert_eq!(count(&d), 101, "everywhere: the dot too");
        d.sel_magic(18, 2, 10, true);
        assert_eq!(count(&d), 99);
        // add the red half to the blue
        d.sel_mode = 1;
        d.sel_magic(2, 2, 10, true);
        assert_eq!(count(&d), 199);
        // subtract a rectangle
        d.sel_mode = 2;
        d.sel_rect(0, 0, 20, 5);
        assert_eq!(count(&d), 99, "rows 0-4 gone");
        assert_eq!(d.sel_mode, 0, "the mode applies once");
        // intersect
        d.sel_all();
        d.sel_mode = 3;
        d.sel_rect(5, 0, 10, 10);
        assert_eq!(count(&d), 100);
    }

    use super::*;
    #[test]
    fn stroke_undo_redo() {
        let mut d = Doc::new(100, 80, [255, 255, 255, 255]);
        d.comp_update();
        let before = d.layers[0].px.clone();
        d.stroke_begin(TOOL_BRUSH, 10.0, 1.0, [255, 0, 0, 255]);
        d.stroke_to(10.0, 10.0);
        d.stroke_to(90.0, 70.0);
        d.stroke_end();
        let after = d.layers[0].px.clone();
        assert_ne!(before, after);
        let mid = (40 * 100 + 50) * 4; // near the stroke path at (50,40)
        assert_eq!(&after[mid..mid + 4], &[255, 0, 0, 255]);
        assert!(d.undo());
        assert_eq!(d.layers[0].px, before);
        assert!(d.redo());
        assert_eq!(d.layers[0].px, after);
    }

    #[test]
    fn pen_pressure_drives_size_and_opacity() {
        // a stroke whose pressure ramps from light to full gets wider and darker along its length
        let width_at = |d: &Doc, x: usize| (0..100).filter(|&y| d.layers[0].px[(y * 200 + x) * 4 + 1] < 128).count();
        let mut d = Doc::new(200, 100, [255, 255, 255, 255]);
        d.stroke_begin(TOOL_BRUSH, 30.0, 1.0, [0, 0, 0, 255]);
        d.stroke_dynamics(1.0, 0.0, false);
        d.stroke_pen(0.1, 0.0, 0.0);
        d.stroke_to(20.0, 50.0);
        d.stroke_pen(1.0, 0.0, 0.0);
        d.stroke_to(180.0, 50.0);
        d.stroke_end();
        let (a, b) = (width_at(&d, 30), width_at(&d, 170));
        assert!(a < 10 && b >= 27, "thin start, full end: {a} {b}");
        // opacity: light pressure leaves a pale stroke
        let mut d = Doc::new(200, 100, [255, 255, 255, 255]);
        d.stroke_begin(TOOL_BRUSH, 20.0, 1.0, [0, 0, 0, 255]);
        d.stroke_dynamics(0.0, 1.0, false);
        d.stroke_pen(0.25, 0.0, 0.0);
        d.stroke_to(20.0, 50.0);
        d.stroke_to(180.0, 50.0);
        d.stroke_end();
        let g = d.layers[0].px[(50 * 200 + 100) * 4];
        assert!(g > 170 && g < 210, "about a quarter dark: {g}");
        // no dynamics (a mouse): unchanged
        let mut d = Doc::new(200, 100, [255, 255, 255, 255]);
        d.stroke_begin(TOOL_BRUSH, 20.0, 1.0, [0, 0, 0, 255]);
        d.stroke_pen(0.1, 0.0, 0.0);
        d.stroke_to(20.0, 50.0);
        d.stroke_to(180.0, 50.0);
        d.stroke_end();
        assert_eq!(d.layers[0].px[(50 * 200 + 100) * 4], 0);
        assert!(width_at(&d, 100) >= 19);
    }

    #[test]
    fn remove_background_is_one_undo_step() {
        let mut d = Doc::new(80, 60, [240, 240, 240, 255]);
        d.shape(&[(20.0, 15.0), (60.0, 15.0), (60.0, 45.0), (20.0, 45.0)], true, 1.0, [0, 0, 0, 0], [30, 90, 200, 255], 2, false);
        let before = d.layers[0].px.clone();
        assert!(d.remove_background());
        assert_eq!(d.layers[0].px[(5 * 80 + 5) * 4 + 3], 0);
        assert_eq!(d.layers[0].px[(30 * 80 + 40) * 4 + 3], 255);
        assert!(!d.remove_background(), "nothing left to remove");
        assert!(d.undo());
        assert_eq!(d.layers[0].px, before);
        // with a selection only the selected part is cut out; the rest stays
        d.sel_rect(0, 0, 40, 60);
        assert!(d.remove_background());
        assert_eq!(d.layers[0].px[(5 * 80 + 5) * 4 + 3], 0);
        assert_eq!(d.layers[0].px[(5 * 80 + 75) * 4 + 3], 255);
    }

    #[test]
    fn pen_tilt_turns_the_calligraphy_nib() {
        // a horizontal stroke with the nib held vertical is tall; with the nib flat it is thin
        let tall = |tx: f32, ty: f32| {
            let mut d = Doc::new(200, 100, [255, 255, 255, 255]);
            d.stroke_begin(TOOL_CALLIGRAPHY, 30.0, 1.0, [0, 0, 0, 255]);
            d.stroke_dynamics(0.0, 0.0, true);
            d.stroke_pen(1.0, tx, ty);
            d.stroke_to(20.0, 50.0);
            d.stroke_to(180.0, 50.0);
            d.stroke_end();
            (0..100).filter(|&y| d.layers[0].px[(y * 200 + 100) * 4] < 128).count()
        };
        let (v, h) = (tall(0.0, 0.8), tall(0.8, 0.0));
        assert!(v > 20 && h < 8, "vertical nib {v}, flat nib {h}");
    }

    #[test]
    fn eraser_makes_transparent_and_layers_composite() {
        let mut d = Doc::new(50, 50, [0, 0, 255, 255]);
        d.stroke_begin(TOOL_ERASER, 20.0, 1.0, [0, 0, 0, 255]);
        d.stroke_to(25.0, 25.0);
        d.stroke_end();
        assert_eq!(d.layers[0].px[(25 * 50 + 25) * 4 + 3], 0);
        d.layer_add("Layer 2");
        d.shape(&[(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)], true, 1.0, [0, 0, 0, 0], [255, 0, 0, 128], 2, true);
        let c = d.pick(25, 25, true);
        assert!(c[0] > 200 && c[3] > 100 && c[3] < 140, "{c:?}");
        assert!(d.undo());
        assert!(d.undo());
        assert_eq!(d.layers.len(), 1);
        assert!(d.redo());
        assert_eq!(d.layers.len(), 2);
    }

    #[test]
    fn float_move_is_one_undo() {
        let mut d = Doc::new(40, 40, [0, 0, 0, 0]);
        d.shape(&[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], true, 1.0, [0; 4], [0, 255, 0, 255], 2, false);
        let base = d.layers[0].px.clone();
        d.sel_rect(0, 0, 10, 10);
        assert!(d.float_lift(true));
        d.float_set_rect(20, 20, 10, 10);
        d.commit_float();
        assert_eq!(d.layers[0].px[(25 * 40 + 25) * 4 + 1], 255);
        assert_eq!(d.layers[0].px[(5 * 40 + 5) * 4 + 3], 0);
        assert!(d.undo());
        assert_eq!(d.layers[0].px, base);
    }

    #[test]
    fn rotate_any_angle() {
        assert_eq!(rotated_size(100, 50, 90.0), (50, 100));
        assert_eq!(rotated_size(100, 50, -90.0), (50, 100));
        assert_eq!(rotated_size(100, 100, 45.0), (142, 142));
        let mut d = Doc::new(40, 20, [255, 0, 0, 255]);
        d.layer_add("Top");
        d.image_rotate(30.0, true, Some([0, 0, 255, 255]));
        let (w, h) = rotated_size(40, 20, 30.0);
        assert_eq!((d.w, d.h), (w, h));
        assert_eq!(d.layers[1].px.len(), w * h * 4);
        // the middle is still red, the corner is the fill colour on the bottom layer
        let mid = ((h / 2) * w + w / 2) * 4;
        assert_eq!(&d.layers[0].px[mid..mid + 4], &[255, 0, 0, 255]);
        assert_eq!(&d.layers[0].px[0..4], &[0, 0, 255, 255]);
        assert_eq!(d.layers[1].px[3], 0);
        assert!(d.undo());
        assert_eq!((d.w, d.h), (40, 20));
        // -90 is exact and lossless, and 360 changes nothing
        let mut e = Doc::new(30, 10, [1, 2, 3, 255]);
        e.layers[0].px[0..4].copy_from_slice(&[9, 9, 9, 255]);
        e.image_rotate(-90.0, true, None);
        assert_eq!((e.w, e.h), (10, 30));
        assert_eq!(&e.layers[0].px[(29 * 10) * 4..(29 * 10) * 4 + 4], &[9, 9, 9, 255]);
        e.image_rotate(360.0, true, None);
        assert_eq!((e.w, e.h), (10, 30));
        // nearest neighbour keeps only colours from the source
        let (px, _, _) = rotate_px(&vec![200u8; 16 * 16 * 4], 16, 16, 17.0, false, None);
        assert!(px.chunks_exact(4).all(|p| p == [0, 0, 0, 0] || p == [200, 200, 200, 200]));
    }

    #[test]
    fn rotate_float() {
        let mut d = Doc::new(60, 60, [255, 255, 255, 255]);
        d.sel_rect(10, 10, 20, 10);
        assert!(d.float_lift(true));
        d.float_rotate(90.0, true);
        let f = d.float.as_ref().unwrap();
        assert_eq!((f.w, f.h), (10, 20));
        assert_eq!((f.x, f.y), (15, 5));
        d.float_rotate(45.0, true);
        let f = d.float.as_ref().unwrap();
        assert_eq!((f.w, f.h), rotated_size(10, 20, 45.0));
        d.commit_float();
        assert!(d.float.is_none());
    }

    #[test]
    fn fill_and_rotate() {
        let mut d = Doc::new(30, 20, [255, 255, 255, 255]);
        d.shape(&[(10.0, 0.0), (10.0, 20.0)], false, 2.0, [0, 0, 0, 255], [0; 4], 1, false);
        assert!(d.flood_fill(2, 2, [255, 0, 0, 255], 0));
        assert_eq!(&d.layers[0].px[(2 * 30 + 2) * 4..(2 * 30 + 2) * 4 + 4], &[255, 0, 0, 255]);
        assert_eq!(&d.layers[0].px[(2 * 30 + 25) * 4..(2 * 30 + 25) * 4 + 4], &[255, 255, 255, 255]);
        d.image_transform(2);
        assert_eq!((d.w, d.h), (20, 30));
        assert!(d.undo());
        assert_eq!((d.w, d.h), (30, 20));
    }
}
