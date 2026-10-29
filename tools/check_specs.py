"""Validate requirements, ADRs and cross-references (REPO-003).

Usage: python3 tools/check_specs.py [--root PATH]

Checks:
- requirement files: title with ID prefix, requirement headings, fields,
  allowed values, normative keyword matching the priority, unique IDs;
- ADR files: file name, title, number, status, date;
- every Markdown document: references to requirement IDs and ADRs exist.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REQUIREMENTS_DIR = Path("specs/requirements")
ADR_DIR = Path("specs/adr")
ADR_TEMPLATE = "template.md"

FILE_TITLE_RE = re.compile(r"^# ([A-Z][A-Z0-9]{1,4}) — \S.*$")
REQ_HEADING_RE = re.compile(r"^## ([A-Z][A-Z0-9]{1,4})-(\d{3}): \S.*$")
FIELD_RE = re.compile(r"^- \*\*([A-Za-z]+):\*\* (.+)$")
ADR_FILE_RE = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ADR_TITLE_RE = re.compile(r"^# ADR-(\d{4}): \S.*$")
ADR_STATUS_RE = re.compile(r"^(Proposed|Accepted|Rejected|Deprecated|Superseded by ADR-\d{4})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQ_REF_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,4})-(\d{3})\b")
ADR_REF_RE = re.compile(r"\bADR-(\d{4})\b")

REQUIRED_FIELDS = ("Status", "Priority", "Phase", "Verification")
STATUSES = {"draft", "accepted", "implemented", "deprecated"}
PRIORITIES = {"MUST", "SHOULD", "MAY"}
PHASES = {"0", "1", "2", "3"}
VERIFICATIONS = {"unit", "integration", "e2e", "design", "security", "eval", "review"}

# Directories never scanned for cross-references.
SKIPPED_DIRS = {".git", ".venv", "node_modules", "LICENSES"}


@dataclass
class Requirement:
    id: str
    path: Path
    line: int
    fields: dict[str, str] = field(default_factory=dict)
    body: list[str] = field(default_factory=list)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _check_requirement(req: Requirement, where: str) -> list[str]:
    errors: list[str] = []
    for name in REQUIRED_FIELDS:
        if name not in req.fields:
            errors.append(f"{where}: {req.id} is missing field '{name}'")
    for name in req.fields:
        if name not in REQUIRED_FIELDS:
            errors.append(f"{where}: {req.id} has unknown field '{name}'")

    status = req.fields.get("Status")
    if status is not None and status not in STATUSES:
        errors.append(f"{where}: {req.id} has invalid status '{status}'")
    priority = req.fields.get("Priority")
    if priority is not None and priority not in PRIORITIES:
        errors.append(f"{where}: {req.id} has invalid priority '{priority}'")
    phase = req.fields.get("Phase")
    if phase is not None and phase not in PHASES:
        errors.append(f"{where}: {req.id} has invalid phase '{phase}'")
    verification = req.fields.get("Verification")
    if verification is not None:
        kinds = [kind.strip() for kind in verification.split(",")]
        unknown = [kind for kind in kinds if kind not in VERIFICATIONS]
        if unknown or not all(kinds):
            errors.append(f"{where}: {req.id} has invalid verification '{verification}'")

    body = " ".join(req.body)
    if not body.strip():
        errors.append(f"{where}: {req.id} has no normative statement")
    elif priority in PRIORITIES and not re.search(rf"\b{priority}\b", body):
        errors.append(f"{where}: {req.id} has priority {priority} but its statement does not use '{priority}'")
    return errors


def parse_requirement_file(root: Path, path: Path) -> tuple[list[Requirement], list[str]]:
    """Parse one requirements file; return its requirements and format errors."""
    rel = _rel(root, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []

    title = FILE_TITLE_RE.match(lines[0]) if lines else None
    if title is None:
        return [], [f"{rel}:1: first line must be '# PREFIX — Title'"]
    prefix = title.group(1)

    requirements: list[Requirement] = []
    current: Requirement | None = None
    for number, line in enumerate(lines[1:], start=2):
        if line.startswith("## "):
            heading = REQ_HEADING_RE.match(line)
            if heading is None:
                errors.append(f"{rel}:{number}: level-2 headings must be '## {prefix}-NNN: Title'")
                current = None
                continue
            req_id = f"{heading.group(1)}-{heading.group(2)}"
            if heading.group(1) != prefix:
                errors.append(f"{rel}:{number}: {req_id} does not use the file prefix {prefix}")
            current = Requirement(id=req_id, path=path, line=number)
            requirements.append(current)
        elif current is not None:
            field_match = FIELD_RE.match(line)
            if field_match is not None and not current.body:
                name, value = field_match.group(1), field_match.group(2).strip()
                if name in current.fields:
                    errors.append(f"{rel}:{number}: {current.id} repeats field '{name}'")
                current.fields[name] = value
            elif line.strip():
                current.body.append(line.strip())

    for req in requirements:
        errors.extend(_check_requirement(req, f"{rel}:{req.line}"))
    return requirements, errors


def parse_adr_file(root: Path, path: Path) -> tuple[str | None, list[str]]:
    """Validate one ADR; return its number and format errors."""
    rel = _rel(root, path)
    file_match = ADR_FILE_RE.match(path.name)
    if file_match is None:
        return None, [f"{rel}: ADR file names must be 'NNNN-kebab-case-title.md'"]

    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    title = ADR_TITLE_RE.match(lines[0]) if lines else None
    if title is None:
        errors.append(f"{rel}:1: first line must be '# ADR-NNNN: Title'")
    elif title.group(1) != file_match.group(1):
        errors.append(f"{rel}:1: title number ADR-{title.group(1)} does not match the file name")

    fields: dict[str, str] = {}
    for line in lines[1:]:
        field_match = FIELD_RE.match(line)
        if field_match is not None:
            fields.setdefault(field_match.group(1), field_match.group(2).strip())
        elif line.startswith("## "):
            break
    status = fields.get("Status")
    if status is None:
        errors.append(f"{rel}: missing field 'Status'")
    elif ADR_STATUS_RE.match(status) is None:
        errors.append(f"{rel}: invalid status '{status}'")
    date = fields.get("Date")
    if date is None:
        errors.append(f"{rel}: missing field 'Date'")
    elif DATE_RE.match(date) is None:
        errors.append(f"{rel}: invalid date '{date}' (expected YYYY-MM-DD)")
    return file_match.group(1), errors


def _markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        parts = path.relative_to(root).parts
        if any(part in SKIPPED_DIRS for part in parts):
            continue
        files.append(path)
    return files


def check(root: Path) -> list[str]:
    """Run every check on the repository at ``root``; return all errors."""
    errors: list[str] = []

    requirements: dict[str, Requirement] = {}
    req_dir = root / REQUIREMENTS_DIR
    for path in sorted(req_dir.glob("*.md")) if req_dir.is_dir() else []:
        parsed, file_errors = parse_requirement_file(root, path)
        errors.extend(file_errors)
        for req in parsed:
            if req.id in requirements:
                first = requirements[req.id]
                errors.append(
                    f"{_rel(root, path)}:{req.line}: duplicate ID {req.id} "
                    f"(first defined in {_rel(root, first.path)}:{first.line})"
                )
            else:
                requirements[req.id] = req

    adrs: set[str] = set()
    adr_dir = root / ADR_DIR
    for path in sorted(adr_dir.glob("*.md")) if adr_dir.is_dir() else []:
        if path.name == ADR_TEMPLATE:
            continue
        number, file_errors = parse_adr_file(root, path)
        errors.extend(file_errors)
        if number is not None:
            if number in adrs:
                errors.append(f"{_rel(root, path)}: duplicate ADR number {number}")
            adrs.add(number)

    prefixes = {req_id.split("-")[0] for req_id in requirements}
    for path in _markdown_files(root):
        rel = _rel(root, path)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in REQ_REF_RE.finditer(line):
                ref = match.group(0)
                if match.group(1) in prefixes and ref not in requirements:
                    errors.append(f"{rel}:{number}: reference to unknown requirement {ref}")
            for match in ADR_REF_RE.finditer(line):
                if match.group(1) not in adrs:
                    errors.append(f"{rel}:{number}: reference to unknown {match.group(0)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    errors = check(root)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"\n{len(errors)} error(s). See specs/README.md for the expected format.", file=sys.stderr)
        return 1
    print("Specs OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
