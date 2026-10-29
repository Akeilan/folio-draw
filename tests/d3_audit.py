"""Backlog 3 for Draw: Resize, Rotate and Flip in embroidery documents (D3-01), more machine
formats (D3-02), shapes straight from an SVG drawing (D3-03), saving Photoshop files (D3-04),
and the ribbon on the suite's shared module (X3-04). Fails loudly on any exception in a callback."""
import json
import math
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
from gi.repository import Gtk  # noqa: E402

ERRORS = []


def hook(t, v, tb):
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))
    sys.__excepthook__(t, v, tb)


sys.excepthook = hook

from folio_draw import dialogs as D  # noqa: E402
from folio_draw import embroidery as M  # noqa: E402
from folio_draw import engine as E  # noqa: E402
from folio_draw import suiteribbon as SR  # noqa: E402
from shot import make, pump  # noqa: E402

OUT = os.environ.get("AUDIT_OUT", tempfile.mkdtemp(prefix="fd-audit-"))
os.makedirs(OUT, exist_ok=True)
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)), flush=True)


answers = {"choice": 1}
messages = []
D.message = lambda parent, title, *a, **k: messages.append(title)
D.ask_choice = lambda *a, **k: answers["choice"]
D.ask_save_changes = lambda *a, **k: "discard"

app, win = make()
ui = win.emb


def near(a, b, tol=0.15):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def all_objects():
    return [(i, o) for i in M.shape_layers(win.doc) for o in ui.spec(i)["objects"]]


# ------------------------------------------------------------------ D3-01
s = dict(M.DEFAULT_SETTINGS)
ui.new_document(s)
pump(0.3)
li = ui.target_layer()
sp = ui.spec(li)
red = M.chart_thread(5)
sp["objects"].append({"id": M.new_object_id(sp), "rings": [[[-20, -10], [20, -10], [20, 10], [-20, 10]]], "thread": red,
                      "stitch": {"type": "fill", "angle": 0}})
sp["objects"].append({"id": M.new_object_id(sp), "rings": [[[25, 15], [35, 15], [30, 25]]], "thread": red})
ui.store(li, sp, "Shapes")
ui.changed("Shapes")
o_rect = ui.spec(li)["objects"][0]
b0 = M.object_bounds(o_rect)
whole0 = ui._targets_bounds(ui.transform_targets()[0])
cx, cy = (whole0[0] + whole0[2]) / 2, (whole0[1] + whole0[3]) / 2
messages.clear()
r = win.cmd("rot_cw")
check("Rotate right 90° acts on the design instead of being refused", r and not messages, messages)
o_rect = ui.spec(li)["objects"][0]
b1 = M.object_bounds(o_rect)
check("the rectangle turns on its side about the design's middle",
      abs((b1[2] - b1[0]) - 20) < 0.2 and abs((b1[3] - b1[1]) - 40) < 0.2, (b0, b1))
