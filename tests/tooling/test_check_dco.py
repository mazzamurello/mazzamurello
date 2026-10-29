"""Tests for tools/check_dco.py (REPO-002)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import check_dco
from tools.check_dco import Commit, problem


def commit(message: str, email: str = "ada@example.org", name: str = "Ada", parents: int = 1) -> Commit:
    return Commit("a" * 40, tuple("b" * 40 for _ in range(parents)), name, email, message)


class DcoProblemTest(unittest.TestCase):
    def test_signed_off_commit_passes(self) -> None:
        self.assertIsNone(problem(commit("feat: x\n\nSigned-off-by: Ada <ada@example.org>\n")))

    def test_email_comparison_is_case_insensitive(self) -> None:
        self.assertIsNone(problem(commit("feat: x\n\nSigned-off-by: Ada <Ada@Example.org>\n")))

    def test_missing_signoff_fails(self) -> None:
        result = problem(commit("feat: x\n"))
        self.assertIsNotNone(result)
        self.assertIn("missing 'Signed-off-by'", result or "")

    def test_signoff_by_someone_else_fails(self) -> None:
        result = problem(commit("feat: x\n\nSigned-off-by: Bob <bob@example.org>\n"))
        self.assertIn("does not match the author email", result or "")

    def test_signoff_must_be_a_trailer_line(self) -> None:
        self.assertIsNotNone(problem(commit("feat: x\n\nPlease add Signed-off-by: Ada <ada@example.org> later\n")))

    def test_merge_commits_are_skipped(self) -> None:
        self.assertIsNone(problem(commit("Merge branch 'x'\n", parents=2)))

    def test_bots_are_exempt(self) -> None:
        self.assertIsNone(problem(commit("chore: bump\n", name="dependabot[bot]", email="bot@example.org")))


class DcoGitIntegrationTest(unittest.TestCase):
    """Runs the check against a real temporary git repository."""

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
        self.git("tag", "base")

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

    def problems(self) -> list[str]:
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            commits = check_dco.commits_between("base", "HEAD")
        finally:
            os.chdir(cwd)
        return [message for c in commits if (message := problem(c)) is not None]

    def test_signed_and_unsigned_commits(self) -> None:
        self.git("commit", "-q", "--allow-empty", "-s", "-m", "signed")
        self.assertEqual(self.problems(), [])
        self.git("commit", "-q", "--allow-empty", "-m", "unsigned")
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("missing 'Signed-off-by'", problems[0])

    def test_multiline_messages_are_parsed(self) -> None:
        self.git("commit", "-q", "--allow-empty", "-s", "-m", "feat: x", "-m", "Body line one.\nBody line two.")
        commits_out = self.git("log", f"--format={check_dco.LOG_FORMAT}", "base..HEAD")
        parsed = check_dco.parse_log(commits_out)
        self.assertEqual(len(parsed), 1)
        self.assertIn("Body line two.", parsed[0].message)
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
