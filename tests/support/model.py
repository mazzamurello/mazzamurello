"""The model the tests serve: an OpenAI-compatible chat completions endpoint.

See specs/contracts/test-harness.md ("Models"). Answers are scripted by the
last user message:

- `slow:N` streams `N` pieces of text, half a second apart;
- `fail` answers with a server error;
- `status:429` answers "too many requests", with `Retry-After`;
- `drop:N` streams `N` pieces of text, then closes the connection mid-answer;
- `refuse` is refused as a content filter refuses, with `REFUSAL` as the
  provider's reason (MOD-015);
- `run:<command>` calls the agent's command tool with `<command>`, then, once
  the tool's result arrives, answers `Tool said: <result>`;
- `runs:<command> ||| <command> …` calls the command tool with each command in
  turn, in one answer, then answers `Tool said: <last result>`;
- `tool:<name> <arguments>` calls the tool named `<name>` with the JSON
  `<arguments>`, then answers `Tool said: <result>`, or `No tool <name>` when
  the request does not offer it;
- `say:<text> ||| tool:<name> <arguments>` says `<text>`, then calls the tool
  in the same answer, as `tool:` does (UX-003);
- `think:<text>` streams `Thinking: <text>` as the model's reasoning, then
  `Echo: <message>` (CNV-013);
- anything else streams `Echo: <message>`.

The command tool is found among the tools the request offers, by its name or
description, so tests do not depend on the tool's name.

`GET /v1/models` lists `SERVER_MODELS`, as OpenAI-compatible servers do; a
request for `refuses-tools` that offers tools is refused as Ollama refuses it.
Under `/html`, the server answers every request with a web page, as a server
that is not a model API would.

Under `/openrouter/api/v1`, the same scripts are answered as OpenRouter's
chat completions API does, as its documentation describes (ADR-0057): a
keep-alive comment before the first chunk, `provider` and
`native_finish_reason` in every chunk, and a final usage chunk that repeats
the finish reason and reports `cost`. Two more scripts apply there:

- `status:402` answers OpenRouter's "insufficient credits" error;
- `error-midstream` streams one piece, then an error event, and ends.

There, `GET /models` answers as OpenRouter's model list (`OPENROUTER_MODELS`),
most used first when asked with `sort=top-weekly` and by name otherwise, its
speech models (`OPENROUTER_SPEECH_MODELS`) when asked for their
`output_modalities`, and `GET /key` accepts every key except `REJECTED_KEY`.

Both serve speech (ADR-0088): `POST /audio/transcriptions` takes a recording
as a multipart form, or as OpenRouter's JSON with base64 audio, and answers
`Heard <bytes> bytes of <format>`; `POST /audio/speech` answers a short WAV
file of silence, a second and a half long, and as OpenRouter an
`X-Generation-Id`, whose cost `GET /generation` reports. A recording that holds `fail` is
refused.

Every request is recorded, with its headers, so that tests can check what
reached the model.
"""

from __future__ import annotations

import base64
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
# The models of the OpenAI-compatible server.
# `gpt-4o-mini` is a model the price catalog knows.
# `test-transcribe` and `test-tts` are speech models, by their names (ADR-0088).
SERVER_MODELS = ("test-model", "refuses-tools", "gpt-4o-mini", "test-transcribe", "test-tts")
# What Ollama answers when a model that cannot call tools is offered some.
REFUSES_TOOLS_ERROR = "registry.ollama.ai/library/refuses-tools does not support tools"
# The reason a content filter gives for a request it refuses.
REFUSAL = "Safeguards flagged this message."
# The key OpenRouter's key check refuses.
REJECTED_KEY = "sk-or-rejected"
# OpenRouter's models, most used in the past week first: (id, name, dollars per
# token in, out, context window, whether it can call tools, whether it can
# reason). A router, whose price depends on the model it picks, lists `-1`, as
# OpenRouter's own does.
OPENROUTER_MODELS = (
    ("test/popular", "Test: Popular", "0.00000027", "0.00000041", 131072, True, True),
    ("test/second", "Test: Second", "0.0000003", "0.0000025", 1048576, True, False),
    ("test/chat-only", "Test: Chat only", "0.0000001", "0.0000002", 32768, False, False),
    ("test/free-chat", "Test: Free chat", "0", "0", 32768, False, False),
    ("test/free", "Test: Free", "0", "0", 131072, True, True),
    ("test/another", "Test: Another", "0.00000015", "0.0000006", 65536, True, False),
    ("test/router", "Test: Router", "-1", "-1", 2000000, False, True),
)

