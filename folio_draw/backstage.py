"""The File view: Home, New, Open, Info, Save, Save As, Print, Export, Close and About,
laid out like the rest of the Folio suite (see the Folio Suite Ribbon Spec)."""

import datetime
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk, Pango  # noqa: E402

from . import __version__
from .icons import Icon

APP_NAME = "Folio Draw"

NAV = [("back", ""), ("home", "Home"), ("new", "New"), ("open", "Open"), None,
       ("info", "Info"), ("save", "Save"), ("saveas", "Save As"), ("print", "Print"),
       ("export", "Export"), ("close", "Close"), "spacer", ("about", "About")]

SAVE_FORMATS = [(".png", "PNG picture", "Lossless, keeps transparency (flattened)"),
                (".jpg", "JPEG picture", "Small files for photos; no transparency"),
                (".bmp", "BMP picture", "Uncompressed, no transparency"),
                (".gif", "GIF picture", "256 colors; layers can become animation frames"),
                (".webp", "WebP picture", "Lossless and compact, keeps transparency; layers can become frames"),
                (".tif", "TIFF picture", "Lossless, keeps transparency; for print and archiving"),
                (".ico", "Windows icon", "Icon sizes from 16 to 256 pixels, keeps transparency"),
                (".ora", "OpenRaster picture", "Keeps every layer, for editing later")]


def _heading(text, cls="fd-bs-title"):
    lab = Gtk.Label(label=text, xalign=0)
    lab.get_style_context().add_class(cls)
    return lab


def _when(ts):
    d = datetime.datetime.fromtimestamp(ts)
    now = datetime.datetime.now()
    if d.date() == now.date():
        return d.strftime("%-I:%M %p")
    if (now - d).days < 7:
        return d.strftime("%A")
    return d.strftime("%-m/%-d/%Y")


def _thumb(path, w=48, h=36):
    """A small picture of the file, or None when it cannot be read as an image."""
    try:
        return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, True))
    except Exception:
        return None


