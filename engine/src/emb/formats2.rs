//! More machine files (D3-02): Janome JEF, Melco EXP, Husqvarna Viking / Pfaff VP3 and Singer
//! XXX, written and read. Layouts follow pyembroidery's MIT-licensed writers and readers as a
//! specification (its thread chart for JEF too); the code is this engine's own.

use super::formats::{bounds, stream, COLOR, END};
use super::plan::{Block, Plan, Thread, JUMP, ST, TRIM};

/// Janome's thread chart, by the index a JEF file carries (0 is a placeholder).
const JEF: [(u32, &str); 79] = [
    (0x000000, "Placeholder"), (0x000000, "Black"), (0xFFFFFF, "White"), (0xFFFF17, "Yellow"), (0xFF6600, "Orange"),
    (0x2F5933, "Olive Green"), (0x237336, "Green"), (0x65C2C8, "Sky"), (0xAB5A96, "Purple"), (0xF669A0, "Pink"),
    (0xFF0000, "Red"), (0xB1704E, "Brown"), (0x0B2F84, "Blue"), (0xE4C35D, "Gold"), (0x481A05, "Dark Brown"),
    (0xAC9CC7, "Pale Violet"), (0xFCF294, "Pale Yellow"), (0xF999B7, "Pale Pink"), (0xFAB381, "Peach"), (0xC9A480, "Beige"),
    (0x970533, "Wine Red"), (0xA0B8CC, "Pale Sky"), (0x7FC21C, "Yellow Green"), (0xE5E5E5, "Silver Gray"), (0x889B9B, "Gray"),
    (0x98D6BD, "Pale Aqua"), (0xB2E1E3, "Baby Blue"), (0x368BA0, "Powder Blue"), (0x4F83AB, "Bright Blue"), (0x386A91, "Slate Blue"),
    (0x071650, "Navy Blue"), (0xF999A2, "Salmon Pink"), (0xF9676B, "Coral"), (0xE3311F, "Burnt Orange"), (0xE2A188, "Cinnamon"),
    (0xB59474, "Umber"), (0xE4CF99, "Blond"), (0xFFCB00, "Sunflower"), (0xE1ADD4, "Orchid Pink"), (0xC3007E, "Peony Purple"),
    (0x80004B, "Burgundy"), (0x540571, "Royal Purple"), (0xB10525, "Cardinal Red"), (0xCAE0C0, "Opal Green"), (0x899856, "Moss Green"),
    (0x5C941A, "Meadow Green"), (0x003114, "Dark Green"), (0x5DAE94, "Aquamarine"), (0x4CBF8F, "Emerald Green"), (0x007772, "Peacock Green"),
    (0x595B61, "Dark Gray"), (0xFFFFF2, "Ivory White"), (0xB15818, "Hazel"), (0xCB8A07, "Toast"), (0x986C80, "Salmon"),
    (0x98692D, "Cocoa Brown"), (0x4D3419, "Sienna"), (0x4C330B, "Sepia"), (0x33200A, "Dark Sepia"), (0x523A97, "Violet Blue"),
    (0x0D217E, "Blue Ink"), (0x1E77AC, "Sola Blue"), (0xB2DD53, "Green Dust"), (0xF33689, "Crimson"), (0xDE649E, "Floral Pink"),
    (0x984161, "Wine"), (0x4C5612, "Olive Drab"), (0x4C881F, "Meadow"), (0xE4DE79, "Mustard"), (0xCB8A1A, "Yellow Ocher"),
    (0xCBA21C, "Old Gold"), (0xFF9805, "Honey Dew"), (0xFCB257, "Tangerine"), (0xFFE505, "Canary Yellow"), (0xF0331F, "Vermilion"),
    (0x1A842D, "Bright Green"), (0x386CAE, "Ocean Blue"), (0xE3C4B4, "Beige Gray"), (0xE3AC81, "Bamboo"),
];

fn rgb_of(c: u32) -> [u8; 3] {
    [(c >> 16) as u8, (c >> 8) as u8, c as u8]
}