# OpenRouter's speech models: (id, name, output modality, voices) (ADR-0088).
OPENROUTER_SPEECH_MODELS = (
    ("test/transcribe", "Test: Transcribe", "transcription", None),
    ("test/voice", "Test: Voice", "speech", ("alloy", "nova")),
)
# The cost OpenRouter reports for a transcription, and for a speech generation, which it reports at
# `/generation` (ADR-0088).
TRANSCRIPTION_COST = 0.000508
SPEECH_COST = 0.000375


def heard(size: int, audio_format: str) -> str:
    """What the served transcription model answers for a recording."""
    return f"Heard {size} bytes of {audio_format}"


def silence(seconds: float = 1.5) -> bytes:
    """A WAV file of silence: 16-bit mono at 8 kHz."""
    samples = int(8000 * seconds)
    data = bytes(2 * samples)
    header = (
        b"RIFF"
        + (36 + len(data)).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (8000).to_bytes(4, "little")
        + (16000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + len(data).to_bytes(4, "little")
    )
    return header + data


def _multipart(content_type: str, data: bytes) -> dict[str, tuple[str | None, bytes]]:
    """The fields of a multipart form: each one's file name, if it has one, and its value."""
    boundary = content_type.partition("boundary=")[2].strip('"').encode()
    fields: dict[str, tuple[str | None, bytes]] = {}
    for part in data.split(b"--" + boundary):
        head, separator, value = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        disposition = next(
            (line for line in head.decode().split("\r\n") if line.lower().startswith("content-disposition")), ""
        )
        attributes = dict(item.strip().split("=", 1) for item in disposition.split(";")[1:] if "=" in item)
        name = attributes.get("name", "").strip('"')
        filename = attributes.get("filename")
        fields[name] = (None if filename is None else filename.strip('"'), value.removesuffix(b"\r\n"))
    return fields


@dataclass(frozen=True)
class ModelRequest:
    authorization: str | None
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict[str, str])
    openrouter: bool = False
    method: str = "POST"
    # The path and query of the request.
    path: str = ""

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

    def system_text(self) -> str:
        """The instructions the model received: its system messages, joined."""
        messages = cast(list[dict[str, Any]], self.body.get("messages", []))
        return "\n\n".join(str(m.get("content", "")) for m in messages if m.get("role") in ("system", "developer"))

    def tool_names(self) -> set[str]:
        """The names of the tools the request offers."""
        tools = cast(list[dict[str, Any]], self.body.get("tools", []))
        return {str(cast(dict[str, Any], tool.get("function", {})).get("name")) for tool in tools}

    def reasoning_effort(self) -> str | None:
        """The reasoning effort the request asks for, as OpenRouter or an OpenAI-compatible server reads it."""
        if self.openrouter:
            reasoning = cast(dict[str, Any] | None, self.body.get("reasoning"))
            return None if reasoning is None else str(reasoning.get("effort"))
        effort = self.body.get("reasoning_effort")
        return None if effort is None else str(effort)


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

    def speech(self, path: str) -> list[ModelRequest]:
        """The speech requests to `path`, `/audio/transcriptions` or `/audio/speech`, in order."""
        with self._lock:
            return [r for r in self.requests if r.method == "POST" and r.path.endswith(path)]

    def requests_with(self, text: str) -> list[ModelRequest]:
        """The requests whose last user message is `text`."""
        with self._lock:
            return [request for request in self.requests if request.user_texts()[-1:] == [text]]

    def reads(self, path: str) -> list[ModelRequest]:
        """The `GET` requests whose path, without the query, ends with `path`."""
        with self._lock:
            return [r for r in self.requests if r.method == "GET" and r.path.split("?")[0].endswith(path)]


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

        def do_GET(self) -> None:
            self.openrouter = self.path.startswith(f"{OPENROUTER_PREFIX}/")
            headers = {name.lower(): value for name, value in self.headers.items()}
            model.record(
                ModelRequest(self.headers.get("Authorization"), {}, headers, self.openrouter, "GET", self.path)
            )
            path, _, query = self.path.partition("?")
            if path.startswith("/html/"):
                self._page()
            elif self.openrouter and path.endswith("/api/v1/key"):
                if self.headers.get("Authorization") == f"Bearer {REJECTED_KEY}":
                    self._error(401, "User not found.", "authentication")
                else:
                    self._json(200, {"data": {"label": "sk-or-v1-...", "limit": None, "usage": 0}})
            elif self.openrouter and path.endswith("/api/v1/generation"):
                generation = next((item.partition("=")[2] for item in query.split("&") if item.startswith("id=")), "")
                self._json(200, {"data": {"id": generation, "total_cost": SPEECH_COST}})
            elif self.openrouter and path.endswith("/api/v1/models"):
                modalities = next(
                    (item.partition("=")[2] for item in query.split("&") if item.startswith("output_modalities=")),
                    "text",
                )
                wanted = set(modalities.replace("%2C", ",").split(","))
                listed = _openrouter_models("sort=top-weekly" in query.split("&")) if "text" in wanted else []
                self._json(200, {"data": listed + _openrouter_speech_models(wanted)})
            elif not self.openrouter and path == "/v1/models":
                self._json(200, {"object": "list", "data": [{"id": name, "object": "model"} for name in SERVER_MODELS]})
            else:
                data = b"404 page not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            self.openrouter = self.path.startswith(f"{OPENROUTER_PREFIX}/")
            if self.path.endswith("/audio/transcriptions"):
                self._transcribe(raw)
                return
            body = cast(dict[str, Any], json.loads(raw or b"{}"))
            if self.path.endswith("/audio/speech"):
                self._speak(body)
                return
            headers = {name.lower(): value for name, value in self.headers.items()}
            request = ModelRequest(self.headers.get("Authorization"), body, headers, self.openrouter, "POST", self.path)
            model.record(request)
            texts = request.user_texts()
            last = texts[-1] if texts else ""
            if self.path.startswith("/html/"):
                self._page()
                return
            if body.get("model") == "refuses-tools" and body.get("tools"):
                self._json(400, {"error": {"message": REFUSES_TOOLS_ERROR, "type": "api_error"}})
                return
            if not self.path.endswith("/chat/completions") or last == "fail":
                self._error(500, "scripted failure", "server_error")
                return
            if last == "status:429":
                self._error(429, "slow down", "rate_limit", {"Retry-After": "1"})
                return
            if last == "status:402" and self.openrouter:
                self._error(402, "Insufficient credits", "payment_required")
                return
            if last.startswith("runs:"):
                self._tool_turns(body, last.removeprefix("runs:").split(" ||| "))
                return
            if last.startswith("run:"):
                self._tool_turn(body, last.removeprefix("run:"))
                return
            if last.startswith("say:") and " ||| tool:" in last:
                said, _, call = last.removeprefix("say:").partition(" ||| tool:")
                name, _, arguments = call.partition(" ")
                self._named_tool_turn(body, name, arguments or "{}", said)
                return
            if last.startswith("tool:"):
                name, _, arguments = last.removeprefix("tool:").partition(" ")
                self._named_tool_turn(body, name, arguments or "{}")
                return
            if last == "refuse":
                self._refuse(body)
                return
            if last.startswith("think:"):
                self._think(body, f"Thinking: {last.removeprefix('think:')}", f"Echo: {last}")
                return
            if body.get("stream"):
                self._stream(body, _pieces(last))
            else:
                self._json(200, self._completion(body, "".join(piece for piece, _ in _pieces(last))))

        def _transcribe(self, raw: bytes) -> None:
            """A transcription, from a multipart form or OpenRouter's JSON (ADR-0088)."""
            headers = {name.lower(): value for name, value in self.headers.items()}
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("multipart/form-data"):
                fields = _multipart(content_type, raw)
                filename, audio = fields.get("file", (None, b""))
                audio_format = (filename or "").rpartition(".")[2] or "unknown"
                model_name = fields.get("model", (None, b""))[1].decode()
            else:
                body = cast(dict[str, Any], json.loads(raw or b"{}"))
                given = cast(dict[str, Any], body.get("input_audio") or {})
                audio = base64.b64decode(str(given.get("data", "")))
                audio_format = str(given.get("format", "unknown"))
                model_name = str(body.get("model", ""))
            summary = {"model": model_name, "bytes": len(audio), "format": audio_format}
            model.record(
                ModelRequest(self.headers.get("Authorization"), summary, headers, self.openrouter, "POST", self.path)
            )
            if b"fail" in audio:
                self._error(500, "scripted failure", "server_error")
                return
            answer: dict[str, Any] = {"text": heard(len(audio), audio_format)}
            if self.openrouter:
                answer["usage"] = {"seconds": 1.0, "cost": TRANSCRIPTION_COST}
            self._json(200, answer)

        def _speak(self, body: dict[str, Any]) -> None:
            """Speech: a short WAV file of silence, whatever the text (ADR-0088)."""
            headers = {name.lower(): value for name, value in self.headers.items()}
            model.record(
                ModelRequest(self.headers.get("Authorization"), body, headers, self.openrouter, "POST", self.path)
            )
            if "fail" in str(body.get("input", "")):
                self._error(500, "scripted failure", "server_error")
                return
            data = silence()
            self.send_response(200)
            if self.openrouter:
                self.send_header("X-Generation-Id", f"gen-speech-{len(model.requests)}")
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, message: str, kind: str, headers: dict[str, str] | None = None) -> None:
            if self.openrouter:
                # OpenRouter's errors carry the HTTP status as their code.
                error: dict[str, Any] = {"code": status, "message": message, "metadata": {"error_type": kind}}
            else:
                error = {"message": message, "type": kind}
            self._json(status, {"error": error}, headers)

        def _page(self) -> None:
            data = b"<!doctype html><title>Router</title><p>Welcome to your router.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
            self._call(body, name, json.dumps({argument: command}))

        def _tool_turns(self, body: dict[str, Any], commands: list[str]) -> None:
            messages = cast(list[dict[str, Any]], body.get("messages", []))
            # The tool results of this answer: those after the last user message.
            users = [index for index, message in enumerate(messages) if message.get("role") == "user"]
            done = sum(1 for message in messages[(users[-1] if users else -1) + 1 :] if message.get("role") == "tool")
            if done >= len(commands):
                result = str(messages[-1].get("content", ""))
                self._answer(body, [(f"Tool said: {result[:2000]}", 0.0)])
                return
            name, argument = _command_tool(cast(list[dict[str, Any]], body.get("tools", [])))
            self._call(body, name, json.dumps({argument: commands[done]}))

        def _named_tool_turn(self, body: dict[str, Any], name: str, arguments: str, said: str = "") -> None:
            messages = cast(list[dict[str, Any]], body.get("messages", []))
            if messages and messages[-1].get("role") == "tool":
                result = str(messages[-1].get("content", ""))
                self._answer(body, [(f"Tool said: {result[:2000]}", 0.0)])
                return
            offered = [cast(dict[str, Any], tool.get("function", {})).get("name") for tool in body.get("tools", [])]
            if name not in offered:
                self._answer(body, [(f"No tool {name}", 0.0)])
                return
            self._call(body, name, arguments, said)

        def _call(self, body: dict[str, Any], name: str, arguments: str, said: str = "") -> None:
            messages = cast(list[dict[str, Any]], body.get("messages", []))
            call = {
                "id": f"call-{len(messages)}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
            if not body.get("stream"):
                completion = self._completion(body, "")
                completion["choices"][0] = {
                    "index": 0,
                    "message": {"role": "assistant", "content": said or None, "tool_calls": [call]},
                    "finish_reason": "tool_calls",
                }
                self._json(200, completion)
                return
            self._start_stream()
            base = self._chunk_base(body)
            if said:
                self._event(base | {"choices": [self._choice({"role": "assistant", "content": said}, None)]})
            delta = {"role": "assistant", "tool_calls": [call | {"index": 0}]}
            self._event(base | {"choices": [self._choice(delta, None)]})
            self._finish(base, "tool_calls")

        def _think(self, body: dict[str, Any], reasoning: str, text: str) -> None:
            # OpenRouter names the reasoning `reasoning`; servers such as vLLM, `reasoning_content`.
            field = "reasoning" if self.openrouter else "reasoning_content"
            if not body.get("stream"):
                completion = self._completion(body, text)
                completion["choices"][0]["message"][field] = reasoning
                self._json(200, completion)
                return
            self._start_stream()
            base = self._chunk_base(body)
            self._event(base | {"choices": [self._choice({"role": "assistant", field: reasoning}, None)]})
            self._event(base | {"choices": [self._choice({"content": text}, None)]})
            self._finish(base, "stop")

        def _refuse(self, body: dict[str, Any]) -> None:
            if not body.get("stream"):
                completion = self._completion(body, "")
                completion["choices"][0]["message"] = {"role": "assistant", "content": None, "refusal": REFUSAL}
                completion["choices"][0]["finish_reason"] = "content_filter"
                if self.openrouter:
                    completion["choices"][0]["native_finish_reason"] = "content_filter"
                self._json(200, completion)
                return
            self._start_stream()
            base = self._chunk_base(body)
            self._event(base | {"choices": [self._choice({"role": "assistant", "refusal": REFUSAL}, None)]})
            self._finish(base, "content_filter")

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
            } | ({"provider": "OpenAI"} if self.openrouter else {})

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


