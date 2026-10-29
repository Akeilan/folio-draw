//! Photoshop documents (.psd, and the large-document .psb): read with their layers.
//!
//! Pixel layers come in with their names, opacity, visibility, blend mode, layer masks and clipping;
//! layers inside groups come in flat, hidden when their group is hidden and faded by the group's opacity.
//! Bitmap, greyscale, indexed, RGB, CMYK and Lab; 8, 16 and 32 bits; raw, RLE and ZIP data.
//! Layers with no pixels of their own (adjustment and fill layers) can't be kept as layers; when a file
//! has them, the picture Photoshop saved with the file is opened instead, so it looks as it did.

use crate::deflate::zlib_decompress_sized;
use crate::doc::*;

pub fn is_psd(data: &[u8]) -> bool {
    data.len() >= 26 && &data[..4] == b"8BPS" && matches!(be16(data, 4), 1 | 2)
}

fn be16(d: &[u8], o: usize) -> u16 {
    u16::from_be_bytes([d[o], d[o + 1]])
}
fn be32(d: &[u8], o: usize) -> u32 {
    u32::from_be_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}

struct R<'a> {
    d: &'a [u8],
    p: usize,
    big: bool,
}

impl<'a> R<'a> {
    fn need(&self, n: usize) -> Result<(), String> {
        if self.p.checked_add(n).map_or(true, |e| e > self.d.len()) {
            Err("Photoshop file: it ends too soon".into())
        } else {
            Ok(())
        }
    }
    fn u8(&mut self) -> Result<u8, String> {
        self.need(1)?;
        self.p += 1;
        Ok(self.d[self.p - 1])
    }
    fn u16(&mut self) -> Result<u16, String> {
        self.need(2)?;
        self.p += 2;
        Ok(be16(self.d, self.p - 2))
    }
    fn u32(&mut self) -> Result<u32, String> {
        self.need(4)?;
        self.p += 4;
        Ok(be32(self.d, self.p - 4))
    }
    fn i32(&mut self) -> Result<i32, String> {
        Ok(self.u32()? as i32)
    }
    /// A length that is 8 bytes in a .psb.
    fn len(&mut self) -> Result<usize, String> {
        if self.big {
            let hi = self.u32()? as u64;
            let lo = self.u32()? as u64;
            Ok(((hi << 32) | lo) as usize)
        } else {
            Ok(self.u32()? as usize)
        }
    }
    fn bytes(&mut self, n: usize) -> Result<&'a [u8], String> {
        self.need(n)?;
        self.p += n;
        Ok(&self.d[self.p - n..self.p])
    }
}

struct Head {
    channels: usize,
    mode: u16,
    palette: Vec<u8>,
}

/// One channel's samples, decoded to 8 bits: w×h bytes.
fn decode_channel(r: &mut R, comp: u16, w: usize, h: usize, depth: usize, counts: Option<&[usize]>) -> Result<Vec<u8>, String> {
    let row_bytes = (w * depth + 7) / 8;
    let raw: Vec<u8> = match comp {
        0 => r.bytes(row_bytes * h)?.to_vec(),
        1 => {
            let mut out = Vec::with_capacity(row_bytes * h);
            for y in 0..h {
                let n = counts.map(|c| c[y]).unwrap_or(0);
                let src = r.bytes(n)?;
                let start = out.len();
                packbits(src, &mut out, row_bytes);
                out.resize(start + row_bytes, 0);
            }
            out
        }
        2 | 3 => {
            let n = counts.and_then(|c| c.first().copied()).unwrap_or(0);
            let src = r.bytes(n)?;
            let mut v = zlib_decompress_sized(src, row_bytes * h).map_err(|e| format!("Photoshop file: {e}"))?;
            v.resize(row_bytes * h, 0);
            if comp == 3 {
                unpredict(&mut v, w, h, depth);
            }
            v
        }
        _ => return Err("Photoshop file: unknown compression".into()),
    };
    Ok(to8(&raw, w, h, depth))
}

fn packbits(src: &[u8], out: &mut Vec<u8>, limit: usize) {
    let start = out.len();
    let mut i = 0;
    while i < src.len() && out.len() - start < limit {
        let n = src[i] as i8;
        i += 1;
        if n >= 0 {
            let k = (n as usize + 1).min(src.len() - i);
            out.extend_from_slice(&src[i..i + k]);
            i += k;
        } else if n != -128 {
            if i < src.len() {
                let k = 1 - n as isize;
                out.extend(std::iter::repeat(src[i]).take(k as usize));
                i += 1;
            }
        }
    }
}

