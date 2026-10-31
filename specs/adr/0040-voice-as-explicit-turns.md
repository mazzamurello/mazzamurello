# ADR-0040: Voice as explicit turns, not real-time conversation

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0017, API-006, UX-005, MOD-003

## Context

Persona P4 of the [product description](../product.md) prefers speaking to
typing, and persona P2 often uses the phone hands-free. Voice assistants
usually work in real time: they detect the end of speech automatically,
answer at once with short replies and can be interrupted. In practice this
interrupts people who pause to think, and pushes answers to be short and
shallow. Real-time speech also needs streaming audio models with low latency,
which local deployments rarely offer.

## Decision

We will implement voice as **explicit turns** (UX-005):

1. The user starts recording, speaks for as long as needed and ends the turn
   explicitly. Silence never ends a turn.
2. The recording is transcribed by the speech-to-text service (API-006); the
   transcription becomes the user message, which the user can review before
   sending or send directly, according to a client setting.
3. The run is a normal run, with the same model, tools and depth as a typed
   message. The assistant's answer is not shortened for speech.
4. When the answer is complete, it is synthesized and read aloud. Code, tables
   and artifacts are not read verbatim; the reading refers to them.
5. Speech services are local by default and pass through the data egress
   policy when remote (MOD-003).

## Consequences

- Voice works with any model and any local speech-to-text and text-to-speech
  service, without real-time models.
- Answers take longer to start being spoken than in real-time assistants; we
  accept this in exchange for complete answers.
- Phase 1 includes voice; API-006 moves from phase 2 to phase 1.

## Alternatives considered

- **Real-time voice with automatic end-of-turn detection and interruptions:**
  interrupts people who pause, produces short answers, and requires
  specialized models.
- **Dictation only, without reading aloud:** does not serve persona P4.
