"""Dialogs: Resize and Skew, Image Properties, Edit Colors, Layer Properties, prompts, About."""

import colorsys
import os
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import engine as E
from .icons import Icon
from .ribbon import PALETTE, checker, draw_swatch

APP_NAME = "Folio Draw"


def _dialog(parent, title, ok="OK"):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.set_resizable(False)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    okb = d.add_button(ok, Gtk.ResponseType.OK)
    okb.get_style_context().add_class("fd-primary")
    d.set_default_response(Gtk.ResponseType.OK)
    area = d.get_content_area()
    area.set_spacing(8)
    area.set_border_width(12)
    return d, area


def _frame(title, child):
    f = Gtk.Frame(label=title)
    child.set_border_width(8)
    f.add(child)
    return f


def _spin(lo, hi, val, digits=0, step=1):
    s = Gtk.SpinButton.new_with_range(lo, hi, step)
    s.set_digits(digits)
    s.set_value(val)
    s.set_activates_default(True)
    return s


# --------------------------------------------------------------------------- Resize and Skew

def resize_skew(parent, cur_w, cur_h, what="image"):
    """Returns (w, h, skew_x, skew_y) or None."""
    d, area = _dialog(parent, "Resize and Skew")
    rb = Gtk.Grid(row_spacing=6, column_spacing=10)
    by_pct = Gtk.RadioButton.new_with_label(None, "Percentage")
    by_px = Gtk.RadioButton.new_with_label_from_widget(by_pct, "Pixels")
    rb.attach(Gtk.Label(label="By:", xalign=0), 0, 0, 1, 1)
    rb.attach(by_pct, 1, 0, 1, 1)
    rb.attach(by_px, 2, 0, 1, 1)
    hs = _spin(1, 100000, 100)
    vs = _spin(1, 100000, 100)
    rb.attach(Icon("resize", 20), 0, 1, 1, 1)
    rb.attach(Gtk.Label(label="Horizontal:", xalign=0), 1, 1, 1, 1)
    rb.attach(hs, 2, 1, 1, 1)
    rb.attach(Gtk.Label(label="Vertical:", xalign=0), 1, 2, 1, 1)
    rb.attach(vs, 2, 2, 1, 1)
    keep = Gtk.CheckButton(label="Maintain aspect ratio")
    keep.set_active(True)
    rb.attach(keep, 1, 3, 2, 1)
    smooth = Gtk.CheckButton(label="Smooth (uncheck for crisp pixel art)")
    smooth.set_active(True)
    rb.attach(smooth, 1, 4, 2, 1)
    area.pack_start(_frame("Resize", rb), False, False, 0)
    sk = Gtk.Grid(row_spacing=6, column_spacing=10)
    sx = _spin(-89, 89, 0)
    sy = _spin(-89, 89, 0)
    sk.attach(Gtk.Label(label="Horizontal:", xalign=0), 0, 0, 1, 1)
    sk.attach(sx, 1, 0, 1, 1)
    sk.attach(Gtk.Label(label="degrees"), 2, 0, 1, 1)
    sk.attach(Gtk.Label(label="Vertical:", xalign=0), 0, 1, 1, 1)
    sk.attach(sy, 1, 1, 1, 1)
    sk.attach(Gtk.Label(label="degrees"), 2, 1, 1, 1)
    skf = _frame("Skew (degrees)", sk)
    area.pack_start(skf, False, False, 0)
    if what != "image":
        skf.set_sensitive(False)
    busy = [False]

    def mode_changed(*_):
        busy[0] = True
        if by_px.get_active():
            hs.set_value(round(cur_w * hs.get_value() / 100) if hs.get_value() else cur_w)
            vs.set_value(round(cur_h * vs.get_value() / 100) if vs.get_value() else cur_h)
        else:
            hs.set_value(round(hs.get_value() * 100 / cur_w))
            vs.set_value(round(vs.get_value() * 100 / cur_h))
        busy[0] = False

    def linked(src, dst, a, b):
        if busy[0] or not keep.get_active():
            return
        busy[0] = True
        if by_pct.get_active():
            dst.set_value(src.get_value())
        else:
            dst.set_value(max(1, round(src.get_value() * b / a)))
        busy[0] = False

    by_px.connect("toggled", mode_changed)
    hs.connect("value-changed", lambda s: linked(hs, vs, cur_w, cur_h))
    vs.connect("value-changed", lambda s: linked(vs, hs, cur_h, cur_w))
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        if by_pct.get_active():
            w = max(1, round(cur_w * hs.get_value() / 100))
            h = max(1, round(cur_h * vs.get_value() / 100))
        else:
            w, h = int(hs.get_value()), int(vs.get_value())
        if w > 32768 or h > 32768:
            message(parent, "That size is too large", "Images can be at most 32,768 pixels on each side.")
        else:
            out = (w, h, sx.get_value(), sy.get_value(), smooth.get_active())
    d.destroy()
    return out


