# ADR-0051: Model configurations managed through the API

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0011, ADR-0027, ADR-0036, ADR-0042, MOD-001, MOD-002, MOD-006, MOD-008

## Context

Runs need a model. Which models a household uses changes over time: a local
server today, a remote service for harder questions tomorrow. The maintainer
wants them configured from the settings of the client, not from files on the
host, so they are managed through the public API (ADR-0016) and stored in the
database. A family member who administers their own tenant may bring their
own provider and key. Provider credentials are the most valuable secret the
instance holds (MOD-002).

## Decision

1. **Model configurations.** An admin configures models one at a time: a
   name shown to users, the endpoint of an OpenAI-compatible API, the model
   name the endpoint expects, an optional API key, whether the provider is
   paid per token, and optional prices per million tokens. One configuration
   per model keeps the rules simple; a provider offering several models gets
   several configurations.
2. **Two scopes.** The instance admin manages **instance models**, available
   to every tenant. A tenant admin manages **tenant models**, available only in
   their tenant. Each scope has at most one **default model**. A run uses the
   tenant's default model, or else the instance's (MOD-008); choosing a model
   per conversation comes later.
3. **Credentials are write-only and encrypted.** An API key is accepted when a
   configuration is created or updated and never returned; responses only say
   whether one is set. Keys are encrypted with AES-256-GCM under a key that
   the control plane reads from `MZM_SECRET_KEY`, so a database dump or backup
   alone does not reveal them. The model gateway decrypts a key only to make
   a request (MOD-002).
4. **Endpoints of tenant models are restricted.** The model gateway makes
   requests from the control plane, so an endpoint chosen by a tenant admin
   could reach internal services. Tenant model endpoints must use `https` and
   resolve only to public addresses, checked when they are saved and again on
   every request. Instance models, configured by the trusted instance admin
   (ADR-0011), may use any address, such as a local server on the household's
   network.
5. **Prices** feed the cost ledger in the order of ADR-0042: the cost reported
   by the provider, then the prices of the configuration, then the
   genai-prices catalog. A configuration that is not paid per token records a
   cost of zero.

## Consequences

- Phase 0 has no settings screen; the API is the settings, and the web client
  uses it in phase 1.
- Losing `MZM_SECRET_KEY` makes stored API keys unusable; admins enter them
  again. Rotating the key needs a migration of the stored keys, planned later.
- Tenant admins cannot use a provider on the household's network unless the
  instance admin configures it as an instance model.
- Instance models are a table without `tenant_id`, like `tenants`: they are
  configuration of the instance, not data of a tenant.

## Alternatives considered

- **Providers configured in environment variables:** simple, but every change
  needs access to the host and a restart, and tenant admins could not bring
  their own.
- **Providers with nested models:** fewer repeated endpoints and keys, but
  defaults, prices and validation all need two levels.
- **Keys stored in plain text:** the database is trusted (ADR-0011), but every
  backup would carry usable keys.
- **One table with a nullable `tenant_id`:** composite foreign keys with a
  null tenant are not checked, and row-level security and design tests would
  need exceptions.
