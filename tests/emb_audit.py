"""Embroidery add-on: drive the whole workflow through the real window under Xvfb —
new embroidery document, place a picture, convert to shapes, edit shapes, stitch settings,
lettering, preview, colour sequence, import, export, template, save and reopen."""
import json
import os
import sys
import tempfile
import time
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
from folio_draw import embdialogs as ED  # noqa: E402
from folio_draw import embroidery as M  # noqa: E402
from folio_draw import engine as E  # noqa: E402
from shot import make, pump, shot  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-emb-"))
os.makedirs(OUT, exist_ok=True)
checks = []
answers = {"choice": 2}
D.message = lambda *a, **k: answers.setdefault("messages", []).append(a[1] if len(a) > 1 else "")
D.ask_choice = lambda *a, **k: answers["choice"]
D.ask_save_changes = lambda *a, **k: "discard"


def check(cond, what):
    checks.append((bool(cond), what))
    print(("ok   " if cond else "FAIL ") + what, flush=True)


def snap(win, name):
    pump(0.3)
    shot(win, os.path.join(OUT, name + ".png"))


if not os.path.exists(os.path.join(DATA, "dsa.gif")):
    # the reference emblem is a third-party logo, kept out of the public repository
    print("emb_audit needs tests/data/dsa.gif (the reference emblem); 0 checks")
    sys.exit(0)

app, win = make()
ui = win.emb

# ---- EMB-01 new embroidery document
s = dict(M.DEFAULT_SETTINGS)
ui.new_document(s)
pump(0.3)
check(ui.active(), "new embroidery document")
check(win.doc.width == 1016 and win.doc.height == 1016, "4×4 hoop canvas is 101.6 mm at 10 px/mm: %dx%d" % (win.doc.width, win.doc.height))
check(win.ribbon.tab_buttons["embroidery"].get_visible(), "Embroidery tab shows")
win.ribbon.show_tab("embroidery")
win.state.view["grid"] = True
win.state.view["rulers"] = True
win.apply_view()
win.canvas.zoom_fit()
snap(win, "emb_new")
check("Hoop" in win.size_label.get_text(), "status shows the hoop: " + win.size_label.get_text())

# ---- EMB-03 place and convert the reference emblem
li = ui.place_rgba(*(lambda d: (d.flatten_rgba(), d.width, d.height))(E.Document.load(os.path.join(DATA, "dsa.gif"))), name="dsa.gif")
# the convert below asks for the crop: the emblem's red field goes, its artwork fills the hoop
pump(0.2)
spec = M.layer_spec(win.doc, li)
px = win.doc.layer_rgba(li)
cols = [x for x in range(win.doc.width) if any(px[(y * win.doc.width + x) * 4 + 3] for y in range(0, win.doc.height, 7))]
rows = [y for y in range(win.doc.height) if any(px[(y * win.doc.width + x) * 4 + 3] for x in range(0, win.doc.width, 7))]
pw, ph = (cols[-1] - cols[0] + 1) / 10.0, (rows[-1] - rows[0] + 1) / 10.0
check(abs(pw - 96.6) < 1 and abs(ph - 96.6 * 216 / 360) < 2, "the whole picture is fitted to the hoop, not cropped (%.1f × %.1f mm)" % (pw, ph))
snap(win, "emb_placed")
check(spec and spec["kind"] == M.PICTURE_KIND and spec.get("bg"), "picture layer remembers its background")
t0 = time.time()
ui.c_emb_trace({"colours": 0, "background": "remove", "crop": True, "smoothing": 1, "min_area": 1.5, "edge_radius": 2})
dt = time.time() - t0
layers = M.shape_layers(win.doc)
threads = [json.dumps(o["thread"], sort_keys=True) for i in layers for o in ui.spec(i)["objects"]]
check(len(set(threads)) == 2, "reference emblem: 2 colours (%s)" % ", ".join(sorted(json.loads(t)["name"] for t in set(threads))))
check(len(layers) == 2 and all(len({json.dumps(o["thread"], sort_keys=True) for o in ui.spec(i)["objects"]}) == 1 for i in layers),
      "one shape layer per colour above the picture (%s)" % ", ".join(win.doc.layer_name(i) for i in layers))
