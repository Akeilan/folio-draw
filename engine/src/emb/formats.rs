//! Machine files: PES (version 6, with the PEC block embedded), PEC and Tajima DST, written
//! and read. Layouts follow pyembroidery's MIT-licensed writers and readers as a specification;
//! the code is this engine's own.

use super::colour::{nearest_pec_redmean, pec_name, pec_rgb};
use super::plan::{Block, Plan, Thread, JUMP, ST, TRIM};

const COLOR: u8 = 3;
const END: u8 = 4;

/// The plan as a 0.1 mm command stream (y down), colour changes between blocks, END last.
fn stream(p: &Plan) -> Vec<(i32, i32, u8)> {
    let mut out = Vec::new();
    for (bi, b) in p.blocks.iter().enumerate() {
        if bi > 0 {
            let last = out.last().copied().unwrap_or((0, 0, ST));
            out.push((last.0, last.1, COLOR));
        }
        for c in &b.cmds {
            out.push(((c.0 * 10.0).round() as i32, (c.1 * 10.0).round() as i32, c.2));
        }
    }
    let last = out.last().copied().unwrap_or((0, 0, ST));
    out.push((last.0, last.1, END));
    out
}

fn bounds(s: &[(i32, i32, u8)]) -> (i32, i32, i32, i32) {
    if s.is_empty() {
        return (0, 0, 0, 0);
    }
    let mut b = (i32::MAX, i32::MAX, i32::MIN, i32::MIN);
    for c in s {
        b.0 = b.0.min(c.0);
        b.1 = b.1.min(c.1);
        b.2 = b.2.max(c.0);
        b.3 = b.3.max(c.1);
    }
    b
}

struct W(Vec<u8>);
impl W {
    fn u8(&mut self, v: u8) {
        self.0.push(v);
    }
    fn u16(&mut self, v: u16) {
        self.0.extend_from_slice(&v.to_le_bytes());
    }
    fn i16(&mut self, v: i32) {
        self.u16(v as i16 as u16);
    }
    fn u24(&mut self, v: u32) {
        self.0.extend_from_slice(&v.to_le_bytes()[..3]);
    }
    fn u32(&mut self, v: u32) {
        self.0.extend_from_slice(&v.to_le_bytes());
    }
    fn f32(&mut self, v: f32) {
        self.0.extend_from_slice(&v.to_le_bytes());
    }
    fn bytes(&mut self, b: &[u8]) {
        self.0.extend_from_slice(b);
    }
    fn str8(&mut self, s: Option<&str>) {
        match s {
            None => self.u8(0),
            Some(s) => {
                let b = s.as_bytes();
                let n = b.len().min(255);
                self.u8(n as u8);
                self.bytes(&b[..n]);
            }
        }
    }
    fn str16(&mut self, s: &str) {
        self.u16(s.len() as u16);
        self.bytes(s.as_bytes());
    }
    fn pos(&self) -> usize {
        self.0.len()
    }
    fn patch_u32(&mut self, at: usize, v: u32) {
        self.0[at..at + 4].copy_from_slice(&v.to_le_bytes());
    }
    fn patch_u16(&mut self, at: usize, v: u16) {
        self.0[at..at + 2].copy_from_slice(&v.to_le_bytes());
    }
    fn patch_u24(&mut self, at: usize, v: u32) {
        self.0[at..at + 3].copy_from_slice(&v.to_le_bytes()[..3]);
    }
}

/// The design name in a header: up to 16 characters (ASCII), from the file name.
pub fn design_name(name: &str) -> String {
    let n: String = name.chars().filter(|c| c.is_ascii() && !c.is_ascii_control()).take(16).collect();
    if n.is_empty() {
        "Untitled".into()
    } else {
        n
    }
}

/// Unique PEC palette indices for the blocks' threads (pyembroidery's build_unique_palette:
/// each distinct thread takes the nearest index nobody else took).
fn pec_indices(threads: &[Thread]) -> Vec<u8> {
    let mut used = vec![false; 65];
    let mut uniq: Vec<(Thread, usize)> = Vec::new();
    for t in threads {
        if uniq.iter().any(|u| &u.0 == t) {
            continue;
        }
        let pick = match t.pec {
            Some(i) if (1..=64).contains(&i) && !used[i] && pec_rgb(i) == t.rgb => Some(i),
            _ => nearest_pec_redmean(t.rgb, &used),
        };
        let i = pick.unwrap_or(20);
        used[i] = true;
        uniq.push((t.clone(), i));
    }
    threads.iter().map(|t| uniq.iter().find(|u| &u.0 == t).map(|u| u.1 as u8).unwrap_or(20)).collect()
}

