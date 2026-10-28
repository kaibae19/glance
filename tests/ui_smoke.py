"""Drive the installed app through the v0.3 acceptance test: open a 1024² icon, Adjust Size to 400 by typing,
Enter, Save (Replace). Not collected by pytest; run with scripts/ui-smoke (needs a display).

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
    step(f"dialog {type(dialog).__name__}, focus on width: {dialog.width_row.has_focus() or dialog.width_row.is_focus()}")
    dialog.width_row.set_text("400")  # what typing does: the editable's text changes
    step(f"typed 400 -> model {dialog.model.size()}, height row {dialog.height_row.get_text()}")
    wait(lambda: "about" in (dialog.result_row.get_subtitle() or ""), lambda: estimated(win, dialog))


def estimated(win, dialog):
    step(f"result: {dialog.result_row.get_subtitle()}")
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
    win.close()
    app.quit()


t0 = time.monotonic()
app.connect("activate", lambda *_: GLib.idle_add(run))
app.run([])
print("\n".join(result["steps"]))
print("PASS" if result["ok"] else "FAIL")
sys.exit(0 if result["ok"] else 1)
