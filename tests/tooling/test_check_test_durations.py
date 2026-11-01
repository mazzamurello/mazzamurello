"""Tests for tools/check_test_durations.py (REPO-011)."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tools.check_test_durations import main, parse_report, problems

REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="0" skipped="0" tests="3" time="95.500">
    <testcase classname="tests.integration.test_runs_api" name="test_fast" time="0.200" />
    <testcase classname="tests.integration.test_runs_api" name="test_slow" time="31.000" />
    <testcase classname="tests.security.test_sandbox_isolation" name="test_probe[10.0.0.1]" time="3.400" />
  </testsuite>
</testsuites>
"""


class ParseReportTest(unittest.TestCase):
    def test_session_and_test_times(self) -> None:
        report = parse_report(REPORT)
        self.assertEqual(report.session_seconds, 95.5)
        self.assertEqual(
            [(timing.test, timing.seconds) for timing in report.tests],
            [
                ("tests.integration.test_runs_api::test_fast", 0.2),
                ("tests.integration.test_runs_api::test_slow", 31.0),
                ("tests.security.test_sandbox_isolation::test_probe[10.0.0.1]", 3.4),
            ],
        )

    def test_a_single_suite_root(self) -> None:
        report = parse_report('<testsuite time="2.0"><testcase classname="a" name="b" time="1.5"/></testsuite>')
        self.assertEqual(report.session_seconds, 2.0)
        self.assertEqual(len(report.tests), 1)


class ProblemsTest(unittest.TestCase):
    def test_within_limits(self) -> None:
        self.assertEqual(problems(parse_report(REPORT), max_test_seconds=40, max_session_seconds=100), [])

    def test_a_slow_test_is_named(self) -> None:
        found = problems(parse_report(REPORT), max_test_seconds=30, max_session_seconds=100)
        self.assertEqual(len(found), 1)
        self.assertIn("test_slow", found[0])

    def test_a_session_over_budget(self) -> None:
        found = problems(parse_report(REPORT), max_test_seconds=40, max_session_seconds=90)
        self.assertEqual(len(found), 1)
        self.assertIn("budget", found[0])


class MainTest(unittest.TestCase):
    def run_main(self, *limits: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            path.write_text(REPORT, encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--junit", str(path), *limits])
        return code, out.getvalue() + err.getvalue()

    def test_passes_within_limits(self) -> None:
        code, output = self.run_main("--max-test-seconds", "40", "--max-session-seconds", "100")
        self.assertEqual(code, 0)
        self.assertIn("test_slow", output, "the slowest tests are listed")

    def test_fails_over_limits(self) -> None:
        code, output = self.run_main("--max-test-seconds", "30", "--max-session-seconds", "90")
        self.assertEqual(code, 1)
        self.assertIn("rules/", output)


if __name__ == "__main__":
    unittest.main()
