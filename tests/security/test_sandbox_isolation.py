"""Isolation of sandboxes, checked from inside them (SBX-001 to SBX-015, ADR-0021, ADR-0053).

A listener on the host proves that the blocked addresses would be reachable
without the egress rules: a plain container on Docker's default network
reaches it, a sandbox does not.
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.sandbox import (
    SANDBOX_NETWORK,
    Driver,
    docker,
    driver_environment,
    free_port,
    start_driver_process,
)

CONNECT = (
    "python3 -c \"import socket,sys; s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET);"
    " s.settimeout(3); s.connect((sys.argv[1], int(sys.argv[2]))); print('connected')\""
)
# Connects to every address at once, each with a 3-second timeout, and
# prints `connected <address>` for each that answers: blocked addresses
# time out together instead of one after another.
PROBE = (
    'python3 -c "import socket,sys,threading\n'
    "def probe(host):\n"
    "    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET); s.settimeout(3)\n"
    "    try:\n"
    "        s.connect((host, int(sys.argv[1]))); print('connected', host, flush=True)\n"
    "    except OSError:\n"
    "        pass\n"
    "threads=[threading.Thread(target=probe, args=(host,)) for host in sys.argv[2:]]\n"
    '[thread.start() for thread in threads]; [thread.join() for thread in threads]"'
)
# One address from every range of SBX-005, IPv4 and IPv6.
BLOCKED_RANGES = (
    "0.0.0.1",
    "10.0.0.1",
    "100.64.0.1",
    "127.0.0.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.0.1",
    "224.0.0.1",
    "240.0.0.1",
    "::1",
    "fc00::1",
    "fe80::1",
    "ff02::1",
)


def _user() -> tuple[str, str]:
    return str(uuid7()), str(uuid7())


def _connects(driver: Driver, tenant_id: str, user_id: str, host: str, port: int) -> bool:
    result = driver.sh(tenant_id, user_id, f"{CONNECT} {host} {port}", timeout_seconds=15)
    return result.exit_code == 0 and "connected" in result.stdout


def _reachable(driver: Driver, tenant_id: str, user_id: str, hosts: list[str], port: int) -> set[str]:
    """The hosts a sandbox connects to, probed all at once."""
    result = driver.sh(tenant_id, user_id, f"{PROBE} {port} {' '.join(hosts)}", timeout_seconds=15)
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith("connected ")}


def _host_addresses() -> list[str]:
    """IPv4 addresses of this host: its LAN address, Docker's bridges, the sandbox bridge's gateway."""
    output = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, check=True).stdout  # noqa: S607
    addresses = [line.split()[3].split("/")[0] for line in output.splitlines()]
    return [address for address in addresses if not ipaddress.ip_address(address).is_loopback]


@pytest.fixture(scope="module")
def host_listener() -> Iterator[int]:
    """A TCP listener on every address of the host."""
    server = socket.create_server(("0.0.0.0", 0))  # noqa: S104 - reachable from containers on purpose
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                connection, _ = server.accept()
                connection.close()
            except TimeoutError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield port
    stop.set()
    thread.join(5)
    server.close()


def _reachable_from_a_plain_container(image: str, hosts: list[str], port: int) -> set[str]:
    command = f"{PROBE} {port} {' '.join(hosts)}"
    result = subprocess.run(  # noqa: S603
        ["docker", "run", "--rm", image, "sh", "-c", command],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith("connected ")}


@pytest.mark.spec("SBX-002")
def test_sandboxes_run_under_gvisor(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(tenant_id, user_id, "dmesg 2>/dev/null | head -n 1")
    assert "gVisor" in result.stdout
    for container in sandboxes.sandbox_containers():
        assert container["HostConfig"]["Runtime"] == "runsc"


@pytest.mark.spec("SBX-005")
def test_the_host_is_unreachable_from_sandboxes(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id = _user()
    addresses = _host_addresses()
    assert addresses
    controls = _reachable_from_a_plain_container(sandboxes.image, addresses, host_listener)
    assert controls == set(addresses), "negative control: every address is reachable without the egress rules"
    assert _reachable(sandboxes, tenant_id, user_id, addresses, host_listener) == set()


@pytest.mark.spec("SBX-005", "SBX-013")
def test_local_ranges_are_unreachable_from_sandboxes(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id = _user()
    assert _reachable(sandboxes, tenant_id, user_id, list(BLOCKED_RANGES), host_listener) == set()


@pytest.mark.spec("SBX-005")
def test_rewriting_routes_inside_the_sandbox_does_not_help(sandboxes: Driver, host_listener: int) -> None:
    tenant_id, user_id = _user()
    # Root in the sandbox controls its own network configuration.
    sandboxes.sh(tenant_id, user_id, "ip route add 192.168.0.0/16 dev eth0 2>/dev/null; ip route show")
    assert _reachable(sandboxes, tenant_id, user_id, _host_addresses(), host_listener) == set()


@pytest.mark.spec("SBX-013")
def test_sandboxes_have_no_ipv6(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(tenant_id, user_id, "cat /proc/net/if_inet6 2>/dev/null; ip -6 addr show scope global")
    assert "global" not in result.stdout
    assert not _connects(sandboxes, tenant_id, user_id, "2606:4700:4700::1111", 443)


@pytest.mark.spec("SBX-004")
def test_sandboxes_reach_the_internet(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    assert _connects(sandboxes, tenant_id, user_id, "1.1.1.1", 443)
    by_name = sandboxes.sh(tenant_id, user_id, "curl -sS -o /dev/null -w '%{http_code}' https://example.com")
    assert by_name.stdout in {"200", "301", "302"}, by_name.stderr


@pytest.mark.spec("SBX-006")
def test_sandboxes_cannot_reach_each_other(sandboxes: Driver) -> None:
    listener, intruder = _user(), _user()
    port = 8765
    with sandboxes.client() as client:
        client.post(f"/sandboxes/{listener[0]}/{listener[1]}/ensure")
    sandboxes.sh(*listener, f"nohup python3 -m http.server {port} >/dev/null 2>&1 & sleep 1")
    address = sandboxes.sh(*listener, "hostname -i").stdout.split()[0]
    assert _connects(sandboxes, *listener, "127.0.0.1", port), "negative control: the server listens"
    assert not _connects(sandboxes, *intruder, address, port)


@pytest.mark.spec("SBX-001")
@pytest.mark.parametrize("same_tenant", [True, False], ids=["same-tenant", "other-tenant"])
def test_workspaces_are_separate(sandboxes: Driver, same_tenant: bool) -> None:
    owner = _user()
    other = (owner[0], str(uuid7())) if same_tenant else _user()
    secret = f"secret-{uuid7()}"
    sandboxes.sh(*owner, f"echo {secret} > secret.txt")
    found = sandboxes.sh(*other, "ls -a /workspace; cat /workspace/secret.txt 2>/dev/null")
    assert secret not in found.stdout


@pytest.mark.spec("SBX-008")
def test_sandboxes_hold_no_credentials(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    environment = sandboxes.sh(tenant_id, user_id, "env").stdout
    assert sandboxes.token not in environment
    assert "MZM_" not in environment
    assert "DOCKER" not in environment
    assert sandboxes.sh(tenant_id, user_id, "test -e /var/run/docker.sock").exit_code != 0
    for container in sandboxes.sandbox_containers():
        assert not [entry for entry in container["Config"]["Env"] if "TOKEN" in entry or "KEY" in entry]


@pytest.mark.spec("SBX-012", "SBX-002", "SBX-011")
def test_sandbox_containers_follow_the_fixed_policy(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    sandboxes.sh(tenant_id, user_id, "true")
    containers = sandboxes.sandbox_containers()
    assert containers
    for container in containers:
        host: dict[str, Any] = container["HostConfig"]
        assert host["Privileged"] is False
        assert host["Runtime"] == "runsc"
        assert not host.get("CapAdd")
        assert host.get("PidMode", "") in {"", "private"}
        assert host.get("IpcMode", "") in {"", "private", "shareable", "none"}
        assert host["NetworkMode"] == SANDBOX_NETWORK
        assert not host.get("Binds")
        assert [mount["Type"] for mount in container["Mounts"]] == ["volume"]
        assert [mount["Destination"] for mount in container["Mounts"]] == ["/workspace"]
        assert host["NanoCpus"] == 500_000_000
        assert host["Memory"] == 256 * 1024 * 1024
        ulimits: list[dict[str, Any]] = host.get("Ulimits") or []
        assert {limit["Name"]: limit["Hard"] for limit in ulimits}.get("nproc") == 64


@pytest.mark.spec("SBX-011")
def test_memory_is_limited(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(
        tenant_id, user_id, "python3 -c \"b=bytearray(600*1024*1024); print('allocated')\"", timeout_seconds=20
    )
    assert "allocated" not in result.stdout


@pytest.mark.spec("SBX-011")
def test_processes_are_limited_inside_the_sandbox(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    # Small processes, so that the process limit is reached before memory
    # runs out: forked copies of the interpreter exhaust a small sandbox first.
    script = (
        "import os\n"
        "started = 0\n"
        "for _ in range(200):\n"
        "    try:\n"
        "        os.posix_spawn('/bin/sleep', ['sleep', '5'], {})\n"
        "        started += 1\n"
        "    except OSError:\n"
        "        break\n"
        "print(started)\n"
    )
    result = sandboxes.exec(tenant_id, user_id, {"argv": ["python3", "-c", script], "timeout_seconds": 20})
    assert int(result.stdout.strip().splitlines()[-1]) < 64


def _refused_the_runtime(health: dict[str, Any] | None) -> bool:
    """Whether the driver has checked the runtime, or run its canary, and found it is not gVisor."""
    if health is None:
        return False
    checks = cast(dict[str, dict[str, Any]], health["checks"])
    return any(
        checks.get(name, {}).get("ok") is False and checks[name].get("detail")
        for name in ("isolation_runtime", "canary")
    )


@pytest.mark.spec("SBX-003", "SBX-002")
@pytest.mark.parametrize("runtime", ["runc", "no-such-runtime"])
def test_the_driver_refuses_sandboxes_without_gvisor(sandboxes: Driver, runtime: str) -> None:
    port = free_port()
    environment = driver_environment(
        sandboxes.token, sandboxes.image, sandboxes.netguard, port, MZM_SANDBOX_RUNTIME=runtime
    )
    process = start_driver_process(environment)
    try:
        # Never ready, while it starts and once it has checked the runtime.
        last: dict[str, Any] | None = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not _refused_the_runtime(last):
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{port}/v1/health",
                    headers={"Authorization": f"Bearer {sandboxes.token}"},
                    timeout=10,
                )
            except httpx.TransportError:
                time.sleep(0.5)
                continue
            assert response.status_code == 503, "a driver without gVisor reported ready"
            last = response.json()
            time.sleep(0.5)
        assert last is not None, process.output()
        assert last["ready"] is False
        assert not (last["checks"]["isolation_runtime"]["ok"] and last["checks"]["canary"]["ok"])
        tenant_id, user_id = _user()
        refused = httpx.post(
            f"http://127.0.0.1:{port}/v1/sandboxes/{tenant_id}/{user_id}/ensure",
            headers={"Authorization": f"Bearer {sandboxes.token}"},
            timeout=30,
        )
        assert refused.status_code == 503
        assert refused.json()["code"] == "driver.isolation_unavailable"
    finally:
        process.close()


@pytest.mark.spec("SBX-015")
def test_sandboxes_stop_when_the_egress_rules_disappear(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    sandboxes.sh(tenant_id, user_id, "true")
    running = [c for c in sandboxes.sandbox_containers() if c["State"]["Running"]]
    assert running
    docker("exec", sandboxes.netguard, "nft", "delete", "table", "inet", "mazzamurello")
    deadline = time.monotonic() + 30
    while any(c["State"]["Running"] for c in sandboxes.sandbox_containers()):
        assert time.monotonic() < deadline, "sandboxes kept running without egress rules"
        time.sleep(0.5)
    with sandboxes.client() as client:
        assert client.get("/health").status_code == 503
    # The guard restores the table; after a new canary, sandboxes start again.
    health = sandboxes.wait_until_ready()
    assert health["checks"]["egress_table"]["ok"] is True
    assert sandboxes.sh(tenant_id, user_id, "echo back").stdout == "back\n"
