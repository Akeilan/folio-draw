"""ctypes binding to the native Folio Draw engine (libfolio_draw_engine.so)."""

import ctypes
import os
from ctypes import POINTER, c_char_p, c_float, c_int, c_uint, c_uint64, c_void_p, c_ubyte

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.environ.get("FOLIO_DRAW_ENGINE", ""),
    os.path.join(_HERE, "_native", "libfolio_draw_engine.so"),
    # a source checkout uses its own fresh build before any installed copy
    os.path.join(_HERE, "..", "engine", "target", "release", "libfolio_draw_engine.so"),
    "/usr/lib/folio-draw/libfolio_draw_engine.so",
]

_lib = None
for _p in _CANDIDATES:
    if _p and os.path.exists(_p):
        _lib = ctypes.CDLL(os.path.abspath(_p))
        break
if _lib is None:
    raise ImportError("Folio Draw engine library not found")

L = _lib
_P = c_void_p


ADJ_BRIGHT_CONTRAST, ADJ_HUE_SAT, ADJ_GREY, ADJ_BLUR, ADJ_SHARPEN, ADJ_SEPIA = range(6)


def _sig(name, res, *args):
    f = getattr(L, name)
    f.restype = res
    f.argtypes = list(args)


_sig("fd_version", c_uint)
_sig("fd_last_error", c_char_p)
_sig("fd_new", _P, c_uint, c_uint, c_uint)
_sig("fd_new_from_rgba", _P, c_uint, c_uint, c_char_p, c_char_p)
_sig("fd_free", None, _P)
_sig("fd_load", _P, c_char_p)
_sig("fd_save", c_int, _P, c_char_p, c_uint, c_uint)
_sig("fd_width", c_uint, _P)
_sig("fd_height", c_uint, _P)
_sig("fd_changes", c_uint64, _P)
_sig("fd_comp_ptr", c_void_p, _P)
_sig("fd_comp_update", c_int, _P, POINTER(c_int))
_sig("fd_invalidate", None, _P)
_sig("fd_flatten_rgba", None, _P, c_void_p)
_sig("fd_undo", c_int, _P)
_sig("fd_redo", c_int, _P)
_sig("fd_can_undo", c_int, _P)
_sig("fd_can_redo", c_int, _P)
_sig("fd_op_begin", None, _P)
_sig("fd_op_restore", None, _P)
_sig("fd_op_end", None, _P)
_sig("fd_op_cancel", None, _P)
_sig("fd_stroke_begin", None, _P, c_uint, c_float, c_float, c_uint)
_sig("fd_stroke_to", None, _P, c_float, c_float)
_sig("fd_stroke_end", None, _P)
_sig("fd_shape", None, _P, POINTER(c_float), c_uint, c_int, c_float, c_uint, c_uint, c_uint, c_int)
_sig("fd_blit_premul", None, _P, c_int, c_int, c_uint, c_uint, c_void_p, c_uint)
_sig("fd_fill", c_int, _P, c_int, c_int, c_uint, c_uint)
_sig("fd_pick", c_uint, _P, c_int, c_int, c_int)
_sig("fd_invert_colors", None, _P)
_sig("fd_adjust_preview", None, _P, c_uint, c_float, c_float, c_float)
_sig("fd_set_sample_all", None, _P, c_int)
_sig("fd_adjust_end", None, _P)
_sig("fd_adjust_cancel", None, _P)
_sig("fd_sel_rect", None, _P, c_int, c_int, c_int, c_int)
_sig("fd_sel_poly", None, _P, POINTER(c_float), c_uint)
_sig("fd_sel_all", None, _P)
_sig("fd_sel_exclude_color", None, _P, c_uint, c_uint)
_sig("fd_sel_none", None, _P)
_sig("fd_sel_invert", None, _P)
_sig("fd_sel_bounds", c_int, _P, POINTER(c_int))
_sig("fd_sel_delete", c_int, _P)
_sig("fd_float_lift", c_int, _P, c_int)
_sig("fd_float_from_rgba", None, _P, c_uint, c_uint, c_char_p, c_int, c_int)
_sig("fd_float_get", c_int, _P, POINTER(c_int))
_sig("fd_float_is_empty", c_int, _P)
_sig("fd_float_set_rect", None, _P, c_int, c_int, c_uint, c_uint)
_sig("fd_float_commit", None, _P)
_sig("fd_float_discard", None, _P)
_sig("fd_float_transform", None, _P, c_uint)
_sig("fd_float_color_key", None, _P, c_uint, c_uint)
_sig("fd_clip_extract", c_int, _P, POINTER(c_uint))
_sig("fd_clip_ptr", c_void_p, _P)
_sig("fd_layer_count", c_uint, _P)
_sig("fd_active", c_uint, _P)
_sig("fd_set_active", None, _P, c_uint)
_sig("fd_layer_name", c_uint, _P, c_uint, c_char_p, c_uint)
_sig("fd_layer_props", c_int, _P, c_uint, POINTER(c_float))
_sig("fd_layer_set_props", None, _P, c_uint, c_char_p, c_float, c_int, c_uint, c_uint, c_int)
_sig("fd_set_solo", None, _P, c_int)
_sig("fd_get_solo", c_int, _P)
_sig("fd_show_frame", None, _P, c_uint)
_sig("fd_gif_loop", c_int, _P)
_sig("fd_set_gif_loop", None, _P, c_int)
_sig("fd_frames_truncated", c_int, _P)
_sig("fd_layer_add", c_uint, _P, c_char_p)
_sig("fd_layer_duplicate", c_uint, _P)
_sig("fd_layer_delete", c_int, _P)
_sig("fd_layer_move", c_int, _P, c_uint, c_uint)
_sig("fd_layer_merge_down", c_int, _P)
_sig("fd_flatten", None, _P)
_sig("fd_layer_rgba", c_int, _P, c_uint, c_void_p)
_sig("fd_layer_thumb", None, _P, c_uint, c_void_p, c_uint, c_uint)
_sig("fd_image_transform", None, _P, c_uint)
_sig("fd_image_resize", None, _P, c_uint, c_uint, c_int)
_sig("fd_image_skew", None, _P, c_float, c_float)
_sig("fd_image_rotate", None, _P, c_float, c_int, c_uint)
_sig("fd_float_rotate", None, _P, c_float, c_int)
_sig("fd_canvas_size", None, _P, c_uint, c_uint, c_float, c_float)
_sig("fd_crop_to_selection", c_int, _P)

TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER, TOOL_AIRBRUSH, TOOL_CALLIG, TOOL_CALLIG2, TOOL_MARKER = range(7)
FMT_PNG, FMT_ORA, FMT_BMP24, FMT_BMP32, FMT_JPEG, FMT_GIF, FMT_GIF_ANIM = range(7)
FLIP_H, FLIP_V, ROT_CW, ROT_180, ROT_CCW = range(5)


def rotated_size(w, h, deg):
    """The size of a w x h image rotated by `deg` (matches the engine)."""
    import math
    n = deg % 360.0
    for k, a in enumerate((0.0, 90.0, 180.0, 270.0, 360.0)):
        if abs(n - a) < 1e-3:
            return (h, w) if k % 2 else (w, h)
    t = math.radians(n)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    return (max(1, math.ceil(w * c + h * s - 1e-3)), max(1, math.ceil(w * s + h * c - 1e-3)))
BLEND_NAMES = ["Normal", "Multiply", "Screen", "Overlay", "Darken", "Lighten", "Difference", "Add"]


class EngineError(Exception):
    pass


def last_error():
    e = L.fd_last_error()
    return e.decode("utf-8", "replace") if e else "unknown error"


def pack(c):
    """(r,g,b,a) 0-255 -> 0xRRGGBBAA"""
    r, g, b, a = c
    return ((r & 255) << 24) | ((g & 255) << 16) | ((b & 255) << 8) | (a & 255)


