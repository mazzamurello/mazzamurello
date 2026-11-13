# ADR-0067: The web client

- **Status:** Accepted
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0008, ADR-0016, ADR-0025, ADR-0031, ADR-0032, ADR-0056, ADR-0059, AUTH-005, I18N-001, UX-001, UX-002, UX-003, UX-007, UX-010

## Context

Phase 1 starts with the web client, the installable web app that every
member of the household uses on the computer and on the phone (ADR-0016). Its
language is TypeScript and its API types come from the committed contract
(ADR-0008); browsers sign in with an `HttpOnly` cookie (ADR-0025). What
remained open is the framework, how the app is served, where it lives in the
repository and how it is tested.

## Decision

1. **React, built with Vite, as a static single-page app.** React has the
   largest ecosystem for chat interfaces, AG-UI's own client libraries and
   accessible components among them, and is what coding agents write most
   reliably. Everything sits behind sign-in, so nothing is rendered on a
   server.
2. **Served by the API process, on the same origin.** The app's files are
   built into the server image and served at `/`, next to the API at `/v1`,
   through the one published port (OPS-003). The same origin lets the session
   cookie work without cross-origin requests. Node is used to build the
   image, never at run time. The app's responses carry a Content Security
   Policy that allows only the app's own scripts.
3. **Cookie sessions for the browser.** The app signs in asking for the
   session in a cookie: the response sets it, `HttpOnly`, `Secure` and
   `SameSite=Lax`, and does not return the token. Every state-changing
   request the app makes carries the header `X-Sibillo-Request`, which a
   cross-site request cannot set; the server refuses a cookie-authenticated
   request without it (AUTH-005). `Secure` cookies need HTTPS, so the app is
   used through the household's reverse proxy, or on `localhost`.
4. **Where it lives:** the app in `src/web/`, its tests in `tests/web/`, so
   that implementation and tests stay apart as for the server.
5. **Libraries:** pnpm with a committed lock file; TypeScript types generated
   from `specs/contracts/openapi.yaml`; AG-UI's types for the event stream;
   Tailwind for styling and Radix for accessible menus and dialogs;
   react-markdown with KaTeX and Shiki for messages, with raw HTML disabled
   (UX-002); i18next for every string (I18N-001); a web app manifest and a
   service worker that caches only the app's own files (UX-001).
6. **Layout:** a conversation sidebar that collapses on phones, the
   conversation in the center, and the composer at the bottom; tool activity
   as compact summaries that expand (UX-003).
7. **Tests:** unit tests with Vitest, and browser tests with Playwright on
   Chromium, driving the real server through the test harness, with
   accessibility checks on every screen (UX-007). They run in a CI job of
   their own, with its own time budget (ADR-0059). Other browsers, Safari's
   engine among them, are checked by hand before each milestone.

## Consequences

- One deployment still serves everything, and the API stays the only way the
  app talks to the server (API-001).
- The server image build gains a Node stage.
- Using the app over plain HTTP from another machine does not work: sign-in
  needs HTTPS. The README says so.
- iPhones are not tested in CI; regressions there are found by hand.

## Alternatives considered

- **Svelte or Vue:** leaner, with smaller ecosystems for chat interfaces and
  accessible components.
- **A server-rendered framework such as Next.js:** adds a Node server to the
  deployment for pages that are all behind sign-in.
- **A separate container for the app:** one more service and a path split in
  front of the API, for no gain over serving static files.
- **Tokens in browser storage:** simpler, but readable by any script that gets
  into the page (ADR-0025).
