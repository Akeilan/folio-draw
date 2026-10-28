"""Backlog 2 for Draw: pen pressure and tilt (D2-01), Remove background (D2-02), opening SVG and
Photoshop files with their layers (D2-03). Fails loudly on any Python exception in a GTK callback."""
import os
import struct
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


def hook(t, v, tb):
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = hook

from folio_draw import dialogs as D  # noqa: E402
from folio_draw import engine as E  # noqa: E402
from folio_draw.window import SEARCH_COMMANDS as SEARCH  # noqa: E402
from shot import make, pump, shot  # noqa: E402

OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-audit-"))
os.makedirs(OUT, exist_ok=True)
checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))


messages = []
D.message = lambda parent, title, *a, **k: messages.append(title)
D.ask_save_changes = lambda *a, **k: "discard"

app, win = make()
cv = win.canvas
area = cv.area
rb = win.ribbon


class PenEvent:
    """A graphics tablet event: the fields GTK gives the handlers, plus pressure and tilt axes."""

    def __init__(self, kind, x, y, pressure=None, tilt=None, button=1):
        self.type, self.x, self.y, self.button, self.state = kind, float(x), float(y), button, Gdk.ModifierType(0)
        self.pressure, self.tilt = pressure, tilt

    def get_axis(self, axis):
        if axis == Gdk.AxisUse.PRESSURE and self.pressure is not None:
            return True, self.pressure
        if self.tilt is not None and axis in (Gdk.AxisUse.XTILT, Gdk.AxisUse.YTILT):
            return True, self.tilt[0 if axis == Gdk.AxisUse.XTILT else 1]
        return False, 0.0


def at(dx, dy):
    return cv.to_screen(dx, dy)


def pen_drag(points):
    """points: (x, y, pressure, tilt or None)"""
    x, y, p, t = points[0]
    cv._press(area, PenEvent(Gdk.EventType.BUTTON_PRESS, *at(x, y), p, t))
    for x, y, p, t in points[1:]:
        cv._motion(area, PenEvent(Gdk.EventType.MOTION_NOTIFY, *at(x, y), p, t))
    cv._release(area, PenEvent(Gdk.EventType.BUTTON_RELEASE, *at(x, y), p, t))
    pump(0.02)


def px(x, y, all_layers=False):
    return win.doc.pick(x, y, all_layers)


def dark_rows(x, y0=0, y1=400):
    return sum(1 for y in range(y0, y1) if px(x, y)[0] < 128)


win.canvas.set_zoom(1.0, (0, 0))
win.new_document()
pump(0.2)

# ---------------------------------------------------------------- D2-01 pen pressure and tilt
win.set_tool("brush")
win.state.brush = "brush"
win.set_size(30)
win.state.color1 = (0, 0, 0, 255)
ramp = [(40 + i * 4, 100, 0.05 + 0.95 * i / 100, None) for i in range(101)]
pen_drag(ramp)
light, heavy = dark_rows(60, 50, 150), dark_rows(420, 50, 150)
check("light pen pressure paints a thin line, full pressure the full width", light < 10 and heavy >= 27, (light, heavy))
# a mouse (no pressure axis) paints at full size
pen_drag([(40 + i * 4, 200, None, None) for i in range(101)])
check("a mouse still paints the full width", dark_rows(60, 150, 250) >= 27 and dark_rows(420, 150, 250) >= 27)
win.new_document()
cv.set_zoom(1.0, (0, 0))
pen_drag(ramp[:30])
drawn = px(60, 100)[0] < 128
win.cmd("undo")
check("a pen stroke is one step to undo", drawn and px(60, 100)[0] == 255 and not win.doc.can_undo())

# opacity, per brush
win.state.brush = "soft"
check("the soft brush has its own pen settings (size and opacity)", win.state.pen["soft"][1] > 0 and win.state.pen["brush"][1] == 0,
      win.state.pen)
win.cmd("pen", 0, 0)
win.cmd("pen", 1, 100)
check("changing one brush's pen settings leaves the others", win.state.pen["soft"][:2] == [0, 100] and win.state.pen["brush"][0] == 100)
pen_drag([(40 + i * 4, 300, 0.3, None) for i in range(101)])
g = px(240, 300)[0]
check("pressure sets the opacity: light pressure leaves a pale stroke", 120 < g < 230, g)
win.state.brush = "brush"

