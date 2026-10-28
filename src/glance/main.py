# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from . import settings, shortcuts
from .window import GlanceWindow

APP_ID = "io.github.kaibae19.Glance"


class GlanceApplication(Adw.Application):
    def __init__(self, version):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.version = version
        for name, handler in (("quit", self._quit), ("about", self._about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            self.add_action(action)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.settings = settings.get()  # None when running uninstalled
        shortcuts.install(self)

    def do_activate(self):
        window = self.props.active_window or GlanceWindow(application=self)
        window.present()
        self._dev_screenshot(window)

    def do_open(self, files, _n_files, _hint):
        # One window per file, as Preview does when files are opened separately.
        for gfile in files:
            window = GlanceWindow(application=self)
            window.open_file(gfile)
            window.present()
            self._dev_screenshot(window)

    def _quit(self):
        for window in list(self.get_windows()):
            window.close()  # each window asks about its own unsaved edits

    def _about(self):
        Adw.AboutDialog(application_name="Glance", application_icon=APP_ID, version=self.version,
                        developer_name="Kailey", copyright="© 2026 Kailey",
                        comments="Quick image viewing and editing, the macOS Preview way",
                        website="https://github.com/kaibae19/glance",
                        license_type=Gtk.License.GPL_3_0).present(self.props.active_window)

    def _dev_screenshot(self, window):
        """GLANCE_SCREENSHOT=out.png: save a picture of the window after ~1.5 s, then quit (headless checks)."""
        path = os.environ.get("GLANCE_SCREENSHOT")
        if not path:
            return

        def shoot():
            paintable = Gtk.WidgetPaintable.new(window)
            snapshot = Gtk.Snapshot()
            paintable.snapshot(snapshot, window.get_width(), window.get_height())
            node = snapshot.to_node()
            if node:
                window.get_renderer().render_texture(node, None).save_to_png(path)
            self.quit()
            return False

        GLib.timeout_add(int(os.environ.get("GLANCE_SCREENSHOT_DELAY", "1500")), shoot)


def main(version):
    return GlanceApplication(version).run(sys.argv)
