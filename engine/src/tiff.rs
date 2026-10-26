//! TIFF: reads baseline images (either byte order; uncompressed, LZW, PackBits or Deflate;
//! the horizontal predictor; grey, RGB, palette, CMYK; 1 to 16 bits; strips or tiles; chunky
//! or planar; associated or unassociated alpha; the Orientation tag), the first page only.
//! Writes 8-bit RGB or RGBA, LZW with the horizontal predictor.

use crate::deflate;
use crate::png::Image;

const MAX_PIXELS: usize = 100_000_000;

pub fn is_tiff(d: &[u8]) -> bool {
    d.len() >= 8 && (&d[..4] == b"II*\0" || &d[..4] == b"MM\0*")
}

struct R<'a> {
    d: &'a [u8],
    be: bool,
}

impl R<'_> {
    fn u16(&self, o: usize) -> Option<u16> {
        let b = self.d.get(o..o + 2)?;
        Some(if self.be { u16::from_be_bytes([b[0], b[1]]) } else { u16::from_le_bytes([b[0], b[1]]) })
    }
    fn u32(&self, o: usize) -> Option<u32> {
        let b = self.d.get(o..o + 4)?;
        let a = [b[0], b[1], b[2], b[3]];
        Some(if self.be { u32::from_be_bytes(a) } else { u32::from_le_bytes(a) })
    }
}

/// The values of one IFD entry, as integers.
fn values(r: &R, e: usize) -> Option<Vec<u32>> {
    let typ = r.u16(e + 2)?;
    let n = r.u32(e + 4)? as usize;
    let size = match typ {
        1 | 2 | 6 | 7 => 1,
        3 | 8 => 2,
        4 | 9 => 4,
        5 | 10 => 8,
        _ => return None,
    };
    if n > 1 << 24 {
        return None;
    }
    let off = if n * size <= 4 { e + 8 } else { r.u32(e + 8)? as usize };
    let mut v = Vec::with_capacity(n);
    for i in 0..n {
        let o = off + i * size;
        v.push(match size {
            1 => *r.d.get(o)? as u32,
            2 => r.u16(o)? as u32,
            4 => r.u32(o)?,
            _ => {
                // a rational: the integer part is enough here
                let (a, b) = (r.u32(o)?, r.u32(o + 4)?);
                if b == 0 { 0 } else { a / b }
            }
        });
    }
    Some(v)
}

// ------------------------------------------------------------------ decompression

fn lzw_decode(src: &[u8], want: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(want);
    // old-style (pre-6.0) LZW wrote codes least-significant bit first
    let lsb = src.len() >= 2 && src[0] == 0 && src[1] & 1 == 1;
    let mut table: Vec<(u32, u8, u16)> = Vec::with_capacity(4096); // (prefix, last byte, length)
    let reset = |t: &mut Vec<(u32, u8, u16)>| {
        t.clear();
        for i in 0..256u32 {
            t.push((u32::MAX, i as u8, 1));
        }
        t.push((u32::MAX, 0, 0));
        t.push((u32::MAX, 0, 0));
    };
    reset(&mut table);
    let mut width = 9u32;
    let mut acc: u64 = 0;
    let mut nbits = 0u32;
    let mut pos = 0usize;
    let mut prev: Option<u32> = None;
    let mut buf = Vec::new();
    let emit = |table: &Vec<(u32, u8, u16)>, code: u32, buf: &mut Vec<u8>| {
        buf.clear();
        let mut c = code;
        while c != u32::MAX {
            let (p, b, _) = table[c as usize];
            buf.push(b);
            c = p;
        }
        buf.reverse();
    };
    loop {
        while nbits < width {
            if pos >= src.len() {
                return out;
            }
            if lsb {
                acc |= (src[pos] as u64) << nbits;
            } else {
                acc = (acc << 8) | src[pos] as u64;
            }
            pos += 1;
            nbits += 8;
        }
        let code = if lsb {
            let c = (acc & ((1 << width) - 1)) as u32;
            acc >>= width;
            c
        } else {
            ((acc >> (nbits - width)) & ((1 << width) - 1)) as u32
        };
        nbits -= width;
        if code == 257 || out.len() >= want {
            break;
        }
        if code == 256 {
            reset(&mut table);
            width = 9;
            prev = None;
            continue;
        }
        match prev {
            None => {
                if code as usize >= table.len() {
                    break;
                }
                emit(&table, code, &mut buf);
            }
            Some(p) => {
                if (code as usize) < table.len() {
                    emit(&table, code, &mut buf);
                    if table.len() < 4096 {
                        let l = table[p as usize].2 + 1;
                        table.push((p, buf[0], l));
                    }
                } else if code as usize == table.len() {
                    emit(&table, p, &mut buf);
                    let f = buf[0];
                    buf.push(f);
                    if table.len() < 4096 {
                        let l = table[p as usize].2 + 1;
                        table.push((p, f, l));
                    }
                } else {
                    break;
                }
            }
        }
        out.extend_from_slice(&buf);
        prev = Some(code);
        // "early change": the width grows one code before the table fills it (the old LSB
        // form did not)
        let n = table.len() + if lsb { 0 } else { 1 };
        width = if n >= 2048 { 12 } else if n >= 1024 { 11 } else if n >= 512 { 10 } else { 9 };
    }
    out
}

