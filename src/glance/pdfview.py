# SPDX-License-Identifier: GPL-3.0-or-later
"""The PDF view: pages in one continuous scroll, and a thumbnail sidebar for page operations.

Both lists are GtkListViews, so only visible pages exist and get rendered. Poppler draws a page with Cairo; the
surface becomes a texture directly (Cairo ARGB32 on little-endian = B8G8R8A8 premultiplied). Glance's extra
quarter turns (pdfdoc.PageRef.turns) are applied on top of the page's own /Rotate, which Poppler handles.

Sidebar, as in Preview: click/Shift/Ctrl-click to select, drag thumbnails to reorder, Delete removes, drop a PDF
file to insert its pages there.
"""

import math
import sys
from collections import OrderedDict

import cairo
import gi

gi.require_foreign("cairo")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Poppler", "0.18")
from gi.repository import Gdk, Gio, GLib, GObject, Graphene, Gtk, Poppler

MIN_ZOOM, MAX_ZOOM = 0.1, 8.0
ZOOM_STOPS = [0.1, 0.25, 0.333, 0.5, 0.667, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
PAGE_GAP = 16  # logical px between pages and around them
THUMB_WIDTH = 120
CACHE_PAGES = 48  # rendered textures kept (main view + thumbnails)
DRAG_PREFIX = "glance-pages:"

_WHITE = Gdk.RGBA()
_WHITE.parse("#ffffff")
_SHADOW = Gdk.RGBA()
_SHADOW.parse("rgba(0,0,0,0.18)")


def _render(page, turns, width, height, scale):
    """A texture of page at scale (device px per point), turned by extra quarter turns clockwise."""
    assert sys.byteorder == "little"
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, width), max(1, height))
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.scale(scale, scale)
    pw, ph = page.get_size()  # already includes the page's own /Rotate
    if turns % 4 == 1:
        cr.translate(ph, 0)
    elif turns % 4 == 2:
        cr.translate(pw, ph)
    elif turns % 4 == 3:
        cr.translate(0, pw)
    cr.rotate(turns * math.pi / 2)
    page.render(cr)
    surface.flush()
    return Gdk.MemoryTexture.new(surface.get_width(), surface.get_height(),
                                 Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                 GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())


class PageItem(GObject.Object):
    """One row of the page lists: the position in the document."""

    def __init__(self, position):
        super().__init__()
        self.position = position


class Renderer:
    """Poppler documents per source file, and an LRU of rendered textures."""

    def __init__(self):
        self._docs = {}
        self._cache = OrderedDict()

    def document(self, source):
        if source not in self._docs:
            self._docs[source] = Poppler.Document.new_from_file(GLib.filename_to_uri(source, None), None)
        return self._docs[source]

    def texture(self, ref, width, height, scale):
        key = (ref, width, height)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        page = self.document(ref.source).get_page(ref.index)
        texture = _render(page, ref.turns, width, height, scale)
        self._cache[key] = texture
        while len(self._cache) > CACHE_PAGES:
            self._cache.popitem(last=False)
        return texture


class PageWidget(Gtk.Widget):
    """One page, sized from its points and the view's zoom (or a fixed thumbnail width)."""

    __gtype_name__ = "GlancePdfPage"

    def __init__(self, view, thumbnail=False):
        super().__init__()
        self._view = view
        self._thumb = thumbnail
        self.position = None

    def bind(self, position):
        self.position = position
        self.queue_resize()

    def _size(self):
        doc = self._view.document
        if doc is None or self.position is None or self.position >= len(doc):
            return 1, 1
        w, h = doc.page_size(self.position)
        if self._thumb:
            return THUMB_WIDTH, max(1, round(THUMB_WIDTH * h / w))
        z = self._view.zoom
        return max(1, round(w * z)), max(1, round(h * z))

    def do_measure(self, orientation, for_size):
        w, h = self._size()
        size = w if orientation == Gtk.Orientation.HORIZONTAL else h
        return size, size, -1, -1

    def do_snapshot(self, snapshot):
        doc = self._view.document
        if doc is None or self.position is None or self.position >= len(doc):
            return
        w, h = self.get_width(), self.get_height()
        native = self.get_native()
        ds = native.get_surface().get_scale() if native and native.get_surface() else 1.0
        pw, _ = doc.page_size(self.position)
        texture = self._view.renderer.texture(doc.pages[self.position], round(w * ds), round(h * ds), w * ds / pw)
        bounds = Graphene.Rect().init(0, 0, w, h)
        snapshot.append_color(_SHADOW, Graphene.Rect().init(1, 2, w, h))
        snapshot.append_color(_WHITE, bounds)
        snapshot.append_texture(texture, bounds)


