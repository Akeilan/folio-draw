//! Stitch generators: tatami fill, satin columns and running stitch, each producing runs of
//! needle points that the sequencer joins up.

use super::geom::*;
use super::json::J;
use super::raster::Mask;
use super::skeleton::centre_lines;
use super::trace::trace_mask;

pub const MASK_S: f32 = 20.0; // px/mm for shape-level raster work

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Kind {
    Auto,
    Fill,
    Satin,
    Run,
    /// placement line, stop, tack-down, stop, satin cover over the edge
    Applique,
    /// a light net sewn first to flatten pile (towels, fleece) so the design sits on top
    Knockdown,
}

#[derive(Clone, Debug)]
pub struct Settings {
    pub kind: Kind,
    pub angle: Option<f32>, // degrees; None = alternate 45/135 by colour
    pub spacing: f32,
    pub length: f32,
    pub stagger: f32,
    pub pull: f32,
    pub underlay: bool,
    pub satin_spacing: f32,
    pub min_width: f32,
    pub run_length: f32,
    pub bean: bool,
    /// appliqué: width of the satin cover over the fabric's edge
    pub cover: f32,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            kind: Kind::Auto,
            angle: None,
            spacing: 0.35,
            length: 3.5,
            stagger: 1.0 / 3.0,
            pull: 0.20,
            underlay: true,
            satin_spacing: 0.40,
            min_width: 1.0,
            run_length: 2.0,
            bean: true,
            cover: 3.0,
        }
    }
}

impl Settings {
    pub fn from_json(j: &J) -> Settings {
        let d = Settings::default();
        let kind = match j.get("type").s() {
            "fill" => Kind::Fill,
            "satin" => Kind::Satin,
            "run" => Kind::Run,
            "applique" => Kind::Applique,
            "knockdown" => Kind::Knockdown,
            _ => Kind::Auto,
        };
        let a = j.get("angle");
        Settings {
            kind,
            angle: if a.is_null() { None } else { Some(a.f32(45.0)) },
            spacing: j.get("spacing").f32(d.spacing).clamp(0.2, 5.0),
            length: j.get("length").f32(d.length).clamp(1.0, 7.0),
            stagger: j.get("stagger").f32(d.stagger).clamp(0.0, 1.0),
            pull: j.get("pull").f32(d.pull).clamp(0.0, 1.0),
            underlay: j.get("underlay").b(d.underlay),
            satin_spacing: j.get("satin_spacing").f32(d.satin_spacing).clamp(0.2, 2.0),
            min_width: j.get("min_width").f32(d.min_width).clamp(0.3, 3.0),
            run_length: j.get("run_length").f32(d.run_length).clamp(1.0, 7.0),
            bean: j.get("bean").b(d.bean),
            cover: j.get("cover").f32(d.cover).clamp(1.0, 8.0),
        }
    }
}

/// A run of needle points sewn one after another. `alt` is the same work sewn from the other
/// end (None when it can't be turned round); `closed` runs may start at any of their points.
#[derive(Clone, Debug)]
pub struct Run {
    pub pts: Vec<Pt>,
    pub alt: Option<Vec<Pt>>,
    pub closed: bool,
    pub top: bool,
}

/// The work for one shape, in stages: runs of a stage are visited nearest-first, stages in order.
pub type Stages = Vec<Vec<Run>>;

pub fn shape_mask(rings: &[Ring], pad: f32) -> Mask {
    let b = bbox(rings);
    let mut m = Mask::new(b.0 - pad, b.1 - pad, b.2 + pad, b.3 + pad, MASK_S);
    m.fill(rings, true);
    m
}

/// Widest point: diameter of the largest inscribed circle (distance-transform maximum).
pub fn inscribed_width(m: &Mask) -> f32 {
    m.inside_mm().into_iter().fold(0.0, f32::max) * 2.0
}

/// The stitch type auto picks: under 0.5 mm running, 0.5–7 mm satin, over 7 mm fill.
pub fn auto_kind(width: f32) -> Kind {
    if width < 0.5 {
        Kind::Run
    } else if width <= 7.0 {
        Kind::Satin
    } else {
        Kind::Fill
    }
}

// ------------------------------------------------------------------ fill

pub struct FillOpts {
    pub angle: f32,
    pub spacing: f32,
    pub length: f32,
    pub stagger: f32,
    pub extend: f32, // pull compensation (> 0) or inset (< 0) at each row end
    pub min: f32,
    pub top: bool,
}