class Backstage(Gtk.Box):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.get_style_context().add_class("fd-backstage")
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav.get_style_context().add_class("fd-bs-nav")
        nav.set_size_request(180, -1)
        self.nav_buttons = {}
        for entry in NAV:
            if entry is None:
                s = Gtk.Separator()
                s.get_style_context().add_class("fd-bs-sep")
                nav.pack_start(s, False, False, 6)
                continue
            if entry == "spacer":
                nav.pack_start(Gtk.Box(), True, True, 0)
                continue
            key, label = entry
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("fd-bs-navbtn")
            if key == "back":
                b.add(Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
                b.set_tooltip_text("Back (Esc)")
                b.set_halign(Gtk.Align.START)
                b.get_style_context().add_class("back")
            else:
                b.add(Gtk.Label(label=label, xalign=0))
            b.connect("clicked", lambda _b, k=key: self.nav(k))
            nav.pack_start(b, False, False, 0)
            self.nav_buttons[key] = b
        self.pack_start(nav, False, False, 0)
        self.stack = Gtk.Stack()
        self.pack_start(self.stack, True, True, 0)
        self.current = None

    # ------------------------------------------------------------ navigation
    def nav(self, key):
        w = self.win
        if key == "back":
            w.hide_backstage()
            return
        if key == "save":
            w.hide_backstage()
            w.cmd("save")
            return
        if key == "close":
            w.hide_backstage()
            w.cmd("close")
            return
        self.current = key
        for k, b in self.nav_buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("active")
        old = self.stack.get_child_by_name(key)
        if old is not None:
            self.stack.remove(old)
        page = getattr(self, "page_" + key)()
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(page)
        sw.show_all()
        self.stack.add_named(sw, key)
        self.stack.set_visible_child_name(key)

    def _page(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(36)
        box.pack_start(_heading(title), False, False, 0)
        return box

    def _run(self, *cmd):
        self.win.hide_backstage()
        self.win.cmd(*cmd)

    # ------------------------------------------------------------ pieces
    def _tile(self, name, transparent, cb):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("fd-bs-tile")
        b.set_name("tile-" + ("transparent" if transparent else "blank"))
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        area = Gtk.DrawingArea()
        area.set_size_request(194, 120)
        area.connect("draw", self._draw_tile, transparent)
        v.pack_start(area, False, False, 0)
        v.pack_start(Gtk.Label(label=name), False, False, 0)
        b.add(v)
        b.connect("clicked", lambda *_: cb())
        return b

    @staticmethod
    def _draw_tile(area, cr, transparent):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        if transparent:
            s = 8
            for y in range(0, h, s):
                for x in range(0, w, s):
                    g = 1.0 if ((x // s) + (y // s)) % 2 == 0 else 0.82
                    cr.set_source_rgb(g, g, g)
                    cr.rectangle(x, y, s, s)
                    cr.fill()
        else:
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
        cr.set_source_rgb(0.6, 0.6, 0.6)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()
        return False

    def _recent_list(self, limit=50, filter_text=""):
        lb = Gtk.ListBox()
        lb.get_style_context().add_class("fd-bs-recent")
        lb.set_name("recent")
        ft = filter_text.lower()
        n = 0
        for p in self.win.state.recent:
            if ft and ft not in os.path.basename(p).lower():
                continue
            row = Gtk.Box(spacing=12)
            row.set_border_width(4)
            th = _thumb(p) if os.path.exists(p) else None
            row.pack_start(th or Icon("open", 32), False, False, 0)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=os.path.basename(p), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            folder = Gtk.Label(label=os.path.dirname(p), xalign=0)
            folder.get_style_context().add_class("dim-label")
            folder.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            txt.pack_start(name, False, False, 0)
            txt.pack_start(folder, False, False, 0)
            row.pack_start(txt, True, True, 0)
            try:
                row.pack_start(Gtk.Label(label=_when(os.path.getmtime(p))), False, False, 8)
            except OSError:
                row.pack_start(Gtk.Label(label="Not found"), False, False, 8)
            row.path = p
            lb.add(row)
            n += 1
            if n >= limit:
                break
        lb.connect("row-activated", lambda _lb, r: self._open_path(r.get_child().path))
        if n == 0:
            lab = Gtk.Label(label="No recent pictures yet." if not ft else "Nothing matches.", xalign=0)
            lab.get_style_context().add_class("dim-label")
            lb.add(lab)
        return lb

    def _filtered_recent(self, limit):
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.pack_start(self._recent_list(limit), False, False, 0)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search")
        search.set_size_request(400, -1)
        search.set_halign(Gtk.Align.START)

        def filt(e):
            for c in holder.get_children():
                holder.remove(c)
            holder.pack_start(self._recent_list(limit, e.get_text()), False, False, 0)
            holder.show_all()
        search.connect("search-changed", filt)
        return search, holder

    def _open_path(self, p):
        if not p:
            return
        self.win.hide_backstage()
        self.win.open_path(p)

    # ------------------------------------------------------------ pages
    def page_home(self):
        h = datetime.datetime.now().hour
        box = self._page("Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening"))
        strip = Gtk.Box(spacing=14)
        strip.pack_start(self._tile("Blank picture", False, lambda: self._run("new")), False, False, 0)
        strip.pack_start(self._tile("Transparent picture", True, lambda: self._run("new_transparent")), False, False, 0)
        box.pack_start(strip, False, False, 0)
        search, holder = self._filtered_recent(12)
        box.pack_start(search, False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Recent</b>")
        box.pack_start(lab, False, False, 0)
        box.pack_start(holder, False, False, 0)
        return box

    def page_new(self):
        box = self._page("New")
        flow = Gtk.Box(spacing=14)
        flow.pack_start(self._tile("Blank picture", False, lambda: self._run("new")), False, False, 0)
        flow.pack_start(self._tile("Transparent picture", True, lambda: self._run("new_transparent")), False, False, 0)
        box.pack_start(flow, False, False, 0)
        return box

    def page_open(self):
        box = self._page("Open")
        h = Gtk.Box(spacing=30)
        places = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        places.set_size_request(240, -1)
        for label, icon, cb in (("Recent", "open", lambda: None),
                                ("This PC", "props", lambda: self._run("open")),
                                ("Browse", "open", lambda: self._run("open"))):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("fd-bs-place")
            b.set_name("place-" + label.lower().replace(" ", ""))
            hb = Gtk.Box(spacing=10)
            hb.pack_start(Icon(icon, 32), False, False, 0)
            hb.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            b.add(hb)
            b.connect("clicked", lambda _b, cb=cb: cb())
            places.pack_start(b, False, False, 0)
        h.pack_start(places, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search, holder = self._filtered_recent(50)
        right.pack_start(search, False, False, 0)
        right.pack_start(holder, True, True, 0)
        h.pack_start(right, True, True, 0)
        box.pack_start(h, True, True, 0)
        return box

    def page_info(self):
        box = self._page("Info")
        w = self.win
        doc = w.doc
        name = os.path.basename(w.path) if w.path else "Untitled"
        box.pack_start(_heading(name, "fd-bs-sub"), False, False, 0)
        if w.path:
            loc = Gtk.Label(label=os.path.dirname(w.path), xalign=0)
            loc.get_style_context().add_class("dim-label")
            box.pack_start(loc, False, False, 0)
        grid = Gtk.Grid(column_spacing=24, row_spacing=6)
        grid.set_name("info")
        rows = []
        if doc is not None:
            rows.append(("Picture size", "%d × %d pixels" % (doc.width, doc.height)))
            rows.append(("Layers", str(doc.layer_count())))
        if w.path and os.path.exists(w.path):
            st = os.stat(w.path)
            rows.append(("Size on disk", "%.1f KB" % (st.st_size / 1024)))
            rows.append(("Last modified", datetime.datetime.fromtimestamp(st.st_mtime).strftime("%-m/%-d/%Y %-I:%M %p")))
        for i, (k, v) in enumerate(rows):
            grid.attach(Gtk.Label(label=k, xalign=0), 0, i, 1, 1)
            grid.attach(Gtk.Label(label=v, xalign=0), 1, i, 1, 1)
        box.pack_start(grid, False, False, 12)
        btns = Gtk.Box(spacing=8)
        for label, cmd in (("Image properties…", "properties"), ("Resize…", "resize")):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("fd-bs-button")
            b.connect("clicked", lambda _b, c=cmd: self._run(c))
            btns.pack_start(b, False, False, 0)
        box.pack_start(btns, False, False, 0)
        return box

    def page_saveas(self):
        box = self._page("Save As")
        for ext, label, note in SAVE_FORMATS:
            b = Gtk.Button()
            b.get_style_context().add_class("fd-bs-button")
            b.set_name("saveas" + ext)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            v.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            d = Gtk.Label(label=note, xalign=0)
            d.get_style_context().add_class("dim-label")
            v.pack_start(d, False, False, 0)
            b.add(v)
            b.set_size_request(380, -1)
            b.set_halign(Gtk.Align.START)
            b.connect("clicked", lambda _b, e=ext: self._run("save_as", e))
            box.pack_start(b, False, False, 0)
        other = Gtk.Button(label="Other formats… (F12)")
        other.get_style_context().add_class("fd-bs-button")
        other.set_halign(Gtk.Align.START)
        other.connect("clicked", lambda *_: self._run("save_as"))
        box.pack_start(other, False, False, 6)
        return box

    def page_print(self):
        from . import pagesetup as PS
        box = self._page("Print")
        w = self.win
        h = Gtk.Box(spacing=30)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pb = Gtk.Button(label="Print…")
        pb.get_style_context().add_class("fd-primary")
        pb.set_name("print")
        pb.set_size_request(120, 40)
        pb.set_halign(Gtk.Align.START)
        pb.connect("clicked", lambda *_: self._run("print"))
        left.pack_start(pb, False, False, 0)
        head = Gtk.Label(label="Page setup", xalign=0)
        head.get_style_context().add_class("fd-bs-sub")
        left.pack_start(head, False, False, 6)
        self.print_preview = PS.Preview(w)
        self.page_setup = PS.PageSetup(w, on_change=lambda s: self.print_preview.refresh())
        left.pack_start(self.page_setup, False, False, 0)
        h.pack_start(left, False, False, 0)
        h.pack_start(self.print_preview, False, False, 0)
        box.pack_start(h, False, False, 0)
        return box

    def page_export(self):
        box = self._page("Export")
        b = Gtk.Button()
        b.get_style_context().add_class("fd-bs-button")
        b.set_name("wallpaper")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.pack_start(Gtk.Label(label="Set as desktop background", xalign=0), False, False, 0)
        d = Gtk.Label(label="Saves a copy and makes it the desktop picture", xalign=0)
        d.get_style_context().add_class("dim-label")
        v.pack_start(d, False, False, 0)
        b.add(v)
        b.set_size_request(380, -1)
        b.set_halign(Gtk.Align.START)
        b.connect("clicked", lambda *_: self._run("wallpaper"))
        box.pack_start(b, False, False, 0)
        return box

    def page_about(self):
        box = self._page("About")
        logo = Gtk.Image.new_from_icon_name("folio-draw", Gtk.IconSize.DIALOG)
        logo.set_halign(Gtk.Align.START)
        box.pack_start(logo, False, False, 0)
        name = Gtk.Label(xalign=0)
        name.set_markup("<b>%s</b>  %s" % (APP_NAME, __version__))
        name.set_name("about-version")
        box.pack_start(name, False, False, 0)
        for t in ("A simple drawing program for quick mock-ups, with layers and real transparency.",
                  "Part of the Folio suite.", "MIT licence. Written from scratch, including every file format."):
            lab = Gtk.Label(label=t, xalign=0)
            lab.set_line_wrap(True)
            box.pack_start(lab, False, False, 0)
        return box
