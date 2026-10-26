//! WebP files: the RIFF container, still images (lossy VP8 with an optional ALPH alpha plane,
//! or lossless VP8L), and animations (ANIM/ANMF, composited frame by frame). Saving writes
//! lossless VP8L, one frame or an animation.

use crate::gif::Frames;
use crate::{vp8, vp8l};

const MAX_CANVAS: usize = 100_000_000; // pixels

pub fn is_webp(d: &[u8]) -> bool {
    d.len() >= 16 && &d[..4] == b"RIFF" && &d[8..12] == b"WEBP"
}

fn u24(d: &[u8]) -> usize {
    d[0] as usize | (d[1] as usize) << 8 | (d[2] as usize) << 16
}

/// The chunks of a RIFF body: (fourcc, payload).
fn chunks(d: &[u8]) -> Vec<([u8; 4], &[u8])> {
    let mut out = Vec::new();
    let mut p = 0;
    while p + 8 <= d.len() {
        let id = [d[p], d[p + 1], d[p + 2], d[p + 3]];
        let n = u32::from_le_bytes([d[p + 4], d[p + 5], d[p + 6], d[p + 7]]) as usize;
        let s = p + 8;
        let e = s.saturating_add(n).min(d.len());
        out.push((id, &d[s..e]));
        p = s.saturating_add(n).saturating_add(n & 1);
    }
    out
}

/// Undo an ALPH filter in place.
fn unfilter(a: &mut [u8], w: usize, h: usize, method: u8) {
    if method == 0 {
        return;
    }
    for y in 0..h {
        for x in 0..w {
            if x == 0 && y == 0 {
                continue;
            }
            let i = y * w + x;
            let pred = if y == 0 {
                a[i - 1]
            } else if x == 0 {
                a[i - w]
            } else {
                match method {
                    1 => a[i - 1],
                    2 => a[i - w],
                    _ => (a[i - 1] as i32 + a[i - w] as i32 - a[i - w - 1] as i32).clamp(0, 255) as u8,
                }
            };
            a[i] = a[i].wrapping_add(pred);
        }
    }
}

fn alpha_plane(d: &[u8], w: usize, h: usize) -> Result<Vec<u8>, String> {
    if d.is_empty() {
        return Err("WebP: empty alpha".into());
    }
    let comp = d[0] & 3;
    let filter = (d[0] >> 2) & 3;
    let mut a = match comp {
        0 => {
            let mut v = d[1..].to_vec();
            v.resize(w * h, 255);
            v
        }
        1 => vp8l::decode_stream(&d[1..], w, h)?.iter().map(|p| (p >> 8) as u8).collect(),
        _ => return Err("WebP: unknown alpha compression".into()),
    };
    unfilter(&mut a, w, h, filter);
    Ok(a)
}

/// One picture from a run of chunks (ALPH? then VP8, or VP8L).
fn picture(cs: &[([u8; 4], &[u8])]) -> Result<(usize, usize, Vec<u8>), String> {
    let mut alph: Option<&[u8]> = None;
    for (id, body) in cs {
        match id {
            b"ALPH" => alph = Some(body),
            b"VP8L" => return vp8l::decode(body),
            b"VP8 " => {
                let (w, h, mut px) = vp8::decode(body)?;
                if let Some(a) = alph {
                    // a damaged alpha plane leaves the picture opaque rather than failing
                    if let Ok(a) = alpha_plane(a, w, h) {
                        for (p, v) in px.chunks_exact_mut(4).zip(a) {
                            p[3] = v;
                        }
                    }
                }
                return Ok((w, h, px));
            }
            _ => {}
        }
    }
    Err("WebP: no image data".into())
}