const ICON_BLANK: [u8; 228] = {
    let mut b = [0u8; 228];
    // frame of the 48×38 icon: top and bottom rows, rounded corners, sides
    let top = [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x08, 0x00, 0x00, 0x00, 0x00, 0x10, 0x04, 0x00, 0x00, 0x00, 0x00, 0x20];
    let mut i = 0;
    while i < 24 {
        b[i] = top[i];
        i += 1;
    }
    let mut r = 4;
    while r < 34 {
        b[r * 6] = 0x02;
        b[r * 6 + 5] = 0x40;
        r += 1;
    }
    let bottom = [0x04, 0x00, 0x00, 0x00, 0x00, 0x20, 0x08, 0x00, 0x00, 0x00, 0x00, 0x10, 0xF0, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00];
    let mut i = 0;
    while i < 24 {
        b[204 + i] = bottom[i];
        i += 1;
    }
    b
};

fn draw_icon(ext: (i32, i32, i32, i32), pts: &[(i32, i32)], g: &mut [u8; 228], buffer: f32) {
    let (left, top, right, bottom) = (ext.0 as f64, ext.1 as f64, ext.2 as f64, ext.3 as f64);
    let dw = if right - left == 0.0 { 1.0 } else { right - left };
    let dh = if bottom - top == 0.0 { 1.0 } else { bottom - top };
    let (gw, gh) = (48.0f64, 38.0f64);
    let scale = ((gw - buffer as f64) / dw).min((gh - buffer as f64) / dh);
    let (cx, cy) = ((right + left) / 2.0, (bottom + top) / 2.0);
    let tx = -cx * scale + gw / 2.0;
    let ty = -cy * scale + gh / 2.0;
    for p in pts {
        let x = (p.0 as f64 * scale + tx).floor() as i64;
        let y = (p.1 as f64 * scale + ty).floor() as i64;
        if x < 0 || y < 0 || x >= 48 || y >= 38 {
            continue;
        }
        g[(y * 6 + x / 8) as usize] |= 1 << (x % 8);
    }
}

fn pec_value(w: &mut W, v: i32, long: bool, flag: u8) {
    if !long && v > -64 && v < 63 {
        w.u8((v & 0x7F) as u8);
    } else {
        let mut x = (v & 0x0FFF) as u16;
        x |= 0x8000;
        x |= (flag as u16) << 8;
        w.u8((x >> 8) as u8);
        w.u8(x as u8);
    }
}