/// pyembroidery's red-mean colour distance.
fn redmean(a: [u8; 3], b: [u8; 3]) -> i64 {
    let rm = ((a[0] as i64 + b[0] as i64) as f64 / 2.0).round() as i64;
    let (r, g, bl) = (a[0] as i64 - b[0] as i64, a[1] as i64 - b[1] as i64, a[2] as i64 - b[2] as i64);
    (((512 + rm) * r * r) >> 8) + 4 * g * g + (((767 - rm) * bl * bl) >> 8)
}

fn nearest_jef(c: [u8; 3], not: Option<usize>) -> usize {
    let mut best = 1;
    let mut bd = i64::MAX;
    for (i, t) in JEF.iter().enumerate().skip(1) {
        if Some(i) == not {
            continue;
        }
        let d = redmean(c, rgb_of(t.0));
        if d < bd {
            bd = d;
            best = i;
        }
    }
    best
}

fn jef_thread(i: usize) -> Thread {
    let i = if i == 0 || i >= JEF.len() { 1 } else { i };
    Thread { rgb: rgb_of(JEF[i].0), pec: None, name: JEF[i].1.to_string() }
}

/// Default colours for files that carry none (EXP), as DST reading does.
fn plain_thread(n: usize) -> Thread {
    let order = [1usize, 10, 12, 6, 3, 8, 4, 11, 30, 23];
    jef_thread(order[n % order.len()])
}

fn i8b(v: i32) -> u8 {
    v as i8 as u8
}

/// Split a move of (dx, dy) into steps of at most `max` per axis.
fn steps(dx: i32, dy: i32, max: i32) -> Vec<(i32, i32)> {
    let n = ((dx.abs().max(dy.abs()) as f32) / max as f32).ceil().max(1.0) as i32;
    let (mut px, mut py) = (0, 0);
    let mut out = Vec::with_capacity(n as usize);
    for k in 1..=n {
        let tx = (dx as f64 * k as f64 / n as f64).round() as i32;
        let ty = (dy as f64 * k as f64 / n as f64).round() as i32;
        out.push((tx - px, ty - py));
        px = tx;
        py = ty;
    }
    out
}

// ------------------------------------------------------------------ EXP

/// Melco EXP: two signed bytes per stitch (0.1 mm, y up); 0x80 escapes jumps, trims and colours.
pub fn write_exp(p: &Plan) -> Vec<u8> {
    let mut out = Vec::new();
    let (mut xx, mut yy) = (0, 0);
    for c in stream(p) {
        match c.2 {
            ST | JUMP => {
                for (dx, dy) in steps(c.0 - xx, c.1 - yy, 127) {
                    if c.2 == JUMP {
                        out.extend_from_slice(&[0x80, 0x04]);
                    }
                    out.extend_from_slice(&[i8b(dx), i8b(-dy)]);
                }
                xx = c.0;
                yy = c.1;
            }
            TRIM => out.extend_from_slice(&[0x80, 0x80, 0x07, 0x00]),
            COLOR => out.extend_from_slice(&[0x80, 0x01, 0x00, 0x00]),
            _ => {}
        }
    }
    out
}

/// Inserts a trim before a run of jumps longer than 3 mm (the way the machines read them).
fn trims_before_long_jumps(blocks: &mut [Block]) {
    for b in blocks.iter_mut() {
        let mut out = Vec::with_capacity(b.cmds.len() + 8);
        let mut i = 0;
        while i < b.cmds.len() {
            if b.cmds[i].2 != JUMP {
                out.push(b.cmds[i]);
                i += 1;
                continue;
            }
            let start = out.last().map(|c: &(f32, f32, u8)| (c.0, c.1)).unwrap_or((b.cmds[i].0, b.cmds[i].1));
            let mut j = i;
            while j < b.cmds.len() && b.cmds[j].2 == JUMP {
                j += 1;
            }
            let end = b.cmds[j - 1];
            let far = ((end.0 - start.0).powi(2) + (end.1 - start.1).powi(2)).sqrt() > 3.0;
            if far && out.last().map_or(false, |c| c.2 != TRIM) {
                out.push((start.0, start.1, TRIM));
            }
            out.extend_from_slice(&b.cmds[i..j]);
            i = j;
        }
        b.cmds = out;
    }
}

