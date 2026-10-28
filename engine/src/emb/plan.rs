//! The sequencer: turns layers of shapes into a stitch plan — colour order, hidden stitches
//! removed, overlaps grown, stages inside each shape, travel instead of trims, ties and limits.

use super::geom::*;
use super::json::J;
use super::raster::Mask;
use super::stitch::{shape_stages, Kind, Run, Settings, MASK_S};
use super::trace::trace_mask;

pub const ST: u8 = 0;
pub const JUMP: u8 = 1;
pub const TRIM: u8 = 2;

#[derive(Clone, Debug, PartialEq)]
pub struct Thread {
    pub rgb: [u8; 3],
    pub pec: Option<usize>,
    pub name: String,
}

impl Thread {
    pub fn from_json(j: &J) -> Thread {
        let c = j.get("rgb");
        let pec = j.get("pec").i(0);
        Thread {
            rgb: [c.at(0).i(0) as u8, c.at(1).i(0) as u8, c.at(2).i(0) as u8],
            pec: if pec > 0 { Some(pec as usize) } else { None },
            name: j.get("name").s().to_string(),
        }
    }
    pub fn to_json(&self) -> J {
        let mut t = J::obj();
        t.set("rgb", J::Arr(self.rgb.iter().map(|v| J::from(*v as i64)).collect()));
        if let Some(p) = self.pec {
            t.set("pec", J::from(p as i64));
        }
        t.set("name", J::from(self.name.clone()));
        t
    }
}

#[derive(Clone, Debug)]
pub struct Block {
    pub thread: Thread,
    pub cmds: Vec<(f32, f32, u8)>,
    /// a stop (colour change to the same thread on a single-needle machine) follows this block
    pub stop: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Plan {
    pub blocks: Vec<Block>,
}

impl Plan {
    pub fn stitch_count(&self) -> usize {
        self.blocks.iter().map(|b| b.cmds.iter().filter(|c| c.2 == ST).count()).sum()
    }
    pub fn count(&self, cmd: u8) -> usize {
        self.blocks.iter().map(|b| b.cmds.iter().filter(|c| c.2 == cmd).count()).sum()
    }
    pub fn bounds(&self) -> (f32, f32, f32, f32) {
        let mut b = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
        for bl in &self.blocks {
            for c in &bl.cmds {
                b.0 = b.0.min(c.0);
                b.1 = b.1.min(c.1);
                b.2 = b.2.max(c.0);
                b.3 = b.3.max(c.1);
            }
        }
        if b.0 > b.2 {
            (0.0, 0.0, 0.0, 0.0)
        } else {
            b
        }
    }
    pub fn info(&self) -> J {
        let mut j = J::obj();
        let mut blocks = Vec::new();
        for b in &self.blocks {
            let mut o = J::obj();
            o.set("thread", b.thread.to_json());
            o.set("stitches", J::from(b.cmds.iter().filter(|c| c.2 == ST).count()));
            o.set("stop", J::from(b.stop));
            blocks.push(o);
        }
        j.set("blocks", J::Arr(blocks));
        j.set("stitches", J::from(self.stitch_count()));
        j.set("jumps", J::from(self.count(JUMP)));
        j.set("trims", J::from(self.count(TRIM)));
        let bb = self.bounds();
        j.set("bounds", J::Arr(vec![J::from(bb.0), J::from(bb.1), J::from(bb.2), J::from(bb.3)]));
        j.set("colour_changes", J::from(self.blocks.len().saturating_sub(1)));
        j
    }
}

pub struct DocSettings {
    pub hoop: (f32, f32),
    pub trim: f32,
    pub ties: bool,
    pub min: f32,
    pub max: f32,
    pub overlap: f32,
}

impl DocSettings {
    pub fn from_json(j: &J) -> DocSettings {
        let h = j.get("hoop");
        DocSettings {
            hoop: (h.at(0).f32(100.0).max(10.0), h.at(1).f32(100.0).max(10.0)),
            trim: j.get("trim").f32(2.0).max(0.0),
            ties: j.get("ties").b(true),
            min: j.get("min").f32(0.3).clamp(0.0, 2.0),
            max: j.get("max").f32(7.0).clamp(2.0, 12.0),
            overlap: j.get("overlap").f32(0.3).clamp(0.0, 2.0),
        }
    }
}

#[derive(Clone)]
struct ShapeIn {
    rings: Vec<Ring>,
    thread: Thread,
    st: Settings,
    stop: bool,
    group: String,
}

enum Obj {
    Shape(ShapeIn),
    Stitches { blocks: Vec<Block> },
}

fn rings_from(j: &J) -> Vec<Ring> {
    j.arr()
        .iter()
        .map(|r| r.arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0))).collect::<Ring>())
        .filter(|r: &Ring| r.len() >= 3)
        .collect()
}

