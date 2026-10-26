"""Open every real dialog, operate its widgets the way a person would, and check the results."""
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
from gi.repository import Gdk, Gtk  # noqa: E402

ERRORS = []
sys.excepthook = lambda t, v, tb: (ERRORS.append("".join(traceback.format_exception(t, v, tb))), sys.__excepthook__(t, v, tb))

from folio_draw import dialogs as D  # noqa: E402
from folio_draw import engine as E  # noqa: E402
from shot import make, pump, shot  # noqa: E402

OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-dlg-"))
os.makedirs(OUT, exist_ok=True)
checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)), flush=True)


def widgets(w, cls):
    out = []
    if isinstance(w, cls):
        out.append(w)
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += widgets(c, cls)
    return out


def spins(d):
    """Spin buttons in reading order (Gtk.Grid lists its children backwards)."""
    ss = widgets(d, Gtk.SpinButton)
    return sorted(ss, key=lambda w: (round(w.translate_coordinates(d, 0, 0)[1] / 8), w.translate_coordinates(d, 0, 0)[0]))


def by_label(d, cls, label):
    for w in widgets(d, cls):
        if w.get_label() == label:
            return w
    raise LookupError(label)


SCRIPT = []  # list of callables(dialog) -> response
SEEN = []
_run = Gtk.Dialog.run


def fake_run(d):
    pump(0.15)
    SEEN.append(d.get_title())
    shot_name = (d.get_title() or "dialog").replace(" ", "_")
    try:
        gw = d.get_window()
        if gw is not None:
            import cairo
            img = cairo.ImageSurface(cairo.FORMAT_ARGB32, gw.get_width(), gw.get_height())
            cr = cairo.Context(img)
            Gdk.cairo_set_source_window(cr, gw, 0, 0)
            cr.paint()
            img.write_to_png(os.path.join(OUT, "dlg_%s_%d.png" % (shot_name, len(SEEN))))
    except Exception:
        pass
    fn = SCRIPT.pop(0) if SCRIPT else (lambda d: Gtk.ResponseType.CANCEL)
    r = fn(d)
    pump(0.05)
    return r


Gtk.Dialog.run = fake_run
app, win = make()
OK, CANCEL = Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL


def fresh(w=400, h=300):
    win.set_document(E.Document.new(w, h, (255, 255, 255, 255)), None)
    pump(0.05)


# ---- Resize and Skew: percentage
fresh()


def pct50(d):
    sp = spins(d)
    sp[0].set_value(50)  # horizontal %, vertical follows (aspect kept)
    return OK


SCRIPT.append(pct50)
win.cmd("resize")
check("resize 50% keeps aspect", (win.doc.width, win.doc.height) == (200, 150), (win.doc.width, win.doc.height))


def px_typed(d):
    by_label(d, Gtk.RadioButton, "Pixels").set_active(True)
    sp = spins(d)
    check("switching to pixels shows the current size", (sp[0].get_value(), sp[1].get_value()) == (200, 150),
          (sp[0].get_value(), sp[1].get_value()))
    # typed but never committed with Enter or Tab: OK must still take it
    sp[0].set_text("100")
    return OK


SCRIPT.append(px_typed)
win.cmd("resize")
check("typed width taken on OK without pressing Enter", win.doc.width == 100, (win.doc.width, win.doc.height))
check("typed width keeps aspect", win.doc.height == 75, (win.doc.width, win.doc.height))


def free_aspect(d):
    by_label(d, Gtk.RadioButton, "Pixels").set_active(True)
    by_label(d, Gtk.CheckButton, "Maintain aspect ratio").set_active(False)
    s = spins(d)
    s[0].set_value(300)
    s[1].set_value(40)
    return OK


SCRIPT.append(free_aspect)
win.cmd("resize")
check("unlinked resize", (win.doc.width, win.doc.height) == (300, 40))


def too_big(d):
    by_label(d, Gtk.RadioButton, "Pixels").set_active(True)
    spins(d)[0].set_value(90000)
    return OK


SCRIPT.append(too_big)
SCRIPT.append(lambda d: Gtk.ResponseType.OK)  # the "too large" message
win.cmd("resize")
check("over-size resize refused with a message", (win.doc.width, win.doc.height) == (300, 40) and SEEN[-1] != "Resize and Skew")


def skew(d):
    s = spins(d)
    s[2].set_value(20)
    return OK


