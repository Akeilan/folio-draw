//! Windows icons (.ico, and .cur read the same way): reads the largest entry, PNG or DIB
//! (1 to 32 bits, with its AND mask); writes the standard sizes up to the picture's, the
//! picture centred on a square, 256 as PNG and smaller sizes as 32-bit DIBs with a mask.

use crate::png::{self, Image};
use crate::{bmp, doc};

pub fn is_ico(d: &[u8]) -> bool {
    d.len() >= 22 && d[0] == 0 && d[1] == 0 && (d[2] == 1 || d[2] == 2) && d[3] == 0 && u16::from_le_bytes([d[4], d[5]]) > 0
}

fn u32le(d: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}

/// One DIB entry (a BITMAPINFOHEADER with doubled height, the colour rows, then the mask).
fn dib(d: &[u8]) -> Result<Image, String> {
    if d.len() < 40 {
        return Err("ICO: truncated picture".into());
    }
    let hsz = u32le(d, 0) as usize;
    let w = u32le(d, 4) as i32;
    let h2 = u32le(d, 8) as i32;
    let bpp = u16::from_le_bytes([d[14], d[15]]) as usize;
    let clrused = u32le(d, 32) as usize;
    if w <= 0 || h2 == 0 || w > 4096 || hsz < 40 || hsz > d.len() {
        return Err("ICO: bad picture header".into());
    }
    let w = w as usize;
    let h = (h2.unsigned_abs() / 2).max(1) as usize;
    let pal = if bpp <= 8 { if clrused > 0 { clrused.min(256) } else { 1 << bpp } } else { 0 };
    // as a BMP file: a file header, the header with the real height, then the rest
    let mut b = Vec::with_capacity(d.len() + 14);
    b.extend_from_slice(b"BM");
    b.extend_from_slice(&((d.len() + 14) as u32).to_le_bytes());
    b.extend_from_slice(&[0; 4]);
    b.extend_from_slice(&((14 + hsz + pal * 4) as u32).to_le_bytes());
    b.extend_from_slice(d);
    b[14 + 8..14 + 12].copy_from_slice(&(h as i32).to_le_bytes());
    let mut img = bmp::decode(&b)?;
    let xor_stride = ((w * bpp + 31) / 32) * 4;
    let mask_at = hsz + pal * 4 + xor_stride * h;
    let mask_stride = ((w + 31) / 32) * 4;
    let use_mask = bpp < 32 || img.px.chunks_exact(4).all(|p| p[3] == 255);
    if use_mask && d.len() >= mask_at + mask_stride * h {
        for y in 0..h {
            let row = &d[mask_at + (h - 1 - y) * mask_stride..];
            for x in 0..w {
                if row[x / 8] & (0x80 >> (x % 8)) != 0 {
                    img.px[(y * w + x) * 4 + 3] = 0;
                }
            }
        }
    }
    Ok(img)
}

pub fn decode(d: &[u8]) -> Result<Image, String> {
    if !is_ico(d) {
        return Err("not an icon file".into());
    }
    let n = u16::from_le_bytes([d[4], d[5]]) as usize;
    // the largest entry, the deepest when sizes tie
    let mut best: Option<(usize, usize, usize, usize)> = None; // (area, bits, offset, size)
    for i in 0..n {
        let e = 6 + i * 16;
        if e + 16 > d.len() {
            break;
        }
        let w = if d[e] == 0 { 256 } else { d[e] as usize };
        let h = if d[e + 1] == 0 { 256 } else { d[e + 1] as usize };
        let bits = u16::from_le_bytes([d[e + 6], d[e + 7]]) as usize;
        let size = u32le(d, e + 8) as usize;
        let off = u32le(d, e + 12) as usize;
        if off >= d.len() {
            continue;
        }
        // a PNG entry may be larger than its 8-bit directory size says
        let (w, h) = if d.len() >= off + 24 && png::is_png(&d[off..]) {
            (u32::from_be_bytes([d[off + 16], d[off + 17], d[off + 18], d[off + 19]]) as usize, u32::from_be_bytes([d[off + 20], d[off + 21], d[off + 22], d[off + 23]]) as usize)
        } else {
            (w, h)
        };
        let key = (w * h, bits, off, size);
        if best.map_or(true, |b| (key.0, key.1) > (b.0, b.1)) {
            best = Some(key);
        }
    }
    let (_, _, off, size) = best.ok_or("ICO: no pictures")?;
    let body = &d[off..off.saturating_add(size).min(d.len())];
    if png::is_png(body) {
        png::decode(body)
    } else {
        dib(body)
    }
}

