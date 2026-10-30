"""Check traceability between requirements and tests (REPO-004).

Usage: python3 tools/check_traceability.py [--root PATH]

Tests declare the requirements they verify with the `spec` pytest marker:

    @pytest.mark.spec("SBX-005", "SBX-006")
    def test_sandbox_cannot_reach_the_lan(): ...

Fails when a test references a requirement that does not exist or whose
status is `draft` or `deprecated`, and when an `implemented` MUST requirement
with an automated verification kind has no test. Reports, without failing,
`accepted` requirements of that kind that have no test yet.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

try:
    from tools.check_specs import REQUIREMENTS_DIR, parse_requirement_file
except ModuleNotFoundError:  # executed as a script from the tools/ directory
    from check_specs import REQUIREMENTS_DIR, parse_requirement_file  # type: ignore[no-redef]

TESTS_DIR = Path("tests")
AUTOMATED = {"unit", "integration", "e2e", "design", "security", "eval"}
REFERENCEABLE = {"accepted", "implemented"}


@dataclass(frozen=True)
class Reference:
    requirement: str
    location: str


@dataclass
class Report:
    errors: list[str]
    untested_accepted: list[str]
    references: int


def _is_spec_marker(node: ast.expr) -> bool:
    # Matches `pytest.mark.spec` and `mark.spec`.
    if not (isinstance(node, ast.Attribute) and node.attr == "spec"):
        return False
    owner = node.value
    return (isinstance(owner, ast.Attribute) and owner.attr == "mark") or (
        isinstance(owner, ast.Name) and owner.id == "mark"
    )


def find_references(root: Path) -> tuple[list[Reference], list[str]]:
    """Return every requirement referenced by a `spec` marker, and parse errors."""
    references: list[Reference] = []
    errors: list[str] = []
    tests_dir = root / TESTS_DIR
    for path in sorted(tests_dir.rglob("*.py")) if tests_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            errors.append(f"{rel}:{exc.lineno}: cannot parse: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_spec_marker(node.func)):
                continue
            where = f"{rel}:{node.lineno}"
            if not node.args:
                errors.append(f"{where}: spec marker without requirement IDs")
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    references.append(Reference(arg.value, where))
                else:
                    errors.append(f"{where}: spec marker arguments must be string literals")
    return references, errors


def check(root: Path) -> Report:
    requirements = {}
    for path in sorted((root / REQUIREMENTS_DIR).glob("*.md")):
        parsed, _ = parse_requirement_file(root, path)
        for req in parsed:
            requirements[req.id] = req

    references, errors = find_references(root)
    tested: dict[str, list[str]] = defaultdict(list)
    for ref in references:
        req = requirements.get(ref.requirement)
        if req is None:
            errors.append(f"{ref.location}: reference to unknown requirement {ref.requirement}")
            continue
        status = req.fields.get("Status", "")
        if status not in REFERENCEABLE:
            errors.append(f"{ref.location}: {ref.requirement} is {status or 'without status'}; tests may only reference accepted or implemented requirements")
            continue
        tested[ref.requirement].append(ref.location)

    untested_accepted: list[str] = []
    for req_id, req in sorted(requirements.items()):
        kinds = {kind.strip() for kind in req.fields.get("Verification", "").split(",")}
        if req.fields.get("Priority") != "MUST" or not kinds & AUTOMATED or req_id in tested:
            continue
        status = req.fields.get("Status")
        if status == "implemented":
            errors.append(f"{req_id} is implemented but no test references it")
        elif status == "accepted":
            untested_accepted.append(req_id)

    return Report(errors=errors, untested_accepted=untested_accepted, references=len(references))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    report = check(args.root.resolve())
    if report.untested_accepted:
        print(f"{len(report.untested_accepted)} accepted requirement(s) awaiting tests:")
        print("  " + " ".join(report.untested_accepted))
    if report.errors:
        for error in report.errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"\n{len(report.errors)} error(s). See REPO-004 in specs/requirements/repository.md.", file=sys.stderr)
        return 1
    print(f"Traceability OK ({report.references} requirement reference(s) in tests).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