pub fn read_exp(data: &[u8]) -> Result<Plan, String> {
    let mut blocks = vec![Block { thread: plain_thread(0), cmds: Vec::new(), stop: false }];
    let (mut x, mut y) = (0i32, 0i32);
    let mut i = 0;
    let s8 = |v: u8| v as i8 as i32;
    while i + 2 <= data.len() {
        let (b0, b1) = (data[i], data[i + 1]);
        i += 2;
        if b0 != 0x80 {
            x += s8(b0);
            y -= s8(b1);
            blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, ST));
            continue;
        }
        if i + 2 > data.len() {
            break;
        }
        let (dx, dy) = (s8(data[i]), -s8(data[i + 1]));
        i += 2;
        match b1 {
            0x80 => {
                let at = (x as f32 / 10.0, y as f32 / 10.0, TRIM);
                blocks.last_mut().unwrap().cmds.push(at);
            }
            0x02 => {
                x += dx;
                y += dy;
                blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, ST));
            }
            0x04 => {
                x += dx;
                y += dy;
                blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
            }
            0x01 => {
                let n = blocks.len();
                blocks.push(Block { thread: plain_thread(n), cmds: Vec::new(), stop: false });
                if dx != 0 || dy != 0 {
                    x += dx;
                    y += dy;
                    blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
                }
            }
            _ => break,
        }
    }
    finish(blocks)
}

fn finish(mut blocks: Vec<Block>) -> Result<Plan, String> {
    blocks.retain(|b| b.cmds.iter().any(|c| c.2 == ST));
    if blocks.is_empty() {
        return Err("no stitches in this design".into());
    }
    Ok(Plan { blocks })
}

// ------------------------------------------------------------------ JEF

/// Janome JEF: a header with the colour list and hoop margins, then EXP-like stitch bytes.
pub fn write_jef(p: &Plan, date: &str) -> Vec<u8> {
    let s = stream(p);
    // palette: the nearest Janome thread per block; two neighbouring blocks that land on the
    // same thread take the next nearest, so the machine still shows a change
    let mut palette: Vec<usize> = Vec::new();
    for (bi, b) in p.blocks.iter().enumerate() {
        let mut k = nearest_jef(b.thread.rgb, None);
        if bi > 0 && palette.last() == Some(&k) && p.blocks[bi - 1].thread != b.thread {
            k = nearest_jef(b.thread.rgb, Some(k));
        }
        palette.push(k);
    }
    let colours = palette.len().max(1);
    let mut body = Vec::new();
    let mut points = 1u32; // the END
    let (mut xx, mut yy) = (0, 0);
    for c in &s {
        match c.2 {
            ST | JUMP => {
                for (dx, dy) in steps(c.0 - xx, c.1 - yy, 127) {
                    if c.2 == JUMP {
                        body.extend_from_slice(&[0x80, 0x02]);
                        points += 2;
                    } else {
                        points += 1;
                    }
                    body.extend_from_slice(&[i8b(dx), i8b(-dy)]);
                }
                xx = c.0;
                yy = c.1;
            }
            COLOR => {
                body.extend_from_slice(&[0x80, 0x01, 0x00, 0x00]);
                points += 2;
            }
            _ => {}
        }
    }
    body.extend_from_slice(&[0x80, 0x10]);
    let b = bounds(&s);
    let (w, h) = (b.2 - b.0, b.3 - b.1);
    let (hw, hh) = ((w as f32 / 2.0).round() as i32, (h as f32 / 2.0).round() as i32);
    let hoop = if w < 500 && h < 500 {
        1
    } else if w < 1260 && h < 1100 {
        3
    } else if w < 1400 && h < 2000 {
        2
    } else if w < 2000 && h < 2000 {
        4
    } else {
        0
    };
    let mut out = Vec::new();
    let put = |out: &mut Vec<u8>, v: i32| out.extend_from_slice(&v.to_le_bytes());
    put(&mut out, 0x74 + colours as i32 * 8);
    put(&mut out, 0x14);
    let mut d: Vec<u8> = date.bytes().filter(|c| c.is_ascii_digit()).take(14).collect();
    d.resize(14, b'0');
    out.extend_from_slice(&d);
    out.extend_from_slice(&[0, 0]);
    put(&mut out, colours as i32);
    put(&mut out, points as i32);
    put(&mut out, hoop);
    for v in [hw, hh, hw, hh] {
        put(&mut out, v);
    }
    for (ex, ey) in [(550, 550), (250, 250), (700, 1000), (700, 1000)] {
        let (x, y) = (ex - hw, ey - hh);
        for v in if x.min(y) >= 0 { [x, y, x, y] } else { [-1; 4] } {
            put(&mut out, v);
        }
    }
    for k in &palette {
        put(&mut out, *k as i32);
    }
    for _ in 0..colours {
        put(&mut out, 0x0D);
    }
    out.extend_from_slice(&body);
    out
}

