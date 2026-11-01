"""Tests for tools/check_specs.py (REPO-003)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.tooling.marks import mark
from tools import check_specs

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_REQUIREMENTS = """\
# ABC — Example area

Intro text.

## ABC-001: First requirement

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit, integration

The system MUST do the first thing.

## ABC-002: Second requirement

- **Status:** accepted
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** review

The system SHOULD do the second thing. See ABC-001.
"""

VALID_ADR = """\
# ADR-0001: Example decision

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @someone
- **Related:** ABC-001

## Context

Text.
"""


@mark.spec("REPO-003")
class CheckSpecsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "specs/requirements").mkdir(parents=True)
        (self.root / "specs/adr").mkdir(parents=True)
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS)
        self.write("specs/adr/0001-example-decision.md", VALID_ADR)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def assertSingleError(self, fragment: str) -> None:
        errors = check_specs.check(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(fragment, errors[0])

    def test_valid_tree_passes(self) -> None:
        self.assertEqual(check_specs.check(self.root), [])

    def test_repository_specs_pass(self) -> None:
        self.assertEqual(check_specs.check(REPO_ROOT), [])

    def test_missing_file_title(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("# ABC — Example area", "# Example"))
        errors = check_specs.check(self.root)
        self.assertTrue(any("first line must be" in error for error in errors), errors)

    def test_prefix_must_match_file(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("## ABC-002", "## XYZ-002"))
        self.assertSingleError("does not use the file prefix ABC")

    def test_duplicate_id(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("## ABC-002", "## ABC-001"))
        self.assertSingleError("duplicate ID ABC-001")

    def test_malformed_heading(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("## ABC-002: Second", "## ABC-2 Second"))
        errors = check_specs.check(self.root)
        self.assertTrue(any("level-2 headings must be" in error for error in errors), errors)

    def test_missing_field(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("- **Phase:** 0\n", "", 1))
        self.assertSingleError("missing field 'Phase'")

    def test_invalid_status(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("draft", "done", 1))
        self.assertSingleError("invalid status 'done'")

    def test_invalid_verification(self) -> None:
        self.write("specs/requirements/example.md", VALID_REQUIREMENTS.replace("unit, integration", "unit, vibes"))
        self.assertSingleError("invalid verification")

    def test_keyword_must_match_priority(self) -> None:
        self.write(
            "specs/requirements/example.md",
            VALID_REQUIREMENTS.replace("The system MUST do the first thing.", "The system does the first thing."),
        )
        self.assertSingleError("does not use 'MUST'")

    def test_must_not_satisfies_must(self) -> None:
        self.write(
            "specs/requirements/example.md",
            VALID_REQUIREMENTS.replace("The system MUST do the first thing.", "The system MUST NOT fail."),
        )
        self.assertEqual(check_specs.check(self.root), [])

    def test_unknown_requirement_reference(self) -> None:
        self.write("docs/page.md", "As required by ABC-009.\n")
        self.assertSingleError("unknown requirement ABC-009")

    def test_unrelated_identifiers_are_ignored(self) -> None:
        self.write("docs/page.md", "Licensed AGPL-3.0, see RFC 2119 and ZZZ-123.\n")
        self.assertEqual(check_specs.check(self.root), [])

    def test_unknown_adr_reference(self) -> None:
        self.write("docs/page.md", "See ADR-0042.\n")
        self.assertSingleError("unknown ADR-0042")

    def test_adr_number_must_match_file_name(self) -> None:
        self.write("specs/adr/0001-example-decision.md", VALID_ADR.replace("ADR-0001", "ADR-0002"))
        errors = check_specs.check(self.root)
        self.assertTrue(any("does not match the file name" in error for error in errors), errors)

    def test_adr_invalid_status(self) -> None:
        self.write("specs/adr/0001-example-decision.md", VALID_ADR.replace("Accepted", "Maybe"))
        self.assertSingleError("invalid status 'Maybe'")

    def test_adr_superseded_status(self) -> None:
        self.write("specs/adr/0001-example-decision.md", VALID_ADR.replace("Accepted", "Superseded by ADR-0002"))
        self.write("specs/adr/0002-new-decision.md", VALID_ADR.replace("ADR-0001", "ADR-0002"))
        self.assertEqual(check_specs.check(self.root), [])

    def test_adr_file_name(self) -> None:
        self.write("specs/adr/1-bad.md", VALID_ADR)
        self.assertSingleError("ADR file names must be")

    def test_template_is_ignored(self) -> None:
        self.write("specs/adr/template.md", "# ADR-NNNN: Title\n")
        self.assertEqual(check_specs.check(self.root), [])

    def test_licenses_directory_is_not_scanned(self) -> None:
        self.write("LICENSES/text.md", "Mentions ABC-999.\n")
        self.assertEqual(check_specs.check(self.root), [])


if __name__ == "__main__":
    unittest.main()
