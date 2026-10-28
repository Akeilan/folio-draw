//! Colour science for embroidery: sRGB ↔ CIELAB, CIEDE2000, k-means++ and the Brother thread chart.

pub type Lab = [f32; 3];

fn lin(c: f32) -> f32 {
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

fn gam(c: f32) -> f32 {
    let c = c.clamp(0.0, 1.0);
    if c <= 0.0031308 {
        c * 12.92
    } else {
        1.055 * c.powf(1.0 / 2.4) - 0.055
    }
}

const XN: f32 = 0.95047;
const YN: f32 = 1.0;
const ZN: f32 = 1.08883;

fn fxyz(t: f32) -> f32 {
    if t > 0.008856 {
        t.cbrt()
    } else {
        7.787 * t + 16.0 / 116.0
    }
}

fn fxyz_inv(t: f32) -> f32 {
    if t > 0.206893 {
        t * t * t
    } else {
        (t - 16.0 / 116.0) / 7.787
    }
}

/// A lookup table for the sRGB decode of 8-bit channels.
pub fn lin_table() -> [f32; 256] {
    let mut t = [0.0; 256];
    for (i, v) in t.iter_mut().enumerate() {
        *v = lin(i as f32 / 255.0);
    }
    t
}

pub fn rgb_to_lab_f(r: f32, g: f32, b: f32) -> Lab {
    // r, g, b: 0..255 (may be fractional)
    let (r, g, b) = (lin(r / 255.0), lin(g / 255.0), lin(b / 255.0));
    lin_to_lab(r, g, b)
}

pub fn lin_to_lab(r: f32, g: f32, b: f32) -> Lab {
    let x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / XN;
    let y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / YN;
    let z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / ZN;
    let (fx, fy, fz) = (fxyz(x), fxyz(y), fxyz(z));
    [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)]
}

pub fn rgb_to_lab(c: [u8; 3]) -> Lab {
    rgb_to_lab_f(c[0] as f32, c[1] as f32, c[2] as f32)
}

pub fn lab_to_rgb(l: Lab) -> [u8; 3] {
    let fy = (l[0] + 16.0) / 116.0;
    let fx = fy + l[1] / 500.0;
    let fz = fy - l[2] / 200.0;
    let (x, y, z) = (fxyz_inv(fx) * XN, fxyz_inv(fy) * YN, fxyz_inv(fz) * ZN);
    let r = 3.2404542 * x - 1.5371385 * y - 0.4985314 * z;
    let g = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z;
    let b = 0.0556434 * x - 0.2040259 * y + 1.0572252 * z;
    [(gam(r) * 255.0).round() as u8, (gam(g) * 255.0).round() as u8, (gam(b) * 255.0).round() as u8]
}

