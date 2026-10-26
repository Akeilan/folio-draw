"""Page setup and print preview: paper, orientation, margins, centring and scaling (a
percentage of normal size, or fit to so many pages across and down), and where each part
of the picture lands on each page."""
import math

from gi.repository import Gtk

PAPERS = [("A4", 210, 297), ("Letter", 215.9, 279.4), ("Legal", 215.9, 355.6), ("A3", 297, 420), ("A5", 148, 210)]
MM_PER_PX = 25.4 / 96.0          # a picture's pixel at 100 %

DEFAULTS = {"paper": "A4", "landscape": False, "margins": [19.1, 19.1, 19.1, 19.1],     # top, right, bottom, left
            "center_h": True, "center_v": False, "mode": "fit", "percent": 100, "fit_w": 1, "fit_h": 1}


def settings(state):
    """The page settings kept with the app's settings (filled in with defaults)."""
    page = getattr(state, "page", None) or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in page.items() if k in DEFAULTS})
    return out


def paper_size(s):
    w, h = next(((pw, ph) for n, pw, ph in PAPERS if n == s["paper"]), (210, 297))
    return (h, w) if s["landscape"] else (w, h)


def layout(s, img_w, img_h):
    """The pages: a list of (src_x, src_y, src_w, src_h, dest_x, dest_y, mm_per_px) — a part of
    the picture, where on the page (mm, from the paper's corner) and at what scale."""
    pw, ph = paper_size(s)
    top, right, bottom, left = s["margins"]
    aw, ah = max(pw - left - right, 10.0), max(ph - top - bottom, 10.0)
    if s["mode"] == "fit":
        fw, fh = max(1, int(s["fit_w"])), max(1, int(s["fit_h"]))
        # shrunk to fit, never enlarged past normal size (Adjust to % enlarges)
        k = min(aw * fw / (img_w * MM_PER_PX), ah * fh / (img_h * MM_PER_PX), 1.0)
    else:
        k = max(1, float(s["percent"])) / 100.0
    mmpp = MM_PER_PX * k
    total_w, total_h = img_w * mmpp, img_h * mmpp
    cols = max(1, math.ceil(total_w / aw - 1e-9))
    rows = max(1, math.ceil(total_h / ah - 1e-9))
    px_per_page_w = aw / mmpp
    px_per_page_h = ah / mmpp
    pages = []
    for r in range(rows):
        for c in range(cols):
            sx, sy = c * px_per_page_w, r * px_per_page_h
            sw, sh = min(px_per_page_w, img_w - sx), min(px_per_page_h, img_h - sy)
            if sw <= 0 or sh <= 0:
                continue
            dx, dy = left, top
            if cols == 1 and s["center_h"]:
                dx = left + (aw - sw * mmpp) / 2
            if rows == 1 and s["center_v"]:
                dy = top + (ah - sh * mmpp) / 2
            pages.append((sx, sy, sw, sh, dx, dy, mmpp))
    return pages


def describe(s, img_w, img_h):
    pages = layout(s, img_w, img_h)
    pct = pages[0][6] / MM_PER_PX * 100 if pages else 100
    return "%d page%s at %d%% of normal size" % (len(pages), "" if len(pages) == 1 else "s", round(pct))


def draw_page(cr, surf, page, scale=1.0):
    """Paint one page's part of the picture; the context is in mm times `scale`."""
    import cairo
    sx, sy, sw, sh, dx, dy, mmpp = page
    cr.save()
    cr.translate(dx * scale, dy * scale)
    cr.rectangle(0, 0, sw * mmpp * scale, sh * mmpp * scale)
    cr.clip()
    cr.scale(mmpp * scale, mmpp * scale)
    cr.translate(-sx, -sy)
    cr.set_source_surface(surf, 0, 0)
    # big enlargements stay crisp (pixel art); reductions are smoothed
    cr.get_source().set_filter(cairo.FILTER_NEAREST if mmpp * scale >= 2 * MM_PER_PX * scale else cairo.FILTER_GOOD)
    cr.paint()
    cr.restore()


