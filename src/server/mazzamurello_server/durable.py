"""Names shared by the API, which enqueues runs and reads their events, and the worker (ADR-0034, ADR-0052)."""

from __future__ import annotations

from dbos import DBOSClient

APPLICATION_NAME = "mazzamurello"
# Changed deliberately: in-flight workflows recover only on a compatible version (ADR-0034).
APPLICATION_VERSION = "2026.10.1"
RUN_QUEUE = "runs"
RUN_WORKFLOW = "mazzamurello.run"
EVENTS_STREAM = "events"


def create_client(database_url: str) -> DBOSClient:
    """A client of the durable execution engine, connected like the rest of the process (TEN-004)."""
    return DBOSClient(system_database_url=database_url, application_name=APPLICATION_NAME)
