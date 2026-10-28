//! Raster work for embroidery: resampling with premultiplied alpha, the bilateral filter,
//! distance transforms (with nearest label), label voting, connected regions and masks.

use super::colour::{lin_table, lin_to_lab, Lab};
use super::geom::{Pt, Ring};

/// Straight-alpha RGBA picture.
#[derive(Clone)]
pub struct Img {
    pub w: usize,
    pub h: usize,
    pub px: Vec<u8>,
}

fn premul(px: &[u8]) -> Vec<f32> {
    let mut out = Vec::with_capacity(px.len());
    for c in px.chunks_exact(4) {
        let a = c[3] as f32 / 255.0;
        out.push(c[0] as f32 * a);
        out.push(c[1] as f32 * a);
        out.push(c[2] as f32 * a);
        out.push(c[3] as f32);
    }
    out
}

fn unpremul(p: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(p.len());
    for c in p.chunks_exact(4) {
        let a = c[3].clamp(0.0, 255.0);
        if a < 0.5 {
            out.extend_from_slice(&[0, 0, 0, 0]);
        } else {
            let k = 255.0 / a;
            out.push((c[0] * k).round().clamp(0.0, 255.0) as u8);
            out.push((c[1] * k).round().clamp(0.0, 255.0) as u8);
            out.push((c[2] * k).round().clamp(0.0, 255.0) as u8);
            out.push(a.round() as u8);
        }
    }
    out
}

/// Area-average one axis (shrinking); `n` source samples into `m`.
fn area_axis(src: &[f32], n: usize, m: usize, stride_in: usize, count: usize, along: impl Fn(usize, usize) -> usize, out_idx: impl Fn(usize, usize) -> usize, out: &mut [f32]) {
    let _ = stride_in;
    let scale = n as f64 / m as f64;
    for line in 0..count {
        for j in 0..m {
            let a = j as f64 * scale;
            let b = (j + 1) as f64 * scale;
            let mut acc = [0f64; 4];
            let mut wsum = 0.0;
            let mut i = a.floor() as usize;
            while (i as f64) < b && i < n {
                let lo = (i as f64).max(a);
                let hi = ((i + 1) as f64).min(b);
                let wgt = hi - lo;
                if wgt > 0.0 {
                    let o = along(line, i);
                    for k in 0..4 {
                        acc[k] += src[o + k] as f64 * wgt;
                    }
                    wsum += wgt;
                }
                i += 1;
            }
            let o = out_idx(line, j);
            for k in 0..4 {
                out[o + k] = (acc[k] / wsum.max(1e-9)) as f32;
            }
        }
    }
}

fn cubic(t: f32) -> [f32; 4] {
    // Catmull-Rom (a = -0.5)
    let a = -0.5f32;
    let w = |x: f32| {
        let x = x.abs();
        if x <= 1.0 {
            (a + 2.0) * x * x * x - (a + 3.0) * x * x + 1.0
        } else if x < 2.0 {
            a * x * x * x - 5.0 * a * x * x + 8.0 * a * x - 4.0 * a
        } else {
            0.0
        }
    };
    [w(1.0 + t), w(t), w(1.0 - t), w(2.0 - t)]
}

fn cubic_axis(src: &[f32], n: usize, m: usize, count: usize, along: impl Fn(usize, usize) -> usize, out_idx: impl Fn(usize, usize) -> usize, out: &mut [f32]) {
    let scale = n as f32 / m as f32;
    for line in 0..count {
        for j in 0..m {
            let x = (j as f32 + 0.5) * scale - 0.5;
            let x0 = x.floor();
            let ws = cubic(x - x0);
            let mut acc = [0f32; 4];
            for (t, wgt) in ws.iter().enumerate() {
                let i = (x0 as i64 - 1 + t as i64).clamp(0, n as i64 - 1) as usize;
                let o = along(line, i);
                for k in 0..4 {
                    acc[k] += src[o + k] * wgt;
                }
            }
            let o = out_idx(line, j);
            for k in 0..4 {
                out[o + k] = acc[k];
            }
        }
    }
}

