import pytest

from glance.selection import (Rect, conform, from_drag, full, move, orient, ratio_value, resize)

B = (1600, 1000)


def approx(rect):
    return pytest.approx((rect.x, rect.y, rect.w, rect.h))


def test_drag_any_direction_normalizes():
    r = from_drag((500, 400), (100, 100), B)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(100, 100, 400, 300))


def test_drag_clamps_to_image():
    r = from_drag((1500, 900), (2000, 1200), B)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(1500, 900, 100, 100))


def test_drag_with_ratio_covers_drag_and_fits():
    r = from_drag((0, 0), (400, 100), B, 4 / 3)
    assert (r.w, r.h) == pytest.approx((400, 300))
    r = from_drag((1400, 0), (1600, 50), B, 1.0)  # only 200 wide available
    assert (r.w, r.h) == pytest.approx((200, 200))


def test_orient_follows_shape():
    assert orient(4 / 3, 100, 300) == pytest.approx(3 / 4)
    assert orient(4 / 3, 300, 100) == pytest.approx(4 / 3)
    assert orient(None, 1, 2) is None


def test_ratio_value():
    assert ratio_value("original", B) == pytest.approx(1.6)
    assert ratio_value("free", B) is None
    assert ratio_value("16:9", B) == pytest.approx(16 / 9)


def test_box_rounds_and_clamps():
    assert Rect(10.4, 10.6, 99.8, 50.2).box(B) == (10, 11, 110, 61)
    assert Rect(-5, -5, 2000, 2000).box(B) == (0, 0, 1600, 1000)
    assert Rect(100, 100, 0, 0).pixel_size(B) == (1, 1)


def test_corner_resize_keeps_opposite_corner():
    r = resize(Rect(100, 100, 400, 300), "se", (700, 600), B)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(100, 100, 600, 500))
    r = resize(Rect(100, 100, 400, 300), "nw", (0, 0), B)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(0, 0, 500, 400))


def test_edge_resize_free_moves_one_edge_and_flips():
    r = resize(Rect(100, 100, 400, 300), "e", (800, 9999), B)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(100, 100, 700, 300))
    r = resize(Rect(100, 100, 400, 300), "e", (50, 0), B)  # dragged past the left edge
    assert (r.x, r.w) == pytest.approx((50, 50))
    r = resize(Rect(100, 100, 400, 300), "n", (0, 0), B)
    assert (r.y, r.h) == pytest.approx((0, 400))


def test_edge_resize_with_ratio_grows_centred_and_fits():
    r = resize(Rect(100, 100, 400, 400), "e", (700, 0), B, 1.0)
    assert (r.x, r.w, r.h) == pytest.approx((100, 600, 600))
    assert r.y + r.h / 2 == pytest.approx(300)
    r = resize(Rect(100, 100, 200, 200), "e", (1600, 0), B, 1.0)  # height room is 2 × 200 = 400
    assert (r.w, r.h) == pytest.approx((400, 400))


def test_move_clamps():
    r = move(Rect(100, 100, 400, 300), 5000, -5000, B)
    assert (r.x, r.y) == (1200, 0)


def test_conform_centres():
    r = conform(Rect(0, 0, 400, 200), 1.0)
    assert (r.x, r.y, r.w, r.h) == approx(Rect(100, 0, 200, 200))


def test_full():
    assert full(B).box(B) == (0, 0, 1600, 1000)
