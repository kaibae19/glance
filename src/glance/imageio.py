"""Load, describe and save images with Pillow. No GTK here, so it runs headless under pytest."""

import io
import os
import re
import shutil
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps

EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F
EXIF_MODEL = 0x0110
EXIF_IFD = 0x8769
EXIF_DATE_TAKEN = 0x9003

# Formats that can't store an alpha channel; RGBA is flattened onto white before saving.
NO_ALPHA = {"JPEG", "BMP", "PCX", "PPM", "EPS"}


@dataclass
class ImageInfo:
    format: str | None
    mode: str  # mode as stored in the file, before conversion for editing
    file_size: int
    dpi: tuple | None
    icc_profile: bytes | None
    exif: Image.Exif | None  # orientation already applied and removed
    n_frames: int

    @property
    def animated(self):
        return self.n_frames > 1


def readable_extensions():
    return {ext for ext, fmt in Image.registered_extensions().items() if fmt in Image.OPEN}


def format_for_path(path):
    """Pillow format name for a file name's extension, or None if Pillow can't write it."""
    fmt = Image.registered_extensions().get(os.path.splitext(path)[1].lower())
    return fmt if fmt in Image.SAVE else None


def _natural_key(name):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.casefold())]


def sibling_images(path):
    """Images in the same folder as path, in Finder-like natural order."""
    folder = os.path.dirname(os.path.abspath(path))
    exts = readable_extensions()
    names = [n for n in os.listdir(folder)
             if not n.startswith(".") and os.path.splitext(n)[1].lower() in exts]
    return [os.path.join(folder, n) for n in sorted(names, key=_natural_key)]


def normalize(img):
    """Convert to RGB or RGBA for editing and display."""
    if img.mode in ("RGB", "RGBA"):
        return img
    if img.mode.startswith("I;16"):
        img = img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    has_alpha = img.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in img.info
    return img.convert("RGBA" if has_alpha else "RGB")


def load(path):
    """Return (image, info). The image is upright (EXIF orientation applied) and RGB or RGBA."""
    with Image.open(path) as src:
        info = ImageInfo(
            format=src.format,
            mode=src.mode,
            file_size=os.path.getsize(path),
            dpi=src.info.get("dpi"),
            icc_profile=src.info.get("icc_profile"),
            exif=None,
            n_frames=getattr(src, "n_frames", 1),
        )
        img = ImageOps.exif_transpose(src)  # a loaded copy, upright
    exif = img.getexif()
    exif.pop(EXIF_ORIENTATION, None)
    info.exif = exif if len(exif) or exif.get_ifd(EXIF_IFD) else None
    return normalize(img), info


def format_size(n):
    for unit in ("bytes", "kB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000


def describe(path, img, info):
    """Rows for the Info popover: [(label, value)]."""
    w, h = img.size
    rows = [("Name", os.path.basename(path)), ("Dimensions", f"{w} × {h} px")]
    rows.append(("Format", f"{info.format or 'unknown'} ({info.mode})"))
    rows.append(("File size", format_size(info.file_size)))
    if info.animated:
        rows.append(("Frames", f"{info.n_frames} (showing the first)"))
    if info.dpi:
        rows.append(("Resolution", f"{round(info.dpi[0])} × {round(info.dpi[1])} dpi"))
    if info.icc_profile:
        try:
            name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(info.icc_profile)))
            rows.append(("Colour profile", name.strip()))
        except (ImageCms.PyCMSError, OSError):
            rows.append(("Colour profile", "embedded"))
    if info.exif:
        camera = " ".join(str(info.exif.get(t, "")).strip() for t in (EXIF_MAKE, EXIF_MODEL)).strip()
        if camera:
            rows.append(("Camera", camera))
        taken = info.exif.get_ifd(EXIF_IFD).get(EXIF_DATE_TAKEN)
        if taken:
            rows.append(("Taken", str(taken)))
    return rows


def save(img, path, info, fmt=None):
    """Write img to path atomically (temp file in the same folder, then rename).

    Keeps the ICC profile, EXIF (orientation already reset) and DPI from info. Returns the format written.
    """
    fmt = fmt or format_for_path(path) or (info.format if info else None)
    if fmt is None:
        raise ValueError(f"no image format for {os.path.basename(path)}")
    out = img
    if fmt in NO_ALPHA and img.mode == "RGBA":
        out = Image.new("RGB", img.size, "white")
        out.paste(img, mask=img.getchannel("A"))
    params = {}
    if info and info.icc_profile:
        params["icc_profile"] = info.icc_profile
    if info and info.exif and fmt in ("JPEG", "PNG", "WEBP", "TIFF"):
        params["exif"] = info.exif.tobytes()
    if info and info.dpi and fmt in ("JPEG", "PNG", "TIFF", "BMP"):
        params["dpi"] = info.dpi
    if fmt == "JPEG":
        params["quality"] = 95

    path = os.path.abspath(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".glance-",
                               suffix=os.path.splitext(path)[1])
    try:
        with os.fdopen(fd, "wb") as f:
            out.save(f, format=fmt, **params)
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return fmt


def _umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask
