"""Load, describe and save images with Pillow. No GTK here, so it runs headless under pytest."""

import io
import os
import re
import shutil
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps, features

Image.init()  # fills Image.SAVE / Image.OPEN; until then they hold only what has been used

EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F
EXIF_MODEL = 0x0110
EXIF_IFD = 0x8769
EXIF_DATE_TAKEN = 0x9003

# Formats that can't store an alpha channel; RGBA is flattened onto white before saving.
NO_ALPHA = {"JPEG", "BMP", "PCX", "PPM", "EPS"}


@dataclass(frozen=True)
class ExportFormat:
    name: str  # Pillow's
    label: str
    extension: str
    lossy: bool
    alpha: bool
    note: str = ""


EXPORT_FORMATS = [
    ExportFormat("PNG", "PNG", ".png", lossy=False, alpha=True),
    ExportFormat("JPEG", "JPEG", ".jpg", lossy=True, alpha=False),
    ExportFormat("WEBP", "WebP", ".webp", lossy=True, alpha=True),
    ExportFormat("AVIF", "AVIF", ".avif", lossy=True, alpha=True),
    ExportFormat("TIFF", "TIFF", ".tiff", lossy=False, alpha=True),
    ExportFormat("GIF", "GIF", ".gif", lossy=False, alpha=True,
                 note="256 colours; transparency is on or off per pixel"),
    ExportFormat("BMP", "BMP", ".bmp", lossy=False, alpha=False),
]
_CODEC = {"WEBP": "webp", "AVIF": "avif", "JPEG": "jpg"}


def export_formats():
    """The EXPORT_FORMATS this Pillow build can write."""
    return [f for f in EXPORT_FORMATS
            if f.name in Image.SAVE and (f.name not in _CODEC or features.check(_CODEC[f.name]))]


@dataclass(frozen=True)
class ExportOptions:
    format: str
    quality: int = 90  # lossy formats
    lossless: bool = False  # WebP
    keep_alpha: bool = True  # off, or a format without alpha: flatten onto background
    background: tuple[int, int, int] = (255, 255, 255)
    strip_metadata: bool = False  # drops EXIF (camera, place, dates); keeps the colour profile


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


def describe(path, img, info, dpi=None):
    """Rows for the Info popover: [(label, value)]. dpi overrides the file's (after Adjust Size)."""
    dpi = dpi or info.dpi
    w, h = img.size
    rows = [("Name", os.path.basename(path)), ("Dimensions", f"{w} × {h} px")]
    rows.append(("Format", f"{info.format or 'unknown'} ({info.mode})"))
    rows.append(("File size", format_size(info.file_size)))
    if info.animated:
        rows.append(("Frames", f"{info.n_frames} (showing the first)"))
    if dpi:
        rows.append(("Resolution", f"{round(dpi[0])} × {round(dpi[1])} dpi"))
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


def _flatten(img, background):
    out = Image.new("RGB", img.size, background)
    out.paste(img, mask=img.getchannel("A"))
    return out


def _prepare(img, info, fmt, dpi=None, options=None):
    """The image and Image.save() parameters for writing img as fmt (Save) or with options (Export)."""
    out = img
    keeps_alpha = fmt not in NO_ALPHA and (options is None or options.keep_alpha)
    if img.mode == "RGBA" and not keeps_alpha:
        out = _flatten(img, options.background if options else (255, 255, 255))
    params = {}
    dpi = dpi or (info.dpi if info else None)
    if info and info.icc_profile:
        params["icc_profile"] = info.icc_profile
    strip = options is not None and options.strip_metadata
    if info and info.exif and not strip and fmt in ("JPEG", "PNG", "WEBP", "TIFF", "AVIF"):
        params["exif"] = info.exif.tobytes()
    if dpi and fmt in ("JPEG", "PNG", "TIFF", "BMP"):
        params["dpi"] = dpi
    quality = options.quality if options else 95
    if fmt == "JPEG":
        params["quality"] = quality
    elif fmt == "WEBP":
        params.update(quality=quality, lossless=bool(options and options.lossless), method=4)
    elif fmt == "AVIF":
        params["quality"] = quality
    elif fmt == "TIFF" and options:
        params["compression"] = "tiff_lzw"
    return out, params


def encoded_size(img, info, fmt=None, dpi=None, options=None):
    """Bytes img would take on disk as fmt (default: the file's own format), or None if unknown."""
    fmt = options.format if options else fmt or (info.format if info else None)
    if fmt not in Image.SAVE:
        return None
    out, params = _prepare(img, info, fmt, dpi, options)
    buf = io.BytesIO()
    out.save(buf, format=fmt, **params)
    return buf.tell()


def save(img, path, info, fmt=None, dpi=None):
    """Write img to path atomically (temp file in the same folder, then rename).

    Keeps the ICC profile, EXIF (orientation already reset) and DPI (dpi, else the file's). Returns the
    format written.
    """
    fmt = fmt or format_for_path(path) or (info.format if info else None)
    if fmt is None:
        raise ValueError(f"no image format for {os.path.basename(path)}")
    out, params = _prepare(img, info, fmt, dpi)
    _write(out, path, fmt, params)
    return fmt


def export(img, path, info, options, dpi=None):
    """Write a copy of img as options.format (Export). The document keeps its own file."""
    out, params = _prepare(img, info, options.format, dpi, options)
    _write(out, path, options.format, params)


def _write(out, path, fmt, params):
    """Save atomically: a temp file in the same folder, then rename over path."""
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


def _umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask
