"""Layers panel: visibility, thumbnails, opacity, blend mode and stack operations."""

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import engine as E
from .icons import Icon
from .ribbon import checker, small_button

TW, TH = 44, 32


class LayerRow(Gtk.ListBoxRow):
    def __init__(self, panel, index):
        super().__init__()
        self.index = index
        self.panel = panel
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.eye = Gtk.Button()
        self.eye.set_relief(Gtk.ReliefStyle.NONE)
        self.eye.get_style_context().add_class("fd-rbtn")
        self.eye_icon = Icon("eye", 16)
        self.eye.add(self.eye_icon)
        self.eye.set_tooltip_text("Show or hide this layer")
        self.eye.connect("clicked", lambda *_: panel.toggle_visible(self.index))
        box.pack_start(self.eye, False, False, 0)
        self.thumb = Gtk.DrawingArea()
        self.thumb.set_size_request(TW, TH)
        self.thumb.connect("draw", self._draw_thumb)
        box.pack_start(self.thumb, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.name = Gtk.Label(xalign=0)
        self.name.set_ellipsize(3)
        self.name.set_max_width_chars(14)
        self.info = Gtk.Label(xalign=0)
        self.info.get_style_context().add_class("dim-label")
        v.pack_start(self.name, False, False, 0)
        v.pack_start(self.info, False, False, 0)
        v.set_valign(1)
        box.pack_start(v, True, True, 0)
        self.add(box)
        self.thumb_surf = None
        self.update()

    def update(self):
        doc = self.panel.win.doc
        p = doc.layer_props(self.index)
        self.name.set_text(doc.layer_name(self.index))
        bits = []
        if p["opacity"] < 0.999:
            bits.append("%d%%" % round(p["opacity"] * 100))
        if p["blend"]:
            bits.append(E.BLEND_NAMES[p["blend"]])
        if p["delay"] > 0:
            bits.append("%d ms" % p["delay"])
        raw = doc.layer_text(self.index)
        if raw:
            kind = ""
            if raw.startswith('{"kind":"emb-shapes"'):
                kind = "Lettering" if '"lettering":true' in raw[-400:] or '"lettering":true' in raw[:400] else "Shapes"
            elif raw.startswith('{"kind":"emb-picture"'):
                kind = "Picture"
            bits.insert(0, kind or "Text")      # typed again with the Text tool
        self.info.set_text(" · ".join(bits) if bits else "")
        self.eye_icon.set_name_icon("eye" if p["visible"] else "eyeoff")
        self.name.set_opacity(1.0 if p["visible"] else 0.55)
        data = bytearray(doc.layer_thumb(self.index, TW, TH))
        self.thumb_surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, TW, TH, TW * 4)
        self._thumb_data = data
        self.thumb.queue_draw()

    def _draw_thumb(self, w, cr):
        checker(cr, 0, 0, TW, TH, 4)
        if self.thumb_surf:
            cr.set_source_surface(self.thumb_surf, 0, 0)
            cr.paint()
        cr.set_source_rgb(0.6, 0.55, 0.55)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, TW - 1, TH - 1)
        cr.stroke()
        return False


