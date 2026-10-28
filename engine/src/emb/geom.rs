//! Simple polygon geometry in millimetres: point in polygon, scanline and ray intersections,
//! ring offsets by walking, simplification and resampling. Anything harder (unions,
//! differences, insets) is done on masks in `raster`.

pub type Pt = (f32, f32);
pub type Ring = Vec<Pt>;

#[inline]
pub fn sub(a: Pt, b: Pt) -> Pt {
    (a.0 - b.0, a.1 - b.1)
}
#[inline]
pub fn add(a: Pt, b: Pt) -> Pt {
    (a.0 + b.0, a.1 + b.1)
}
#[inline]
pub fn mul(a: Pt, k: f32) -> Pt {
    (a.0 * k, a.1 * k)
}
#[inline]
pub fn dot(a: Pt, b: Pt) -> f32 {
    a.0 * b.0 + a.1 * b.1
}
#[inline]
pub fn cross(a: Pt, b: Pt) -> f32 {
    a.0 * b.1 - a.1 * b.0
}
#[inline]
pub fn len(a: Pt) -> f32 {
    (a.0 * a.0 + a.1 * a.1).sqrt()
}
#[inline]
pub fn dist(a: Pt, b: Pt) -> f32 {
    len(sub(a, b))
}
pub fn norm(a: Pt) -> Pt {
    let l = len(a);
    if l < 1e-12 {
        (0.0, 0.0)
    } else {
        (a.0 / l, a.1 / l)
    }
}
pub fn lerp(a: Pt, b: Pt, t: f32) -> Pt {
    (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t)
}
pub fn rot(p: Pt, c: f32, s: f32) -> Pt {
    (p.0 * c - p.1 * s, p.0 * s + p.1 * c)
}

pub fn signed_area(r: &[Pt]) -> f32 {
    let n = r.len();
    let mut a = 0.0;
    for i in 0..n {
        let (p, q) = (r[i], r[(i + 1) % n]);
        a += p.0 * q.1 - q.0 * p.1;
    }
    a * 0.5
}

/// Area of a shape given as rings (even-odd: holes subtract).
pub fn rings_area(rings: &[Ring]) -> f32 {
    let mut outer = 0.0;
    for r in rings {
        outer += signed_area(r).abs();
    }
    // the first ring is the outline, the rest holes
    if rings.is_empty() {
        return 0.0;
    }
    let first = signed_area(&rings[0]).abs();
    2.0 * first - outer
}

pub fn bbox(rings: &[Ring]) -> (f32, f32, f32, f32) {
    let mut b = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for r in rings {
        for p in r {
            b.0 = b.0.min(p.0);
            b.1 = b.1.min(p.1);
            b.2 = b.2.max(p.0);
            b.3 = b.3.max(p.1);
        }
    }
    b
}

/// Even-odd point in polygon over all rings.
pub fn inside(rings: &[Ring], p: Pt) -> bool {
    let mut c = false;
    for r in rings {
        let n = r.len();
        if n < 3 {
            continue;
        }
        let mut j = n - 1;
        for i in 0..n {
            let (a, b) = (r[i], r[j]);
            if (a.1 > p.1) != (b.1 > p.1) && p.0 < (b.0 - a.0) * (p.1 - a.1) / (b.1 - a.1) + a.0 {
                c = !c;
            }
            j = i;
        }
    }
    c
}

