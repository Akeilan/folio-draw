//! Remove Background: a local cut-out of the subject from its background, from colour and edges only.
//!
//! The background is what the picture's border is made of: the border colours are grouped, and the
//! background grows inwards from the border while the colour stays close to one of those groups and
//! changes smoothly from pixel to pixel (so a sky gradient goes, a subject's edge stops it). Closed
//! gaps of background colour inside the subject go too; specks and crumbs are cleaned up, and the
//! edge gets one pixel of soft alpha.

use crate::emb::colour::{de76, kmeans, lin_table, lin_to_lab, Lab};
use std::collections::VecDeque;

/// Alpha (0..255) to keep for every pixel of a w×h RGBA picture: 0 is background.
pub fn subject_alpha(px: &[u8], w: usize, h: usize) -> Vec<u8> {
    let n = w * h;
    if w < 3 || h < 3 {
        return vec![255; n];
    }
    let t = lin_table();
    let raw: Vec<Lab> = px.chunks_exact(4).map(|c| lin_to_lab(t[c[0] as usize], t[c[1] as usize], t[c[2] as usize])).collect();
    // light smoothing against noise and JPEG blocks: 3×3 mean
    let mut lab = raw.clone();
    for y in 1..h - 1 {
        for x in 1..w - 1 {
            let mut s = [0f32; 3];
            for dy in 0..3 {
                for dx in 0..3 {
                    let q = raw[(y + dy - 1) * w + x + dx - 1];
                    s[0] += q[0];
                    s[1] += q[1];
                    s[2] += q[2];
                }
            }
            lab[y * w + x] = [s[0] / 9.0, s[1] / 9.0, s[2] / 9.0];
        }
    }
    let transparent = |i: usize| px[i * 4 + 3] < 16;
    // the border ring
    let mut border = Vec::new();
    for x in 0..w {
        border.push(x);
        border.push((h - 1) * w + x);
    }
    for y in 1..h - 1 {
        border.push(y * w);
        border.push(y * w + w - 1);
    }
    let opaque_border: Vec<usize> = border.iter().copied().filter(|&i| !transparent(i)).collect();
    let mut bg = vec![false; n];
    let mut q = VecDeque::new();
    for i in 0..n {
        if transparent(i) {
            bg[i] = true;
            q.push_back(i);
        }
    }
    // background colour groups from the border; groups that make up little of it are the subject touching the edge
    let mut groups: Vec<Lab> = Vec::new();
    if opaque_border.len() >= 8 {
        let pts: Vec<Lab> = opaque_border.iter().map(|&i| lab[i]).collect();
        let k = 4.min(pts.len());
        let centres = kmeans(&pts, k, 7, 12);
        let mut count = vec![0usize; centres.len()];
        for p in &pts {
            let j = (0..centres.len()).min_by(|&a, &b| de76(*p, centres[a]).total_cmp(&de76(*p, centres[b]))).unwrap();
            count[j] += 1;
        }
        let total = pts.len() as f32;
        for (c, &m) in centres.iter().zip(&count) {
            if m as f32 / total >= 0.12 && !groups.iter().any(|g| de76(*g, *c) < 4.0) {
                groups.push(*c);
            }
        }
    }
    if groups.is_empty() && q.is_empty() {
        return vec![255; n];
    }
    let near = |l: Lab| groups.iter().map(|g| de76(l, *g)).fold(f32::MAX, f32::min);
    // how varied the background is along the border sets the tolerance
    let spread = if opaque_border.is_empty() {
        0.0
    } else {
        let mut d: Vec<f32> = opaque_border.iter().map(|&i| near(lab[i])).collect();
        d.sort_by(|a, b| a.total_cmp(b));
        d[(d.len() as f32 * 0.6) as usize]
    };
    let tol = (spread * 2.5 + 9.0).clamp(9.0, 24.0);
    let step = 5.5f32;
    for &i in &opaque_border {
        if near(lab[i]) < tol && !bg[i] {
            bg[i] = true;
            q.push_back(i);
        }
    }
    // grow inwards: close to a background group, and no edge between neighbours
    while let Some(i) = q.pop_front() {
        let (x, y) = (i % w, i / w);
        let nb = [(x > 0).then(|| i - 1), (x + 1 < w).then(|| i + 1), (y > 0).then(|| i - w), (y + 1 < h).then(|| i + w)];
        for j in nb.into_iter().flatten() {
            if bg[j] || transparent(j) {
                continue;
            }
            let from = if transparent(i) { None } else { Some(lab[i]) };
            let d_here = near(lab[j]);
            let smooth = from.map_or(true, |f| de76(f, lab[j]) < step);
            if d_here < tol && (smooth || d_here < tol * 0.45) {
                bg[j] = true;
                q.push_back(j);
            }
        }
    }
    // the smoothing blurs the edge outwards by a pixel: take back edge pixels whose own colour is background
    for _ in 0..2 {
        let mut more = Vec::new();
        for y in 0..h {
            for x in 0..w {
                let i = y * w + x;
                if bg[i] {
                    continue;
                }
                let touches = (x > 0 && bg[i - 1]) || (x + 1 < w && bg[i + 1]) || (y > 0 && bg[i - w]) || (y + 1 < h && bg[i + w]);
                if touches && near(raw[i]) < tol * 0.6 {
                    more.push(i);
                }
            }
        }
        for i in more {
            bg[i] = true;
        }
    }
    // enclosed gaps of background colour (the hole of a ring, between an arm and a body)
    let cand: Vec<bool> = (0..n).map(|i| !bg[i] && near(lab[i]) < tol * 0.6).collect();
    let (gid, gsizes) = components(&cand, w, h, true, true);
    let min_gap = (n / 800).max(12);
    for i in 0..n {
        if let Some(id) = gid[i] {
            if gsizes[id] >= min_gap {
                bg[i] = true;
            }
        }
    }
    // keep the subject's main pieces, drop crumbs
    let fg: Vec<bool> = bg.iter().map(|b| !b).collect();
    let (ids, sizes) = components(&fg, w, h, true, false);
    let biggest = sizes.iter().copied().max().unwrap_or(0);
    let keep_min = (biggest / 20).max((n / 2000).max(4));
    let mut keep = vec![false; n];
    for i in 0..n {
        if let Some(id) = ids[i] {
            keep[i] = sizes[id] >= keep_min;
        }
    }
    // pinholes inside the subject close up
    let (hid, hsizes) = components(&keep, w, h, false, true);
    for i in 0..n {
        if let Some(id) = hid[i] {
            if hsizes[id] < (n / 4000).max(6) {
                keep[i] = true;
            }
        }
    }
    // one pixel of soft edge
    let mut out = vec![0u8; n];
    for y in 0..h {
        for x in 0..w {
            let i = y * w + x;
            if !keep[i] {
                continue;
            }
            if px[i * 4 + 3] < 250 {
                out[i] = 255; // already soft from an earlier cut: leave its alpha as it is
                continue;
            }
            let mut c = 0;
            let mut s = 0;
            for dy in -1i64..=1 {
                for dx in -1i64..=1 {
                    let (xx, yy) = (x as i64 + dx, y as i64 + dy);
                    if xx < 0 || yy < 0 || xx >= w as i64 || yy >= h as i64 {
                        continue;
                    }
                    c += 1;
                    if keep[yy as usize * w + xx as usize] {
                        s += 1;
                    }
                }
            }
            out[i] = (255 * s / c) as u8;
        }
    }
    out
}