/// Tatami: rows on a global grid in the rotated frame (row k at (k − ½)·spacing) so
/// neighbouring shapes line up; needle points on a global grid along each row, staggered by
/// `stagger` of a stitch per row. Row segments are grouped into blocks sewn back and forth.
pub fn fill_runs(rings: &[Ring], o: &FillOpts) -> Vec<Run> {
    let a = o.angle.to_radians();
    let (c, s) = (a.cos(), a.sin());
    // into the frame where rows are horizontal
    let rr: Vec<Ring> = rings.iter().map(|r| r.iter().map(|p| rot(*p, c, -s)).collect()).collect();
    let b = bbox(&rr);
    if !b.0.is_finite() {
        return Vec::new();
    }
    let k0 = (b.1 / o.spacing + 0.5).floor() as i64 - 1;
    let k1 = (b.3 / o.spacing + 0.5).ceil() as i64 + 1;
    // rows: (k, [segments a..b])
    let mut rows: Vec<(i64, Vec<(f32, f32, f32, f32)>)> = Vec::new(); // (orig a, orig b, ext a, ext b)
    for k in k0..=k1 {
        let y = (k as f32 - 0.5) * o.spacing;
        let xs = scanline(&rr, y);
        let mut segs = Vec::new();
        for pair in xs.chunks_exact(2) {
            let (x0, x1) = (pair[0], pair[1]);
            let (e0, e1) = (x0 - o.extend, x1 + o.extend);
            if e1 - e0 < o.min.max(0.3) {
                continue;
            }
            segs.push((x0, x1, e0, e1));
        }
        if !segs.is_empty() {
            rows.push((k, segs));
        }
    }
    let ov = |a: (f32, f32, f32, f32), b: (f32, f32, f32, f32)| a.0 < b.1 && b.0 < a.1;
    // blocks as lists of (row index into rows, segment index)
    let mut blocks: Vec<Vec<(usize, usize)>> = Vec::new();
    let mut open: Vec<Option<usize>> = Vec::new(); // per segment of previous row: its block
    for ri in 0..rows.len() {
        let (k, segs) = (&rows[ri].0, &rows[ri].1);
        let prev = if ri > 0 && rows[ri - 1].0 == k - 1 { Some(ri - 1) } else { None };
        let mut next_open = vec![None; segs.len()];
        for (si, seg) in segs.iter().enumerate() {
            let mut link = None;
            if let Some(pr) = prev {
                let psegs = &rows[pr].1;
                let hits: Vec<usize> = (0..psegs.len()).filter(|&pi| ov(psegs[pi], *seg)).collect();
                if hits.len() == 1 {
                    let pi = hits[0];
                    let back: usize = segs.iter().filter(|s2| ov(psegs[pi], **s2)).count();
                    if back == 1 {
                        if let Some(bi) = open.get(pi).copied().flatten() {
                            link = Some(bi);
                        }
                    }
                }
            }
            let bi = match link {
                Some(bi) => bi,
                None => {
                    blocks.push(Vec::new());
                    blocks.len() - 1
                }
            };
            blocks[bi].push((ri, si));
            next_open[si] = Some(bi);
        }
        open = next_open;
    }
    let mut runs = Vec::new();
    let near_shape = |p: Pt| inside(&rr, p) || nearest_on_rings(&rr, p).3 < 0.3;
    for blk in blocks {
        let mut cur: Vec<Pt> = Vec::new();
        let mut forward = true;
        let mut last_end: Option<Pt> = None;
        for (ri, si) in blk {
            let k = rows[ri].0;
            let seg = rows[ri].1[si];
            let y = (k as f32 - 0.5) * o.spacing;
            let (a0, b0) = (seg.2, seg.3);
            let (start, end) = if forward { (a0, b0) } else { (b0, a0) };
            let sp = (start, y);
            if let Some(le) = last_end {
                // split the block where the connector to this row would leave the shape
                let ok = [0.25f32, 0.5, 0.75].iter().all(|t| near_shape(lerp(le, sp, *t)));
                if !ok {
                    if cur.len() >= 2 {
                        runs.push(std::mem::take(&mut cur));
                    }
                    cur.clear();
                }
            }
            row_points(&mut cur, start, end, y, k, o);
            last_end = Some((end, y));
            forward = !forward;
        }
        if cur.len() >= 2 {
            runs.push(cur);
        }
    }
    runs.into_iter()
        .map(|r| {
            let pts: Vec<Pt> = r.into_iter().map(|p| rot(p, c, s)).collect();
            let mut alt = pts.clone();
            alt.reverse();
            Run { pts, alt: Some(alt), closed: false, top: o.top }
        })
        .collect()
}

fn row_points(out: &mut Vec<Pt>, start: f32, end: f32, y: f32, k: i64, o: &FillOpts) {
    out.push((start, y));
    let phase = (k.rem_euclid(3)) as f32 * o.stagger * o.length;
    let (lo, hi) = (start.min(end), start.max(end));
    let j0 = ((lo - phase) / o.length).floor() as i64;
    let j1 = ((hi - phase) / o.length).ceil() as i64;
    let mut grid: Vec<f32> = (j0..=j1)
        .map(|j| j as f32 * o.length + phase)
        .filter(|g| *g > lo + o.min && *g < hi - o.min)
        .collect();
    if start > end {
        grid.reverse();
    }
    for g in grid {
        out.push((g, y));
    }
    out.push((end, y));
}

