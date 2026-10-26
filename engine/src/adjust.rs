//! Image adjustments: brightness/contrast, hue/saturation/lightness, greyscale, blur and
//! sharpen, on the floating selection, or on the active layer inside the selection (all of
//! it when nothing is selected). A preview can be shown, changed and then kept or dropped.

use crate::doc::Doc;

pub const BRIGHT_CONTRAST: u32 = 0;
pub const HUE_SAT: u32 = 1;
pub const GREY: u32 = 2;
pub const BLUR: u32 = 3;
pub const SHARPEN: u32 = 4;
pub const SEPIA: u32 = 5;

fn clamp8(v: f32) -> u8 {
    v.round().clamp(0.0, 255.0) as u8
}

fn rgb_to_hsl(r: f32, g: f32, b: f32) -> (f32, f32, f32) {
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let l = (max + min) / 2.0;
    if max == min {
        return (0.0, 0.0, l);
    }
    let d = max - min;
    let s = if l > 0.5 { d / (2.0 - max - min) } else { d / (max + min) };
    let h = if max == r {
        (g - b) / d + if g < b { 6.0 } else { 0.0 }
    } else if max == g {
        (b - r) / d + 2.0
    } else {
        (r - g) / d + 4.0
    };
    (h * 60.0, s, l)
}

fn hsl_to_rgb(h: f32, s: f32, l: f32) -> (f32, f32, f32) {
    if s == 0.0 {
        return (l, l, l);
    }
    let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
    let p = 2.0 * l - q;
    let hk = h / 360.0;
    let f = |t: f32| {
        let t = if t < 0.0 { t + 1.0 } else if t > 1.0 { t - 1.0 } else { t };
        if t < 1.0 / 6.0 {
            p + (q - p) * 6.0 * t
        } else if t < 0.5 {
            q
        } else if t < 2.0 / 3.0 {
            p + (q - p) * (2.0 / 3.0 - t) * 6.0
        } else {
            p
        }
    };
    (f(hk + 1.0 / 3.0), f(hk), f(hk - 1.0 / 3.0))
}

/// One pixel's colour changed (alpha kept). a, b, c: the adjustment's settings.
fn point(kind: u32, a: f32, b: f32, c: f32, p: &mut [u8]) {
    let (r, g, bl) = (p[0] as f32, p[1] as f32, p[2] as f32);
    let out = match kind {
        BRIGHT_CONTRAST => {
            // brightness -100..100 moves every level; contrast -100..100 spreads them about the middle
            let ct = (b * 2.55).clamp(-254.0, 254.0);
            let f = (259.0 * (ct + 255.0)) / (255.0 * (259.0 - ct));
            let br = a * 2.55;
            let m = |v: f32| f * (v + br - 128.0) + 128.0;
            (m(r), m(g), m(bl))
        }
        HUE_SAT => {
            let (h, s, l) = rgb_to_hsl(r / 255.0, g / 255.0, bl / 255.0);
            let h = (h + a).rem_euclid(360.0);
            let s = (s * (1.0 + b / 100.0)).clamp(0.0, 1.0);
            let l = if c >= 0.0 { l + (1.0 - l) * c / 100.0 } else { l * (1.0 + c / 100.0) };
            let (r2, g2, b2) = hsl_to_rgb(h, s, l.clamp(0.0, 1.0));
            (r2 * 255.0, g2 * 255.0, b2 * 255.0)
        }
        GREY => {
            let y = 0.299 * r + 0.587 * g + 0.114 * bl;
            (y, y, y)
        }
        SEPIA => {
            (0.393 * r + 0.769 * g + 0.189 * bl, 0.349 * r + 0.686 * g + 0.168 * bl, 0.272 * r + 0.534 * g + 0.131 * bl)
        }
        _ => (r, g, bl),
    };
    p[0] = clamp8(out.0);
    p[1] = clamp8(out.1);
    p[2] = clamp8(out.2);
}

/// A box blur of radius r over premultiplied RGBA (w x h), three passes (close to Gaussian).
fn blur_premul(px: &[f32], w: usize, h: usize, r: usize) -> Vec<f32> {
    let mut cur = px.to_vec();
    let mut tmp = vec![0f32; px.len()];
    for _ in 0..3 {
        // across
        for y in 0..h {
            let row = y * w;
            let mut acc = [0f32; 4];
            let n = (2 * r + 1) as f32;
            for k in 0..=(2 * r) {
                let x = (k as isize - r as isize).clamp(0, w as isize - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += cur[(row + x) * 4 + ch];
                }
            }
            for x in 0..w {
                for ch in 0..4 {
                    tmp[(row + x) * 4 + ch] = acc[ch] / n;
                }
                let out_x = (x as isize - r as isize).clamp(0, w as isize - 1) as usize;
                let in_x = (x as isize + r as isize + 1).clamp(0, w as isize - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += cur[(row + in_x) * 4 + ch] - cur[(row + out_x) * 4 + ch];
                }
            }
        }
        // down
        for x in 0..w {
            let mut acc = [0f32; 4];
            let n = (2 * r + 1) as f32;
            for k in 0..=(2 * r) {
                let y = (k as isize - r as isize).clamp(0, h as isize - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += tmp[(y * w + x) * 4 + ch];
                }
            }
            for y in 0..h {
                for ch in 0..4 {
                    cur[(y * w + x) * 4 + ch] = acc[ch] / n;
                }
                let out_y = (y as isize - r as isize).clamp(0, h as isize - 1) as usize;
                let in_y = (y as isize + r as isize + 1).clamp(0, h as isize - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += tmp[(in_y * w + x) * 4 + ch] - tmp[(out_y * w + x) * 4 + ch];
                }
            }
        }
    }
    cur
}

