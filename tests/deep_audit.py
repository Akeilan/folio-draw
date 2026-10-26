"""Deeper audit: exact undo/redo per action, every brush/shape/tool, edge geometry,
tiny images, extreme zoom, every shortcut, and a seeded random fuzz replayed through undo/redo.
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
from folio_draw.shapes import SHAPES as S_SHAPES  # noqa: E402

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
    if not cond or os.environ.get("VERBOSE"): print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))


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
D.rotate_angle = lambda *a, **k: answers.get("rotate")

_popup = Gtk.Menu.popup_at_pointer
Gtk.Menu.popup_at_pointer = lambda self, ev=None: None  # fake events are not Gdk.Events
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
import hashlib  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402

ALT = Gdk.ModifierType.MOD1_MASK


def snap():
    d = win.doc
    h = hashlib.sha1()
    h.update(b"%d,%d,%d;" % (d.width, d.height, d.layer_count()))
    for i in range(d.layer_count()):
        h.update(d.layer_rgba(i))
        p = d.layer_props(i)
        h.update(repr(sorted(p.items())).encode())
    return h.hexdigest()


def settle():
    win.finalize_pending()
    if win.doc.float_rect():
        win.doc.float_commit()
    win.doc.sel_none()
    cv.sel_path = None
    cv.sync()
    pump(0.01)


def undoable(name, action, expect_change=True):
    """Run an action, then check undo restores the exact prior state and redo the exact result."""
    settle()
    before = snap()
    n_err = len(ERRORS)
    action()
    settle()
    after = snap()
    changed = after != before
    if expect_change is not None:
        check(name + (" changes the picture" if expect_change else " leaves the picture alone"), changed == expect_change)
    if changed:
        win.cmd("undo")
        settle()
        ok_u = snap() == before
        win.cmd("redo")
        settle()
        ok_r = snap() == after
        check(name + ": undo exact, redo exact", ok_u and ok_r, (ok_u, ok_r))
    if len(ERRORS) > n_err:
        check(name + " raised no errors", False, ERRORS[-1].splitlines()[-1])


def fresh(w=640, h=480, transparent=False):
    win.set_document(E.Document.new(w, h, (0, 0, 0, 0) if transparent else (255, 255, 255, 255)), None)
    win.cmd("zoom_100")
    pump(0.05)


fresh()
win.set_color(1, (20, 40, 200, 255))
win.set_color(2, (250, 200, 0, 255))

# ---- every plain tool, normal stroke, off-canvas stroke, single click
for tool in ("pencil", "eraser"):
    win.set_tool("brush")
    win.set_brush("brush")
    drag([(0, 240), (640, 240)])  # something to erase
    win.set_tool(tool)
    undoable("%s stroke" % tool, lambda: drag([(50, 50), (300, 200), (500, 80)]))
    undoable("%s stroke crossing the edge" % tool, lambda: drag([(600, 240), (900, 240), (900, -50), (-50, 240)]))
    undoable("%s stroke entirely off canvas" % tool, lambda: drag([(-200, -200), (-100, -150)]), expect_change=False)
    undoable("%s single click" % tool, lambda: click(320, 300))
    undoable("%s right-button stroke" % tool, lambda: drag([(60, 400), (300, 420)], button=3))

for kind in ("brush", "soft", "callig", "callig2", "airbrush", "marker"):
    fresh()
    win.set_brush(kind)
    undoable("brush '%s' stroke" % kind, lambda: drag([(50, 50), (200, 150), (400, 60), (600, 300)]))
    undoable("brush '%s' click" % kind, lambda: click(100, 300))
    undoable("brush '%s' crossing the corner" % kind, lambda: drag([(620, 460), (700, 520)]))
    win.set_size(500)
    undoable("brush '%s' at size 500" % kind, lambda: drag([(320, 240), (330, 250)]))
    win.set_size(1)
    undoable("brush '%s' at size 1" % kind, lambda: drag([(10, 470), (630, 470)]))
    win.set_size(5)

fresh()
win.set_tool("fill")
undoable("fill blank canvas", lambda: click(10, 10))
undoable("fill same colour again", lambda: click(10, 10), expect_change=False)
undoable("fill outside canvas", lambda: click(-10, -10), expect_change=False)
fresh()
win.set_tool("pencil")
drag([(0, 100), (640, 100)])
win.set_tool("fill")
undoable("fill one side of a line with the secondary colour", lambda: click(20, 300, button=3))
check("fill stopped at the line", px(20, 20)[:3] == (255, 255, 255) and px(20, 300)[:3] == (250, 200, 0), (px(20, 20), px(20, 300)))
win.set_tool("brush")
win.set_brush("soft")
win.set_size(40)
drag([(100, 300), (400, 300)])
win.set_tool("fill")
for tol in (0, 100):
    win.state.tolerance = tol
    undoable("fill at tolerance %d" % tol, lambda: click(250, 300))
win.state.tolerance = 15
win.set_tool("picker")
win.cmd("undo")
win.set_color(1, (1, 2, 3, 255))
click(20, 20)
check("picker takes the colour into well 1", win.state.color1 == px(20, 20), (win.state.color1, px(20, 20)))
check("picker returns to the previous tool", win.state.tool == "fill")
win.set_tool("picker")
click(20, 300, button=3)
check("right-click picker sets well 2", win.state.color2 == px(20, 300), (win.state.color2, px(20, 300)))
win.set_tool("picker")
click(-50, -50)
check("picker off canvas does nothing harmful", not ERRORS)
win.set_color(1, (20, 40, 200, 255))
win.set_color(2, (250, 200, 0, 255))
win.set_tool("pencil")

# ---- every shape, outline / fill / both, edited through handles and moved
modes = [("outline", True, False), ("fill", False, True), ("both", True, True)]
for kind, label in S_SHAPES:
    for mname, ol, fl in modes:
        fresh()
        win.set_shape(kind)
        win.cmd("outline", ol)
        win.cmd("fillmode", fl)
        if kind == "polygon":
            def act():
                drag([(100, 100), (300, 100)])
                click(300, 300)
                click(100, 300, double=True)
        elif kind == "curve":
            def act():
                drag([(100, 300), (500, 300)])
                drag([(300, 300), (300, 100)])
                drag([(400, 300), (400, 420)])
        else:
            def act():
                drag([(100, 100), (300, 250)])
                if cv.pending is not None:
                    # grab the south-east handle and stretch, then move the whole shape
                    drag([(300, 250), (360, 300)])
                    drag([(200, 180), (260, 200)])
        undoable("shape %s (%s)" % (kind, mname), act)
    win.cmd("outline", True)
    win.cmd("fillmode", False)

fresh()
win.set_shape("rect")
undoable("zero-size shape", lambda: click(200, 200), expect_change=None)
undoable("shape dragged backwards", lambda: drag([(400, 400), (100, 100)]))
undoable("shape dragged off the canvas", lambda: drag([(500, 400), (900, 900)]))
drag([(100, 100), (200, 200)])
key("Escape")
check("Escape cancels a pending shape", cv.pending is None)
drag([(100, 100), (200, 200)])
key("Return")
check("Enter commits a pending shape", cv.pending is None and px(100, 150)[:3] == (20, 40, 200))
drag([(300, 300), (400, 400)])
win.cmd("undo")
check("undo with a pending shape just drops it", cv.pending is None)
drag([(300, 300), (400, 400)])
before = win.doc.changes
key("Right", 0)
key("Right", SHIFT)
win.finalize_pending()
check("arrow keys nudge a pending shape", px(311, 350)[:3] == (20, 40, 200) and px(300, 350)[3] == 255 and px(300, 350)[:3] != (20, 40, 200), (px(311, 350), px(300, 350)))

# ---- selections
fresh()
win.set_brush("brush")
win.set_size(30)
drag([(100, 240), (540, 240)])
win.set_tool("select")
undoable("select then delete", lambda: (drag([(80, 200), (300, 280)]), win.cmd("delete")))
undoable("select then move", lambda: (drag([(280, 200), (500, 280)]), drag([(400, 240), (400, 400)])))
undoable("select then nudge", lambda: (drag([(80, 100), (600, 450)]), key("Left"), key("Up", SHIFT)))
for c in ("rot_cw", "rot_ccw", "rot_180", "flip_h", "flip_v", "invert_colors"):
    undoable("%s on a selection" % c, lambda c=c: (drag([(100, 300), (400, 450)]), win.cmd(c)))
    undoable("%s on the whole image" % c, lambda c=c: (win.set_tool("pencil"), win.set_tool("select"), win.cmd(c)))
fresh(400, 300)
win.set_tool("pencil")
drag([(0, 0), (399, 299)])
undoable("rotate a non-square image", lambda: win.cmd("rot_cw"))
check("rotation swaps width and height", (win.doc.width, win.doc.height) == (300, 400))
win.set_tool("select")
undoable("select all + cut", lambda: (win.cmd("select_all"), win.cmd("cut")))
win.cmd("undo")
undoable("paste", lambda: win.cmd("paste"), expect_change=None)
undoable("crop to a selection", lambda: (drag([(10, 10), (110, 60)]), win.cmd("crop")))
check("crop sizes the image to the selection", (win.doc.width, win.doc.height) == (100, 50), (win.doc.width, win.doc.height))
undoable("crop with no selection", lambda: (win.cmd("select_all"), win.doc.sel_none(), win.cmd("crop")), expect_change=False)
undoable("invert selection then delete", lambda: (drag([(10, 10), (50, 40)]), win.cmd("invert_selection"), win.cmd("delete")))
fresh()
win.set_tool("freeselect")
undoable("free-form select then delete", lambda: (drag([(100, 100), (300, 120), (250, 300), (90, 250)]), win.cmd("delete")))
undoable("free-form select of a single point", lambda: (click(200, 200), win.cmd("delete")), expect_change=None)
win.set_tool("select")
undoable("selection dragged entirely off the canvas", lambda: (drag([(-300, -300), (-100, -100)]), win.cmd("delete")), expect_change=None)
win.state.transparent_sel = False
win.cmd("toggle_transparent_sel")
undoable("transparent selection move", lambda: (drag([(0, 0), (200, 200)]), drag([(100, 100), (300, 250)])), expect_change=None)
win.cmd("toggle_transparent_sel")

# ---- whole-image dialogs (canned answers)
fresh()
win.set_tool("pencil")
drag([(0, 0), (639, 479)])
answers["resize"] = (320, 240, 0, 0, True)
undoable("resize to half", lambda: win.cmd("resize"))
check("resize result size", (win.doc.width, win.doc.height) == (320, 240))
answers["resize"] = (320, 240, 30, -20, False)
undoable("skew both ways", lambda: win.cmd("resize"))
answers["resize"] = (1, 1, 0, 0, True)
undoable("resize to 1x1", lambda: win.cmd("resize"))
answers["resize"] = (2000, 1500, 0, 0, False)
undoable("resize 1x1 up to 2000x1500", lambda: win.cmd("resize"))
answers["props"] = (50, 4000)
undoable("properties: change canvas size", lambda: win.cmd("properties"))
answers["props"] = None
undoable("properties: cancel", lambda: win.cmd("properties"), expect_change=False)
answers["resize"] = None
undoable("resize: cancel", lambda: win.cmd("resize"), expect_change=False)
fresh()
win.set_tool("select")
drag([(10, 10), (110, 110)])
answers["resize"] = (300, 50, 0, 0, True)
undoable("resize a selection", lambda: win.cmd("resize"), expect_change=None)
answers["resize"] = None
win.cmd("select_all")
win.doc.sel_none()
win.set_tool("pencil")
answers["rotate"] = (33.0, True, True)
undoable("rotate the image 33°", lambda: win.cmd("rotate_angle"))
answers["rotate"] = (-137.5, False, False)
undoable("rotate the image -137.5° without smoothing", lambda: win.cmd("rotate_angle"))
win.set_tool("select")
answers["rotate"] = (12.0, True, False)
undoable("rotate a selection 12°", lambda: (drag([(20, 20), (120, 90)]), win.cmd("rotate_angle")), expect_change=None)
answers["rotate"] = None
undoable("rotate: cancel", lambda: win.cmd("rotate_angle"), expect_change=None)
win.set_tool("pencil")

# ---- tiny document: every command must survive a 1x1 image
fresh(1, 1)
check("1x1 document", (win.doc.width, win.doc.height) == (1, 1))
for tool in ("pencil", "brush", "eraser", "fill", "select", "freeselect", "shape", "picker"):
    win.set_tool(tool)
    drag([(0, 0), (5, 5), (-3, 2)])
    click(0, 0)
    settle()
for c in ("rot_cw", "rot_ccw", "rot_180", "flip_h", "flip_v", "invert_colors", "select_all", "invert_selection", "crop",
          "copy", "delete", "zoom_in", "zoom_out", "zoom_fit", "zoom_100", "layer_add", "layer_dup", "layer_up", "layer_down",
          "layer_merge", "flatten", "layer_delete", "undo", "redo", "rotate_angle"):
    answers["rotate"] = (45.0, True, True)
    win.cmd(c)
    settle()
answers["rotate"] = None
check("every tool and command on a 1x1 image without errors", not ERRORS, ERRORS[-1:] and ERRORS[-1].splitlines()[-1])

# ---- extreme zoom: drawing must land on the right pixels
fresh(200, 150)
win.set_tool("pencil")
for z in (0.125, 32):
    win.canvas.set_zoom(z, (0, 0))
    pump(0.05)
    cv.hadj.set_value(0)
    cv.vadj.set_value(0)
    pump(0.02)
    click(3, 4)
    check("pencil at zoom %g hits pixel (3,4)" % z, px(3, 4)[:3] == (20, 40, 200) and px(4, 4)[:3] == (255, 255, 255), (px(3, 4), px(4, 4)))
    win.cmd("undo")
    # scroll to the far corner and draw there
    cv.hadj.set_value(cv.hadj.get_upper())
    cv.vadj.set_value(cv.vadj.get_upper())
    pump(0.02)
    click(198, 148)
    check("pencil at zoom %g after scrolling hits (198,148)" % z, px(198, 148)[:3] == (20, 40, 200))
    win.cmd("undo")
for _ in range(25):
    win.cmd("zoom_in")
check("zoom in clamps at 32x", abs(cv.z - 32) < 1e-6, cv.z)
for _ in range(25):
    win.cmd("zoom_out")
check("zoom out clamps at 1/8", abs(cv.z - 0.125) < 1e-6, cv.z)
win.cmd("zoom_100")

# ---- layers
fresh()
win.set_brush("brush")
win.set_size(20)
drag([(50, 50), (590, 50)])
win.cmd("layer_add")
undoable("draw on layer 2", lambda: drag([(50, 100), (590, 100)]))
answers["layerprops"] = ("Hidden", 1.0, False, 0, 100)
undoable("hide a layer", lambda: win.cmd("layer_props"))
check("hidden layer not composited", px(300, 100, True)[:3] == (255, 255, 255), px(300, 100, True))
undoable("draw on a hidden layer", lambda: drag([(50, 150), (590, 150)]), expect_change=None)
answers["layerprops"] = ("Half", 0.5, True, 0, 100)
undoable("half-opacity layer", lambda: win.cmd("layer_props"))
c = px(300, 100, True)
check("half opacity blends", 100 < c[0] < 200, c)
undoable("layer up", lambda: win.cmd("layer_up"), expect_change=None)
undoable("layer down", lambda: win.cmd("layer_down"), expect_change=None)
undoable("duplicate layer", lambda: win.cmd("layer_dup"))
undoable("merge down", lambda: win.cmd("layer_merge"))
undoable("delete layer", lambda: win.cmd("layer_delete"))
while win.doc.layer_count() > 1:
    win.cmd("layer_delete")
win.cmd("layer_delete")
check("the last layer cannot be deleted", win.doc.layer_count() == 1)
win.doc.set_active(0)
win.cmd("layer_merge")
check("merging the bottom layer is a no-op", win.doc.layer_count() == 1 and not ERRORS[-1:])
for _ in range(60):
    win.cmd("layer_add")
check("many layers (%d)" % win.doc.layer_count(), win.doc.layer_count() >= 2 and not ERRORS)
pump(0.1)

# ---- text: commit, cancel, empty, edits off-canvas
fresh()
win.set_tool("text")
def text_box(x0, y0, x1, y1, txt):
    drag([(x0, y0), (x1, y1)])
    if cv.text is not None:
        cv.text["view"].get_buffer().set_text(txt)
undoable("text committed", lambda: (text_box(50, 50, 400, 150, "Folio Draw"), cv.text_commit()))
undoable("empty text box", lambda: (text_box(50, 200, 400, 300, ""), cv.text_commit()), expect_change=False)
text_box(50, 200, 400, 300, "gone")
key("Escape")
check("Escape in text cancels", cv.text is None)
undoable("text box half off the canvas", lambda: (text_box(500, 400, 900, 700, "Edge"), cv.text_commit()))
for fam in ("Sans", "Serif", "Monospace", "NoSuchFont"):
    undoable("text in font %s" % fam, lambda: (text_box(50, 300, 600, 420, "Aa"), win.cmd("text_font", fam), cv.text_commit()))
win.cmd("text_size", 400)
undoable("huge text", lambda: (text_box(0, 0, 640, 480, "W"), cv.text_commit()))
win.cmd("text_size", 12)
win.cmd("text_opaque", True)
undoable("opaque text", lambda: (text_box(10, 10, 200, 60, "box"), cv.text_commit()))
win.cmd("text_opaque", False)
text_box(10, 10, 200, 60, "switch")
win.set_tool("pencil")
check("switching tools commits text", cv.text is None and not ERRORS)

# ---- every keyboard shortcut runs cleanly
fresh()
win.set_tool("pencil")
drag([(10, 10), (600, 400)])
D_ask = D.ask_choice
for st in (0, CTRL, CTRL | SHIFT):
    for k in ("a", "c", "d", "e", "g", "i", "m", "n", "r", "v", "w", "x", "y", "z", "0", "1", "plus", "minus",
              "Page_Up", "Page_Down", "Delete", "Escape", "Return", "Left", "Right", "Up", "Down", "F4", "F7",
              "comma", "period", "space"):
        answers["resize"] = None
        answers["props"] = None
        answers["layerprops"] = None
        key(k, st)
        settle()
        if win.playing:
            win.stop_playback()
key("f", ALT)
pump(0.05)
win.hide_backstage()
key("w", ALT)
key("Escape")
key("Escape")
key("h", ALT)
key("Escape")
key("Escape")
check("every shortcut runs without errors", not ERRORS, ERRORS[-1:] and ERRORS[-1].splitlines()[-1])
key("F11")
pump(0.2)
key("Escape")
pump(0.2)
check("F11 fullscreen then Escape leaves it", not win.fullscreen_on)

# ---- seeded random fuzz, then replay all the way back and forward through undo/redo
def fuzz(seed, steps=int(os.environ.get("FUZZ_STEPS", "250"))):
    rnd = random.Random(seed)
    fresh(320, 240)
    start = snap()
    tools = ["pencil", "eraser", "fill", "select", "freeselect", "shape", "picker", "brush"]
    cmds = ["rot_cw", "rot_ccw", "rot_180", "flip_h", "flip_v", "invert_colors", "select_all", "invert_selection",
            "delete", "crop", "layer_add", "layer_dup", "layer_up", "layer_down", "layer_merge", "flatten", "layer_delete",
            "copy", "paste", "cut", "zoom_in", "zoom_out", "zoom_fit", "zoom_100", "rotate_angle"]
    log = []
    for i in range(steps):
        r = rnd.random()
        if r < 0.15:
            t = rnd.choice(tools)
            if t == "shape":
                win.set_shape(rnd.choice(S_SHAPES)[0])
            elif t == "brush":
                win.set_brush(rnd.choice(["brush", "soft", "callig", "callig2", "airbrush", "marker"]))
            else:
                win.set_tool(t)
            log.append("tool " + win.state.tool)
        elif r < 0.6:
            pts = [(rnd.randint(-40, 360), rnd.randint(-40, 280)) for _ in range(rnd.randint(1, 5))]
            drag(pts, button=rnd.choice([1, 1, 3]), state=rnd.choice([0, 0, SHIFT]))
            log.append("drag %s" % (pts,))
        elif r < 0.85:
            c = rnd.choice(cmds)
            if c == "crop" and win.doc.width * win.doc.height < 64:
                continue
            if c == "rotate_angle":
                if win.doc.width * win.doc.height > 400000:
                    continue
                answers["rotate"] = (rnd.uniform(-360, 360), rnd.random() < 0.7, rnd.random() < 0.5)
            win.cmd(c)
            log.append(c)
        elif r < 0.92:
            k = rnd.choice(["Escape", "Return", "Left", "Right", "Delete"])
            key(k)
            log.append("key " + k)
        else:
            win.set_color(rnd.choice([1, 2]), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), rnd.choice([255, 255, 128])))
            win.set_size(rnd.randint(1, 40))
        if ERRORS:
            break
        if win.doc.width > 4000 or win.doc.height > 4000:
            break
    settle()
    end = snap()
    n = 0
    while win.doc.can_undo() and n < 2000:
        win.cmd("undo")
        n += 1
    settle()
    ok_back = snap() == start
    m = 0
    while win.doc.can_redo() and m < 2000:
        win.cmd("redo")
        m += 1
    settle()
    ok_fwd = snap() == end
    check("fuzz seed %d: %d actions, no errors" % (seed, len(log)), not ERRORS, ERRORS[-1:] and (ERRORS[-1].splitlines()[-1], log[-5:]))
    capped = n >= 200  # the engine keeps at most 200 undo steps; older history is gone by design
    check("fuzz seed %d: undo all (%d) returns to %s, redo all (%d) returns to the end" % (seed, n, "the oldest kept step" if capped else "blank", m),
          (ok_back or capped) and ok_fwd and n == m, (ok_back, ok_fwd, n, m))


for seed in range(int(os.environ.get("FUZZ_SEEDS", "12"))):
    if ERRORS:
        break
    fuzz(seed)

shot(win, os.path.join(OUT, "deep_final.png"))
print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
