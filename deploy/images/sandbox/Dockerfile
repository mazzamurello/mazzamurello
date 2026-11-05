# The sandbox image (ADR-0053): where the agent's commands run, under gVisor.
# It holds no credentials (SBX-008) and runs nothing until the driver execs
# commands in it.
FROM debian:13.2-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash ca-certificates coreutils curl git iproute2 procps python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# The page reader of read_page (AGT-021, ADR-0075), with its dependencies
# pinned by hash, in an environment of its own.
COPY deploy/images/sandbox/reader-requirements.txt /opt/reader-requirements.txt
RUN python3 -m venv /opt/reader \
    && /opt/reader/bin/pip install --no-cache-dir --require-hashes --only-binary :all: \
        -r /opt/reader-requirements.txt \
    && rm /opt/reader-requirements.txt
COPY --chmod=0755 deploy/images/sandbox/mzm-read-page /usr/local/bin/mzm-read-page

# Commands start in the scratch folder; only /workspace persists (ADR-0076).
RUN mkdir -p /scratch /workspace
WORKDIR /scratch
CMD ["sleep", "infinity"]