pub fn read_jef(data: &[u8]) -> Result<Plan, String> {
    let u32at = |at: usize| -> Option<i32> { data.get(at..at + 4).map(|b| i32::from_le_bytes([b[0], b[1], b[2], b[3]])) };
    let start = u32at(0).ok_or("JEF: short file")? as usize;
    let n = u32at(24).ok_or("JEF: short file")?.clamp(0, 1000) as usize;
    let mut threads = Vec::new();
    for k in 0..n {
        let idx = u32at(116 + k * 4).ok_or("JEF: short file")?.unsigned_abs() as usize;
        threads.push(jef_thread(idx % JEF.len()));
    }
    if start > data.len() {
        return Err("JEF: bad stitch offset".into());
    }
    let next = |k: usize| threads.get(k).cloned().unwrap_or_else(|| plain_thread(k));
    let mut blocks = vec![Block { thread: next(0), cmds: Vec::new(), stop: false }];
    let (mut x, mut y) = (0i32, 0i32);
    let s8 = |v: u8| v as i8 as i32;
    let mut i = start;
    while i + 2 <= data.len() {
        let (b0, b1) = (data[i], data[i + 1]);
        i += 2;
        if b0 != 0x80 {
            x += s8(b0);
            y -= s8(b1);
            blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, ST));
            continue;
        }
        if b1 == 0x10 || i + 2 > data.len() {
            break;
        }
        let (dx, dy) = (s8(data[i]), -s8(data[i + 1]));
        i += 2;
        match b1 {
            0x02 => {
                x += dx;
                y += dy;
                blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
            }
            0x01 => {
                let k = blocks.len();
                blocks.push(Block { thread: next(k), cmds: Vec::new(), stop: false });
            }
            _ => break,
        }
    }
    trims_before_long_jumps(&mut blocks);
    finish(blocks)
}

// ------------------------------------------------------------------ XXX

