"""Main window: title bar, ribbon, canvas, layers panel, status bar and every command."""

import json
import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from .tools import SEL_TOOLS
from . import __version__
from . import dialogs as D
from . import engine as E
from .canvas import ZOOM_STEPS, Canvas
from .icons import Icon
from .layers import LayersPanel
from .history import HistoryPanel
from .ribbon import Ribbon

APP_NAME = "Folio Draw"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "folio-draw")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "folio-draw")

# extension -> (engine format, label)
SAVE_FORMATS = {
    ".png": (E.FMT_PNG, "PNG picture"),
    ".jpg": (E.FMT_JPEG, "JPEG picture"),
    ".jpeg": (E.FMT_JPEG, "JPEG picture"),
    ".bmp": (E.FMT_BMP24, "24-bit bitmap"),
    ".gif": (E.FMT_GIF, "GIF picture"),
    ".webp": (E.FMT_WEBP, "WebP picture"),
    ".tif": (E.FMT_TIFF, "TIFF picture"),
    ".tiff": (E.FMT_TIFF, "TIFF picture"),
    ".ico": (E.FMT_ICO, "Windows icon"),
    ".ora": (E.FMT_ORA, "OpenRaster (keeps layers)"),
}
OPEN_PATTERNS = ["*.png", "*.jpg", "*.jpeg", "*.jpe", "*.jfif", "*.bmp", "*.dib", "*.gif", "*.ora",
                 "*.webp", "*.tif", "*.tiff", "*.ico", "*.cur",
                 "*.PNG", "*.JPG", "*.JPEG", "*.BMP", "*.GIF", "*.ORA", "*.WEBP", "*.TIF", "*.TIFF", "*.ICO", "*.CUR"]
# a still format and the animated form it can take when layers become frames
ANIM_FORMATS = {E.FMT_GIF: E.FMT_GIF_ANIM, E.FMT_WEBP: E.FMT_WEBP_ANIM}
# commands that may run while an animation preview is playing
PLAYBACK_SAFE = {"play", "zoom_in", "zoom_out", "zoom_100", "zoom_fit", "view_toggle", "fullscreen", "gif_loop", "about"}
FLAT_ALPHA_FORMATS = {E.FMT_PNG, E.FMT_ORA, E.FMT_GIF, E.FMT_GIF_ANIM, E.FMT_WEBP, E.FMT_WEBP_ANIM, E.FMT_TIFF, E.FMT_ICO}

# Quick Access Toolbar: command -> (icon, tooltip), in menu order
QAT_COMMANDS = {
    "new": ("new", "New (Ctrl+N)"),
    "open": ("open", "Open (Ctrl+O)"),
    "save": ("save", "Save (Ctrl+S)"),
    "undo": ("undo", "Undo (Ctrl+Z)"),
    "redo": ("redo", "Redo (Ctrl+Y)"),
    "print": ("print", "Print (Ctrl+P)"),
}
QAT_NAMES = {"new": "New", "open": "Open", "save": "Save", "undo": "Undo", "redo": "Redo", "print": "Print"}

# what the search box (Alt+Q) finds: label, command (with arguments), shortcut
SEARCH_COMMANDS = [
    ("New picture", ("new",), "Ctrl+N"), ("New transparent picture", ("new_transparent",), ""),
    ("Open", ("open",), "Ctrl+O"), ("Save", ("save",), "Ctrl+S"), ("Save as", ("save_as",), "F12"),
    ("Print", ("print",), "Ctrl+P"), ("Set as desktop background", ("wallpaper",), ""),
    ("Image properties", ("properties",), "Ctrl+E"), ("Close picture", ("close",), ""),
    ("Page setup", ("page_setup",), ""),
    ("Undo", ("undo",), "Ctrl+Z"), ("Redo", ("redo",), "Ctrl+Y"),
    ("Cut", ("cut",), "Ctrl+X"), ("Copy", ("copy",), "Ctrl+C"), ("Paste", ("paste",), "Ctrl+V"),
    ("Paste as new layer", ("paste_layer",), "Ctrl+Shift+V"), ("Paste from file", ("paste_from",), ""),
    ("Select all", ("select_all",), "Ctrl+A"), ("Invert selection", ("invert_selection",), ""),
    ("Delete selection", ("delete",), "Delete"), ("Crop", ("crop",), "Ctrl+Shift+X"),
    ("Resize and skew", ("resize",), "Ctrl+W"), ("Rotate right 90°", ("rot_cw",), ""),
    ("Rotate left 90°", ("rot_ccw",), ""), ("Rotate 180°", ("rot_180",), ""),
    ("Rotate by angle", ("rotate_angle",), "Ctrl+Shift+R"), ("Flip horizontal", ("flip_h",), ""),
    ("Flip vertical", ("flip_v",), ""), ("Invert colors", ("invert_colors",), "Ctrl+Shift+I"),
    ("Brightness and contrast", ("adjust", "brightness"), ""), ("Hue and saturation", ("adjust", "huesat"), ""),
    ("Greyscale", ("greyscale",), ""), ("Sepia", ("sepia",), ""), ("Blur", ("adjust", "blur"), ""),
    ("Sharpen", ("adjust", "sharpen"), ""),
    ("Edit colors", ("edit_colors",), ""), ("Stabilizer", ("stabilizer_open",), ""),
    ("Pencil", ("tool", "pencil"), ""), ("Fill with color", ("tool", "fill"), ""), ("Text", ("tool", "text"), ""),
    ("Eraser", ("tool", "eraser"), ""), ("Color picker", ("tool", "picker"), ""), ("Magnifier", ("tool", "zoom"), ""),
    ("Brushes", ("tool", "brush"), ""), ("Rectangular selection", ("tool", "select"), ""),
    ("Free-form selection", ("tool", "freeselect"), ""), ("Polygon selection", ("tool", "polyselect"), ""),
    ("Magic wand", ("tool", "wand"), ""),
    ("Zoom in", ("zoom_in",), "Ctrl+Page Up"), ("Zoom out", ("zoom_out",), "Ctrl+Page Down"),
    ("Zoom to 100%", ("zoom_100",), "Ctrl+1"), ("Fit to window", ("zoom_fit",), "Ctrl+0"),
    ("Rulers", ("view_toggle", "rulers"), "Ctrl+R"), ("Gridlines", ("view_toggle", "grid"), "Ctrl+G"),
    ("Status bar", ("view_toggle", "statusbar"), ""), ("Layers panel", ("view_toggle", "layers"), "F7"),
    ("History panel", ("view_toggle", "history"), "F8"),
    ("Full screen", ("fullscreen",), "F11"),
    ("New layer", ("layer_add",), "Ctrl+Shift+N"), ("Duplicate layer", ("layer_dup",), "Ctrl+Shift+D"),
    ("Delete layer", ("layer_delete",), ""), ("Merge layer down", ("layer_merge",), "Ctrl+M"),
    ("Flatten image", ("flatten",), ""), ("Layer properties", ("layer_props",), "F4"),
    ("Frames view", ("frames_view",), ""), ("Play animation", ("play",), "Space"),
    ("About Folio Draw", ("about",), ""),
]


# what each command and tool is called in the History panel
CMD_LABELS = {tuple(cmd): label for label, cmd, _ in SEARCH_COMMANDS}
CMD_LABELS.update({("delete",): "Delete", ("cut",): "Cut", ("paste",): "Paste", ("crop",): "Crop",
                   ("layer_add",): "New layer", ("adjust",): "Adjustment"})
TOOL_LABELS = {"pencil": "Pencil", "brush": "Brush", "eraser": "Eraser", "fill": "Fill with color", "text": "Text",
               "shape": "Shape", "select": "Move selection", "freeselect": "Move selection",
               "polyselect": "Move selection", "wand": "Move selection"}


