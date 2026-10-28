"""The image view: fit or zoom, pan, a checkerboard behind transparency, and the crop selection.

Mouse, as in Preview: drag on the image to select (Shift = square), drag inside the selection to move it,
drag a handle to resize it, click outside to clear it. Scroll or middle-drag pans; Ctrl+scroll or pinch zooms.
"""

import math

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk

from . import selection as sel

MIN_ZOOM, MAX_ZOOM = 0.02, 64.0
ZOOM_STOPS = [0.02, 0.05, 0.1, 0.125, 0.167, 0.25, 0.333, 0.5, 0.667, 0.75, 1.0,
              1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0]
CHECK = 8  # checkerboard square, logical px
HANDLE = 8  # selection handle size, logical px
HANDLE_HIT = 10  # how close (logical px) counts as grabbing a handle
CLICK_SLOP = 3  # a drag shorter than this (logical px) is a click
HANDLE_CURSORS = {"nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize", "sw": "nesw-resize",
                  "n": "ns-resize", "s": "ns-resize", "e": "ew-resize", "w": "ew-resize"}


def _rgba(spec):
    color = Gdk.RGBA()
    color.parse(spec)
    return color


CHECK_LIGHT, CHECK_DARK = _rgba("#ffffff"), _rgba("#d6d6d6")
SHADE = _rgba("rgba(0,0,0,0.45)")
LINE_LIGHT, LINE_DARK = _rgba("rgba(255,255,255,0.95)"), _rgba("rgba(0,0,0,0.6)")
BADGE_BG, BADGE_FG = _rgba("rgba(0,0,0,0.7)"), _rgba("#ffffff")


def texture_from_image(img):
    """Pillow RGB/RGBA → GdkTexture. Straight (non-premultiplied) alpha, matching Pillow."""
    if img.mode == "RGBA":
        fmt, bpp = Gdk.MemoryFormat.R8G8B8A8, 4
    else:
        fmt, bpp = Gdk.MemoryFormat.R8G8B8, 3
    return Gdk.MemoryTexture.new(img.width, img.height, fmt, GLib.Bytes.new(img.tobytes()), img.width * bpp)


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def _border(snapshot, x, y, w, h, color):
    outline = Gsk.RoundedRect()
    outline.init_from_rect(_rect(x, y, w, h), 0)
    snapshot.append_border(outline, [1, 1, 1, 1], [color] * 4)


