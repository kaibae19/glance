# SPDX-License-Identifier: GPL-3.0-or-later
"""File → Export, after Preview: pick format and options here, then the file name in the file chooser.

Export writes a copy; the document keeps its own file and its unsaved state.
"""

from gi.repository import Adw, Gdk, Gtk

from . import imageio
from .estimate import Estimator
from .imageio import ExportOptions


def _rgba(rgb):
    color = Gdk.RGBA()
    color.red, color.green, color.blue = (c / 255 for c in rgb)
    color.alpha = 1.0
    return color


@Gtk.Template(resource_path="/io/github/kaibae19/Glance/export.ui")
class ExportDialog(Adw.Dialog):
    __gtype_name__ = "GlanceExportDialog"

    export_button = Gtk.Template.Child()
    format_row = Gtk.Template.Child()
    note_row = Gtk.Template.Child()
    quality_row = Gtk.Template.Child()
    quality_scale = Gtk.Template.Child()
    lossless_row = Gtk.Template.Child()
    alpha_row = Gtk.Template.Child()
    background_row = Gtk.Template.Child()
    background_button = Gtk.Template.Child()
    strip_row = Gtk.Template.Child()
    result_row = Gtk.Template.Child()

    def __init__(self, document, defaults, on_export):
        """defaults: the ExportOptions used last (or None); on_export(options) runs on Export…"""
        super().__init__()
        self._document = document
        self._on_export = on_export
        self._formats = imageio.export_formats()
        self._has_alpha = document.image.mode == "RGBA"
        self._estimator = Estimator(self._show_estimate)

        self.format_row.set_model(Gtk.StringList.new([f.label for f in self._formats]))
        names = [f.name for f in self._formats]
        initial = defaults.format if defaults and defaults.format in names else (
            document.info.format if document.info and document.info.format in names else "PNG")
        self.format_row.set_selected(names.index(initial))
        if defaults:
            self.quality_scale.set_value(defaults.quality)
            self.lossless_row.set_active(defaults.lossless)
            self.alpha_row.set_active(defaults.keep_alpha)
            self.background_button.set_rgba(_rgba(defaults.background))
            self.strip_row.set_active(defaults.strip_metadata)
        else:
            self.background_button.set_rgba(_rgba((255, 255, 255)))
        has_exif = bool(document.info and document.info.exif)
        self.strip_row.set_subtitle("Removes camera, place and dates (EXIF); keeps the colour profile"
                                    if has_exif else "This image has no EXIF metadata")
        self.strip_row.set_sensitive(has_exif)

        self.format_row.connect("notify::selected", lambda *_: self._sync())
        self.quality_scale.connect("value-changed", lambda *_: self._sync())
        for row in (self.lossless_row, self.alpha_row, self.strip_row):
            row.connect("notify::active", lambda *_: self._sync())
        self.background_button.connect("notify::rgba", lambda *_: self._sync())
        self.connect("closed", lambda *_: self._estimator.cancel())
        self._sync()

    @property
    def format(self):
        return self._formats[self.format_row.get_selected()]

    def options(self):
        color = self.background_button.get_rgba()
        return ExportOptions(
            format=self.format.name,
            quality=int(self.quality_scale.get_value()),
            lossless=self.lossless_row.get_active() and self.format.name == "WEBP",
            keep_alpha=self.alpha_row.get_active() and self.format.alpha,
            background=tuple(round(c * 255) for c in (color.red, color.green, color.blue)),
            strip_metadata=self.strip_row.get_active() and self.strip_row.get_sensitive(),
        )

    def _sync(self):
        fmt, opts = self.format, self.options()
        self.lossless_row.set_visible(fmt.name == "WEBP")
        self.quality_row.set_visible(fmt.lossy and not opts.lossless)
        self.alpha_row.set_visible(self._has_alpha and fmt.alpha)
        flattens = self._has_alpha and not opts.keep_alpha
        self.background_row.set_visible(flattens)
        self.background_row.set_subtitle(
            f"{fmt.label} can't store transparency; transparent areas get this colour" if not fmt.alpha
            else "Transparent areas get this colour")
        notes = [fmt.note] if fmt.note else []
        if self._document.info and self._document.info.animated:
            notes.append("Only the first frame is exported")
        self.note_row.set_visible(bool(notes))
        self.note_row.set_subtitle("; ".join(notes))

        self.result_row.set_subtitle(f"{fmt.label} · estimating…")
        doc = self._document
        image, info, dpi = doc.image, doc.info, doc.dpi
        self._estimator.schedule(lambda: imageio.encoded_size(image, info, dpi=dpi, options=opts))

    def _show_estimate(self, size):
        self.result_row.set_subtitle(f"{self.format.label} · about {imageio.format_size(size)}")

    @Gtk.Template.Callback()
    def on_export(self, *_args):
        options = self.options()
        self.close()
        self._on_export(options)

    @Gtk.Template.Callback()
    def on_cancel(self, *_args):
        self.close()