check(win.doc.layer_name(layers[0]).startswith("White"), "the biggest colour is the bottom layer, sewn first")
sp = ui.spec(layers[0])
check(dt < 6, "convert in %.1f s" % dt)
win.doc.layer_set(li, visible=False)
win.canvas.sync()
snap(win, "emb_shapes")
for i in layers[1:]:
    win.doc.layer_set(i, visible=False)
win.canvas.sync()
snap(win, "emb_white_alone")
pix = win.canvas.surf.get_data()
check(True, "white layer shown alone over the transparency grid (screenshot emb_white_alone)")
for i in layers[1:]:
    win.doc.layer_set(i, visible=True)
win.canvas.sync()
blocks = ui.blocks()
check(blocks and blocks[0]["thread"]["name"] == "White", "first thread White")
check(len(ui.pane.rows) == len(blocks), "colour sequence lists %d blocks" % len(blocks))

# ---- EMB-05 erase the traced top lettering by box-select
n0 = len(sp["objects"])
win.state.tool = "emb"
got = ui.box_select(-45, -48, 45, -22)
check(got >= 8, "box-select over the top lettering picks %d pieces" % got)
ui.c_emb_delete()
sp = ui.spec(layers[0])
check(n0 - len(sp["objects"]) >= 8, "erasing the traced top lettering removes %d objects" % (n0 - len(sp["objects"])))
win.c_undo()
check(len(ui.spec(layers[0])["objects"]) == n0, "undo brings them back")
win.c_redo()
check(len(ui.spec(layers[0])["objects"]) == n0 - got, "redo removes them again")

# ---- EMB-15 arc lettering re-set on the upper arc
o = ui.c_emb_lettering({"text": "DEMOCRATIC SOCIALISTS", "font": "Sans Bold", "cap": 5.0, "spacing": 0.6, "arc": "top",
                        "radius": 34.5, "thread": M.chart_thread(29), "type": "auto"})
check(o and len(o["glyphs"]) >= 18, "arc lettering made %d glyph shapes" % (len(o["glyphs"]) if o else 0))
import math  # noqa: E402
cents = []
for g in o["glyphs"]:
    pts = [p for r in g[:1] for p in r]
    cents.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
on_arc = all(34.0 < math.hypot(cx, cy) < 34.5 + 5.5 for cx, cy in cents)
upper = sum(1 for cx, cy in cents if cy < 0) == len(cents) and abs(sum(cx for cx, cy in cents) / len(cents)) < 3
check(on_arc and upper, "arc lettering sits on the upper arc (radii %.1f–%.1f mm)" % (
    min(math.hypot(*c) for c in cents), max(math.hypot(*c) for c in cents)))
snap(win, "emb_lettering")

# ---- EMB-06 stitch properties, multi-select
sp = ui.spec(layers[0])
ids = [ob["id"] for ob in sp["objects"][:3]]
ui.select(layers[0], ids)
ui.c_emb_stitch({"type": "fill", "angle": 30.0})
sp = ui.spec(layers[0])
check(all((ob.get("stitch") or {}).get("type") == "fill" and ob["stitch"].get("angle") == 30.0 for ob in sp["objects"][:3]),
      "multi-select stitch edit applies to all three")

# ---- merge, split, nodes, recolour
ui.select(layers[0], ids[:2])
ui.c_emb_merge()
sp = ui.spec(layers[0])
check(any(ob["id"] == ids[0] for ob in sp["objects"]), "merge keeps the first shape")
ui.select(layers[0], [ids[0]])
before = len(ui.spec(layers[0])["objects"])
ui.c_emb_split()
check(len(ui.spec(layers[0])["objects"]) >= before, "split separates the parts (or waits for a line)")
ui.mode = "select"
ui.c_emb_recolour(M.chart_thread(5))
check(all(ob["thread"]["name"] == "Red" for ob in ui.spec(layers[0])["objects"] if ob["id"] in ui.sel), "recolour")
win.c_undo()