fn unpredict(v: &mut [u8], w: usize, h: usize, depth: usize) {
    match depth {
        8 => {
            for y in 0..h {
                for x in 1..w {
                    v[y * w + x] = v[y * w + x].wrapping_add(v[y * w + x - 1]);
                }
            }
        }
        16 => {
            for y in 0..h {
                let row = &mut v[y * w * 2..(y + 1) * w * 2];
                for x in 1..w {
                    let a = u16::from_be_bytes([row[x * 2 - 2], row[x * 2 - 1]]);
                    let b = u16::from_be_bytes([row[x * 2], row[x * 2 + 1]]);
                    row[x * 2..x * 2 + 2].copy_from_slice(&a.wrapping_add(b).to_be_bytes());
                }
            }
        }
        32 => {
            // byte-wise delta, then the bytes of each row are stored plane by plane
            for y in 0..h {
                let row = &mut v[y * w * 4..(y + 1) * w * 4];
                for i in 1..row.len() {
                    row[i] = row[i].wrapping_add(row[i - 1]);
                }
                let planes = row.to_vec();
                for x in 0..w {
                    for b in 0..4 {
                        row[x * 4 + b] = planes[b * w + x];
                    }
                }
            }
        }
        _ => {}
    }
}

fn to8(raw: &[u8], w: usize, h: usize, depth: usize) -> Vec<u8> {
    match depth {
        1 => {
            let rb = (w + 7) / 8;
            let mut o = vec![0u8; w * h];
            for y in 0..h {
                for x in 0..w {
                    // bitmap mode: 1 is black
                    o[y * w + x] = if raw[y * rb + x / 8] & (0x80 >> (x % 8)) != 0 { 0 } else { 255 };
                }
            }
            o
        }
        16 => raw.chunks_exact(2).map(|c| c[0]).collect(),
        32 => raw
            .chunks_exact(4)
            .map(|c| {
                let f = f32::from_be_bytes([c[0], c[1], c[2], c[3]]).clamp(0.0, 1.0);
                // 32-bit documents are linear light
                let s = if f <= 0.003_130_8 { f * 12.92 } else { 1.055 * f.powf(1.0 / 2.4) - 0.055 };
                (s * 255.0 + 0.5) as u8
            })
            .collect(),
        _ => raw.to_vec(),
    }
}

/// Interleave decoded channels into straight RGBA. `ch` maps channel id → samples (id -1 is alpha).
fn compose(head: &Head, ch: &[(i16, Vec<u8>)], n: usize, alpha_default: u8) -> Vec<u8> {
    let get = |id: i16| ch.iter().find(|c| c.0 == id).map(|c| &c.1);
    let mut px = vec![0u8; n * 4];
    let a = get(-1);
    for i in 0..n {
        let s = |id: i16| get(id).map_or(0u8, |v| v[i]);
        let (r, g, b) = match head.mode {
            0 | 1 | 8 => (s(0), s(0), s(0)),
            2 => {
                let k = s(0) as usize;
                let p = &head.palette;
                if p.len() >= 768 {
                    (p[k], p[256 + k], p[512 + k])
                } else {
                    (s(0), s(0), s(0))
                }
            }
            4 => {
                // stored with 0 meaning full ink
                let k = s(3) as u32;
                ((s(0) as u32 * k / 255) as u8, (s(1) as u32 * k / 255) as u8, (s(2) as u32 * k / 255) as u8)
            }
            9 => {
                let l = s(0) as f32 / 255.0 * 100.0;
                let aa = s(1) as f32 - 128.0;
                let bb = s(2) as f32 - 128.0;
                let c = crate::emb::colour::lab_to_rgb([l, aa, bb]);
                (c[0], c[1], c[2])
            }
            _ => (s(0), s(1), s(2)),
        };
        let al = a.map_or(alpha_default, |v| v[i]);
        px[i * 4..i * 4 + 4].copy_from_slice(&[r, g, b, al]);
    }
    px
}

fn blend_of(key: &[u8]) -> u8 {
    match key {
        b"mul " => BLEND_MULTIPLY,
        b"scrn" => BLEND_SCREEN,
        b"over" => BLEND_OVERLAY,
        b"dark" => BLEND_DARKEN,
        b"lite" => BLEND_LIGHTEN,
        b"diff" => BLEND_DIFFERENCE,
        b"lddg" => BLEND_ADD,
        _ => BLEND_NORMAL,
    }
}

struct Rec {
    top: i32,
    left: i32,
    bottom: i32,
    right: i32,
    chans: Vec<(i16, usize)>,
    blend: u8,
    opacity: u8,
    clipping: bool,
    hidden: bool,
    name: String,
    divider: u32,
    mask: Option<(i32, i32, i32, i32, u8, bool)>, // top, left, bottom, right, default colour, disabled
    pixels: bool,
}

