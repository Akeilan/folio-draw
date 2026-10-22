"""Render the Folio Draw app icon at the standard hicolor sizes (mirrors folio-draw.svg)."""
import math
import os
import sys

import cairo

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "icons", "png")


def rr(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def draw(cr):
    g = cairo.LinearGradient(0, 16, 0, 240)
    g.add_color_stop_rgb(0, 0x9a / 255, 0x10 / 255, 0x10 / 255)
    g.add_color_stop_rgb(1, 0x68 / 255, 0, 0)
    rr(cr, 16, 16, 224, 224, 44)
    cr.set_source(g)
    cr.fill()
    cr.move_to(128, 52)
    cr.curve_to(82, 52, 46, 84, 46, 126)
    cr.curve_to(46, 166, 78, 198, 114, 198)
    cr.curve_to(128, 198, 134, 190, 134, 180)
    cr.curve_to(134, 174, 130, 170, 130, 164)
    cr.curve_to(130, 156, 136, 152, 144, 152)
    cr.line_to(160, 152)
    cr.curve_to(188, 152, 210, 132, 210, 106)
    cr.curve_to(210, 74, 174, 52, 128, 52)
    cr.close_path()
    cr.set_source_rgb(1, 1, 1)
    cr.fill()
    for (x, y, a) in ((92, 104, 1), (126, 84, 0.75), (162, 96, 0.5), (84, 142, 0.3)):
        cr.arc(x, y, 11, 0, math.tau)
        cr.set_source_rgba(0.5, 0, 0, a)
        cr.fill()
    cr.move_to(210, 70)
    cr.line_to(152, 140)
    cr.set_line_width(10)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_source_rgb(1, 1, 1)
    cr.stroke()
    cr.move_to(148, 136)
    cr.curve_to(138, 138, 130, 146, 130, 158)
    cr.curve_to(130, 164, 126, 170, 120, 172)
    cr.curve_to(138, 178, 160, 168, 160, 150)
    cr.curve_to(160, 144, 156, 138, 148, 136)
    cr.close_path()
    cr.set_source_rgb(1, 0.85, 0.85)
    cr.fill_preserve()
    cr.set_source_rgb(0.5, 0, 0)
    cr.set_line_width(4)
    cr.stroke()


os.makedirs(OUT, exist_ok=True)
for s in (16, 24, 32, 48, 64, 128, 256):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, s, s)
    cr = cairo.Context(surf)
    cr.scale(s / 256, s / 256)
    draw(cr)
    surf.write_to_png(os.path.join(OUT, "%d.png" % s))
print("icons written to", os.path.abspath(OUT))