pub fn stitch_blocks_from(j: &J) -> Vec<Block> {
    j.get("blocks")
        .arr()
        .iter()
        .map(|b| Block {
            thread: Thread::from_json(b.get("thread")),
            cmds: b.get("pts").arr().iter().map(|p| (p.at(0).f32(0.0), p.at(1).f32(0.0), p.at(2).i(0) as u8)).collect(),
            stop: b.get("stop").b(false),
        })
        .collect()
}

fn parse_layers(j: &J) -> Vec<Vec<Obj>> {
    let mut layers = Vec::new();
    for l in j.get("layers").arr() {
        let mut objs = Vec::new();
        for o in l.get("objects").arr() {
            if o.get("kind").s() == "stitches" {
                objs.push(Obj::Stitches { blocks: stitch_blocks_from(o) });
                continue;
            }
            let rings = rings_from(o.get("rings"));
            if rings.is_empty() {
                continue;
            }
            objs.push(Obj::Shape(ShapeIn {
                rings,
                thread: Thread::from_json(o.get("thread")),
                st: Settings::from_json(o),
                stop: o.get("stop").b(false),
                group: o.get("group").s().to_string(),
            }));
        }
        layers.push(objs);
    }
    layers
}

/// A mask of the whole hoop (plus a margin) on the global grid.
fn hoop_mask(ds: &DocSettings, s: f32) -> Mask {
    let (hw, hh) = (ds.hoop.0 / 2.0 + 5.0, ds.hoop.1 / 2.0 + 5.0);
    Mask::new((-hw * s).floor() / s, (-hh * s).floor() / s, hw, hh, s)
}

fn fill_global(g: &mut Mask, rings: &[Ring]) {
    // fill only the rows and columns the shape spans: faster than scanning the whole hoop
    let b = bbox(rings);
    let j0 = (((b.1 - g.y0) * g.s).floor().max(0.0)) as usize;
    let j1 = ((((b.3 - g.y0) * g.s).ceil()) as usize + 1).min(g.h);
    if j0 >= j1 {
        return;
    }
    let mut sub = Mask { w: g.w, h: j1 - j0, s: g.s, x0: g.x0, y0: g.y0 + j0 as f32 / g.s, v: vec![false; g.w * (j1 - j0)] };
    sub.fill(rings, true);
    for (k, v) in sub.v.iter().enumerate() {
        if *v {
            g.v[j0 * g.w + k] = true;
        }
    }
}

/// The part of `rings` left after taking away `cut` (global grid); None when nothing changed.
fn subtract(rings: &[Ring], cut: &Mask) -> Option<Vec<Vec<Ring>>> {
    let b = bbox(rings);
    let s = cut.s;
    // the shape on the global grid
    let x0 = cut.x0 + ((b.0 - cut.x0) * s).floor().max(0.0) / s - 1.0 / s;
    let y0 = cut.y0 + ((b.1 - cut.y0) * s).floor().max(0.0) / s - 1.0 / s;
    let mut m = Mask::new(x0, y0, b.2 + 2.0 / s, b.3 + 2.0 / s, s);
    m.fill(rings, true);
    let ox = ((x0 - cut.x0) * s).round() as i64;
    let oy = ((y0 - cut.y0) * s).round() as i64;
    let mut removed = 0usize;
    let before = m.count();
    for j in 0..m.h {
        for i in 0..m.w {
            let k = j * m.w + i;
            if !m.v[k] {
                continue;
            }
            let (gi, gj) = (i as i64 + ox, j as i64 + oy);
            if gi >= 0 && gj >= 0 && (gi as usize) < cut.w && (gj as usize) < cut.h && cut.v[gj as usize * cut.w + gi as usize] {
                m.v[k] = false;
                removed += 1;
            }
        }
    }
    if removed == 0 {
        return None;
    }
    if removed * 50 < before {
        // a sliver: not worth re-tracing (and re-tracing blunts the outline slightly)
        if removed * 400 < before {
            return None;
        }
    }
    Some(trace_mask(&m, 0.05).into_iter().filter(|r| rings_area(r) > 0.2).collect())
}