/// Blur (radius a px) or sharpen (amount a %, unsharp mask of radius 1) a block of straight
/// RGBA, returning the new pixels.
fn neighbourhood(kind: u32, a: f32, src: &[u8], w: usize, h: usize) -> Vec<u8> {
    let pre: Vec<f32> = src.chunks_exact(4).flat_map(|p| {
        let al = p[3] as f32 / 255.0;
        [p[0] as f32 * al, p[1] as f32 * al, p[2] as f32 * al, p[3] as f32]
    }).collect();
    let r = if kind == BLUR { (a.round().max(1.0)) as usize } else { 1 };
    let bl = blur_premul(&pre, w, h, r);
    let mut out = vec![0u8; src.len()];
    for i in 0..w * h {
        let mut v = [0f32; 4];
        for ch in 0..4 {
            v[ch] = if kind == BLUR { bl[i * 4 + ch] } else { pre[i * 4 + ch] + (pre[i * 4 + ch] - bl[i * 4 + ch]) * a / 100.0 };
        }
        let al = v[3].clamp(0.0, 255.0);
        out[i * 4 + 3] = clamp8(al);
        if al > 0.0 {
            for ch in 0..3 {
                out[i * 4 + ch] = clamp8(v[ch] * 255.0 / al);
            }
        }
    }
    out
}

/// The adjustment applied to straight RGBA in place.
fn apply_block(kind: u32, a: f32, b: f32, c: f32, px: &mut [u8], w: usize, h: usize) {
    if kind == BLUR || kind == SHARPEN {
        let out = neighbourhood(kind, a, px, w, h);
        px.copy_from_slice(&out);
        return;
    }
    for p in px.chunks_exact_mut(4) {
        if p[3] > 0 {
            point(kind, a, b, c, p);
        }
    }
}