pub fn load(data: &[u8]) -> Result<Doc, String> {
    if !is_psd(data) {
        return Err("unsupported".into());
    }
    let big = be16(data, 4) == 2;
    let mut r = R { d: data, p: 12, big };
    let channels = r.u16()? as usize;
    let h = r.u32()? as usize;
    let w = r.u32()? as usize;
    let depth = r.u16()? as usize;
    let mode = r.u16()?;
    if w == 0 || h == 0 || w > 32768 || h > 32768 {
        return Err("Photoshop file: the picture is too large (Folio Draw opens up to 32,768 pixels a side)".into());
    }
    if !matches!(depth, 1 | 8 | 16 | 32) {
        return Err("Photoshop file: unsupported bit depth".into());
    }
    if !matches!(mode, 0 | 1 | 2 | 3 | 4 | 7 | 8 | 9) {
        return Err("Photoshop file: unsupported colour mode".into());
    }
    let cm = r.u32()? as usize;
    let palette = r.bytes(cm)?.to_vec();
    let head = Head { channels, mode, palette };
    let ir = r.u32()? as usize;
    r.bytes(ir)?;
    let lm_len = r.len()?;
    let lm_end = r.p + lm_len;
    let mut layers: Vec<(Rec, Vec<u8>)> = Vec::new();
    let mut merged_alpha_first = false;
    if lm_len > 0 {
        let li_len = r.len()?;
        let li_end = r.p + li_len;
        if li_len > 0 {
            let count = r.u16()? as i16;
            merged_alpha_first = count < 0;
            let count = count.unsigned_abs() as usize;
            let mut recs = Vec::with_capacity(count);
            for _ in 0..count {
                recs.push(read_record(&mut r)?);
            }
            for rec in recs {
                let lw = (rec.right - rec.left).max(0) as usize;
                let lh = (rec.bottom - rec.top).max(0) as usize;
                let mut chans: Vec<(i16, Vec<u8>)> = Vec::new();
                for &(id, len) in &rec.chans {
                    let end = r.p + len;
                    let (cw, chh) = if id == -2 {
                        rec.mask.map_or((0, 0), |m| ((m.3 - m.1).max(0) as usize, (m.2 - m.0).max(0) as usize))
                    } else {
                        (lw, lh)
                    };
                    if len >= 2 && cw > 0 && chh > 0 {
                        let comp = r.u16()?;
                        let counts = if comp == 1 {
                            let mut c = Vec::with_capacity(chh);
                            for _ in 0..chh {
                                c.push(if big { r.u32()? as usize } else { r.u16()? as usize });
                            }
                            Some(c)
                        } else if comp >= 2 {
                            Some(vec![len - 2])
                        } else {
                            None
                        };
                        if let Ok(v) = decode_channel(&mut r, comp, cw, chh, depth, counts.as_deref()) {
                            chans.push((id, v));
                        }
                    }
                    r.p = end.min(data.len());
                }
                let mut px = Vec::new();
                if lw > 0 && lh > 0 && rec.pixels {
                    let local = compose(&head, &chans, lw * lh, 255);
                    px = vec![0u8; w * h * 4];
                    let mask = chans.iter().find(|c| c.0 == -2).map(|c| &c.1);
                    for y in 0..lh {
                        let dy = y as i64 + rec.top as i64;
                        if dy < 0 || dy >= h as i64 {
                            continue;
                        }
                        for x in 0..lw {
                            let dx = x as i64 + rec.left as i64;
                            if dx < 0 || dx >= w as i64 {
                                continue;
                            }
                            let s = &local[(y * lw + x) * 4..(y * lw + x) * 4 + 4];
                            let mut a = s[3] as u32;
                            if let (Some(m), Some(mk)) = (rec.mask, mask) {
                                if !m.5 {
                                    let (mx, my) = (dx - m.1 as i64, dy - m.0 as i64);
                                    let mw = (m.3 - m.1) as i64;
                                    let mh = (m.2 - m.0) as i64;
                                    let mv = if mx >= 0 && my >= 0 && mx < mw && my < mh { mk[(my * mw + mx) as usize] } else { m.4 };
                                    a = a * mv as u32 / 255;
                                }
                            }
                            let o = (dy as usize * w + dx as usize) * 4;
                            px[o..o + 4].copy_from_slice(&[s[0], s[1], s[2], a as u8]);
                        }
                    }
                }
                layers.push((rec, px));
            }
        }
        r.p = li_end.min(data.len());
    }
    r.p = lm_end.min(data.len());

    // groups: records run bottom to top; a divider (type 3) opens a group, a folder record (1 or 2) closes it
    let mut doc = Doc::empty(w, h);
    let mut stack: Vec<(bool, f32)> = Vec::new();
    let mut adjustments = false;
    let mut base_alpha: Option<Vec<u8>> = None;
    for (rec, px) in layers.into_iter() {
        match rec.divider {
            3 => {
                stack.push((false, 0.0));
                continue;
            }
            1 | 2 => {
                // the folder record carries the group's own settings: apply them to what it holds
                let op = rec.opacity as f32 / 255.0;
                let pos = doc.layers.len();
                let n_in = group_len(&mut stack).min(pos);
                for l in &mut doc.layers[pos - n_in..pos] {
                    if rec.hidden {
                        l.visible = false;
                    }
                    l.opacity *= op;
                }
                continue;
            }
            _ => {}
        }
        if !rec.pixels || px.is_empty() {
            if !rec.pixels && !rec.hidden {
                adjustments = true;
            }
            continue;
        }
        let mut px = px;
        if rec.clipping {
            if let Some(b) = &base_alpha {
                for i in 0..w * h {
                    px[i * 4 + 3] = (px[i * 4 + 3] as u32 * b[i] as u32 / 255) as u8;
                }
            }
        } else {
            base_alpha = Some(px.chunks_exact(4).map(|p| p[3]).collect());
        }
        let name = if rec.name.trim().is_empty() { format!("Layer {}", doc.layers.len() + 1) } else { rec.name.clone() };
        doc.push_layer(&name, px, rec.opacity as f32 / 255.0, !rec.hidden, rec.blend);
        if let Some(top) = stack.last_mut() {
            top.1 += 1.0;
        }
    }

    // the picture Photoshop saved with the file: every channel one after another
    let merged = (|| -> Result<Vec<u8>, String> {
        let comp = r.u16()?;
        let n = head.channels.max(1);
        let counts = match comp {
            1 => {
                let mut c = Vec::with_capacity(n * h);
                for _ in 0..n * h {
                    c.push(if big { r.u32()? as usize } else { r.u16()? as usize });
                }
                Some(c)
            }
            0 => None,
            _ => Some(vec![data.len() - r.p]),
        };
        let all = decode_channel(&mut r, comp, w, h * n, depth, counts.as_deref())?;
        let chans: Vec<(i16, Vec<u8>)> = (0..n).map(|k| (merged_id(&head, k, merged_alpha_first), all[k * w * h..(k + 1) * w * h].to_vec())).collect();
        Ok(compose(&head, &chans, w * h, 255))
    })();
    if doc.layers.is_empty() || adjustments {
        let px = merged?;
        let mut d = Doc::empty(w, h);
        d.push_layer("Background", px, 1.0, true, BLEND_NORMAL);
        if adjustments && !doc.layers.is_empty() {
            d.note = "psd-adjustments".into();
        }
        return Ok(d);
    }
    doc.active = doc.layers.len() - 1;
    Ok(doc)
}