/// Grow a fill by `d` only where `later` (what is sewn after it) will cover it.
fn grow_into(rings: &[Ring], later: &Mask, d: f32) -> Vec<Ring> {
    let b = bbox(rings);
    let s = later.s;
    let x0 = later.x0 + ((b.0 - d - 0.5 - later.x0) * s).floor().max(0.0) / s;
    let y0 = later.y0 + ((b.1 - d - 0.5 - later.y0) * s).floor().max(0.0) / s;
    let mut m = Mask::new(x0, y0, b.2 + d + 0.5, b.3 + d + 0.5, s);
    m.fill(rings, true);
    let g = m.offset(d);
    let ox = ((x0 - later.x0) * s).round() as i64;
    let oy = ((y0 - later.y0) * s).round() as i64;
    let mut out = m.clone();
    let mut grew = false;
    for j in 0..m.h {
        for i in 0..m.w {
            let k = j * m.w + i;
            if m.v[k] || !g.v[k] {
                continue;
            }
            let (gi, gj) = (i as i64 + ox, j as i64 + oy);
            if gi >= 0 && gj >= 0 && (gi as usize) < later.w && (gj as usize) < later.h && later.v[gj as usize * later.w + gi as usize] {
                out.v[k] = true;
                grew = true;
            }
        }
    }
    if !grew {
        return rings.to_vec();
    }
    let mut parts = trace_mask(&out, 0.05);
    parts.sort_by(|a, b| rings_area(b).partial_cmp(&rings_area(a)).unwrap());
    parts.into_iter().next().unwrap_or_else(|| rings.to_vec())
}

struct Unit {
    thread: Thread,
    stop: bool,
    /// keep this unit where it is (appliqué parts: their stops must follow them)
    pin: bool,
    work: UnitWork,
}

/// The units one shape makes: usually one; appliqué makes three with stops between.
fn shape_units(rings: Vec<Ring>, thread: Thread, st: &Settings, stop: bool, angle: f32) -> Vec<Unit> {
    if st.kind == Kind::Applique {
        let parts = super::stitch::applique_parts(&rings, st, angle);
        let n = parts.len();
        return parts
            .into_iter()
            .enumerate()
            .map(|(k, stages)| Unit { thread: thread.clone(), stop: if k + 1 < n { true } else { stop }, pin: true, work: UnitWork::Shape { rings: rings.clone(), stages } })
            .collect();
    }
    let (_, stages) = shape_stages(&rings, st, angle);
    vec![Unit { thread, stop, pin: false, work: UnitWork::Shape { rings, stages } }]
}

enum UnitWork {
    Shape { rings: Vec<Ring>, stages: Vec<Vec<Run>> },
    Stitches(Vec<(f32, f32, u8)>),
}

struct Emitter<'a> {
    ds: &'a DocSettings,
    blocks: Vec<Block>,
    pos: Pt,
    started: bool,
    top: Mask,
    last_thread: Option<Thread>,
    pending_stop: bool,
}

