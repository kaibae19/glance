# SPDX-License-Identifier: GPL-3.0-or-later
"""Crop selection geometry, in image pixel coordinates. No GTK here, so it tests headless.

Ratios are width / height. Callers orient a ratio (landscape or portrait) before passing it in.
"""

from dataclasses import dataclass

RATIOS = {"free": None, "original": "original", "1:1": 1.0, "4:3": 4 / 3, "16:9": 16 / 9}
HANDLES = ("nw", "ne", "se", "sw", "n", "e", "s", "w")  # corners first: they win hit-tests
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def contains(self, px, py):
        return self.x <= px <= self.right and self.y <= py <= self.bottom

    def box(self, bounds):
        """Whole-pixel (left, top, right, bottom) inside the image, at least 1×1: what Crop gets."""
        iw, ih = bounds
        left = min(max(round(self.x), 0), iw - 1)
        top = min(max(round(self.y), 0), ih - 1)
        right = max(min(round(self.right), iw), left + 1)
        bottom = max(min(round(self.bottom), ih), top + 1)
        return left, top, right, bottom

    def pixel_size(self, bounds):
        left, top, right, bottom = self.box(bounds)
        return right - left, bottom - top


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def ratio_value(name, bounds):
    ratio = RATIOS.get(name)
    return bounds[0] / bounds[1] if ratio == "original" else ratio


def orient(ratio, w, h):
    """ratio or its inverse, whichever matches a w × h shape (landscape or portrait)."""
    if ratio is None or ratio == 1:
        return ratio
    return ratio if (w >= h) == (ratio >= 1) else 1 / ratio


def handle_point(rect, handle):
    x = rect.x if "w" in handle else rect.right if "e" in handle else rect.x + rect.w / 2
    y = rect.y if "n" in handle else rect.bottom if "s" in handle else rect.y + rect.h / 2
    return x, y


def full(bounds):
    return Rect(0, 0, bounds[0], bounds[1])


def from_drag(anchor, point, bounds, ratio=None):
    """The rectangle dragged from anchor to point, kept inside the image, optionally at a fixed ratio."""
    iw, ih = bounds
    ax, ay = _clamp(anchor[0], 0, iw), _clamp(anchor[1], 0, ih)
    px, py = _clamp(point[0], 0, iw), _clamp(point[1], 0, ih)
    sx, sy = (-1 if px < ax else 1), (-1 if py < ay else 1)
    w, h = abs(px - ax), abs(py - ay)
    if ratio:
        w = max(w, h * ratio)
        h = w / ratio
        room_w = ax if sx < 0 else iw - ax
        room_h = ay if sy < 0 else ih - ay
        k = min(1.0, room_w / w if w else 1.0, room_h / h if h else 1.0)
        w, h = w * k, h * k
    return Rect(ax - w if sx < 0 else ax, ay - h if sy < 0 else ay, w, h)


def resize(rect, handle, point, bounds, ratio=None):
    """Drag one handle of rect to point; the opposite corner or edge stays put."""
    if len(handle) == 2:
        anchor = handle_point(rect, OPPOSITE[handle[0]] + OPPOSITE[handle[1]])
        return from_drag(anchor, point, bounds, ratio)
    iw, ih = bounds
    horizontal = handle in ("e", "w")
    if horizontal:
        fixed = rect.x if handle == "e" else rect.right
        moving, limit, cross, cross_limit = _clamp(point[0], 0, iw), iw, rect.y + rect.h / 2, ih
    else:
        fixed = rect.y if handle == "s" else rect.bottom
        moving, limit, cross, cross_limit = _clamp(point[1], 0, ih), ih, rect.x + rect.w / 2, iw
    length = abs(moving - fixed)
    if ratio:
        other = length / ratio if horizontal else length * ratio  # the perpendicular side
        room = 2 * min(cross, cross_limit - cross)
        if other > room:
            other = room
            length = other * ratio if horizontal else other / ratio
        start = fixed if moving >= fixed else fixed - length
        if horizontal:
            return Rect(start, cross - other / 2, length, other)
        return Rect(cross - other / 2, start, other, length)
    start = min(fixed, moving)
    if horizontal:
        return Rect(start, rect.y, length, rect.h)
    return Rect(rect.x, start, rect.w, length)


def move(rect, dx, dy, bounds):
    iw, ih = bounds
    return Rect(_clamp(rect.x + dx, 0, max(iw - rect.w, 0)), _clamp(rect.y + dy, 0, max(ih - rect.h, 0)),
                rect.w, rect.h)


def conform(rect, ratio):
    """The largest rectangle at ratio inside rect, centred on it (when the user picks a ratio)."""
    if not ratio or rect.w <= 0 or rect.h <= 0:
        return rect
    if rect.w / rect.h > ratio:
        w, h = rect.h * ratio, rect.h
    else:
        w, h = rect.w, rect.w / ratio
    return Rect(rect.x + (rect.w - w) / 2, rect.y + (rect.h - h) / 2, w, h)