def _openrouter_models(most_used_first: bool) -> list[dict[str, Any]]:
    """OpenRouter's model list, as its documentation describes it."""
    models = list(OPENROUTER_MODELS) if most_used_first else sorted(OPENROUTER_MODELS, key=lambda m: m[1])
    return [
        {
            "id": model_id,
            "canonical_slug": model_id,
            "name": name,
            "context_length": context,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "pricing": {"prompt": prompt, "completion": completion, "request": "0", "image": "0"},
            "supported_parameters": [
                "max_tokens",
                "temperature",
                *(["tools", "tool_choice"] if tools else []),
                *(["reasoning", "include_reasoning"] if reasoning else []),
            ],
            "top_provider": {"context_length": context, "is_moderated": False},
        }
        for model_id, name, prompt, completion, context, tools, reasoning in models
    ]


def _openrouter_speech_models(modalities: set[str]) -> list[dict[str, Any]]:
    """OpenRouter's speech models of the output modalities asked for."""
    return [
        {
            "id": model_id,
            "canonical_slug": model_id,
            "name": name,
            "context_length": None,
            "architecture": {
                "input_modalities": ["audio"] if modality == "transcription" else ["text"],
                "output_modalities": [modality],
            },
            "pricing": {"prompt": "0", "completion": "0.0001"},
            "supported_parameters": [],
            "supported_voices": None if voices is None else list(voices),
        }
        for model_id, name, modality, voices in OPENROUTER_SPEECH_MODELS
        if modality in modalities or "all" in modalities
    ]


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
