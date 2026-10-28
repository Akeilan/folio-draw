//! Acceptance tests ported from the Folio Stitch prototype, run on the reference pictures in
//! tests/data. They exercise the whole engine path: place, convert, plan, write, read.

use super::colour::pec_name;
use super::convert::{convert, place, Params};
use super::formats;
use super::geom::{dist, Ring};
use super::json::{parse, J};
use super::plan::{plan, Plan, JUMP, ST};
use super::raster::{Img, Mask};
use std::time::Instant;

const S: f32 = 10.0;
const HOOP: f32 = 101.6;

fn data(name: &str) -> Vec<u8> {
    let p = format!("{}/../tests/data/{}", env!("CARGO_MANIFEST_DIR"), name);
    std::fs::read(&p).unwrap_or_else(|e| panic!("{p}: {e}"))
}

fn load(name: &str) -> Img {
    let d = data(name);
    if crate::png::is_png(&d) {
        let i = crate::png::decode(&d).unwrap();
        Img { w: i.w, h: i.h, px: i.px }
    } else {
        let i = crate::gif::decode(&d).unwrap();
        Img { w: i.w, h: i.h, px: i.px }
    }
}

struct Traced {
    shapes: Vec<J>,
    names: Vec<String>,
    secs: f64,
}

fn trace(name: &str, opts: &str) -> Traced {
    let src = load(name);
    let cw = (HOOP * S).round() as usize;
    let t0 = Instant::now();
    let pl = place(&src, cw, cw, S, 2.5, true);
    let mut pj = parse(opts).unwrap();
    pj.set("upscale", J::from(pl.upscale));
    if let Some(b) = pl.bg {
        pj.set("bg", J::Arr(b.iter().map(|v| J::from(*v as i64)).collect()));
    }
    let p = Params::from_json(&pj);
    let c = convert(&pl.img, S, -HOOP / 2.0, -HOOP / 2.0, &p);
    let secs = t0.elapsed().as_secs_f64();
    let names = c.colours.iter().map(|c| c.get("thread").get("name").s().to_string()).collect();
    Traced { shapes: c.shapes, names, secs }
}

fn design(layers: &[Vec<J>]) -> J {
    let mut d = J::obj();
    let mut st = J::obj();
    st.set("hoop", J::Arr(vec![J::from(HOOP), J::from(HOOP)]));
    d.set("settings", st);
    d.set(
        "layers",
        J::Arr(
            layers
                .iter()
                .map(|objs| {
                    let mut l = J::obj();
                    l.set("objects", J::Arr(objs.clone()));
                    l
                })
                .collect(),
        ),
    );
    d
}

fn grouped(shapes: &[J], g: &str) -> Vec<J> {
    shapes
        .iter()
        .map(|s| {
            let mut s = s.clone();
            s.set("group", J::from(g));
            s
        })
        .collect()
}

fn rings(j: &J) -> Vec<Ring> {
    j.get("rings").arr().iter().map(|r| r.arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0))).collect()).collect()
}

fn coverage_mask(p: &Plan, only: Option<usize>) -> Mask {
    let mut m = Mask::new(-HOOP / 2.0, -HOOP / 2.0, HOOP / 2.0, HOOP / 2.0, 20.0);
    let sub = Plan { blocks: p.blocks.iter().enumerate().filter(|(i, _)| only.map_or(true, |o| o == *i)).map(|(_, b)| b.clone()).collect() };
    let d = super::density(&sub, 20.0, m.x0, m.y0, m.w, m.h);
    for (v, c) in m.v.iter_mut().zip(d) {
        *v = c > 0;
    }
    m
}