/// Running stitch along a polyline, `len` per stitch; triple ("bean") goes forward, back, forward.
pub fn running(path: &[Pt], len: f32, bean: bool) -> Vec<Pt> {
    let pts = resample(path, len);
    if !bean || pts.len() < 2 {
        return pts;
    }
    let mut out = vec![pts[0]];
    for w in pts.windows(2) {
        out.push(w[1]);
        out.push(w[0]);
        out.push(w[1]);
    }
    out
}

fn ring_closed(r: &[Pt]) -> Vec<Pt> {
    let mut p = r.to_vec();
    if let Some(f) = r.first() {
        p.push(*f);
    }
    p
}

/// Edge-run underlay: each ring inset by `inset` (outline shrinks, holes grow).
pub fn edge_runs(rings: &[Ring], inset: f32, len: f32) -> Vec<Run> {
    let mut out = Vec::new();
    for (i, r) in rings.iter().enumerate() {
        if r.len() < 3 {
            continue;
        }
        let o = offset_ring(r, if i == 0 { -inset } else { inset });
        if signed_area(&o).abs() < 0.5 || signed_area(&o).signum() != signed_area(r).signum() {
            continue;
        }
        let mut pts = resample(&ring_closed(&o), len);
        pts.pop();
        if pts.len() >= 3 {
            out.push(Run { pts, alt: None, closed: true, top: false });
        }
    }
    out
}

// ------------------------------------------------------------------ satin

struct Rail {
    p: Pt,
    n: Pt,
    l: f32,
    r: f32,
}

fn rails_for(path: &[Pt], rings: &[Ring], dist: &dyn Fn(Pt) -> f32, step: f32, st: &Settings) -> Vec<Rail> {
    let pts = resample(path, step);
    let n = pts.len();
    let mut out = Vec::new();
    for i in 0..n {
        let a = pts[if i == 0 { 0 } else { i - 1 }];
        let b = pts[if i + 1 >= n { n - 1 } else { i + 1 }];
        let t = norm(sub(b, a));
        if t == (0.0, 0.0) {
            continue;
        }
        let nn = (-t.1, t.0);
        let p = pts[i];
        let r0 = dist(p).max(0.05);
        let lh = ray_hits(rings, p, nn);
        let rh = ray_hits(rings, p, (-nn.0, -nn.1));
        let (Some(&l), Some(&r)) = (lh.first(), rh.first()) else { continue };
        // clamp each side: rays at tight curves and junctions run across bowls otherwise
        let cap = 1.3 * r0 + 0.15;
        let (l, r) = (l.min(cap), r.min(cap));
        if l + r > 6.0 * r0 + 1.0 {
            continue;
        }
        let _ = st;
        out.push(Rail { p, n: nn, l, r });
    }
    out
}

/// Widen a column under the minimum width; otherwise add pull compensation. A widened column
/// gets no pull compensation (it would make thin lines stitch far too wide).
fn finish_rail(r: &Rail, st: &Settings) -> (f32, f32) {
    let w = r.l + r.r;
    if w < st.min_width {
        let add = (st.min_width - w) * 0.5;
        (r.l + add, r.r + add)
    } else {
        let pc = st.pull * 0.5;
        (r.l + pc, r.r + pc)
    }
}

fn satin_chain(path: &[Pt], rings: &[Ring], dist: &dyn Fn(Pt) -> f32, st: &Settings) -> Option<(Vec<Pt>, Vec<(Pt, Pt)>, f32)> {
    let mut rails = rails_for(path, rings, dist, st.satin_spacing * 0.5, st);
    if rails.len() < 2 {
        return None;
    }
    // where columns meet, rays run off along the other column and the stitches fan out: no
    // side may reach past 1.5× the column's usual half width (the junction gets a small fill)
    let mut halves: Vec<f32> = rails.iter().flat_map(|r| [r.l, r.r]).collect();
    halves.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let cap = halves[halves.len() / 2] * 1.5 + 0.1;
    for r in rails.iter_mut() {
        r.l = r.l.min(cap);
        r.r = r.r.min(cap);
    }
    let ends: Vec<(Pt, Pt)> = rails
        .iter()
        .map(|r| {
            let (l, rr) = finish_rail(r, st);
            (add(r.p, mul(r.n, l)), sub(r.p, mul(r.n, rr)))
        })
        .collect();
    let mean_w = rails.iter().map(|r| r.l + r.r).sum::<f32>() / rails.len() as f32;
    let mut chain = Vec::new();
    if st.underlay {
        let centre: Vec<Pt> = rails.iter().map(|r| r.p).collect();
        if mean_w > 2.5 {
            // centre walk out, 60 %-width zig-zag back at 2 mm, then the satin
            chain.extend(resample(&centre, 2.0));
            let back: Vec<Pt> = centre.iter().rev().copied().collect();
            let samples = resample(&back, 1.0);
            for (i, p) in samples.iter().enumerate() {
                // nearest rail for the local width
                let ri = (((samples.len() - 1 - i) as f32 / (samples.len().max(2) - 1) as f32) * (rails.len() - 1) as f32).round() as usize;
                let r = &rails[ri.min(rails.len() - 1)];
                let half = 0.3 * (r.l + r.r);
                let side = if i % 2 == 0 { 1.0 } else { -1.0 };
                chain.push(add(*p, mul(r.n, half * side)));
            }
        } else if mean_w >= 1.2 {
            chain.extend(resample(&centre, 2.0));
            let back: Vec<Pt> = centre.iter().rev().copied().collect();
            chain.extend(resample(&back, 2.0).into_iter().skip(1));
        }
    }
    for (i, e) in ends.iter().enumerate() {
        chain.push(if i % 2 == 0 { e.0 } else { e.1 });
    }
    Some((chain, ends, mean_w))
}

