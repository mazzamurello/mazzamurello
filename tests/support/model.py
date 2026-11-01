"""The model the tests serve: an OpenAI-compatible chat completions endpoint.

See specs/contracts/test-harness.md ("Models"). Answers are scripted by the
last user message:

- `slow:N` streams `N` pieces of text, half a second apart;
- `fail` answers with a server error;
- `status:429` answers "too many requests", with `Retry-After`;
- `drop:N` streams `N` pieces of text, then closes the connection mid-answer;
- `run:<command>` calls the agent's command tool with `<command>`, then, once
  the tool's result arrives, answers `Tool said: <result>`;
- anything else streams `Echo: <message>`.

The command tool is found among the tools the request offers, by its name or
description, so tests do not depend on the tool's name.

Under `/openrouter/api/v1`, the same scripts are answered as OpenRouter's
chat completions API does, as its documentation describes (ADR-0057): a
keep-alive comment before the first chunk, `provider` and
`native_finish_reason` in every chunk, and a final usage chunk that repeats
the finish reason and reports `cost`. Two more scripts apply there:

- `status:402` answers OpenRouter's "insufficient credits" error;
- `error-midstream` streams one piece, then an error event, and ends.

Every request is recorded, with its headers, so that tests can check what
reached the model.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

PROMPT_TOKENS = 10
COMPLETION_TOKENS = 5
SLOW_PIECE_SECONDS = 0.5
OPENROUTER_PREFIX = "/openrouter"
# The cost OpenRouter reports for every answer, in credits of one US dollar.
OPENROUTER_COST = 0.000420


@dataclass(frozen=True)
class ModelRequest:
    authorization: str | None
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict[str, str])
    openrouter: bool = False

    def user_texts(self) -> list[str]:
        """The text of every user message the model received, in order."""
        texts: list[str] = []
        for message in self.body.get("messages", []):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                parts = cast(list[dict[str, Any]], content)
                texts.append("".join(str(part.get("text", "")) for part in parts if part.get("type") == "text"))
        return texts


@dataclass
class ModelServer:
    url: str
    requests: list[ModelRequest] = field(default_factory=list[ModelRequest])
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def openrouter_url(self) -> str:
        """The base URL at which the model answers as OpenRouter."""
        return self.url.removesuffix("/v1") + f"{OPENROUTER_PREFIX}/api/v1"

    def record(self, request: ModelRequest) -> None:
        with self._lock:
            self.requests.append(request)

    def requests_with(self, text: str) -> list[ModelRequest]:
        """The requests whose last user message is `text`."""
        with self._lock:
            return [request for request in self.requests if request.user_texts()[-1:] == [text]]


def _last_text(body: dict[str, Any]) -> str:
    texts = ModelRequest(None, body).user_texts()
    return texts[-1] if texts else ""


def _command_tool(tools: list[dict[str, Any]]) -> tuple[str, str]:
    """The name of the tool that runs a command, and the name of its command argument."""
    functions = [cast(dict[str, Any], tool.get("function", {})) for tool in tools]
    # A tool that runs a command and waits for it, rather than one that
    # starts, checks or stops a background command.
    functions.sort(key=lambda function: "run" not in str(function.get("name", "")))
    for function in functions:
        text = f"{function.get('name', '')} {function.get('description', '')}".lower()
        if "command" not in text or any(word in str(function.get("name", "")) for word in ("start", "check", "stop")):
            continue
        parameters = cast(dict[str, Any], function.get("parameters", {}))
        properties = cast(dict[str, Any], parameters.get("properties", {}))
        for argument in cast(list[str], parameters.get("required", [])):
            if cast(dict[str, Any], properties.get(argument, {})).get("type") == "string":
                return str(function["name"]), argument
    raise AssertionError(f"no command tool among {[t.get('function', {}).get('name') for t in tools]}")


def _pieces(text: str) -> list[tuple[str, float]]:
    if text.startswith("drop:"):
        count = int(text.removeprefix("drop:") or "1")
        return [(f"piece {index} ", 0.1) for index in range(count)]
    if text.startswith("slow:"):
        count = int(text.removeprefix("slow:") or "1")
        return [(f"piece {index} ", SLOW_PIECE_SECONDS) for index in range(count)]
    reply = f"Echo: {text}"
    third = max(1, len(reply) // 3)
    return [(reply[:third], 0.0), (reply[third : 2 * third], 0.0), (reply[2 * third :], 0.0)]


def _handler(model: ModelServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        # Whether this request is answered as OpenRouter's API.
        openrouter = False

        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = cast(dict[str, Any], json.loads(self.rfile.read(length) or b"{}"))
            self.openrouter = self.path.startswith(f"{OPENROUTER_PREFIX}/")
            headers = {name.lower(): value for name, value in self.headers.items()}
            request = ModelRequest(self.headers.get("Authorization"), body, headers, self.openrouter)
            model.record(request)
            texts = request.user_texts()
            last = texts[-1] if texts else ""
            if not self.path.endswith("/chat/completions") or last == "fail":
                self._error(500, "scripted failure", "server_error")
                return
            if last == "status:429":
                self._error(429, "slow down", "rate_limit", {"Retry-After": "1"})
                return
            if last == "status:402" and self.openrouter:
                self._error(402, "Insufficient credits", "payment_required")
                return
            if last.startswith("run:"):
                self._tool_turn(body, last.removeprefix("run:"))
                return
            if body.get("stream"):
                self._stream(body, _pieces(last))
            else:
                self._json(200, self._completion(body, "".join(piece for piece, _ in _pieces(last))))

        def _error(self, status: int, message: str, kind: str, headers: dict[str, str] | None = None) -> None:
            if self.openrouter:
                # OpenRouter's errors carry the HTTP status as their code.
                error: dict[str, Any] = {"code": status, "message": message, "metadata": {"error_type": kind}}
            else:
                error = {"message": message, "type": kind}
            self._json(status, {"error": error}, headers)

        def _json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def _tool_turn(self, body: dict[str, Any], command: str) -> None:
            messages = cast(list[dict[str, Any]], body.get("messages", []))
            if messages and messages[-1].get("role") == "tool":
                result = str(messages[-1].get("content", ""))
                self._answer(body, [(f"Tool said: {result[:2000]}", 0.0)])
                return
            name, argument = _command_tool(cast(list[dict[str, Any]], body.get("tools", [])))
            call = {
                "id": f"call-{len(messages)}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({argument: command})},
            }
            if not body.get("stream"):
                completion = self._completion(body, "")
                completion["choices"][0] = {
                    "index": 0,
                    "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                    "finish_reason": "tool_calls",
                }
                self._json(200, completion)
                return
            self._start_stream()
            base = self._chunk_base(body)
            delta = {"role": "assistant", "tool_calls": [call | {"index": 0}]}
            self._event(base | {"choices": [self._choice(delta, None)]})
            self._finish(base, "tool_calls")

        def _answer(self, body: dict[str, Any], pieces: list[tuple[str, float]]) -> None:
            if body.get("stream"):
                self._stream(body, pieces)
            else:
                self._json(200, self._completion(body, "".join(piece for piece, _ in pieces)))

        def _chunk_base(self, body: dict[str, Any]) -> dict[str, Any]:
            base: dict[str, Any] = {
                "id": "gen-test" if self.openrouter else "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "test-model"),
            }
            return base | ({"provider": "OpenAI"} if self.openrouter else {})

        def _choice(self, delta: dict[str, Any], finish_reason: str | None) -> dict[str, Any]:
            choice: dict[str, Any] = {"index": 0, "delta": delta, "finish_reason": finish_reason}
            return choice | ({"native_finish_reason": finish_reason} if self.openrouter else {})

        def _start_stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if self.openrouter:
                self.wfile.write(b": OPENROUTER PROCESSING\n\n")
                self.wfile.flush()

        def _finish(self, base: dict[str, Any], finish_reason: str) -> None:
            self._event(base | {"choices": [self._choice({}, finish_reason)]})
            if self.openrouter:
                # OpenRouter repeats the finish reason in a content-free choice of the usage chunk.
                empty = {"content": "", "role": "assistant"}
                self._event(base | {"choices": [self._choice(empty, finish_reason)], "usage": _openrouter_usage()})
            else:
                self._event(base | {"choices": [], "usage": _usage()})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def _completion(self, body: dict[str, Any], text: str) -> dict[str, Any]:
            choice: dict[str, Any] = {"index": 0, "message": {"role": "assistant", "content": text}}
            choice |= {"finish_reason": "stop"} | ({"native_finish_reason": "stop"} if self.openrouter else {})
            return {
                "id": "gen-test" if self.openrouter else "chatcmpl-test",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.get("model", "test-model"),
                "choices": [choice],
                "usage": _openrouter_usage() if self.openrouter else _usage(),
            }

        def _stream(self, body: dict[str, Any], pieces: list[tuple[str, float]]) -> None:
            self._start_stream()
            base = self._chunk_base(body)
            last = _last_text(body)
            try:
                for index, (piece, delay) in enumerate(pieces):
                    time.sleep(delay)
                    delta = {"content": piece} | ({"role": "assistant"} if index == 0 else {})
                    self._event(base | {"choices": [self._choice(delta, None)]})
                    if last == "error-midstream" and self.openrouter:
                        # A mid-stream error, after which OpenRouter ends the stream.
                        error = {
                            "code": 502,
                            "message": "Provider returned error",
                            "metadata": {"error_type": "provider_unavailable"},
                        }
                        self._event(base | {"error": error, "choices": [self._choice({"content": ""}, "error")]})
                        return
                if last.startswith("drop:"):
                    # Close the connection mid-answer, without finishing the stream.
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                self._finish(base, "stop")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _event(self, payload: dict[str, Any]) -> None:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()

    return Handler


def _usage() -> dict[str, int]:
    return {
        "prompt_tokens": PROMPT_TOKENS,
        "completion_tokens": COMPLETION_TOKENS,
        "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
    }


def _openrouter_usage() -> dict[str, Any]:
    """Usage as OpenRouter reports it, with the cost of the answer."""
    return _usage() | {
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
        "cost": OPENROUTER_COST,
        "cost_details": {
            "upstream_inference_cost": None,
            "upstream_inference_prompt_cost": 0.000300,
            "upstream_inference_completions_cost": 0.000120,
        },
    }


def start_model_server(
    host: str = "127.0.0.1", advertised: str | None = None
) -> tuple[ModelServer, ThreadingHTTPServer]:
    """Serve the model on `host`; its URL names `advertised`, the address clients use, or `host`."""
    model = ModelServer(url="")
    http = ThreadingHTTPServer((host, 0), _handler(model))
    http.daemon_threads = True
    model.url = f"http://{advertised or host}:{http.server_address[1]}/v1"
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return model, http
