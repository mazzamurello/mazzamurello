"""The egress table of the sandbox bridge, kept in the host kernel (ADR-0021, ADR-0053).

The table matches only traffic entering from the sandbox bridge. It drops
forwarded traffic to every local range of SBX-005, all IPv6 (SBX-013), and
everything addressed to the host itself; the rest is left to the host's
normal processing, so sandboxes reach public addresses (SBX-004). It never
touches other tables.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from pathlib import Path
from types import FrameType

logger = logging.getLogger("mazzamurello.netguard")

TABLE_FAMILY = "inet"
TABLE_NAME = "mazzamurello"
BRIDGE_INTERFACE = "mzmsbx0"
CHECK_INTERVAL_SECONDS = 1.0
# The guard reports unhealthy this long after it last found the table missing (ADR-0053).
UNHEALTHY_AFTER_MISSING_SECONDS = 10.0
STATE_FILE = Path("/run/mazzamurello-netguard/last-missing")

BLOCKED_IPV4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
)

RULES = f"""
table {TABLE_FAMILY} {TABLE_NAME} {{
  chain forward {{
    type filter hook forward priority -10; policy accept;
    iifname "{BRIDGE_INTERFACE}" meta nfproto ipv6 drop
    iifname "{BRIDGE_INTERFACE}" ip daddr {{ {", ".join(BLOCKED_IPV4)} }} drop
  }}
  chain input {{
    type filter hook input priority -10; policy accept;
    iifname "{BRIDGE_INTERFACE}" drop
  }}
}}
"""


def _nft(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - nft with fixed arguments
        ["nft", *args],  # noqa: S607 - nft from the image's PATH
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def table_present() -> bool:
    """Whether the table is installed with both of its chains."""
    listed = _nft("list", "table", TABLE_FAMILY, TABLE_NAME)
    return listed.returncode == 0 and "chain forward" in listed.stdout and "chain input" in listed.stdout


def install() -> None:
    """Install the table, replacing any previous version of it atomically."""
    script = f"table {TABLE_FAMILY} {TABLE_NAME}\ndelete table {TABLE_FAMILY} {TABLE_NAME}\n{RULES}"
    result = _nft("-f", "-", stdin=script)
    if result.returncode != 0:
        raise RuntimeError(f"nft refused the egress table: {result.stderr.strip()}")


def remove() -> None:
    _nft("delete", "table", TABLE_FAMILY, TABLE_NAME)


def _mark_missing() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(time.time()))


def healthy() -> bool:
    """The health check: the table is in place, and was not missing in the last seconds."""
    if not table_present():
        return False
    try:
        last_missing = float(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return True
    return time.time() - last_missing > UNHEALTHY_AFTER_MISSING_SECONDS


def run() -> None:
    """Install the table, keep it in place, and remove it on shutdown."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    install()
    logger.info("egress table %s %s installed for %s", TABLE_FAMILY, TABLE_NAME, BRIDGE_INTERFACE)
    try:
        while not stopping:
            time.sleep(CHECK_INTERVAL_SECONDS)
            if not table_present():
                logger.warning("egress table missing: reinstalling it")
                _mark_missing()
                install()
    finally:
        remove()
        logger.info("egress table removed")
