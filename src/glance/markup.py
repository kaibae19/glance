# SPDX-License-Identifier: GPL-3.0-or-later
"""Markup shapes and their drawing, shared by the canvas (live, as vectors) and Save/Export (as pixels).

Pure Cairo + Pango, no GTK widgets, so it tests headless. Coordinates are image pixels.
"""

import math
import sys
from dataclasses import dataclass, replace

import cairo
import gi

gi.require_foreign("cairo")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo
from PIL import Image

from . import selection as sel
from .ops import Op

KINDS = ("rect", "ellipse", "line", "arrow", "highlight", "text")
BOX_KINDS = ("rect", "ellipse", "highlight")
HIGHLIGHT_ALPHA = 0.4
FONT = "Sans Bold"

# GNOME palette, in Preview's order
PALETTE = [("Red", "#e01b24"), ("Orange", "#ff7800"), ("Yellow", "#f6d32d"), ("Green", "#33d17a"),
           ("Blue", "#3584e4"), ("Purple", "#9141ac"), ("Black", "#000000"), ("White", "#ffffff")]
WIDTHS = {"thin": 1, "medium": 2, "thick": 4}  # × the image's base stroke
TEXT_SIZES = {"thin": 7, "medium": 10, "thick": 16}  # × the base stroke, in px


TEXT_HANDLES = ("nw", "ne", "se", "sw")


def rgba_to_hex(rgba):
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgba[:3])


def nearest_weight(width, size):
    """The WIDTHS key closest to a stroke width on an image of size."""
    ratio = width / base_stroke(size)
    return min(WIDTHS, key=lambda k: abs(WIDTHS[k] - ratio))


