"""X2-01: Folio Draw under a dark desktop theme and a loud coloured one. Every ribbon tab, the File
view pages, the panels and the Size menu keep Draw's own colours and stay readable.
Run under each theme: GTK_THEME=$(python3 themecheck.py dark|colour) python3 x201_audit.py
(theme_run.sh runs all three: dark, dark with Draw set to light, colour)."""
import os
import sys
import tempfile
import traceback

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="fd-cfg-")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="fd-data-")
os.environ["GSETTINGS_BACKEND"] = "memory"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import themecheck  # noqa: E402

if not os.environ.get("GTK_THEME"):
    os.environ.update(themecheck.theme_env("dark"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

ERRORS = []


def hook(t, v, tb):
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = hook

from folio_draw import dialogs as D  # noqa: E402
from shot import make, pump  # noqa: E402

D.message = lambda *a, **k: None
OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-theme-"))
os.makedirs(OUT, exist_ok=True)
FAILS = []
looked = []


def look(w, where):
    pump(0.25)
    probs = themecheck.audit(w, where)
    if probs:
        # a busy machine can grab a window before it has finished drawing: look again
        pump(1.5)
        probs = themecheck.audit(w, where)
    for p in probs:
        print("FAIL " + p)
    if probs or os.environ.get("THEME_SHOTS"):
        themecheck.save(w, os.path.join(OUT, "theme_%s%s_%s.png" % (themecheck.mode(), os.environ.get("FOLIO_THEME", ""),
                                                                      where.replace(" ", "_"))))
    FAILS.extend(probs)
    looked.append(where)
    if not probs:
        print("ok   %s (%s)" % (where, themecheck.mode()))


app, win = make()
rb = win.ribbon
print("theme", os.environ.get("GTK_THEME"), "mode", themecheck.mode(), "app", os.environ.get("FOLIO_THEME", "desktop"))
win.state.view["history"] = True
win.apply_view()
for name, b in rb.tab_buttons.items():
    if not b.get_visible():
        continue
    rb.show_tab(name)
    look(win, "tab " + name)
rb.show_tab("home")
win.set_tool("brush")
rb.size_btn.set_active(True)
pump(0.3)
pop = rb.size_pop
if os.environ.get("GDK_BACKEND") == "wayland":
    # X3-05: on Wayland the menu is a surface of its own over the window, and the window is
    # unfocused (:backdrop) while it is open: look at each on its own
    look(pop, "size menu")
    pop.set_opacity(0)
    look(win, "the window behind the size menu")
    pop.set_opacity(1)
else:
    look(pop.get_toplevel() if pop.get_toplevel() is not win else win, "size menu")
rb.size_btn.set_active(False)
win.show_backstage()
for key in win.backstage.nav_buttons:
    if key in ("back", "save", "close"):
        continue
    win.backstage.nav(key)
    look(win, "file " + key)
win.hide_backstage()
pump()
# the dialogs: each is looked at once, then cancelled
seen = set()


def look_run(d):
    t = d.get_title() or type(d).__name__
    if t not in seen:
        seen.add(t)
        d.show_all()
        pump(0.3)
        look(d, "dialog " + t)
    return Gtk.ResponseType.CANCEL


Gtk.Dialog.run = look_run
for c in (("resize",), ("properties",), ("layer_props",), ("edit_colors",), ("rotate_angle",), ("page_setup",),
          ("adjust", "brightness"), ("emb_new",)):
    try:
        win.cmd(*c)
    except Exception as e:  # a cancelled dialog may leave a command with nothing to do
        print("note", c, e)
    pump(0.2)
    for w in Gtk.Window.list_toplevels():
        if isinstance(w, Gtk.Dialog) and w.get_visible():
            w.destroy()
# an embroidery document: its ribbon tab and panes
from folio_draw import embroidery as M  # noqa: E402
win.emb.new_document(dict(M.DEFAULT_SETTINGS))
pump(0.3)
for name, b in rb.tab_buttons.items():
    if b.get_visible() and name not in ("home", "view"):
        rb.show_tab(name)
        look(win, "embroidery tab " + name)
print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
print("%d checks, %d failed" % (len(looked), len(FAILS)))
sys.exit(1 if FAILS or ERRORS or len(looked) < 8 else 0)
