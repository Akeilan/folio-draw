"""Stroke stabilizer for the pencil, brushes and eraser (StreamLine, Stabilization and Motion
filtering, each 0-100), applied to pointer positions before they reach the engine.

Distances are in screen pixels, so the feel is the same at any zoom."""

import math

TOOLS = ("pencil", "brush", "eraser")
NAMES = ("StreamLine", "Stabilization", "Motion filtering")
TIPS = ("Smooths the line by letting it trail behind the pointer on a string, so wobbles and corners are evened out.",
        "Averages the last few pointer positions; the higher, the smoother and slower the line follows.",
        "Ignores small, shaky movements of the hand; the higher, the bigger the movement it ignores.")


class Stabilizer:
    def __init__(self, streamline=0, stabilization=0, motion=0, zoom=1.0):
        self.string = streamline / 100 * 40 / zoom          # length of the string
        self.window = 1 + int(round(stabilization / 100 * 15))  # how many points to average
        self.deadzone = motion / 100 * 8 / zoom             # movements smaller than this are jitter
        self.raw = None
        self.recent = []
        self.held = []
        self.out = None
        self.last_in = None

    @property
    def active(self):
        return self.string > 0 or self.window > 1 or self.deadzone > 0

    def start(self, x, y):
        self.raw = (x, y)
        self.recent = [(x, y)]
        self.held = []
        self.out = (x, y)
        self.last_in = (x, y)
        return (x, y)

    def feed(self, x, y):
        """A new pointer position; returns the point to draw to, or None to draw nothing yet."""
        self.last_in = (x, y)
        # motion filtering: wait for the hand to really move, then take where it has been on average
        if self.deadzone > 0:
            self.held.append((x, y))
            if math.hypot(x - self.raw[0], y - self.raw[1]) < self.deadzone:
                return None
            x = sum(p[0] for p in self.held) / len(self.held)
            y = sum(p[1] for p in self.held) / len(self.held)
            self.held = []
        self.raw = (x, y)
        # stabilization: average of the last few positions
        self.recent.append((x, y))
        del self.recent[:-self.window]
        tx = sum(p[0] for p in self.recent) / len(self.recent)
        ty = sum(p[1] for p in self.recent) / len(self.recent)
        # streamline: the pen is pulled along on a string
        ox, oy = self.out
        if self.string > 0:
            d = math.hypot(tx - ox, ty - oy)
            if d <= self.string:
                return None
            f = (d - self.string) / d
            tx, ty = ox + (tx - ox) * f, oy + (ty - oy) * f
        if (tx, ty) == self.out:
            return None
        self.out = (tx, ty)
        return self.out

    def finish(self):
        """At the end of the stroke the line runs on to where the pointer was let go."""
        if self.last_in is None or self.last_in == self.out:
            return []
        ox, oy = self.out
        ex, ey = self.last_in
        n = max(1, int(math.hypot(ex - ox, ey - oy) // 2))
        pts = [(ox + (ex - ox) * i / n, oy + (ey - oy) * i / n) for i in range(1, n + 1)]
        self.out = self.last_in
        return pts
