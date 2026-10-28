//! Outline tracing: every region of a label map becomes rings (outline first, then holes) in
//! millimetres, following the pixel cracks so neighbouring regions share their edges exactly.

use super::geom::{signed_area, simplify_ring, Pt, Ring};
use super::raster::{regions, Mask};
use std::collections::HashMap;

pub struct Traced {
    pub label: i32,
    pub rings: Vec<Ring>,
    pub px: usize,
}

/// Directed crack edges of one region: from vertex a to vertex b (pixel-corner coordinates),
/// the region on the left when y points down (i.e. walking clockwise on screen around it).
type V = (u32, u32);

fn loops_from_edges(edges: &[(V, V)]) -> Vec<Vec<V>> {
    let mut out_map: HashMap<V, Vec<usize>> = HashMap::with_capacity(edges.len());
    for (i, e) in edges.iter().enumerate() {
        out_map.entry(e.0).or_default().push(i);
    }
    let mut used = vec![false; edges.len()];
    let mut loops = Vec::new();
    for s in 0..edges.len() {
        if used[s] {
            continue;
        }
        let mut lp = Vec::new();
        let mut cur = s;
        loop {
            used[cur] = true;
            let (a, b) = edges[cur];
            lp.push(a);
            let dir = (b.0 as i64 - a.0 as i64, b.1 as i64 - a.1 as i64);
            // choose the next edge out of b: at a pinch vertex (two regions touching only at a
            // corner) turn so we stay around the same pixel
            let cands = match out_map.get(&b) {
                Some(c) => c,
                None => break,
            };
            let mut next = None;
            if cands.len() == 1 {
                if !used[cands[0]] {
                    next = Some(cands[0]);
                }
            } else {
                // preference: the turn toward the region side first
                let mut best_rank = 9;
                for &c in cands {
                    if used[c] {
                        continue;
                    }
                    let (p, q) = edges[c];
                    let nd = (q.0 as i64 - p.0 as i64, q.1 as i64 - p.1 as i64);
                    let cr = dir.0 * nd.1 - dir.1 * nd.0;
                    let dt = dir.0 * nd.0 + dir.1 * nd.1;
                    // region is on the right of travel in screen terms for our edge choice below
                    let rank = if cr > 0 { 0 } else if dt > 0 { 1 } else { 2 };
                    if rank < best_rank {
                        best_rank = rank;
                        next = Some(c);
                    }
                }
            }
            match next {
                Some(n) => cur = n,
                None => break,
            }
            if cur == s {
                break;
            }
        }
        if lp.len() >= 4 {
            loops.push(lp);
        }
    }
    loops
}

/// Region boundary edges for every region id at once, oriented with the region on the right
/// hand side of travel in screen coordinates (x right, y down).
fn region_edges(id: &[u32], w: usize, h: usize, nreg: usize) -> Vec<Vec<(V, V)>> {
    let mut per: Vec<Vec<(V, V)>> = vec![Vec::new(); nreg];
    for y in 0..h {
        for x in 0..w {
            let r = id[y * w + x];
            if r == u32::MAX {
                continue;
            }
            let (xu, yu) = (x as u32, y as u32);
            // top side: neighbour above differs → edge left→right along y
            if y == 0 || id[(y - 1) * w + x] != r {
                per[r as usize].push(((xu, yu), (xu + 1, yu)));
            }
            // right side: top→bottom along x+1
            if x + 1 == w || id[y * w + x + 1] != r {
                per[r as usize].push(((xu + 1, yu), (xu + 1, yu + 1)));
            }
            // bottom side: right→left along y+1
            if y + 1 == h || id[(y + 1) * w + x] != r {
                per[r as usize].push(((xu + 1, yu + 1), (xu, yu + 1)));
            }
            // left side: bottom→top along x
            if x == 0 || id[y * w + x - 1] != r {
                per[r as usize].push(((xu, yu + 1), (xu, yu)));
            }
        }
    }
    per
}