class LayersPanel(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self._sync = False
        self._opacity_recorded = False
        self._thumb_timer = None
        self.get_style_context().add_class("fd-layers")
        self.set_size_request(232, -1)
        title = Gtk.Label(label="Layers", xalign=0)
        title.get_style_context().add_class("fd-layers-title")
        self.pack_start(title, False, False, 0)

        grid = Gtk.Grid(row_spacing=4, column_spacing=6, margin_start=8, margin_end=8, margin_bottom=6)
        grid.attach(Gtk.Label(label="Blend", xalign=0), 0, 0, 1, 1)
        self.blend = Gtk.ComboBoxText()
        for n in E.BLEND_NAMES:
            self.blend.append_text(n)
        self.blend.set_tooltip_text("How this layer mixes with the layers below it")
        self.blend.connect("changed", self._blend_changed)
        self.blend.set_hexpand(True)
        grid.attach(self.blend, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="Opacity", xalign=0), 0, 1, 1, 1)
        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.opacity.set_draw_value(False)
        self.opacity.set_hexpand(True)
        self.opacity.get_style_context().add_class("fd-accent")
        self.opacity.connect("value-changed", self._opacity_changed)
        self.opacity.connect("button-release-event", self._opacity_done)
        self.opacity.connect("key-release-event", self._opacity_done)
        self.opacity_lbl = Gtk.Label(label="100%")
        self.opacity_lbl.set_width_chars(4)
        grid.attach(self.opacity, 1, 1, 1, 1)
        grid.attach(self.opacity_lbl, 2, 1, 1, 1)
        self.pack_start(grid, False, False, 0)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self._row_selected)
        self.list.connect("row-activated", lambda *_: self.win.cmd("layer_props"))
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.add(self.list)
        self.pack_start(sc, True, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, margin=4)
        self.buttons = {}
        for icon, tip, cmd in (("layeradd", "Add layer (Ctrl+Shift+N)", "layer_add"),
                               ("layerdup", "Duplicate layer (Ctrl+Shift+D)", "layer_dup"),
                               ("delete", "Delete layer", "layer_delete"),
                               ("up", "Move layer up", "layer_up"),
                               ("down", "Move layer down", "layer_down"),
                               ("merge", "Merge layer down (Ctrl+M)", "layer_merge"),
                               ("props", "Layer properties (F4)", "layer_props")):
            b = small_button(icon, None, tip)
            b.connect("clicked", lambda _b, c=cmd: self.win.cmd(c))
            bar.pack_start(b, False, False, 0)
            self.buttons[cmd] = b
        self.pack_end(bar, False, False, 0)
        self.pack_end(Gtk.Separator(), False, False, 0)

    # rows are listed top layer first
    def _row_for_layer(self, i):
        n = self.win.doc.layer_count()
        return self.list.get_row_at_index(n - 1 - i)

    def rebuild(self):
        doc = self.win.doc
        self._sync = True
        for c in self.list.get_children():
            c.destroy()
        n = doc.layer_count()
        for i in reversed(range(n)):
            self.list.add(LayerRow(self, i))
        self.list.show_all()
        row = self._row_for_layer(doc.active)
        if row:
            self.list.select_row(row)
        self._sync = False
        self.refresh_controls()

    def refresh(self):
        """Cheap refresh: rebuild if the stack shape changed, else just update rows."""
        doc = self.win.doc
        rows = self.list.get_children()
        if len(rows) != doc.layer_count():
            self.rebuild()
            return
        for r in rows:
            r.update()
        self._sync = True
        row = self._row_for_layer(doc.active)
        if row and self.list.get_selected_row() is not row:
            self.list.select_row(row)
        self._sync = False
        self.refresh_controls()

    def refresh_thumbs_soon(self):
        if self._thumb_timer:
            return

        def go():
            self._thumb_timer = None
            if self.get_visible():
                self.refresh()
            return False
        self._thumb_timer = GLib.timeout_add(250, go)

    def refresh_controls(self):
        doc = self.win.doc
        p = doc.layer_props(doc.active)
        self._sync = True
        self.blend.set_active(p["blend"])
        self.opacity.set_value(round(p["opacity"] * 100))
        self.opacity_lbl.set_text("%d%%" % round(p["opacity"] * 100))
        self._sync = False
        n = doc.layer_count()
        self.buttons["layer_delete"].set_sensitive(n > 1)
        self.buttons["layer_up"].set_sensitive(doc.active < n - 1)
        self.buttons["layer_down"].set_sensitive(doc.active > 0)
        self.buttons["layer_merge"].set_sensitive(doc.active > 0)

    def _row_selected(self, lb, row):
        if self._sync or row is None:
            return
        self.win.finalize_pending()
        self.win.doc.set_active(row.index)
        self.win.canvas.sync()
        self.refresh_controls()
        self.win.refresh_state()

    def toggle_visible(self, i):
        doc = self.win.doc
        p = doc.layer_props(i)
        doc.layer_set(i, visible=not p["visible"], record=True)
        self.win._action = "Show layer" if not p["visible"] else "Hide layer"
        self.win.canvas.sync()
        self.refresh()
        self.win.after_edit()

    def _blend_changed(self, combo):
        if self._sync:
            return
        doc = self.win.doc
        doc.layer_set(doc.active, blend=combo.get_active(), record=True)
        self.win._action = "Layer blend mode"
        self.win.canvas.sync()
        self.refresh()
        self.win.after_edit()

    def _opacity_changed(self, s):
        if self._sync:
            return
        doc = self.win.doc
        v = s.get_value() / 100.0
        doc.layer_set(doc.active, opacity=v, record=not self._opacity_recorded)
        self.win._action = "Layer opacity"
        self._opacity_recorded = True
        self.opacity_lbl.set_text("%d%%" % round(v * 100))
        self.win.canvas.sync()

    def _opacity_done(self, *_):
        if self._opacity_recorded:
            self._opacity_recorded = False
            self.refresh()
            self.win.after_edit()
        return False
