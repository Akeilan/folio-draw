"""Icons for the Embroidery tab, drawn on the same 24 × 24 grid as the rest of Folio Draw."""

import math

from . import icons


def _hoop(cr, ink, acc, x=3, y=3, w=18, h=18):
    icons._rr(cr, x, y, w, h, 4)
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.6)
    cr.stroke()
    icons._rr(cr, x + 2.2, y + 2.2, w - 4.4, h - 4.4, 2.5)
    cr.set_line_width(0.9)
    cr.stroke()


def i_hoop(cr, ink, acc):
    _hoop(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.set_line_width(1.1)
    cr.move_to(12, 8)
    cr.line_to(12, 16)
    cr.move_to(8, 12)
    cr.line_to(16, 12)
    cr.stroke()


def i_embnew(cr, ink, acc):
    icons._paper(cr, 4.5, 2.5, 15, 19)
    icons._fs(cr, ink)
    cr.set_source_rgb(*acc)
    cr.set_line_width(1.2)
    # a little satin zig-zag
    cr.move_to(7, 16)
    for i in range(6):
        cr.line_to(8 + i * 1.6, 9 if i % 2 == 0 else 16)
    cr.stroke()


def i_place(cr, ink, acc):
    _hoop(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.move_to(7, 16)
    cr.line_to(10.5, 11)
    cr.line_to(13, 14)
    cr.line_to(14.5, 12.5)
    cr.line_to(17, 16)
    cr.close_path()
    cr.fill()
    cr.arc(15, 8.5, 1.5, 0, math.tau)
    cr.fill()


def i_trace(cr, ink, acc):
    # picture on the left becoming outlined shapes on the right
    cr.set_source_rgb(*acc)
    cr.rectangle(2.5, 6, 8, 10)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.2)
    cr.move_to(11.5, 11)
    cr.line_to(14, 11)
    cr.stroke()
    cr.move_to(13, 9)
    cr.line_to(15, 11)
    cr.line_to(13, 13)
    cr.stroke()
    cr.arc(18.5, 8.5, 3, 0, math.tau)
    cr.stroke()
    cr.rectangle(15.5, 13.5, 6, 6)
    cr.stroke()


def i_shapetool(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.arc(15, 15, 6, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.move_to(4, 3)
    cr.line_to(4, 17)
    cr.line_to(7.5, 13.5)
    cr.line_to(10, 19)
    cr.line_to(12, 18)
    cr.line_to(9.5, 12.5)
    cr.line_to(14, 12.5)
    cr.close_path()
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()


def i_nodes(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.move_to(4, 18)
    cr.curve_to(6, 6, 16, 4, 20, 8)
    cr.stroke()
    for x, y in ((4, 18), (12, 6.2), (20, 8)):
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x - 2, y - 2, 4, 4)
        cr.fill_preserve()
        cr.set_source_rgb(*acc)
        cr.stroke()


def i_union(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.arc(9, 12, 6, 0, math.tau)
    cr.fill()
    cr.arc(15, 12, 6, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.arc(9, 12, 6, 0, math.tau)
    cr.new_sub_path()
    cr.arc(15, 12, 6, 0, math.tau)
    cr.stroke()


def i_split(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.move_to(3, 5)
    cr.line_to(10.5, 5)
    cr.line_to(8.5, 19)
    cr.line_to(3, 19)
    cr.close_path()
    cr.fill()
    cr.move_to(13.5, 5)
    cr.line_to(21, 5)
    cr.line_to(21, 19)
    cr.line_to(11.5, 19)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_dash([2, 1.5])
    cr.move_to(12.5, 2)
    cr.line_to(10, 22)
    cr.stroke()


def i_spool(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(7, 6, 10, 12)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(0.6)
    for y in range(7, 18, 2):
        cr.move_to(7, y + 0.5)
        cr.line_to(17, y + 0.5)
    cr.stroke()
    cr.set_line_width(1.2)
    icons._rr(cr, 5, 3, 14, 3, 1)
    icons._fs(cr, ink)
    icons._rr(cr, 5, 18, 14, 3, 1)
    icons._fs(cr, ink)


def i_fillholes(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(3, 5, 18, 14)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.arc(12, 12, 4.5, math.pi * 0.5, math.pi * 1.5)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_dash([1.5, 1.2])
    cr.arc(12, 12, 4.5, 0, math.tau)
    cr.stroke()


def i_stitchtype(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.set_line_width(1.1)
    for i in range(7):
        cr.move_to(3 + i * 2.6, 4)
        cr.line_to(5.2 + i * 2.6, 11)
    cr.stroke()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.4)
    cr.set_dash([3, 1.6])
    cr.move_to(3, 17)
    cr.curve_to(8, 13, 14, 21, 21, 16)
    cr.stroke()


def i_lettering(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.2)
    cr.arc(12, 20, 13, math.radians(215), math.radians(325))
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(11)
    cr.move_to(5.5, 18)
    cr.show_text("A")
    cr.move_to(12.5, 18)
    cr.show_text("b")


def i_colourseq(cr, ink, acc):
    cols = [acc, (0.85, 0.65, 0.1), (0.1, 0.35, 0.75)]
    for i, c in enumerate(cols):
        y = 4 + i * 6
        cr.set_source_rgb(*c)
        cr.rectangle(3, y, 5, 4.5)
        cr.fill()
        cr.set_source_rgb(*ink)
        cr.move_to(10, y + 2.25)
        cr.line_to(21, y + 2.25)
        cr.stroke()


def i_preview(cr, ink, acc):
    _hoop(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.set_line_width(0.9)
    for i in range(8):
        cr.move_to(7 + i * 1.3, 8)
        cr.line_to(8 + i * 1.3, 16)
    cr.stroke()


def i_density(cr, ink, acc):
    for (x, y, c) in ((4, 4, (0.3, 0.69, 0.31)), (12, 4, (1, 0.75, 0)), (4, 12, (1, 0.45, 0)), (12, 12, (0.85, 0.1, 0.1))):
        cr.set_source_rgb(*c)
        cr.rectangle(x, y, 8, 8)
        cr.fill()
    cr.set_source_rgb(*ink)
    cr.rectangle(4, 4, 16, 16)
    cr.stroke()


def i_embimport(cr, ink, acc):
    icons._paper(cr, 5, 2.5, 14, 19)
    icons._fs(cr, ink)
    cr.set_source_rgb(*acc)
    cr.move_to(12, 7)
    cr.line_to(12, 15)
    cr.stroke()
    cr.move_to(9, 12)
    cr.line_to(12, 15.5)
    cr.line_to(15, 12)
    cr.stroke()
    cr.set_source_rgb(*ink)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(5)
    cr.move_to(7.3, 20.5)
    cr.show_text("PES")


def i_embexport(cr, ink, acc):
    icons._paper(cr, 5, 2.5, 14, 19)
    icons._fs(cr, ink)
    cr.set_source_rgb(*acc)
    cr.move_to(12, 15)
    cr.line_to(12, 7)
    cr.stroke()
    cr.move_to(9, 10)
    cr.line_to(12, 6.5)
    cr.line_to(15, 10)
    cr.stroke()
    cr.set_source_rgb(*ink)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(5)
    cr.move_to(7.3, 20.5)
    cr.show_text("PES")


def i_template(cr, ink, acc):
    icons._paper(cr, 4.5, 2.5, 15, 19)
    icons._fs(cr, ink)
    cr.set_source_rgb(*acc)
    cr.set_line_width(0.9)
    cr.move_to(12, 6)
    cr.line_to(12, 18)
    cr.move_to(7, 12)
    cr.line_to(17, 12)
    cr.stroke()
    cr.arc(12, 12, 3.5, 0, math.tau)
    cr.stroke()


def i_stopsign(cr, ink, acc):
    cr.set_source_rgb(*acc)
    n = 8
    for k in range(n):
        a = math.tau * (k + 0.5) / n
        x, y = 12 + 9 * math.cos(a), 12 + 9 * math.sin(a)
        if k == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(7, 10.5, 10, 3)
    cr.fill()


def i_mirror(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.move_to(10, 5)
    cr.line_to(10, 19)
    cr.line_to(3, 19)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.move_to(14, 5)
    cr.line_to(14, 19)
    cr.line_to(21, 19)
    cr.close_path()
    cr.stroke()
    cr.set_dash([2, 1.5])
    cr.move_to(12, 2)
    cr.line_to(12, 22)
    cr.stroke()


def i_forward(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 9.5, 11, 11)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.rectangle(9, 3.5, 11, 11)
    cr.fill()


def i_backward(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(3.5, 9.5, 11, 11)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(9, 3.5, 11, 11)
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()


def i_sortcol(cr, ink, acc):
    i_colourseq(cr, ink, acc)


def i_tostitches(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 5.5, 8, 13)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.set_line_width(1)
    for i in range(5):
        cr.move_to(13 + i * 1.8, 6)
        cr.line_to(14 + i * 1.8, 18)
    cr.stroke()


for _k, _v in list(globals().items()):
    if _k.startswith("i_") and callable(_v):
        icons.ICONS[_k[2:]] = _v
