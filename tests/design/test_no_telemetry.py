"""Nothing is sent to external services by default (OBS-001, ADR-0058)."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from tests.support.database import ROOT

# Packages whose purpose is to send telemetry, error reports or traces to a
# service. `logfire-api`, the no-op shim Pydantic AI imports, sends nothing;
# `opentelemetry-api` alone has no exporter.
DENIED_PACKAGES = re.compile(
    r"^(sentry-sdk|logfire|opentelemetry-sdk|opentelemetry-exporter-.*|posthog|ddtrace|datadog|newrelic"
    r"|rollbar|bugsnag|honeybadger|analytics-python|segment-analytics-python|mixpanel|amplitude-analytics)$"
)
SOURCES = ROOT / "src"
WORKER = SOURCES / "server" / "mazzamurello_server" / "worker.py"
# DBOS settings that would send data to a service.
DENIED_DBOS_SETTINGS = {"conductor_key", "conductor_url", "enable_otlp", "otlp_traces_endpoints", "otlp_logs_endpoints"}


def _locked_packages() -> set[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return {str(package["name"]) for package in cast(list[dict[str, Any]], lock["package"])}


def _trees() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text(), filename=str(path))) for path in sorted(SOURCES.rglob("*.py"))]


@pytest.mark.spec("OBS-001")
def test_no_telemetry_package_is_installed() -> None:
    assert "pydantic-ai-slim" in _locked_packages() or "pydantic-ai" in _locked_packages(), "unexpected lock file"
    assert sorted(name for name in _locked_packages() if DENIED_PACKAGES.match(name)) == []


@pytest.mark.spec("OBS-001")
def test_dbos_is_configured_without_a_conductor_or_otlp() -> None:
    calls = [
        node
        for node in ast.walk(ast.parse(WORKER.read_text()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DBOSConfig"
    ]
    assert calls, "the worker no longer configures DBOS with DBOSConfig"
    for call in calls:
        assert {keyword.arg for keyword in call.keywords} & DENIED_DBOS_SETTINGS == set()


@pytest.mark.spec("OBS-001")
def test_nothing_instruments_pydantic_ai_or_imports_an_exporter() -> None:
    offenders: list[str] = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                offenders += [
                    f"{path}: imports {name}" for name in modules if name.split(".")[0] in {"logfire", "sentry_sdk"}
                ]
                offenders += [f"{path}: imports {name}" for name in modules if name.startswith("opentelemetry.sdk")]
            elif isinstance(node, ast.Attribute) and node.attr == "instrument_all":
                offenders.append(f"{path}: calls instrument_all")
            elif isinstance(node, ast.keyword) and node.arg == "instrument":
                offenders.append(f"{path}: passes instrument=")
    assert offenders == []