fn quads_mask(m: &Mask, ends: &[(Pt, Pt)]) -> Mask {
    let mut cov = m.like();
    for w in ends.windows(2) {
        let q = vec![w[0].0, w[1].0, w[1].1, w[0].1];
        cov.fill(&[q], true);
    }
    cov
}

/// Square up a column's ends. The skeleton bends near its ends (into a junction, toward a
/// corner of the stroke's end), and rails square to a bend fan out; so each end keeps the
/// direction of the straight part behind it and runs on in that line to the outline.
pub fn column_ends(path: &[Pt], dist: &dyn Fn(Pt) -> f32) -> Vec<Pt> {
    let step = 0.05;
    let pts = resample(path, step);
    let n = pts.len();
    if n < 8 {
        return path.to_vec();
    }
    let mut sorted: Vec<f32> = pts.iter().map(|p| dist(*p)).collect();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let med = sorted[n / 2].max(0.1);
    let w = 2.0 * med;
    // half a column width in from each end (less on short columns)
    let k1 = (((w * 0.5) / step) as usize).min(n / 6).max(2);
    let k2 = 2 * k1;
    if n < 2 * k2 + 4 {
        return path.to_vec();
    }
    let run = |from: Pt, d: Pt| -> Vec<Pt> {
        let mut out = Vec::new();
        let mut cur = from;
        for _ in 0..((3.0 * w / step) as usize) {
            let nx = add(cur, mul(d, step));
            if dist(nx) < 0.15 {
                break;
            }
            cur = nx;
            out.push(cur);
        }
        out
    };
    let d_end = norm(sub(pts[n - 1 - k1], pts[n - 1 - k2]));
    let d_start = norm(sub(pts[k1], pts[k2]));
    let mut out: Vec<Pt> = run(pts[k1], d_start).into_iter().rev().collect();
    out.extend_from_slice(&pts[k1..n - k1]);
    out.extend(run(pts[n - 1 - k1], d_end));
    if out.len() < 4 {
        return path.to_vec();
    }
    out
}

fn line_meet(p: Pt, d: Pt, q: Pt, e: Pt) -> Option<Pt> {
    let den = cross(d, e);
    if den.abs() < 0.2 {
        return None; // nearly parallel: no corner to square off
    }
    let t = cross(sub(q, p), e) / den;
    Some(add(p, mul(d, t)))
}

/// Split a centre line at its sharp corners (turns over 50° within about a column width) into
/// straight pieces. At each corner the incoming column runs on to the far edge of the outgoing
/// one, and the outgoing column starts at the incoming one's inner edge: a butt joint, so the
/// corner square is sewn once, by straight stitches.
pub fn split_corners(path: &[Pt], dist: &dyn Fn(Pt) -> f32, width: f32) -> Vec<Vec<Pt>> {
    let step = 0.1;
    let mut pts = resample(path, step);
    let n0 = pts.len();
    if n0 < 8 {
        return vec![path.to_vec()];
    }
    let closed = dist_pts(pts[0], pts[n0 - 1]) < 0.15;
    let span = (width.max(0.8) / step).round().max(3.0) as usize;
    let turn = |pts: &Vec<Pt>, i: usize, closed: bool| -> f32 {
        let n = pts.len();
        let (a, b) = if closed {
            (pts[(i + n - 1 - span % (n - 1)) % (n - 1)], pts[(i + span) % (n - 1)])
        } else {
            if i < span || i + span >= n {
                return 0.0;
            }
            (pts[i - span], pts[i + span])
        };
        let d0 = norm(sub(pts[i], a));
        let d1 = norm(sub(b, pts[i]));
        dot(d0, d1).clamp(-1.0, 1.0).acos()
    };
    let limit = 50f32.to_radians();
    let find = |pts: &Vec<Pt>, closed: bool| -> Vec<usize> {
        let n = if closed { pts.len() - 1 } else { pts.len() };
        let t: Vec<f32> = (0..n).map(|i| turn(pts, i, closed)).collect();
        let mut out: Vec<usize> = Vec::new();
        let mut i = 0;
        while i < n {
            if t[i] > limit {
                // the sharpest point of this bend
                let mut j = i;
                let mut best = i;
                while j < n && t[j] > limit {
                    if t[j] > t[best] {
                        best = j;
                    }
                    j += 1;
                }
                if out.last().map_or(true, |&l| best - l > 2 * span) {
                    out.push(best);
                }
                i = j;
            } else {
                i += 1;
            }
        }
        out
    };
    let mut corners = find(&pts, closed);
    if corners.is_empty() {
        return vec![path.to_vec()];
    }
    if closed {
        // start the loop at its first corner, so every corner sits between two pieces
        let c0 = corners[0];
        let n = pts.len() - 1;
        let mut r: Vec<Pt> = (0..=n).map(|k| pts[(c0 + k) % n]).collect();
        r[n] = r[0];
        pts = r;
        corners = find(&pts, false).into_iter().filter(|&c| c > span && c + span < pts.len()).collect();
        let mut cs = vec![0];
        cs.extend(corners);
        cs.push(pts.len() - 1);
        return butt_pieces(&pts, &cs, dist, span, true);
    }
    let mut cs = vec![0];
    cs.extend(corners.into_iter().filter(|&c| c > span && c + span < pts.len()));
    cs.push(pts.len() - 1);
    butt_pieces(&pts, &cs, dist, span, false)
}

