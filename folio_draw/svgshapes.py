"""Shapes straight from an SVG drawing (D3-03): its paths, rectangles, circles, ellipses,
polygons and lines become embroidery shapes in their fill colours, without tracing a picture.

Filled outlines become shapes (holes from even-odd subpaths); an outline that is only stroked
becomes a running stitch; an open line becomes a satin column as wide as its stroke.

    shapes_from_svg(path, hoop_w, hoop_h, margin) -> [{"rings", "rgb", "kind"}]   (mm, hoop centre 0,0)
"""
import math
import re
import xml.etree.ElementTree as ET

TOL = 0.08          # flattening tolerance in mm
NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "lime": (0, 255, 0),
         "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255),
         "aqua": (0, 255, 255), "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "gray": (128, 128, 128),
         "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0), "olive": (128, 128, 0),
         "purple": (128, 0, 128), "teal": (0, 128, 128), "navy": (0, 0, 128), "orange": (255, 165, 0),
         "brown": (165, 42, 42), "pink": (255, 192, 203), "gold": (255, 215, 0), "darkgreen": (0, 100, 0),
         "darkblue": (0, 0, 139), "darkred": (139, 0, 0), "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
         "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169), "beige": (245, 245, 220), "tan": (210, 180, 140),
         "violet": (238, 130, 238), "indigo": (75, 0, 130), "crimson": (220, 20, 60), "coral": (255, 127, 80),
         "salmon": (250, 128, 114), "khaki": (240, 230, 140), "skyblue": (135, 206, 235), "royalblue": (65, 105, 225)}

UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}


def _tag(e):
    return e.tag.split("}")[-1]


def _len(v, default=0.0):
    if v is None:
        return default
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", v)
    if not m:
        return default
    return float(m.group(1))


def _len_mm(v):
    """A length with its unit, in mm (None when the drawing gives no physical size)."""
    if not v:
        return None
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", v)
    if not m or m.group(2) == "%":
        return None
    u = m.group(2)
    if u not in ("mm", "cm", "in", "pt", "pc"):
        return None
    return float(m.group(1)) * UNITS[u]


def parse_colour(v):
    if v is None:
        return None
    v = v.strip().lower()
    if v in ("none", "transparent", ""):
        return None
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        return None
    m = re.match(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        out = []
        for p in parts[:3]:
            out.append(int(round(float(p[:-1]) * 2.55)) if p.endswith("%") else int(float(p)))
        return tuple(max(0, min(255, c)) for c in out) if len(out) == 3 else None
    return NAMED.get(v)


# ---------------------------------------------------------------- transforms (a, b, c, d, e, f)

def mul(m2, m1):
    a2, b2, c2, d2, e2, f2 = m2
    a1, b1, c1, d1, e1, f1 = m1
    return (a2 * a1 + c2 * b1, b2 * a1 + d2 * b1, a2 * c1 + c2 * d1, b2 * c1 + d2 * d1,
            a2 * e1 + c2 * f1 + e2, b2 * e1 + d2 * f1 + f2)


def parse_transform(t):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not t:
        return m
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", t):
        a = [float(x) for x in NUM.findall(args)]
        if name == "matrix" and len(a) == 6:
            n = tuple(a)
        elif name == "translate":
            n = (1, 0, 0, 1, a[0] if a else 0, a[1] if len(a) > 1 else 0)
        elif name == "scale":
            sx = a[0] if a else 1
            n = (sx, 0, 0, a[1] if len(a) > 1 else sx, 0, 0)
        elif name == "rotate":
            r = math.radians(a[0] if a else 0)
            co, si = math.cos(r), math.sin(r)
            n = (co, si, -si, co, 0, 0)
            if len(a) == 3:
                n = mul((1, 0, 0, 1, a[1], a[2]), mul(n, (1, 0, 0, 1, -a[1], -a[2])))
        elif name == "skewX":
            n = (1, 0, math.tan(math.radians(a[0] if a else 0)), 1, 0, 0)
        elif name == "skewY":
            n = (1, math.tan(math.radians(a[0] if a else 0)), 0, 1, 0, 0)
        else:
            continue
        m = mul(m, n)
    return m


def apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


# ---------------------------------------------------------------- path data

def _bez(p0, p1, p2, p3, out, scale):
    d = (math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)) * scale
    n = max(2, min(200, int(math.sqrt(d / TOL) * 1.5)))
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))


