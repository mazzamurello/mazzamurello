"""Tests for tools/check_traceability.py (REPO-004)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.tooling.marks import mark
from tools import check_traceability

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENTS = """\
# ABC — Example area

## ABC-001: Implemented and automated

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

The system MUST do one thing.

## ABC-002: Accepted and automated

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration, review

The system MUST do another thing.

## ABC-003: Draft

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** unit

The system MUST do a future thing.

## ABC-004: Verified by review only

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

The system MUST be reviewed.

## ABC-005: Optional

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 0
- **Verification:** unit

The system SHOULD be nice.
"""


@mark.spec("REPO-004")
class TraceabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write("specs/requirements/example.md", REQUIREMENTS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_implemented_requirement_without_test_fails(self) -> None:
        report = check_traceability.check(self.root)
        self.assertEqual(report.errors, ["ABC-001 is implemented but no test references it"])

    def test_accepted_requirement_without_test_is_reported_not_failed(self) -> None:
        self.write("tests/test_a.py", 'import pytest\n\n@pytest.mark.spec("ABC-001")\ndef test_a(): ...\n')
        report = check_traceability.check(self.root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.untested_accepted, ["ABC-002"])

    def test_review_only_and_should_requirements_need_no_test(self) -> None:
        self.write("tests/test_a.py", 'import pytest\n\n@pytest.mark.spec("ABC-001", "ABC-002")\ndef test_a(): ...\n')
        report = check_traceability.check(self.root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.untested_accepted, [])
        self.assertEqual(report.references, 2)

    def test_reference_to_unknown_requirement_fails(self) -> None:
        self.write("tests/test_a.py", 'import pytest\n\n@pytest.mark.spec("ABC-001", "ABC-999")\ndef test_a(): ...\n')
        errors = check_traceability.check(self.root).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown requirement ABC-999", errors[0])

    def test_reference_to_draft_requirement_fails(self) -> None:
        self.write("tests/test_a.py", 'import pytest\n\n@pytest.mark.spec("ABC-001", "ABC-003")\ndef test_a(): ...\n')
        errors = check_traceability.check(self.root).errors
        self.assertEqual(len(errors), 1)
        self.assertIn("ABC-003 is draft", errors[0])

    def test_module_level_and_short_marker_forms(self) -> None:
        self.write(
            "tests/unit/test_b.py",
            'import pytest\nfrom pytest import mark\n\npytestmark = pytest.mark.spec("ABC-001")\n\n'
            '@mark.spec("ABC-002")\ndef test_b(): ...\n',
        )
        report = check_traceability.check(self.root)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.references, 2)

    def test_non_literal_arguments_fail(self) -> None:
        self.write("tests/test_a.py", 'import pytest\nIDS = "ABC-001"\n\n@pytest.mark.spec(IDS)\ndef test_a(): ...\n')
        errors = check_traceability.check(self.root).errors
        self.assertTrue(any("must be string literals" in error for error in errors), errors)

    def test_marker_without_ids_fails(self) -> None:
        self.write("tests/test_a.py", 'import pytest\n\n@pytest.mark.spec()\ndef test_a(): ...\n')
        errors = check_traceability.check(self.root).errors
        self.assertTrue(any("without requirement IDs" in error for error in errors), errors)

    def test_unparsable_test_file_fails(self) -> None:
        self.write("tests/test_a.py", "def broken(:\n")
        errors = check_traceability.check(self.root).errors
        self.assertTrue(any("cannot parse" in error for error in errors), errors)

    def test_repository_passes(self) -> None:
        self.assertEqual(check_traceability.check(REPO_ROOT).errors, [])


if __name__ == "__main__":
    unittest.main()