/// How many layers were added since the innermost open group, closing that group.
fn group_len(stack: &mut Vec<(bool, f32)>) -> usize {
    let n = stack.pop().map_or(0.0, |g| g.1) as usize;
    if let Some(parent) = stack.last_mut() {
        parent.1 += n as f32;
    }
    n
}

fn merged_id(head: &Head, k: usize, alpha: bool) -> i16 {
    let colour = match head.mode {
        0 | 1 | 2 | 8 => 1,
        4 => 4,
        _ => 3,
    };
    if k < colour {
        k as i16
    } else if k == colour && alpha {
        -1
    } else {
        100 + k as i16 // a saved selection, not part of the picture
    }
}

fn read_record(r: &mut R) -> Result<Rec, String> {
    let top = r.i32()?;
    let left = r.i32()?;
    let bottom = r.i32()?;
    let right = r.i32()?;
    let n = r.u16()? as usize;
    let mut chans = Vec::with_capacity(n);
    for _ in 0..n {
        let id = r.u16()? as i16;
        let len = r.len()?;
        chans.push((id, len));
    }
    let sig = r.bytes(4)?;
    if sig != b"8BIM" && sig != b"8B64" {
        return Err("Photoshop file: damaged layer record".into());
    }
    let key = r.bytes(4)?.to_vec();
    let opacity = r.u8()?;
    let clipping = r.u8()? == 1;
    let flags = r.u8()?;
    r.u8()?;
    let extra = r.u32()? as usize;
    let end = r.p + extra;
    // layer mask
    let ml = r.u32()? as usize;
    let mstart = r.p;
    let mut mask = None;
    if ml >= 20 {
        let mt = r.i32()?;
        let mlft = r.i32()?;
        let mb = r.i32()?;
        let mr = r.i32()?;
        let def = r.u8()?;
        let mf = r.u8()?;
        mask = Some((mt, mlft, mb, mr, def, mf & 2 != 0));
    }
    r.p = mstart + ml;
    let br = r.u32()? as usize;
    r.bytes(br)?;
    let nl = r.u8()? as usize;
    let name_bytes = r.bytes(nl)?;
    let mut name: String = name_bytes.iter().map(|&b| b as char).collect();
    let pad = (4 - (nl + 1) % 4) % 4;
    r.bytes(pad.min(end.saturating_sub(r.p)))?;
    let mut divider = 0;
    let mut pixels = true;
    while r.p + 12 <= end {
        let s = r.bytes(4)?;
        if s != b"8BIM" && s != b"8B64" {
            break;
        }
        let k = r.bytes(4)?.to_vec();
        let wide = r.big && matches!(&k[..], b"LMsk" | b"Lr16" | b"Lr32" | b"Layr" | b"Mt16" | b"Mt32" | b"Mtrn" | b"Alph" | b"FMsk" | b"lnk2" | b"FEid" | b"FXid" | b"PxSD");
        let len = if wide { r.len()? } else { r.u32()? as usize };
        let st = r.p;
        let body = r.bytes(len.min(end - st))?;
        match &k[..] {
            b"luni" if body.len() >= 4 => {
                let cnt = be32(body, 0) as usize;
                let u: Vec<u16> = (0..cnt).filter(|i| 4 + i * 2 + 1 < body.len()).map(|i| be16(body, 4 + i * 2)).collect();
                if let Ok(s) = String::from_utf16(&u) {
                    name = s.trim_end_matches('\0').to_string();
                }
            }
            b"lsct" | b"lsdk" if body.len() >= 4 => divider = be32(body, 0),
            b"levl" | b"curv" | b"brit" | b"blnc" | b"hue " | b"hue2" | b"selc" | b"mixr" | b"grdm" | b"thrs" | b"nvrt"
            | b"post" | b"vibA" | b"expA" | b"phfl" | b"clrL" | b"SoCo" | b"GdFl" | b"PtFl" | b"blwh" => pixels = false,
            _ => {}
        }
        r.p = st + len;
    }
    r.p = end;
    Ok(Rec {
        top,
        left,
        bottom,
        right,
        chans,
        blend: blend_of(&key),
        opacity,
        clipping,
        hidden: flags & 2 != 0,
        name,
        divider,
        mask,
        pixels: pixels && divider == 0,
    })
}


