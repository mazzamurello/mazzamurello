"""The control plane never reaches the container runtime itself (SBX-009, AGT-013, ADR-0022, ADR-0035)."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from tests.support.database import ROOT

SERVER = ROOT / "src" / "server"
# Libraries that talk to a container runtime, or run commands on the host.
FORBIDDEN_DEPENDENCIES = ("docker", "aiodocker", "podman", "kubernetes")
FORBIDDEN_IMPORTS = (
    "docker",
    "aiodocker",
    "subprocess",
    "pydantic_ai.capabilities.local_workspace",
    "pydantic_ai.workspaces.local",
)


def _python_files() -> list[Path]:
    return sorted((SERVER / "mazzamurello_server").rglob("*.py"))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.spec("SBX-009")
def test_the_server_does_not_depend_on_container_runtimes() -> None:
    project = tomllib.loads((SERVER / "pyproject.toml").read_text())
    dependencies = [str(item).lower() for item in project["project"].get("dependencies", [])]
    offenders = [item for item in dependencies if item.split("[")[0].split("=")[0].strip() in FORBIDDEN_DEPENDENCIES]
    assert not offenders


@pytest.mark.spec("SBX-009", "AGT-013")
def test_the_server_does_not_import_container_runtimes_or_run_host_commands() -> None:
    files = _python_files()
    assert files
    offenders = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in files
        for name in _imports(path)
        if any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_IMPORTS)
    )
    assert not offenders, offenders
