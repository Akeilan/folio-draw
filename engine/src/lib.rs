//! Folio Draw engine — C ABI consumed by the GTK front end through ctypes.
//! No third-party crates: codecs, rasteriser and compositor are all in this crate.

pub mod adjust;
pub mod bmp;
pub mod deflate;
pub mod doc;
pub mod gif;
pub mod jpeg;
pub mod ora;
pub mod png;
pub mod zip;

use doc::{Doc, Pt};
use std::cell::RefCell;
use std::ffi::{c_char, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};

thread_local! {
    static LAST_ERROR: RefCell<CString> = RefCell::new(CString::new("").unwrap());
}

fn set_error(msg: &str) {
    let c = CString::new(msg.replace('\0', " ")).unwrap();
    LAST_ERROR.with(|e| *e.borrow_mut() = c);
}

/// Run `f`, converting a panic into an error message and the fallback value.
fn guard<T>(fallback: T, f: impl FnOnce() -> T) -> T {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => v,
        Err(e) => {
            let msg = e
                .downcast_ref::<&str>()
                .map(|s| s.to_string())
                .or_else(|| e.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "internal error".into());
            set_error(&format!("engine error: {msg}"));
            fallback
        }
    }
}

unsafe fn d<'a>(p: *mut Doc) -> Option<&'a mut Doc> {
    p.as_mut()
}

