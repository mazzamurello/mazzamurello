"""Tests for tools/check_pr_paths.py (REPO-001)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.check_pr_paths import milestone_violations, sync_violations, target_violations, violations


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
        for path in (
            "AGENTS.md",
            ".github/workflows/ci.yml",
            ".devcontainer/devcontainer.json",
            "tools/check_dco.py",
            "tests/tooling/test_x.py",
            "tests/conftest.py",
            "LICENSE",
        ):
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


class PullRequestTargetTest(unittest.TestCase):
    def test_rules_pull_requests_target_the_default_branch(self) -> None:
        self.assertEqual(target_violations("rules/tighten-ci", "master"), [])
        self.assertNotEqual(target_violations("rules/tighten-ci", "next"), [])
        self.assertNotEqual(target_violations("rules/tighten-ci", "spec/other"), [])

    def test_other_pull_requests_target_the_integration_branch_or_the_default_branch(self) -> None:
        for branch in ("spec/x", "test/x", "impl/x", "docs/x"):
            with self.subTest(branch=branch):
                self.assertEqual(target_violations(branch, "next"), [])
                self.assertEqual(target_violations(branch, "master"), [])


class MilestonePullRequestTest(unittest.TestCase):
    """Runs the milestone check against a real temporary git repository (ADR-0055)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ada",
            "GIT_AUTHOR_EMAIL": "ada@example.org",
            "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.git("init", "-q", "-b", "master")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.git("branch", "next")
        self.pull_requests = 0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def commit(self, branch: str, *paths: str) -> None:
        self.git("checkout", "-q", branch)
        for path in paths:
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(f"{branch}\n")
            self.git("add", path)
        self.git("commit", "-q", "--allow-empty", "-m", f"change on {branch}")

    def merge_pull_request(self, branch: str, *paths: str) -> None:
        """A pull request from `branch` into next, merged as GitHub merges it."""
        self.git("checkout", "-q", "-b", branch, "next")
        self.commit(branch, *paths)
        self.pull_requests += 1
        self.git("checkout", "-q", "next")
        title = f"Merge pull request #{self.pull_requests} from mazzamurello/{branch}"
        self.git("merge", "-q", "--no-ff", "-m", title, branch)

    def problems(self) -> list[str]:
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            return milestone_violations("master", "next")
        finally:
            os.chdir(cwd)

    def sync_problems(self, head: str) -> list[str]:
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            return sync_violations(head, "master")
        finally:
            os.chdir(cwd)

    def test_the_default_branch_may_be_merged_into_next(self) -> None:
        self.commit("master", "tools/check_x.py")
        self.assertEqual(self.sync_problems("master"), [])

    def test_a_branch_named_like_the_default_branch_must_be_its_history(self) -> None:
        self.git("checkout", "-q", "-b", "elsewhere", "master")
        self.commit("elsewhere", "tools/check_x.py")
        self.assertNotEqual(self.sync_problems("elsewhere"), [])

    def test_pull_requests_of_every_type_pass(self) -> None:
        self.merge_pull_request("spec/x", "specs/adr/0001-x.md")
        self.merge_pull_request("test/x", "tests/test_x.py")
        self.merge_pull_request("impl/x", "src/x.py")
        self.merge_pull_request("docs/x", "README.md")
        self.assertEqual(self.problems(), [])

    def test_each_pull_request_is_checked_against_its_own_type(self) -> None:
        self.merge_pull_request("spec/x", "specs/adr/0001-x.md")
        self.merge_pull_request("impl/x", "src/x.py", "tests/test_x.py")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("impl/x", problems[0])
        self.assertIn("tests/test_x.py", problems[0])

    def test_rules_pull_requests_into_next_are_rejected(self) -> None:
        self.merge_pull_request("rules/x", "tools/check_x.py")
        self.assertNotEqual(self.problems(), [])

    def test_commits_pushed_to_next_are_rejected(self) -> None:
        self.merge_pull_request("spec/x", "specs/adr/0001-x.md")
        self.commit("next", "src/x.py")
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("without a pull request", problems[0])

    def test_merges_that_are_not_pull_requests_are_rejected(self) -> None:
        self.git("checkout", "-q", "-b", "impl/x", "next")
        self.commit("impl/x", "src/x.py")
        self.git("checkout", "-q", "next")
        self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'impl/x' into next", "impl/x")
        self.assertNotEqual(self.problems(), [])

    def test_the_default_branch_merged_into_next_is_not_checked_again(self) -> None:
        self.commit("master", "tools/check_x.py")
        self.git("checkout", "-q", "next")
        self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'master' into next", "master")
        self.merge_pull_request("impl/x", "src/x.py")
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
