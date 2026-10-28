"""Drive the installed app: v0.3 acceptance (open a 1024² icon, Adjust Size to 400 by typing, Enter, Save,
Replace) and v0.4 crop (drag, crop, undo, 1:1 ratio, click to clear, select all). Not collected by pytest; run with scripts/ui-smoke (needs a display).

Usage: ui_smoke.py PKGDATADIR WORKDIR
"""

import os
import sys
import time

pkgdatadir, workdir = sys.argv[1:3]
sys.path.insert(1, pkgdatadir)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from PIL import Image  # noqa: E402

Gio.Resource.load(os.path.join(pkgdatadir, "glance.gresource"))._register()
from glance.main import GlanceApplication  # noqa: E402

icon = os.path.join(workdir, "icon.png")
Image.new("RGBA", (1024, 1024), (30, 140, 90, 255)).save(icon)
photo = os.path.join(workdir, "photo.png")
_img = Image.new("RGB", (1600, 1000), (60, 110, 170))
for _x in range(0, 1600, 100):
    _img.paste((230, 190, 60), (_x, 0, _x + 50, 1000))
_img.save(photo)
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
    step(f"dialog {type(dialog).__name__}")
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
    wait(lambda: not win.document.dirty, lambda: saved(win))


def saved(win):
    with Image.open(icon) as img:
        step(f"saved; file now {img.size} {img.mode}; title {win.get_title()!r}")
        result["ok"] = img.size == (400, 400)
    shoot(win, "after-save.png")
    win.open_file(Gio.File.new_for_path(photo))
    wait(lambda: win.document and win.document.size == (1600, 1000), lambda: crop_start(win))


# --- v0.4 crop ---------------------------------------------------------------------------------

def crop_start(win):
    canvas = win.canvas
    step(f"opened photo {win.document.size}, crop enabled: {win.lookup_action('crop').get_enabled()}")
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
    win.close()
    app.quit()


t0 = time.monotonic()
app.connect("activate", lambda *_: GLib.idle_add(run))
app.run([])
print("\n".join(result["steps"]))
print("PASS" if result["ok"] else "FAIL")
sys.exit(0 if result["ok"] else 1)
