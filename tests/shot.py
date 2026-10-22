"""Launch Folio Draw under Xvfb, optionally run a script of actions, save screenshots."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from folio_draw import theme
from folio_draw.app import App
from folio_draw.window import Window

def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        time.sleep(0.01)

def shot(win, path):
    pump(0.3)
    gw = win.get_window()
    w, h = gw.get_width(), gw.get_height()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, w, h)
    pb.savev(path, "png", [], [])

def make():
    app = App(); app.register(None); app.do_startup() if False else None
    theme.install()
    Gtk.IconTheme.get_default().append_search_path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "icons")))
    win = Window(app)
    win.set_default_size(1280, 820); win.resize(1280, 820)
    win.show_all(); win.ribbon.tab_buttons["text"].hide(); win.apply_view()
    pump(0.6)
    return app, win

if __name__ == "__main__":
    app, win = make()
    shot(win, sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-0/xt/shot.png")