impl<'a> Emitter<'a> {
    fn cur(&mut self) -> &mut Vec<(f32, f32, u8)> {
        &mut self.blocks.last_mut().unwrap().cmds
    }
    fn clamp(&self, p: Pt) -> Pt {
        let (hw, hh) = (self.ds.hoop.0 / 2.0 - 0.2, self.ds.hoop.1 / 2.0 - 0.2);
        (p.0.clamp(-hw, hw), p.1.clamp(-hh, hh))
    }
    /// A stitch to p: split if too long, dropped if too short (ties excepted).
    fn stitch(&mut self, p: Pt, tie: bool) {
        let p = self.clamp(p);
        let d = dist(self.pos, p);
        if !tie && d < self.ds.min {
            return;
        }
        let max = self.ds.max;
        let from = self.pos;
        for q in split_move(from, p, max) {
            self.cur().push((q.0, q.1, ST));
        }
        self.pos = p;
    }
    fn tie_in(&mut self, toward: Pt) {
        let p = self.pos;
        self.cur().push((p.0, p.1, ST));
        if !self.ds.ties {
            return;
        }
        let d = norm(sub(toward, p));
        if d == (0.0, 0.0) {
            return;
        }
        let q = add(p, mul(d, 0.5));
        self.stitch(q, true);
        self.stitch(p, true);
    }
    fn tie_off(&mut self) {
        if !self.ds.ties {
            return;
        }
        let cmds = &self.blocks.last().unwrap().cmds;
        let n = cmds.len();
        if n < 2 {
            return;
        }
        let p = self.pos;
        // back along the last stitch
        let mut prev = None;
        for c in cmds.iter().rev() {
            if c.2 == ST && dist((c.0, c.1), p) > 0.05 {
                prev = Some((c.0, c.1));
                break;
            }
        }
        let Some(o) = prev else { return };
        let q = add(p, mul(norm(sub(o, p)), 0.5));
        self.stitch(q, true);
        self.stitch(p, true);
    }
    /// Move the needle to p without sewing: a jump, with a trim (and ties) when it is long.
    fn jump(&mut self, p: Pt, next: Pt) {
        let p = self.clamp(p);
        let d = dist(self.pos, p);
        let had = self.blocks.last().map(|b| !b.cmds.is_empty()).unwrap_or(false);
        if had && d < 0.05 {
            return;
        }
        let long = d > self.ds.trim;
        if had && long {
            self.tie_off();
            let pos = self.pos;
            self.cur().push((pos.0, pos.1, TRIM));
        }
        for q in split_move(self.pos, p, 12.0) {
            self.cur().push((q.0, q.1, JUMP));
        }
        self.pos = p;
        if long || !had {
            self.tie_in(next);
        } else {
            let pos = self.pos;
            self.cur().push((pos.0, pos.1, ST));
        }
    }
    fn begin_thread(&mut self, t: &Thread, force_new: bool) {
        let same = self.last_thread.as_ref() == Some(t);
        if !same || force_new || self.blocks.is_empty() {
            if !self.blocks.is_empty() {
                self.tie_off();
                if force_new && same {
                    self.blocks.last_mut().unwrap().stop = true;
                }
            }
            self.blocks.push(Block { thread: t.clone(), cmds: Vec::new(), stop: false });
            self.last_thread = Some(t.clone());
        }
    }
    fn stamp_top(&mut self, a: Pt, b: Pt) {
        let s = self.top.s;
        let r = 0.25 * s;
        let n = ((dist(a, b) * s).ceil() as usize).max(1);
        let ri = r.ceil() as i64;
        for k in 0..=n {
            let p = lerp(a, b, k as f32 / n as f32);
            let ci = ((p.0 - self.top.x0) * s) as i64;
            let cj = ((p.1 - self.top.y0) * s) as i64;
            for dj in -ri..=ri {
                for di in -ri..=ri {
                    if ((di * di + dj * dj) as f32) > r * r {
                        continue;
                    }
                    let (i, j) = (ci + di, cj + dj);
                    if i >= 0 && j >= 0 && (i as usize) < self.top.w && (j as usize) < self.top.h {
                        self.top.v[j as usize * self.top.w + i as usize] = true;
                    }
                }
            }
        }
    }
    fn over_top(&self, route: &[Pt]) -> f32 {
        let mut over = 0.0;
        for w in route.windows(2) {
            let l = dist(w[0], w[1]);
            let n = ((l / 0.1).ceil() as usize).max(1);
            for k in 0..n {
                let p = lerp(w[0], w[1], (k as f32 + 0.5) / n as f32);
                if self.top.at_mm(p) {
                    over += l / n as f32;
                }
            }
        }
        over
    }
    fn sew(&mut self, pts: &[Pt], top: bool) {
        for &p in pts {
            let before = self.pos;
            self.stitch(p, false);
            if top && dist(before, self.pos) > 0.0 {
                self.stamp_top(before, self.pos);
            }
        }
    }
}

/// A travel route inside the shape from a to b: straight when the line stays inside, else
/// along the 0.3 mm-inset outline. None when no acceptable route exists.
fn travel_route(rings: &[Ring], inset: &[Ring], a: Pt, b: Pt) -> Option<Vec<Pt>> {
    let straight = dist(a, b);
    if straight < 1e-4 {
        return Some(vec![a, b]);
    }
    if segment_inside(rings, a, b) {
        return Some(vec![a, b]);
    }
    if inset.is_empty() {
        return None;
    }
    let (ra, ka, ta, _) = nearest_on_rings(inset, a);
    let (rb, kb, tb, _) = nearest_on_rings(inset, b);
    if ra != rb {
        return None;
    }
    let r = &inset[ra];
    let n = r.len();
    let pa = lerp(r[ka], r[(ka + 1) % n], ta);
    let pb = lerp(r[kb], r[(kb + 1) % n], tb);
    // the clear line from the ring point to the target must exist
    if !segment_inside(rings, a, pa) && dist(a, pa) > 0.35 {
        return None;
    }
    if !segment_inside(rings, pb, b) && dist(pb, b) > 0.35 {
        return None;
    }
    let walk = |fwd: bool| -> Vec<Pt> {
        let mut out = vec![a, pa];
        if ka == kb && ((fwd && tb >= ta) || (!fwd && tb <= ta)) {
            out.push(pb);
            out.push(b);
            return out;
        }
        let mut k = ka;
        for _ in 0..n + 1 {
            if fwd {
                k = (k + 1) % n;
                out.push(r[k]);
                if k == kb {
                    break;
                }
            } else {
                out.push(r[k]);
                if k == (kb + 1) % n {
                    break;
                }
                k = (k + n - 1) % n;
            }
        }
        out.push(pb);
        out.push(b);
        out
    };
    let f = walk(true);
    let g = walk(false);
    let route = if path_length(&f) <= path_length(&g) { f } else { g };
    if path_length(&route) > 3.0 * straight + 15.0 {
        return None;
    }
    Some(route)
}