fn dist_pts(a: Pt, b: Pt) -> f32 {
    dist(a, b)
}

fn butt_pieces(pts: &[Pt], cs: &[usize], dist: &dyn Fn(Pt) -> f32, span: usize, closed: bool) -> Vec<Vec<Pt>> {
    // corners are cs[1..len-1] (and, closed, cs[0] == cs[last] too)
    let k = cs.len() - 1;
    let mut pieces: Vec<Vec<Pt>> = (0..k).map(|i| pts[cs[i]..=cs[i + 1]].to_vec()).collect();
    let corner_ids: Vec<usize> = if closed { (0..k).collect() } else { (1..k).collect() };
    for &ci in &corner_ids {
        // between piece a (ending at the corner) and piece b (starting there)
        let (a, b) = if ci == 0 { (k - 1, 0) } else { (ci - 1, ci) };
        let (pa, pb) = (&pieces[a], &pieces[b]);
        if pa.len() < 2 * span + 2 || pb.len() < 2 * span + 2 {
            continue;
        }
        let a1 = pa[pa.len() - 1 - span];
        let a0 = pa[pa.len() - 1 - 2 * span.min((pa.len() - 1) / 2 - 1).max(1)];
        let b1 = pb[span];
        let b2 = pb[(2 * span).min(pb.len() - 1)];
        let da = norm(sub(a1, a0));
        let db = norm(sub(b2, b1));
        let Some(x) = line_meet(a1, da, b1, db) else { continue };
        let corner = pa[pa.len() - 1];
        let ra = dist(a1).max(0.2);
        let rb = dist(b1).max(0.2);
        if dist_pts(x, corner) > 3.0 * (ra + rb) {
            continue;
        }
        // a right-angle turn gets a butt joint; a sharp point (an M or A apex) just meets at
        // the point. Either way the ends stay inside the shape, or their stitches would stick out
        let sharp = dot(da, db) < -0.34; // turned by more than ~110°
        let inside_end = |from: Pt, to: Pt| -> Pt {
            let mut q = to;
            for _ in 0..40 {
                if dist(q) > 0.1 {
                    return q;
                }
                q = lerp(q, from, 0.1);
            }
            from
        };
        let a_end = inside_end(a1, if sharp { x } else { add(x, mul(da, rb)) });
        let b_start = inside_end(b1, if sharp { x } else { add(x, mul(db, ra)) });
        let mut na: Vec<Pt> = pa[..pa.len() - span].to_vec();
        na.push(a_end);
        let mut nb: Vec<Pt> = vec![b_start];
        nb.extend_from_slice(&pb[span..]);
        pieces[a] = na;
        pieces[b] = nb;
    }
    pieces
}