/// Singer XXX: a 256-byte header, two-byte stitches (0x7F escapes), the colours at the end.
pub fn write_xxx(p: &Plan) -> Vec<u8> {
    let s = stream(p);
    let b = bounds(&s);
    let mut body = Vec::new();
    let (mut xx, mut yy) = (0, 0);
    for c in &s {
        match c.2 {
            ST => {
                for (dx, dy) in steps(c.0 - xx, c.1 - yy, 123) {
                    body.extend_from_slice(&[i8b(dx), i8b(-dy)]);
                }
                xx = c.0;
                yy = c.1;
            }
            JUMP => {
                for (dx, dy) in steps(c.0 - xx, c.1 - yy, 123) {
                    body.extend_from_slice(&[0x7F, 0x01, i8b(dx), i8b(-dy)]);
                }
                xx = c.0;
                yy = c.1;
            }
            TRIM => body.extend_from_slice(&[0x7F, 0x03, 0, 0]),
            COLOR => body.extend_from_slice(&[0x7F, 0x08, 0, 0]),
            _ => {}
        }
    }
    let count = s.len().saturating_sub(1) as u32;
    let mut out = vec![0u8; 0x17];
    out.extend_from_slice(&count.to_le_bytes());
    out.extend_from_slice(&[0u8; 0x0C]);
    out.extend_from_slice(&(p.blocks.len() as u32).to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    let last = s.iter().rev().find(|c| c.2 != END).copied().unwrap_or((0, 0, ST));
    for v in [b.2 - b.0, b.3 - b.1, last.0, -last.1, -b.0, b.3] {
        out.extend_from_slice(&(v as i16).to_le_bytes());
    }
    out.extend_from_slice(&[0u8; 0x42]);
    out.extend_from_slice(&[0u8; 4]);
    out.extend_from_slice(&[0u8; 0x73]);
    out.extend_from_slice(&0x20u16.to_le_bytes());
    out.extend_from_slice(&[0u8; 8]);
    debug_assert_eq!(out.len(), 0xFC);
    let end_at = (0x100 + body.len()) as u32;
    out.extend_from_slice(&end_at.to_le_bytes());
    out.extend_from_slice(&body);
    out.extend_from_slice(&[0x7F, 0x7F, 0x02, 0x14]);
    out.extend_from_slice(&[0, 0]);
    for bl in &p.blocks {
        out.extend_from_slice(&[0, bl.thread.rgb[0], bl.thread.rgb[1], bl.thread.rgb[2]]);
    }
    for _ in p.blocks.len()..21 {
        out.extend_from_slice(&[0u8; 4]);
    }
    out.extend_from_slice(&0xFFFF_FF00u32.to_le_bytes());
    out.extend_from_slice(&[0, 1]);
    out
}

pub fn read_xxx(data: &[u8]) -> Result<Plan, String> {
    if data.len() < 0x100 {
        return Err("XXX: short file".into());
    }
    let ncol = u16::from_le_bytes([data[0x27], data[0x28]]) as usize;
    let s8 = |v: u8| v as i8 as i32;
    let mut blocks = vec![Block { thread: plain_thread(0), cmds: Vec::new(), stop: false }];
    let (mut x, mut y) = (0i32, 0i32);
    let mut i = 0x100;
    let mut ended = false;
    while i + 2 <= data.len() {
        let b1 = data[i];
        if b1 == 0x7D || b1 == 0x7E {
            if i + 5 > data.len() {
                break;
            }
            x += i16::from_le_bytes([data[i + 1], data[i + 2]]) as i32;
            y -= i16::from_le_bytes([data[i + 3], data[i + 4]]) as i32;
            i += 5;
            blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
            continue;
        }
        let b2 = data[i + 1];
        i += 2;
        if b1 != 0x7F {
            x += s8(b1);
            y -= s8(b2);
            blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, ST));
            continue;
        }
        if b2 == 0x7F || b2 == 0x18 {
            i += 2;
            ended = true;
            break;
        }
        if i + 2 > data.len() {
            break;
        }
        let (dx, dy) = (s8(data[i]), -s8(data[i + 1]));
        i += 2;
        match b2 {
            0x01 => {
                x += dx;
                y += dy;
                blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
            }
            0x03 => {
                let at = (x as f32 / 10.0, y as f32 / 10.0, TRIM);
                blocks.last_mut().unwrap().cmds.push(at);
                if dx != 0 || dy != 0 {
                    x += dx;
                    y += dy;
                    blocks.last_mut().unwrap().cmds.push((x as f32 / 10.0, y as f32 / 10.0, JUMP));
                }
            }
            0x08 | 0x0A..=0x17 => {
                let n = blocks.len();
                blocks.push(Block { thread: plain_thread(n), cmds: Vec::new(), stop: false });
            }
            _ => break,
        }
    }
    if ended {
        i += 2;
        for k in 0..ncol.min(blocks.len()) {
            if let Some(c) = data.get(i + k * 4..i + k * 4 + 4) {
                let rgb = [c[1], c[2], c[3]];
                blocks[k].thread = Thread { rgb, pec: None, name: format!("#{:02X}{:02X}{:02X}", rgb[0], rgb[1], rgb[2]) };
            }
        }
    }
    finish(blocks)
}

// ------------------------------------------------------------------ VP3

fn be32(out: &mut Vec<u8>, v: i32) {
    out.extend_from_slice(&v.to_be_bytes());
}
fn be16(out: &mut Vec<u8>, v: u16) {
    out.extend_from_slice(&v.to_be_bytes());
}
fn str16(out: &mut Vec<u8>, s: &str) {
    let u: Vec<u16> = s.encode_utf16().collect();
    be16(out, (u.len() * 2) as u16);
    for c in u {
        be16(out, c);
    }
}
fn str8(out: &mut Vec<u8>, s: &str) {
    be16(out, s.len() as u16);
    out.extend_from_slice(s.as_bytes());
}
/// Fill in a 4-byte length at `at`: the bytes after it, to the end so far.
fn patch(out: &mut [u8], at: usize) {
    let d = (out.len() - at - 4) as i32;
    out[at..at + 4].copy_from_slice(&d.to_be_bytes());
}