# --------------------------------------------------------------------------- Image properties

def image_properties(parent, doc, path, saved_at):
    d, area = _dialog(parent, "Image Properties")
    info = Gtk.Grid(row_spacing=4, column_spacing=16)
    rows = [("Last saved", time.strftime("%d-%m-%Y %H:%M", time.localtime(saved_at)) if saved_at else "Not available"),
            ("Size on disk", _human(os.path.getsize(path)) if path and os.path.exists(path) else "Not available"),
            ("Resolution", "96 DPI"),
            ("Layers", str(doc.layer_count()))]
    for i, (a, b) in enumerate(rows):
        info.attach(Gtk.Label(label=a, xalign=0), 0, i, 1, 1)
        info.attach(Gtk.Label(label=b, xalign=0), 1, i, 1, 1)
    area.pack_start(_frame("File attributes", info), False, False, 0)
    units = Gtk.Box(spacing=12)
    u_in = Gtk.RadioButton.new_with_label(None, "Inches")
    u_cm = Gtk.RadioButton.new_with_label_from_widget(u_in, "Centimetres")
    u_px = Gtk.RadioButton.new_with_label_from_widget(u_in, "Pixels")
    u_px.set_active(True)
    for u in (u_in, u_cm, u_px):
        units.pack_start(u, False, False, 0)
    area.pack_start(_frame("Units", units), False, False, 0)
    g = Gtk.Grid(row_spacing=6, column_spacing=10)
    ws = _spin(0.01, 32768, doc.width)
    hs = _spin(0.01, 32768, doc.height)
    g.attach(Gtk.Label(label="Width:", xalign=0), 0, 0, 1, 1)
    g.attach(ws, 1, 0, 1, 1)
    g.attach(Gtk.Label(label="Height:", xalign=0), 0, 1, 1, 1)
    g.attach(hs, 1, 1, 1, 1)
    area.pack_start(_frame("Canvas size", g), False, False, 0)
    factor = {"px": 1.0, "in": 96.0, "cm": 96.0 / 2.54}
    cur = ["px"]

    def unit_changed(btn, u):
        if not btn.get_active():
            return
        f_old, f_new = factor[cur[0]], factor[u]
        digits = 0 if u == "px" else 2
        for s in (ws, hs):
            v = s.get_value() * f_old / f_new
            s.set_digits(digits)
            s.set_increments(1 if u == "px" else 0.1, 10)
            s.set_value(v)
        cur[0] = u

    u_in.connect("toggled", unit_changed, "in")
    u_cm.connect("toggled", unit_changed, "cm")
    u_px.connect("toggled", unit_changed, "px")
    d.show_all()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        f = factor[cur[0]]
        out = (max(1, min(32768, round(ws.get_value() * f))), max(1, min(32768, round(hs.get_value() * f))))
    d.destroy()
    return out


def _human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.1f %s" % (n, unit))
        n /= 1024.0


# --------------------------------------------------------------------------- Edit colors

