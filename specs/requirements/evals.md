# EVL — Agent behavior evals

How the behavior of the assistant is measured. Background: ADR-0015.

## EVL-001: Versioned eval suite

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** review

The repository MUST contain a versioned suite of eval scenarios, each with
explicit pass criteria, runnable with a single command.

## EVL-002: Multiple models

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** review

The eval suite SHOULD run against several models, including at
least one small local model, and report results per scenario and per model.

## EVL-003: Adversarial scenarios

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** eval

The eval suite MUST include prompt-injection and exfiltration scenarios in
which untrusted content instructs the agent to send private data externally
or to take irreversible actions. Such a scenario passes only if no private
data leaves the instance and no consequential action runs without approval.

## EVL-004: Releases gated by evals

- **Status:** draft
- **Priority:** MUST
- **Phase:** 3
- **Verification:** review

A release MUST NOT be published if the eval suite falls below its documented
thresholds for the reference models.

## EVL-005: Synthetic data only

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** review

Eval scenarios MUST use synthetic data only, never real user data.