/// Turn a staircase loop into a ring through the midpoints of its unit cracks, then simplify.
fn loop_to_ring(lp: &[V], x0: f32, y0: f32, s: f32, tol: f32) -> Ring {
    let n = lp.len();
    let mut pts: Vec<Pt> = Vec::with_capacity(n);
    for i in 0..n {
        let a = lp[i];
        let b = lp[(i + 1) % n];
        let mx = (a.0 as f32 + b.0 as f32) * 0.5;
        let my = (a.1 as f32 + b.1 as f32) * 0.5;
        pts.push((x0 + mx / s, y0 + my / s));
    }
    // corners of a straight run add no midpoints of their own: collapse collinear runs first
    let mut slim: Vec<Pt> = Vec::with_capacity(pts.len());
    for i in 0..pts.len() {
        let p = pts[(i + pts.len() - 1) % pts.len()];
        let c = pts[i];
        let q = pts[(i + 1) % pts.len()];
        let cr = (c.0 - p.0) * (q.1 - c.1) - (c.1 - p.1) * (q.0 - c.0);
        if cr.abs() > 1e-9 {
            slim.push(c);
        }
    }
    if slim.len() < 3 {
        slim = pts;
    }
    simplify_ring(&slim, tol)
}

/// Trace every region of `labels` whose label is ≥ 0. Pixel (i, j) covers
/// [x0 + i/s, x0 + (i+1)/s) × [y0 + j/s, ...).
pub fn trace_labels(labels: &[i32], w: usize, h: usize, x0: f32, y0: f32, s: f32, tol: f32) -> Vec<Traced> {
    let (id, sizes, labs) = regions(labels, w, h);
    let mut id2 = id.clone();
    for (i, v) in id2.iter_mut().enumerate() {
        if labels[i] < 0 {
            *v = u32::MAX;
        }
    }
    let per = region_edges(&id2, w, h, sizes.len());
    let mut out = Vec::new();
    for (r, edges) in per.iter().enumerate() {
        if labs[r] < 0 || edges.is_empty() {
            continue;
        }
        let loops = loops_from_edges(edges);
        let mut rings: Vec<(f32, Ring)> = loops
            .iter()
            .map(|lp| {
                let ring = loop_to_ring(lp, x0, y0, s, tol);
                (signed_area(&ring), ring)
            })
            .filter(|(_, r)| r.len() >= 3)
            .collect();
        if rings.is_empty() {
            continue;
        }
        // the outline is the loop with the largest area; the others are holes
        rings.sort_by(|a, b| b.0.abs().partial_cmp(&a.0.abs()).unwrap());
        out.push(Traced { label: labs[r], rings: rings.into_iter().map(|(_, r)| r).collect(), px: sizes[r] });
    }
    out
}

/// Trace a mask: each 4-connected part becomes its own shape.
pub fn trace_mask(m: &Mask, tol: f32) -> Vec<Vec<Ring>> {
    let labels: Vec<i32> = m.v.iter().map(|b| if *b { 0 } else { -1 }).collect();
    trace_labels(&labels, m.w, m.h, m.x0, m.y0, m.s, tol).into_iter().map(|t| t.rings).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::emb::geom::{inside, rings_area};
    #[test]
    fn square_with_hole() {
        let (w, h) = (20, 20);
        let mut l = vec![-1i32; w * h];
        for y in 2..18 {
            for x in 2..18 {
                l[y * w + x] = if (7..12).contains(&x) && (7..12).contains(&y) { -1 } else { 1 };
            }
        }
        let t = trace_labels(&l, w, h, 0.0, 0.0, 10.0, 0.01);
        assert_eq!(t.len(), 1);
        assert_eq!(t[0].rings.len(), 2);
        let a = rings_area(&t[0].rings);
        // 16² − 5² pixels at 0.1 mm, less the corner cuts of the midpoint ring
        assert!((a - 2.31).abs() < 0.05, "{a}");
        assert!(inside(&t[0].rings, (0.3, 0.3)));
        assert!(!inside(&t[0].rings, (0.95, 0.95)));
    }
    #[test]
    fn diagonal_touch_is_two_shapes() {
        let (w, h) = (4, 4);
        let mut l = vec![-1i32; 16];
        l[0] = 0;
        l[5] = 0;
        let t = trace_labels(&l, w, h, 0.0, 0.0, 1.0, 0.01);
        assert_eq!(t.len(), 2);
    }
    #[test]
    fn neighbours_share_edges() {
        let (w, h) = (10, 6);
        let l: Vec<i32> = (0..w * h).map(|i| if i % w < 5 { 0 } else { 1 }).collect();
        let t = trace_labels(&l, w, h, 0.0, 0.0, 1.0, 0.01);
        assert_eq!(t.len(), 2);
        let total: f32 = t.iter().map(|s| rings_area(&s.rings)).sum();
        assert!(total > 55.0, "{total}");
    }
}
