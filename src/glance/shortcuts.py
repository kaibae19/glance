"""Keyboard shortcuts: macOS Preview's, with ⌘ read as Ctrl (Kailey, 2026-10-28).

GTK runs application accelerators in the capture phase, before the focused widget, so a text field would
never see them. Keys that text fields use (arrows, Ctrl+A, Ctrl+Z) are therefore window shortcuts in the
bubble phase instead: they fire only when the focused widget doesn't take the key.
"""

from gi.repository import Gtk

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
    "win.adjust-size": ["<Control><Alt>i"],  # Preview has none by default (design doc §6)
    "win.rotate-left": ["<Control>l"],
    "win.rotate-right": ["<Control>r"],
    "win.info": ["<Control>i"],  # Preview: Show Inspector
    "win.fullscreen": ["<Control><Super>f", "F11"],  # Preview ⌃⌘F
}

# Yield to text fields (see above). Menus show these through the items' accel attribute.
WINDOW = {
    "win.undo": ["<Control>z"],
    "win.redo": ["<Control><Shift>z"],
    "win.select-all": ["<Control>a"],
    "win.previous": ["Left"],
    "win.next": ["Right"],
}


def install(app):
    for action, accels in APP.items():
        app.set_accels_for_action(action, accels)


def install_window(window):
    controller = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.BUBBLE)
    for action, accels in WINDOW.items():
        trigger = Gtk.ShortcutTrigger.parse_string("|".join(accels))
        controller.add_shortcut(Gtk.Shortcut.new(trigger, Gtk.NamedAction.new(action)))
    window.add_controller(controller)