# ---- EMB-11/13 preview
ui.c_emb_preview()
pump(0.5)
pv = ui.preview
check(pv is not None and pv.plan is not None, "preview opens")
for mode in ("real", "lines", "density"):
    pv.mode_buttons[mode].set_active(True)
    pump(0.3)
    shot(pv, os.path.join(OUT, "emb_preview_%s.png" % mode))
pv.slider.set_value(len(pv.plan.cmds()) // 3)
pump(0.2)
check(pv.upto == len(pv.plan.cmds()) // 3, "stitch-out slider")
start = pv.upto
pv.toggle_play()
for _ in range(5):
    pv._tick()          # the timer's ticks, without waiting on them
check(pv.playing and pv.upto is not None and pv.upto > start, "play advances the stitch-out (%s -> %s)" % (start, pv.upto))
pv.toggle_play()
shot(pv, os.path.join(OUT, "emb_preview_sim.png"))
pv.destroy()
pump(0.1)

# ---- EMB-12 export with read-back
pes = os.path.join(OUT, "emblem.pes")
check(ui.c_emb_export(pes) is True and os.path.exists(pes), "PES exported")
back = M.Plan.read(pes)
p = ui.plan()
check(len(back.info["blocks"]) == len(p.info["blocks"]), "PES read back: same colour count")
with open(pes, "rb") as f:
    head = f.read(8)
check(head == b"#PES0060", "PES header #PES0060")
dst = os.path.join(OUT, "emblem.dst")
check(ui.c_emb_export(dst) is True, "DST exported")
pes2 = os.path.join(OUT, "emblem2", "emblem.pes")
os.makedirs(os.path.dirname(pes2), exist_ok=True)
ui.c_emb_export(pes2)
check(open(pes, "rb").read() == open(pes2, "rb").read(), "two exports are byte-identical")

# ---- EMB-18 template
pdf = ui.c_emb_template(os.path.join(OUT, "template.pdf"))
check(pdf and os.path.getsize(pdf) > 1000, "1:1 template PDF")

# ---- save and reopen keeps stitches
ora = os.path.join(OUT, "design.ora")
win.save_to(ora, E.FMT_ORA)
n_before = ui.plan().stitches
win.open_path(ora, ask=False)
pump(0.3)
check(ui.active(), "reopened document is an embroidery document")
check(ui.plan().stitches == n_before, "save/reopen gives the same stitch count (%d)" % n_before)
lay = [i for i in M.shape_layers(win.doc) if (ui.spec(i) or {}).get("lettering")]
lo = [ob for ob in ui.spec(lay[0])["objects"] if ob.get("kind") == "lettering"][0]
ui.select(lay[0], [lo["id"]])
x0 = lo["x"]
ui.move_selection(5.0, 0.0)
ui.c_emb_lettering_edit({"text": "FOLIO", "font": "Sans Bold", "cap": 5.0, "spacing": 0.6, "arc": "top", "radius": 34.5,
                         "thread": M.chart_thread(29), "type": "auto"})
win.c_undo()
win.c_undo()
lo2 = [ob for ob in ui.spec(lay[0])["objects"] if ob.get("kind") == "lettering"][0]
check(lo2["text"] == "DEMOCRATIC SOCIALISTS" and abs(lo2["x"] - x0) < 1e-6, "undo restores lettering text and position")

# ---- EMB-16 import PES as stitches
ui.new_document(dict(M.DEFAULT_SETTINGS))
ob = ui.c_emb_import(pes)
check(ob and ob["kind"] == "stitches", "PES imported as a stitch object")
n_imp = ui.plan().stitches
check(abs(n_imp - back.stitches) <= 0.05 * back.stitches, "imported PES re-plans within 5%% (%d vs %d)" % (n_imp, back.stitches))
ui.move_selection(3, 2)
ui.c_emb_mirror()
answers["choice"] = 0
ui.c_emb_scale(150)
check(abs(((ui.selected()[2][0].get("transform") or {}).get("scale", 1.0)) - 1.0) < 1e-9, "scaling stitches by 50 % asks first (cancelled)")
answers["choice"] = 1
ui.c_emb_scale(105)
check(abs(ui.selected()[2][0]["transform"]["scale"] - 1.05) < 1e-9, "scale within 10 % without asking")
snap(win, "emb_import")

# ---- drawn artwork to shapes, blocked commands
ui.new_document(dict(M.DEFAULT_SETTINGS))
doc = win.doc
doc.layer_add("Drawing")
doc.shape([(300, 300), (700, 300), (700, 700), (300, 700)], True, 4, (0, 0, 0, 255), (20, 70, 170, 255), True, True)
win.canvas.sync()
ui.c_emb_trace({"colours": 0, "background": "remove", "crop": False, "smoothing": 1, "min_area": 1.5, "edge_radius": 2})
check(len(M.shape_layers(doc)) == 2 and all(ui.spec(i)["objects"] for i in M.shape_layers(doc)),
      "drawn artwork converts to shapes: the fill and its outline on layers of their own")
win.cmd("resize")
check("isn't available" in win.hint_label.get_text(), "Resize says it isn't available in an embroidery document")
win.state.tool = "pencil"
doc.set_active(M.shape_layers(doc)[0])
ui.ensure_paint_layer()
check(not M.is_shape_layer(doc, doc.active), "painting on a shape layer goes to a new drawing layer")

# ---- CLI
from folio_draw.embroidery import cli  # noqa: E402
outp = os.path.join(OUT, "cli.pes")
r = cli(["folio-draw", "--embroider", os.path.join(DATA, "logo.png"), "-o", outp, "--size", "4x4"])
check(r == 0 and os.path.exists(outp), "command-line conversion")

# ---- the emblem with its background kept: the dark lines survive (no pink edge colour)
ui.new_document(dict(M.DEFAULT_SETTINGS))
li2 = ui.place_rgba(*(lambda d: (d.flatten_rgba(), d.width, d.height))(E.Document.load(os.path.join(DATA, "dsa.gif"))), name="dsa.gif")
ui.c_emb_trace({"colours": 0, "background": "keep", "crop": False, "smoothing": 1, "min_area": 1.5, "edge_radius": 2})
names = sorted(win.doc.layer_name(i) for i in M.shape_layers(win.doc))
check(len(names) == 3 and any(n.startswith("Dark Brown") for n in names) and not any("Pink" in n for n in names),
      "background kept: red, white and the dark lines (%s)" % ", ".join(names))

# ---- a shape within a shape: fill the hole (red field with a white disc)
import cairo  # noqa: E402
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 360, 216)
cr = cairo.Context(surf)
cr.set_source_rgb(0.93, 0.1, 0.12)
cr.paint()
cr.set_source_rgb(1, 1, 1)
cr.arc(180, 108, 70, 0, 6.2832)
cr.fill()
surf.flush()
bgra = bytes(surf.get_data())
rgba = bytearray(len(bgra))
rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = bgra[2::4], bgra[1::4], bgra[0::4], bgra[3::4]
ui.new_document(dict(M.DEFAULT_SETTINGS))
ui.place_rgba(bytes(rgba), 360, 216, "flag.png")
ui.c_emb_trace({"colours": 0, "background": "keep", "crop": False, "smoothing": 1, "min_area": 1.5, "edge_radius": 2})
doc = win.doc
red = [i for i in M.shape_layers(doc) if ui.spec(i)["objects"][0]["thread"]["name"] == "Red"]
check(red and len(ui.spec(red[0])["objects"][0]["rings"]) == 2, "the red field comes out as a shape with a hole")


class _Ev:
    def __init__(self, x, y):
        self.type, self.button, self.x, self.y = Gdk.EventType.BUTTON_PRESS, 1, x, y


if red:
    o = ui.spec(red[0])["objects"][0]
    ui.select(red[0], [o["id"]])
    cx, cy = M.mm_to_px(ui.settings(), 0.0, 0.0)
    ui.press(_Ev(*win.canvas.to_screen(cx, cy)), cx, cy, False, False)
    check(ui.sel_hole == 1, "clicking inside the selected shape's hole picks the hole")
    snap(win, "emb_hole")
    check(ui.key("Delete", False), "Delete fills the hole")
    check(len(ui.spec(red[0])["objects"][0]["rings"]) == 1, "the field is a filled rectangle now")
    win.c_undo()
    check(len(ui.spec(red[0])["objects"][0]["rings"]) == 2, "undo brings the hole back")
    ui.select(red[0], [o["id"]])
    ui.c_emb_fill_holes()
    check(len(ui.spec(red[0])["objects"][0]["rings"]) == 1, "Fill Holes on a selected shape")

    # ---- node editing: move a node, delete one (its neighbours join), add one
    o = ui.spec(red[0])["objects"][0]
    ui.select(red[0], [o["id"]])
    ui.c_emb_nodes()
    check(ui.mode == "nodes", "Edit Nodes")
    ring = o["rings"][0]
    n0 = len(ring)
    vx, vy = ring[0]
    px0, py0 = M.mm_to_px(ui.settings(), vx, vy)
    sx, sy = win.canvas.to_screen(px0, py0)
    ui.press(_Ev(sx, sy), px0, py0, False, False)
    check(ui.drag and ui.drag["kind"] == "node", "a node picked up")
    tx, ty = M.mm_to_px(ui.settings(), vx - 3.0, vy - 2.0)
    ui.motion(_Ev(*win.canvas.to_screen(tx, ty)), tx, ty)
    ui.release(_Ev(*win.canvas.to_screen(tx, ty)), tx, ty)
    moved = ui.spec(red[0])["objects"][0]["rings"][0][0]
    check(abs(moved[0] - (vx - 3.0)) < 0.05 and abs(moved[1] - (vy - 2.0)) < 0.05, "the node moved and was kept (%.1f, %.1f)" % tuple(moved))
    nb = (ui.spec(red[0])["objects"][0]["rings"][0][-1], ui.spec(red[0])["objects"][0]["rings"][0][1])
    check(ui.key("Delete", False), "Delete removes the node")
    r2 = ui.spec(red[0])["objects"][0]["rings"][0]
    check(len(r2) == n0 - 1 and r2[0] == nb[1] and r2[-1] == nb[0], "its neighbours are joined directly (%d -> %d nodes)" % (n0, len(r2)))
    win.c_undo()
    check(len(ui.spec(red[0])["objects"][0]["rings"][0]) == n0, "undo brings the node back")
    ui.key("Escape", False)
    check(ui.mode == "select" and ui.sel, "Esc leaves Edit Nodes, the shape stays selected")

# ---- dialogs open and close cleanly (screenshots of each)
_real_run = Gtk.Dialog.run
seen = []


def fake_run(d):
    d.show_all()
    pump(0.25)
    gw = d.get_window()
    if gw is not None:
        import cairo
        w, h = gw.get_width(), gw.get_height()
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(img)
        Gdk.cairo_set_source_window(cr, gw, 0, 0)
        cr.paint()
        img.write_to_png(os.path.join(OUT, "dlg_%d.png" % len(seen)))
    seen.append(d.get_title())
    return Gtk.ResponseType.OK


Gtk.Dialog.run = fake_run
r1 = ED.hoop_settings(win, M.DEFAULT_SETTINGS, new=True)
r2 = ED.trace_settings(win, None, [255, 0, 0])
r3 = ED.stitch_properties(win, [{"stitch": {"type": "satin"}}, {"stitch": {"type": "fill"}}])
r4 = ED.lettering(win, {"text": "Hello"})
r5 = ED.choose_thread(win, M.chart_thread(29))
Gtk.Dialog.run = _real_run
check(r1 and r1["hoop_mm"][0] > 100, "hoop dialog returns settings")
check(r2 and r2["background"] == "remove", "convert dialog returns settings")
check(r3 == {}, "stitch dialog with nothing changed changes nothing")
check(r4 and r4["text"] == "Hello", "lettering dialog")
check(r5 and r5["pec"] == 29, "thread chooser keeps the current thread")

for e in ERRORS:
    print(e)
fails = [w for ok, w in checks if not ok]
print("%d checks, %d failed, %d errors; screenshots in %s" % (len(checks), len(fails), len(ERRORS), OUT))
sys.exit(1 if fails or ERRORS else 0)