fn inset_rings(rings: &[Ring]) -> Vec<Ring> {
    rings
        .iter()
        .enumerate()
        .map(|(i, r)| offset_ring(r, if i == 0 { -0.3 } else { 0.3 }))
        .filter(|r| r.len() >= 3)
        .collect()
}

fn entry(run: &Run, pos: Pt) -> (f32, Vec<Pt>) {
    if run.closed {
        let (mut bi, mut bd) = (0, f32::MAX);
        for (i, p) in run.pts.iter().enumerate() {
            let d = dist(*p, pos);
            if d < bd {
                bd = d;
                bi = i;
            }
        }
        let mut v: Vec<Pt> = run.pts[bi..].to_vec();
        v.extend_from_slice(&run.pts[..bi]);
        v.push(run.pts[bi]);
        return (bd, v);
    }
    let d0 = dist(run.pts[0], pos);
    if let Some(alt) = &run.alt {
        if !alt.is_empty() && dist(alt[0], pos) < d0 {
            return (dist(alt[0], pos), alt.clone());
        }
    }
    (d0, run.pts.clone())
}

fn emit_shape(e: &mut Emitter, rings: &[Ring], stages: &[Vec<Run>]) {
    let inset = inset_rings(rings);
    for stage in stages {
        let mut left: Vec<&Run> = stage.iter().filter(|r| r.pts.len() >= 2).collect();
        while !left.is_empty() {
            let pos = e.pos;
            let (mut bi, mut bd, mut bp) = (0, f32::MAX, Vec::new());
            for (i, r) in left.iter().enumerate() {
                let (d, p) = entry(r, pos);
                if d < bd {
                    bd = d;
                    bi = i;
                    bp = p;
                }
            }
            let run = left.remove(bi);
            let start = bp[0];
            let fresh = e.blocks.last().map(|b| b.cmds.is_empty()).unwrap_or(true);
            let mut travelled = false;
            if !fresh && (inside(rings, e.pos) || nearest_on_rings(rings, e.pos).3 < 0.3) {
                if let Some(route) = travel_route(rings, &inset, e.pos, start) {
                    if e.over_top(&route) <= 1.0 {
                        let mut pts = Vec::new();
                        for w in route.windows(2) {
                            pts.extend(split_move(w[0], w[1], 3.0));
                        }
                        e.sew(&pts, false);
                        travelled = true;
                    }
                }
            }
            if !travelled {
                let next = *bp.get(1).unwrap_or(&start);
                e.jump(start, next);
            }
            e.sew(&bp[1..], run.top);
        }
    }
}

