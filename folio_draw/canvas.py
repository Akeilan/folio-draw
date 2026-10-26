"""The drawing surface: viewport, rulers, overlays and every tool's mouse handling."""

import json
import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .tools import SEL_TOOLS
from .stabilizer import Stabilizer
from . import engine as E
from . import shapes as S
from .icons import paint_icon

MARGIN = 6
HANDLE = 7
RULER = 18
ZOOM_STEPS = [0.125, 0.25, 0.5, 0.75, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32]
BBOX_SHAPES = {k for k, _ in S.SHAPES} - {"line", "curve", "polygon"}

BRUSH_TOOLS = {
    "brush": (E.TOOL_BRUSH, 1.0),
    "soft": (E.TOOL_BRUSH, 0.0),
    "callig": (E.TOOL_CALLIG, 1.0),
    "callig2": (E.TOOL_CALLIG2, 1.0),
    "airbrush": (E.TOOL_AIRBRUSH, 1.0),
    "marker": (E.TOOL_MARKER, 1.0),
}

HANDLE_CURSORS = {"nw": "nw-resize", "n": "n-resize", "ne": "ne-resize", "e": "e-resize",
                  "se": "se-resize", "s": "s-resize", "sw": "sw-resize", "w": "w-resize"}


def _norm_box(x0, y0, x1, y1):
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


class Pending:
    """A shape that is still editable (handles) until the next click outside it."""

    def __init__(self, kind, button, pts):
        self.kind = kind
        self.button = button
        self.pts = pts
        self.stage = 0          # curve: 0 line, 1 first bend, 2 second bend, 3 done; polygon: 0 drawing, 3 closed
        self.closed = kind not in ("line", "curve", "polygon")

    def paths(self):
        k = self.kind
        if k == "line":
            return [(self.pts, False)]
        if k == "curve":
            p0, p1, p2, p3 = self.pts
            return [(S.cubic(p0, p1, p2, p3), False)]
        if k == "polygon":
            return [(self.pts, self.stage == 3)]
        (x0, y0), (x1, y1) = self.pts
        out = [S.shape_path(k, x0, y0, x1, y1)]
        if k == "callout_cloud":
            out += [(b, True) for b in S.cloud_tail_bubbles(x0, y0, x1, y1)]
        return out

    def bbox(self):
        if self.kind in BBOX_SHAPES:
            (x0, y0), (x1, y1) = self.pts
            return _norm_box(x0, y0, x1, y1)
        pts = [p for path, _ in self.paths() for p in path] or self.pts
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def editable(self):
        if self.kind == "curve":
            return self.stage >= 3
        if self.kind == "polygon":
            return self.stage == 3
        return True