/// The PEC section (header, stitches, icons). Returns the colour index list with its leading
/// count byte, as the PES addendum repeats it.
fn write_pec(w: &mut W, p: &Plan, s: &[(i32, i32, u8)], name: &str) -> Vec<u8> {
    let ext = bounds(s);
    let threads: Vec<Thread> = p.blocks.iter().map(|b| b.thread.clone()).collect();
    let label = format!("LA:{:<16}\r", design_name(name));
    w.bytes(label.as_bytes());
    w.bytes(&[0x20; 12]);
    w.bytes(&[0xFF, 0x00]);
    w.u8(6);
    w.u8(38);
    let mut list = pec_indices(&threads);
    let count = list.len();
    if count != 0 {
        w.bytes(&[0x20; 12]);
        list.insert(0, (count - 1) as u8);
        w.bytes(&list);
    } else {
        w.bytes(&[0x20, 0x20, 0x20, 0x20, 0x64, 0x20, 0x00, 0x20, 0x00, 0x20, 0x20, 0x20, 0xFF]);
    }
    for _ in count..463 {
        w.u8(0x20);
    }
    // stitch block
    let start = w.pos();
    w.bytes(&[0x00, 0x00]);
    w.u24(0);
    w.bytes(&[0x31, 0xFF, 0xF0]);
    w.i16(ext.2 - ext.0);
    w.i16(ext.3 - ext.1);
    w.u16(0x1E0);
    w.u16(0x1B0);
    let (mut xx, mut yy) = (0i32, 0i32);
    let mut jumping = true;
    let mut init = true;
    let mut colour_two = true;
    let mut trim_pending = false;
    for c in s {
        let (dx, dy) = (c.0 - xx, c.1 - yy);
        match c.2 {
            ST => {
                if jumping {
                    if dx != 0 && dy != 0 {
                        pec_value(w, 0, false, 0);
                        pec_value(w, 0, false, 0);
                    }
                    jumping = false;
                }
                pec_value(w, dx, false, 0);
                pec_value(w, dy, false, 0);
                xx += dx;
                yy += dy;
            }
            JUMP => {
                jumping = true;
                let flag = if !init && trim_pending { 0x20 } else { 0x10 };
                pec_value(w, dx, true, flag);
                pec_value(w, dy, true, flag);
                trim_pending = false;
                xx += dx;
                yy += dy;
            }
            TRIM => trim_pending = true,
            COLOR => {
                if jumping {
                    pec_value(w, 0, false, 0);
                    pec_value(w, 0, false, 0);
                    jumping = false;
                }
                w.bytes(&[0xFE, 0xB0, if colour_two { 0x02 } else { 0x01 }]);
                colour_two = !colour_two;
            }
            END => {
                w.u8(0xFF);
                break;
            }
            _ => {}
        }
        init = false;
    }
    let len = (w.pos() - start) as u32;
    w.patch_u24(start + 2, len);
    // icons: the whole design, then one per colour
    let mut all = ICON_BLANK;
    let stitches_of = |bi: Option<usize>| -> Vec<(i32, i32)> {
        let mut out = Vec::new();
        let mut b = 0;
        for c in s {
            match c.2 {
                COLOR => b += 1,
                ST if bi.map_or(true, |x| x == b) => out.push((c.0, c.1)),
                _ => {}
            }
        }
        out
    };
    draw_icon(ext, &stitches_of(None), &mut all, 4.0);
    w.bytes(&all);
    for bi in 0..p.blocks.len() {
        let mut g = ICON_BLANK;
        draw_icon(ext, &stitches_of(Some(bi)), &mut g, 5.0);
        w.bytes(&g);
    }
    list
}

fn pes_thread(w: &mut W, t: &Thread) {
    match t.pec {
        Some(i) if pec_rgb(i) == t.rgb => {
            w.str8(Some(&i.to_string()));
            w.bytes(&t.rgb);
            w.u8(0);
            w.u32(0xA);
            w.str8(Some(if t.name.is_empty() { pec_name(i) } else { &t.name }));
            w.str8(Some("Brother"));
            w.str8(Some("Brother"));
        }
        _ => {
            w.str8(None);
            w.bytes(&t.rgb);
            w.u8(0);
            w.u32(0xA);
            w.str8(Some(if t.name.is_empty() { "Custom" } else { &t.name }));
            w.str8(None);
            w.str8(None);
        }
    }
}

