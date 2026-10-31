# Roadmap

Mazzamurello is built in phases. Each phase has a goal and exit criteria;
the requirements of a phase are those with the matching `Phase` field in
[`specs/requirements/`](specs/requirements/). Dates are deliberately absent:
this is a personal, best-effort project.

## Phase 0 — Walking skeleton

**Goal:** the thinnest path through the whole architecture, with the
security foundations in place:
sign in → open a conversation → send a message → the agent runs a command in
the user's isolated sandbox → the answer streams back.

Includes: tenancy and row-level security (TEN), local accounts (AUTH), the
sandbox and its network isolation (SBX), mediated tools (AGT-001), the model
gateway with one local and one remote provider (MOD), the public API with
conversations, message versions, stopping runs and streaming (API, CNV-001
to CNV-003), privacy defaults for logs (OBS), Docker
Compose deployment (OPS), and the repository governance checks (REPO).
There is no user interface in phase 0: the API is exercised by end-to-end
tests (ADR-0024).

**Exit criteria:**

- every phase 0 requirement is `implemented`, with passing tests;
- the cross-user, cross-tenant and sandbox network security tests pass;
- a fresh Linux host goes from `git clone` to a working conversation by
  following the README.

## Phase 1 — Daily use

**Goal:** an assistant the maintainer's family uses every day, on the web and
on the phone (installable web app).

Includes: the web client as an installable web app (UX) with externalized
strings (I18N-001), notifications, voice turns (UX-005, API-006),
attachments, search, spaces and sharing within the household, temporary
conversations (CNV), artifacts (ART), web search and page reading, persistent
workspaces, transparent memory (MEM), tool permissions, provenance and approvals with the
lethal trifecta mitigation (AGT), the data egress policy (MOD-003), backup
and restore (OPS-006), and the first eval suite (EVL).

**Exit criteria:** used daily by at least one household for a month without
data loss; eval suite in place, including injection scenarios.

## Phase 2 — A real assistant, and a first release

**Goal:** the features that make it an assistant rather than a chat, and the
release engineering to let others run it.

Includes: multi-step research producing reports, scheduled tasks, connectors over open protocols
(calendar, mail, files, home automation through mediated tools), OpenID
Connect (AUTH-003), budgets (MOD-004), debug mode (OBS-004), signed
multi-architecture images, upgrade guarantees, English and Italian
translations, release gating by evals.

**Exit criteria:** first public release `0.1.0`; installation and upgrade
documentation verified on a clean machine; public announcement.

## Phase 3 — Opening up

**Goal:** make the project sustainable beyond its first household.

Candidates: tenant administration for operators hosting several households,
Kata Containers and Kubernetes providers, a native mobile app with push
notifications, community translations, a second maintainer and the governance
transition described in [GOVERNANCE.md](GOVERNANCE.md).