class Canvas(Gtk.Grid):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.st = win.state
        self.z = 1.0
        self.surf = None
        self.surf_key = None
        self.interacting = False
        self.drag = None             # current mouse interaction dict
        self.pending = None
        self.text = None             # text box dict while editing
        self.sel_path = None         # outline of the current selection for display
        self.polysel = None          # polygon selection being placed: points, the pointer, mode
        self._outline = None         # cached edge segments of the selection mask
        self.ants = 0
        self.mouse = None            # last doc position under the pointer
        self.marquee = None
        self.canvas_preview = None
        self._cursor_name = None
        self._cursors = {}

        self.hadj = Gtk.Adjustment(value=0, lower=0, upper=1, step_increment=20, page_increment=200, page_size=1)
        self.vadj = Gtk.Adjustment(value=0, lower=0, upper=1, step_increment=20, page_increment=200, page_size=1)
        self.hadj.connect("value-changed", self._scrolled)
        self.vadj.connect("value-changed", self._scrolled)

        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
                             Gdk.EventMask.KEY_PRESS_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("size-allocate", lambda *_: self.update_adjustments())
        self.area.connect("button-press-event", self._press)
        self.area.connect("button-release-event", self._release)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("scroll-event", self._scroll)
        self.area.connect("leave-notify-event", self._leave)
        self.area.get_style_context().add_class("fd-workspace")

        # overlay hosts the text editor
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.area)
        self.fixed = Gtk.Fixed()
        self.fixed.set_halign(Gtk.Align.FILL)
        self.fixed.set_valign(Gtk.Align.FILL)
        self.overlay.add_overlay(self.fixed)
        self.overlay.set_overlay_pass_through(self.fixed, True)

        self.hruler = Gtk.DrawingArea()
        self.hruler.set_size_request(-1, RULER)
        self.hruler.connect("draw", self._draw_ruler, True)
        self.vruler = Gtk.DrawingArea()
        self.vruler.set_size_request(RULER, -1)
        self.vruler.connect("draw", self._draw_ruler, False)
        corner = Gtk.DrawingArea()
        corner.set_size_request(RULER, RULER)
        corner.connect("draw", lambda w, cr: (cr.set_source_rgb(0.965, 0.965, 0.965), cr.paint()))
        self.corner = corner
        self.hscroll = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.hadj)
        self.vscroll = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.vadj)
        self.attach(corner, 0, 0, 1, 1)
        self.attach(self.hruler, 1, 0, 1, 1)
        self.attach(self.vruler, 0, 1, 1, 1)
        self.attach(self.overlay, 1, 1, 1, 1)
        self.attach(self.vscroll, 2, 1, 1, 1)
        self.attach(self.hscroll, 1, 2, 1, 1)

        GLib.timeout_add(250, self._tick_ants)

    # ------------------------------------------------------------------ geometry
    @property
    def doc(self):
        return self.win.doc

    @property
    def ox(self):
        return MARGIN - self.hadj.get_value()

    @property
    def oy(self):
        return MARGIN - self.vadj.get_value()

    def to_doc(self, wx, wy):
        return (wx - self.ox) / self.z, (wy - self.oy) / self.z

    def to_screen(self, dx, dy):
        return self.ox + dx * self.z, self.oy + dy * self.z

    def show_rulers(self, on):
        for w in (self.hruler, self.vruler, self.corner):
            w.set_visible(on)

    def update_adjustments(self):
        if self.doc is None:
            return
        aw = max(1, self.area.get_allocated_width())
        ah = max(1, self.area.get_allocated_height())
        tw = self.doc.width * self.z + 2 * MARGIN + HANDLE * 2
        th = self.doc.height * self.z + 2 * MARGIN + HANDLE * 2
        for adj, total, page in ((self.hadj, tw, aw), (self.vadj, th, ah)):
            adj.freeze_notify()
            adj.set_upper(max(total, page))
            adj.set_page_size(page)
            adj.set_page_increment(page * 0.9)
            adj.set_step_increment(max(10, page * 0.05))
            adj.set_value(min(adj.get_value(), max(0, adj.get_upper() - page)))
            adj.thaw_notify()
        self.hscroll.set_visible(tw > aw)
        self.vscroll.set_visible(th > ah)

    def _scrolled(self, *_):
        self.place_text_editor()
        self.area.queue_draw()
        self.hruler.queue_draw()
        self.vruler.queue_draw()

    def set_zoom(self, z, anchor=None):
        z = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], z))
        if anchor is None:
            anchor = (self.area.get_allocated_width() / 2, self.area.get_allocated_height() / 2)
        dx, dy = self.to_doc(*anchor)
        self.z = z
        self.update_adjustments()
        self.hadj.set_value(max(0, MARGIN + dx * z - anchor[0]))
        self.vadj.set_value(max(0, MARGIN + dy * z - anchor[1]))
        self.update_adjustments()
        self.place_text_editor()
        self.area.queue_draw()
        self.hruler.queue_draw()
        self.vruler.queue_draw()
        self.win.on_zoom_changed()

    def zoom_step(self, direction, anchor=None):
        if direction > 0:
            nxt = next((s for s in ZOOM_STEPS if s > self.z + 1e-6), ZOOM_STEPS[-1])
        else:
            nxt = next((s for s in reversed(ZOOM_STEPS) if s < self.z - 1e-6), ZOOM_STEPS[0])
        self.set_zoom(nxt, anchor)

    def zoom_fit(self):
        aw = max(1, self.area.get_allocated_width() - 2 * MARGIN - 2 * HANDLE)
        ah = max(1, self.area.get_allocated_height() - 2 * MARGIN - 2 * HANDLE)
        z = min(aw / self.doc.width, ah / self.doc.height)
        self.z = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], z))
        self.hadj.set_value(0)
        self.vadj.set_value(0)
        self.update_adjustments()
        self.place_text_editor()
        self.area.queue_draw()
        self.hruler.queue_draw()
        self.vruler.queue_draw()
        self.win.on_zoom_changed()

    # ------------------------------------------------------------------ engine sync
    def reset_document(self):
        self.surf = None
        self.surf_key = None
        self.pending = None
        self.text_cancel()
        self.drag = None
        self.sel_path = None
        self.hadj.set_value(0)
        self.vadj.set_value(0)
        self.sync(full=True)

    def _pull(self):
        """Let the engine write its fresh pixels into the shared buffer, then tell cairo.
        cairo requires flush() before the memory is changed behind its back (the X server
        keeps a cached copy of the surface attached to it); marking a surface dirty without
        it trips an assertion in cairo and aborts the program."""
        self.surf.flush()
        r = self.doc.comp_update()
        if r:
            self.surf.mark_dirty_rectangle(*r)
        return r

    def sync(self, full=False):
        """Pull composited pixels from the engine and schedule the matching repaint."""
        doc = self.doc
        if doc is None:
            return
        self._outline = None
        key = (doc.h, doc.width, doc.height, doc.comp_ptr())
        if key != self.surf_key:
            buf = doc.comp_buffer()
            self.surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, doc.width, doc.height, doc.width * 4)
            self.surf_key = key
            doc.invalidate()
            full = True
            self.update_adjustments()
        r = self._pull()
        if full or r is None or True:
            # overlays (ants, handles) move with most changes; a full queue is cheap since
            # cairo clips the scaled paint to the damaged region anyway
            self.area.queue_draw()
        self.win.on_doc_changed()

    # ------------------------------------------------------------------ drawing
    def _draw(self, w, cr):
        doc = self.doc
        aw, ah = w.get_allocated_width(), w.get_allocated_height()
        cr.set_source_rgb(0.902, 0.902, 0.902)   # suite canvas grey #e6e6e6
        cr.paint()
        if doc is None or self.surf is None:
            return False
        if (doc.h, doc.width, doc.height, doc.comp_ptr()) != self.surf_key:
            # the engine reallocated its buffer (e.g. flip/rotate/undo of one); rebind first
            self.sync(full=True)
        self._pull()
        z = self.z
        ox, oy = self.ox, self.oy
        iw, ih = doc.width * z, doc.height * z
        # drop shadow
        cr.set_source_rgba(0, 0, 0, 0.12)
        cr.rectangle(ox + 2, oy + 2, iw, ih)
        cr.fill()
        # transparency checkerboard (screen-space, anchored to the image)
        cr.save()
        cr.rectangle(ox, oy, iw, ih)
        cr.clip()
        cr.set_source(self._checker_pattern(ox, oy))
        cr.paint()
        # the picture
        cr.translate(ox, oy)
        cr.scale(z, z)
        cr.set_source_surface(self.surf, 0, 0)
        pat = cr.get_source()
        if z >= 1:
            pat.set_filter(cairo.FILTER_NEAREST)
        else:
            pat.set_filter(cairo.FILTER_BILINEAR if self.interacting else cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
        if self.st.view["grid"]:
            self._draw_grid(cr, aw, ah)
        self._draw_overlays(cr)
        return False

    def _checker_pattern(self, ox, oy):
        s = 8
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 2 * s, 2 * s)
        c = cairo.Context(surf)
        c.set_source_rgb(1, 1, 1)
        c.paint()
        c.set_source_rgb(0.80, 0.80, 0.80)
        c.rectangle(0, 0, s, s)
        c.rectangle(s, s, s, s)
        c.fill()
        pat = cairo.SurfacePattern(surf)
        pat.set_extend(cairo.EXTEND_REPEAT)
        m = cairo.Matrix()
        m.translate(-ox, -oy)
        pat.set_matrix(m)
        return pat

    def _draw_grid(self, cr, aw, ah):
        z = self.z
        step = 1
        for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if s * z >= 8:
                step = s
                break
        doc = self.doc
        x0, y0 = self.to_doc(0, 0)
        x1, y1 = self.to_doc(aw, ah)
        cr.save()
        cr.rectangle(self.ox, self.oy, doc.width * z, doc.height * z)
        cr.clip()
        cr.set_line_width(1)
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.28)
        gx = max(0, int(x0 // step) * step)
        while gx <= min(doc.width, x1):
            sx = math.floor(self.ox + gx * z) + 0.5
            cr.move_to(sx, max(0, self.oy))
            cr.line_to(sx, min(ah, self.oy + doc.height * z))
            gx += step
        gy = max(0, int(y0 // step) * step)
        while gy <= min(doc.height, y1):
            sy = math.floor(self.oy + gy * z) + 0.5
            cr.move_to(max(0, self.ox), sy)
            cr.line_to(min(aw, self.ox + doc.width * z), sy)
            gy += step
        cr.stroke()
        cr.restore()

    def _ants(self, cr, path_fn):
        cr.save()
        cr.set_line_width(1)
        path_fn()
        cr.set_source_rgb(1, 1, 1)
        cr.set_dash([])
        cr.stroke_preserve()
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.set_dash([4, 4], self.ants)
        cr.stroke()
        cr.restore()

    def _rect_path(self, cr, x0, y0, x1, y1):
        sx0, sy0 = self.to_screen(x0, y0)
        sx1, sy1 = self.to_screen(x1, y1)
        cr.rectangle(math.floor(sx0) + 0.5, math.floor(sy0) + 0.5, math.floor(sx1) - math.floor(sx0), math.floor(sy1) - math.floor(sy0))

    def _handles(self, cr, box, which=None):
        for name, (hx, hy) in self._handle_points(box).items():
            if which and name not in which:
                continue
            cr.rectangle(math.floor(hx - HANDLE / 2) + 0.5, math.floor(hy - HANDLE / 2) + 0.5, HANDLE - 1, HANDLE - 1)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0.35, 0.3, 0.3)
            cr.set_line_width(1)
            cr.stroke()

    def _handle_points(self, box):
        x0, y0, x1, y1 = box
        sx0, sy0 = self.to_screen(x0, y0)
        sx1, sy1 = self.to_screen(x1, y1)
        mx, my = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        return {"nw": (sx0, sy0), "n": (mx, sy0), "ne": (sx1, sy0), "e": (sx1, my),
                "se": (sx1, sy1), "s": (mx, sy1), "sw": (sx0, sy1), "w": (sx0, my)}

    def _hit_handle(self, box, wx, wy, which=None):
        for name, (hx, hy) in self._handle_points(box).items():
            if which and name not in which:
                continue
            if abs(wx - hx) <= HANDLE and abs(wy - hy) <= HANDLE:
                return name
        return None

    def _draw_overlays(self, cr):
        doc = self.doc
        st = self.st
        # selection outline
        fr = doc.float_rect()
        if fr:
            x, y, w, h = fr
            self._ants(cr, lambda: self._rect_path(cr, x, y, x + w, y + h))
            self._handles(cr, (x, y, x + w, y + h))
        else:
            b = doc.sel_bounds()
            if b:
                if self.sel_path and len(self.sel_path) > 2:
                    def path():
                        p = self.sel_path
                        cr.move_to(*self.to_screen(*p[0]))
                        for q in p[1:]:
                            cr.line_to(*self.to_screen(*q))
                        cr.close_path()
                    self._ants(cr, path)
                else:
                    if self._outline is None:
                        self._outline = doc.sel_outline()
                    segs = self._outline

                    def outline():
                        for x0, y0, x1, y1 in segs:
                            cr.move_to(*self.to_screen(x0, y0))
                            cr.line_to(*self.to_screen(x1, y1))
                    self._ants(cr, outline)
        # live marquee / lasso while dragging
        if self.marquee is not None:
            if self.marquee[0] == "rect":
                _, x0, y0, x1, y1 = self.marquee
                bx = _norm_box(x0, y0, x1, y1)
                self._ants(cr, lambda: self._rect_path(cr, *bx))
            else:
                pts = self.marquee[1]
                if len(pts) > 1:
                    def lasso():
                        cr.move_to(*self.to_screen(*pts[0]))
                        for q in pts[1:]:
                            cr.line_to(*self.to_screen(*q))
                    self._ants(cr, lasso)
        # polygon selection being placed
        ps = self.polysel
        if ps is not None:
            pts = ps["pts"] + [ps["hover"]]

            def poly():
                cr.move_to(*self.to_screen(*pts[0]))
                for q in pts[1:]:
                    cr.line_to(*self.to_screen(*q))
            self._ants(cr, poly)
            for q in ps["pts"]:
                sx, sy = self.to_screen(*q)
                self._handle_at(cr, sx, sy)
        # pending shape
        p = self.pending
        if p is not None:
            if p.kind == "line":
                for q in p.pts:
                    sx, sy = self.to_screen(*q)
                    self._handle_at(cr, sx, sy)
            elif p.kind == "polygon" and p.stage < 3:
                for q in p.pts:
                    sx, sy = self.to_screen(*q)
                    self._handle_at(cr, sx, sy)
            elif p.kind == "curve" and p.stage < 3:
                pass
            else:
                bx = p.bbox()
                self._ants(cr, lambda: self._rect_path(cr, *bx))
                self._handles(cr, bx)
        # text box frame
        t = self.text
        if t is not None:
            bx = (t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"])
            self._ants(cr, lambda: self._rect_path(cr, *bx))
            self._handles(cr, bx)
        # canvas resize preview / handles
        if self.canvas_preview is not None:
            w, h = self.canvas_preview
            cr.save()
            cr.set_source_rgb(0.2, 0.2, 0.2)
            cr.set_dash([3, 3])
            cr.set_line_width(1)
            self._rect_path(cr, 0, 0, w, h)
            cr.stroke()
            cr.restore()
        elif self._canvas_handles_visible():
            for name, (hx, hy) in self._canvas_handle_points().items():
                self._handle_at(cr, hx, hy)
        # brush footprint
        if self.mouse and st.tool in ("brush", "eraser", "pencil") and self.drag is None or (self.mouse and self.drag and self.drag.get("kind") == "stroke"):
            size = self.win.current_size()
            if size * self.z >= 5 and self.mouse:
                sx, sy = self.to_screen(*self.mouse)
                cr.save()
                cr.set_line_width(1)
                cr.arc(sx, sy, size * self.z / 2, 0, math.tau)
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.stroke_preserve()
                cr.set_dash([2, 2])
                cr.set_source_rgba(0, 0, 0, 0.9)
                cr.stroke()
                cr.restore()

    def _handle_at(self, cr, sx, sy):
        cr.rectangle(math.floor(sx - HANDLE / 2) + 0.5, math.floor(sy - HANDLE / 2) + 0.5, HANDLE - 1, HANDLE - 1)
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgb(0.35, 0.3, 0.3)
        cr.set_line_width(1)
        cr.stroke()

    def _canvas_handles_visible(self):
        return (self.pending is None and self.text is None and self.doc.float_rect() is None)

    def _canvas_handle_points(self):
        w, h = self.doc.width, self.doc.height
        ex, ey = self.to_screen(w, h)
        mx, my = self.to_screen(w / 2, h / 2)
        off = HANDLE / 2 + 1
        return {"e": (ex + off, my), "s": (mx, ey + off), "se": (ex + off, ey + off)}

    def _canvas_handle_hit(self, wx, wy):
        """The canvas-resize handle under the pointer, but never one overlapping the picture:
        a click on the image's last pixels must paint, whatever the zoom."""
        x, y = self.to_doc(wx, wy)
        if x < self.doc.width and y < self.doc.height:
            return None
        for name, (hx, hy) in self._canvas_handle_points().items():
            if abs(wx - hx) <= HANDLE and abs(wy - hy) <= HANDLE:
                return name
        return None

    def _tick_ants(self):
        if self.doc is not None and (self.doc.sel_bounds() or self.doc.float_rect() or self.pending or self.text or self.marquee):
            self.ants = (self.ants + 1) % 8
            self.area.queue_draw()
        return True

    # ------------------------------------------------------------------ rulers
    def _draw_ruler(self, w, cr, horizontal):
        width, height = w.get_allocated_width(), w.get_allocated_height()
        cr.set_source_rgb(0.965, 0.965, 0.965)
        cr.paint()
        cr.set_source_rgb(0.78, 0.72, 0.72)
        cr.set_line_width(1)
        if horizontal:
            cr.move_to(0, height - 0.5)
            cr.line_to(width, height - 0.5)
        else:
            cr.move_to(width - 0.5, 0)
            cr.line_to(width - 0.5, height)
        cr.stroke()
        if self.doc is None:
            return False
        z = self.z
        major = 1
        for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
            if s * z >= 50:
                major = s
                break
        minor = major / 5 if major >= 5 else major / 2 if major >= 2 else major
        length = width if horizontal else height
        origin = self.ox if horizontal else self.oy
        start = math.floor((-origin) / z / minor) * minor
        cr.set_source_rgb(0.35, 0.3, 0.3)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(8.5)
        v = start
        i = 0
        while True:
            pos = origin + v * z
            if pos > length:
                break
            if pos >= 0:
                is_major = abs(v / major - round(v / major)) < 1e-6
                tick = RULER * (0.6 if is_major else 0.25)
                p = math.floor(pos) + 0.5
                if horizontal:
                    cr.move_to(p, height)
                    cr.line_to(p, height - tick)
                else:
                    cr.move_to(width, p)
                    cr.line_to(width - tick, p)
                cr.stroke()
                if is_major:
                    label = str(int(round(v)))
                    if horizontal:
                        cr.move_to(p + 2, 9)
                        cr.show_text(label)
                    else:
                        cr.save()
                        cr.move_to(9, p + 2)
                        cr.rotate(math.pi / 2)
                        cr.show_text(label)
                        cr.restore()
            v += minor
            i += 1
            if i > 5000:
                break
        if self.mouse:
            pos = (self.to_screen(*self.mouse)[0] if horizontal else self.to_screen(*self.mouse)[1])
            cr.set_source_rgb(0.5, 0, 0)
            if horizontal:
                cr.move_to(pos, 0)
                cr.line_to(pos, height)
            else:
                cr.move_to(0, pos)
                cr.line_to(width, pos)
            cr.stroke()
        return False

    # ------------------------------------------------------------------ cursors
    def _cursor_from_icon(self, name, hot):
        if name in self._cursors:
            return self._cursors[name]
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 32, 32)
        c = cairo.Context(surf)
        # white halo for visibility on dark pictures
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            c.save()
            c.translate(dx, dy)
            paint_icon(c, name, 24, (1, 1, 1), (1, 1, 1))
            c.restore()
        paint_icon(c, name, 24)
        cur = Gdk.Cursor.new_from_surface(self.area.get_display(), surf, hot[0], hot[1])
        self._cursors[name] = cur
        return cur

    def set_cursor(self, name):
        if name == self._cursor_name:
            return
        self._cursor_name = name
        win = self.area.get_window()
        if win is None:
            return
        disp = self.area.get_display()
        if name == "pencil":
            cur = self._cursor_from_icon("pencil", (5, 18))
        elif name == "fill":
            cur = self._cursor_from_icon("fill", (19, 20))
        elif name == "picker":
            cur = self._cursor_from_icon("picker", (4, 20))
        elif name == "zoom":
            cur = self._cursor_from_icon("zoom", (10, 10))
        else:
            cur = Gdk.Cursor.new_from_name(disp, name)
        win.set_cursor(cur)

    def _update_cursor(self, wx, wy):
        st = self.st
        doc = self.doc
        if self.drag:
            return
        if self._canvas_handles_visible():
            name = self._canvas_handle_hit(wx, wy)
            if name:
                self.set_cursor(HANDLE_CURSORS[name])
                return
        if self.text is not None:
            t = self.text
            h = self._hit_handle((t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]), wx, wy)
            if h:
                self.set_cursor(HANDLE_CURSORS[h])
                return
        if self.pending is not None and self.pending.editable():
            p = self.pending
            if p.kind == "line":
                for q in p.pts:
                    sx, sy = self.to_screen(*q)
                    if abs(wx - sx) <= HANDLE and abs(wy - sy) <= HANDLE:
                        self.set_cursor("crosshair")
                        return
            else:
                h = self._hit_handle(p.bbox(), wx, wy)
                if h:
                    self.set_cursor(HANDLE_CURSORS[h])
                    return
            if self._inside_pending(wx, wy):
                self.set_cursor("move")
                return
        fr = doc.float_rect()
        if fr and st.tool in SEL_TOOLS:
            x, y, w, h = fr
            hh = self._hit_handle((x, y, x + w, y + h), wx, wy)
            if hh:
                self.set_cursor(HANDLE_CURSORS[hh])
                return
            dx, dy = self.to_doc(wx, wy)
            if x <= dx < x + w and y <= dy < y + h:
                self.set_cursor("move")
                return
        if st.tool in SEL_TOOLS:
            b = doc.sel_bounds()
            if b:
                dx, dy = self.to_doc(wx, wy)
                if b[0] <= dx < b[0] + b[2] and b[1] <= dy < b[1] + b[3]:
                    self.set_cursor("move")
                    return
            self.set_cursor("crosshair")
        elif st.tool == "text":
            self.set_cursor("text")
        elif st.tool in ("pencil", "fill", "picker", "zoom"):
            self.set_cursor(st.tool)
        else:
            self.set_cursor("crosshair")

    # ------------------------------------------------------------------ helpers
    def _button_colors(self, button):
        st = self.st
        return (st.color1, st.color2) if button != 3 else (st.color2, st.color1)

    def _inside_pending(self, wx, wy):
        p = self.pending
        if p is None:
            return False
        x0, y0, x1, y1 = p.bbox()
        dx, dy = self.to_doc(wx, wy)
        pad = HANDLE / self.z
        return x0 - pad <= dx <= x1 + pad and y0 - pad <= dy <= y1 + pad

    def render_pending(self):
        p = self.pending
        if p is None:
            return
        doc = self.doc
        st = self.st
        doc.op_restore()
        outline, fill = self._button_colors(p.button)
        width = float(st.sizes["shape"])
        for path, closed in p.paths():
            if len(path) < 1:
                continue
            is_open_kind = p.kind in ("line", "curve") or (p.kind == "polygon" and p.stage < 3)
            doc.shape(path, closed, width, outline, fill,
                      True if is_open_kind else st.outline,
                      False if is_open_kind else st.fill_shape)
        self.sync()

    def commit_pending(self):
        if self.pending is None:
            return
        p = self.pending
        if p.kind == "polygon" and p.stage < 3 and len(p.pts) >= 3:
            p.stage = 3
            self.render_pending()
        self.pending = None
        self.doc.op_end()
        # what the step was, and the colours it used
        st = self.st
        outline, fill = self._button_colors(p.button)
        open_kind = p.kind in ("line", "curve")
        if open_kind or st.outline:
            self.win.note_color(outline)
        if not open_kind and st.fill_shape:
            self.win.note_color(fill)
        self.win._action = dict(S.SHAPES).get(p.kind, "Shape")
        self.sync()
        self.win.after_edit()

    def cancel_pending(self):
        if self.pending is None:
            return False
        self.pending = None
        self.doc.op_cancel()
        self.sync()
        return True

    def finalize(self):
        self.polysel = None
        """Commit anything in progress (shape, text) before a command runs."""
        if self.drag and self.drag.get("kind") == "stroke":
            self.doc.stroke_end()
            self.drag = None
        self.commit_pending()
        self.text_commit()

    # ------------------------------------------------------------------ mouse
    def _press(self, w, ev):
        self.area.grab_focus()
        self.win._action = None
        if self.win.playing:
            self.win.stop_playback()
        doc = self.doc
        if doc is None:
            return True
        wx, wy = ev.x, ev.y
        x, y = self.to_doc(wx, wy)
        st = self.st
        dbl = ev.type == Gdk.EventType._2BUTTON_PRESS
        if ev.type == Gdk.EventType._3BUTTON_PRESS:
            return True
        if ev.button == 2:
            self.drag = {"kind": "pan", "wx": wx, "wy": wy, "h": self.hadj.get_value(), "v": self.vadj.get_value()}
            self.set_cursor("grabbing")
            return True
        if ev.button not in (1, 3):
            return True
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)

        # text box: handles first, then click outside commits
        if self.text is not None:
            t = self.text
            h = self._hit_handle((t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]), wx, wy)
            if h and ev.button == 1:
                self.drag = {"kind": "textbox", "handle": h, "start": (x, y), "orig": (t["x"], t["y"], t["w"], t["h"])}
                return True
            self.text_commit()
            return True

        # polygon in progress
        p = self.pending
        if p is not None and p.kind == "polygon" and p.stage < 3:
            first = self.to_screen(*p.pts[0])
            if dbl or (math.hypot(wx - first[0], wy - first[1]) <= HANDLE and len(p.pts) >= 3):
                if not dbl:
                    pass
                elif len(p.pts) > 3:
                    p.pts.pop()  # the double-click's first press already added a vertex
                p.stage = 3
                self.render_pending()
                return True
            p.pts.append(self._snap(p.pts[-1], (x, y)) if shift else (x, y))
            self.drag = {"kind": "polyvertex", "shift": shift}
            self.render_pending()
            return True

        # curve bending stages
        if p is not None and p.kind == "curve" and p.stage in (1, 2):
            if p.stage == 1:
                p.pts[1] = (x, y)
                p.pts[2] = (x, y)
            else:
                p.pts[2] = (x, y)
            self.drag = {"kind": "curvebend"}
            self.render_pending()
            return True

        # editable pending shape
        if p is not None and p.editable():
            if p.kind == "line":
                for i, q in enumerate(p.pts):
                    sx, sy = self.to_screen(*q)
                    if abs(wx - sx) <= HANDLE and abs(wy - sy) <= HANDLE:
                        self.drag = {"kind": "lineend", "i": i}
                        return True
            else:
                h = self._hit_handle(p.bbox(), wx, wy)
                if h:
                    self.drag = {"kind": "shapehandle", "handle": h, "orig": list(p.pts), "box": p.bbox(), "start": (x, y)}
                    return True
            if self._inside_pending(wx, wy):
                self.drag = {"kind": "shapemove", "orig": list(p.pts), "start": (x, y)}
                return True
            self.commit_pending()

        # canvas resize handles
        if self._canvas_handles_visible() and ev.button == 1:
            name = self._canvas_handle_hit(wx, wy)
            if name:
                self.drag = {"kind": "canvas", "handle": name, "start": (x, y), "orig": (doc.width, doc.height)}
                self.canvas_preview = (doc.width, doc.height)
                return True

        tool = st.tool
        self.interacting = True
        if tool in ("pencil", "brush", "eraser"):
            if tool == "pencil":
                code, hard = E.TOOL_PENCIL, 1.0
            elif tool == "eraser":
                code, hard = E.TOOL_ERASER, 1.0
            else:
                code, hard = BRUSH_TOOLS[st.brush]
            color = self._button_colors(ev.button)[0]
            self.win.note_color(color)
            doc.stroke_begin(code, float(self.win.current_size()), hard, color)
            px, py = (math.floor(x) + 0.5, math.floor(y) + 0.5) if tool == "pencil" else (x, y)
            doc.stroke_to(px, py)
            stab = Stabilizer(*st.stabilizer[tool], zoom=self.z)
            stab.start(x, y)
            self.drag = {"kind": "stroke", "tool": tool, "start": (px, py), "stab": stab if stab.active else None}
            if tool == "brush" and st.brush == "airbrush":
                self.drag["timer"] = GLib.timeout_add(40, self._airbrush_tick)
            self.sync()
        elif tool == "fill":
            color = self._button_colors(ev.button)[0]
            self.win.note_color(color)
            if doc.fill(int(math.floor(x)), int(math.floor(y)), color, int(round(st.tolerance * 2.55))):
                self.sync()
                self.win.after_edit()
        elif tool == "picker":
            if 0 <= x < doc.width and 0 <= y < doc.height:
                c = doc.pick(int(x), int(y), True)
                self.win.set_color(1 if ev.button == 1 else 2, c)
                self.win.set_tool(st.prev_tool or "pencil")
        elif tool == "zoom":
            self.zoom_step(1 if ev.button == 1 else -1, (wx, wy))
        elif tool == "text":
            if ev.button == 1:
                hit = self.text_layer_at(x, y)
                if hit is not None and self.text is None:
                    # a text layer: typed again where it is
                    self.text_edit_layer(*hit)
                    return True
                self.drag = {"kind": "textnew", "start": (x, y)}
                self.marquee = ("rect", x, y, x, y)
        elif tool == "shape":
            kind = st.shape
            if kind == "line":
                self.pending = Pending("line", ev.button, [(x, y), (x, y)])
            elif kind == "curve":
                self.pending = Pending("curve", ev.button, [(x, y), (x, y), (x, y), (x, y)])
            elif kind == "polygon":
                self.pending = Pending("polygon", ev.button, [(x, y), (x, y)])
            else:
                self.pending = Pending(kind, ev.button, [(x, y), (x, y)])
            doc.op_begin()
            self.drag = {"kind": "shapenew", "start": (x, y)}
        elif tool in SEL_TOOLS:
            if ev.button == 3:
                if self.polysel is not None:
                    self.polysel = None
                    self.area.queue_draw()
                self.win.popup_selection_menu(ev)
                self.interacting = False
                return True
            alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
            # Shift adds to the selection, Alt takes away, both keep what is in both
            mode = (E.Document.SEL_INTERSECT if shift and alt else E.Document.SEL_ADD if shift
                    else E.Document.SEL_SUBTRACT if alt else E.Document.SEL_REPLACE)
            if tool == "polyselect" and self.polysel is not None:
                ps = self.polysel
                first = self.to_screen(*ps["pts"][0])
                if dbl or (len(ps["pts"]) >= 3 and math.hypot(wx - first[0], wy - first[1]) <= HANDLE):
                    if dbl and len(ps["pts"]) > 3:
                        ps["pts"].pop()   # the double-click's first press added a point
                    self.polysel_finish()
                else:
                    ps["pts"].append((x, y))
                    ps["hover"] = (x, y)
                    self.area.queue_draw()
                self.interacting = False
                return True
            if mode != E.Document.SEL_REPLACE or tool in ("wand", "polyselect"):
                # combining (or a wand click / polygon point): no moving, start the new part straight away
                if doc.float_rect():
                    doc.float_commit()
                    self.win.after_edit()
                self._sel_start(tool, x, y, mode)
                return True
            fr = doc.float_rect()
            if fr:
                fx, fy, fw, fh = fr
                h = self._hit_handle((fx, fy, fx + fw, fy + fh), wx, wy)
                if h:
                    self.drag = {"kind": "floatresize", "handle": h, "orig": fr, "start": (x, y)}
                    return True
                if fx <= x < fx + fw and fy <= y < fy + fh:
                    if ctrl:
                        # Ctrl-drag stamps a copy and keeps moving
                        doc.float_commit()
                        self._lift(False)
                    self.drag = {"kind": "floatmove", "orig": doc.float_rect(), "start": (x, y)}
                    return True
                doc.float_commit()
                self.sel_path = None
                self.sync()
                self.win.after_edit()
            b = doc.sel_bounds()
            if b and b[0] <= x < b[0] + b[2] and b[1] <= y < b[1] + b[3]:
                self._lift(not ctrl)
                self.drag = {"kind": "floatmove", "orig": doc.float_rect(), "start": (x, y)}
                return True
            self._sel_start(tool, x, y, mode)
        return True

    def _sel_start(self, tool, x, y, mode):
        doc = self.doc
        if tool == "select":
            self.drag = {"kind": "marquee", "start": (x, y), "mode": mode}
            self.marquee = ("rect", x, y, x, y)
        elif tool == "freeselect":
            self.drag = {"kind": "lasso", "mode": mode}
            self.marquee = ("lasso", [(x, y)])
        elif tool == "polyselect":
            self.polysel = {"pts": [(x, y)], "hover": (x, y), "mode": mode}
            self.interacting = False
            self.area.queue_draw()
        elif tool == "wand":
            self.interacting = False
            if 0 <= x < doc.width and 0 <= y < doc.height:
                doc.sel_set_mode(mode)
                doc.sel_magic(int(math.floor(x)), int(math.floor(y)), int(round(self.st.wand_tolerance * 2.55)),
                              self.st.wand_contiguous)
                self.sel_path = None
                self.sync()
                b = doc.sel_bounds()
                self.win.on_selection_size(b[2], b[3]) if b else self.win.on_selection_size(0, 0)

    def polysel_finish(self):
        """Close the polygon selection being placed (at least three points)."""
        ps, self.polysel = self.polysel, None
        if ps is None:
            return False
        if len(ps["pts"]) >= 3:
            self.doc.sel_set_mode(ps["mode"])
            self.doc.sel_poly(ps["pts"])
            replace = ps["mode"] == E.Document.SEL_REPLACE
            self.sel_path = list(ps["pts"]) if replace and self.doc.sel_bounds() else None
        self.sync()
        return True

    def _lift(self, cut):
        doc = self.doc
        if self.st.transparent_sel:
            doc.sel_exclude_color(self.st.color2, 0)
        ok = doc.float_lift(cut)
        if ok and doc.float_is_empty() and doc.layer_count() > 1:
            self.win.hint("Nothing to move on “%s”. Click the layer that holds it in the Layers panel." % doc.layer_name(doc.active))
        self.sel_path = None
        self.sync()
        return ok

    def _stroke_to(self, d, pts):
        drew = False
        for p in pts:
            if p is None:
                continue
            x, y = p
            if d["tool"] == "pencil":
                x, y = math.floor(x) + 0.5, math.floor(y) + 0.5
            self.doc.stroke_to(x, y)
            d["at"] = (x, y)
            drew = True
        if drew:
            self.sync()

    def _airbrush_tick(self):
        d = self.drag
        if not d or d.get("kind") != "stroke" or not self.mouse:
            return False
        self.doc.stroke_to(*(d.get("at") if d.get("stab") and d.get("at") else self.mouse))
        self.sync()
        return True

    def _snap(self, origin, pt, square=False):
        dx, dy = pt[0] - origin[0], pt[1] - origin[1]
        if square:
            m = max(abs(dx), abs(dy))
            return (origin[0] + math.copysign(m, dx or 1), origin[1] + math.copysign(m, dy or 1))
        ang = math.atan2(dy, dx)
        snap = round(ang / (math.pi / 4)) * (math.pi / 4)
        r = math.hypot(dx, dy)
        return (origin[0] + r * math.cos(snap), origin[1] + r * math.sin(snap))

    def _motion(self, w, ev):
        doc = self.doc
        if doc is None:
            return True
        wx, wy = ev.x, ev.y
        x, y = self.to_doc(wx, wy)
        self.mouse = (x, y)
        self.win.on_pointer(x, y)
        if self.st.view["rulers"]:
            self.hruler.queue_draw()
            self.vruler.queue_draw()
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        d = self.drag
        if d is None:
            self._update_cursor(wx, wy)
            if self.polysel is not None:
                self.polysel["hover"] = (x, y)
                self.area.queue_draw()
            p = self.pending
            if p is not None and p.kind == "polygon" and p.stage < 3 and len(p.pts) >= 2:
                pass
            if self.st.tool in ("brush", "eraser", "pencil"):
                self.area.queue_draw()
            return True
        k = d["kind"]
        if k == "pan":
            self.hadj.set_value(d["h"] - (wx - d["wx"]))
            self.vadj.set_value(d["v"] - (wy - d["wy"]))
        elif k == "stroke":
            self._stroke_to(d, [(x, y)] if d["stab"] is None else [d["stab"].feed(x, y)])
        elif k == "shapenew":
            p = self.pending
            sx, sy = d["start"]
            if p.kind in BBOX_SHAPES:
                end = self._snap((sx, sy), (x, y), square=True) if shift else (x, y)
                p.pts = [(sx, sy), end]
            elif p.kind == "line":
                p.pts = [(sx, sy), self._snap((sx, sy), (x, y)) if shift else (x, y)]
            elif p.kind == "curve":
                end = self._snap((sx, sy), (x, y)) if shift else (x, y)
                p.pts = [(sx, sy), (sx, sy), end, end]
            elif p.kind == "polygon":
                p.pts[-1] = self._snap(p.pts[0], (x, y)) if shift else (x, y)
            self.render_pending()
        elif k == "polyvertex":
            p = self.pending
            p.pts[-1] = self._snap(p.pts[-2], (x, y)) if shift else (x, y)
            self.render_pending()
        elif k == "curvebend":
            p = self.pending
            if p.stage == 1:
                p.pts[1] = (x, y)
                p.pts[2] = (x, y)
            else:
                p.pts[2] = (x, y)
            self.render_pending()
        elif k == "lineend":
            p = self.pending
            other = p.pts[1 - d["i"]]
            p.pts[d["i"]] = self._snap(other, (x, y)) if shift else (x, y)
            self.render_pending()
        elif k == "shapemove":
            p = self.pending
            dx, dy = x - d["start"][0], y - d["start"][1]
            p.pts = [(q[0] + dx, q[1] + dy) for q in d["orig"]]
            self.render_pending()
        elif k == "shapehandle":
            p = self.pending
            nb = self._resize_box(d["box"], d["handle"], x - d["start"][0], y - d["start"][1], shift)
            ob = d["box"]
            ow, oh = (ob[2] - ob[0]) or 1e-6, (ob[3] - ob[1]) or 1e-6
            nw, nh = nb[2] - nb[0], nb[3] - nb[1]
            p.pts = [(nb[0] + (q[0] - ob[0]) * nw / ow, nb[1] + (q[1] - ob[1]) * nh / oh) for q in d["orig"]]
            self.render_pending()
        elif k == "marquee":
            sx, sy = d["start"]
            square = shift and d.get("mode", 0) == E.Document.SEL_REPLACE
            end = self._snap((sx, sy), (x, y), square=True) if square else (x, y)
            self.marquee = ("rect", sx, sy, end[0], end[1])
            self.win.on_selection_size(abs(end[0] - sx), abs(end[1] - sy))
            self.area.queue_draw()
        elif k == "lasso":
            pts = self.marquee[1]
            if math.hypot(x - pts[-1][0], y - pts[-1][1]) * self.z >= 1.5:
                pts.append((x, y))
            self.area.queue_draw()
        elif k == "floatmove":
            fx, fy, fw, fh = d["orig"]
            dx, dy = round(x - d["start"][0]), round(y - d["start"][1])
            doc.float_set_rect(fx + dx, fy + dy, fw, fh)
            self.sync()
        elif k == "floatresize":
            fx, fy, fw, fh = d["orig"]
            nb = self._resize_box((fx, fy, fx + fw, fy + fh), d["handle"], x - d["start"][0], y - d["start"][1], shift)
            doc.float_set_rect(nb[0], nb[1], max(1, nb[2] - nb[0]), max(1, nb[3] - nb[1]))
            self.win.on_selection_size(max(1, round(nb[2] - nb[0])), max(1, round(nb[3] - nb[1])))
            self.sync()
        elif k == "textnew":
            sx, sy = d["start"]
            self.marquee = ("rect", sx, sy, x, y)
            self.area.queue_draw()
        elif k == "textbox":
            t = self.text
            ox_, oy_, ow, oh = d["orig"]
            nb = self._resize_box((ox_, oy_, ox_ + ow, oy_ + oh), d["handle"], x - d["start"][0], y - d["start"][1], False)
            t["x"], t["y"] = round(nb[0]), round(nb[1])
            t["w"], t["h"] = max(8, round(nb[2] - nb[0])), max(8, round(nb[3] - nb[1]))
            self.place_text_editor()
            self.area.queue_draw()
        elif k == "canvas":
            cw, ch = d["orig"]
            nx = max(1, min(32768, round(cw + x - d["start"][0])))
            ny = max(1, min(32768, round(ch + y - d["start"][1])))
            if d["handle"] == "e":
                self.canvas_preview = (nx, ch)
            elif d["handle"] == "s":
                self.canvas_preview = (cw, ny)
            else:
                self.canvas_preview = (nx, ny)
            self.win.on_selection_size(*self.canvas_preview)
            self.area.queue_draw()
        return True

    def _resize_box(self, box, handle, dx, dy, keep_aspect):
        x0, y0, x1, y1 = box
        if "w" in handle:
            x0 += dx
        if "e" in handle:
            x1 += dx
        if "n" in handle:
            y0 += dy
        if "s" in handle:
            y1 += dy
        if keep_aspect and len(handle) == 2:
            ow, oh = box[2] - box[0], box[3] - box[1]
            if ow > 0 and oh > 0:
                sc = max(abs(x1 - x0) / ow, abs(y1 - y0) / oh)
                nw, nh = ow * sc, oh * sc
                if "w" in handle:
                    x0 = x1 - nw
                else:
                    x1 = x0 + nw
                if "n" in handle:
                    y0 = y1 - nh
                else:
                    y1 = y0 + nh
        return _norm_box(x0, y0, x1, y1)

    def _release(self, w, ev):
        doc = self.doc
        d = self.drag
        self.drag = None
        self.interacting = False
        if d is None or doc is None:
            self.area.queue_draw()
            return True
        x, y = self.to_doc(ev.x, ev.y)
        k = d["kind"]
        if k == "pan":
            self._cursor_name = None
            self._update_cursor(ev.x, ev.y)
        elif k == "stroke":
            if "timer" in d:
                GLib.source_remove(d["timer"])
            if d["stab"] is not None:
                self._stroke_to(d, d["stab"].finish())
            doc.stroke_end()
            self.sync()
            self.win.after_edit()
        elif k == "shapenew":
            p = self.pending
            if p.kind == "curve":
                if p.pts[0] == p.pts[3]:
                    self.cancel_pending()
                else:
                    p.stage = 1
            elif p.kind == "polygon":
                pass
            else:
                (ax, ay), (bx, by) = p.pts[0], p.pts[-1]
                if abs(ax - bx) * self.z < 2 and abs(ay - by) * self.z < 2:
                    self.cancel_pending()
            self.area.queue_draw()
        elif k == "curvebend":
            p = self.pending
            p.stage += 1
            self.area.queue_draw()
        elif k == "marquee":
            _, x0, y0, x1, y1 = self.marquee
            self.marquee = None
            bx = _norm_box(round(x0), round(y0), round(x1), round(y1))
            mode = d.get("mode", E.Document.SEL_REPLACE)
            if bx[2] - bx[0] >= 1 and bx[3] - bx[1] >= 1:
                doc.sel_set_mode(mode)
                doc.sel_rect(bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1])
                self.sel_path = None
            elif mode == E.Document.SEL_REPLACE:
                doc.sel_none()
                self.sel_path = None
            self.sync()
        elif k == "lasso":
            pts = self.marquee[1]
            self.marquee = None
            mode = d.get("mode", E.Document.SEL_REPLACE)
            if len(pts) >= 3:
                doc.sel_set_mode(mode)
                doc.sel_poly(pts)
                self.sel_path = pts if mode == E.Document.SEL_REPLACE and doc.sel_bounds() else None
            elif mode == E.Document.SEL_REPLACE:
                doc.sel_none()
                self.sel_path = None
            self.sync()
        elif k in ("floatmove", "floatresize"):
            self.sync()
            self.win.after_edit()
        elif k == "textnew":
            sx, sy = d["start"]
            self.marquee = None
            bx = _norm_box(sx, sy, x, y)
            if (bx[2] - bx[0]) * self.z < 6 or (bx[3] - bx[1]) * self.z < 6:
                # a click makes a default-sized box
                size_px = self.st.font_size * 96 / 72
                bx = (sx, sy, sx + max(120, size_px * 8), sy + size_px * 1.6)
            self.text_begin(round(bx[0]), round(bx[1]), round(bx[2] - bx[0]), round(bx[3] - bx[1]))
        elif k == "canvas":
            w2, h2 = self.canvas_preview
            self.canvas_preview = None
            if (w2, h2) != (doc.width, doc.height):
                self.win.cmd("canvas_resize", w2, h2)
            self.area.queue_draw()
        self.area.queue_draw()
        self.win.refresh_state()
        return True

    def _scroll(self, w, ev):
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok:
            d = ev.direction
            dx, dy = {Gdk.ScrollDirection.UP: (0, -1), Gdk.ScrollDirection.DOWN: (0, 1),
                      Gdk.ScrollDirection.LEFT: (-1, 0), Gdk.ScrollDirection.RIGHT: (1, 0)}.get(d, (0, 0))
        if ctrl:
            if dy < 0:
                self.zoom_step(1, (ev.x, ev.y))
            elif dy > 0:
                self.zoom_step(-1, (ev.x, ev.y))
            return True
        if shift and dx == 0:
            dx, dy = dy, 0
        self.hadj.set_value(self.hadj.get_value() + dx * 60)
        self.vadj.set_value(self.vadj.get_value() + dy * 60)
        return True

    def _leave(self, *_):
        self.mouse = None
        self.win.on_pointer(None, None)
        self.area.queue_draw()
        self.hruler.queue_draw()
        self.vruler.queue_draw()

    # ------------------------------------------------------------------ keyboard
    def nudge(self, dx, dy):
        doc = self.doc
        if self.pending is not None and self.pending.editable():
            p = self.pending
            p.pts = [(q[0] + dx, q[1] + dy) for q in p.pts]
            self.render_pending()
            return True
        if doc.float_rect() is None and doc.sel_bounds():
            self._lift(True)
        fr = doc.float_rect()
        if fr:
            doc.float_set_rect(fr[0] + dx, fr[1] + dy, fr[2], fr[3])
            self.sync()
            return True
        return False

    def escape(self):
        if self.polysel is not None:
            self.polysel = None
            self.area.queue_draw()
            return True
        if self.drag:
            d = self.drag
            self.drag = None
            self.marquee = None
            self.canvas_preview = None
            if d["kind"] == "stroke":
                if "timer" in d:
                    GLib.source_remove(d["timer"])
                self.doc.stroke_end()
                self.doc.undo()
            if self.pending is not None:
                self.cancel_pending()
            self.sync()
            return True
        if self.text is not None:
            self.text_cancel()
            return True
        if self.pending is not None:
            p = self.pending
            if p.kind == "polygon" and p.stage < 3 and len(p.pts) >= 3:
                p.stage = 3
                self.render_pending()
                self.commit_pending()
            else:
                self.commit_pending()
            return True
        if self.doc.float_rect():
            self.doc.float_commit()
            self.sync()
            return True
        if self.doc.sel_bounds():
            self.doc.sel_none()
            self.sel_path = None
            self.sync()
            return True
        return False

    def enter(self):
        if self.polysel is not None:
            if len(self.polysel["pts"]) >= 3:
                self.polysel_finish()
            return True
        p = self.pending
        if p is not None:
            if p.kind == "polygon" and p.stage < 3:
                if len(p.pts) >= 3:
                    p.stage = 3
                    self.render_pending()
                return True
            self.commit_pending()
            return True
        return False

    # ------------------------------------------------------------------ text editing
    def text_begin(self, x, y, w, h):
        self.text_commit()
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(0)
        tv.set_right_margin(0)
        tv.set_top_margin(0)
        tv.set_bottom_margin(0)
        tv.set_accepts_tab(True)
        tv.get_style_context().add_class("fd-textedit")
        prov = Gtk.CssProvider()
        tv.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        buf = tv.get_buffer()
        tags = {
            "underline": buf.create_tag("u", underline=Pango.Underline.SINGLE),
            "strike": buf.create_tag("s", strikethrough=True),
        }
        self.text = {"x": x, "y": y, "w": w, "h": h, "view": tv, "css": prov, "tags": tags,
                     "history": [""], "hpos": 0, "lock": False}
        buf.connect("changed", self._text_changed)
        self.fixed.put(tv, 0, 0)
        self.text_style_changed()
        self.place_text_editor()
        tv.show()
        tv.grab_focus()
        self.win.on_text_mode(True)
        self.area.queue_draw()

    def _text_changed(self, buf):
        t = self.text
        if t is None:
            return
        self._apply_text_tags()
        if t["lock"]:
            return
        txt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        hist = t["history"][: t["hpos"] + 1]
        prev = hist[-1]
        # coalesce typing into word-sized undo steps
        if len(hist) > 1 and len(txt) == len(prev) + 1 and txt.startswith(prev) and not txt[-1].isspace():
            hist[-1] = txt
        else:
            hist.append(txt)
        t["history"] = hist[-200:]
        t["hpos"] = len(t["history"]) - 1

    def text_undo(self, redo=False):
        t = self.text
        if t is None:
            return
        npos = t["hpos"] + (1 if redo else -1)
        if 0 <= npos < len(t["history"]):
            t["hpos"] = npos
            t["lock"] = True
            t["view"].get_buffer().set_text(t["history"][npos])
            t["lock"] = False

    def _apply_text_tags(self):
        t = self.text
        buf = t["view"].get_buffer()
        s, e = buf.get_start_iter(), buf.get_end_iter()
        for k, tag in t["tags"].items():
            buf.remove_tag(tag, s, e)
            if getattr(self.st, k):
                buf.apply_tag(tag, s, e)

    def _font_px(self):
        return self.st.font_size * 96.0 / 72.0

    def text_style_changed(self):
        t = self.text
        if t is None:
            return
        st = self.st
        c1 = st.color1
        bg = "rgba(%d,%d,%d,%.3f)" % (st.color2[0], st.color2[1], st.color2[2], st.color2[3] / 255) if st.text_opaque else "transparent"
        fam = st.font_family.replace('"', "")
        css = (
            "textview, textview text { background-color: %s; color: rgba(%d,%d,%d,%.3f); caret-color: rgb(%d,%d,%d);"
            " font-family: \"%s\"; font-size: %.2fpx; font-weight: %s; font-style: %s; padding: 0; }"
            % (bg, c1[0], c1[1], c1[2], max(0.25, c1[3] / 255), 255 - c1[0] if c1[3] < 40 else c1[0], c1[1], c1[2],
               fam, self._font_px() * self.z, "bold" if st.bold else "normal", "italic" if st.italic else "normal")
        )
        t["css"].load_from_data(css.encode())
        self._apply_text_tags()

    def place_text_editor(self):
        t = self.text
        if t is None:
            return
        sx, sy = self.to_screen(t["x"], t["y"])
        tv = t["view"]
        tv.set_size_request(max(4, int(t["w"] * self.z)), max(4, int(t["h"] * self.z)))
        self.fixed.move(tv, int(round(sx)), int(round(sy)))
        if self.text_style_changed and t.get("_z") != self.z:
            t["_z"] = self.z
            self.text_style_changed()

    def text_cancel(self):
        t = self.text
        if t is None:
            return
        self.text = None
        t["view"].destroy()
        self._text_layer_shown(t)
        self.sync()
        self.win.on_text_mode(False)
        self.area.queue_draw()
        self.area.grab_focus()

    TEXT_KEYS = ("font_family", "font_size", "bold", "italic", "underline", "strike", "text_opaque")

    def text_spec(self, txt, x, y, w, h):
        """What a text layer keeps so it can be typed again."""
        d = {"text": txt, "x": x, "y": y, "w": w, "h": h, "color1": list(self.st.color1), "color2": list(self.st.color2)}
        for k in self.TEXT_KEYS:
            d[k] = getattr(self.st, k)
        return json.dumps(d)

    def text_layer_at(self, x, y):
        """The topmost visible text layer whose box holds the point: (index, description) or None."""
        doc = self.doc
        for i in range(doc.layer_count() - 1, -1, -1):
            raw = doc.layer_text(i)
            if not raw or not doc.layer_props(i)["visible"]:
                continue
            try:
                s = json.loads(raw)
            except ValueError:
                continue
            if s["x"] <= x < s["x"] + s["w"] and s["y"] <= y < s["y"] + s["h"]:
                return i, s
        return None

    def text_edit_layer(self, i, s):
        """Open a text layer for typing again: its settings come back, its pixels hide meanwhile."""
        self.text_commit()
        doc = self.doc
        if doc.active != i:
            doc.set_active(i)
        for k in self.TEXT_KEYS:
            if k in s:
                setattr(self.st, k, s[k])
        self.st.color1 = tuple(s.get("color1", self.st.color1))
        self.st.color2 = tuple(s.get("color2", self.st.color2))
        doc.layer_set(i, visible=False, record=False)
        self.sync()
        self.text_begin(s["x"], s["y"], s["w"], s["h"])
        self.text["layer"] = i
        buf = self.text["view"].get_buffer()
        buf.set_text(s.get("text", ""))
        self.text["history"] = [s.get("text", "")]
        self.text["hpos"] = 0
        self.text_style_changed()
        self.win.ribbon.refresh()
        self.win.refresh_state()

    def _text_layer_shown(self, t):
        i = t.get("layer")
        if i is not None and i < self.doc.layer_count():
            self.doc.layer_set(i, visible=True, record=False)

    def text_commit(self):
        t = self.text
        if t is None:
            return
        buf = t["view"].get_buffer()
        txt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self.text = None
        t["view"].destroy()
        self.win.on_text_mode(False)
        self._text_layer_shown(t)
        keep = txt.strip() or (self.st.text_opaque and txt)
        i = t.get("layer")
        if keep:
            block = self.render_text_block(txt, t["w"], t["h"])
            spec = self.text_spec(txt, t["x"], t["y"], t["w"], t["h"])
            if i is not None:
                self.doc.text_layer_set(i, spec, (t["x"], t["y"]) + block)
            else:
                self.doc.text_layer_add("Text", spec, t["x"], t["y"], *block)
            self.win.note_color(self.st.color1)
            self.win._action = "Text"
            self.sync()
            self.win.after_edit()
        elif i is not None:
            # emptied: the text layer goes
            self.doc.set_active(i)
            self.doc.layer_delete()
            self.sync()
            self.win.after_edit()
        self.area.grab_focus()
        self.area.queue_draw()

    def text_layout(self, cr, txt, w):
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        st = self.st
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription()
        fd.set_family(st.font_family)
        fd.set_absolute_size(self._font_px() * Pango.SCALE)
        fd.set_weight(Pango.Weight.BOLD if st.bold else Pango.Weight.NORMAL)
        fd.set_style(Pango.Style.ITALIC if st.italic else Pango.Style.NORMAL)
        layout.set_font_description(fd)
        layout.set_width(int(w * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        attrs = Pango.AttrList()
        if st.underline:
            attrs.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
        if st.strike:
            attrs.insert(Pango.attr_strikethrough_new(True))
        layout.set_attributes(attrs)
        layout.set_text(txt, -1)
        return layout

    def render_text_block(self, txt, w, h):
        """The text as cairo ARGB32: (w, h, data, stride)."""
        from gi.repository import PangoCairo
        st = self.st
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
        cr = cairo.Context(surf)
        opts = cairo.FontOptions()
        opts.set_antialias(cairo.ANTIALIAS_GRAY)
        opts.set_hint_style(cairo.HINT_STYLE_NONE)
        opts.set_hint_metrics(cairo.HINT_METRICS_OFF)
        PangoCairo.context_set_font_options(PangoCairo.create_context(cr), opts)
        if st.text_opaque:
            c2 = st.color2
            cr.set_source_rgba(c2[0] / 255, c2[1] / 255, c2[2] / 255, c2[3] / 255)
            cr.paint()
        layout = self.text_layout(cr, txt, w)
        PangoCairo.context_set_font_options(layout.get_context(), opts)
        layout.context_changed()
        c1 = st.color1
        cr.set_source_rgba(c1[0] / 255, c1[1] / 255, c1[2] / 255, c1[3] / 255)
        PangoCairo.show_layout(cr, layout)
        surf.flush()
        data = bytes(surf.get_data())
        return (surf.get_width(), surf.get_height(), data, surf.get_stride())

    def render_text_to_layer(self, txt, x, y, w, h):
        """The text painted into the active layer's pixels."""
        w2, h2, data, stride = self.render_text_block(txt, w, h)
        self.doc.blit_premul(x, y, w2, h2, data, stride)
        self.sync()
        self.win.after_edit()
