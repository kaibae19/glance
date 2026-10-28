# SPDX-License-Identifier: GPL-3.0-or-later
"""An open image: the untouched original plus a list of ops, with undo/redo and a dirty flag.

History is a list of op tuples. apply() adds an op; amend() replaces the last one (how the markup layer is
edited), and each is one undo step.
"""

from . import imageio


class AnimatedImageError(Exception):
    """Saving would flatten an animated image to one frame."""


class Document:
    def __init__(self, image, info=None, path=None):
        self.original = image
        self.info = info
        self.path = path
        self._states = [()]
        self._index = 0
        # _renders[i] is the original with _render_ops[:i] applied. Moving between states re-applies only the
        # ops past the shared prefix. Memory-heavy for huge images (design doc: a later optimisation).
        self._render_ops = ()
        self._renders = [image]
        self._saved_ops = ()
        self._listeners = []

    @classmethod
    def open(cls, path):
        image, info = imageio.load(path)
        return cls(image, info, path)

    def connect(self, callback):
        self._listeners.append(callback)

    def _changed(self):
        for callback in self._listeners:
            callback(self)

    # --- state ------------------------------------------------------------------------------

    @property
    def ops(self):
        return list(self._states[self._index])

    @property
    def image(self):
        return self._renders[-1]

    @property
    def size(self):
        return self.image.size

    @property
    def open_markup(self):
        """The last op if it is an editable markup layer, else None."""
        ops = self._states[self._index]
        return ops[-1] if ops and getattr(ops[-1], "editable", False) else None

    @property
    def base_image(self):
        """The image under the open markup layer (what the canvas shows beneath live shapes)."""
        return self._renders[-2] if self.open_markup else self.image

    @property
    def dpi(self):
        """Resolution after the ops: the last Resize that set one, else the file's."""
        for op in reversed(self._states[self._index]):
            if getattr(op, "dpi", None):
                return op.dpi
        return self.info.dpi if self.info else None

    @property
    def dirty(self):
        return self._states[self._index] != self._saved_ops

    @property
    def can_undo(self):
        return self._index > 0

    @property
    def can_redo(self):
        return self._index < len(self._states) - 1

    # --- editing ----------------------------------------------------------------------------

    def _render(self, state):
        keep = 0
        for a, b in zip(self._render_ops, state):
            if a != b:
                break
            keep += 1
        self._renders = self._renders[:keep + 1]
        for op in state[keep:]:
            self._renders.append(op.apply(self._renders[-1]))
        self._render_ops = state

    def _push(self, state):
        self._states = self._states[:self._index + 1] + [state]
        self._index += 1
        self._render(state)
        self._changed()

    def apply(self, op):
        self._push(self._states[self._index] + (op,))

    def amend(self, op):
        """Replace the last op with op (None removes it), as one undo step."""
        current = self._states[self._index]
        if current:
            self._push(current[:-1] + ((op,) if op is not None else ()))

    def undo(self):
        if self.can_undo:
            self._index -= 1
            self._render(self._states[self._index])
            self._changed()

    def redo(self):
        if self.can_redo:
            self._index += 1
            self._render(self._states[self._index])
            self._changed()

    # --- files ------------------------------------------------------------------------------

    def export(self, path, options):
        """Write a copy (File → Export). The document keeps its path and its unsaved state; animated images
        export their first frame."""
        imageio.export(self.image, path, self.info, options, dpi=self.dpi)

    def save(self, path=None):
        """Save over the original (path=None) or to a new path (Save As), which becomes the document's path."""
        target = path or self.path
        if target is None:
            raise ValueError("document has no path")
        if self.info and self.info.animated:
            raise AnimatedImageError(target)
        fmt = imageio.save(self.image, target, self.info, dpi=self.dpi)
        if self.info:
            self.info.format = fmt
        self.path = target
        self._saved_ops = self._states[self._index]
        self._changed()