/// PES version 6 with the PEC block embedded.
pub fn write_pes(p: &Plan, name: &str) -> Vec<u8> {
    let s = stream(p);
    let mut w = W(Vec::new());
    w.bytes(b"#PES0060");
    let b = bounds(&s);
    let (left, top, right, bottom) = (b.0 as f64, b.1 as f64, b.2 as f64, b.3 as f64);
    let cx = (right + left) / 2.0;
    let cy = (bottom + top) / 2.0;
    let (l, t, r, bo) = (left - cx, top - cy, right - cx, bottom - cy);
    let pec_at = w.pos();
    w.u32(0);
    let has = s.iter().any(|c| c.2 == ST);
    // header
    w.u16(0x01);
    w.bytes(b"02");
    w.str8(Some(&design_name(name)));
    for _ in 0..4 {
        w.str8(None);
    }
    for v in [0u16, 0, 0x64, 0x64, 0, 0xC8, 0xC8, 0x64, 0x64, 0x64, 0x07, 0x13, 0x01, 0x01, 0x00, 100, 0x01, 0x00] {
        w.u16(v);
    }
    w.u8(0);
    for v in [1.0f32, 0.0, 0.0, 1.0, 0.0, 0.0] {
        w.f32(v);
    }
    w.u16(0);
    w.u16(0);
    w.u16(0);
    w.u16(p.blocks.len() as u16);
    for bl in &p.blocks {
        pes_thread(&mut w, &bl.thread);
    }
    w.u16(if has { 1 } else { 0 });
    if !has {
        w.u16(0);
        w.u16(0);
    } else {
        w.u16(0xFFFF);
        w.u16(0x0000);
        // CEmbOne
        w.str16("CEmbOne");
        let (width, height) = (r - l, bo - t);
        for _ in 0..8 {
            w.u16(0);
        }
        let tx = 350.0 + 1300.0 / 2.0 - width / 2.0;
        let ty = 100.0 + height + 1800.0 / 2.0 - height / 2.0;
        for v in [1.0f32, 0.0, 0.0, 1.0, tx as f32, ty as f32] {
            w.f32(v);
        }
        w.u16(1);
        w.u16(0);
        w.u16(0);
        w.i16(width as i32);
        w.i16(height as i32);
        w.bytes(&[0; 8]);
        let sections_at = w.pos();
        w.u16(0);
        w.u16(0xFFFF);
        w.u16(0x0000);
        w.str16("CSewSeg");
        // segments
        let adjust_x = (l + cx) as i32;
        let adjust_y = (bo + cy) as i32;
        let mut sections = 0u16;
        let mut colorlog: Vec<(u16, u16)> = Vec::new();
        let mut prev_code: i32 = -1;
        let mut flag_started = false;
        let (mut sx, mut sy) = (0i32, 0i32);
        let mut code = 0u16;
        let mut i = 0;
        while i < s.len() {
            let cmd = s[i].2;
            let mut j = i;
            while j < s.len() && s[j].2 == cmd {
                j += 1;
            }
            let run = &s[i..j];
            i = j;
            let (seg, flag): (Vec<(i32, i32)>, u16) = match cmd {
                JUMP => {
                    let last = run.last().unwrap();
                    (vec![(sx - adjust_x, sy - adjust_y), (last.0 - adjust_x, last.1 - adjust_y)], 1)
                }
                COLOR => {
                    code += 1;
                    continue;
                }
                ST => {
                    let v: Vec<(i32, i32)> = run.iter().map(|c| (c.0 - adjust_x, c.1 - adjust_y)).collect();
                    let last = run.last().unwrap();
                    sx = last.0;
                    sy = last.1;
                    (v, 0)
                }
                _ => continue,
            };
            if flag_started {
                w.u16(0x8003);
            }
            flag_started = true;
            if prev_code != code as i32 {
                colorlog.push((sections, code));
                prev_code = code as i32;
            }
            w.u16(flag);
            w.u16(code);
            w.u16(seg.len() as u16);
            for q in seg {
                w.i16(q.0);
                w.i16(q.1);
            }
            sections += 1;
        }
        w.u16(colorlog.len() as u16);
        for (sct, c) in &colorlog {
            w.u16(*sct);
            w.u16(*c);
        }
        w.patch_u16(sections_at, sections);
        w.u16(0);
        w.u16(0);
        w.u32(0);
        w.u32(0);
        for k in 0..colorlog.len() {
            w.u32(k as u32);
            w.u32(0);
        }
    }
    let here = w.pos() as u32;
    w.patch_u32(pec_at, here);
    let list = write_pec(&mut w, p, &s, name);
    // addendum: the colour list again, then the RGB of every block
    let count = list.len();
    w.bytes(&list);
    for _ in count..128 {
        w.u8(0x20);
    }
    for _ in &p.blocks {
        w.bytes(&[0u8; 0x90]);
    }
    for bl in &p.blocks {
        let c = bl.thread.rgb;
        w.u24(((c[0] as u32) << 16) | ((c[1] as u32) << 8) | c[2] as u32);
    }
    w.u16(0);
    w.0
}

pub fn write_pec_file(p: &Plan, name: &str) -> Vec<u8> {
    let s = stream(p);
    let mut w = W(Vec::new());
    w.bytes(b"#PEC0001");
    write_pec(&mut w, p, &s, name);
    w.0
}