unsafe fn cstr(p: *const c_char) -> String {
    if p.is_null() {
        String::new()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}

unsafe fn pts(p: *const f32, n: usize) -> Vec<Pt> {
    if p.is_null() {
        return Vec::new();
    }
    let s = std::slice::from_raw_parts(p, n * 2);
    s.chunks_exact(2).map(|c| (c[0], c[1])).collect()
}

fn rgba(c: u32) -> [u8; 4] {
    // packed as 0xRRGGBBAA
    [(c >> 24) as u8, (c >> 16) as u8, (c >> 8) as u8, c as u8]
}

#[no_mangle]
pub extern "C" fn fd_version() -> u32 {
    100
}

#[no_mangle]
pub extern "C" fn fd_last_error() -> *const c_char {
    LAST_ERROR.with(|e| e.borrow().as_ptr())
}

// ------------------------------------------------------------------ lifecycle & files

#[no_mangle]
pub extern "C" fn fd_new(w: u32, h: u32, fill: u32) -> *mut Doc {
    guard(std::ptr::null_mut(), || {
        if w == 0 || h == 0 || w > 32768 || h > 32768 {
            set_error("image size must be between 1 and 32768 pixels");
            return std::ptr::null_mut();
        }
        Box::into_raw(Box::new(Doc::new(w as usize, h as usize, rgba(fill))))
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_new_from_rgba(w: u32, h: u32, data: *const u8, name: *const c_char) -> *mut Doc {
    guard(std::ptr::null_mut(), || {
        if data.is_null() || w == 0 || h == 0 {
            set_error("empty image");
            return std::ptr::null_mut();
        }
        let px = std::slice::from_raw_parts(data, (w * h * 4) as usize).to_vec();
        let n = cstr(name);
        Box::into_raw(Box::new(Doc::from_rgba(w as usize, h as usize, px, if n.is_empty() { "Background" } else { &n })))
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_free(p: *mut Doc) {
    if !p.is_null() {
        drop(Box::from_raw(p));
    }
}

/// Load PNG, BMP or OpenRaster by content sniffing. Returns null on failure (see fd_last_error).
#[no_mangle]
pub unsafe extern "C" fn fd_load(path: *const c_char) -> *mut Doc {
    let path = cstr(path);
    guard(std::ptr::null_mut(), || {
        let data = match std::fs::read(&path) {
            Ok(d) => d,
            Err(e) => {
                set_error(&format!("could not read file: {e}"));
                return std::ptr::null_mut();
            }
        };
        let res: Result<Doc, String> = if png::is_png(&data) {
            png::decode(&data).map(|i| Doc::from_rgba(i.w, i.h, i.px, "Background"))
        } else if bmp::is_bmp(&data) {
            bmp::decode(&data).map(|i| Doc::from_rgba(i.w, i.h, i.px, "Background"))
        } else if jpeg::is_jpeg(&data) {
            jpeg::decode(&data).map(|i| Doc::from_rgba(i.w, i.h, i.px, "Background"))
        } else if gif::is_gif(&data) {
            gif::decode_frames(&data).map(|f| {
                if f.frames.len() == 1 {
                    let (px, _) = f.frames.into_iter().next().unwrap();
                    return Doc::from_rgba(f.w, f.h, px, "Background");
                }
                // every frame becomes a layer, bottom = first frame
                let mut doc = Doc::empty(f.w, f.h);
                for (i, (px, delay)) in f.frames.into_iter().enumerate() {
                    doc.push_layer(&format!("Frame {}", i + 1), px, 1.0, true, 0);
                    doc.layers.last_mut().unwrap().delay_ms = delay;
                }
                doc.active = 0;
                doc.solo = true;
                doc.gif_loop = f.loop_count.map_or(-1, |v| v as i32);
                doc.frames_truncated = f.truncated;
                doc
            })
        } else if data.len() > 4 && &data[..4] == b"PK\x03\x04" {
            ora::load(&data)
        } else {
            Err("unsupported".into())
        };
        match res {
            Ok(doc) => Box::into_raw(Box::new(doc)),
            Err(e) => {
                set_error(&e);
                std::ptr::null_mut()
            }
        }
    })
}

/// format: 0 PNG, 1 OpenRaster, 2 BMP 24-bit (flattened on `matte`), 3 BMP 32-bit,
/// 4 JPEG (flattened on `matte`, quality 92), 5 GIF (flattened), 6 animated GIF (layers = frames)
#[no_mangle]
pub unsafe extern "C" fn fd_save(p: *mut Doc, path: *const c_char, format: u32, matte: u32) -> i32 {
    let path = cstr(path);
    guard(-1, || {
        let Some(doc) = d(p) else { return -1 };
        doc.commit_float();
        let bytes = match format {
            0 => png::encode(doc.w, doc.h, &doc.flatten_rgba(), 7),
            1 => ora::save(doc),
            2 => {
                let m = rgba(matte);
                bmp::encode(doc.w, doc.h, &doc.flatten_rgba(), false, [m[0], m[1], m[2]])
            }
            3 => bmp::encode(doc.w, doc.h, &doc.flatten_rgba(), true, [255, 255, 255]),
            4 => {
                let m = rgba(matte);
                let mut px = doc.flatten_rgba();
                for p in px.chunks_exact_mut(4) {
                    let a = p[3] as u32;
                    for k in 0..3 {
                        p[k] = ((p[k] as u32 * a + m[k] as u32 * (255 - a) + 127) / 255) as u8;
                    }
                    p[3] = 255;
                }
                jpeg::encode(doc.w, doc.h, &px, 92)
            }
            5 => gif::encode(doc.w, doc.h, &doc.flatten_rgba()),
            6 => {
                // animation: every layer is one frame, bottom layer first
                let frames: Vec<Vec<u8>> = doc
                    .layers
                    .iter()
                    .map(|l| {
                        let mut px = l.px.clone();
                        if l.opacity < 1.0 {
                            for p in px.chunks_exact_mut(4) {
                                p[3] = (p[3] as f32 * l.opacity + 0.5) as u8;
                            }
                        }
                        px
                    })
                    .collect();
                let refs: Vec<(&[u8], u32)> = frames
                    .iter()
                    .zip(doc.layers.iter())
                    .map(|(f, l)| (f.as_slice(), if l.delay_ms == 0 { 100 } else { l.delay_ms }))
                    .collect();
                let lc = if doc.gif_loop < 0 { None } else { Some(doc.gif_loop.min(65535) as u16) };
                gif::encode_animation(doc.w, doc.h, &refs, lc)
            }
            _ => {
                set_error("unknown format");
                return -1;
            }
        };
        // write atomically so a failed save never destroys the previous file
        let tmp = format!("{path}.folio-tmp");
        if let Err(e) = std::fs::write(&tmp, &bytes) {
            set_error(&format!("could not write file: {e}"));
            return -1;
        }
        if let Err(e) = std::fs::rename(&tmp, &path) {
            let _ = std::fs::remove_file(&tmp);
            set_error(&format!("could not write file: {e}"));
            return -1;
        }
        0
    })
}

/// Decode PNG/BMP bytes into a caller-owned RGBA buffer obtained with fd_buf_*.
#[no_mangle]
pub unsafe extern "C" fn fd_decode_file(path: *const c_char, w: *mut u32, h: *mut u32) -> *mut u8 {
    let path = cstr(path);
    guard(std::ptr::null_mut(), || {
        let data = match std::fs::read(&path) {
            Ok(d) => d,
            Err(e) => {
                set_error(&e.to_string());
                return std::ptr::null_mut();
            }
        };
        let img = if png::is_png(&data) {
            png::decode(&data)
        } else if bmp::is_bmp(&data) {
            bmp::decode(&data)
        } else if jpeg::is_jpeg(&data) {
            jpeg::decode(&data)
        } else if gif::is_gif(&data) {
            gif::decode(&data)
        } else {
            Err("unsupported".into())
        };
        match img {
            Ok(i) => {
                *w = i.w as u32;
                *h = i.h as u32;
                let mut b = i.px.into_boxed_slice();
                let ptr = b.as_mut_ptr();
                std::mem::forget(b);
                ptr
            }
            Err(e) => {
                set_error(&e);
                std::ptr::null_mut()
            }
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_buf_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        drop(Box::from_raw(std::slice::from_raw_parts_mut(ptr, len)));
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_width(p: *mut Doc) -> u32 {
    d(p).map_or(0, |d| d.w as u32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_height(p: *mut Doc) -> u32 {
    d(p).map_or(0, |d| d.h as u32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_changes(p: *mut Doc) -> u64 {
    d(p).map_or(0, |d| d.changes)
}

// ------------------------------------------------------------------ compositing

#[no_mangle]
pub unsafe extern "C" fn fd_comp_ptr(p: *mut Doc) -> *mut u8 {
    d(p).map_or(std::ptr::null_mut(), |d| d.comp.as_mut_ptr())
}

/// Recomposite pending changes. Writes the updated rect (x,y,w,h) and returns 1, or 0 if clean.
#[no_mangle]
pub unsafe extern "C" fn fd_comp_update(p: *mut Doc, out: *mut i32) -> i32 {
    guard(0, || {
        let Some(doc) = d(p) else { return 0 };
        match doc.comp_update() {
            Some((x0, y0, x1, y1)) => {
                if !out.is_null() {
                    let o = std::slice::from_raw_parts_mut(out, 4);
                    o.copy_from_slice(&[x0 as i32, y0 as i32, (x1 - x0) as i32, (y1 - y0) as i32]);
                }
                1
            }
            None => 0,
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_invalidate(p: *mut Doc) {
    if let Some(doc) = d(p) {
        doc.mark_all();
    }
}

#[no_mangle]
pub unsafe extern "C" fn fd_flatten_rgba(p: *mut Doc, out: *mut u8) {
    guard((), || {
        if let Some(doc) = d(p) {
            let v = doc.flatten_rgba();
            std::ptr::copy_nonoverlapping(v.as_ptr(), out, v.len());
        }
    })
}

// ------------------------------------------------------------------ undo

#[no_mangle]
pub unsafe extern "C" fn fd_undo(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.undo() as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_redo(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.redo() as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_can_undo(p: *mut Doc) -> i32 {
    d(p).map_or(0, |d| d.can_undo() as i32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_can_redo(p: *mut Doc) -> i32 {
    d(p).map_or(0, |d| d.can_redo() as i32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_op_begin(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.commit_float();
            doc.op_begin()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_op_restore(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.op_restore()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_op_end(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.op_end();
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_op_cancel(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.op_cancel()
        }
    })
}

// ------------------------------------------------------------------ painting

#[no_mangle]
pub unsafe extern "C" fn fd_stroke_begin(p: *mut Doc, tool: u32, size: f32, hardness: f32, col: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.stroke_begin(tool as u8, size, hardness, rgba(col))
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_stroke_to(p: *mut Doc, x: f32, y: f32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.stroke_to(x, y)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_stroke_end(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.stroke_end()
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_shape(p: *mut Doc, xy: *const f32, n: u32, closed: i32, width: f32, outline: u32, fill: u32, mode: u32, aa: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            let v = pts(xy, n as usize);
            doc.shape(&v, closed != 0, width, rgba(outline), rgba(fill), mode, aa != 0)
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_blit_premul(p: *mut Doc, x: i32, y: i32, w: u32, h: u32, data: *const u8, stride: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if data.is_null() {
                return;
            }
            let s = std::slice::from_raw_parts(data, (stride * h) as usize);
            doc.blit_premul(x as i64, y as i64, w as usize, h as usize, s, stride as usize)
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_fill(p: *mut Doc, x: i32, y: i32, col: u32, tol: u32) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.flood_fill(x as i64, y as i64, rgba(col), tol.min(255) as u8) as i32))
}

/// Returns the colour as 0xRRGGBBAA.
#[no_mangle]
pub unsafe extern "C" fn fd_pick(p: *mut Doc, x: i32, y: i32, all: i32) -> u32 {
    guard(0, || {
        d(p).map_or(0, |d| {
            let c = d.pick(x as i64, y as i64, all != 0);
            u32::from_be_bytes(c)
        })
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_invert_colors(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.invert_colors()
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn fd_set_sample_all(p: *mut Doc, on: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sample_all = on != 0
        }
    })
}

// ------------------------------------------------------------------ adjustments

#[no_mangle]
pub unsafe extern "C" fn fd_adjust_preview(p: *mut Doc, kind: u32, a: f32, b: f32, c: f32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.adjust_preview(kind, a, b, c)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_adjust_end(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.adjust_end()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_adjust_cancel(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.adjust_cancel()
        }
    })
}

// ------------------------------------------------------------------ selection

#[no_mangle]
pub unsafe extern "C" fn fd_sel_rect(p: *mut Doc, x: i32, y: i32, w: i32, h: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_rect(x as i64, y as i64, w as i64, h as i64)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_poly(p: *mut Doc, xy: *const f32, n: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_poly(&pts(xy, n as usize))
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_exclude_color(p: *mut Doc, col: u32, tol: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_exclude_color(rgba(col), tol.min(255) as u8)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_all(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_all()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_none(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_none()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_invert(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.sel_invert()
        }
    })
}
/// Writes bounds (x,y,w,h); returns 1 if a selection exists.
#[no_mangle]
pub unsafe extern "C" fn fd_sel_bounds(p: *mut Doc, out: *mut i32) -> i32 {
    guard(0, || {
        let Some(doc) = d(p) else { return 0 };
        match doc.sel_bounds() {
            Some((x0, y0, x1, y1)) => {
                std::slice::from_raw_parts_mut(out, 4).copy_from_slice(&[x0 as i32, y0 as i32, (x1 - x0) as i32, (y1 - y0) as i32]);
                1
            }
            None => 0,
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_mask_ptr(p: *mut Doc) -> *const u8 {
    d(p).and_then(|d| d.sel.as_ref().map(|m| m.as_ptr())).unwrap_or(std::ptr::null())
}
#[no_mangle]
pub unsafe extern "C" fn fd_sel_delete(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.sel_delete() as i32))
}

#[no_mangle]
pub unsafe extern "C" fn fd_float_lift(p: *mut Doc, cut: i32) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.float_lift(cut != 0) as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_from_rgba(p: *mut Doc, w: u32, h: u32, data: *const u8, x: i32, y: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if data.is_null() || w == 0 || h == 0 {
                return;
            }
            let px = std::slice::from_raw_parts(data, (w * h * 4) as usize).to_vec();
            doc.float_from_rgba(w as usize, h as usize, px, x, y)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_get(p: *mut Doc, out: *mut i32) -> i32 {
    let Some(doc) = d(p) else { return 0 };
    match &doc.float {
        Some(f) => {
            std::slice::from_raw_parts_mut(out, 4).copy_from_slice(&[f.x, f.y, f.w as i32, f.h as i32]);
            1
        }
        None => 0,
    }
}
/// 1 when the floating selection has no visible pixels.
#[no_mangle]
pub unsafe extern "C" fn fd_float_is_empty(p: *mut Doc) -> i32 {
    let Some(doc) = d(p) else { return 1 };
    match &doc.float {
        Some(f) => f.src.chunks_exact(4).all(|px| px[3] == 0) as i32,
        None => 1,
    }
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_set_rect(p: *mut Doc, x: i32, y: i32, w: u32, h: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.float_set_rect(x, y, w as usize, h as usize)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_commit(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.commit_float()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_discard(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.float_discard()
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_transform(p: *mut Doc, kind: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.float_transform(kind as u8)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_color_key(p: *mut Doc, col: u32, tol: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.float_color_key(rgba(col), tol.min(255) as u8)
        }
    })
}
/// Prepare the clipboard image; returns 1 and writes (w,h) if there is something to copy.
#[no_mangle]
pub unsafe extern "C" fn fd_clip_extract(p: *mut Doc, out: *mut u32) -> i32 {
    guard(0, || {
        let Some(doc) = d(p) else { return 0 };
        if doc.clip_extract() {
            std::slice::from_raw_parts_mut(out, 2).copy_from_slice(&[doc.clip_w as u32, doc.clip_h as u32]);
            1
        } else {
            0
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_clip_ptr(p: *mut Doc) -> *const u8 {
    d(p).map_or(std::ptr::null(), |d| d.clip.as_ptr())
}

// ------------------------------------------------------------------ layers

#[no_mangle]
pub unsafe extern "C" fn fd_layer_count(p: *mut Doc) -> u32 {
    d(p).map_or(0, |d| d.layers.len() as u32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_active(p: *mut Doc) -> u32 {
    d(p).map_or(0, |d| d.active as u32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_set_active(p: *mut Doc, i: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.set_active(i as usize)
        }
    })
}
/// Copy the layer name (UTF-8, NUL-terminated) into buf; returns the full length.
#[no_mangle]
pub unsafe extern "C" fn fd_layer_name(p: *mut Doc, i: u32, buf: *mut u8, len: u32) -> u32 {
    let Some(doc) = d(p) else { return 0 };
    let Some(l) = doc.layers.get(i as usize) else { return 0 };
    let b = l.name.as_bytes();
    if !buf.is_null() && len > 0 {
        let n = b.len().min(len as usize - 1);
        std::ptr::copy_nonoverlapping(b.as_ptr(), buf, n);
        *buf.add(n) = 0;
    }
    b.len() as u32
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_text(p: *mut Doc, i: u32, buf: *mut u8, len: u32) -> u32 {
    let Some(doc) = d(p) else { return 0 };
    let Some(l) = doc.layers.get(i as usize) else { return 0 };
    let b = l.text.as_bytes();
    if !buf.is_null() && len > 0 {
        let n = b.len().min(len as usize - 1);
        std::ptr::copy_nonoverlapping(b.as_ptr(), buf, n);
        *buf.add(n) = 0;
    }
    b.len() as u32
}
/// A new text layer from cairo's premultiplied BGRA block at x, y.
#[no_mangle]
pub unsafe extern "C" fn fd_text_layer_add(p: *mut Doc, name: *const c_char, text: *const c_char, x: i32, y: i32, w: u32, h: u32, data: *const u8, stride: u32) -> u32 {
    guard(0, || {
        let Some(doc) = d(p) else { return 0 };
        let name = cstr(name);
        let text = cstr(text);
        let block = std::slice::from_raw_parts(data, stride as usize * h as usize);
        doc.text_layer_add(&name, &text, x as i64, y as i64, w as usize, h as usize, block, stride as usize) as u32
    })
}
/// A text layer typed again (data null: only the description changes, e.g. emptied to rasterize).
#[no_mangle]
pub unsafe extern "C" fn fd_text_layer_set(p: *mut Doc, i: u32, text: *const c_char, x: i32, y: i32, w: u32, h: u32, data: *const u8, stride: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            let text = cstr(text);
            if data.is_null() {
                doc.text_layer_set(i as usize, &text, None);
            } else {
                let block = std::slice::from_raw_parts(data, stride as usize * h as usize);
                doc.text_layer_set(i as usize, &text, Some((x as i64, y as i64, w as usize, h as usize, block, stride as usize)));
            }
        }
    })
}
/// out: [opacity, visible, blend, id, delay_ms]
#[no_mangle]
pub unsafe extern "C" fn fd_layer_props(p: *mut Doc, i: u32, out: *mut f32) -> i32 {
    let Some(doc) = d(p) else { return 0 };
    let Some(l) = doc.layers.get(i as usize) else { return 0 };
    std::slice::from_raw_parts_mut(out, 5).copy_from_slice(&[l.opacity, l.visible as i32 as f32, l.blend as f32, l.id as f32, l.delay_ms as f32]);
    1
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_set_props(p: *mut Doc, i: u32, name: *const c_char, opacity: f32, visible: i32, blend: u32, delay_ms: u32, record: i32) {
    let name = if name.is_null() { None } else { Some(cstr(name)) };
    guard((), || {
        if let Some(doc) = d(p) {
            doc.layer_set_props(i as usize, name, opacity, visible != 0, blend as u8, delay_ms, record != 0)
        }
    })
}
/// Frames view: 1 = canvas shows only the active layer.
#[no_mangle]
pub unsafe extern "C" fn fd_set_solo(p: *mut Doc, on: i32) {
    if let Some(doc) = d(p) {
        if doc.solo != (on != 0) {
            doc.solo = on != 0;
            doc.mark_all();
        }
    }
}
#[no_mangle]
pub unsafe extern "C" fn fd_get_solo(p: *mut Doc) -> i32 {
    d(p).map_or(0, |d| d.solo as i32)
}
/// Change which layer is active without committing anything (animation playback).
#[no_mangle]
pub unsafe extern "C" fn fd_show_frame(p: *mut Doc, i: u32) {
    if let Some(doc) = d(p) {
        if (i as usize) < doc.layers.len() && doc.float.is_none() && doc.active != i as usize {
            doc.active = i as usize;
            if doc.solo {
                doc.mark_all();
            }
        }
    }
}
#[no_mangle]
pub unsafe extern "C" fn fd_gif_loop(p: *mut Doc) -> i32 {
    d(p).map_or(0, |d| d.gif_loop)
}
#[no_mangle]
pub unsafe extern "C" fn fd_set_gif_loop(p: *mut Doc, v: i32) {
    if let Some(doc) = d(p) {
        doc.gif_loop = v.clamp(-1, 65535);
    }
}
#[no_mangle]
pub unsafe extern "C" fn fd_frames_truncated(p: *mut Doc) -> i32 {
    d(p).map_or(0, |d| d.frames_truncated as i32)
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_add(p: *mut Doc, name: *const c_char) -> u32 {
    let name = cstr(name);
    guard(0, || d(p).map_or(0, |d| d.layer_add(&name) as u32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_duplicate(p: *mut Doc) -> u32 {
    guard(0, || d(p).map_or(0, |d| d.layer_duplicate() as u32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_delete(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.layer_delete() as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_move(p: *mut Doc, from: u32, to: u32) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.layer_move(from as usize, to as usize) as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_layer_merge_down(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.layer_merge_down() as i32))
}
#[no_mangle]
pub unsafe extern "C" fn fd_flatten(p: *mut Doc) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.flatten()
        }
    })
}
/// Copy a layer's straight RGBA pixels into `out` (w*h*4 bytes).
#[no_mangle]
pub unsafe extern "C" fn fd_layer_rgba(p: *mut Doc, i: u32, out: *mut u8) -> i32 {
    let Some(doc) = d(p) else { return 0 };
    let Some(l) = doc.layers.get(i as usize) else { return 0 };
    std::ptr::copy_nonoverlapping(l.px.as_ptr(), out, l.px.len());
    1
}
/// Render a layer thumbnail as cairo ARGB32 premultiplied into `out` (tw*th*4 bytes).
#[no_mangle]
pub unsafe extern "C" fn fd_layer_thumb(p: *mut Doc, i: u32, out: *mut u8, tw: u32, th: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            let v = doc.layer_thumb(i as usize, tw as usize, th as usize);
            std::ptr::copy_nonoverlapping(v.as_ptr(), out, v.len());
        }
    })
}

// ------------------------------------------------------------------ image operations

#[no_mangle]
pub unsafe extern "C" fn fd_image_transform(p: *mut Doc, kind: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.image_transform(kind as u8)
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_image_rotate(p: *mut Doc, deg: f32, smooth: i32, bg: u32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if deg.is_finite() {
                let (w, h) = doc::rotated_size(doc.w, doc.h, deg);
                if w <= 32768 && h <= 32768 {
                    let c = rgba(bg);
                    doc.image_rotate(deg, smooth != 0, if c[3] == 0 { None } else { Some(c) })
                }
            }
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_float_rotate(p: *mut Doc, deg: f32, smooth: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if deg.is_finite() {
                doc.float_rotate(deg, smooth != 0)
            }
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_image_resize(p: *mut Doc, w: u32, h: u32, smooth: i32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if w > 0 && h > 0 && w <= 32768 && h <= 32768 {
                doc.image_resize(w as usize, h as usize, smooth != 0)
            }
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_image_skew(p: *mut Doc, ax: f32, ay: f32) {
    guard((), || {
        if let Some(doc) = d(p) {
            doc.image_skew(ax.clamp(-89.0, 89.0), ay.clamp(-89.0, 89.0))
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_canvas_size(p: *mut Doc, w: u32, h: u32, ax: f32, ay: f32) {
    guard((), || {
        if let Some(doc) = d(p) {
            if w > 0 && h > 0 && w <= 32768 && h <= 32768 {
                doc.canvas_size(w as usize, h as usize, ax, ay)
            }
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn fd_crop_to_selection(p: *mut Doc) -> i32 {
    guard(0, || d(p).map_or(0, |d| d.crop_to_selection() as i32))
}
