"""The README's screenshots must be the ones in this checkout.

They were absolute links to another repository's `main` branch, so a branch's
new screenshots never showed on GitHub and a new one (the split view) showed as
a broken image. Relative links render from whatever branch and repo is being
viewed; the publish workflow rewrites them to the release tag for PyPI, which
cannot follow relative links.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _readme_images() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return re.findall(r'<img[^>]*\bsrc="([^"]+)"', text) + re.findall(r"!\[[^\]]*\]\(([^)\s]+)", text)


def test_readme_screenshots_are_relative_and_exist():
    # Badges (shields.io) are external by nature; screenshots are ours.
    shots = [s for s in _readme_images() if "docs/images/" in s]
    assert len(shots) >= 4, shots
    for src in shots:
        assert not src.startswith(("http://", "https://")), f"absolute screenshot link: {src}"
        assert (ROOT / src).is_file(), f"README screenshot missing from the repo: {src}"


def test_publish_workflow_pins_readme_images_to_the_release():
    wf = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "docs/images/" in wf and "github.ref_name" in wf
    assert wf.index("docs/images/") < wf.index("python -m build"), "rewrite must run before the build"
