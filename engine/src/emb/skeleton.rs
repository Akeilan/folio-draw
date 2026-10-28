//! Centre lines: Zhang–Suen thinning of a mask, then a walker that turns the one-pixel skeleton
//! into paths between endpoints and junctions, prunes short spurs and smooths.

use super::geom::{dist, path_length, Pt};
use super::raster::Mask;

/// Zhang–Suen thinning (in place on a copy).
pub fn thin(m: &[bool], w: usize, h: usize) -> Vec<bool> {
    let mut v = m.to_vec();
    if w < 3 || h < 3 {
        return v;
    }
    let get = |v: &Vec<bool>, x: i64, y: i64| -> u8 {
        if x < 0 || y < 0 || x >= w as i64 || y >= h as i64 {
            0
        } else {
            v[y as usize * w + x as usize] as u8
        }
    };
    let mut del = Vec::new();
    loop {
        let mut changed = false;
        for pass in 0..2 {
            del.clear();
            for y in 0..h as i64 {
                for x in 0..w as i64 {
                    if !v[y as usize * w + x as usize] {
                        continue;
                    }
                    let p2 = get(&v, x, y - 1);
                    let p3 = get(&v, x + 1, y - 1);
                    let p4 = get(&v, x + 1, y);
                    let p5 = get(&v, x + 1, y + 1);
                    let p6 = get(&v, x, y + 1);
                    let p7 = get(&v, x - 1, y + 1);
                    let p8 = get(&v, x - 1, y);
                    let p9 = get(&v, x - 1, y - 1);
                    let nb = [p2, p3, p4, p5, p6, p7, p8, p9];
                    let b: u8 = nb.iter().sum();
                    if !(2..=6).contains(&b) {
                        continue;
                    }
                    let mut a = 0;
                    for i in 0..8 {
                        if nb[i] == 0 && nb[(i + 1) % 8] == 1 {
                            a += 1;
                        }
                    }
                    if a != 1 {
                        continue;
                    }
                    let ok = if pass == 0 {
                        p2 * p4 * p6 == 0 && p4 * p6 * p8 == 0
                    } else {
                        p2 * p4 * p8 == 0 && p2 * p6 * p8 == 0
                    };
                    if ok {
                        del.push(y as usize * w + x as usize);
                    }
                }
            }
            for &i in &del {
                v[i] = false;
            }
            if !del.is_empty() {
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    v
}

const NB: [(i64, i64); 8] = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)];

/// Skeleton neighbours: the four sides, plus a diagonal only when neither pixel beside it is
/// set (otherwise a staircase would count as a junction at every step).
fn neighbours(v: &[bool], w: usize, h: usize, i: usize) -> Vec<usize> {
    let (x, y) = ((i % w) as i64, (i / w) as i64);
    let set = |xx: i64, yy: i64| xx >= 0 && yy >= 0 && xx < w as i64 && yy < h as i64 && v[yy as usize * w + xx as usize];
    let mut out = Vec::with_capacity(8);
    for (dx, dy) in NB {
        let (xx, yy) = (x + dx, y + dy);
        if !set(xx, yy) {
            continue;
        }
        if dx != 0 && dy != 0 && (set(x + dx, y) || set(x, y + dy)) {
            continue;
        }
        out.push(yy as usize * w + xx as usize);
    }
    out
}

/// Pixel paths of a skeleton: each runs between nodes (ends, junctions) or around a loop.
pub fn walk(v: &[bool], w: usize, h: usize) -> Vec<Vec<usize>> {
    let deg: Vec<usize> = (0..w * h).map(|i| if v[i] { neighbours(v, w, h, i).len() } else { 0 }).collect();
    let is_node = |i: usize| v[i] && deg[i] != 2;
    // visited edges as (min, max) pixel pairs
    let mut seen = std::collections::HashSet::new();
    let mut paths = Vec::new();
    let mut visited_px = vec![false; w * h];
    for s in 0..w * h {
        if !is_node(s) {
            continue;
        }
        if deg[s] == 0 {
            paths.push(vec![s]);
            visited_px[s] = true;
            continue;
        }
        for n in neighbours(v, w, h, s) {
            let key = (s.min(n), s.max(n));
            if seen.contains(&key) {
                continue;
            }
            seen.insert(key);
            let mut path = vec![s, n];
            visited_px[s] = true;
            let mut prev = s;
            let mut cur = n;
            while !is_node(cur) {
                visited_px[cur] = true;
                let nx = neighbours(v, w, h, cur).into_iter().find(|&q| q != prev && !seen.contains(&(cur.min(q), cur.max(q))));
                match nx {
                    Some(q) => {
                        seen.insert((cur.min(q), cur.max(q)));
                        path.push(q);
                        prev = cur;
                        cur = q;
                    }
                    None => break,
                }
            }
            visited_px[cur] = true;
            paths.push(path);
        }
    }
    // loops with no node at all
    for s in 0..w * h {
        if !v[s] || visited_px[s] {
            continue;
        }
        let mut path = vec![s];
        visited_px[s] = true;
        let mut prev = usize::MAX;
        let mut cur = s;
        loop {
            let nx = neighbours(v, w, h, cur).into_iter().find(|&q| q != prev && !visited_px[q]);
            match nx {
                Some(q) => {
                    visited_px[q] = true;
                    path.push(q);
                    prev = cur;
                    cur = q;
                }
                None => break,
            }
        }
        path.push(s);
        paths.push(path);
    }
    paths
}

/// Centre-line paths in millimetres for a mask: thinned, walked, spurs shorter than `spur`
/// pruned, smoothed with a 5-sample moving average.
pub fn centre_lines(m: &Mask, spur: f32) -> Vec<Vec<Pt>> {
    let mut sk = thin(&m.v, m.w, m.h);
    // prune spurs: paths with a free end shorter than `spur`, repeated while anything goes
    for _ in 0..4 {
        let paths = walk(&sk, m.w, m.h);
        if paths.len() <= 1 {
            break;
        }
        let deg = |sk: &Vec<bool>, i: usize| neighbours(sk, m.w, m.h, i).len();
        let mut removed = false;
        for p in &paths {
            if p.len() < 2 {
                continue;
            }
            let (a, b) = (p[0], *p.last().unwrap());
            let free_a = deg(&sk, a) == 1;
            let free_b = deg(&sk, b) == 1;
            if free_a == free_b {
                continue; // both free (an isolated stroke) or both attached: keep
            }
            let len = p.len() as f32 / m.s;
            if len < spur {
                // remove all but the attached end
                let keep_end = if free_a { b } else { a };
                for &q in p {
                    if q != keep_end {
                        sk[q] = false;
                    }
                }
                removed = true;
            }
        }
        if !removed {
            break;
        }
        sk = thin(&sk, m.w, m.h);
    }
    let paths = walk(&sk, m.w, m.h);
    let mut out = Vec::new();
    for p in paths {
        let pts: Vec<Pt> = p.iter().map(|&i| m.centre(i % m.w, i / m.w)).collect();
        if pts.len() == 1 {
            out.push(pts);
            continue;
        }
        let closed = p.len() > 3 && p[0] == *p.last().unwrap();
        out.push(smooth(&pts, closed));
    }
    join_paths(out)
}

fn smooth(p: &[Pt], closed: bool) -> Vec<Pt> {
    let n = p.len();
    if n < 5 {
        return p.to_vec();
    }
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        if !closed && (i < 2 || i + 2 >= n) {
            out.push(p[i]);
            continue;
        }
        let mut sx = 0.0;
        let mut sy = 0.0;
        for k in -2i64..=2 {
            let j = if closed { ((i as i64 + k).rem_euclid(n as i64 - 1)) as usize } else { (i as i64 + k) as usize };
            sx += p[j].0;
            sy += p[j].1;
        }
        out.push((sx / 5.0, sy / 5.0));
    }
    if closed {
        let first = out[0];
        *out.last_mut().unwrap() = first;
    }
    out
}

