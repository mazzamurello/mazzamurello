"""Enforce pull request types and allowed paths (REPO-001).

Usage: python3 tools/check_pr_paths.py --branch BRANCH --base REF --head REF

The branch prefix (the text before the first '/') is the pull request type.
Each type may change only its allowed paths. Rules files can be changed only
by 'rules' pull requests, so that a change can never relax the checks that
gate it, and 'rules' pull requests target the default branch.

The milestone pull request, from the integration branch into the default
branch, has no type of its own: every pull request merged into the
integration branch is checked against its own type, and commits that reached
the integration branch without a pull request are rejected (ADR-0055). A
pull request from the default branch into the integration branch may contain
only the default branch's own history.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

DEFAULT_BRANCH = "master"
# Spec, test, impl and docs pull requests target the integration branch; a
# milestone pull request brings it into the default branch (ADR-0055).
INTEGRATION_BRANCH = "next"
# The title GitHub gives the merge commit of a pull request.
MERGE_TITLE_RE = re.compile(r"^Merge pull request #\d+ from [^/\s]+/(\S+)$")

# A pattern ending with '/' matches everything below that directory;
# any other pattern matches exactly one file.
RULES_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "LICENSES/",
    "REUSE.toml",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".github/",
    ".devcontainer/",
    "tools/",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/tooling/",
)

POLICY: dict[str, tuple[str, ...]] = {
    "spec": ("specs/", "ROADMAP.md", "VISION.md"),
    "test": ("tests/", "evals/"),
    "impl": ("src/", "migrations/", "deploy/", "pyproject.toml", "uv.lock"),
    "docs": ("docs/", "README.md", "CHANGELOG.md"),
    "rules": RULES_PATHS,
    # Automated dependency updates: manifests and pinned workflow actions.
    "dependabot": (".github/workflows/", ".github/dependabot.yml", "pyproject.toml", "uv.lock", "deploy/"),
}


def matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern


def matches_any(patterns: tuple[str, ...], path: str) -> bool:
    return any(matches(pattern, path) for pattern in patterns)


def pr_type(branch: str) -> str | None:
    prefix, separator, rest = branch.partition("/")
    if not separator or not rest:
        return None
    return prefix


def violations(branch: str, paths: list[str]) -> list[str]:
    """Return a message for every path the branch's pull request type may not change."""
    kind = pr_type(branch)
    if kind is None or kind not in POLICY:
        allowed = ", ".join(f"{name}/" for name in POLICY)
        return [f"branch '{branch}' must be named '<type>/<description>' with type one of: {allowed}"]

    allowed_paths = POLICY[kind]
    problems: list[str] = []
    for path in paths:
        if not matches_any(allowed_paths, path):
            problems.append(f"{path}: not allowed in a '{kind}/' pull request")
        elif kind not in ("rules", "dependabot") and matches_any(RULES_PATHS, path):
            problems.append(f"{path}: rules files can only be changed by a 'rules/' pull request")
    return problems


def target_violations(branch: str, base_branch: str) -> list[str]:
    """Return a message when the pull request targets a branch its type may not."""
    if pr_type(branch) == "rules" and base_branch != DEFAULT_BRANCH:
        return [f"'rules/' pull requests target '{DEFAULT_BRANCH}', not '{base_branch}'"]
    return []


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def is_ancestor(commit: str, ref: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], check=False).returncode == 0


def milestone_violations(base: str, head: str) -> list[str]:
    """Check every change the integration branch brings into the default branch."""
    problems: list[str] = []
    log = git("log", "--first-parent", "--format=%H%x1f%P%x1f%s", f"{base}..{head}")
    for line in log.splitlines():
        sha, parents, title = line.split("\x1f", 2)
        commit, parent_shas = sha[:12], parents.split()
        if len(parent_shas) != 2:
            problems.append(f"{commit}: reached '{INTEGRATION_BRANCH}' without a pull request")
            continue
        if is_ancestor(parent_shas[1], base):
            continue  # the default branch merged into the integration branch
        match = MERGE_TITLE_RE.match(title)
        if match is None:
            problems.append(f"{commit}: merged into '{INTEGRATION_BRANCH}' without a pull request")
            continue
        source = match.group(1)
        found = target_violations(source, INTEGRATION_BRANCH)
        found += violations(source, changed_paths(parent_shas[0], parent_shas[1]))
        problems += [f"{commit} ({source}): {problem}" for problem in found]
    return problems


def sync_violations(head: str, default_ref: str) -> list[str]:
    """The default branch merged into the integration branch brings only reviewed work."""
    if is_ancestor(head, default_ref):
        return []
    return [f"a pull request from '{DEFAULT_BRANCH}' into '{INTEGRATION_BRANCH}' must contain only '{DEFAULT_BRANCH}'"]


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--branch", required=True, help="name of the pull request's head branch")
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/master")
    parser.add_argument("--head", default="HEAD", help="head ref")
    args = parser.parse_args(argv)

    base_branch = args.base.removeprefix("origin/")
    paths = changed_paths(args.base, args.head)
    if args.branch == INTEGRATION_BRANCH and base_branch == DEFAULT_BRANCH:
        problems = milestone_violations(args.base, args.head)
    elif args.branch == DEFAULT_BRANCH and base_branch == INTEGRATION_BRANCH:
        problems = sync_violations(args.head, f"origin/{DEFAULT_BRANCH}")
    else:
        problems = violations(args.branch, paths) + target_violations(args.branch, base_branch)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("\nSee 'Pull request types' in AGENTS.md. Split the change into separate pull requests.", file=sys.stderr)
        return 1
    print(f"Pull request policy OK ({len(paths)} file(s) changed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
