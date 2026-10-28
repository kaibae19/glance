# SPDX-License-Identifier: GPL-3.0-or-later
import os
import threading

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import imageio, markup, pdfdoc, settings, shortcuts
from .adjust_size import AdjustSizeDialog
from .export import ExportDialog
from .canvas import Canvas  # noqa: F401  registers GlanceCanvas for the template
from .document import AnimatedImageError, Document
from .ops import Crop, Flip, Rotate
from .pdfview import PAGE_GAP, THUMB_WIDTH, PdfView

# Fitting the window to a newly opened image, as Preview does: at most this much of the monitor (room for
# GNOME's top bar and dock), and at least big enough for the header bar's buttons.
FIT_SCREEN_W, FIT_SCREEN_H = 0.9, 0.85
FIT_MIN_W, FIT_MIN_H = 520, 360

DOC_ACTIONS = ["save", "save-as", "export", "markup", "markup-tool", "markup-color", "markup-weight",
               "adjust-size", "crop", "select-all", "zoom-in", "zoom-out", "zoom-actual", "zoom-fit", "rotate-left",
               "rotate-right", "flip-horizontal", "flip-vertical", "previous", "next", "info",
               "insert-pages", "delete-pages"]
# Image tools that don't apply to a PDF (yet): off while a PDF is open.
IMAGE_ONLY = ["export", "markup", "markup-tool", "markup-color", "markup-weight", "adjust-size", "crop",
              "flip-horizontal", "flip-vertical"]
PDF_ONLY = ["insert-pages", "delete-pages"]


