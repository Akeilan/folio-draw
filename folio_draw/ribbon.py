"""The ribbon: File menu, Home / View tabs and the contextual Text tab."""

import math

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, PangoCairo  # noqa: E402

from . import shapes
from .icons import INK, Icon

PALETTE = [
    (0, 0, 0, 255), (127, 127, 127, 255), (136, 0, 21, 255), (237, 28, 36, 255), (255, 127, 39, 255),
    (255, 242, 0, 255), (34, 177, 76, 255), (0, 162, 232, 255), (63, 72, 204, 255), (163, 73, 164, 255),
    (255, 255, 255, 255), (195, 195, 195, 255), (185, 122, 87, 255), (255, 174, 201, 255), (255, 201, 14, 255),
    (239, 228, 176, 255), (181, 230, 29, 255), (153, 217, 234, 255), (112, 146, 190, 255), (200, 191, 231, 255),
]

BRUSHES = [
    ("brush", "Brush"),
    ("soft", "Soft brush"),
    ("callig", "Calligraphy brush 1"),
    ("callig2", "Calligraphy brush 2"),
    ("airbrush", "Airbrush"),
    ("marker", "Marker"),
]


def checker(cr, x, y, w, h, s=4):
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.set_source_rgb(0.8, 0.8, 0.8)
    yy = 0
    while yy < h:
        xx = ((yy // s) % 2) * s
        while xx < w:
            cr.rectangle(x + xx, y + yy, s, s)
            xx += 2 * s
        yy += s
    cr.fill()
    cr.restore()


def draw_swatch(cr, x, y, w, h, color):
    if color is None:
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x, y, w, h)
        cr.fill()
    else:
        if color[3] < 255:
            checker(cr, x, y, w, h, max(2, int(w // 4)))
        cr.set_source_rgba(color[0] / 255, color[1] / 255, color[2] / 255, color[3] / 255)
        cr.rectangle(x, y, w, h)
        cr.fill()
    cr.set_source_rgb(0.55, 0.5, 0.5)
    cr.set_line_width(1)
    cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
    cr.stroke()


def shape_painter(kind):
    def paint(cr, size, ink, acc):
        m = 2.5
        cr.set_source_rgb(*ink)
        cr.set_line_width(1.1)
        cr.set_line_join(1)
        if kind == "curve":
            cr.move_to(m, size - m)
            cr.curve_to(size * 0.2, -size * 0.2, size * 0.75, size * 1.3, size - m, m)
            cr.stroke()
            return
        if kind == "polygon":
            pts = [(m, size * 0.4), (size * 0.5, m), (size - m, size * 0.35), (size * 0.75, size - m), (size * 0.25, size - m * 2)]
            closed = True
        else:
            pts, closed = shapes.shape_path(kind, m, m, size - m, size - m)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        if closed:
            cr.close_path()
        cr.stroke()
        if kind == "callout_cloud":
            for b in shapes.cloud_tail_bubbles(m, m, size - m, size - m):
                cr.move_to(*b[0])
                for p in b[1:]:
                    cr.line_to(*p)
                cr.close_path()
                cr.stroke()
    return paint


def brush_painter(kind):
    def paint(cr, size, ink, acc):
        cr.set_source_rgb(*ink)
        pts = [(size * 0.12 + i * size * 0.76 / 20, size * 0.5 + math.sin(i / 20 * math.tau) * size * 0.22) for i in range(21)]
        if kind == "airbrush":
            import random
            rnd = random.Random(3)
            for (x, y) in pts:
                for _ in range(6):
                    a = rnd.random() * math.tau
                    r = rnd.random() * size * 0.09
                    cr.rectangle(x + math.cos(a) * r, y + math.sin(a) * r, 1, 1)
            cr.fill()
            return
        if kind in ("callig", "callig2"):
            d = size * 0.07 * (1 if kind == "callig" else -1)
            for (x, y) in pts:
                cr.move_to(x - d, y + d)
                cr.line_to(x + d, y - d)
            cr.set_line_width(1.3)
            cr.stroke()
            return
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        if kind == "marker":
            cr.set_source_rgba(ink[0], ink[1], ink[2], 0.45)
            cr.set_line_width(size * 0.16)
            cr.set_line_cap(0)
        elif kind == "soft":
            cr.set_source_rgba(ink[0], ink[1], ink[2], 0.35)
            cr.set_line_width(size * 0.18)
            cr.set_line_cap(1)
            cr.stroke_preserve()
            cr.set_source_rgb(*ink)
            cr.set_line_width(size * 0.07)
        else:
            cr.set_line_width(size * 0.1)
            cr.set_line_cap(1)
        cr.stroke()
    return paint


# --------------------------------------------------------------------------- widgets

def _box(vertical=False, spacing=0):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


def big_button(icon, label, tooltip=None, toggle=False, menu=None, painter=None):
    content = _box(True, 1)
    content.pack_start(Icon(icon, 32, painter=painter), False, False, 0)
    lbl = Gtk.Label(label=label + (" ▾" if menu else ""))
    lbl.set_justify(Gtk.Justification.CENTER)
    lbl.set_line_wrap(True)
    lbl.set_max_width_chars(8)
    content.pack_start(lbl, False, False, 0)
    if menu is not None:
        b = Gtk.MenuButton()
        if isinstance(menu, Gtk.Popover):
            b.set_popover(menu)
        else:
            b.set_popup(menu)
    elif toggle:
        b = Gtk.ToggleButton()
    else:
        b = Gtk.Button()
    b.add(content)
    b.get_style_context().add_class("fd-rbtn")
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_valign(Gtk.Align.START)
    if tooltip:
        b.set_tooltip_text(tooltip)
    b.label_widget = lbl
    return b


def small_button(icon, label=None, tooltip=None, toggle=False, menu=None, painter=None, size=16):
    content = _box(False, 4)
    content.pack_start(Icon(icon, size, painter=painter), False, False, 0)
    if label:
        content.pack_start(Gtk.Label(label=label + (" ▾" if menu else "")), False, False, 0)
    elif menu is not None:
        content.pack_start(Gtk.Label(label="▾"), False, False, 0)
    if menu is not None:
        b = Gtk.MenuButton()
        if isinstance(menu, Gtk.Popover):
            b.set_popover(menu)
        else:
            b.set_popup(menu)
    elif toggle:
        b = Gtk.ToggleButton()
    else:
        b = Gtk.Button()
    b.add(content)
    b.get_style_context().add_class("fd-rbtn")
    b.set_relief(Gtk.ReliefStyle.NONE)
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


def group(label, child):
    g = _box(True, 0)
    child.set_vexpand(True)
    g.pack_start(child, True, True, 0)
    lbl = Gtk.Label(label=label)
    lbl.get_style_context().add_class("fd-group-label")
    g.pack_end(lbl, False, False, 1)
    return g


def sep():
    s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    s.get_style_context().add_class("fd-sep")
    return s


def menu_item(label, icon=None, cb=None, accel=None, check=None):
    if check is not None:
        mi = Gtk.CheckMenuItem()
        mi.set_active(check)
    else:
        mi = Gtk.MenuItem()
    row = _box(False, 8)
    if check is None:
        row.pack_start(Icon(icon, 16) if icon else Gtk.Box(width_request=16), False, False, 0)
    row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
    if accel:
        al = Gtk.Label(label=accel)
        al.get_style_context().add_class("dim-label")
        row.pack_end(al, False, False, 0)
    mi.add(row)
    if cb:
        mi.connect("toggled" if check is not None else "activate", lambda *_: cb())
    mi.item_label = label
    return mi


def make_menu(items):
    m = Gtk.Menu()
    for it in items:
        if it is None:
            m.append(Gtk.SeparatorMenuItem())
        elif isinstance(it, Gtk.MenuItem):
            m.append(it)
        else:
            m.append(menu_item(*it))
    m.show_all()
    return m


class Swatch(Gtk.Button):
    def __init__(self, size, color_fn, on_click):
        super().__init__()
        self.color_fn = color_fn
        self.get_style_context().add_class("fd-swatch")
        self.set_relief(Gtk.ReliefStyle.NONE)
        da = Gtk.DrawingArea()
        da.set_size_request(size, size)
        da.connect("draw", lambda w, cr: draw_swatch(cr, 0, 0, w.get_allocated_width(), w.get_allocated_height(), self.color_fn()))
        self.add(da)
        self.da = da
        self.connect("button-press-event", lambda w, e: on_click(e.button) or True)


# --------------------------------------------------------------------------- ribbon

class Ribbon(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.st = win.state
        self._sync = False
        self.tool_buttons = {}
        self.shape_buttons = {}

        # tab strip
        tabs = _box(False, 0)
        tabs.get_style_context().add_class("fd-tabs")
        self.file_btn = Gtk.MenuButton(label="File")
        self.file_btn.get_style_context().add_class("fd-tab")
        self.file_btn.get_style_context().add_class("fd-file")
        self.file_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.file_btn.set_tooltip_text("File (Alt+F)")
        self.file_menu = Gtk.Menu()
        self.file_btn.set_popup(self.file_menu)
        self.file_menu.connect("show", lambda *_: self.win.build_file_menu(self.file_menu))
        tabs.pack_start(self.file_btn, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.tab_buttons = {}
        self.home = self._home()
        self.view = self._view()
        self.text = self._text()
        for name, title, page in (("home", "Home", self.home), ("view", "View", self.view), ("text", "Text", self.text)):
            b = Gtk.ToggleButton(label=title)
            b.get_style_context().add_class("fd-tab")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("toggled", self._on_tab, name)
            tabs.pack_start(b, False, False, 0)
            self.tab_buttons[name] = b
            self.stack.add_named(page, name)
        self.tab_buttons["text"].get_style_context().add_class("fd-context")
        self.tab_buttons["text"].set_no_show_all(True)
        self.pack_start(tabs, False, False, 0)
        holder = _box(False)
        holder.get_style_context().add_class("fd-ribbon")
        holder.pack_start(self.stack, True, True, 0)
        self.pack_start(holder, False, False, 0)
        self.tab_buttons["home"].set_active(True)

    def _on_tab(self, btn, name):
        if self._sync:
            return
        self._sync = True
        if btn.get_active():
            for n, b in self.tab_buttons.items():
                if n != name:
                    b.set_active(False)
            self.stack.set_visible_child_name(name)
        elif self.stack.get_visible_child_name() == name:
            btn.set_active(True)
        self._sync = False

    def show_tab(self, name):
        self.tab_buttons[name].set_active(True)

    def set_text_tab(self, visible):
        b = self.tab_buttons["text"]
        if visible:
            b.show()
            b.set_active(True)
        else:
            if b.get_active():
                self.tab_buttons["home"].set_active(True)
            b.hide()

    # ------------------------------------------------------------------ Home
    def _home(self):
        w = self.win
        row = _box(False, 2)

        # Clipboard
        paste_menu = make_menu([
            ("Paste", "paste", lambda: w.cmd("paste"), "Ctrl+V"),
            ("Paste as new layer", "layeradd", lambda: w.cmd("paste_layer"), "Ctrl+Shift+V"),
            ("Paste from file…", "open", lambda: w.cmd("paste_from")),
        ])
        clip = _box(False, 2)
        self.paste_btn = big_button("paste", "Paste", "Paste (Ctrl+V)\nPaste the contents of the clipboard.", menu=paste_menu)
        clip.pack_start(self.paste_btn, False, False, 0)
        col = _box(True, 0)
        self.cut_btn = small_button("cut", "Cut", "Cut (Ctrl+X)")
        self.cut_btn.connect("clicked", lambda *_: w.cmd("cut"))
        self.copy_btn = small_button("copy", "Copy", "Copy (Ctrl+C)")
        self.copy_btn.connect("clicked", lambda *_: w.cmd("copy"))
        col.pack_start(self.cut_btn, False, False, 0)
        col.pack_start(self.copy_btn, False, False, 0)
        clip.pack_start(col, False, False, 0)
        row.pack_start(group("Clipboard", clip), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Image
        self.transparent_item = menu_item("Transparent selection", check=self.st.transparent_sel,
                                          cb=lambda: w.cmd("toggle_transparent_sel"))
        sel_menu = make_menu([
            ("Rectangular selection", "select", lambda: w.set_tool("select")),
            ("Free-form selection", "freeselect", lambda: w.set_tool("freeselect")),
            None,
            ("Select all", "selall", lambda: w.cmd("select_all"), "Ctrl+A"),
            ("Invert selection", "selinvert", lambda: w.cmd("invert_selection")),
            ("Delete", "delete", lambda: w.cmd("delete"), "Delete"),
            None,
            self.transparent_item,
        ])
        img = _box(False, 2)
        self.select_btn = big_button("select", "Select", "Select\nSelect a part of the picture.", menu=sel_menu)
        img.pack_start(self.select_btn, False, False, 0)
        col = _box(True, 0)
        self.crop_btn = small_button("crop", "Crop", "Crop (Ctrl+Shift+X)\nCrop the picture to the selection.")
        self.crop_btn.connect("clicked", lambda *_: w.cmd("crop"))
        resize = small_button("resize", "Resize", "Resize and skew (Ctrl+W)")
        resize.connect("clicked", lambda *_: w.cmd("resize"))
        rot_menu = make_menu([
            ("Rotate right 90°", "rotate", lambda: w.cmd("rot_cw")),
            ("Rotate left 90°", "rot_left", lambda: w.cmd("rot_ccw")),
            ("Rotate 180°", "rot180", lambda: w.cmd("rot_180")),
            None,
            ("Flip vertical", "flip_v", lambda: w.cmd("flip_v")),
            ("Flip horizontal", "flip_h", lambda: w.cmd("flip_h")),
            None,
            ("Invert colors", "invert", lambda: w.cmd("invert_colors"), "Ctrl+Shift+I"),
        ])
        rotate = small_button("rotate", "Rotate", "Rotate or flip", menu=rot_menu)
        for b in (self.crop_btn, resize, rotate):
            col.pack_start(b, False, False, 0)
        img.pack_start(col, False, False, 0)
        row.pack_start(group("Image", img), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Tools
        grid = Gtk.Grid(row_spacing=1, column_spacing=1)
        tools = [("pencil", "Pencil\nDraw a free-form line with the selected line width."),
                 ("fill", "Fill with color\nClick an area to fill it with color 1, right-click for color 2."),
                 ("text", "Text\nInsert text into the picture."),
                 ("eraser", "Eraser\nErase part of the picture to transparency."),
                 ("picker", "Color picker\nPick a color from the picture to use for drawing."),
                 ("zoom", "Magnifier\nLeft-click to zoom in, right-click to zoom out.")]
        for i, (t, tip) in enumerate(tools):
            b = small_button(t, None, tip, toggle=True, size=18)
            b.connect("toggled", self._tool_toggled, t)
            grid.attach(b, i % 3, i // 3, 1, 1)
            self.tool_buttons[t] = b
        row.pack_start(group("Tools", grid), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Brushes
        pop = Gtk.Popover()
        bgrid = Gtk.Grid(row_spacing=2, column_spacing=2, margin=6)
        self.brush_buttons = {}
        for i, (k, name) in enumerate(BRUSHES):
            b = Gtk.ToggleButton()
            b.get_style_context().add_class("fd-rbtn")
            b.set_tooltip_text(name)
            b.add(Icon(k, 40, painter=brush_painter(k)))
            b.connect("toggled", self._brush_toggled, k, pop)
            bgrid.attach(b, i % 3, i // 3, 1, 1)
            self.brush_buttons[k] = b
        bgrid.show_all()
        pop.add(bgrid)
        self.brush_btn = big_button("brush", "Brushes", "Brushes\nDraw with different brushes.", menu=pop)
        self.brush_btn.connect("button-press-event", self._brush_btn_press)
        row.pack_start(group("Brushes", self.brush_btn), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Shapes
        shp = _box(False, 4)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(7)
        flow.set_min_children_per_line(7)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_row_spacing(0)
        flow.set_column_spacing(0)
        for k, tip in shapes.SHAPES:
            b = Gtk.ToggleButton()
            b.get_style_context().add_class("fd-rbtn")
            b.set_tooltip_text(tip)
            b.add(Icon(k, 16, painter=shape_painter(k)))
            b.connect("toggled", self._shape_toggled, k)
            flow.add(b)
            self.shape_buttons[k] = b
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_size_request(7 * 28, 66)
        sc.add(flow)
        shp.pack_start(sc, False, False, 0)
        col = _box(True, 0)
        self.outline_items = {}
        out_menu = make_menu([
            ("No outline", None, lambda: w.cmd("outline", False)),
            ("Solid color", "outline", lambda: w.cmd("outline", True)),
        ])
        fill_menu = make_menu([
            ("No fill", None, lambda: w.cmd("fillmode", False)),
            ("Solid color", "fillmode", lambda: w.cmd("fillmode", True)),
        ])
        self.outline_btn = small_button("outline", "Outline", "Shape outline\nColor 1 outlines the shape.", menu=out_menu)
        self.fillmode_btn = small_button("fillmode", "Fill", "Shape fill\nColor 2 fills the shape.", menu=fill_menu)
        col.pack_start(self.outline_btn, False, False, 0)
        col.pack_start(self.fillmode_btn, False, False, 0)
        shp.pack_start(col, False, False, 0)
        row.pack_start(group("Shapes", shp), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Size
        self.size_pop = Gtk.Popover()
        sb = _box(True, 4)
        sb.set_margin_start(8)
        sb.set_margin_end(8)
        sb.set_margin_top(8)
        sb.set_margin_bottom(8)
        self.size_presets = _box(True, 2)
        sb.pack_start(self.size_presets, False, False, 0)
        self.size_caption = Gtk.Label(xalign=0)
        sb.pack_start(self.size_caption, False, False, 0)
        hb = _box(False, 6)
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.size_scale.set_size_request(160, -1)
        self.size_scale.set_draw_value(False)
        self.size_scale.get_style_context().add_class("fd-accent")
        self.size_spin = Gtk.SpinButton.new_with_range(1, 500, 1)
        self.size_scale.connect("value-changed", self._size_scale_changed)
        self.size_spin.connect("value-changed", self._size_spin_changed)
        hb.pack_start(self.size_scale, True, True, 0)
        hb.pack_start(self.size_spin, False, False, 0)
        sb.pack_start(hb, False, False, 0)
        sb.show_all()
        self.size_pop.add(sb)
        self.size_pop.connect("show", lambda *_: self._fill_size_presets())
        self.size_btn = big_button("size", "Size", "Size (Ctrl++ / Ctrl+−)\nSelect the width for the selected tool.", menu=self.size_pop)
        row.pack_start(group("Size", self.size_btn), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Colors
        colors = _box(False, 4)
        self.well_buttons = {}
        for n in (1, 2):
            b = Gtk.ToggleButton()
            b.get_style_context().add_class("fd-rbtn")
            v = _box(True, 1)
            da = Gtk.DrawingArea()
            sz = 30 if n == 1 else 24
            da.set_size_request(32, 32)
            da.connect("draw", self._draw_well, n, sz)
            v.pack_start(da, False, False, 0)
            lbl = Gtk.Label(label=f"Color\n{n}")
            lbl.set_justify(Gtk.Justification.CENTER)
            v.pack_start(lbl, False, False, 0)
            b.add(v)
            b.set_valign(Gtk.Align.START)
            b.set_tooltip_text(
                "Color 1 (foreground)\nClick here and then select a color from the palette. "
                "This color is used with the pencil, brushes, text and shape outlines." if n == 1 else
                "Color 2 (background)\nClick here and then select a color from the palette. "
                "This color is used for right-click drawing, shape fill and text background.")
            b.connect("toggled", self._well_toggled, n)
            b.well_da = da
            colors.pack_start(b, False, False, 0)
            self.well_buttons[n] = b
        pal = Gtk.Grid(row_spacing=2, column_spacing=2)
        pal.set_valign(Gtk.Align.CENTER)
        self.pal_swatches = []
        for i in range(30):
            if i < 20:
                fn = (lambda c=PALETTE[i]: c)
            else:
                fn = (lambda j=i - 20: self.st.custom_colors[j])
            sw = Swatch(16, fn, lambda button, f=fn: self._palette_click(f(), button))
            sw.set_tooltip_text(self._color_tip(i))
            pal.attach(sw, i % 10, i // 10, 1, 1)
            self.pal_swatches.append(sw)
        colors.pack_start(pal, False, False, 2)
        edit = big_button("editcolors", "Edit colors", "Edit colors\nSelect a color from the color palette.")
        edit.connect("clicked", lambda *_: w.cmd("edit_colors"))
        colors.pack_start(edit, False, False, 0)
        row.pack_start(group("Colors", colors), False, False, 2)
        return row

    def _color_tip(self, i):
        names = ["Black", "Gray-50%", "Dark red", "Red", "Orange", "Yellow", "Green", "Turquoise", "Indigo", "Purple",
                 "White", "Gray-25%", "Brown", "Rose", "Gold", "Light yellow", "Lime", "Light turquoise", "Blue-gray", "Lavender"]
        if i < 20:
            return names[i]
        if i == 20:
            return "Transparent\nPaint with this to cut holes; fill with it to clear an area."
        return "Custom color\nUse Edit colors to add your own."

    def _palette_click(self, color, button):
        if color is None:
            return
        if button == 3:
            self.win.set_color(2, color)
        else:
            self.win.set_color(self.st.active_well, color)

    def _draw_well(self, da, cr, n, sz):
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        draw_swatch(cr, (w - sz) / 2, (h - sz) / 2, sz, sz, self.st.color1 if n == 1 else self.st.color2)
        return False

    def _well_toggled(self, b, n):
        if self._sync:
            return
        if b.get_active():
            self.st.active_well = n
        self.refresh()

    def _tool_toggled(self, b, tool):
        if self._sync:
            return
        if b.get_active():
            self.win.set_tool(tool)
        else:
            self.refresh()

    def _brush_btn_press(self, btn, ev):
        # a click on the big button selects the brush tool too (like the original's split button)
        if self.st.tool != "brush":
            self.win.set_tool("brush")
        return False

    def _brush_toggled(self, b, kind, pop):
        if self._sync:
            return
        if b.get_active():
            self.win.set_brush(kind)
            pop.popdown()
        else:
            self.refresh()

    def _shape_toggled(self, b, kind):
        if self._sync:
            return
        if b.get_active():
            self.win.set_shape(kind)
        else:
            self.refresh()

    # ---- size
    def _size_key(self):
        return self.win.size_key()

    def _fill_size_presets(self):
        for c in self.size_presets.get_children():
            c.destroy()
        key = self._size_key()
        if key == "fill":
            self.size_caption.set_text("Fill tolerance (%)")
            self.size_scale.set_range(0, 100)
            self.size_spin.set_range(0, 100)
            self._sync = True
            self.size_scale.set_value(self.st.tolerance)
            self.size_spin.set_value(self.st.tolerance)
            self._sync = False
            return
        self.size_caption.set_text("Width (px)")
        self.size_scale.set_range(1, 100)
        self.size_spin.set_range(1, 500)
        presets = {"pencil": [1, 2, 3, 4], "eraser": [4, 8, 16, 32], "shape": [1, 3, 5, 8]}.get(key, [1, 3, 5, 8, 16, 32])
        cur = self.st.sizes.get(key, 3)
        for p in presets:
            b = Gtk.ToggleButton()
            b.get_style_context().add_class("fd-rbtn")
            da = Gtk.DrawingArea()
            da.set_size_request(160, max(10, min(p, 32) + 6))

            def draw(w, cr, p=p):
                h = w.get_allocated_height()
                cr.set_source_rgb(*INK)
                cr.rectangle(4, (h - min(p, 32)) / 2, w.get_allocated_width() - 8, min(p, 32))
                cr.fill()
            da.connect("draw", draw)
            b.add(da)
            b.set_tooltip_text(f"{p} px")
            b.set_active(p == cur)
            b.connect("clicked", lambda _b, p=p: (self.win.set_size(p), self.size_pop.popdown()))
            self.size_presets.pack_start(b, False, False, 0)
        self._sync = True
        self.size_scale.set_value(min(cur, 100))
        self.size_spin.set_value(cur)
        self._sync = False
        self.size_presets.show_all()

    def _size_scale_changed(self, s):
        if self._sync:
            return
        v = int(s.get_value())
        self._sync = True
        self.size_spin.set_value(v)
        self._sync = False
        self._apply_size(v)

    def _size_spin_changed(self, s):
        if self._sync:
            return
        v = int(s.get_value())
        self._sync = True
        self.size_scale.set_value(min(v, 100))
        self._sync = False
        self._apply_size(v)

    def _apply_size(self, v):
        if self._size_key() == "fill":
            self.st.tolerance = v
        else:
            self.win.set_size(v)

    # ------------------------------------------------------------------ View
    def _view(self):
        w = self.win
        row = _box(False, 2)
        z = _box(False, 2)
        for icon, label, tip, cmd in (("zoomin", "Zoom\nin", "Zoom in (Ctrl+Page Up)", "zoom_in"),
                                      ("zoomout", "Zoom\nout", "Zoom out (Ctrl+Page Down)", "zoom_out"),
                                      ("zoom100", "100%", "Zoom to 100%", "zoom_100"),
                                      ("fit", "Fit to\nwindow", "Fit the picture to the window", "zoom_fit")):
            b = big_button(icon, label, tip)
            b.connect("clicked", lambda _b, c=cmd: w.cmd(c))
            z.pack_start(b, False, False, 0)
        row.pack_start(group("Zoom", z), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        sh = Gtk.Grid(row_spacing=0, column_spacing=12)
        sh.set_valign(Gtk.Align.CENTER)
        self.view_checks = {}
        for i, (key, label, tip) in enumerate((("rulers", "Rulers", "Rulers (Ctrl+R)"), ("grid", "Gridlines", "Gridlines (Ctrl+G)"),
                                               ("statusbar", "Status bar", "Status bar"), ("layers", "Layers panel", "Layers panel (F7)"))):
            c = Gtk.CheckButton(label=label)
            c.get_style_context().add_class("fd-check")
            c.set_tooltip_text(tip)
            c.connect("toggled", lambda cb, k=key: (not self._sync) and w.cmd("view_toggle", k, cb.get_active()))
            sh.attach(c, i // 3, i % 3, 1, 1)
            self.view_checks[key] = c
        row.pack_start(group("Show or hide", sh), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        fs = big_button("fullscreen", "Full\nscreen", "Full screen (F11)\nView the picture in full screen.")
        fs.connect("clicked", lambda *_: w.cmd("fullscreen"))
        row.pack_start(group("Display", fs), False, False, 2)
        row.pack_start(sep(), False, False, 0)

        # Animation: each layer is one frame (bottom layer first)
        an = _box(False, 2)
        self.frames_btn = big_button("frames", "Frames\nview", "Frames view\nShow one layer at a time, so each layer works as an animation frame. "
                                     "Saving is not affected.", toggle=True)
        self.frames_btn.connect("toggled", lambda b: (not self._sync) and w.cmd("frames_view", b.get_active()))
        an.pack_start(self.frames_btn, False, False, 0)
        self.play_btn = big_button("play", "Play", "Play (Space)\nPreview the layers as an animation, bottom layer first.", toggle=True)
        self.play_btn.connect("toggled", lambda b: (not self._sync) and w.cmd("play", b.get_active()))
        an.pack_start(self.play_btn, False, False, 0)
        col = _box(True, 0)
        prev_b = small_button("prevframe", "Previous frame", "Previous frame (,)")
        prev_b.connect("clicked", lambda *_: w.cmd("frame_step", -1))
        next_b = small_button("nextframe", "Next frame", "Next frame (.)")
        next_b.connect("clicked", lambda *_: w.cmd("frame_step", 1))
        rep = _box(False, 4)
        rep.pack_start(Gtk.Label(label="Plays"), False, False, 2)
        self.loop_combo = Gtk.ComboBoxText()
        for label in ("Forever", "Once", "2 times", "3 times", "5 times", "10 times"):
            self.loop_combo.append_text(label)
        self.loop_combo.set_tooltip_text("How many times the saved GIF plays")
        self.loop_combo.connect("changed", lambda c: (not self._sync) and w.cmd("gif_loop", c.get_active()))
        rep.pack_start(self.loop_combo, False, False, 0)
        for b in (prev_b, next_b, rep):
            col.pack_start(b, False, False, 0)
        an.pack_start(col, False, False, 0)
        self.anim_widgets = (prev_b, next_b)
        row.pack_start(group("Animation", an), False, False, 2)
        return row

    # ------------------------------------------------------------------ Text (contextual)
    def _text(self):
        w = self.win
        row = _box(False, 2)
        font = Gtk.Grid(row_spacing=3, column_spacing=4)
        font.set_valign(Gtk.Align.CENTER)
        self.font_combo = Gtk.ComboBoxText.new_with_entry()
        fams = sorted({f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}, key=str.lower)
        for f in fams:
            self.font_combo.append_text(f)
        self.font_combo.get_child().set_width_chars(18)
        self.font_combo.connect("changed", lambda c: (not self._sync) and w.cmd("text_font", c.get_active_text()))
        self.size_combo = Gtk.ComboBoxText.new_with_entry()
        for s in (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72):
            self.size_combo.append_text(str(s))
        self.size_combo.get_child().set_width_chars(4)
        self.size_combo.connect("changed", self._text_size_changed)
        font.attach(self.font_combo, 0, 0, 4, 1)
        font.attach(self.size_combo, 4, 0, 1, 1)
        self.style_toggles = {}
        for i, (k, label, tip) in enumerate((("bold", "<b>B</b>", "Bold (Ctrl+B)"), ("italic", "<i>I</i>", "Italic (Ctrl+I)"),
                                              ("underline", "<u>U</u>", "Underline (Ctrl+U)"), ("strike", "<s>abc</s>", "Strikethrough"))):
            b = Gtk.ToggleButton()
            lbl = Gtk.Label()
            lbl.set_markup(label)
            b.add(lbl)
            b.get_style_context().add_class("fd-rbtn")
            b.set_tooltip_text(tip)
            b.connect("toggled", lambda tb, k=k: (not self._sync) and w.cmd("text_style", k, tb.get_active()))
            font.attach(b, i, 1, 1, 1)
            self.style_toggles[k] = b
        row.pack_start(group("Font", font), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        bg = _box(True, 2)
        bg.set_valign(Gtk.Align.CENTER)
        self.opaque_radio = Gtk.RadioButton.new_with_label(None, "Opaque")
        self.transp_radio = Gtk.RadioButton.new_with_label_from_widget(self.opaque_radio, "Transparent")
        for r in (self.opaque_radio, self.transp_radio):
            r.get_style_context().add_class("fd-check")
        self.opaque_radio.set_tooltip_text("Opaque\nThe text background is filled with color 2.")
        self.transp_radio.set_tooltip_text("Transparent\nThe text has no background.")
        self.opaque_radio.connect("toggled", lambda r: (not self._sync) and w.cmd("text_opaque", r.get_active()))
        bg.pack_start(self.opaque_radio, False, False, 0)
        bg.pack_start(self.transp_radio, False, False, 0)
        row.pack_start(group("Background", bg), False, False, 2)
        row.pack_start(sep(), False, False, 0)
        done = big_button("text", "Done", "Finish the text and place it on the picture (click outside the box)")
        done.connect("clicked", lambda *_: w.cmd("text_commit"))
        row.pack_start(group("Text", done), False, False, 2)
        return row

    def _text_size_changed(self, c):
        if self._sync:
            return
        try:
            v = float(c.get_active_text())
        except (TypeError, ValueError):
            return
        if 1 <= v <= 1000:
            self.win.cmd("text_size", v)

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        st = self.st
        self._sync = True
        for t, b in self.tool_buttons.items():
            b.set_active(st.tool == t)
        for k, b in self.brush_buttons.items():
            b.set_active(st.brush == k)
        self.brush_btn.get_style_context().remove_class("fd-on")
        if st.tool == "brush":
            self.brush_btn.get_style_context().add_class("fd-on")
        self.select_btn.get_style_context().remove_class("fd-on")
        if st.tool in ("select", "freeselect"):
            self.select_btn.get_style_context().add_class("fd-on")
        for k, b in self.shape_buttons.items():
            b.set_active(st.tool == "shape" and st.shape == k)
        for n, b in self.well_buttons.items():
            b.set_active(st.active_well == n)
            b.well_da.queue_draw()
        for sw in self.pal_swatches:
            sw.da.queue_draw()
        shape_mode = st.tool == "shape"
        self.outline_btn.set_sensitive(shape_mode)
        self.fillmode_btn.set_sensitive(shape_mode)
        self.size_btn.set_sensitive(st.tool not in ("text", "picker", "zoom", "select", "freeselect"))
        self.transparent_item.set_active(st.transparent_sel)
        for k, c in self.view_checks.items():
            c.set_active(st.view[k])
        doc = self.win.doc
        if doc is not None:
            self.frames_btn.set_active(doc.frames_view)
            self.play_btn.set_active(self.win.playing)
            self.play_btn.label_widget.set_text("Stop" if self.win.playing else "Play")
            for ch in self.play_btn.get_child().get_children():
                if isinstance(ch, Icon):
                    ch.set_name_icon("stop" if self.win.playing else "play")
            multi = doc.layer_count() > 1
            self.play_btn.set_sensitive(multi)
            for b in self.anim_widgets:
                b.set_sensitive(multi)
            lp = doc.gif_loop
            self.loop_combo.set_active({0: 0, -1: 1, 1: 2, 2: 3, 4: 4, 9: 5}.get(lp, 0))
        self.font_combo.get_child().set_text(st.font_family)
        self.size_combo.get_child().set_text(("%g" % st.font_size))
        for k, b in self.style_toggles.items():
            b.set_active(getattr(st, k))
        (self.opaque_radio if st.text_opaque else self.transp_radio).set_active(True)
        self._sync = False

    def refresh_edit_state(self, has_sel, can_paste):
        self.cut_btn.set_sensitive(has_sel)
        self.copy_btn.set_sensitive(has_sel)
        self.crop_btn.set_sensitive(has_sel)
