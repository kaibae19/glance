# SPDX-License-Identifier: GPL-3.0-or-later
"""GSettings, when the schema is installed (meson install, Flatpak). Running uninstalled works without it."""

from gi.repository import Gio

from .imageio import ExportOptions

SCHEMA = "io.github.kaibae19.Glance"


def get():
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(SCHEMA, True) is None:
        return None
    return Gio.Settings.new(SCHEMA)


def load_export(settings):
    if settings is None or not settings.get_string("export-format"):
        return None
    spec = settings.get_string("export-background").lstrip("#")
    try:
        background = tuple(int(spec[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        background = (255, 255, 255)
    return ExportOptions(
        format=settings.get_string("export-format"),
        quality=settings.get_int("export-quality"),
        lossless=settings.get_boolean("export-lossless"),
        keep_alpha=settings.get_boolean("export-keep-alpha"),
        background=background,
        strip_metadata=settings.get_boolean("export-strip-metadata"),
    )


def save_export(settings, options):
    if settings is None:
        return
    settings.set_string("export-format", options.format)
    settings.set_int("export-quality", options.quality)
    settings.set_boolean("export-lossless", options.lossless)
    settings.set_boolean("export-keep-alpha", options.keep_alpha)
    settings.set_string("export-background", "#" + "".join(f"{c:02x}" for c in options.background))
    settings.set_boolean("export-strip-metadata", options.strip_metadata)