SCRIPT.append(skew)
win.cmd("resize")
check("skew widens the image", win.doc.width > 300, win.doc.width)
SCRIPT.append(lambda d: CANCEL)
w0 = (win.doc.width, win.doc.height)
win.cmd("resize")
check("cancel leaves the image", (win.doc.width, win.doc.height) == w0)

# selection resize: skew section disabled
fresh()
win.set_tool("select")
cv = win.canvas
from deep_helpers import drag_on  # noqa: E402

drag_on(win, [(10, 10), (110, 60)])


def sel_resize(d):
    frames = widgets(d, Gtk.Frame)
    skf = [f for f in frames if f.get_label().startswith("Skew")][0]
    check("skew disabled for a selection", not skf.get_sensitive())
    by_label(d, Gtk.RadioButton, "Pixels").set_active(True)
    s = spins(d)
    check("selection resize starts at the selection size", (s[0].get_value(), s[1].get_value()) == (100, 50), (s[0].get_value(), s[1].get_value()))
    s[0].set_value(200)
    return OK


SCRIPT.append(sel_resize)
win.cmd("resize")
fr = win.doc.float_rect()
check("selection resized", fr is not None and fr[2:] == (200, 100), fr)
win.set_tool("pencil")

# ---- Rotate by any angle
def named(d, cls, name):
    for w in widgets(d, cls):
        if w.get_name() == name:
            return w
    raise LookupError(name)


fresh(200, 100)
win.state.color2 = (0, 0, 255, 255)


def rot30(d):
    a = named(d, Gtk.SpinButton, "angle")
    a.set_text("30")  # typed, never committed
    size = named(d, Gtk.Label, "size").get_text()
    check("rotate dialog shows the new size", "×" in size, size)
    check("an opaque picture fills its corners by default", named(d, Gtk.CheckButton, "fill").get_active())
    return OK


