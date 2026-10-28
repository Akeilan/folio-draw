"""Lettering for embroidery: glyph outlines straight from the installed fonts (vector, not traced
pixels), set straight or on an arc, in millimetres."""

import math

import cairo

K = 20.0   # outlines are made at 20 units per mm, then scaled down: fine curves, flat tolerance 0.005 mm


def _face(cr, font):
    bold = font.endswith(" Bold")
    fam = font[:-5] if bold else font
    cr.select_font_face(fam or "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)


def _ctx():
    surf = cairo.ImageSurface(cairo.FORMAT_A8, 4, 4)
    return cairo.Context(surf)


def font_size_for_cap(font, cap_mm):
    """The font size (in units of K per mm) whose capital H is cap_mm tall."""
    cr = _ctx()
    _face(cr, font)
    cr.set_font_size(100)
    cr.text_path("H")
    x0, y0, x1, y1 = cr.fill_extents()
    h = max(1e-3, y1 - y0)
    return 100.0 * cap_mm * K / h


def _subpaths(cr):
    rings = []
    cur = []
    for kind, pts in cr.copy_path_flat():
        if kind == cairo.PATH_MOVE_TO:
            if len(cur) >= 3:
                rings.append(cur)
            cur = [pts]
        elif kind == cairo.PATH_LINE_TO:
            cur.append(pts)
        elif kind == cairo.PATH_CLOSE_PATH:
            if len(cur) >= 3:
                rings.append(cur)
            cur = []
    if len(cur) >= 3:
        rings.append(cur)
    return rings


def _area(r):
    a = 0.0
    n = len(r)
    for i in range(n):
        x0, y0 = r[i]
        x1, y1 = r[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2


def _inside(r, x, y):
    c = False
    n = len(r)
    j = n - 1
    for i in range(n):
        xi, yi = r[i]
        xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            c = not c
        j = i
    return c


def group_rings(rings):
    """Outline rings and their holes → [[outline, hole, ...], ...] by containment depth."""
    rings = [r for r in rings if abs(_area(r)) > 1e-6]
    depth = []
    for i, r in enumerate(rings):
        px, py = r[0]
        d = sum(1 for j, o in enumerate(rings) if j != i and abs(_area(o)) > abs(_area(r)) and _inside(o, px, py))
        depth.append(d)
    shapes = []
    for i, r in enumerate(rings):
        if depth[i] % 2:
            continue
        holes = []
        for j, h in enumerate(rings):
            if depth[j] == depth[i] + 1 and _inside(r, h[0][0], h[0][1]):
                holes.append(h)
        shapes.append([r] + holes)
    return shapes


def _glyph_rings(cr, ch, x, y, angle, origin_dx):
    """Rings of one glyph placed with its baseline origin at (x, y) mm, rotated by angle (rad);
    origin_dx shifts the glyph along its baseline first (mm)."""
    cr.new_path()
    cr.save()
    cr.identity_matrix()
    cr.text_path(ch)
    cr.restore()
    out = []
    ca, sa = math.cos(angle), math.sin(angle)
    for r in _subpaths(cr):
        ring = []
        for px, py in r:
            gx, gy = px / K + origin_dx, py / K
            ring.append([round(x + gx * ca - gy * sa, 4), round(y + gx * sa + gy * ca, 4)])
        out.append(ring)
    cr.new_path()
    return out


def lettering_shapes(obj):
    """Shapes (each [outline, holes...]) for a lettering object: text, font, cap (mm), spacing
    (mm), arc ('none' | 'top' | 'bottom'), radius (mm), x, y (centre, mm)."""
    text = obj.get("text", "")
    font = obj.get("font", "Sans Bold")
    cap = float(obj.get("cap", 10.0))
    spacing = float(obj.get("spacing", 0.0))
    cx, cy = float(obj.get("x", 0.0)), float(obj.get("y", 0.0))
    arc = obj.get("arc", "none")
    R = max(1.0, float(obj.get("radius", 40.0)))
    cr = _ctx()
    _face(cr, font)
    cr.set_font_size(font_size_for_cap(font, cap))
    adv = []
    for ch in text:
        xa = cr.text_extents(ch).x_advance / K
        adv.append(xa)
    total = sum(adv) + spacing * max(0, len(text) - 1)
    shapes = []
    pos = 0.0
    for i, ch in enumerate(text):
        a = adv[i]
        mid = pos + a / 2.0
        if ch.strip():
            if arc == "top":
                th = (mid - total / 2.0) / R
                bx, by = cx + R * math.sin(th), cy - R * math.cos(th)
                rings = _glyph_rings(cr, ch, bx, by, th, -a / 2.0)
            elif arc == "bottom":
                th = (mid - total / 2.0) / R
                # the cap line sits on the circle: the baseline is cap height further out
                rb = R + cap
                bx, by = cx + rb * math.sin(th), cy + rb * math.cos(th)
                rings = _glyph_rings(cr, ch, bx, by, -th, -a / 2.0)
            else:
                bx, by = cx - total / 2.0 + mid, cy + cap / 2.0
                rings = _glyph_rings(cr, ch, bx, by, 0.0, -a / 2.0)
            shapes.extend(group_rings(rings))
        pos += a + spacing
    return shapes


def default_type(cap):
    """Under 8 mm cap height fill beats satin for lettering built from outlines."""
    return "fill" if cap < 8.0 else "satin"


def fit_circle(pts):
    """Least-squares circle through points: (cx, cy, r, rms) or None."""
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = svv = suv = suuu = svvv = suvv = svuu = 0.0
    for x, y in pts:
        u, v = x - mx, y - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    a = 0.5 * (suuu + suvv)
    b = 0.5 * (svvv + svuu)
    uc = (a * svv - b * suv) / det
    vc = (b * suu - a * suv) / det
    cx, cy = uc + mx, vc + my
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    rms = math.sqrt(sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in pts) / n)
    return cx, cy, r, rms
