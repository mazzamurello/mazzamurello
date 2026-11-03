"""The web app loads everything from the instance (OBS-006, ADR-0072, ADR-0070).

The built app is read as files: its pages, styles, manifest and the list of
files the service worker caches. None may name a script, style, font, icon
or image on another origin, and the fonts are part of the build.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# A reference to another origin: an absolute or protocol-relative URL.
REMOTE = re.compile(r"""(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", re.IGNORECASE)
# Where pages and styles load resources from.
HTML_REFERENCES = re.compile(
    r"""<(?:script|link|img|source|iframe)\b[^>]*?\b(?:src|href|srcset)\s*=\s*["']([^"']+)""", re.I
)
CSS_REFERENCES = re.compile(r"""(?:url\(\s*["']?|@import\s+["'])([^"')]+)""", re.IGNORECASE)


def _remote(references: list[str]) -> list[str]:
    return [reference for reference in references if REMOTE.match(reference.strip())]


@pytest.mark.spec("OBS-006")
def test_pages_and_styles_reference_only_the_instance(web_build: Path) -> None:
    offenders: list[str] = []
    for page in web_build.rglob("*.html"):
        offenders += [f"{page.name}: {ref}" for ref in _remote(HTML_REFERENCES.findall(page.read_text()))]
    for style in web_build.rglob("*.css"):
        offenders += [f"{style.name}: {ref}" for ref in _remote(CSS_REFERENCES.findall(style.read_text()))]
    assert offenders == []


@pytest.mark.spec("OBS-006")
def test_the_manifest_and_the_offline_cache_name_only_local_files(web_build: Path) -> None:
    manifest = json.loads((web_build / "manifest.webmanifest").read_text())
    assert _remote([icon["src"] for icon in manifest["icons"]]) == []
    worker = (web_build / "sw.js").read_text()
    cached = re.findall(r"""url\s*:\s*["']([^"']+)""", worker)
    assert cached, "the service worker caches nothing"
    assert _remote(cached) == []


@pytest.mark.spec("OBS-006")
def test_the_fonts_are_part_of_the_app(web_build: Path) -> None:
    fonts = [path.name for path in web_build.rglob("*") if path.suffix in {".woff2", ".woff"}]
    for family in ("hanken", "newsreader", "jetbrains"):
        assert any(family in name.lower() for name in fonts), f"no {family} font in the build: {sorted(fonts)}"