@Gtk.Template(resource_path="/io/github/kaibae19/Glance/window.ui")
class GlanceWindow(Adw.ApplicationWindow):
    __gtype_name__ = "GlanceWindow"

    toast_overlay = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    window_title = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    canvas = Gtk.Template.Child()
    info_button = Gtk.Template.Child()
    info_grid = Gtk.Template.Child()
    markup_bar = Gtk.Template.Child()
    swatches = Gtk.Template.Child()
    custom_color = Gtk.Template.Child()
    text_controls = Gtk.Template.Child()
    font_button = Gtk.Template.Child()
    size_spin = Gtk.Template.Child()
    weight_button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.document = None  # an image Document, or None
        self.pdf = None  # a pdfdoc.PdfDocument, or None (one of the two is open at a time)
        self.pdf_view = PdfView()
        self.stack.add_named(self.pdf_view, "pdf")
        self.pdf_view.connect("zoom-changed", lambda *_: self._update_title())
        self.pdf_view.connect("page-changed", lambda *_: (self._update_title(), self._fill_info()))
        self.pdf_view.connect("selection-changed", lambda *_: self._update_state())
        self.pdf_view.connect("files-dropped", self._on_pdf_files_dropped)
        self._siblings = []
        self._load_seq = 0
        self._fit_on_load = False
        self._present_pending = False
        self._overwrite_ok = False  # the user confirmed saving over this document's original
        self._closing = False
        self._add_actions()
        shortcuts.install_window(self)
        self._restore_window_state()

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)
        self.canvas.connect("zoom-changed", lambda *_: self._update_title())
        self.canvas.connect("selection-changed", lambda *_: (self._update_state(), self._sync_bar()))
        self._syncing_bar = False
        self._text_hint_shown = False
        self.font_button.set_font_desc(Pango.FontDescription.from_string(markup.FONT))
        self.font_button.connect("notify::font-desc", self._on_font)
        self.size_spin.connect("value-changed", self._on_text_size)
        self.canvas.connect("shapes-changed", self._on_shapes_changed)
        self.canvas.connect("text-requested", self._on_text_requested)
        self._build_swatches()
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
            "select-all": lambda: self.pdf_view.selection.select_all() if self.pdf else self.canvas.select_all(),
            "close": self.close,
            "undo": lambda: self._doc and self._doc.undo(),
            "redo": lambda: self._doc and self._doc.redo(),
            "zoom-in": lambda: self.pdf_view.zoom_in() if self.pdf else self.canvas.zoom_in(),
            "zoom-out": lambda: self.pdf_view.zoom_out() if self.pdf else self.canvas.zoom_out(),
            "zoom-actual": lambda: self.pdf_view.zoom_actual() if self.pdf else self.canvas.zoom_to(1.0),
            "zoom-fit": lambda: self.pdf_view.zoom_fit() if self.pdf else self.canvas.zoom_fit(),
            "rotate-left": lambda: self._rotate(-1),
            "rotate-right": lambda: self._rotate(1),
            "insert-pages": self.on_insert_pages,
            "delete-pages": self.on_delete_pages,
            "flip-horizontal": lambda: self._apply(Flip(horizontal=True)),
            "flip-vertical": lambda: self._apply(Flip(horizontal=False)),
            "previous": lambda: self.pdf_view.step(-1) if self.pdf else self._step(-1),
            "next": lambda: self.pdf_view.step(1) if self.pdf else self._step(1),
            "fullscreen": lambda: self.unfullscreen() if self.is_fullscreen() else self.fullscreen(),
            "info": self.info_button.popup,
            "shortcuts": lambda: shortcuts.show_dialog(self),
        }
        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            self.add_action(action)

        stateful = {
            "selection-ratio": GLib.Variant("s", "free"),
            "markup": GLib.Variant("b", False),
            "markup-tool": GLib.Variant("s", "select"),
            "markup-color": GLib.Variant("s", markup.PALETTE[0][1]),
            "markup-weight": GLib.Variant("s", "medium"),
        }
        for name, initial in stateful.items():
            vtype = None if name == "markup" else GLib.VariantType.new("s")
            action = Gio.SimpleAction.new_stateful(name, vtype, initial)
            action.connect("change-state", getattr(self, "_on_" + name.replace("-", "_")))
            self.add_action(action)
        delete = Gio.SimpleAction.new("markup-delete", None)
        delete.connect("activate", lambda *_: self.canvas.delete_selected())
        self.add_action(delete)

    def _on_selection_ratio(self, action, value):
        action.set_state(value)
        self.canvas.set_ratio(value.get_string())

    # --- markup -------------------------------------------------------------------------------

    def _on_markup(self, action, value):
        action.set_state(value)
        on = value.get_boolean()
        self.markup_bar.set_visible(on)
        self.canvas.markup_enabled = on
        if not on:
            self.canvas.select_shape(None)
        self.canvas.queue_draw()

    def _on_markup_tool(self, action, value):
        action.set_state(value)
        self.canvas.tool = value.get_string()
        if not self.canvas.markup_enabled:
            self.activate_action("win.markup", None)
        self._sync_bar()

    def _on_markup_color(self, action, value):
        action.set_state(value)
        self.canvas.markup_color = markup.hex_to_rgba(value.get_string())
        if not self._syncing_bar:
            self.canvas.restyle_selected(color=self.canvas.markup_color)

    def _on_markup_weight(self, action, value):
        action.set_state(value)
        self.canvas.markup_weight = value.get_string()
        if not self._syncing_bar:
            self.canvas.restyle_selected(width=self.canvas.style("rect")["width"])

    def _on_font(self, button, _pspec):
        if self._syncing_bar or button.get_font_desc() is None:
            return
        desc = button.get_font_desc().copy()
        desc.unset_fields(Pango.FontMask.SIZE)  # the size comes from the size field
        self.canvas.text_font = desc.to_string()
        self.canvas.restyle_selected(font=self.canvas.text_font)

    def _on_text_size(self, spin):
        if self._syncing_bar:
            return
        self.canvas.text_size = spin.get_value()
        self.canvas.restyle_selected(size=self.canvas.text_size)

    def _sync_bar(self):
        """Show the selected shape's style in the bar (so changing it there restyles that shape), and the
        text controls while text is selected or the Text tool is on."""
        canvas = self.canvas
        shape = canvas.selected if canvas.markup_enabled else None
        is_text = shape.kind == "text" if shape else canvas.tool == "text"
        self.text_controls.set_visible(canvas.markup_enabled and is_text)
        self.weight_button.set_visible(not is_text)
        self._syncing_bar = True
        try:
            if shape:
                self.change_action_state("markup-color", GLib.Variant("s", markup.rgba_to_hex(shape.color)))
                if shape.kind == "text":
                    canvas.text_font, canvas.text_size = shape.font, shape.size
                else:
                    weight = markup.nearest_weight(shape.width, canvas.image_size)
                    self.change_action_state("markup-weight", GLib.Variant("s", weight))
            if is_text:
                self.font_button.set_font_desc(Pango.FontDescription.from_string(canvas.text_font))
                self.size_spin.set_value(round(canvas.text_size or canvas.default_text_size()))
        finally:
            self._syncing_bar = False

    def _build_swatches(self):
        css = []
        for name, spec in markup.PALETTE:
            key = name.lower()
            dot = Gtk.Box(css_classes=["swatch-dot", f"swatch-{key}"], width_request=14, height_request=14,
                          halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            button = Gtk.ToggleButton(child=dot, tooltip_text=name, focus_on_click=False, valign=Gtk.Align.CENTER,
                                      action_name="win.markup-color",
                                      action_target=GLib.Variant("s", spec), css_classes=["flat", "swatch"])
            self.swatches.append(button)
            css.append(f".swatch-{key} {{ background: {spec}; }}")
        css.append(".swatch-dot { border-radius: 999px; box-shadow: inset 0 0 0 1px alpha(black, 0.25); }")
        css.append("button.swatch { min-width: 22px; min-height: 22px; padding: 2px; border-radius: 999px; }")
        css.append("button.swatch:checked { box-shadow: inset 0 0 0 2px @accent_color; background: none; }")
        provider = Gtk.CssProvider()
        provider.load_from_string("\n".join(css))
        Gtk.StyleContext.add_provider_for_display(self.get_display(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.custom_color.connect("notify::rgba", self._on_custom_color)

    def _on_custom_color(self, button, _pspec):
        c = button.get_rgba()
        spec = "#" + "".join(f"{round(v * 255):02x}" for v in (c.red, c.green, c.blue))
        self.activate_action("win.markup-color", GLib.Variant("s", spec))

    def _on_shapes_changed(self, canvas):
        doc = self.document
        if not doc:
            return
        shapes = canvas.shapes
        if (not self._text_hint_shown and canvas.selected and canvas.selected.kind == "text"
                and not (doc.open_markup and canvas.selected in doc.open_markup.shapes)):
            self._text_hint_shown = True
            self.toast("Text stays editable: double-click to retype, drag a corner to resize; "
                       "font, size and colour are in the bar")
        if doc.open_markup is not None:
            doc.amend(markup.Annotate(shapes) if shapes else None)
        elif shapes:
            doc.apply(markup.Annotate(shapes))

    def _on_text_requested(self, canvas, x, y, index):
        existing = canvas.shapes[index] if index >= 0 else None
        entry = Gtk.Entry(text=existing.text if existing else "", placeholder_text="Text", width_chars=28)
        popover = Gtk.Popover(child=entry, position=Gtk.PositionType.BOTTOM)
        popover.set_parent(canvas)
        # Point at the text's bottom edge so the bubble sits under the text, which updates live as you type.
        if existing:
            r = markup.bbox(existing)
        else:
            size = canvas.style("text")["size"]
            r = markup.bbox(markup.Shape("text", (x, y), (x, y), text="Text", size=size,
                                         font=canvas.text_font))
        x0, y0 = canvas.to_widget(r.x, r.y)
        x1, y1 = canvas.to_widget(r.right, r.bottom)
        target = Gdk.Rectangle()
        target.x, target.y, target.width, target.height = int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0))
        popover.set_pointing_to(target)
        entry.connect("changed", lambda e: canvas.preview_text(index, (x, y), e.get_text()))
        committed = []

        def commit(*_args):
            if not committed:  # Enter, then the popover closing: commit once
                committed.append(True)
                canvas.commit_text(index, (x, y), entry.get_text())
                popover.popdown()

        entry.connect("activate", commit)
        popover.connect("closed", lambda p: (commit(), GLib.idle_add(p.unparent)))
        popover.popup()
        entry.grab_focus()

    def _enable(self, name, enabled):
        self.lookup_action(name).set_enabled(enabled)

    @property
    def _doc(self):
        """The open document, image or PDF."""
        return self.pdf or self.document

    def _update_state(self):
        if self.pdf:
            self._update_pdf_state()
            return
        doc = self.document
        for name in DOC_ACTIONS:
            self._enable(name, doc is not None and name not in PDF_ONLY)
        self._enable("save", bool(doc and doc.dirty))
        self._enable("crop", bool(doc and self.canvas.selection))
        self._enable("markup-delete", bool(doc and self.canvas.markup_enabled
                                          and self.canvas.selected_shape is not None))
        self._enable("undo", bool(doc and doc.can_undo))
        self._enable("redo", bool(doc and doc.can_redo))
        index = self._sibling_index()
        self._enable("previous", index is not None and index > 0)
        self._enable("next", index is not None and index < len(self._siblings) - 1)
        self.info_button.set_sensitive(doc is not None)
        self._update_title()

    def _update_pdf_state(self):
        pdf = self.pdf
        for name in DOC_ACTIONS:
            self._enable(name, name not in IMAGE_ONLY)
        self._enable("save", pdf.dirty)
        self._enable("undo", pdf.can_undo)
        self._enable("redo", pdf.can_redo)
        self._enable("markup-delete", False)
        self._enable("delete-pages", len(self.pdf_view.target_positions()) < len(pdf))
        self._enable("previous", self.pdf_view.current_page > 0)
        self._enable("next", self.pdf_view.current_page < len(pdf) - 1)
        self.info_button.set_sensitive(True)
        self._update_title()

    def _update_title(self):
        if self.pdf:
            name = os.path.basename(self.pdf.path)
            title = f"{name} — Edited" if self.pdf.dirty else name
            self.set_title(title)
            self.window_title.set_title(title)
            view = self.pdf_view
            subtitle = f"Page {view.current_page + 1} of {len(self.pdf)} · {round(view.zoom * 100)}%"
            selected = view.selected_positions()
            if len(selected) > 1:
                subtitle += f" · {len(selected)} pages selected"
            self.window_title.set_subtitle(subtitle)
            return
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
        both = Gtk.FileFilter(name="Images and PDFs")
        images = Gtk.FileFilter(name="Images")
        for ext in sorted(imageio.readable_extensions()):
            both.add_suffix(ext.lstrip("."))
            images.add_suffix(ext.lstrip("."))
        pdfs = Gtk.FileFilter(name="PDF Documents")
        for f in (both, pdfs):
            f.add_suffix("pdf")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        for f in (both, images, pdfs):
            filters.append(f)
        dialog = Gtk.FileDialog(title="Open", filters=filters, default_filter=both)
        if self._doc:
            dialog.set_initial_folder(Gio.File.new_for_path(os.path.dirname(self._doc.path)))
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

    def open_file(self, gfile, present=False):
        """present: show the window once the image has loaded (already sized to it), not before."""
        path = gfile.get_path()
        if path is None:
            self.toast("Glance can only open local files")
            if present:
                self.present()
            return
        if present:
            self._present_pending = True
            GLib.timeout_add(1000, self._present_now)  # don't wait forever on a slow decode
        self._confirm_discard(lambda: self._load(path, fit_window=True))

    def _present_now(self):
        if self._present_pending:
            self._present_pending = False
            self.present()
        return False

    def _load(self, path, fit_window=False):
        """Open path in the background. fit_window: size the window to the image (a new open, not Left/Right)."""
        self._load_seq += 1
        seq = self._load_seq
        self._fit_on_load = fit_window

        def work():
            try:
                opener = pdfdoc.PdfDocument.open if pdfdoc.is_pdf(path) else Document.open
                doc, error = opener(path), None
            except pdfdoc.EncryptedPdfError:
                doc, error = None, "it is password-protected, which Glance can't open yet"
            except Exception as e:  # Pillow and pypdf raise many types for bad files
                doc, error = None, e
            GLib.idle_add(self._on_loaded, seq, path, doc, error)

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, seq, path, doc, error):
        if seq != self._load_seq:
            return False  # a newer load superseded this one
        if error:
            self.toast(f"Couldn't open {os.path.basename(path)}: {error}")
            self._present_now()
            return False
        self._overwrite_ok = False
        if isinstance(doc, pdfdoc.PdfDocument):
            self._show_pdf(doc)
            return False
        self.pdf = None
        self.document = doc
        doc.connect(self._on_document_changed)
        self._siblings = imageio.sibling_images(path)
        self.canvas.set_image(doc.image)
        self.canvas.select_shape(None)
        self.canvas.text_size = None  # back to this image's default
        self._sync_bar()
        self.stack.set_visible_child_name("image")
        self.canvas.grab_focus()
        self._fill_info()
        self._update_state()
        if self._fit_on_load:
            self._fit_window_to(doc.size)
        self._present_now()
        return False

    def _show_pdf(self, pdf):
        self.document = None
        self.pdf = pdf
        self._siblings = []
        if self.lookup_action("markup").get_state().get_boolean():
            self.activate_action("win.markup", None)
        pdf.connect(lambda _d: (self.pdf_view.reload(), self._fill_info(), self._update_state()))
        self.pdf_view.set_document(pdf)
        self.stack.set_visible_child_name("pdf")
        self.pdf_view.pages.grab_focus()
        self._fill_info()
        self._update_state()
        if self._fit_on_load:
            pw, ph = pdf.page_size(0)
            # 100% = one point per logical px, as Preview's Actual Size; the sidebar sits beside the page.
            self._fit_window_to((pw + 2 * PAGE_GAP + 16, ph + 2 * PAGE_GAP), scale=1.0,
                                extra_w=THUMB_WIDTH + 49)
            self.pdf_view.zoom_fit()
        self._present_now()

    def _fit_window_to(self, size, scale=None, extra_w=0):
        """Resize the window so the image shows at 100%, or as large as fits on the monitor. size is in image px
        (device px at 100%) unless scale says otherwise; extra_w is fixed width beside it (the PDF sidebar)."""
        if self.is_maximized() or self.is_fullscreen():
            return
        display, surface = self.get_display(), self.get_surface() if self.get_mapped() else None
        monitor = display.get_monitor_at_surface(surface) if surface else None
        if monitor is None and display.get_monitors().get_n_items():
            monitor = display.get_monitors().get_item(0)
        if monitor is None:
            return
        area = monitor.get_geometry()  # logical px; GTK has no work area on Wayland
        if scale is None:
            scale = surface.get_scale() if surface else monitor.get_scale()
        chrome_w, chrome_h = self._chrome()
        if not self.get_mapped() or self.stack.get_visible_child_name() != "pdf":
            chrome_w += extra_w  # when mapped in PDF mode the sidebar is already outside the measured page area
        room_w = area.width * FIT_SCREEN_W - chrome_w
        room_h = area.height * FIT_SCREEN_H - chrome_h
        iw, ih = size[0] / scale, size[1] / scale  # 100% = one image px per device px, as in the canvas
        k = min(1.0, room_w / iw, room_h / ih)
        self.set_default_size(max(FIT_MIN_W, round(iw * k + chrome_w)), max(FIT_MIN_H, round(ih * k + chrome_h)))
        if not self.pdf:
            self.canvas.zoom_fit()

    def _chrome(self):
        """(w, h) around the image: header bar, markup bar when shown. Measured before the window is shown."""
        if self.get_mapped():
            return max(0, self.get_width() - self.stack.get_width()), max(0, self.get_height() - self.stack.get_height())
        h = self.header_bar.measure(Gtk.Orientation.VERTICAL, -1)[1]
        if self.markup_bar.get_visible():
            h += self.markup_bar.measure(Gtk.Orientation.VERTICAL, -1)[1] + self.markup_bar.get_margin_bottom()
        return 0, h

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

    def _rotate(self, turns):
        if self.pdf:
            targets = self.pdf_view.target_positions()
            self.pdf.rotate(targets, turns)
            self.pdf_view.reload(select=self.pdf_view.selected_positions() and targets)
        else:
            self._apply(Rotate(turns))

    # --- PDF pages ----------------------------------------------------------------------------

    def on_delete_pages(self):
        targets = self.pdf_view.target_positions()
        if not self.pdf or not targets:
            return
        if len(targets) >= len(self.pdf):
            self.toast("A PDF needs at least one page")
            return
        self.pdf.delete(targets)
        self.toast(f"Deleted {len(targets)} page{'s' if len(targets) > 1 else ''}")

    def on_insert_pages(self):
        if not self.pdf:
            return
        pdfs = Gtk.FileFilter(name="PDF Documents")
        pdfs.add_suffix("pdf")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(pdfs)
        dialog = Gtk.FileDialog(title="Insert Pages from File", filters=filters, default_filter=pdfs,
                                initial_folder=Gio.File.new_for_path(os.path.dirname(self.pdf.path)))

        def on_chosen(_dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
            self.insert_pdfs(paths, self.pdf_view.current_page + 1)

        dialog.open_multiple(self, None, on_chosen)

    def _on_pdf_files_dropped(self, _view, paths, at):
        self.insert_pdfs(paths, at)

    def insert_pdfs(self, paths, at):
        """Insert every page of each PDF in paths at position at (Insert from File, or a drop on the sidebar)."""
        inserted, skipped = 0, []
        for path in paths:
            if not pdfdoc.is_pdf(path):
                skipped.append(os.path.basename(path))
                continue
            try:
                inserted += self.pdf.insert(at + inserted, path)
            except Exception as e:
                skipped.append(f"{os.path.basename(path)} ({e})")
        if inserted:
            self.pdf_view.reload(select=range(at, at + inserted))
            self.pdf_view.go_to(at)
            self.toast(f"Inserted {inserted} page{'s' if inserted > 1 else ''}")
        if skipped:
            self.toast("Not inserted (only PDFs can be): " + ", ".join(skipped))

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
        layer = doc.open_markup
        self.canvas.show(doc.base_image, layer.shapes if layer else ())
        self._fill_info()
        self._update_state()

    def _fill_info(self):
        while child := self.info_grid.get_first_child():
            self.info_grid.remove(child)
        if self.pdf:
            rows = pdfdoc.describe(self.pdf, self.pdf_view.current_page)
        elif self.document:
            doc = self.document
            rows = imageio.describe(doc.path, doc.image, doc.info, doc.dpi)
        else:
            return
        for row, (label, value) in enumerate(rows):
            key = Gtk.Label(label=label, xalign=1, css_classes=["dim-label"])
            val = Gtk.Label(label=value, xalign=0, selectable=True, wrap=True, max_width_chars=40)
            self.info_grid.attach(key, 0, row, 1, 1)
            self.info_grid.attach(val, 1, row, 1, 1)

    # --- saving -------------------------------------------------------------------------------
    # Save writes over the original, asking once per document first; Save As picks a new file and
    # format (from the extension). Nothing is written without one of the two (no autosave).

    def on_save(self, then=None):
        doc = self._doc
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
        doc = self._doc
        if not doc:
            return
        dialog = Gtk.FileDialog(title="Save As", initial_name=os.path.basename(doc.path),
                                initial_folder=Gio.File.new_for_path(os.path.dirname(doc.path)))

        def on_chosen(_dialog, result):
            try:
                path = dialog.save_finish(result).get_path()
            except GLib.Error:
                return
            if self.pdf:
                if not path.lower().endswith(".pdf"):
                    path += ".pdf"
            elif imageio.format_for_path(path) is None:
                self.toast(f"Glance can't save “{os.path.splitext(path)[1] or 'no extension'}” files")
                return
            if path != doc.path:
                self._overwrite_ok = True  # the file chooser already confirmed any replacement
            self._save_to(path, then)

        dialog.save(self, None, on_chosen)

    def _save_to(self, path, then):
        try:
            self._doc.save(path)
        except AnimatedImageError:
            self.toast("Glance can't save animated images yet; nothing was written")
            return
        except Exception as e:
            self.toast(f"Couldn't save: {e}")
            return
        if self.document:
            self._siblings = imageio.sibling_images(self.document.path)
        self._update_state()
        if then:
            then()

    # --- export -------------------------------------------------------------------------------

    def on_export(self):
        if self.document:
            app = self.get_application()
            defaults = getattr(app, "export_defaults", None) or settings.load_export(self._settings)
            ExportDialog(self.document, defaults, self._choose_export_path).present(self)

    def remember_export(self, options):
        self.get_application().export_defaults = options
        settings.save_export(self._settings, options)

    def _choose_export_path(self, options):
        self.remember_export(options)
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
        doc = self._doc
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

    @property
    def _settings(self):
        app = self.get_application()
        return getattr(app, "settings", None) if app else None

    def _restore_window_state(self):
        s = self._settings
        if s:
            self.set_default_size(s.get_int("window-width"), s.get_int("window-height"))
            if s.get_boolean("window-maximized"):
                self.maximize()

    def _save_window_state(self):
        s = self._settings
        if s:
            s.set_boolean("window-maximized", self.is_maximized())
            if not self.is_maximized() and not self.is_fullscreen():
                w, h = self.get_default_size()
                s.set_int("window-width", w)
                s.set_int("window-height", h)

    def _on_close_request(self, _window):
        if self._closing or not (self._doc and self._doc.dirty):
            self._save_window_state()
            return False

        def close():
            self._closing = True
            self.close()

        self._confirm_discard(close)
        return True
