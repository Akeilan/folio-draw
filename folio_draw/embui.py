"""The embroidery add-on's interface: the Embroidery tab, the shape tool on the canvas (select,
move, box-select, node edit, cut), the colour sequence pane, the stitch preview window, and the
commands behind them. The engine work is in embroidery.py and the native engine."""

import json
import math
import os

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import embdialogs as ED
from . import embicons  # noqa: F401  (registers the icons)
from . import embroidery as M
from . import engine as E
from . import letters
from .icons import Icon
from .ribbon import big_button, group, make_menu, sep, small_button, _box

# commands that would turn shapes into pixels or change the hoop's scale
BLOCKED = {"resize": "Resize", "rotate_angle": "Rotate", "rot_cw": "Rotate", "rot_ccw": "Rotate", "rot_180": "Rotate",
           "flip_h": "Flip", "flip_v": "Flip", "crop": "Crop", "canvas_resize": "Canvas size", "flatten": "Flatten",
           "properties": "Image properties", "layer_merge": "Merge down"}

HANDLE_PX = 4


def _mm(win, x, y):
    return M.px_to_mm(win.emb.settings(), x, y)


class EmbUI:
    def __init__(self, win):
        self.win = win
        self.sel_layer = None        # layer id holding the selected objects
        self.sel = []                # selected object ids
        self.mode = "select"         # select | nodes | cut
        self.drag = None
        self.cut_line = None
        self.marquee = None
        self.last_trace = None
        self._plan = None
        self._plan_key = None
        self._settings_cache = (None, None)
        self.preview = None
        self.pane = ColourPane(self)
        self.pane.set_no_show_all(True)

    # ------------------------------------------------------------------ document
    def settings(self):
        doc = self.win.doc
        if doc is None:
            return None
        key = (doc.h, doc.changes)
        if self._settings_cache[0] != key:
            self._settings_cache = (key, M.doc_settings(doc))
        return self._settings_cache[1]

    def active(self):
        return self.settings() is not None

    def on_document(self):
        self._settings_cache = (None, None)
        self.sel = []
        self.sel_layer = None
        self.mode = "select"
        self._plan = None
        self._plan_key = None
        on = self.active()
        rb = self.win.ribbon
        b = rb.tab_buttons.get("embroidery")
        if b is not None:
            if on:
                b.show()
            else:
                if b.get_active():
                    rb.tab_buttons["home"].set_active(True)
                b.hide()
        if on:
            if self.win.state.view.get("colours", True):
                self.show_pane()
            self.pane.refresh_soon()
        else:
            self.pane.hide()
        if self.preview is not None:
            self.preview.destroy()
            self.preview = None
        if on and self.win.state.tool not in ("emb",):
            self.win.state.tool = "emb"

    def ensure_paint_layer(self):
        """Painting tools never paint on a shape layer (that would turn its shapes into
        pixels): a drawing layer above it takes the paint."""
        doc = self.win.doc
        if M.is_shape_layer(doc, doc.active):
            doc.layer_add("Drawing")
            self.win.layers.rebuild()
            self.win.hint("Drawing goes on a layer of its own. Convert to Shapes turns it into shapes.", 7)

    def cursor(self, x, y):
        if self.mode == "cut":
            return "crosshair"
        mx, my = M.px_to_mm(self.settings(), x, y)
        i, sp, objs = self.selected()
        if self.mode == "nodes" and len(objs) == 1:
            return "crosshair"
        li, o = self.hit(mx, my)
        if o is not None:
            return "move" if o.get("id") in self.sel else "pointer"
        return "default"

    def show_pane(self):
        # show_all does nothing on a no-show-all widget: lift it for the moment
        self.pane.set_no_show_all(False)
        self.pane.show_all()
        self.pane.set_no_show_all(True)

    def plan(self):
        """The stitch plan of the visible shape layers (cached until the next change)."""
        doc = self.win.doc
        key = (doc.h, doc.changes, tuple(doc.layer_props(i)["visible"] for i in range(doc.layer_count())))
        if self._plan_key != key or self._plan is None:
            self._plan = M.Plan.make(M.design_json(doc, self.settings()))
            self._plan_key = key
        return self._plan

    def changed(self, label=None):
        """After a shape edit: refresh everything that shows the design."""
        win = self.win
        if label:
            win._action = label
        win.canvas.sync()
        win.layers.rebuild()
        win.after_edit()
        self.pane.refresh_soon()
        if self.preview is not None:
            self.preview.refresh()
        self.refresh_ribbon()

    # ------------------------------------------------------------------ layers and objects
    def layer_index(self, lid):
        doc = self.win.doc
        for i in range(doc.layer_count()):
            if doc.layer_props(i)["id"] == lid:
                return i
        return None

    def spec(self, i):
        return M.layer_spec(self.win.doc, i)

    def store(self, i, spec, label=None):
        spec["edited"] = True
        M.store_layer(self.win.doc, i, spec, self.settings())
        if label:
            self.win.doc.label_last(label)

    def selected(self):
        """(layer index, spec, [objects]) of the selection, or (None, None, [])."""
        if self.sel_layer is None or not self.sel:
            return None, None, []
        i = self.layer_index(self.sel_layer)
        if i is None:
            return None, None, []
        sp = self.spec(i)
        if not sp:
            return None, None, []
        objs = [o for o in sp.get("objects", []) if o.get("id") in self.sel]
        return i, sp, objs

    def target_layer(self, name="Shapes"):
        """The shape layer new work goes on: the active one if it is a shape layer, else a new one."""
        doc = self.win.doc
        if M.is_shape_layer(doc, doc.active):
            return doc.active
        i = M.add_shape_layer(doc, name, {"objects": [], "next_id": 1}, self.settings())
        return i

    def hit(self, mx, my):
        """The topmost object under the point: (layer index, object) or (None, None)."""
        doc = self.win.doc
        for i in range(doc.layer_count() - 1, -1, -1):
            if not doc.layer_props(i)["visible"]:
                continue
            sp = self.spec(i)
            if not sp or sp.get("kind") != M.SHAPES_KIND:
                continue
            for o in reversed(sp.get("objects", [])):
                if M.object_at(o, mx, my, tol=max(0.3, 4 / (self.win.canvas.z * M.PX_PER_MM))):
                    return i, o
        return None, None

    # ------------------------------------------------------------------ canvas drawing
    def draw_under(self, cr, ox, oy, z):
        s = self.settings()
        doc = self.win.doc
        r, g, b = [v / 255 for v in s.get("fabric", [244, 239, 226])]
        cr.set_source_rgb(r, g, b)
        cr.rectangle(ox, oy, doc.width * z, doc.height * z)
        cr.fill()

    def draw_over(self, cr):
        cv = self.win.canvas
        s = self.settings()
        z = cv.z * M.PX_PER_MM          # screen px per mm
        hw, hh = M.hoop_mm(s)
        ox, oy = cv.to_screen(0, 0)
        cx, cy = ox + hw / 2 * z, oy + hh / 2 * z
        cr.save()
        # 10 mm grid
        if self.win.state.view.get("grid"):
            cr.set_line_width(1)
            cr.set_source_rgba(0.35, 0.35, 0.35, 0.22)
            k = 0
            while k * 10 <= hw / 2:
                for sgn in (1, -1):
                    x = math.floor(cx + sgn * k * 10 * z) + 0.5
                    cr.move_to(x, oy)
                    cr.line_to(x, oy + hh * z)
                k += 1
            k = 0
            while k * 10 <= hh / 2:
                for sgn in (1, -1):
                    y = math.floor(cy + sgn * k * 10 * z) + 0.5
                    cr.move_to(ox, y)
                    cr.line_to(ox + hw * z, y)
                k += 1
            cr.stroke()
        # the hoop: its sewing field with rounded corners, and the centre marks
        rr = min(hw, hh) * 0.08 * z
        x0, y0, x1, y1 = ox + 1.5, oy + 1.5, ox + hw * z - 1.5, oy + hh * z - 1.5
        cr.new_sub_path()
        cr.arc(x1 - rr, y0 + rr, rr, -math.pi / 2, 0)
        cr.arc(x1 - rr, y1 - rr, rr, 0, math.pi / 2)
        cr.arc(x0 + rr, y1 - rr, rr, math.pi / 2, math.pi)
        cr.arc(x0 + rr, y0 + rr, rr, math.pi, 1.5 * math.pi)
        cr.close_path()
        cr.set_source_rgba(0.35, 0.33, 0.33, 0.8)
        cr.set_line_width(2)
        cr.stroke()
        cr.set_line_width(1)
        cr.set_source_rgba(0.5, 0.0, 0.0, 0.7)
        for d in (-1, 1):
            cr.move_to(cx + d * 3 * z, cy + 0.5)
            cr.line_to(cx + d * 6 * z, cy + 0.5)
            cr.move_to(cx + 0.5, cy + d * 3 * z)
            cr.line_to(cx + 0.5, cy + d * 6 * z)
        cr.stroke()
        # selection
        i, sp, objs = self.selected()
        dx, dy = (0.0, 0.0)
        if self.drag and self.drag.get("kind") == "move":
            dx, dy = self.drag.get("dmm", (0.0, 0.0))

        def scr(x, y):
            return cv.to_screen(*M.mm_to_px(s, x, y))
        for o in objs:
            cr.set_source_rgba(0.5, 0.0, 0.0, 0.95)
            cr.set_line_width(1.5)
            cr.set_dash([4, 3])
            for rings in M.object_shapes(o):
                for ring in rings:
                    for k, (x, y) in enumerate(ring):
                        X, Y = scr(x + dx, y + dy)
                        (cr.move_to if k == 0 else cr.line_to)(X, Y)
                    cr.close_path()
            cr.stroke()
            cr.set_dash([])
            b = M.object_bounds(o)
            X0, Y0 = scr(b[0] + dx, b[1] + dy)
            X1, Y1 = scr(b[2] + dx, b[3] + dy)
            cr.set_source_rgba(0.5, 0, 0, 0.6)
            cr.set_line_width(1)
            cr.rectangle(math.floor(X0) + 0.5, math.floor(Y0) + 0.5, X1 - X0, Y1 - Y0)
            cr.stroke()
            if self.mode == "nodes" and o.get("rings") and len(objs) == 1:
                for ring in o["rings"]:
                    for x, y in ring:
                        X, Y = scr(x, y)
                        cr.rectangle(X - HANDLE_PX, Y - HANDLE_PX, 2 * HANDLE_PX, 2 * HANDLE_PX)
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgb(0.5, 0, 0)
                cr.stroke()
        if self.marquee:
            (ax, ay), (bx, by) = self.marquee
            A, B = scr(ax, ay), scr(bx, by)
            cr.set_source_rgba(0.5, 0, 0, 0.12)
            cr.rectangle(min(A[0], B[0]), min(A[1], B[1]), abs(B[0] - A[0]), abs(B[1] - A[1]))
            cr.fill_preserve()
            cr.set_source_rgba(0.5, 0, 0, 0.8)
            cr.set_dash([4, 3])
            cr.stroke()
            cr.set_dash([])
        if self.cut_line:
            cr.set_source_rgba(0.8, 0.1, 0.1, 0.9)
            cr.set_line_width(1.5)
            for k, (x, y) in enumerate(self.cut_line):
                X, Y = scr(x, y)
                (cr.move_to if k == 0 else cr.line_to)(X, Y)
            cr.stroke()
        cr.restore()

    # ------------------------------------------------------------------ shape tool
    def press(self, ev, x, y, shift, ctrl):
        mx, my = _mm(self.win, x, y)
        dbl = ev.type == Gdk.EventType._2BUTTON_PRESS
        if ev.button == 3:
            li, o = self.hit(mx, my)
            if o is not None and o.get("id") not in self.sel:
                self.select(li, [o["id"]])
            self.context_menu(ev)
            return
        if self.mode == "cut":
            self.cut_line = [(mx, my), (mx, my)]
            self.drag = {"kind": "cut"}
            return
        i, sp, objs = self.selected()
        if self.mode == "nodes" and len(objs) == 1 and objs[0].get("rings"):
            cv = self.win.canvas
            s = self.settings()
            for ri, ring in enumerate(objs[0]["rings"]):
                for vi, (vx, vy) in enumerate(ring):
                    X, Y = cv.to_screen(*M.mm_to_px(s, vx, vy))
                    if abs(X - ev.x) <= HANDLE_PX + 2 and abs(Y - ev.y) <= HANDLE_PX + 2:
                        self.drag = {"kind": "node", "ring": ri, "vertex": vi, "start": (mx, my)}
                        return
        li, o = self.hit(mx, my)
        if o is None:
            if not shift:
                self.select(None, [])
            self.drag = {"kind": "marquee", "start": (mx, my), "add": shift}
            self.marquee = ((mx, my), (mx, my))
            return
        lid = self.win.doc.layer_props(li)["id"]
        if dbl and o.get("kind") == "lettering":
            self.select(li, [o["id"]])
            self.c_emb_lettering_edit()
            return
        if shift and lid == self.sel_layer:
            ids = list(self.sel)
            if o["id"] in ids:
                ids.remove(o["id"])
            else:
                ids.append(o["id"])
            self.select(li, ids)
        elif o["id"] not in self.sel or lid != self.sel_layer:
            self.select(li, [o["id"]])
        self.drag = {"kind": "move", "start": (mx, my), "dmm": (0.0, 0.0)}

    def motion(self, ev, x, y):
        if not self.drag:
            return
        mx, my = _mm(self.win, x, y)
        k = self.drag["kind"]
        if k == "move":
            sx, sy = self.drag["start"]
            self.drag["dmm"] = (mx - sx, my - sy)
        elif k == "marquee":
            self.marquee = (self.drag["start"], (mx, my))
        elif k == "node":
            self.drag["at"] = (mx, my)
            i, sp, objs = self.selected()
            if objs:
                r = objs[0]["rings"][self.drag["ring"]]
                r[self.drag["vertex"]] = [mx, my]
        elif k == "cut":
            self.cut_line[-1] = (mx, my)
        self.win.canvas.area.queue_draw()

    def release(self, ev, x, y):
        d = self.drag
        self.drag = None
        if not d:
            return
        k = d["kind"]
        if k == "move":
            dx, dy = d.get("dmm", (0, 0))
            if abs(dx) > 1e-3 or abs(dy) > 1e-3:
                self.move_selection(dx, dy)
        elif k == "marquee":
            (ax, ay), (bx, by) = self.marquee
            self.marquee = None
            if abs(bx - ax) > 0.2 or abs(by - ay) > 0.2:
                self.box_select(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), add=d.get("add"))
        elif k == "node":
            i, sp, objs = self.selected()
            if i is not None and "at" in d:
                self.store(i, sp, "Edit nodes")
                self.changed("Edit nodes")
        elif k == "cut":
            line = self.cut_line
            self.cut_line = None
            self.mode = "select"
            if line and math.hypot(line[1][0] - line[0][0], line[1][1] - line[0][1]) > 0.5:
                self.split_with_line(line)
        self.win.canvas.area.queue_draw()
        self.refresh_ribbon()

    def key(self, name, shift):
        if not self.active() or self.win.state.tool != "emb":
            return False
        if name in ("Delete", "BackSpace") and self.sel:
            self.c_emb_delete()
            return True
        if name == "Escape":
            if self.mode != "select" or self.sel:
                self.mode = "select"
                self.cut_line = None
                self.select(None, [])
                return True
            return False
        step = 1.0 if shift else 0.1
        moves = {"Left": (-step, 0), "Right": (step, 0), "Up": (0, -step), "Down": (0, step)}
        if name in moves and self.sel:
            self.move_selection(*moves[name])
            return True
        return False

    def select(self, li, ids):
        if li is None or not ids:
            self.sel = []
            self.sel_layer = None
        else:
            self.sel_layer = self.win.doc.layer_props(li)["id"]
            self.sel = list(ids)
            if self.win.doc.active != li:
                self.win.doc.set_active(li)
                self.win.layers.rebuild()
        self.win.canvas.area.queue_draw()
        self.refresh_ribbon()
        n = len(self.sel)
        if n:
            i, sp, objs = self.selected()
            if n == 1 and objs:
                o = objs[0]
                if o.get("kind") == "stitches":
                    what = "Imported design"
                elif o.get("kind") == "lettering":
                    what = "Lettering “%s”" % o.get("text", "")
                else:
                    what = "Shape"
                self.win.hint("%s · %s" % (what, M.thread_label(o.get("thread") or (o.get("blocks") or [{}])[0].get("thread", {"rgb": [0, 0, 0]}))), 5)
            else:
                self.win.hint("%d objects selected" % n, 4)

    def box_select(self, x0, y0, x1, y1, add=False):
        """Select every object lying wholly inside the box (on the active shape layer, or the
        topmost layer that has any)."""
        doc = self.win.doc
        order = [doc.active] + [i for i in range(doc.layer_count() - 1, -1, -1) if i != doc.active]
        for li in order:
            sp = self.spec(li)
            if not sp or sp.get("kind") != M.SHAPES_KIND or not doc.layer_props(li)["visible"]:
                continue
            ids = []
            for o in sp.get("objects", []):
                b = M.object_bounds(o)
                if b[0] >= x0 and b[1] >= y0 and b[2] <= x1 and b[3] <= y1:
                    ids.append(o["id"])
            if ids:
                lid = doc.layer_props(li)["id"]
                if add and lid == self.sel_layer:
                    ids = list(dict.fromkeys(self.sel + ids))
                self.select(li, ids)
                return len(ids)
        return 0

    def move_selection(self, dx, dy):
        i, sp, objs = self.selected()
        if not objs:
            return
        for o in objs:
            M.move_object(o, dx, dy)
        self.store(i, sp, "Move shapes")
        self.changed("Move shapes")

    def context_menu(self, ev):
        items = [("Stitch properties…", "stitchtype", lambda: self.win.cmd("emb_stitch")),
                 ("Thread…", "spool", lambda: self.win.cmd("emb_recolour")),
                 None,
                 ("Merge", "union", lambda: self.win.cmd("emb_merge")),
                 ("Split", "split", lambda: self.win.cmd("emb_split")),
                 ("Edit nodes", "nodes", lambda: self.win.cmd("emb_nodes")),
                 None,
                 ("Sew earlier", "backward", lambda: self.win.cmd("emb_order", -1)),
                 ("Sew later", "forward", lambda: self.win.cmd("emb_order", 1)),
                 None,
                 ("Delete", "delete", lambda: self.win.cmd("emb_delete"))]
        m = make_menu(items)
        m.attach_to_widget(self.win.canvas.area, None)
        m.popup_at_pointer(ev)

    # ------------------------------------------------------------------ ribbon
    def build_tab(self):
        w = self.win
        row = _box(False, 2)
        self.buttons = {}

        def big(key, icon, label, tip, cmd, *args):
            b = big_button(icon, label, tip)
            b.connect("clicked", lambda *_: w.cmd(cmd, *args))
            self.buttons[key] = b
            return b

        def small(key, icon, label, tip, cmd, *args):
            b = small_button(icon, label, tip)
            b.connect("clicked", lambda *_: w.cmd(cmd, *args))
            self.buttons[key] = b
            return b
        pic = _box(False, 2)
        pic.pack_start(big("place", "place", "Place Picture", "Place a picture on the hoop, fitted to it (Ctrl+Shift+P)", "emb_place"), False, False, 0)
        pic.pack_start(big("trace", "trace", "Convert to Shapes",
                           "Turn the picture (or what you drew) on the active layer into editable shapes, one per colour region", "emb_trace"), False, False, 0)
        row.pack_start(group("Picture", pic), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        sh = _box(False, 2)
        sh.pack_start(big("tool", "shapetool", "Select", "Select, move and box-select shapes (S)", "emb_tool"), False, False, 0)
        col = _box(True, 0)
        col.pack_start(small("nodes", "nodes", "Edit Nodes", "Drag the corners of the selected shape", "emb_nodes"), False, False, 0)
        col.pack_start(small("merge", "union", "Merge", "Join the selected shapes into one", "emb_merge"), False, False, 0)
        col.pack_start(small("split", "split", "Split", "Split the selected shape into its separate parts, or along a line you draw", "emb_split"), False, False, 0)
        sh.pack_start(col, False, False, 0)
        col = _box(True, 0)
        col.pack_start(small("recolour", "spool", "Thread", "Change the thread of the selected shapes", "emb_recolour"), False, False, 0)
        col.pack_start(small("delete", "delete", "Delete", "Delete the selected shapes (Delete)", "emb_delete"), False, False, 0)
        order = _box(False, 0)
        order.pack_start(small("earlier", "backward", None, "Sew earlier", "emb_order", -1), False, False, 0)
        order.pack_start(small("later", "forward", None, "Sew later", "emb_order", 1), False, False, 0)
        col.pack_start(order, False, False, 0)
        sh.pack_start(col, False, False, 0)
        row.pack_start(group("Shapes", sh), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        stb = _box(False, 2)
        menu = make_menu([(lab, None, (lambda k=k: w.cmd("emb_set_type", k))) for k, lab in ED.TYPES])
        b = big_button("stitchtype", "Stitch Type", "Automatic, fill, satin or running stitch for the selected shapes", menu=menu)
        self.buttons["type"] = b
        stb.pack_start(b, False, False, 0)
        col = _box(True, 0)
        col.pack_start(small("stitch", "props", "Properties", "Angle, density, underlay and pull compensation", "emb_stitch"), False, False, 0)
        col.pack_start(small("stop", "stopsign", "Stop After", "Stop the machine after the selected shapes", "emb_stop"), False, False, 0)
        stb.pack_start(col, False, False, 0)
        row.pack_start(group("Stitches", stb), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        lt = _box(False, 2)
        lt.pack_start(big("lettering", "lettering", "Lettering", "Add lettering from your installed fonts, straight or on an arc", "emb_lettering"), False, False, 0)
        row.pack_start(group("Text", lt), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        ds = _box(False, 2)
        ds.pack_start(big("preview", "preview", "Preview", "See the stitches: thread view, stitch lines, density and the stitch-out", "emb_preview"), False, False, 0)
        col = _box(True, 0)
        col.pack_start(small("colours", "colourseq", "Colours", "Show or hide the colour sequence", "emb_colours"), False, False, 0)
        col.pack_start(small("hoop", "hoop", "Hoop", "Hoop, machine, fabric and stitching settings", "emb_hoop"), False, False, 0)
        col.pack_start(small("import", "embimport", "Import", "Add a PES or DST design as stitches", "emb_import"), False, False, 0)
        ds.pack_start(col, False, False, 0)
        col = _box(True, 0)
        col.pack_start(small("export", "embexport", "Export", "Save the stitches as PES (Artspira, Brother) or DST (Ctrl+E)", "emb_export"), False, False, 0)
        col.pack_start(small("template", "template", "Template", "Print a 1:1 template with the hoop, centre marks and thread list", "emb_template"), False, False, 0)
        col.pack_start(small("mirror", "mirror", "Mirror", "Mirror the selected imported design", "emb_mirror"), False, False, 0)
        ds.pack_start(col, False, False, 0)
        row.pack_start(group("Design", ds), False, False, 2)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        row.pack_start(self.status, False, False, 8)
        return row

    def refresh_ribbon(self):
        if not hasattr(self, "buttons"):
            return
        i, sp, objs = self.selected()
        has = bool(objs)
        shapes = [o for o in objs if o.get("kind") not in ("stitches",)]
        for k in ("recolour", "delete", "earlier", "later", "stop"):
            self.buttons[k].set_sensitive(has)
        for k in ("stitch", "type"):
            self.buttons[k].set_sensitive(bool(shapes))
        self.buttons["nodes"].set_sensitive(len(objs) == 1 and bool(objs[0].get("rings")))
        self.buttons["merge"].set_sensitive(len([o for o in objs if o.get("rings")]) >= 2)
        self.buttons["split"].set_sensitive(len(objs) == 1 and bool(objs[0].get("rings")))
        self.buttons["mirror"].set_sensitive(any(o.get("kind") == "stitches" for o in objs))
        self.buttons["tool"].get_style_context().remove_class("fd-on")
        if self.win.state.tool == "emb":
            self.buttons["tool"].get_style_context().add_class("fd-on")

    def update_status(self):
        if not hasattr(self, "status") or not self.active():
            return
        try:
            p = self.plan()
            inf = p.info
            b = inf.get("bounds", [0, 0, 0, 0])
            self.status.set_text("%d stitches · %d colours · %.0f × %.0f mm" % (inf.get("stitches", 0), len(inf.get("blocks", [])),
                                                                                b[2] - b[0], b[3] - b[1]))
        except M.EngineError:
            self.status.set_text("")

    # ------------------------------------------------------------------ commands
    def c_emb_new(self):
        win = self.win
        if not win.confirm_discard():
            return
        s = ED.hoop_settings(win, M.DEFAULT_SETTINGS, new=True)
        if not s:
            return
        self.new_document(s)

    def new_document(self, s):
        win = self.win
        w, h = M.canvas_px(s)
        doc = E.Document.new(w, h, (0, 0, 0, 0))
        doc.layer_set(0, name="Fabric", record=False)
        M.set_doc_settings(doc, s)
        win.set_document(doc, None)
        win.saved_changes = doc.changes
        win.state.tool = "emb"
        win.ribbon.show_tab("embroidery")
        win.ribbon.refresh()
        win.refresh_state()

    def c_emb_hoop(self):
        s = self.settings()
        if s is None:
            return self.c_emb_new()
        n = ED.hoop_settings(self.win, s)
        if not n:
            return
        doc = self.win.doc
        if tuple(n["hoop_mm"]) != tuple(s["hoop_mm"]):
            # a bigger or smaller hoop: the canvas grows or shrinks around the centre; shapes
            # keep their millimetres, so their layers are drawn again
            w, h = M.canvas_px(n)
            doc.canvas_size(w, h, 0.5, 0.5)
            M.set_doc_settings(doc, n)
            for i in M.shape_layers(doc):
                M.store_layer(doc, i, self.spec(i), n)
        else:
            M.set_doc_settings(doc, n)
            for i in M.shape_layers(doc):
                M.store_layer(doc, i, self.spec(i), n)
        self._settings_cache = (None, None)
        self.win.canvas.sync(full=True)
        self.changed("Hoop and machine")

    def c_emb_tool(self):
        self.win.state.tool = "emb"
        self.mode = "select"
        self.win.ribbon.refresh()
        self.refresh_ribbon()

    def c_emb_place(self, path=None):
        win = self.win
        if path is None:
            path = choose_file(win, "Place Picture", ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp", "*.tif", "*.tiff"], "Pictures")
            if not path:
                return
        try:
            src = E.Document.load(path)
        except E.EngineError as e:
            from . import dialogs as D
            D.message(win, "Folio Draw can't open %s" % os.path.basename(path), str(e), Gtk.MessageType.ERROR)
            return
        self.place_rgba(src.flatten_rgba(), src.width, src.height, os.path.basename(path))
        src.close()

    def place_rgba(self, rgba, sw, sh, name="Picture", crop=False):
        win = self.win
        s = self.settings()
        cw, ch = M.canvas_px(s)
        data, info = M.place(rgba, sw, sh, cw, ch, crop=crop)
        doc = win.doc
        doc.layer_add(os.path.splitext(name)[0][:40] or "Picture")
        doc.float_from_rgba(cw, ch, data, 0, 0)
        doc.float_commit()
        spec = {"kind": M.PICTURE_KIND, "upscale": info.get("upscale", 1.0), "source": name, "fitted": bool(crop)}
        if info.get("bg"):
            spec["bg"] = info["bg"]
        doc.text_layer_set(doc.active, M._spec_text(spec), None)
        doc.label_last("Place picture")
        self.changed("Place picture")
        win.hint("Picture placed. Embroidery ▸ Convert to Shapes turns it into shapes.", 8)
        return doc.active

    def c_emb_trace(self, params=None):
        """Convert the active layer's picture into shapes on a new shape layer above it."""
        win = self.win
        doc = win.doc
        li = doc.active
        if M.is_shape_layer(doc, li):
            # converting from a shape layer: use the picture beneath it
            below = [i for i in range(li - 1, -1, -1) if not M.is_shape_layer(doc, i)]
            if not below:
                win.hint("Select the layer with the picture first.", 6)
                return
            li = below[0]
            doc.set_active(li)
        pspec = self.spec(li) or {}
        if params is None:
            params = ED.trace_settings(win, self.last_trace, pspec.get("bg"))
            if params is None:
                return
        self.last_trace = dict(params)
        s = self.settings()
        cw, ch = M.canvas_px(s)
        rgba = doc.layer_rgba(li)
        if not any(rgba[3::4]):
            win.hint("There is nothing on this layer to convert.", 6)
            return
        if params.get("crop") and pspec.get("kind") == M.PICTURE_KIND and not pspec.get("fitted", True):
            # fit the picture to the hoop first (its layer follows, so it still lines up)
            rgba, info = M.place(rgba, cw, ch, cw, ch, crop=True)
            doc.sel_all()
            doc.sel_delete()
            doc.float_from_rgba(cw, ch, rgba, 0, 0)
            doc.float_commit()
            doc.sel_none()
            pspec["upscale"] = pspec.get("upscale", 1.0) * info.get("upscale", 1.0)
            pspec["fitted"] = True
            doc.text_layer_set(li, M._spec_text(pspec), None)
        ox, oy = M.origin(s)
        tp = {"colours": params.get("colours", 0), "background": params.get("background", "remove"),
              "smoothing": params.get("smoothing", 1), "min_area": params.get("min_area", 1.5),
              "edge_radius": params.get("edge_radius", 2), "upscale": pspec.get("upscale", 1.0),
              "threads": s.get("threads", "brother")}
        if params.get("bg"):
            tp["bg"] = params["bg"]
        elif pspec.get("bg"):
            tp["bg"] = pspec["bg"]
        res = M.convert(rgba, cw, ch, ox, oy, tp)
        shapes = res.get("shapes", [])
        if not shapes:
            win.hint("No shapes came out: the picture may be all background.", 8)
            return
        src_id = doc.layer_props(li)["id"]
        # the shape layer made from this picture before
        existing = None
        for i in M.shape_layers(doc):
            sp = self.spec(i)
            if sp.get("source") == src_id:
                existing = i
        group_id = "pic%d" % src_id
        spec = {"kind": M.SHAPES_KIND, "source": src_id, "objects": [], "next_id": 1, "edited": False}
        for sh in shapes:
            o = {"id": M.new_object_id(spec), "rings": sh["rings"], "thread": sh["thread"], "group": group_id}
            spec["objects"].append(o)
        if existing is not None:
            esp = self.spec(existing)
            if esp.get("edited"):
                from . import dialogs as D
                r = D.ask_choice(win, "Replace the shapes you edited?",
                                 "This picture was converted before and its shapes have been changed since. "
                                 "Converting again replaces them.", ["Cancel", "Add as a new layer", "Replace"], default=1)
                if r <= 0:
                    return
                if r == 1:
                    existing = None
            if existing is not None:
                M.store_layer(doc, existing, spec, s)
                spec["edited"] = False
                doc.label_last("Convert to shapes")
                self.select(None, [])
                self.changed("Convert to shapes")
                self._trace_done(spec, li)
                return
        doc.set_active(li)
        M.add_shape_layer(doc, "Shapes", spec, s)
        doc.label_last("Convert to shapes")
        self.select(None, [])
        self.changed("Convert to shapes")
        self._trace_done(spec, li)

    def _trace_done(self, spec, picture_layer):
        n = len(spec["objects"])
        threads = []
        for o in spec["objects"]:
            if o["thread"] not in threads:
                threads.append(o["thread"])
        self.win.state.tool = "emb"
        self.win.ribbon.refresh()
        self.win.hint("%d shapes in %d colours. Hide the picture layer to see them on the fabric." % (n, len(threads)), 10)

    def c_emb_delete(self):
        i, sp, objs = self.selected()
        if not objs:
            return
        ids = {o["id"] for o in objs}
        sp["objects"] = [o for o in sp["objects"] if o["id"] not in ids]
        self.store(i, sp, "Delete shapes")
        self.sel = []
        self.changed("Delete shapes")

    def c_emb_recolour(self, thread=None):
        i, sp, objs = self.selected()
        if not objs:
            return
        if thread is None:
            cur = objs[0].get("thread") or (objs[0].get("blocks") or [{}])[0].get("thread")
            thread = ED.choose_thread(self.win, cur, exact=self.settings().get("threads") == "exact")
            if not thread:
                return
        for o in objs:
            if o.get("kind") == "stitches":
                for b in o.get("blocks", []):
                    b["thread"] = dict(thread)
            else:
                o["thread"] = dict(thread)
        self.store(i, sp, "Thread")
        self.changed("Thread")

    def c_emb_nodes(self):
        i, sp, objs = self.selected()
        if len(objs) != 1 or not objs[0].get("rings"):
            self.win.hint("Select one shape to edit its nodes.", 5)
            return
        self.win.state.tool = "emb"
        self.mode = "select" if self.mode == "nodes" else "nodes"
        self.win.canvas.area.queue_draw()
        if self.mode == "nodes":
            self.win.hint("Drag the corners of the shape. Esc when done.", 6)

    def c_emb_merge(self):
        i, sp, objs = self.selected()
        objs = [o for o in objs if o.get("rings")]
        if len(objs) < 2:
            self.win.hint("Select two or more shapes to merge (Shift+click).", 5)
            return
        res = M.shapes_op({"op": "union", "shapes": [o["rings"] for o in objs]})
        parts = res.get("shapes", [])
        if not parts:
            return
        keep = objs[0]
        ids = {o["id"] for o in objs[1:]}
        # touching shapes become one; parts that stay apart remain separate shapes of the merge
        keep["rings"] = parts[0]
        new = []
        for p in parts[1:]:
            o = dict(keep)
            o["id"] = M.new_object_id(sp)
            o["rings"] = p
            new.append(o)
        out = []
        for o in sp["objects"]:
            if o["id"] in ids:
                continue
            out.append(o)
            if o is keep:
                out.extend(new)
        sp["objects"] = out
        self.store(i, sp, "Merge shapes")
        self.sel = [keep["id"]] + [o["id"] for o in new]
        self.changed("Merge shapes")

    def c_emb_split(self):
        i, sp, objs = self.selected()
        if len(objs) != 1 or not objs[0].get("rings"):
            self.win.hint("Select one shape to split.", 5)
            return
        o = objs[0]
        parts = M.shapes_op({"op": "parts", "rings": o["rings"]}).get("shapes", [])
        if len(parts) > 1:
            self._replace_with_parts(i, sp, o, parts, "Split shape")
            return
        self.mode = "cut"
        self.win.state.tool = "emb"
        self.win.hint("Draw a line across the shape to split it.", 6)

    def split_with_line(self, line):
        i, sp, objs = self.selected()
        if len(objs) != 1 or not objs[0].get("rings"):
            return
        o = objs[0]
        parts = M.shapes_op({"op": "split", "rings": o["rings"], "line": [list(p) for p in line]}).get("shapes", [])
        if len(parts) < 2:
            self.win.hint("The line has to cross the shape from one side to the other.", 6)
            return
        self._replace_with_parts(i, sp, o, parts, "Split shape")

    def _replace_with_parts(self, i, sp, o, parts, label):
        out = []
        new_ids = []
        for q in sp["objects"]:
            if q is not o:
                out.append(q)
                continue
            for k, p in enumerate(parts):
                n = dict(o)
                n["rings"] = p
                n["id"] = o["id"] if k == 0 else M.new_object_id(sp)
                out.append(n)
                new_ids.append(n["id"])
        sp["objects"] = out
        self.store(i, sp, label)
        self.sel = new_ids
        self.changed(label)

    def c_emb_order(self, d):
        i, sp, objs = self.selected()
        if not objs:
            return
        ids = {o["id"] for o in objs}
        lst = sp["objects"]
        idx = [k for k, o in enumerate(lst) if o["id"] in ids]
        if d < 0:
            for k in idx:
                if k > 0 and lst[k - 1]["id"] not in ids:
                    lst[k - 1], lst[k] = lst[k], lst[k - 1]
        else:
            for k in reversed(idx):
                if k + 1 < len(lst) and lst[k + 1]["id"] not in ids:
                    lst[k + 1], lst[k] = lst[k], lst[k + 1]
        # an ordered shape no longer follows the picture's automatic order
        for o in objs:
            o.pop("group", None)
        self.store(i, sp, "Stitch order")
        self.changed("Stitch order")

    def c_emb_set_type(self, kind):
        self.apply_stitch({"type": kind})

    def apply_stitch(self, values):
        i, sp, objs = self.selected()
        objs = [o for o in objs if o.get("kind") != "stitches"]
        if not objs:
            return
        for o in objs:
            st = dict(o.get("stitch") or {})
            for k, v in values.items():
                if k == "stop":
                    o["stop"] = bool(v)
                else:
                    st[k] = v
            o["stitch"] = st
        self.store(i, sp, "Stitch properties")
        self.changed("Stitch properties")

    def c_emb_stitch(self, values=None):
        i, sp, objs = self.selected()
        objs = [o for o in objs if o.get("kind") != "stitches"]
        if not objs:
            self.win.hint("Select the shapes first.", 5)
            return
        if values is None:
            values = ED.stitch_properties(self.win, objs)
            if not values:
                return
        self.apply_stitch(values)

    def c_emb_stop(self):
        i, sp, objs = self.selected()
        if not objs:
            return
        on = not all(o.get("stop") for o in objs)
        for o in objs:
            o["stop"] = on
        self.store(i, sp, "Stop after")
        self.changed("Stop after")
        self.win.hint("The machine stops after %s." % ("these shapes" if on else "nothing here"), 5)

    def c_emb_lettering(self, values=None):
        win = self.win
        if values is None:
            values = ED.lettering(win)
            if not values:
                return
        doc = win.doc
        # lettering goes on a layer of its own above everything, so it covers what is beneath
        top = doc.layer_count() - 1
        if not M.is_shape_layer(doc, top) or not (self.spec(top) or {}).get("lettering"):
            doc.set_active(top)
            M.add_shape_layer(doc, "Lettering", {"objects": [], "next_id": 1, "lettering": True}, self.settings())
            top = doc.layer_count() - 1
        sp = self.spec(top)
        o = {"id": M.new_object_id(sp), "kind": "lettering", "x": values.pop("x", 0.0), "y": values.pop("y", 0.0)}
        o.update({k: v for k, v in values.items() if k != "type"})
        if values.get("type") and values["type"] != "auto":
            o["stitch"] = {"type": values["type"]}
        M.regen_lettering(o)
        sp["objects"].append(o)
        self.store(top, sp, "Lettering")
        self.select(top, [o["id"]])
        self.changed("Lettering")
        return o

    def c_emb_lettering_edit(self, values=None):
        i, sp, objs = self.selected()
        if len(objs) != 1 or objs[0].get("kind") != "lettering":
            return self.c_emb_lettering(values)
        o = objs[0]
        if values is None:
            cur = dict(o)
            cur["type"] = (o.get("stitch") or {}).get("type", "auto")
            values = ED.lettering(self.win, cur)
            if not values:
                return
        o.update({k: v for k, v in values.items() if k != "type"})
        st = dict(o.get("stitch") or {})
        st["type"] = values.get("type", st.get("type", "auto"))
        if st["type"] == "auto":
            st.pop("type")
        o["stitch"] = st
        M.regen_lettering(o)
        self.store(i, sp, "Lettering")
        self.changed("Lettering")

    def c_emb_colours(self, on=None):
        st = self.win.state
        cur = st.view.get("colours", True)
        on = (not cur) if on is None else on
        st.view["colours"] = on
        if on and self.active():
            self.show_pane()
            self.pane.refresh_soon()
        else:
            self.pane.hide()

    def c_emb_preview(self):
        if not self.active():
            return
        if self.preview is None:
            self.preview = PreviewWindow(self)
            self.preview.connect("destroy", lambda *_: setattr(self, "preview", None))
        self.preview.refresh()
        self.preview.present()

    def c_emb_import(self, path=None):
        win = self.win
        if path is None:
            path = choose_file(win, "Import Design", ["*.pes", "*.PES", "*.dst", "*.DST", "*.pec", "*.PEC"], "Embroidery designs")
            if not path:
                return
        try:
            p = M.Plan.read(path)
        except M.EngineError as e:
            from . import dialogs as D
            D.message(win, "Folio Draw can't read %s" % os.path.basename(path), str(e), Gtk.MessageType.ERROR)
            return
        if not self.active():
            s = dict(M.DEFAULT_SETTINGS)
            b = p.info["bounds"]
            # a hoop the design fits in
            for name, w, h in M.HOOPS:
                if max(abs(b[0]), abs(b[2])) * 2 <= w and max(abs(b[1]), abs(b[3])) * 2 <= h:
                    s["hoop"], s["hoop_mm"] = name, [w, h]
                    break
            self.new_document(s)
        blocks = p.blocks_json()
        doc = win.doc
        doc.set_active(doc.layer_count() - 1)
        li = M.add_shape_layer(doc, "Imported design", {"objects": [], "next_id": 1}, self.settings())
        li = doc.layer_count() - 1
        sp = self.spec(li)
        o = {"id": M.new_object_id(sp), "kind": "stitches", "blocks": blocks.get("blocks", []), "transform": {},
             "source": os.path.basename(path)}
        sp["objects"].append(o)
        self.store(li, sp, "Import design")
        self.select(li, [o["id"]])
        self.changed("Import design")
        win.hint("%s: %d stitches, %d colours." % (os.path.basename(path), p.info["stitches"], len(p.info["blocks"])), 8)
        return o

    def c_emb_mirror(self):
        i, sp, objs = self.selected()
        st = [o for o in objs if o.get("kind") == "stitches"]
        if not st:
            return
        for o in st:
            tr = dict(o.get("transform") or {})
            tr["mirror"] = not tr.get("mirror", False)
            o["transform"] = tr
        self.store(i, sp, "Mirror")
        self.changed("Mirror")

    def c_emb_rotate(self, deg=90.0):
        i, sp, objs = self.selected()
        if not objs:
            return
        for o in objs:
            if o.get("kind") == "stitches":
                tr = dict(o.get("transform") or {})
                tr["rotate"] = (tr.get("rotate", 0.0) + deg) % 360
                o["transform"] = tr
            elif o.get("rings"):
                b = M.object_bounds(o)
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                a = math.radians(deg)
                c, s = math.cos(a), math.sin(a)
                o["rings"] = [[[cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c] for x, y in r] for r in o["rings"]]
        self.store(i, sp, "Rotate")
        self.changed("Rotate")

    def c_emb_scale(self, pct=None):
        i, sp, objs = self.selected()
        if not objs:
            return
        if pct is None:
            pct = ED.scale_percent(self.win)
            if pct is None:
                return
        k = pct / 100.0
        if any(o.get("kind") == "stitches" for o in objs) and abs(k - 1) > 0.10:
            from . import dialogs as D
            r = D.ask_choice(self.win, "Scale the stitches by %d %%?" % round(pct),
                             "Imported stitches are scaled, not made again: beyond 10 % they come out too dense or too sparse.",
                             ["Cancel", "Scale anyway"], default=0)
            if r != 1:
                return
        for o in objs:
            b = M.object_bounds(o)
            M.scale_object(o, k, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        self.store(i, sp, "Scale")
        self.changed("Scale")

    def c_emb_export(self, path=None, fmt=None):
        win = self.win
        if not self.active():
            return
        p = self.plan()
        if p.stitches == 0:
            from . import dialogs as D
            D.message(win, "There are no stitches yet", "Place a picture and convert it to shapes, or add lettering, first.")
            return
        if path is None:
            path, fmt = choose_export(win, self.export_name())
            if not path:
                return
        if fmt is None:
            fmt = M.FMT_DST if path.lower().endswith(".dst") else M.FMT_PEC if path.lower().endswith(".pec") else M.FMT_PES
        try:
            p.write(path, fmt, M.safe_name(path))
        except M.EngineError as e:
            from . import dialogs as D
            D.message(win, "The design wasn't saved", str(e), Gtk.MessageType.ERROR)
            return False
        win.hint("Saved %s: %d stitches, %d colours." % (os.path.basename(path), p.stitches, len(p.info["blocks"])), 8)
        return True

    def export_name(self):
        base = os.path.splitext(os.path.basename(self.win.path))[0] if self.win.path else "Design"
        return base + ".pes"

    def c_emb_template(self, path=None):
        win = self.win
        if not self.active():
            return
        if path is None:
            path = choose_save(win, "Print Template", os.path.splitext(self.export_name())[0] + " template.pdf", "*.pdf", "PDF")
            if not path:
                return
        write_template(path, self.plan(), self.settings(), os.path.splitext(os.path.basename(path))[0])
        win.hint("Template saved: print it at 100 % (actual size).", 8)
        try:
            Gtk.show_uri_on_window(win, GLib.filename_to_uri(path, None), Gdk.CURRENT_TIME)
        except Exception:
            pass
        return path

    # ------------------------------------------------------------------ the colour sequence
    def blocks(self):
        try:
            return self.plan().info.get("blocks", [])
        except M.EngineError:
            return []

    def recolour_thread(self, old, new):
        """Every object sewn in thread `old` takes thread `new` (the colour sequence pane)."""
        doc = self.win.doc
        for i in M.shape_layers(doc):
            sp = self.spec(i)
            hit = False
            for o in sp.get("objects", []):
                if o.get("kind") == "stitches":
                    for b in o.get("blocks", []):
                        if same_thread(b["thread"], old):
                            b["thread"] = dict(new)
                            hit = True
                elif same_thread(o.get("thread", {}), old):
                    o["thread"] = dict(new)
                    hit = True
            if hit:
                self.store(i, sp)
        self.changed("Thread")

    def sort_colours(self):
        """Group each layer's shapes by thread (first colour first), so a colour is sewn in one go."""
        doc = self.win.doc
        for i in M.shape_layers(doc):
            sp = self.spec(i)
            objs = sp.get("objects", [])
            order = []
            for o in objs:
                t = json.dumps(o.get("thread"), sort_keys=True)
                if t not in order:
                    order.append(t)
            objs.sort(key=lambda o: order.index(json.dumps(o.get("thread"), sort_keys=True)))
            for o in objs:
                o.pop("group", None) if o.get("kind") == "lettering" else None
            self.store(i, sp)
        self.changed("Sort colours")

    def combine_colours(self):
        """Clear the stops between neighbouring blocks of the same thread."""
        doc = self.win.doc
        for i in M.shape_layers(doc):
            sp = self.spec(i)
            for o in sp.get("objects", []):
                o["stop"] = False
            self.store(i, sp)
        self.changed("Combine colours")

    def stop_after_block(self, bi, on=True):
        """Stop after colour block bi: the stop goes on that block's last object."""
        info = self.blocks()
        if not (0 <= bi < len(info)):
            return
        t = info[bi]["thread"]
        # the last object of this thread in stitch order up to this block
        doc = self.win.doc
        seen = -1
        last = None
        prev = None
        for i in M.shape_layers(doc):
            sp = self.spec(i)
            for o in sp.get("objects", []):
                th = o.get("thread")
                if th is None:
                    continue
                if prev is None or not same_thread(prev, th):
                    seen += 1
                prev = th
                if seen == bi and same_thread(th, t):
                    last = (i, o["id"])
        if last is None:
            return
        i, oid = last
        sp = self.spec(i)
        for o in sp["objects"]:
            if o["id"] == oid:
                o["stop"] = on
        self.store(i, sp, "Stop after")
        self.changed("Stop after")


def same_thread(a, b):
    if not a or not b:
        return False
    if a.get("pec") and b.get("pec"):
        return a["pec"] == b["pec"] and list(a.get("rgb", [])) == list(b.get("rgb", []))
    return list(a.get("rgb", [])) == list(b.get("rgb", []))


# --------------------------------------------------------------------------- file choosers

def choose_file(win, title, patterns, label):
    d = Gtk.FileChooserDialog(title=title, transient_for=win, action=Gtk.FileChooserAction.OPEN)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("Open", Gtk.ResponseType.OK).get_style_context().add_class("fd-primary")
    f = Gtk.FileFilter()
    f.set_name(label)
    for p in patterns:
        f.add_pattern(p)
    d.add_filter(f)
    r = d.run()
    path = d.get_filename() if r == Gtk.ResponseType.OK else None
    d.destroy()
    return path


def choose_save(win, title, name, pattern, label):
    d = Gtk.FileChooserDialog(title=title, transient_for=win, action=Gtk.FileChooserAction.SAVE)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("Save", Gtk.ResponseType.OK).get_style_context().add_class("fd-primary")
    d.set_do_overwrite_confirmation(True)
    d.set_current_name(name)
    f = Gtk.FileFilter()
    f.set_name(label)
    f.add_pattern(pattern)
    d.add_filter(f)
    r = d.run()
    path = d.get_filename() if r == Gtk.ResponseType.OK else None
    d.destroy()
    return path


def choose_export(win, name):
    d = Gtk.FileChooserDialog(title="Export Embroidery", transient_for=win, action=Gtk.FileChooserAction.SAVE)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("Export", Gtk.ResponseType.OK).get_style_context().add_class("fd-primary")
    d.set_do_overwrite_confirmation(True)
    d.set_current_name(name)
    filters = {}
    for label, pat, fmt in (("PES — Brother, Artspira (*.pes)", "*.pes", M.FMT_PES), ("DST — Tajima (*.dst)", "*.dst", M.FMT_DST),
                            ("PEC — Brother (*.pec)", "*.pec", M.FMT_PEC)):
        f = Gtk.FileFilter()
        f.set_name(label)
        f.add_pattern(pat)
        f.add_pattern(pat.upper())
        d.add_filter(f)
        filters[f] = (pat[1:], fmt)

    def changed(*_):
        f = d.get_filter()
        if f in filters:
            ext = filters[f][0]
            n = d.get_current_name() or name
            d.set_current_name(os.path.splitext(n)[0] + ext)
    d.connect("notify::filter", changed)
    r = d.run()
    path, fmt = None, None
    if r == Gtk.ResponseType.OK:
        path = d.get_filename()
        ext, fmt = filters.get(d.get_filter(), (".pes", M.FMT_PES))
        low = path.lower()
        if low.endswith(".dst"):
            fmt = M.FMT_DST
        elif low.endswith(".pec"):
            fmt = M.FMT_PEC
        elif low.endswith(".pes"):
            fmt = M.FMT_PES
        else:
            path += ext
    d.destroy()
    return path, fmt


# --------------------------------------------------------------------------- print template

def write_template(path, plan, settings, title):
    """A 1:1 PDF: the hoop's sewing field, centre crosshairs, the design as stitch lines and the
    thread list in sewing order."""
    hw, hh = M.hoop_mm(settings)
    pt = 72.0 / 25.4
    # A4 portrait, or bigger when the hoop needs it
    pw, ph = max(210.0, hw + 30), max(297.0, hh + 90)
    surf = cairo.PDFSurface(path, pw * pt, ph * pt)
    cr = cairo.Context(surf)
    cr.scale(pt, pt)
    cx, cy = pw / 2, 15 + hh / 2
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(0.3)
    rr = min(hw, hh) * 0.08
    x0, y0, x1, y1 = cx - hw / 2, cy - hh / 2, cx + hw / 2, cy + hh / 2
    cr.new_sub_path()
    cr.arc(x1 - rr, y0 + rr, rr, -math.pi / 2, 0)
    cr.arc(x1 - rr, y1 - rr, rr, 0, math.pi / 2)
    cr.arc(x0 + rr, y1 - rr, rr, math.pi / 2, math.pi)
    cr.arc(x0 + rr, y0 + rr, rr, math.pi, 1.5 * math.pi)
    cr.close_path()
    cr.stroke()
    # centre crosshairs across the whole field
    cr.set_line_width(0.2)
    cr.set_dash([2, 1])
    cr.move_to(x0, cy)
    cr.line_to(x1, cy)
    cr.move_to(cx, y0)
    cr.line_to(cx, y1)
    cr.stroke()
    cr.set_dash([])
    cr.save()
    cr.translate(cx, cy)
    _template_stitches(cr, plan)
    cr.restore()
    # 10 mm scale bar to check the print size
    cr.set_line_width(0.4)
    cr.move_to(x0, y1 + 6)
    cr.line_to(x0 + 50, y1 + 6)
    for k in range(6):
        cr.move_to(x0 + 10 * k, y1 + 4.5)
        cr.line_to(x0 + 10 * k, y1 + 7.5)
    cr.stroke()
    cr.select_font_face("Sans", 0, 0)
    cr.set_font_size(3.2)
    cr.move_to(x0 + 52, y1 + 7)
    cr.show_text("50 mm — check this with a ruler; print at 100 %")
    cr.set_font_size(5)
    cr.move_to(x0, y1 + 17)
    cr.show_text(title)
    inf = plan.info
    b = inf.get("bounds", [0, 0, 0, 0])
    cr.set_font_size(3.5)
    cr.move_to(x0, y1 + 23)
    cr.show_text("%s · %.1f × %.1f mm · %d stitches · %d colours" % (settings.get("hoop", ""), b[2] - b[0], b[3] - b[1],
                                                                      inf.get("stitches", 0), len(inf.get("blocks", []))))
    y = y1 + 31
    for k, bl in enumerate(inf.get("blocks", []), start=1):
        r, g, bb = [v / 255 for v in bl["thread"]["rgb"]]
        cr.set_source_rgb(r, g, bb)
        cr.rectangle(x0, y - 3, 6, 4)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(0.2)
        cr.stroke()
        cr.move_to(x0 + 9, y)
        cr.show_text("%d. %s — %d stitches%s" % (k, M.thread_label(bl["thread"]), bl["stitches"], " · stop" if bl.get("stop") else ""))
        y += 6
        if y > ph - 10:
            surf.show_page()
            y = 15
    surf.finish()


def _template_stitches(cr, plan):
    cr.set_line_width(0.15)
    last = None
    cur_block = -1
    for x, y, c, bi in plan.cmds():
        if bi != cur_block:
            cr.stroke()
            cur_block = bi
            t = plan.info["blocks"][bi]["thread"]["rgb"]
            # light colours print grey so they show on paper
            lum = 0.3 * t[0] + 0.59 * t[1] + 0.11 * t[2]
            if lum > 200:
                cr.set_source_rgb(0.6, 0.6, 0.6)
            else:
                cr.set_source_rgb(t[0] / 255, t[1] / 255, t[2] / 255)
            last = None
        if c == M.ST and last is not None:
            cr.move_to(*last)
            cr.line_to(x, y)
        last = (x, y)
    cr.stroke()


# --------------------------------------------------------------------------- colour pane

class ColourPane(Gtk.Box):
    """The colour sequence: one row per colour block in sewing order."""

    def __init__(self, ui):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.ui = ui
        self.get_style_context().add_class("fd-panel")
        self.set_size_request(220, 160)
        head = Gtk.Box(spacing=4)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>Colour sequence</b>")
        head.pack_start(lbl, True, True, 4)
        self.pack_start(head, False, False, 2)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._activated)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.add(self.list)
        sc.set_min_content_height(120)
        self.pack_start(sc, True, True, 0)
        bar = Gtk.Box(spacing=0)
        for icon, tip, fn in (("sortcol", "Sort colours: each layer's shapes grouped by thread", lambda: ui.sort_colours()),
                              ("union", "Combine: no stops between blocks of the same thread", lambda: ui.combine_colours()),
                              ("stopsign", "Stop after the selected colour", self._stop),
                              ("spool", "Change the selected colour's thread (or double-click it)", self._change)):
            b = Gtk.Button()
            b.add(Icon(icon, 16))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_a, f=fn: f())
            bar.pack_start(b, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.rows = []
        self._pending = None

    def refresh_soon(self):
        if self._pending is None:
            self._pending = GLib.idle_add(self._refresh_idle)

    def _refresh_idle(self):
        self._pending = None
        self.refresh()
        return False

    def refresh(self):
        for ch in self.list.get_children():
            self.list.remove(ch)
        self.rows = []
        if not self.ui.active():
            return
        blocks = self.ui.blocks()
        for k, b in enumerate(blocks):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=6)
            da = Gtk.DrawingArea()
            da.set_size_request(18, 14)
            rgb = b["thread"]["rgb"]

            def draw(w, cr, rgb=rgb):
                cr.set_source_rgb(*[v / 255 for v in rgb])
                cr.rectangle(1, 1, 16, 12)
                cr.fill_preserve()
                cr.set_source_rgb(0.5, 0.5, 0.5)
                cr.set_line_width(1)
                cr.stroke()
            da.connect("draw", draw)
            box.pack_start(da, False, False, 4)
            lb = Gtk.Label(xalign=0)
            lb.set_text("%d. %s" % (k + 1, M.thread_label(b["thread"])))
            lb.set_ellipsize(3)
            box.pack_start(lb, True, True, 0)
            info = Gtk.Label(label="%d%s" % (b["stitches"], "  ■" if b.get("stop") else ""))
            info.get_style_context().add_class("dim-label")
            info.set_tooltip_text("stitches" + (" — the machine stops after this colour" if b.get("stop") else ""))
            box.pack_end(info, False, False, 4)
            row.add(box)
            row.block = k
            row.thread = b["thread"]
            self.list.add(row)
            self.rows.append(row)
        self.list.show_all()
        self.ui.update_status()

    def _current(self):
        r = self.list.get_selected_row()
        return r

    def _activated(self, lb, row):
        self.change_row(row)

    def change_row(self, row, thread=None):
        if thread is None:
            thread = ED.choose_thread(self.ui.win, row.thread, exact=self.ui.settings().get("threads") == "exact")
            if not thread:
                return
        self.ui.recolour_thread(row.thread, thread)

    def _change(self):
        r = self._current()
        if r is not None:
            self.change_row(r)

    def _stop(self):
        r = self._current()
        if r is not None:
            self.ui.stop_after_block(r.block, True)


# --------------------------------------------------------------------------- preview window

class PreviewWindow(Gtk.Window):
    """The stitches as they will come out: thread view on the fabric, stitch lines with jumps
    and trims, density map, and the stitch-out simulator."""

    def __init__(self, ui):
        super().__init__(title="Embroidery Preview")
        self.ui = ui
        self.set_transient_for(ui.win)
        self.set_default_size(760, 720)
        self.mode = "real"
        self.upto = None
        self.playing = False
        self._timer = None
        self.speed = 400          # stitches per minute (the machine's speed)
        self.factor = 10
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        v.set_border_width(6)
        bar = Gtk.Box(spacing=6)
        self.mode_buttons = {}
        first = None
        for key, label in (("real", "Thread"), ("lines", "Stitch lines"), ("density", "Density")):
            b = Gtk.RadioButton.new_with_label_from_widget(first, label)
            first = first or b
            b.set_mode(False)
            b.connect("toggled", self._mode, key)
            self.mode_buttons[key] = b
            bar.pack_start(b, False, False, 0)
        bar.pack_start(Gtk.Label(label="Fabric"), False, False, 8)
        rgb = ui.settings().get("fabric", [244, 239, 226])
        self.fabric = ED._colour_button(rgb)
        self.fabric.connect("color-set", self._fabric)
        bar.pack_start(self.fabric, False, False, 0)
        self.info = Gtk.Label(xalign=1)
        bar.pack_end(self.info, True, True, 0)
        v.pack_start(bar, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_vexpand(True)
        self.area.connect("draw", self._draw)
        v.pack_start(self.area, True, True, 0)
        sim = Gtk.Box(spacing=6)
        self.play = Gtk.Button()
        self.play_icon = Icon("play", 16)
        self.play.add(self.play_icon)
        self.play.set_tooltip_text("Play the stitch-out")
        self.play.connect("clicked", lambda *_: self.toggle_play())
        sim.pack_start(self.play, False, False, 0)
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.slider.set_draw_value(False)
        self.slider.connect("value-changed", self._slide)
        sim.pack_start(self.slider, True, True, 0)
        sim.pack_start(Gtk.Label(label="Speed"), False, False, 0)
        self.speed_combo = Gtk.ComboBoxText()
        for f in (1, 5, 10, 50, 100):
            self.speed_combo.append(str(f), "%d×" % f)
        self.speed_combo.set_active_id("10")
        self.speed_combo.connect("changed", lambda c: setattr(self, "factor", int(c.get_active_id() or 10)))
        sim.pack_start(self.speed_combo, False, False, 0)
        self.time_lbl = Gtk.Label(label="")
        sim.pack_start(self.time_lbl, False, False, 4)
        v.pack_start(sim, False, False, 0)
        self.add(v)
        self.connect("destroy", lambda *_: self._stop_timer())
        self.show_all()

    def refresh(self):
        try:
            self.plan = self.ui.plan()
        except M.EngineError:
            self.plan = None
        n = len(self.plan.cmds()) if self.plan else 0
        self.slider.set_range(0, max(1, n))
        if self.upto is None or self.upto > n:
            self.slider.set_value(n)
        self._density = None
        inf = self.plan.info if self.plan else {}
        b = inf.get("bounds", [0, 0, 0, 0])
        m = M.MACHINES.get(self.ui.settings().get("machine"), {})
        mins = inf.get("stitches", 0) / float(m.get("spm", 400))
        dens = ""
        if self.plan:
            ds = M.density_stats(self.plan, self.ui.settings())
            if ds["covered"]:
                dens = " · %.0f%% at 3 layers, %.0f%% at 4+" % (100.0 * ds["three"] / ds["covered"], 100.0 * ds["four"] / ds["covered"])
        self.info.set_text("%d stitches · %d colours · %d trims · %.0f × %.0f mm · about %d min%s" % (
            inf.get("stitches", 0), len(inf.get("blocks", [])), inf.get("trims", 0), b[2] - b[0], b[3] - b[1], max(1, round(mins)), dens))
        self.area.queue_draw()

    def _mode(self, b, key):
        if b.get_active():
            self.mode = key
            self.area.queue_draw()

    def _fabric(self, b):
        s = dict(self.ui.settings())
        s["fabric"] = ED._rgb_of(b)
        M.set_doc_settings(self.ui.win.doc, s)
        self.ui._settings_cache = (None, None)
        self.ui.win.canvas.area.queue_draw()
        self.area.queue_draw()

    def _slide(self, s):
        n = int(s.get_value())
        total = len(self.plan.cmds()) if self.plan else 0
        self.upto = None if n >= total else n
        mins = n / float(self.speed)
        self.time_lbl.set_text("%d / %d · %d:%02d" % (n, total, int(mins), int((mins % 1) * 60)))
        self.area.queue_draw()

    def toggle_play(self):
        self.playing = not self.playing
        self.play_icon.set_name_icon("stop" if self.playing else "play")
        if self.playing:
            total = len(self.plan.cmds()) if self.plan else 0
            if self.upto is None or self.upto >= total:
                self.slider.set_value(0)
            self._timer = GLib.timeout_add(40, self._tick)
        else:
            self._stop_timer()

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self.playing = False

    def _tick(self):
        if not self.playing or not self.plan:
            return False
        step = max(1, int(self.speed / 60.0 * 0.04 * self.factor))
        total = len(self.plan.cmds())
        v = int(self.slider.get_value()) + step
        self.slider.set_value(min(total, v))
        if v >= total:
            self.toggle_play()
            return False
        return True

    def _draw(self, w, cr):
        aw, ah = w.get_allocated_width(), w.get_allocated_height()
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.paint()
        s = self.ui.settings()
        if not self.plan or s is None:
            return False
        hw, hh = M.hoop_mm(s)
        k = min((aw - 20) / hw, (ah - 20) / hh)
        cr.translate(aw / 2, ah / 2)
        cr.scale(k, k)
        r, g, b = [v / 255 for v in s.get("fabric", [244, 239, 226])]
        cr.set_source_rgb(r, g, b)
        cr.rectangle(-hw / 2, -hh / 2, hw, hh)
        cr.fill()
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.6)
        cr.set_line_width(1.0 / k)
        cr.rectangle(-hw / 2, -hh / 2, hw, hh)
        cr.stroke()
        if self.mode == "density":
            if self._density is None:
                self._density = M.density_surface(self.plan, s, 10.0)
            M.draw_threads(cr, self.plan, k, upto=self.upto, mode="lines")
            cr.save()
            cr.translate(-hw / 2, -hh / 2)
            cr.scale(0.1, 0.1)
            cr.set_source_surface(self._density, 0, 0)
            cr.paint_with_alpha(0.85)
            cr.restore()
        else:
            M.draw_threads(cr, self.plan, k, upto=self.upto, mode=self.mode)
        # the needle in the simulator
        if self.upto is not None and self.plan:
            cm = self.plan.cmds()
            if 0 < self.upto <= len(cm):
                x, y = cm[self.upto - 1][0], cm[self.upto - 1][1]
                cr.set_source_rgb(0.8, 0.0, 0.0)
                cr.arc(x, y, 6.0 / k, 0, 2 * math.pi)
                cr.set_line_width(1.5 / k)
                cr.stroke()
        return False