class _HSField(Gtk.DrawingArea):
    """Hue (x) by saturation (y) field."""

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.set_size_request(220, 180)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_MOTION_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._pick)
        self.connect("motion-notify-event", self._pick)
        self.img = None

    def _ensure(self, w, h):
        import cairo
        if self.img is not None and self.img.get_width() == w and self.img.get_height() == h:
            return
        self.img = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        data = self.img.get_data()
        stride = self.img.get_stride()
        for y in range(h):
            s = 1 - y / max(1, h - 1)
            for x in range(w):
                r, g, b = colorsys.hsv_to_rgb(x / max(1, w - 1), s, 1.0)
                o = y * stride + x * 4
                data[o] = int(b * 255)
                data[o + 1] = int(g * 255)
                data[o + 2] = int(r * 255)
        self.img.mark_dirty()

    def _draw(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        self._ensure(W, H)
        cr.set_source_surface(self.img, 0, 0)
        cr.paint()
        h, s, v = self.dlg.hsv
        x, y = h * (W - 1), (1 - s) * (H - 1)
        cr.set_line_width(2)
        cr.set_source_rgb(0, 0, 0)
        for (a, b, c, e) in ((x - 9, y, x - 3, y), (x + 3, y, x + 9, y), (x, y - 9, x, y - 3), (x, y + 3, x, y + 9)):
            cr.move_to(a, b)
            cr.line_to(c, e)
        cr.stroke()
        return False

    def _pick(self, w, ev):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        h = min(1, max(0, ev.x / (W - 1)))
        s = 1 - min(1, max(0, ev.y / (H - 1)))
        self.dlg.set_hsv(h, s, self.dlg.hsv[2])
        return True


class _Slider(Gtk.DrawingArea):
    """Vertical value (brightness) or alpha slider."""

    def __init__(self, dlg, kind):
        super().__init__()
        self.dlg = dlg
        self.kind = kind
        self.set_size_request(22, 180)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_MOTION_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._pick)
        self.connect("motion-notify-event", self._pick)

    def _draw(self, w, cr):
        import cairo
        W, H = w.get_allocated_width(), w.get_allocated_height()
        bw = W - 8
        h, s, v = self.dlg.hsv
        r, g, b = colorsys.hsv_to_rgb(h, s, 1.0 if self.kind == "v" else v)
        if self.kind == "a":
            checker(cr, 0, 0, bw, H, 5)
        grad = cairo.LinearGradient(0, 0, 0, H)
        if self.kind == "v":
            grad.add_color_stop_rgb(0, r, g, b)
            grad.add_color_stop_rgb(1, 0, 0, 0)
            pos = 1 - v
        else:
            grad.add_color_stop_rgba(0, r, g, b, 1)
            grad.add_color_stop_rgba(1, r, g, b, 0)
            pos = 1 - self.dlg.alpha / 255
        cr.set_source(grad)
        cr.rectangle(0, 0, bw, H)
        cr.fill()
        y = pos * (H - 1)
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.move_to(W, y - 5)
        cr.line_to(bw + 1, y)
        cr.line_to(W, y + 5)
        cr.close_path()
        cr.fill()
        return False

    def _pick(self, w, ev):
        H = w.get_allocated_height()
        t = 1 - min(1, max(0, ev.y / (H - 1)))
        if self.kind == "v":
            self.dlg.set_hsv(self.dlg.hsv[0], self.dlg.hsv[1], t)
        else:
            self.dlg.set_alpha(round(t * 255))
        return True