fn dst_record(dx: i32, dy: i32, kind: u8) -> [u8; 3] {
    let (mut x, mut y) = (dx, -dy);
    let (mut b0, mut b1, mut b2) = (0u8, 0u8, 0u8);
    if kind == JUMP {
        b2 |= 0x80;
    }
    if kind == ST || kind == JUMP {
        b2 |= 0x03;
        if x > 40 {
            b2 |= 1 << 2;
            x -= 81;
        }
        if x < -40 {
            b2 |= 1 << 3;
            x += 81;
        }
        if x > 13 {
            b1 |= 1 << 2;
            x -= 27;
        }
        if x < -13 {
            b1 |= 1 << 3;
            x += 27;
        }
        if x > 4 {
            b0 |= 1 << 2;
            x -= 9;
        }
        if x < -4 {
            b0 |= 1 << 3;
            x += 9;
        }
        if x > 1 {
            b1 |= 1 << 0;
            x -= 3;
        }
        if x < -1 {
            b1 |= 1 << 1;
            x += 3;
        }
        if x > 0 {
            b0 |= 1 << 0;
            x -= 1;
        }
        if x < 0 {
            b0 |= 1 << 1;
            x += 1;
        }
        if y > 40 {
            b2 |= 1 << 5;
            y -= 81;
        }
        if y < -40 {
            b2 |= 1 << 4;
            y += 81;
        }
        if y > 13 {
            b1 |= 1 << 5;
            y -= 27;
        }
        if y < -13 {
            b1 |= 1 << 4;
            y += 27;
        }
        if y > 4 {
            b0 |= 1 << 5;
            y -= 9;
        }
        if y < -4 {
            b0 |= 1 << 4;
            y += 9;
        }
        if y > 1 {
            b1 |= 1 << 7;
            y -= 3;
        }
        if y < -1 {
            b1 |= 1 << 6;
            y += 3;
        }
        if y > 0 {
            b0 |= 1 << 7;
            y -= 1;
        }
        if y < 0 {
            b0 |= 1 << 6;
            y += 1;
        }
        debug_assert!(x == 0 && y == 0);
    } else if kind == COLOR {
        b2 = 0xC3;
    } else if kind == END {
        b2 = 0xF3;
    }
    [b0, b1, b2]
}

/// Tajima DST: 512-byte header, 3-byte records of at most 12.1 mm; a trim is three jumps.
pub fn write_dst(p: &Plan, name: &str) -> Vec<u8> {
    let s = stream(p);
    // records (moves split to 121 units)
    let mut recs: Vec<[u8; 3]> = Vec::new();
    let (mut xx, mut yy) = (0i32, 0i32);
    for c in &s {
        match c.2 {
            ST | JUMP => {
                let (dx, dy) = (c.0 - xx, c.1 - yy);
                let n = ((dx.abs().max(dy.abs()) as f32) / 121.0).ceil().max(1.0) as i32;
                let (mut px, mut py) = (0, 0);
                for k in 1..=n {
                    let tx = (dx as f64 * k as f64 / n as f64).round() as i32;
                    let ty = (dy as f64 * k as f64 / n as f64).round() as i32;
                    recs.push(dst_record(tx - px, ty - py, c.2));
                    px = tx;
                    py = ty;
                }
                xx = c.0;
                yy = c.1;
            }
            TRIM => {
                recs.push(dst_record(2, 2, JUMP));
                recs.push(dst_record(-4, -4, JUMP));
                recs.push(dst_record(2, 2, JUMP));
            }
            COLOR => recs.push(dst_record(0, 0, COLOR)),
            END => recs.push(dst_record(0, 0, END)),
            _ => {}
        }
    }
    let b = bounds(&s);
    let last = s.iter().rev().find(|c| c.2 != END).copied().unwrap_or((0, 0, ST));
    let (ax, ay) = (last.0, -last.1);
    let mut h = String::new();
    h.push_str(&format!("LA:{:<16}\r", design_name(name)));
    h.push_str(&format!("ST:{:>7}\r", recs.len()));
    h.push_str(&format!("CO:{:>3}\r", p.blocks.len().saturating_sub(1)));
    h.push_str(&format!("+X:{:>5}\r", b.2.abs()));
    h.push_str(&format!("-X:{:>5}\r", b.0.abs()));
    h.push_str(&format!("+Y:{:>5}\r", b.3.abs()));
    h.push_str(&format!("-Y:{:>5}\r", b.1.abs()));
    h.push_str(&if ax >= 0 { format!("AX:+{:>5}\r", ax) } else { format!("AX:-{:>5}\r", ax.abs()) });
    h.push_str(&if ay >= 0 { format!("AY:+{:>5}\r", ay) } else { format!("AY:-{:>5}\r", ay.abs()) });
    h.push_str("MX:+    0\r");
    h.push_str("MY:+    0\r");
    h.push_str("PD:******\r");
    let mut out = h.into_bytes();
    out.push(0x1A);
    while out.len() < 512 {
        out.push(0x20);
    }
    for r in recs {
        out.extend_from_slice(&r);
    }
    out
}

