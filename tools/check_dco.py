"""Verify the Developer Certificate of Origin sign-off on commits (REPO-002).

Usage: python3 tools/check_dco.py --base REF --head REF

Every non-merge commit in base..head must contain a 'Signed-off-by' trailer
whose email matches the commit author's email. Commits authored by bots
(names ending in '[bot]') are exempt.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

SIGNOFF_RE = re.compile(r"^Signed-off-by: .+ <([^<>\s]+)>\s*$", re.MULTILINE)
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
LOG_FORMAT = FIELD_SEP.join(("%H", "%P", "%an", "%ae", "%B")) + RECORD_SEP


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    message: str


def parse_log(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in output.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, name, email, message = record.split(FIELD_SEP, 4)
        commits.append(Commit(sha, tuple(parents.split()), name, email, message))
    return commits


def problem(commit: Commit) -> str | None:
    """Return a description of the commit's DCO problem, or None if it complies."""
    if len(commit.parents) > 1 or commit.author_name.endswith("[bot]"):
        return None
    emails = {email.lower() for email in SIGNOFF_RE.findall(commit.message)}
    if not emails:
        return f"{commit.sha[:12]}: missing 'Signed-off-by' (use 'git commit -s')"
    if commit.author_email.lower() not in emails:
        return f"{commit.sha[:12]}: 'Signed-off-by' does not match the author email <{commit.author_email}>"
    return None


def commits_between(base: str, head: str) -> list[Commit]:
    result = subprocess.run(
        ["git", "log", f"--format={LOG_FORMAT}", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_log(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/master")
    parser.add_argument("--head", default="HEAD", help="head ref")
    args = parser.parse_args(argv)

    commits = commits_between(args.base, args.head)
    problems = [message for commit in commits if (message := problem(commit)) is not None]
    if problems:
        for message in problems:
            print(f"error: {message}", file=sys.stderr)
        print(
            "\nSign off with 'git commit -s'; to fix existing commits: 'git rebase --signoff <base>'. "
            "See CONTRIBUTING.md.",
            file=sys.stderr,
        )
        return 1
    print(f"DCO OK ({len(commits)} commit(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