// ------------------------------------------------------------------ writing (D3-04)

/// PackBits for one row: repeats of 3+ as runs, the rest literal.
fn rle_row(row: &[u8], o: &mut Vec<u8>) {
    let mut i = 0;
    while i < row.len() {
        let mut j = i + 1;
        while j < row.len() && row[j] == row[i] && j - i < 128 {
            j += 1;
        }
        if j - i >= 3 {
            o.push((1i16 - (j - i) as i16) as i8 as u8);
            o.push(row[i]);
            i = j;
        } else {
            let s = i;
            let mut e = i;
            while e < row.len() && e - s < 128 && !(e + 2 < row.len() && row[e] == row[e + 1] && row[e] == row[e + 2]) {
                e += 1;
            }
            o.push((e - s - 1) as u8);
            o.extend_from_slice(&row[s..e]);
            i = e;
        }
    }
}

/// One channel of a w×h block, RLE: [compression 1][row lengths][rows].
fn rle_channel(get: impl Fn(usize, usize) -> u8, w: usize, h: usize, with_kind: bool) -> (Vec<u8>, Vec<u8>) {
    let mut counts = Vec::with_capacity(h * 2);
    let mut rows = Vec::new();
    let mut row = vec![0u8; w];
    for y in 0..h {
        for (x, v) in row.iter_mut().enumerate() {
            *v = get(x, y);
        }
        let before = rows.len();
        rle_row(&row, &mut rows);
        counts.extend_from_slice(&((rows.len() - before) as u16).to_be_bytes());
    }
    let mut head = Vec::new();
    if with_kind {
        head.extend_from_slice(&1u16.to_be_bytes());
    }
    head.extend_from_slice(&counts);
    (head, rows)
}

fn blend_key(b: u8) -> &'static [u8; 4] {
    match b {
        BLEND_MULTIPLY => b"mul ",
        BLEND_SCREEN => b"scrn",
        BLEND_OVERLAY => b"over",
        BLEND_DARKEN => b"dark",
        BLEND_LIGHTEN => b"lite",
        BLEND_DIFFERENCE => b"diff",
        BLEND_ADD => b"lddg",
        _ => b"norm",
    }
}

