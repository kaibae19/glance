# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard shortcuts: macOS Preview's, with ⌘ read as Ctrl (Kailey, 2026-10-28).

GTK runs application accelerators in the capture phase, before the focused widget, so a text field would
never see them. Keys that text fields use (arrows, Ctrl+A, Ctrl+Z) are therefore window shortcuts in the
bubble phase instead: they fire only when the focused widget doesn't take the key.
"""

from gi.repository import Adw, Gtk

# action → accelerators. Comments give Preview's key where it differs or isn't obvious.
APP = {
    "win.open": ["<Control>o"],
    "win.save": ["<Control>s"],
    "win.save-as": ["<Control><Shift><Alt>s", "<Control><Shift>s"],  # Preview ⌥⇧⌘S; ⇧ alone is the GNOME habit
    "win.close": ["<Control>w"],
    "app.quit": ["<Control>q"],
    "win.zoom-in": ["<Control>equal", "<Control>plus", "<Control>KP_Add"],
    "win.zoom-out": ["<Control>minus", "<Control>KP_Subtract"],
    "win.zoom-actual": ["<Control>0", "<Control>KP_0"],
    "win.zoom-fit": ["<Control>9"],
    "win.crop": ["<Control>k"],  # Preview: Crop
    "win.markup": ["<Control><Shift>a"],  # Preview: Show Markup Toolbar
    "win.adjust-size": ["<Control><Alt>i"],  # Preview has none by default (design doc §6)
    "win.rotate-left": ["<Control>l"],
    "win.rotate-right": ["<Control>r"],
    "win.info": ["<Control>i"],  # Preview: Show Inspector
    "win.fullscreen": ["<Control><Super>f", "F11"],  # Preview ⌃⌘F
    "win.shortcuts": ["<Control>question"],
}

# Yield to text fields (see above). Menus show these through the items' accel attribute.
WINDOW = {
    "win.undo": ["<Control>z"],
    "win.redo": ["<Control><Shift>z"],
    "win.select-all": ["<Control>a"],
    "win.previous": ["Left"],
    "win.next": ["Right"],
}


# The Keyboard Shortcuts dialog, built from the tables above so it can't drift from the real bindings.
SECTIONS = [
    ("File", [("win.open", "Open"), ("win.save", "Save"), ("win.save-as", "Save As"),
              ("win.close", "Close Window"), ("app.quit", "Quit")]),
    ("Edit", [("win.undo", "Undo"), ("win.redo", "Redo"), ("win.select-all", "Select All"),
              ("win.crop", "Crop to Selection"), ("win.adjust-size", "Adjust Size"),
              ("win.rotate-left", "Rotate Left"), ("win.rotate-right", "Rotate Right")]),
    ("View", [("win.zoom-in", "Zoom In"), ("win.zoom-out", "Zoom Out"), ("win.zoom-actual", "Actual Size"),
              ("win.zoom-fit", "Zoom to Fit"), ("win.fullscreen", "Full Screen"), ("win.info", "Info"),
              ("win.previous", "Previous Image in Folder"), ("win.next", "Next Image in Folder")]),
    ("Markup", [("win.markup", "Show Markup Toolbar"), ("Delete", "Delete Selected Shape"),
                ("Escape", "Deselect"), ("Return", "Crop to Selection (image focused)")]),
    ("General", [("win.shortcuts", "Keyboard Shortcuts")]),
]


def accelerator(key):
    """An action's first accelerator, or key itself when it is a plain key name."""
    accels = APP.get(key) or WINDOW.get(key)
    return accels[0] if accels else key


def show_dialog(window):
    if not hasattr(Adw, "ShortcutsDialog"):  # libadwaita < 1.8
        return
    dialog = Adw.ShortcutsDialog()
    for title, items in SECTIONS:
        section = Adw.ShortcutsSection.new(title)
        for key, label in items:
            section.add(Adw.ShortcutsItem.new(label, accelerator(key)))
        dialog.add(section)
    dialog.present(window)


def install(app):
    for action, accels in APP.items():
        app.set_accels_for_action(action, accels)


def install_window(window):
    controller = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.BUBBLE)
    for action, accels in WINDOW.items():
        trigger = Gtk.ShortcutTrigger.parse_string("|".join(accels))
        controller.add_shortcut(Gtk.Shortcut.new(trigger, Gtk.NamedAction.new(action)))
    window.add_controller(controller)