/// Resize with premultiplied alpha, so transparent pixels don't bleed dark fringes into edges:
/// area average when shrinking an axis, bicubic when enlarging it.
pub fn resize(img: &Img, dw: usize, dh: usize) -> Img {
    let (sw, sh) = (img.w, img.h);
    if sw == dw && sh == dh {
        return img.clone();
    }
    let p = premul(&img.px);
    // horizontal pass: sh rows, sw -> dw
    let mut t = vec![0f32; dw * sh * 4];
    if dw <= sw {
        area_axis(&p, sw, dw, 0, sh, |r, i| (r * sw + i) * 4, |r, j| (r * dw + j) * 4, &mut t);
    } else {
        cubic_axis(&p, sw, dw, sh, |r, i| (r * sw + i) * 4, |r, j| (r * dw + j) * 4, &mut t);
    }
    let mut o = vec![0f32; dw * dh * 4];
    if dh <= sh {
        area_axis(&t, sh, dh, 0, dw, |c, i| (i * dw + c) * 4, |c, j| (j * dw + c) * 4, &mut o);
    } else {
        cubic_axis(&t, sh, dh, dw, |c, i| (i * dw + c) * 4, |c, j| (j * dw + c) * 4, &mut o);
    }
    // bicubic can overshoot: keep colour within alpha
    for c in o.chunks_exact_mut(4) {
        c[3] = c[3].clamp(0.0, 255.0);
        for k in 0..3 {
            c[k] = c[k].clamp(0.0, c[3]);
        }
    }
    Img { w: dw, h: dh, px: unpremul(&o) }
}

/// Lab of every pixel (alpha ignored; callers mask transparent pixels themselves).
pub fn to_lab(img: &Img) -> Vec<Lab> {
    let t = lin_table();
    img.px.chunks_exact(4).map(|c| lin_to_lab(t[c[0] as usize], t[c[1] as usize], t[c[2] as usize])).collect()
}

/// Edge-preserving smoothing in Lab: spatial Gaussian of `radius` pixels, range sigma `sr` ΔE.
pub fn bilateral(lab: &[Lab], w: usize, h: usize, radius: usize, sr: f32) -> Vec<Lab> {
    if radius == 0 {
        return lab.to_vec();
    }
    let r = radius as i64;
    let ss = (radius as f32 / 2.0).max(0.5);
    let mut sw = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            sw.push((dx, dy, (-((dx * dx + dy * dy) as f32) / (2.0 * ss * ss)).exp()));
        }
    }
    let inv = 1.0 / (2.0 * sr * sr);
    let mut out = vec![[0f32; 3]; lab.len()];
    for y in 0..h as i64 {
        for x in 0..w as i64 {
            let c = lab[(y as usize) * w + x as usize];
            let mut acc = [0f32; 3];
            let mut ws = 0f32;
            for &(dx, dy, g) in &sw {
                let (xx, yy) = (x + dx, y + dy);
                if xx < 0 || yy < 0 || xx >= w as i64 || yy >= h as i64 {
                    continue;
                }
                let q = lab[(yy as usize) * w + xx as usize];
                let d = (q[0] - c[0]).powi(2) + (q[1] - c[1]).powi(2) + (q[2] - c[2]).powi(2);
                let wgt = g * (-d * inv).exp();
                acc[0] += q[0] * wgt;
                acc[1] += q[1] * wgt;
                acc[2] += q[2] * wgt;
                ws += wgt;
            }
            out[(y as usize) * w + x as usize] = [acc[0] / ws, acc[1] / ws, acc[2] / ws];
        }
    }
    out
}