class State:
    def __init__(self):
        self.tool = "pencil"
        self.prev_tool = "pencil"
        self.brush = "brush"
        self.shape = "rect"
        self.color1 = (0, 0, 0, 255)
        self.color2 = (255, 255, 255, 255)
        self.active_well = 1
        self.custom_colors = [(0, 0, 0, 0)] + [None] * 9
        self.sizes = {"pencil": 1, "brush": 8, "eraser": 16, "shape": 3}
        self.tolerance = 0
        self.outline = True
        self.fill_shape = False
        self.transparent_sel = False
        self.sample_all = False
        self.wand_tolerance = 25        # percent
        self.wand_contiguous = True
        self.page = {}                  # Page setup (see pagesetup.DEFAULTS)
        self.view = {"rulers": False, "grid": False, "statusbar": True, "layers": True, "history": False}
        self.recent_colors = []         # the last colours painted with, newest first
        self.stabilizer = {t: [0, 0, 0] for t in ("pencil", "brush", "eraser")}  # StreamLine, Stabilization, Motion filtering
        self.font_family = "Sans"
        self.font_size = 14.0
        self.bold = self.italic = self.underline = self.strike = False
        self.text_opaque = False
        self.recent = []
        self.qat = ["save", "undo", "redo"]

    KEYS = ["brush", "shape", "color1", "color2", "custom_colors", "sizes", "tolerance", "outline", "fill_shape",
            "transparent_sel", "sample_all", "wand_tolerance", "wand_contiguous", "recent_colors", "stabilizer", "page", "view", "font_family", "font_size", "text_opaque", "recent", "qat"]

    def load(self):
        try:
            with open(os.path.join(CONFIG_DIR, "settings.json")) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for k in self.KEYS:
            if k not in data:
                continue
            v = data[k]
            try:
                if k in ("color1", "color2"):
                    v = tuple(int(x) for x in v)[:4]
                    if len(v) != 4:
                        continue
                elif k == "custom_colors":
                    v = [tuple(c) if c else None for c in v][:10]
                    v += [None] * (10 - len(v))
                    v[0] = (0, 0, 0, 0)
                elif k in ("sizes", "view"):
                    base = dict(getattr(self, k))
                    base.update({kk: vv for kk, vv in v.items() if kk in base})
                    v = base
                elif k == "recent":
                    v = [p for p in v if isinstance(p, str)][:10]
                elif k == "stabilizer":
                    base = {t: list(vs) for t, vs in self.stabilizer.items()}
                    for t, vs in (v.items() if isinstance(v, dict) else ()):
                        if t in base and isinstance(vs, list) and len(vs) == 3:
                            base[t] = [max(0, min(100, int(x))) for x in vs]
                    v = base
                elif k == "recent_colors":
                    v = [tuple(c) for c in v if isinstance(c, (list, tuple)) and len(c) == 4][:10]
                elif k == "qat":
                    v = [c for c in v if c in QAT_COMMANDS]
                setattr(self, k, v)
            except (TypeError, ValueError, AttributeError):
                pass

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = os.path.join(CONFIG_DIR, "settings.json.tmp")
            with open(tmp, "w") as f:
                json.dump({k: getattr(self, k) for k in self.KEYS}, f, indent=1)
            os.replace(tmp, os.path.join(CONFIG_DIR, "settings.json"))
        except OSError:
            pass


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, path=None):
        super().__init__(application=app)
        self.app = app
        self.state = State()
        self.state.load()
        self.doc = None
        self._action = None
        self.path = None
        self.saved_changes = 0
        self.saved_at = None
        self.warned_flatten = False
        self.set_default_size(1200, 800)
        self.set_icon_name("folio-draw")

        # ---- title bar: Quick Access on the left, title in the middle, search and window buttons right
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_decoration_layout(":minimize,maximize,close")
        hb.get_style_context().add_class("fd-header")
        self.qat_box = Gtk.Box(spacing=0)
        self.qa_buttons = {}
        for cmd, (icon, tip) in QAT_COMMANDS.items():
            b = Gtk.Button()
            b.add(Icon(icon, 16, on_dark=True))
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, c=cmd: self.cmd(c))
            b.set_no_show_all(True)
            b.get_child().show()
            self.qat_box.pack_start(b, False, False, 0)
            self.qa_buttons[cmd] = b
        self.qat_menu_btn = Gtk.MenuButton()
        self.qat_menu_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.qat_menu_btn.set_tooltip_text("Customize Quick Access Toolbar")
        self.qat_menu_btn.add(Gtk.Label(label="▾"))
        self.qat_menu = Gtk.Menu()
        self.qat_menu_btn.set_popup(self.qat_menu)
        self.qat_menu.connect("show", lambda *_: self._build_qat_menu())
        self.qat_box.pack_start(self.qat_menu_btn, False, False, 0)
        hb.pack_start(self.qat_box)
        self.title_label = Gtk.Label()
        hb.set_custom_title(self.title_label)
        self.search = Gtk.SearchEntry()
        self.search.get_style_context().add_class("fd-search")
        self.search.set_placeholder_text("Search (Alt+Q)")
        self.search.set_size_request(240, -1)
        self.search.set_valign(Gtk.Align.CENTER)
        self._setup_search()
        hb.pack_end(self.search)
        self.set_titlebar(hb)
        self.headerbar = hb

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # the window body: the document view, or the File view over it; KeyTips float above both
        self.body = Gtk.Stack()
        self.body.set_transition_type(Gtk.StackTransitionType.NONE)
        self.body.add_named(root, "main")
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.body)
        self.add(self.overlay)
        self.canvas = Canvas(self)
        self.ribbon = Ribbon(self)
        self.ribbon.set_vexpand(False)
        root.pack_start(self.ribbon, False, False, 0)
        mid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        mid.pack_start(self.canvas, True, True, 0)
        self.layers = LayersPanel(self)
        self.layers.set_hexpand(False)
        self.history = HistoryPanel(self)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.pack_start(self.layers, True, True, 0)
        side.pack_start(self.history, False, False, 0)
        mid.pack_start(side, False, False, 0)
        root.pack_start(mid, True, True, 0)
        root.pack_start(self._status_bar(), False, False, 0)

        self.connect("key-press-event", self._key)
        self.connect("delete-event", self._on_delete)
        self.connect("window-state-event", self._window_state)
        self.fullscreen_on = False
        self.playing = False
        self._play_timer = None
        self._play_restore = None
        self.gif_mode = None  # "anim" / "flat" once chosen for this document

        # drag and drop files onto the window
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self._drop)

        from .backstage import Backstage
        from .keytips import KeyTips
        self.backstage = Backstage(self)
        self.body.add_named(self.backstage, "backstage")
        self.keytips = KeyTips(self)
        self._alt_alone = False
        self.connect("key-release-event", self._key_release)
        self.connect("button-press-event", lambda *_: (self.keytips.leave() if self.keytips.active else None, False)[1])
        self.show_all()
        self.body.set_visible_child_name("main")
        self._apply_qat()
        self.ribbon.tab_buttons["text"].hide()
        if path:
            if not self.open_path(path, ask=False):
                self.new_document()
        else:
            self.new_document()
        self.apply_view()
        self.ribbon.refresh()
        self.canvas.area.grab_focus()

    # ------------------------------------------------------------------ status bar
    # ------------------------------------------------------------------ Quick Access, search, File view
    def qat_order(self):
        return [c for c in QAT_COMMANDS if c in self.state.qat]

    def _apply_qat(self):
        for cmd, b in self.qa_buttons.items():
            b.set_visible(cmd in self.state.qat)

    def _build_qat_menu(self):
        for c in self.qat_menu.get_children():
            self.qat_menu.remove(c)
        title = Gtk.MenuItem(label="Customize Quick Access Toolbar")
        title.set_sensitive(False)
        self.qat_menu.append(title)
        for cmd in QAT_COMMANDS:
            mi = Gtk.CheckMenuItem(label=QAT_NAMES[cmd])
            mi.set_active(cmd in self.state.qat)
            mi.connect("toggled", lambda m, c=cmd: self.set_qat(c, m.get_active()))
            self.qat_menu.append(mi)
        self.qat_menu.show_all()

    def set_qat(self, cmd, on):
        q = [c for c in self.state.qat if c != cmd]
        if on:
            q.append(cmd)
        self.state.qat = [c for c in QAT_COMMANDS if c in q]
        self.state.save()
        self._apply_qat()

    def _setup_search(self):
        store = Gtk.ListStore(str, str, int)
        for i, (label, _cmd, keys) in enumerate(SEARCH_COMMANDS):
            store.append([label, keys, i])
        comp = Gtk.EntryCompletion()
        comp.set_model(store)
        comp.set_text_column(0)
        comp.set_inline_completion(False)
        comp.set_popup_completion(True)
        comp.set_minimum_key_length(1)

        def match(c, key, it):
            return key.lower() in store[it][0].lower()
        comp.set_match_func(match)
        keys = Gtk.CellRendererText()
        keys.set_property("foreground", "#777777")
        comp.pack_end(keys, False)
        comp.add_attribute(keys, "text", 1)
        comp.connect("match-selected", lambda c, m, it: (self.run_search(m[it][2]), True)[1])
        self.search.set_completion(comp)
        self.search.connect("activate", lambda e: self.run_search(self.search_matches(e.get_text())[0] if self.search_matches(e.get_text()) else None))
        self.search.connect("key-press-event", self._search_key)

    def search_matches(self, text):
        t = (text or "").strip().lower()
        if not t:
            return []
        starts = [i for i, c in enumerate(SEARCH_COMMANDS) if c[0].lower().startswith(t)]
        rest = [i for i, c in enumerate(SEARCH_COMMANDS) if t in c[0].lower() and i not in starts]
        return starts + rest

    def run_search(self, index):
        if index is None:
            return
        self.search.set_text("")
        self.canvas.area.grab_focus()
        cmd = SEARCH_COMMANDS[index][1]
        if cmd[0] == "tool":
            self.set_tool(cmd[1])
            self.ribbon.refresh()
        elif cmd[0] == "view_toggle":
            self.cmd("view_toggle", cmd[1])
        else:
            self.cmd(*cmd)

    def _search_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.search.set_text("")
            self.canvas.area.grab_focus()
            return True
        return False

    def show_backstage(self, page="home"):
        self.keytips.leave()
        self.finalize_pending()
        self.body.set_visible_child_name("backstage")
        self.backstage.nav(page)

    def hide_backstage(self):
        self.body.set_visible_child_name("main")
        self.canvas.area.grab_focus()

    def backstage_open(self):
        return self.body.get_visible_child_name() == "backstage"

    def c_close(self):
        if self.confirm_discard():
            self.new_document()

    def _key_release(self, w, ev):
        name = (Gdk.keyval_name(ev.keyval) or "").lower()
        if name in ("alt_l", "alt_r") and self._alt_alone and not self.backstage_open():
            self._alt_alone = False
            if self.keytips.active:
                self.keytips.leave()
            else:
                self.keytips.start()
            return True
        return False

    def _status_bar(self):
        sb = Gtk.Box(spacing=18)
        sb.get_style_context().add_class("fd-status")
        self.pos_label = Gtk.Label(xalign=0)
        self.pos_label.set_width_chars(14)
        self.sel_label = Gtk.Label(xalign=0)
        self.sel_label.set_width_chars(14)
        self.size_label = Gtk.Label(xalign=0)
        self.size_label.set_width_chars(16)
        self.layer_label = Gtk.Label(xalign=0)
        for icon, lbl in (("pencil", self.pos_label), ("select", self.sel_label), ("resize", self.size_label), ("layers", self.layer_label)):
            b = Gtk.Box(spacing=4)
            b.pack_start(Icon(icon, 14), False, False, 0)
            b.pack_start(lbl, False, False, 0)
            sb.pack_start(b, False, False, 0)
        self.hint_label = Gtk.Label(xalign=0)
        self.hint_label.set_ellipsize(3)
        self.hint_label.set_markup("")
        sb.pack_start(self.hint_label, True, True, 0)
        self._hint_timer = None
        zb = Gtk.Box(spacing=2)
        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.set_width_chars(6)
        zout = Gtk.Button(label="−")
        zout.set_tooltip_text("Zoom out")
        zout.connect("clicked", lambda *_: self.canvas.zoom_step(-1))
        zin = Gtk.Button(label="+")
        zin.set_tooltip_text("Zoom in")
        zin.connect("clicked", lambda *_: self.canvas.zoom_step(1))
        self.zoom_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, len(ZOOM_STEPS) - 1, 1)
        self.zoom_scale.set_draw_value(False)
        self.zoom_scale.set_size_request(140, -1)
        self.zoom_scale.get_style_context().add_class("fd-accent")
        self._zoom_sync = False
        self.zoom_scale.connect("value-changed", self._zoom_scale_changed)
        for w in (self.zoom_label, zout, self.zoom_scale, zin):
            zb.pack_start(w, False, False, 0)
        sb.pack_end(zb, False, False, 0)
        self.status_bar = sb
        return sb

    def hint(self, text, seconds=7):
        self.hint_label.set_markup("<span foreground='#800000'>%s</span>" % GLib.markup_escape_text(text))
        if self._hint_timer:
            GLib.source_remove(self._hint_timer)

        def clear():
            self._hint_timer = None
            self.hint_label.set_text("")
            return False
        self._hint_timer = GLib.timeout_add_seconds(seconds, clear)

    def _zoom_scale_changed(self, s):
        if self._zoom_sync:
            return
        self.canvas.set_zoom(ZOOM_STEPS[int(round(s.get_value()))])

    def on_zoom_changed(self):
        z = self.canvas.z
        self.zoom_label.set_text("%g%%" % round(z * 100, 1))
        self._zoom_sync = True
        idx = min(range(len(ZOOM_STEPS)), key=lambda i: abs(ZOOM_STEPS[i] - z))
        self.zoom_scale.set_value(idx)
        self._zoom_sync = False

    def on_pointer(self, x, y):
        if x is None or self.doc is None:
            self.pos_label.set_text("")
            return
        ix, iy = int(x // 1), int(y // 1)
        if 0 <= ix < self.doc.width and 0 <= iy < self.doc.height:
            self.pos_label.set_text("%d, %dpx" % (ix, iy))
        else:
            self.pos_label.set_text("")

    def on_selection_size(self, w, h):
        self.sel_label.set_text("%d × %dpx" % (round(w), round(h)))

    def on_doc_changed(self):
        doc = self.doc
        if doc is None:
            return
        self.size_label.set_text("%d × %dpx" % (doc.width, doc.height))
        fr = doc.float_rect()
        b = fr or doc.sel_bounds()
        if b and not (self.canvas.drag and self.canvas.drag.get("kind") in ("marquee", "canvas", "floatresize")):
            self.sel_label.set_text("%d × %dpx" % (b[2], b[3]))
        elif not self.canvas.drag:
            self.sel_label.set_text("")
        self.update_title()

    def after_edit(self):
        """Called after any completed change: refresh layers, undo buttons, title."""
        self.layers.refresh_thumbs_soon()
        self.refresh_state()

    def refresh_state(self):
        doc = self.doc
        if doc is None:
            return
        # name a new step after what made it
        undo, _ = doc.history()
        if undo and not undo[-1]:
            doc.label_last(self._action or TOOL_LABELS.get(self.state.tool, "Edit"))
        self._action = None
        self.history.refresh()
        busy = self.canvas.pending is not None or self.canvas.text is not None
        self.qa_buttons["undo"].set_sensitive(doc.can_undo() or busy)
        self.qa_buttons["redo"].set_sensitive(doc.can_redo() and not busy)
        has_sel = bool(doc.sel_bounds() or doc.float_rect())
        self.ribbon.refresh_edit_state(has_sel, True)
        n = doc.layer_count()
        self.layer_label.set_text("Layer %d of %d: %s" % (doc.active + 1, n, doc.layer_name(doc.active)))
        self.update_title()

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        dirty = self.doc is not None and self.doc.changes != self.saved_changes
        t = ("*" if dirty else "") + name + " - " + APP_NAME
        self.title_label.set_markup("<span foreground='white'>%s</span>" % GLib.markup_escape_text(t))
        self.set_title(t)

    # ------------------------------------------------------------------ tool & colour state
    def set_tool(self, tool):
        st = self.state
        self.finalize_pending()
        if tool not in SEL_TOOLS and self.doc is not None:
            if self.doc.float_rect():
                self.doc.float_commit()
            if self.doc.sel_bounds():
                self.doc.sel_none()
            self.canvas.sel_path = None
            self.canvas.sync()
        if tool != "picker" and st.tool != "picker":
            st.prev_tool = st.tool
        elif tool == "picker" and st.tool != "picker":
            st.prev_tool = st.tool
        st.tool = tool
        self.canvas._cursor_name = None
        self.ribbon.refresh()
        self.refresh_state()
        self.canvas.area.queue_draw()

    def set_brush(self, kind):
        self.state.brush = kind
        self.set_tool("brush")

    def set_shape(self, kind):
        self.state.shape = kind
        self.set_tool("shape")

    def set_color(self, well, color):
        st = self.state
        if well == 1:
            st.color1 = tuple(color)
        else:
            st.color2 = tuple(color)
        self.ribbon.refresh()
        self.canvas.render_pending()
        self.canvas.text_style_changed()

    def size_key(self):
        t = self.state.tool
        if t in ("pencil", "brush", "eraser", "shape", "fill"):
            return t
        return "brush"

    def current_size(self):
        k = self.size_key()
        return self.state.sizes.get(k, 3)

    def set_size(self, v):
        k = self.size_key()
        if k == "fill":
            self.state.tolerance = max(0, min(100, int(v)))
            return
        self.state.sizes[k] = max(1, min(500, int(v)))
        self.canvas.render_pending()
        self.canvas.area.queue_draw()

    def on_text_mode(self, on):
        self.ribbon.set_text_tab(on)
        self.refresh_state()

    def finalize_pending(self):
        if self.doc is not None:
            self.canvas.finalize()

    # ------------------------------------------------------------------ document lifecycle
    def set_document(self, doc, path):
        self.stop_playback()
        old = self.doc
        self.doc = doc
        self.path = path
        self.saved_changes = doc.changes
        self.saved_at = os.path.getmtime(path) if path and os.path.exists(path) else None
        self.warned_flatten = False
        self.gif_mode = "anim" if (doc.layer_count() > 1 and doc.frames_view) else None
        if self._hint_timer:
            GLib.source_remove(self._hint_timer)
            self._hint_timer = None
        self.hint_label.set_text("")
        doc.set_sample_all(self.state.sample_all)
        self.canvas.reset_document()
        if old is not None:
            old.close()
        self.layers.rebuild()
        self.refresh_state()
        GLib.idle_add(self._initial_zoom)

    def _initial_zoom(self):
        doc = self.doc
        aw = self.canvas.area.get_allocated_width()
        ah = self.canvas.area.get_allocated_height()
        if aw > 1 and (doc.width > aw - 30 or doc.height > ah - 30):
            self.canvas.zoom_fit()
        else:
            self.canvas.set_zoom(1.0, (0, 0))
            self.canvas.hadj.set_value(0)
            self.canvas.vadj.set_value(0)
        return False

    def is_dirty(self):
        return self.doc is not None and self.doc.changes != self.saved_changes

    def confirm_discard(self):
        self.finalize_pending()
        if not self.is_dirty():
            return True
        r = D.ask_save_changes(self, os.path.basename(self.path) if self.path else "Untitled")
        if r == "save":
            return self.cmd_save()
        return r == "discard"

    def new_document(self, transparent=False):
        w, h = 1152, 648
        self.set_document(E.Document.new(w, h, (0, 0, 0, 0) if transparent else (255, 255, 255, 255)), None)

    def open_path(self, path, ask=True):
        if ask and not self.confirm_discard():
            return False
        try:
            doc = E.Document.load(path)
        except E.EngineError as e:
            msg = str(e)
            if msg == "unsupported":
                msg = "This file isn't a picture Folio Draw can open. Supported formats are PNG, JPEG, BMP, GIF, WebP, TIFF, icons and OpenRaster."
            D.message(self, "Folio Draw can't open %s" % os.path.basename(path), msg, Gtk.MessageType.ERROR)
            return False
        self.set_document(doc, os.path.abspath(path))
        self.add_recent(self.path)
        if doc.frames_view and doc.layer_count() > 1:
            self.hint("Opened %d frames, one per layer. View \u25b8 Play previews the animation." % doc.layer_count(), 10)
        if doc.frames_truncated:
            D.message(self, "Only part of the animation was opened",
                      "This animation has more frames than fit in memory. The first %d frames were opened as layers." % doc.layer_count())
        self.ribbon.refresh()
        return True

    def add_recent(self, path):
        r = [p for p in self.state.recent if p != path]
        self.state.recent = [path] + r[:9]
        self.state.save()
        try:
            Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())
        except Exception:
            pass

    def save_to(self, path, fmt):
        doc = self.doc
        self.finalize_pending()
        self.stop_playback()
        if fmt in ANIM_FORMATS and doc.layer_count() > 1:
            kind = "GIF" if fmt == E.FMT_GIF else "WebP"
            if self.gif_mode is None:
                r = D.ask_choice(self, "Save as an animated %s?" % kind,
                                 "This picture has %d layers. A %s can play them as an animation, one layer per frame, "
                                 "starting with the bottom layer. Frame times are set in each layer's properties." % (doc.layer_count(), kind),
                                 ["Cancel", "Save one flattened picture", "Save as animation"], default=2)
                if r < 1:
                    return False
                self.gif_mode = "anim" if r == 2 else "flat"
            if self.gif_mode == "anim":
                fmt = ANIM_FORMATS[fmt]
        if fmt not in (E.FMT_ORA, E.FMT_GIF_ANIM, E.FMT_WEBP_ANIM) and doc.layer_count() > 1 and not self.warned_flatten:
            r = D.ask_choice(self, "Save a flattened copy?",
                             "This picture has %d layers. %s files can only hold one, so the layers will be merged in the saved file "
                             "(they stay separate here). Choose OpenRaster to keep the layers." % (doc.layer_count(), os.path.splitext(path)[1].upper().lstrip(".")),
                             ["Cancel", "Save as OpenRaster instead", "Save flattened"], default=2)
            if r == 1:
                return self.cmd_save_as(".ora")
            if r != 2:
                return False
            self.warned_flatten = True
        if fmt not in FLAT_ALPHA_FORMATS and doc.has_transparency():
            r = D.ask_choice(self, "Transparency will be lost",
                             "%s files can't store see-through areas; they will be filled with white. "
                             "Save as PNG to keep transparency." % os.path.splitext(path)[1].upper().lstrip("."),
                             ["Cancel", "Save as PNG instead", "Save anyway"], default=2)
            if r == 1:
                return self.cmd_save_as(".png")
            if r != 2:
                return False
        try:
            doc.save(path, fmt)
        except E.EngineError as e:
            D.message(self, "Couldn't save the picture", str(e), Gtk.MessageType.ERROR)
            return False
        self.path = os.path.abspath(path)
        self.saved_changes = doc.changes
        self.saved_at = time.time()
        self.add_recent(self.path)
        self.update_title()
        return True

    def cmd_save(self):
        if self.path:
            ext = os.path.splitext(self.path)[1].lower()
            if ext in SAVE_FORMATS:
                return self.save_to(self.path, SAVE_FORMATS[ext][0])
        return self.cmd_save_as()

    def cmd_save_as(self, ext=None):
        self.finalize_pending()
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        sb = dlg.add_button("Save", Gtk.ResponseType.ACCEPT)
        sb.get_style_context().add_class("fd-primary")
        dlg.set_do_overwrite_confirmation(True)
        filters = {}
        for e in (".png", ".jpg", ".bmp", ".gif", ".webp", ".tif", ".ico", ".ora"):
            f = Gtk.FileFilter()
            f.set_name("%s (*%s)" % (SAVE_FORMATS[e][1], e))
            f.add_pattern("*" + e)
            f.add_pattern("*" + e.upper())
            if e == ".jpg":
                f.add_pattern("*.jpeg")
            if e == ".tif":
                f.add_pattern("*.tiff")
            dlg.add_filter(f)
            filters[e] = f
        if ext is None:
            cur = os.path.splitext(self.path)[1].lower() if self.path else ".png"
            ext = {".jpeg": ".jpg", ".tiff": ".tif"}.get(cur, cur)
            ext = ext if ext in filters else ".png"
        dlg.set_filter(filters[ext])
        base = os.path.splitext(os.path.basename(self.path))[0] if self.path else "Untitled"
        if self.path:
            dlg.set_current_folder(os.path.dirname(self.path))
        else:
            pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
            if pics and os.path.isdir(pics):
                dlg.set_current_folder(pics)
        dlg.set_current_name(base + ext)

        def filter_changed(*_):
            f = dlg.get_filter()
            new_ext = next((e for e, ff in filters.items() if ff == f), None)
            name = dlg.get_current_name() or base
            if new_ext:
                dlg.set_current_name(os.path.splitext(name)[0] + new_ext)
        dlg.connect("notify::filter", filter_changed)
        ok = False
        while True:
            if dlg.run() != Gtk.ResponseType.ACCEPT:
                break
            path = dlg.get_filename()
            e = os.path.splitext(path)[1].lower()
            if e not in SAVE_FORMATS:
                f = dlg.get_filter()
                e = next((k for k, ff in filters.items() if ff == f), ".png")
                path += e
            dlg.hide()
            ok = self.save_to(path, SAVE_FORMATS[e][0])
            break
        dlg.destroy()
        return ok

    def cmd_open(self):
        if not self.confirm_discard():
            return
        dlg = Gtk.FileChooserDialog(title="Open", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ob = dlg.add_button("Open", Gtk.ResponseType.ACCEPT)
        ob.get_style_context().add_class("fd-primary")
        f = Gtk.FileFilter()
        f.set_name("All picture files")
        for p in OPEN_PATTERNS:
            f.add_pattern(p)
        dlg.add_filter(f)
        fa = Gtk.FileFilter()
        fa.set_name("All files")
        fa.add_pattern("*")
        dlg.add_filter(fa)
        if self.path:
            dlg.set_current_folder(os.path.dirname(self.path))
        else:
            pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
            if pics and os.path.isdir(pics):
                dlg.set_current_folder(pics)
        r = dlg.run()
        path = dlg.get_filename()
        dlg.destroy()
        if r == Gtk.ResponseType.ACCEPT and path:
            self.open_path(path, ask=False)

    def _drop(self, w, ctx, x, y, data, info, t):
        uris = data.get_uris()
        if not uris:
            return
        path = Gio.File.new_for_uri(uris[0]).get_path()
        if path:
            GLib.idle_add(lambda: self.open_path(path) and False)

    def _on_delete(self, *_):
        if not self.confirm_discard():
            return True
        self.state.save()
        return False

    def _window_state(self, w, ev):
        self.fullscreen_on = bool(ev.new_window_state & Gdk.WindowState.FULLSCREEN)

    # ------------------------------------------------------------------ File menu
    def popup_selection_menu(self, ev):
        from .ribbon import make_menu
        has = bool(self.doc.sel_bounds() or self.doc.float_rect())
        m = make_menu([
            ("Cut", "cut", lambda: self.cmd("cut"), "Ctrl+X"),
            ("Copy", "copy", lambda: self.cmd("copy"), "Ctrl+C"),
            ("Paste", "paste", lambda: self.cmd("paste"), "Ctrl+V"),
            None,
            ("Select all", "selall", lambda: self.cmd("select_all"), "Ctrl+A"),
            ("Invert selection", "selinvert", lambda: self.cmd("invert_selection")),
            ("Delete", "delete", lambda: self.cmd("delete"), "Delete"),
            None,
            ("Crop", "crop", lambda: self.cmd("crop"), "Ctrl+Shift+X"),
            ("Rotate right 90°", "rotate", lambda: self.cmd("rot_cw")),
            ("Rotate by angle…", "rotate", lambda: self.cmd("rotate_angle"), "Ctrl+Shift+R"),
            ("Flip horizontal", "flip_h", lambda: self.cmd("flip_h")),
            ("Flip vertical", "flip_v", lambda: self.cmd("flip_v")),
            ("Resize…", "resize", lambda: self.cmd("resize"), "Ctrl+W"),
            ("Invert colors", "invert", lambda: self.cmd("invert_colors"), "Ctrl+Shift+I"),
        ])
        for it in m.get_children():
            if getattr(it, "item_label", "") in ("Cut", "Copy", "Delete", "Crop") and not has:
                it.set_sensitive(False)
        m.attach_to_widget(self.canvas.area, None)
        m.popup_at_pointer(ev)

    # ------------------------------------------------------------------ commands
    def c_stabilizer(self, i, v):
        st = self.state
        if st.tool in st.stabilizer:
            st.stabilizer[st.tool][i] = max(0, min(100, int(v)))
            st.save()

    def c_stabilizer_open(self):
        if self.state.tool not in self.state.stabilizer:
            self.set_tool("brush")
        self.ribbon.show_tab("home")
        self.ribbon.size_btn.set_active(True)

    def note_color(self, c):
        """A colour was painted with: it goes to the front of the Recent colours."""
        c = tuple(c)
        r = [x for x in self.state.recent_colors if tuple(x) != c]
        self.state.recent_colors = [c] + r[:9]
        self.ribbon.refresh_recent()

    def cmd(self, name, *args):
        fn = getattr(self, "c_" + name, None)
        if fn is None:
            return
        if name not in ("undo", "redo"):
            self._action = CMD_LABELS.get((name,) + tuple(args)) or CMD_LABELS.get((name,)) or name.replace("_", " ").capitalize()
        if self.playing and name not in PLAYBACK_SAFE:
            self.stop_playback()
        fn(*args)
        self.ribbon.refresh()
        self.refresh_state()

    def c_new(self):
        if self.confirm_discard():
            self.new_document()

    def c_new_transparent(self):
        if self.confirm_discard():
            self.new_document(transparent=True)

    def c_open(self):
        self.cmd_open()

    def c_save(self):
        self.cmd_save()

    def c_save_as(self, ext=None):
        self.cmd_save_as(ext)

    def c_exit(self):
        if self._on_delete() is False:
            self.destroy()

    def c_about(self):
        D.about(self, __version__)

    def c_undo(self):
        cv = self.canvas
        if cv.text is not None:
            cv.text_undo()
            return
        if cv.pending is not None:
            cv.cancel_pending()
            self.after_edit()
            return
        if self.doc.undo():
            cv.sel_path = None
            cv.sync()
            self.layers.refresh()
            self.after_edit()

    def c_redo(self):
        cv = self.canvas
        if cv.text is not None:
            cv.text_undo(redo=True)
            return
        self.finalize_pending()
        if self.doc.redo():
            cv.sel_path = None
            cv.sync()
            self.layers.refresh()
            self.after_edit()

    # ---- clipboard
    def _clipboard(self):
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def c_copy(self, cut=False):
        self.finalize_pending()
        got = self.doc.clip_extract()
        if not got:
            return False
        w, h, data = got
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
        self._clipboard().set_image(pb)
        self._clipboard().store()
        return True

    def c_cut(self):
        if self.c_copy():
            self.c_delete()

    def c_delete(self):
        self.finalize_pending()
        if self.doc.sel_delete():
            self.canvas.sel_path = None
            self.canvas.sync()
            self.after_edit()

    def _pixbuf_rgba(self, pb):
        if not pb.get_has_alpha():
            pb = pb.add_alpha(False, 0, 0, 0)
        w, h, rs = pb.get_width(), pb.get_height(), pb.get_rowstride()
        raw = pb.get_pixels()
        if rs == w * 4:
            return w, h, bytes(raw[: w * h * 4])
        return w, h, b"".join(bytes(raw[y * rs: y * rs + w * 4]) for y in range(h))

    def c_paste(self, as_layer=False):
        self.finalize_pending()
        pb = self._clipboard().wait_for_image()
        if pb is None:
            # files copied in a file manager arrive as URIs
            uris = self._clipboard().wait_for_uris()
            if uris:
                p = Gio.File.new_for_uri(uris[0]).get_path()
                if p:
                    self.paste_file(p, as_layer)
            return
        w, h, data = self._pixbuf_rgba(pb)
        self.paste_pixels(w, h, data, as_layer)

    def c_paste_layer(self):
        self.c_paste(as_layer=True)

    def c_paste_from(self):
        self.finalize_pending()
        dlg = Gtk.FileChooserDialog(title="Paste From", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Open", Gtk.ResponseType.ACCEPT)
        f = Gtk.FileFilter()
        f.set_name("All picture files")
        for p in OPEN_PATTERNS:
            f.add_pattern(p)
        dlg.add_filter(f)
        r = dlg.run()
        path = dlg.get_filename()
        dlg.destroy()
        if r == Gtk.ResponseType.ACCEPT and path:
            self.paste_file(path, False)

    def paste_file(self, path, as_layer):
        try:
            tmp = E.Document.load(path)
        except E.EngineError as e:
            D.message(self, "Couldn't paste the picture", str(e), Gtk.MessageType.ERROR)
            return
        w, h, data = tmp.width, tmp.height, tmp.flatten_rgba()
        tmp.close()
        self.paste_pixels(w, h, data, as_layer)

    def paste_pixels(self, w, h, data, as_layer=False):
        doc = self.doc
        if w > doc.width or h > doc.height:
            r = D.ask_choice(self, "The picture you are pasting is larger than the canvas",
                             "Would you like the canvas to be enlarged?", ["Cancel", "Don't enlarge", "Enlarge canvas"], default=2)
            if r < 1:
                return
            if r == 2:
                doc.canvas_size(max(w, doc.width), max(h, doc.height), 0, 0)
                self.canvas.sync(full=True)
        if as_layer:
            doc.layer_add("Pasted layer")
            self.layers.rebuild()
        # paste at the top-left of the visible area
        vx, vy = self.canvas.to_doc(0, 0)
        x = max(0, min(int(vx), doc.width - w)) if w <= doc.width else 0
        y = max(0, min(int(vy), doc.height - h)) if h <= doc.height else 0
        doc.float_from_rgba(w, h, data, x, y)
        self.canvas.sel_path = None
        if self.state.tool not in SEL_TOOLS:
            self.state.prev_tool = self.state.tool
            self.state.tool = "select"
        self.canvas.sync()
        self.after_edit()

    # ---- selection
    def c_select_all(self):
        self.finalize_pending()
        if self.state.tool not in SEL_TOOLS:
            self.state.tool = "select"
        self.doc.sel_all()
        self.canvas.sel_path = None
        self.canvas.sync()

    def c_invert_selection(self):
        self.finalize_pending()
        if self.state.tool not in SEL_TOOLS:
            self.state.tool = "select"
        self.doc.sel_invert()
        self.canvas.sel_path = None
        self.canvas.sync()

    def c_toggle_transparent_sel(self, on=None):
        # an explicit value from the check item; refresh() then re-syncs the item to the same
        # value, which emits nothing (a bare toggle here would ping-pong with the item forever)
        self.state.transparent_sel = (not self.state.transparent_sel) if on is None else bool(on)
        if self.state.transparent_sel and self.doc.float_rect():
            self.doc.float_color_key(self.state.color2, 0)
            self.canvas.sync()

    def c_wand_tolerance(self, pct):
        self.state.wand_tolerance = max(0, min(100, int(pct)))
        self.state.save()
        self.ribbon.refresh()

    def c_toggle_wand_contiguous(self, on=None):
        self.state.wand_contiguous = (not self.state.wand_contiguous) if on is None else bool(on)
        self.state.save()
        self.ribbon.refresh()

    def c_toggle_sample_all(self, on=None):
        self.state.sample_all = (not self.state.sample_all) if on is None else bool(on)
        self.doc.set_sample_all(self.state.sample_all)
        self.hint_label.set_text("Copy, Transparent selection and Fill now use all visible layers."
                                 if self.state.sample_all else
                                 "Copy, Transparent selection and Fill now use the active layer.")

    def c_crop(self):
        self.finalize_pending()
        if self.doc.crop_to_selection():
            self.canvas.sel_path = None
            self.canvas.sync(full=True)
            self.after_edit()

    # ---- image
    def _transform(self, kind):
        self.finalize_pending()
        doc = self.doc
        if doc.float_rect():
            doc.float_transform(kind)
        elif doc.sel_bounds():
            self.canvas._lift(True)
            doc.float_transform(kind)
        else:
            doc.image_transform(kind)
            self.canvas.sel_path = None
        self.canvas.sync(full=True)
        self.after_edit()

    def c_rot_cw(self):
        self._transform(E.ROT_CW)

    def c_rot_ccw(self):
        self._transform(E.ROT_CCW)

    def c_rot_180(self):
        self._transform(E.ROT_180)

    def c_rotate_angle(self):
        """Rotate the selection, or the whole image when nothing is selected, by any angle."""
        self.finalize_pending()
        doc = self.doc
        fr = doc.float_rect()
        sb = doc.sel_bounds()
        if fr:
            what, rect = "selection", fr
        elif sb:
            what = "selection"
            rect = (sb[0], sb[1], sb[2] - sb[0], sb[3] - sb[1])
        else:
            what, rect = "image", (0, 0, doc.width, doc.height)
        if not hasattr(self, "_rotate_last"):
            self._rotate_last = {}
        # Paint-style: an opaque picture gets its corners filled; a transparent one stays transparent
        bottom_opaque = what == "image" and min(doc.layer_rgba(0)[3::4]) == 255
        r = D.rotate_angle(self, self.canvas.surf, rect, what, bottom_opaque, self._rotate_last)
        if not r:
            return
        deg, smooth, fill = r
        if what == "selection":
            if not fr:
                self.canvas._lift(True)
            doc.float_rotate(deg, smooth)
        else:
            doc.image_rotate(deg, smooth, self.state.color2 if fill else None)
            self.canvas.sel_path = None
        self.canvas.sync(full=True)
        self.after_edit()

    def c_flip_h(self):
        self._transform(E.FLIP_H)

    def c_flip_v(self):
        self._transform(E.FLIP_V)

    def c_invert_colors(self):
        self.finalize_pending()
        self.doc.invert_colors()
        self.canvas.sync()
        self.after_edit()

    # ---- adjustments: on the floating selection, else the active layer inside the selection
    ADJ_KINDS = {"brightness": E.ADJ_BRIGHT_CONTRAST, "huesat": E.ADJ_HUE_SAT, "blur": E.ADJ_BLUR,
                 "sharpen": E.ADJ_SHARPEN}

    def c_adjust(self, kind):
        self.finalize_pending()
        doc = self.doc
        code = self.ADJ_KINDS[kind]
        if not hasattr(self, "_adjust_last"):
            self._adjust_last = {}
        last = self._adjust_last.setdefault(kind, {})

        def preview(vals):
            if vals is None:
                doc.adjust_cancel()
            else:
                doc.adjust_preview(code, *vals)
            self.canvas.sync()
        vals = D.adjust(self, kind, preview, last)
        if vals is None:
            doc.adjust_cancel()
        else:
            doc.adjust_preview(code, *vals)
            doc.adjust_end()
        self.canvas.sync()
        self.after_edit()

    def c_greyscale(self):
        self.finalize_pending()
        self.doc.adjust(E.ADJ_GREY)
        self.canvas.sync()
        self.after_edit()

    def c_sepia(self):
        self.finalize_pending()
        self.doc.adjust(E.ADJ_SEPIA)
        self.canvas.sync()
        self.after_edit()

    def c_resize(self):
        self.finalize_pending()
        doc = self.doc
        if doc.sel_bounds() and not doc.float_rect():
            self.canvas._lift(True)
        fr = doc.float_rect()
        if fr:
            r = D.resize_skew(self, fr[2], fr[3], "selection")
            if r:
                doc.float_set_rect(fr[0], fr[1], r[0], r[1])
        else:
            r = D.resize_skew(self, doc.width, doc.height)
            if r:
                w, h, sx, sy, smooth = r
                if (w, h) != (doc.width, doc.height):
                    doc.image_resize(w, h, smooth)
                if sx or sy:
                    doc.image_skew(sx, sy)
                self.canvas.sel_path = None
        self.canvas.sync(full=True)
        self.after_edit()

    def c_properties(self):
        self.finalize_pending()
        r = D.image_properties(self, self.doc, self.path, self.saved_at)
        if r and r != (self.doc.width, self.doc.height):
            self.doc.canvas_size(r[0], r[1], 0, 0)
            self.canvas.sync(full=True)
            self.after_edit()

    def c_canvas_resize(self, w, h):
        self.finalize_pending()
        self.doc.canvas_size(w, h, 0, 0)
        self.canvas.sync(full=True)
        self.after_edit()

    # ---- shapes / size
    def c_outline(self, on):
        self.state.outline = on
        if not on and not self.state.fill_shape:
            self.state.fill_shape = True
        self.canvas.render_pending()

    def c_fillmode(self, on):
        self.state.fill_shape = on
        if not on and not self.state.outline:
            self.state.outline = True
        self.canvas.render_pending()

    def c_size_step(self, d):
        if self.size_key() == "fill":
            self.state.tolerance = max(0, min(100, self.state.tolerance + d * 5))
        else:
            self.set_size(self.current_size() + d)

    def c_edit_colors(self):
        st = self.state
        cur = st.color1 if st.active_well == 1 else st.color2
        r = D.edit_colors(self, cur, st.custom_colors)
        if r:
            color, custom = r
            st.custom_colors = custom
            self.set_color(st.active_well, color)
            st.save()

    # ---- text
    def c_text_font(self, fam):
        if fam:
            self.state.font_family = fam
            self.canvas.text_style_changed()

    def c_text_size(self, v):
        self.state.font_size = float(v)
        self.canvas.text_style_changed()

    def c_text_style(self, key, on):
        setattr(self.state, key, on)
        self.canvas.text_style_changed()

    def c_text_opaque(self, on):
        self.state.text_opaque = on
        self.canvas.text_style_changed()

    def c_text_commit(self):
        self.canvas.text_commit()

    # ---- layers
    def c_layer_add(self):
        self.finalize_pending()
        n = self.doc.layer_count()
        self.doc.layer_add("Layer %d" % (n + 1))
        self.canvas.sync()
        self.layers.rebuild()
        self.after_edit()

    def c_layer_dup(self):
        self.finalize_pending()
        self.doc.layer_duplicate()
        self.canvas.sync()
        self.layers.rebuild()
        self.after_edit()

    def c_layer_delete(self):
        self.finalize_pending()
        if self.doc.layer_delete():
            self.canvas.sync()
            self.layers.rebuild()
            self.after_edit()

    def c_layer_up(self):
        self.finalize_pending()
        a = self.doc.active
        if self.doc.layer_move(a, a + 1):
            self.canvas.sync()
            self.layers.rebuild()
            self.after_edit()

    def c_layer_down(self):
        self.finalize_pending()
        a = self.doc.active
        if a > 0 and self.doc.layer_move(a, a - 1):
            self.canvas.sync()
            self.layers.rebuild()
            self.after_edit()

    def c_layer_merge(self):
        self.finalize_pending()
        if self.doc.layer_merge_down():
            self.canvas.sync()
            self.layers.rebuild()
            self.after_edit()

    def c_flatten(self):
        self.finalize_pending()
        self.doc.flatten()
        self.canvas.sync()
        self.layers.rebuild()
        self.after_edit()

    def c_layer_props(self):
        self.finalize_pending()
        doc = self.doc
        i = doc.active
        p = doc.layer_props(i)
        r = D.layer_properties(self, doc.layer_name(i), p["opacity"], p["visible"], p["blend"], p["delay"])
        if r:
            name, op, vis, blend, delay = r
            doc.layer_set(i, name=name, opacity=op, visible=vis, blend=blend, delay=delay, record=True)
            self.canvas.sync()
            self.layers.refresh()
            self.after_edit()

    # ---- view
    def c_zoom_in(self):
        self.canvas.zoom_step(1)

    def c_zoom_out(self):
        self.canvas.zoom_step(-1)

    def c_zoom_100(self):
        self.canvas.set_zoom(1.0)

    def c_zoom_fit(self):
        self.canvas.zoom_fit()

    def c_view_toggle(self, key, on=None):
        st = self.state
        st.view[key] = (not st.view[key]) if on is None else on
        self.apply_view()
        st.save()

    def apply_view(self):
        v = self.state.view
        self.canvas.show_rulers(v["rulers"])
        self.status_bar.set_visible(v["statusbar"])
        self.layers.set_visible(v["layers"])
        if v["layers"]:
            self.layers.refresh()
        self.history.set_visible(v.get("history", False))
        self.history.refresh(force=True)
        self.canvas.area.queue_draw()

    # ---- animation
    def c_frames_view(self, on=None):
        self.finalize_pending()
        doc = self.doc
        on = (not doc.frames_view) if on is None else on
        if not on:
            self.stop_playback()
        doc.set_frames_view(on)
        self.canvas.sync(full=True)

    def c_frame_step(self, d):
        self.finalize_pending()
        self.stop_playback()
        doc = self.doc
        n = doc.layer_count()
        if n < 2:
            return
        if not doc.frames_view:
            doc.set_frames_view(True)
        doc.set_active((doc.active + d) % n)
        self.canvas.sync(full=True)
        self.layers.refresh()
        self.hint("Frame %d of %d" % (doc.active + 1, n), 3)

    def c_play(self, on=None):
        on = (not self.playing) if on is None else on
        if on:
            self.start_playback()
        else:
            self.stop_playback()

    def c_gif_loop(self, idx):
        val = {0: 0, 1: -1, 2: 1, 3: 2, 4: 4, 5: 9}.get(idx, 0)
        if val != self.doc.gif_loop:
            self.doc.set_gif_loop(val)
            # a setting of the file, like a change: make it saveable
            self.saved_changes = -1
            self.update_title()

    def start_playback(self):
        doc = self.doc
        if self.playing or doc.layer_count() < 2:
            return
        self.finalize_pending()
        doc.float_commit()
        self._play_restore = (doc.frames_view, doc.active)
        doc.set_frames_view(True)
        self.playing = True
        self._play_index = 0
        self._play_next()
        self.ribbon.refresh()

    def _play_next(self):
        doc = self.doc
        if not self.playing or doc is None:
            return False
        n = doc.layer_count()
        i = self._play_index % n
        doc.show_frame(i)
        self.canvas.sync(full=True)
        self.layer_label.set_text("Frame %d of %d" % (i + 1, n))
        delay = doc.layer_props(i)["delay"] or 100
        self._play_index = i + 1
        self._play_timer = GLib.timeout_add(max(20, delay), self._play_next)
        return False

    def stop_playback(self):
        if not self.playing:
            return
        self.playing = False
        if self._play_timer:
            GLib.source_remove(self._play_timer)
            self._play_timer = None
        doc = self.doc
        if doc is not None and self._play_restore is not None:
            view, active = self._play_restore
            doc.show_frame(min(active, doc.layer_count() - 1))
            doc.set_frames_view(view)
            self.canvas.sync(full=True)
        self._play_restore = None
        self.ribbon.refresh()
        self.refresh_state()

    def c_fullscreen(self):
        if self.fullscreen_on:
            self.unfullscreen()
        else:
            self.fullscreen()

    # ---- print & wallpaper
    def _print_surface(self):
        import cairo
        doc = self.doc
        data = bytearray(doc.flatten_rgba())
        # cairo wants premultiplied BGRA
        w, h = doc.width, doc.height
        for i in range(0, len(data), 4):
            r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            data[i] = b * a // 255
            data[i + 1] = g * a // 255
            data[i + 2] = r * a // 255
        return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, w, h, w * 4)

    def print_operation(self):
        """A print job laid out by Page setup (paper, orientation, margins, scaling)."""
        from . import pagesetup as PS
        s = PS.settings(self.state)
        surf = self._print_surface()
        pages = PS.layout(s, self.doc.width, self.doc.height)
        op = Gtk.PrintOperation()
        op.set_n_pages(len(pages))
        op.set_job_name(os.path.basename(self.path) if self.path else "Untitled")
        setup = Gtk.PageSetup()
        pw, ph = PS.paper_size(dict(s, landscape=False))
        setup.set_paper_size(Gtk.PaperSize.new_custom(s["paper"], s["paper"], pw, ph, Gtk.Unit.MM))
        setup.set_orientation(Gtk.PageOrientation.LANDSCAPE if s["landscape"] else Gtk.PageOrientation.PORTRAIT)
        for side in ("top", "right", "bottom", "left"):
            getattr(setup, "set_%s_margin" % side)(0, Gtk.Unit.MM)
        op.set_default_page_setup(setup)
        op.set_use_full_page(True)
        op.set_unit(Gtk.Unit.MM)

        def draw_page(op, ctx, n):
            PS.draw_page(ctx.get_cairo_context(), surf, pages[n])
        op.connect("draw-page", draw_page)
        op.pages = pages
        return op

    def c_print(self):
        self.finalize_pending()
        op = self.print_operation()
        try:
            op.run(Gtk.PrintOperationAction.PRINT_DIALOG, self)
        except GLib.Error as e:
            D.message(self, "Printing failed", str(e), Gtk.MessageType.ERROR)

    def c_page_setup(self):
        self.finalize_pending()
        from . import pagesetup as PS
        PS.page_setup_dialog(self)

    def c_wallpaper(self):
        self.finalize_pending()
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "wallpaper-%d.png" % int(time.time()))
        for old in os.listdir(DATA_DIR):
            if old.startswith("wallpaper-") and old.endswith(".png"):
                try:
                    os.remove(os.path.join(DATA_DIR, old))
                except OSError:
                    pass
        try:
            self.doc.save(path, E.FMT_PNG)
        except E.EngineError as e:
            D.message(self, "Couldn't set the background", str(e), Gtk.MessageType.ERROR)
            return
        src = Gio.SettingsSchemaSource.get_default()
        if src is None or src.lookup("org.gnome.desktop.background", True) is None:
            D.message(self, "Couldn't set the background", "This desktop doesn't offer a background setting Folio Draw can change.")
            return
        s = Gio.Settings.new("org.gnome.desktop.background")
        uri = Gio.File.new_for_path(path).get_uri()
        s.set_string("picture-uri", uri)
        if "picture-uri-dark" in s.list_keys():
            s.set_string("picture-uri-dark", uri)
        s.set_string("picture-options", "zoom")
        Gio.Settings.sync()

    # ------------------------------------------------------------------ keyboard
    def _key(self, w, ev):
        kv = ev.keyval
        name = (Gdk.keyval_name(Gdk.keyval_to_lower(kv)) or "").lower()
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        # a lone tap of Alt shows KeyTips (on release); any other key in between cancels that
        self._alt_alone = name in ("alt_l", "alt_r")
        if self.keytips.active:
            return self.keytips.key(ev)
        if self.backstage_open():
            if name == "escape":
                self.hide_backstage()
                return True
            return False
        if name == "f10" and not shift:
            self.keytips.start()
            return True
        if alt and name == "q":
            self.search.grab_focus()
            return True
        if alt and not ctrl and len(name) == 1 and name.isalnum():
            if self.keytips.start_with(name.upper()):
                return True
        cv = self.canvas
        focus = self.get_focus()
        in_text = cv.text is not None and focus is cv.text["view"]
        in_entry = isinstance(focus, (Gtk.Entry, Gtk.SpinButton)) and not in_text

        if in_text:
            if name == "escape":
                cv.text_cancel()
                return True
            if ctrl and name in ("b", "i", "u"):
                key = {"b": "bold", "i": "italic", "u": "underline"}[name]
                self.cmd("text_style", key, not getattr(self.state, key))
                return True
            if ctrl and name == "z":
                cv.text_undo(redo=shift)
                return True
            if ctrl and name == "y":
                cv.text_undo(redo=True)
                return True
            if ctrl and name in ("s",):
                self.cmd("save")
                return True
            return False  # let the text view have everything else
        if in_entry:
            return False

        if ctrl:
            table = {
                "n": ("layer_add",) if shift else ("new",), "o": ("open",), "s": ("save_as",) if shift else ("save",),
                "p": ("print",), "z": ("undo",), "y": ("redo",), "a": ("select_all",), "c": ("copy",), "x": ("crop",) if shift else ("cut",),
                "v": ("paste_layer",) if shift else ("paste",), "e": ("properties",), "w": ("resize",), "r": ("rotate_angle",) if shift else ("view_toggle", "rulers"),
                "g": ("view_toggle", "grid"), "i": ("invert_colors",) if shift else None, "m": ("layer_merge",),
                "d": ("layer_dup",) if shift else None, "page_up": ("zoom_in",), "page_down": ("zoom_out",),
                "plus": ("size_step", 1), "equal": ("size_step", 1), "kp_add": ("size_step", 1),
                "minus": ("size_step", -1), "kp_subtract": ("size_step", -1), "0": ("zoom_fit",), "1": ("zoom_100",),
            }
            if name == "z" and shift:
                self.cmd("redo")
                return True
            ent = table.get(name)
            if ent:
                self.cmd(*ent)
                return True
            return False
        if name == "space" and focus is cv.area:
            self.cmd("play")
            return True
        if name in ("comma", "period") and focus is cv.area:
            self.cmd("frame_step", -1 if name == "comma" else 1)
            return True
        if name == "f11":
            self.cmd("fullscreen")
            return True
        if name == "f12":
            self.cmd("save_as")
            return True
        if name == "f7":
            self.cmd("view_toggle", "layers")
            return True
        if name == "f8":
            self.cmd("view_toggle", "history")
            return True
        if name == "f4":
            self.cmd("layer_props")
            return True
        if name == "delete":
            self.cmd("delete")
            return True
        if name == "backspace" and cv.polysel is not None:
            # take back the last point of the polygon selection
            if len(cv.polysel["pts"]) > 1:
                cv.polysel["pts"].pop()
            else:
                cv.polysel = None
            cv.area.queue_draw()
            return True
        if name == "escape":
            if self.fullscreen_on and cv.drag is None and cv.pending is None and not self.doc.sel_bounds() and not self.doc.float_rect():
                self.unfullscreen()
                return True
            if cv.escape():
                self.refresh_state()
            return True
        if name in ("return", "kp_enter"):
            if cv.enter():
                self.refresh_state()
                return True
            return False
        arrows = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if name in arrows and focus is cv.area:
            dx, dy = arrows[name]
            if self.state.tool in SEL_TOOLS + ("shape",):
                if cv.nudge(dx * (10 if shift else 1), dy * (10 if shift else 1)):
                    return True
            cv.hadj.set_value(cv.hadj.get_value() + dx * 40)
            cv.vadj.set_value(cv.vadj.get_value() + dy * 40)
            return True
        return False
