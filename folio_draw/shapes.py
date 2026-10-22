"""Shape library. Each shape maps a bounding box to a flattened path (points, closed)."""

import math

# (id, tooltip)
SHAPES = [
    ("line", "Line"),
    ("curve", "Curve"),
    ("oval", "Oval"),
    ("rect", "Rectangle"),
    ("roundrect", "Rounded rectangle"),
    ("polygon", "Polygon"),
    ("triangle", "Triangle"),
    ("righttriangle", "Right triangle"),
    ("diamond", "Diamond"),
    ("pentagon", "Pentagon"),
    ("hexagon", "Hexagon"),
    ("arrow_right", "Right arrow"),
    ("arrow_left", "Left arrow"),
    ("arrow_up", "Up arrow"),
    ("arrow_down", "Down arrow"),
    ("star4", "Four-point star"),
    ("star5", "Five-point star"),
    ("star6", "Six-point star"),
    ("callout_rect", "Rounded rectangular callout"),
    ("callout_oval", "Oval callout"),
    ("callout_cloud", "Cloud callout"),
    ("heart", "Heart"),
    ("lightning", "Lightning"),
]


def _norm(pts, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    return [(x0 + u * w, y0 + v * h) for u, v in pts]


def _ellipse(cx, cy, rx, ry, a0=0.0, a1=math.tau, n=None):
    if n is None:
        n = int(max(24, min(720, (abs(rx) + abs(ry)) * 1.2)))
    return [(cx + rx * math.cos(a0 + (a1 - a0) * i / n), cy + ry * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def cubic(p0, p1, p2, p3, n=None):
    if n is None:
        d = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
        n = int(max(8, min(400, d / 2)))
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        out.append((
            mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1],
        ))
    return out


def _star(n, inner):
    pts = []
    for i in range(n * 2):
        r = 0.5 if i % 2 == 0 else 0.5 * inner
        a = -math.pi / 2 + i * math.pi / n
        pts.append((0.5 + r * math.cos(a), 0.5 + r * math.sin(a)))
    return pts


def _regular(n):
    return [(0.5 + 0.5 * math.cos(-math.pi / 2 + i * math.tau / n), 0.5 + 0.5 * math.sin(-math.pi / 2 + i * math.tau / n)) for i in range(n)]


def _roundrect(x0, y0, x1, y1, r):
    r = max(0.0, min(r, abs(x1 - x0) / 2, abs(y1 - y0) / 2))
    if r < 0.5:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    pts = []
    for cx, cy, a in ((x1 - r, y0 + r, -math.pi / 2), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, math.pi / 2), (x0 + r, y0 + r, math.pi)):
        pts += _ellipse(cx, cy, r, r, a, a + math.pi / 2, 12)
    return pts


def shape_path(kind, x0, y0, x1, y1):
    """Return (points, closed) for a bbox-driven shape. Box corners may be in any order
    (dragging up/left flips the shape like a mirror, as expected)."""
    w, h = x1 - x0, y1 - y0
    if kind == "line":
        return [(x0, y0), (x1, y1)], False
    if kind == "rect":
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True
    if kind == "roundrect":
        lx, hx = min(x0, x1), max(x0, x1)
        ly, hy = min(y0, y1), max(y0, y1)
        return _roundrect(lx, ly, hx, hy, min(hx - lx, hy - ly) * 0.18), True
    if kind == "oval":
        return _ellipse((x0 + x1) / 2, (y0 + y1) / 2, abs(w) / 2, abs(h) / 2)[:-1], True
    if kind == "triangle":
        return _norm([(0.5, 0), (1, 1), (0, 1)], x0, y0, x1, y1), True
    if kind == "righttriangle":
        return _norm([(0, 0), (1, 1), (0, 1)], x0, y0, x1, y1), True
    if kind == "diamond":
        return _norm([(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)], x0, y0, x1, y1), True
    if kind == "pentagon":
        return _norm(_regular(5), x0, y0, x1, y1), True
    if kind == "hexagon":
        return _norm([(0.25, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0.25, 1), (0, 0.5)], x0, y0, x1, y1), True
    if kind == "arrow_right":
        return _norm([(0, 0.25), (0.6, 0.25), (0.6, 0), (1, 0.5), (0.6, 1), (0.6, 0.75), (0, 0.75)], x0, y0, x1, y1), True
    if kind == "arrow_left":
        return _norm([(1, 0.25), (0.4, 0.25), (0.4, 0), (0, 0.5), (0.4, 1), (0.4, 0.75), (1, 0.75)], x0, y0, x1, y1), True
    if kind == "arrow_up":
        return _norm([(0.25, 1), (0.25, 0.4), (0, 0.4), (0.5, 0), (1, 0.4), (0.75, 0.4), (0.75, 1)], x0, y0, x1, y1), True
    if kind == "arrow_down":
        return _norm([(0.25, 0), (0.25, 0.6), (0, 0.6), (0.5, 1), (1, 0.6), (0.75, 0.6), (0.75, 0)], x0, y0, x1, y1), True
    if kind == "star4":
        return _norm(_star(4, 0.38), x0, y0, x1, y1), True
    if kind == "star5":
        return _norm(_star(5, 0.45), x0, y0, x1, y1), True
    if kind == "star6":
        return _norm(_star(6, 0.58), x0, y0, x1, y1), True
    if kind == "heart":
        u = [(0.5, 0.25)]
        u += cubic((0.5, 0.25), (0.5, -0.05), (0.0, -0.05), (0.0, 0.3))[1:]
        u += cubic((0.0, 0.3), (0.0, 0.6), (0.35, 0.75), (0.5, 1.0))[1:]
        u += cubic((0.5, 1.0), (0.65, 0.75), (1.0, 0.6), (1.0, 0.3))[1:]
        u += cubic((1.0, 0.3), (1.0, -0.05), (0.5, -0.05), (0.5, 0.25))[1:-1]
        return _norm(u, x0, y0, x1, y1), True
    if kind == "lightning":
        return _norm([(0.38, 0), (0.7, 0.32), (0.55, 0.38), (0.88, 0.66), (0.72, 0.72), (1, 1),
                      (0.45, 0.78), (0.6, 0.72), (0.2, 0.5), (0.36, 0.44), (0, 0.18)], x0, y0, x1, y1), True
    if kind == "callout_rect":
        body = _roundrect(0, 0, 1, 0.72, 0.1)
        # insert a tail on the bottom edge (between the bottom-right and bottom-left corners)
        idx = next(i for i, p in enumerate(body) if p[1] >= 0.72 - 1e-6 and p[0] < 0.5)
        tail = [(0.42, 0.72), (0.2, 1.0), (0.28, 0.72)]
        pts = body[:idx] + tail + body[idx:]
        return _norm(pts, x0, y0, x1, y1), True
    if kind == "callout_oval":
        e = _ellipse(0.5, 0.38, 0.5, 0.38, math.radians(100), math.radians(100) + math.tau - math.radians(18), 96)
        pts = e + [(0.2, 1.0)]
        return _norm(pts, x0, y0, x1, y1), True
    if kind == "callout_cloud":
        bumps = 9
        pts = []
        for i in range(bumps):
            a0 = i * math.tau / bumps
            a1 = (i + 1) * math.tau / bumps
            cx = 0.5 + 0.4 * math.cos((a0 + a1) / 2)
            cy = 0.36 + 0.28 * math.sin((a0 + a1) / 2)
            r = 0.13
            ang = math.atan2((cy - 0.36) / 0.28, (cx - 0.5) / 0.4)
            pts += _ellipse(cx, cy, r, r * 0.9, ang - 1.6, ang + 1.6, 14)
        main = _norm(pts, x0, y0, x1, y1)
        return main, True
    if kind == "cloud_tail":
        return [], True
    # polygon / curve are interactive and not bbox-driven
    return [(x0, y0), (x1, y1)], False


def cloud_tail_bubbles(x0, y0, x1, y1):
    """Small thought bubbles under a cloud callout, as separate closed paths."""
    out = []
    for cx, cy, r in ((0.3, 0.8, 0.06), (0.2, 0.92, 0.035)):
        out.append(_norm(_ellipse(cx, cy, r, r * 1.1)[:-1], x0, y0, x1, y1))
    return out
