"""Embroidery for Folio Draw: the engine binding, the embroidery document model (hoop, shape
layers, threads) and the thread-view rendering. The interface lives in embui.py."""

import ctypes
import json
import math
import os
from ctypes import POINTER, c_char_p, c_float, c_int, c_uint, c_void_p

from .engine import L, _P

# ---------------------------------------------------------------- engine binding


def _sig(name, res, *args):
    f = getattr(L, name)
    f.restype = res
    f.argtypes = list(args)


_sig("fd_emb_free_str", None, c_void_p)
_sig("fd_emb_get", c_void_p, _P)
_sig("fd_emb_set", None, _P, c_char_p)
_sig("fd_emb_place", c_void_p, c_char_p, c_uint, c_uint, c_uint, c_uint, c_float, c_float, c_uint, c_void_p)
_sig("fd_emb_convert", c_void_p, c_char_p, c_uint, c_uint, c_float, c_float, c_float, c_char_p)
_sig("fd_emb_plan", c_void_p, c_char_p)
_sig("fd_emb_plan_free", None, c_void_p)
_sig("fd_emb_plan_info", c_void_p, c_void_p)
_sig("fd_emb_plan_len", c_uint, c_void_p)
_sig("fd_emb_plan_cmds", None, c_void_p, POINTER(c_float))
_sig("fd_emb_plan_json", c_void_p, c_void_p)
_sig("fd_emb_plan_write", c_int, c_void_p, c_char_p, c_uint, c_char_p)
_sig("fd_emb_read", c_void_p, c_char_p)
_sig("fd_emb_density", None, c_void_p, c_float, c_float, c_float, c_uint, c_uint, c_void_p)
_sig("fd_emb_threads", c_void_p)
_sig("fd_emb_nearest_thread", c_uint, c_uint, c_uint, c_uint)
_sig("fd_emb_shapes", c_void_p, c_char_p)
_sig("fd_last_error", c_char_p)


class EngineError(Exception):
    pass


def _take(p):
    if not p:
        raise EngineError((L.fd_last_error() or b"").decode("utf-8", "replace") or "the engine failed")
    s = ctypes.cast(p, c_char_p).value.decode("utf-8", "replace")
    L.fd_emb_free_str(p)
    return s


def _take_json(p):
    s = _take(p)
    return json.loads(s) if s else {}


ST, JUMP, TRIM = 0, 1, 2
FMT_PES, FMT_DST, FMT_PEC = 0, 1, 2

PX_PER_MM = 10.0          # embroidery canvas resolution
MM_PER_INCH = 25.4

# hoops: name -> (width mm, height mm). The Skitch PP1 takes the 4" × 4" (100 × 100 mm) hoop.
HOOPS = [
    ("4 × 4 in (100 × 100 mm)", 101.6, 101.6),
    ("5 × 7 in (130 × 180 mm)", 127.0, 177.8),
    ("6 × 10 in (160 × 260 mm)", 152.4, 254.0),
    ("8 × 8 in (200 × 200 mm)", 203.2, 203.2),
    ("8 × 12 in (200 × 300 mm)", 203.2, 304.8),
]

MACHINES = {
    "Brother Skitch PP1": {"needles": 1, "hoops": ["4 × 4 in (100 × 100 mm)"], "spm": 400, "trimmer": False},
    "Single-needle machine": {"needles": 1, "hoops": None, "spm": 650, "trimmer": False},
    "Multi-needle machine": {"needles": 6, "hoops": None, "spm": 1000, "trimmer": True},
}

DEFAULT_SETTINGS = {
    "hoop": HOOPS[0][0],
    "hoop_mm": [HOOPS[0][1], HOOPS[0][2]],
    "machine": "Brother Skitch PP1",
    "fabric": [244, 239, 226],
    "threads": "brother",
    "trim": 2.0,
    "ties": True,
    "min": 0.3,
    "max": 7.0,
}


def threads():
    """The Brother 63-colour chart: [{pec, name, rgb}]."""
    return _take_json(L.fd_emb_threads())


_CHART = None