class Canvas(Gtk.Widget):
    """Zoom is image pixels per device pixel, so 100% is actual size on HiDPI screens too."""

    __gtype_name__ = "GlanceCanvas"
    __gsignals__ = {
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._texture = None
        self._has_alpha = False
        self._fit = True
        self._zoom = 1.0
        self._center = (0.0, 0.0)  # image point shown at the widget's centre (manual zoom only)
        self._pointer = None
        self._pan_start = None
        self._pinch_start = None
        self.selection = None  # sel.Rect in image pixels, or None
        self.ratio_name = "free"
        self._drag = None  # the selection gesture in progress: dict(mode=…)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda _c: setattr(self, "_pointer", None))
        self.add_controller(motion)

        select = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        select.connect("drag-begin", lambda _g, x, y: self.begin_drag(x, y))
        select.connect("drag-update", self._on_select_update)
        select.connect("drag-end", lambda *_: self.end_drag())
        self.add_controller(select)

        pan = Gtk.GestureDrag(button=Gdk.BUTTON_MIDDLE)
        pan.connect("drag-begin", self._on_pan_begin)
        pan.connect("drag-update", self._on_pan_update)
        pan.connect("drag-end", self._on_pan_end)
        self.add_controller(pan)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch)
        self.add_controller(pinch)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # --- public -------------------------------------------------------------------------------

    def set_image(self, img, reset=True):
        self._texture = texture_from_image(img)
        self._has_alpha = img.mode == "RGBA"
        if reset:
            self._fit = True
        self._center = (img.width / 2, img.height / 2)
        self.set_selection(None)
        self.queue_draw()
        self.emit("zoom-changed")

    @property
    def zoom(self):
        return self._fit_zoom() if self._fit else self._zoom

    @property
    def image_size(self):
        return (self._texture.get_width(), self._texture.get_height()) if self._texture else None

    def zoom_fit(self):
        self._fit = True
        self.queue_draw()
        self.emit("zoom-changed")

    def zoom_in(self):
        current = self.zoom
        self.zoom_to(next((z for z in ZOOM_STOPS if z > current * 1.01), MAX_ZOOM))

    def zoom_out(self):
        current = self.zoom
        self.zoom_to(next((z for z in reversed(ZOOM_STOPS) if z < current / 1.01), MIN_ZOOM))

    def zoom_to(self, zoom, anchor=None):
        """Zoom keeping the image point under anchor (widget coords; default the centre) in place."""
        if not self._texture:
            return
        w, h = self.get_width(), self.get_height()
        ax, ay = anchor or (w / 2, h / 2)
        old = self._scale()
        cx, cy = self._view_center(old)
        ix, iy = cx + (ax - w / 2) / old, cy + (ay - h / 2) / old
        self._fit = False
        self._zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        new = self._scale()
        self._center = (ix - (ax - w / 2) / new, iy - (ay - h / 2) / new)
        self.queue_draw()
        self.emit("zoom-changed")

    def set_selection(self, rect):
        if rect != self.selection:
            self.selection = rect
            self.queue_draw()
            self.emit("selection-changed")

    def select_all(self):
        if self._texture:
            self.set_selection(sel.full(self.image_size))

    def set_ratio(self, name):
        """Pick a fixed ratio (selection.RATIOS key); an existing selection takes it on, centred."""
        self.ratio_name = name
        if self.selection and self._texture:
            ratio = sel.ratio_value(name, self.image_size)
            if name != "original":
                ratio = sel.orient(ratio, self.selection.w, self.selection.h)
            self.set_selection(sel.conform(self.selection, ratio))

    # --- geometry -----------------------------------------------------------------------------

    def _device_scale(self):
        native = self.get_native()
        surface = native.get_surface() if native else None
        return surface.get_scale() if surface else 1.0

    def _fit_zoom(self):
        if not self._texture or self.get_width() <= 0:
            return 1.0
        ds = self._device_scale()
        iw, ih = self.image_size
        return min(self.get_width() * ds / iw, self.get_height() * ds / ih, 1.0)

    def _scale(self):
        """Logical px per image px."""
        return self.zoom / self._device_scale()

    def _view_center(self, scale):
        iw, ih = self.image_size
        if self._fit:
            return iw / 2, ih / 2

        def clamp(c, size, view):
            visible = view / scale
            return size / 2 if size <= visible else min(max(c, visible / 2), size - visible / 2)

        return clamp(self._center[0], iw, self.get_width()), clamp(self._center[1], ih, self.get_height())

    def _layout(self):
        """(x, y, scale): the image's top-left corner in widget coords and logical px per image px."""
        s = self._scale()
        ds = self._device_scale()
        cx, cy = self._view_center(s)
        # Snap the origin to device pixels so 100% stays sharp.
        x = round((self.get_width() / 2 - cx * s) * ds) / ds
        y = round((self.get_height() / 2 - cy * s) * ds) / ds
        return x, y, s

    def to_image(self, wx, wy):
        x, y, s = self._layout()
        return (wx - x) / s, (wy - y) / s

    def to_widget(self, ix, iy):
        x, y, s = self._layout()
        return x + ix * s, y + iy * s

    def _pannable(self):
        if not self._texture or self._fit:
            return False
        s = self._scale()
        iw, ih = self.image_size
        return iw * s > self.get_width() or ih * s > self.get_height()

    def _handle_at(self, wx, wy):
        if not self.selection:
            return None
        for handle in sel.HANDLES:
            hx, hy = self.to_widget(*sel.handle_point(self.selection, handle))
            if abs(wx - hx) <= HANDLE_HIT and abs(wy - hy) <= HANDLE_HIT:
                return handle
        return None

    # --- drawing ------------------------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        return 64, 400, -1, -1

    def do_size_allocate(self, width, height, baseline):
        if self._fit:
            self.emit("zoom-changed")

    def do_snapshot(self, snapshot):
        if not self._texture:
            return
        x, y, s = self._layout()
        if not self._fit:
            self._center = self._view_center(s)
        iw, ih = self.image_size
        bounds = _rect(x, y, iw * s, ih * s)
        if self._has_alpha:
            self._checkerboard(snapshot, x, y, bounds)
        zoom = s * self._device_scale()
        filt = (Gsk.ScalingFilter.NEAREST if zoom >= 2 else
                Gsk.ScalingFilter.LINEAR if zoom >= 1 else Gsk.ScalingFilter.TRILINEAR)
        snapshot.append_scaled_texture(self._texture, filt, bounds)
        if self.selection:
            self._draw_selection(snapshot, x, y, s)

    def _checkerboard(self, snapshot, x, y, bounds):
        tile = _rect(x, y, CHECK * 2, CHECK * 2)
        snapshot.push_repeat(bounds, tile)
        snapshot.append_color(CHECK_LIGHT, tile)
        snapshot.append_color(CHECK_DARK, _rect(x, y, CHECK, CHECK))
        snapshot.append_color(CHECK_DARK, _rect(x + CHECK, y + CHECK, CHECK, CHECK))
        snapshot.pop()

    def _draw_selection(self, snapshot, x, y, s):
        iw, ih = self.image_size
        # Draw the whole-pixel box that Crop will use, so what you see is what you get.
        left, top, right, bottom = self.selection.box(self.image_size)
        x0, y0, x1, y1 = x + left * s, y + top * s, x + right * s, y + bottom * s
        x_end, y_end = x + iw * s, y + ih * s
        for shade in ((x, y, iw * s, y0 - y), (x, y1, iw * s, y_end - y1),
                      (x, y0, x0 - x, y1 - y0), (x1, y0, x_end - x1, y1 - y0)):
            if shade[2] > 0 and shade[3] > 0:
                snapshot.append_color(SHADE, _rect(*shade))
        _border(snapshot, x0 - 1, y0 - 1, x1 - x0 + 2, y1 - y0 + 2, LINE_DARK)
        _border(snapshot, x0, y0, x1 - x0, y1 - y0, LINE_LIGHT)
        shown = sel.Rect(x0, y0, x1 - x0, y1 - y0)
        for handle in sel.HANDLES:
            hx, hy = sel.handle_point(shown, handle)
            snapshot.append_color(LINE_LIGHT, _rect(hx - HANDLE / 2, hy - HANDLE / 2, HANDLE, HANDLE))
            _border(snapshot, hx - HANDLE / 2, hy - HANDLE / 2, HANDLE, HANDLE, LINE_DARK)
        if self._drag:
            self._draw_badge(snapshot, f"{right - left} × {bottom - top}", x1, y1)

    def _draw_badge(self, snapshot, text, x, y):
        layout = self.create_pango_layout(text)
        tw, th = layout.get_pixel_size()
        pad = 4
        bx = min(x + 6, self.get_width() - tw - 2 * pad - 2)
        by = min(y + 6, self.get_height() - th - 2 * pad - 2)
        snapshot.append_color(BADGE_BG, _rect(bx, by, tw + 2 * pad, th + 2 * pad))
        snapshot.save()
        point = Graphene.Point()
        point.init(bx + pad, by + pad)
        snapshot.translate(point)
        snapshot.append_layout(layout, BADGE_FG)
        snapshot.restore()

    # --- selection gesture (public so the headless smoke test can drive it) -----------------

    def begin_drag(self, wx, wy):
        if not self._texture:
            return
        self.grab_focus()
        point = self.to_image(wx, wy)
        handle = self._handle_at(wx, wy)
        if handle:
            ratio = sel.ratio_value(self.ratio_name, self.image_size)
            if self.ratio_name != "original":
                ratio = sel.orient(ratio, self.selection.w, self.selection.h)
            self._drag = dict(mode="resize", handle=handle, rect=self.selection, ratio=ratio)
        elif self.selection and self.selection.contains(*point):
            self._drag = dict(mode="move", rect=self.selection, start=point)
        else:
            self._drag = dict(mode="new", anchor=point, moved=False)
        self._drag["origin"] = (wx, wy)

    def update_drag(self, wx, wy, shift=False):
        drag = self._drag
        if not drag:
            return
        point = self.to_image(wx, wy)
        bounds = self.image_size
        if drag["mode"] == "new":
            ox, oy = drag["origin"]
            if not drag["moved"] and max(abs(wx - ox), abs(wy - oy)) < CLICK_SLOP:
                return
            drag["moved"] = True
            ratio = sel.ratio_value(self.ratio_name, bounds) or (1.0 if shift else None)
            if self.ratio_name != "original":
                ratio = sel.orient(ratio, abs(point[0] - drag["anchor"][0]), abs(point[1] - drag["anchor"][1]))
            self.set_selection(sel.from_drag(drag["anchor"], point, bounds, ratio))
        elif drag["mode"] == "move":
            sx, sy = drag["start"]
            self.set_selection(sel.move(drag["rect"], point[0] - sx, point[1] - sy, bounds))
        else:
            ratio = drag["ratio"] or (1.0 if shift and len(drag["handle"]) == 2 else None)
            self.set_selection(sel.resize(drag["rect"], drag["handle"], point, bounds, ratio))

    def end_drag(self):
        drag, self._drag = self._drag, None
        if drag and drag["mode"] == "new" and not drag["moved"]:
            self.set_selection(None)  # a click clears the selection, as in Preview
        else:
            self.queue_draw()  # drop the size badge

    def _on_select_update(self, gesture, dx, dy):
        _ok, sx, sy = gesture.get_start_point()
        shift = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        self.update_drag(sx + dx, sy + dy, shift)

    # --- other input --------------------------------------------------------------------------

    def _on_motion(self, _controller, wx, wy):
        self._pointer = (wx, wy)
        if self._drag or self._pan_start or not self._texture:
            return
        handle = self._handle_at(wx, wy)
        ix, iy = self.to_image(wx, wy)
        iw, ih = self.image_size
        if handle:
            name = HANDLE_CURSORS[handle]
        elif self.selection and self.selection.contains(ix, iy):
            name = "move"
        elif 0 <= ix <= iw and 0 <= iy <= ih:
            name = "crosshair"
        else:
            name = None
        self.set_cursor_from_name(name)

    def _on_key(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_Escape and self.selection:
            self.set_selection(None)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.selection:
            self.activate_action("win.crop", None)
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and not state & Gdk.ModifierType.MODIFIER_MASK:
            self.activate_action("win.previous" if keyval == Gdk.KEY_Left else "win.next", None)
            return True
        return False

    def _on_scroll(self, controller, dx, dy):
        if not self._texture:
            return False
        wheel = controller.get_unit() == Gdk.ScrollUnit.WHEEL
        if controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            self.zoom_to(self.zoom * math.exp(-dy * (0.2 if wheel else 0.01)), self._pointer)
            return True
        if not self._pannable():
            return False
        step = 40 if wheel else 1
        s = self._scale()
        cx, cy = self._view_center(s)
        self._center = (cx + dx * step / s, cy + dy * step / s)
        self.queue_draw()
        return True

    def _on_pan_begin(self, gesture, _x, _y):
        if not self._pannable():
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self._pan_start = self._view_center(self._scale())
        self.set_cursor_from_name("grabbing")

    def _on_pan_update(self, _gesture, dx, dy):
        if self._pan_start:
            s = self._scale()
            self._center = (self._pan_start[0] - dx / s, self._pan_start[1] - dy / s)
            self.queue_draw()

    def _on_pan_end(self, *_args):
        self._pan_start = None
        self.set_cursor(None)

    def _on_pinch_begin(self, _gesture, _sequence):
        self._pinch_start = self.zoom

    def _on_pinch(self, gesture, scale):
        if self._pinch_start is None:
            return
        ok, x, y = gesture.get_bounding_box_center()
        self.zoom_to(self._pinch_start * scale, (x, y) if ok else None)
