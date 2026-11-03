"""No library downloads data at run time (OBS-006, ADR-0072).

Libraries the server depends on can fetch data on their own: the price
catalog's updater, tokenizer encodings, model files. The code never starts
them; what they would download is bundled or not used.
"""

from __future__ import annotations

import ast

import pytest

from tests.support.database import ROOT

SOURCES = ROOT / "src"
# Modules whose use downloads data at run time, and names that start a download.
DOWNLOADING_MODULES = (
    "genai_prices.update_prices",
    "tiktoken",
    "huggingface_hub",
    "transformers",
    "sentence_transformers",
)
DOWNLOADING_NAMES = {
    "UpdatePrices",
    "update_prices",
    "hf_hub_download",
    "snapshot_download",
    "get_encoding",
    "encoding_for_model",
}


@pytest.mark.spec("OBS-006")
def test_no_code_starts_a_downloader() -> None:
    offenders: list[str] = []
    for path in sorted(SOURCES.rglob("*.py")):
        if "node_modules" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import | ast.ImportFrom):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                names = [alias.name for alias in node.names] if isinstance(node, ast.ImportFrom) else []
                offenders += [f"{path}: imports {m}" for m in modules if m.startswith(DOWNLOADING_MODULES)]
                offenders += [f"{path}: imports {n}" for n in names if n in DOWNLOADING_NAMES]
            elif isinstance(node, ast.Attribute) and node.attr in DOWNLOADING_NAMES:
                offenders.append(f"{path}: uses {node.attr}")
    assert offenders == []