/// The document as an 8-bit RGB Photoshop file: every layer (cropped to what it holds) with its
/// name, opacity, visibility and blend mode, and the flattened picture for programs that read
/// only that. Layers are written bottom first, as Photoshop lists them.
pub fn save(doc: &Doc) -> Vec<u8> {
    let (w, h) = (doc.w, doc.h);
    let mut o = Vec::new();
    o.extend_from_slice(b"8BPS");
    o.extend_from_slice(&1u16.to_be_bytes());
    o.extend_from_slice(&[0; 6]);
    o.extend_from_slice(&3u16.to_be_bytes());
    o.extend_from_slice(&(h as u32).to_be_bytes());
    o.extend_from_slice(&(w as u32).to_be_bytes());
    o.extend_from_slice(&8u16.to_be_bytes());
    o.extend_from_slice(&3u16.to_be_bytes());
    o.extend_from_slice(&0u32.to_be_bytes()); // colour mode data
    o.extend_from_slice(&0u32.to_be_bytes()); // image resources
    let mut recs = Vec::new();
    let mut data = Vec::new();
    for l in &doc.layers {
        // the box of what the layer holds
        let (mut x0, mut y0, mut x1, mut y1) = (w, h, 0usize, 0usize);
        for y in 0..h {
            let row = &l.px[y * w * 4..(y + 1) * w * 4];
            for x in 0..w {
                if row[x * 4 + 3] != 0 {
                    x0 = x0.min(x);
                    x1 = x1.max(x + 1);
                    y0 = y0.min(y);
                    y1 = y1.max(y + 1);
                }
            }
        }
        if x1 <= x0 || y1 <= y0 {
            x0 = 0;
            y0 = 0;
            x1 = 0;
            y1 = 0;
        }
        let (lw, lh) = (x1 - x0, y1 - y0);
        for v in [y0, x0, y1, x1] {
            recs.extend_from_slice(&(v as i32).to_be_bytes());
        }
        recs.extend_from_slice(&4u16.to_be_bytes());
        let px = &l.px;
        let mut chans = Vec::new();
        for (id, k) in [(-1i16, 3usize), (0, 0), (1, 1), (2, 2)] {
            let (head, rows) = rle_channel(|x, y| px[((y0 + y) * w + x0 + x) * 4 + k], lw, lh, true);
            recs.extend_from_slice(&(id as u16).to_be_bytes());
            recs.extend_from_slice(&((head.len() + rows.len()) as u32).to_be_bytes());
            chans.push((head, rows));
        }
        recs.extend_from_slice(b"8BIM");
        recs.extend_from_slice(blend_key(l.blend));
        recs.push((l.opacity.clamp(0.0, 1.0) * 255.0).round() as u8);
        recs.push(0); // clipping
        recs.push(if l.visible { 0 } else { 2 } | 8);
        recs.push(0);
        let mut extra = Vec::new();
        extra.extend_from_slice(&0u32.to_be_bytes()); // no mask
        extra.extend_from_slice(&0u32.to_be_bytes()); // no blending ranges
        // the name as a Pascal string padded to 4, then in full as Unicode
        let ascii: Vec<u8> = l.name.chars().map(|c| if c.is_ascii() && !c.is_ascii_control() { c as u8 } else { b'_' }).take(255).collect();
        let start = extra.len();
        extra.push(ascii.len() as u8);
        extra.extend_from_slice(&ascii);
        while (extra.len() - start) % 4 != 0 {
            extra.push(0);
        }
        let u: Vec<u16> = l.name.encode_utf16().collect();
        let mut lu = Vec::new();
        lu.extend_from_slice(&(u.len() as u32).to_be_bytes());
        for c in &u {
            lu.extend_from_slice(&c.to_be_bytes());
        }
        while lu.len() % 4 != 0 {
            lu.push(0);
        }
        extra.extend_from_slice(b"8BIMluni");
        extra.extend_from_slice(&(lu.len() as u32).to_be_bytes());
        extra.extend_from_slice(&lu);
        recs.extend_from_slice(&(extra.len() as u32).to_be_bytes());
        recs.extend_from_slice(&extra);
        for (head, rows) in chans {
            data.extend_from_slice(&head);
            data.extend_from_slice(&rows);
        }
    }
    let mut li = Vec::new();
    // a negative count: the first alpha channel holds the merged picture's transparency
    li.extend_from_slice(&(-(doc.layers.len() as i16) as u16).to_be_bytes());
    li.extend_from_slice(&recs);
    li.extend_from_slice(&data);
    if li.len() % 2 == 1 {
        li.push(0);
    }
    let mut lm = Vec::new();
    lm.extend_from_slice(&(li.len() as u32).to_be_bytes());
    lm.extend_from_slice(&li);
    lm.extend_from_slice(&0u32.to_be_bytes()); // global mask
    o.extend_from_slice(&(lm.len() as u32).to_be_bytes());
    o.extend_from_slice(&lm);
    // the merged picture: RLE, all row counts first, then the planes
    let merged = doc.flatten_rgba();
    o.extend_from_slice(&1u16.to_be_bytes());
    let mut counts = Vec::new();
    let mut planes = Vec::new();
    for k in 0..3 {
        let (head, rows) = rle_channel(|x, y| {
            // over white, as Photoshop's composite has no transparency
            let p = &merged[(y * w + x) * 4..(y * w + x) * 4 + 4];
            ((p[k] as u32 * p[3] as u32 + 255 * (255 - p[3] as u32) + 127) / 255) as u8
        }, w, h, false);
        counts.extend_from_slice(&head);
        planes.extend_from_slice(&rows);
    }
    o.extend_from_slice(&counts);
    o.extend_from_slice(&planes);
    o
}

#[cfg(test)]
pub mod tests {
    use super::*;

    fn rle(row: &[u8]) -> Vec<u8> {
        // literal runs only, plus repeats of 3+, as Photoshop writes
        let mut o = Vec::new();
        let mut i = 0;
        while i < row.len() {
            let mut j = i + 1;
            while j < row.len() && row[j] == row[i] && j - i < 128 {
                j += 1;
            }
            if j - i >= 3 {
                o.push((1i16 - (j - i) as i16) as i8 as u8);
                o.push(row[i]);
                i = j;
            } else {
                let s = i;
                let mut e = i;
                while e < row.len() && e - s < 128 && !(e + 2 < row.len() && row[e] == row[e + 1] && row[e] == row[e + 2]) {
                    e += 1;
                }
                o.push((e - s - 1) as u8);
                o.extend_from_slice(&row[s..e]);
                i = e;
            }
        }
        o
    }

    pub struct L {
        pub name: &'static str,
        pub rect: (i32, i32, i32, i32),
        pub rgba: [u8; 4],
        pub opacity: u8,
        pub hidden: bool,
        pub blend: &'static [u8; 4],
        pub divider: u32,
        pub clip: bool,
        pub mask: Option<(i32, i32, i32, i32)>,
        pub adjustment: bool,
    }

    impl L {
        pub fn px(name: &'static str, rect: (i32, i32, i32, i32), rgba: [u8; 4]) -> L {
            L { name, rect, rgba, opacity: 255, hidden: false, blend: b"norm", divider: 0, clip: false, mask: None, adjustment: false }
        }
    }