fn packbits_decode(src: &[u8], want: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(want);
    let mut i = 0;
    while i < src.len() && out.len() < want {
        let n = src[i] as i8;
        i += 1;
        if n >= 0 {
            let k = n as usize + 1;
            let e = (i + k).min(src.len());
            out.extend_from_slice(&src[i..e]);
            i = e;
        } else if n != -128 {
            if i < src.len() {
                let k = (1 - n as isize) as usize;
                out.extend(std::iter::repeat(src[i]).take(k));
                i += 1;
            }
        }
    }
    out
}

// ------------------------------------------------------------------ decode

pub fn decode(d: &[u8]) -> Result<Image, String> {
    if !is_tiff(d) {
        return Err("not a TIFF file".into());
    }
    let r = R { d, be: d[0] == b'M' };
    let ifd = r.u32(4).ok_or("TIFF: truncated")? as usize;
    let n = r.u16(ifd).ok_or("TIFF: bad directory")? as usize;
    let mut tags: std::collections::HashMap<u16, Vec<u32>> = Default::default();
    for i in 0..n {
        let e = ifd + 2 + i * 12;
        let Some(tag) = r.u16(e) else { break };
        if let Some(v) = values(&r, e) {
            tags.insert(tag, v);
        }
    }
    let one = |t: u16, def: u32| tags.get(&t).and_then(|v| v.first().copied()).unwrap_or(def);
    let w = one(256, 0) as usize;
    let h = one(257, 0) as usize;
    if w == 0 || h == 0 {
        return Err("TIFF: no picture size".into());
    }
    if w * h > MAX_PIXELS {
        return Err("TIFF: picture too large".into());
    }
    let spp = one(277, 1) as usize;
    let bps = one(258, 1) as usize;
    let comp = one(259, 1);
    let photo = one(262, if spp >= 3 { 2 } else { 1 });
    let planar = one(284, 1) == 2 && spp > 1;
    let predictor = one(317, 1);
    let fill_lsb = one(266, 1) == 2;
    let sample_fmt = one(339, 1);
    if !matches!(bps, 1 | 2 | 4 | 8 | 16) {
        return Err(format!("TIFF: {bps}-bit samples are not supported"));
    }
    if sample_fmt == 3 {
        return Err("TIFF: floating-point samples are not supported".into());
    }
    if spp == 0 || spp > 8 {
        return Err("TIFF: unsupported sample count".into());
    }
    match comp {
        1 | 5 | 8 | 32946 | 32773 => {}
        6 | 7 => return Err("TIFF: JPEG-compressed TIFF is not supported".into()),
        _ => return Err(format!("TIFF: compression {comp} is not supported")),
    }
    if photo == 6 {
        return Err("TIFF: YCbCr TIFF is not supported".into());
    }
    // chunks (strips or tiles)
    let tiled = tags.contains_key(&322);
    let (cw, ch) = if tiled {
        (one(322, 0) as usize, one(323, 0) as usize)
    } else {
        (w, (one(278, h as u32) as usize).clamp(1, h))
    };
    if cw == 0 || ch == 0 {
        return Err("TIFF: bad tile size".into());
    }
    let offs = tags.get(&if tiled { 324 } else { 273 }).cloned().ok_or("TIFF: no image data")?;
    let counts = tags.get(&if tiled { 325 } else { 279 }).cloned().unwrap_or_default();
    let across = (w + cw - 1) / cw;
    let down = (h + ch - 1) / ch;
    let per_plane = across * down;
    let planes = if planar { spp } else { 1 };
    let chunk_spp = if planar { 1 } else { spp };
    let row_bytes = (cw * chunk_spp * bps + 7) / 8;
    // samples, widened to 16 bits, chunky
    let mut s = vec![0u16; w * h * spp];
    let max = ((1u32 << bps) - 1) as u16;
    for pl in 0..planes {
        for cy in 0..down {
            for cx in 0..across {
                let k = pl * per_plane + cy * across + cx;
                let Some(&off) = offs.get(k) else { continue };
                let off = off as usize;
                let cnt = counts.get(k).map(|&c| c as usize).unwrap_or(d.len().saturating_sub(off));
                let end = off.saturating_add(cnt).min(d.len());
                if off >= end {
                    continue;
                }
                let mut src: Vec<u8> = d[off..end].to_vec();
                if fill_lsb {
                    for b in src.iter_mut() {
                        *b = b.reverse_bits();
                    }
                }
                let want = row_bytes * ch;
                let mut raw = match comp {
                    1 => src,
                    5 => lzw_decode(&src, want),
                    32773 => packbits_decode(&src, want),
                    _ => deflate::zlib_decompress_sized(&src, want).or_else(|_| deflate::inflate_sized(&src, want)).unwrap_or_default(),
                };
                raw.resize(want, 0);
                // undo the horizontal predictor
                if predictor == 2 {
                    for row in raw.chunks_exact_mut(row_bytes) {
                        if bps == 8 {
                            for i in chunk_spp..cw * chunk_spp {
                                row[i] = row[i].wrapping_add(row[i - chunk_spp]);
                            }
                        } else if bps == 16 {
                            let g = |row: &[u8], i: usize| if r.be { u16::from_be_bytes([row[2 * i], row[2 * i + 1]]) } else { u16::from_le_bytes([row[2 * i], row[2 * i + 1]]) };
                            for i in chunk_spp..cw * chunk_spp {
                                let v = g(row, i).wrapping_add(g(row, i - chunk_spp));
                                let b = if r.be { v.to_be_bytes() } else { v.to_le_bytes() };
                                row[2 * i] = b[0];
                                row[2 * i + 1] = b[1];
                            }
                        }
                    }
                }
                for y in 0..ch {
                    let iy = cy * ch + y;
                    if iy >= h {
                        break;
                    }
                    let row = &raw[y * row_bytes..(y + 1) * row_bytes];
                    for x in 0..cw {
                        let ix = cx * cw + x;
                        if ix >= w {
                            break;
                        }
                        for c in 0..chunk_spp {
                            let i = x * chunk_spp + c;
                            let v = match bps {
                                8 => row[i] as u16,
                                16 => {
                                    if r.be { u16::from_be_bytes([row[2 * i], row[2 * i + 1]]) } else { u16::from_le_bytes([row[2 * i], row[2 * i + 1]]) }
                                }
                                _ => {
                                    let bit = i * bps;
                                    ((row[bit / 8] >> (8 - bps - bit % 8)) as u16) & max
                                }
                            };
                            let ch_i = if planar { pl } else { c };
                            s[(iy * w + ix) * spp + ch_i] = v;
                        }
                    }
                }
            }
        }
    }
    // to RGBA8
    let to8 = |v: u16| -> u8 {
        match bps {
            16 => (v >> 8) as u8,
            8 => v as u8,
            _ => ((v as u32 * 255 + max as u32 / 2) / max as u32) as u8,
        }
    };
    let extra = tags.get(&338).and_then(|v| v.first().copied());
    let colour_n = match photo {
        0 | 1 | 3 | 4 => 1,
        5 => 4,
        _ => 3,
    };
    let has_alpha = spp > colour_n && extra.map_or(spp == colour_n + 1 && colour_n != 4, |e| e == 1 || e == 2);
    let premult = extra == Some(1);
    let pal = tags.get(&320);
    let mut px = vec![0u8; w * h * 4];
    for i in 0..w * h {
        let p = &s[i * spp..i * spp + spp];
        let mut o = match photo {
            0 => {
                let g = 255 - to8(p[0]);
                [g, g, g, 255]
            }
            1 | 4 => {
                let g = to8(p[0]);
                [g, g, g, 255]
            }
            3 => {
                let n = 1usize << bps;
                let k = p[0] as usize;
                match pal {
                    Some(pl) if pl.len() >= 3 * n && k < n => [(pl[k] >> 8) as u8, (pl[n + k] >> 8) as u8, (pl[2 * n + k] >> 8) as u8, 255],
                    _ => [0, 0, 0, 255],
                }
            }
            5 => {
                let k = 255 - to8(p[3.min(spp - 1)]) as u32;
                let f = |c: u16| ((255 - to8(c) as u32) * k / 255) as u8;
                [f(p[0]), f(p[1.min(spp - 1)]), f(p[2.min(spp - 1)]), 255]
            }
            _ => {
                let g = |c: usize| to8(p[c.min(spp - 1)]);
                [g(0), g(1), g(2), 255]
            }
        };
        if has_alpha {
            let a = to8(p[colour_n]);
            o[3] = a;
            if premult && a > 0 && a < 255 {
                for c in 0..3 {
                    o[c] = ((o[c] as u32 * 255 + a as u32 / 2) / a as u32).min(255) as u8;
                }
            }
        }
        px[i * 4..i * 4 + 4].copy_from_slice(&o);
    }
    let (w, h, px) = orient(w, h, px, one(274, 1));
    Ok(Image { w, h, px })
}