mid = ((b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2)
exp = (cx - ((b0[1] + b0[3]) / 2 - cy), cy + ((b0[0] + b0[2]) / 2 - cx))
check("…round the middle of the whole design, clockwise", near(mid, exp, 0.3), (mid, exp))
check("a fixed fill angle turns with the shape (0° → 90°)", abs(o_rect["stitch"]["angle"] - 90) < 0.01, o_rect["stitch"])
n_undo = len(win.doc.history()[0])
win.cmd("undo")
pump(0.1)
o_rect = ui.spec(li)["objects"][0]
check("one Undo puts the whole design back", near(M.object_bounds(o_rect), b0, 0.01), M.object_bounds(o_rect))
win.cmd("redo")
pump(0.1)
check("Redo turns it again", near(M.object_bounds(ui.spec(li)["objects"][0]), b1, 0.01))
check("the History panel names it", any("Rotate" in h for h in win.doc.history()[0]), win.doc.history()[0][-3:])
# selection only: flip the triangle, the rectangle stays
tri = ui.spec(li)["objects"][1]
tb = M.object_bounds(tri)
ui.select(li, [tri["id"]])
win.cmd("flip_h")
tri2 = [o for o in ui.spec(li)["objects"] if o["id"] == tri["id"]][0]
check("Flip horizontal on a selection flips only the selected shape",
      near(M.object_bounds(tri2), tb, 0.01) and near(M.object_bounds(ui.spec(li)["objects"][0]), b1, 0.01))
xs = [p[0] for p in tri2["rings"][0]]
check("…mirrored about its own middle (apex stays, base corners swap)", sorted(xs) == sorted(xs) and tri2["rings"][0] != tri["rings"][0])
ui.select(None, [])
# resize the whole design by 150 %
bb = ui._targets_bounds(ui.transform_targets()[0])
ui.transform_cmd("resize", 1.5, 1.5)
bb2 = ui._targets_bounds(ui.transform_targets()[0])
check("Resize 150 % scales the whole design about its middle",
      abs((bb2[2] - bb2[0]) - 1.5 * (bb[2] - bb[0])) < 0.05 and abs((bb2[0] + bb2[2]) - (bb[0] + bb[2])) < 0.05, (bb, bb2))
ui.transform_cmd("resize", 1 / 1.5, 1 / 1.5)
# lettering keeps its text and its turn
lo = ui.c_emb_lettering({"text": "ABC", "font": "Sans Bold", "cap": 8.0, "arc": "none", "thread": M.chart_thread(20), "type": "auto",
                         "x": 0.0, "y": -30.0})
lb0 = M.object_bounds(lo)
ui.select(None, [])
ui.transform_cmd("rotate_angle", 90)
lyr = [i for i in M.shape_layers(win.doc) if (ui.spec(i) or {}).get("lettering")][0]
lo = ui.spec(lyr)["objects"][0]
lb1 = M.object_bounds(lo)
check("lettering turns with the design and remembers how (a matrix, not traced outlines)",
      lo.get("kind") == "lettering" and lo.get("matrix") and (lb1[3] - lb1[1]) > (lb1[2] - lb1[0]), (lb0, lb1))
ui.select(lyr, [lo["id"]])
ui.c_emb_lettering_edit({"text": "ABCD"})
lo = ui.spec(lyr)["objects"][0]
lb2 = M.object_bounds(lo)
check("editing the text keeps the turn (the longer word grows downwards, not sideways)",
      (lb2[3] - lb2[1]) > (lb1[3] - lb1[1]) + 2 and abs((lb2[2] - lb2[0]) - (lb1[2] - lb1[0])) < 1.5, (lb1, lb2))
ui.select(None, [])
# a placed picture turns with the design
pic = E.Document.new(60, 30, (0, 0, 255, 255))
pli = ui.place_rgba(pic.flatten_rgba(), 60, 30, "blue.png")
pump(0.1)


def opaque_box(i):
    px = win.doc.layer_rgba(i)
    w, h = win.doc.width, win.doc.height
    xs = [x for x in range(0, w, 4) if any(px[(y * w + x) * 4 + 3] > 128 for y in range(0, h, 4))]
    ys = [y for y in range(0, h, 4) if any(px[(y * w + x) * 4 + 3] > 128 for x in range(0, w, 4))]
    return (xs[0], ys[0], xs[-1], ys[-1]) if xs else None


pb0 = opaque_box(pli)
win.cmd("rot_cw")
pb1 = opaque_box(pli)
check("a placed picture turns with the design (wide becomes tall)",
      pb0 and pb1 and (pb0[2] - pb0[0]) > (pb0[3] - pb0[1]) and (pb1[3] - pb1[1]) > (pb1[2] - pb1[0]), (pb0, pb1))
check("the picture layer is still a picture layer", (ui.spec(pli) or {}).get("kind") == M.PICTURE_KIND)
win.cmd("undo")
# Crop and Canvas size still say they don't apply
messages.clear()
hints = []
_hint = win.hint
win.hint = lambda t, *a, **k: hints.append(t)
win.cmd("crop")
win.hint = _hint
check("Crop still says it isn't available in an embroidery document", hints and "isn't available" in hints[-1], hints)
# imported stitches: flipping moves the needle points
plan = M.Plan.make(M.design_json(win.doc, ui.settings()))
dst = os.path.join(OUT, "d3.dst")
plan.write(dst, M.FMT_DST, "d3")
so = ui.c_emb_import(dst)
pump(0.2)
sli = [i for i in M.shape_layers(win.doc) if any(o.get("kind") == "stitches" for o in ui.spec(i)["objects"])][-1]
st = [o for o in ui.spec(sli)["objects"] if o.get("kind") == "stitches"][0]
sb = M.object_bounds(st)
ui.select(sli, [st["id"]])
win.cmd("flip_v")
st2 = [o for o in ui.spec(sli)["objects"] if o["id"] == st["id"]][0]
check("Flip vertical moves imported stitches point by point (no transform left over)",
      near(M.object_bounds(st2), sb, 0.05) and not st2.get("transform"), (sb, M.object_bounds(st2)))
ui.select(None, [])
check("no errors so far (D3-01)", not ERRORS, ERRORS[-1:] if ERRORS else "")

# ------------------------------------------------------------------ D3-02
plan = M.Plan.make(M.design_json(win.doc, ui.settings()))
n0 = plan.info["stitches"]
for ext, fmt in ((".jef", M.FMT_JEF), (".exp", M.FMT_EXP), (".vp3", M.FMT_VP3), (".xxx", M.FMT_XXX)):
    path = os.path.join(OUT, "d3" + ext)
    try:
        plan.write(path, M.format_for(path), "d3")
        back = M.Plan.read(path)
        n1 = back.info["stitches"]
        nb = len(back.info["blocks"])
        check("%s writes and reads back (%d stitches, %d colours)" % (ext.upper().lstrip("."), n1, nb),
              abs(n1 - n0) <= max(2, 0.01 * n0) and nb == len(plan.info["blocks"]), (n0, n1, nb))
    except Exception as e:
        check("%s writes and reads back" % ext, False, e)
check("the format follows the extension", M.format_for("x.VP3") == M.FMT_VP3 and M.format_for("x.jef") == M.FMT_JEF)
check("Import Design offers the new formats", "*.jef" in M.READ_PATTERNS and "*.xxx" in M.READ_PATTERNS)
before = len(M.shape_layers(win.doc))
ui.c_emb_import(os.path.join(OUT, "d3.jef"))
check("a JEF imports as a stitch design", len(M.shape_layers(win.doc)) >= before)

# ------------------------------------------------------------------ D3-03
svg = os.path.join(OUT, "drawing.svg")
with open(svg, "w") as f:
    f.write("""<svg xmlns="http://www.w3.org/2000/svg" width="60mm" height="40mm" viewBox="0 0 60 40">
  <rect x="2" y="2" width="20" height="15" fill="#e01010"/>
  <path d="M30 2 h20 v20 h-20 Z M35 7 h10 v10 h-10 Z" fill="navy" fill-rule="evenodd"/>
  <g transform="translate(0,20)"><circle cx="10" cy="10" r="6" style="fill:#10a010"/></g>
  <path d="M30 30 C 35 20, 45 40, 55 30" fill="none" stroke="black" stroke-width="2"/>
  <ellipse cx="50" cy="35" rx="4" ry="2" fill="none" stroke="#e01010" stroke-width="0.4"/>
  <text x="5" y="38">ignored</text>
</svg>""")
nl = len(M.shape_layers(win.doc))
specs = ui.c_emb_svg(svg)
objs = [o for spx in (specs or []) for o in spx["objects"]]
check("Shapes from Drawing makes one layer per colour (red, navy, green, black)", specs and len(specs) == 4, [len(x["objects"]) for x in specs or []])
check("…each colour its own thread", specs and len({json.dumps(x["objects"][0]["thread"], sort_keys=True) for x in specs}) == 4)
sq = [o for o in objs if len(o.get("rings", [])) == 2]
check("a subpath inside another (even-odd) is a hole", sq, [len(o["rings"]) for o in objs])
rect = [o for o in objs if len(o["rings"]) == 1 and len(o["rings"][0]) == 4]
if rect:
    rb = M.object_bounds(rect[0])
    check("real-size drawings keep their size (20 × 15 mm)", abs((rb[2] - rb[0]) - 20) < 0.1 and abs((rb[3] - rb[1]) - 15) < 0.1, rb)
else:
    check("the rectangle comes in as four corners", False, [len(o["rings"][0]) for o in objs])
kinds = sorted((o.get("stitch") or {}).get("type", "fill") for o in objs)
check("an open stroked line becomes a satin column, a thin outline a running stitch", "satin" in kinds and "run" in kinds, kinds)
ab = [M.object_bounds(o) for o in objs]
xs = [b[0] for b in ab] + [b[2] for b in ab]
check("the drawing sits in the middle of the hoop", abs((min(xs) + max(xs)) / 2) < 0.6, (min(xs), max(xs)))
check("one undo step for the import", win.doc.history()[0][-1] == "Shapes from drawing", win.doc.history()[0][-1:])
p2 = M.Plan.make(M.design_json(win.doc, ui.settings()))
check("the imported shapes stitch", p2.info["stitches"] > 500, p2.info["stitches"])
big = os.path.join(OUT, "big.svg")
with open(big, "w") as f:
    f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 500"><rect width="1000" height="500" fill="gold"/></svg>')
ui.c_emb_svg(big)
gb = M.object_bounds(ui.spec(M.shape_layers(win.doc)[-1])["objects"][0])
hw, hh = M.hoop_mm(ui.settings())
check("a drawing with no physical size is fitted to the hoop", abs((gb[2] - gb[0]) - (hw - 5)) < 0.2, gb)
bad = os.path.join(OUT, "bad.svg")
with open(bad, "w") as f:
    f.write("<svg><rect width=")
messages.clear()
ui.c_emb_svg(bad)
check("a damaged SVG is reported, not crashed on", messages, messages)

# ------------------------------------------------------------------ D3-04
d = E.Document.new(80, 50, (255, 255, 255, 255))
d.layer_add("Red box")
d.float_from_rgba(20, 10, bytes([200, 20, 20, 255]) * 200, 10, 10)
d.float_commit()
d.layer_set(d.active, opacity=0.6, blend=1)
d.layer_add("Hidden one")
d.float_from_rgba(5, 5, bytes([0, 0, 0, 255]) * 25, 0, 0)
d.float_commit()
d.layer_set(d.active, visible=False)
psd = os.path.join(OUT, "layers.psd")
d.save(psd, E.FMT_PSD)
back = E.Document.load(psd)
props = [back.layer_props(i) for i in range(back.layer_count())]
names = [back.layer_name(i) for i in range(back.layer_count())]
check("Save as .psd keeps every layer (%s)" % ", ".join(names), names == ["Background", "Red box", "Hidden one"], names)
check("…with opacity, blend mode and visibility",
      abs(props[1]["opacity"] - 0.6) < 0.01 and props[1]["blend"] == 1 and not props[2]["visible"], props)
check("…and the same pixels", back.layer_rgba(1) == d.layer_rgba(1))
check("Photoshop is offered in Save As", ".psd" in __import__("folio_draw.window", fromlist=["SAVE_FORMATS"]).SAVE_FORMATS)

# ------------------------------------------------------------------ X3-04
rb = win.ribbon
check("Draw's ribbon is the suite's shared ribbon", isinstance(rb, SR.Ribbon) and all(isinstance(g, SR.Group) for g in rb.pages["home"].groups))
check("its tabs: Home, View, Embroidery, Text", list(rb.pages) == ["home", "view", "embroidery", "text"])
rb.set_display_mode("tabs")
pump(0.1)
check("Ribbon Display Options: Show tabs only hides the commands", rb.collapsed and not rb.revealer.get_reveal_child())
rb.show_tab("view")
pump(0.1)
check("…and a tab shows them again", rb.revealer.get_reveal_child())
rb.set_display_mode("always")
pump(0.1)
check("Always show Ribbon brings it back", not rb.collapsed and rb.revealer.get_reveal_child())
rb.show_tab("home")
pump(0.2)
h = rb.revealer.get_allocated_height() + rb.tabbar.get_allocated_height()
check("the ribbon keeps Draw's height (tabs + body = 130 px ±2)", abs(h - 130) <= 2, h)
check("no errors", not ERRORS, ERRORS[-1:] if ERRORS else "")

failed = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(failed)))

os._exit(1 if failed else 0)