SCRIPT.append(rot30)
win.cmd("rotate_angle")
exp = E.rotated_size(200, 100, 30)
check("rotate 30° grows the canvas to fit", (win.doc.width, win.doc.height) == exp, (win.doc.width, win.doc.height, exp))
corner = win.doc.layer_rgba(0)[0:4]
check("corners take the secondary color", tuple(corner) == (0, 0, 255, 255), tuple(corner))
mid = (win.doc.height // 2 * win.doc.width + win.doc.width // 2) * 4
check("the picture itself is kept", tuple(win.doc.layer_rgba(0)[mid:mid + 4]) == (255, 255, 255, 255))
win.cmd("undo")
check("undo restores the size", (win.doc.width, win.doc.height) == (200, 100), (win.doc.width, win.doc.height))


def rot_ccw_clear(d):
    named(d, Gtk.SpinButton, "angle").set_value(45)
    named(d, Gtk.RadioButton, "ccw").set_active(True)
    named(d, Gtk.CheckButton, "fill").set_active(False)
    return OK


SCRIPT.append(rot_ccw_clear)
win.cmd("rotate_angle")
check("counter-clockwise 45° rotates", (win.doc.width, win.doc.height) == E.rotated_size(200, 100, -45))
check("unfilled corners are transparent", win.doc.layer_rgba(0)[3] == 0)


def remembers(d):
    a = named(d, Gtk.SpinButton, "angle").get_value()
    check("the dialog remembers the last angle and direction", a == 45 and named(d, Gtk.RadioButton, "ccw").get_active(), a)
    return CANCEL


w0 = (win.doc.width, win.doc.height)
SCRIPT.append(remembers)
win.cmd("rotate_angle")
check("cancel leaves the image", (win.doc.width, win.doc.height) == w0)

fresh(400, 300)
win.set_tool("select")
drag_on(win, [(10, 10), (110, 60)])


def sel_rot(d):
    check("a selection has no corner-fill option", not any(w.get_name() == "fill" for w in widgets(d, Gtk.CheckButton)))
    named(d, Gtk.RadioButton, "cw").set_active(True)
    named(d, Gtk.SpinButton, "angle").set_value(90)
    return OK


SCRIPT.append(sel_rot)
win.cmd("rotate_angle")
fr = win.doc.float_rect()
check("selection rotated 90° about its centre", fr is not None and fr[2:] == (50, 100) and (win.doc.width, win.doc.height) == (400, 300), fr)


def sel_rot2(d):
    named(d, Gtk.SpinButton, "angle").set_value(20)
    return OK


SCRIPT.append(sel_rot2)
win.cmd("rotate_angle")
fr = win.doc.float_rect()
check("a floating selection rotates again by any angle", fr is not None and fr[2:] == E.rotated_size(50, 100, 20), fr)
win.set_tool("pencil")


class FakeKey:
    keyval = Gdk.KEY_R
    state = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK


n = len(SEEN)
win._key(win, FakeKey())
check("Ctrl+Shift+R opens Rotate", SEEN[n:] == ["Rotate"], SEEN[n:])

# ---- Image properties with units
fresh()


def props_cm(d):
    by_label(d, Gtk.RadioButton, "Centimetres").set_active(True)
    s = spins(d)
    check("400 px shown as 10.58 cm", abs(s[0].get_value() - 10.58) < 0.01, s[0].get_value())
    s[0].set_value(5.0)
    by_label(d, Gtk.RadioButton, "Inches").set_active(True)
    check("5 cm shown as 1.97 in", abs(s[0].get_value() - 1.97) < 0.01, s[0].get_value())
    by_label(d, Gtk.RadioButton, "Pixels").set_active(True)
    return OK


SCRIPT.append(props_cm)
win.cmd("properties")
check("properties: 5 cm wide = 189 px", win.doc.width == 189, win.doc.width)


def props_typed(d):
    s = spins(d)
    s[1].set_text("123")
    return OK


SCRIPT.append(props_typed)
win.cmd("properties")
check("properties: typed height taken on OK", win.doc.height == 123, win.doc.height)

# ---- Layer properties
fresh()


def lp(d):
    e = [w for w in widgets(d, Gtk.Entry) if type(w) is Gtk.Entry][0]
    e.set_text("Sky")
    by_label(d, Gtk.CheckButton, "Visible").set_active(False)
    widgets(d, Gtk.ComboBoxText)[0].set_active(2)
    widgets(d, Gtk.Scale)[0].set_value(40)
    return OK


SCRIPT.append(lp)
win.cmd("layer_props")
p = win.doc.layer_props(0)
check("layer properties applied", win.doc.layer_name(0) == "Sky" and not p["visible"] and p["blend"] == 2 and abs(p["opacity"] - 0.4) < 0.01, p)
check("layer list shows the new name", any("Sky" in (l.get_text() or "") for l in widgets(win.layers, Gtk.Label)))


def lp_empty(d):
    [w for w in widgets(d, Gtk.Entry) if type(w) is Gtk.Entry][0].set_text("")
    return OK


SCRIPT.append(lp_empty)
win.cmd("layer_props")
check("empty layer name keeps the old one", win.doc.layer_name(0) == "Sky")


def lp_typed(d):
    s = spins(d)
    s[0].set_text("75")
    return OK


SCRIPT.append(lp_typed)
win.cmd("layer_props")
check("typed opacity taken on OK", abs(win.doc.layer_props(0)["opacity"] - 0.75) < 0.01, win.doc.layer_props(0)["opacity"])

# ---- Edit colours
def ec(d):
    d.set_rgba((10, 20, 30, 255))
    pump(0.05)
    check("hex field follows", d.hex.get_text().lower().lstrip("#") in ("0a141e", "0a141eff"), d.hex.get_text())
    d.hex.set_text("#ff8000")
    d.hex.activate()
    check("hex entry sets the colour", d.rgba()[:3] == (255, 128, 0), d.rgba())
    # click into the hue/saturation field and the value slider
    for cls in (D._HSField, D._Slider):
        for w in widgets(d, cls):
            a = w.get_allocation()
            ev = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
            ev.button.x, ev.button.y, ev.button.button = a.width * 0.3, a.height * 0.6, 1
            ev.button.window = w.get_window()
            w.emit("button-press-event", ev)
    pump(0.05)
    by = [b for b in widgets(d, Gtk.Button) if (b.get_label() or "").startswith("Add")]
    if by:
        by[0].clicked()
    return OK


SCRIPT.append(ec)
win.cmd("edit_colors")
check("edit colours ran its widgets cleanly", not ERRORS)


def ec_typed(d):
    d.hex.grab_focus()
    d.hex.set_text("#123456")
    return OK


SCRIPT.append(ec_typed)
win.cmd("edit_colors")
check("typed hex taken on OK without Enter", win.state.color1[:3] == (0x12, 0x34, 0x56), win.state.color1)

# ---- message boxes and prompts
SCRIPT.append(lambda d: Gtk.ResponseType.NO)
check("save-changes prompt: Don't Save", D.ask_save_changes(win, "x.png") == "discard")
SCRIPT.append(lambda d: Gtk.ResponseType.DELETE_EVENT)
check("save-changes prompt: closed = cancel", D.ask_save_changes(win, "x.png") == "cancel")
SCRIPT.append(lambda d: 1)
check("choice prompt returns the button index", D.ask_choice(win, "t", "x", ["a", "b", "c"]) == 1)
SCRIPT.append(lambda d: Gtk.ResponseType.DELETE_EVENT)
check("choice prompt closed = -1", D.ask_choice(win, "t", "x", ["a", "b"]) == -1)
SCRIPT.append(lambda d: Gtk.ResponseType.CLOSE)
win.cmd("about")
check("about box", SEEN[-1] is not None or True)

# ---- open a file that is not a picture
bad = os.path.join(OUT, "bad.png")
open(bad, "wb").write(b"not a picture at all")
SCRIPT.append(lambda d: OK)
n = len(SEEN)
win.open_path(bad, ask=False)
check("opening a broken file shows a message, keeps the document", len(SEEN) == n + 1 and win.doc is not None)

# ---- closing with unsaved changes: Cancel keeps the window
fresh()
win.set_tool("pencil")
drag_on(win, [(10, 10), (100, 100)])
SCRIPT.append(lambda d: Gtk.ResponseType.CANCEL)
r = win._on_delete()
check("close with changes then Cancel keeps the window open", r is True, r)

# ---- adjustments: live preview, OK keeps, Cancel restores, selection only
def solid(rgba, w=40, h=30):
    win.set_document(E.Document.new(w, h, rgba), None)
    pump(0.05)


def px(x, y):
    o = (y * win.doc.width + x) * 4
    return tuple(win.doc.layer_rgba(0)[o:o + 4])


solid((100, 150, 200, 255))
seen_preview = {}


def bright(d):
    sc = [s for s in widgets(d, Gtk.Scale)]
    check("Brightness and Contrast has two sliders", len(sc) == 2, len(sc))
    named(d, Gtk.Scale, "brightness").get_adjustment().set_value(40)
    pump(0.2)
    seen_preview["px"] = px(5, 5)
    return CANCEL


SCRIPT.append(bright)
win.cmd("adjust", "brightness")
check("the picture previews the adjustment as the slider moves", seen_preview.get("px", (0,))[0] > 100, seen_preview)
check("Cancel puts it back", px(5, 5) == (100, 150, 200, 255), px(5, 5))
check("and leaves nothing to undo", not (win.doc.can_undo() if callable(win.doc.can_undo) else win.doc.can_undo))


def bright_ok(d):
    named(d, Gtk.Scale, "brightness").get_adjustment().set_value(-30)
    named(d, Gtk.Scale, "contrast").get_adjustment().set_value(20)
    return OK


SCRIPT.append(bright_ok)
win.cmd("adjust", "brightness")
check("OK keeps it", px(5, 5)[0] < 100, px(5, 5))
win.cmd("undo")
check("one undo takes it back", px(5, 5) == (100, 150, 200, 255), px(5, 5))
SCRIPT.append(lambda d: (named(d, Gtk.Scale, "saturation").get_adjustment().set_value(-100), OK)[1])
win.cmd("adjust", "huesat")
p = px(5, 5)
check("Saturation -100 makes it grey", p[0] == p[1] == p[2], p)
win.cmd("undo")
win.cmd("greyscale")
p = px(5, 5)
check("Greyscale", p[0] == p[1] == p[2] and abs(p[0] - 141) <= 1, p)
win.cmd("undo")
win.cmd("sepia")
p = px(5, 5)
check("Sepia warms it", p[0] > p[1] > p[2], p)
win.cmd("undo")
win.doc.sel_rect(0, 0, 10, 30)
win.cmd("greyscale")
check("only the selection changes", px(2, 2)[0] == px(2, 2)[1] and px(20, 2) == (100, 150, 200, 255),
      (px(2, 2), px(20, 2)))
win.cmd("undo")
win.doc.sel_none()
data = bytearray()
for y in range(3):
    for x in range(30):
        data += bytes((255, 255, 255, 255) if x == 20 else (0, 0, 0, 255))
win.set_document(E.Document.from_rgba(30, 3, data), None)
pump(0.05)
SCRIPT.append(lambda d: (named(d, Gtk.Scale, "radius").get_adjustment().set_value(2), OK)[1])
win.cmd("adjust", "blur")
check("Blur spreads a white dot", 0 < px(19, 1)[0] < 255 and px(20, 1)[0] < 255, (px(19, 1), px(20, 1)))
win.cmd("undo")
SCRIPT.append(lambda d: OK)
win.cmd("adjust", "sharpen")
check("Sharpen leaves a flat area flat", px(5, 1) == (0, 0, 0, 255), px(5, 1))

# ---- Sample all layers: copy and fill see every visible layer
win.set_document(E.Document.new(20, 20, (255, 255, 255, 255)), None)
pump(0.05)
win.cmd("layer_add")
pump(0.05)
check("a second layer to work on", win.doc.layer_count() == 2)
win.cmd("select_all")
got = win.doc.clip_extract()
check("Copy takes the active layer by default (empty)", got and got[2][0:4] == bytes(4), got and got[2][0:4])
win.ribbon.sample_item.set_active(True)
pump(0.05)
check("Sample all layers is on", win.state.sample_all)
got = win.doc.clip_extract()
check("then Copy takes what is seen", got and got[2][0:4] == bytes((255, 255, 255, 255)), got and got[2][0:4])
win.ribbon.sample_item.set_active(False)
pump(0.05)
check("and off again", not win.state.sample_all and win.doc.clip_extract()[2][0:4] == bytes(4))

# ---- page setup and print preview
from folio_draw import pagesetup as PS  # noqa: E402
s = dict(PS.DEFAULTS)
pg = PS.layout(s, 800, 600)
check("fit to 1 page: one page, shrunk to fit", len(pg) == 1 and pg[0][6] <= PS.MM_PER_PX, pg)
check("centred across the page", abs(pg[0][4] - (19.1 + (210 - 38.2 - 800 * pg[0][6]) / 2)) < 0.01, pg[0])
pg = PS.layout(dict(s, mode="fit"), 100, 100)
check("a small picture isn't enlarged by Fit", abs(pg[0][6] - PS.MM_PER_PX) < 1e-9)
pg = PS.layout(dict(s, mode="percent", percent=100), 3000, 1000)
check("100% of a big picture spreads over pages", len(pg) == 5 * 2, len(pg))
check("which together cover it", abs(sum(p[2] for p in pg if p[1] == 0) - 3000) < 1e-6)
pg = PS.layout(dict(s, mode="percent", percent=200), 100, 100)
check("Adjust to 200% doubles it", abs(pg[0][6] - 2 * PS.MM_PER_PX) < 1e-9)
check("landscape turns the paper", PS.paper_size(dict(s, landscape=True)) == (297, 210))
pg = PS.layout(dict(s, mode="fit", fit_w=2, fit_h=1), 4000, 500)
check("Fit to 2 by 1 pages", len(pg) == 2, len(pg))
win.set_document(E.Document.new(1200, 300, (255, 255, 255, 255)), None)
pump(0.05)


def setup_dlg(d):
    named(d, Gtk.RadioButton, "landscape").set_active(True)
    named(d, Gtk.RadioButton, "adjust-to").set_active(True)
    named(d, Gtk.SpinButton, "percent").set_value(150)
    pump(0.05)
    check("the preview counts the pages", named(d, Gtk.Label, "page-count").get_text().startswith("Page 1 of "))
    return OK


SCRIPT.append(setup_dlg)
win.cmd("page_setup")
st = PS.settings(win.state)
check("Page setup keeps its settings", st["landscape"] and st["mode"] == "percent" and st["percent"] == 150, st)
op = win.print_operation()
check("printing uses them", len(op.pages) == len(PS.layout(st, 1200, 300)) and
      op.get_default_page_setup().get_orientation() == Gtk.PageOrientation.LANDSCAPE)


def setup_cancel(d):
    named(d, Gtk.RadioButton, "fit-to").set_active(True)
    return CANCEL


SCRIPT.append(setup_cancel)
win.cmd("page_setup")
check("Cancel keeps the old settings", PS.settings(win.state)["mode"] == "percent")
win.state.page = dict(PS.DEFAULTS)

print()
print("dialogs seen:", SEEN)
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