#[test]
fn reference_logo_five_colours() {
    let t = trace("logo.png", "{}");
    assert_eq!(t.names.len(), 5, "{:?}", t.names);
    assert!(t.names.iter().any(|n| n == "Black"), "{:?}", t.names);
    assert!(t.names.iter().any(|n| n.contains("Red") || n == "Vermilion"), "{:?}", t.names);
    assert!(t.names.iter().any(|n| n.contains("Green")), "{:?}", t.names);
    assert!(t.names.iter().any(|n| n.contains("Blue") || n == "Ultramarine"), "{:?}", t.names);
    assert!(t.secs < 3.0, "conversion took {:.2} s", t.secs);
}

/// The reference emblem is a third-party logo kept out of the public repository: the test
/// runs when tests/data/dsa.gif is present.
fn have(name: &str) -> bool {
    let ok = std::path::Path::new(&format!("{}/../tests/data/{}", env!("CARGO_MANIFEST_DIR"), name)).exists();
    if !ok {
        eprintln!("skipped: tests/data/{name} is not here");
    }
    ok
}

#[test]
fn reference_emblem_two_colours() {
    if !have("dsa.gif") {
        return;
    }
    let t = trace("dsa.gif", "{}");
    assert_eq!(t.names.len(), 2, "{:?}", t.names);
    let pinks = ["Salmon Pink", "Pink", "Flesh Pink", "Deep Rose", "Carmine", "Light Lilac", "Amber Red"];
    assert!(!t.names.iter().any(|n| pinks.contains(&n.as_str())), "{:?}", t.names);
    // size over 90 × 90 mm
    let mut b = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for s in &t.shapes {
        for r in rings(s) {
            for p in r {
                b = (b.0.min(p.0), b.1.min(p.1), b.2.max(p.0), b.3.max(p.1));
            }
        }
    }
    assert!(b.2 - b.0 > 90.0 && b.3 - b.1 > 90.0, "{:?}", b);
    let p = plan(&design(&[grouped(&t.shapes, "emblem")]));
    assert_eq!(p.blocks.len(), 2);
    assert_eq!(p.blocks[0].thread.name, "White", "{:?}", p.blocks.iter().map(|b| b.thread.name.clone()).collect::<Vec<_>>());
    assert!(t.secs < 3.0, "conversion took {:.2} s", t.secs);
}

#[test]
fn logo_plan_limits_and_coverage() {
    let t = trace("logo.png", "{}");
    let p = plan(&design(&[grouped(&t.shapes, "logo")]));
    let (mut moves, mut short, mut over) = (0usize, 0usize, 0usize);
    let half = HOOP / 2.0;
    for b in &p.blocks {
        let mut last: Option<(f32, f32)> = None;
        for c in &b.cmds {
            assert!(c.0.abs() <= half && c.1.abs() <= half, "stitch outside the hoop: {:?}", c);
            if c.2 != ST {
                // the needle lands where a jump ends: that first penetration is not a move
                last = None;
                continue;
            }
            if c.2 == ST {
                if let Some(l) = last {
                    let d = dist(l, (c.0, c.1));
                    moves += 1;
                    if d > 7.0 + 1e-3 {
                        over += 1;
                    }
                    if d < 0.3 {
                        short += 1;
                    }
                }
            }
            last = Some((c.0, c.1));
        }
    }
    assert_eq!(over, 0, "needle moves over 7 mm");
    assert!((short as f32) < 0.01 * moves as f32, "{short} of {moves} moves under 0.3 mm");
    // coverage per colour against the traced shapes
    let all = coverage_mask(&p, None);
    let mut union = all.like();
    let mut seen: Vec<super::plan::Thread> = Vec::new();
    for b in p.blocks.iter() {
        if seen.contains(&b.thread) {
            continue;
        }
        seen.push(b.thread.clone());
        let mut m = all.like();
        for s in &t.shapes {
            if super::plan::Thread::from_json(s.get("thread")) == b.thread {
                m.fill(&rings(s), true);
            }
        }
        let mut cov = all.like();
        for (bi, b2) in p.blocks.iter().enumerate() {
            if b2.thread == b.thread {
                cov = cov.or(&coverage_mask(&p, Some(bi)));
            }
        }
        let ratio = cov.and(&m).count() as f32 / m.count().max(1) as f32;
        let hairline = pec_name(b.thread.pec.unwrap_or(20)) == "Black";
        assert!(ratio > if hairline { 0.55 } else { 0.80 }, "{} covers {:.2}", b.thread.name, ratio);
        union = union.or(&m);
    }
    let uncovered = union.minus(&all).count() as f32 / union.count() as f32;
    assert!(uncovered < 0.03, "uncovered {:.3}", uncovered);
}