/// Husqvarna Viking / Pfaff VP3: nested length-prefixed blocks, one per colour, positions in
/// 1/1000 mm from the design's centre (y up), stitches as signed bytes in 0.1 mm (y down). A
/// move without sewing is a trim and then a long-form stitch.
pub fn write_vp3(p: &Plan, name: &str) -> Vec<u8> {
    let s = stream(p);
    let b = bounds(&s);
    let (cx, cy) = ((b.0 + b.2) / 2, (b.1 + b.3) / 2);
    let (w, h) = (b.2 - b.0, b.3 - b.1);
    let producer = "Produced by     Folio Draw";
    let mut out = Vec::new();
    out.extend_from_slice(b"%vsm%\0");
    str16(&mut out, producer);
    out.extend_from_slice(&[0, 2, 0]);
    let file_len = out.len();
    be32(&mut out, 0);
    str16(&mut out, "");
    for v in [b.2 * 100, -b.1 * 100, b.0 * 100, -b.3 * 100] {
        be32(&mut out, v);
    }
    let nst = s.iter().filter(|c| c.2 != END).count() as i32;
    be32(&mut out, nst);
    out.extend_from_slice(&[0, p.blocks.len().min(255) as u8, 12, 0, 1]);
    // the design
    out.extend_from_slice(&[0, 3, 0]);
    let design_len = out.len();
    be32(&mut out, 0);
    be32(&mut out, cx * 100);
    be32(&mut out, -cy * 100);
    out.extend_from_slice(&[0, 0, 0]);
    for v in [-(w / 2) * 100, (w / 2) * 100, -(h / 2) * 100, (h / 2) * 100, w * 100, h * 100] {
        be32(&mut out, v);
    }
    str16(&mut out, "");
    out.extend_from_slice(&[0x64, 0x64]);
    for v in [4096, 0, 0, 4096] {
        be32(&mut out, v);
    }
    out.extend_from_slice(b"xxPP\x01\x00");
    str16(&mut out, producer);
    be16(&mut out, p.blocks.len() as u16);
    // the colours: split the stream at its colour changes
    let mut pieces: Vec<Vec<(i32, i32, u8)>> = vec![Vec::new()];
    for c in &s {
        match c.2 {
            COLOR => pieces.push(Vec::new()),
            END => {}
            _ => pieces.last_mut().unwrap().push(*c),
        }
    }
    let _ = name;
    for (bi, (piece, bl)) in pieces.iter().zip(p.blocks.iter()).enumerate() {
        out.extend_from_slice(&[0, 5, 0]);
        let block_len = out.len();
        be32(&mut out, 0);
        let first = if bi == 0 { (0, 0) } else { piece.first().map(|c| (c.0, c.1)).unwrap_or((0, 0)) };
        let last = piece.last().map(|c| (c.0, c.1)).unwrap_or(first);
        be32(&mut out, (first.0 - cx) * 100);
        be32(&mut out, -(first.1 - cy) * 100);
        let t = &bl.thread;
        out.extend_from_slice(&[1, 0, t.rgb[0], t.rgb[1], t.rgb[2], 0, 0, 0, 5, 0x28]);
        str8(&mut out, "");
        str8(&mut out, &t.name.chars().filter(|c| c.is_ascii()).collect::<String>());
        str8(&mut out, "");
        be32(&mut out, (last.0 - first.0) * 100);
        be32(&mut out, -(last.1 - first.1) * 100);
        out.extend_from_slice(&[0, 1, 0]);
        let st_len = out.len();
        be32(&mut out, 0);
        out.extend_from_slice(&[0x0A, 0xF6, 0x00]);
        let (mut lx, mut ly) = first;
        let mut moving = false;
        for c in piece.iter() {
            match c.2 {
                TRIM => out.extend_from_slice(&[0x80, 0x03]),
                JUMP => moving = true,
                ST => {
                    let (dx, dy) = (c.0 - lx, c.1 - ly);
                    if moving || dx.abs() > 127 || dy.abs() > 127 {
                        if moving && out[out.len() - 2..] != [0x80, 0x03] {
                            out.extend_from_slice(&[0x80, 0x03]);
                        }
                        out.extend_from_slice(&[0x80, 0x01]);
                        be16(&mut out, dx as i16 as u16);
                        be16(&mut out, dy as i16 as u16);
                        out.extend_from_slice(&[0x80, 0x02]);
                        // the needle comes down where the long form lands (after a trim that is the
                        // first stitch there; without one, the long form itself was sewn)
                        out.extend_from_slice(&[0, 0]);
                    } else {
                        out.extend_from_slice(&[i8b(dx), i8b(dy)]);
                    }
                    lx = c.0;
                    ly = c.1;
                    moving = false;
                }
                _ => {}
            }
        }
        patch(&mut out, st_len);
        out.push(0);
        patch(&mut out, block_len);
    }
    patch(&mut out, design_len);
    patch(&mut out, file_len);
    out
}