impl Doc {
    /// Show (or change) the preview of an adjustment; adjust_end keeps it, adjust_cancel drops it.
    pub fn adjust_preview(&mut self, kind: u32, a: f32, b: f32, c: f32) {
        if !self.adj_open {
            self.adj_open = true;
            if let Some(f) = self.float.as_ref() {
                self.adj_float = Some(f.src.clone());
            } else {
                self.finish_pending();
                self.op_begin();
            }
        }
        if let Some(orig) = self.adj_float.clone() {
            if let Some(f) = self.float.as_mut() {
                f.src = orig;
                let (sw, sh) = (f.sw, f.sh);
                apply_block(kind, a, b, c, &mut f.src, sw, sh);
                f.refresh();
                let (x0, y0, x1, y1) = f.rect();
                self.mark_dirty(x0, y0, x1, y1);
            }
            return;
        }
        self.op_restore();
        let (x0, y0, x1, y1) = self.sel_bounds().unwrap_or((0, 0, self.w, self.h));
        if x1 <= x0 || y1 <= y0 || self.layers.is_empty() {
            return;
        }
        // blur and sharpen read a margin around what they change
        let m = if kind == BLUR { (a.round().max(1.0) as usize) * 3 } else if kind == SHARPEN { 3 } else { 0 };
        let (bx0, by0) = (x0.saturating_sub(m), y0.saturating_sub(m));
        let (bx1, by1) = ((x1 + m).min(self.w), (y1 + m).min(self.h));
        let (bw, bh) = (bx1 - bx0, by1 - by0);
        let li = self.active;
        let mut block = vec![0u8; bw * bh * 4];
        for y in 0..bh {
            let o = ((by0 + y) * self.w + bx0) * 4;
            block[y * bw * 4..(y + 1) * bw * 4].copy_from_slice(&self.layers[li].px[o..o + bw * 4]);
        }
        let mut done = block.clone();
        apply_block(kind, a, b, c, &mut done, bw, bh);
        self.touch(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
        for y in y0..y1 {
            for x in x0..x1 {
                let i = y * self.w + x;
                let s = self.sel_at(i);
                if s <= 0.0 {
                    continue;
                }
                let k = ((y - by0) * bw + (x - bx0)) * 4;
                let p = &mut self.layers[li].px[i * 4..i * 4 + 4];
                for ch in 0..4 {
                    let o = block[k + ch] as f32;
                    p[ch] = clamp8(o + (done[k + ch] as f32 - o) * s);
                }
            }
        }
        self.mark_dirty(x0 as i64, y0 as i64, x1 as i64, y1 as i64);
    }

    pub fn adjust_end(&mut self) {
        if !self.adj_open {
            return;
        }
        self.adj_open = false;
        if self.adj_float.take().is_none() {
            self.op_end();
        }
    }

    pub fn adjust_cancel(&mut self) {
        if !self.adj_open {
            return;
        }
        self.adj_open = false;
        if let Some(orig) = self.adj_float.take() {
            if let Some(f) = self.float.as_mut() {
                f.src = orig;
                f.refresh();
                let (x0, y0, x1, y1) = f.rect();
                self.mark_dirty(x0, y0, x1, y1);
            }
        } else {
            self.op_cancel();
        }
    }

    /// An adjustment in one go (Greyscale, Sepia).
    pub fn adjust(&mut self, kind: u32, a: f32, b: f32, c: f32) {
        self.adjust_preview(kind, a, b, c);
        self.adjust_end();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn doc_with(px: [u8; 4]) -> Doc {
        let mut d = Doc::new(4, 4, [255, 255, 255, 255]);
        for p in d.layers[0].px.chunks_exact_mut(4) {
            p.copy_from_slice(&px);
        }
        d
    }

    #[test]
    fn points() {
        let mut d = doc_with([100, 150, 200, 255]);
        d.adjust(GREY, 0.0, 0.0, 0.0);
        let p = &d.layers[0].px[0..4];
        assert!(p[0] == p[1] && p[1] == p[2] && (p[0] as i32 - 141).abs() <= 1, "{:?}", p);
        assert!(d.can_undo());
        d.undo();
        assert_eq!(&d.layers[0].px[0..4], &[100, 150, 200, 255]);
        // brightness up, then the preview changed and dropped
        d.adjust_preview(BRIGHT_CONTRAST, 50.0, 0.0, 0.0);
        assert!(d.layers[0].px[0] > 100);
        d.adjust_preview(BRIGHT_CONTRAST, -50.0, 0.0, 0.0);
        assert!(d.layers[0].px[0] < 100, "a new preview starts from the original");
        d.adjust_cancel();
        assert_eq!(&d.layers[0].px[0..4], &[100, 150, 200, 255]);
        // hue by 180 turns blue-ish to orange-ish; saturation -100 is grey
        d.adjust(HUE_SAT, 180.0, 0.0, 0.0);
        let p = d.layers[0].px[0..3].to_vec();
        assert!(p[0] > p[2], "{:?}", p);
        d.adjust(HUE_SAT, 0.0, -100.0, 0.0);
        let p = &d.layers[0].px[0..3];
        assert!(p[0] == p[1] && p[1] == p[2]);
        // contrast pushes levels apart
        let mut e = doc_with([100, 160, 128, 255]);
        e.adjust(BRIGHT_CONTRAST, 0.0, 50.0, 0.0);
        let p = &e.layers[0].px[0..3];
        assert!(p[0] < 100 && p[1] > 160 && (p[2] as i32 - 128).abs() <= 1, "{:?}", p);
    }

    #[test]
    fn blur_and_selection() {
        let mut d = Doc::new(20, 1, [0, 0, 0, 255]);
        for x in 10..20 {
            d.layers[0].px[x * 4..x * 4 + 3].copy_from_slice(&[255, 255, 255]);
        }
        d.adjust(BLUR, 2.0, 0.0, 0.0);
        let v: Vec<u8> = (0..20).map(|x| d.layers[0].px[x * 4]).collect();
        assert!(v[9] > 0 && v[9] < 255 && v[10] < 255 && v[0] == 0 && v[19] == 255, "{:?}", v);
        d.undo();
        // sharpen makes the edge steeper
        d.adjust(SHARPEN, 100.0, 0.0, 0.0);
        let v: Vec<u8> = (0..20).map(|x| d.layers[0].px[x * 4]).collect();
        assert_eq!((v[0], v[19]), (0, 255));
        d.undo();
        // only inside the selection
        d.sel_rect(0, 0, 5, 1);
        d.adjust(GREY, 0.0, 0.0, 0.0);
        let mut f = Doc::new(4, 1, [10, 200, 30, 255]);
        f.sel_rect(0, 0, 2, 1);
        f.adjust(GREY, 0.0, 0.0, 0.0);
        assert!(f.layers[0].px[0] == f.layers[0].px[1] && f.layers[0].px[12] == 10 && f.layers[0].px[13] == 200);
        // transparent pixels don't pick up colour from a blur
        let mut t = Doc::new(10, 1, [0, 0, 0, 0]);
        t.layers[0].px[20..24].copy_from_slice(&[255, 0, 0, 255]);
        t.adjust(BLUR, 2.0, 0.0, 0.0);
        let p = &t.layers[0].px[16..20];
        assert!(p[3] > 0 && p[0] > 200 && p[1] == 0, "colour stays red at the soft edge: {:?}", p);
    }
}
