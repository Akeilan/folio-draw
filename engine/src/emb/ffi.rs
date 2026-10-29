//! C ABI for the embroidery engine. Strings cross as JSON; returned strings are owned by the
//! caller and given back with fd_emb_free_str.

use super::convert::{convert, place, Params};
use super::formats;
use super::geom::Ring;
use super::json::{parse, J};
use super::plan::{blocks_json, plan, Plan};
use super::raster::{Img, Mask};
use super::trace::trace_mask;
use crate::doc::Doc;
use crate::{cstr, guard, set_error};
use std::ffi::{c_char, CString};

fn out_str(s: String) -> *mut c_char {
    CString::new(s.replace('\0', " ")).map(|c| c.into_raw()).unwrap_or(std::ptr::null_mut())
}

fn parse_or_err(s: &str) -> Option<J> {
    match parse(s) {
        Ok(j) => Some(j),
        Err(e) => {
            set_error(&e);
            None
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_emb_free_str(p: *mut c_char) {
    if !p.is_null() {
        drop(CString::from_raw(p));
    }
}

/// The document's embroidery settings (JSON; empty for an ordinary picture).
#[no_mangle]
pub unsafe extern "C" fn fd_emb_get(p: *mut Doc) -> *mut c_char {
    match p.as_ref() {
        Some(d) => out_str(d.emb.clone()),
        None => out_str(String::new()),
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_note(p: *mut Doc) -> *mut c_char {
    match p.as_ref() {
        Some(d) => out_str(d.note.clone()),
        None => out_str(String::new()),
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_emb_set(p: *mut Doc, s: *const c_char) {
    if let Some(d) = p.as_mut() {
        d.emb = cstr(s);
        d.changes += 1;
    }
}

/// Fit a picture to the hoop: `out` receives cw×ch RGBA. Returns JSON {bg, upscale, rect}.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_place(src: *const u8, sw: u32, sh: u32, cw: u32, ch: u32, s: f32, margin: f32, crop: u32, out: *mut u8) -> *mut c_char {
    guard(std::ptr::null_mut(), || {
        if src.is_null() || out.is_null() || sw == 0 || sh == 0 || cw == 0 || ch == 0 {
            set_error("empty picture");
            return std::ptr::null_mut();
        }
        let img = Img { w: sw as usize, h: sh as usize, px: std::slice::from_raw_parts(src, (sw * sh * 4) as usize).to_vec() };
        let pl = place(&img, cw as usize, ch as usize, s, margin, crop != 0);
        std::ptr::copy_nonoverlapping(pl.img.px.as_ptr(), out, pl.img.px.len());
        let mut j = J::obj();
        if let Some(b) = pl.bg {
            j.set("bg", J::Arr(b.iter().map(|v| J::from(*v as i64)).collect()));
        }
        j.set("upscale", J::from(pl.upscale));
        j.set("rect", J::Arr(vec![J::from(pl.rect.0), J::from(pl.rect.1), J::from(pl.rect.2), J::from(pl.rect.3)]));
        out_str(j.dump())
    })
}

/// Picture → shapes. Returns JSON {shapes:[{rings, thread, area}], colours:[...]}.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_convert(px: *const u8, w: u32, h: u32, s: f32, x0: f32, y0: f32, params: *const c_char) -> *mut c_char {
    guard(std::ptr::null_mut(), || {
        if px.is_null() || w == 0 || h == 0 {
            set_error("empty picture");
            return std::ptr::null_mut();
        }
        let Some(pj) = parse_or_err(&cstr(params)) else { return std::ptr::null_mut() };
        let img = Img { w: w as usize, h: h as usize, px: std::slice::from_raw_parts(px, (w * h * 4) as usize).to_vec() };
        let c = convert(&img, s, x0, y0, &Params::from_json(&pj));
        let mut j = J::obj();
        j.set("shapes", J::Arr(c.shapes));
        j.set("colours", J::Arr(c.colours));
        out_str(j.dump())
    })
}

/// The stitch plan for a design (JSON: settings + layers of objects, bottom layer first).
#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan(design: *const c_char) -> *mut Plan {
    guard(std::ptr::null_mut(), || {
        let Some(j) = parse_or_err(&cstr(design)) else { return std::ptr::null_mut() };
        Box::into_raw(Box::new(plan(&j)))
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_free(p: *mut Plan) {
    if !p.is_null() {
        drop(Box::from_raw(p));
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_info(p: *mut Plan) -> *mut c_char {
    match p.as_ref() {
        Some(pl) => out_str(pl.info().dump()),
        None => out_str("{}".into()),
    }
}

/// Number of commands in the plan (all blocks).
#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_len(p: *mut Plan) -> u32 {
    p.as_ref().map(|pl| pl.blocks.iter().map(|b| b.cmds.len()).sum::<usize>() as u32).unwrap_or(0)
}

/// Commands as floats: x, y (mm), command (0 stitch, 1 jump, 2 trim), block index.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_cmds(p: *mut Plan, out: *mut f32) {
    let Some(pl) = p.as_ref() else { return };
    if out.is_null() {
        return;
    }
    let mut k = 0usize;
    for (bi, b) in pl.blocks.iter().enumerate() {
        for c in &b.cmds {
            *out.add(k) = c.0;
            *out.add(k + 1) = c.1;
            *out.add(k + 2) = c.2 as f32;
            *out.add(k + 3) = bi as f32;
            k += 4;
        }
    }
}

/// The plan as stitch-object JSON (blocks with their threads and commands).
#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_json(p: *mut Plan) -> *mut c_char {
    match p.as_ref() {
        Some(pl) => out_str(blocks_json(pl).dump()),
        None => out_str("{}".into()),
    }
}

/// Write a machine file (fmt 0 PES, 1 DST, 2 PEC). It is written under a temporary name with
/// the same extension, read back and compared (stitch count within 1 %, size within 0.5 mm),
/// then renamed into place. Returns 0, or -1 with fd_last_error.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_plan_write(p: *mut Plan, path: *const c_char, fmt: u32, name: *const c_char) -> i32 {
    let path = cstr(path);
    let name = cstr(name);
    guard(-1, || {
        let Some(pl) = p.as_ref() else {
            set_error("no design");
            return -1;
        };
        if pl.stitch_count() == 0 {
            set_error("there are no stitches to save");
            return -1;
        }
        let bytes = match fmt {
            1 => formats::write_dst(pl, &name),
            2 => formats::write_pec_file(pl, &name),
            3 => super::formats2::write_jef(pl, &now_stamp()),
            4 => super::formats2::write_exp(pl),
            5 => super::formats2::write_vp3(pl, &name),
            6 => super::formats2::write_xxx(pl),
            _ => formats::write_pes(pl, &name),
        };
        let pp = std::path::Path::new(&path);
        let ext = pp.extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_else(|| "pes".into());
        let stem = pp.file_stem().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default();
        let tmp = pp.with_file_name(format!(".{}.folio-tmp.{}", stem, ext));
        if let Err(e) = std::fs::write(&tmp, &bytes) {
            set_error(&format!("could not write the file: {e}"));
            return -1;
        }
        let back = std::fs::read(&tmp).map_err(|e| e.to_string()).and_then(|d| formats::read_named(&d, &ext));
        let ok = match &back {
            Ok(b) => {
                let (n0, n1) = (pl.stitch_count() as f32, b.stitch_count() as f32);
                let (a, c) = (pl.bounds(), b.bounds());
                (n1 - n0).abs() <= 0.01 * n0.max(1.0) && ((a.2 - a.0) - (c.2 - c.0)).abs() <= 0.5 && ((a.3 - a.1) - (c.3 - c.1)).abs() <= 0.5
            }
            Err(_) => false,
        };
        if !ok {
            let _ = std::fs::remove_file(&tmp);
            set_error(&match back {
                Err(e) => format!("the saved file didn't read back: {e}"),
                Ok(_) => "the saved file didn't match the design when read back".into(),
            });
            return -1;
        }
        if let Err(e) = std::fs::rename(&tmp, &path) {
            let _ = std::fs::remove_file(&tmp);
            set_error(&format!("could not save the file: {e}"));
            return -1;
        }
        0
    })
}

/// Read a PES, PEC or DST design.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_read(path: *const c_char) -> *mut Plan {
    let path = cstr(path);
    let ext = std::path::Path::new(&path).extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default();
    guard(std::ptr::null_mut(), || match std::fs::read(&path).map_err(|e| e.to_string()).and_then(|d| formats::read_named(&d, &ext)) {
        Ok(p) => Box::into_raw(Box::new(p)),
        Err(e) => {
            set_error(&e);
            std::ptr::null_mut()
        }
    })
}

/// Thread layers per pixel (density map) of a w×h grid at s px/mm, pixel (0,0) at (x0, y0).
#[no_mangle]
pub unsafe extern "C" fn fd_emb_density(p: *mut Plan, s: f32, x0: f32, y0: f32, w: u32, h: u32, out: *mut u8) {
    let Some(pl) = p.as_ref() else { return };
    if out.is_null() {
        return;
    }
    let d = super::density(pl, s, x0, y0, w as usize, h as usize);
    std::ptr::copy_nonoverlapping(d.as_ptr(), out, d.len());
}

/// The Brother thread chart: [{pec, name, rgb}] for the 63 threads.
#[no_mangle]
pub extern "C" fn fd_emb_threads() -> *mut c_char {
    let mut a = Vec::new();
    for i in 1..=super::colour::CHART {
        let mut t = J::obj();
        t.set("pec", J::from(i as i64));
        t.set("name", J::from(super::colour::pec_name(i)));
        let c = super::colour::pec_rgb(i);
        t.set("rgb", J::Arr(c.iter().map(|v| J::from(*v as i64)).collect()));
        a.push(t);
    }
    out_str(J::Arr(a).dump())
}

/// The chart thread nearest an RGB colour (CIEDE2000).
#[no_mangle]
pub extern "C" fn fd_emb_nearest_thread(r: u32, g: u32, b: u32) -> u32 {
    super::colour::nearest_thread(super::colour::rgb_to_lab([r as u8, g as u8, b as u8])) as u32
}

fn rings_of(j: &J) -> Vec<Ring> {
    j.arr().iter().map(|r| r.arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0))).collect::<Ring>()).filter(|r: &Ring| r.len() >= 3).collect()
}

fn rings_json(rs: &[Ring]) -> J {
    J::Arr(rs.iter().map(|r| J::Arr(r.iter().map(|p| J::Arr(vec![J::from(p.0), J::from(p.1)])).collect())).collect())
}

/// Shape operations on masks at 20 px/mm. JSON in: {op: "union", shapes: [rings...]} |
/// {op: "split", rings, line: [[x,y]...]} | {op: "parts", rings} | {op: "info", rings} |
/// {op: "offset", rings, d}. Returns {shapes: [rings...]} or {width, kind, area}.
#[no_mangle]
pub unsafe extern "C" fn fd_emb_shapes(req: *const c_char) -> *mut c_char {
    guard(std::ptr::null_mut(), || {
        let Some(j) = parse_or_err(&cstr(req)) else { return std::ptr::null_mut() };
        let op = j.get("op").s().to_string();
        let mut all: Vec<Vec<Ring>> = Vec::new();
        if op == "union" {
            for s in j.get("shapes").arr() {
                all.push(rings_of(s));
            }
        } else {
            all.push(rings_of(j.get("rings")));
        }
        let every: Vec<Ring> = all.iter().flatten().cloned().collect();
        if every.is_empty() {
            set_error("no shape");
            return std::ptr::null_mut();
        }
        let b = super::geom::bbox(&every);
        let pad = 1.0 + j.get("d").f32(0.0).abs();
        let mut m = Mask::new(b.0 - pad, b.1 - pad, b.2 + pad, b.3 + pad, 20.0);
        let mut out = J::obj();
        match op.as_str() {
            "info" => {
                m.fill(&all[0], true);
                let w = super::stitch::inscribed_width(&m);
                out.set("width", J::from(w));
                out.set("area", J::from(super::geom::rings_area(&all[0])));
                out.set(
                    "kind",
                    J::from(match super::stitch::auto_kind(w) {
                        super::stitch::Kind::Run => "run",
                        super::stitch::Kind::Satin => "satin",
                        _ => "fill",
                    }),
                );
                return out_str(out.dump());
            }
            "union" => {
                for r in &all {
                    let mut one = m.like();
                    one.fill(r, true);
                    m = m.or(&one);
                }
                // touching shapes merge; ones that stay apart are kept together as one shape's
                // parts by tracing each part
            }
            "split" => {
                m.fill(&all[0], true);
                let line: Vec<(f32, f32)> = j.get("line").arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0))).collect();
                let mut cut = m.like();
                for w in line.windows(2) {
                    let (a, c) = (w[0], w[1]);
                    let n = ((super::geom::dist(a, c) * 40.0).ceil() as usize).max(1);
                    for k in 0..=n {
                        let p = super::geom::lerp(a, c, k as f32 / n as f32);
                        let ci = ((p.0 - cut.x0) * cut.s) as i64;
                        let cj = ((p.1 - cut.y0) * cut.s) as i64;
                        for dj in -1..=1i64 {
                            for di in -1..=1i64 {
                                let (i, jj) = (ci + di, cj + dj);
                                if i >= 0 && jj >= 0 && (i as usize) < cut.w && (jj as usize) < cut.h {
                                    cut.v[jj as usize * cut.w + i as usize] = true;
                                }
                            }
                        }
                    }
                }
                m = m.minus(&cut);
            }
            "offset" => {
                m.fill(&all[0], true);
                m = m.offset(j.get("d").f32(0.0));
            }
            _ => {
                m.fill(&all[0], true);
            }
        }
        let parts: Vec<J> = trace_mask(&m, 0.05).into_iter().filter(|r| super::geom::rings_area(r) > 0.05).map(|r| rings_json(&r)).collect();
        out.set("shapes", J::Arr(parts));
        out_str(out.dump())
    })
}

/// Today's date and time as JEF writes it (YYYYMMDDHHMMSS, UTC), from the system clock.
fn now_stamp() -> String {
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
    let (days, rem) = (t.div_euclid(86400), t.rem_euclid(86400));
    // civil from days (Howard Hinnant)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{:04}{:02}{:02}{:02}{:02}{:02}", y, m, d, rem / 3600, rem / 60 % 60, rem % 60)
}
