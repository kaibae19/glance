import pytest
from PIL import Image, ImageCms

from glance import imageio
from glance.document import AnimatedImageError, Document
from glance.ops import Flip, Rotate


def png(tmp_path, name="a.png", size=(4, 2), mode="RGBA", color=(0, 128, 255, 100), **save):
    path = tmp_path / name
    Image.new(mode, size, color).save(path, **save)
    return str(path)


def test_undo_redo_and_dirty(tmp_path):
    doc = Document.open(png(tmp_path))
    assert not doc.dirty and not doc.can_undo
    doc.apply(Rotate(1))
    assert doc.size == (2, 4) and doc.dirty
    doc.undo()
    assert doc.size == (4, 2) and not doc.dirty and doc.can_redo
    doc.redo()
    assert doc.size == (2, 4) and doc.dirty


def test_new_op_clears_redo(tmp_path):
    doc = Document.open(png(tmp_path))
    doc.apply(Rotate(1))
    doc.undo()
    doc.apply(Flip(True))
    assert not doc.can_redo


def test_original_untouched(tmp_path):
    doc = Document.open(png(tmp_path))
    doc.apply(Rotate(1))
    assert doc.original.size == (4, 2)


def test_listener_called(tmp_path):
    doc = Document.open(png(tmp_path))
    seen = []
    doc.connect(seen.append)
    doc.apply(Rotate(1))
    doc.undo()
    assert len(seen) == 2


def test_save_in_place_keeps_alpha(tmp_path):
    path = png(tmp_path)
    doc = Document.open(path)
    doc.apply(Rotate(1))
    doc.save()
    assert not doc.dirty
    with Image.open(path) as img:
        assert img.size == (2, 4)
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 100
    doc.undo()
    assert doc.dirty
    assert not list(tmp_path.glob(".glance-*")), "temp file left behind"


def test_save_as_changes_path_and_format(tmp_path):
    doc = Document.open(png(tmp_path))
    target = str(tmp_path / "b.jpg")
    doc.apply(Rotate(1))
    doc.save(target)
    assert doc.path == target and doc.info.format == "JPEG"
    with Image.open(target) as img:
        assert img.format == "JPEG" and img.mode == "RGB" and img.size == (2, 4)
        r, g, b = img.getpixel((0, 0))
        assert r > 150, "alpha should flatten onto white"


def test_exif_orientation_applied_and_reset(tmp_path):
    path = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[imageio.EXIF_ORIENTATION] = 6  # stored sideways, display rotated 90° clockwise
    exif[imageio.EXIF_MAKE] = "Pixel"
    Image.new("RGB", (4, 2), "white").save(path, exif=exif)
    doc = Document.open(str(path))
    assert doc.size == (2, 4)
    doc.apply(Flip(True))
    doc.save()
    with Image.open(path) as img:
        assert img.size == (2, 4)
        assert img.getexif().get(imageio.EXIF_ORIENTATION, 1) == 1
        assert img.getexif().get(imageio.EXIF_MAKE) == "Pixel"


def test_icc_profile_kept(tmp_path):
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = png(tmp_path, icc_profile=icc)
    doc = Document.open(path)
    doc.apply(Rotate(2))
    doc.save()
    with Image.open(path) as img:
        assert img.info.get("icc_profile") == icc


def test_animated_refused(tmp_path):
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (2, 2), c) for c in ("red", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    doc = Document.open(str(path))
    assert doc.info.animated
    doc.apply(Rotate(1))
    before = path.read_bytes()
    with pytest.raises(AnimatedImageError):
        doc.save()
    assert path.read_bytes() == before


def test_palette_with_transparency_becomes_rgba(tmp_path):
    img = Image.new("P", (2, 2), 0)
    img.putpalette([0, 0, 0, 255, 0, 0])
    path = tmp_path / "p.png"
    img.save(path, transparency=0)
    loaded, info = imageio.load(str(path))
    assert loaded.mode == "RGBA" and info.mode == "P"
    assert loaded.getpixel((0, 0))[3] == 0


def test_16bit_grey_scaled_to_8bit(tmp_path):
    path = tmp_path / "g16.png"
    Image.new("I;16", (1, 1), 65535).save(path)
    loaded, info = imageio.load(str(path))
    assert info.mode.startswith("I")
    assert loaded.getpixel((0, 0)) == (255, 255, 255)


def test_sibling_images_natural_order(tmp_path):
    for name in ("img10.png", "img2.png", "Img1.jpg", "notes.txt", ".hidden.png"):
        (tmp_path / name).write_bytes(b"")
    names = [p.rsplit("/", 1)[1] for p in imageio.sibling_images(str(tmp_path / "img2.png"))]
    assert names == ["Img1.jpg", "img2.png", "img10.png"]


def test_describe(tmp_path):
    path = png(tmp_path, size=(400, 300), dpi=(144, 144))
    img, info = imageio.load(path)
    rows = dict(imageio.describe(path, img, info))
    assert rows["Dimensions"] == "400 × 300 px"
    assert rows["Format"] == "PNG (RGBA)"
    assert rows["Resolution"] == "144 × 144 dpi"


def test_resize_and_resolution_saved(tmp_path):
    from glance.ops import Resize
    path = png(tmp_path, size=(1024, 1024), dpi=(72, 72))
    doc = Document.open(path)
    doc.apply(Resize((400, 400), dpi=(144.0, 144.0)))
    assert doc.size == (400, 400) and doc.dpi == (144.0, 144.0)
    doc.save()
    with Image.open(path) as img:
        assert img.size == (400, 400)
        assert round(img.info["dpi"][0]) == 144
    doc.undo()
    assert doc.dpi == (72, 72) or round(doc.dpi[0]) == 72


def test_resolution_only_keeps_pixels(tmp_path):
    from glance.ops import Resize
    doc = Document.open(png(tmp_path, size=(10, 10)))
    before = doc.image
    doc.apply(Resize((10, 10), dpi=(300.0, 300.0)))
    assert doc.image is before and doc.dirty


def test_encoded_size_estimate(tmp_path):
    img, info = imageio.load(png(tmp_path, size=(200, 100)))
    estimate = imageio.encoded_size(img, info)
    assert estimate and abs(estimate - info.file_size) < 200
    assert imageio.encoded_size(img, info, "JPEG") > 0
