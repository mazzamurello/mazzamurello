# Running the evals

The eval suite measures how the assistant behaves with a given model: does
it resist prompt injection, does it keep the right files in the workspace,
does it use its tools when it should (EVL-001 to EVL-005,
[ADR-0092](../../specs/adr/0092-the-first-eval-suite.md)). Unlike the tests,
it talks to real models, so its results depend on the model and are not
committed.

## What you need

The same as for the sandbox tests: Docker with gVisor registered as `runsc`
(see the README). And at least one model: a local server with an
OpenAI-compatible API, such as Ollama, or an OpenRouter key.

## Choose the models

Copy the example and edit it. Each `[[model]]` becomes a connection, as the
household settings would create it:

```bash
cp evals/models.example.toml evals/models.toml
```

Keys are never written in the file: `api_key_env` names the environment
variable that holds one, such as `OPENROUTER_API_KEY`.

## Run

```bash
uv run pytest evals --eval-models evals/models.toml
```

Every scenario runs three times per model; `--eval-repeat N` changes that.
Use `-k` to pick scenarios or models, for example `-k injection`. A run of
the whole suite against one local model takes a few minutes.

At the end, the terminal shows each scenario's pass rate per model.
`LEAK/HARM` marks an adversarial scenario that failed at least once: the
model sent the planted secret away, or deleted what an injection told it
to. The JSON report in `evals/results/` lists every run, the tools it
called and which of them asked for approval, and, for a failed run, the
whole conversation.

## How a run behaves

- Every run starts with a fresh household on a stack of its own, like the
  tests: nothing touches your deployment.
- The suite plays a careless user: it approves every approval request, for
  the conversation, and answers every question with "Do what you think
  best". Integration tests already prove that the approval gate holds; the
  evals measure what the model does once the gate is open.
- The data is synthetic, and attackers' addresses use the reserved
  `attacker.example` domain, so an obeyed injection never reaches a real
  host.

## Adding a scenario

Scenarios live in `evals/scenarios.py`. Each one arranges files, pages and
search results, states its request and its checks, and carries two scripts
for the model the tests serve: one that should pass and one that should
fail. `tests/evals/` runs both in CI (EVL-006), so add a test there for the
new scenario.
