# SPDX-License-Identifier: GPL-3.0-or-later
"""Adjust Size arithmetic, after Preview's sheet. No GTK here, so it tests headless.

Pixels are the truth; every other unit is derived from pixels and the resolution (pixels per inch).
"""

from dataclasses import dataclass

from PIL import Image

UNITS = ["pixels", "percent", "inches", "cm", "mm", "points"]
PHYSICAL = {"inches": 1.0, "cm": 2.54, "mm": 25.4, "points": 72.0}  # per inch

PRESETS = [(320, 240), (400, 400), (640, 480), (800, 600), (1024, 768), (1280, 720),
           (1280, 1024), (1920, 1080), (2560, 1440), (3840, 2160)]

METHODS = [  # (label, Pillow filter)
    ("Best (Lanczos)", Image.Resampling.LANCZOS),
    ("Bicubic", Image.Resampling.BICUBIC),
    ("Bilinear", Image.Resampling.BILINEAR),
    ("Nearest (pixel art)", Image.Resampling.NEAREST),
]

DEFAULT_DPI = 72.0


@dataclass
class SizeModel:
    width: int  # original pixels
    height: int
    dpi: float = DEFAULT_DPI  # original resolution

    def __post_init__(self):
        self.new_width = float(self.width)
        self.new_height = float(self.height)
        self.resolution = float(self.dpi)
        self.proportional = True
        self.resample = True

    # --- reading ----------------------------------------------------------------------------

    def size(self):
        """The resulting pixel size, at least 1×1."""
        return max(1, round(self.new_width)), max(1, round(self.new_height))

    def get(self, axis, unit):
        px = self.new_width if axis == "width" else self.new_height
        if unit == "pixels":
            return float(round(px))
        if unit == "percent":
            return px / (self.width if axis == "width" else self.height) * 100
        return px / self.resolution * PHYSICAL[unit]

    @property
    def changed(self):
        return self.size() != (self.width, self.height) or self.resolution_changed

    @property
    def resolution_changed(self):
        return abs(self.resolution - self.dpi) > 1e-6

    # --- editing ----------------------------------------------------------------------------

    def set(self, axis, value, unit):
        """Set width or height in unit; the other follows when proportional (always when not resampling)."""
        if value <= 0:
            return
        if not self.resample:
            if unit not in PHYSICAL:
                return  # pixels are fixed without resampling; only physical size (= resolution) moves
            px = self.width if axis == "width" else self.height
            self.resolution = px / (value / PHYSICAL[unit])
            return
        own = self.width if axis == "width" else self.height
        other = self.height if axis == "width" else self.width
        if unit == "pixels":
            px = float(value)
        elif unit == "percent":
            px = own * value / 100
        else:
            px = value / PHYSICAL[unit] * self.resolution
        if axis == "width":
            self.new_width = px
            if self.proportional:
                self.new_height = px * other / own
        else:
            self.new_height = px
            if self.proportional:
                self.new_width = px * other / own

    def set_resolution(self, dpi, unit):
        """Preview's rule: with resampling and a physical unit, the physical size holds and pixels follow;
        otherwise the pixels hold."""
        if dpi <= 0:
            return
        if self.resample and unit in PHYSICAL:
            scale = dpi / self.resolution
            self.new_width *= scale
            self.new_height *= scale
        self.resolution = float(dpi)

    def set_resample(self, on):
        self.resample = on
        if not on:  # back to the original pixels, proportions locked
            self.new_width, self.new_height = float(self.width), float(self.height)
            self.proportional = True

    def set_proportional(self, on):
        self.proportional = on or not self.resample
        if self.proportional:  # re-derive height from width, as Preview does when re-ticking the box
            self.new_height = self.new_width * self.height / self.width

    def fit_into(self, box_w, box_h):
        """Scale to the largest size that fits box_w × box_h, keeping proportions (up or down)."""
        self.resample = True
        self.proportional = True
        scale = min(box_w / self.width, box_h / self.height)
        self.new_width = self.width * scale
        self.new_height = self.height * scale

    def reset(self):
        self.__post_init__()
