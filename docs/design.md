# Glance — Design Guide

*2026-10-28 · Kailey · design guide*

Glance is a macOS-Preview-style image viewer and quick editor for GNOME, built in Python with GTK4 and
libadwaita. v1 views, resizes, crops, rotates, converts and annotates images. PDF tools come later.

---

## 1. Why it exists

GNOME has no single app for the everyday image jobs that Preview does on a Mac. It started on 2026-10-27 with
resizing an icon to 400×400, which took more apps than it should have.

- **Need:** open an image, make a quick change, save it. Loupe only views. Pinta, Switcheroo and GIMP each
  cover one slice, and GIMP is far too heavy for a resize.
- **For:** quick, common edits: resize, crop, rotate, convert, mark up a screenshot.
- **Not for:** layers, filters, painting, retouching or batch pipelines. Those stay with GIMP, Pinta or
  ImageMagick.
- **Retire if:** Loupe (or another GNOME app) grows Adjust Size, crop and markup well enough.
- **Status:** a personal side project.

## 2. Decisions so far

| Decision | Choice | Why | Status |
|---|---|---|---|
| Language | Python 3 + PyGObject | Fastest path to a working v1; GTK bindings are first-class | Decided 2026-10-27 |
| Toolkit | GTK4 + libadwaita | Native GNOME look, dark mode for free, adaptive layouts | Decided 2026-10-27 |
| Name | **Glance** (working name) | *Peek* is an existing GIF recorder; *Loupe+* is confusable with GNOME Loupe | Decided 2026-10-27 |
| Repo home | GitHub `kaibae19/glance`, mirrored from a personal Gitea | Personal project | Decided 2026-10-27; public mirror 2026-10-29 |
| App ID | `io.github.kaibae19.Glance` | GitHub-based ID, verified through the GitHub account (Flathub) | Since 1.0.1 (2026-10-29) |
| Pixel engine | Pillow; markup drawn with Cairo + Pango, composited by Pillow | Smooth shapes and real text; premultiplied ARGB read as Pillow "RGBa" | Decided 2026-10-28 |
| Edit model | Operation list over the untouched original | Free undo/redo, nothing written until Save | Built 2026-10-28 (v0.2) |
| License | GPL-3.0-or-later | The GNOME norm | Decided 2026-10-28 |
| Shortcuts | Preview's ⌘ keys on **Ctrl** (⌘L → Ctrl+L …); no Super bindings | GNOME Shell owns Super+S/L/A/V/N/P/1–9; Ctrl is close enough | Decided 2026-10-28 |
| Save | Explicit **Save** (asks once per image before replacing the original) + **Save As** (Ctrl+Shift+S, Preview's Ctrl+Alt+Shift+S); no autosave | The safer save | Decided 2026-10-28 |
| Shortcut phases | Keys text fields use (arrows, Ctrl+A, Ctrl+Z) are bubble-phase window shortcuts, the rest app accels | GTK runs app accels in the capture phase, ahead of the focused widget (checked 2026-10-28) | Built 2026-10-28 |
| Reference platform | Ubuntu 26.04, GNOME 50, GTK 4.22, libadwaita 1.9 | What it's developed and tested on | Decided 2026-10-28 |

⚠ **Name collision to know about:** "Glance" is also a popular self-hosted dashboard (glanceapp/glance).
It's a different category, so it's fine as a working name, but check again before a Flathub submission.

## 3. v1 features

| Tool | Behaviour |
|---|---|
| **View** | Open from file chooser, drag-and-drop or "Open With". Fit to window by default; zoom with Ctrl+scroll, pinch or Ctrl+=/−; actual size with Ctrl+0 (full list in §6). Transparent areas drawn on a checkerboard. Left/Right steps through the other images in the same folder. |
| **Adjust Size** | Dialog: width, height, unit (px or %), lock-aspect toggle (on by default), resampling (Lanczos default; Nearest for pixel art). Shows resulting dimensions and an estimated file size. *The 400×400 icon case is the acceptance test.* |
| **Crop** | Drag a selection on the canvas; handles to adjust; optional fixed ratio (free, 1:1, 4:3, 16:9, original). Enter or Ctrl+K applies (Preview's key). Selection size shown live in px. |
| **Rotate / flip** | Rotate left/right 90° (Ctrl+L / Ctrl+R), flip horizontal/vertical. Lossless as operations; applied once at save. |
| **Export / convert** | "Export As…" chooses format (PNG, JPEG, WebP, TIFF, BMP, GIF, AVIF if Pillow supports it on the system), with quality slider for lossy formats. Warns when the target format drops alpha (e.g. PNG → JPEG) and offers a background colour to flatten onto. |
| **Quick annotate** | Markup toolbar: rectangle, ellipse, arrow, line, text, highlight. Colour and stroke-width pickers. Shapes stay editable (move, resize, delete) until saved; they are flattened into pixels only on export. |
| **Info** | Side panel or popover: dimensions, format, file size, colour mode, DPI, EXIF summary. |

**Save semantics (Preview-like but safer):** Ctrl+S overwrites the original in its own format after the
first-time confirmation; Shift+Ctrl+S is Save As (Shift+Ctrl+Alt+S, Preview's chord, works too). Export has no shortcut. Closing with unsaved operations asks. No auto-save in v1.

## 4. Architecture

```
          ┌──────────────┐  open   ┌──────────────────────┐
 file ───▶│  Document    │────────▶│ original: PIL.Image  │
          │ (model)      │         │ ops: [Op, Op, …]     │◀── undo/redo stack
          └──────┬───────┘         └──────────┬───────────┘
                 │ render(ops)                │ export(ops, fmt)
                 ▼                            ▼
          ┌──────────────┐            ┌──────────────┐
          │ Canvas       │            │ Exporter     │──▶ file
          │ (Gtk widget) │            │ (Pillow)     │
          └──────┬───────┘            └──────────────┘
                 │ overlays: crop box, annotation handles
          ┌──────┴───────┐
          │ Tools        │  view · crop · markup  (each a controller on the canvas)
          └──────────────┘
```

| Component | Responsibility | Built on |
|---|---|---|
| `Application` | App lifecycle, actions, shortcuts, open-file handling | `Adw.Application` |
| `Window` | Header bar, toolbar, canvas, toasts, info panel | `Adw.ApplicationWindow`, `Adw.ToolbarView`, `Adw.ToastOverlay` |
| `Document` | Original image + operation list + undo/redo + dirty flag + path | Pillow `Image` |
| `Op` classes | `Crop`, `Rotate`, `Flip`, `Resize`, `Annotate(shapes)`; each has `apply(img) -> img` | Pillow |
| `Canvas` | Shows the rendered image, zoom/pan, draws overlays | `Gtk.Widget` subclass with `do_snapshot`, `Gdk.MemoryTexture`, `Gtk.GestureZoom`/`GestureDrag`, `Gtk.EventControllerScroll` |
| Tools | Input handling per mode (view, crop selection, markup shapes) | Gesture controllers attached to the canvas |
| Dialogs | Adjust Size, Export options, unsaved-changes prompt | `Adw.Dialog`, `Adw.AlertDialog`, `Gtk.FileDialog` |
| `Exporter` | Format choice, quality, alpha flattening, metadata policy | Pillow `Image.save` |

**The edit model (proposed).** The original is never modified in memory. Each edit appends an `Op`. The
rendered image is `reduce(apply, ops, original)`, cached after the last op so a new op only applies itself.
Undo pops an op and re-renders from a cached checkpoint. This makes undo trivial and keeps rotates and
flips lossless until Save.

- Annotations are **one `Annotate` op holding a list of vector shapes**, kept editable while the markup tool
  is active, and rasterised only at render/export.
- Render for display at screen resolution only when the image is huge (downscale the preview, apply ops to
  the full image only on export) — a later optimisation, not v1.
- Coordinates: shapes and crop rects are stored in **image pixel coordinates**, never widget coordinates, so
  zoom never changes them.

## 5. Image handling — traps to design for up front

- **Transparency:** keep `RGBA` end to end. Convert Pillow → texture with `Gdk.MemoryTexture` in
  `R8G8B8A8` (straight alpha), so there is no premultiplication bug. If Cairo is used for annotation rendering,
  remember Cairo `ARGB32` is **premultiplied BGRA in native byte order** — convert carefully or draw shapes
  with Pillow's `ImageDraw` instead (simpler, one engine).
- **EXIF orientation:** apply `ImageOps.exif_transpose()` on open, or phone photos appear sideways. On save,
  write orientation = 1 (or drop the tag) so it isn't applied twice.
- **Palette / mode images:** `P`, `LA`, `I;16`, `CMYK` — convert to `RGBA`/`RGB` for editing; warn if
  saving would change the mode (e.g. a 16-bit PNG).
- **Colour profiles:** preserve the source ICC profile on save (`icc_profile=img.info.get("icc_profile")`).
  Display-side colour management is out of scope for v1.
- **Metadata:** keep EXIF by default on Save; Export offers "strip metadata" (useful for screenshots and
  privacy).
- **Formats:** Pillow covers PNG, JPEG, WebP, GIF, TIFF, BMP, ICO. HEIC needs `pillow-heif`; AVIF depends on
  the Pillow build. Show only formats the running Pillow can actually write (`Image.SAVE`).
- **Animated GIF/WebP:** v1 shows frame 1 and refuses to save over an animated file (warn instead of silently
  flattening it).
- **Large images:** decode off the main thread (`GLib` thread + `idle_add`) so the window never freezes.
- **Glycin** (GNOME's sandboxed loader that Loupe uses) is worth a look later for safe decoding of untrusted
  files and extra formats, but Pillow as the single decoder keeps display and export identical in v1.

## 6. Window and shortcuts

Layout: `Adw.HeaderBar` with Open, the file name as the title (dimensions as subtitle), zoom controls, and a
"Markup" toggle that reveals a second toolbar row. Main area is the canvas; an optional right-hand info
sidebar (`Adw.OverlaySplitView`). Errors and confirmations ("Saved", "Exported as WebP") come as toasts.

| Action | Shortcut | Preview equivalent |
|---|---|---|
| Open | Ctrl+O | ⌘O |
| Save | Ctrl+S | ⌘S |
| Save As | Shift+Ctrl+S (also Shift+Ctrl+Alt+S) | ⌥⇧⌘S |
| Export | none | File → Export |
| Undo / Redo | Ctrl+Z / Shift+Ctrl+Z | ⌘Z / ⇧⌘Z |
| Zoom in / out | Ctrl+= / Ctrl+− (and Ctrl+scroll, pinch) | ⌘+ / ⌘− |
| Actual size | Ctrl+0 | ⌘0 |
| Fit to window | Ctrl+9 (proposed) | ⌘9 |
| Rotate left / right | Ctrl+L / Ctrl+R | ⌘L / ⌘R |
| Adjust Size | Ctrl+Alt+I (proposed) | Tools → Adjust Size (no default shortcut, as far as I know) |
| Crop to selection | Ctrl+K | ⌘K |
| Markup toolbar | Shift+Ctrl+A | ⇧⌘A |
| Info | Ctrl+I | ⌘I |
| Previous / next image | Left / Right | ← / → |
| Fullscreen | F11 | ⌃⌘F |

## 7. Project layout and dev setup

Use the standard GNOME **meson** layout (what GNOME Builder's "Python / GTK4 / libadwaita" template
generates) — it handles the `.desktop` file, icons, GSettings schema, metainfo and the Flatpak build in the
expected way.

```
glance/
├── meson.build
├── io.github.kaibae19.Glance.json        # Flatpak manifest
├── data/
│   ├── io.github.kaibae19.Glance.desktop.in
│   ├── io.github.kaibae19.Glance.metainfo.xml.in
│   ├── io.github.kaibae19.Glance.gschema.xml   # window size, last export format/quality
│   └── icons/
├── po/
├── src/
│   ├── meson.build
│   ├── glance.in              # launcher script
│   ├── main.py                # Adw.Application
│   ├── window.py / window.blp # UI in Blueprint (or .ui XML)
│   ├── document.py            # original + ops + undo
│   ├── ops.py                 # Crop, Rotate, Flip, Resize, Annotate
│   ├── canvas.py              # zoom/pan/overlays
│   ├── tools/                 # crop.py, markup.py
│   ├── dialogs/               # adjust_size.py, export.py
│   └── exporter.py
└── tests/                     # pytest for ops/document/exporter (no display needed)
```

**Testing split:** `document`, `ops` and `exporter` are pure Pillow and get pytest coverage that runs
headless. Only the UI needs a GNOME session.

**Version floor: libadwaita ≥ 1.5 (GNOME 46).** `Adw.ToolbarView` needs 1.4 and `Adw.Dialog` needs 1.5.
That rules out Debian 12 (libadwaita 1.2).

| Distro | Packages for running from source |
|---|---|
| Fedora 40+ | `python3-gobject gtk4 libadwaita python3-pillow meson blueprint-compiler` |
| Ubuntu 24.04+ / Debian 13 | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-pil meson blueprint-compiler` |
| Arch | `python-gobject gtk4 libadwaita python-pillow meson blueprint-compiler` |
| Any (preferred for release) | Flatpak, `org.gnome.Platform` / `org.gnome.Sdk` runtime 47+, Pillow as a pip module in the manifest |

Run during dev: `meson setup build && meson compile -C build && meson devenv -C build glance` — or open the
folder in GNOME Builder and press Run.

## 8. Milestones

1. ✅ 2026-10-28 **v0.1 — viewer.** Open, drag-and-drop, fit/zoom/pan, checkerboard alpha, folder navigation, info popover.
2. ✅ 2026-10-28 **v0.2 — document model.** `Document` + ops + undo/redo; rotate and flip; Save with orientation reset.
   pytest suite for ops.
3. ✅ 2026-10-28 **v0.3 — Adjust Size.** The dialog, aspect lock, units, resampling. *Done when the 400×400 icon job takes
   under 10 seconds.* Headless `scripts/ui-smoke`: open → resized + saved in 1.6 s scripted; still to time by hand.
4. ✅ 2026-10-28 **v0.4 — crop.** Selection overlay, handles, ratio presets, Ctrl+K. Drag selects (as in Preview);
   panning moved to scroll and middle-drag. Ratio presets orient to the drag (4:3 gives 3:4 when dragged tall).
5. ✅ 2026-10-28 **v0.5 — export / convert.** Format list from Pillow, quality, alpha-flatten warning, metadata strip.
   Like Preview's File → Export, it writes a copy and the document keeps its file. Options sheet first, then the file
   chooser (GTK's can't hold extra controls). The distro Pillow used in development has no AVIF, so it isn't offered. Options are remembered
   for the run only (GSettings in v1.0).
6. ✅ 2026-10-28 **v0.6 — markup.** Shapes, text, colours, editable until flattened. Drawn with Cairo + Pango
   (nicer antialiased shapes and text), one module for screen and file. Rectangle, oval, line, arrow,
   highlight, text; 8 swatches + custom; thin/medium/thick scaled to the image; Shift = square/circle or 45°.
   History became a list of states so each shape edit is one undo step (`Document.amend`). Shapes stay
   editable while the markup layer is the last edit (also after Save); a later rotate/crop/resize flattens them.
   Known limits: each shape edit re-rasterises the whole image on the main thread (slow on very large photos);
   text is typed in a popover (it previews live on the image), not inline; no fill colour or Preview's extra
   shapes (bubble, star, loupe).
   After the first hands-on session (2026-10-28: retyping worked, text formatting was missing):
   font button (family + style) and size field for text; the bar follows the selected shape, so changing colour,
   weight, font or size restyles it; text corners scale it; first placed text shows a hint toast.
7. ✅ 2026-10-28 **v1.0 — polish + Flatpak.** Icon, metainfo, desktop integration ("Open With"), Flatpak manifest building
   from the repo. GPL-3.0-or-later. GSettings for window size and export choices; Keyboard Shortcuts
   dialog built from the binding tables; metainfo passes `appstreamcli validate`. Flatpak: GNOME 51 runtime
   (Python 3.14, pycairo 1.29, blueprint-compiler 0.22.2 in the SDK), Pillow 12.1.1 wheels (bring AVIF),
   `--filesystem=host` for folder stepping and saving beside the original. Built with Flathub's
   `org.flatpak.Builder` (user install, `--disable-rofiles-fuse` inside its sandbox) and installed for the user
   from a local repo. The manifest builds the current checkout (`dir` source); a `git` source pointing at the
   public repo is the step before a Flathub submission.
8. **PDF.** View, reorder pages, merge, sign (likely `poppler` GI for render + `pypdf` for edits).
   ✅ 2026-10-28 **step 1 — view and page operations.** Poppler (GPL-2.0-or-later) renders, pypdf (BSD) writes;
   PyMuPDF was passed over for its AGPL. A PDF is a list of (source file, page, extra quarter turns), so reorder,
   delete, rotate and insert (Insert Pages from File…, or drop PDFs on the sidebar) are undoable and touch no
   file until Save / Save As. Continuous pages and thumbnails are virtualised GtkListViews; Cairo surfaces
   become textures directly. As in Preview, a single sidebar selection follows the current page, so what
   Delete/Rotate act on is always highlighted. Fit width uses the median page width (one landscape page doesn't
   shrink the rest); the sideways scroll stays centred. Password-protected PDFs are refused. Flatpak builds
   Poppler 26.10.0 (GLib + introspection only) and bundles pypdf 6.9.2.
   Next steps (not started): find and text selection; markup on pages (as PDF annotations); signatures; forms.

## 9. Open questions for the first dev session

- [ ] **Other metadata:** Save and Export deliberately carry EXIF, the ICC profile and DPI. XMP, PNG text chunks
      and comments aren't carried on purpose; whether Pillow passes any of them through on its own is unchecked.


- [ ] **Edit model:** operation list (proposed, non-destructive until Save) versus applying edits straight to
      the image the way Preview *feels*. The op list can still feel immediate — it's a UX question, not just
      an architecture one.
- [ ] **Save behaviour:** overwrite in place on Ctrl+S (Preview), or always Save-As for the first save?
- [ ] **UI definition:** Blueprint (`.blp`, terser) or plain GtkBuilder `.ui` XML?
- [ ] **Annotation renderer:** Pillow `ImageDraw` (one engine, simpler) or Cairo (nicer antialiased text and
      arrows, but premultiplied-alpha conversion)?
- [x] **App ID** `io.github.kaibae19.Glance` (since 1.0.1, for Flathub).
- [x] **Dev platform:** Ubuntu 26.04 / GNOME 50 (libadwaita ≥ 1.5 needed).

## 10. Status (2026-10-29)

**State.** v1.0.0 tagged (`v1.0.0`), plus PDF step 1 on `main` after it (not tagged; version still 1.0.0).
Image editing has had hands-on use; PDF hasn't been tried by hand yet.

**Dev loop:** `scripts/dev <file>` (build into `_build`, install into `_install`, run); `meson test -C _build`
(unit, desktop file, metainfo, gschema); `scripts/ui-smoke [dir]` drives the real window in a throwaway headless
GNOME Shell and leaves screenshots; `scripts/headless-shot out.png <file>`. Flatpak: README § Install.

**Untested by hand** (headless runs call the same code, not real input)
- Mouse: crop handles, shape dragging, Shift snapping; PDF thumbnail drag-reorder and dropping files on the sidebar.
- Keys: arrow keys inside Adjust Size fields (the capture-phase fix), Enter in dialogs.
- The file chooser and portal paths (Open, Save As, Export, Insert Pages) and "Open With" from Files.
- Large real-world PDFs (speed, memory, odd page boxes).

**Known limits**
- Each markup edit re-rasterises the whole image on the main thread; slow on very large photos.
- Text is typed in a popover (live preview on the image), not inline. No fill colour; none of Preview's extra shapes.
- Save/Export carry EXIF, ICC and DPI; XMP / PNG text / comments are not carried on purpose and unchecked otherwise.
- PDF: password-protected files are refused. Save keeps basic metadata (title, author, …) but bookmarks and links
  are probably lost when pages are rearranged (unchecked). No find, text selection or annotations yet.
- Multi-monitor: a window opened from Files is sized for the first monitor.

**Next**
1. PDF step 2: find and text selection (Poppler `find_text`, `get_text_layout`).
2. PDF step 3: markup on pages, saved as real PDF annotations (Preview does), not flattened.
3. PDF step 4: signatures, then forms.
4. Tag `v1.1.0` once PDF has been tried on real files; update metainfo releases.