// ------------------------------------------------------------------ reading

struct R<'a> {
    b: &'a [u8],
    i: usize,
}
impl<'a> R<'a> {
    fn u8(&mut self) -> Option<u8> {
        let v = *self.b.get(self.i)?;
        self.i += 1;
        Some(v)
    }
    fn u16(&mut self) -> Option<u16> {
        Some(self.u8()? as u16 | (self.u8()? as u16) << 8)
    }
    fn u24(&mut self) -> Option<u32> {
        Some(self.u8()? as u32 | (self.u8()? as u32) << 8 | (self.u8()? as u32) << 16)
    }
    fn u32(&mut self) -> Option<u32> {
        Some(self.u16()? as u32 | (self.u16()? as u32) << 16)
    }
    fn skip(&mut self, n: usize) {
        self.i += n;
    }
    fn str8(&mut self) -> Option<String> {
        let n = self.u8()? as usize;
        if n == 0 {
            return Some(String::new());
        }
        let s = self.b.get(self.i..self.i + n)?;
        self.i += n;
        Some(String::from_utf8_lossy(s).into_owned())
    }
}

fn pes_threads(r: &mut R, version: u32) -> Option<Vec<Thread>> {
    r.skip(4);
    for _ in 0..5 {
        r.str8()?;
    }
    r.skip(if version >= 6 { 36 } else { 24 });
    r.str8()?;
    r.skip(24);
    if r.u16()? != 0 || r.u16()? != 0 || r.u16()? != 0 {
        return None;
    }
    let n = r.u16()? as usize;
    let mut out = Vec::new();
    for _ in 0..n {
        let cat = r.str8()?;
        let (red, g, b) = (r.u8()?, r.u8()?, r.u8()?);
        r.skip(5);
        let desc = r.str8()?;
        let brand = r.str8()?;
        let _chart = r.str8()?;
        let pec = cat.trim().parse::<usize>().ok().filter(|i| brand == "Brother" && (1..=64).contains(i) && pec_rgb(*i) == [red, g, b]);
        out.push(Thread { rgb: [red, g, b], pec, name: desc });
    }
    Some(out)
}

fn signed12(v: u16) -> i32 {
    let v = (v & 0xFFF) as i32;
    if v > 0x7FF {
        v - 0x1000
    } else {
        v
    }
}

fn signed7(v: u8) -> i32 {
    if v > 63 {
        v as i32 - 128
    } else {
        v as i32
    }
}