/// Apply the Orientation tag so the picture shows the right way up.
fn orient(w: usize, h: usize, px: Vec<u8>, o: u32) -> (usize, usize, Vec<u8>) {
    if !(2..=8).contains(&o) {
        return (w, h, px);
    }
    let swap = o >= 5;
    let (nw, nh) = if swap { (h, w) } else { (w, h) };
    let mut out = vec![0u8; px.len()];
    for y in 0..h {
        for x in 0..w {
            // where stored pixel (x, y) lands
            let (dx, dy) = match o {
                2 => (w - 1 - x, y),
                3 => (w - 1 - x, h - 1 - y),
                4 => (x, h - 1 - y),
                5 => (y, x),
                6 => (h - 1 - y, x),
                7 => (h - 1 - y, w - 1 - x),
                _ => (y, w - 1 - x),
            };
            let s = (y * w + x) * 4;
            let d = (dy * nw + dx) * 4;
            out[d..d + 4].copy_from_slice(&px[s..s + 4]);
        }
    }
    (nw, nh, out)
}

// ------------------------------------------------------------------ encode

fn lzw_encode(src: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(src.len() / 2);
    let mut acc: u64 = 0;
    let mut nbits = 0u32;
    let mut put = |out: &mut Vec<u8>, code: u32, width: u32| {
        acc = (acc << width) | code as u64;
        nbits += width;
        while nbits >= 8 {
            out.push((acc >> (nbits - 8)) as u8);
            nbits -= 8;
        }
    };
    // the table: (prefix code, byte) -> code
    let mut dict: std::collections::HashMap<(u32, u8), u32> = std::collections::HashMap::with_capacity(4096);
    let mut next = 258u32;
    let mut width = 9u32;
    put(&mut out, 256, width);
    let mut cur: Option<u32> = None;
    for &b in src {
        match cur {
            None => cur = Some(b as u32),
            Some(c) => {
                if let Some(&k) = dict.get(&(c, b)) {
                    cur = Some(k);
                } else {
                    put(&mut out, c, width);
                    dict.insert((c, b), next);
                    next += 1;
                    if next == 4095 {
                        // table full: start over
                        put(&mut out, 256, width);
                        dict.clear();
                        next = 258;
                        width = 9;
                    } else if next >= 1 << width {
                        width += 1;
                    }
                    cur = Some(b as u32);
                }
            }
        }
    }
    if let Some(c) = cur {
        put(&mut out, c, width);
        next += 1;
        if next >= 1 << width && width < 12 {
            width += 1;
        }
    }
    put(&mut out, 257, width);
    if nbits > 0 {
        out.push((acc << (8 - nbits)) as u8);
    }
    out
}