/// Separable max/min over a (2r+1)² square of one f32 channel.
fn minmax_filter(v: &[f32], w: usize, h: usize, r: usize, max: bool) -> Vec<f32> {
    let pick = |a: f32, b: f32| if max { a.max(b) } else { a.min(b) };
    let mut t = vec![0f32; v.len()];
    for y in 0..h {
        for x in 0..w {
            let mut m = v[y * w + x];
            let lo = x.saturating_sub(r);
            let hi = (x + r).min(w - 1);
            for xx in lo..=hi {
                m = pick(m, v[y * w + xx]);
            }
            t[y * w + x] = m;
        }
    }
    let mut o = vec![0f32; v.len()];
    for y in 0..h {
        let lo = y.saturating_sub(r);
        let hi = (y + r).min(h - 1);
        for x in 0..w {
            let mut m = t[y * w + x];
            for yy in lo..=hi {
                m = pick(m, t[yy * w + x]);
            }
            o[y * w + x] = m;
        }
    }
    o
}

/// Morphological gradient in Lab: ΔE between the per-channel dilation and erosion over a square
/// kernel of side `k` (odd).
pub fn lab_gradient(lab: &[Lab], w: usize, h: usize, k: usize) -> Vec<f32> {
    let r = k / 2;
    let mut chans_max = Vec::new();
    let mut chans_min = Vec::new();
    for c in 0..3 {
        let v: Vec<f32> = lab.iter().map(|p| p[c]).collect();
        chans_max.push(minmax_filter(&v, w, h, r, true));
        chans_min.push(minmax_filter(&v, w, h, r, false));
    }
    (0..lab.len())
        .map(|i| {
            let d0 = chans_max[0][i] - chans_min[0][i];
            let d1 = chans_max[1][i] - chans_min[1][i];
            let d2 = chans_max[2][i] - chans_min[2][i];
            (d0 * d0 + d1 * d1 + d2 * d2).sqrt()
        })
        .collect()
}

const INF: f32 = 1e20;

/// One-dimensional squared distance transform (Felzenszwalb & Huttenlocher) with the index of
/// the nearest seed.
fn dt1(f: &[f32], arg: &[i32], n: usize, d: &mut [f32], a: &mut [i32], v: &mut [usize], z: &mut [f32]) {
    let mut k = 0usize;
    v[0] = 0;
    z[0] = -INF;
    z[1] = INF;
    let mut q = 1;
    // skip leading infinities by treating them normally (they never win)
    while q < n {
        loop {
            let vk = v[k];
            let s = ((f[q] + (q * q) as f32) - (f[vk] + (vk * vk) as f32)) / (2.0 * q as f32 - 2.0 * vk as f32);
            if s <= z[k] {
                if k == 0 {
                    v[0] = q;
                    z[0] = -INF;
                    z[1] = INF;
                    break;
                }
                k -= 1;
                continue;
            }
            k += 1;
            v[k] = q;
            z[k] = s;
            z[k + 1] = INF;
            break;
        }
        q += 1;
    }
    k = 0;
    for q in 0..n {
        while z[k + 1] < q as f32 {
            k += 1;
        }
        let vk = v[k];
        let dd = (q as f32 - vk as f32).powi(2) + f[vk];
        d[q] = dd;
        a[q] = arg[vk];
    }
}

/// Two-pass Euclidean distance transform. `seed[i]` marks seed pixels; returns the squared
/// distance to the nearest seed and that seed's index. Pixels with no seed anywhere get INF / -1.
pub fn edt(seed: &[bool], w: usize, h: usize) -> (Vec<f32>, Vec<i32>) {
    let n = w.max(h);
    let mut f = vec![0f32; n];
    let mut arg = vec![0i32; n];
    let mut d = vec![0f32; n];
    let mut a = vec![0i32; n];
    let mut v = vec![0usize; n + 1];
    let mut z = vec![0f32; n + 2];
    let mut dist = vec![INF; w * h];
    let mut near = vec![-1i32; w * h];
    // columns
    for x in 0..w {
        for y in 0..h {
            let i = y * w + x;
            f[y] = if seed[i] { 0.0 } else { INF };
            arg[y] = if seed[i] { i as i32 } else { -1 };
        }
        dt1(&f[..h], &arg[..h], h, &mut d[..h], &mut a[..h], &mut v, &mut z);
        for y in 0..h {
            dist[y * w + x] = d[y];
            near[y * w + x] = a[y];
        }
    }
    // rows
    for y in 0..h {
        for x in 0..w {
            f[x] = dist[y * w + x];
            arg[x] = near[y * w + x];
        }
        dt1(&f[..w], &arg[..w], w, &mut d[..w], &mut a[..w], &mut v, &mut z);
        for x in 0..w {
            let dd = d[x];
            dist[y * w + x] = if dd >= INF * 0.5 { INF } else { dd };
            near[y * w + x] = if dd >= INF * 0.5 { -1 } else { a[x] };
        }
    }
    (dist, near)
}