/// x positions where the horizontal line y crosses the rings, sorted.
pub fn scanline(rings: &[Ring], y: f32) -> Vec<f32> {
    let mut xs = Vec::new();
    for r in rings {
        let n = r.len();
        if n < 3 {
            continue;
        }
        for k in 0..n {
            let (a, b) = (r[k], r[(k + 1) % n]);
            if (a.1 <= y) != (b.1 <= y) {
                xs.push(a.0 + (y - a.1) / (b.1 - a.1) * (b.0 - a.0));
            }
        }
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    xs
}

/// Parameters t > 0 at which the ray p + t·d crosses the rings (d need not be unit), sorted.
pub fn ray_hits(rings: &[Ring], p: Pt, d: Pt) -> Vec<f32> {
    let mut ts = Vec::new();
    for r in rings {
        let n = r.len();
        for k in 0..n {
            let (a, b) = (r[k], r[(k + 1) % n]);
            let e = sub(b, a);
            let den = cross(d, e);
            if den.abs() < 1e-12 {
                continue;
            }
            let ap = sub(a, p);
            let t = cross(ap, e) / den;
            let u = cross(ap, d) / den;
            if t > 1e-6 && (0.0..1.0).contains(&u) {
                ts.push(t);
            }
        }
    }
    ts.sort_by(|a, b| a.partial_cmp(b).unwrap());
    ts
}

/// Does the segment a→b cross any ring edge (touching at the ends allowed)?
pub fn segment_crosses(rings: &[Ring], a: Pt, b: Pt) -> bool {
    let d = sub(b, a);
    for r in rings {
        let n = r.len();
        for k in 0..n {
            let (p, q) = (r[k], r[(k + 1) % n]);
            let e = sub(q, p);
            let den = cross(d, e);
            if den.abs() < 1e-12 {
                continue;
            }
            let ap = sub(p, a);
            let t = cross(ap, e) / den;
            let u = cross(ap, d) / den;
            if t > 1e-4 && t < 1.0 - 1e-4 && (0.0..=1.0).contains(&u) {
                return true;
            }
        }
    }
    false
}

/// The segment stays inside the shape: no crossings and its middle is inside.
pub fn segment_inside(rings: &[Ring], a: Pt, b: Pt) -> bool {
    !segment_crosses(rings, a, b) && inside(rings, lerp(a, b, 0.5))
}

pub fn dist_to_segment(p: Pt, a: Pt, b: Pt) -> f32 {
    let ab = sub(b, a);
    let l2 = dot(ab, ab);
    if l2 < 1e-12 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), ab) / l2).clamp(0.0, 1.0);
    dist(p, add(a, mul(ab, t)))
}

/// Closest point on the rings to p: (ring, edge index, t on the edge, distance).
pub fn nearest_on_rings(rings: &[Ring], p: Pt) -> (usize, usize, f32, f32) {
    let mut best = (0, 0, 0.0, f32::MAX);
    for (ri, r) in rings.iter().enumerate() {
        let n = r.len();
        for k in 0..n {
            let (a, b) = (r[k], r[(k + 1) % n]);
            let ab = sub(b, a);
            let l2 = dot(ab, ab);
            let t = if l2 < 1e-12 { 0.0 } else { (dot(sub(p, a), ab) / l2).clamp(0.0, 1.0) };
            let d = dist(p, add(a, mul(ab, t)));
            if d < best.3 {
                best = (ri, k, t, d);
            }
        }
    }
    best
}

fn dp(pts: &[Pt], tol: f32, keep: &mut [bool], lo: usize, hi: usize) {
    if hi <= lo + 1 {
        return;
    }
    let (a, b) = (pts[lo], pts[hi]);
    let mut best = lo;
    let mut bd = -1.0;
    for i in lo + 1..hi {
        let d = dist_to_segment(pts[i], a, b);
        if d > bd {
            bd = d;
            best = i;
        }
    }
    if bd > tol {
        keep[best] = true;
        dp(pts, tol, keep, lo, best);
        dp(pts, tol, keep, best, hi);
    }
}

/// Douglas–Peucker on an open polyline.
pub fn simplify_open(pts: &[Pt], tol: f32) -> Vec<Pt> {
    if pts.len() < 3 {
        return pts.to_vec();
    }
    let mut keep = vec![false; pts.len()];
    keep[0] = true;
    *keep.last_mut().unwrap() = true;
    dp(pts, tol, &mut keep, 0, pts.len() - 1);
    pts.iter().zip(keep).filter(|(_, k)| *k).map(|(p, _)| *p).collect()
}

/// Douglas–Peucker on a closed ring (split at the point farthest from the first).
pub fn simplify_ring(r: &[Pt], tol: f32) -> Ring {
    let n = r.len();
    if n < 4 {
        return r.to_vec();
    }
    let mut far = 0;
    let mut fd = -1.0;
    for (i, p) in r.iter().enumerate() {
        let d = dist(*p, r[0]);
        if d > fd {
            fd = d;
            far = i;
        }
    }
    let mut a: Vec<Pt> = r[..=far].to_vec();
    let mut b: Vec<Pt> = r[far..].to_vec();
    b.push(r[0]);
    a = simplify_open(&a, tol);
    b = simplify_open(&b, tol);
    a.pop();
    b.pop();
    a.extend(b);
    a
}

