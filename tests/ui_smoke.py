# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the installed app: v0.3 acceptance (open a 1024² icon, Adjust Size to 400 by typing, Enter, Save,
Replace) and v0.4 crop (drag, crop, undo, 1:1 ratio, click to clear, select all) and v0.5 export (sheet rows per
format, JPEG flattened onto white with EXIF stripped, document untouched) and v0.6 markup (draw, move, recolour, delete,
undo, save flattened, text formatting) and v1.0 (GSettings, shortcuts and About dialogs, window size). Not collected by pytest; run with scripts/ui-smoke (needs a display).

Usage: ui_smoke.py PKGDATADIR WORKDIR
"""

import os
import sys
import time

pkgdatadir, workdir = sys.argv[1:3]
sys.path.insert(1, pkgdatadir)
os.environ["GSETTINGS_SCHEMA_DIR"] = os.path.join(pkgdatadir, "..", "glib-2.0", "schemas")  # as the launcher does

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from PIL import Image  # noqa: E402

Gio.Resource.load(os.path.join(pkgdatadir, "glance.gresource"))._register()
from glance import markup as glance_markup  # noqa: E402
from glance.main import GlanceApplication  # noqa: E402
from glance.window import GlanceWindow  # noqa: E402

icon = os.path.join(workdir, "icon.png")
Image.new("RGBA", (1024, 1024), (30, 140, 90, 255)).save(icon)
photo = os.path.join(workdir, "photo.png")
_img = Image.new("RGB", (1600, 1000), (60, 110, 170))
for _x in range(0, 1600, 100):
    _img.paste((230, 190, 60), (_x, 0, _x + 50, 1000))
_img.save(photo)
report = os.path.join(workdir, "report.pdf")
appendix = os.path.join(workdir, "appendix.pdf")
shot = os.path.join(workdir, "shot.png")
Image.new("RGB", (800, 500), "white").save(shot)
logo = os.path.join(workdir, "logo.png")
_img = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
_img.paste((40, 90, 200, 255), (50, 50, 250, 150))
_exif = Image.Exif()
_exif[0x010F] = "SmokeCam"
_img.save(logo, exif=_exif)
app = GlanceApplication("smoke")
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
result = {"ok": False, "steps": []}


def step(name):
    result["steps"].append(f"{time.monotonic() - t0:5.2f}s {name}")


def shoot(widget, name):
    paintable = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, widget.get_width(), widget.get_height())
    node = snap.to_node()
    if node:
        widget.get_native().get_renderer().render_texture(node, None).save_to_png(os.path.join(workdir, name))


def wait(cond, then, timeout=5.0):
    start = time.monotonic()

    def poll():
        if cond():
            then()
            return False
        if time.monotonic() - start > timeout:
            step("TIMEOUT")
            app.quit()
            return False
        return True

    GLib.timeout_add(50, poll)


def run():
    win = app.get_active_window()
    win.open_file(Gio.File.new_for_path(icon))
    wait(lambda: win.document is not None, lambda: opened(win))


def opened(win):
    step(f"opened {win.document.size}")
    win.activate_action("win.adjust-size", None)
    wait(lambda: win.get_visible_dialog() is not None, lambda: dialog_up(win))


def dialog_up(win):
    dialog = win.get_visible_dialog()
    cw, ch = win.canvas.get_width(), win.canvas.get_height()
    step(f"dialog {type(dialog).__name__}; window fitted to the 1024² icon: {win.get_width()}×{win.get_height()}, "
         f"canvas {cw}×{ch}, zoom {win.canvas.zoom:.2f}")
    result["fit_ok"] = abs(cw - ch) <= 2 and win.get_width() < 960  # square canvas for a square image
    dialog.width_row.set_text("400")  # what typing does: the editable's text changes
    step(f"typed 400 -> model {dialog.model.size()}, height row {dialog.height_row.get_text()}")
    wait(lambda: "about" in (dialog.result_row.get_subtitle() or ""), lambda: estimated(win, dialog))


def focused_in(widget, root):
    focus = root.get_focus()
    while focus and focus is not widget:
        focus = focus.get_parent()
    return focus is widget


def estimated(win, dialog):
    step(f"result: {dialog.result_row.get_subtitle()}; focus in width: {focused_in(dialog.width_row, win)}")
    if "about 6.5 kB" in dialog.result_row.get_subtitle():
        step("FAIL: estimate is the unresized file's")
        result["stale_estimate"] = True
    shoot(win, "adjust-size.png")
    dialog.on_apply()  # what Enter does
    wait(lambda: win.document.size == (400, 400), lambda: resized(win))


def resized(win):
    step(f"resized {win.document.size}, title {win.get_title()!r}")
    win.activate_action("win.save", None)
    wait(lambda: win.get_visible_dialog() is not None, lambda: replace(win))


def replace(win):
    confirm = win.get_visible_dialog()
    step(f"confirm: {confirm.get_heading()!r}")
    confirm.emit("response", "replace")
    confirm.force_close()  # a click closes it; an emitted response doesn't
    wait(lambda: not win.document.dirty, lambda: saved(win))


def saved(win):
    with Image.open(icon) as img:
        step(f"saved; file now {img.size} {img.mode}; title {win.get_title()!r}")
        result["ok"] = img.size == (400, 400) and not result.get("stale_estimate")
    shoot(win, "after-save.png")
    win.open_file(Gio.File.new_for_path(photo))
    wait(lambda: win.document and win.document.size == (1600, 1000), lambda: crop_start(win))


# --- v0.4 crop ---------------------------------------------------------------------------------

def crop_start(win):
    canvas = win.canvas
    step(f"opened photo {win.document.size}, crop enabled: {win.lookup_action('crop').get_enabled()}; "
         f"window {win.get_width()}×{win.get_height()}, canvas {canvas.get_width()}×{canvas.get_height()}")
    result["fit_ok"] = result["fit_ok"] and abs(canvas.get_width() / canvas.get_height() - 1.6) < 0.02
    x0, y0 = canvas.to_widget(200, 100)
    x1, y1 = canvas.to_widget(1000, 700)
    canvas.begin_drag(x0, y0)
    canvas.update_drag((x0 + x1) / 2, (y0 + y1) / 2)
    canvas.update_drag(x1, y1)
    step(f"dragged; selection px {canvas.selection.pixel_size(win.document.size)}; "
         f"subtitle {win.window_title.get_subtitle()!r}")
    GLib.timeout_add(200, lambda: crop_shot(win))


def crop_shot(win):
    shoot(win, "crop-drag.png")
    win.canvas.end_drag()
    step(f"crop enabled: {win.lookup_action('crop').get_enabled()}")
    win.activate_action("win.crop", None)
    step(f"cropped -> {win.document.size}; selection {win.canvas.selection}")
    ok = win.document.size == (800, 600)
    win.activate_action("win.undo", None)
    step(f"undo -> {win.document.size}")
    ok = ok and win.document.size == (1600, 1000)
    win.activate_action("win.selection-ratio", GLib.Variant("s", "1:1"))
    canvas = win.canvas
    x0, y0 = canvas.to_widget(100, 100)
    canvas.begin_drag(x0, y0)
    canvas.update_drag(*canvas.to_widget(700, 300))
    canvas.end_drag()
    size = canvas.selection.pixel_size(win.document.size)
    step(f"1:1 drag 600×200 -> selection {size}")
    ok = ok and size[0] == size[1]
    x, y = canvas.to_widget(1500, 900)  # a click outside the selection clears it
    canvas.begin_drag(x, y)
    canvas.end_drag()
    step(f"click outside -> selection {canvas.selection}")
    ok = ok and canvas.selection is None
    canvas.select_all()
    shoot(win, "select-all.png")
    win.activate_action("win.crop", None)
    step(f"select all + crop -> {win.document.size}, dirty {win.document.dirty}")
    ok = ok and win.document.size == (1600, 1000) and not win.document.dirty
    result["ok"] = result["ok"] and ok
    win.open_file(Gio.File.new_for_path(logo))
    wait(lambda: win.document and win.document.path == logo, lambda: export_start(win))


# --- v0.5 export -------------------------------------------------------------------------------

def visible_rows(dialog):
    return [n for n in ("quality_row", "lossless_row", "alpha_row", "background_row", "note_row")
            if getattr(dialog, n).get_visible()]


def export_start(win):
    win.activate_action("win.export", None)
    wait(lambda: win.get_visible_dialog() is not None, lambda: export_sheet(win))


def export_sheet(win):
    dialog = win.get_visible_dialog()
    labels = [f.label for f in dialog._formats]
    step(f"export sheet {type(dialog).__name__}; formats {labels}; initial {dialog.format.label}; "
         f"rows {visible_rows(dialog)}; strip sensitive {dialog.strip_row.get_sensitive()}")
    ok = dialog.format.name == "PNG" and "alpha_row" in visible_rows(dialog)
    dialog.format_row.set_selected(labels.index("JPEG"))
    dialog.quality_scale.set_value(60)
    dialog.strip_row.set_active(True)
    rows = visible_rows(dialog)
    step(f"JPEG rows {rows}; background note {dialog.background_row.get_subtitle()!r}")
    ok = ok and rows == ["quality_row", "background_row"]
    dialog.format_row.set_selected(labels.index("WebP"))
    dialog.lossless_row.set_active(True)
    step(f"WebP lossless rows {visible_rows(dialog)}")
    ok = ok and "quality_row" not in visible_rows(dialog)
    dialog.lossless_row.set_active(False)
    dialog.format_row.set_selected(labels.index("JPEG"))
    result["export_ok"] = ok
    wait(lambda: "about" in (dialog.result_row.get_subtitle() or ""), lambda: export_go(win, dialog))


def export_go(win, dialog):
    step(f"estimate {dialog.result_row.get_subtitle()!r}")
    shoot(win, "export-sheet.png")
    options = dialog.options()
    dialog.close()
    win.remember_export(options)  # what choosing Export… does before the file chooser
    target = os.path.join(workdir, "logo-export.jpg")
    win._export(target, options)  # what the file chooser's answer leads to
    wait(lambda: os.path.exists(target), lambda: exported(win, target, options))


def exported(win, target, options):
    with Image.open(target) as img:
        exif = img.getexif()
        step(f"exported {img.format} {img.size} {img.mode}; corner {img.getpixel((0, 0))}; "
             f"EXIF make {exif.get(0x010F)!r}; options {options}")
        ok = (img.format == "JPEG" and img.mode == "RGB" and img.getpixel((0, 0))[0] > 240
              and 0x010F not in exif)
    doc = win.document
    step(f"document still {os.path.basename(doc.path)}, format {doc.info.format}, dirty {doc.dirty}")
    ok = ok and doc.path == logo and doc.info.format == "PNG" and result.pop("export_ok")
    result["ok"] = result["ok"] and ok
    win.open_file(Gio.File.new_for_path(shot))
    wait(lambda: win.document and win.document.path == shot, lambda: markup_start(win))


# --- v0.6 markup -------------------------------------------------------------------------------

def drag(canvas, a, b, shift=False):
    canvas.begin_drag(*canvas.to_widget(*a))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    canvas.update_drag(*canvas.to_widget(*mid), shift)
    canvas.update_drag(*canvas.to_widget(*b), shift)
    canvas.end_drag()


def kinds(doc):
    return [sh.kind for sh in doc.open_markup.shapes] if doc.open_markup else []


def markup_start(win):
    canvas, doc = win.canvas, win.document
    win.activate_action("win.markup", None)
    step(f"markup bar visible {win.markup_bar.get_visible()}, swatches {len(list(_children(win.swatches)))}")
    win.activate_action("win.markup-tool", GLib.Variant("s", "rect"))
    drag(canvas, (100, 100), (300, 250))
    win.activate_action("win.markup-tool", GLib.Variant("s", "arrow"))
    drag(canvas, (500, 400), (350, 260))
    win.activate_action("win.markup-tool", GLib.Variant("s", "text"))
    canvas.commit_text(-1, (420, 80), "Look here")  # what the popover's Enter does
    step(f"shapes {kinds(doc)}; ops {len(doc.ops)}; undo steps {doc._index}; selected {canvas.selected_shape}")
    ok = kinds(doc) == ["rect", "arrow", "text"] and len(doc.ops) == 1 and doc._index == 3
    win.activate_action("win.markup-tool", GLib.Variant("s", "select"))
    drag(canvas, (100, 175), (140, 195))  # grab the rect's left edge, move it 40, 20
    rect = doc.open_markup.shapes[0]
    step(f"moved rect -> p0 {tuple(round(v) for v in rect.p0)}")
    ok = ok and tuple(round(v) for v in rect.p0) == (140, 120)
    win.activate_action("win.markup-color", GLib.Variant("s", "#3584e4"))
    step(f"recoloured rect -> {tuple(round(c, 2) for c in doc.open_markup.shapes[0].color)}")
    ok = ok and doc.open_markup.shapes[0].color[2] > 0.8
    canvas.select_shape(1)
    win.activate_action("win.markup-delete", None)
    step(f"deleted arrow -> {kinds(doc)}")
    ok = ok and kinds(doc) == ["rect", "text"]
    win.activate_action("win.undo", None)
    step(f"undo -> {kinds(doc)}; canvas shapes {len(canvas.shapes)}")
    ok = ok and kinds(doc) == ["rect", "arrow", "text"] and len(canvas.shapes) == 3
    result["markup_ok"] = ok
    text_format(win)


def text_format(win):
    from gi.repository import Pango
    canvas, doc = win.canvas, win.document
    canvas.select_shape(2)
    shown = win.text_controls.get_visible()
    step(f"text selected: text controls {shown}, weight menu {win.weight_button.get_visible()}, "
         f"font {win.font_button.get_font_desc().to_string()!r}, size {win.size_spin.get_value()}")
    ok = shown and not win.weight_button.get_visible()
    win.font_button.set_font_desc(Pango.FontDescription.from_string("Monospace Bold"))
    win.size_spin.set_value(40)
    win.activate_action("win.markup-color", GLib.Variant("s", "#000000"))
    t = doc.open_markup.shapes[2]
    step(f"restyled text -> font {t.font!r}, size {t.size}, colour {markup_hex(t.color)}")
    ok = ok and t.font == "Monospace Bold" and t.size == 40 and markup_hex(t.color) == "#000000"
    canvas.select_shape(0)
    state = win.lookup_action("markup-color").get_state().get_string()
    step(f"rect selected: text controls {win.text_controls.get_visible()}, colour state {state}")
    ok = ok and not win.text_controls.get_visible() and state == "#3584e4"
    canvas.select_shape(2)
    r = glance_markup.bbox(doc.open_markup.shapes[2])
    canvas.begin_drag(*canvas.to_widget(r.right, r.bottom))
    canvas.update_drag(*canvas.to_widget(r.right + 20, r.bottom + 10))
    canvas.update_drag(*canvas.to_widget(r.right + r.w * 0.25, r.bottom + r.h * 0.25))
    canvas.end_drag()
    t = doc.open_markup.shapes[2]
    step(f"corner drag -> text size {t.size:.1f}, p0 {tuple(round(v) for v in t.p0)}")
    ok = ok and 48 <= t.size <= 52 and tuple(round(v) for v in t.p0) == (420, 80)
    canvas.preview_text(2, t.p0, "Look here!")
    live = canvas._live[2].text if canvas._live else None
    canvas.commit_text(2, t.p0, "Look here!")
    step(f"live preview text {live!r}; committed {doc.open_markup.shapes[2].text!r}")
    ok = ok and live == "Look here!" and doc.open_markup.shapes[2].text == "Look here!"
    result["markup_ok"] = result["markup_ok"] and ok
    canvas.select_shape(2)
    GLib.timeout_add(200, lambda: markup_save(win))


def markup_hex(rgba):
    return glance_markup.rgba_to_hex(rgba)


def _children(box):
    child = box.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def markup_save(win):
    shoot(win, "markup.png")
    doc = win.document
    win._overwrite_ok = True
    win.on_save()
    with Image.open(shot) as img:
        img = img.convert("RGB")
        edge = img.getpixel((140, 200))  # moved rect's left edge, now blue
        inside = img.getpixel((220, 180))
        shaft = img.getpixel((425, 330))  # middle of the arrow
        text_px = Image.open(shot).convert("L").crop((420, 80, 560, 120)).getextrema()
    step(f"saved: rect edge {edge}, inside {inside}, arrow {shaft}, text luminance range {text_px}")
    ok = (edge[2] > 180 and edge[0] < 120 and inside == (255, 255, 255) and shaft[0] > 180 and shaft[1] < 80
          and text_px[0] < 100 and not doc.dirty and doc.open_markup is not None)
    step(f"after save: still editable {doc.open_markup is not None}, dirty {doc.dirty}")
    result["ok"] = result["ok"] and ok and result.pop("markup_ok")
    v1_start(win)


# --- v1.0 settings, shortcuts, about -----------------------------------------------------------

def v1_start(win):
    from glance import settings as glance_settings
    s = app.settings
    saved = glance_settings.load_export(s)
    step(f"settings {'on' if s else 'MISSING'}; saved export {saved}")
    ok = s is not None and saved is not None and saved.format == "JPEG" and saved.quality == 60 and saved.strip_metadata
    result["v1_ok"] = ok
    win.activate_action("win.shortcuts", None)
    wait(lambda: win.get_visible_dialog() is not None, lambda: v1_shortcuts(win))


def v1_shortcuts(win):
    dialog = win.get_visible_dialog()
    step(f"shortcuts dialog {type(dialog).__name__}")
    result["v1_ok"] = result["v1_ok"] and type(dialog).__name__ == "ShortcutsDialog"
    GLib.timeout_add(300, lambda: v1_about(win, dialog))


def v1_about(win, shortcuts_dialog):
    shoot(win, "shortcuts.png")
    shortcuts_dialog.force_close()
    app.activate_action("about", None)
    wait(lambda: win.get_visible_dialog() is not None, lambda: GLib.timeout_add(300, lambda: v1_done(win)))


def v1_done(win):
    about = win.get_visible_dialog()
    step(f"about: {about.get_application_name()} {about.get_version()}, license {about.get_license_type().value_nick}, "
         f"icon {about.get_application_icon()}, icon found {Gtk.IconTheme.get_for_display(win.get_display()).has_icon(about.get_application_icon())}")
    ok = (about.get_version() == "smoke" and about.get_license_type() == Gtk.License.GPL_3_0
          and Gtk.IconTheme.get_for_display(win.get_display()).has_icon("io.github.kaibae19.Glance"))
    shoot(win, "about.png")
    about.force_close()
    win.set_default_size(1000, 700)
    win.close()
    w, h = app.settings.get_int("window-width"), app.settings.get_int("window-height")
    step(f"window size saved {w}×{h}")
    result["ok"] = result["ok"] and ok and result.pop("v1_ok") and (w, h) == (1000, 700) and result.pop("fit_ok")
    pdf_start()


# --- PDF ---------------------------------------------------------------------------------------

def make_pdf(path, sizes, label):
    import cairo
    surface = cairo.PDFSurface(path, *sizes[0])
    cr = cairo.Context(surface)
    for i, size in enumerate(sizes):
        surface.set_size(*size)
        cr.set_source_rgb(0.2, 0.3, 0.7)
        cr.rectangle(20, 20, size[0] - 40, 60)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        cr.set_font_size(28)
        cr.move_to(30, 130)
        cr.show_text(f"{label}{i}")
        cr.show_page()
    surface.finish()


def pdf_texts(path):
    import pypdf
    reader = pypdf.PdfReader(path)
    return [p.extract_text().strip() for p in reader.pages], [p.rotation for p in reader.pages]


def pdf_start():
    win = GlanceWindow(application=app)
    win.open_file(Gio.File.new_for_path(report), present=True)
    wait(lambda: win.pdf is not None and win.get_mapped(), lambda: GLib.timeout_add(400, lambda: pdf_view(win)))


def pdf_view(win):
    view, pdf = win.pdf_view, win.pdf
    step(f"PDF open: page {win.stack.get_visible_child_name()}, {len(pdf)} pages, window {win.get_width()}×{win.get_height()}, "
         f"zoom {view.zoom:.2f}, subtitle {win.window_title.get_subtitle()!r}; "
         f"markup enabled {win.lookup_action('markup').get_enabled()}, crop {win.lookup_action('crop').get_enabled()}")
    # 466 px page area − margins over the A4 width (595 pt): ≈ 0.70, not the landscape page's 0.50.
    ok = (win.stack.get_visible_child_name() == "pdf" and len(pdf) == 4 and 0.65 < view.zoom < 0.75
          and not win.lookup_action("markup").get_enabled())
    shoot(win, "pdf.png")
    view.go_to(2)
    step(f"go to page 3 -> current {view.current_page + 1}, subtitle {win.window_title.get_subtitle()!r}")
    ok = ok and view.current_page == 2
    step(f"selected follows the current page: {view.selected_positions()}")
    ok = ok and view.selected_positions() == [2]
    view.selection.select_item(0, True)
    win.activate_action("win.rotate-right", None)
    step(f"rotate page 1 -> turns {[p.turns for p in pdf.pages]}, still selected {view.selected_positions()}")
    ok = ok and pdf.pages[0].turns == 1 and view.selected_positions() == [0]
    view.move_pages([3], 0)  # what dragging the last thumbnail to the top does
    step(f"drag page 4 to the top -> order {[p.index for p in pdf.pages]}, selected {view.selected_positions()}")
    ok = ok and [p.index for p in pdf.pages] == [3, 0, 1, 2] and view.selected_positions() == [0]
    win.insert_pdfs([appendix, logo], 2)  # a drop of two files: one PDF, one PNG
    step(f"insert appendix at 3 -> {len(pdf)} pages, sources {[os.path.basename(p.source)[0] for p in pdf.pages]}")
    ok = ok and len(pdf) == 6 and os.path.basename(pdf.pages[2].source) == "appendix.pdf"
    view.selection.unselect_all()
    view.selection.select_range(4, 2, True)
    win.activate_action("win.delete-pages", None)
    step(f"delete pages 5–6 -> {len(pdf)} pages; can undo {pdf.can_undo}")
    ok = ok and len(pdf) == 4
    win.activate_action("win.undo", None)
    step(f"undo -> {len(pdf)} pages; title {win.get_title()!r}; selected {view.selected_positions()}")
    ok = ok and len(pdf) == 6 and win.get_title().endswith("Edited") and len(view.selected_positions()) == 1
    view.selection.select_range(4, 2, True)
    win.activate_action("win.delete-pages", None)
    target = os.path.join(workdir, "report-edited.pdf")
    win._save_to(target, None)  # what Save As leads to
    texts, rotations = pdf_texts(target)
    step(f"saved {os.path.basename(target)}: {texts}, rotations {rotations}; title {win.get_title()!r}")
    ok = (ok and texts == ["r3", "r0", "a0", "a1"] and rotations == [0, 90, 0, 0]
          and win.get_title() == "report-edited.pdf" and pdf_texts(report)[0] == ["r0", "r1", "r2", "r3"])
    shoot(win, "pdf-edited.png")
    result["ok"] = result["ok"] and ok
    win.close()
    app.quit()


make_pdf(report, [(595, 842)] * 3 + [(842, 595)], "r")  # A4 portrait ×3, then landscape
make_pdf(appendix, [(400, 300)] * 2, "a")
t0 = time.monotonic()
app.connect("activate", lambda *_: GLib.idle_add(run))
app.run([])
print("\n".join(result["steps"]))
print("PASS" if result["ok"] else "FAIL " + str({k: v for k, v in result.items() if k != "steps"}))
sys.exit(0 if result["ok"] else 1)
