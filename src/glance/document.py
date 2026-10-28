"""An open image: the untouched original plus a list of ops, with undo/redo and a dirty flag."""

from . import imageio


class AnimatedImageError(Exception):
    """Saving would flatten an animated image to one frame."""


class Document:
    def __init__(self, image, info=None, path=None):
        self.original = image
        self.info = info
        self.path = path
        self.ops = []
        self._redo = []
        # _renders[i] is the original with ops[:i] applied. Keeping every step makes undo instant;
        # memory-heavy for huge images, which the design doc defers to a later optimisation.
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

    @property
    def image(self):
        return self._renders[-1]

    @property
    def size(self):
        return self.image.size

    @property
    def dpi(self):
        """Resolution after the ops: the last Resize that set one, else the file's."""
        for op in reversed(self.ops):
            if getattr(op, "dpi", None):
                return op.dpi
        return self.info.dpi if self.info else None

    @property
    def dirty(self):
        return tuple(self.ops) != self._saved_ops

    @property
    def can_undo(self):
        return bool(self.ops)

    @property
    def can_redo(self):
        return bool(self._redo)

    def apply(self, op):
        self.ops.append(op)
        self._renders.append(op.apply(self.image))
        self._redo.clear()
        self._changed()

    def undo(self):
        if self.ops:
            self._redo.append(self.ops.pop())
            self._renders.pop()
            self._changed()

    def redo(self):
        if self._redo:
            op = self._redo.pop()
            self.ops.append(op)
            self._renders.append(op.apply(self.image))
            self._changed()

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
        self._saved_ops = tuple(self.ops)
        self._changed()