class EditColors(Gtk.Dialog):
    def __init__(self, parent, color, custom):
        super().__init__(title="Edit Colors", transient_for=parent, modal=True)
        self.set_resizable(False)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = self.add_button("OK", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("fd-primary")
        self.set_default_response(Gtk.ResponseType.OK)
        self.custom = list(custom)
        r, g, b, a = color
        self.hsv = list(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255))
        self.alpha = a
        self._busy = False
        area = self.get_content_area()
        area.set_border_width(12)
        top = Gtk.Box(spacing=14)
        area.pack_start(top, False, False, 0)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.pack_start(Gtk.Label(label="Basic colors", xalign=0), False, False, 0)
        basic = Gtk.Grid(row_spacing=3, column_spacing=3)
        for i, c in enumerate(PALETTE):
            basic.attach(self._swatch(lambda c=c: c, lambda c=c: self.set_rgba(c)), i % 10, i // 10, 1, 1)
        basic.attach(self._swatch(lambda: (0, 0, 0, 0), lambda: self.set_rgba((0, 0, 0, 0)), "Transparent"), 0, 2, 1, 1)
        left.pack_start(basic, False, False, 0)
        left.pack_start(Gtk.Label(label="Custom colors", xalign=0), False, False, 4)
        self.cgrid = Gtk.Grid(row_spacing=3, column_spacing=3)
        for i in range(1, 10):
            self.cgrid.attach(self._swatch(lambda i=i: self.custom[i], lambda i=i: self.custom[i] and self.set_rgba(self.custom[i])), i - 1, 0, 1, 1)
        left.pack_start(self.cgrid, False, False, 0)
        add = Gtk.Button(label="Add to custom colors")
        add.connect("clicked", self._add_custom)
        left.pack_start(add, False, False, 4)
        top.pack_start(left, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pick = Gtk.Box(spacing=8)
        self.field = _HSField(self)
        self.vslider = _Slider(self, "v")
        self.aslider = _Slider(self, "a")
        self.vslider.set_tooltip_text("Brightness")
        self.aslider.set_tooltip_text("Opacity (alpha). Lower it for see-through colors.")
        pick.pack_start(self.field, False, False, 0)
        pick.pack_start(self.vslider, False, False, 0)
        pick.pack_start(self.aslider, False, False, 0)
        right.pack_start(pick, False, False, 0)
        fields = Gtk.Grid(row_spacing=4, column_spacing=8)
        self.preview = Gtk.DrawingArea()
        self.preview.set_size_request(70, 56)
        self.preview.connect("draw", lambda w, cr: draw_swatch(cr, 0, 0, w.get_allocated_width(), w.get_allocated_height(), self.rgba()))
        fields.attach(self.preview, 0, 0, 1, 4)
        self.spins = {}
        for i, (k, lab, hi) in enumerate((("h", "Hue", 360), ("s", "Sat", 100), ("v", "Val", 100))):
            fields.attach(Gtk.Label(label=lab, xalign=1), 1, i, 1, 1)
            sp = _spin(0, hi, 0)
            sp.connect("value-changed", self._hsv_spin)
            fields.attach(sp, 2, i, 1, 1)
            self.spins[k] = sp
        for i, (k, lab) in enumerate((("r", "Red"), ("g", "Green"), ("b", "Blue"), ("a", "Alpha"))):
            fields.attach(Gtk.Label(label=lab, xalign=1), 3, i, 1, 1)
            sp = _spin(0, 255, 0)
            sp.connect("value-changed", self._rgb_spin)
            fields.attach(sp, 4, i, 1, 1)
            self.spins[k] = sp
        fields.attach(Gtk.Label(label="Hex", xalign=1), 1, 3, 1, 1)
        self.hex = Gtk.Entry()
        self.hex.set_width_chars(9)
        self.hex.connect("activate", self._hex)
        self.hex.connect("focus-out-event", lambda *_: self._hex(self.hex) or False)
        fields.attach(self.hex, 2, 3, 1, 1)
        right.pack_start(fields, False, False, 0)
        top.pack_start(right, False, False, 0)
        self._update_fields()
        self.show_all()

    def _swatch(self, color_fn, on_click, tip=None):
        b = Gtk.Button()
        b.get_style_context().add_class("fd-swatch")
        da = Gtk.DrawingArea()
        da.set_size_request(18, 18)
        da.connect("draw", lambda w, cr: draw_swatch(cr, 0, 0, 18, 18, color_fn()))
        b.add(da)
        b.connect("clicked", lambda *_: on_click())
        if tip:
            b.set_tooltip_text(tip)
        return b

    def rgba(self):
        r, g, b = colorsys.hsv_to_rgb(*self.hsv)
        return (round(r * 255), round(g * 255), round(b * 255), self.alpha)

    def set_rgba(self, c):
        r, g, b, a = c
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s == 0 or v == 0:
            h = self.hsv[0]
        if v == 0:
            s = self.hsv[1]
        self.hsv = [h, s, v]
        self.alpha = a
        self._update_fields()

    def set_hsv(self, h, s, v):
        self.hsv = [h, s, v]
        self._update_fields()

    def set_alpha(self, a):
        self.alpha = max(0, min(255, a))
        self._update_fields()

    def _update_fields(self):
        self._busy = True
        r, g, b, a = self.rgba()
        self.spins["h"].set_value(round(self.hsv[0] * 360))
        self.spins["s"].set_value(round(self.hsv[1] * 100))
        self.spins["v"].set_value(round(self.hsv[2] * 100))
        for k, val in zip("rgba", (r, g, b, a)):
            self.spins[k].set_value(val)
        self.hex.set_text("#%02X%02X%02X" % (r, g, b) + ("" if a == 255 else "%02X" % a))
        self._busy = False
        for w in (self.field, self.vslider, self.aslider, self.preview):
            w.queue_draw()

    def _hsv_spin(self, *_):
        if self._busy:
            return
        self.hsv = [self.spins["h"].get_value() / 360, self.spins["s"].get_value() / 100, self.spins["v"].get_value() / 100]
        self._update_fields()

    def _rgb_spin(self, *_):
        if self._busy:
            return
        self.set_rgba(tuple(int(self.spins[k].get_value()) for k in "rgba"))

    def _hex(self, e):
        t = e.get_text().strip().lstrip("#")
        try:
            if len(t) in (3, 4):
                t = "".join(ch * 2 for ch in t)
            if len(t) == 6:
                self.set_rgba((int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16), 255))
            elif len(t) == 8:
                self.set_rgba((int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16), int(t[6:8], 16)))
        except ValueError:
            pass

    def _add_custom(self, *_):
        c = self.rgba()
        slots = self.custom[1:]
        if c in slots:
            return
        try:
            i = slots.index(None)
        except ValueError:
            slots = slots[1:] + [None]
            i = len(slots) - 1
        slots[i] = c
        self.custom = [self.custom[0]] + slots
        self.cgrid.queue_draw()
        for ch in self.cgrid.get_children():
            ch.queue_draw()


