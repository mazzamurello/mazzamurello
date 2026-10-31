"""Login rate limits (AUTH-006, ADR-0047).

Each attempt is recorded as the server records it after verifying a
password: through `auth_record_login_attempt`, as `mzm_app`, with no request
context. Earlier attempts are arranged as superuser when their time matters.
Every test uses fresh usernames and source addresses, so the limits of one
test never count attempts of another.
"""

from __future__ import annotations

import ipaddress

import pytest

from tests.support.database import Database, uuid7

USERNAME_LIMIT = 5
SOURCE_LIMIT = 20
WINDOW_SECONDS = 15 * 60


def _username() -> str:
    return f"user-{uuid7()}"


def _source() -> str:
    """A fresh address in the shared address space (RFC 6598)."""
    return str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("100.64.0.0")) + uuid7().int % (1 << 22)))


def _attempt(database: Database, username: str, source: str, *, success: bool) -> tuple[bool, int]:
    with database.app() as conn:
        row = conn.execute(
            "SELECT allowed, retry_after_seconds FROM auth_record_login_attempt(%s, %s::inet, %s)",
            (username, source, success),
        ).fetchone()
        conn.commit()
    assert row is not None
    return row


def _arrange_failures(database: Database, username: str, source: str, minutes_ago: list[int]) -> None:
    with database.superuser() as conn:
        for minutes in minutes_ago:
            conn.execute(
                "INSERT INTO login_attempts (username, source, success, created_at)"
                " VALUES (%s, %s::inet, false, now() - make_interval(mins => %s))",
                (username, source, minutes),
            )


def _recorded(database: Database, username: str) -> int:
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT count(*) FROM login_attempts WHERE lower(username) = lower(%s)", (username,)
        ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.spec("AUTH-006")
def test_failures_for_one_username_are_limited_ignoring_case(database: Database) -> None:
    username = _username()
    spellings = [username, username.upper(), username.capitalize()]
    for attempt in range(USERNAME_LIMIT):
        # From different addresses: only the username limit can be reached.
        assert _attempt(database, spellings[attempt % 3], _source(), success=False) == (True, 0)
    # Refused even with the right password.
    allowed, retry_after = _attempt(database, username, _source(), success=True)
    assert not allowed
    assert 0 < retry_after <= WINDOW_SECONDS


@pytest.mark.spec("AUTH-006")
def test_refused_attempts_are_not_recorded(database: Database) -> None:
    username = _username()
    for _ in range(USERNAME_LIMIT):
        _attempt(database, username, _source(), success=False)
    for _ in range(3):
        assert _attempt(database, username, _source(), success=False)[0] is False
    assert _recorded(database, username) == USERNAME_LIMIT


@pytest.mark.spec("AUTH-006")
def test_failures_from_one_source_are_limited(database: Database) -> None:
    source = _source()
    for _ in range(SOURCE_LIMIT):
        assert _attempt(database, _username(), source, success=False) == (True, 0)
    assert _attempt(database, _username(), source, success=True)[0] is False
    # Other addresses are not affected.
    assert _attempt(database, _username(), _source(), success=True) == (True, 0)


@pytest.mark.spec("AUTH-006")
def test_successful_attempts_do_not_count(database: Database) -> None:
    username, source = _username(), _source()
    for _ in range(2 * SOURCE_LIMIT):
        assert _attempt(database, username, source, success=True) == (True, 0)
    for _ in range(USERNAME_LIMIT):
        assert _attempt(database, username, source, success=False) == (True, 0)


@pytest.mark.spec("AUTH-006")
def test_failures_outside_the_window_do_not_count_and_are_deleted(database: Database) -> None:
    username = _username()
    _arrange_failures(database, username, _source(), [16, 20, 30, 45, 60])
    assert _attempt(database, username, _source(), success=False) == (True, 0)
    assert _recorded(database, username) == 1


@pytest.mark.spec("AUTH-006")
def test_retry_waits_for_the_oldest_counted_failure_to_leave_the_window(database: Database) -> None:
    username = _username()
    # The oldest failure leaves the window in about one minute.
    _arrange_failures(database, username, _source(), [14, 10, 8, 6, 2])
    allowed, retry_after = _attempt(database, username, _source(), success=False)
    assert not allowed
    assert 50 <= retry_after <= 60


@pytest.mark.spec("AUTH-006")
def test_retry_waits_for_the_longer_limit_when_both_are_reached(database: Database) -> None:
    username, source = _username(), _source()
    # The username limit ends in about one minute ...
    _arrange_failures(database, username, _source(), [14, 10, 8, 6, 2])
    # ... and the source limit in about ten.
    with database.superuser() as conn:
        for _ in range(SOURCE_LIMIT):
            conn.execute(
                "INSERT INTO login_attempts (username, source, success, created_at)"
                " VALUES (%s, %s::inet, false, now() - interval '5 minutes')",
                (_username(), source),
            )
    allowed, retry_after = _attempt(database, username, source, success=False)
    assert not allowed
    assert 590 <= retry_after <= 600