/// Distance (pixels) from each inside pixel of a mask to the nearest outside pixel; 0 outside.
pub fn inside_distance(mask: &[bool], w: usize, h: usize) -> Vec<f32> {
    // pad by one so the picture border counts as outside
    let (pw, ph) = (w + 2, h + 2);
    let mut seed = vec![true; pw * ph];
    for y in 0..h {
        for x in 0..w {
            seed[(y + 1) * pw + x + 1] = !mask[y * w + x];
        }
    }
    let (d, _) = edt(&seed, pw, ph);
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        for x in 0..w {
            out[y * w + x] = d[(y + 1) * pw + x + 1].sqrt();
        }
    }
    out
}

/// Smooth a label map by a Gaussian-weighted vote over a disc of `radius` pixels.
pub fn label_vote(labels: &[i32], w: usize, h: usize, radius: usize, nlabels: usize) -> Vec<i32> {
    if radius == 0 {
        return labels.to_vec();
    }
    let r = radius as i64;
    let s = radius as f32 / 1.5;
    let mut ker = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            if dx * dx + dy * dy <= r * r {
                ker.push((dx, dy, (-((dx * dx + dy * dy) as f32) / (2.0 * s * s)).exp()));
            }
        }
    }
    let mut out = labels.to_vec();
    let mut votes = vec![0f32; nlabels + 1];
    for y in 0..h as i64 {
        for x in 0..w as i64 {
            let me = labels[(y as usize) * w + x as usize];
            // only boundary pixels can change; skip uniform neighbourhoods fast
            let mut uniform = true;
            for &(dx, dy, _) in &ker {
                let (xx, yy) = (x + dx, y + dy);
                if xx < 0 || yy < 0 || xx >= w as i64 || yy >= h as i64 {
                    continue;
                }
                if labels[(yy as usize) * w + xx as usize] != me {
                    uniform = false;
                    break;
                }
            }
            if uniform {
                continue;
            }
            for v in votes.iter_mut() {
                *v = 0.0;
            }
            for &(dx, dy, g) in &ker {
                let (xx, yy) = (x + dx, y + dy);
                if xx < 0 || yy < 0 || xx >= w as i64 || yy >= h as i64 {
                    continue;
                }
                let l = labels[(yy as usize) * w + xx as usize];
                votes[(l + 1) as usize] += g;
            }
            let mut best = me;
            let mut bv = votes[(me + 1) as usize];
            for (i, v) in votes.iter().enumerate() {
                if *v > bv + 1e-6 {
                    bv = *v;
                    best = i as i32 - 1;
                }
            }
            out[(y as usize) * w + x as usize] = best;
        }
    }
    out
}

/// 4-connected regions of equal label: (region id per pixel, size of each region, label of each).
pub fn regions(labels: &[i32], w: usize, h: usize) -> (Vec<u32>, Vec<usize>, Vec<i32>) {
    let mut id = vec![u32::MAX; w * h];
    let mut sizes = Vec::new();
    let mut labs = Vec::new();
    let mut stack = Vec::new();
    for s in 0..w * h {
        if id[s] != u32::MAX {
            continue;
        }
        let rid = sizes.len() as u32;
        let l = labels[s];
        let mut n = 0;
        id[s] = rid;
        stack.push(s);
        while let Some(p) = stack.pop() {
            n += 1;
            let (x, y) = (p % w, p / w);
            let try_push = |q: usize, id: &mut Vec<u32>, stack: &mut Vec<usize>| {
                if id[q] == u32::MAX && labels[q] == l {
                    id[q] = rid;
                    stack.push(q);
                }
            };
            if x > 0 {
                try_push(p - 1, &mut id, &mut stack);
            }
            if x + 1 < w {
                try_push(p + 1, &mut id, &mut stack);
            }
            if y > 0 {
                try_push(p - w, &mut id, &mut stack);
            }
            if y + 1 < h {
                try_push(p + w, &mut id, &mut stack);
            }
        }
        sizes.push(n);
        labs.push(l);
    }
    (id, sizes, labs)
}