def edit_colors(parent, color, custom):
    d = EditColors(parent, color, custom)
    r = d.run()
    out = (d.rgba(), d.custom) if r == Gtk.ResponseType.OK else None
    d.destroy()
    return out


# --------------------------------------------------------------------------- layer props

def layer_properties(parent, name, opacity, visible, blend, delay=0):
    d, area = _dialog(parent, "Layer Properties")
    g = Gtk.Grid(row_spacing=8, column_spacing=10)
    ne = Gtk.Entry()
    ne.set_text(name)
    ne.set_activates_default(True)
    ne.set_width_chars(24)
    g.attach(Gtk.Label(label="Name:", xalign=0), 0, 0, 1, 1)
    g.attach(ne, 1, 0, 2, 1)
    vis = Gtk.CheckButton(label="Visible")
    vis.set_active(visible)
    g.attach(vis, 1, 1, 2, 1)
    g.attach(Gtk.Label(label="Blend mode:", xalign=0), 0, 2, 1, 1)
    bc = Gtk.ComboBoxText()
    for n in E.BLEND_NAMES:
        bc.append_text(n)
    bc.set_active(blend)
    g.attach(bc, 1, 2, 2, 1)
    g.attach(Gtk.Label(label="Opacity:", xalign=0), 0, 3, 1, 1)
    sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    sc.set_value(round(opacity * 100))
    sc.set_hexpand(True)
    sc.get_style_context().add_class("fd-accent")
    sp = _spin(0, 100, round(opacity * 100))
    sc.connect("value-changed", lambda s: sp.set_value(s.get_value()))
    sp.connect("value-changed", lambda s: sc.set_value(s.get_value()))
    g.attach(sc, 1, 3, 1, 1)
    g.attach(sp, 2, 3, 1, 1)
    g.attach(Gtk.Label(label="Frame time:", xalign=0), 0, 4, 1, 1)
    ds = _spin(10, 60000, delay if delay > 0 else 100, step=10)
    ds.set_tooltip_text("How long this layer shows when the picture is saved as an animated GIF (each layer is one frame).")
    g.attach(ds, 1, 4, 1, 1)
    g.attach(Gtk.Label(label="ms", xalign=0), 2, 4, 1, 1)
    area.pack_start(g, False, False, 0)
    d.show_all()
    ne.grab_focus()
    r = d.run()
    out = None
    if r == Gtk.ResponseType.OK:
        out = (ne.get_text() or name, sp.get_value() / 100, vis.get_active(), bc.get_active(), int(ds.get_value()))
    d.destroy()
    return out


# --------------------------------------------------------------------------- prompts

def message(parent, title, text, kind=Gtk.MessageType.INFO):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind, buttons=Gtk.ButtonsType.OK, text=title)
    d.format_secondary_text(text)
    d.set_title(APP_NAME)
    d.run()
    d.destroy()


def ask_save_changes(parent, name):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE, text="Do you want to save changes to %s?" % name)
    d.set_title(APP_NAME)
    d.add_button("Don't Save", Gtk.ResponseType.NO)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    s = d.add_button("Save", Gtk.ResponseType.YES)
    s.get_style_context().add_class("fd-primary")
    d.set_default_response(Gtk.ResponseType.YES)
    r = d.run()
    d.destroy()
    return {Gtk.ResponseType.YES: "save", Gtk.ResponseType.NO: "discard"}.get(r, "cancel")


def ask_choice(parent, title, text, buttons, default=0):
    """buttons: list of labels; returns index or -1 when dismissed."""
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE, text=title)
    d.set_title(APP_NAME)
    d.format_secondary_text(text)
    for i, b in enumerate(buttons):
        w = d.add_button(b, i)
        if i == default:
            w.get_style_context().add_class("fd-primary")
    d.set_default_response(default)
    r = d.run()
    d.destroy()
    return r if isinstance(r, int) and r >= 0 else -1


def about(parent, version):
    d = Gtk.AboutDialog(transient_for=parent, modal=True)
    d.set_program_name(APP_NAME)
    d.set_version(version)
    d.set_comments("A simple drawing program for quick mock-ups — with layers and real transparency.\nPart of the Folio suite.")
    d.set_logo_icon_name("folio-draw")
    d.set_license_type(Gtk.License.MIT_X11)
    d.set_authors(["Ron Shillings"])
    d.run()
    d.destroy()
