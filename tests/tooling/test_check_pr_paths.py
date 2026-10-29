"""Tests for tools/check_pr_paths.py (REPO-001)."""

from __future__ import annotations

import unittest

from tools.check_pr_paths import violations


class PullRequestPathsTest(unittest.TestCase):
    def assertAllowed(self, branch: str, *paths: str) -> None:
        self.assertEqual(violations(branch, list(paths)), [])

    def assertRejected(self, branch: str, *paths: str) -> None:
        self.assertNotEqual(violations(branch, list(paths)), [], f"{branch} should not change {paths}")

    def test_branch_without_type_is_rejected(self) -> None:
        self.assertRejected("feature-x", "specs/glossary.md")
        self.assertRejected("spec/", "specs/glossary.md")

    def test_unknown_type_is_rejected(self) -> None:
        self.assertRejected("feature/x", "src/app.py")

    def test_spec_pull_request(self) -> None:
        self.assertAllowed("spec/sandbox-egress", "specs/requirements/sandbox.md", "specs/adr/0021-x.md", "ROADMAP.md")
        self.assertRejected("spec/sandbox-egress", "src/sandbox.py")
        self.assertRejected("spec/sandbox-egress", "tests/test_sandbox.py")

    def test_test_pull_request(self) -> None:
        self.assertAllowed("test/sandbox-egress", "tests/security/test_egress.py", "evals/injection.yaml")
        self.assertRejected("test/sandbox-egress", "src/sandbox.py")

    def test_impl_pull_request_cannot_touch_tests(self) -> None:
        self.assertAllowed("impl/sandbox-egress", "src/mazzamurello/sandbox.py", "migrations/0001.py", "pyproject.toml")
        self.assertRejected("impl/sandbox-egress", "src/mazzamurello/sandbox.py", "tests/test_sandbox.py")
        self.assertRejected("impl/sandbox-egress", "specs/requirements/sandbox.md")

    def test_docs_pull_request(self) -> None:
        self.assertAllowed("docs/install-guide", "docs/how-to/install.md", "README.md")
        self.assertRejected("docs/install-guide", "AGENTS.md")

    def test_rules_files_only_in_rules_pull_requests(self) -> None:
        for path in ("AGENTS.md", ".github/workflows/ci.yml", "tools/check_dco.py", "tests/tooling/test_x.py", "LICENSE"):
            with self.subTest(path=path):
                self.assertAllowed("rules/tighten-ci", path)
                self.assertRejected("test/anything", path)
                self.assertRejected("impl/anything", path)

    def test_rules_pull_request_is_limited_to_rules(self) -> None:
        self.assertRejected("rules/tighten-ci", "src/app.py")
        self.assertRejected("rules/tighten-ci", "specs/glossary.md")

    def test_directory_prefix_does_not_match_similar_names(self) -> None:
        self.assertRejected("docs/x", "docs-old/page.md")
        self.assertRejected("impl/x", "srcx/app.py")

    def test_dependabot_may_update_workflows_and_manifests(self) -> None:
        self.assertAllowed("dependabot/github_actions/actions/checkout-7.1.0", ".github/workflows/ci.yml")
        self.assertAllowed("dependabot/pip/pydantic-2.12", "pyproject.toml", "uv.lock")
        self.assertRejected("dependabot/github_actions/x", "tools/check_dco.py")

    def test_empty_change_is_allowed(self) -> None:
        self.assertAllowed("spec/nothing")


if __name__ == "__main__":
    unittest.main()