/// Remove regions smaller than `min_px` pixels, handing their pixels to the nearest surviving
/// region through a distance transform. Every label (background included) takes part.
pub fn remove_small(labels: &[i32], w: usize, h: usize, min_px: usize) -> Vec<i32> {
    let (id, sizes, _) = regions(labels, w, h);
    let keep: Vec<bool> = id.iter().map(|r| sizes[*r as usize] >= min_px).collect();
    if keep.iter().all(|k| *k) || !keep.iter().any(|k| *k) {
        return labels.to_vec();
    }
    let (_, near) = edt(&keep, w, h);
    (0..w * h).map(|i| if keep[i] { labels[i] } else { labels[near[i].max(0) as usize] }).collect()
}

/// A binary mask on a millimetre grid: pixel (i, j) covers [x0 + i/s, x0 + (i+1)/s).
#[derive(Clone)]
pub struct Mask {
    pub w: usize,
    pub h: usize,
    pub s: f32,
    pub x0: f32,
    pub y0: f32,
    pub v: Vec<bool>,
}

impl Mask {
    pub fn new(x0: f32, y0: f32, x1: f32, y1: f32, s: f32) -> Mask {
        let w = (((x1 - x0) * s).ceil() as usize).max(1);
        let h = (((y1 - y0) * s).ceil() as usize).max(1);
        Mask { w, h, s, x0, y0, v: vec![false; w * h] }
    }
    pub fn like(&self) -> Mask {
        Mask { w: self.w, h: self.h, s: self.s, x0: self.x0, y0: self.y0, v: vec![false; self.w * self.h] }
    }
    /// Centre of pixel (i, j) in millimetres.
    pub fn centre(&self, i: usize, j: usize) -> Pt {
        (self.x0 + (i as f32 + 0.5) / self.s, self.y0 + (j as f32 + 0.5) / self.s)
    }
    pub fn at_mm(&self, p: Pt) -> bool {
        let i = ((p.0 - self.x0) * self.s).floor();
        let j = ((p.1 - self.y0) * self.s).floor();
        if i < 0.0 || j < 0.0 || i >= self.w as f32 || j >= self.h as f32 {
            return false;
        }
        self.v[j as usize * self.w + i as usize]
    }
    /// Fill rings (even-odd) into the mask, sampling pixel centres.
    pub fn fill(&mut self, rings: &[Ring], on: bool) {
        let mut xs: Vec<f32> = Vec::new();
        for j in 0..self.h {
            let y = self.y0 + (j as f32 + 0.5) / self.s;
            xs.clear();
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
            if xs.len() < 2 {
                continue;
            }
            xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
            for pair in xs.chunks_exact(2) {
                // pixel i is inside when its centre lies in [x0, x1)
                let i0 = (((pair[0] - self.x0) * self.s) - 0.5).ceil().max(0.0) as usize;
                let i1f = ((pair[1] - self.x0) * self.s) - 0.5;
                if i1f < 0.0 {
                    continue;
                }
                let i1 = (i1f.ceil() as usize).min(self.w);
                for i in i0..i1 {
                    self.v[j * self.w + i] = on;
                }
            }
        }
    }
    pub fn count(&self) -> usize {
        self.v.iter().filter(|b| **b).count()
    }
    pub fn area_mm2(&self) -> f32 {
        self.count() as f32 / (self.s * self.s)
    }
    pub fn and(&self, o: &Mask) -> Mask {
        let mut m = self.clone();
        for (a, b) in m.v.iter_mut().zip(&o.v) {
            *a = *a && *b;
        }
        m
    }
    pub fn or(&self, o: &Mask) -> Mask {
        let mut m = self.clone();
        for (a, b) in m.v.iter_mut().zip(&o.v) {
            *a = *a || *b;
        }
        m
    }
    pub fn minus(&self, o: &Mask) -> Mask {
        let mut m = self.clone();
        for (a, b) in m.v.iter_mut().zip(&o.v) {
            *a = *a && !*b;
        }
        m
    }
    /// Grow (d > 0) or shrink (d < 0) by `d` millimetres: a thresholded distance field.
    pub fn offset(&self, d: f32) -> Mask {
        if d == 0.0 {
            return self.clone();
        }
        let px = d.abs() * self.s;
        let mut m = self.clone();
        if d > 0.0 {
            let (dist, _) = edt(&self.v, self.w, self.h);
            let lim = px * px;
            for (o, dd) in m.v.iter_mut().zip(&dist) {
                *o = *dd <= lim;
            }
        } else {
            let inv: Vec<bool> = self.v.iter().map(|b| !b).collect();
            // outside the picture counts as outside the shape
            let (pw, ph) = (self.w + 2, self.h + 2);
            let mut seed = vec![true; pw * ph];
            for y in 0..self.h {
                for x in 0..self.w {
                    seed[(y + 1) * pw + x + 1] = inv[y * self.w + x];
                }
            }
            let (dist, _) = edt(&seed, pw, ph);
            let lim = px * px;
            for y in 0..self.h {
                for x in 0..self.w {
                    m.v[y * self.w + x] = self.v[y * self.w + x] && dist[(y + 1) * pw + x + 1] > lim;
                }
            }
        }
        m
    }
    /// Distance in millimetres from each inside pixel to the outline.
    pub fn inside_mm(&self) -> Vec<f32> {
        inside_distance(&self.v, self.w, self.h).into_iter().map(|d| d / self.s).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn edt_matches_brute_force() {
        let (w, h) = (17, 11);
        let mut seed = vec![false; w * h];
        for &i in &[3usize, 40, 99, 150, 186] {
            seed[i] = true;
        }
        let (d, a) = edt(&seed, w, h);
        for y in 0..h {
            for x in 0..w {
                let mut best = f32::MAX;
                for s in 0..w * h {
                    if seed[s] {
                        let (sx, sy) = ((s % w) as f32, (s / w) as f32);
                        best = best.min((sx - x as f32).powi(2) + (sy - y as f32).powi(2));
                    }
                }
                assert!((d[y * w + x] - best).abs() < 1e-3);
                let s = a[y * w + x] as usize;
                let dd = ((s % w) as f32 - x as f32).powi(2) + ((s / w) as f32 - y as f32).powi(2);
                assert!((dd - best).abs() < 1e-3);
            }
        }
    }
    #[test]
    fn resize_keeps_edges_clean() {
        // opaque red on transparent black: no dark fringe after enlarging
        let mut px = vec![0u8; 4 * 4 * 4];
        for y in 0..4 {
            for x in 0..2 {
                px[(y * 4 + x) * 4..(y * 4 + x) * 4 + 4].copy_from_slice(&[255, 0, 0, 255]);
            }
        }
        let big = resize(&Img { w: 4, h: 4, px }, 16, 16);
        for c in big.px.chunks_exact(4) {
            if c[3] > 10 {
                assert!(c[0] > 240, "{:?}", c);
            }
        }
        let small = resize(&big, 2, 2);
        assert!(small.px[3] > 230, "{}", small.px[3]);
    }
    #[test]
    fn mask_fill_and_offset() {
        let sq: Ring = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let mut m = Mask::new(-2.0, -2.0, 12.0, 12.0, 10.0);
        m.fill(&[sq], true);
        assert!((m.area_mm2() - 100.0).abs() < 0.5);
        let g = m.offset(1.0);
        assert!(g.area_mm2() > 140.0 && g.area_mm2() < 146.0, "{}", g.area_mm2());
        let s = m.offset(-1.0);
        assert!((s.area_mm2() - 64.0).abs() < 2.0, "{}", s.area_mm2());
    }
}
