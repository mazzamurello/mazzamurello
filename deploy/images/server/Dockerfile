# The server image: API, worker, migrations and the operator commands
# (ADR-0028, ADR-0054). Built from the repository root:
# `docker build -f deploy/images/server/Dockerfile .`
FROM python:3.13.9-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
# The workspace's lock file pins every dependency, with hashes (REPO-009).
COPY pyproject.toml uv.lock ./
COPY src/server/pyproject.toml src/server/pyproject.toml
COPY src/sandboxd/pyproject.toml src/sandboxd/pyproject.toml
COPY src/netguard/pyproject.toml src/netguard/pyproject.toml
RUN uv sync --frozen --no-dev --package mazzamurello-server --no-install-workspace
COPY src/server src/server
COPY migrations migrations
RUN uv sync --frozen --no-dev --package mazzamurello-server --no-editable

ENV PATH=/opt/venv/bin:$PATH
RUN useradd --system --uid 10001 --no-create-home mazzamurello
USER mazzamurello
ENTRYPOINT ["python", "-m"]
CMD ["mazzamurello_server", "api"]
