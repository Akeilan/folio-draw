from gi.repository import Gdk


class _Ev:
    def __init__(self, kind, x, y, button=1, state=0):
        self.type, self.x, self.y, self.button, self.state = kind, float(x), float(y), button, Gdk.ModifierType(state)


def drag_on(win, points, button=1, state=0):
    cv = win.canvas
    sx, sy = cv.to_screen(*points[0])
    cv._press(cv.area, _Ev(Gdk.EventType.BUTTON_PRESS, sx, sy, button, state))
    for p in points[1:]:
        cv._motion(cv.area, _Ev(Gdk.EventType.MOTION_NOTIFY, *cv.to_screen(*p), button, state))
    cv._release(cv.area, _Ev(Gdk.EventType.BUTTON_RELEASE, *cv.to_screen(*points[-1]), button, state))