/// Make the plan for a design (JSON: settings + layers of objects, bottom layer first).
pub fn plan(design: &J) -> Plan {
    let ds = DocSettings::from_json(design.get("settings"));
    let mut layers = parse_layers(design);
    let s = MASK_S;

    // hidden stitches: take away what upper layers cover (shrunk by the overlap) from lower ones
    let nl = layers.len();
    if nl > 1 {
        let mut above = hoop_mask(&ds, s);
        let mut any_above = false;
        for li in (0..nl).rev() {
            if any_above {
                let cut = above.offset(-ds.overlap);
                let objs = std::mem::take(&mut layers[li]);
                let mut out = Vec::new();
                for o in objs {
                    match o {
                        Obj::Shape(sh) if sh.st.kind == Kind::Knockdown => out.push(Obj::Shape(sh)),
                        Obj::Shape(sh) => match subtract(&sh.rings, &cut) {
                            None => out.push(Obj::Shape(sh)),
                            Some(parts) => {
                                for p in parts {
                                    out.push(Obj::Shape(ShapeIn { rings: p, ..sh.clone() }));
                                }
                            }
                        },
                        other => out.push(other),
                    }
                }
                layers[li] = out;
            }
            for o in &layers[li] {
                if let Obj::Shape(sh) = o {
                    fill_global(&mut above, &sh.rings);
                    any_above = true;
                }
            }
        }
    }

    // order and stage every layer
    let mut units: Vec<Unit> = Vec::new();
    let mut colour_index: Vec<Thread> = Vec::new();
    let angle_for = |t: &Thread, ci: &mut Vec<Thread>| -> f32 {
        let i = match ci.iter().position(|x| x == t) {
            Some(i) => i,
            None => {
                ci.push(t.clone());
                ci.len() - 1
            }
        };
        if i % 2 == 0 {
            45.0
        } else {
            135.0
        }
    };
    // a picture's colours may sit on layers of their own: each layer's fills still grow under
    // the same picture's colours on the layers above
    let group_shapes: Vec<Vec<(String, Vec<Ring>)>> = layers
        .iter()
        .map(|objs| {
            objs.iter()
                .filter_map(|o| match o {
                    Obj::Shape(sh) if !sh.group.is_empty() => Some((sh.group.clone(), sh.rings.clone())),
                    _ => None,
                })
                .collect()
        })
        .collect();
    for (li, objs) in layers.into_iter().enumerate() {
        // split into runs: consecutive shapes of one traced group, or single objects
        let mut i = 0;
        let objs: Vec<Obj> = objs;
        let mut groups: Vec<Vec<Obj>> = Vec::new();
        let mut cur_group = String::new();
        for o in objs {
            let g = match &o {
                Obj::Shape(sh) => sh.group.clone(),
                _ => String::new(),
            };
            if g.is_empty() || g != cur_group || groups.is_empty() {
                groups.push(Vec::new());
            }
            cur_group = g;
            groups.last_mut().unwrap().push(o);
            i += 1;
        }
        let _ = i;
        for grp in groups {
            let is_traced = matches!(grp.first(), Some(Obj::Shape(s)) if !s.group.is_empty());
            if !is_traced {
                for o in grp {
                    match o {
                        Obj::Shape(sh) => {
                            let angle = sh.st.angle.unwrap_or_else(|| angle_for(&sh.thread, &mut colour_index));
                            units.extend(shape_units(sh.rings, sh.thread, &sh.st, sh.stop, angle));
                        }
                        Obj::Stitches { blocks } => {
                            for b in blocks {
                                units.push(Unit { thread: b.thread, stop: b.stop, pin: false, work: UnitWork::Stitches(b.cmds) });
                            }
                        }
                    }
                }
                continue;
            }
            // traced picture: large fill colours first, thin detail last, largest first
            let shapes: Vec<ShapeIn> = grp.into_iter().filter_map(|o| if let Obj::Shape(s) = o { Some(s) } else { None }).collect();
            let kinds: Vec<Kind> = shapes
                .iter()
                .map(|sh| {
                    if sh.st.kind != Kind::Auto {
                        sh.st.kind
                    } else {
                        let m = super::stitch::shape_mask(&sh.rings, 0.5);
                        let k = super::stitch::auto_kind(super::stitch::inscribed_width(&m));
                        // small traced pieces (letters, marks) fan out as satin: fill holds their
                        // shape better, as with lettering under 8 mm
                        let b = bbox(&sh.rings);
                        if k == Kind::Satin && (b.2 - b.0).max(b.3 - b.1) < 6.0 {
                            Kind::Fill
                        } else {
                            k
                        }
                    }
                })
                .collect();
            let areas: Vec<f32> = shapes.iter().map(|s| rings_area(&s.rings)).collect();
            let mut colour_area: Vec<(Thread, bool, f32)> = Vec::new();
            for (k, sh) in shapes.iter().enumerate() {
                let fill = kinds[k] == Kind::Fill;
                match colour_area.iter_mut().find(|c| c.0 == sh.thread && c.1 == fill) {
                    Some(c) => c.2 += areas[k],
                    None => colour_area.push((sh.thread.clone(), fill, areas[k])),
                }
            }
            colour_area.sort_by(|a, b| b.1.cmp(&a.1).then(b.2.partial_cmp(&a.2).unwrap()));
            let mut order: Vec<usize> = (0..shapes.len()).collect();
            order.sort_by_key(|&k| {
                let fill = kinds[k] == Kind::Fill;
                let ci = colour_area.iter().position(|c| c.0 == shapes[k].thread && c.1 == fill).unwrap_or(0);
                (ci, (-(areas[k] * 100.0)) as i64)
            });
            // overlap: grow each fill only where something sewn later covers it
            let mut later = hoop_mask(&ds, s);
            let gname = shapes.first().map(|sh| sh.group.clone()).unwrap_or_default();
            for upper in group_shapes.iter().skip(li + 1) {
                for (g, r) in upper {
                    if *g == gname {
                        fill_global(&mut later, r);
                    }
                }
            }
            let mut grown: Vec<Vec<Ring>> = vec![Vec::new(); shapes.len()];
            for &k in order.iter().rev() {
                grown[k] = if kinds[k] == Kind::Fill && ds.overlap > 0.0 { grow_into(&shapes[k].rings, &later, ds.overlap) } else { shapes[k].rings.clone() };
                fill_global(&mut later, &shapes[k].rings);
            }
            for &k in &order {
                let sh = &shapes[k];
                let angle = sh.st.angle.unwrap_or_else(|| angle_for(&sh.thread, &mut colour_index));
                let mut st = sh.st.clone();
                st.kind = kinds[k];
                units.extend(shape_units(grown[k].clone(), sh.thread.clone(), &st, sh.stop, angle));
            }
        }
    }
    // inside one colour, visit shapes nearest-first: reorder runs of consecutive same-thread
    // shape units by proximity
    let units = nearest_first(units);

    let mut e = Emitter { ds: &ds, blocks: Vec::new(), pos: (0.0, 0.0), started: false, top: hoop_mask(&ds, 10.0), last_thread: None, pending_stop: false };
    for u in units {
        let force = e.pending_stop;
        e.begin_thread(&u.thread, force);
        e.pending_stop = false;
        match u.work {
            UnitWork::Shape { rings, stages } => emit_shape(&mut e, &rings, &stages),
            UnitWork::Stitches(cmds) => {
                let mut first = true;
                let mut trim_next = false;
                for (i, c) in cmds.iter().enumerate() {
                    let p = (c.0, c.1);
                    if first {
                        let next = cmds.get(i + 1).map(|n| (n.0, n.1)).unwrap_or(p);
                        e.jump(p, next);
                        first = false;
                        continue;
                    }
                    match c.2 {
                        TRIM => trim_next = true,
                        JUMP => {
                            if trim_next {
                                let pos = e.pos;
                                e.cur().push((pos.0, pos.1, TRIM));
                                trim_next = false;
                            }
                            let pp = e.clamp(p);
                            e.cur().push((pp.0, pp.1, JUMP));
                            e.pos = pp;
                        }
                        _ => {
                            let pp = e.clamp(p);
                            e.cur().push((pp.0, pp.1, ST));
                            e.pos = pp;
                        }
                    }
                }
            }
        }
        e.started = true;
        if u.stop {
            e.pending_stop = true;
        }
    }
    if !e.blocks.is_empty() {
        e.tie_off();
    }
    let mut blocks: Vec<Block> = e.blocks.into_iter().filter(|b| b.cmds.iter().any(|c| c.2 == ST)).collect();
    // a stop on the very last block means nothing
    if let Some(l) = blocks.last_mut() {
        l.stop = false;
    }
    Plan { blocks }
}