/// Offset a closed ring by d (positive grows a counter-clockwise ring in y-down coordinates
/// where the outline is counter-clockwise in screen terms... callers pass the sign that grows),
/// walking the edges with mitred joins (mitre limited to 2·|d|).
pub fn offset_ring(r: &[Pt], d: f32) -> Ring {
    let n = r.len();
    if n < 3 || d == 0.0 {
        return r.to_vec();
    }
    // outward normal for a ring with positive signed area (in y-down coords that is clockwise
    // on screen): rotate the edge direction by -90°
    let sgn = if signed_area(r) >= 0.0 { 1.0 } else { -1.0 };
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let p0 = r[(i + n - 1) % n];
        let p1 = r[i];
        let p2 = r[(i + 1) % n];
        let e0 = norm(sub(p1, p0));
        let e1 = norm(sub(p2, p1));
        let n0 = mul((e0.1, -e0.0), sgn);
        let n1 = mul((e1.1, -e1.0), sgn);
        let m = norm(add(n0, n1));
        let c = dot(m, n1);
        let k = if c.abs() < 0.5 { 2.0 } else { 1.0 / c };
        out.push(add(p1, mul(m, d * k)));
    }
    out
}

pub fn ring_length(r: &[Pt]) -> f32 {
    let n = r.len();
    (0..n).map(|i| dist(r[i], r[(i + 1) % n])).sum()
}

pub fn path_length(p: &[Pt]) -> f32 {
    p.windows(2).map(|w| dist(w[0], w[1])).sum()
}

/// Points every `step` along an open polyline (both ends included; the last step may be shorter).
pub fn resample(p: &[Pt], step: f32) -> Vec<Pt> {
    if p.len() < 2 {
        return p.to_vec();
    }
    let total = path_length(p);
    if total < 1e-6 {
        return vec![p[0]];
    }
    let n = (total / step).ceil().max(1.0) as usize;
    let st = total / n as f32;
    let mut out = vec![p[0]];
    let mut seg = 0;
    let mut acc = 0.0;
    let mut target = st;
    while out.len() < n {
        while seg < p.len() - 1 {
            let l = dist(p[seg], p[seg + 1]);
            if acc + l >= target {
                let t = if l < 1e-9 { 0.0 } else { (target - acc) / l };
                out.push(lerp(p[seg], p[seg + 1], t));
                break;
            }
            acc += l;
            seg += 1;
        }
        if seg >= p.len() - 1 {
            break;
        }
        target += st;
    }
    out.push(*p.last().unwrap());
    out
}

/// Split a straight move into pieces no longer than `max`.
pub fn split_move(a: Pt, b: Pt, max: f32) -> Vec<Pt> {
    let d = dist(a, b);
    let n = (d / max).ceil().max(1.0) as usize;
    (1..=n).map(|i| lerp(a, b, i as f32 / n as f32)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sq(x: f32, y: f32, s: f32) -> Ring {
        vec![(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
    }
    #[test]
    fn basics() {
        let shape = vec![sq(0.0, 0.0, 10.0), sq(3.0, 3.0, 4.0)];
        assert!(inside(&shape, (1.0, 1.0)));
        assert!(!inside(&shape, (5.0, 5.0)));
        assert!((rings_area(&shape) - 84.0).abs() < 1e-3);
        assert_eq!(scanline(&shape, 5.0).len(), 4);
        let hits = ray_hits(&shape, (1.0, 5.0), (1.0, 0.0));
        assert!((hits[0] - 2.0).abs() < 1e-4);
        assert!(!segment_inside(&shape, (1.0, 5.0), (9.0, 5.0)));
        assert!(segment_inside(&shape, (1.0, 1.0), (9.0, 1.0)));
        let g = offset_ring(&sq(0.0, 0.0, 10.0), 1.0);
        assert!((signed_area(&g).abs() - 144.0).abs() < 1e-2);
        let s = simplify_ring(&[(0.0, 0.0), (5.0, 0.01), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], 0.1);
        assert_eq!(s.len(), 4);
        let rs = resample(&[(0.0, 0.0), (10.0, 0.0)], 3.0);
        assert_eq!(rs.len(), 5);
    }
}
