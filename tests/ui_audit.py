"""Drive every tool, button and command through the real UI handlers under Xvfb.
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

win.canvas.set_zoom(1.0, (0, 0))
pump(0.2)
doc = win.doc
check("new document is 1152x648 white", (doc.width, doc.height) == (1152, 648) and px(5, 5) == (255, 255, 255, 255))

# ---- pencil
win.set_tool("pencil")
drag([(10, 10), (60, 10)])
check("pencil draws 1px black line", px(30, 10) == (0, 0, 0, 255) and px(30, 12) == (255, 255, 255, 255), px(30, 10))
drag([(10, 20), (60, 20)], button=3)
check("right-button pencil uses color 2", px(30, 20) == (255, 255, 255, 255))

# ---- colours
win.ribbon._palette_click((237, 28, 36, 255), 1)
check("palette click sets color 1", win.state.color1 == (237, 28, 36, 255))
win.ribbon.well_buttons[2].set_active(True)
win.ribbon._palette_click((0, 162, 232, 255), 1)
check("palette click with color 2 active sets color 2", win.state.color2 == (0, 162, 232, 255))
win.ribbon.well_buttons[1].set_active(True)

# ---- every brush
y = 40
for kind in ("brush", "soft", "callig", "callig2", "airbrush", "marker"):
    win.set_brush(kind)
    win.set_size(10)
    drag([(20, y), (120, y), (200, y + 5)])
    c = px(70, y)
    check("brush '%s' paints" % kind, c != (255, 255, 255, 255) or kind == "airbrush", c)
    y += 25
check("marker is translucent", px(70, 40 + 25 * 5)[0] > 237 or px(70, 165)[1] > 28, px(70, 165))

# ---- eraser makes transparency
win.set_tool("eraser")
drag([(20, 40), (120, 40)])
check("eraser erases to transparent", px(70, 40)[3] == 0, px(70, 40))

# ---- fill
win.set_tool("shape")
win.set_shape("rect")
win.set_color(1, (0, 0, 0, 255))
drag([(300, 50), (400, 150)])
cv.commit_pending()
win.set_tool("fill")
win.set_color(1, (34, 177, 76, 255))
click(350, 100)
check("fill inside rectangle", px(350, 100) == (34, 177, 76, 255), px(350, 100))
check("fill stays inside the outline", px(450, 100) == (255, 255, 255, 255))
win.set_color(1, (0, 0, 0, 0))
click(350, 100)
check("filling with transparent clears the area", px(350, 100)[3] == 0, px(350, 100))
win.set_color(1, (0, 0, 0, 255))

# ---- picker
win.set_tool("picker")
win.state.prev_tool = "pencil"
click(300, 100)
check("picker picks color", win.state.color1 == (0, 0, 0, 255))
check("picker returns to previous tool", win.state.tool == "pencil")

# ---- every shape, with editable handles
win.set_tool("shape")
from folio_draw.shapes import SHAPES  # noqa: E402
x0 = 500
for i, (kind, _) in enumerate(SHAPES):
    if kind in ("curve", "polygon"):
        continue
    win.set_shape(kind)
    bx = 480 + (i % 7) * 90
    by = 220 + (i // 7) * 90
    before = doc.changes
    drag([(bx, by), (bx + 70, by + 70)])
    pend = cv.pending is not None
    cv.commit_pending()
    check("shape '%s' draws and commits" % kind, pend and doc.changes > before)
# fill mode
win.cmd("fillmode", True)
win.set_color(2, (255, 201, 14, 255))
win.set_shape("oval")
drag([(20, 300), (120, 400)])
check("pending shape exists before commit", cv.pending is not None)
# move the pending shape by dragging inside it
drag([(70, 350), (90, 360)])
cv.commit_pending()
check("oval filled with color 2 and moved", px(90, 360) == (255, 201, 14, 255), px(90, 360))
win.cmd("fillmode", False)
# resize pending via handle
win.set_shape("rect")
drag([(150, 300), (200, 350)])
drag([(200, 350), (240, 390)])  # se handle
cv.commit_pending()
check("pending shape resized by handle", px(240, 370)[0] == 0 and px(240, 370)[3] == 255, px(240, 370))
# line with shift snapping
win.set_shape("line")
drag([(20, 450), (120, 455)], state=SHIFT)
cv.commit_pending()
check("shift-line snaps horizontal", px(110, 450)[3] == 255 and px(110, 450)[0] == 0, px(110, 450))
# curve: drag, bend, bend
win.set_shape("curve")
drag([(20, 500), (200, 500)])
drag([(100, 470), (100, 460)])
drag([(150, 540), (150, 545)])
check("curve finished and editable", cv.pending is not None and cv.pending.stage == 3)
cv.commit_pending()
# polygon: drag first edge, click vertices, double-click closes
win.set_shape("polygon")
win.cmd("fillmode", True)
drag([(250, 450), (350, 450)])
click(350, 550)
click(250, 550, double=True)
check("polygon closed by double-click", cv.pending is not None and cv.pending.stage == 3)
cv.commit_pending()
check("polygon filled", px(300, 500) == (255, 201, 14, 255), px(300, 500))
win.cmd("fillmode", False)
# escape cancels drawing-in-progress line
win.set_shape("line")
sx, sy = at(400, 600)
cv._press(area, ev(Gdk.EventType.BUTTON_PRESS, sx, sy))
cv._motion(area, ev(Gdk.EventType.MOTION_NOTIFY, *at(500, 600)))
key("Escape")
check("Escape during a drag cancels the shape", px(450, 600) == (255, 255, 255, 255))

# ---- text
win.set_tool("text")
drag([(700, 30), (1000, 120)])
check("text box opened, Text tab shown", cv.text is not None and win.ribbon.tab_buttons["text"].get_visible())
cv.text["view"].get_buffer().set_text("Hello Folio")
win.cmd("text_style", "bold", True)
win.cmd("text_size", 28)
before = doc.changes
n_layers = doc.layer_count()
cv.text_commit()
check("text rendered onto the layer", doc.changes > before and any(px(x, y)[0] < 50 and px(x, y)[3] > 200 for x in range(700, 900, 2) for y in range(35, 70, 2)))
check("Text tab hidden after commit", not win.ribbon.tab_buttons["text"].get_visible())
win.cmd("text_style", "bold", False)
# the text stays editable: a text layer, typed again by clicking it with the Text tool
ti = doc.active
check("the text goes on its own text layer", doc.layer_count() == n_layers + 1 and '"Hello Folio"' in doc.layer_text(ti),
      (doc.layer_count(), doc.layer_text(ti)[:60]))
click(760, 50)
check("clicking it with the Text tool opens it again", cv.text is not None and cv.text.get("layer") == ti and
      cv.text["view"].get_buffer().get_text(*cv.text["view"].get_buffer().get_bounds(), True) == "Hello Folio")
check("with its settings back (bold, 28 pt)", win.state.bold and win.state.font_size == 28, (win.state.bold, win.state.font_size))
check("and its pixels out of the way while typing", not doc.layer_props(ti)["visible"])
cv.text["view"].get_buffer().set_text("Hi")
cv.text_commit()
check("typed again it shows the new text", '"Hi"' in doc.layer_text(ti) and doc.layer_props(ti)["visible"] and
      doc.layer_count() == n_layers + 1)
check("the old letters are gone", not any(px(x, y)[3] > 200 for x in range(840, 900, 2) for y in range(35, 70, 2)))
win.cmd("undo")
check("undo brings the first text back", '"Hello Folio"' in doc.layer_text(ti))
win.cmd("redo")
click(760, 50)
key("Escape")
check("Escape leaves it as it was", cv.text is None and '"Hi"' in doc.layer_text(ti) and doc.layer_props(ti)["visible"])
win.cmd("text_style", "bold", False)
win.state.bold = False
# the rest of the audit works on one layer: put the text down into it
win.cmd("layer_merge")
check("merged down, back to one layer", doc.layer_count() == n_layers, doc.layer_count())

# ---- selection: rect select, move (cut), undo as one step
win.set_tool("select")
drag([(300, 50), (402, 152)])
check("rectangle selection", doc.sel_bounds() == (300, 50, 102, 102), doc.sel_bounds())
changes_before = doc.changes
drag([(350, 100), (650, 100)])
check("dragging selection makes a floating selection", doc.float_rect() == (600, 50, 102, 102), doc.float_rect())
key("Escape")
check("Escape commits float", doc.float_rect() is None and px(600, 100)[3] == 255)
check("hole left behind is transparent", px(300, 100)[3] == 0, px(300, 100))
win.cmd("undo")
check("move undone in one step", px(300, 100) == (0, 0, 0, 255) and px(650, 100)[3] == 255 and px(600, 100) == (255, 255, 255, 255), (px(300, 100), px(600, 100)))

# ctrl-drag copies
drag([(300, 50), (402, 152)])
drag([(350, 100), (350, 450)], state=CTRL)
key("Escape")
check("ctrl-drag leaves the original", px(301, 51)[3] == 255 and px(301, 401)[3] == 255)

# free-form select + delete
win.set_tool("freeselect")
drag([(20, 300), (120, 300), (120, 400), (20, 400)])
check("free-form selection exists", doc.sel_bounds() is not None)
key("Delete")
check("delete clears to transparency", px(90, 360)[3] == 0, px(90, 360))

# select all / invert / crop on a copy later
key("a", CTRL)
check("Ctrl+A selects all", doc.sel_bounds() == (0, 0, doc.width, doc.height))
win.cmd("invert_selection")
check("invert of all = nothing", doc.sel_bounds() is None)

# transparent selection keeps color-2 pixels behind
win.set_tool("select")
win.set_color(2, (255, 255, 255, 255))
win.state.transparent_sel = True
drag([(690, 25), (1010, 125)])
drag([(800, 60), (800, 160)])
key("Escape")
check("transparent selection leaves white behind", px(695, 28) == (255, 255, 255, 255), px(695, 28))
win.state.transparent_sel = False
win.cmd("undo")

# ---- clipboard (needs a clipboard owner, which Xvfb provides)
drag([(300, 50), (402, 152)])
win.cmd("copy")
pump(0.2)
win.cmd("paste")
pump(0.2)
check("paste creates floating selection", doc.float_rect() is not None and doc.float_rect()[2:] == (102, 102), doc.float_rect())
key("Escape")
n = doc.layer_count()
drag([(300, 50), (402, 152)])
win.cmd("copy")
win.cmd("paste_layer")
check("paste as new layer adds a layer", doc.layer_count() == n + 1)
key("Escape")

# ---- nudge with arrows
drag([(300, 50), (310, 60)])
area.grab_focus()
pump(0.05)
key("Right")
check("arrow key nudges selection", doc.float_rect() is not None and doc.float_rect()[0] == 301, doc.float_rect())
key("Escape")

# ---- rotate/flip selection and image
drag([(300, 50), (350, 150)])
win.cmd("rot_cw")
check("rotating a selection rotates the float", doc.float_rect() is not None and doc.float_rect()[2:] == (100, 50), doc.float_rect())
key("Escape")
win.cmd("undo")
w0, h0 = doc.width, doc.height
win.set_tool("pencil")
for c in ("rot_cw", "rot_ccw", "rot_180", "flip_h", "flip_v"):
    win.cmd(c)
check("image rotations/flips", (doc.width, doc.height) == (w0, h0))
pump(0.1)
check("display is bound to the live engine buffer after flips", cv.surf_key[3] == doc.comp_ptr())
win.cmd("rot_cw")
check("rotate right swaps size", (doc.width, doc.height) == (h0, w0))
win.cmd("undo")

# ---- resize/skew/properties/canvas handles
answers["resize"] = (576, 324, 0, 0, True)
win.cmd("resize")
check("resize to 50%", (doc.width, doc.height) == (576, 324))
win.cmd("undo")
answers["resize"] = (w0, h0, 10, 0, True)
win.cmd("resize")
check("skew grows canvas", doc.width > w0)
win.cmd("undo")
answers["props"] = (800, 600)
win.cmd("properties")
check("image properties changes canvas size", (doc.width, doc.height) == (800, 600))
win.cmd("undo")
hx, hy = cv._canvas_handle_points()["se"]
cv._press(area, ev(Gdk.EventType.BUTTON_PRESS, hx, hy))
cv._motion(area, ev(Gdk.EventType.MOTION_NOTIFY, hx + 50, hy + 30))
cv._release(area, ev(Gdk.EventType.BUTTON_RELEASE, hx + 50, hy + 30))
check("canvas corner handle enlarges canvas", doc.width == w0 + 50 and doc.height == h0 + 30, (doc.width, doc.height))
check("new canvas area is transparent", px(doc.width - 2, doc.height - 2)[3] == 0)
win.cmd("undo")
lp0 = win.layers
lp0.list.select_row(lp0._row_for_layer(0))
pump(0.05)
win.cmd("invert_colors")
check("invert colors", px(1100, 600, True) == (0, 0, 0, 255), px(1100, 600, True))
win.cmd("undo")

# crop
win.set_tool("select")
drag([(10, 10), (210, 110)])
win.cmd("crop")
check("crop to selection", (doc.width, doc.height) == (200, 100))
win.cmd("undo")
check("undo crop", (doc.width, doc.height) == (w0, h0))

# ---- layers
lp = win.layers
n = doc.layer_count()
a0 = doc.active
win.cmd("layer_add")
check("add layer above the active one", doc.layer_count() == n + 1 and doc.active == a0 + 1)
win.set_tool("brush")
win.set_brush("brush")
win.set_color(1, (0, 0, 255, 255))
win.set_size(30)
drag([(500, 500), (700, 500)])
check("painting goes to the new layer", doc.layer_props(doc.active) and px(600, 500) == (0, 0, 255, 255) and px(600, 500, True)[2] == 255)
lp.opacity.set_value(50)
lp._opacity_done()
check("layer opacity 50%", abs(doc.layer_props(doc.active)["opacity"] - 0.5) < 0.01 and 100 < px(600, 500, True)[0] < 160, px(600, 500, True))
lp.blend.set_active(1)
check("blend mode multiply", doc.layer_props(doc.active)["blend"] == 1)
lp.toggle_visible(doc.active)
check("hide layer", px(600, 500, True)[2] != 255 or px(600, 500, True)[0] > 200)
lp.toggle_visible(doc.active)
answers["layerprops"] = ("Ink", 1.0, True, 0, 0)
win.cmd("layer_props")
check("layer properties rename", doc.layer_name(doc.active) == "Ink")
win.cmd("layer_dup")
check("duplicate layer", doc.layer_count() == n + 2 and doc.layer_name(doc.active) == "Ink copy")
win.cmd("layer_down")
check("move layer down", doc.active == a0 + 1)
win.cmd("layer_up")
check("move layer up", doc.active == a0 + 2)
win.cmd("layer_merge")
check("merge down", doc.layer_count() == n + 1)
win.cmd("layer_delete")
check("delete layer", doc.layer_count() == n)
# row selection switches active layer
win.cmd("layer_add")
row = lp._row_for_layer(0)
lp.list.select_row(row)
pump(0.05)
check("clicking a row makes that layer active", doc.active == 0)
win.cmd("flatten")
check("flatten", doc.layer_count() == 1)

# ---- undo everything, redo everything
steps = 0
while doc.can_undo() and steps < 500:
    win.cmd("undo")
    steps += 1
check("undo back to blank (%d steps)" % steps, px(30, 10) == (255, 255, 255, 255) and doc.layer_count() == 1)
r = 0
while doc.can_redo() and r < 500:
    win.cmd("redo")
    r += 1
check("redo everything (%d steps)" % r, r == steps and doc.layer_count() == 1)

# ---- view toggles, zoom
for k in ("rulers", "grid", "statusbar", "layers"):
    win.cmd("view_toggle", k)
    win.cmd("view_toggle", k)
check("view toggles round-trip", win.state.view["statusbar"] and win.state.view["layers"])
win.cmd("view_toggle", "rulers")
win.cmd("view_toggle", "grid")
for c in ("zoom_in", "zoom_in", "zoom_out", "zoom_fit", "zoom_100"):
    win.cmd(c)
check("zoom commands", abs(cv.z - 1.0) < 1e-6)
win.set_tool("zoom")
click(100, 100)
check("magnifier zooms in", cv.z == 2)
click(100, 100, button=3)
check("magnifier right-click zooms out", cv.z == 1)
shot(win, os.path.join(OUT, "rulers_grid.png"))
win.cmd("view_toggle", "rulers")
win.cmd("view_toggle", "grid")

# ---- ribbon buttons: click every plain button/toggle to make sure none throw
def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


clicked = 0
for w in list(walk(win.ribbon.home)) + list(walk(win.ribbon.view)):
    if isinstance(w, Gtk.Button):
        print("  click", (w.get_tooltip_text() or "").split("\n")[0], flush=True)
    if isinstance(w, Gtk.Button) and not isinstance(w, Gtk.MenuButton) and w.get_sensitive() and w.get_mapped():
        if "Edit colors" in (w.get_tooltip_text() or "") or w is win.ribbon.paste_btn:
            continue
        if isinstance(w, Gtk.ToggleButton) and not isinstance(w, Gtk.CheckButton):
            w.set_active(not w.get_active())
        else:
            w.clicked()
        clicked += 1
        pump(0.005)
        if cv.pending:
            cv.commit_pending()
check("clicked %d ribbon buttons without errors" % clicked, clicked > 40)
win.set_tool("pencil")

# menus: activate every item in the File menu and dropdown menus (dialogs are canned)
answers["resize"] = None
answers["props"] = None
# ---- File view (the suite's full-window File page instead of a menu)
win.show_backstage()
pump(0.05)
check("File opens the File view", win.backstage_open() and win.body.get_visible_child_name() == "backstage")
for page in ("home", "new", "open", "info", "saveas", "print", "export", "about"):
    win.backstage.nav(page)
    pump(0.03)
    check("File view page %s" % page, win.backstage.stack.get_visible_child_name() == page and not ERRORS)
shot(win, os.path.join(OUT, "backstage.png"))


def find_named(w, name):
    if w.get_name() == name:
        return w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            r = find_named(c, name)
            if r is not None:
                return r
    return None


win.backstage.nav("new")
pump(0.02)
tile = find_named(win.backstage, "tile-transparent")
check("New page has a transparent picture tile", tile is not None)
if tile is not None:
    tile.clicked()
    pump(0.05)
check("the tile makes a transparent picture and leaves the File view", not win.backstage_open() and win.doc.has_transparency())
win.show_backstage("info")
pump(0.02)
info = find_named(win.backstage, "info")
labels = [c.get_text() for c in info.get_children() if isinstance(c, Gtk.Label)] if info else []
check("Info shows the picture size", any("pixels" in t for t in labels), labels)
key("Escape")
check("Esc leaves the File view", not win.backstage_open())
win.cmd("new")

# ---- KeyTips: tap Alt, type a tab letter, then a control's letters
win._key(win, FakeKey(Gdk.KEY_Alt_L, 0))
win._key_release(win, FakeKey(Gdk.KEY_Alt_L, 0))
pump(0.05)
tips = win.keytips.tips()
check("Alt shows KeyTips on the tabs, Quick Access and search", win.keytips.active and {"F", "H", "W", "1", "2", "3", "Q"} <= set(tips), tips)
key("h")
pump(0.1)
tips = win.keytips.tips()
check("H shows the Home tab's KeyTips", "P" in tips and "SE" in tips and "EC" in tips, tips)
key("e")
pump(0.1)
check("E picks the eraser", win.state.tool == "eraser" and not win.keytips.active, win.state.tool)
win.keytips.start()
key("w")
pump(0.1)
check("W opens View with its KeyTips", win.ribbon.stack.get_visible_child_name() == "view" and "R" in win.keytips.tips(), win.keytips.tips())
key("Escape")
check("Esc steps back to the tab letters", win.keytips.active and win.keytips.level == 1)
key("Escape")
check("a second Esc leaves KeyTips", not win.keytips.active)
key("f", Gdk.ModifierType.MOD1_MASK)
pump(0.05)
check("Alt+F opens the File view", win.backstage_open())
key("Escape")
key("h", Gdk.ModifierType.MOD1_MASK)
pump(0.05)
check("Alt+H goes to Home with its KeyTips", win.ribbon.stack.get_visible_child_name() == "home" and win.keytips.active)
key("Escape")
key("Escape")
win.set_tool("pencil")

# ---- search (Alt+Q)
key("q", Gdk.ModifierType.MOD1_MASK)
check("Alt+Q goes to the search box", win.get_focus() is win.search)
m = win.search_matches("flip h")
check("search finds commands", m and SEARCH[m[0]][0] == "Flip horizontal", [SEARCH[i][0] for i in m])
n0 = win.doc.changes
win.run_search(m[0])
pump(0.02)
check("running a found command does it", win.doc.changes != n0)
win.run_search(win.search_matches("eraser")[0])
check("search also picks tools", win.state.tool == "eraser")
win.set_tool("pencil")

# ---- Quick Access Toolbar
check("Quick Access starts with Save, Undo, Redo", win.qat_order() == ["save", "undo", "redo"], win.qat_order())
win.set_qat("print", True)
check("Quick Access can add Print", win.qa_buttons["print"].get_visible() and win.qat_order()[-1] == "print")
win.set_qat("print", False)
check("and remove it", not win.qa_buttons["print"].get_visible())

# ---- save/load every format, layers preserved in .ora
win.new_document()
doc = win.doc
win.set_tool("brush")
win.set_color(1, (200, 0, 0, 255))
drag([(100, 100), (300, 100)])
win.cmd("layer_add")
win.set_color(1, (0, 0, 200, 128))
drag([(100, 200), (300, 200)])
answers["choice"] = 2
for ext in (".png", ".jpg", ".bmp", ".gif", ".ora"):
    path = os.path.join(OUT, "audit" + ext)
    win.warned_flatten = False
    ok = win.save_to(path, __import__("folio_draw.window", fromlist=["SAVE_FORMATS"]).SAVE_FORMATS[ext][0])
    check("save %s" % ext, ok and os.path.getsize(path) > 100)
    d2 = E.Document.load(path)
    if ext == ".ora":
        check("reopen .ora keeps 2 layers", d2.layer_count() == 2)
    c = d2.pick(200, 100, True)
    check("reopen %s pixel is red-ish" % ext, c[0] > 150 and c[2] < 60, c)
    d2.close()
check("save clears dirty flag", not win.is_dirty())
win.doc.set_active(0)
win.set_tool("eraser")
drag([(500, 400), (600, 400)])
win.save_to(os.path.join(OUT, "alpha.png"), E.FMT_PNG)
check("PNG keeps alpha", E.Document.load(os.path.join(OUT, "alpha.png")).pick(550, 400, True)[3] == 0)
win.open_path(os.path.join(OUT, "audit.ora"), ask=False)
check("open .ora in window", win.doc.layer_count() == 2 and win.layers.list.get_children().__len__() == 2)

# ---- animation: layers as GIF frames
import time as _t  # noqa: E402
win.new_document(transparent=True)
doc = win.doc
win.set_tool("shape")
win.set_shape("oval")
win.cmd("fillmode", True)
win.set_color(1, (0, 0, 0, 255))
win.set_color(2, (237, 28, 36, 255))
for f in range(4):
    if f:
        win.cmd("layer_add")
    drag([(100 + f * 150, 200), (220 + f * 150, 320)])
    cv.commit_pending()
    doc.layer_set(doc.active, delay=100 + f * 50, record=True)
win.cmd("fillmode", False)
check("4 frames as 4 layers", doc.layer_count() == 4)
win.cmd("frames_view", True)
check("frames view shows only the active layer", px(160, 260, True)[3] == 0 and px(610, 260, True)[0] == 237, (px(160, 260, True), px(610, 260, True)))
win.cmd("frame_step", 1)
check("next frame wraps to the first", doc.active == 0 and px(160, 260, True)[0] == 237 and px(610, 260, True)[3] == 0)
key("period")
check("'.' key steps to the next frame", doc.active == 1)
key("comma")
check("',' key steps back", doc.active == 0)
win.cmd("play", True)
check("play starts", win.playing and win.ribbon.play_btn.get_active())
seen = set()
t_end = _t.time() + 1.2
while _t.time() < t_end:
    pump(0.03)
    seen.add(doc.active)
check("playback advances through frames (%s)" % sorted(seen), len(seen) >= 3)
click(50, 50)
check("clicking the canvas stops playback and restores the frame", not win.playing and doc.active == 0)
win.cmd("frames_view", False)
check("frames view off shows all layers again", px(160, 260, True)[0] == 237 and px(610, 260, True)[0] == 237)
win.cmd("frames_view", True)
# delay editing via layer properties (undoable)
answers["layerprops"] = ("Frame A", 1.0, True, 0, 333)
win.cmd("layer_props")
check("frame time set in layer properties", doc.layer_props(doc.active)["delay"] == 333)
win.cmd("undo")
check("frame time change is undoable", doc.layer_props(doc.active)["delay"] == 100)
# loop setting + save as animation
win.ribbon.loop_combo.set_active(1)  # "Once"
check("plays-once setting", doc.gif_loop == -1)
win.ribbon.loop_combo.set_active(3)  # "3 times" -> repeat 2
gif_path = os.path.join(OUT, "anim.gif")
win.gif_mode = None
answers["choice"] = 2
ok = win.save_to(gif_path, E.FMT_GIF)
check("save as animated GIF", ok and win.gif_mode == "anim")
d2 = E.Document.load(gif_path)
check("reopened GIF has 4 frame layers", d2.layer_count() == 4)
check("frame times survive", [d2.layer_props(i)["delay"] for i in range(4)] == [100, 150, 200, 250], [d2.layer_props(i)["delay"] for i in range(4)])
check("loop setting survives", d2.gif_loop == 2)
check("reopened animation starts in frames view", d2.frames_view)
def gif_view(b):
    """What a GIF can hold: on/off transparency, exact colour where opaque."""
    return bytes(v for k in range(0, len(b), 4) for v in ((b[k], b[k + 1], b[k + 2], 1) if b[k + 3] >= 128 else (0, 0, 0, 0)))


same = all(gif_view(d2.layer_rgba(i)) == gif_view(doc.layer_rgba(i)) for i in range(4))
check("every frame round-trips exactly (within GIF's on/off transparency)", same)
d2.close()
win.save_to(os.path.join(OUT, "anim.png"), E.FMT_PNG)
pngd = E.Document.load(os.path.join(OUT, "anim.png"))
check("PNG export ignores frames view (all visible layers)", pngd.pick(160, 260, True)[0] == 237 and pngd.pick(610, 260, True)[0] == 237)
pngd.close()
win.save_to(os.path.join(OUT, "anim.ora"), E.FMT_ORA)
od = E.Document.load(os.path.join(OUT, "anim.ora"))
check("OpenRaster keeps frame times, loop and frames view", od.layer_props(3)["delay"] == 250 and od.gif_loop == 2 and od.frames_view)
od.close()
# flattened GIF choice
win.gif_mode = None
answers["choice"] = 1
win.save_to(os.path.join(OUT, "flat.gif"), E.FMT_GIF)
fd = E.Document.load(os.path.join(OUT, "flat.gif"))
check("flattened GIF choice gives a single picture", fd.layer_count() == 1)
fd.close()
answers["choice"] = 2
win.open_path(gif_path, ask=False)
check("opening an animated GIF in the window", win.doc.layer_count() == 4 and win.ribbon.frames_btn.get_active() and "frames" in win.hint_label.get_text())
win.set_tool("pencil")
shot(win, os.path.join(OUT, "animation.png"))

shot(win, os.path.join(OUT, "final.png"))
print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