fn unit_centre(u: &Unit) -> Pt {
    match &u.work {
        UnitWork::Shape { rings, .. } => {
            let b = bbox(rings);
            ((b.0 + b.2) / 2.0, (b.1 + b.3) / 2.0)
        }
        UnitWork::Stitches(c) => c.first().map(|p| (p.0, p.1)).unwrap_or((0.0, 0.0)),
    }
}

fn nearest_first(units: Vec<Unit>) -> Vec<Unit> {
    let mut out: Vec<Unit> = Vec::with_capacity(units.len());
    let mut i = 0;
    let mut units: Vec<Option<Unit>> = units.into_iter().map(Some).collect();
    let n = units.len();
    let mut pos = (0.0f32, 0.0f32);
    while i < n {
        // a run of shape units with the same thread and no stop inside
        let t = units[i].as_ref().unwrap().thread.clone();
        let mut j = i;
        while j < n {
            let u = units[j].as_ref().unwrap();
            if u.thread != t || !matches!(u.work, UnitWork::Shape { .. }) || u.pin {
                break;
            }
            j += 1;
            if u.stop {
                break;
            }
        }
        if j <= i + 1 {
            let u = units[i].take().unwrap();
            pos = unit_centre(&u);
            out.push(u);
            i += 1;
            continue;
        }
        let mut left: Vec<usize> = (i..j).collect();
        // keep a stop flag on whichever unit ends up last
        let had_stop = (i..j).any(|k| units[k].as_ref().unwrap().stop);
        let mut picked = Vec::new();
        while !left.is_empty() {
            let (mut bi, mut bd) = (0, f32::MAX);
            for (q, &k) in left.iter().enumerate() {
                let d = dist(unit_centre(units[k].as_ref().unwrap()), pos);
                if d < bd {
                    bd = d;
                    bi = q;
                }
            }
            let k = left.remove(bi);
            let mut u = units[k].take().unwrap();
            u.stop = false;
            pos = unit_centre(&u);
            picked.push(u);
        }
        if had_stop {
            picked.last_mut().unwrap().stop = true;
        }
        out.extend(picked);
        i = j;
    }
    out
}

