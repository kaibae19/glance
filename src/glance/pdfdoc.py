# SPDX-License-Identifier: GPL-3.0-or-later
"""An open PDF as a list of page references, with undo/redo; pypdf writes it on Save. No GTK here.

A page is (source file, page index in it, extra quarter turns). Reorder, delete, rotate and insert only change that
list, so nothing touches a file until Save, and undo is free. Rendering is the view's job (Poppler).
"""

import os
from dataclasses import dataclass, replace

import pypdf

from . import imageio


class EncryptedPdfError(Exception):
    """A password-protected PDF: Glance can't edit it (yet)."""


@dataclass(frozen=True)
class PageRef:
    source: str  # absolute path of the PDF the page comes from
    index: int  # page number in that file, from 0
    turns: int = 0  # extra quarter turns clockwise, on top of the page's own /Rotate


def is_pdf(path):
    if os.path.splitext(path)[1].lower() == ".pdf":
        return True
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


class PdfDocument:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._readers = {}
        reader = self.reader(self.path)
        self.metadata = reader.metadata
        first = tuple(PageRef(self.path, i) for i in range(len(reader.pages)))
        self._states = [first]
        self._index = 0
        self._saved = first
        self._listeners = []

    @classmethod
    def open(cls, path):
        return cls(path)

    def reader(self, source):
        if source not in self._readers:
            reader = pypdf.PdfReader(source)
            if reader.is_encrypted and not reader.decrypt(""):
                raise EncryptedPdfError(source)
            self._readers[source] = reader
        return self._readers[source]

    def connect(self, callback):
        self._listeners.append(callback)

    def _changed(self):
        for callback in self._listeners:
            callback(self)

    # --- state ------------------------------------------------------------------------------

    @property
    def pages(self):
        return self._states[self._index]

    def __len__(self):
        return len(self.pages)

    @property
    def dirty(self):
        return self.pages != self._saved

    @property
    def can_undo(self):
        return self._index > 0

    @property
    def can_redo(self):
        return self._index < len(self._states) - 1

    def page_size(self, i):
        """(width, height) in points as displayed: the page's own /Rotate and the extra turns applied."""
        ref = self.pages[i]
        page = self.reader(ref.source).pages[ref.index]
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        if ((page.rotation // 90) + ref.turns) % 2:
            w, h = h, w
        return w, h

    # --- editing (each is one undo step) ----------------------------------------------------

    def _push(self, pages):
        pages = tuple(pages)
        if pages == self.pages:
            return
        self._states = self._states[:self._index + 1] + [pages]
        self._index += 1
        self._changed()

    def move(self, indices, to):
        """Move the pages at indices (kept in their order) so they start at position to (counted before the move)."""
        chosen = sorted(set(indices))
        moving = [self.pages[i] for i in chosen]
        rest = [p for i, p in enumerate(self.pages) if i not in chosen]
        to -= sum(1 for i in chosen if i < to)
        to = max(0, min(to, len(rest)))
        self._push(rest[:to] + moving + rest[to:])

    def delete(self, indices):
        chosen = set(indices)
        if len(chosen) >= len(self.pages):
            raise ValueError("a PDF needs at least one page")
        self._push(p for i, p in enumerate(self.pages) if i not in chosen)

    def rotate(self, indices, turns):
        chosen = set(indices)
        self._push(replace(p, turns=(p.turns + turns) % 4) if i in chosen else p for i, p in enumerate(self.pages))

    def insert(self, at, source):
        """Insert every page of the PDF at source before position at. Returns how many."""
        source = os.path.abspath(source)
        count = len(self.reader(source).pages)
        new = [PageRef(source, i) for i in range(count)]
        at = max(0, min(at, len(self.pages)))
        self._push(list(self.pages[:at]) + new + list(self.pages[at:]))
        return count

    def undo(self):
        if self.can_undo:
            self._index -= 1
            self._changed()

    def redo(self):
        if self.can_redo:
            self._index += 1
            self._changed()

    # --- saving -----------------------------------------------------------------------------

    def save(self, path=None):
        """Write the page list to path (default: over the original), atomically."""
        target = os.path.abspath(path or self.path)
        writer = pypdf.PdfWriter()
        for ref in self.pages:
            page = writer.add_page(self.reader(ref.source).pages[ref.index])
            if ref.turns:
                page.rotate(ref.turns * 90)
        if self.metadata:
            writer.add_metadata({k: v for k, v in self.metadata.items() if isinstance(v, str)})
        imageio.write_atomic(target, writer.write)
        # Keep reading the old bytes: open readers hold the replaced file's inode, so history stays valid.
        self.path = target
        self._saved = self.pages
        self._changed()


def describe(doc, current):
    """Rows for the Info popover: [(label, value)]."""
    rows = [("Name", os.path.basename(doc.path)), ("Pages", str(len(doc)))]
    if len(doc):
        w, h = doc.page_size(current)
        rows.append((f"Page {current + 1}", f"{w:.0f} × {h:.0f} pt ({w / 72 * 25.4:.0f} × {h / 72 * 25.4:.0f} mm)"))
    meta = doc.metadata or {}
    for key, label in (("/Title", "Title"), ("/Author", "Author"), ("/Producer", "Producer")):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            rows.append((label, value.strip()))
    try:
        rows.append(("File size", imageio.format_size(os.path.getsize(doc.path))))
    except OSError:
        pass
    return rows
