# Glance

A macOS-Preview-style image viewer and quick editor for GNOME (Python, GTK4, libadwaita, Pillow).
Design and decisions: [`docs/design.md`](docs/design.md).

Needs GTK ≥ 4.12, libadwaita ≥ 1.5, PyGObject, Pillow, meson, blueprint-compiler, `glib-compile-resources`
(Ubuntu: `libglib2.0-dev-bin`), pytest.

    scripts/dev [image…]            # build into _build, install into _install, run
    meson test -C _build            # unit tests (headless) + desktop file check
    scripts/headless-shot out.png img.png   # screenshot in a throwaway headless GNOME Shell
