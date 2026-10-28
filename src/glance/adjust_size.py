"""Tools → Adjust Size, after Preview's sheet. The arithmetic lives in sizing.py."""

import threading

from gi.repository import Adw, Gdk, GLib, Gtk

from . import imageio
from .ops import Resize
from .sizing import DEFAULT_DPI, METHODS, PHYSICAL, PRESETS, UNITS, SizeModel

ESTIMATE_DELAY_MS = 250


@Gtk.Template(resource_path="/io/github/kaibae19/Glance/adjust_size.ui")
class AdjustSizeDialog(Adw.Dialog):
    __gtype_name__ = "GlanceAdjustSizeDialog"

    resize_button = Gtk.Template.Child()
    fit_row = Gtk.Template.Child()
    width_row = Gtk.Template.Child()
    height_row = Gtk.Template.Child()
    unit_row = Gtk.Template.Child()
    proportional_row = Gtk.Template.Child()
    resolution_row = Gtk.Template.Child()
    resample_row = Gtk.Template.Child()
    method_row = Gtk.Template.Child()
    result_row = Gtk.Template.Child()

    def __init__(self, document, on_resize):
        super().__init__()
        self._document = document
        self._on_resize = on_resize
        w, h = document.size
        self.model = SizeModel(w, h, document.dpi[0] if document.dpi else DEFAULT_DPI)
        self._syncing = False
        self._estimate_seq = 0
        self._estimate_timer = 0

        self.fit_row.set_model(Gtk.StringList.new(["Custom"] + [f"{pw} × {ph}" for pw, ph in PRESETS]))
        self.unit_row.set_model(Gtk.StringList.new([u.capitalize() for u in UNITS]))
        self.method_row.set_model(Gtk.StringList.new([label for label, _ in METHODS]))

        self.fit_row.connect("notify::selected", self._on_fit)
        for axis, row in (("width", self.width_row), ("height", self.height_row)):
            row.connect("changed", self._on_dimension, axis)  # live while typing
            row.connect("notify::value", self._on_dimension, axis)  # +/− buttons and arrows
        self.resolution_row.connect("changed", self._on_resolution)
        self.resolution_row.connect("notify::value", self._on_resolution)
        self.unit_row.connect("notify::selected", lambda *_: self._sync())
        self.proportional_row.connect("notify::active", self._on_toggle, self.model.set_proportional)
        self.resample_row.connect("notify::active", self._on_toggle, self.model.set_resample)
        self.method_row.connect("notify::selected", lambda *_: self._update_result())

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("closed", self._on_closed)

        self._sync()
        GLib.idle_add(self._select_width)

    # --- model ↔ rows -------------------------------------------------------------------------

    @property
    def unit(self):
        return UNITS[self.unit_row.get_selected()]

    def _sync(self, skip=None):
        """Push the model into the rows, leaving alone the row the user is typing in."""
        self._syncing = True
        unit, model = self.unit, self.model
        for axis, row in (("width", self.width_row), ("height", self.height_row)):
            row.set_digits(0 if unit == "pixels" else 2)
            if row is not skip:
                row.set_value(model.get(axis, unit))
            row.set_sensitive(model.resample or unit in PHYSICAL)
        if skip is not self.resolution_row:
            self.resolution_row.set_value(model.resolution)
        self.proportional_row.set_active(model.proportional)
        self.proportional_row.set_sensitive(model.resample)
        self.resample_row.set_active(model.resample)
        self.method_row.set_sensitive(model.resample)
        if skip is not self.fit_row:
            self.fit_row.set_selected(0)  # "Custom" once edited by hand, as in Preview
        self.resize_button.set_sensitive(model.changed)
        self._syncing = False
        self._update_result()

    @staticmethod
    def _number(row):
        try:
            return float(row.get_text().replace(",", "."))
        except ValueError:
            return None

    def _on_dimension(self, row, *args):
        if self._syncing:
            return
        value = self._number(row)
        if value is not None:
            self.model.set(args[-1], value, self.unit)
            self._sync(skip=row)

    def _on_resolution(self, row, *_args):
        if self._syncing:
            return
        value = self._number(row)
        if value is not None:
            self.model.set_resolution(value, self.unit)
            self._sync(skip=row)

    def _on_toggle(self, row, _pspec, setter):
        if not self._syncing:
            setter(row.get_active())
            self._sync()

    def _on_fit(self, row, _pspec):
        if self._syncing or row.get_selected() == 0:
            return
        self.model.fit_into(*PRESETS[row.get_selected() - 1])
        self._sync(skip=row)

    def _select_width(self):
        self.width_row.grab_focus()
        self.width_row.select_region(0, -1)
        return False

    # --- result and estimate ------------------------------------------------------------------

    def _op(self):
        if not self.model.changed:
            return None
        dpi = (self.model.resolution,) * 2 if self.model.resolution_changed else None
        return Resize(self.model.size(), METHODS[self.method_row.get_selected()][1], dpi)

    def _update_result(self):
        w, h = self.model.size()
        self.result_row.set_subtitle(f"{w} × {h} px")
        self._estimate_seq += 1  # an estimate still running is for the old settings
        if self._estimate_timer:
            GLib.source_remove(self._estimate_timer)
        self._estimate_timer = GLib.timeout_add(ESTIMATE_DELAY_MS, self._start_estimate)

    def _start_estimate(self):
        self._estimate_timer = 0
        self._estimate_seq += 1
        seq, op, doc = self._estimate_seq, self._op(), self._document
        image, dpi = doc.image, (op.dpi if op and op.dpi else doc.dpi)

        def work():
            try:
                size = imageio.encoded_size(op.apply(image) if op else image, doc.info, dpi=dpi)
            except Exception:  # an estimate is optional
                size = None
            GLib.idle_add(self._show_estimate, seq, size)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _show_estimate(self, seq, size):
        if seq == self._estimate_seq and size:
            w, h = self.model.size()
            was = imageio.format_size(self._document.info.file_size)
            self.result_row.set_subtitle(f"{w} × {h} px · about {imageio.format_size(size)} (was {was})")
        return False

    # --- closing ------------------------------------------------------------------------------

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.on_apply()
            return True
        return False

    @Gtk.Template.Callback()
    def on_apply(self, *_args):
        op = self._op()
        self.close()
        if op:
            self._on_resize(op)

    @Gtk.Template.Callback()
    def on_cancel(self, *_args):
        self.close()

    def _on_closed(self, *_args):
        if self._estimate_timer:
            GLib.source_remove(self._estimate_timer)
            self._estimate_timer = 0
        self._estimate_seq += 1  # drop any estimate still running
