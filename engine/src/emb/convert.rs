//! Picture → shapes: place a picture on the hoop, then reduce its colours, clean the regions up
//! and trace each one into an editable shape with its thread.

use super::colour::{de2000, de76, de76sq, kmeans, lab_to_rgb, nearest_thread, pec_name, pec_rgb, rgb_to_lab, rgb_to_lab_f, Lab};
use super::json::J;
use super::raster::{bilateral, label_vote, lab_gradient, remove_small, resize, to_lab, Img};
use super::trace::trace_labels;

/// Median of the opaque border pixels; None when the border is mostly transparent.
pub fn detect_background(img: &Img) -> Option<[u8; 3]> {
    let (w, h) = (img.w, img.h);
    let mut ch: [Vec<u8>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    let mut total = 0;
    let mut push = |x: usize, y: usize| {
        total += 1;
        let o = (y * w + x) * 4;
        if img.px[o + 3] >= 128 {
            for k in 0..3 {
                ch[k].push(img.px[o + k]);
            }
        }
    };
    for x in 0..w {
        push(x, 0);
        if h > 1 {
            push(x, h - 1);
        }
    }
    for y in 1..h.saturating_sub(1) {
        push(0, y);
        if w > 1 {
            push(w - 1, y);
        }
    }
    if ch[0].len() * 2 < total {
        return None;
    }
    let mut out = [0u8; 3];
    for k in 0..3 {
        ch[k].sort_unstable();
        out[k] = ch[k][ch[k].len() / 2];
    }
    Some(out)
}

/// Bounding box (x0, y0, x1, y1) of the content: opaque pixels that are not background.
pub fn content_box(img: &Img, bg: Option<[u8; 3]>) -> Option<(usize, usize, usize, usize)> {
    let bgl = bg.map(rgb_to_lab);
    let mut b = (usize::MAX, usize::MAX, 0usize, 0usize);
    for y in 0..img.h {
        for x in 0..img.w {
            let o = (y * img.w + x) * 4;
            if img.px[o + 3] < 128 {
                continue;
            }
            if let Some(l) = bgl {
                if de76(rgb_to_lab([img.px[o], img.px[o + 1], img.px[o + 2]]), l) < 12.0 {
                    continue;
                }
            }
            b.0 = b.0.min(x);
            b.1 = b.1.min(y);
            b.2 = b.2.max(x + 1);
            b.3 = b.3.max(y + 1);
        }
    }
    if b.0 == usize::MAX {
        None
    } else {
        Some(b)
    }
}

pub struct Placed {
    pub img: Img,
    pub bg: Option<[u8; 3]>,
    pub upscale: f32,
    pub rect: (i64, i64, usize, usize),
}

/// Fit a picture to the hoop: background found on the uncropped source, crop to content, then
/// scale the content to fill the hoop less `margin` mm on each side, centred, on a transparent
/// canvas of `cw`×`ch` pixels at `s` px/mm.
pub fn place(src: &Img, cw: usize, ch: usize, s: f32, margin: f32, crop: bool) -> Placed {
    let bg = detect_background(src);
    let (x0, y0, x1, y1) = if crop { content_box(src, bg).unwrap_or((0, 0, src.w, src.h)) } else { (0, 0, src.w, src.h) };
    let (cw0, ch0) = (x1 - x0, y1 - y0);
    let mut cropped = Img { w: cw0, h: ch0, px: vec![0; cw0 * ch0 * 4] };
    for y in 0..ch0 {
        let so = ((y + y0) * src.w + x0) * 4;
        cropped.px[y * cw0 * 4..(y + 1) * cw0 * 4].copy_from_slice(&src.px[so..so + cw0 * 4]);
    }
    let avail_w = (cw as f32 - 2.0 * margin * s).max(1.0);
    let avail_h = (ch as f32 - 2.0 * margin * s).max(1.0);
    let k = (avail_w / cw0 as f32).min(avail_h / ch0 as f32);
    let tw = ((cw0 as f32 * k).round() as usize).clamp(1, cw);
    let th = ((ch0 as f32 * k).round() as usize).clamp(1, ch);
    let fitted = resize(&cropped, tw, th);
    let ox = (cw - tw) / 2;
    let oy = (ch - th) / 2;
    let mut out = Img { w: cw, h: ch, px: vec![0; cw * ch * 4] };
    for y in 0..th {
        let d = ((y + oy) * cw + ox) * 4;
        out.px[d..d + tw * 4].copy_from_slice(&fitted.px[y * tw * 4..(y + 1) * tw * 4]);
    }
    Placed { img: out, bg, upscale: k, rect: (ox as i64, oy as i64, tw, th) }
}

pub struct Params {
    pub colours: usize, // 0 = auto
    pub auto_max: usize,
    pub bg_mode: u8, // 0 remove, 1 keep
    pub bg: Option<[u8; 3]>,
    pub smoothing: usize,
    pub min_area: f32, // mm²
    pub edge_radius: usize,
    pub upscale: f32,
    pub exact: bool,
    pub seed: u64,
}

impl Params {
    pub fn from_json(j: &J) -> Params {
        let bg = j.get("bg");
        Params {
            colours: j.get("colours").i(0).clamp(0, 40) as usize,
            auto_max: j.get("auto_max").i(12).clamp(1, 40) as usize,
            bg_mode: if j.get("background").s() == "keep" { 1 } else { 0 },
            bg: if bg.arr().len() >= 3 { Some([bg.at(0).i(0) as u8, bg.at(1).i(0) as u8, bg.at(2).i(0) as u8]) } else { None },
            smoothing: j.get("smoothing").i(1).clamp(0, 6) as usize,
            min_area: j.get("min_area").f32(1.5).max(0.0),
            edge_radius: j.get("edge_radius").i(2).clamp(0, 6) as usize,
            upscale: j.get("upscale").f32(1.0).max(1.0),
            exact: j.get("threads").s() == "exact",
            seed: j.get("seed").i(20261028) as u64,
        }
    }
}

fn lab_lerp_rgb(a: [f32; 3], b: [f32; 3], t: f32) -> Lab {
    rgb_to_lab_f(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
}

/// Is `c` a blend between the background and colour `r`? Blends lie on the straight RGB line,
/// which is curved in Lab, so the test follows that curve with a tolerance that grows with the
/// distance between the two ends.
fn is_blend(c: Lab, bg: Lab, r: Lab) -> bool {
    let ab = de76(bg, r);
    let tol = 10f32.max(0.16 * ab);
    let (bgr, rr) = (lab_to_rgb(bg), lab_to_rgb(r));
    let (bgf, rf) = ([bgr[0] as f32, bgr[1] as f32, bgr[2] as f32], [rr[0] as f32, rr[1] as f32, rr[2] as f32]);
    let mut best = f32::MAX;
    let mut tbest = 0.0;
    for i in 1..40 {
        let t = i as f32 / 40.0;
        let d = de76(c, lab_lerp_rgb(bgf, rf, t));
        if d < best {
            best = d;
            tbest = t;
        }
    }
    // the ends themselves are not blends
    let _ = tbest;
    best < tol && de76(c, r) > 4.0 && de76(c, bg) > 4.0
}

/// Is `c` on the straight RGB line between two real colours (an edge between them)?
fn is_pair_blend(c: Lab, a: Lab, b: Lab) -> bool {
    let ab = de76(a, b);
    let tol = 10f32.max(0.16 * ab);
    let (ar, br) = (lab_to_rgb(a), lab_to_rgb(b));
    let (af, bf) = ([ar[0] as f32, ar[1] as f32, ar[2] as f32], [br[0] as f32, br[1] as f32, br[2] as f32]);
    (1..40).any(|i| de76(c, lab_lerp_rgb(af, bf, i as f32 / 40.0)) < tol)
}

pub struct Converted {
    pub shapes: Vec<J>,
    pub colours: Vec<J>,
    pub labels: Vec<i32>,
}

/// Picture → shapes. `img` is the picture layer at `s` px/mm; pixel (0,0) sits at (x0, y0) mm.
pub fn convert(img: &Img, s: f32, x0: f32, y0: f32, p: &Params) -> Converted {
    let (w, h) = (img.w, img.h);
    let n = w * h;
    let raw = to_lab(img);
    let lab = bilateral(&raw, w, h, p.smoothing, 12.0);
    let opaque: Vec<bool> = img.px.chunks_exact(4).map(|c| c[3] >= 128).collect();
    let bg_rgb = p.bg.or_else(|| detect_background(img));
    let bg_lab = bg_rgb.map(rgb_to_lab);
    let remove_bg = p.bg_mode == 0 && bg_lab.is_some();

    // interior pixels only: edges found with a morphological gradient, kernel scaled to the
    // upscale factor so wide ramps of an enlarged picture don't count as colours
    let k = 2 * (p.upscale.round() as usize).max(1) + 1;
    let grad_wide = lab_gradient(&lab, w, h, k);
    // thin lines can be all edge at the wide kernel: their flat cores still count (a 3×3
    // window with a stricter threshold keeps the ramps out)
    let grad3 = if k > 3 { lab_gradient(&lab, w, h, 3) } else { grad_wide.clone() };
    let grad: Vec<f32> = (0..n).map(|i| if grad3[i] <= 6.0 { grad3[i].min(grad_wide[i]) } else { grad_wide[i] }).collect();
    let mut samples: Vec<Lab> = Vec::new();
    let mut interior_count = 0usize;
    for i in 0..n {
        if !opaque[i] || grad[i] > 12.0 {
            continue;
        }
        if remove_bg && de76(lab[i], bg_lab.unwrap()) < 10.0 {
            continue;
        }
        interior_count += 1;
    }
    let stride = (interior_count / 60000).max(1);
    let mut c = 0usize;
    for i in 0..n {
        if !opaque[i] || grad[i] > 12.0 {
            continue;
        }
        if remove_bg && de76(lab[i], bg_lab.unwrap()) < 10.0 {
            continue;
        }
        if c % stride == 0 {
            samples.push(lab[i]);
        }
        c += 1;
    }
    if samples.is_empty() {
        // nothing but edges (or nothing at all): fall back to every opaque non-background pixel
        for i in 0..n {
            if opaque[i] && !(remove_bg && de76(lab[i], bg_lab.unwrap()) < 10.0) {
                samples.push(lab[i]);
            }
        }
    }
    let mut centres: Vec<Lab> = Vec::new();
    if !samples.is_empty() {
        if p.colours > 0 {
            centres = kmeans(&samples, p.colours, p.seed, 40);
        } else {
            // grow k until fewer than 0.1 % of the samples are more than ΔE 14 from every centre
            // (background included) and the mean error is under 8
            for kk in 1..=p.auto_max {
                centres = kmeans(&samples, kk, p.seed, 40);
                let mut far = 0usize;
                let mut sum = 0f64;
                for s in &samples {
                    let mut d = centres.iter().map(|c| de76sq(*s, *c)).fold(f32::MAX, f32::min);
                    if let Some(b) = bg_lab {
                        if remove_bg {
                            d = d.min(de76sq(*s, b));
                        }
                    }
                    let d = d.sqrt();
                    if d > 14.0 {
                        far += 1;
                    }
                    sum += d as f64;
                }
                let mean = sum / samples.len() as f64;
                if (far as f64) < 0.001 * samples.len() as f64 && mean < 8.0 {
                    break;
                }
            }
        }
    }
    // population of each centre among the samples
    let pop = |cs: &Vec<Lab>| -> Vec<usize> {
        let mut v = vec![0usize; cs.len()];
        for s in &samples {
            let mut best = 0;
            let mut bd = f32::MAX;
            for (j, c) in cs.iter().enumerate() {
                let d = de76sq(*s, *c);
                if d < bd {
                    bd = d;
                    best = j;
                }
            }
            if !cs.is_empty() {
                v[best] += 1;
            }
        }
        v
    };
    if p.colours == 0 {
        // drop anti-aliasing blends between the removed background and a real colour
        if remove_bg {
            let b = bg_lab.unwrap();
            let pv = pop(&centres);
            let mut order: Vec<usize> = (0..centres.len()).collect();
            order.sort_by(|a, c| pv[*c].cmp(&pv[*a]));
            let mut kept: Vec<Lab> = Vec::new();
            for &i in &order {
                let c = centres[i];
                if de76(c, b) < 10.0 {
                    continue;
                }
                if kept.iter().any(|r| is_blend(c, b, *r)) {
                    continue;
                }
                kept.push(c);
            }
            centres = kept;
        }
        // merge centres closer than ΔE2000 4
        let mut merged: Vec<Lab> = Vec::new();
        for c in centres {
            if !merged.iter().any(|m| de2000(*m, c) < 4.0) {
                merged.push(c);
            }
        }
        centres = merged;
        // thin artwork can be all edge, so its colour never reached the interior samples: look
        // for pixels far from every colour that are not blends of colours already found
        let content: usize = (0..n).filter(|&i| opaque[i] && !(remove_bg && de76(lab[i], bg_lab.unwrap()) < 10.0)).count();
        for _ in 0..4 {
            if centres.len() >= p.auto_max {
                break;
            }
            let mut ends: Vec<Lab> = centres.clone();
            if let Some(b) = bg_lab {
                ends.push(b);
            }
            // distance of every pixel to the nearest colour found so far
            let near: Vec<f32> = (0..n)
                .map(|i| if opaque[i] { ends.iter().map(|e| de76sq(lab[i], *e)).fold(f32::MAX, f32::min) } else { 0.0 })
                .collect();
            let mut cand: Vec<Lab> = Vec::new();
            for i in 0..n {
                if near[i] <= 14.0 * 14.0 {
                    continue;
                }
                // the core of a thin line: as far from every known colour as its neighbours
                let (x, y) = (i % w, i / w);
                let mut core = true;
                'nb: for dy in -1i64..=1 {
                    for dx in -1i64..=1 {
                        let (xx, yy) = (x as i64 + dx, y as i64 + dy);
                        if xx < 0 || yy < 0 || xx >= w as i64 || yy >= h as i64 || (dx == 0 && dy == 0) {
                            continue;
                        }
                        if near[yy as usize * w + xx as usize] > near[i] * 1.0001 + 1.0 {
                            core = false;
                            break 'nb;
                        }
                    }
                }
                if core {
                    cand.push(lab[i]);
                }
            }
            if cand.len() < 30 || (cand.len() as f64) < 0.001 * content as f64 {
                break;
            }
            // the purest of them: drop blends of any two colours found so far
            let step = (cand.len() / 20000).max(1);
            let cand: Vec<Lab> = cand
                .into_iter()
                .step_by(step)
                .filter(|c| {
                    for a in 0..ends.len() {
                        for b in a + 1..ends.len() {
                            if is_pair_blend(*c, ends[a], ends[b]) {
                                return false;
                            }
                        }
                    }
                    true
                })
                .collect();
            if cand.len() * step < 30 || ((cand.len() * step) as f64) < 0.001 * content as f64 {
                break;
            }
            let c = kmeans(&cand, 1, p.seed, 20)[0];
            if centres.iter().any(|m| de2000(*m, c) < 4.0) {
                break;
            }
            centres.push(c);
        }
    }
    let keep_bg_label = p.bg_mode == 1 && bg_lab.is_some() && !centres.iter().any(|c| de2000(*c, bg_lab.unwrap()) < 4.0);
    if keep_bg_label {
        centres.push(bg_lab.unwrap());
    }
    // assign every pixel; the background competes, so edge pixels nearer it go back to fabric
    let nl = centres.len();
    let mut labels = vec![-1i32; n];
    for i in 0..n {
        if !opaque[i] {
            continue;
        }
        let mut best = -1i32;
        let mut bd = if remove_bg { de76sq(lab[i], bg_lab.unwrap()) } else { f32::MAX };
        for (j, c) in centres.iter().enumerate() {
            let d = de76sq(lab[i], *c);
            if d < bd {
                bd = d;
                best = j as i32;
            }
        }
        labels[i] = best;
    }
    let labels = label_vote(&labels, w, h, p.edge_radius, nl);
    let min_px = (p.min_area * s * s).round() as usize;
    let labels = remove_small(&labels, w, h, min_px.max(1));

    // threads: each colour matched on its purest pixels (the quarter farthest from the
    // background), which thin lines would otherwise drag toward the background
    let mut per: Vec<Vec<(f32, Lab)>> = vec![Vec::new(); nl];
    for i in 0..n {
        let l = labels[i];
        if l < 0 {
            continue;
        }
        let d = bg_lab.map(|b| de76(raw[i], b)).unwrap_or(0.0);
        per[l as usize].push((d, raw[i]));
    }
    let mut colours = Vec::new();
    let mut thread_of = Vec::new();
    for (j, v) in per.iter_mut().enumerate() {
        let mean = if v.is_empty() {
            centres[j]
        } else {
            v.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
            let q = (v.len() / 4).max(1);
            let mut acc = [0f64; 3];
            for (_, l) in &v[..q] {
                acc[0] += l[0] as f64;
                acc[1] += l[1] as f64;
                acc[2] += l[2] as f64;
            }
            [(acc[0] / q as f64) as f32, (acc[1] / q as f64) as f32, (acc[2] / q as f64) as f32]
        };
        let pec = nearest_thread(mean);
        let rgb = if p.exact { lab_to_rgb(mean) } else { pec_rgb(pec) };
        let mut t = J::obj();
        t.set("rgb", J::Arr(vec![J::from(rgb[0] as i64), J::from(rgb[1] as i64), J::from(rgb[2] as i64)]));
        if !p.exact {
            t.set("pec", J::from(pec as i64));
            t.set("name", J::from(pec_name(pec)));
        } else {
            t.set("name", J::from(format!("#{:02X}{:02X}{:02X}", rgb[0], rgb[1], rgb[2])));
        }
        let mut cj = J::obj();
        cj.set("thread", t.clone());
        cj.set("pixels", J::from(v.len()));
        colours.push(cj);
        thread_of.push(t);
    }
    // colours that came out as the same chart thread are one colour
    let mut labels = labels;
    if !p.exact {
        let mut remap: Vec<usize> = (0..nl).collect();
        for j in 0..nl {
            for i in 0..j {
                if remap[i] == i && thread_of[i].get("pec").i(0) == thread_of[j].get("pec").i(0) {
                    remap[j] = i;
                    break;
                }
            }
        }
        if remap.iter().enumerate().any(|(i, r)| *r != i) {
            for l in labels.iter_mut() {
                if *l >= 0 {
                    *l = remap[*l as usize] as i32;
                }
            }
            let mut kept_colours = Vec::new();
            let mut px_of = vec![0usize; nl];
            for l in labels.iter() {
                if *l >= 0 {
                    px_of[*l as usize] += 1;
                }
            }
            for i in 0..nl {
                if remap[i] == i {
                    let mut c = colours[i].clone();
                    c.set("pixels", J::from(px_of[i]));
                    kept_colours.push(c);
                }
            }
            colours = kept_colours;
        }
    }
    let traced = trace_labels(&labels, w, h, x0, y0, s, 0.1);
    let mut shapes = Vec::new();
    for t in traced {
        let mut sj = J::obj();
        let rings = J::Arr(
            t.rings
                .iter()
                .map(|r| J::Arr(r.iter().map(|p| J::Arr(vec![J::from(p.0), J::from(p.1)])).collect()))
                .collect(),
        );
        sj.set("rings", rings);
        sj.set("thread", thread_of[t.label as usize].clone());
        sj.set("colour", J::from(t.label as i64));
        sj.set("area", J::from(t.px as f64 / (s * s) as f64));
        shapes.push(sj);
    }
    Converted { shapes, colours, labels }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn flat_logo_colours() {
        // 200×200 white field with a red disc, a blue bar and a thin black line
        let (w, h) = (200, 200);
        let mut px = vec![255u8; w * h * 4];
        for y in 0..h {
            for x in 0..w {
                let o = (y * w + x) * 4;
                let (dx, dy) = (x as f32 - 70.0, y as f32 - 70.0);
                let c: [u8; 3] = if dx * dx + dy * dy < 40.0 * 40.0 {
                    [237, 23, 31]
                } else if (120..180).contains(&x) && (40..160).contains(&y) {
                    [10, 85, 163]
                } else if (20..190).contains(&x) && (180..184).contains(&y) {
                    [0, 0, 0]
                } else {
                    [255, 255, 255]
                };
                px[o..o + 3].copy_from_slice(&c);
            }
        }
        let img = Img { w, h, px };
        let p = Params::from_json(&J::obj());
        let c = convert(&img, 10.0, -10.0, -10.0, &p);
        assert_eq!(c.colours.len(), 3, "{:?}", c.colours.iter().map(|c| c.get("thread").get("name").s().to_string()).collect::<Vec<_>>());
        let names: Vec<String> = c.colours.iter().map(|c| c.get("thread").get("name").s().to_string()).collect();
        assert!(names.contains(&"Red".to_string()) && names.contains(&"Black".to_string()), "{:?}", names);
        assert!(c.shapes.len() >= 3);
    }
}