#[test]
fn pes_dst_export_and_repeat() {
    let t = trace("logo.png", "{}");
    let p = plan(&design(&[grouped(&t.shapes, "logo")]));
    let pes = formats::write_pes(&p, "logo");
    assert!(pes.starts_with(b"#PES0060"));
    let back = formats::read(&pes).unwrap();
    assert_eq!(back.blocks.len(), p.blocks.len());
    let (a, b) = (p.bounds(), back.bounds());
    assert!((a.2 - a.0 - (b.2 - b.0)).abs() < 0.5 && (a.3 - a.1 - (b.3 - b.1)).abs() < 0.5);
    let n0 = p.stitch_count() as f32;
    assert!((back.stitch_count() as f32 - n0).abs() <= 0.01 * n0);
    // the same design twice: byte-identical
    let t2 = trace("logo.png", "{}");
    let p2 = plan(&design(&[grouped(&t2.shapes, "logo")]));
    assert_eq!(formats::write_pes(&p2, "logo"), pes);
    let dst = formats::write_dst(&p, "logo");
    let dback = formats::read(&dst).unwrap();
    assert_eq!(dback.blocks.len(), p.blocks.len());
    assert!((dback.stitch_count() as f32 - n0).abs() <= 0.01 * n0);
    // an imported PES re-plans within 5 % of its stitch count with the same colour count
    let mut obj = super::plan::blocks_json(&back);
    obj.set("kind", J::from("stitches"));
    let re = plan(&design(&[vec![obj]]));
    assert_eq!(re.blocks.len(), back.blocks.len());
    let n1 = back.stitch_count() as f32;
    assert!((re.stitch_count() as f32 - n1).abs() <= 0.05 * n1, "{} vs {}", re.stitch_count(), n1);
}

fn scale_shapes(shapes: &[J], k: f32) -> Vec<J> {
    shapes
        .iter()
        .map(|s| {
            let mut s = s.clone();
            let r = J::Arr(
                rings(&s)
                    .iter()
                    .map(|r| J::Arr(r.iter().map(|p| J::Arr(vec![J::from(p.0 * k), J::from(p.1 * k)])).collect()))
                    .collect(),
            );
            s.set("rings", r);
            s
        })
        .collect()
}

#[test]
fn doubling_regenerates_density() {
    let t = trace("logo.png", "{}");
    let small = scale_shapes(&t.shapes, 0.5);
    let big = scale_shapes(&t.shapes, 1.0);
    let a = plan(&design(&[grouped(&small, "logo")])).stitch_count() as f32;
    let b = plan(&design(&[grouped(&big, "logo")])).stitch_count() as f32;
    let r = b / a;
    for (k, sh) in [(0.5f32, &small), (1.0, &big)] {
        let p = plan(&design(&[grouped(sh, "logo")]));
        eprintln!("scale {k}: {} stitches, {} jumps, {} trims, blocks {:?}", p.stitch_count(), p.count(JUMP), p.count(super::plan::TRIM),
            p.blocks.iter().map(|b| (b.thread.name.clone(), b.cmds.iter().filter(|c| c.2 == ST).count())).collect::<Vec<_>>());
    }
    // fills grow with the area (4×), satin columns with the length (2×): the stand-in logo is
    // half satin, so its mix sits near 2.8; stretched stitches would stay at 1×
    assert!((2.5..=5.0).contains(&r), "ratio {r:.2}");
}

