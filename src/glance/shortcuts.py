"""Keyboard shortcuts: macOS Preview's, with ⌘ read as Ctrl (Kailey, 2026-10-28)."""

# action → accelerators. Comments give Preview's key where it differs or isn't obvious.
SHORTCUTS = {
    "win.open": ["<Control>o"],
    "win.save": ["<Control>s"],
    "win.save-as": ["<Control><Shift><Alt>s", "<Control><Shift>s"],  # Preview ⌥⇧⌘S; ⇧ alone is the GNOME habit
    "win.close": ["<Control>w"],
    "app.quit": ["<Control>q"],
    "win.undo": ["<Control>z"],
    "win.redo": ["<Control><Shift>z"],
    "win.zoom-in": ["<Control>equal", "<Control>plus", "<Control>KP_Add"],
    "win.zoom-out": ["<Control>minus", "<Control>KP_Subtract"],
    "win.zoom-actual": ["<Control>0", "<Control>KP_0"],
    "win.zoom-fit": ["<Control>9"],
    "win.crop": ["<Control>k"],  # Preview: Crop
    "win.select-all": ["<Control>a"],
    "win.adjust-size": ["<Control><Alt>i"],  # Preview has none by default (design doc §6)
    "win.rotate-left": ["<Control>l"],
    "win.rotate-right": ["<Control>r"],
    "win.info": ["<Control>i"],  # Preview: Show Inspector
    "win.fullscreen": ["<Control><Super>f", "F11"],  # Preview ⌃⌘F
    "win.previous": ["Left"],
    "win.next": ["Right"],
}


def install(app):
    for action, accels in SHORTCUTS.items():
        app.set_accels_for_action(action, accels)
