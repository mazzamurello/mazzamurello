"""Speech through the household's connections (API-006, ADR-0088).

The model the tests serve also transcribes and speaks, as an OpenAI-compatible
server, whose speech models are told apart by their names, and as OpenRouter,
which says which models do what and lists their voices (tests/support/model.py).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import OPENROUTER_SPEECH_MODELS, SPEECH_COST, TRANSCRIPTION_COST, heard
from tests.support.runs import create_conversation, run_input, start_run, wait_for_run
from tests.support.server import Server

RECORDING = b"\x1aE\xdf\xa3" + bytes(range(256)) * 8


@dataclass(frozen=True)
class Household:
    member: Account
    token: str
    model: HouseholdModel
    openrouter_id: str


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> Household:
    member = create_account(database, create_tenant(database))
    model = default_model.connect(member.tenant_id)
    with server.client(model.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": model.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{secrets.token_hex(8)}",
            },
        )
    assert response.status_code == 201, response.text
    return Household(member, login(server, member), model, body(response)["id"])


def _models(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/models")
    assert response.status_code == 200, response.text
    return body(response)


def _set_speech(server: Server, household: Household, settings: dict[str, Any]) -> dict[str, Any]:
    with server.client(household.model.admin_token) as client:
        response = client.put("/tenant/speech", json=settings)
    assert response.status_code == 200, response.text
    return body(response)


def _transcribe(server: Server, token: str, audio: bytes = RECORDING, name: str = "turn.webm") -> Any:
    with server.client(token) as client:
        return client.post("/speech/transcriptions", files={"audio": (name, audio, f"audio/{name.rpartition('.')[2]}")})


def _synthesize(server: Server, token: str, text: str) -> Any:
    with server.client(token) as client:
        return client.post("/speech/synthesis", json={"text": text})


@pytest.mark.spec("API-006")
def test_connections_say_which_models_transcribe_and_which_speak(server: Server, household: Household) -> None:
    items = _models(server, household.token)["items"]
    local = {m["model"]: m for m in items if m["connection_id"] == household.model.connection_id}
    # An OpenAI-compatible server says nothing: the names tell.
    assert {name: (m["kind"], m["voices"]) for name, m in local.items()} == {
        "test-model": ("chat", None),
        "refuses-tools": ("chat", None),
        "gpt-4o-mini": ("chat", None),
        "test-transcribe": ("transcription", None),
        "test-tts": ("speech", None),
    }
    # OpenRouter says, with the voices of each speech model.
    remote = {m["model"]: m for m in items if m["connection_id"] == household.openrouter_id}
    for model_id, name, modality, voices in OPENROUTER_SPEECH_MODELS:
        assert (remote[model_id]["name"], remote[model_id]["kind"]) == (name, modality)
        assert remote[model_id]["voices"] == (None if voices is None else list(voices))
    assert remote["test/popular"]["kind"] == "chat"
    # The household has no speech models until its admins choose them.
    assert _models(server, household.token)["speech"] == {"transcription": None, "speech": None}


@pytest.mark.spec("API-006", "TEN-006")
def test_admins_choose_the_households_speech_models(server: Server, household: Household) -> None:
    chosen = {
        "transcription": {"connection_id": household.model.connection_id, "model": "test-transcribe"},
        "speech": {"connection_id": household.openrouter_id, "model": "test/voice", "voice": "nova"},
    }
    with server.client(household.token) as client:
        assert_problem(client.put("/tenant/speech", json=chosen), 403, "permission.denied")
    with server.client(household.model.admin_token) as client:
        # Only a model of the matching kind, of one of the household's connections.
        for wrong in (
            {**chosen, "transcription": {"connection_id": household.model.connection_id, "model": "test-model"}},
            {
                **chosen,
                "speech": {"connection_id": household.openrouter_id, "model": "test/transcribe", "voice": "nova"},
            },
            {**chosen, "speech": {"connection_id": household.openrouter_id, "model": "test/unknown", "voice": "nova"}},
        ):
            assert_problem(client.put("/tenant/speech", json=wrong), 422, "request.validation_failed")
    assert _set_speech(server, household, chosen) == chosen
    # Every member sees them.
    assert _models(server, household.token)["speech"] == chosen
    # Taken away, with null.
    assert _set_speech(server, household, {"transcription": None, "speech": None}) == {
        "transcription": None,
        "speech": None,
    }
    assert _models(server, household.token)["speech"] == {"transcription": None, "speech": None}


@pytest.mark.spec("API-006", "UX-005")
def test_a_spoken_turn_is_transcribed_by_the_households_model(server: Server, household: Household) -> None:
    # No transcription model: no spoken turns.
    assert_problem(_transcribe(server, household.token), 409, "speech.unavailable")
    _set_speech(
        server,
        household,
        {"transcription": {"connection_id": household.model.connection_id, "model": "test-transcribe"}, "speech": None},
    )
    response = _transcribe(server, household.token)
    assert response.status_code == 200, response.text
    assert body(response) == {"text": heard(len(RECORDING), "webm")}
    sent = household.model.endpoint.speech("/audio/transcriptions")[-1]
    assert (sent.body["model"], sent.body["bytes"]) == ("test-transcribe", len(RECORDING))


@pytest.mark.spec("API-006", "MOD-006")
def test_a_remote_transcription_carries_the_key_and_its_cost_is_recorded(
    database: Database, server: Server, household: Household
) -> None:
    _set_speech(
        server,
        household,
        {"transcription": {"connection_id": household.openrouter_id, "model": "test/transcribe"}, "speech": None},
    )
    response = _transcribe(server, household.token, name="turn.ogg")
    assert response.status_code == 200, response.text
    assert body(response) == {"text": heard(len(RECORDING), "ogg")}
    sent = household.model.endpoint.speech("/audio/transcriptions")[-1]
    assert sent.openrouter
    assert (sent.authorization or "").startswith("Bearer sk-or-v1-")
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT purpose, model, cost, currency, conversation_id FROM usage_ledger WHERE owner_id = %s",
            (household.member.id,),
        ).fetchall()
    assert [(r[0], r[1], r[3], r[4]) for r in rows] == [("speech", "test/transcribe", "USD", None)]
    assert rows[0][2] == Decimal(str(TRANSCRIPTION_COST))


@pytest.mark.spec("API-006")
def test_recordings_are_bounded_and_failures_say_so(server: Server, household: Household) -> None:
    _set_speech(
        server,
        household,
        {"transcription": {"connection_id": household.model.connection_id, "model": "test-transcribe"}, "speech": None},
    )
    assert_problem(_transcribe(server, household.token, b"x" * (25 * 1024 * 1024 + 1)), 413, "file.too_large")
    failed = assert_problem(_transcribe(server, household.token, b"fail"), 502, "model.request_failed")
    # It says why.
    assert "500" in failed["detail"]
    with server.client(household.token) as client:
        assert_problem(client.post("/speech/transcriptions", files={}), 422, "request.validation_failed")


@pytest.mark.spec("API-006", "UX-005")
def test_text_is_read_aloud_with_the_households_voice(database: Database, server: Server, household: Household) -> None:
    assert_problem(_synthesize(server, household.token, "Hello."), 409, "speech.unavailable")
    _set_speech(
        server,
        household,
        {
            "transcription": None,
            "speech": {"connection_id": household.openrouter_id, "model": "test/voice", "voice": "nova"},
        },
    )
    response = _synthesize(server, household.token, "Buongiorno, ecco il piano.")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/")
    assert response.content.startswith(b"RIFF")
    sent = household.model.endpoint.speech("/audio/speech")[-1]
    assert sent.openrouter
    assert (sent.body["model"], sent.body["voice"], sent.body["input"]) == (
        "test/voice",
        "nova",
        "Buongiorno, ecco il piano.",
    )
    assert (sent.authorization or "").startswith("Bearer sk-or-v1-")
    # Its cost, as OpenRouter reports it for the generation once the audio is sent (MOD-006).
    deadline = time.monotonic() + 10
    while True:
        with database.superuser() as conn:
            rows = conn.execute(
                "SELECT model, cost, currency FROM usage_ledger WHERE owner_id = %s AND purpose = 'speech'",
                (household.member.id,),
            ).fetchall()
        if (rows and rows[0][1] is not None) or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert [(r[0], r[1], r[2]) for r in rows] == [("test/voice", Decimal(str(SPEECH_COST)), "USD")]
    # A piece of an answer at a time.
    assert_problem(_synthesize(server, household.token, "a" * 4001), 422, "request.validation_failed")
    assert_problem(_synthesize(server, household.token, "   "), 422, "request.validation_failed")
    failed = assert_problem(_synthesize(server, household.token, "fail"), 502, "model.request_failed")
    assert "500" in failed["detail"]


@pytest.mark.spec("API-006")
def test_a_server_speech_model_reads_with_the_voice_its_admin_names(server: Server, household: Household) -> None:
    _set_speech(
        server,
        household,
        {
            "transcription": None,
            "speech": {"connection_id": household.model.connection_id, "model": "test-tts", "voice": "af_heart"},
        },
    )
    response = _synthesize(server, household.token, "Hello there.")
    assert response.status_code == 200, response.text
    sent = household.model.endpoint.speech("/audio/speech")[-1]
    assert not sent.openrouter
    assert (sent.body["model"], sent.body["voice"]) == ("test-tts", "af_heart")


@pytest.mark.spec("API-006", "TEN-001")
def test_another_households_connection_cannot_be_chosen(
    database: Database, server: Server, household: Household, default_model: HarnessModel
) -> None:
    other = default_model.connect(create_account(database, create_tenant(database)).tenant_id)
    with server.client(household.model.admin_token) as client:
        foreign = {"transcription": {"connection_id": other.connection_id, "model": "test-transcribe"}, "speech": None}
        assert_problem(client.put("/tenant/speech", json=foreign), 422, "request.validation_failed")


@pytest.mark.spec("API-006", "UX-005")
def test_the_assistant_is_told_how_a_turn_came(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    systems: dict[str | None, str] = {}
    for voice in (None, "dictated", "hands_free"):
        text = f"how it came {voice} {secrets.token_hex(4)}"
        run_id, _ = start_run(server, household.token, conversation["id"], text, voice=voice)
        assert wait_for_run(server, household.token, run_id)["status"] == "completed"
        systems[voice] = household.model.endpoint.requests_with(text)[0].system_text()
    # Dictated: words may have been misheard. Hands-free: the answer is read aloud, written for listening.
    assert "dictated" in systems["dictated"]
    assert "read aloud" not in systems["dictated"]
    assert "read aloud" in systems["hands_free"]
    assert "no shorter" in systems["hands_free"]
    assert "dictated" not in systems[None]
    assert "read aloud" not in systems[None]
    # Only these two.
    with server.client(household.token) as client:
        payload = run_input(conversation["id"], "whispered", None, None) | {"voice": "whispered"}
        assert_problem(
            client.post(f"/conversations/{conversation['id']}/runs", json=payload), 422, "request.validation_failed"
        )