/// Satin for a shape: centre lines, rails clamped to the outline, coverage check (under 75 %
/// falls back to fill), residual patches as small fills sewn first.
pub fn satin_stages(rings: &[Ring], m: &Mask, st: &Settings, width: f32, fill_angle: f32) -> Option<Stages> {
    let dvals = m.inside_mm();
    let dist = |p: Pt| -> f32 {
        let i = ((p.0 - m.x0) * m.s).floor();
        let j = ((p.1 - m.y0) * m.s).floor();
        if i < 0.0 || j < 0.0 || i >= m.w as f32 || j >= m.h as f32 {
            return 0.0;
        }
        dvals[j as usize * m.w + i as usize]
    };
    let spur = (0.7 * width).max(0.8);
    let raw: Vec<Vec<Pt>> = centre_lines(m, spur).into_iter().filter(|p| p.len() >= 2 && path_length(p) > 0.2).collect();
    // sharp corners: a column turned through a right angle fans its stitches into a starburst,
    // so it is cut into straight columns that meet with a butt joint
    let paths: Vec<Vec<Pt>> = raw
        .iter()
        .flat_map(|p| split_corners(p, &dist, width))
        .map(|p| column_ends(&p, &dist))
        .filter(|p| p.len() >= 2 && path_length(p) > 0.2)
        .collect();
    if paths.is_empty() {
        return None;
    }
    let mut chains = Vec::new();
    let mut cov = m.like();
    for p in &paths {
        let Some((fwd, ends, _)) = satin_chain(p, rings, &dist, st) else { continue };
        let rev: Vec<Pt> = p.iter().rev().copied().collect();
        let alt = satin_chain(&rev, rings, &dist, st).map(|c| c.0);
        let q = quads_mask(m, &ends);
        cov = cov.or(&q);
        chains.push(Run { pts: fwd, alt, closed: false, top: true });
    }
    let total = m.count().max(1);
    let covered = cov.and(m).count();
    if (covered as f32) < 0.75 * total as f32 || chains.is_empty() {
        return None;
    }
    // residual patches the columns miss: corners, junctions, stroke ends
    let resid = m.minus(&cov.offset(0.15));
    let mut patches = Vec::new();
    for prings in trace_mask(&resid, 0.05) {
        if rings_area(&prings) < 0.4 {
            continue;
        }
        let o = FillOpts { angle: fill_angle, spacing: st.spacing, length: st.length, stagger: st.stagger, extend: 0.1, min: 0.3, top: true };
        patches.extend(fill_runs(&prings, &o));
    }
    let mut stages = Vec::new();
    if !patches.is_empty() {
        stages.push(patches);
    }
    stages.push(chains);
    Some(stages)
}

// ------------------------------------------------------------------ per shape

pub fn fill_stages(rings: &[Ring], st: &Settings, angle: f32) -> Stages {
    let mut stages = Vec::new();
    let area = rings_area(rings);
    if st.underlay && area > 6.0 {
        let e = edge_runs(rings, 0.4, 2.5);
        if !e.is_empty() {
            stages.push(e);
        }
        let o = FillOpts { angle: angle + 90.0, spacing: 2.0, length: 3.0, stagger: 0.5, extend: -0.4, min: 0.3, top: false };
        let u = fill_runs(rings, &o);
        if !u.is_empty() {
            stages.push(u);
        }
    }
    let o = FillOpts { angle, spacing: st.spacing, length: st.length, stagger: st.stagger, extend: st.pull, min: 0.3, top: true };
    stages.push(fill_runs(rings, &o));
    stages
}

pub fn run_stages(rings: &[Ring], m: &Mask, st: &Settings, centre: bool) -> Stages {
    let mut runs = Vec::new();
    if centre {
        for p in centre_lines(m, 0.3) {
            if p.len() < 2 {
                continue;
            }
            let fwd = running(&p, st.run_length, st.bean);
            let rev: Vec<Pt> = p.iter().rev().copied().collect();
            let alt = running(&rev, st.run_length, st.bean);
            runs.push(Run { pts: fwd, alt: Some(alt), closed: false, top: true });
        }
    }
    if runs.is_empty() {
        for r in rings {
            if r.len() < 2 {
                continue;
            }
            let mut pts = running(&ring_closed(r), st.run_length, st.bean);
            pts.pop();
            if pts.len() >= 2 {
                runs.push(Run { pts, alt: None, closed: !st.bean, top: true });
            }
        }
    }
    vec![runs]
}

/// Everything one shape needs: (resolved kind, stages).
/// Knockdown: two light passes of long stitches crossing at right angles, 1.5 mm apart.
pub fn knockdown_stages(rings: &[Ring], angle: f32) -> Stages {
    let mut out = Vec::new();
    for a in [angle, angle + 90.0] {
        let o = FillOpts { angle: a, spacing: 1.5, length: 4.0, stagger: 0.5, extend: 0.0, min: 0.3, top: false };
        let r = fill_runs(rings, &o);
        if !r.is_empty() {
            out.push(r);
        }
    }
    out
}

