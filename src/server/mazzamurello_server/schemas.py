"""Request and response bodies of the public API (specs/contracts/openapi.yaml)."""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, PlainSerializer, UrlConstraints

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
    # `cookie` for browsers: the token is set as an HttpOnly cookie instead (ADR-0067).
    session_delivery: Literal["token", "cookie"] = "token"


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
    # Absent when the session was set as a cookie.
    token: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None
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


class ModelPricesOut(Response):
    input: str
    # Left out when not set: the contract has no null price.
    cached_input: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None
    output: str
    currency: str


# A connection reaches OpenRouter or a server with an OpenAI-compatible API (ADR-0057, ADR-0069).
type ConnectionKind = Literal["openrouter", "openai"]
# Where inference runs (MOD-010, ADR-0066).
type Location = Literal["local", "remote"]
type Address = Annotated[HttpUrl, UrlConstraints(max_length=2000)]
type ApiKey = Annotated[str, Field(min_length=1, max_length=1000)]


type ContextWindow = Annotated[int, Field(ge=512, le=10_000_000)]


class CreateConnectionRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    kind: ConnectionKind
    base_url: Address | None = None
    location: Location | None = None
    context_window: ContextWindow | None = None
    api_key: ApiKey | None = None


class UpdateConnectionRequest(Request):
    """Only the fields present change; `api_key` set to null is removed."""

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    base_url: Address | None = None
    location: Location | None = None
    context_window: ContextWindow | None = None
    api_key: ApiKey | None = None


class Connection(Response):
    id: uuid.UUID
    name: str
    kind: ConnectionKind
    base_url: str
    location: Location
    has_api_key: bool
    private_network: bool
    context_window: int | None
    model_count: int
    models_refreshed_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class ConnectionList(Response):
    items: list[Connection]


type TestStepName = Literal["resolve", "connect", "tls", "authenticate", "list_models"]
type TestReason = Literal[
    "name_not_found",
    "connection_refused",
    "timeout",
    "tls_untrusted",
    "address_not_allowed",
    "http_error",
    "unauthorized",
    "not_a_model_server",
]


class ConnectionTestStep(Response):
    step: TestStepName
    outcome: Literal["passed", "failed", "skipped"]
    duration_ms: int | None
    detail: str


class ConnectionTest(Response):
    passed: bool
    steps: list[ConnectionTestStep]
    reason: TestReason | None
    http_status: int | None
    technical_detail: str | None
    model_count: int | None


class ModelChoice(Request):
    connection_id: uuid.UUID
    model: Annotated[str, Field(min_length=1, max_length=200)]


class ModelChoiceOut(Response):
    connection_id: uuid.UUID
    model: str


class ModelOption(Response):
    connection_id: uuid.UUID
    connection_name: str
    model: str
    name: str
    location: Location
    prices: ModelPricesOut | None
    context_window: int | None
    tools: bool | None
    reasoning: bool | None


class ModelList(Response):
    items: list[ModelOption]
    default: ModelChoiceOut | None


# How much a model reasons before it answers, and the tools a user can switch off (CNV-013, ADR-0081).
type Reasoning = Literal["off", "on", "deep"]
type ToolName = Literal["web_search", "read_page", "shell", "file_system", "offer_download"]


def _unique(tools: list[ToolName]) -> list[ToolName]:
    if len(set(tools)) != len(tools):
        raise ValueError("a tool is listed twice")
    return tools


type DisabledTools = Annotated[list[ToolName], AfterValidator(_unique)]
# Postgres text holds no NUL character.
type Instructions = Annotated[str, Field(max_length=20000, pattern=r"^[^\x00]*$")]


class UserSettings(Request):
    """A user's defaults for their conversations (CNV-013, CNV-014)."""

    model: ModelChoice | None
    reasoning: Reasoning | None
    disabled_tools: DisabledTools
    base_instructions: Instructions | None
    additional_instructions: Instructions | None


