"""Checks exchanges with the server against the API contract (API-002, ADR-0056).

The contract's schemas are JSON Schema 2020-12, as OpenAPI 3.1 defines them.
Every response is checked against the operation it answers; event streams
are checked event by event; the body of a request the server accepted is
checked against the operation's request body.
"""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Any, cast

import httpx
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.support.database import ROOT

CONTRACT = ROOT / "specs" / "contracts" / "openapi.yaml"
CONTRACT_URI = "urn:mazzamurello:openapi"
METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
JSON_TYPES = ("application/json", "application/problem+json")


class ContractViolationError(AssertionError):
    """An exchange with the server that the contract does not allow."""


@cache
def contract() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(CONTRACT.read_text()))


@cache
def _registry() -> Registry[Any]:
    registry: Registry[Any] = Registry()
    resource: Resource[Any] = Resource.from_contents(contract(), default_specification=DRAFT202012)
    return registry.with_resource(CONTRACT_URI, resource)


def _pointer(*parts: str) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


@cache
def _validator(pointer: str) -> Draft202012Validator:
    schema = {"$ref": f"{CONTRACT_URI}#{pointer}"}
    return Draft202012Validator(schema, registry=_registry(), format_checker=Draft202012Validator.FORMAT_CHECKER)


def _resolve(item: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...] | None]:
    """An OpenAPI object behind a local `$ref`, with its location in the contract when it moved."""
    reference = item.get("$ref")
    if not isinstance(reference, str):
        return item, None
    parts = tuple(part.replace("~1", "/").replace("~0", "~") for part in reference.removeprefix("#/").split("/"))
    target: Any = contract()
    for part in parts:
        target = target[part]
    return cast("dict[str, Any]", target), parts


@cache
def _base_path() -> str:
    return str(contract()["servers"][0]["url"]).rstrip("/")


@cache
def _templates() -> list[tuple[re.Pattern[str], str]]:
    templates = [
        (re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(path)) + "$"), path)
        for path in contract()["paths"]
    ]
    # Literal paths win over templated ones, such as /models/defaults over /models/{id}.
    return sorted(templates, key=lambda item: item[1].count("{"))


def operation_of(method: str, path: str) -> tuple[str, str]:
    """The contract's path template and method for a request, or a violation."""
    relative = path.removeprefix(_base_path()) or "/"
    for pattern, template in _templates():
        if pattern.match(relative):
            if method.lower() in contract()["paths"][template]:
                return template, method.lower()
            raise ContractViolationError(f"{method} {relative}: the contract has no {method} for {template}")
    raise ContractViolationError(f"{method} {relative}: no operation in the contract")


def _check(pointer: str, instance: Any, what: str) -> None:
    found: list[ValidationError] = list(_validator(pointer).iter_errors(instance))  # pyright: ignore[reportUnknownMemberType]
    errors = sorted(found, key=lambda error: [str(part) for part in error.absolute_path])
    if errors:
        details = "; ".join(_describe(error) for error in errors[:5])
        raise ContractViolationError(f"{what} does not match the contract: {details}")


def _describe(error: ValidationError) -> str:
    location = "/".join(str(part) for part in error.absolute_path) or "(root)"
    return f"at {location}: {error.message}"


def check_event(data: Any, what: str = "event") -> None:
    """An event of an event stream (ADR-0056)."""
    _check(_pointer("components", "schemas", "AgUiEvent"), data, what)


def check_response(response: httpx.Response) -> None:
    """The response's status and body, and the body of an accepted request."""
    request = response.request
    template, method = operation_of(request.method, request.url.path)
    what = f"{request.method} {request.url.path} -> {response.status_code}"
    responses: dict[str, Any] = contract()["paths"][template][method]["responses"]
    status = str(response.status_code)
    for key in (status, f"{status[0]}XX", "default"):
        if key in responses:
            break
    else:
        raise ContractViolationError(f"{what}: the contract lists no such status for {method.upper()} {template}")
    described, moved = _resolve(responses[key])
    location = moved or ("paths", template, method, "responses", key)
    content: dict[str, Any] = described.get("content", {})
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    if not response.content and not media_type:
        if content and response.status_code != 204:
            raise ContractViolationError(f"{what}: the contract describes a body, and there is none")
    elif media_type not in content:
        raise ContractViolationError(f"{what}: content type {media_type!r} is not one of {sorted(content)}")
    elif media_type in JSON_TYPES and "schema" in content[media_type]:
        _check(_pointer(*location, "content", media_type, "schema"), response.json(), what)
    if response.is_success:
        _check_request(request, template, method)


def _check_request(request: httpx.Request, template: str, method: str) -> None:
    body = contract()["paths"][template][method].get("requestBody")
    if body is None or not request.content:
        return
    described, moved = _resolve(body)
    location = moved or ("paths", template, method, "requestBody")
    media_type = request.headers.get("content-type", "").split(";")[0].strip()
    what = f"the accepted body of {request.method} {request.url.path}"
    if media_type not in described.get("content", {}):
        raise ContractViolationError(f"{what}: content type {media_type!r} is not in the contract")
    if media_type in JSON_TYPES:
        _check(_pointer(*location, "content", media_type, "schema"), json.loads(request.content), what)


def response_hook(response: httpx.Response) -> None:
    """An httpx response hook; event streams are checked as they are read."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        operation_of(response.request.method, response.request.url.path)
        return
    response.read()
    check_response(response)