/// RGBA as an 8-bit RGB (or RGBA when any pixel is not opaque) TIFF, LZW with prediction.
pub fn encode(w: usize, h: usize, rgba: &[u8]) -> Vec<u8> {
    let alpha = rgba.chunks_exact(4).any(|p| p[3] != 255);
    let spp = if alpha { 4 } else { 3 };
    let row = w * spp;
    let rows_per = (65536 / row.max(1)).clamp(1, h);
    let mut strips = Vec::new();
    let mut y = 0;
    while y < h {
        let n = rows_per.min(h - y);
        let mut raw = Vec::with_capacity(n * row);
        for yy in y..y + n {
            let start = raw.len();
            for x in 0..w {
                let p = &rgba[(yy * w + x) * 4..(yy * w + x) * 4 + 4];
                raw.extend_from_slice(&p[..spp]);
            }
            for i in (spp..row).rev() {
                raw[start + i] = raw[start + i].wrapping_sub(raw[start + i - spp]);
            }
        }
        strips.push(lzw_encode(&raw));
        y += n;
    }
    // layout: header, strips, then the directory and its out-of-line values
    let mut out = b"II*\0\0\0\0\0".to_vec();
    let mut offsets = Vec::new();
    for s in &strips {
        offsets.push(out.len() as u32);
        out.extend_from_slice(s);
        if out.len() & 1 == 1 {
            out.push(0);
        }
    }
    let mut entries: Vec<(u16, u16, Vec<u32>)> = vec![
        (256, 4, vec![w as u32]),
        (257, 4, vec![h as u32]),
        (258, 3, vec![8; spp]),
        (259, 3, vec![5]),
        (262, 3, vec![2]),
        (273, 4, offsets),
        (274, 3, vec![1]),
        (277, 3, vec![spp as u32]),
        (278, 4, vec![rows_per as u32]),
        (279, 4, strips.iter().map(|s| s.len() as u32).collect()),
        (282, 5, vec![72, 1]),
        (283, 5, vec![72, 1]),
        (284, 3, vec![1]),
        (296, 3, vec![2]),
        (317, 3, vec![2]),
    ];
    if alpha {
        entries.push((338, 3, vec![2]));
    }
    let ifd = out.len();
    out[4..8].copy_from_slice(&(ifd as u32).to_le_bytes());
    let mut extra_at = ifd + 2 + entries.len() * 12 + 4;
    let mut extra = Vec::new();
    out.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    for (tag, typ, vals) in &entries {
        // rationals are stored as numerator/denominator pairs
        let (count, bytes): (usize, Vec<u8>) = match typ {
            3 => (vals.len(), vals.iter().flat_map(|v| (*v as u16).to_le_bytes()).collect()),
            5 => (vals.len() / 2, vals.iter().flat_map(|v| v.to_le_bytes()).collect()),
            _ => (vals.len(), vals.iter().flat_map(|v| v.to_le_bytes()).collect()),
        };
        out.extend_from_slice(&tag.to_le_bytes());
        out.extend_from_slice(&typ.to_le_bytes());
        out.extend_from_slice(&(count as u32).to_le_bytes());
        if bytes.len() <= 4 {
            let mut b = bytes.clone();
            b.resize(4, 0);
            out.extend_from_slice(&b);
        } else {
            out.extend_from_slice(&(extra_at as u32).to_le_bytes());
            extra_at += bytes.len() + (bytes.len() & 1);
            extra.extend_from_slice(&bytes);
            if bytes.len() & 1 == 1 {
                extra.push(0);
            }
        }
    }
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&extra);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lzw_round_trip() {
        let mut v = Vec::new();
        for i in 0..200_000u32 {
            v.push(((i * 7) % 13 + (i / 1000) % 5) as u8);
        }
        assert_eq!(lzw_decode(&lzw_encode(&v), v.len()), v);
        let r: Vec<u8> = (0..70_000u32).map(|i| (i.wrapping_mul(2654435761) >> 13) as u8).collect();
        assert_eq!(lzw_decode(&lzw_encode(&r), r.len()), r);
        assert_eq!(lzw_decode(&lzw_encode(&[]), 0), Vec::<u8>::new());
    }

    #[test]
    fn round_trip() {
        let (w, h) = (300, 257);
        for alpha in [false, true] {
            let mut px = Vec::new();
            for y in 0..h {
                for x in 0..w {
                    px.extend_from_slice(&[(x ^ y) as u8, (x * 3) as u8, (y * 5) as u8, if alpha { (x + y) as u8 } else { 255 }]);
                }
            }
            let img = decode(&encode(w, h, &px)).unwrap();
            assert_eq!((img.w, img.h), (w, h));
            assert!(img.px == px, "alpha {alpha}");
        }
    }

    #[test]
    fn packbits() {
        assert_eq!(packbits_decode(&[0xfe, 0xaa, 0x02, 1, 2, 3, 0x80, 0xff, 9], 7), vec![0xaa, 0xaa, 0xaa, 1, 2, 3, 9, 9]);
    }

    #[test]
    fn orientation() {
        // 2x1: red, green; rotated 90 degrees clockwise (6) becomes 1x2, red on top
        let px = vec![255, 0, 0, 255, 0, 255, 0, 255];
        let (w, h, o) = orient(2, 1, px, 6);
        assert_eq!((w, h), (1, 2));
        assert_eq!(&o[..4], &[255, 0, 0, 255]);
    }
}
