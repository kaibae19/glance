import os
import threading

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import imageio, shortcuts
from .adjust_size import AdjustSizeDialog
from .export import ExportDialog
from .canvas import Canvas  # noqa: F401  registers GlanceCanvas for the template
from .document import AnimatedImageError, Document
from .ops import Crop, Flip, Rotate

DOC_ACTIONS = ["save", "save-as", "export", "adjust-size", "crop", "select-all", "zoom-in", "zoom-out", "zoom-actual", "zoom-fit", "rotate-left",
               "rotate-right", "flip-horizontal", "flip-vertical", "previous", "next", "info"]


@Gtk.Template(resource_path="/io/github/kaibae19/Glance/window.ui")
class GlanceWindow(Adw.ApplicationWindow):
    __gtype_name__ = "GlanceWindow"

    toast_overlay = Gtk.Template.Child()
    window_title = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    canvas = Gtk.Template.Child()
    info_button = Gtk.Template.Child()
    info_grid = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.document = None
        self._siblings = []
        self._load_seq = 0
        self._overwrite_ok = False  # the user confirmed saving over this document's original
        self._closing = False
        self._add_actions()
        shortcuts.install_window(self)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)
        self.canvas.connect("zoom-changed", lambda *_: self._update_title())
        self.canvas.connect("selection-changed", lambda *_: self._update_state())
        self.connect("close-request", self._on_close_request)
        self._update_state()

    # --- actions ------------------------------------------------------------------------------

    def _add_actions(self):
        handlers = {
            "open": self.on_open,
            "save": self.on_save,
            "save-as": self.on_save_as,
            "export": self.on_export,
            "adjust-size": self.on_adjust_size,
            "crop": self.on_crop,
            "select-all": self.canvas.select_all,
            "close": self.close,
            "undo": lambda: self.document and self.document.undo(),
            "redo": lambda: self.document and self.document.redo(),
            "zoom-in": self.canvas.zoom_in,
            "zoom-out": self.canvas.zoom_out,
            "zoom-actual": lambda: self.canvas.zoom_to(1.0),
            "zoom-fit": self.canvas.zoom_fit,
            "rotate-left": lambda: self._apply(Rotate(-1)),
            "rotate-right": lambda: self._apply(Rotate(1)),
            "flip-horizontal": lambda: self._apply(Flip(horizontal=True)),
            "flip-vertical": lambda: self._apply(Flip(horizontal=False)),
            "previous": lambda: self._step(-1),
            "next": lambda: self._step(1),
            "fullscreen": lambda: self.unfullscreen() if self.is_fullscreen() else self.fullscreen(),
            "info": self.info_button.popup,
        }
        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            self.add_action(action)

        ratio = Gio.SimpleAction.new_stateful("selection-ratio", GLib.VariantType.new("s"),
                                              GLib.Variant("s", "free"))
        ratio.connect("change-state", self._on_ratio)
        self.add_action(ratio)

    def _on_ratio(self, action, value):
        action.set_state(value)
        self.canvas.set_ratio(value.get_string())

    def _enable(self, name, enabled):
        self.lookup_action(name).set_enabled(enabled)

    def _update_state(self):
        doc = self.document
        for name in DOC_ACTIONS:
            self._enable(name, doc is not None)
        self._enable("save", bool(doc and doc.dirty))
        self._enable("crop", bool(doc and self.canvas.selection))
        self._enable("undo", bool(doc and doc.can_undo))
        self._enable("redo", bool(doc and doc.can_redo))
        index = self._sibling_index()
        self._enable("previous", index is not None and index > 0)
        self._enable("next", index is not None and index < len(self._siblings) - 1)
        self.info_button.set_sensitive(doc is not None)
        self._update_title()

    def _update_title(self):
        doc = self.document
        if not doc:
            self.set_title("Glance")
            self.window_title.set_title("Glance")
            self.window_title.set_subtitle("")
            return
        name = os.path.basename(doc.path)
        title = f"{name} — Edited" if doc.dirty else name  # Preview's wording
        w, h = doc.size
        self.set_title(title)
        self.window_title.set_title(title)
        subtitle = f"{w} × {h} px · {round(self.canvas.zoom * 100)}%"
        if self.canvas.selection:
            sw, sh = self.canvas.selection.pixel_size(doc.size)
            subtitle += f" · selection {sw} × {sh}"
        self.window_title.set_subtitle(subtitle)

    def toast(self, text):
        self.toast_overlay.add_toast(Adw.Toast(title=text))

    # --- opening ------------------------------------------------------------------------------

    def on_open(self):
        images = Gtk.FileFilter(name="Images")
        for ext in sorted(imageio.readable_extensions()):
            images.add_suffix(ext.lstrip("."))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog = Gtk.FileDialog(title="Open Image", filters=filters, default_filter=images)
        if self.document:
            dialog.set_initial_folder(Gio.File.new_for_path(os.path.dirname(self.document.path)))
        dialog.open(self, None, self._on_open_chosen)

    def _on_open_chosen(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        self.open_file(gfile)

    def _on_drop(self, _target, value, _x, _y):
        files = value.get_files()
        if files:
            self.open_file(files[0])
        return True

    def open_file(self, gfile):
        path = gfile.get_path()
        if path is None:
            self.toast("Glance can only open local files")
            return
        self._confirm_discard(lambda: self._load(path))

    def _load(self, path):
        self._load_seq += 1
        seq = self._load_seq

        def work():
            try:
                doc, error = Document.open(path), None
            except Exception as e:  # Pillow raises many types for bad files
                doc, error = None, e
            GLib.idle_add(self._on_loaded, seq, path, doc, error)

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, seq, path, doc, error):
        if seq != self._load_seq:
            return False  # a newer load superseded this one
        if error:
            self.toast(f"Couldn't open {os.path.basename(path)}: {error}")
            return False
        self.document = doc
        self._overwrite_ok = False
        doc.connect(self._on_document_changed)
        self._siblings = imageio.sibling_images(path)
        self.canvas.set_image(doc.image)
        self.stack.set_visible_child_name("image")
        self.canvas.grab_focus()
        self._fill_info()
        self._update_state()
        return False

    def _sibling_index(self):
        if not self.document or self.document.path not in self._siblings:
            return None
        return self._siblings.index(self.document.path)

    def _step(self, delta):
        index = self._sibling_index()
        if index is None:
            return
        target = index + delta
        if 0 <= target < len(self._siblings):
            self._confirm_discard(lambda: self._load(self._siblings[target]))
        else:
            self.error_bell()

    # --- editing ------------------------------------------------------------------------------

    def _apply(self, op):
        if self.document:
            self.document.apply(op)

    def on_crop(self):
        doc, rect = self.document, self.canvas.selection
        if not doc or not rect:
            return
        box = rect.box(doc.size)
        if box == (0, 0, *doc.size):
            self.canvas.set_selection(None)  # cropping to everything changes nothing
        else:
            doc.apply(Crop(box))

    def on_adjust_size(self):
        if self.document:
            AdjustSizeDialog(self.document, self._apply).present(self)

    def _on_document_changed(self, doc):
        self.canvas.set_image(doc.image, reset=False)
        self._fill_info()
        self._update_state()

    def _fill_info(self):
        while child := self.info_grid.get_first_child():
            self.info_grid.remove(child)
        doc = self.document
        if not doc:
            return
        for row, (label, value) in enumerate(imageio.describe(doc.path, doc.image, doc.info, doc.dpi)):
            key = Gtk.Label(label=label, xalign=1, css_classes=["dim-label"])
            val = Gtk.Label(label=value, xalign=0, selectable=True, wrap=True, max_width_chars=40)
            self.info_grid.attach(key, 0, row, 1, 1)
            self.info_grid.attach(val, 1, row, 1, 1)

    # --- saving -------------------------------------------------------------------------------
    # Save writes over the original, asking once per document first; Save As picks a new file and
    # format (from the extension). Nothing is written without one of the two (no autosave).

    def on_save(self, then=None):
        doc = self.document
        if not doc or not doc.dirty:
            return
        if self._overwrite_ok:
            self._save_to(None, then)
            return
        dialog = Adw.AlertDialog(
            heading=f"Replace “{os.path.basename(doc.path)}”?",
            body="Saving writes your edits over the original file. Use Save As to keep the original.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save-as", "Save As…")
        dialog.add_response("replace", "Replace")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("replace")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response == "replace":
                self._overwrite_ok = True
                self._save_to(None, then)
            elif response == "save-as":
                self.on_save_as(then)

        dialog.connect("response", on_response)
        dialog.present(self)

    def on_save_as(self, then=None):
        doc = self.document
        if not doc:
            return
        dialog = Gtk.FileDialog(title="Save As", initial_name=os.path.basename(doc.path),
                                initial_folder=Gio.File.new_for_path(os.path.dirname(doc.path)))

        def on_chosen(_dialog, result):
            try:
                path = dialog.save_finish(result).get_path()
            except GLib.Error:
                return
            if imageio.format_for_path(path) is None:
                self.toast(f"Glance can't save “{os.path.splitext(path)[1] or 'no extension'}” files")
                return
            if path != doc.path:
                self._overwrite_ok = True  # the file chooser already confirmed any replacement
            self._save_to(path, then)

        dialog.save(self, None, on_chosen)

    def _save_to(self, path, then):
        try:
            self.document.save(path)
        except AnimatedImageError:
            self.toast("Glance can't save animated images yet; nothing was written")
            return
        except Exception as e:
            self.toast(f"Couldn't save: {e}")
            return
        self._siblings = imageio.sibling_images(self.document.path)
        self._update_state()
        if then:
            then()

    # --- export -------------------------------------------------------------------------------

    def on_export(self):
        if self.document:
            app = self.get_application()
            ExportDialog(self.document, getattr(app, "export_defaults", None), self._choose_export_path).present(self)

    def _choose_export_path(self, options):
        self.get_application().export_defaults = options  # remembered for this run (GSettings later)
        doc = self.document
        fmt = next(f for f in imageio.export_formats() if f.name == options.format)
        stem = os.path.splitext(os.path.basename(doc.path))[0]
        dialog = Gtk.FileDialog(title="Export", initial_name=stem + fmt.extension,
                                initial_folder=Gio.File.new_for_path(os.path.dirname(doc.path)))

        def on_chosen(_dialog, result):
            try:
                path = dialog.save_finish(result).get_path()
            except GLib.Error:
                return
            if imageio.format_for_path(path) != options.format:
                # The format picked on the sheet wins; the chooser only confirmed the name it was given.
                path = os.path.splitext(path)[0] + fmt.extension
                if os.path.exists(path):
                    self._confirm_replace(path, lambda: self._export(path, options))
                    return
            self._export(path, options)

        dialog.save(self, None, on_chosen)

    def _confirm_replace(self, path, then):
        dialog = Adw.AlertDialog(heading=f"Replace “{os.path.basename(path)}”?",
                                 body="A file with that name already exists in this folder.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("replace", "Replace")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: then() if r == "replace" else None)
        dialog.present(self)

    def _export(self, path, options):
        doc = self.document

        def work():
            try:
                doc.export(path, options)
                error = None
            except Exception as e:
                error = e
            GLib.idle_add(self._exported, path, error)

        threading.Thread(target=work, daemon=True).start()

    def _exported(self, path, error):
        if error:
            self.toast(f"Couldn't export: {error}")
        else:
            self.toast(f"Exported “{os.path.basename(path)}”")
            if self.document and os.path.dirname(path) == os.path.dirname(self.document.path):
                self._siblings = imageio.sibling_images(self.document.path)
                self._update_state()
        return False

    def _confirm_discard(self, then):
        """Run then() now, or after the user saves or discards unsaved edits."""
        doc = self.document
        if not doc or not doc.dirty:
            then()
            return
        dialog = Adw.AlertDialog(heading=f"Save changes to “{os.path.basename(doc.path)}”?",
                                 body="Your edits will be lost if you don't save them.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Don't Save")
        dialog.add_response("save", "Save…")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response == "discard":
                then()
            elif response == "save":
                self.on_save(then)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_close_request(self, _window):
        if self._closing or not (self.document and self.document.dirty):
            return False

        def close():
            self._closing = True
            self.close()

        self._confirm_discard(close)
        return True
