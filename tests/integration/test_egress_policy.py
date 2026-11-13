"""The data egress policy: local models only, for the household, a member or oneself (MOD-003, MOD-012, API-006,
ADR-0091).

Each household reaches the model the tests serve through two connections: a
server whose inference runs locally, and OpenRouter, which runs remotely
(tests/support/model.py).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.runs import create_conversation, messages, run_input, start_run, text_of, wait_for_run
from tests.support.server import Server

ANY = {"household": "any", "admin": "any", "own": "any", "effective": "any"}
RECORDING = b"\x1aE\xdf\xa3" + bytes(range(256)) * 8


@dataclass(frozen=True)
class Household:
    member: Account
    token: str
    model: HouseholdModel
    openrouter_id: str

    @property
    def admin_token(self) -> str:
        return self.model.admin_token

    @property
    def remote(self) -> dict[str, str]:
        return {"connection_id": self.openrouter_id, "model": "test/popular"}

    @property
    def local(self) -> dict[str, str]:
        return {"connection_id": self.model.connection_id, "model": "test-model"}


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


def _policies(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/me/egress-policy")
    assert response.status_code == 200, response.text
    return body(response)


def _own(server: Server, token: str, policy: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.put("/me/egress-policy", json={"policy": policy})
    assert response.status_code == 200, response.text
    return body(response)


def _for_household(server: Server, household: Household, policy: str) -> None:
    with server.client(household.admin_token) as client:
        response = client.put("/tenant/egress-policy", json={"policy": policy})
    assert response.status_code == 200, response.text
    assert body(response) == {"policy": policy}


def _for_user(server: Server, household: Household, user: Account, policy: str) -> None:
    with server.client(household.admin_token) as client:
        response = client.put(f"/tenant/users/{user.id}/egress-policy", json={"policy": policy})
    assert response.status_code == 200, response.text
    assert body(response) == {"policy": policy}


def _on_remote_model(server: Server, household: Household) -> str:
    conversation = create_conversation(server, household.token)
    with server.client(household.token) as client:
        response = client.patch(f"/conversations/{conversation['id']}", json={"model": household.remote})
    assert response.status_code == 200, response.text
    return str(conversation["id"])


@pytest.mark.spec("MOD-003")
def test_without_settings_every_model_is_allowed(server: Server, household: Household) -> None:
    assert _policies(server, household.token) == ANY
    conversation_id = _on_remote_model(server, household)
    text = f"anywhere {secrets.token_hex(4)}"
    run_id, events = start_run(server, household.token, conversation_id, text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"


@pytest.mark.spec("MOD-003", "TEN-006")
def test_only_a_tenant_admin_sets_the_households_and_a_users_policy(
    database: Database, server: Server, household: Household
) -> None:
    with server.client(household.token) as client:
        assert_problem(client.put("/tenant/egress-policy", json={"policy": "local_only"}), 403, "permission.denied")
        for method in ("get", "put"):
            response = client.request(
                method,
                f"/tenant/users/{household.member.id}/egress-policy",
                json={"policy": "local_only"} if method == "put" else None,
            )
            assert_problem(response, 403, "permission.denied")
    with server.client(household.admin_token) as client:
        assert body(client.get(f"/tenant/users/{household.member.id}/egress-policy")) == {"policy": "any"}
        for wrong in ({"policy": "nowhere"}, {}, {"policy": "local_only", "extra": True}):
            assert_problem(client.put("/tenant/egress-policy", json=wrong), 422, "request.validation_failed")
            assert_problem(
                client.put(f"/tenant/users/{household.member.id}/egress-policy", json=wrong),
                422,
                "request.validation_failed",
            )
    _for_user(server, household, household.member, "local_only")
    with server.client(household.admin_token) as client:
        assert body(client.get(f"/tenant/users/{household.member.id}/egress-policy")) == {"policy": "local_only"}
    # Another household's admin does not find the user.
    stranger = login(server, create_account(database, create_tenant(database), "tenant_admin"))
    with server.client(stranger) as client:
        assert_problem(client.get(f"/tenant/users/{household.member.id}/egress-policy"), 404, "resource.not_found")
        assert_problem(
            client.put(f"/tenant/users/{household.member.id}/egress-policy", json={"policy": "any"}),
            404,
            "resource.not_found",
        )


@pytest.mark.spec("MOD-003")
def test_the_strictest_policy_applies_and_nobody_loosens_anothers(
    database: Database, server: Server, household: Household
) -> None:
    # The household's applies to every member.
    other = login(server, create_account(database, household.member.tenant_id))
    _for_household(server, household, "local_only")
    for token in (household.token, other):
        assert _policies(server, token) == ANY | {"household": "local_only", "effective": "local_only"}
    # A member's own choice does not loosen it.
    assert _own(server, household.token, "any")["effective"] == "local_only"
    _for_household(server, household, "any")
    # The admin's choice for one member applies to them only.
    _for_user(server, household, household.member, "local_only")
    assert _policies(server, household.token) == ANY | {"admin": "local_only", "effective": "local_only"}
    assert _policies(server, other) == ANY
    _for_user(server, household, household.member, "any")
    # A member chooses for themself, and only for themself.
    assert _own(server, household.token, "local_only") == ANY | {"own": "local_only", "effective": "local_only"}
    assert _policies(server, other) == ANY
    assert _own(server, household.token, "any") == ANY
    with server.client(household.token) as client:
        assert_problem(client.put("/me/egress-policy", json={"policy": "remote"}), 422, "request.validation_failed")


@pytest.mark.spec("MOD-003")
def test_a_tenant_admin_never_sees_a_users_own_choice(server: Server, household: Household) -> None:
    _own(server, household.token, "local_only")
    with server.client(household.admin_token) as client:
        assert body(client.get(f"/tenant/users/{household.member.id}/egress-policy")) == {"policy": "any"}
    # Setting the user's policy and taking it away leaves the user's own choice in place.
    _for_user(server, household, household.member, "local_only")
    _for_user(server, household, household.member, "any")
    assert _policies(server, household.token) == ANY | {"own": "local_only", "effective": "local_only"}


@pytest.mark.spec("MOD-003", "UX-024")
def test_refused_models_stay_listed_with_the_policies(server: Server, household: Household) -> None:
    with server.client(household.token) as client:
        before = body(client.get("/models"))
    assert before["egress"] == ANY
    _own(server, household.token, "local_only")
    with server.client(household.token) as client:
        after = body(client.get("/models"))
    assert after["items"] == before["items"]
    assert {item["location"] for item in after["items"]} == {"local", "remote"}
    assert after["egress"] == ANY | {"own": "local_only", "effective": "local_only"}


@pytest.mark.spec("MOD-003", "MOD-012")
def test_a_run_on_a_refused_model_never_reaches_it(server: Server, household: Household) -> None:
    conversation_id = _on_remote_model(server, household)
    _own(server, household.token, "local_only")
    text = f"stay home {secrets.token_hex(4)}"
    with server.client(household.token) as client:
        response = client.post(f"/conversations/{conversation_id}/runs", json=run_input(conversation_id, text))
    assert_problem(response, 409, "model.egress_refused")
    assert household.model.endpoint.requests_with(text) == [], "the request left the household"
    # Nothing switched the model: the user chooses a local one, which answers.
    with server.client(household.token) as client:
        assert body(client.get(f"/conversations/{conversation_id}"))["model"] == household.remote
        changed = client.patch(f"/conversations/{conversation_id}", json={"model": household.local})
    assert changed.status_code == 200, changed.text
    run_id, events = start_run(server, household.token, conversation_id, text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"
    (request,) = household.model.endpoint.requests_with(text)
    assert request.openrouter is False


@pytest.mark.spec("MOD-003")
def test_a_policy_set_during_a_run_refuses_its_next_request(server: Server, household: Household) -> None:
    conversation_id = _on_remote_model(server, household)
    marker = f"midway-{secrets.token_hex(4)}"
    text = f"run:sleep 3; echo {marker}"
    run_id, _ = start_run(server, household.token, conversation_id, text, stop_after=1)
    # Once the model has asked for the command, while it runs, the household's admin says no.
    deadline = time.monotonic() + 30
    while not household.model.endpoint.requests_with(text):
        assert time.monotonic() < deadline, "the model was never asked"
        time.sleep(0.1)
    _for_household(server, household, "local_only")
    run = wait_for_run(server, household.token, run_id)
    assert (run["status"], run["error_code"]) == ("failed", "model.egress_refused")
    # Only the request made before the change reached the model: the command's result never left.
    (request,) = household.model.endpoint.requests_with(text)
    assert request.openrouter is True
    runs = {item["run_id"]: item for item in messages(server, household.token, conversation_id)["runs"]}
    assert runs[run_id]["error"]["code"] == "model.egress_refused"


@pytest.mark.spec("MOD-003", "MOD-012")
def test_a_new_conversation_starts_only_with_an_allowed_default(server: Server, household: Household) -> None:
    with server.client(household.token) as client:
        response = client.put(
            "/me/settings",
            json={
                "model": household.remote,
                "reasoning": None,
                "disabled_tools": [],
                "base_instructions": None,
                "additional_instructions": None,
            },
        )
    assert response.status_code == 200, response.text
    assert create_conversation(server, household.token)["model"] == household.remote
    _own(server, household.token, "local_only")
    # The user's own default is refused: the household's default applies.
    assert create_conversation(server, household.token)["model"] == household.local
    # Both are refused: the conversation starts without a model, for the user to choose.
    with server.client(household.admin_token) as client:
        response = client.put(
            "/tenant/default-model", json={"connection_id": household.openrouter_id, "model": "test/free"}
        )
    assert response.status_code == 200, response.text
    assert create_conversation(server, household.token)["model"] is None


def _remote_speech(server: Server, household: Household) -> None:
    with server.client(household.admin_token) as client:
        response = client.put(
            "/tenant/speech",
            json={
                "transcription": {"connection_id": household.openrouter_id, "model": "test/transcribe"},
                "speech": {"connection_id": household.openrouter_id, "model": "test/voice", "voice": "nova"},
            },
        )
    assert response.status_code == 200, response.text


@pytest.mark.spec("MOD-003", "API-006")
def test_remote_speech_is_refused_before_it_leaves(server: Server, household: Household) -> None:
    _remote_speech(server, household)
    _for_user(server, household, household.member, "local_only")
    endpoint = household.model.endpoint
    transcriptions, syntheses = len(endpoint.speech("/audio/transcriptions")), len(endpoint.speech("/audio/speech"))
    with server.client(household.token) as client:
        heard = client.post("/speech/transcriptions", files={"audio": ("turn.webm", RECORDING, "audio/webm")})
        assert_problem(heard, 409, "model.egress_refused")
        assert_problem(client.post("/speech/synthesis", json={"text": "Hello"}), 409, "model.egress_refused")
    assert len(endpoint.speech("/audio/transcriptions")) == transcriptions
    assert len(endpoint.speech("/audio/speech")) == syntheses
    # The admin, whose policy allows them, still speaks.
    with server.client(household.admin_token) as client:
        assert client.post("/speech/synthesis", json={"text": "Hello"}).status_code == 200
