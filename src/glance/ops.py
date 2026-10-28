"""Edit operations. Each op is an immutable value whose apply() maps a PIL image to a new one."""

from dataclasses import dataclass

from PIL import Image


class Op:
    def apply(self, img):
        raise NotImplementedError


@dataclass(frozen=True)
class Rotate(Op):
    turns: int  # quarter turns, positive = clockwise (Rotate Right)

    def apply(self, img):
        method = {1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180,
                  3: Image.Transpose.ROTATE_90}.get(self.turns % 4)
        return img.transpose(method) if method is not None else img


@dataclass(frozen=True)
class Flip(Op):
    horizontal: bool  # True = mirror left/right, False = upside down

    def apply(self, img):
        return img.transpose(Image.Transpose.FLIP_LEFT_RIGHT if self.horizontal
                             else Image.Transpose.FLIP_TOP_BOTTOM)


@dataclass(frozen=True)
class Crop(Op):
    box: tuple[int, int, int, int]  # left, top, right, bottom in image pixels

    def apply(self, img):
        return img.crop(self.box)


@dataclass(frozen=True)
class Resize(Op):
    """Adjust Size: new pixel size and/or new resolution (dpi None = unchanged)."""
    size: tuple[int, int]
    resample: Image.Resampling = Image.Resampling.LANCZOS
    dpi: tuple[float, float] | None = None

    def apply(self, img):
        return img if img.size == tuple(self.size) else img.resize(self.size, self.resample)