class PdfView(Gtk.Box):
    """Sidebar + pages. The window sets .document (a PdfDocument) and calls reload() after edits."""

    __gtype_name__ = "GlancePdfView"
    __gsignals__ = {
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "page-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "files-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),  # [paths], insert position
    }

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, **kwargs)
        self.document = None
        self.renderer = Renderer()
        self.zoom = 1.0  # logical px per point
        self.fit_width = True
        self.current_page = 0

        self._store = Gio.ListStore.new(PageItem)
        # Sidebar
        self.selection = Gtk.MultiSelection.new(self._store)
        self.selection.connect("selection-changed", lambda *_: self.emit("selection-changed"))
        thumb_factory = Gtk.SignalListItemFactory()
        thumb_factory.connect("setup", self._thumb_setup)
        thumb_factory.connect("bind", self._thumb_bind)
        self.sidebar = Gtk.ListView(model=self.selection, factory=thumb_factory, css_classes=["navigation-sidebar"])
        self.sidebar.connect("activate", lambda _l, pos: self.go_to(pos))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_sidebar_key)
        self.sidebar.add_controller(keys)
        files = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        files.connect("drop", lambda _t, value, _x, _y: self._drop_files(value, len(self.document or ())))
        self.sidebar.add_controller(files)
        sidebar_scroll = Gtk.ScrolledWindow(child=self.sidebar, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                            width_request=THUMB_WIDTH + 48)
        self.append(sidebar_scroll)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Pages
        page_factory = Gtk.SignalListItemFactory()
        page_factory.connect("setup", self._page_setup)
        page_factory.connect("bind", self._page_bind)
        self.pages = Gtk.ListView(model=Gtk.NoSelection.new(self._store), factory=page_factory,
                                  css_classes=["glance-pdf-pages"], hexpand=True, vexpand=True)
        self.pages_scroll = Gtk.ScrolledWindow(child=self.pages, hexpand=True, vexpand=True)
        self.pages_scroll.get_vadjustment().connect("value-changed", lambda *_: self._track_page())
        zoom_keys = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        zoom_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        zoom_keys.connect("scroll", self._on_scroll)
        self.pages_scroll.add_controller(zoom_keys)
        self.append(self.pages_scroll)
        self._bound_pages = set()

        provider = Gtk.CssProvider()
        provider.load_from_string(".glance-pdf-pages, .glance-pdf-pages > row { background: none; padding: 0; }"
                                  ".glance-pdf-pages > row:hover, .glance-pdf-pages > row:selected"
                                  " { background: none; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # --- document ---------------------------------------------------------------------------

    def set_document(self, document):
        self.document = document
        self.fit_width = True
        self.current_page = 0
        self.reload()
        GLib.idle_add(self._apply_fit)

    def reload(self, select=None):
        """Rebuild both lists from the document (after an edit or undo). select: positions to select after."""
        n = len(self.document) if self.document else 0
        self._store.remove_all()
        for i in range(n):
            self._store.append(PageItem(i))
        self.current_page = min(self.current_page, max(0, n - 1))
        select = [i for i in (select or ()) if 0 <= i < n] or ([self.current_page] if n else [])
        for i in select:
            self.selection.select_item(i, False)
        self.emit("page-changed")

    def _follow(self, position):
        """As in Preview, a single selection follows the current page, so what Delete or Rotate will act on is
        always highlighted; a multiple selection stays put."""
        if len(self.selected_positions()) <= 1:
            self.selection.select_item(position, True)

    def selected_positions(self):
        bits = self.selection.get_selection()
        return [bits.get_nth(i) for i in range(bits.get_size())]

    def target_positions(self):
        """The selected pages, or the current one when nothing is selected."""
        return self.selected_positions() or ([self.current_page] if self.document else [])

    # --- zoom and navigation ----------------------------------------------------------------

    def _apply_fit(self):
        if self.fit_width and self.document and len(self.document):
            width = self.pages_scroll.get_width() - 2 * PAGE_GAP - 16
            if width > 0:
                widest = max(self.document.page_size(i)[0] for i in range(min(len(self.document), 50)))
                self._set_zoom(width / widest, keep_fit=True)
        return False

    def _set_zoom(self, zoom, keep_fit=False):
        zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        if not keep_fit:
            self.fit_width = False
        if abs(zoom - self.zoom) < 1e-6:
            return
        page = self.current_page
        self.zoom = zoom
        for widget in list(self._bound_pages):
            widget.queue_resize()
        GLib.idle_add(lambda: (self.go_to(page, select=False), False)[1])
        self.emit("zoom-changed")

    def zoom_in(self):
        self._set_zoom(next((z for z in ZOOM_STOPS if z > self.zoom * 1.01), MAX_ZOOM))

    def zoom_out(self):
        self._set_zoom(next((z for z in reversed(ZOOM_STOPS) if z < self.zoom / 1.01), MIN_ZOOM))

    def zoom_actual(self):
        self._set_zoom(1.0)

    def zoom_fit(self):
        self.fit_width = True
        self._apply_fit()

    def do_size_allocate(self, width, height, baseline):
        Gtk.Box.do_size_allocate(self, width, height, baseline)
        if self.fit_width:
            GLib.idle_add(self._apply_fit)

    def go_to(self, position, select=True):
        if not self.document or not 0 <= position < len(self.document):
            return
        self.pages.scroll_to(position, Gtk.ListScrollFlags.NONE, None)
        self.current_page = position
        if select:
            self.sidebar.scroll_to(position, Gtk.ListScrollFlags.NONE, None)
            self._follow(position)
        self.emit("page-changed")

    def step(self, delta):
        self.go_to(self.current_page + delta)

    def _track_page(self):
        """The current page is the one nearest the top of the scrolled area."""
        best, best_y = None, None
        for widget in self._bound_pages:
            if widget.position is None or not widget.get_mapped():
                continue
            ok, point = widget.compute_point(self.pages_scroll, Graphene.Point().init(0, 0))
            if not ok:
                continue
            y = point.y + widget.get_height() / 2
            if y >= 0 and (best_y is None or y < best_y):
                best, best_y = widget.position, y
        if best is not None and best != self.current_page:
            self.current_page = best
            self._follow(best)
            self.emit("page-changed")

    def _on_scroll(self, controller, _dx, dy):
        if controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            self._set_zoom(self.zoom * math.exp(-dy * 0.2))
            return True
        return False

    # --- list rows --------------------------------------------------------------------------

    def _page_setup(self, _factory, item):
        widget = PageWidget(self)
        widget.set_halign(Gtk.Align.CENTER)
        widget.set_margin_top(PAGE_GAP // 2)
        widget.set_margin_bottom(PAGE_GAP // 2)
        item.set_child(widget)
        self._bound_pages.add(widget)

    def _page_bind(self, _factory, item):
        item.get_child().bind(item.get_item().position)

    def _thumb_setup(self, _factory, item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6)
        page = PageWidget(self, thumbnail=True)
        page.set_halign(Gtk.Align.CENTER)
        label = Gtk.Label(css_classes=["caption", "dim-label"])
        box.append(page)
        box.append(label)
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", self._drag_prepare, page)
        box.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", self._drop_pages, page)
        box.add_controller(drop)
        files = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        files.connect("drop", lambda _t, value, _x, y: self._drop_files(
            value, page.position + (1 if y > box.get_height() / 2 else 0)))
        box.add_controller(files)
        item.set_child(box)

    def _thumb_bind(self, _factory, item):
        box = item.get_child()
        position = item.get_item().position
        box.get_first_child().bind(position)
        box.get_last_child().set_label(str(position + 1))

    # --- drag and drop ----------------------------------------------------------------------

    def _drag_prepare(self, _source, _x, _y, page):
        selected = self.selected_positions()
        moving = selected if page.position in selected else [page.position]
        return Gdk.ContentProvider.new_for_value(DRAG_PREFIX + ",".join(map(str, moving)))

    def _drop_pages(self, target, value, _x, y, page):
        if not isinstance(value, str) or not value.startswith(DRAG_PREFIX) or page.position is None:
            return False
        moving = [int(v) for v in value[len(DRAG_PREFIX):].split(",") if v]
        box = target.get_widget()
        to = page.position + (1 if y > box.get_height() / 2 else 0)
        self.move_pages(moving, to)
        return True

    def move_pages(self, moving, to):
        """Move pages (drag and drop, or the smoke test) and keep them selected at their new place."""
        doc = self.document
        before = sum(1 for i in moving if i < to)
        doc.move(moving, to)
        start = max(0, min(to - before, len(doc) - len(moving)))
        self.reload(select=range(start, start + len(set(moving))))

    def _drop_files(self, value, at):
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        if paths:
            self.emit("files-dropped", paths, at)
        return bool(paths)

    def _on_sidebar_key(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace, Gdk.KEY_KP_Delete):
            self.activate_action("win.delete-pages", None)
            return True
        return False
