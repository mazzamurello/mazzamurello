"""The web client's strings come from translation resources (I18N-001, ADR-0067)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.support.database import ROOT

SOURCES = ROOT / "src" / "web" / "src"
ENGLISH = SOURCES / "locales" / "en.json"
# Text between JSX tags on one line, outside any `{expression}`, with a word in
# it; a `>` of `=>` or `->` and code characters are not JSX text.
JSX_TEXT = re.compile(r"(?<![=-])>([^<>{}();=\n]*[A-Za-z]{2,}[^<>{}();=\n]*)<")
# Attributes a user reads or hears, set to a literal with a word in it.
LITERAL_ATTRIBUTE = re.compile(r"\b(aria-label|placeholder|title|alt)=\"([^\"]*[A-Za-z]{2,}[^\"]*)\"")
KEY = re.compile(r"\bt\(\s*\"([\w.]+)\"")


def _components() -> list[Path]:
    return sorted(SOURCES.rglob("*.tsx"))


def _keys(tree: dict[str, object], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for name, value in tree.items():
        path = f"{prefix}{name}"
        keys |= _keys(value, f"{path}.") if isinstance(value, dict) else {path}  # pyright: ignore[reportUnknownArgumentType]
    return keys


@pytest.mark.spec("I18N-001")
def test_components_hold_no_user_facing_text() -> None:
    assert _components(), "the web client's components moved"
    found = [
        f"{path.relative_to(ROOT)}: {match.group(0).strip()}"
        for path in _components()
        for pattern in (JSX_TEXT, LITERAL_ATTRIBUTE)
        for match in pattern.finditer(path.read_text())
    ]
    assert found == []


@pytest.mark.spec("I18N-001")
def test_every_string_the_app_uses_is_translated() -> None:
    english = _keys(json.loads(ENGLISH.read_text()))
    used = {key for path in [*SOURCES.rglob("*.ts"), *_components()] for key in KEY.findall(path.read_text())}
    assert used, "no translated strings found: the pattern no longer matches the app"
    assert sorted(used - english) == []