/// Stitch plan as compact JSON (for importing designs as stitch objects).
pub fn blocks_json(p: &Plan) -> J {
    let mut arr = Vec::new();
    for b in &p.blocks {
        let mut o = J::obj();
        o.set("thread", b.thread.to_json());
        o.set("stop", J::from(b.stop));
        o.set("pts", J::Arr(b.cmds.iter().map(|c| J::Arr(vec![J::from(c.0), J::from(c.1), J::from(c.2 as i64)])).collect()));
        arr.push(o);
    }
    let mut j = J::obj();
    j.set("blocks", J::Arr(arr));
    j
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::emb::json::parse;
    #[test]
    fn plan_two_squares() {
        let d = parse(
            r#"{"settings":{"hoop":[100,100]},"layers":[{"objects":[
            {"rings":[[[-30,-30],[0,-30],[0,0],[-30,0]]],"thread":{"rgb":[237,23,31],"pec":5,"name":"Red"}},
            {"rings":[[[5,5],[25,5],[25,25],[5,25]]],"thread":{"rgb":[0,0,0],"pec":20,"name":"Black"}}
            ]}]}"#,
        )
        .unwrap();
        let p = plan(&d);
        assert_eq!(p.blocks.len(), 2);
        for b in &p.blocks {
            let mut last: Option<Pt> = None;
            for c in &b.cmds {
                if c.2 == ST {
                    if let Some(l) = last {
                        assert!(dist(l, (c.0, c.1)) <= 7.0 + 1e-3);
                    }
                    last = Some((c.0, c.1));
                } else {
                    last = Some((c.0, c.1));
                }
            }
        }
        assert!(p.stitch_count() > 1200, "{}", p.stitch_count());
    }

    #[test]
    fn applique_stops_twice_and_knockdown_stays_whole() {
        let d = parse(
            r#"{"settings":{"hoop":[100,100]},"layers":[
            {"objects":[{"rings":[[[-40,-40],[40,-40],[40,40],[-40,40]]],"thread":{"rgb":[240,240,240],"pec":29,"name":"White"},"type":"knockdown"}]},
            {"objects":[{"rings":[[[-20,-20],[20,-20],[20,20],[-20,20]]],"thread":{"rgb":[237,23,31],"pec":5,"name":"Red"},"type":"applique"}]}
            ]}"#,
        )
        .unwrap();
        let p = plan(&d);
        let names: Vec<(String, bool)> = p.blocks.iter().map(|b| (b.thread.name.clone(), b.stop)).collect();
        assert_eq!(names, vec![("White".into(), false), ("Red".into(), true), ("Red".into(), true), ("Red".into(), false)], "{:?}", names);
        // the knockdown is not cut under the appliqué
        let inside = p.blocks[0].cmds.iter().filter(|c| c.2 == ST && c.0.abs() < 15.0 && c.1.abs() < 15.0).count();
        assert!(inside > 50, "{inside}");
        // placement and tack-down are running lines; the cover sits on the edge
        let cover = &p.blocks[3];
        let on_edge = cover.cmds.iter().filter(|c| c.2 == ST && ((c.0.abs() - 20.0).abs() < 2.0 || (c.1.abs() - 20.0).abs() < 2.0)).count();
        let n = cover.cmds.iter().filter(|c| c.2 == ST).count();
        assert!(on_edge as f32 > 0.8 * n as f32, "{on_edge} of {n}");
    }
}