# tilt turns the calligraphy nib
win.state.brush = "callig"
win.set_size(30)
check("tilt is on for the calligraphy brushes by default", win.state.pen["callig"][2] is True)
win.new_document()
cv.set_zoom(1.0, (0, 0))
pen_drag([(40 + i * 4, 100, 1.0, (0.0, 0.8)) for i in range(101)])
pen_drag([(40 + i * 4, 250, 1.0, (0.8, 0.0)) for i in range(101)])
upright, flat = dark_rows(240, 50, 180), dark_rows(240, 200, 320)
check("a pen held upright draws a tall nib stroke, held flat a thin one", upright > 20 and flat < 8, (upright, flat))
win.cmd("pen", 2, False)
win.new_document()
cv.set_zoom(1.0, (0, 0))
pen_drag([(40 + i * 4, 100, 1.0, (0.8, 0.0)) for i in range(101)])
check("with tilt off the nib keeps its fixed angle", dark_rows(240, 50, 180) > 12)
win.cmd("pen", 2, True)

# the settings in the Size menu
rb.size_btn.set_active(True)
pump(0.2)
check("the Size menu shows the pen pressure settings for the brush", rb.pen_box.get_visible() and "Calligraphy" in rb.pen_title.get_text(),
      rb.pen_title.get_text())
check("the tilt option shows for a calligraphy brush", rb.pen_tilt.get_visible() and rb.pen_tilt.get_active())
shot(win, os.path.join(OUT, "d2_pen_menu.png"))
rb.pen_scales[0].set_value(40)
check("the Size menu changes the brush's pen setting", win.state.pen["callig"][0] == 40, win.state.pen["callig"])
rb.size_btn.set_active(False)
win.state.brush = "brush"
win.set_tool("pencil")
rb.size_btn.set_active(True)
pump(0.1)
check("the pencil shows its own pen settings, without tilt", rb.pen_box.get_visible() and not rb.pen_tilt.get_visible())
rb.size_btn.set_active(False)
win.set_tool("fill")
rb.size_btn.set_active(True)
pump(0.1)
check("tools without strokes show no pen settings", not rb.pen_box.get_visible())
rb.size_btn.set_active(False)
st2 = type(win.state)()
st2.load()
check("the pen settings are remembered", st2.pen["callig"][0] == 40 and st2.pen["soft"][:2] == [0, 100], st2.pen)

# ---------------------------------------------------------------- D2-02 Remove background
from gi.repository import GdkPixbuf  # noqa: E402
import cairo  # noqa: E402

W, H = 400, 300
surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
cr = cairo.Context(surf)
grad = cairo.LinearGradient(0, 0, 0, H)
grad.add_color_stop_rgb(0, 0.55, 0.75, 0.95)
grad.add_color_stop_rgb(1, 0.85, 0.92, 1.0)
cr.set_source(grad)
cr.paint()
cr.set_source_rgb(0.75, 0.2, 0.1)
cr.arc(200, 170, 80, 0, 6.2832)
cr.fill()
cr.set_source_rgb(0.2, 0.5, 0.15)
cr.rectangle(170, 40, 60, 60)
cr.fill()
pic = os.path.join(OUT, "subject.png")
surf.write_to_png(pic)
win.open_path(pic, ask=False)
pump(0.2)
check("Remove background is on the Home tab in the Image group", rb.removebg_btn.get_visible() and rb.removebg_btn.get_mapped())
check("Remove background has a KeyTip", getattr(rb.removebg_btn, "keytip", None) == "RB")
check("Search finds Remove background", any(c == ("remove_background",) for _, c, _ in SEARCH))
rb.removebg_btn.clicked()
pump(0.2)
check("the sky is gone (top and bottom)", px(10, 10)[3] == 0 and px(390, 290)[3] == 0, (px(10, 10), px(390, 290)))
check("the subject stays", px(200, 170)[3] == 255 and px(200, 70)[3] == 255)
check("the sky between the two shapes is background too", px(200, 100)[3] == 255 and px(160, 70)[3] == 0, (px(200, 100), px(160, 70)))
shot(win, os.path.join(OUT, "d2_removebg.png"))
win.cmd("undo")
check("Remove background is one step to undo", px(10, 10)[3] == 255)
win.doc.sel_rect(0, 0, 200, 300)
win.cmd("remove_background")
check("with a selection, only the selected part is cut out", px(10, 10)[3] == 0 and px(390, 10)[3] == 255, (px(10, 10), px(390, 10)))
win.doc.sel_none()
blank = os.path.join(OUT, "blank.png")
s2 = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
s2.write_to_png(blank)
win.open_path(blank, ask=False)
messages.clear()
win.cmd("remove_background")
check("a picture with nothing to remove says so", messages and "background" in messages[-1], messages)