class UserSettingsOut(Response):
    model: ModelChoiceOut | None
    reasoning: Reasoning | None
    disabled_tools: list[ToolName]
    base_instructions: str | None
    additional_instructions: str | None
    built_in_base_instructions: str


class CreateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    model: ModelChoice | None = None
    reasoning: Reasoning | None = None
    disabled_tools: DisabledTools | None = None


class UpdateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    archived: bool | None = None
    model: ModelChoice | None = None
    # Present and null moves the conversation out of its folder (CNV-007).
    folder_id: uuid.UUID | None = None
    pinned: bool | None = None
    reasoning: Reasoning | None = None
    disabled_tools: DisabledTools | None = None
    # Present and null uses the user's defaults again (CNV-014).
    base_instructions: Instructions | None = None
    additional_instructions: Instructions | None = None


class ForkRequest(Request):
    run_id: uuid.UUID


class Money(Response):
    amount: str
    currency: str


class ForkedFrom(Response):
    conversation_id: uuid.UUID | None
    run_id: uuid.UUID | None


class Usage(Response):
    last_24_hours: list[Money]
    last_30_days: list[Money]
    unpriced_requests: int


class CreateFolderRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]


class UpdateFolderRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    pinned: bool | None = None
    collapsed: bool | None = None


class Folder(Response):
    id: uuid.UUID
    name: str
    pinned: bool
    collapsed: bool
    last_message_at: Timestamp | None
    created_at: Timestamp


class SearchResult(Response):
    conversation_id: uuid.UUID
    title: str
    snippet: str
    last_message_at: Timestamp


class SearchResults(Response):
    items: list[SearchResult]


class RewindRequest(Request):
    run_id: uuid.UUID | None


class Conversation(Response):
    id: uuid.UUID
    title: str
    archived: bool
    active_run_id: uuid.UUID | None
    model: ModelChoiceOut | None
    reasoning: Reasoning
    disabled_tools: list[ToolName]
    base_instructions: str | None
    additional_instructions: str | None
    folder_id: uuid.UUID | None
    pinned: bool
    forked_from: ForkedFrom | None
    cost: list[Money]
    last_message_at: Timestamp
    created_at: Timestamp
    updated_at: Timestamp


class ConversationPage(Response):
    items: list[Conversation]
    next_cursor: str | None


class FolderEntry(Response):
    kind: Literal["folder"] = "folder"
    folder: Folder
    conversations: list[Conversation]


class ConversationEntry(Response):
    kind: Literal["conversation"] = "conversation"
    conversation: Conversation


class ConversationListPage(Response):
    items: list[FolderEntry | ConversationEntry]
    next_cursor: str | None


type RunKind = Literal["message", "resume"]


class RunError(Response):
    code: str
    reason: str | None


class PathRun(Response):
    run_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: RunKind
    message_ids: list[str]
    cost: list[Money]
    # Why the run failed, shown in place of its answer (UX-014).
    error: RunError | None


class MessagePage(Response):
    items: list[dict[str, Any]]
    runs: list[PathRun]
    next_cursor: str | None


class ModelRef(Response):
    connection_id: uuid.UUID | None
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
    # A Mazzamurello extension: the files attached to the message, already uploaded (CNV-017).
    attachments: Annotated[list[Annotated[str, Field(max_length=4096)]], Field(max_length=20)] = []


# A conversation's workspace (UX-019, ADR-0079).


class WorkspaceSummary(Response):
    size: int
    quota: int


class WorkspaceEntry(Response):
    name: str
    path: str
    type: Literal["file", "folder", "link"]
    size: int
    modified: Timestamp


class WorkspaceFolder(Response):
    path: str
    entries: list[WorkspaceEntry]


class WorkspacePathRequest(Request):
    path: Annotated[str, Field(min_length=1, max_length=4096)]


class WorkspaceMoveRequest(Request):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: Annotated[str, Field(alias="from", min_length=1, max_length=4096)]
    to: Annotated[str, Field(min_length=1, max_length=4096)]
