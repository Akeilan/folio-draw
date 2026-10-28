"""Embroidery dialogs: hoop and machine, picture to shapes, stitch properties, lettering, threads,
scale. Each returns plain values (or None when cancelled) so the window and the tests can
drive them alike."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, PangoCairo  # noqa: E402

from . import embroidery as M
from .dialogs import _commit_spins, _dialog, _frame, _spin


def _grid():
    g = Gtk.Grid(row_spacing=6, column_spacing=10)
    return g


def _label(text):
    lb = Gtk.Label(label=text, xalign=0)
    return lb


def _colour_button(rgb):
    b = Gtk.ColorButton()
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1
    b.set_rgba(c)
    return b


def _rgb_of(btn):
    c = btn.get_rgba()
    return [int(round(c.red * 255)), int(round(c.green * 255)), int(round(c.blue * 255))]


# --------------------------------------------------------------------------- hoop and machine

def hoop_settings(parent, settings, new=False):
    """Hoop, machine, fabric and thread settings. Returns the new settings dict or None."""
    s = dict(M.DEFAULT_SETTINGS)
    s.update(settings or {})
    d, area = _dialog(parent, "New Embroidery" if new else "Hoop and Machine", ok="Create" if new else "OK")
    g = _grid()
    g.attach(_label("Machine"), 0, 0, 1, 1)
    machine = Gtk.ComboBoxText()
    for name in M.MACHINES:
        machine.append(name, name)
    machine.set_active_id(s.get("machine", "Brother Skitch PP1"))
    g.attach(machine, 1, 0, 3, 1)
    g.attach(_label("Hoop"), 0, 1, 1, 1)
    hoop = Gtk.ComboBoxText()
    for name, w, h in M.HOOPS:
        hoop.append(name, name)
    hoop.append("custom", "Custom size")
    hoop.set_active_id(s.get("hoop") if s.get("hoop") in [h[0] for h in M.HOOPS] else "custom")
    g.attach(hoop, 1, 1, 3, 1)
    hw, hh = M.hoop_mm(s)
    wspin = _spin(30, 500, hw, 1, 1)
    hspin = _spin(30, 500, hh, 1, 1)
    g.attach(_label("Width"), 0, 2, 1, 1)
    g.attach(wspin, 1, 2, 1, 1)
    g.attach(_label("Height"), 2, 2, 1, 1)
    g.attach(hspin, 3, 2, 1, 1)
    mm_note = _label("mm")

    def hoop_changed(*_):
        hid = hoop.get_active_id()
        for name, w, h in M.HOOPS:
            if name == hid:
                wspin.set_value(w)
                hspin.set_value(h)
        custom = hid == "custom"
        wspin.set_sensitive(custom)
        hspin.set_sensitive(custom)

    def machine_changed(*_):
        m = M.MACHINES.get(machine.get_active_id(), {})
        if m.get("hoops"):
            hoop.set_active_id(m["hoops"][0])
    hoop.connect("changed", hoop_changed)
    machine.connect("changed", machine_changed)
    hoop_changed()
    g.attach(mm_note, 4, 2, 1, 1)
    area.pack_start(_frame("Hoop", g), False, False, 0)

    g2 = _grid()
    g2.attach(_label("Fabric colour (preview)"), 0, 0, 1, 1)
    fabric = _colour_button(s.get("fabric", [244, 239, 226]))
    g2.attach(fabric, 1, 0, 1, 1)
    g2.attach(_label("Threads"), 0, 1, 1, 1)
    chart = Gtk.ComboBoxText()
    chart.append("brother", "Brother chart (63 colours)")
    chart.append("exact", "Exact colours of the picture")
    chart.set_active_id(s.get("threads", "brother"))
    g2.attach(chart, 1, 1, 1, 1)
    g2.attach(_label("Trim jumps longer than"), 0, 2, 1, 1)
    trim = _spin(0.5, 20, s.get("trim", 2.0), 1, 0.5)
    g2.attach(trim, 1, 2, 1, 1)
    g2.attach(_label("mm"), 2, 2, 1, 1)
    ties = Gtk.CheckButton(label="Tie stitches at starts and ends")
    ties.set_active(bool(s.get("ties", True)))
    g2.attach(ties, 0, 3, 3, 1)
    g2.attach(_label("Longest stitch"), 0, 4, 1, 1)
    smax = _spin(3, 12, s.get("max", 7.0), 1, 0.5)
    g2.attach(smax, 1, 4, 1, 1)
    g2.attach(_label("mm"), 2, 4, 1, 1)
    area.pack_start(_frame("Stitching", g2), False, False, 0)
    d.show_all()
    r = d.run()
    _commit_spins(wspin, hspin, trim, smax)
    out = None
    if r == Gtk.ResponseType.OK:
        out = dict(s)
        out.update({"machine": machine.get_active_id(), "hoop": hoop.get_active_id(),
                    "hoop_mm": [round(wspin.get_value(), 1), round(hspin.get_value(), 1)],
                    "fabric": _rgb_of(fabric), "threads": chart.get_active_id(), "trim": trim.get_value(),
                    "ties": ties.get_active(), "max": smax.get_value()})
    d.destroy()
    return out


# --------------------------------------------------------------------------- picture to shapes

def trace_settings(parent, last=None, bg=None):
    """Picture-to-shapes settings: colours, background, crop, smoothing, smallest region."""
    p = {"colours": 0, "background": "remove", "crop": True, "smoothing": 1, "min_area": 1.5, "edge_radius": 2}
    p.update(last or {})
    d, area = _dialog(parent, "Convert to Shapes", ok="Convert")
    g = _grid()
    g.attach(_label("Colours"), 0, 0, 1, 1)
    auto = Gtk.RadioButton.new_with_label(None, "Automatic")
    fixed = Gtk.RadioButton.new_with_label_from_widget(auto, "Exactly")
    count = _spin(1, 30, p["colours"] or 6)
    (fixed if p["colours"] else auto).set_active(True)
    g.attach(auto, 1, 0, 1, 1)
    g.attach(fixed, 2, 0, 1, 1)
    g.attach(count, 3, 0, 1, 1)
    g.attach(_label("Background"), 0, 1, 1, 1)
    bgmode = Gtk.ComboBoxText()
    bgmode.append("remove", "Remove (leave the fabric showing)")
    bgmode.append("keep", "Keep (stitch it)")
    bgmode.append("pick", "Remove this colour:")
    bgmode.set_active_id(p.get("background", "remove") if not p.get("pick") else "pick")
    g.attach(bgmode, 1, 1, 2, 1)
    pick = _colour_button(p.get("bg") or bg or [255, 255, 255])
    g.attach(pick, 3, 1, 1, 1)
    crop = Gtk.CheckButton(label="Crop to the artwork and fit it to the hoop")
    crop.set_active(bool(p.get("crop", True)))
    g.attach(crop, 0, 2, 4, 1)
    g.attach(_label("Smoothing"), 0, 3, 1, 1)
    smooth = _spin(0, 4, p.get("smoothing", 1))
    g.attach(smooth, 1, 3, 1, 1)
    g.attach(_label("Edge smoothing"), 2, 3, 1, 1)
    edge = _spin(0, 6, p.get("edge_radius", 2))
    g.attach(edge, 3, 3, 1, 1)
    g.attach(_label("Smallest region"), 0, 4, 1, 1)
    minar = _spin(0.1, 50, p.get("min_area", 1.5), 1, 0.1)
    g.attach(minar, 1, 4, 1, 1)
    g.attach(_label("mm²"), 2, 4, 1, 1)
    area.pack_start(_frame("Picture to shapes", g), False, False, 0)
    note = Gtk.Label(xalign=0)
    note.set_markup("<small>Each colour region becomes a shape you can reshape, recolour and give its own stitches.</small>")
    note.set_line_wrap(True)
    area.pack_start(note, False, False, 0)
    d.show_all()
    r = d.run()
    _commit_spins(count, smooth, edge, minar)
    out = None
    if r == Gtk.ResponseType.OK:
        mode = bgmode.get_active_id()
        out = {"colours": 0 if auto.get_active() else int(count.get_value()), "background": "keep" if mode == "keep" else "remove",
               "pick": mode == "pick", "crop": crop.get_active(), "smoothing": int(smooth.get_value()),
               "edge_radius": int(edge.get_value()), "min_area": minar.get_value()}
        if mode == "pick":
            out["bg"] = _rgb_of(pick)
    d.destroy()
    return out


# --------------------------------------------------------------------------- stitch properties

TYPES = [("auto", "Automatic (by width)"), ("fill", "Fill (tatami)"), ("satin", "Satin"), ("run", "Running stitch")]


def stitch_properties(parent, objs):
    """Stitch settings for one or more shapes. Returns {key: value} of the fields the person
    set (applied to every selected shape), or None."""
    first = dict(M.STITCH_DEFAULTS)
    first.update((objs[0].get("stitch") or {}) if objs else {})

    def same(key):
        vals = {repr(((o.get("stitch") or {}).get(key, M.STITCH_DEFAULTS.get(key)))) for o in objs}
        return len(vals) == 1
    d, area = _dialog(parent, "Stitch Properties" + (" (%d shapes)" % len(objs) if len(objs) > 1 else ""))
    changed = set()
    g = _grid()
    g.attach(_label("Stitch type"), 0, 0, 1, 1)
    kind = Gtk.ComboBoxText()
    for k, lab in TYPES:
        kind.append(k, lab)
    kind.set_active_id(first.get("type", "auto") if same("type") else None)
    kind.connect("changed", lambda *_: changed.add("type"))
    g.attach(kind, 1, 0, 3, 1)
    rows = [("angle", "Fill angle", 0, 359, 0, "°"), ("spacing", "Row spacing", 0.2, 2.0, 2, "mm"),
            ("length", "Stitch length", 1.0, 7.0, 1, "mm"), ("satin_spacing", "Satin spacing", 0.2, 1.5, 2, "mm"),
            ("pull", "Pull compensation", 0.0, 1.0, 2, "mm"), ("min_width", "Narrowest satin", 0.4, 3.0, 1, "mm"),
            ("run_length", "Running stitch length", 1.0, 5.0, 1, "mm")]
    spins = {}
    for i, (key, lab, lo, hi, dig, unit) in enumerate(rows, start=1):
        g.attach(_label(lab), 0, i, 1, 1)
        val = first.get(key)
        if key == "angle":
            autoang = Gtk.CheckButton(label="Automatic")
            autoang.set_active(val is None)
            g.attach(autoang, 3, i, 1, 1)
            autoang.connect("toggled", lambda *_: changed.add("angle"))
            spins["_autoangle"] = autoang
            val = 45 if val is None else val
        sp = _spin(lo, hi, val, dig, 10 ** -dig if dig else 1)
        if not same(key):
            sp.set_text("")
        sp.connect("value-changed", lambda *_a, k=key: changed.add(k))
        g.attach(sp, 1, i, 1, 1)
        g.attach(_label(unit), 2, i, 1, 1)
        spins[key] = sp
    n = len(rows) + 1
    underlay = Gtk.CheckButton(label="Underlay")
    underlay.set_active(bool(first.get("underlay", True)))
    underlay.connect("toggled", lambda *_: changed.add("underlay"))
    g.attach(underlay, 0, n, 2, 1)
    bean = Gtk.CheckButton(label="Triple running stitch")
    bean.set_active(bool(first.get("bean", True)))
    bean.connect("toggled", lambda *_: changed.add("bean"))
    g.attach(bean, 2, n, 2, 1)
    stop = Gtk.CheckButton(label="Stop the machine after this shape")
    stop.set_active(all(o.get("stop") for o in objs))
    stop.connect("toggled", lambda *_: changed.add("stop"))
    g.attach(stop, 0, n + 1, 4, 1)
    area.pack_start(_frame("Stitches", g), False, False, 0)
    d.show_all()
    r = d.run()
    _commit_spins(*[v for k, v in spins.items() if not k.startswith("_")])
    out = None
    if r == Gtk.ResponseType.OK:
        out = {}
        for k in changed:
            if k == "type":
                if kind.get_active_id():
                    out["type"] = kind.get_active_id()
            elif k == "angle":
                out["angle"] = None if spins["_autoangle"].get_active() else spins["angle"].get_value()
            elif k == "underlay":
                out["underlay"] = underlay.get_active()
            elif k == "bean":
                out["bean"] = bean.get_active()
            elif k == "stop":
                out["stop"] = stop.get_active()
            elif k in spins:
                out[k] = spins[k].get_value()
    d.destroy()
    return out


# --------------------------------------------------------------------------- threads

def choose_thread(parent, current=None, exact=False):
    """Pick a thread from the Brother chart (or any colour). Returns a thread dict or None."""
    d, area = _dialog(parent, "Thread")
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(9)
    flow.set_min_children_per_line(9)
    flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
    chosen = {"t": dict(current) if current else None}
    name_lbl = Gtk.Label(xalign=0)

    def show(t):
        name_lbl.set_text(M.thread_label(t) if t else "")
    for t in M.chart():
        da = Gtk.DrawingArea()
        da.set_size_request(30, 22)

        def draw(w, cr, t=t):
            r, g, b = [v / 255 for v in t["rgb"]]
            cr.set_source_rgb(r, g, b)
            cr.rectangle(1, 1, w.get_allocated_width() - 2, w.get_allocated_height() - 2)
            cr.fill_preserve()
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.set_line_width(1)
            cr.stroke()
        da.connect("draw", draw)
        da.set_tooltip_text(M.thread_label(t))
        child = Gtk.FlowBoxChild()
        child.add(da)
        child.thread = t
        flow.add(child)
        if current and current.get("pec") == t["pec"]:
            flow.select_child(child)

    def picked(fb, child):
        chosen["t"] = dict(child.thread)
        show(chosen["t"])
    flow.connect("child-activated", picked)
    area.pack_start(_frame("Brother thread chart", flow), False, False, 0)
    row = Gtk.Box(spacing=8)
    row.pack_start(name_lbl, True, True, 0)
    custom = _colour_button((current or {}).get("rgb", [0, 0, 0]))
    custom.set_tooltip_text("Any colour (stitched with the nearest chart thread on machines that read only PEC)")

    def custom_set(b):
        rgb = _rgb_of(b)
        chosen["t"] = {"rgb": rgb, "name": "#%02X%02X%02X" % tuple(rgb)} if exact else M.nearest_thread(rgb)
        show(chosen["t"])
    custom.connect("color-set", custom_set)
    row.pack_end(custom, False, False, 0)
    row.pack_end(_label("Other colour"), False, False, 0)
    area.pack_start(row, False, False, 0)
    show(chosen["t"])
    d.show_all()
    for child in flow.get_children():
        if current and current.get("pec") == child.thread["pec"]:
            flow.select_child(child)
            child.grab_focus()
    r = d.run()
    out = chosen["t"] if r == Gtk.ResponseType.OK else None
    d.destroy()
    return out


# --------------------------------------------------------------------------- lettering

def lettering(parent, obj=None):
    """Lettering settings. Returns a dict (text, font, cap, arc, radius, spacing, thread, type)
    or None."""
    o = {"text": "", "font": "Sans Bold", "cap": 10.0, "arc": "none", "radius": 40.0, "spacing": 0.0,
         "thread": M.chart_thread(20), "type": "auto"}
    if obj:
        o.update({k: obj[k] for k in o if k in obj})
    d, area = _dialog(parent, "Lettering", ok="OK")
    g = _grid()
    g.attach(_label("Text"), 0, 0, 1, 1)
    text = Gtk.Entry()
    text.set_text(o["text"])
    text.set_activates_default(True)
    text.set_width_chars(28)
    g.attach(text, 1, 0, 3, 1)
    g.attach(_label("Font"), 0, 1, 1, 1)
    font = Gtk.ComboBoxText.new_with_entry()
    fams = sorted({f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}, key=str.lower)
    for f in fams:
        font.append_text(f)
    font.get_child().set_text(o["font"].replace(" Bold", ""))
    g.attach(font, 1, 1, 2, 1)
    bold = Gtk.CheckButton(label="Bold")
    bold.set_active(o["font"].endswith(" Bold"))
    g.attach(bold, 3, 1, 1, 1)
    g.attach(_label("Cap height"), 0, 2, 1, 1)
    cap = _spin(2, 150, o["cap"], 1, 0.5)
    g.attach(cap, 1, 2, 1, 1)
    g.attach(_label("mm"), 2, 2, 1, 1)
    g.attach(_label("Letter spacing"), 0, 3, 1, 1)
    sp = _spin(-5, 20, o["spacing"], 1, 0.1)
    g.attach(sp, 1, 3, 1, 1)
    g.attach(_label("mm"), 2, 3, 1, 1)
    g.attach(_label("Shape"), 0, 4, 1, 1)
    arc = Gtk.ComboBoxText()
    for k, lab in (("none", "Straight"), ("top", "Arc over the top"), ("bottom", "Arc along the bottom")):
        arc.append(k, lab)
    arc.set_active_id(o["arc"])
    g.attach(arc, 1, 4, 1, 1)
    g.attach(_label("Radius"), 2, 4, 1, 1)
    rad = _spin(5, 300, o["radius"], 1, 0.5)
    g.attach(rad, 3, 4, 1, 1)
    arc.connect("changed", lambda *_: rad.set_sensitive(arc.get_active_id() != "none"))
    rad.set_sensitive(o["arc"] != "none")
    g.attach(_label("Stitches"), 0, 5, 1, 1)
    kind = Gtk.ComboBoxText()
    for k, lab in (("auto", "Automatic (fill under 8 mm)"), ("fill", "Fill"), ("satin", "Satin"), ("run", "Running stitch")):
        kind.append(k, lab)
    kind.set_active_id(o["type"])
    g.attach(kind, 1, 5, 3, 1)
    thr = {"t": o["thread"]}
    tb = Gtk.Button(label=M.thread_label(o["thread"]))

    def pick_thread(*_):
        t = choose_thread(d, thr["t"])
        if t:
            thr["t"] = t
            tb.set_label(M.thread_label(t))
    tb.connect("clicked", pick_thread)
    g.attach(_label("Thread"), 0, 6, 1, 1)
    g.attach(tb, 1, 6, 3, 1)
    area.pack_start(_frame("Lettering", g), False, False, 0)
    d.show_all()
    r = d.run()
    _commit_spins(cap, sp, rad)
    out = None
    if r == Gtk.ResponseType.OK and text.get_text().strip():
        fam = font.get_child().get_text().strip() or "Sans"
        out = {"text": text.get_text(), "font": fam + (" Bold" if bold.get_active() else ""), "cap": cap.get_value(),
               "spacing": sp.get_value(), "arc": arc.get_active_id(), "radius": rad.get_value(), "thread": thr["t"],
               "type": kind.get_active_id()}
    d.destroy()
    return out


def scale_percent(parent, current=100.0):
    d, area = _dialog(parent, "Scale Design")
    g = _grid()
    g.attach(_label("Size"), 0, 0, 1, 1)
    s = _spin(10, 400, current, 0, 1)
    g.attach(s, 1, 0, 1, 1)
    g.attach(_label("%"), 2, 0, 1, 1)
    note = _label("Imported stitches are scaled, not re-made: beyond ±10 % the stitches get too dense or too sparse.")
    note.set_line_wrap(True)
    note.set_max_width_chars(40)
    g.attach(note, 0, 1, 3, 1)
    area.pack_start(g, False, False, 0)
    d.show_all()
    r = d.run()
    _commit_spins(s)
    out = s.get_value() if r == Gtk.ResponseType.OK else None
    d.destroy()
    return out
