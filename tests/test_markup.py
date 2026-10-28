import pytest
from PIL import Image

from glance import markup
from glance.document import Document
from glance.markup import Annotate, Shape
from glance.ops import Rotate

RED = (1.0, 0.0, 0.0, 1.0)


def test_rasterize_unpremultiplies():
    img = markup.rasterize((Shape("highlight", (0, 0), (10, 10), color=RED),), (20, 20))
    r, g, b, a = img.getpixel((5, 5))
    assert (r, g, b) == (255, 0, 0)
    assert a == pytest.approx(255 * markup.HIGHLIGHT_ALPHA, abs=2)
    assert img.getpixel((15, 15))[3] == 0


def test_rect_strokes_outline_only():
    img = markup.rasterize((Shape("rect", (10, 10), (90, 90), color=RED, width=4),), (100, 100))
    assert img.getpixel((10, 50))[3] == 255  # on the left edge
    assert img.getpixel((50, 50))[3] == 0  # inside


def test_arrow_has_filled_head():
    img = markup.rasterize((Shape("arrow", (10, 50), (90, 50), color=RED, width=4),), (100, 100))
    assert img.getpixel((50, 50))[3] == 255  # shaft
    assert img.getpixel((85, 50))[3] == 255  # head


def test_text_draws_and_measures():
    shape = Shape("text", (5, 5), (5, 5), color=RED, text="Hi", size=30)
    w, h = markup.text_extent(shape)
    assert w > 20 and h >= 30
    img = markup.rasterize((shape,), (100, 60))
    assert img.getbbox() is not None


def test_annotate_keeps_mode():
    rgb = Image.new("RGB", (50, 50), "white")
    out = Annotate((Shape("highlight", (0, 0), (50, 50), color=RED),)).apply(rgb)
    assert out.mode == "RGB"
    assert out.getpixel((25, 25))[1] < 200  # tinted red


def test_hit_testing():
    shapes = (Shape("rect", (10, 10), (50, 50)), Shape("line", (0, 100), (100, 100), width=2))
    assert markup.shape_at(shapes, (30, 30), 3) == 0
    assert markup.shape_at(shapes, (50, 101), 3) == 1
    assert markup.shape_at(shapes, (80, 60), 3) is None


def test_resize_and_move():
    s = Shape("rect", (10, 10), (50, 50))
    r = markup.resized(s, "se", (80, 70), (200, 200))
    assert (r.p0, r.p1) == ((10, 10), (80, 70))
    line = markup.resized(Shape("line", (0, 0), (10, 10)), "p1", (30, 5), (200, 200))
    assert line.p1 == (30, 5)
    assert s.moved(5, -5).p0 == (15, 5)


def test_from_drag_normalizes_boxes_not_lines():
    assert markup.from_drag("rect", (50, 50), (10, 20), {}).p0 == (10, 20)
    assert markup.from_drag("arrow", (50, 50), (10, 20), {}).p1 == (10, 20)


def test_amend_is_one_undo_step():
    doc = Document(Image.new("RGB", (40, 40), "white"))
    a = Shape("rect", (5, 5), (30, 30))
    doc.apply(Annotate((a,)))
    doc.amend(Annotate((a, Shape("line", (0, 0), (40, 40)))))
    assert len(doc.ops) == 1 and len(doc.open_markup.shapes) == 2
    doc.undo()
    assert len(doc.open_markup.shapes) == 1
    doc.undo()
    assert doc.open_markup is None and not doc.dirty
    doc.redo()
    doc.redo()
    assert len(doc.open_markup.shapes) == 2


def test_open_markup_and_base_image():
    doc = Document(Image.new("RGB", (40, 40), "white"))
    doc.apply(Annotate((Shape("highlight", (0, 0), (40, 40), color=RED),)))
    assert doc.open_markup is not None
    assert doc.base_image.getpixel((20, 20)) == (255, 255, 255)
    assert doc.image.getpixel((20, 20)) != (255, 255, 255)
    doc.apply(Rotate(1))  # a later edit flattens the layer
    assert doc.open_markup is None


def test_amend_none_removes_layer():
    doc = Document(Image.new("RGB", (40, 40), "white"))
    doc.apply(Annotate((Shape("rect", (5, 5), (30, 30)),)))
    doc.amend(None)
    assert doc.ops == [] and doc.can_undo and not doc.dirty


def test_markup_saved_flattened(tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (100, 100), "white").save(path)
    doc = Document.open(str(path))
    doc.apply(Annotate((Shape("rect", (10, 10), (90, 90), color=RED, width=6),)))
    doc.save()
    with Image.open(path) as img:
        assert img.convert("RGB").getpixel((10, 50)) == (255, 0, 0)


def test_font_changes_layout():
    sans = Shape("text", (0, 0), (0, 0), text="Wide words", size=30, font="Sans")
    mono = markup.replace(sans, font="Monospace")
    assert markup.text_extent(sans) != markup.text_extent(mono)


def test_text_corner_scales_size():
    shape = Shape("text", (10, 10), (10, 10), text="Hi", size=20)
    r = markup.bbox(shape)
    bigger = markup.resized(shape, "se", (r.right + r.w, r.bottom + r.h), (1000, 1000))
    assert bigger.size == pytest.approx(40, rel=0.05)
    assert bigger.p0 == pytest.approx((10, 10))
    assert set(markup.handles(shape)) == {"nw", "ne", "se", "sw"}


def test_style_helpers():
    assert markup.rgba_to_hex((1, 0.5, 0, 1)) == "#ff8000"
    assert markup.nearest_weight(markup.base_stroke((1600, 1000)) * 4, (1600, 1000)) == "thick"
