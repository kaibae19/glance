# Security scans

Glance opens images and PDFs, often from untrusted sources. Nearly all of the code that parses those files is in
libraries the Flatpak bundles: **Pillow** (with its own copies of libjpeg, libpng, libtiff, libwebp and others),
**Poppler** and **pypdf** (PDF support, on `main` for 1.1). Everything else comes from the GNOME runtime, which Flathub
maintains and updates separately. So the scans below focus on the bundled libraries, and they run before each release.

## How to run them

Everything runs in throwaway containers; nothing is installed on the host. `APP` is an installed copy of the Flatpak.

```
APP=~/.local/share/flatpak/app/io.github.kaibae19.Glance/current/active/files

# Bundled Python libraries against the PyPI advisory database
docker run --rm python:3.14-slim sh -c 'pip install -q pip-audit;
  printf "pillow==13.0.0\npypdf==6.21.4\n" > r.txt; pip-audit -r r.txt --no-deps --disable-pip'

# The installed Flatpak, including the C libraries inside the Pillow wheel
docker run --rm -v $APP:/app:ro anchore/grype:latest dir:/app

# Glance's own code
docker run --rm -v $PWD:/src:ro python:3.14-slim sh -c 'pip install -q bandit; bandit -r /src/src'

# Secrets anywhere in the git history
docker run --rm -v $PWD:/repo:ro zricethezav/gitleaks:latest git /repo --redact

# Flathub's manifest checks
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.kaibae19.Glance.json
```

## Results

### 2026-10-30: 1.0.1 → 1.0.2

Tools: pip-audit 2.10.1, grype 0.121.0, bandit 1.9.4, gitleaks 8.30.1, flatpak-builder-lint from org.flatpak.Builder
(flatpak-builder 1.4.9).

| Check | 1.0.1 | 1.0.2 / `main` |
|---|---|---|
| Pillow (grype) | 12.1.1: **59 advisories** (5 critical, 35 high, 19 medium), all fixed in 13.0.0 | 13.0.0: **0** |
| pypdf (pip-audit), `main` only | 6.9.2: **62 advisories**, all fixed in 6.21.2 | 6.21.4: none known |
| Poppler, `main` only | 26.10.0 | 26.10.0, the current upstream release. Not matched against an advisory database: the ones checked track distribution packages, not upstream releases. |
| Glance's code (bandit) | 2 low: `assert` statements, not security-relevant | same |
| Secrets in history (gitleaks) | none in 52 commits | none |
| Manifest lint | passes | passes |

**1.0.2** (from `release-1.0`) updates the bundled Pillow to 13.0.0 and changes nothing else. `main` has the same
update plus pypdf 6.21.4. Both were tested against the new versions: the unit tests, the UI smoke test (open, edit,
markup, export, settings, and on `main` PDF open, undo and save), and ten sample images (PNG, JPEG, WebP, TIFF, GIF,
BMP) decoded inside the built Flatpak.

If you installed 1.0.0 or 1.0.1, update to 1.0.2: `flatpak update`, or install the new release bundle.
