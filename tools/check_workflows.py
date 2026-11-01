"""Check the CI workflows against the project's hardening rules (REPO-007, REPO-008, REPO-009).

Usage: python3 tools/check_workflows.py [--root PATH]

Reads every workflow in .github/workflows, without a YAML library, line by
line, and fails when:

- a third-party action is not pinned to a full commit SHA, or a workflow does
  not declare its permissions (REPO-007);
- a `run:` script interpolates an expression that a pull request's author
  controls, such as a branch name or a title, instead of passing it through
  the environment (REPO-007);
- a workflow runs on `pull_request_target`, or a workflow that runs on pull
  requests uses secrets or asks for a write permission (REPO-008);
- CI does not run, on pull requests and on master, the formatter check, the
  linter, the strict type checker and the tests, or installs dependencies
  without the lock file (REPO-009).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

WORKFLOWS_DIR = Path(".github/workflows")
CI_WORKFLOW = "ci.yml"
SHA_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)")
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
# Contexts whose values a pull request's author chooses.
UNTRUSTED = re.compile(
    r"github\.head_ref|github\.event\.(pull_request|issue|comment|review|review_comment|head_commit|commits|pages)"
    r"|github\.event\.workflow_run\.(head_branch|head_commit|display_title)"
)
WRITE_PERMISSION = re.compile(r"^\s*[\w-]+:\s*write\b|^\s*permissions:\s*write-all\b")
# What REPO-009 requires CI to run, as fragments of its scripts.
QUALITY_GATES = {
    "the formatter check": "ruff format --check",
    "the linter": "ruff check",
    "the strict type checker": "pyright",
    "the tests": "pytest",
    "an install from the lock file": "uv sync --locked",
}


@dataclass(frozen=True)
class Workflow:
    name: str
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def triggers(self) -> set[str]:
        """The events of the top-level `on:` key, in its inline or block form."""
        events: set[str] = set()
        inside = False
        for line in self.lines:
            if re.match(r"^(on|\"on\"|'on'):", line):
                inline = line.split(":", 1)[1].strip()
                events.update(re.findall(r"[a-z_]+", inline))
                inside = not inline
                continue
            if inside:
                if line and not line[0].isspace():
                    break
                match = re.match(r"^  ([a-z_]+):?", line)
                if match:
                    events.add(match.group(1))
        return events

    def run_scripts(self) -> list[tuple[int, str]]:
        """Every line of a `run:` script, with its line number."""
        found: list[tuple[int, str]] = []
        indent: int | None = None
        for number, line in enumerate(self.lines, start=1):
            stripped = line.lstrip()
            current = len(line) - len(stripped)
            if indent is not None and stripped and current <= indent:
                indent = None
            match = re.match(r"^(\s*)(-\s*)?run:\s*(.*)$", line)
            if match:
                indent = len(match.group(1))
                if match.group(3) not in ("", "|", ">", "|-", ">-"):
                    found.append((number, match.group(3)))
                continue
            if indent is not None and stripped:
                found.append((number, stripped))
        return found


def load(root: Path) -> list[Workflow]:
    directory = root / WORKFLOWS_DIR
    paths = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]) if directory.is_dir() else []
    return [Workflow(path.name, path.read_text(encoding="utf-8").splitlines()) for path in paths]


def problems(workflow: Workflow) -> list[str]:
    found: list[str] = []
    where = f"{WORKFLOWS_DIR / workflow.name}"
    for number, line in enumerate(workflow.lines, start=1):
        match = USES.match(line)
        if match and not match.group(1).startswith(("./", "docker://")) and not SHA_PINNED.match(match.group(1)):
            found.append(f"{where}:{number}: {match.group(1)} is not pinned to a full commit SHA (REPO-007)")
    if not any(re.match(r"^permissions:", line) for line in workflow.lines):
        found.append(f"{where}: declares no top-level permissions (REPO-007)")
    for number, script in workflow.run_scripts():
        for expression in EXPRESSION.findall(script):
            if UNTRUSTED.search(expression):
                found.append(
                    f"{where}:{number}: `${{{{ {expression} }}}}` is interpolated into a script; "
                    "pass it through `env:` instead (REPO-007)"
                )
    triggers = workflow.triggers()
    if "pull_request_target" in triggers:
        found.append(f"{where}: runs on pull_request_target, with secrets for untrusted code (REPO-008)")
    if triggers & {"pull_request", "pull_request_target"}:
        for number, line in enumerate(workflow.lines, start=1):
            if "secrets." in line:
                found.append(f"{where}:{number}: uses secrets in a workflow that runs on pull requests (REPO-008)")
            if WRITE_PERMISSION.match(line):
                found.append(f"{where}:{number}: asks for a write permission on pull requests (REPO-008)")
    return found


def gate_problems(workflows: list[Workflow]) -> list[str]:
    """The quality gates of REPO-009, in the CI workflow."""
    ci = next((workflow for workflow in workflows if workflow.name == CI_WORKFLOW), None)
    if ci is None:
        return [f"{WORKFLOWS_DIR / CI_WORKFLOW} is missing (REPO-009)"]
    found: list[str] = []
    triggers = ci.triggers()
    if "pull_request" not in triggers or "push" not in triggers:
        found.append(f"{WORKFLOWS_DIR / CI_WORKFLOW}: must run on pull requests and on pushes to master (REPO-009)")
    scripts = "\n".join(script for _, script in ci.run_scripts())
    for gate, fragment in QUALITY_GATES.items():
        if fragment not in scripts:
            found.append(f"{WORKFLOWS_DIR / CI_WORKFLOW}: does not run {gate} (`{fragment}`) (REPO-009)")
    for number, script in ci.run_scripts():
        if re.search(r"\b(pip install|uv pip install|uv sync)\b", script) and "--locked" not in script:
            found.append(f"{WORKFLOWS_DIR / CI_WORKFLOW}:{number}: installs without the lock file (REPO-009)")
    return found


def check(root: Path) -> list[str]:
    workflows = load(root)
    return [problem for workflow in workflows for problem in problems(workflow)] + gate_problems(workflows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    found = check(args.root.resolve())
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if found:
        return 1
    print("Workflows OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
