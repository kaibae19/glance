# SPDX-License-Identifier: GPL-3.0-or-later
import cairo
import pypdf
import pytest

from glance.pdfdoc import EncryptedPdfError, PageRef, PdfDocument, is_pdf


def make_pdf(path, sizes, label="p"):
    """A PDF whose page i is sizes[i] (points) and says f"{label}{i}"."""
    surface = cairo.PDFSurface(str(path), *sizes[0])
    cr = cairo.Context(surface)
    for i, size in enumerate(sizes):
        surface.set_size(*size)
        cr.move_to(10, 30)
        cr.set_font_size(18)
        cr.show_text(f"{label}{i}")
        cr.show_page()
    surface.finish()
    return str(path)


def texts(path):
    return [page.extract_text().strip() for page in pypdf.PdfReader(path).pages]


@pytest.fixture
def three(tmp_path):
    return make_pdf(tmp_path / "three.pdf", [(200, 300)] * 3)


def test_open(three):
    doc = PdfDocument.open(three)
    assert len(doc) == 3 and not doc.dirty
    assert doc.page_size(0) == (200, 300)


def test_move_delete_rotate_and_undo(three):
    doc = PdfDocument.open(three)
    doc.move([2], 0)
    assert [p.index for p in doc.pages] == [2, 0, 1]
    doc.move([0], 3)  # to the end
    assert [p.index for p in doc.pages] == [0, 1, 2]
    doc.move([0, 1], 3)
    assert [p.index for p in doc.pages] == [2, 0, 1]
    doc.rotate([1], 1)
    assert doc.pages[1].turns == 1 and doc.page_size(1) == (300, 200)
    doc.delete([0])
    assert [p.index for p in doc.pages] == [0, 1]
    doc.undo()
    doc.undo()
    assert doc.pages[1].turns == 0
    doc.undo()
    doc.undo()
    doc.undo()
    assert not doc.dirty and not doc.can_undo


def test_cannot_delete_every_page(three):
    with pytest.raises(ValueError):
        PdfDocument.open(three).delete([0, 1, 2])


def test_save_order_rotation_and_merge(tmp_path, three):
    other = make_pdf(tmp_path / "other.pdf", [(300, 200), (300, 200)], label="o")
    doc = PdfDocument.open(three)
    doc.move([2], 0)
    doc.rotate([0], 1)
    assert doc.insert(1, other) == 2
    target = str(tmp_path / "out.pdf")
    doc.save(target)
    assert texts(target) == ["p2", "o0", "o1", "p0", "p1"]
    reader = pypdf.PdfReader(target)
    assert reader.pages[0].rotation == 90
    assert not doc.dirty and doc.path == target


def test_save_over_original_keeps_history(three):
    doc = PdfDocument.open(three)
    doc.delete([1])
    doc.save()
    assert texts(three) == ["p0", "p2"]
    doc.undo()  # the old pages are still readable from the replaced file's open reader
    assert len(doc) == 3 and doc.dirty


def test_rotation_adds_to_existing(tmp_path, three):
    w = pypdf.PdfWriter()
    for page in pypdf.PdfReader(three).pages:
        w.add_page(page)
    w.pages[0].rotate(90)
    rotated = str(tmp_path / "rotated.pdf")
    with open(rotated, "wb") as f:
        w.write(f)
    doc = PdfDocument.open(rotated)
    assert doc.page_size(0) == (300, 200)
    doc.rotate([0], 1)
    assert doc.page_size(0) == (200, 300)
    doc.save()
    assert pypdf.PdfReader(rotated).pages[0].rotation == 180


def test_encrypted_refused(tmp_path, three):
    w = pypdf.PdfWriter(clone_from=three)
    w.encrypt("secret")
    locked = str(tmp_path / "locked.pdf")
    with open(locked, "wb") as f:
        w.write(f)
    with pytest.raises(EncryptedPdfError):
        PdfDocument.open(locked)


def test_is_pdf(tmp_path, three):
    renamed = tmp_path / "noext"
    renamed.write_bytes(open(three, "rb").read())
    assert is_pdf(three) and is_pdf(str(renamed))
    (tmp_path / "x.txt").write_text("hello")
    assert not is_pdf(str(tmp_path / "x.txt"))


def test_pageref_value():
    assert PageRef("/a.pdf", 1) == PageRef("/a.pdf", 1, 0)
