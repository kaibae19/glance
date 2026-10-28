# SPDX-License-Identifier: GPL-3.0-or-later
from PIL import Image

from glance.ops import Crop, Flip, Resize, Rotate

RED = (255, 0, 0, 255)


def marked(w=3, h=2):
    """A transparent w×h image with one red pixel in the top-left corner."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.putpixel((0, 0), RED)
    return img


def red_at(img):
    return [(x, y) for y in range(img.height) for x in range(img.width) if img.getpixel((x, y)) == RED]


def test_rotate_right_moves_top_left_to_top_right():
    out = Rotate(1).apply(marked())
    assert out.size == (2, 3)
    assert red_at(out) == [(1, 0)]


def test_rotate_left_moves_top_left_to_bottom_left():
    out = Rotate(-1).apply(marked())
    assert out.size == (2, 3)
    assert red_at(out) == [(0, 2)]


def test_rotate_full_turn_is_identity():
    img = marked()
    assert red_at(Rotate(4).apply(img)) == [(0, 0)]
    assert red_at(Rotate(2).apply(Rotate(2).apply(img))) == [(0, 0)]


def test_flips():
    assert red_at(Flip(horizontal=True).apply(marked())) == [(2, 0)]
    assert red_at(Flip(horizontal=False).apply(marked())) == [(0, 1)]


def test_crop():
    out = Crop((0, 0, 2, 1)).apply(marked())
    assert out.size == (2, 1)
    assert red_at(out) == [(0, 0)]


def test_resize_keeps_alpha():
    img = Image.new("RGBA", (800, 600), (10, 20, 30, 128))
    out = Resize((400, 400)).apply(img)
    assert out.size == (400, 400)
    assert out.mode == "RGBA"
    assert out.getpixel((200, 200))[3] == 128


def test_ops_compare_by_value():
    assert Rotate(1) == Rotate(1)
    assert Rotate(1) != Rotate(-1)
    assert Flip(True) != Flip(False)