# ---------------------------------------------------------------- D2-03 open SVG and Photoshop files
svg = os.path.join(OUT, "drawing.svg")
with open(svg, "w") as f:
    f.write('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200">'
            '<rect x="20" y="20" width="100" height="80" fill="#ff0000"/>'
            '<circle cx="230" cy="120" r="50" fill="#0000ff" fill-opacity="0.5"/></svg>')
ok = win.open_path(svg, ask=False)
pump(0.2)
check("an SVG drawing opens as a picture at its own size", ok and (win.doc.width, win.doc.height) == (320, 200),
      (ok, win.doc.width, win.doc.height))
check("its shapes and transparency come in", px(60, 60)[:3] == (255, 0, 0) and px(5, 5)[3] == 0 and 100 < px(230, 120)[3] < 160,
      (px(60, 60), px(5, 5), px(230, 120)))
from folio_draw.window import SAVE_FORMATS  # noqa: E402
check("an opened SVG is saved as another format", ".svg" not in SAVE_FORMATS)


def psd(w, h, layers, merged):
    """A layered RGB Photoshop file, written the way Photoshop lays it out (raw channel data here)."""
    recs, data = b"", b""
    for name, rect, rgba, opacity, hidden, blend in layers:
        t, l, b, r = rect
        lw, lh = r - l, b - t
        chans = [(-1, rgba[3]), (0, rgba[0]), (1, rgba[1]), (2, rgba[2])]
        recs += struct.pack(">iiiiH", t, l, b, r, len(chans))
        for cid, v in chans:
            body = struct.pack(">H", 0) + bytes([v]) * (lw * lh)
            recs += struct.pack(">hI", cid, len(body))
            data += body
        nb = name.encode("latin-1", "replace")
        pas = bytes([len(nb)]) + nb
        pas += b"\0" * ((4 - len(pas) % 4) % 4)
        u = name.encode("utf-16-be")
        lu = struct.pack(">I", len(name)) + u
        lu += b"\0" * ((4 - len(lu) % 4) % 4)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + pas + b"8BIMluni" + struct.pack(">I", len(lu)) + lu
        recs += b"8BIM" + blend + bytes([opacity, 0, 2 if hidden else 0, 0]) + struct.pack(">I", len(extra)) + extra
    li = struct.pack(">h", -len(layers)) + recs + data
    li += b"\0" * (len(li) % 2)
    lm = struct.pack(">I", len(li)) + li + struct.pack(">I", 0)
    out = b"8BPS" + struct.pack(">H", 1) + b"\0" * 6 + struct.pack(">HIIHH", 3, h, w, 8, 3)
    out += struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", len(lm)) + lm
    out += struct.pack(">H", 0) + b"".join(bytes([c]) * (w * h) for c in merged)
    return out


p = os.path.join(OUT, "layers.psd")
with open(p, "wb") as f:
    f.write(psd(120, 80, [("Background", (0, 0, 80, 120), (255, 255, 255, 255), 255, False, b"norm"),
                          ("Red square", (10, 10, 40, 40), (255, 0, 0, 255), 255, False, b"norm"),
                          ("Shadow", (20, 50, 70, 110), (0, 0, 0, 255), 128, False, b"mul "),
                          ("Hidden note", (0, 0, 20, 20), (0, 255, 0, 255), 255, True, b"norm")], (9, 9, 9)))
