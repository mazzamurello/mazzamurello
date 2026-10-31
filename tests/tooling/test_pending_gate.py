"""Tests for the pending-test gate in tests/conftest.py (REPO-004)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENTS = """\
# ABC — Example area

## ABC-001: Implemented

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

The system MUST do one thing.

## ABC-002: Accepted

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

The system MUST do another thing.

## ABC-003: Accepted too

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

The system MUST do a third thing.
"""


@unittest.skipUnless(importlib.util.find_spec("pytest"), "needs pytest, run by the Python checks job")
class PendingGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write("specs/requirements/example.md", REQUIREMENTS)
        self.write("tests/__init__.py", "")
        self.write("tools/__init__.py", "")
        shutil.copy(REPO_ROOT / "tests" / "conftest.py", self.root / "tests" / "conftest.py")
        shutil.copy(REPO_ROOT / "tools" / "check_specs.py", self.root / "tools" / "check_specs.py")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_pytest(self, test_source: str) -> subprocess.CompletedProcess[str]:
        self.write("tests/test_example.py", "import pytest\n\n" + test_source)
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rxX", "-W", "ignore::pytest.PytestUnknownMarkWarning", "tests"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_failing_test_of_accepted_requirement_is_pending(self) -> None:
        result = self.run_pytest('@pytest.mark.spec("ABC-002")\ndef test_a():\n    assert False\n')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 xfailed", result.stdout)
        self.assertIn("pending: ABC-002", result.stdout)

    def test_setup_error_of_accepted_requirement_is_pending(self) -> None:
        result = self.run_pytest(
            "@pytest.fixture\ndef database():\n    raise RuntimeError('no migrations')\n\n"
            '@pytest.mark.spec("ABC-002")\ndef test_a(database):\n    pass\n'
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 xfailed", result.stdout)

    def test_failing_test_of_implemented_requirement_fails(self) -> None:
        result = self.run_pytest('@pytest.mark.spec("ABC-001")\ndef test_a():\n    assert False\n')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("1 failed", result.stdout)

    def test_any_implemented_requirement_makes_the_test_binding(self) -> None:
        result = self.run_pytest('@pytest.mark.spec("ABC-002", "ABC-001")\ndef test_a():\n    assert False\n')
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_failing_test_without_marker_fails(self) -> None:
        result = self.run_pytest("def test_a():\n    assert False\n")
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_unknown_requirement_is_not_pending(self) -> None:
        result = self.run_pytest('@pytest.mark.spec("ABC-999")\ndef test_a():\n    assert False\n')
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_module_marker_applies(self) -> None:
        result = self.run_pytest('pytestmark = pytest.mark.spec("ABC-002")\n\ndef test_a():\n    assert False\n')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 xfailed", result.stdout)

    def test_requirements_whose_pending_tests_all_pass_are_listed(self) -> None:
        result = self.run_pytest(
            '@pytest.mark.spec("ABC-002")\ndef test_a():\n    pass\n\n'
            '@pytest.mark.spec("ABC-003")\ndef test_b():\n    pass\n\n'
            '@pytest.mark.spec("ABC-003")\ndef test_c():\n    assert False\n'
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Candidates for 'implemented': ABC-002\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