fn read_pec(data: &[u8], at: usize, chart: Option<Vec<Thread>>) -> Result<Plan, String> {
    let mut r = R { b: data, i: at };
    r.skip(3 + 16 + 15);
    let _stride = r.u8().ok_or("PEC: short file")?;
    let _height = r.u8().ok_or("PEC: short file")?;
    r.skip(12);
    let cc = r.u8().ok_or("PEC: short file")? as usize;
    let count = cc + 1;
    let mut idx = Vec::new();
    for _ in 0..count {
        idx.push(r.u8().ok_or("PEC: short file")?);
    }
    r.skip(0x1D0 - cc);
    let _len = r.u24().ok_or("PEC: short file")?;
    r.skip(0x0B);
    // threads: one per colour block from the PES chart when it covers them, else the palette
    let threads: Vec<Thread> = match chart {
        Some(c) if c.len() >= count => c,
        _ => idx
            .iter()
            .map(|&i| {
                let i = (i as usize % 65).max(1);
                Thread { rgb: pec_rgb(i), pec: Some(i), name: pec_name(i).to_string() }
            })
            .collect(),
    };
    let mut blocks: Vec<Block> = vec![Block { thread: threads[0].clone(), cmds: Vec::new(), stop: false }];
    let (mut x, mut y) = (0i32, 0i32);
    loop {
        let Some(v1) = r.u8() else { break };
        let Some(mut v2) = r.u8() else { break };
        if v1 == 0xFF && v2 == 0x00 {
            break;
        }
        if v1 == 0xFF {
            break;
        }
        if v1 == 0xFE && v2 == 0xB0 {
            r.skip(1);
            let n = blocks.len();
            let t = threads.get(n).cloned().unwrap_or_else(|| threads[n % threads.len()].clone());
            if blocks.last().unwrap().thread == t {
                blocks.last_mut().unwrap().stop = true;
            }
            blocks.push(Block { thread: t, cmds: Vec::new(), stop: false });
            continue;
        }
        let (mut jump, mut trim) = (false, false);
        let dx;
        if v1 & 0x80 != 0 {
            trim |= v1 & 0x20 != 0;
            jump |= v1 & 0x10 != 0;
            dx = signed12(((v1 as u16) << 8) | v2 as u16);
            v2 = match r.u8() {
                Some(v) => v,
                None => break,
            };
        } else {
            dx = signed7(v1);
        }
        let dy;
        if v2 & 0x80 != 0 {
            trim |= v2 & 0x20 != 0;
            jump |= v2 & 0x10 != 0;
            let Some(v3) = r.u8() else { break };
            dy = signed12(((v2 as u16) << 8) | v3 as u16);
        } else {
            dy = signed7(v2);
        }
        x += dx;
        y += dy;
        let p = (x as f32 / 10.0, y as f32 / 10.0);
        let b = &mut blocks.last_mut().unwrap().cmds;
        if trim {
            let last = b.last().map(|c| (c.0, c.1)).unwrap_or(p);
            b.push((last.0, last.1, TRIM));
            b.push((p.0, p.1, JUMP));
        } else if jump {
            b.push((p.0, p.1, JUMP));
        } else {
            b.push((p.0, p.1, ST));
        }
    }
    blocks.retain(|b| b.cmds.iter().any(|c| c.2 == ST));
    if blocks.is_empty() {
        return Err("no stitches in this design".into());
    }
    Ok(Plan { blocks })
}

fn read_dst(data: &[u8]) -> Result<Plan, String> {
    if data.len() < 512 {
        return Err("DST: short file".into());
    }
    let bit = |b: u8, n: u8| ((b >> n) & 1) as i32;
    let mut i = 512;
    let palette = [20usize, 5, 2, 13, 3, 29, 7, 12, 24, 16];
    let mk = |n: usize| {
        let p = palette[n % palette.len()];
        Thread { rgb: pec_rgb(p), pec: Some(p), name: pec_name(p).to_string() }
    };
    let mut blocks = vec![Block { thread: mk(0), cmds: Vec::new(), stop: false }];
    let (mut x, mut y) = (0i32, 0i32);
    let mut jumps_in_row = 0;
    while i + 3 <= data.len() {
        let (b0, b1, b2) = (data[i], data[i + 1], data[i + 2]);
        i += 3;
        let dx = bit(b2, 2) * 81 - bit(b2, 3) * 81 + bit(b1, 2) * 27 - bit(b1, 3) * 27 + bit(b0, 2) * 9 - bit(b0, 3) * 9 + bit(b1, 0) * 3 - bit(b1, 1) * 3 + bit(b0, 0) - bit(b0, 1);
        let dy = -(bit(b2, 5) * 81 - bit(b2, 4) * 81 + bit(b1, 5) * 27 - bit(b1, 4) * 27 + bit(b0, 5) * 9 - bit(b0, 4) * 9 + bit(b1, 7) * 3 - bit(b1, 6) * 3 + bit(b0, 7) - bit(b0, 6));
        if b2 & 0xF3 == 0xF3 {
            break;
        }
        if b2 & 0xC3 == 0xC3 {
            let n = blocks.len();
            blocks.push(Block { thread: mk(n), cmds: Vec::new(), stop: false });
            jumps_in_row = 0;
            continue;
        }
        x += dx;
        y += dy;
        let p = (x as f32 / 10.0, y as f32 / 10.0);
        let b = &mut blocks.last_mut().unwrap().cmds;
        if b2 & 0x83 == 0x83 {
            jumps_in_row += 1;
            // three jumps in a row are a trim
            if jumps_in_row == 3 {
                let at = b.len() - 2;
                let q = (b[at].0, b[at].1);
                b.insert(at, (q.0, q.1, TRIM));
            }
            b.push((p.0, p.1, JUMP));
        } else {
            jumps_in_row = 0;
            b.push((p.0, p.1, ST));
        }
    }
    blocks.retain(|b| b.cmds.iter().any(|c| c.2 == ST));
    if blocks.is_empty() {
        return Err("no stitches in this design".into());
    }
    Ok(Plan { blocks })
}