/// Euclidean ΔE (CIE76): cheap, used inside k-means and gradient tests.
#[inline]
pub fn de76(a: Lab, b: Lab) -> f32 {
    let (d0, d1, d2) = (a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    (d0 * d0 + d1 * d1 + d2 * d2).sqrt()
}

#[inline]
pub fn de76sq(a: Lab, b: Lab) -> f32 {
    let (d0, d1, d2) = (a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    d0 * d0 + d1 * d1 + d2 * d2
}

/// CIEDE2000 colour difference.
pub fn de2000(a: Lab, b: Lab) -> f32 {
    let (l1, a1, b1) = (a[0] as f64, a[1] as f64, a[2] as f64);
    let (l2, a2, b2) = (b[0] as f64, b[1] as f64, b[2] as f64);
    let c1 = (a1 * a1 + b1 * b1).sqrt();
    let c2 = (a2 * a2 + b2 * b2).sqrt();
    let cm = (c1 + c2) / 2.0;
    let cm7 = cm.powi(7);
    let g = 0.5 * (1.0 - (cm7 / (cm7 + 25f64.powi(7))).sqrt());
    let a1p = (1.0 + g) * a1;
    let a2p = (1.0 + g) * a2;
    let c1p = (a1p * a1p + b1 * b1).sqrt();
    let c2p = (a2p * a2p + b2 * b2).sqrt();
    let h = |bb: f64, ap: f64| {
        if bb == 0.0 && ap == 0.0 {
            0.0
        } else {
            let v = bb.atan2(ap).to_degrees();
            if v < 0.0 {
                v + 360.0
            } else {
                v
            }
        }
    };
    let h1p = h(b1, a1p);
    let h2p = h(b2, a2p);
    let dlp = l2 - l1;
    let dcp = c2p - c1p;
    let dhp = if c1p * c2p == 0.0 {
        0.0
    } else {
        let d = h2p - h1p;
        if d.abs() <= 180.0 {
            d
        } else if d > 180.0 {
            d - 360.0
        } else {
            d + 360.0
        }
    };
    let dhh = 2.0 * (c1p * c2p).sqrt() * (dhp.to_radians() / 2.0).sin();
    let lpm = (l1 + l2) / 2.0;
    let cpm = (c1p + c2p) / 2.0;
    let hpm = if c1p * c2p == 0.0 {
        h1p + h2p
    } else if (h1p - h2p).abs() <= 180.0 {
        (h1p + h2p) / 2.0
    } else if h1p + h2p < 360.0 {
        (h1p + h2p + 360.0) / 2.0
    } else {
        (h1p + h2p - 360.0) / 2.0
    };
    let t = 1.0 - 0.17 * (hpm - 30.0).to_radians().cos() + 0.24 * (2.0 * hpm).to_radians().cos()
        + 0.32 * (3.0 * hpm + 6.0).to_radians().cos()
        - 0.20 * (4.0 * hpm - 63.0).to_radians().cos();
    let dtheta = 30.0 * (-((hpm - 275.0) / 25.0).powi(2)).exp();
    let cpm7 = cpm.powi(7);
    let rc = 2.0 * (cpm7 / (cpm7 + 25f64.powi(7))).sqrt();
    let lm50 = (lpm - 50.0) * (lpm - 50.0);
    let sl = 1.0 + 0.015 * lm50 / (20.0 + lm50).sqrt();
    let sc = 1.0 + 0.045 * cpm;
    let sh = 1.0 + 0.015 * cpm * t;
    let rt = -(2.0 * dtheta).to_radians().sin() * rc;
    let v = (dlp / sl).powi(2) + (dcp / sc).powi(2) + (dhh / sh).powi(2) + rt * (dcp / sc) * (dhh / sh);
    v.max(0.0).sqrt() as f32
}

/// A small deterministic generator (xorshift64*), so every run picks the same centres.
pub struct Rng(pub u64);

impl Rng {
    pub fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }
    pub fn unit(&mut self) -> f64 {
        (self.next() >> 11) as f64 / (1u64 << 53) as f64
    }
}

/// k-means++ in Lab with a fixed seed. Returns the centres (k or fewer when the data has fewer
/// distinct colours).
pub fn kmeans(pts: &[Lab], k: usize, seed: u64, iters: usize) -> Vec<Lab> {
    if pts.is_empty() || k == 0 {
        return Vec::new();
    }
    let mut rng = Rng(seed | 1);
    let mut centres: Vec<Lab> = Vec::with_capacity(k);
    centres.push(pts[(rng.next() % pts.len() as u64) as usize]);
    let mut d2: Vec<f32> = pts.iter().map(|p| de76sq(*p, centres[0])).collect();
    while centres.len() < k {
        let total: f64 = d2.iter().map(|v| *v as f64).sum();
        if total <= 1e-9 {
            break;
        }
        let mut target = rng.unit() * total;
        let mut pick = pts.len() - 1;
        for (i, v) in d2.iter().enumerate() {
            target -= *v as f64;
            if target <= 0.0 {
                pick = i;
                break;
            }
        }
        let c = pts[pick];
        centres.push(c);
        for (i, p) in pts.iter().enumerate() {
            let v = de76sq(*p, c);
            if v < d2[i] {
                d2[i] = v;
            }
        }
    }
    let mut assign = vec![0usize; pts.len()];
    for _ in 0..iters {
        let mut changed = false;
        for (i, p) in pts.iter().enumerate() {
            let mut best = 0;
            let mut bd = f32::MAX;
            for (j, c) in centres.iter().enumerate() {
                let v = de76sq(*p, *c);
                if v < bd {
                    bd = v;
                    best = j;
                }
            }
            if assign[i] != best {
                assign[i] = best;
                changed = true;
            }
        }
        let mut sum = vec![[0f64; 4]; centres.len()];
        for (i, p) in pts.iter().enumerate() {
            let s = &mut sum[assign[i]];
            s[0] += p[0] as f64;
            s[1] += p[1] as f64;
            s[2] += p[2] as f64;
            s[3] += 1.0;
        }
        for (j, s) in sum.iter().enumerate() {
            if s[3] > 0.0 {
                centres[j] = [(s[0] / s[3]) as f32, (s[1] / s[3]) as f32, (s[2] / s[3]) as f32];
            }
        }
        if !changed {
            break;
        }
    }
    centres
}

/// The Brother (PEC) thread palette: index 1..=63 are threads, 64 is appliqué material.
pub const PEC: [(u8, u8, u8, &str); 64] = [
    (14, 31, 124, "Prussian Blue"),
    (10, 85, 163, "Blue"),
    (0, 135, 119, "Teal Green"),
    (75, 107, 175, "Cornflower Blue"),
    (237, 23, 31, "Red"),
    (209, 92, 0, "Reddish Brown"),
    (145, 54, 151, "Magenta"),
    (228, 154, 203, "Light Lilac"),
    (145, 95, 172, "Lilac"),
    (158, 214, 125, "Mint Green"),
    (232, 169, 0, "Deep Gold"),
    (254, 186, 53, "Orange"),
    (255, 255, 0, "Yellow"),
    (112, 188, 31, "Lime Green"),
    (186, 152, 0, "Brass"),
    (168, 168, 168, "Silver"),
    (125, 111, 0, "Russet Brown"),
    (255, 255, 179, "Cream Brown"),
    (79, 85, 86, "Pewter"),
    (0, 0, 0, "Black"),
    (11, 61, 145, "Ultramarine"),
    (119, 1, 118, "Royal Purple"),
    (41, 49, 51, "Dark Gray"),
    (42, 19, 1, "Dark Brown"),
    (246, 74, 138, "Deep Rose"),
    (178, 118, 36, "Light Brown"),
    (252, 187, 197, "Salmon Pink"),
    (254, 55, 15, "Vermilion"),
    (240, 240, 240, "White"),
    (106, 28, 138, "Violet"),
    (168, 221, 196, "Seacrest"),
    (37, 132, 187, "Sky Blue"),
    (254, 179, 67, "Pumpkin"),
    (255, 243, 107, "Cream Yellow"),
    (208, 166, 96, "Khaki"),
    (209, 84, 0, "Clay Brown"),
    (102, 186, 73, "Leaf Green"),
    (19, 74, 70, "Peacock Blue"),
    (135, 135, 135, "Gray"),
    (216, 204, 198, "Warm Gray"),
    (67, 86, 7, "Dark Olive"),
    (253, 217, 222, "Flesh Pink"),
    (249, 147, 188, "Pink"),
    (0, 56, 34, "Deep Green"),
    (178, 175, 212, "Lavender"),
    (104, 106, 176, "Wisteria Violet"),
    (239, 227, 185, "Beige"),
    (247, 56, 102, "Carmine"),
    (181, 75, 100, "Amber Red"),
    (19, 43, 26, "Olive Green"),
    (199, 1, 86, "Dark Fuchsia"),
    (254, 158, 50, "Tangerine"),
    (168, 222, 235, "Light Blue"),
    (0, 103, 62, "Emerald Green"),
    (78, 41, 144, "Purple"),
    (47, 126, 32, "Moss Green"),
    (255, 204, 204, "Flesh Pink"),
    (255, 217, 17, "Harvest Gold"),
    (9, 91, 166, "Electric Blue"),
    (240, 249, 112, "Lemon Yellow"),
    (227, 243, 91, "Fresh Green"),
    (255, 153, 0, "Orange"),
    (255, 240, 141, "Cream Yellow"),
    (255, 200, 200, "Applique"),
];

/// Number of real threads in the chart (the last palette entry is appliqué material).
pub const CHART: usize = 63;

pub fn pec_rgb(i: usize) -> [u8; 3] {
    let e = PEC[(i.clamp(1, 64)) - 1];
    [e.0, e.1, e.2]
}

pub fn pec_name(i: usize) -> &'static str {
    PEC[(i.clamp(1, 64)) - 1].3
}

