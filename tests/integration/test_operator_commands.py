"""The operator's `init` command: fresh secrets, never defaults (AUTH-007, ADR-0054)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.database import ROOT

SECRETS = ("MZM_POSTGRES_PASSWORD", "MZM_OWNER_PASSWORD", "MZM_APP_PASSWORD", "MZM_SECRET_KEY", "MZM_SANDBOXD_TOKEN")


def _init(output: Path) -> subprocess.CompletedProcess[str]:
    environment = {name: value for name, value in os.environ.items() if not name.startswith("MZM_")}
    return subprocess.run(  # noqa: S603 - the server's entry point
        [sys.executable, "-m", "mazzamurello_server", "init", "--output", str(output)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _values(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))


@pytest.mark.spec("AUTH-007", "OPS-001")
def test_init_writes_random_secrets(tmp_path: Path) -> None:
    first, second = tmp_path / "first.env", tmp_path / "second.env"
    assert _init(first).returncode == 0
    assert _init(second).returncode == 0
    one, two = _values(first), _values(second)
    for name in SECRETS:
        assert len(one[name]) >= 32, name
        assert one[name] != two[name], f"{name} is not random"
    assert len({one[name] for name in SECRETS}) == len(SECRETS)
    assert oct(first.stat().st_mode & 0o777) in {"0o600", "0o640"}


@pytest.mark.spec("AUTH-007")
def test_init_never_overwrites_a_configuration(tmp_path: Path) -> None:
    existing = tmp_path / ".env"
    existing.write_text("MZM_SECRET_KEY=mine\n")
    result = _init(existing)
    assert result.returncode != 0
    assert existing.read_text() == "MZM_SECRET_KEY=mine\n"
    assert "exists" in result.stderr