/// Appliqué in three parts, a stop between each: where the fabric goes (a running line on the
/// outline), the tack-down that holds it (a running line just inside), and the satin cover
/// over the trimmed edge.
pub fn applique_parts(rings: &[Ring], st: &Settings, angle: f32) -> Vec<Stages> {
    let mut place = Vec::new();
    let mut tack = Vec::new();
    for (i, r) in rings.iter().enumerate() {
        if r.len() < 3 {
            continue;
        }
        let mut p = resample(&ring_closed(r), 2.5);
        p.pop();
        if p.len() >= 3 {
            place.push(Run { pts: p, alt: None, closed: true, top: false });
        }
        let inset = offset_ring(r, if i == 0 { -0.6 } else { 0.6 });
        if signed_area(&inset).abs() > 0.5 && signed_area(&inset).signum() == signed_area(r).signum() {
            let mut t = resample(&ring_closed(&inset), 2.0);
            t.pop();
            if t.len() >= 3 {
                tack.push(Run { pts: t, alt: None, closed: true, top: false });
            }
        }
    }
    // the cover: a band along the outline, cover wide, as satin
    let m = shape_mask(rings, st.cover + 1.0);
    let band = m.offset(st.cover * 0.5).minus(&m.offset(-st.cover * 0.5));
    let mut cover: Stages = Vec::new();
    let mut cst = st.clone();
    cst.kind = Kind::Satin;
    cst.underlay = true;
    for b in trace_mask(&band, 0.05) {
        let (_, s) = shape_stages(&b, &cst, angle);
        for (k, stage) in s.into_iter().enumerate() {
            if cover.len() <= k {
                cover.push(Vec::new());
            }
            cover[k].extend(stage);
        }
    }
    let mut parts = Vec::new();
    if !place.is_empty() {
        parts.push(vec![place]);
    }
    if !tack.is_empty() {
        parts.push(vec![tack]);
    }
    if !cover.is_empty() {
        parts.push(cover);
    }
    parts
}

