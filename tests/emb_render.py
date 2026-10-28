"""Render a picture's stitch-out (thread view and lines view) for a visual check."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cairo
from folio_draw import engine as E, embroidery as M

src, out = sys.argv[1], sys.argv[2]
d = E.Document.load(src)
rgba = d.flatten_rgba()
st = dict(M.DEFAULT_SETTINGS)
cw, ch = M.canvas_px(st)
t0 = time.time()
canvas, info = M.place(rgba, d.width, d.height, cw, ch)
ox, oy = M.origin(st)
params = {"upscale": info.get("upscale", 1)}
if "bg" in info:
    params["bg"] = info["bg"]
res = M.convert(canvas, cw, ch, ox, oy, params)
t1 = time.time()
objs = [dict(s, group="pic") for s in res["shapes"]]
design = M.design_json.__wrapped__ if False else None
layers = [{"objects": [dict(o, **M.STITCH_DEFAULTS) for o in objs]}]
for l in layers:
    for o in l["objects"]:
        o.pop("angle", None)
design = {"settings": {"hoop": list(M.hoop_mm(st))}, "layers": layers}
plan = M.Plan.make(design)
t2 = time.time()
print("convert %.2fs plan %.2fs" % (t1 - t0, t2 - t1), plan.info["stitches"], "stitches", plan.info["trims"], "trims",
      [b["thread"]["name"] for b in plan.info["blocks"]])
for mode, s in (("real", 8.0), ("lines", 8.0)):
    W, H = int(M.hoop_mm(st)[0] * s), int(M.hoop_mm(st)[1] * s)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    cr.set_source_rgb(*[v / 255 for v in st["fabric"]])
    cr.paint()
    cr.scale(s, s)
    cr.translate(-ox, -oy)
    M.draw_threads(cr, plan, s, mode=mode)
    surf.write_to_png(out.replace(".png", "_%s.png" % mode))