/// Every frame composited onto the canvas (a still image is one frame).
pub fn decode_frames(d: &[u8]) -> Result<Frames, String> {
    if !is_webp(d) {
        return Err("not a WebP file".into());
    }
    let size = (u32::from_le_bytes([d[4], d[5], d[6], d[7]]) as usize).saturating_add(8).min(d.len());
    let cs = chunks(&d[12..size]);
    let Some((first, _)) = cs.first() else { return Err("WebP: empty file".into()) };
    if first != b"VP8X" {
        let (w, h, px) = picture(&cs)?;
        return Ok(Frames { w, h, frames: vec![(px, 0)], loop_count: None, truncated: false });
    }
    let x = cs[0].1;
    if x.len() < 10 {
        return Err("WebP: bad extended header".into());
    }
    let animated = x[0] & 0x02 != 0;
    let cw = u24(&x[4..]) + 1;
    let ch = u24(&x[7..]) + 1;
    if cw * ch > MAX_CANVAS {
        return Err("WebP: picture too large".into());
    }
    if !animated {
        let (w, h, px) = picture(&cs[1..])?;
        return Ok(Frames { w, h, frames: vec![(px, 0)], loop_count: None, truncated: false });
    }
    let mut loop_count = Some(0u16);
    let mut canvas = vec![0u8; cw * ch * 4];
    let mut frames = Vec::new();
    let mut truncated = false;
    let mut total = 0usize;
    for (id, body) in &cs[1..] {
        if id == b"ANIM" && body.len() >= 6 {
            loop_count = Some(u16::from_le_bytes([body[4], body[5]]));
            continue;
        }
        if id != b"ANMF" || body.len() < 16 {
            continue;
        }
        let fx = u24(&body[0..]) * 2;
        let fy = u24(&body[3..]) * 2;
        let dur = u24(&body[12..]) as u32;
        let flags = body[15];
        let blend = flags & 0x02 == 0;
        let dispose = flags & 0x01 != 0;
        let sub = chunks(&body[16..]);
        let (fw, fh, px) = match picture(&sub) {
            Ok(p) => p,
            Err(_) => continue,
        };
        // composite
        for y in 0..fh {
            let cy = fy + y;
            if cy >= ch {
                break;
            }
            for x in 0..fw {
                let cx = fx + x;
                if cx >= cw {
                    break;
                }
                let s = &px[(y * fw + x) * 4..(y * fw + x) * 4 + 4];
                let o = (cy * cw + cx) * 4;
                if !blend || s[3] == 255 {
                    canvas[o..o + 4].copy_from_slice(s);
                } else if s[3] > 0 {
                    let sa = s[3] as u32;
                    let da = canvas[o + 3] as u32 * (255 - sa) / 255;
                    let oa = sa + da;
                    for k in 0..3 {
                        canvas[o + k] = ((s[k] as u32 * sa + canvas[o + k] as u32 * da) / oa) as u8;
                    }
                    canvas[o + 3] = oa as u8;
                }
            }
        }
        total += canvas.len();
        if total > 1 << 30 {
            truncated = true;
            break;
        }
        frames.push((canvas.clone(), dur));
        if dispose {
            for y in fy..(fy + fh).min(ch) {
                for x in fx..(fx + fw).min(cw) {
                    let o = (y * cw + x) * 4;
                    canvas[o..o + 4].fill(0);
                }
            }
        }
    }
    if frames.is_empty() {
        return Err("WebP: no frames".into());
    }
    Ok(Frames { w: cw, h: ch, frames, loop_count, truncated })
}

/// The first frame (what a still viewer shows).
pub fn decode(d: &[u8]) -> Result<crate::png::Image, String> {
    let f = decode_frames(d)?;
    let (px, _) = f.frames.into_iter().next().unwrap();
    Ok(crate::png::Image { w: f.w, h: f.h, px })
}

fn put_chunk(out: &mut Vec<u8>, id: &[u8; 4], body: &[u8]) {
    out.extend_from_slice(id);
    out.extend_from_slice(&(body.len() as u32).to_le_bytes());
    out.extend_from_slice(body);
    if body.len() & 1 == 1 {
        out.push(0);
    }
}

fn riff(body: Vec<u8>) -> Vec<u8> {
    let mut out = Vec::with_capacity(body.len() + 12);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&(body.len() as u32 + 4).to_le_bytes());
    out.extend_from_slice(b"WEBP");
    out.extend_from_slice(&body);
    out
}

fn le24(v: usize) -> [u8; 3] {
    [v as u8, (v >> 8) as u8, (v >> 16) as u8]
}

/// A still image, lossless.
pub fn encode(w: usize, h: usize, rgba: &[u8]) -> Vec<u8> {
    let mut body = Vec::new();
    put_chunk(&mut body, b"VP8L", &vp8l::encode(w, h, rgba));
    riff(body)
}

