# The sandbox driver image (ADR-0022, ADR-0054): the only container with the
# Docker socket. Built from the repository root:
# `docker build -f deploy/images/sandboxd/Dockerfile .`
FROM python:3.13.9-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/server/pyproject.toml src/server/pyproject.toml
COPY src/sandboxd/pyproject.toml src/sandboxd/pyproject.toml
COPY src/netguard/pyproject.toml src/netguard/pyproject.toml
RUN uv sync --frozen --no-dev --package mazzamurello-sandboxd --no-install-workspace
COPY src/sandboxd src/sandboxd
RUN uv sync --frozen --no-dev --package mazzamurello-sandboxd --no-editable

ENV PATH=/opt/venv/bin:$PATH
# The Docker socket is root's; the driver holds it alone (SBX-009).
ENTRYPOINT ["python", "-m", "mazzamurello_sandboxd"]