/// The chart thread (1..=63) nearest a Lab colour by CIEDE2000.
pub fn nearest_thread(l: Lab) -> usize {
    let mut best = 1;
    let mut bd = f32::MAX;
    for i in 1..=CHART {
        let d = de2000(l, rgb_to_lab(pec_rgb(i)));
        if d < bd {
            bd = d;
            best = i;
        }
    }
    best
}

/// The PEC palette index nearest an RGB colour by pyembroidery's red-mean distance; PEC
/// files carry this index for machines that only read the PEC block.
pub fn nearest_pec_redmean(c: [u8; 3], used: &[bool]) -> Option<usize> {
    let mut best = None;
    let mut bd = i64::MAX;
    for i in 1..=64 {
        if used.get(i).copied().unwrap_or(false) {
            continue;
        }
        let t = pec_rgb(i);
        let rm = ((c[0] as i64 + t[0] as i64) as f64 / 2.0).round() as i64;
        let (r, g, b) = (c[0] as i64 - t[0] as i64, c[1] as i64 - t[1] as i64, c[2] as i64 - t[2] as i64);
        let d = (((512 + rm) * r * r) >> 8) + 4 * g * g + (((767 - rm) * b * b) >> 8);
        if d <= bd {
            bd = d;
            best = Some(i);
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lab_roundtrip() {
        for c in [[0u8, 0, 0], [255, 255, 255], [237, 23, 31], [10, 85, 163]] {
            let back = lab_to_rgb(rgb_to_lab(c));
            for k in 0..3 {
                assert!((back[k] as i32 - c[k] as i32).abs() <= 1, "{:?} {:?}", c, back);
            }
        }
        let w = rgb_to_lab([255, 255, 255]);
        assert!((w[0] - 100.0).abs() < 0.1 && w[1].abs() < 0.2 && w[2].abs() < 0.2);
    }
    #[test]
    fn ciede2000_reference() {
        // Sharma, Wu & Dalal test data, pairs 1 and 7
        let d = de2000([50.0, 2.6772, -79.7751], [50.0, 0.0, -82.7485]);
        assert!((d - 2.0425).abs() < 1e-3, "{d}");
        let d = de2000([50.0, 0.0, 0.0], [50.0, -1.0, 2.0]);
        assert!((d - 2.3669).abs() < 1e-3, "{d}");
    }
    #[test]
    fn threads() {
        assert_eq!(pec_name(nearest_thread(rgb_to_lab([250, 250, 250]))), "White");
        assert_eq!(pec_name(nearest_thread(rgb_to_lab([0, 0, 0]))), "Black");
        assert_eq!(pec_name(nearest_thread(rgb_to_lab([236, 24, 32]))), "Red");
    }
    #[test]
    fn kmeans_finds_clusters() {
        let mut pts = Vec::new();
        for i in 0..300 {
            let j = (i % 7) as f32 * 0.1;
            pts.push([20.0 + j, 0.0, 0.0]);
            pts.push([80.0 - j, 10.0, 10.0]);
        }
        let c = kmeans(&pts, 2, 7, 30);
        assert_eq!(c.len(), 2);
        let lo = c.iter().map(|v| v[0]).fold(f32::MAX, f32::min);
        assert!((lo - 20.3).abs() < 0.5);
    }
}
