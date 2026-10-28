# SPDX-License-Identifier: GPL-3.0-or-later
from PIL import Image, ImageCms

from glance import imageio
from glance.document import Document
from glance.imageio import ExportOptions
from glance.ops import Rotate


def make(tmp_path, name="a.png", **save):
    path = tmp_path / name
    img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    img.paste((200, 40, 40, 255), (0, 0, 32, 32))
    exif = Image.Exif()
    exif[imageio.EXIF_MAKE] = "Pixel"
    img.save(path, exif=exif, **save)
    return str(path)


def test_formats_available_here():
    names = [f.name for f in imageio.export_formats()]
    assert {"PNG", "JPEG", "TIFF", "GIF", "BMP"} <= set(names)
    assert all(f.name in Image.SAVE for f in imageio.export_formats())


def test_export_leaves_document_alone(tmp_path):
    path = make(tmp_path)
    doc = Document.open(path)
    doc.apply(Rotate(1))
    target = str(tmp_path / "out.jpg")
    doc.export(target, ExportOptions("JPEG"))
    assert doc.path == path and doc.dirty and doc.info.format == "PNG"
    with Image.open(target) as img:
        assert img.format == "JPEG" and img.size == (32, 64)


def test_jpeg_flattens_onto_background(tmp_path):
    doc = Document.open(make(tmp_path))
    target = str(tmp_path / "out.jpg")
    doc.export(target, ExportOptions("JPEG", background=(0, 0, 255)))
    with Image.open(target) as img:
        r, g, b = img.getpixel((60, 16))  # was transparent
        assert b > 200 and r < 50


def test_png_without_alpha_flattens(tmp_path):
    doc = Document.open(make(tmp_path))
    target = str(tmp_path / "flat.png")
    doc.export(target, ExportOptions("PNG", keep_alpha=False, background=(0, 255, 0)))
    with Image.open(target) as img:
        assert img.mode == "RGB" and img.getpixel((60, 16)) == (0, 255, 0)


def test_webp_lossless_keeps_pixels_and_alpha(tmp_path):
    doc = Document.open(make(tmp_path))
    target = str(tmp_path / "out.webp")
    doc.export(target, ExportOptions("WEBP", lossless=True))
    with Image.open(target) as img:
        img = img.convert("RGBA")
        assert img.getpixel((0, 0)) == (200, 40, 40, 255)
        assert img.getpixel((60, 16))[3] == 0


def test_quality_changes_size(tmp_path):
    img = Image.effect_noise((256, 256), 64).convert("RGB")
    low = imageio.encoded_size(img, None, options=ExportOptions("JPEG", quality=20))
    high = imageio.encoded_size(img, None, options=ExportOptions("JPEG", quality=95))
    assert low < high


def test_gif_keeps_binary_transparency(tmp_path):
    doc = Document.open(make(tmp_path))
    target = str(tmp_path / "out.gif")
    doc.export(target, ExportOptions("GIF"))
    with Image.open(target) as img:
        rgba = img.convert("RGBA")
        assert rgba.getpixel((60, 16))[3] == 0 and rgba.getpixel((0, 0))[3] == 255


def test_strip_metadata_drops_exif_keeps_icc(tmp_path):
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    doc = Document.open(make(tmp_path, icc_profile=icc))
    kept, stripped = str(tmp_path / "kept.jpg"), str(tmp_path / "stripped.jpg")
    doc.export(kept, ExportOptions("JPEG"))
    doc.export(stripped, ExportOptions("JPEG", strip_metadata=True))
    with Image.open(kept) as img:
        assert img.getexif().get(imageio.EXIF_MAKE) == "Pixel"
    with Image.open(stripped) as img:
        assert imageio.EXIF_MAKE not in img.getexif()
        assert img.info.get("icc_profile") == icc


def test_animated_exports_first_frame(tmp_path):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (2, 2), c) for c in ("red", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    doc = Document.open(str(path))
    target = str(tmp_path / "frame.png")
    doc.export(target, ExportOptions("PNG"))
    with Image.open(target) as img:
        assert getattr(img, "n_frames", 1) == 1
        assert img.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
