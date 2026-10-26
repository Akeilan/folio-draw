"""The P3 tools: magic wand, polygon selection and combining selections; the History panel and
recent colours; the stroke stabilizer.
Fails loudly on any Python exception raised inside a GTK callback."""
import os
import sys
import tempfile
import traceback

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="fd-cfg-")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="fd-data-")
os.environ["GSETTINGS_BACKEND"] = "memory"

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

app, win = make()
cv = win.canvas
area = cv.area


class FakeEvent:
    """Carries exactly the fields GTK's button/motion events give the handlers."""

    def __init__(self, kind, x, y, button, state):
        self.type, self.x, self.y, self.button, self.state = kind, float(x), float(y), button, Gdk.ModifierType(state)


def ev(kind, wx, wy, button=1, state=0):
    return FakeEvent(kind, wx, wy, button, state)


def at(dx, dy):
    return cv.to_screen(dx, dy)


def drag(points, button=1, state=0):
    sx, sy = at(*points[0])
    cv._press(area, ev(Gdk.EventType.BUTTON_PRESS, sx, sy, button, state))
    for p in points[1:]:
        cv._motion(area, ev(Gdk.EventType.MOTION_NOTIFY, *at(*p), button, state))
    cv._release(area, ev(Gdk.EventType.BUTTON_RELEASE, *at(*points[-1]), button, state))
    pump(0.02)


def click(x, y, button=1, state=0, double=False):
    drag([(x, y)], button, state)
    if double:
        # GTK sends press, release, press, 2BUTTON_PRESS, release
        sx, sy = at(x, y)
        cv._press(area, ev(Gdk.EventType.BUTTON_PRESS, sx, sy, button, state))
        cv._press(area, ev(Gdk.EventType._2BUTTON_PRESS, sx, sy, button, state))
        cv._release(area, ev(Gdk.EventType.BUTTON_RELEASE, sx, sy, button, state))


def px(x, y, all_layers=False):
    return win.doc.pick(x, y, all_layers)


class FakeKey:
    def __init__(self, keyval, state):
        self.keyval, self.state = keyval, Gdk.ModifierType(state)


def key(name, state=0):
    return win._key(win, FakeKey(Gdk.keyval_from_name(name), state))


CTRL = Gdk.ModifierType.CONTROL_MASK
SHIFT = Gdk.ModifierType.SHIFT_MASK

ALT = Gdk.ModifierType.MOD1_MASK

win.canvas.set_zoom(1.0, (0, 0))
pump(0.2)

# ---- a picture to select in: red on the left, a red square on the right, a white field
from gi.repository import GdkPixbuf  # noqa: E402
W, H = 600, 400
pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, W, H)
pb.fill(0xFFFFFFFF)
pb.new_subpixbuf(0, 0, 200, H).fill(0xD02020FF)
pb.new_subpixbuf(400, 100, 50, 50).fill(0xD02020FF)
pic = os.path.join(OUT, "wand.png")
pb.savev(pic, "png", [], [])
win.open_path(pic, ask=False)
pump(0.2)
doc = win.doc
cv.set_zoom(1.0, (0, 0))
pump(0.1)

# ---- magic wand
win.set_tool("wand")
check("the Magic wand is a selection tool on the Select button",
      win.state.tool == "wand" and win.ribbon.select_btn.get_style_context().has_class("fd-on"))
click(50, 50)
check("a click selects the colour joined to it", doc.sel_bounds() == (0, 0, 200, H), doc.sel_bounds())
win.cmd("toggle_wand_contiguous", False)
click(50, 50)
check("not contiguous: that colour everywhere", doc.sel_bounds() == (0, 0, 450, H), doc.sel_bounds())
win.cmd("toggle_wand_contiguous", True)
click(500, 300)
check("the white field", doc.sel_bounds() == (200, 0, 400, H), doc.sel_bounds())
click(50, 50, state=SHIFT)
check("Shift adds to the selection", doc.sel_bounds() == (0, 0, 600, H), doc.sel_bounds())
win.set_tool("select")
drag([(0, 0), (600, 50)], state=ALT)
check("Alt takes away from it (here with a rectangle)", doc.sel_bounds() == (0, 50, 600, 350), doc.sel_bounds())
drag([(100, 100), (500, 200)], state=SHIFT | ALT)
check("Shift+Alt keeps only what both cover", doc.sel_bounds() == (100, 100, 400, 100), doc.sel_bounds())
win.set_tool("wand")
# tolerance: a slightly different red joins in only above it
pb2 = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 100, 50)
pb2.fill(0xFFFFFFFF)
pb2.new_subpixbuf(0, 0, 50, 50).fill(0xC82828FF)
pb2.new_subpixbuf(50, 0, 50, 50).fill(0xD02020FF)
p2 = os.path.join(OUT, "tol.png")
pb2.savev(p2, "png", [], [])
win.open_path(p2, ask=False)
pump(0.1)
doc = win.doc
cv.set_zoom(1.0, (0, 0))
win.cmd("wand_tolerance", 0)
click(10, 10)
check("tolerance 0: the exact colour only", doc.sel_bounds() == (0, 0, 50, 50), doc.sel_bounds())
win.cmd("wand_tolerance", 10)
click(10, 10)
check("tolerance 10%: the near colour joins", doc.sel_bounds() == (0, 0, 100, 50), doc.sel_bounds())
check("the tolerance is remembered", win.state.wand_tolerance == 10 and win.ribbon.tol_items[10].get_active())
win.open_path(pic, ask=False)
pump(0.1)
doc = win.doc
cv.set_zoom(1.0, (0, 0))
win.cmd("wand_tolerance", 25)

# ---- the outline follows the selection's shape
win.set_tool("wand")
click(425, 125)
pump(0.05)
cv.area.queue_draw()
pump(0.3)
segs = cv._outline or []
check("marching ants go round the selected shape", len(segs) == 4 and doc.sel_bounds() == (400, 100, 50, 50), segs[:6])
shot(win, os.path.join(OUT, "wand.png"))

# ---- polygon selection: click from point to point
win.set_tool("polyselect")
for p in ((20, 20), (300, 20), (300, 200)):
    click(*p)
check("polygon points are placed one click at a time", cv.polysel is not None and len(cv.polysel["pts"]) == 3)
key("BackSpace")
check("Backspace takes back the last point", len(cv.polysel["pts"]) == 2)
click(300, 200)
click(20, 200)
pump(0.1)
shot(win, os.path.join(OUT, "polygon.png"))
click(21, 21)                          # on the first point closes it
check("clicking the first point closes the shape", cv.polysel is None and doc.sel_bounds() == (20, 20, 280, 180), doc.sel_bounds())
for p in ((50, 250), (150, 250), (150, 350)):
    click(*p)
key("Escape")
check("Esc drops a polygon being placed", cv.polysel is None and doc.sel_bounds() == (20, 20, 280, 180))
for p in ((400, 50), (500, 50), (500, 150)):
    click(*p, state=SHIFT)
key("Return")
check("Enter closes it; Shift at the first click adds it", doc.sel_bounds() == (20, 20, 480, 180), doc.sel_bounds())
for p in ((100, 300), (200, 300)):
    click(*p)
click(150, 380, double=True)
check("a double-click closes it too", cv.polysel is None and doc.sel_bounds() is not None and doc.sel_bounds()[1] >= 299,
      doc.sel_bounds())

# ---- what the selection is for: delete what the wand picked
win.set_tool("wand")
click(50, 50)
key("Delete")
check("Delete clears what the wand selected", px(50, 50)[3] == 0 or px(50, 50)[:3] == (255, 255, 255), px(50, 50))
check("and nothing beside it", px(250, 50) == (255, 255, 255, 255))
win.cmd("undo")
check("undo brings it back", px(50, 50)[:3] == (0xD0, 0x20, 0x20))

# ---- D-09: History panel and recent colours
check("the History panel starts hidden", not win.history.get_visible())
key("F8")
pump(0.1)
check("F8 shows the History panel", win.history.get_visible() and win.ribbon.view_checks["history"].get_active())
check("an undone step shows greyed, ready to redo", win.history.rows()[-1] == ("Delete", True), win.history.rows())
win.set_color(1, (10, 120, 200, 255))
win.set_tool("pencil")
drag([(300, 300), (350, 320), (380, 360)])
pump(0.05)
rows = win.history.rows()
check("a new step drops what was undone; named after the tool", rows[-1] == ("Pencil", False) and ("Delete", True) not in rows, rows)
check("the colour painted with goes to Recent", tuple(win.state.recent_colors[0]) == (10, 120, 200, 255), win.state.recent_colors[:3])
win.set_color(1, (0, 160, 60, 255))
win.state.shape = "rect"
win.set_tool("shape")
drag([(420, 220), (520, 300)])
key("Return")
pump(0.05)
check("a shape is named after its kind", win.history.rows()[-1][0] == "Rectangle", win.history.rows()[-3:])
check("newest colour first, no repeats", [tuple(c) for c in win.state.recent_colors[:2]] == [(0, 160, 60, 255), (10, 120, 200, 255)],
      win.state.recent_colors[:3])
win.cmd("flip_h")
check("a command is named as in the menus", win.history.rows()[-1][0] == "Flip horizontal", win.history.rows()[-2:])
n = len(win.history.rows())
win.history.go_to(n - 4)
rows = win.history.rows()
check("clicking an earlier step undoes back to it", [r[1] for r in rows[-3:]] == [True, True, True] and sum(r[1] for r in rows) == 3, rows)
win.history.go_to(n - 1)
check("and forward again", not any(r[1] for r in win.history.rows()), win.history.rows())
win.set_color(1, (0, 0, 0, 255))
sw = win.ribbon.recent_swatches[1]
win.ribbon._palette_click(sw.color_fn(), 1)
check("a Recent swatch puts its colour back in Color 1", tuple(win.state.color1) == (10, 120, 200, 255), win.state.color1)
# ---- D-10: stabilizer
pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, W, H)
pb.fill(0xFFFFFFFF)
blank = os.path.join(OUT, "blank.png")
pb.savev(blank, "png", [], [])
win.open_path(blank, ask=False)
pump(0.2)
doc = win.doc
cv.set_zoom(1.0, (0, 0))
pump(0.1)
win.set_color(1, (0, 0, 0, 255))
win.set_tool("brush")
rb = win.ribbon
rb.size_btn.set_active(True)
pump(0.1)
check("the Size menu has a Stabilizer section for the brushes",
      rb.stab_box.get_visible() and rb.stab_title.get_text() == "Stabilizer for the brushes" and len(rb.stab_scales) == 3,
      rb.stab_title.get_text())
check("all three start at 0%", [sc.get_value() for sc in rb.stab_scales] == [0, 0, 0])
rb.size_btn.set_active(False)
win.set_tool("fill")
rb.size_btn.set_active(True)
pump(0.1)
check("not for tools that don't draw lines", not rb.stab_box.get_visible())
rb.size_btn.set_active(False)


def ink_rows(x0, x1, y0, y1):
    """Rows y0..y1 with ink in columns x0..x1."""
    ys = [y for y in range(y0, y1) if any(px(x, y)[0] < 128 for x in range(x0, x1, 3))]
    return (min(ys), max(ys)) if ys else None


def zigzag(y0):
    return [(40 + i * 4, y0 + (18 if i % 2 else -18)) for i in range(60)]


win.set_tool("pencil")
drag(zigzag(80))
raw = ink_rows(100, 260, 40, 130)
check("without the stabilizer a zigzag is drawn as it was moved", raw is not None and raw[1] - raw[0] >= 34, raw)
rb.size_btn.set_active(True)
pump(0.05)
rb.stab_scales[1].set_value(100)
rb.stab_scales[0].set_value(30)
rb.size_btn.set_active(False)
check("the slider settings are kept for that tool", win.state.stabilizer["pencil"] == [30, 100, 0]
      and win.state.stabilizer["brush"] == [0, 0, 0], win.state.stabilizer)
pts = zigzag(220)
drag(pts)
smooth = ink_rows(100, 200, 180, 270)
check("StreamLine and Stabilization smooth the zigzag out", smooth is not None and smooth[1] - smooth[0] <= 12, smooth)
check("the line still runs on to where the pointer let go", px(int(pts[-1][0]), int(pts[-1][1]))[0] < 128, pts[-1])
win.cmd("stabilizer", 0, 0)
win.cmd("stabilizer", 1, 0)
win.cmd("stabilizer", 2, 100)
shaky = [(40 + i * 3, 330 + (2 if i % 2 else -2)) for i in range(100)]
drag(shaky)
mf = ink_rows(60, 300, 300, 360)
check("Motion filtering ignores small shaky movements", mf is not None and mf[1] - mf[0] <= 3, mf)
win.cmd("stabilizer", 2, 0)
n0 = len(win.history.rows())
drag(shaky[:20])
check("a stabilized stroke is still one step to undo", len(win.history.rows()) == n0 + 1)
st2 = type(win.state)()
st2.load()
check("the settings are remembered", st2.stabilizer["pencil"] == [0, 0, 0] and isinstance(st2.stabilizer["eraser"], list),
      st2.stabilizer)
win.cmd("stabilizer_open")
pump(0.1)
check("Search can open the Stabilizer", rb.size_btn.get_active() and rb.stab_box.get_visible())
shot(win, os.path.join(OUT, "tools_stabilizer.png"))
rb.size_btn.set_active(False)
shot(win, os.path.join(OUT, "tools_final.png"))
print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