/// The sizes an icon of a w x h picture carries.
fn sizes(w: usize, h: usize) -> Vec<usize> {
    let side = w.max(h);
    let v: Vec<usize> = [16, 24, 32, 48, 64, 128, 256].into_iter().filter(|&s| s <= side).collect();
    if v.is_empty() { vec![side.max(1)] } else { v }
}

pub fn encode(w: usize, h: usize, rgba: &[u8]) -> Vec<u8> {
    // centre on a transparent square first, so nothing is stretched
    let side = w.max(h);
    let mut sq = vec![0u8; side * side * 4];
    let (ox, oy) = ((side - w) / 2, (side - h) / 2);
    for y in 0..h {
        let s = y * w * 4;
        let d = ((oy + y) * side + ox) * 4;
        sq[d..d + w * 4].copy_from_slice(&rgba[s..s + w * 4]);
    }
    let sizes = sizes(w, h);
    let mut bodies = Vec::new();
    for &s in &sizes {
        let px = if s == side { sq.clone() } else { doc::resample(&sq, side, side, s, s, true) };
        if s >= 256 {
            bodies.push(png::encode(s, s, &px, 9));
            continue;
        }
        let mask_stride = ((s + 31) / 32) * 4;
        let mut b = Vec::with_capacity(40 + s * s * 4 + mask_stride * s);
        b.extend_from_slice(&40u32.to_le_bytes());
        b.extend_from_slice(&(s as i32).to_le_bytes());
        b.extend_from_slice(&(2 * s as i32).to_le_bytes());
        b.extend_from_slice(&1u16.to_le_bytes());
        b.extend_from_slice(&32u16.to_le_bytes());
        b.extend_from_slice(&0u32.to_le_bytes());
        b.extend_from_slice(&((s * s * 4 + mask_stride * s) as u32).to_le_bytes());
        b.extend_from_slice(&[0; 16]);
        for y in (0..s).rev() {
            for x in 0..s {
                let p = &px[(y * s + x) * 4..(y * s + x) * 4 + 4];
                b.extend_from_slice(&[p[2], p[1], p[0], p[3]]);
            }
        }
        for y in (0..s).rev() {
            let mut row = vec![0u8; mask_stride];
            for x in 0..s {
                if px[(y * s + x) * 4 + 3] == 0 {
                    row[x / 8] |= 0x80 >> (x % 8);
                }
            }
            b.extend_from_slice(&row);
        }
        bodies.push(b);
    }
    let mut out = vec![0, 0, 1, 0];
    out.extend_from_slice(&(sizes.len() as u16).to_le_bytes());
    let mut off = 6 + 16 * sizes.len();
    for (&s, b) in sizes.iter().zip(&bodies) {
        let d = if s >= 256 { 0 } else { s as u8 };
        out.extend_from_slice(&[d, d, 0, 0]);
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&32u16.to_le_bytes());
        out.extend_from_slice(&(b.len() as u32).to_le_bytes());
        out.extend_from_slice(&(off as u32).to_le_bytes());
        off += b.len();
    }
    for b in &bodies {
        out.extend_from_slice(b);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip() {
        let (w, h) = (40, 30);
        let mut px = Vec::new();
        for y in 0..h {
            for x in 0..w {
                px.extend_from_slice(&[(x * 6) as u8, (y * 8) as u8, 90, if x < 5 { 0 } else { 255 }]);
            }
        }
        let f = encode(w, h, &px);
        // 16, 24 and 32; the largest (32) comes back, centred on a 40 x 40 square scaled down
        assert_eq!(u16::from_le_bytes([f[4], f[5]]), 3);
        let img = decode(&f).unwrap();
        assert_eq!((img.w, img.h), (32, 32));
        assert_eq!(img.px[3], 0); // the padding above the picture
        // an exact-size icon keeps its pixels
        let img = decode(&encode(16, 16, &px[..16 * 16 * 4])).unwrap();
        assert_eq!(img.px, px[..16 * 16 * 4].to_vec());
    }

    #[test]
    fn big_is_png() {
        let px = vec![200u8; 300 * 300 * 4];
        let f = encode(300, 300, &px);
        let n = u16::from_le_bytes([f[4], f[5]]) as usize;
        assert_eq!(n, 7);
        let e = 6 + 6 * 16;
        let off = u32le(&f, e + 12) as usize;
        assert!(png::is_png(&f[off..]));
        let img = decode(&f).unwrap();
        assert_eq!((img.w, img.h), (256, 256));
    }
}
