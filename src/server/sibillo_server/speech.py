"""Speech through the household's connections: spoken turns and reading aloud (API-006, UX-005, ADR-0088).

The household's transcription and speech models are models of its
connections, reached with the connection's credentials, which never leave the
control plane. A recording is held for its request only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from starlette.datastructures import UploadFile

from sibillo_server import egress, errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.connections import SecretKey, Target, connection_client
from sibillo_server.credentials import uuid7
from sibillo_server.database import Identity, transaction
from sibillo_server.encryption import decrypt

logger = logging.getLogger(__name__)
router = APIRouter()

# The largest recording a transcription takes, as OpenRouter's and OpenAI's (ADR-0088).
RECORDING_BYTES = 25 * 1024 * 1024
# The file name a recording is sent under: servers tell its format by the extension.
EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav"}
# The most of a provider's error that is logged and said.
ERROR_CHARS = 300
# A speech model takes seconds for a long text; the connection test's limit is for listing models (ADR-0088).
SPEECH_SECONDS = 120
SPEECH_TIMEOUT = httpx.Timeout(SPEECH_SECONDS, connect=10)
# How often, and how long apart, OpenRouter is asked for a generation's cost once the audio is sent.
COST_ATTEMPTS = 5
COST_INTERVAL_SECONDS = 1.0
# Speech requests whose cost is still being asked for.
_COSTING: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class _Speaker:
    """The connection of one of the household's speech models, and the model."""

    target: Target
    model: str
    voice: str | None
    provider: str
    location: str


def _unavailable() -> errors.ApiError:
    return errors.ApiError(409, "speech.unavailable", "The household has no model for this")


def _failed(detail: str = "The speech model answered with something that is not speech.") -> errors.ApiError:
    """A failed speech request, saying why (API-006)."""
    return errors.ApiError(502, "model.request_failed", "The speech model failed", detail=detail)


# The household's model of each use, and the connection that offers it.
QUERIES = {
    "transcription": "SELECT id, kind, base_url, location, api_key_ciphertext, private_network,"
    " transcription_model AS model, NULL AS voice FROM connections WHERE transcription_model IS NOT NULL",
    "speech": "SELECT id, kind, base_url, location, api_key_ciphertext, private_network, speech_model AS model,"
    " speech_voice AS voice FROM connections WHERE speech_model IS NOT NULL",
}


async def _speaker(engine: Any, identity: Identity, secret: bytes, use: Literal["transcription", "speech"]) -> _Speaker:
    """The household's model for `use`; row-level security scopes the lookup to the user's tenant."""
    async with transaction(engine, identity) as connection:
        row = (await connection.execute(text(QUERIES[use]))).one_or_none()
        # Remote speech goes only where the user's data egress policy allows (MOD-003, ADR-0091).
        allowed = row is None or await egress.allows(connection, row.location)
    if row is None:
        raise _unavailable()
    if not allowed:
        raise egress.refused()
    key = None if row.api_key_ciphertext is None else decrypt(secret, row.id, bytes(row.api_key_ciphertext))
    return _Speaker(
        Target(row.kind, row.base_url, key, row.private_network),
        row.model,
        row.voice,
        "openrouter" if row.kind == "openrouter" else "openai",
        row.location,
    )


def _headers(target: Target) -> dict[str, str]:
    return {} if target.api_key is None else {"Authorization": f"Bearer {target.api_key}"}


async def _post(target: Target, path: str, **request: Any) -> httpx.Response:
    url = target.base_url.rstrip("/") + path
    try:
        async with connection_client(target, SPEECH_TIMEOUT) as client:
            response = await client.post(url, headers=_headers(target), **request)
    except httpx.TimeoutException as error:
        logger.warning("speech request to %s failed: %s", path, type(error).__name__)
        raise _failed(f"The speech model took more than {SPEECH_SECONDS} seconds to answer.") from None
    except httpx.HTTPError as error:
        logger.warning("speech request to %s failed: %s", path, type(error).__name__)
        raise _failed(f"The speech model could not be reached ({type(error).__name__}).") from None
    if not response.is_success:
        excerpt = " ".join(response.text[:ERROR_CHARS].split())
        logger.warning("speech request to %s answered %s: %s", path, response.status_code, excerpt)
        raise _failed(f"The speech model answered {response.status_code} {response.reason_phrase}: {excerpt}")
    return response