    /// A small RGB .psd made the way Photoshop lays it out (RLE channels, Unicode names, group dividers).
    pub fn write(w: usize, h: usize, layers: &[L], merged: [u8; 3]) -> Vec<u8> {
        let mut o = Vec::new();
        o.extend_from_slice(b"8BPS");
        o.extend_from_slice(&1u16.to_be_bytes());
        o.extend_from_slice(&[0; 6]);
        o.extend_from_slice(&3u16.to_be_bytes());
        o.extend_from_slice(&(h as u32).to_be_bytes());
        o.extend_from_slice(&(w as u32).to_be_bytes());
        o.extend_from_slice(&8u16.to_be_bytes());
        o.extend_from_slice(&3u16.to_be_bytes());
        o.extend_from_slice(&0u32.to_be_bytes());
        o.extend_from_slice(&0u32.to_be_bytes());
        let mut recs = Vec::new();
        let mut data = Vec::new();
        for l in layers {
            let (t, lf, b, rt) = if l.divider != 0 || l.adjustment { (0, 0, 0, 0) } else { l.rect };
            let (lw, lh) = ((rt - lf).max(0) as usize, (b - t).max(0) as usize);
            let mut ids: Vec<i16> = vec![-1, 0, 1, 2];
            if l.mask.is_some() {
                ids.push(-2);
            }
            recs.extend_from_slice(&t.to_be_bytes());
            recs.extend_from_slice(&lf.to_be_bytes());
            recs.extend_from_slice(&b.to_be_bytes());
            recs.extend_from_slice(&rt.to_be_bytes());
            recs.extend_from_slice(&(ids.len() as u16).to_be_bytes());
            let mut chan_data = Vec::new();
            for &id in &ids {
                let (cw, ch, v) = if id == -2 {
                    let m = l.mask.unwrap();
                    (((m.3 - m.1) as usize), ((m.2 - m.0) as usize), 255u8)
                } else {
                    (lw, lh, if id == -1 { l.rgba[3] } else { l.rgba[id as usize] })
                };
                let mut c = Vec::new();
                c.extend_from_slice(&1u16.to_be_bytes());
                let rows: Vec<Vec<u8>> = (0..ch).map(|_| rle(&vec![v; cw])).collect();
                for row in &rows {
                    c.extend_from_slice(&(row.len() as u16).to_be_bytes());
                }
                for row in &rows {
                    c.extend_from_slice(row);
                }
                recs.extend_from_slice(&(id as u16).to_be_bytes());
                recs.extend_from_slice(&(c.len() as u32).to_be_bytes());
                chan_data.push(c);
            }
            recs.extend_from_slice(b"8BIM");
            recs.extend_from_slice(if l.divider == 1 || l.divider == 2 { b"pass" } else { l.blend });
            recs.push(l.opacity);
            recs.push(l.clip as u8);
            recs.push(if l.hidden { 2 } else { 0 } | 8);
            recs.push(0);
            let mut extra = Vec::new();
            if let Some(m) = l.mask {
                extra.extend_from_slice(&20u32.to_be_bytes());
                for v in [m.0, m.1, m.2, m.3] {
                    extra.extend_from_slice(&v.to_be_bytes());
                }
                extra.extend_from_slice(&[0, 0, 0, 0]);
            } else {
                extra.extend_from_slice(&0u32.to_be_bytes());
            }
            extra.extend_from_slice(&0u32.to_be_bytes());
            let nb = l.name.as_bytes();
            extra.push(nb.len() as u8);
            extra.extend_from_slice(nb);
            while (nb.len() + 1 + (extra.len() - nb.len() - 1)) % 4 != 0 || extra.len() % 4 != 0 {
                extra.push(0);
            }
            let u: Vec<u16> = l.name.encode_utf16().collect();
            let mut lu = Vec::new();
            lu.extend_from_slice(&(u.len() as u32).to_be_bytes());
            for c in &u {
                lu.extend_from_slice(&c.to_be_bytes());
            }
            if lu.len() % 4 != 0 {
                lu.resize((lu.len() + 3) / 4 * 4, 0);
            }
            extra.extend_from_slice(b"8BIMluni");
            extra.extend_from_slice(&(lu.len() as u32).to_be_bytes());
            extra.extend_from_slice(&lu);
            if l.divider != 0 {
                extra.extend_from_slice(b"8BIMlsct");
                extra.extend_from_slice(&4u32.to_be_bytes());
                extra.extend_from_slice(&l.divider.to_be_bytes());
            }
            if l.adjustment {
                extra.extend_from_slice(b"8BIMlevl");
                extra.extend_from_slice(&4u32.to_be_bytes());
                extra.extend_from_slice(&[0, 2, 0, 0]);
            }
            recs.extend_from_slice(&(extra.len() as u32).to_be_bytes());
            recs.extend_from_slice(&extra);
            for c in chan_data {
                data.extend_from_slice(&c);
            }
        }
        let mut li = Vec::new();
        li.extend_from_slice(&(-(layers.len() as i16) as u16).to_be_bytes());
        li.extend_from_slice(&recs);
        li.extend_from_slice(&data);
        if li.len() % 2 == 1 {
            li.push(0);
        }
        let mut lm = Vec::new();
        lm.extend_from_slice(&(li.len() as u32).to_be_bytes());
        lm.extend_from_slice(&li);
        lm.extend_from_slice(&0u32.to_be_bytes());
        o.extend_from_slice(&(lm.len() as u32).to_be_bytes());
        o.extend_from_slice(&lm);
        // merged image, raw
        o.extend_from_slice(&0u16.to_be_bytes());
        for c in merged {
            o.extend(std::iter::repeat(c).take(w * h));
        }
        o
    }