pub fn shape_stages(rings: &[Ring], st: &Settings, angle: f32) -> (Kind, Stages) {
    if st.kind == Kind::Knockdown {
        return (Kind::Knockdown, knockdown_stages(rings, angle));
    }
    if st.kind == Kind::Applique {
        // the parts are sewn with stops between them by the sequencer; alone, all in a row
        let parts = applique_parts(rings, st, angle);
        return (Kind::Applique, parts.into_iter().flatten().collect());
    }
    let m = shape_mask(rings, 0.5);
    let width = inscribed_width(&m);
    let mut kind = if st.kind == Kind::Auto { auto_kind(width) } else { st.kind };
    if kind == Kind::Satin {
        if let Some(s) = satin_stages(rings, &m, st, width, angle) {
            return (kind, s);
        }
        kind = Kind::Fill;
    }
    if kind == Kind::Run {
        return (kind, run_stages(rings, &m, st, st.kind == Kind::Auto || width < 0.5));
    }
    (Kind::Fill, fill_stages(rings, st, angle))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sq(x: f32, y: f32, s: f32) -> Ring {
        vec![(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
    }
    #[test]
    fn fill_rows_and_limits() {
        let o = FillOpts { angle: 0.0, spacing: 0.4, length: 3.5, stagger: 1.0 / 3.0, extend: 0.2, min: 0.3, top: true };
        let runs = fill_runs(&[sq(0.0, 0.0, 20.0)], &o);
        assert_eq!(runs.len(), 1);
        let p = &runs[0].pts;
        let mut maxs: f32 = 0.0;
        for w in p.windows(2) {
            maxs = maxs.max(dist(w[0], w[1]));
        }
        assert!(maxs <= 3.5 + 0.3 + 0.21, "{maxs}");
        // 50 rows of 0.4 mm
        let rows = p.iter().map(|q| (q.1 * 100.0).round() as i64).collect::<std::collections::BTreeSet<_>>();
        assert_eq!(rows.len(), 50);
    }
    #[test]
    fn rows_line_up_across_shapes() {
        let o = FillOpts { angle: 30.0, spacing: 0.4, length: 3.5, stagger: 1.0 / 3.0, extend: 0.0, min: 0.3, top: true };
        let a = fill_runs(&[sq(0.0, 0.0, 10.0)], &o);
        let b = fill_runs(&[sq(10.0, 0.0, 10.0)], &o);
        let (c, s) = ((-30f32).to_radians().cos(), (-30f32).to_radians().sin());
        let rowy = |p: Pt| rot(p, c, s).1;
        let ya: std::collections::BTreeSet<i64> = a[0].pts.iter().map(|p| (rowy(*p) * 1000.0).round() as i64).collect();
        let yb: std::collections::BTreeSet<i64> = b[0].pts.iter().map(|p| (rowy(*p) * 1000.0).round() as i64).collect();
        assert!(ya.intersection(&yb).count() > 10);
    }
    #[test]
    fn u_shape_splits_into_blocks() {
        let u: Ring = vec![(0.0, 0.0), (3.0, 0.0), (3.0, 7.0), (7.0, 7.0), (7.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let o = FillOpts { angle: 0.0, spacing: 0.4, length: 3.5, stagger: 1.0 / 3.0, extend: 0.0, min: 0.3, top: true };
        let runs = fill_runs(&[u], &o);
        assert!(runs.len() >= 3, "{}", runs.len());
    }
    #[test]
    fn right_angle_column_is_split() {
        // an L of 2 mm columns: two straight pieces meeting square, no fan at the corner
        let l: Ring = vec![(0.0, 0.0), (20.0, 0.0), (20.0, 2.0), (2.0, 2.0), (2.0, 20.0), (0.0, 20.0)];
        let m = shape_mask(&[l.clone()], 0.5);
        let dv = m.inside_mm();
        let dist = |p: Pt| -> f32 {
            let i = ((p.0 - m.x0) * m.s).floor();
            let j = ((p.1 - m.y0) * m.s).floor();
            if i < 0.0 || j < 0.0 || i >= m.w as f32 || j >= m.h as f32 {
                return 0.0;
            }
            dv[j as usize * m.w + i as usize]
        };
        let paths = centre_lines(&m, 1.4);
        let pieces: Vec<Vec<Pt>> = paths.iter().flat_map(|p| split_corners(p, &dist, 2.0)).collect();
        assert_eq!(pieces.len(), 2, "{}", pieces.len());
        // each piece is straight: its points stay close to the line through its ends
        for p in &pieces {
            let (a, b) = (p[0], *p.last().unwrap());
            let worst = p.iter().map(|q| dist_to_segment(*q, a, b)).fold(0.0, f32::max);
            assert!(worst < 0.2, "piece bends by {worst}");
        }
        let (k, st) = shape_stages(&[l], &Settings::default(), 45.0);
        assert_eq!(k, Kind::Satin);
        // no satin stitch longer than the column is wide (plus pull): a fan would be
        for stage in &st {
            for run in stage.iter().filter(|r| r.top) {
                let long = run.pts.windows(2).filter(|w| super::dist(w[0], w[1]) > 3.2).count();
                assert!(long <= 2, "{long} long stitches");
            }
        }
    }

    #[test]
    fn auto_picks_by_width() {
        let (k, st) = shape_stages(&[vec![(0.0, 0.0), (30.0, 0.0), (30.0, 3.0), (0.0, 3.0)]], &Settings::default(), 45.0);
        assert_eq!(k, Kind::Satin);
        assert!(!st.is_empty());
        let (k, _) = shape_stages(&[sq(0.0, 0.0, 20.0)], &Settings::default(), 45.0);
        assert_eq!(k, Kind::Fill);
        let (k, st) = shape_stages(&[vec![(0.0, 0.0), (30.0, 0.0), (30.0, 0.3), (0.0, 0.3)]], &Settings::default(), 45.0);
        assert_eq!(k, Kind::Run);
        assert!(st[0][0].pts.len() > 10);
    }
}

#[cfg(test)]
mod debug {
    use super::*;
    #[test]
    #[ignore]
    fn strip_satin() {
        let a = 10f32.to_radians();
        let (c, s) = (a.cos(), a.sin());
        let r: Ring = vec![(0.0, 0.0), (30.0, 0.0), (30.0, 3.0), (0.0, 3.0)].into_iter().map(|p| rot(p, c, s)).collect();
        let (k, st) = shape_stages(&[r], &Settings::default(), 45.0);
        eprintln!("kind {:?}, stages {}", k, st.len());
        for (i, stage) in st.iter().enumerate() {
            for run in stage {
                let mut lens: Vec<f32> = run.pts.windows(2).map(|w| dist(w[0], w[1])).collect();
                lens.sort_by(|a, b| a.partial_cmp(b).unwrap());
                eprintln!("stage {i}: run {} pts, len min {:.2} med {:.2} max {:.2}, first {:?}", run.pts.len(), lens[0], lens[lens.len() / 2], lens[lens.len() - 1], &run.pts[..6.min(run.pts.len())]);
            }
        }
    }
}

#[cfg(test)]
mod debug2 {
    use super::*;
    #[test]
    #[ignore]
    fn strip_from_file() {
        let j = crate::emb::json::parse(&std::fs::read_to_string("/tmp/strip.json").unwrap()).unwrap();
        let rings: Vec<Ring> = j.arr().iter().map(|r| r.arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0))).collect()).collect();
        let m = shape_mask(&rings, 0.5);
        let width = inscribed_width(&m);
        let dvals = m.inside_mm();
        let dist = |p: Pt| -> f32 {
            let i = ((p.0 - m.x0) * m.s).floor();
            let j = ((p.1 - m.y0) * m.s).floor();
            if i < 0.0 || j < 0.0 || i >= m.w as f32 || j >= m.h as f32 { return 0.0; }
            dvals[j as usize * m.w + i as usize]
        };
        let paths = centre_lines(&m, (0.7 * width).max(0.8));
        eprintln!("width {width:.2} paths {}", paths.len());
        for p in &paths {
            let rs = rails_for(p, &rings, &dist, 0.2, &Settings::default());
            let n = resample(p, 0.2).len();
            eprintln!(" path len {:.1} samples {} rails {}", path_length(p), n, rs.len());
            let ws: Vec<f32> = rs.iter().map(|r| r.l + r.r).collect();
            eprintln!("  widths {:?}", &ws[..ws.len().min(40)].iter().map(|w| (w * 10.0).round() / 10.0).collect::<Vec<_>>());
        }
    }
}


