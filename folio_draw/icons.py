"""Folio Draw's own vector icon set, drawn with cairo on a 24x24 design grid."""

import math

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

MAROON = (0.50, 0.0, 0.0)
INK = (0.20, 0.20, 0.22)


def _paper(cr, x, y, w, h, fold=4):
    cr.move_to(x, y)
    cr.line_to(x + w - fold, y)
    cr.line_to(x + w, y + fold)
    cr.line_to(x + w, y + h)
    cr.line_to(x, y + h)
    cr.close_path()


def _rr(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def _fs(cr, ink, fill=(1, 1, 1)):
    cr.set_source_rgb(*fill)
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()


def i_paste(cr, ink, acc):
    _rr(cr, 3.5, 4.5, 14, 17, 1.5)
    cr.set_source_rgb(0.85, 0.72, 0.55)
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()
    _rr(cr, 7.5, 2.5, 6, 4, 1)
    _fs(cr, ink, (0.95, 0.95, 0.95))
    _paper(cr, 10.5, 9.5, 11, 13)
    _fs(cr, ink)
    cr.set_source_rgb(*acc)
    for yy in (14, 17, 20):
        cr.rectangle(12.5, yy - 0.5, 7, 1)
    cr.fill()


def i_cut(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.move_to(9, 3)
    cr.line_to(15, 15)
    cr.move_to(15, 3)
    cr.line_to(9, 15)
    cr.stroke()
    cr.set_source_rgb(*acc)
    for cx in (7, 17):
        cr.arc(cx, 18, 3, 0, math.tau)
        cr.new_sub_path()
    cr.stroke()


def i_copy(cr, ink, acc):
    _paper(cr, 3.5, 2.5, 11, 14)
    _fs(cr, ink)
    _paper(cr, 9.5, 7.5, 11, 14)
    _fs(cr, ink)
    cr.set_source_rgb(*acc)
    for yy in (12, 15, 18):
        cr.rectangle(11.5, yy - 0.5, 7, 1)
    cr.fill()


def i_select(cr, ink, acc):
    cr.set_dash([2, 2])
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 4.5, 17, 15)
    cr.stroke()
    cr.set_dash([])


def i_freeselect(cr, ink, acc):
    cr.set_dash([2, 2])
    cr.set_source_rgb(*ink)
    cr.move_to(5, 8)
    cr.curve_to(4, 2, 17, 2, 19, 8)
    cr.curve_to(21, 14, 14, 13, 13, 17)
    cr.curve_to(12, 22, 3, 20, 5, 8)
    cr.stroke()
    cr.set_dash([])


def i_polyselect(cr, ink, acc):
    pts = [(4, 18), (6, 5), (14, 9), (20, 4), (19, 19)]
    cr.set_dash([2, 2])
    cr.set_source_rgb(*ink)
    cr.move_to(*pts[0])
    for q in pts[1:]:
        cr.line_to(*q)
    cr.close_path()
    cr.stroke()
    cr.set_dash([])
    cr.set_source_rgb(*acc)
    for q in pts:
        cr.rectangle(q[0] - 1.5, q[1] - 1.5, 3, 3)
    cr.fill()


def i_wand(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2.2)
    cr.move_to(4, 20)
    cr.line_to(14, 10)
    cr.stroke()
    cr.set_source_rgb(*acc)
    # the star at the tip
    cx, cy, r1, r2 = 17, 7, 5, 2
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        r = r1 if k % 2 == 0 else r2
        (cr.move_to if k == 0 else cr.line_to)(cx + r * math.cos(a), cy + r * math.sin(a))
    cr.close_path()
    cr.fill()


def i_history(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.6)
    cr.arc(12, 12, 8, -math.pi * 0.85, math.pi * 0.95)
    cr.stroke()
    cr.move_to(3, 5)
    cr.line_to(4.6, 10.4)
    cr.line_to(9.5, 8.5)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.set_line_width(1.8)
    cr.move_to(12, 7)
    cr.line_to(12, 12)
    cr.line_to(15.5, 14)
    cr.stroke()


def i_stabilizer(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(1)
    cr.move_to(3, 17)
    for i in range(1, 19):
        cr.line_to(3 + i, 17 - i * 0.55 + (1.6 if i % 2 else -1.6))
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.set_line_width(2.2)
    cr.move_to(3, 15)
    cr.curve_to(9, 13, 14, 9, 21, 5)
    cr.stroke()


def i_crop(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.move_to(6, 2)
    cr.line_to(6, 18)
    cr.line_to(22, 18)
    cr.move_to(2, 6)
    cr.line_to(18, 6)
    cr.line_to(18, 22)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.rectangle(8, 8, 8, 8)
    cr.fill()


def i_removebg(cr, ink, acc):
    # a checkerboard behind a person's head and shoulders
    cr.set_source_rgba(*ink, 0.35)
    for yy in range(4):
        for xx in range(4):
            if (xx + yy) % 2 == 0:
                cr.rectangle(3 + xx * 4.5, 3 + yy * 4.5, 4.5, 4.5)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1)
    cr.rectangle(2.5, 2.5, 19, 19)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.arc(12, 9.5, 3.6, 0, math.tau)
    cr.fill()
    cr.move_to(5, 21)
    cr.curve_to(5, 15, 19, 15, 19, 21)
    cr.close_path()
    cr.fill()


def i_resize(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(3, 11, 10, 10)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 3.5, 17, 17)
    cr.stroke()
    cr.move_to(11, 13)
    cr.line_to(18, 6)
    cr.move_to(13, 6)
    cr.line_to(18, 6)
    cr.line_to(18, 11)
    cr.stroke()


def i_rotate(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(4, 12, 9, 9)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.arc(12, 12, 7, math.pi * 1.0, math.pi * 1.9)
    cr.stroke()
    cr.move_to(19.5, 5)
    cr.line_to(19.8, 10.2)
    cr.line_to(14.8, 9)
    cr.stroke()


def i_pencil(cr, ink, acc):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.radians(45))
    cr.rectangle(-2.5, -10, 5, 14)
    cr.set_source_rgb(1.0, 0.8, 0.25)
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()
    cr.rectangle(-2.5, -11, 5, 2.5)
    cr.set_source_rgb(*acc)
    cr.fill()
    cr.move_to(-2.5, 4)
    cr.line_to(0, 9)
    cr.line_to(2.5, 4)
    cr.close_path()
    _fs(cr, ink, (0.96, 0.88, 0.75))
    cr.restore()


def i_fill(cr, ink, acc):
    cr.save()
    cr.translate(10, 13)
    cr.rotate(math.radians(-30))
    cr.rectangle(-5, -5, 10, 10)
    _fs(cr, ink)
    cr.restore()
    cr.set_source_rgb(*acc)
    cr.move_to(17, 12)
    cr.curve_to(20, 16, 21, 18, 19, 20)
    cr.curve_to(17, 21, 15, 19, 17, 12)
    cr.fill()
    cr.move_to(8, 6)
    cr.line_to(16, 13)
    cr.set_source_rgb(*acc)
    cr.stroke()


def i_text(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.move_to(4, 20)
    cr.line_to(10, 4)
    cr.line_to(14, 4)
    cr.line_to(20, 20)
    cr.move_to(6.5, 14)
    cr.line_to(17.5, 14)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.rectangle(2, 21, 20, 2)
    cr.fill()


def i_eraser(cr, ink, acc):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.radians(-40))
    _rr(cr, -8, -4, 16, 8, 1.5)
    _fs(cr, ink, (0.98, 0.75, 0.8))
    cr.rectangle(-8, -4, 6, 8)
    cr.set_source_rgb(*acc)
    cr.fill()
    cr.restore()
    cr.set_source_rgb(*ink)
    cr.move_to(3, 21.5)
    cr.line_to(21, 21.5)
    cr.stroke()


def i_picker(cr, ink, acc):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.radians(45))
    cr.rectangle(-1.5, -2, 3, 11)
    _fs(cr, ink, (0.9, 0.95, 1))
    cr.move_to(-1.5, 9)
    cr.line_to(0, 11.5)
    cr.line_to(1.5, 9)
    cr.set_source_rgb(*ink)
    cr.stroke()
    _rr(cr, -3.5, -10, 7, 7, 2.5)
    cr.set_source_rgb(*acc)
    cr.fill()
    cr.rectangle(-4, -3, 8, 1.5)
    cr.set_source_rgb(*ink)
    cr.fill()
    cr.restore()


def i_zoom(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.arc(10, 10, 6, 0, math.tau)
    cr.stroke()
    cr.set_line_width(3)
    cr.move_to(14.5, 14.5)
    cr.line_to(20.5, 20.5)
    cr.stroke()


def i_zoomin(cr, ink, acc):
    i_zoom(cr, ink, acc)
    cr.set_line_width(1.5)
    cr.set_source_rgb(*acc)
    cr.move_to(7, 10)
    cr.line_to(13, 10)
    cr.move_to(10, 7)
    cr.line_to(10, 13)
    cr.stroke()


def i_zoomout(cr, ink, acc):
    i_zoom(cr, ink, acc)
    cr.set_line_width(1.5)
    cr.set_source_rgb(*acc)
    cr.move_to(7, 10)
    cr.line_to(13, 10)
    cr.stroke()


def i_zoom100(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 5.5, 17, 13)
    cr.stroke()
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(8)
    cr.set_source_rgb(*acc)
    cr.move_to(5.5, 15)
    cr.show_text("1:1")


def i_fit(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(6.5, 7.5, 11, 9)
    cr.stroke()
    cr.set_source_rgb(*acc)
    for (x, y, dx, dy) in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
        cr.move_to(x, y + 4 * dy)
        cr.line_to(x, y)
        cr.line_to(x + 4 * dx, y)
    cr.stroke()


def i_brush(cr, ink, acc):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.radians(40))
    cr.rectangle(-1.5, -11, 3, 10)
    _fs(cr, ink, (0.7, 0.5, 0.3))
    cr.rectangle(-2.5, -1.5, 5, 3)
    _fs(cr, ink, (0.8, 0.8, 0.82))
    cr.move_to(-2.5, 1.5)
    cr.curve_to(-3, 6, -1, 9, 0, 11)
    cr.curve_to(1, 9, 3, 6, 2.5, 1.5)
    cr.close_path()
    cr.set_source_rgb(*acc)
    cr.fill()
    cr.restore()


def i_shapes(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.arc(8, 9, 5, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.rectangle(10.5, 10.5, 10, 10)
    cr.stroke()


def i_outline(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2.5)
    cr.rectangle(4, 5, 16, 14)
    cr.stroke()


def i_fillmode(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(4, 5, 16, 14)
    cr.fill_preserve()
    cr.set_source_rgb(*ink)
    cr.stroke()


def i_size(cr, ink, acc):
    cr.set_source_rgb(*ink)
    for y, w in ((5, 1), (9.5, 2), (15, 3.5), (20.5, 5)):
        cr.rectangle(3, y - w / 2, 18, w)
    cr.fill()


def i_editcolors(cr, ink, acc):
    cols = [(0.9, 0.1, 0.1), (1, 0.6, 0), (1, 0.9, 0), (0.2, 0.75, 0.2), (0.1, 0.5, 1), (0.6, 0.2, 0.8)]
    for i, c in enumerate(cols):
        cr.move_to(12, 12)
        cr.arc(12, 12, 9, i * math.tau / 6, (i + 1) * math.tau / 6)
        cr.close_path()
        cr.set_source_rgb(*c)
        cr.fill()
    cr.arc(12, 12, 3.5, 0, math.tau)
    cr.set_source_rgb(1, 1, 1)
    cr.fill()


def i_undo(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.move_to(5, 9)
    cr.line_to(14, 9)
    cr.curve_to(22, 9, 22, 20, 14, 20)
    cr.line_to(9, 20)
    cr.stroke()
    cr.move_to(9, 4)
    cr.line_to(4, 9)
    cr.line_to(9, 14)
    cr.stroke()


def i_redo(cr, ink, acc):
    cr.save()
    cr.translate(24, 0)
    cr.scale(-1, 1)
    i_undo(cr, ink, acc)
    cr.restore()


def i_save(cr, ink, acc):
    _rr(cr, 3.5, 3.5, 17, 17, 2)
    cr.set_source_rgb(*ink)
    cr.stroke()
    cr.rectangle(7, 4, 10, 6)
    cr.stroke()
    cr.rectangle(7, 14, 10, 6)
    cr.stroke()


def i_new(cr, ink, acc):
    _paper(cr, 5.5, 2.5, 13, 19, 5)
    _fs(cr, ink)


def i_open(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.move_to(3, 19)
    cr.line_to(3, 5)
    cr.line_to(9, 5)
    cr.line_to(11, 7)
    cr.line_to(18, 7)
    cr.line_to(18, 10)
    cr.stroke()
    cr.move_to(3, 19)
    cr.line_to(7, 10)
    cr.line_to(22, 10)
    cr.line_to(18, 19)
    cr.close_path()
    _fs(cr, ink, (1.0, 0.85, 0.5))


def i_print(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(6.5, 3.5, 11, 6)
    cr.stroke()
    _rr(cr, 2.5, 9.5, 19, 8, 1.5)
    _fs(cr, ink, (0.9, 0.9, 0.92))
    cr.rectangle(6.5, 14.5, 11, 7)
    _fs(cr, ink)


def i_eye(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.move_to(2, 12)
    cr.curve_to(7, 4, 17, 4, 22, 12)
    cr.curve_to(17, 20, 7, 20, 2, 12)
    cr.stroke()
    cr.arc(12, 12, 3.5, 0, math.tau)
    cr.fill()


def i_eyeoff(cr, ink, acc):
    cr.set_source_rgba(ink[0], ink[1], ink[2], 0.45)
    cr.move_to(2, 12)
    cr.curve_to(7, 4, 17, 4, 22, 12)
    cr.curve_to(17, 20, 7, 20, 2, 12)
    cr.stroke()
    cr.set_source_rgb(*ink)
    cr.move_to(4, 20)
    cr.line_to(20, 4)
    cr.stroke()


def i_layeradd(cr, ink, acc):
    i_layers(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.set_line_width(2.5)
    cr.move_to(18, 13)
    cr.line_to(18, 23)
    cr.move_to(13, 18)
    cr.line_to(23, 18)
    cr.stroke()


def i_layers(cr, ink, acc):
    for dy, f in ((6, (0.85, 0.85, 0.88)), (0, (1, 1, 1))):
        cr.move_to(12, 4 + dy)
        cr.line_to(21, 8.5 + dy)
        cr.line_to(12, 13 + dy)
        cr.line_to(3, 8.5 + dy)
        cr.close_path()
        _fs(cr, ink, f)


def i_layerdup(cr, ink, acc):
    i_layers(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.rectangle(15, 15, 7, 7)
    cr.fill()


def i_delete(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(4, 6, 16, 2)
    cr.fill()
    cr.rectangle(9, 3, 6, 3)
    cr.stroke()
    cr.move_to(6, 8)
    cr.line_to(7.5, 21)
    cr.line_to(16.5, 21)
    cr.line_to(18, 8)
    cr.stroke()
    cr.set_source_rgb(*acc)
    for x in (10, 14):
        cr.move_to(x, 11)
        cr.line_to(x, 18)
    cr.stroke()


def i_up(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.move_to(12, 20)
    cr.line_to(12, 5)
    cr.move_to(6, 11)
    cr.line_to(12, 5)
    cr.line_to(18, 11)
    cr.stroke()


def i_down(cr, ink, acc):
    cr.save()
    cr.translate(0, 24)
    cr.scale(1, -1)
    i_up(cr, ink, acc)
    cr.restore()


def i_merge(cr, ink, acc):
    for dy in (0, 8):
        cr.move_to(12, 2 + dy)
        cr.line_to(20, 6 + dy)
        cr.line_to(12, 10 + dy)
        cr.line_to(4, 6 + dy)
        cr.close_path()
        _fs(cr, ink)
    cr.set_source_rgb(*acc)
    cr.set_line_width(2)
    cr.move_to(12, 13)
    cr.line_to(12, 23)
    cr.move_to(9, 20)
    cr.line_to(12, 23)
    cr.line_to(15, 20)
    cr.stroke()


def i_props(cr, ink, acc):
    cr.set_source_rgb(*ink)
    for y in (6, 12, 18):
        cr.move_to(3, y)
        cr.line_to(21, y)
    cr.stroke()
    cr.set_source_rgb(*acc)
    for x, y in ((8, 6), (16, 12), (11, 18)):
        cr.arc(x, y, 2.5, 0, math.tau)
        cr.fill()


def i_flatten(cr, ink, acc):
    cr.move_to(12, 8)
    cr.line_to(21, 12.5)
    cr.line_to(12, 17)
    cr.line_to(3, 12.5)
    cr.close_path()
    _fs(cr, ink, acc)


def i_rulers(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(2, 2, 20, 5)
    cr.rectangle(2, 2, 5, 20)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    for i in range(9, 22, 3):
        cr.move_to(i + 0.5, 2)
        cr.line_to(i + 0.5, 5)
        cr.move_to(2, i + 0.5)
        cr.line_to(5, i + 0.5)
    cr.set_line_width(1)
    cr.stroke()


def i_grid(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(1)
    for i in range(3, 22, 6):
        cr.move_to(i + 0.5, 3)
        cr.line_to(i + 0.5, 21)
        cr.move_to(3, i + 0.5)
        cr.line_to(21, i + 0.5)
    cr.stroke()


def i_statusbar(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 3.5, 17, 17)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.rectangle(4, 16, 16, 4)
    cr.fill()


def i_fullscreen(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 5.5, 17, 13)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.set_line_width(2)
    for (x, y, dx, dy) in ((6, 8, 1, 1), (18, 8, -1, 1), (6, 16, 1, -1), (18, 16, -1, -1)):
        cr.move_to(x, y + 3 * dy)
        cr.line_to(x, y)
        cr.line_to(x + 3 * dx, y)
    cr.stroke()


def i_invert(cr, ink, acc):
    cr.arc(12, 12, 9, 0, math.tau)
    cr.set_source_rgb(*ink)
    cr.stroke()
    cr.move_to(12, 3)
    cr.arc(12, 12, 9, -math.pi / 2, math.pi / 2)
    cr.close_path()
    cr.fill()


def i_layerpanel(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 3.5, 17, 17)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.rectangle(14, 4, 6, 16)
    cr.fill()


def i_wallpaper(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(2.5, 3.5, 19, 13)
    cr.stroke()
    cr.move_to(9, 20.5)
    cr.line_to(15, 20.5)
    cr.stroke()
    cr.set_source_rgb(*acc)
    cr.move_to(4, 15)
    cr.line_to(9, 9)
    cr.line_to(13, 13)
    cr.line_to(16, 10)
    cr.line_to(20, 15)
    cr.close_path()
    cr.fill()


def i_info(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.arc(12, 12, 9, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(11, 10, 2, 8)
    cr.arc(12, 7, 1.3, 0, math.tau)
    cr.fill()


def i_exit(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.set_line_width(2)
    cr.move_to(6, 6)
    cr.line_to(18, 18)
    cr.move_to(18, 6)
    cr.line_to(6, 18)
    cr.stroke()


def i_flip_h(cr, ink, acc):
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
    cr.set_dash([2, 2])
    cr.move_to(12, 2)
    cr.line_to(12, 22)
    cr.stroke()
    cr.set_dash([])


def i_flip_v(cr, ink, acc):
    cr.save()
    cr.translate(12, 12)
    cr.rotate(math.pi / 2)
    cr.translate(-12, -12)
    i_flip_h(cr, ink, acc)
    cr.restore()


def i_rot_left(cr, ink, acc):
    cr.save()
    cr.translate(24, 0)
    cr.scale(-1, 1)
    i_rotate(cr, ink, acc)
    cr.restore()


def i_rot180(cr, ink, acc):
    i_rotate(cr, ink, acc)
    cr.set_source_rgb(*acc)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(6)
    cr.move_to(12, 23)
    cr.show_text("180")


def i_selall(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(4, 5, 16, 14)
    cr.fill()
    i_select(cr, ink, acc)


def i_selinvert(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(4, 5, 16, 14)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(8, 9, 8, 6)
    cr.fill()
    i_select(cr, ink, acc)


def i_transparent(cr, ink, acc):
    for yy in range(4):
        for xx in range(4):
            cr.set_source_rgb(*((0.8, 0.8, 0.8) if (xx + yy) % 2 else (1, 1, 1)))
            cr.rectangle(4 + xx * 4, 4 + yy * 4, 4, 4)
            cr.fill()
    cr.set_source_rgb(*ink)
    cr.rectangle(4.5, 4.5, 15, 15)
    cr.stroke()


def i_play(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.move_to(7, 4)
    cr.line_to(20, 12)
    cr.line_to(7, 20)
    cr.close_path()
    cr.fill()


def i_stop(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.rectangle(6, 5, 4, 14)
    cr.rectangle(14, 5, 4, 14)
    cr.fill()


def i_prevframe(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.rectangle(5, 5, 2.5, 14)
    cr.fill()
    cr.set_source_rgb(*acc)
    cr.move_to(19, 5)
    cr.line_to(9, 12)
    cr.line_to(19, 19)
    cr.close_path()
    cr.fill()


def i_nextframe(cr, ink, acc):
    cr.save()
    cr.translate(24, 0)
    cr.scale(-1, 1)
    i_prevframe(cr, ink, acc)
    cr.restore()


def i_frames(cr, ink, acc):
    # a film strip
    cr.set_source_rgb(*ink)
    cr.rectangle(3.5, 5.5, 17, 13)
    cr.stroke()
    for x in (5, 9, 13, 17):
        cr.rectangle(x, 6.5, 2, 1.5)
        cr.rectangle(x, 16, 2, 1.5)
    cr.fill()
    cr.set_source_rgb(*acc)
    cr.rectangle(6, 9.5, 5, 5)
    cr.fill()
    cr.set_source_rgba(acc[0], acc[1], acc[2], 0.35)
    cr.rectangle(13, 9.5, 5, 5)
    cr.fill()



def i_adjust(cr, ink, acc):
    # three sliders
    cr.set_line_width(1.6)
    cr.set_source_rgb(*ink)
    for y in (6, 12, 18):
        cr.move_to(3, y)
        cr.line_to(21, y)
    cr.stroke()
    cr.set_source_rgb(*acc)
    for x, y in ((8, 6), (15, 12), (10, 18)):
        cr.rectangle(x - 2, y - 3, 4, 6)
    cr.fill()


def i_brightness(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.arc(12, 12, 4.5, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.6)
    for k in range(8):
        a = k * math.tau / 8
        cr.move_to(12 + 7 * math.cos(a), 12 + 7 * math.sin(a))
        cr.line_to(12 + 10 * math.cos(a), 12 + 10 * math.sin(a))
    cr.stroke()


def i_huesat(cr, ink, acc):
    cols = [(0.86, 0.2, 0.2), (0.92, 0.7, 0.15), (0.3, 0.7, 0.3), (0.2, 0.55, 0.85), (0.55, 0.3, 0.75), (0.85, 0.3, 0.6)]
    for k, c in enumerate(cols):
        cr.set_source_rgb(*c)
        cr.move_to(12, 12)
        cr.arc(12, 12, 9, k * math.tau / 6 - math.pi / 2, (k + 1) * math.tau / 6 - math.pi / 2)
        cr.close_path()
        cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.arc(12, 12, 3.5, 0, math.tau)
    cr.fill()


def i_grey(cr, ink, acc):
    for k in range(4):
        v = 0.15 + k * 0.25
        cr.set_source_rgb(v, v, v)
        cr.rectangle(3 + k * 4.5, 4, 4.5, 16)
        cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1)
    cr.rectangle(3.5, 4.5, 17, 15)
    cr.stroke()


def i_blur(cr, ink, acc):
    for r, a in ((9, 0.15), (7, 0.3), (5, 0.55), (3, 1.0)):
        cr.set_source_rgba(acc[0], acc[1], acc[2], a)
        cr.arc(12, 12, r, 0, math.tau)
        cr.fill()


def i_sharpen(cr, ink, acc):
    cr.set_source_rgb(*acc)
    cr.move_to(12, 3)
    cr.line_to(20, 20)
    cr.line_to(4, 20)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(*ink)
    cr.set_line_width(1.4)
    cr.move_to(12, 3)
    cr.line_to(20, 20)
    cr.line_to(4, 20)
    cr.close_path()
    cr.stroke()


def i_sepia(cr, ink, acc):
    cr.set_source_rgb(0.55, 0.38, 0.2)
    cr.rectangle(3, 4, 18, 16)
    cr.fill()
    cr.set_source_rgb(0.85, 0.72, 0.5)
    cr.move_to(3, 20)
    cr.line_to(9, 11)
    cr.line_to(13, 16)
    cr.line_to(16, 13)
    cr.line_to(21, 20)
    cr.close_path()
    cr.fill()

ICONS = {k[2:]: v for k, v in globals().items() if k.startswith("i_") and callable(v)}


def _dark():
    from . import appearance
    return appearance.is_dark()


def ink_colors():
    """(ink, accent) for icons on the ribbon in the current light or dark mode."""
    if _dark():
        return (0.90, 0.90, 0.90), (0.94, 0.55, 0.55)
    return INK, MAROON


def ink():
    return ink_colors()[0]


def paint_icon(cr, name, size, ink=INK, acc=MAROON):
    fn = ICONS.get(name)
    if fn is None:
        return
    cr.save()
    cr.scale(size / 24.0, size / 24.0)
    cr.set_line_width(1.2)
    cr.set_line_cap(1)  # round
    cr.set_line_join(1)
    fn(cr, ink, acc)
    cr.restore()


class Icon(Gtk.DrawingArea):
    """A widget that paints one icon; greys out when insensitive, whitens on dark headers."""

    def __init__(self, name, size=16, on_dark=False, painter=None):
        super().__init__()
        self.name = name
        self.size = size
        self.on_dark = on_dark
        self.painter = painter
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_name_icon(self, name):
        self.name = name
        self.queue_draw()

    def _draw(self, w, cr):
        sens = self.is_sensitive()
        if self.on_dark:
            ink, acc = (1, 1, 1), (1, 0.85, 0.85)
        else:
            ink, acc = ink_colors()
        if not sens:
            ink = acc = (0.42, 0.42, 0.42) if _dark() else (0.65, 0.65, 0.65)
        if self.painter:
            self.painter(cr, self.size, ink, acc)
        else:
            paint_icon(cr, self.name, self.size, ink, acc)
        return False

    def snapshot_pixbuf(self, size=32):
        """The icon drawn at `size` as a pixbuf (a ribbon group folded into one button shows it)."""
        return pixbuf(self.name, size, self.painter)


def _chevron(cr, ink, acc):
    cr.set_source_rgb(*ink)
    cr.move_to(7, 10)
    cr.line_to(12, 15)
    cr.line_to(17, 10)
    cr.stroke()


ICONS.setdefault("chevron", _chevron)


def pixbuf(name, size, painter=None):
    """An icon as a GdkPixbuf (used by the suite's shared ribbon code)."""
    import cairo
    if painter is None and name not in ICONS:
        return None
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    ink, acc = ink_colors()
    if painter:
        painter(cr, size, ink, acc)
    else:
        paint_icon(cr, name, size, ink, acc)
    surf.flush()
    return Gdk.pixbuf_get_from_surface(surf, 0, 0, size, size)


def image(name, size):
    """An icon as a Gtk.Image (shared ribbon code)."""
    return Icon(name, size)


def swatch_pixbuf(name, size, color):
    return pixbuf(name, size)