def chart():
    global _CHART
    if _CHART is None:
        _CHART = threads()
    return _CHART


def chart_thread(pec):
    for t in chart():
        if t["pec"] == pec:
            return dict(t)
    return dict(chart()[19])


def nearest_thread(rgb):
    return chart_thread(int(L.fd_emb_nearest_thread(int(rgb[0]), int(rgb[1]), int(rgb[2]))))


def thread_label(t):
    if t.get("pec"):
        return "%s (%d)" % (t.get("name") or chart_thread(t["pec"])["name"], t["pec"])
    return t.get("name") or "#%02X%02X%02X" % tuple(t["rgb"])


def place(rgba, sw, sh, cw, ch, margin=2.5, crop=False):
    """Fit a picture to the hoop canvas. Returns (canvas RGBA bytes, info)."""
    out = ctypes.create_string_buffer(cw * ch * 4)
    info = _take_json(L.fd_emb_place(bytes(rgba), sw, sh, cw, ch, PX_PER_MM, margin, 1 if crop else 0, out))
    return out.raw, info


def convert(rgba, w, h, x0, y0, params):
    """A picture layer (RGBA, PX_PER_MM) → {shapes, colours}."""
    return _take_json(L.fd_emb_convert(bytes(rgba), w, h, PX_PER_MM, x0, y0, json.dumps(params).encode()))


def shapes_op(req):
    return _take_json(L.fd_emb_shapes(json.dumps(req).encode()))


class Plan:
    """A stitch plan (owned engine handle)."""

    def __init__(self, handle):
        if not handle:
            raise EngineError((L.fd_last_error() or b"").decode("utf-8", "replace") or "no plan")
        self.h = handle
        self._info = None
        self._cmds = None

    @classmethod
    def make(cls, design):
        return cls(L.fd_emb_plan(json.dumps(design).encode()))

    @classmethod
    def read(cls, path):
        return cls(L.fd_emb_read(path.encode()))

    def close(self):
        if self.h:
            L.fd_emb_plan_free(self.h)
            self.h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def info(self):
        if self._info is None:
            self._info = _take_json(L.fd_emb_plan_info(self.h))
        return self._info

    def cmds(self):
        """Flat list of (x, y, cmd, block)."""
        if self._cmds is None:
            n = L.fd_emb_plan_len(self.h)
            arr = (c_float * (n * 4))()
            L.fd_emb_plan_cmds(self.h, arr)
            self._cmds = [(arr[i], arr[i + 1], int(arr[i + 2]), int(arr[i + 3])) for i in range(0, n * 4, 4)]
        return self._cmds

    def blocks_json(self):
        return _take_json(L.fd_emb_plan_json(self.h))

    def write(self, path, fmt, name):
        if L.fd_emb_plan_write(self.h, path.encode(), fmt, name.encode()) != 0:
            raise EngineError((L.fd_last_error() or b"").decode("utf-8", "replace"))

    def density(self, s, x0, y0, w, h):
        out = ctypes.create_string_buffer(w * h)
        L.fd_emb_density(self.h, s, x0, y0, w, h, out)
        return out.raw

    @property
    def stitches(self):
        return self.info.get("stitches", 0)


# ---------------------------------------------------------------- document model

SHAPES_KIND = "emb-shapes"
PICTURE_KIND = "emb-picture"


def doc_settings(doc):
    """The embroidery settings of a document, or None for an ordinary picture."""
    raw = _take(L.fd_emb_get(doc.h))
    if not raw:
        return None
    try:
        s = json.loads(raw)
    except ValueError:
        return None
    out = dict(DEFAULT_SETTINGS)
    out.update(s)
    return out


def set_doc_settings(doc, s):
    L.fd_emb_set(doc.h, json.dumps(s, sort_keys=True).encode())


def hoop_mm(settings):
    return tuple(settings.get("hoop_mm") or (HOOPS[0][1], HOOPS[0][2]))


def canvas_px(settings):
    w, h = hoop_mm(settings)
    return int(round(w * PX_PER_MM)), int(round(h * PX_PER_MM))