ok = win.open_path(p, ask=False)
pump(0.2)
names = [win.doc.layer_name(i) for i in range(win.doc.layer_count())]
check("a Photoshop file opens with its layers", ok and win.doc.layer_count() == 4, (ok, win.doc.layer_count()))
info = [win.doc.layer_props(i) for i in range(win.doc.layer_count())]
check("layer names, opacity, blend and visibility come in",
      names == ["Background", "Red square", "Shadow", "Hidden note"] and abs(info[2]["opacity"] - 128 / 255) < 0.01
      and info[2]["blend"] == 1 and not info[3]["visible"] and info[1]["visible"], (names, info))
check("the layers sit where they were", px(25, 25, True)[:3] == (255, 0, 0)
      and px(5, 70, True)[:3] == (255, 255, 255), (px(25, 25), px(5, 70, True)))
check("the Layers panel lists them", len(win.layers.list.get_children()) == 4)
shot(win, os.path.join(OUT, "d2_psd.png"))
check("the open dialog lists Photoshop and SVG files", any(".psd" in x for x in __import__("folio_draw.window", fromlist=["x"]).OPEN_PATTERNS)
      and any(".svg" in x for x in __import__("folio_draw.window", fromlist=["x"]).OPEN_PATTERNS))
bad = os.path.join(OUT, "bad.psd")
with open(bad, "wb") as f:
    f.write(b"8BPS\0\1" + b"\0" * 30)
messages.clear()
ok = win.open_path(bad, ask=False)
check("a damaged Photoshop file is refused with a message", not ok and messages, messages)

# ---------------------------------------------------------------- X2-04 the same text height on 22.04 and 24.04
from folio_draw import fontfix  # noqa: E402
labs = []


def labels(w):
    if isinstance(w, Gtk.Label) and w.get_mapped() and w.get_text() and "\n" not in w.get_text():
        labs.append(w)
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            labels(c)


labels(rb)
hs = sorted(l.get_allocated_height() for l in labs)
check("ribbon labels are one line of 9 pt text tall", bool(hs) and hs[len(hs) // 2] <= 17,  # 16 on 22.04; 24.04's tall Carlito made it 20
      (hs[len(hs) // 2] if hs else None, "tall Carlito: %s" % fontfix.needed()))

# ---------------------------------------------------------------- M-12 File > Send in email
import time  # noqa: E402
fake = tempfile.mkdtemp(prefix="fd-bin-")
log = os.path.join(fake, "log")
with open(os.path.join(fake, "folio-post"), "w") as f:
    f.write("#!/bin/sh\necho \"$@\" >> %s\n" % log)
os.chmod(os.path.join(fake, "folio-post"), 0o755)
os.environ["PATH_SAVED"] = os.environ["PATH"]
os.environ["PATH"] = fake + ":" + os.environ["PATH"]
win.open_path(p, ask=False)
win.show_backstage()
pump(0.2)
win.backstage.nav("share")
pump(0.2)
shot(win, os.path.join(OUT, "d2_share.png"))
check("the File view has Send in email", "share" in win.backstage.nav_buttons)
names_ = []


def walk(w):
    names_.append(w.get_name())
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            walk(c)


walk(win.backstage.stack.get_visible_child())
check("it offers a PNG and a layered picture", "send-png" in names_ and "send-ora" in names_)
win.hide_backstage()
a = win.cmd("send_email", "png")
b = win.cmd("send_email", "ora")
t0 = time.time()
while time.time() - t0 < 5 and not (os.path.exists(log) and len(open(log).read().splitlines()) >= 2):
    pump(0.1)
lines = open(log).read().splitlines() if os.path.exists(log) else []
check("Send in email hands the picture to Folio Post as an attachment", len(lines) == 2 and lines[0] == "--attach " + a
      and a.endswith("layers.png") and b.endswith("layers.ora"), (lines, a, b))
check("the attachment is the picture", a and E.Document.load(a).width == 120 and E.Document.load(b).layer_count() == 4)
os.environ["PATH"] = "/nonexistent"
messages.clear()
check("without a mail app it says what's needed", win.cmd("send_email", "png") is None and messages and "mail app" in messages[-1], messages)
os.environ["PATH"] = os.environ.get("PATH_SAVED", "/usr/bin:/bin")

print()
print("ERRORS IN CALLBACKS: %d" % len(ERRORS))
for e in ERRORS:
    print(e)
failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed or ERRORS else 0)
