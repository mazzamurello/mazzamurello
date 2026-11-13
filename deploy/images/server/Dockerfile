# The server image: API, worker, migrations and the operator commands
# (ADR-0028, ADR-0054). Built from the repository root:
# `docker build -f deploy/images/server/Dockerfile .`
# The web app (ADR-0067), built with Node, which the running image does not need.
FROM node:24.14.1-trixie-slim AS web
WORKDIR /build/src/web
RUN corepack enable
COPY specs/contracts/openapi.yaml /build/specs/contracts/openapi.yaml
COPY src/web/package.json src/web/pnpm-lock.yaml src/web/pnpm-workspace.yaml ./
RUN COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm install --frozen-lockfile
COPY src/web ./
RUN pnpm build

FROM python:3.13.9-slim-trixie

# Backups dump and restore the database and encrypt their archives (ADR-0077).
RUN apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client-17 age \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
# The workspace's lock file pins every dependency, with hashes (REPO-009).
COPY pyproject.toml uv.lock ./
COPY src/server/pyproject.toml src/server/pyproject.toml
COPY src/sandboxd/pyproject.toml src/sandboxd/pyproject.toml
COPY src/netguard/pyproject.toml src/netguard/pyproject.toml
RUN uv sync --frozen --no-dev --package sibillo-server --no-install-workspace
COPY src/server src/server
COPY migrations migrations
RUN uv sync --frozen --no-dev --package sibillo-server --no-editable

ENV PATH=/opt/venv/bin:$PATH
# Served at `/` by the API (SIBILLO_WEB_ROOT's default).
COPY --from=web /build/src/web/dist /opt/sibillo/web
RUN useradd --system --uid 10001 --no-create-home sibillo
USER sibillo
ENTRYPOINT ["python", "-m"]
CMD ["sibillo_server", "api"]