def origin(settings):
    """mm position of pixel (0, 0): the hoop centre is (0, 0), y down."""
    w, h = hoop_mm(settings)
    return -w / 2.0, -h / 2.0


def mm_to_px(settings, x, y):
    ox, oy = origin(settings)
    return (x - ox) * PX_PER_MM, (y - oy) * PX_PER_MM


def px_to_mm(settings, x, y):
    ox, oy = origin(settings)
    return x / PX_PER_MM + ox, y / PX_PER_MM + oy


def layer_spec(doc, i):
    raw = doc.layer_text(i)
    if not raw or not raw.startswith("{"):
        return None
    try:
        s = json.loads(raw)
    except ValueError:
        return None
    return s if isinstance(s, dict) and s.get("kind") in (SHAPES_KIND, PICTURE_KIND) else None


def is_shape_layer(doc, i):
    s = layer_spec(doc, i)
    return bool(s and s.get("kind") == SHAPES_KIND)


def shape_layers(doc):
    return [i for i in range(doc.layer_count()) if is_shape_layer(doc, i)]


def new_object_id(spec):
    n = spec.get("next_id", 1)
    spec["next_id"] = n + 1
    return n


# stitch settings a shape carries (missing keys use the engine defaults)
STITCH_DEFAULTS = {"type": "auto", "angle": None, "spacing": 0.40, "length": 3.5, "pull": 0.20,
                   "underlay": True, "satin_spacing": 0.40, "min_width": 1.0, "run_length": 2.0, "bean": True}


def design_json(doc, settings, only_visible=True):
    """The design for the stitch planner: every visible shape layer, bottom first."""
    layers = []
    for i in range(doc.layer_count()):
        spec = layer_spec(doc, i)
        if not spec or spec.get("kind") != SHAPES_KIND:
            continue
        if only_visible and not doc.layer_props(i)["visible"]:
            continue
        objs = []
        for o in spec.get("objects", []):
            if o.get("hidden"):
                continue
            if o.get("kind") == "stitches":
                objs.append(transformed_stitches(o))
                continue
            st = dict(STITCH_DEFAULTS)
            if o.get("kind") == "lettering":
                from .letters import default_type
                st["type"] = default_type(float(o.get("cap", 10)))
            st.update(o.get("stitch") or {})
            if st.get("angle") is None:
                st.pop("angle", None)
            parts = object_shapes(o)
            for k, rings in enumerate(parts):
                d = {"rings": rings, "thread": o.get("thread", {"rgb": [0, 0, 0]}),
                     "stop": bool(o.get("stop")) and k == len(parts) - 1,
                     "group": o.get("group", "") if o.get("kind") != "lettering" else ""}
                d.update(st)
                objs.append(d)
        layers.append({"objects": objs})
    hw, hh = hoop_mm(settings)
    return {"settings": {"hoop": [hw, hh], "trim": settings.get("trim", 2.0), "ties": settings.get("ties", True),
                         "min": settings.get("min", 0.3), "max": settings.get("max", 7.0)}, "layers": layers}


def transformed_stitches(o):
    """An imported design's blocks with its move / rotate / mirror / scale applied."""
    tr = o.get("transform") or {}
    dx, dy = tr.get("dx", 0.0), tr.get("dy", 0.0)
    ang = math.radians(tr.get("rotate", 0.0))
    sx = tr.get("scale", 1.0) * (-1 if tr.get("mirror") else 1)
    sy = tr.get("scale", 1.0)
    c, s = math.cos(ang), math.sin(ang)
    blocks = []
    for b in o.get("blocks", []):
        pts = []
        for x, y, cmd in b["pts"]:
            x, y = x * sx, y * sy
            x, y = x * c - y * s + dx, x * s + y * c + dy
            pts.append([x, y, cmd])
        blocks.append({"thread": b["thread"], "stop": b.get("stop", False), "pts": pts})
    return {"kind": "stitches", "blocks": blocks}


def object_shapes(o):
    """The shapes ([outline, holes...] each) an object stitches as."""
    if o.get("kind") == "lettering":
        return [g for g in o.get("glyphs", []) if g]
    if o.get("kind") == "stitches":
        return []
    return [o.get("rings", [])] if o.get("rings") else []