struct Rd<'a> {
    b: &'a [u8],
    i: usize,
}
impl<'a> Rd<'a> {
    fn take(&mut self, n: usize) -> Option<&'a [u8]> {
        let s = self.b.get(self.i..self.i + n)?;
        self.i += n;
        Some(s)
    }
    fn be16(&mut self) -> Option<u16> {
        self.take(2).map(|s| u16::from_be_bytes([s[0], s[1]]))
    }
    fn be32(&mut self) -> Option<i32> {
        self.take(4).map(|s| i32::from_be_bytes([s[0], s[1], s[2], s[3]]))
    }
    fn skip_str(&mut self) -> Option<()> {
        let n = self.be16()? as usize;
        self.take(n).map(|_| ())
    }
    fn str8(&mut self) -> Option<String> {
        let n = self.be16()? as usize;
        self.take(n).map(|s| String::from_utf8_lossy(s).into_owned())
    }
}

pub fn read_vp3(data: &[u8]) -> Result<Plan, String> {
    vp3(data).ok_or_else(|| "VP3: the file is damaged or of an unknown kind".to_string()).and_then(finish)
}

fn vp3(data: &[u8]) -> Option<Vec<Block>> {
    let mut r = Rd { b: data, i: 6 };
    r.skip_str()?;
    r.take(7)?;
    r.skip_str()?;
    r.take(32)?;
    let cx = r.be32()? as f32 / 100.0;
    let cy = -(r.be32()? as f32 / 100.0);
    r.take(27)?;
    r.skip_str()?;
    r.take(24)?;
    r.skip_str()?;
    let n = r.be16()? as usize;
    let mut blocks = Vec::new();
    for bi in 0..n {
        r.take(3)?;
        let len = r.be32()? as usize;
        let end = r.i + len;
        let sx = r.be32()? as f32 / 100.0;
        let sy = -(r.be32()? as f32 / 100.0);
        let (mut x, mut y) = (sx + cx, sy + cy);
        let ncol = r.take(1)?[0] as usize;
        r.take(1)?;
        let mut rgb = [0u8; 3];
        for _ in 0..ncol {
            let c = r.take(3)?;
            rgb = [c[0], c[1], c[2]];
            r.take(3)?;
        }
        r.take(2)?;
        let _cat = r.str8()?;
        let desc = r.str8()?;
        let _brand = r.str8()?;
        r.take(15)?;
        r.take(3)?;
        let name = if desc.is_empty() { format!("#{:02X}{:02X}{:02X}", rgb[0], rgb[1], rgb[2]) } else { desc };
        let mut cmds: Vec<(f32, f32, u8)> = Vec::new();
        if bi > 0 && !(sx + cx == 0.0 && sy + cy == 0.0) {
            cmds.push((x / 10.0, y / 10.0, JUMP));
        }
        let st = data.get(r.i..end.min(data.len()))?;
        let mut i = 0;
        let s8 = |v: u8| v as i8 as f32;
        while i + 1 < st.len() {
            let (a, b) = (st[i], st[i + 1]);
            i += 2;
            if a != 0x80 {
                x += s8(a);
                y += s8(b);
                cmds.push((x / 10.0, y / 10.0, ST));
                continue;
            }
            match b {
                0x01 => {
                    if i + 4 > st.len() {
                        break;
                    }
                    x += i16::from_be_bytes([st[i], st[i + 1]]) as f32;
                    y += i16::from_be_bytes([st[i + 2], st[i + 3]]) as f32;
                    i += 6;
                    cmds.push((x / 10.0, y / 10.0, JUMP));
                }
                0x03 => cmds.push((x / 10.0, y / 10.0, TRIM)),
                _ => {}
            }
        }
        // a long form followed by a zero stitch was sewn, not moved
        for k in 1..cmds.len() {
            if cmds[k].2 == ST && cmds[k - 1].2 == JUMP && cmds[k].0 == cmds[k - 1].0 && cmds[k].1 == cmds[k - 1].1
                && (k < 2 || cmds[k - 2].2 != TRIM)
            {
                cmds[k - 1].2 = ST;
            }
        }
        cmds.dedup_by(|a, b| a.2 == ST && b.2 == ST && a.0 == b.0 && a.1 == b.1);
        r.i = end;
        blocks.push(Block { thread: Thread { rgb, pec: None, name }, cmds, stop: false });
    }
    Some(blocks)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::formats::read;
    fn sample() -> Plan {
        let red = Thread { rgb: [237, 23, 31], pec: Some(5), name: "Red".into() };
        let black = Thread { rgb: [0, 0, 0], pec: Some(20), name: "Black".into() };
        let mut a = vec![(-10.0, -10.0, JUMP), (-10.0, -10.0, ST)];
        for i in 0..50 {
            a.push((-10.0 + i as f32 * 0.4, if i % 2 == 0 { -10.0 } else { -5.0 }, ST));
        }
        a.push((10.0, 10.0, ST));
        a.push((10.0, 10.0, TRIM));
        a.push((25.0, 12.0, JUMP));
        a.push((25.0, 12.0, ST));
        a.push((28.0, 12.0, ST));
        let b = vec![(0.0, 20.0, JUMP), (0.0, 20.0, ST), (3.5, 20.0, ST), (6.9, 21.0, ST), (-14.0, 21.0, ST)];
        Plan { blocks: vec![Block { thread: red, cmds: a, stop: false }, Block { thread: black, cmds: b, stop: false }] }
    }
    fn same(p: &Plan, q: &Plan, what: &str) {
        assert_eq!(q.blocks.len(), p.blocks.len(), "{what} blocks");
        let (b0, b1) = (p.bounds(), q.bounds());
        for (u, v) in [(b0.0, b1.0), (b0.1, b1.1), (b0.2, b1.2), (b0.3, b1.3)] {
            assert!((u - v).abs() < 0.11, "{what} bounds {:?} {:?}", b0, b1);
        }
        // sewn points land on the same spots (long stitches come back split)
        let sewn = |pl: &Plan| -> Vec<(i32, i32)> {
            let mut v: Vec<(i32, i32)> = pl.blocks.iter().flat_map(|b| b.cmds.iter().filter(|c| c.2 == ST).map(|c| ((c.0 * 10.0).round() as i32, (c.1 * 10.0).round() as i32))).collect();
            v.dedup();
            v
        };
        let (a, b) = (sewn(p), sewn(q));
        for pt in &a {
            assert!(b.contains(pt), "{what}: {:?} missing", pt);
        }
        assert!(q.count(TRIM) >= 1, "{what}: the trim");
    }
    #[test]
    fn exp_roundtrip() {
        let p = sample();
        let q = super::super::formats::read_named(&write_exp(&p), "exp").unwrap();
        same(&p, &q, "EXP");
    }
    #[test]
    fn jef_roundtrip() {
        let p = sample();
        let bytes = write_jef(&p, "20261029120000");
        let q = read(&bytes).unwrap();
        same(&p, &q, "JEF");
        // the nearest Janome threads (red-mean): 237,23,31 is Burnt Orange
        assert_eq!(q.blocks[0].thread.name, "Burnt Orange");
        assert_eq!(q.blocks[1].thread.name, "Black");
    }
    #[test]
    fn xxx_roundtrip() {
        let p = sample();
        let q = read(&write_xxx(&p)).unwrap();
        same(&p, &q, "XXX");
        assert_eq!(q.blocks[0].thread.rgb, [237, 23, 31]);
    }
    #[test]
    fn vp3_roundtrip() {
        let p = sample();
        let q = read(&write_vp3(&p, "t")).unwrap();
        same(&p, &q, "VP3");
        assert_eq!(q.blocks[1].thread.rgb, [0, 0, 0]);
        assert_eq!(q.blocks[0].thread.name, "Red");
    }
}
