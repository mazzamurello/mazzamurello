# Roadmap

Sibillo is built in phases. Each phase has a goal and exit criteria;
the requirements of a phase are those with the matching `Phase` field in
[`specs/requirements/`](specs/requirements/). Dates are deliberately absent:
this is a personal, best-effort project.

The phases were renumbered when connected devices became phase 2 (ADR-0063):
ADRs written before then call the release phase 2 and opening up phase 3.

## Phase 0 — Walking skeleton

**Status:** complete. Every phase 0 requirement is `implemented`, the security
tests pass, and the end-to-end test installs Sibillo by following the
README. Known limits are recorded in the specs, such as the workspace disk
limit, which comes with SBX-016 in phase 1.

**Goal:** the thinnest path through the whole architecture, with the
security foundations in place:
sign in → open a conversation → send a message → the agent runs a command in
the user's isolated sandbox → the answer streams back.

Includes: tenancy and row-level security (TEN), local accounts (AUTH), the
sandbox and its network isolation (SBX), mediated tools (AGT-001), the model
gateway with one local and one remote provider (MOD), the public API with
conversations, message versions, rewinding, stopping runs and streaming (API,
CNV-001 to CNV-004, CNV-015; message versions were replaced in phase 1 by
editing that rewinds, ADR-0068), the cost ledger (MOD-006), privacy defaults for
logs (OBS), Docker Compose deployment (OPS), and the repository governance
checks (REPO). There is no user interface in phase 0: the API is exercised by
end-to-end tests (ADR-0024).

**Exit criteria:**

- every phase 0 requirement is `implemented`, with passing tests;
- the cross-user, cross-tenant and sandbox network security tests pass;
- a fresh Linux host goes from `git clone` to a working conversation by
  following the README.

## Phase 1 — Daily use

**Goal:** an assistant the maintainer's family uses every day, on the web and
on the phone (installable web app).

Includes: the web client as an installable web app (UX) with externalized
strings (I18N-001), notifications, voice turns (UX-005, API-006), live context
and cost (UX-008, MOD-007), the conversation list with folders, forks, search,
the file library, conversation settings, custom instructions, temporary
conversations and sharing within the household (CNV), artifacts (ART),
automatic compaction, skills and questions to the user (AGT), web search and
page reading, persistent workspaces in ephemeral sandboxes (ADR-0076), a
sandbox image with a selection of common tools for documents, media and
data, so that they need no installing (ADR-0022), transparent memory (MEM), tool
permissions, provenance and approvals with the lethal trifecta mitigation
(AGT), the data egress policy (MOD-003), backup and restore (OPS-006), and the
first eval suite (EVL). It also lays the foundations of connected devices:
approval of every call to a device or an MCP server (AGT-018), remote MCP
servers added by tenant admins (AGT-019), passkeys as a second factor
(AUTH-010), and models labeled as local or remote (MOD-010).

Suggested order: the web client's foundation (sign-in, conversations, streamed
answers, versions, model settings); then trust (approvals, the egress policy,
local and remote models, passkeys, backup, the first evals); then everyday
conversations; memory and files; remote MCP servers and the other agent
capabilities; notifications and voice last.

**Exit criteria:** used daily by at least one household for a month without
data loss; eval suite in place, including injection scenarios.

## Phase 2 — Connected devices

**Goal:** the assistant helps with the household's own machines: diagnosing a
server, installing updates, checking logs and firewall rules, editing files,
from any device where the user is signed in.

Includes: the device service for Linux, paired to one user and connected
outbound (DEV-001, DEV-002), its tools for commands and files (DEV-003), the
tools of several devices in one run (DEV-004), calls that wait for offline
devices (DEV-005), device status (DEV-006), least privilege by default
(DEV-007), and the web app as a device (DEV-008) (ADR-0063). macOS and
Windows may follow (DEV-009).

**Exit criteria:** the maintainer administers their own servers through
Sibillo for a month, with every device call approved and none surprising.

## Phase 3 — A real assistant, and a first release

**Goal:** the features that make it an assistant rather than a chat, and the
release engineering to let others run it.

Includes: multi-step research producing reports, browser automation in the
sandbox, scheduled tasks, connectors over open protocols (calendar, mail,
files, home automation through mediated tools), OpenID Connect (AUTH-003),
budgets (MOD-004), debug mode (OBS-004), signed multi-architecture images,
upgrade guarantees, English and Italian translations, release gating by evals.

**Exit criteria:** first public release `0.1.0`; installation and upgrade
documentation verified on a clean machine; public announcement.

## Phase 4 — Opening up

**Goal:** make the project sustainable beyond its first household.

Candidates: tenant administration for operators hosting several households,
Kata Containers and Kubernetes providers, a native mobile app with push
notifications, community translations, a second maintainer and the governance
transition described in [GOVERNANCE.md](GOVERNANCE.md).

## Later

Ideas kept for after these phases, not planned yet:

- personal remote MCP servers that a user adds for themselves, with per-user
  credentials and OAuth sign-in (ADR-0064);
- sessions of external coding agents shown as Sibillo conversations.