/// An animation, lossless; every frame covers the canvas.
pub fn encode_animation(w: usize, h: usize, frames: &[(&[u8], u32)], loop_count: Option<u16>) -> Vec<u8> {
    let mut body = Vec::new();
    let alpha = frames.iter().any(|(f, _)| f.chunks_exact(4).any(|p| p[3] != 255));
    let mut x = vec![0x02 | if alpha { 0x10 } else { 0 }, 0, 0, 0];
    x.extend_from_slice(&le24(w - 1));
    x.extend_from_slice(&le24(h - 1));
    put_chunk(&mut body, b"VP8X", &x);
    let mut anim = vec![0, 0, 0, 0];
    // no loop extension in a GIF means play once; WebP has no "once" besides a count of 1
    anim.extend_from_slice(&loop_count.unwrap_or(1).to_le_bytes());
    put_chunk(&mut body, b"ANIM", &anim);
    for (px, dur) in frames {
        let mut f = Vec::new();
        f.extend_from_slice(&le24(0));
        f.extend_from_slice(&le24(0));
        f.extend_from_slice(&le24(w - 1));
        f.extend_from_slice(&le24(h - 1));
        f.extend_from_slice(&le24((*dur as usize).min(0xff_ffff)));
        f.push(0x02); // replace, don't blend; no disposal
        put_chunk(&mut f, b"VP8L", &vp8l::encode(w, h, px));
        put_chunk(&mut body, b"ANMF", &f);
    }
    riff(body)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pattern(w: usize, h: usize, t: u8) -> Vec<u8> {
        let mut v = Vec::new();
        for y in 0..h {
            for x in 0..w {
                v.extend_from_slice(&[(x * 9) as u8 ^ t, (y * 7) as u8, ((x + y) * 3) as u8, if (x / 4 + y / 4) % 3 == 0 { 0 } else { 200 + (x % 50) as u8 }]);
            }
        }
        v
    }

    #[test]
    fn still_round_trip() {
        let px = pattern(37, 21, 0);
        let f = decode_frames(&encode(37, 21, &px)).unwrap();
        assert_eq!((f.w, f.h, f.frames.len()), (37, 21, 1));
        // fully transparent pixels may lose their colour
        for (a, b) in f.frames[0].0.chunks(4).zip(px.chunks(4)) {
            if b[3] != 0 {
                assert_eq!(a, b);
            } else {
                assert_eq!(a[3], 0);
            }
        }
    }

    #[test]
    fn animation_round_trip() {
        let a = pattern(16, 9, 0);
        let b = pattern(16, 9, 0x55);
        let f = decode_frames(&encode_animation(16, 9, &[(&a, 80), (&b, 120)], Some(3))).unwrap();
        assert_eq!(f.frames.len(), 2);
        assert_eq!(f.frames[1].1, 120);
        assert_eq!(f.loop_count, Some(3));
        let i = (4 * 16 + 5) * 4;
        assert_eq!(&f.frames[1].0[i..i + 4], &b[i..i + 4]);
    }

    #[test]
    fn alpha_filters() {
        let (w, h) = (5, 4);
        let orig: Vec<u8> = (0..w * h).map(|i| (i * 37 % 251) as u8).collect();
        for m in 1..4u8 {
            // filter forwards, then undo
            let mut f = orig.clone();
            for y in (0..h).rev() {
                for x in (0..w).rev() {
                    if x == 0 && y == 0 {
                        continue;
                    }
                    let i = y * w + x;
                    let pred = if y == 0 { orig[i - 1] } else if x == 0 { orig[i - w] } else {
                        match m { 1 => orig[i - 1], 2 => orig[i - w], _ => (orig[i - 1] as i32 + orig[i - w] as i32 - orig[i - w - 1] as i32).clamp(0, 255) as u8 }
                    };
                    f[i] = orig[i].wrapping_sub(pred);
                }
            }
            unfilter(&mut f, w, h, m);
            assert_eq!(f, orig, "filter {m}");
        }
    }
}

/// Decodes every .webp in $WEBP_DIR to <name>.rgba (u32 w, u32 h, frame count, then RGBA
/// frames), for comparing against a reference decoder outside the build.
#[cfg(test)]
#[test]
#[ignore]
fn dump_for_oracle() {
    let Ok(dir) = std::env::var("WEBP_DIR") else { return };
    for e in std::fs::read_dir(&dir).unwrap() {
        let p = e.unwrap().path();
        if p.extension().map_or(true, |x| x != "webp") {
            continue;
        }
        let d = std::fs::read(&p).unwrap();
        let mut out = Vec::new();
        match decode_frames(&d) {
            Ok(f) => {
                out.extend_from_slice(&(f.w as u32).to_le_bytes());
                out.extend_from_slice(&(f.h as u32).to_le_bytes());
                out.extend_from_slice(&(f.frames.len() as u32).to_le_bytes());
                for (px, _) in &f.frames {
                    out.extend_from_slice(px);
                }
                let enc = if f.frames.len() == 1 {
                    encode(f.w, f.h, &f.frames[0].0)
                } else {
                    let refs: Vec<(&[u8], u32)> = f.frames.iter().map(|(p, d)| (p.as_slice(), *d)).collect();
                    encode_animation(f.w, f.h, &refs, f.loop_count)
                };
                std::fs::write(p.with_extension("enc"), enc).unwrap();
            }
            Err(e) => out.extend_from_slice(format!("ERR {e}").as_bytes()),
        }
        std::fs::write(p.with_extension("rgba"), out).unwrap();
    }
}
