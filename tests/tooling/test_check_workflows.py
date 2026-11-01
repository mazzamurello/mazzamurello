"""Tests for tools/check_workflows.py (REPO-007, REPO-008, REPO-009)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.tooling.marks import mark
from tools.check_workflows import check

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
GOOD = f"""name: CI

on:
  push:
    branches: [master]
  pull_request:

permissions:
  contents: read

jobs:
  checks:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@{SHA} # v7
      - name: Install
        run: uv sync --locked --all-packages
      - name: Checks
        env:
          HEAD_REF: ${{{{ github.head_ref }}}}
        run: |
          uv run --locked ruff format --check
          uv run --locked ruff check
          uv run --locked pyright
          uv run --locked pytest
          echo "$HEAD_REF"
"""


class CheckWorkflowsTest(unittest.TestCase):
    def problems(self, text: str, name: str = "ci.yml") -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / name).write_text(text, encoding="utf-8")
            if name != "ci.yml":
                (root / ".github" / "workflows" / "ci.yml").write_text(GOOD, encoding="utf-8")
            return check(root)

    def assertProblem(self, text: str, fragment: str, name: str = "ci.yml") -> None:
        found = self.problems(text, name)
        self.assertTrue(any(fragment in problem for problem in found), found)

    @mark.spec("REPO-007", "REPO-008", "REPO-009")
    def test_a_hardened_workflow_passes(self) -> None:
        self.assertEqual(self.problems(GOOD), [])

    @mark.spec("REPO-007")
    def test_actions_are_pinned_to_full_commit_shas(self) -> None:
        self.assertProblem(GOOD.replace(f"@{SHA}", "@v7"), "not pinned")
        self.assertProblem(GOOD.replace(f"@{SHA}", f"@{SHA[:12]}"), "not pinned")
        local = GOOD.replace(f"actions/checkout@{SHA}", "./.github/actions/setup")
        self.assertEqual(self.problems(local), [])

    @mark.spec("REPO-007")
    def test_permissions_are_declared(self) -> None:
        self.assertProblem(GOOD.replace("permissions:\n  contents: read\n", ""), "no top-level permissions")

    @mark.spec("REPO-007")
    def test_untrusted_input_is_not_interpolated_into_scripts(self) -> None:
        for expression in ("github.head_ref", "github.event.pull_request.title", "github.event.comment.body"):
            with self.subTest(expression=expression):
                self.assertProblem(
                    GOOD.replace('echo "$HEAD_REF"', f'echo "${{{{ {expression} }}}}"'), "pass it through `env:`"
                )
        trusted = GOOD.replace('echo "$HEAD_REF"', 'echo "${{ github.sha }}"')
        self.assertEqual(self.problems(trusted), [])

    @mark.spec("REPO-008")
    def test_pull_request_target_is_refused(self) -> None:
        self.assertProblem(GOOD.replace("  pull_request:\n", "  pull_request_target:\n"), "pull_request_target")

    @mark.spec("REPO-008")
    def test_pull_request_workflows_have_no_secrets_or_write_access(self) -> None:
        self.assertProblem(GOOD.replace("HEAD_REF: ${{ github.head_ref }}", "TOKEN: ${{ secrets.DEPLOY }}"), "secrets")
        self.assertProblem(GOOD.replace("  contents: read\n", "  contents: write\n"), "write permission")
        self.assertProblem(GOOD.replace("permissions:\n  contents: read\n", "permissions: write-all\n"), "write")

    @mark.spec("REPO-008")
    def test_secrets_are_allowed_where_pull_requests_cannot_reach(self) -> None:
        release = GOOD.replace("  pull_request:\n", "").replace(
            "HEAD_REF: ${{ github.head_ref }}", "TOKEN: ${{ secrets.DEPLOY }}"
        )
        self.assertEqual(self.problems(release, name="release.yml"), [])

    @mark.spec("REPO-009")
    def test_every_quality_gate_runs(self) -> None:
        for fragment in ("ruff format --check", "ruff check", "pyright", "pytest"):
            with self.subTest(gate=fragment):
                self.assertProblem(GOOD.replace(f"uv run --locked {fragment}\n", ""), fragment)

    @mark.spec("REPO-009")
    def test_dependencies_come_from_the_lock_file(self) -> None:
        self.assertProblem(GOOD.replace("uv sync --locked --all-packages", "uv sync --all-packages"), "lock file")
        self.assertProblem(GOOD.replace("uv sync --locked --all-packages", "pip install httpx"), "lock file")

    @mark.spec("REPO-009")
    def test_ci_runs_on_pull_requests_and_on_master(self) -> None:
        self.assertProblem(GOOD.replace("  pull_request:\n", ""), "must run on pull requests")


if __name__ == "__main__":
    unittest.main()
