"""S-08: light or dark as the desktop is set. Fails loudly on any Python exception raised inside a
GTK callback."""
import os
import sys
import tempfile
import traceback

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="fd-cfg-")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="fd-data-")
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["FOLIO_THEME"] = "dark"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

ERRORS = []


def hook(t, v, tb):
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = hook

from folio_draw import dialogs as D  # noqa: E402
from folio_draw import engine as E  # noqa: E402
from shot import make, pump, shot  # noqa: E402
from folio_draw.window import SEARCH_COMMANDS as SEARCH  # noqa: E402

OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-audit-"))
os.makedirs(OUT, exist_ok=True)
checks = []


_last = [None]


def check(name, cond, detail=""):
    try:
        v = win.doc.pick(5, 5, False)
        if v != _last[0]:
            print("   (5,5) now", v, "after", name)
            _last[0] = v
    except Exception:
        pass
    checks.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))


# canned dialog answers
answers = {"choice": 2}
D.message = lambda *a, **k: None
D.ask_choice = lambda *a, **k: answers["choice"]
D.ask_save_changes = lambda *a, **k: "discard"
D.resize_skew = lambda parent, w, h, what="image": answers.get("resize")
D.image_properties = lambda *a, **k: answers.get("props")
D.layer_properties = lambda *a, **k: answers.get("layerprops")
D.edit_colors = lambda parent, color, custom: answers.get("colors")
D.about = lambda *a, **k: None

Gtk.Settings.get_default().set_property("gtk-theme-name", "Adwaita")   # a theme with a dark variant, as desktops have
app, win = make()
import cairo  # noqa: E402
from folio_draw import appearance, icons  # noqa: E402


def grab():
    pump(0.3)
    gw = win.get_window()
    w, h = gw.get_width(), gw.get_height()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(img)
    Gdk.cairo_set_source_window(cr, gw, 0, 0)
    cr.paint()
    img.flush()
    return img


def pixel(img, x, y):
    data = img.get_data()
    o = y * img.get_stride() + x * 4
    b, g, r = data[o], data[o + 1], data[o + 2]
    return (r, g, b)


def tr(w, x, y):
    r = w.translate_coordinates(win, int(x), int(y))
    return tuple(r[-2:])


def at_widget(w, fx=0.98, fy=0.5):
    return tr(w, w.get_allocated_width() * fx, w.get_allocated_height() * fy)


def lum(c):
    return (c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000


rb = win.ribbon
check("FOLIO_THEME=dark is followed", appearance.is_dark())
check("GTK's own widgets go dark too", Gtk.Settings.get_default().get_property("gtk-application-prefer-dark-theme"))
img = grab()
img.write_to_png(os.path.join(OUT, "theme_dark.png"))
ribbon_px = pixel(img, *at_widget(rb, 0.995, 0.6))
work_px = pixel(img, *at_widget(win.canvas.area, 0.97, 0.97))
check("the ribbon is dark", lum(ribbon_px) < 70, ribbon_px)
check("the workspace around the picture is dark", lum(work_px) < 50, work_px)
check("icons are drawn in a light ink", lum([c * 255 for c in icons.ink()]) > 180, icons.ink())
pic_px = pixel(img, *at_widget(win.canvas.area, 0.0, 0.0))
ox, oy = win.canvas.to_screen(20, 20)
px_, py_ = tr(win.canvas.area, ox, oy)
check("the picture keeps its own colours (white)", pixel(img, px_, py_) == (255, 255, 255), pixel(img, px_, py_))

# the desktop switches to light: everything follows at once, no restart
appearance.set_dark(False)
img = grab()
img.write_to_png(os.path.join(OUT, "theme_light.png"))
ribbon_px2 = pixel(img, *at_widget(rb, 0.995, 0.6))
work_px2 = pixel(img, *at_widget(win.canvas.area, 0.97, 0.97))
check("switching to light: ribbon light again", lum(ribbon_px2) > 200, ribbon_px2)
check("workspace grey #e6e6e6", work_px2 == (230, 230, 230), work_px2)
check("GTK widgets light", not Gtk.Settings.get_default().get_property("gtk-application-prefer-dark-theme"))
check("icons dark ink", lum([c * 255 for c in icons.ink()]) < 80)
appearance.set_dark(True)
img = grab()
check("and back to dark", lum(pixel(img, *at_widget(win.canvas.area, 0.97, 0.97))) < 50)

# reading the desktop's setting
os.environ["FOLIO_THEME"] = "light"
check("FOLIO_THEME=light wins", not appearance.system_prefers_dark())
del os.environ["FOLIO_THEME"]
from gi.repository import Gio  # noqa: E402
src = Gio.SettingsSchemaSource.get_default()
schema = src.lookup("org.gnome.desktop.interface", True) if src else None
if schema is not None and schema.has_key("color-scheme"):
    gs = Gio.Settings.new("org.gnome.desktop.interface")
    gs.set_string("color-scheme", "default")
    gs.set_string("gtk-theme", "Adwaita")
    appearance.refresh()
    check("desktop set to default: light", not appearance.is_dark())
    appearance._watching = False
    appearance._watch()
    gs.set_string("color-scheme", "prefer-dark")
    pump(0.5)
    check("the desktop switching to dark is picked up while running", appearance.is_dark())
    gs.set_string("color-scheme", "default")
    pump(0.5)
    check("and back to light", not appearance.is_dark())
    gs.set_string("gtk-theme", "Adwaita-dark")
    pump(0.5)
    check("a dark GTK theme counts as dark", appearance.is_dark())
else:
    print("(no GNOME interface settings here: desktop detection checks skipped)")

# every dialog-less view still draws in dark mode
appearance.set_dark(True)
for name in ("view", "home"):
    try:
        rb.show_tab(name)
    except Exception:
        pass
    grab()
win.cmd("view_toggle", "rulers", True)
win.cmd("view_toggle", "history", True)
img = grab()
img.write_to_png(os.path.join(OUT, "theme_dark_view.png"))
hx, hy = tr(win.canvas.hruler, 200, 5)
check("rulers are dark", lum(pixel(img, hx, hy)) < 70, pixel(img, hx, hy))
lx, ly = tr(win.history, 10, win.history.get_allocated_height() - 5)
check("the History panel is dark", lum(pixel(img, lx, ly)) < 70, pixel(img, lx, ly))
win.cmd("view_toggle", "rulers", False)
win.cmd("view_toggle", "history", False)
win.show_backstage("home")
img = grab()
img.write_to_png(os.path.join(OUT, "theme_dark_file.png"))
check("the File view is dark", lum(pixel(img, img.get_width() - 20, img.get_height() - 20)) < 70,
      pixel(img, img.get_width() - 20, img.get_height() - 20))
win.hide_backstage() if hasattr(win, "hide_backstage") else None

print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
