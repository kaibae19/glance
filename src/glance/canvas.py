"""The image view: fit or zoom, pan, and a checkerboard behind transparent areas."""

import math

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk

MIN_ZOOM, MAX_ZOOM = 0.02, 64.0
ZOOM_STOPS = [0.02, 0.05, 0.1, 0.125, 0.167, 0.25, 0.333, 0.5, 0.667, 0.75, 1.0,
              1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0]
CHECK = 8  # checkerboard square, logical px


def _rgba(spec):
    color = Gdk.RGBA()
    color.parse(spec)
    return color


CHECK_LIGHT, CHECK_DARK = _rgba("#ffffff"), _rgba("#d6d6d6")


def texture_from_image(img):
    """Pillow RGB/RGBA → GdkTexture. Straight (non-premultiplied) alpha, matching Pillow."""
    if img.mode == "RGBA":
        fmt, bpp = Gdk.MemoryFormat.R8G8B8A8, 4
    else:
        fmt, bpp = Gdk.MemoryFormat.R8G8B8, 3
    return Gdk.MemoryTexture.new(img.width, img.height, fmt, GLib.Bytes.new(img.tobytes()), img.width * bpp)


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


class Canvas(Gtk.Widget):
    """Zoom is image pixels per device pixel, so 100% is actual size on HiDPI screens too."""

    __gtype_name__ = "GlanceCanvas"
    __gsignals__ = {"zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._texture = None
        self._has_alpha = False
        self._fit = True
        self._zoom = 1.0
        self._center = (0.0, 0.0)  # image point shown at the widget's centre (manual zoom only)
        self._pointer = None
        self._drag_start = None
        self._pinch_start = None
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: setattr(self, "_pointer", (x, y)))
        motion.connect("leave", lambda _c: setattr(self, "_pointer", None))
        self.add_controller(motion)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch)
        self.add_controller(pinch)

    # --- public -------------------------------------------------------------------------------

    def set_image(self, img, reset=True):
        self._texture = texture_from_image(img)
        self._has_alpha = img.mode == "RGBA"
        if reset:
            self._fit = True
        self._center = (img.width / 2, img.height / 2)
        self.queue_draw()
        self.emit("zoom-changed")

    @property
    def zoom(self):
        return self._fit_zoom() if self._fit else self._zoom

    @property
    def fitted(self):
        return self._fit

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

    # --- geometry -----------------------------------------------------------------------------

    def _device_scale(self):
        native = self.get_native()
        surface = native.get_surface() if native else None
        return surface.get_scale() if surface else 1.0

    def _fit_zoom(self):
        if not self._texture or self.get_width() <= 0:
            return 1.0
        ds = self._device_scale()
        iw, ih = self._texture.get_width(), self._texture.get_height()
        return min(self.get_width() * ds / iw, self.get_height() * ds / ih, 1.0)

    def _scale(self):
        """Logical px per image px."""
        return self.zoom / self._device_scale()

    def _view_center(self, scale):
        iw, ih = self._texture.get_width(), self._texture.get_height()
        if self._fit:
            return iw / 2, ih / 2

        def clamp(c, size, view):
            visible = view / scale
            return size / 2 if size <= visible else min(max(c, visible / 2), size - visible / 2)

        return clamp(self._center[0], iw, self.get_width()), clamp(self._center[1], ih, self.get_height())

    def _pannable(self):
        if not self._texture or self._fit:
            return False
        s = self._scale()
        return (self._texture.get_width() * s > self.get_width()
                or self._texture.get_height() * s > self.get_height())

    # --- drawing ------------------------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        return 64, 400, -1, -1

    def do_size_allocate(self, width, height, baseline):
        if self._fit:
            self.emit("zoom-changed")

    def do_snapshot(self, snapshot):
        if not self._texture:
            return
        s = self._scale()
        ds = self._device_scale()
        cx, cy = self._view_center(s)
        if not self._fit:
            self._center = (cx, cy)
        iw, ih = self._texture.get_width(), self._texture.get_height()
        # Snap the origin to device pixels so 100% stays sharp.
        x = round((self.get_width() / 2 - cx * s) * ds) / ds
        y = round((self.get_height() / 2 - cy * s) * ds) / ds
        bounds = _rect(x, y, iw * s, ih * s)
        if self._has_alpha:
            self._checkerboard(snapshot, x, y, bounds)
        zoom = s * ds
        filt = (Gsk.ScalingFilter.NEAREST if zoom >= 2 else
                Gsk.ScalingFilter.LINEAR if zoom >= 1 else Gsk.ScalingFilter.TRILINEAR)
        snapshot.append_scaled_texture(self._texture, filt, bounds)

    def _checkerboard(self, snapshot, x, y, bounds):
        tile = _rect(x, y, CHECK * 2, CHECK * 2)
        snapshot.push_repeat(bounds, tile)
        snapshot.append_color(CHECK_LIGHT, tile)
        snapshot.append_color(CHECK_DARK, _rect(x, y, CHECK, CHECK))
        snapshot.append_color(CHECK_DARK, _rect(x + CHECK, y + CHECK, CHECK, CHECK))
        snapshot.pop()

    # --- input --------------------------------------------------------------------------------

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

    def _on_drag_begin(self, gesture, _x, _y):
        if not self._pannable():
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self._drag_start = self._view_center(self._scale())
        self.set_cursor_from_name("grabbing")

    def _on_drag_update(self, _gesture, dx, dy):
        if self._drag_start:
            s = self._scale()
            self._center = (self._drag_start[0] - dx / s, self._drag_start[1] - dy / s)
            self.queue_draw()

    def _on_drag_end(self, *_args):
        self._drag_start = None
        self.set_cursor(None)

    def _on_pinch_begin(self, gesture, _sequence):
        self._pinch_start = self.zoom

    def _on_pinch(self, gesture, scale):
        if self._pinch_start is None:
            return
        ok, x, y = gesture.get_bounding_box_center()
        self.zoom_to(self._pinch_start * scale, (x, y) if ok else None)
