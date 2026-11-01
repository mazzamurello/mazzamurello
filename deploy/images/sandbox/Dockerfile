# The sandbox image (ADR-0053): where the agent's commands run, under gVisor.
# It holds no credentials (SBX-008) and runs nothing until the driver execs
# commands in it.
FROM debian:13.2-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash ca-certificates coreutils curl git iproute2 procps python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
CMD ["sleep", "infinity"]
