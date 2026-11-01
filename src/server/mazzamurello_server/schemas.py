"""Request and response bodies of the public API (specs/contracts/openapi.yaml)."""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PlainSerializer, UrlConstraints

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


type DecimalText = Annotated[str, Field(pattern=r"^[0-9]{1,10}(\.[0-9]{1,10})?$")]


class ModelPrices(Request):
    input: DecimalText
    cached_input: DecimalText | None = None
    output: DecimalText
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class ModelPricesOut(Response):
    input: str
    # Left out when not set: the contract has no null price.
    cached_input: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None
    output: str
    currency: str


# The API of a model's endpoint (ADR-0057).
type ModelApi = Literal["openai", "openrouter"]


class CreateModelConfigurationRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    api: ModelApi = "openai"
    base_url: Annotated[HttpUrl, UrlConstraints(max_length=2000)]
    model: Annotated[str, Field(min_length=1, max_length=200)]
    api_key: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    paid: bool
    prices: ModelPrices | None = None
    is_default: bool = False


class UpdateModelConfigurationRequest(Request):
    """Only the fields present change; `api_key` and `prices` set to null are removed."""

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    api: ModelApi | None = None
    base_url: Annotated[HttpUrl, UrlConstraints(max_length=2000)] | None = None
    model: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    api_key: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    paid: bool | None = None
    prices: ModelPrices | None = None
    is_default: bool | None = None


class ModelConfiguration(Response):
    id: uuid.UUID
    name: str
    api: ModelApi
    base_url: str
    model: str
    has_api_key: bool
    paid: bool
    prices: ModelPricesOut | None
    is_default: bool
    created_at: Timestamp
    updated_at: Timestamp


class ModelConfigurationList(Response):
    items: list[ModelConfiguration]


class CreateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class UpdateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    archived: bool | None = None
    active_run_id: uuid.UUID | None = None


class Conversation(Response):
    id: uuid.UUID
    title: str
    archived: bool
    active_run_id: uuid.UUID | None
    created_at: Timestamp
    updated_at: Timestamp


class ConversationPage(Response):
    items: list[Conversation]
    next_cursor: str | None


type RunKind = Literal["message", "resume"]


class PathRun(Response):
    run_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: RunKind
    message_ids: list[str]
    versions: list[uuid.UUID]


class MessagePage(Response):
    items: list[dict[str, Any]]
    runs: list[PathRun]
    next_cursor: str | None


class ModelRef(Response):
    provider: str
    model: str


class Run(Response):
    id: uuid.UUID
    conversation_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: RunKind
    status: Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]
    error_code: str | None
    model: ModelRef | None
    last_event_seq: int
    created_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None


class AgUiInputMessage(BaseModel):
    """A message of an AG-UI run input; only the last one, from the user, is used (ADR-0031)."""

    model_config = ConfigDict(extra="allow")

    id: str
    role: str
    content: Any = None


class RunInput(BaseModel):
    """The fields of an AG-UI `RunAgentInput` that the server uses; the others are ignored."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    thread_id: uuid.UUID = Field(alias="threadId")
    run_id: uuid.UUID = Field(alias="runId")
    parent_run_id: uuid.UUID | None = Field(default=None, alias="parentRunId")
    messages: Annotated[list[AgUiInputMessage], Field(min_length=1)]
    resume: list[dict[str, Any]] | None = None
