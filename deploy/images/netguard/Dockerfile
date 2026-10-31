# The network guard (ADR-0021, ADR-0053): installs the egress table on the
# host. Run with host networking and NET_ADMIN, nothing else. Built from the
# repository root: `docker build -f deploy/images/netguard/Dockerfile .`
FROM python:3.13.9-slim-trixie

RUN apt-get update \
    && apt-get install --yes --no-install-recommends nftables \
    && rm -rf /var/lib/apt/lists/*

COPY src/netguard/mazzamurello_netguard /opt/netguard/mazzamurello_netguard
ENV PYTHONPATH=/opt/netguard PYTHONDONTWRITEBYTECODE=1

# Unhealthy while the table is missing and for 10 seconds after it was
# last found missing; the sandbox driver stops sandboxes meanwhile.
HEALTHCHECK --interval=1s --timeout=3s --start-period=10s --retries=1 \
    CMD ["python", "-m", "mazzamurello_netguard", "check"]
STOPSIGNAL SIGTERM
CMD ["python", "-m", "mazzamurello_netguard"]
