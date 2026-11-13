"""Nightly backups, and the health of an instance whose backups fail (OPS-010, OPS-011, ADR-0077).

Making and restoring archives needs the deployment's containers, and is
tested end to end (tests/e2e/test_deployment.py).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from sibillo_server.backup import next_backup, prune_archives
from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.server import Server, fresh_source

NOW = datetime(2026, 11, 5, 21, 30, tzinfo=UTC)


@pytest.mark.spec("OPS-010")
@pytest.mark.parametrize(
    ("now", "at", "expected"),
    [
        (NOW, "03:00", datetime(2026, 11, 6, 3, 0, tzinfo=UTC)),
        (NOW, "23:15", datetime(2026, 11, 5, 23, 15, tzinfo=UTC)),
        (datetime(2026, 11, 6, 3, 0, tzinfo=UTC), "03:00", datetime(2026, 11, 7, 3, 0, tzinfo=UTC)),
    ],
    ids=["tomorrow", "tonight", "just-made"],
)
def test_backups_run_every_day_at_the_chosen_time(now: datetime, at: str, expected: datetime) -> None:
    assert next_backup(now, at) == expected


@pytest.mark.spec("OPS-010")
def test_only_the_newest_archives_are_kept(tmp_path: Path) -> None:
    names = [f"sibillo-2026110{day}T030000Z.tar.age" for day in range(1, 8)]
    for name in names:
        (tmp_path / name).write_bytes(b"archive")
    (tmp_path / "status.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("the household's own file")
    prune_archives(tmp_path, keep=3)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([*names[-3:], "notes.txt", "status.json"])


@pytest.fixture
def instance_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


@pytest.fixture
def some_default(database: Database, default_model: HarnessModel) -> None:
    default_model.connect(create_tenant(database))


def _status(
    started: timedelta | None, attempt: timedelta | None, success: timedelta | None, outcome: str | None
) -> Any:
    now = datetime.now(UTC)

    def at(ago: timedelta | None) -> str | None:
        return None if ago is None else (now - ago).isoformat()

    return {
        "started": at(started),
        "last_attempt": at(attempt),
        "last_success": at(success),
        "outcome": outcome,
        "archive": None,
        "error": "pg_dump failed" if outcome == "failed" else None,
    }


@pytest.mark.spec("OPS-011")
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "degraded"),
        (_status(timedelta(hours=1), None, None, None), "ok"),
        (_status(timedelta(days=5), timedelta(hours=2), timedelta(hours=2), "succeeded"), "ok"),
        (_status(timedelta(days=5), timedelta(hours=2), timedelta(days=1), "failed"), "degraded"),
        (_status(timedelta(days=5), timedelta(days=3), timedelta(days=3), "succeeded"), "degraded"),
        (_status(timedelta(days=3), None, None, None), "degraded"),
    ],
    ids=["missing", "just-started", "recent-success", "last-failed", "stale-success", "never-ran"],
)
def test_backups_that_fail_or_stop_make_the_instance_degraded(
    tmp_path: Path,
    server: Server,
    instance_admin: Account,
    some_default: None,
    status: dict[str, Any] | None,
    expected: str,
) -> None:
    path = tmp_path / "status.json"
    if status is not None:
        path.write_text(json.dumps(status))
    token = login(server, instance_admin)
    api, origin = server.start_twin_api(SIBILLO_BACKUP_STATUS=str(path))
    try:
        headers = {"Authorization": f"Bearer {token}", "X-Forwarded-For": fresh_source()}
        health = httpx.get(f"{origin}/v1/health", headers=headers, timeout=30).json()
        anonymous = httpx.get(f"{origin}/v1/health", headers={"X-Forwarded-For": fresh_source()}, timeout=30).json()
    finally:
        api.close()
    assert health["checks"]["backups"] == expected
    assert health["status"] == expected
    assert anonymous == {"status": expected}