class PageSetup(Gtk.Box):
    """The settings, as a panel (the File view's Print page) or inside a dialog."""

    def __init__(self, win, on_change=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.on_change = on_change
        s = settings(win.state)
        self.s = s
        g = Gtk.Grid(row_spacing=6, column_spacing=8)
        g.attach(Gtk.Label(label="Paper size:", xalign=0), 0, 0, 1, 1)
        self.paper = Gtk.ComboBoxText()
        for n, pw, ph in PAPERS:
            self.paper.append(n, "%s (%g × %g mm)" % (n, pw, ph))
        self.paper.set_active_id(s["paper"])
        self.paper.set_name("paper")
        g.attach(self.paper, 1, 0, 3, 1)
        g.attach(Gtk.Label(label="Orientation:", xalign=0), 0, 1, 1, 1)
        self.portrait = Gtk.RadioButton.new_with_label(None, "Portrait")
        self.landscape = Gtk.RadioButton.new_with_label_from_widget(self.portrait, "Landscape")
        self.landscape.set_name("landscape")
        (self.landscape if s["landscape"] else self.portrait).set_active(True)
        g.attach(self.portrait, 1, 1, 1, 1)
        g.attach(self.landscape, 2, 1, 2, 1)
        g.attach(Gtk.Label(label="Margins (mm):", xalign=0), 0, 2, 1, 1)
        self.margins = []
        for i, (label, v) in enumerate(zip(("Top", "Right", "Bottom", "Left"), s["margins"])):
            b = Gtk.Box(spacing=4)
            b.pack_start(Gtk.Label(label=label), False, False, 0)
            sp = Gtk.SpinButton.new_with_range(0, 100, 1)
            sp.set_digits(1)
            sp.set_value(v)
            sp.set_name("margin-" + label.lower())
            b.pack_start(sp, False, False, 0)
            g.attach(b, 1 + i % 2, 2 + i // 2, 1, 1)
            self.margins.append(sp)
        g.attach(Gtk.Label(label="Centre on page:", xalign=0), 0, 4, 1, 1)
        self.center_h = Gtk.CheckButton(label="Horizontally")
        self.center_h.set_active(s["center_h"])
        self.center_v = Gtk.CheckButton(label="Vertically")
        self.center_v.set_active(s["center_v"])
        g.attach(self.center_h, 1, 4, 1, 1)
        g.attach(self.center_v, 2, 4, 2, 1)
        g.attach(Gtk.Label(label="Scaling:", xalign=0), 0, 5, 1, 1)
        self.m_pct = Gtk.RadioButton.new_with_label(None, "Adjust to")
        self.m_pct.set_name("adjust-to")
        self.pct = Gtk.SpinButton.new_with_range(10, 400, 5)
        self.pct.set_value(s["percent"])
        self.pct.set_name("percent")
        pb = Gtk.Box(spacing=4)
        pb.pack_start(self.m_pct, False, False, 0)
        pb.pack_start(self.pct, False, False, 0)
        pb.pack_start(Gtk.Label(label="% normal size"), False, False, 0)
        g.attach(pb, 1, 5, 3, 1)
        self.m_fit = Gtk.RadioButton.new_with_label_from_widget(self.m_pct, "Fit to")
        self.m_fit.set_name("fit-to")
        self.fit_w = Gtk.SpinButton.new_with_range(1, 20, 1)
        self.fit_w.set_value(s["fit_w"])
        self.fit_w.set_name("fit-w")
        self.fit_h = Gtk.SpinButton.new_with_range(1, 20, 1)
        self.fit_h.set_value(s["fit_h"])
        self.fit_h.set_name("fit-h")
        fb = Gtk.Box(spacing=4)
        fb.pack_start(self.m_fit, False, False, 0)
        fb.pack_start(self.fit_w, False, False, 0)
        fb.pack_start(Gtk.Label(label="by"), False, False, 0)
        fb.pack_start(self.fit_h, False, False, 0)
        fb.pack_start(Gtk.Label(label="page(s)"), False, False, 0)
        g.attach(fb, 1, 6, 3, 1)
        (self.m_fit if s["mode"] == "fit" else self.m_pct).set_active(True)
        self.pack_start(g, False, False, 0)
        self.summary = Gtk.Label(xalign=0)
        self.summary.get_style_context().add_class("dim-label")
        self.pack_start(self.summary, False, False, 0)
        for w in [self.paper]:
            w.connect("changed", self._changed)
        for w in (self.portrait, self.landscape, self.center_h, self.center_v, self.m_pct, self.m_fit):
            w.connect("toggled", self._changed)
        for w in self.margins + [self.pct, self.fit_w, self.fit_h]:
            w.connect("value-changed", self._changed)
        self._changed()

    def read(self):
        for sp in self.margins + [self.pct, self.fit_w, self.fit_h]:
            sp.update()
        self.s = {"paper": self.paper.get_active_id() or "A4", "landscape": self.landscape.get_active(),
                  "margins": [sp.get_value() for sp in self.margins], "center_h": self.center_h.get_active(),
                  "center_v": self.center_v.get_active(), "mode": "fit" if self.m_fit.get_active() else "percent",
                  "percent": self.pct.get_value(), "fit_w": int(self.fit_w.get_value()),
                  "fit_h": int(self.fit_h.get_value())}
        return self.s

    def _changed(self, *_):
        s = self.read()
        self.pct.set_sensitive(s["mode"] == "percent")
        self.fit_w.set_sensitive(s["mode"] == "fit")
        self.fit_h.set_sensitive(s["mode"] == "fit")
        self.win.state.page = dict(s)
        doc = self.win.doc
        if doc is not None:
            self.summary.set_text(describe(s, doc.width, doc.height))
        if self.on_change:
            self.on_change(s)


class Preview(Gtk.Box):
    """The pages as they will print, one at a time."""

    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.win = win
        self.page = 0
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(320, 420)
        self.area.set_name("preview")
        self.area.connect("draw", self._draw)
        self.pack_start(self.area, True, True, 0)
        nav = Gtk.Box(spacing=6)
        self.prev = Gtk.Button(label="◀")
        self.prev.set_name("prev-page")
        self.next = Gtk.Button(label="▶")
        self.next.set_name("next-page")
        self.count = Gtk.Label()
        self.count.set_name("page-count")
        self.prev.connect("clicked", lambda *_: self.go(-1))
        self.next.connect("clicked", lambda *_: self.go(1))
        nav.pack_start(self.prev, False, False, 0)
        nav.pack_start(self.count, False, False, 0)
        nav.pack_start(self.next, False, False, 0)
        nav.set_halign(Gtk.Align.CENTER)
        self.pack_start(nav, False, False, 0)
        self.refresh()

    def pages(self):
        doc = self.win.doc
        if doc is None:
            return []
        return layout(settings(self.win.state), doc.width, doc.height)

    def go(self, d):
        n = len(self.pages())
        self.page = max(0, min(n - 1, self.page + d))
        self.refresh()

    def refresh(self, *_):
        n = len(self.pages())
        self.page = max(0, min(self.page, n - 1))
        self.count.set_text("Page %d of %d" % (self.page + 1, max(n, 1)))
        self.prev.set_sensitive(self.page > 0)
        self.next.set_sensitive(self.page < n - 1)
        self.area.queue_draw()

    def _draw(self, a, cr):
        aw, ah = a.get_allocated_width(), a.get_allocated_height()
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.paint()
        s = settings(self.win.state)
        pw, ph = paper_size(s)
        k = min((aw - 30) / pw, (ah - 30) / ph)
        ox, oy = (aw - pw * k) / 2, (ah - ph * k) / 2
        cr.set_source_rgba(0, 0, 0, 0.15)
        cr.rectangle(ox + 3, oy + 3, pw * k, ph * k)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(ox, oy, pw * k, ph * k)
        cr.fill()
        pages = self.pages()
        surf = self.win.canvas.surf
        if pages and surf is not None:
            cr.save()
            cr.translate(ox, oy)
            draw_page(cr, surf, pages[self.page], k)
            cr.restore()
        # the margins, dotted
        t, r, b, l = s["margins"]
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_line_width(1)
        cr.set_dash([2, 2])
        cr.rectangle(ox + l * k + 0.5, oy + t * k + 0.5, (pw - l - r) * k, (ph - t - b) * k)
        cr.stroke()
        cr.set_dash([])
        return False


def page_setup_dialog(win):
    """File > Page setup, as a dialog: the settings beside the preview."""
    d = Gtk.Dialog(title="Page Setup", transient_for=win, modal=True)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    okb = d.add_button("OK", Gtk.ResponseType.OK)
    okb.get_style_context().add_class("fd-primary")
    before = dict(settings(win.state))
    box = Gtk.Box(spacing=16)
    box.set_border_width(12)
    prev = Preview(win)
    panel = PageSetup(win, on_change=lambda s: prev.refresh())
    box.pack_start(panel, False, False, 0)
    box.pack_start(prev, True, True, 0)
    d.get_content_area().pack_start(box, True, True, 0)
    d.panel, d.preview = panel, prev
    d.show_all()
    r = d.run()
    d.destroy()
    if r != Gtk.ResponseType.OK:
        win.state.page = before
        return None
    return settings(win.state)