def object_bounds(o):
    """(x0, y0, x1, y1) mm of a shape object (rings) or a stitch object."""
    xs, ys = [], []
    if o.get("kind") == "stitches":
        for b in transformed_stitches(o)["blocks"]:
            for x, y, _c in b["pts"]:
                xs.append(x)
                ys.append(y)
    else:
        for rings in object_shapes(o):
            for r in rings:
                for x, y in r:
                    xs.append(x)
                    ys.append(y)
    if not xs:
        return (0, 0, 0, 0)
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_rings(rings, x, y):
    c = False
    for r in rings:
        n = len(r)
        j = n - 1
        for i in range(n):
            xi, yi = r[i]
            xj, yj = r[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
                c = not c
            j = i
    return c


def object_at(o, x, y, tol=0.6):
    if o.get("kind") == "stitches":
        b = object_bounds(o)
        return b[0] - tol <= x <= b[2] + tol and b[1] - tol <= y <= b[3] + tol
    shapes = object_shapes(o)
    if o.get("kind") == "lettering":
        b = object_bounds(o)
        if b[0] - tol <= x <= b[2] + tol and b[1] - tol <= y <= b[3] + tol and any(point_in_rings(g, x, y) for g in shapes):
            return True
    if any(point_in_rings(g, x, y) for g in shapes):
        return True
    # thin shapes: near the outline counts
    for r in [r for g in shapes for r in g]:
        n = len(r)
        for i in range(n):
            ax, ay = r[i]
            bx, by = r[(i + 1) % n]
            vx, vy = bx - ax, by - ay
            l2 = vx * vx + vy * vy
            t = 0 if l2 < 1e-12 else max(0, min(1, ((x - ax) * vx + (y - ay) * vy) / l2))
            if math.hypot(ax + vx * t - x, ay + vy * t - y) < tol:
                return True
    return False


def move_object(o, dx, dy):
    if o.get("kind") == "stitches":
        tr = dict(o.get("transform") or {})
        tr["dx"] = tr.get("dx", 0.0) + dx
        tr["dy"] = tr.get("dy", 0.0) + dy
        o["transform"] = tr
        return
    if o.get("kind") == "lettering":
        o["x"] = o.get("x", 0.0) + dx
        o["y"] = o.get("y", 0.0) + dy
        o["glyphs"] = [[[[x + dx, y + dy] for x, y in r] for r in g] for g in o.get("glyphs", [])]
        return
    o["rings"] = [[[x + dx, y + dy] for x, y in r] for r in o.get("rings", [])]


def scale_object(o, k, cx, cy):
    if o.get("kind") == "stitches":
        tr = dict(o.get("transform") or {})
        tr["scale"] = tr.get("scale", 1.0) * k
        o["transform"] = tr
        return
    if o.get("kind") == "lettering":
        o["cap"] = o.get("cap", 10.0) * k
        o["radius"] = o.get("radius", 40.0) * k
        o["spacing"] = o.get("spacing", 0.0) * k
        o["x"] = cx + (o.get("x", 0.0) - cx) * k
        o["y"] = cy + (o.get("y", 0.0) - cy) * k
        regen_lettering(o)
        return
    o["rings"] = [[[cx + (x - cx) * k, cy + (y - cy) * k] for x, y in r] for r in o.get("rings", [])]


def regen_lettering(o):
    from .letters import lettering_shapes
    o["glyphs"] = lettering_shapes(o)


def thread_rgb(t):
    return tuple(t.get("rgb", (0, 0, 0)))


def render_layer(spec, settings, selected=()):
    """Pixels for a shape layer: every shape filled with its thread colour (cairo ARGB32,
    canvas size). Returns (data, stride, w, h)."""
    import cairo
    w, h = canvas_px(settings)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    ox, oy = origin(settings)
    cr.scale(PX_PER_MM, PX_PER_MM)
    cr.translate(-ox, -oy)
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    for o in spec.get("objects", []):
        if o.get("hidden"):
            continue
        if o.get("kind") == "stitches":
            draw_stitch_lines(cr, transformed_stitches(o)["blocks"], 0.35)
            continue
        r, g, b = thread_rgb(o.get("thread", {}))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        for rings in object_shapes(o):
            for ring in rings:
                if len(ring) < 3:
                    continue
                cr.move_to(*ring[0])
                for p in ring[1:]:
                    cr.line_to(*p)
                cr.close_path()
            cr.fill()
    surf.flush()
    return bytes(surf.get_data()), surf.get_stride(), w, h


def draw_stitch_lines(cr, blocks, width):
    cr.save()
    cr.set_line_cap(1)
    cr.set_line_join(1)
    cr.set_line_width(width)
    for b in blocks:
        r, g, bb = thread_rgb(b["thread"])
        cr.set_source_rgb(r / 255, g / 255, bb / 255)
        last = None
        for x, y, c in b["pts"]:
            if c == ST and last is not None:
                cr.move_to(*last)
                cr.line_to(x, y)
            last = (x, y)
        cr.stroke()
    cr.restore()


def store_layer(doc, i, spec, settings):
    """Write a shape layer's description and fresh pixels (one undo step)."""
    data, stride, w, h = render_layer(spec, settings)
    doc.text_layer_set(i, _spec_text(spec), (0, 0, w, h, data, stride))


def add_shape_layer(doc, name, spec, settings):
    spec = dict(spec)
    spec["kind"] = SHAPES_KIND
    data, stride, w, h = render_layer(spec, settings)
    return doc.text_layer_add(name, _spec_text(spec), 0, 0, w, h, data, stride)


def _spec_text(spec):
    """A layer description with its kind first, so a glance at the start tells what it is."""
    out = {"kind": spec.get("kind", SHAPES_KIND)}
    out.update({k: v for k, v in spec.items() if k != "kind"})
    return json.dumps(out, separators=(",", ":"))


# ---------------------------------------------------------------- thread view

def _blocks_from(plan):
    info = plan.info
    blocks = [{"thread": b["thread"], "pts": []} for b in info.get("blocks", [])]
    for x, y, c, bi in plan.cmds():
        if 0 <= bi < len(blocks):
            blocks[bi]["pts"].append((x, y, c))
    return blocks


def draw_threads(cr, plan, px_per_mm, upto=None, mode="real"):
    """Draw the stitches in mm coordinates (the caller sets up the transform). `px_per_mm` is
    the device scale, which picks the shading: at 3 px thread width or less the thread is drawn
    flat with a faint edge, wider it gets dark edge, mid tone and highlight. `upto` limits the
    drawing to the first n commands (the stitch-out simulator)."""
    blocks = _blocks_from(plan)
    tw = 0.4                       # thread width, mm
    wpx = tw * px_per_mm
    n = 0
    cr.save()
    cr.set_line_cap(1)
    cr.set_line_join(1)
    for b in blocks:
        r, g, bl = [v / 255 for v in thread_rgb(b["thread"])]
        segs = []
        jumps = []
        trims = []
        last = None
        for x, y, c in b["pts"]:
            if upto is not None and n >= upto:
                break
            n += 1
            if c == ST:
                if last is not None:
                    segs.append((last, (x, y)))
            elif c == JUMP and last is not None:
                jumps.append((last, (x, y)))
            elif c == TRIM:
                trims.append((x, y))
            last = (x, y)
        if mode == "lines":
            cr.set_line_width(max(0.08, 1.0 / px_per_mm))
            cr.set_source_rgb(r, g, bl)
            for a, q in segs:
                cr.move_to(*a)
                cr.line_to(*q)
            cr.stroke()
            # needle points
            rad = max(0.06, 1.2 / px_per_mm)
            for a, q in segs:
                cr.arc(q[0], q[1], rad, 0, 2 * math.pi)
                cr.new_sub_path()
            cr.fill()
            cr.save()
            cr.set_source_rgba(0.35, 0.35, 0.35, 0.9)
            cr.set_dash([1.2, 0.8])
            cr.set_line_width(max(0.05, 1.0 / px_per_mm))
            for a, q in jumps:
                cr.move_to(*a)
                cr.line_to(*q)
            cr.stroke()
            cr.restore()
            cr.save()
            cr.set_source_rgb(0.8, 0.1, 0.1)
            cr.set_line_width(max(0.06, 1.2 / px_per_mm))
            k = max(0.4, 4 / px_per_mm)
            for x, y in trims:
                cr.move_to(x - k, y - k)
                cr.line_to(x + k, y + k)
                cr.move_to(x - k, y + k)
                cr.line_to(x + k, y - k)
            cr.stroke()
            cr.restore()
        else:
            if wpx > 3.0:
                # dark edge, mid tone, highlight
                for width, k, alpha in ((tw, 0.55, 1.0), (tw * 0.7, 1.0, 1.0), (tw * 0.22, 1.35, 0.7)):
                    cr.set_line_width(width)
                    cr.set_source_rgba(min(1, r * k + (0.12 if k > 1 else 0)), min(1, g * k + (0.12 if k > 1 else 0)),
                                       min(1, bl * k + (0.12 if k > 1 else 0)), alpha)
                    for a, q in segs:
                        cr.move_to(*a)
                        cr.line_to(*q)
                    cr.stroke()
            else:
                cr.set_line_width(tw)
                cr.set_source_rgb(r * 0.85, g * 0.85, bl * 0.85)
                for a, q in segs:
                    cr.move_to(*a)
                    cr.line_to(*q)
                cr.stroke()
                cr.set_line_width(tw * 0.8)
                cr.set_source_rgb(r, g, bl)
                for a, q in segs:
                    cr.move_to(*a)
                    cr.line_to(*q)
                cr.stroke()
        if upto is not None and n >= upto:
            break
    cr.restore()
    return n


DENSITY_COLOURS = {0: None, 1: (0.30, 0.69, 0.31), 2: (0.30, 0.69, 0.31), 3: (1.0, 0.75, 0.0)}


def density_surface(plan, settings, s=10.0):
    """A cairo surface of the density map: 1–2 layers green, 3 amber, 4+ orange to red."""
    import cairo
    hw, hh = hoop_mm(settings)
    w, h = int(round(hw * s)), int(round(hh * s))
    ox, oy = origin(settings)
    d = plan.density(s, ox, oy, w, h)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    buf = surf.get_data()
    stride = surf.get_stride()
    cols = {}
    for v in range(256):
        if v == 0:
            cols[v] = b"\x00\x00\x00\x00"
            continue
        if v <= 2:
            rgb = (77, 176, 79)
        elif v == 3:
            rgb = (255, 191, 0)
        else:
            t = min(1.0, (v - 4) / 3.0)
            rgb = (255, int(140 * (1 - t)), 0)
        a = 200
        cols[v] = bytes((rgb[2] * a // 255, rgb[1] * a // 255, rgb[0] * a // 255, a))
    row = bytearray(stride)
    mv = memoryview(buf)
    for y in range(h):
        line = d[y * w:(y + 1) * w]
        out = b"".join(cols[v] for v in line)
        row[:len(out)] = out
        mv[y * stride:(y + 1) * stride] = bytes(row)
    surf.mark_dirty()
    return surf


def density_stats(plan, settings, s=10.0):
    hw, hh = hoop_mm(settings)
    w, h = int(round(hw * s)), int(round(hh * s))
    ox, oy = origin(settings)
    d = plan.density(s, ox, oy, w, h)
    covered = sum(1 for v in d if v)
    return {"covered": covered, "three": sum(1 for v in d if v == 3), "four": sum(1 for v in d if v >= 4)}


def safe_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return base[:16] or "Untitled"


# ---------------------------------------------------------------- command line

CLI_HELP = """usage: folio-draw --embroider PICTURE -o DESIGN.pes [--size 4x4] [--colours N] [--threads brother|exact] [--crop]

Turns a picture (PNG, JPEG, GIF, BMP, WebP, TIFF) into an embroidery design, or exports an
embroidery document (.ora) made in Folio Draw. The output format follows the extension:
.pes (Brother, Artspira), .dst (Tajima) or .pec.
  --size WxH    hoop in inches (4x4, 5x7, 6x10, 8x8, 8x12) or millimetres (100x100mm)
  --colours N   exactly N colours (default: automatic)
  --threads     brother (the 63-colour chart, default) or exact (the picture's colours)
  --crop        crop away the picture's background border first (default: the whole picture fits the hoop)
"""


def _hoop_from(size):
    size = size.lower().replace("×", "x").replace(" ", "")
    mm = size.endswith("mm")
    size = size[:-2] if mm else size.rstrip("in").rstrip('"')
    w, h = [float(v) for v in size.split("x")]
    if not mm:
        for name, hw, hh in HOOPS:
            if abs(hw - w * MM_PER_INCH) < 1 and abs(hh - h * MM_PER_INCH) < 1:
                return name, hw, hh
        return "Custom", w * MM_PER_INCH, h * MM_PER_INCH
    return "Custom", w, h


def cli(argv):
    import sys
    args = argv[argv.index("--embroider") + 1:]
    src = out = None
    size = "4x4"
    colours = 0
    chart_mode = "brother"
    crop = False
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a in ("-o", "--output"):
                out = args[i + 1]
                i += 2
            elif a == "--size":
                size = args[i + 1]
                i += 2
            elif a in ("--colours", "--colors"):
                colours = int(args[i + 1])
                i += 2
            elif a == "--threads":
                chart_mode = args[i + 1]
                i += 2
            elif a == "--crop":
                crop = True
                i += 1
            elif a in ("-h", "--help"):
                print(CLI_HELP)
                return 0
            elif src is None:
                src = a
                i += 1
            else:
                raise ValueError("unexpected argument %s" % a)
        if not src or not out:
            raise ValueError("a picture and -o DESIGN are needed")
        name, hw, hh = _hoop_from(size)
    except (ValueError, IndexError) as e:
        sys.stderr.write("folio-draw: %s\n\n%s" % (e, CLI_HELP))
        return 2
    from . import engine as E
    try:
        doc = E.Document.load(src)
    except E.EngineError as e:
        sys.stderr.write("folio-draw: can't open %s: %s\n" % (src, e))
        return 1
    s = doc_settings(doc)
    if s is None:
        s = dict(DEFAULT_SETTINGS)
        s.update({"hoop": name, "hoop_mm": [hw, hh], "threads": chart_mode})
        cw, ch = canvas_px(s)
        canvas, info = place(doc.flatten_rgba(), doc.width, doc.height, cw, ch, crop=crop)
        ox, oy = origin(s)
        params = {"colours": colours, "upscale": info.get("upscale", 1.0), "threads": chart_mode}
        if info.get("bg"):
            params["bg"] = info["bg"]
        res = convert(canvas, cw, ch, ox, oy, params)
        objs = []
        for k, sh in enumerate(res.get("shapes", [])):
            o = {"rings": sh["rings"], "thread": sh["thread"], "group": "picture"}
            o.update({k2: v for k2, v in STITCH_DEFAULTS.items() if v is not None})
            objs.append(o)
        hwm, hhm = hoop_mm(s)
        design = {"settings": {"hoop": [hwm, hhm], "trim": s["trim"], "ties": s["ties"], "min": s["min"], "max": s["max"]},
                  "layers": [{"objects": objs}]}
    else:
        design = design_json(doc, s)
    plan = Plan.make(design)
    low = out.lower()
    fmt = FMT_DST if low.endswith(".dst") else FMT_PEC if low.endswith(".pec") else FMT_PES
    try:
        plan.write(out, fmt, safe_name(out))
    except EngineError as e:
        sys.stderr.write("folio-draw: %s\n" % e)
        return 1
    inf = plan.info
    b = inf.get("bounds", [0, 0, 0, 0])
    print("%s: %d stitches, %d colours (%s), %.1f x %.1f mm" % (out, inf.get("stitches", 0), len(inf.get("blocks", [])),
          ", ".join(thread_label(x["thread"]) for x in inf.get("blocks", [])), b[2] - b[0], b[3] - b[1]))
    return 0
