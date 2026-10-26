"""KeyTips: tap Alt (or F10) to show letters on the tabs, the Quick Access buttons and the
search box; type a tab's letter to see the letters of its controls; type those to press them.
Esc steps back a level; a click, or Alt again, leaves. Same rules as the rest of the suite."""

from gi.repository import Gdk, GLib, Gtk

TAB_TIPS = {"home": "H", "view": "W", "text": "JT"}


def press(widget):
    """Do what a click on the control would do."""
    if isinstance(widget, Gtk.MenuButton):
        widget.set_active(True)
    elif isinstance(widget, Gtk.RadioButton):
        widget.set_active(True)
    elif isinstance(widget, Gtk.CheckButton):
        widget.set_active(not widget.get_active())
    elif isinstance(widget, Gtk.ToggleButton):
        # tool, shape, brush and colour-well buttons pick; other toggles flip
        widget.set_active(True if getattr(widget, "keytip_pick", False) else not widget.get_active())
    elif isinstance(widget, Gtk.ComboBox):
        widget.popup()
    elif isinstance(widget, Gtk.Entry):
        widget.grab_focus()
    elif isinstance(widget, Gtk.Button):
        widget.clicked()


class KeyTips:
    def __init__(self, win):
        self.win = win
        self.active = False
        self.level = 0
        self.buffer = ""
        self.targets = {}
        self.badges = []
        self.layer = Gtk.Fixed()
        self.layer.set_halign(Gtk.Align.FILL)
        self.layer.set_valign(Gtk.Align.FILL)
        win.overlay.add_overlay(self.layer)
        win.overlay.set_overlay_pass_through(self.layer, True)
        self.layer.show()

    # ------------------------------------------------------------ badges
    def _clear(self):
        for b in self.badges:
            if isinstance(b, Gtk.Popover):
                b.popdown()
                b.destroy()
            else:
                self.layer.remove(b)
        self.badges = []

    def _pop_badge(self, widget, tip):
        """Badges for widgets outside the window body (title bar, popups)."""
        if not widget.get_mapped():
            return
        pop = Gtk.Popover.new(widget)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_modal(False)
        pop.get_style_context().add_class("fd-keytip-pop")
        lab = Gtk.Label(label=tip)
        lab.get_style_context().add_class("fd-keytip")
        pop.add(lab)
        lab.show()
        pop.popup()
        self.badges.append(pop)

    def _badge(self, widget, tip, below=False):
        if not widget.get_mapped():
            return
        alloc = widget.get_allocation()
        res = widget.translate_coordinates(self.win.overlay, 0, 0)
        if not res:
            return
        x, y = res
        lab = Gtk.Label(label=tip)
        lab.get_style_context().add_class("fd-keytip")
        lab.show()
        bw = 10 + 7 * len(tip)
        bx = x + max(0, (alloc.width - bw) // 2)
        by = y + alloc.height - 12 if below else y + max(0, alloc.height - 16)
        self.layer.put(lab, bx, by)
        self.badges.append(lab)

    def _filter(self):
        for b in self.badges:
            lab = b.get_child() if isinstance(b, Gtk.Popover) else b
            b.set_visible(lab.get_text().startswith(self.buffer))

    def tips(self):
        """The tips showing now (tests)."""
        out = []
        for b in self.badges:
            lab = b.get_child() if isinstance(b, Gtk.Popover) else b
            if b.get_visible():
                out.append(lab.get_text())
        return out

    # ------------------------------------------------------------ levels
    def start(self):
        self.leave()
        self.active = True
        self.level = 1
        self.buffer = ""
        self.targets = {}
        r = self.win.ribbon
        self.targets["F"] = ("file", None)
        self._badge(r.file_btn, "F", below=True)
        for name, b in r.tab_buttons.items():
            if not b.get_visible():
                continue
            tip = TAB_TIPS.get(name)
            if tip:
                self.targets[tip] = ("tab", name)
                self._badge(b, tip, below=True)
        for i, cmd in enumerate(self.win.qat_order(), start=1):
            b = self.win.qa_buttons.get(cmd)
            if b is not None and b.get_visible():
                self.targets[str(i)] = ("button", b)
                self._pop_badge(b, str(i))
        self.targets["Q"] = ("search", None)
        self._pop_badge(self.win.search, "Q")
        return True

    def start_with(self, letter):
        self.start()
        if not any(t.startswith(letter) for t in self.targets):
            self.leave()
            return False
        self._typed(letter)
        return True

    def show_tab(self, name):
        self._clear()
        self.level = 2
        self.buffer = ""
        self.targets = {}
        self.win.ribbon.show_tab(name)

        def place():
            used = set()
            for c in self.win.ribbon.page_controls.get(name, []):
                tip = getattr(c, "keytip", None)
                if not tip or tip in used or not c.get_mapped() or not c.get_sensitive():
                    continue
                used.add(tip)
                self.targets[tip] = ("control", c)
                self._badge(c, tip)
            return False
        GLib.idle_add(place)

    def leave(self):
        self.active = False
        self.level = 0
        self.buffer = ""
        self.targets = {}
        self._clear()

    # ------------------------------------------------------------ keys
    def key(self, event):
        kv = event.keyval
        name = (Gdk.keyval_name(kv) or "").lower()
        if name in ("alt_l", "alt_r", "shift_l", "shift_r", "control_l", "control_r"):
            return True
        if kv == Gdk.KEY_Escape:
            if self.level == 2:
                self.start()
            else:
                self.leave()
                self.win.canvas.area.grab_focus()
            return True
        if kv == Gdk.KEY_BackSpace:
            self.buffer = self.buffer[:-1]
            self._filter()
            return True
        ch = Gdk.keyval_to_unicode(Gdk.keyval_to_upper(kv))
        ch = chr(ch).upper() if ch else ""
        if not ch or not ch.isalnum():
            self.leave()
            return False
        self._typed(ch)
        return True

    def _typed(self, ch):
        self.buffer += ch
        hit = self.targets.get(self.buffer)
        if hit is None:
            if any(t.startswith(self.buffer) for t in self.targets):
                self._filter()
            else:
                self.buffer = self.buffer[:-1]
            return
        kind, obj = hit
        if kind == "tab":
            self.show_tab(obj)
        elif kind == "file":
            self.leave()
            self.win.show_backstage()
        elif kind == "search":
            self.leave()
            self.win.search.grab_focus()
        elif kind == "button":
            self.leave()
            obj.clicked()
        else:
            self.leave()
            GLib.idle_add(lambda: (press(obj), False)[1])