    #[test]
    fn layers_with_names_masks_groups_and_clipping() {
        let mut hidden_group = L::px("Hidden group", (0, 0, 0, 0), [0; 4]);
        hidden_group.divider = 1;
        hidden_group.hidden = true;
        let mut end = L::px("</Layer group>", (0, 0, 0, 0), [0; 4]);
        end.divider = 3;
        let mut half = L::px("Half", (0, 0, 10, 20), [0, 255, 0, 255]);
        half.opacity = 128;
        half.blend = b"mul ";
        let mut masked = L::px("Masked", (0, 0, 20, 20), [255, 255, 0, 255]);
        masked.mask = Some((0, 0, 10, 10)); // the mask shows only the top-left; outside it is 0
        let mut clipped = L::px("Clipped", (0, 0, 20, 20), [9, 9, 9, 255]);
        clipped.clip = true;
        let layers = vec![
            L::px("Background", (0, 0, 20, 20), [255, 255, 255, 255]),
            L::px("Square é", (5, 5, 15, 15), [255, 0, 0, 255]),
            clipped,
            half,
            end,
            L::px("Inside", (0, 0, 20, 20), [0, 0, 255, 255]),
            hidden_group,
            masked,
        ];
        let f = write(20, 20, &layers, [1, 2, 3]);
        assert!(is_psd(&f));
        let d = load(&f).unwrap();
        let names: Vec<&str> = d.layers.iter().map(|l| l.name.as_str()).collect();
        assert_eq!(names, ["Background", "Square é", "Clipped", "Half", "Inside", "Masked"]);
        assert_eq!(&d.layers[1].px[(10 * 20 + 10) * 4..][..4], &[255, 0, 0, 255]);
        assert_eq!(d.layers[1].px[(1 * 20 + 1) * 4 + 3], 0, "outside the layer's rectangle");
        assert_eq!(d.layers[2].px[(1 * 20 + 1) * 4 + 3], 0, "clipped to the square below");
        assert_eq!(d.layers[2].px[(10 * 20 + 10) * 4 + 3], 255);
        assert!((d.layers[3].opacity - 128.0 / 255.0).abs() < 1e-3);
        assert_eq!(d.layers[3].blend, BLEND_MULTIPLY);
        assert!(!d.layers[4].visible, "in a hidden group");
        assert!(d.layers[3].visible, "{:?}", d.layers.iter().map(|l| l.visible).collect::<Vec<_>>());
        assert_eq!(d.layers[5].px[(2 * 20 + 2) * 4 + 3], 255, "inside the mask");
        assert_eq!(d.layers[5].px[(15 * 20 + 15) * 4 + 3], 0, "outside the mask");
    }

    #[test]
    fn adjustment_layers_open_the_saved_picture() {
        let mut adj = L::px("Levels", (0, 0, 0, 0), [0; 4]);
        adj.adjustment = true;
        let f = write(8, 8, &[L::px("Background", (0, 0, 8, 8), [255, 255, 255, 255]), adj], [10, 20, 30]);
        let d = load(&f).unwrap();
        assert_eq!(d.layers.len(), 1);
        assert_eq!(&d.layers[0].px[..4], &[10, 20, 30, 255]);
        assert_eq!(d.note, "psd-adjustments");
    }

    #[test]
    fn flat_file_and_damage() {
        let f = write(6, 4, &[], [200, 100, 50]);
        let d = load(&f).unwrap();
        assert_eq!(d.layers.len(), 1);
        assert_eq!(&d.layers[0].px[..4], &[200, 100, 50, 255]);
        for cut in [30, 40, f.len() / 2] {
            let _ = load(&f[..cut]);
        }
        let mut g = write(4, 4, &[L::px("A", (0, 0, 4, 4), [1, 2, 3, 255])], [0, 0, 0]);
        let n = g.len();
        g.truncate(n - 20);
        let _ = load(&g);
    }

    #[test]
    fn save_reads_back() {
        let mut d = Doc::new(40, 30, [255, 255, 255, 255]);
        let mut px = vec![0u8; 40 * 30 * 4];
        for y in 5..20 {
            for x in 8..30 {
                let o = (y * 40 + x) * 4;
                px[o..o + 4].copy_from_slice(&[200, 30, 40, 255]);
            }
        }
        d.push_layer("Röd kvadrat", px, 0.5, true, BLEND_MULTIPLY);
        d.push_layer("Hidden", vec![0u8; 40 * 30 * 4], 1.0, false, BLEND_NORMAL);
        let bytes = save(&d);
        let back = load(&bytes).unwrap();
        assert_eq!(back.layers.len(), 3);
        assert_eq!(back.layers[1].name, "Röd kvadrat");
        assert!((back.layers[1].opacity - 0.5).abs() < 0.01);
        assert_eq!(back.layers[1].blend, BLEND_MULTIPLY);
        assert!(!back.layers[2].visible);
        assert_eq!(back.layers[1].px, d.layers[1].px);
        assert_eq!(back.layers[0].px, d.layers[0].px);
    }
}