/// 4-connected components of the cells equal to `on`; with `inner` only the ones not touching the border.
fn components(m: &[bool], w: usize, h: usize, on: bool, inner: bool) -> (Vec<Option<usize>>, Vec<usize>) {
    let n = w * h;
    let mut id = vec![None; n];
    let mut seen = vec![false; n];
    let mut sizes = Vec::new();
    let mut stack = Vec::new();
    for s in 0..n {
        if m[s] != on || seen[s] {
            continue;
        }
        let k = sizes.len();
        let mut cells = Vec::new();
        let mut touches = false;
        id[s] = Some(k);
        seen[s] = true;
        stack.push(s);
        while let Some(i) = stack.pop() {
            cells.push(i);
            let (x, y) = (i % w, i / w);
            if x == 0 || y == 0 || x + 1 == w || y + 1 == h {
                touches = true;
            }
            let nb = [(x > 0).then(|| i - 1), (x + 1 < w).then(|| i + 1), (y > 0).then(|| i - w), (y + 1 < h).then(|| i + w)];
            for j in nb.into_iter().flatten() {
                if m[j] == on && !seen[j] {
                    seen[j] = true;
                    id[j] = Some(k);
                    stack.push(j);
                }
            }
        }
        if inner && touches {
            for i in cells {
                id[i] = None;
            }
            sizes.push(0);
        } else {
            sizes.push(cells.len());
        }
    }
    (id, sizes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pic(w: usize, h: usize, f: impl Fn(usize, usize) -> [u8; 3]) -> Vec<u8> {
        let mut px = Vec::with_capacity(w * h * 4);
        for y in 0..h {
            for x in 0..w {
                let c = f(x, y);
                px.extend_from_slice(&[c[0], c[1], c[2], 255]);
            }
        }
        px
    }

    #[test]
    fn a_disc_on_a_gradient_sky() {
        let (w, h) = (120, 90);
        let px = pic(w, h, |x, y| {
            let d = ((x as f32 - 60.0).powi(2) + (y as f32 - 45.0).powi(2)).sqrt();
            if d < 25.0 {
                [200, 40, 30]
            } else {
                [(90 + y) as u8, (150 + y / 2) as u8, 230]
            }
        });
        let a = subject_alpha(&px, w, h);
        assert_eq!(a[45 * w + 60], 255, "subject kept");
        assert_eq!(a[5 * w + 5], 0, "sky top gone");
        assert_eq!(a[85 * w + 110], 0, "sky bottom gone");
        let kept = a.iter().filter(|&&v| v > 128).count() as f32;
        let disc = std::f32::consts::PI * 25.0 * 25.0;
        assert!((kept - disc).abs() / disc < 0.08, "{kept} vs {disc}");
    }

    #[test]
    fn a_ring_loses_its_hole_and_keeps_a_subject_touching_the_edge() {
        let (w, h) = (100, 100);
        let px = pic(w, h, |x, y| {
            let d = ((x as f32 - 50.0).powi(2) + (y as f32 - 50.0).powi(2)).sqrt();
            if (18.0..32.0).contains(&d) || (y > 85 && (40..60).contains(&x)) {
                [20, 20, 20]
            } else {
                [250, 250, 250]
            }
        });
        let a = subject_alpha(&px, w, h);
        assert_eq!(a[50 * w + 50], 0, "the hole is background");
        assert_eq!(a[50 * w + 25], 255, "the ring stays");
        assert_eq!(a[98 * w + 50], 255, "the stem touching the edge stays");
    }
}

#[cfg(test)]
mod bench {
    #[test]
    fn big_picture_is_quick() {
        let (w, h) = (400usize, 300usize);
        let mut px = Vec::new();
        for y in 0..h {
            for x in 0..w {
                let d = ((x as f32 - 200.0).powi(2) + (y as f32 - 170.0).powi(2)).sqrt();
                let c = if d < 80.0 { [190, 50, 25] } else if (170..230).contains(&x) && (40..100).contains(&y) { [50, 128, 38] } else {
                    let t = y as f32 / h as f32; [(140.0 + 77.0 * t) as u8, (191.0 + 44.0 * t) as u8, (242.0 + 13.0 * t) as u8] };
                px.extend_from_slice(&[c[0], c[1], c[2], 255]);
            }
        }
        let t = std::time::Instant::now();
        let a = super::subject_alpha(&px, w, h);
        let el = t.elapsed();
        assert!(el.as_secs_f32() < 4.0, "{el:?}"); // well under a second on an idle machine
        assert_eq!(a[10 * w + 10], 0);
    }
}
