"""Pending tests (ADR-0045).

A test is pending when it carries `spec` markers and every requirement they
reference is `accepted`. A pending test that fails, in setup or in its body,
is reported as an expected failure; every other test must pass. Marking a
requirement `implemented` in the specs makes its tests binding.

This file decides what CI enforces: it is a rules file (REPO-001).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from tools.check_specs import REQUIREMENTS_DIR, parse_requirement_file

ROOT = Path(__file__).resolve().parent.parent

STATUSES = pytest.StashKey[dict[str, str]]()
# Per requirement referenced by pending tests: whether all of them passed.
PENDING_RESULTS = pytest.StashKey[dict[str, bool]]()
PENDING = pytest.StashKey[tuple[str, ...]]()


def _requirement_statuses(root: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in sorted((root / REQUIREMENTS_DIR).glob("*.md")):
        requirements, _ = parse_requirement_file(root, path)
        for requirement in requirements:
            statuses[requirement.id] = requirement.fields.get("Status", "")
    return statuses


def pytest_configure(config: pytest.Config) -> None:
    config.stash[STATUSES] = _requirement_statuses(ROOT)
    config.stash[PENDING_RESULTS] = {}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    statuses = config.stash[STATUSES]
    for item in items:
        ids = tuple(str(arg) for marker in item.iter_markers("spec") for arg in marker.args)
        if ids and all(statuses.get(req_id) == "accepted" for req_id in ids):
            item.stash[PENDING] = ids


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    pending = item.stash.get(PENDING, None)
    if pending is None:
        return report

    results = item.config.stash[PENDING_RESULTS]
    if report.failed and report.when in ("setup", "call"):
        report.outcome = "skipped"
        report.wasxfail = "pending: " + ", ".join(pending)
        for req_id in pending:
            results[req_id] = False
    elif report.skipped or (report.when == "call" and not report.passed):
        for req_id in pending:
            results[req_id] = False
    elif report.when == "call":
        for req_id in pending:
            results.setdefault(req_id, True)
    return report


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, config: pytest.Config) -> None:
    candidates = sorted(req_id for req_id, passed in config.stash[PENDING_RESULTS].items() if passed)
    if candidates:
        terminalreporter.write_sep("=", "pending tests all pass (ADR-0045)")
        terminalreporter.write_line("Candidates for 'implemented': " + " ".join(candidates))