def hex_to_rgba(spec):
    spec = spec.lstrip("#")
    return tuple(int(spec[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


def base_stroke(size):
    """Line width unit for an image, so markup reads the same on a screenshot and on a 24 MP photo."""
    return max(1.5, max(size) / 500)


@dataclass(frozen=True)
class Shape:
    kind: str
    p0: tuple[float, float]  # box kinds: one corner; line/arrow: start; text: top-left
    p1: tuple[float, float]  # box kinds: the other corner; line/arrow: end (the arrowhead); text: unused
    color: tuple[float, float, float, float] = (0.88, 0.11, 0.14, 1.0)
    width: float = 4.0
    text: str = ""
    size: float = 32.0  # text height in px
    font: str = FONT  # Pango family and style, e.g. "Cantarell Bold"; no size

    def moved(self, dx, dy):
        return replace(self, p0=(self.p0[0] + dx, self.p0[1] + dy), p1=(self.p1[0] + dx, self.p1[1] + dy))


@dataclass(frozen=True)
class Annotate(Op):
    """The markup layer: one op holding every shape. Editable while it is the document's last op."""
    shapes: tuple[Shape, ...]
    editable = True

    def apply(self, img):
        if not self.shapes:
            return img
        overlay = rasterize(self.shapes, img.size)
        out = Image.alpha_composite(img if img.mode == "RGBA" else img.convert("RGBA"), overlay)
        return out if img.mode == "RGBA" else out.convert("RGB")


# --- drawing ------------------------------------------------------------------------------------

def _box(shape):
    (x0, y0), (x1, y1) = shape.p0, shape.p1
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def _layout(cr, shape):
    layout = PangoCairo.create_layout(cr)
    # Unhinted metrics, so text measures the same at every zoom and in the saved file.
    options = cairo.FontOptions()
    options.set_hint_style(cairo.HINT_STYLE_NONE)
    options.set_hint_metrics(cairo.HINT_METRICS_OFF)
    PangoCairo.context_set_font_options(layout.get_context(), options)
    font = Pango.FontDescription.from_string(shape.font or FONT)
    font.set_absolute_size(shape.size * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(shape.text or " ", -1)
    return layout


def arrow_head(shape):
    """(tip, left, right, base): the filled arrowhead's corners and where the shaft stops."""
    (x0, y0), (x1, y1) = shape.p0, shape.p1
    angle = math.atan2(y1 - y0, x1 - x0)
    length = min(max(shape.width * 4, 10), math.hypot(x1 - x0, y1 - y0))
    spread = math.radians(25)
    left = (x1 - length * math.cos(angle - spread), y1 - length * math.sin(angle - spread))
    right = (x1 - length * math.cos(angle + spread), y1 - length * math.sin(angle + spread))
    base = (x1 - length * 0.8 * math.cos(angle), y1 - length * 0.8 * math.sin(angle))
    return (x1, y1), left, right, base


def draw(cr, shapes):
    for shape in shapes:
        cr.save()
        draw_shape(cr, shape)
        cr.restore()


def draw_shape(cr, shape):
    r, g, b, a = shape.color
    cr.set_source_rgba(r, g, b, a)
    cr.set_line_width(shape.width)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    x, y, w, h = _box(shape)
    if shape.kind == "rect":
        cr.rectangle(x, y, w, h)
        cr.stroke()
    elif shape.kind == "highlight":
        cr.set_source_rgba(r, g, b, a * HIGHLIGHT_ALPHA)
        cr.rectangle(x, y, w, h)
        cr.fill()
    elif shape.kind == "ellipse":
        if w > 0 and h > 0:
            cr.save()
            cr.translate(x + w / 2, y + h / 2)
            cr.scale(w / 2, h / 2)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()  # stroke in the unscaled space, so the line keeps one width
            cr.stroke()
    elif shape.kind == "line":
        cr.move_to(*shape.p0)
        cr.line_to(*shape.p1)
        cr.stroke()
    elif shape.kind == "arrow":
        tip, left, right, base = arrow_head(shape)
        cr.move_to(*shape.p0)
        cr.line_to(*base)
        cr.stroke()
        cr.move_to(*tip)
        cr.line_to(*left)
        cr.line_to(*right)
        cr.close_path()
        cr.fill()
    elif shape.kind == "text":
        cr.move_to(*shape.p0)
        PangoCairo.show_layout(cr, _layout(cr, shape))


def rasterize(shapes, size):
    """The shapes as a transparent RGBA image of size."""
    assert sys.byteorder == "little", "Cairo ARGB32 is native-endian; this reads it as BGRa"
    w, h = size
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    draw(cairo.Context(surface), shapes)
    surface.flush()
    # Cairo stores premultiplied alpha; Pillow's "RGBa" is premultiplied too, and convert() undoes it.
    return Image.frombuffer("RGBa", (w, h), bytes(surface.get_data()), "raw", "BGRa",
                            surface.get_stride(), 1).convert("RGBA")


# --- geometry for selecting and editing shapes ---------------------------------------------------

_scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def text_extent(shape):
    return _layout(_scratch, shape).get_pixel_size()


def bbox(shape):
    """The shape's selection.Rect (what handles surround)."""
    if shape.kind == "text":
        w, h = text_extent(shape)
        return sel.Rect(shape.p0[0], shape.p0[1], w, h)
    x, y, w, h = _box(shape)
    return sel.Rect(x, y, w, h)


def _segment_distance(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def hit(shape, point, tolerance):
    if shape.kind in ("line", "arrow"):
        return _segment_distance(point, shape.p0, shape.p1) <= tolerance + shape.width / 2
    r = bbox(shape)
    pad = tolerance + (shape.width / 2 if shape.kind in ("rect", "ellipse") else 0)
    return r.x - pad <= point[0] <= r.right + pad and r.y - pad <= point[1] <= r.bottom + pad


def shape_at(shapes, point, tolerance):
    """Index of the topmost shape under point, or None."""
    for i in range(len(shapes) - 1, -1, -1):
        if hit(shapes[i], point, tolerance):
            return i
    return None


def handles(shape):
    """{name: (x, y)}: endpoints for lines and arrows, corners for text (they scale it), all eight for boxes."""
    if shape.kind in ("line", "arrow"):
        return {"p0": shape.p0, "p1": shape.p1}
    r = bbox(shape)
    if shape.kind == "text":
        return {h: sel.handle_point(r, h) for h in TEXT_HANDLES}
    return {h: sel.handle_point(r, h) for h in sel.HANDLES}


def resized(shape, handle, point, bounds):
    if handle in ("p0", "p1"):
        return replace(shape, **{handle: point})
    if shape.kind == "text":  # a corner scales the text, the opposite corner stays put
        r = bbox(shape)
        new = sel.resize(r, handle, point, bounds, r.w / r.h if r.h else None)
        scale = new.h / r.h if r.h else 1.0
        return replace(shape, p0=(new.x, new.y), p1=(new.x, new.y), size=max(4.0, shape.size * scale))
    r = sel.resize(bbox(shape), handle, point, bounds)
    return replace(shape, p0=(r.x, r.y), p1=(r.right, r.bottom))


def from_drag(kind, anchor, point, style):
    """A new shape dragged from anchor to point. style: dict(color, width)."""
    if kind in BOX_KINDS:
        x0, y0 = anchor
        x1, y1 = point
        return Shape(kind, (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1)), **style)
    return Shape(kind, tuple(anchor), tuple(point), **style)
