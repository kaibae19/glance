# Security policy

Glance decodes images and PDFs, often from untrusted sources, through Pillow, Poppler and pypdf.

## Reporting a vulnerability

Please use GitHub's private reporting: **Security → Report a vulnerability** on this repository. Don't open a public
issue. Include the Glance version, how you run it (Flatpak or source), and a sample file or steps that reproduce the
problem.

You can expect an acknowledgement within a week. Glance is a spare-time project, so a fix may take longer, and you'll
be kept informed. If the bug is in Pillow, Poppler or pypdf rather than in Glance, it will be passed upstream, with
credit to you if you want it.

## Supported versions

Only the latest release and `main` get fixes.

## Scans

Each release is checked for known vulnerabilities in the bundled libraries, for secrets in the history, and with
Flathub's linter. How to run the scans and the latest results: [docs/security-scans.md](docs/security-scans.md).