def _arc(p0, rx, ry, phi, large, sweep, p1, out, scale):
    """SVG elliptical arc to polyline points (endpoint parameterisation, F.6.5)."""
    if rx == 0 or ry == 0:
        out.append(p1)
        return
    rx, ry = abs(rx), abs(ry)
    ph = math.radians(phi)
    co, si = math.cos(ph), math.sin(ph)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = co * dx + si * dy, -si * dx + co * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0, num / den)) if den else 0
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = co * cx1 - si * cy1 + (p0[0] + p1[0]) / 2
    cy = si * cx1 + co * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, min(360, int(abs(dt) * math.sqrt(max(rx, ry) * scale / TOL))))
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((co * x - si * y + cx, si * x + co * y + cy))


def path_subpaths(d, scale=1.0):
    """[(points, closed)] in the drawing's own units."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d or "")
    subs = []
    cur = None
    pos = (0.0, 0.0)
    start = (0.0, 0.0)
    last_c = None
    last_q = None
    cmd = None
    i = 0

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    def isnum():
        return i < len(toks) and not toks[i].isalpha()
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
        elif cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if c == "M":
            if not isnum():
                continue
            pos = (ox + num(), oy + num())
            start = pos
            cur = [pos]
            subs.append([cur, False])
            cmd = "l" if rel else "L"
            last_c = last_q = None
            continue
        if cur is None:
            cur = [pos]
            subs.append([cur, False])
        if c == "Z":
            subs[-1][1] = True
            pos = start
            cur = None
            last_c = last_q = None
            cmd = None          # numbers after Z without a command are an error: stop there
            continue
        if not isnum():
            continue
        if c == "L":
            pos = (ox + num(), oy + num())
            cur.append(pos)
            last_c = last_q = None
        elif c == "H":
            pos = ((pos[0] if rel else 0) + num(), pos[1])
            cur.append(pos)
            last_c = last_q = None
        elif c == "V":
            pos = (pos[0], (pos[1] if rel else 0) + num())
            cur.append(pos)
            last_c = last_q = None
        elif c == "C":
            p1 = (ox + num(), oy + num())
            p2 = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            _bez(pos, p1, p2, p3, cur, scale)
            pos, last_c, last_q = p3, p2, None
        elif c == "S":
            p1 = (2 * pos[0] - last_c[0], 2 * pos[1] - last_c[1]) if last_c else pos
            p2 = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            _bez(pos, p1, p2, p3, cur, scale)
            pos, last_c, last_q = p3, p2, None
        elif c == "Q":
            q = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            _bez(pos, (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1])),
                 (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1])), p3, cur, scale)
            pos, last_q, last_c = p3, q, None
        elif c == "T":
            q = (2 * pos[0] - last_q[0], 2 * pos[1] - last_q[1]) if last_q else pos
            p3 = (ox + num(), oy + num())
            _bez(pos, (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1])),
                 (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1])), p3, cur, scale)
            pos, last_q, last_c = p3, q, None
        elif c == "A":
            rx, ry, phi = num(), num(), num()
            large, sweep = num() != 0, num() != 0
            p3 = (ox + num(), oy + num())
            _arc(pos, rx, ry, phi, large, sweep, p3, cur, scale)
            pos = p3
            last_c = last_q = None
        else:
            i += 1
    return [(pts, closed) for pts, closed in subs if len(pts) >= 2]


def _ellipse(cx, cy, rx, ry, scale):
    n = max(16, min(360, int(2 * math.pi * math.sqrt(max(rx, ry) * scale / TOL))))
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def element_subpaths(e, scale):
    t = _tag(e)
    g = lambda k, d=0.0: _len(e.get(k), d)  # noqa: E731
    if t == "path":
        return path_subpaths(e.get("d"), scale)
    if t == "rect":
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        if w <= 0 or h <= 0:
            return []
        rx, ry = e.get("rx"), e.get("ry")
        rx = _len(rx if rx is not None else ry, 0)
        ry = _len(ry if ry is not None else e.get("rx"), 0)
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0 or ry <= 0:
            return [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
        d = ("M%g,%g H%g A%g,%g 0 0 1 %g,%g V%g A%g,%g 0 0 1 %g,%g H%g A%g,%g 0 0 1 %g,%g V%g A%g,%g 0 0 1 %g,%g Z"
             % (x + rx, y, x + w - rx, rx, ry, x + w, y + ry, y + h - ry, rx, ry, x + w - rx, y + h, x + rx,
                rx, ry, x, y + h - ry, y + ry, rx, ry, x + rx, y))
        return path_subpaths(d, scale)
    if t == "circle":
        r = g("r")
        return [(_ellipse(g("cx"), g("cy"), r, r, scale), True)] if r > 0 else []
    if t == "ellipse":
        rx, ry = g("rx"), g("ry")
        return [(_ellipse(g("cx"), g("cy"), rx, ry, scale), True)] if rx > 0 and ry > 0 else []
    if t in ("polygon", "polyline"):
        v = [float(x) for x in NUM.findall(e.get("points", ""))]
        pts = list(zip(v[0::2], v[1::2]))
        return [(pts, t == "polygon")] if len(pts) >= 2 else []
    if t == "line":
        return [([(g("x1"), g("y1")), (g("x2"), g("y2"))], False)]
    return []


def _style(e, inherited):
    st = dict(inherited)
    for k in ("fill", "stroke", "stroke-width", "fill-rule", "display", "visibility", "opacity", "fill-opacity"):
        if e.get(k) is not None:
            st[k] = e.get(k)
    for part in (e.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            st[k.strip()] = v.strip()
    return st


def _area(r):
    return 0.5 * sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))


def _band(pts, w):
    """A polygon w wide round an open polyline (mitred, clamped)."""
    if len(pts) < 2:
        return None
    h = w / 2
    left, right = [], []
    n = len(pts)
    for i in range(n):
        p = pts[i]
        if i == 0:
            d = (pts[1][0] - p[0], pts[1][1] - p[1])
        elif i == n - 1:
            d = (p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])
        else:
            a = (p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])
            b = (pts[i + 1][0] - p[0], pts[i + 1][1] - p[1])
            la, lb = math.hypot(*a) or 1, math.hypot(*b) or 1
            d = (a[0] / la + b[0] / lb, a[1] / la + b[1] / lb)
        ld = math.hypot(*d)
        if ld < 1e-9:
            continue
        nx, ny = -d[1] / ld, d[0] / ld
        k = 1.0
        if 0 < i < n - 1:
            a = (p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])
            la = math.hypot(*a) or 1
            cosh = abs(nx * (-a[1] / la) + ny * (a[0] / la))
            k = min(3.0, 1 / max(cosh, 0.34))
        left.append((p[0] + nx * h * k, p[1] + ny * h * k))
        right.append((p[0] - nx * h * k, p[1] - ny * h * k))
    ring = left + right[::-1]
    return ring if len(ring) >= 4 else None


def collect(svg_path):
    """(items, (x0, y0, x1, y1) in user units, mm per user unit or None) of everything drawn."""
    root = ET.parse(svg_path).getroot()
    vb = [float(x) for x in NUM.findall(root.get("viewBox", ""))]
    w_mm, h_mm = _len_mm(root.get("width")), _len_mm(root.get("height"))
    unit_mm = None
    base = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        base = (1.0, 0.0, 0.0, 1.0, -vb[0], -vb[1])
        if w_mm:
            unit_mm = w_mm / vb[2]
        elif h_mm:
            unit_mm = h_mm / vb[3]
    elif w_mm:
        unit_mm = w_mm / max(1e-9, _len(root.get("width")))
    items = []
    scale = unit_mm or 0.264

    def walk(e, m, st):
        t = _tag(e)
        if t in ("defs", "clipPath", "mask", "symbol", "marker", "pattern", "linearGradient", "radialGradient",
                 "style", "title", "desc", "metadata", "text"):
            return
        st = _style(e, st)
        if st.get("display") == "none" or st.get("visibility") == "hidden":
            return
        m = mul(m, parse_transform(e.get("transform")))
        if t in ("svg", "g", "a", "switch"):
            for c in e:
                walk(c, m, st)
            return
        subs = element_subpaths(e, scale * math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or scale)
        if not subs:
            return
        subs = [([apply(m, p) for p in pts], closed) for pts, closed in subs]
        fill = st.get("fill", "black")
        fill_rgb = None
        if fill.startswith("url("):
            fill_rgb = _gradient_colour(root, fill)
        else:
            fill_rgb = parse_colour(fill)
        stroke_rgb = parse_colour(st.get("stroke"))
        sw = _len(st.get("stroke-width"), 1.0) * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
        items.append({"subs": subs, "fill": fill_rgb, "stroke": stroke_rgb, "sw": sw})
    walk(root, base, {})
    xs = [p[0] for it in items for pts, _c in it["subs"] for p in pts]
    ys = [p[1] for it in items for pts, _c in it["subs"] for p in pts]
    if not xs:
        return [], None, unit_mm
    return items, (min(xs), min(ys), max(xs), max(ys)), unit_mm


def _gradient_colour(root, ref):
    m = re.match(r"url\(#([^)]+)\)", ref)
    if not m:
        return None
    gid = m.group(1)
    for e in root.iter():
        if e.get("id") == gid:
            href = e.get("{http://www.w3.org/1999/xlink}href") or e.get("href")
            stops = [s for s in e if _tag(s) == "stop"]
            if not stops and href:
                return _gradient_colour(root, "url(%s)" % href)
            for s in stops:
                c = parse_colour(_style(s, {}).get("stop-color"))
                if c:
                    return c
    return None


def shapes_from_svg(path, hoop_w, hoop_h, margin=2.5):
    """Shapes in mm about the hoop's centre: the drawing at its real size when it has one and
    fits, else fitted to the hoop. Each: {"rings", "rgb", "kind": "fill"|"run"|"satin"}."""
    items, box, unit_mm = collect(path)
    if not items:
        return []
    bw, bh = box[2] - box[0], box[3] - box[1]
    room_w, room_h = hoop_w - 2 * margin, hoop_h - 2 * margin
    k = unit_mm
    if k is None or bw * k > room_w or bh * k > room_h:
        k = min(room_w / max(bw, 1e-9), room_h / max(bh, 1e-9))
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    to = lambda p: ((p[0] - cx) * k, (p[1] - cy) * k)  # noqa: E731
    out = []
    for it in items:
        closed_rings = [[to(p) for p in pts] for pts, closed in it["subs"] if len(pts) >= 3 and (closed or it["fill"])]
        closed_rings = [_clean(r) for r in closed_rings]
        closed_rings = [r for r in closed_rings if r and abs(_area(r)) > 0.05]
        if it["fill"] and closed_rings:
            # the biggest outline first, the rest even-odd inside it; separate pieces become
            # separate shapes
            for group in _pieces(closed_rings):
                out.append({"rings": [[list(p) for p in r] for r in group], "rgb": list(it["fill"]), "kind": "fill"})
        if it["stroke"]:
            w = it["sw"] * k
            for pts, closed in it["subs"]:
                mp = _clean([to(p) for p in pts])
                if len(mp) < 2:
                    continue
                if closed and it["fill"]:
                    continue        # an outline round a filled shape: the fill covers it
                if closed:
                    if w >= 1.2:
                        ring = _band(mp + mp[:1], w)
                        if ring:
                            out.append({"rings": [[list(p) for p in ring]], "rgb": list(it["stroke"]), "kind": "satin"})
                    elif len(mp) >= 3:
                        out.append({"rings": [[list(p) for p in mp]], "rgb": list(it["stroke"]), "kind": "run"})
                else:
                    ring = _band(mp, max(w, 0.8))
                    if ring:
                        out.append({"rings": [[list(p) for p in ring]], "rgb": list(it["stroke"]),
                                    "kind": "satin" if w >= 0.8 else "run"})
    return out


def _clean(r):
    out = []
    for p in r:
        if not out or math.dist(out[-1], p) > 0.02:
            out.append(p)
    if len(out) > 2 and math.dist(out[0], out[-1]) < 0.02:
        out.pop()
    return out


def _inside(p, ring):
    c = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi + 1e-12) + xi:
            c = not c
        j = i
    return c


def _pieces(rings):
    """Group rings into shapes: each outline with the rings that lie inside it an odd number of deep."""
    order = sorted(range(len(rings)), key=lambda i: -abs(_area(rings[i])))
    depth = {}
    parent = {}
    for idx, i in enumerate(order):
        p = rings[i][0]
        holders = [j for j in order[:idx] if _inside(p, rings[j])]
        depth[i] = len(holders)
        # the smallest container is the parent
        parent[i] = holders[-1] if holders else None
    groups = {}
    for i in order:
        if depth[i] % 2 == 0:
            groups[i] = [rings[i]]
    for i in order:
        if depth[i] % 2 == 1 and parent[i] in groups:
            groups[parent[i]].append(rings[i])
    return [groups[i] for i in order if i in groups]
