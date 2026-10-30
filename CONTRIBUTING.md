# Contributing to Glance

Thanks for your interest. Glance is a small personal project maintained in spare time, so replies can take a few
days. Bug reports, fixes and well-scoped features are all welcome.

## Before you start

- **Bugs:** open an issue with your distro and GNOME version, whether you run the Flatpak or a source build, the
  Glance version (About Glance), the file type involved, and the steps to reproduce. Attach a sample file if you can
  share one. Strip any private metadata first.
- **Features:** open an issue to discuss it before writing code. Glance aims to be Preview for GNOME: quick, common
  edits on images and PDFs. Layers, filters, painting, retouching and batch pipelines are out of scope (see
  [`docs/design.md`](docs/design.md) § 1). A short conversation up front saves you a pull request that can't be merged.
- **Small fixes** (typos, obvious bugs) can go straight to a pull request.

## Development setup

[README § Build from source](README.md#build-from-source) lists the packages. Then:

    scripts/dev [file…]     # build into _build, install into _install, and run
    meson test -C _build    # unit tests, plus desktop file, metainfo and schema checks

The pixel and page logic is plain Python with pytest coverage that runs headless. `scripts/ui-smoke` drives the real
window in a throwaway headless GNOME Shell, if you have one available. The reasoning behind the main choices (edit
model, Cairo for markup, save behaviour, shortcuts) is in [`docs/design.md`](docs/design.md). Please read the
relevant section before changing one of them.

## Pull requests

- Keep each pull request to one change. Split unrelated fixes into separate pull requests.
- `meson test -C _build` must pass. Add or update tests for logic changes in `document`, `ops`, `imageio`, `sizing`,
  `selection`, `markup` or `pdfdoc`.
- For UI changes, describe what you tested by hand and include a screenshot when the look changes.
- Match the surrounding code: its naming, comment density and structure. The UI is Blueprint (`.blp`), and the app
  follows the [GNOME Human Interface Guidelines](https://developer.gnome.org/hig/).
- Write commit messages that say what changed and why, in the imperative ("Fix crop handles on rotated images").
- Don't add a dependency without discussing it first. Glance ships as a Flatpak, and every library gets bundled.

## Licensing and sign-off

Glance is licensed under GPL-3.0-or-later, and contributions are accepted under the same license. There is no CLA.
Please sign off your commits (`git commit -s`) to certify the
[Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or otherwise have the
right to submit it under this license.

## AI-assisted contributions

AI tools are fine to use; Glance itself is developed with one. You are still the author: read and understand every
line you submit, test it, and be ready to explain and revise it in review. Mention the tool in the pull request
description. Pull requests that look generated and untested will be closed.

## Conduct

Be kind and assume good faith. Harassment and personal attacks aren't tolerated in issues, pull requests or any other
project space. The maintainer may edit or remove comments and block anyone who doesn't follow this.

## Security

Glance opens untrusted files, so decoding bugs can matter. Please report security problems privately as described in
[`SECURITY.md`](SECURITY.md), not in a public issue.