/// Join paths that meet end to end at a node where only those two meet (after pruning a
/// junction can become a simple bend).
fn join_paths(mut paths: Vec<Vec<Pt>>) -> Vec<Vec<Pt>> {
    let tol = 0.08;
    loop {
        let mut merged = false;
        'outer: for i in 0..paths.len() {
            if paths[i].len() < 2 {
                continue;
            }
            for end_i in [true, false] {
                let pi = if end_i { *paths[i].last().unwrap() } else { paths[i][0] };
                // how many path ends touch this point?
                let mut touching = Vec::new();
                for (j, q) in paths.iter().enumerate() {
                    if q.len() < 2 {
                        continue;
                    }
                    if dist(q[0], pi) < tol {
                        touching.push((j, false));
                    }
                    if dist(*q.last().unwrap(), pi) < tol {
                        touching.push((j, true));
                    }
                }
                if touching.len() == 2 {
                    let other = touching.iter().find(|t| !(t.0 == i && t.1 == end_i)).copied();
                    if let Some((j, j_end)) = other {
                        if j == i {
                            continue;
                        }
                        let mut a = paths[i].clone();
                        let mut b = paths[j].clone();
                        if !end_i {
                            a.reverse();
                        }
                        if j_end {
                            b.reverse();
                        }
                        a.extend(b.into_iter().skip(1));
                        let (lo, hi) = (i.min(j), i.max(j));
                        paths.remove(hi);
                        paths.remove(lo);
                        paths.push(a);
                        merged = true;
                        break 'outer;
                    }
                }
            }
        }
        if !merged {
            break;
        }
    }
    paths.retain(|p| p.len() == 1 || path_length(p) > 0.0);
    paths
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::emb::geom::Ring;
    #[test]
    fn bar_has_one_centre_line() {
        let bar: Ring = vec![(0.0, 0.0), (20.0, 0.0), (20.0, 2.0), (0.0, 2.0)];
        let mut m = Mask::new(-1.0, -1.0, 21.0, 3.0, 20.0);
        m.fill(&[bar], true);
        let c = centre_lines(&m, 1.4);
        assert_eq!(c.len(), 1, "{:?}", c.iter().map(|p| p.len()).collect::<Vec<_>>());
        let l = path_length(&c[0]);
        assert!(l > 17.0 && l < 20.5, "{l}");
        for p in &c[0] {
            assert!((p.1 - 1.0).abs() < 0.15, "{:?}", p);
        }
    }
    #[test]
    fn cross_has_four_arms() {
        let mut m = Mask::new(-11.0, -11.0, 11.0, 11.0, 20.0);
        m.fill(&[vec![(-10.0, -1.0), (10.0, -1.0), (10.0, 1.0), (-10.0, 1.0)]], true);
        let mut v = Mask::new(-11.0, -11.0, 11.0, 11.0, 20.0);
        v.fill(&[vec![(-1.0, -10.0), (1.0, -10.0), (1.0, 10.0), (-1.0, 10.0)]], true);
        let m = m.or(&v);
        let c = centre_lines(&m, 1.4);
        let long: Vec<_> = c.iter().filter(|p| path_length(p) > 5.0).collect();
        assert!(long.len() == 4 || long.len() == 2, "{}", long.len());
    }
}
