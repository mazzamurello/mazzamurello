# ADR-0005: English as the repository language, with a canonical glossary

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** REPO-006, I18N-001

## Context

The founder works with AI agents mostly in Italian, sometimes in English.
The project targets an international open-source audience. Agents tend to
mirror the language of the conversation, and when concepts are discussed in
one language and written in another, translations drift: one concept ends up
with several names.

## Decision

We will:

1. Write every repository artifact in English — code, comments,
   specifications, ADRs, commit messages, pull request titles and
   descriptions, documentation — regardless of the conversation language.
2. Keep other languages only in i18n resource files.
3. Maintain a canonical [glossary](../glossary.md): one English term per
   domain concept, with its definition. New concepts require a glossary
   entry first.
4. When an agent proposes a specification to an Italian-speaking maintainer,
   it accompanies the English text with an Italian summary of the key
   decisions and flags ambiguous terms, so approval covers meaning, not just
   wording.

## Consequences

- Contributors worldwide can read everything.
- The glossary must be maintained as carefully as the specs.

## Alternatives considered

- **Italian repository:** limits the audience.
- **Mixed languages:** inconsistent and hard to search.