def unpack(v):
    return ((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255)


def _floats(points):
    flat = [float(v) for p in points for v in p]
    return (c_float * len(flat))(*flat), len(points)


class Document:
    """Owns one native document handle."""

    def __init__(self, handle):
        if not handle:
            raise EngineError(last_error())
        self.h = handle
        self._comp_array = None

    # ---- construction
    @classmethod
    def new(cls, w, h, fill=(255, 255, 255, 255)):
        return cls(L.fd_new(w, h, pack(fill)))

    @classmethod
    def from_rgba(cls, w, h, data, name="Background"):
        return cls(L.fd_new_from_rgba(w, h, bytes(data), name.encode()))

    @classmethod
    def load(cls, path):
        return cls(L.fd_load(path.encode()))

    def close(self):
        if self.h:
            L.fd_free(self.h)
            self.h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def save(self, path, fmt, matte=(255, 255, 255, 255)):
        if L.fd_save(self.h, path.encode(), fmt, pack(matte)) != 0:
            raise EngineError(last_error())

    # ---- basic info
    @property
    def width(self):
        return L.fd_width(self.h)

    @property
    def height(self):
        return L.fd_height(self.h)

    @property
    def changes(self):
        return L.fd_changes(self.h)

    def comp_ptr(self):
        return L.fd_comp_ptr(self.h)

    def comp_buffer(self):
        """A writable ctypes view of the composite (cairo ARGB32) buffer."""
        n = self.width * self.height * 4
        addr = L.fd_comp_ptr(self.h)
        self._comp_array = (c_ubyte * n).from_address(addr)
        return self._comp_array

    def comp_update(self):
        r = (c_int * 4)()
        if L.fd_comp_update(self.h, r):
            return tuple(r)
        return None

    def invalidate(self):
        L.fd_invalidate(self.h)

    def flatten_rgba(self):
        buf = ctypes.create_string_buffer(self.width * self.height * 4)
        L.fd_flatten_rgba(self.h, buf)
        return buf.raw

    def has_transparency(self):
        data = self.flatten_rgba()
        return any(a != 255 for a in data[3::4])

    # ---- undo / ops
    def undo(self):
        return bool(L.fd_undo(self.h))

    def redo(self):
        return bool(L.fd_redo(self.h))

    def can_undo(self):
        return bool(L.fd_can_undo(self.h))

    def can_redo(self):
        return bool(L.fd_can_redo(self.h))

    def op_begin(self):
        L.fd_op_begin(self.h)

    def op_restore(self):
        L.fd_op_restore(self.h)

    def op_end(self):
        L.fd_op_end(self.h)

    def op_cancel(self):
        L.fd_op_cancel(self.h)

    # ---- painting
    def stroke_begin(self, tool, size, hardness, color):
        L.fd_stroke_begin(self.h, tool, size, hardness, pack(color))

    def stroke_to(self, x, y):
        L.fd_stroke_to(self.h, x, y)

    def stroke_end(self):
        L.fd_stroke_end(self.h)

    def shape(self, points, closed, width, outline, fill, outline_on, fill_on, aa=True):
        arr, n = _floats(points)
        mode = (1 if outline_on else 0) | (2 if fill_on else 0)
        L.fd_shape(self.h, arr, n, 1 if closed else 0, width, pack(outline), pack(fill), mode, 1 if aa else 0)

    def blit_premul(self, x, y, w, h, data, stride):
        buf = (c_ubyte * len(data)).from_buffer_copy(data)
        L.fd_blit_premul(self.h, int(x), int(y), w, h, ctypes.addressof(buf), stride)

    def fill(self, x, y, color, tol):
        return bool(L.fd_fill(self.h, int(x), int(y), pack(color), int(tol)))

    def pick(self, x, y, all_layers=True):
        return unpack(L.fd_pick(self.h, int(x), int(y), 1 if all_layers else 0))

    def invert_colors(self):
        L.fd_invert_colors(self.h)

    # ---- adjustments (kinds: ADJ_*); a preview can be changed, then kept or dropped
    def adjust_preview(self, kind, a=0.0, b=0.0, c=0.0):
        L.fd_adjust_preview(self.h, kind, float(a), float(b), float(c))

    def set_sample_all(self, on):
        """Copy, Transparent selection and Fill look at every visible layer."""
        L.fd_set_sample_all(self.h, 1 if on else 0)

    def adjust_end(self):
        L.fd_adjust_end(self.h)

    def adjust_cancel(self):
        L.fd_adjust_cancel(self.h)

    def adjust(self, kind, a=0.0, b=0.0, c=0.0):
        self.adjust_preview(kind, a, b, c)
        self.adjust_end()

    # ---- selection
    def sel_rect(self, x, y, w, h):
        L.fd_sel_rect(self.h, int(x), int(y), int(w), int(h))

    def sel_poly(self, points):
        arr, n = _floats(points)
        L.fd_sel_poly(self.h, arr, n)

    def sel_exclude_color(self, color, tol=0):
        L.fd_sel_exclude_color(self.h, pack(color), tol)

    def sel_all(self):
        L.fd_sel_all(self.h)

    def sel_none(self):
        L.fd_sel_none(self.h)

    def sel_invert(self):
        L.fd_sel_invert(self.h)

    def sel_bounds(self):
        r = (c_int * 4)()
        return tuple(r) if L.fd_sel_bounds(self.h, r) else None

    def sel_delete(self):
        return bool(L.fd_sel_delete(self.h))

    def float_lift(self, cut=True):
        return bool(L.fd_float_lift(self.h, 1 if cut else 0))

    def float_from_rgba(self, w, h, data, x, y):
        L.fd_float_from_rgba(self.h, w, h, bytes(data), int(x), int(y))

    def float_rect(self):
        r = (c_int * 4)()
        return tuple(r) if L.fd_float_get(self.h, r) else None

    def float_is_empty(self):
        return bool(L.fd_float_is_empty(self.h))

    def float_set_rect(self, x, y, w, h):
        L.fd_float_set_rect(self.h, int(round(x)), int(round(y)), max(1, int(round(w))), max(1, int(round(h))))

    def float_commit(self):
        L.fd_float_commit(self.h)

    def float_discard(self):
        L.fd_float_discard(self.h)

    def float_transform(self, kind):
        L.fd_float_transform(self.h, kind)

    def float_color_key(self, color, tol=0):
        L.fd_float_color_key(self.h, pack(color), tol)

    def clip_extract(self):
        wh = (c_uint * 2)()
        if not L.fd_clip_extract(self.h, wh):
            return None
        w, h = wh[0], wh[1]
        addr = L.fd_clip_ptr(self.h)
        return w, h, ctypes.string_at(addr, w * h * 4)

    # ---- layers
    def layer_count(self):
        return L.fd_layer_count(self.h)

    @property
    def active(self):
        return L.fd_active(self.h)

    def set_active(self, i):
        L.fd_set_active(self.h, i)

    def layer_name(self, i):
        n = L.fd_layer_name(self.h, i, None, 0)
        buf = ctypes.create_string_buffer(n + 1)
        L.fd_layer_name(self.h, i, buf, n + 1)
        return buf.value.decode("utf-8", "replace")

    def layer_props(self, i):
        out = (c_float * 5)()
        L.fd_layer_props(self.h, i, out)
        return {"opacity": out[0], "visible": out[1] > 0.5, "blend": int(out[2]), "id": int(out[3]), "delay": int(out[4])}

    def layer_set(self, i, name=None, opacity=None, visible=None, blend=None, delay=None, record=True):
        p = self.layer_props(i)
        L.fd_layer_set_props(
            self.h, i, name.encode() if name is not None else None,
            p["opacity"] if opacity is None else opacity,
            int(p["visible"] if visible is None else visible),
            p["blend"] if blend is None else blend,
            int(p["delay"] if delay is None else delay),
            1 if record else 0,
        )

    # ---- animation
    @property
    def frames_view(self):
        return bool(L.fd_get_solo(self.h))

    def set_frames_view(self, on):
        L.fd_set_solo(self.h, 1 if on else 0)

    def show_frame(self, i):
        """Switch the displayed/active frame without committing anything (playback)."""
        L.fd_show_frame(self.h, i)

    @property
    def gif_loop(self):
        return L.fd_gif_loop(self.h)

    def set_gif_loop(self, v):
        L.fd_set_gif_loop(self.h, int(v))

    @property
    def frames_truncated(self):
        return bool(L.fd_frames_truncated(self.h))

    def is_animation(self):
        return self.layer_count() > 1 and (self.frames_view or any(self.layer_props(i)["delay"] > 0 for i in range(self.layer_count())))

    def layer_add(self, name):
        return L.fd_layer_add(self.h, name.encode())

    def layer_duplicate(self):
        return L.fd_layer_duplicate(self.h)

    def layer_delete(self):
        return bool(L.fd_layer_delete(self.h))

    def layer_move(self, a, b):
        return bool(L.fd_layer_move(self.h, a, b))

    def layer_merge_down(self):
        return bool(L.fd_layer_merge_down(self.h))

    def flatten(self):
        L.fd_flatten(self.h)

    def layer_rgba(self, i):
        buf = ctypes.create_string_buffer(self.width * self.height * 4)
        L.fd_layer_rgba(self.h, i, buf)
        return buf.raw

    def layer_thumb(self, i, tw, th):
        buf = ctypes.create_string_buffer(tw * th * 4)
        L.fd_layer_thumb(self.h, i, buf, tw, th)
        return buf.raw

    # ---- image
    def image_transform(self, kind):
        L.fd_image_transform(self.h, kind)

    def image_resize(self, w, h, smooth=True):
        L.fd_image_resize(self.h, int(w), int(h), 1 if smooth else 0)

    def image_skew(self, ax, ay):
        L.fd_image_skew(self.h, ax, ay)

    def image_rotate(self, deg, smooth=True, fill=None):
        """Rotate the whole image by any angle (degrees, clockwise); `fill` colours the
        uncovered corners of the bottom layer, None leaves them transparent."""
        L.fd_image_rotate(self.h, float(deg), 1 if smooth else 0, pack(fill) if fill and fill[3] else 0)

    def float_rotate(self, deg, smooth=True):
        L.fd_float_rotate(self.h, float(deg), 1 if smooth else 0)

    def canvas_size(self, w, h, ax=0.0, ay=0.0):
        L.fd_canvas_size(self.h, int(w), int(h), ax, ay)

    def crop_to_selection(self):
        return bool(L.fd_crop_to_selection(self.h))