/// Read a PES, PEC or DST design (format from the content).
pub fn read(data: &[u8]) -> Result<Plan, String> {
    if data.starts_with(b"#PEC0001") {
        return read_pec(data, 8, None);
    }
    if data.starts_with(b"#PES") {
        let ver: u32 = std::str::from_utf8(&data[4..8]).ok().and_then(|v| v.parse().ok()).unwrap_or(1);
        let mut r = R { b: data, i: 8 };
        let pec_at = r.u32().ok_or("PES: short file")? as usize;
        let chart = if ver == 60 || (50..=56).contains(&ver) { pes_threads(&mut r, if ver == 60 { 6 } else { 5 }) } else { None };
        if pec_at >= data.len() {
            return Err("PES: bad PEC offset".into());
        }
        return read_pec(data, pec_at, chart);
    }
    if data.len() >= 512 && data.starts_with(b"LA:") {
        return read_dst(data);
    }
    Err("not a PES, PEC or DST design".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sample() -> Plan {
        let red = Thread { rgb: [237, 23, 31], pec: Some(5), name: "Red".into() };
        let black = Thread { rgb: [0, 0, 0], pec: Some(20), name: "Black".into() };
        let mut a = vec![(-10.0, -10.0, JUMP), (-10.0, -10.0, ST)];
        for i in 0..50 {
            a.push((-10.0 + i as f32 * 0.4, if i % 2 == 0 { -10.0 } else { -5.0 }, ST));
        }
        a.push((10.0, 10.0, TRIM));
        a.push((15.0, 12.0, JUMP));
        a.push((15.0, 12.0, ST));
        a.push((18.0, 12.0, ST));
        let b = vec![(0.0, 20.0, JUMP), (0.0, 20.0, ST), (3.5, 20.0, ST), (6.9, 21.0, ST)];
        Plan { blocks: vec![Block { thread: red, cmds: a, stop: false }, Block { thread: black, cmds: b, stop: false }] }
    }
    #[test]
    fn pes_roundtrip() {
        let p = sample();
        let bytes = write_pes(&p, "test");
        assert!(bytes.starts_with(b"#PES0060"));
        let back = read(&bytes).unwrap();
        assert_eq!(back.blocks.len(), 2);
        assert_eq!(back.blocks[0].thread.rgb, [237, 23, 31]);
        assert_eq!(back.stitch_count(), p.stitch_count());
        let (b0, b1) = (p.bounds(), back.bounds());
        assert!((b0.2 - b1.2).abs() < 0.11 && (b0.1 - b1.1).abs() < 0.11, "{:?} {:?}", b0, b1);
        assert_eq!(write_pes(&p, "test"), bytes);
    }
    #[test]
    fn dst_roundtrip() {
        let p = sample();
        let bytes = write_dst(&p, "test");
        assert_eq!(bytes.len() % 3, 512 % 3);
        let back = read(&bytes).unwrap();
        assert_eq!(back.blocks.len(), 2);
        assert_eq!(back.stitch_count(), p.stitch_count());
        assert_eq!(back.count(TRIM), 1);
    }
}
