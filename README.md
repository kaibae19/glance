# Glance

A macOS-Preview-style image viewer and quick editor for GNOME (Python, GTK4, libadwaita, Pillow, Cairo).
GPL-3.0-or-later (`LICENSE`).
Design and decisions: [`docs/design.md`](docs/design.md).

Needs GTK ≥ 4.12, libadwaita ≥ 1.5, PyGObject, Pillow, meson, blueprint-compiler, `glib-compile-resources`
(Ubuntu: `libglib2.0-dev-bin`), pytest.

    scripts/dev [image…]            # build into _build, install into _install, run
    meson test -C _build            # unit tests (headless) + desktop file check
    scripts/headless-shot out.png img.png   # screenshot in a throwaway headless GNOME Shell
    scripts/ui-smoke [dir]          # drive the real window headless (Adjust Size, Save, crop); screenshots in dir

Mouse, as in Preview: drag to select, Ctrl+K crops; scroll or middle-drag pans; Ctrl+scroll or pinch zooms.

## Flatpak

    flatpak-builder --user --install --force-clean flatpak-build io.github.kaibae19.Glance.json

Builds the checkout you are in (GNOME 51 runtime; Pillow 12.1.1 wheels, which include AVIF).
`--filesystem=host` is there for Preview-style folder stepping (Left/Right) and saving next to the original;
the file chooser alone would only grant the one file.