#[test]
fn upper_layer_removes_hidden_stitches() {
    let t = trace("logo.png", "{}");
    let lower = grouped(&t.shapes, "logo");
    let bar = parse(r#"{"rings":[[[-30,-12],[30,-12],[30,12],[-30,12]]],"thread":{"rgb":[240,240,240],"pec":29,"name":"White"}}"#).unwrap();
    let alone = plan(&design(&[lower.clone()]));
    let stacked = plan(&design(&[lower, vec![bar]]));
    let inside = |p: &Plan, skip_last: bool| -> usize {
        let n = if skip_last { p.blocks.len() - 1 } else { p.blocks.len() };
        p.blocks[..n]
            .iter()
            .map(|b| b.cmds.iter().filter(|c| c.2 == ST && c.0.abs() < 29.0 && c.1.abs() < 11.0).count())
            .sum()
    };
    let before = inside(&alone, false) as f32;
    let after = inside(&stacked, true) as f32;
    assert!(after < 0.2 * before, "{after} of {before} stitches left under the upper layer");
    assert_eq!(stacked.blocks.last().unwrap().thread.name, "White");
    let _ = JUMP;
}

#[test]
#[ignore]
fn debug_colours() {
    for name in ["logo.png", "dsa.gif"] {
        if !have(name) {
            continue;
        }
        let src = load(name);
        let cw = (HOOP * S).round() as usize;
        let pl = place(&src, cw, cw, S, 2.5, true);
        eprintln!("{name}: bg {:?} upscale {:.2} rect {:?}", pl.bg, pl.upscale, pl.rect);
        let raw = super::raster::to_lab(&pl.img);
        let k = 2 * (pl.upscale.round() as usize).max(1) + 1;
        let g = super::raster::lab_gradient(&raw, pl.img.w, pl.img.h, k);
        let g3 = super::raster::lab_gradient(&raw, pl.img.w, pl.img.h, 3);
        // darkest pixels and their gradients
        let mut dark: Vec<(f32, f32, f32)> = raw.iter().enumerate().filter(|(i, l)| l[0] < 30.0 && pl.img.px[i * 4 + 3] > 128).map(|(i, l)| (l[0], g[i], g3[i])).collect();
        dark.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        eprintln!("  dark px {} first {:?}", dark.len(), &dark[..dark.len().min(8)]);
        let n3 = dark.iter().filter(|d| d.2 <= 6.0).count();
        eprintln!("  dark with grad3<=6: {n3}");
    }
}

#[test]
fn one_layer_per_colour_stitches_like_one_layer() {
    let t = trace("logo.png", "{}");
    let all = grouped(&t.shapes, "logo");
    let one = plan(&design(&[all.clone()]));
    // the same shapes, one layer per thread, biggest colour at the bottom
    let mut by: Vec<(String, Vec<J>, f64)> = Vec::new();
    for s in &all {
        let k = s.get("thread").dump();
        let a = s.get("area").f(0.0);
        match by.iter_mut().find(|b| b.0 == k) {
            Some(b) => {
                b.1.push(s.clone());
                b.2 += a;
            }
            None => by.push((k, vec![s.clone()], a)),
        }
    }
    by.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap());
    let layers: Vec<Vec<J>> = by.into_iter().map(|b| b.1).collect();
    let split = plan(&design(&layers));
    let (a, b) = (one.stitch_count() as f32, split.stitch_count() as f32);
    assert!((a - b).abs() < 0.1 * a, "{a} vs {b}");
    let colours = |p: &Plan| p.blocks.iter().map(|b| b.thread.name.clone()).collect::<std::collections::BTreeSet<_>>().len();
    assert_eq!(colours(&one), colours(&split));
    assert!(split.blocks.len() <= one.blocks.len(), "{} vs {} blocks", split.blocks.len(), one.blocks.len());
}
