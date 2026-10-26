"""History panel: every step of the document, newest last; click one to go back (or forward)
to it in one go."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class HistoryPanel(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self._sig = None
        self._sync = False
        self.get_style_context().add_class("fd-layers")
        self.set_size_request(232, 190)
        title = Gtk.Label(label="History", xalign=0)
        title.get_style_context().add_class("fd-layers-title")
        self.pack_start(title, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._activated)
        self.list.connect("row-selected", lambda lb, row: (not self._sync and row is not None) and self._activated(lb, row))
        sw.add(self.list)
        self.scroller = sw
        self.pack_start(sw, True, True, 0)

    def refresh(self, force=False):
        doc = self.win.doc
        if doc is None or not self.get_visible():
            return
        undo, redo = doc.history()
        sig = (tuple(undo), tuple(redo))
        if sig == self._sig and not force:
            return
        self._sig = sig
        self._sync = True
        for c in self.list.get_children():
            self.list.remove(c)
        names = ["Open"] + [u or "Edit" for u in undo] + [r or "Edit" for r in redo]
        cur = len(undo)
        for i, n in enumerate(names):
            row = Gtk.ListBoxRow()
            lab = Gtk.Label(label=n, xalign=0, margin_start=10, margin_top=3, margin_bottom=3)
            if i > cur:
                lab.get_style_context().add_class("dim-label")   # undone: still there to redo
            row.add(lab)
            row.step = i
            self.list.add(row)
        self.list.show_all()
        self.list.select_row(self.list.get_row_at_index(cur))
        self._sync = False
        # keep the current step in view
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper())

    def rows(self):
        """(label, undone) of each step, the first being the document as opened."""
        out = []
        for row in self.list.get_children():
            lab = row.get_child()
            out.append((lab.get_text(), lab.get_style_context().has_class("dim-label")))
        return out

    def go_to(self, step):
        """Undo or redo until the document is as it was after `step` (0 = as opened)."""
        w = self.win
        undo, redo = w.doc.history()
        n = step - len(undo)
        for _ in range(abs(n)):
            w.cmd("undo" if n < 0 else "redo")
        self.refresh(force=True)

    def _activated(self, lb, row):
        if self._sync or row is None:
            return
        self.go_to(row.step)
