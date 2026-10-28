# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from glance.sizing import SizeModel


def test_icon_to_400_square():
    m = SizeModel(1024, 1024)
    m.set("width", 400, "pixels")
    assert m.size() == (400, 400)
    assert m.changed


def test_proportional_height_follows_width():
    m = SizeModel(1600, 1000)
    m.set("width", 800, "pixels")
    assert m.size() == (800, 500)
    m.set("height", 250, "pixels")
    assert m.size() == (400, 250)


def test_not_proportional():
    m = SizeModel(1600, 1000)
    m.set_proportional(False)
    m.set("width", 400, "pixels")
    assert m.size() == (400, 1000)


def test_retick_proportional_rederives_height():
    m = SizeModel(1600, 1000)
    m.set_proportional(False)
    m.set("width", 800, "pixels")
    m.set_proportional(True)
    assert m.size() == (800, 500)


def test_percent():
    m = SizeModel(1600, 1000)
    m.set("width", 25, "percent")
    assert m.size() == (400, 250)
    assert m.get("height", "percent") == pytest.approx(25)


def test_physical_units():
    m = SizeModel(600, 300, dpi=300)
    assert m.get("width", "inches") == pytest.approx(2)
    assert m.get("width", "cm") == pytest.approx(5.08)
    assert m.get("width", "points") == pytest.approx(144)
    m.set("width", 1, "inches")
    assert m.size() == (300, 150)


def test_resolution_with_resample_keeps_physical_size_in_physical_units():
    m = SizeModel(600, 300, dpi=300)
    m.set_resolution(150, "inches")
    assert m.size() == (300, 150)
    assert m.get("width", "inches") == pytest.approx(2)


def test_resolution_in_pixels_keeps_pixels():
    m = SizeModel(600, 300, dpi=300)
    m.set_resolution(150, "pixels")
    assert m.size() == (600, 300)
    assert m.resolution_changed and m.changed


def test_without_resample_pixels_fixed_and_inches_move_resolution():
    m = SizeModel(600, 300, dpi=300)
    m.set("width", 400, "pixels")
    m.set_resample(False)
    assert m.size() == (600, 300)
    m.set("width", 400, "pixels")  # ignored
    assert m.size() == (600, 300)
    m.set("width", 4, "inches")
    assert m.resolution == pytest.approx(150)
    assert m.size() == (600, 300)


def test_fit_into_keeps_aspect():
    m = SizeModel(4000, 3000)
    m.fit_into(1024, 768)
    assert m.size() == (1024, 768)
    m = SizeModel(1000, 2000)
    m.fit_into(640, 480)
    assert m.size() == (240, 480)


def test_unchanged_and_minimum():
    m = SizeModel(100, 50)
    assert not m.changed
    m.set("width", 1, "pixels")
    assert m.size() == (1, 1)
    m.set("width", 0, "pixels")  # ignored
    assert m.size() == (1, 1)
