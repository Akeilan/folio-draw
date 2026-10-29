//! Embroidery: pictures to editable shapes, shapes to stitches, stitches to machine files.
//! Everything here is written for Folio Draw; no outside code.

pub mod colour;
pub mod convert;
pub mod ffi;
pub mod formats;
pub mod formats2;
pub mod geom;
pub mod json;
pub mod plan;
pub mod raster;
pub mod skeleton;
pub mod stitch;
pub mod trace;

#[cfg(test)]
mod acceptance;

use json::J;
use plan::Plan;

/// Stitch density: how many thread layers cover each pixel (thread 0.4 mm wide) of a
/// `w`×`h` grid at `s` px/mm whose pixel (0,0) is at (x0, y0) mm.
pub fn density(p: &Plan, s: f32, x0: f32, y0: f32, w: usize, h: usize) -> Vec<u8> {
    let mut cnt = vec![0u8; w * h];
    let mut stamp = vec![0u32; w * h];
    let r = 0.2 * s;
    let mut sid = 0u32;
    for b in &p.blocks {
        let mut last: Option<(f32, f32)> = None;
        for c in &b.cmds {
            let q = (c.0, c.1);
            if c.2 != plan::ST {
                last = Some(q);
                continue;
            }
            if let Some(a) = last {
                sid += 1;
                let (ax, ay) = ((a.0 - x0) * s, (a.1 - y0) * s);
                let (bx, by) = ((q.0 - x0) * s, (q.1 - y0) * s);
                let i0 = (ax.min(bx) - r).floor().max(0.0) as usize;
                let i1 = ((ax.max(bx) + r).ceil() as usize + 1).min(w);
                let j0 = (ay.min(by) - r).floor().max(0.0) as usize;
                let j1 = ((ay.max(by) + r).ceil() as usize + 1).min(h);
                for j in j0..j1 {
                    for i in i0..i1 {
                        let pc = (i as f32 + 0.5, j as f32 + 0.5);
                        if geom::dist_to_segment(pc, (ax, ay), (bx, by)) <= r {
                            let k = j * w + i;
                            if stamp[k] != sid {
                                stamp[k] = sid;
                                cnt[k] = cnt[k].saturating_add(1);
                            }
                        }
                    }
                }
            }
            last = Some(q);
        }
    }
    cnt
}

/// Plan as JSON from a stitch-object description (an imported design kept as stitches).
pub fn plan_from_blocks(j: &J) -> Plan {
    Plan { blocks: plan::stitch_blocks_from(j) }
}