async def _record_cost(engine: Any, identity: Identity, speaker: _Speaker, cost: object) -> None:
    """Record a speech request in the cost ledger, with its cost when the provider reported one (MOD-006).

    A local model costs nothing (ADR-0069).
    """
    try:
        amount = None if cost is None else Decimal(str(cost))
    except InvalidOperation:
        amount = None
    if amount is not None and (not amount.is_finite() or amount < 0):
        amount = None
    if amount is None and speaker.location == "local":
        amount, source = Decimal(0), "free"
    else:
        source = "unknown" if amount is None else "provider"
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, purpose, provider, model, cost, currency,"
                " price_source, created_at) VALUES (:id, :tenant_id, :owner_id, 'speech', :provider, :model, :cost,"
                " :currency, :price_source, now())"
            ),
            {
                "id": uuid7(),
                "tenant_id": identity.tenant_id,
                "owner_id": identity.user_id,
                "provider": speaker.provider,
                "model": speaker.model,
                "cost": amount,
                "currency": None if amount is None else "USD",
                "price_source": source,
            },
        )


async def _generation_cost(target: Target, generation: str) -> object:
    """The cost OpenRouter reports for a generation, once it has it; None when it never says (ADR-0088)."""
    url = target.base_url.rstrip("/") + "/generation"
    for _ in range(COST_ATTEMPTS):
        await asyncio.sleep(COST_INTERVAL_SECONDS)
        try:
            async with connection_client(target) as client:
                response = await client.get(url, params={"id": generation}, headers=_headers(target))
        except httpx.HTTPError:
            continue
        if response.is_success:
            data = cast(dict[str, Any], response.json()).get("data")
            cost = cast(dict[str, Any], data).get("total_cost") if isinstance(data, dict) else None
            if cost is not None:
                return cost
    return None


async def _record_later(engine: Any, identity: Identity, speaker: _Speaker, generation: str | None) -> None:
    cost = None if generation is None else await _generation_cost(speaker.target, generation)
    await _record_cost(engine, identity, speaker, cost)


async def _recording(request: Request) -> tuple[bytes, str]:
    """The recording of the form and its format, refused when too large; it is never stored."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > RECORDING_BYTES + 64 * 1024:
        raise errors.ApiError(413, "file.too_large", "The recording is larger than 25 MB")
    form = await request.form(max_files=1, max_fields=1, max_part_size=RECORDING_BYTES + 1)
    upload = form.get("audio")
    if not isinstance(upload, UploadFile):
        raise errors.invalid("/audio", "required")
    audio = await upload.read(RECORDING_BYTES + 1)
    await form.close()
    if len(audio) > RECORDING_BYTES:
        raise errors.ApiError(413, "file.too_large", "The recording is larger than 25 MB")
    if not audio:
        raise errors.invalid("/audio", "empty")
    media = (upload.content_type or "").split(";")[0].strip().lower()
    name = upload.filename or ""
    extension = EXTENSIONS.get(media) or (name.rpartition(".")[2].lower() if "." in name else "webm")
    return audio, extension


@router.post(
    "/speech/transcriptions",
    response_model=schemas.Transcription,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": {"type": "object", "required": ["audio"]}}},
        }
    },
)
async def transcribe(
    request: Request, identity: Authenticated, engine: Engine, secret: SecretKey
) -> schemas.Transcription:
    """Turn one recorded spoken turn into text, with the household's transcription model (API-006)."""
    speaker = await _speaker(engine, identity, secret, "transcription")
    audio, extension = await _recording(request)
    response = await _post(
        speaker.target,
        "/audio/transcriptions",
        files={"file": (f"turn.{extension}", audio, f"audio/{extension}")},
        data={"model": speaker.model},
    )
    try:
        payload = cast(dict[str, Any], response.json())
    except ValueError:
        raise _failed() from None
    said = payload.get("text")
    if not isinstance(said, str):
        raise _failed()
    usage = payload.get("usage")
    await _record_cost(
        engine, identity, speaker, cast(dict[str, Any], usage).get("cost") if isinstance(usage, dict) else None
    )
    return schemas.Transcription(text=said.strip())


@router.post("/speech/synthesis", response_class=Response)
async def synthesize(
    body: schemas.SynthesisRequest, identity: Authenticated, engine: Engine, secret: SecretKey
) -> Response:
    """Read text aloud, as audio, with the household's speech model and voice (API-006)."""
    speaker = await _speaker(engine, identity, secret, "speech")
    response = await _post(
        speaker.target,
        "/audio/speech",
        json={"model": speaker.model, "input": body.text, "voice": speaker.voice, "response_format": "mp3"},
    )
    media = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
    if not media.startswith("audio/"):
        raise _failed()
    # OpenRouter reports the cost of speech for its generation, a moment after (ADR-0088).
    generation = response.headers.get("x-generation-id") if speaker.provider == "openrouter" else None
    task = asyncio.create_task(_record_later(engine, identity, speaker, generation))
    _COSTING.add(task)
    task.add_done_callback(_COSTING.discard)
    return Response(content=response.content, media_type=media, headers={"Cache-Control": "no-store"})
