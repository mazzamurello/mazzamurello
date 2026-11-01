"""Keep CI's test time within its budget (REPO-011, ADR-0059).

Usage: python3 tools/check_test_durations.py --junit REPORT --max-test-seconds N --max-session-seconds M

Reads the JUnit XML report of one pytest session, written with
`--junitxml=REPORT -o junit_duration_report=call`, so that each test's time
is the time of its call alone; fixtures shared by many tests count in the
session's time instead. Fails when a test took longer than N seconds or the
session longer than M seconds, and lists the slowest tests either way.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

SLOWEST_SHOWN = 10


@dataclass(frozen=True)
class Timing:
    test: str
    seconds: float


@dataclass(frozen=True)
class Report:
    session_seconds: float
    tests: list[Timing]


def parse_report(text: str) -> Report:
    root = ElementTree.fromstring(text)  # noqa: S314 - a report this CI job wrote itself
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = [
        Timing(f"{case.get('classname', '')}::{case.get('name', '')}", float(case.get("time", "0") or 0))
        for suite in suites
        for case in suite.iter("testcase")
    ]
    return Report(sum(float(suite.get("time", "0") or 0) for suite in suites), tests)


def problems(report: Report, max_test_seconds: float, max_session_seconds: float) -> list[str]:
    """A message for every test over its limit, and for a session over its budget."""
    found = [
        f"{timing.test} took {timing.seconds:.1f} s, more than the {max_test_seconds:g} s a test may take"
        for timing in sorted(report.tests, key=lambda timing: -timing.seconds)
        if timing.seconds > max_test_seconds
    ]
    if report.session_seconds > max_session_seconds:
        found.append(
            f"the tests took {report.session_seconds:.0f} s, more than this job's budget of {max_session_seconds:g} s"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--junit", required=True, type=Path, help="pytest's JUnit XML report")
    parser.add_argument("--max-test-seconds", required=True, type=float, help="the longest one test may take")
    parser.add_argument("--max-session-seconds", required=True, type=float, help="this job's budget")
    args = parser.parse_args(argv)

    report = parse_report(args.junit.read_text(encoding="utf-8"))
    print(f"Tests took {report.session_seconds:.0f} s of a budget of {args.max_session_seconds:g} s. Slowest:")
    for timing in sorted(report.tests, key=lambda timing: -timing.seconds)[:SLOWEST_SHOWN]:
        print(f"  {timing.seconds:6.1f} s  {timing.test}")
    found = problems(report, args.max_test_seconds, args.max_session_seconds)
    if found:
        for problem in found:
            print(f"error: {problem}", file=sys.stderr)
        print(
            "\nMake the tests faster, or move them to another job; raising a budget takes a 'rules/' pull "
            "request (ADR-0059).",
            file=sys.stderr,
        )
        return 1
    print("Test time OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
