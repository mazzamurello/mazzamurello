"""Request and response bodies of the public API (specs/contracts/openapi.yaml)."""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

type Role = Literal["member", "tenant_admin"]


class Request(BaseModel):
    """A request body: unknown fields are rejected (`additionalProperties: false`)."""

    model_config = ConfigDict(extra="forbid")


class Response(BaseModel):
    pass


def _rfc3339(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


# Timestamps are RFC 3339 in UTC.
type Timestamp = Annotated[datetime.datetime, PlainSerializer(_rfc3339, return_type=str, when_used="json")]


class LoginRequest(Request):
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    device_name: Annotated[str, Field(min_length=1, max_length=100)]


class User(Response):
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    display_name: str
    role: Role
    instance_admin: bool
    created_at: Timestamp


class DeviceSession(Response):
    id: uuid.UUID
    device_name: str
    created_at: Timestamp
    last_used_at: Timestamp
    expires_at: Timestamp
    current: bool


class LoginResponse(Response):
    token: str
    session: DeviceSession
    user: User


class DeviceSessionList(Response):
    items: list[DeviceSession]


class UserPage(Response):
    items: list[User]
    next_cursor: str | None


class _NewUser(Request):
    username: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=12, max_length=1024)]


class CreateUserRequest(_NewUser):
    role: Role


class FirstAdminRequest(_NewUser):
    """The first admin of a new tenant is a tenant admin."""

    role: Literal["tenant_admin"]


class CreateTenantRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    admin: FirstAdminRequest


class Tenant(Response):
    id: uuid.UUID
    name: str
    created_at: Timestamp


class TenantPage(Response):
    items: list[Tenant]
    next_cursor: str | None
