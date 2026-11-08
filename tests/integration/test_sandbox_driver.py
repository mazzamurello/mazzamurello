"""The sandbox driver's API, and the tools its sandboxes hold.

specs/contracts/sandbox-driver.yaml, ADR-0022, ADR-0053 and ADR-0080.
"""

from __future__ import annotations

import textwrap
import time
from typing import Any, cast

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.sandbox import Driver, driver_environment, free_port, start_driver_process


def _sandbox() -> tuple[str, str, str]:
    """A tenant, a user and a conversation of theirs: one sandbox (SBX-001)."""
    return str(uuid7()), str(uuid7()), str(uuid7())


@pytest.mark.spec("SBX-003", "SBX-015", "SBX-017", "OPS-002", "OPS-009")
def test_the_driver_reports_verified_isolation(sandboxes: Driver) -> None:
    with sandboxes.client() as client:
        response = client.get("/health")
    assert response.status_code == 200, response.text
    health = response.json()
    assert health["ready"] is True
    assert health["runtime_version"].startswith("release-")
    assert set(health["checks"]) >= {"platform", "isolation_runtime", "runtime_version", "egress_table", "canary"}
    assert all(check["ok"] is True for check in health["checks"].values())


@pytest.mark.spec("SBX-009")
@pytest.mark.parametrize("token", [None, "wrong-token-of-sufficient-length-0123456789"], ids=["missing", "wrong"])
def test_every_request_needs_the_control_plane_secret(sandboxes: Driver, token: str | None) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    with sandboxes.client() as client:
        headers = {"Authorization": ""} if token is None else {"Authorization": f"Bearer {token}"}
        for method, path, body in (
            ("GET", "/health", None),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure", None),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/exec", {"argv": ["true"]}),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/stop", None),
        ):
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401, (path, response.text)
            assert response.json()["code"] == "driver.unauthenticated"


@pytest.mark.spec("SBX-001", "SBX-002")
def test_ensure_starts_one_sandbox_per_user(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    with sandboxes.client() as client:
        first = client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure")
        again = client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/ensure")
    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    assert first.json()["state"] == "running"
    # Commands start in the scratch folder (SBX-018).
    assert first.json()["working_dir"] == again.json()["working_dir"] == "/scratch"
    assert first.json()["started_at"] == again.json()["started_at"]


@pytest.mark.spec("AGT-011")
def test_commands_return_output_and_exit_codes(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    argv = sandboxes.exec(tenant_id, user_id, conversation_id, {"argv": ["sh", "-c", "echo out; echo err >&2; exit 3"]})
    assert (argv.exit_code, argv.stdout, argv.stderr, argv.timed_out, argv.truncated) == (
        3,
        "out\n",
        "err\n",
        False,
        False,
    )
    shell = sandboxes.sh(tenant_id, user_id, conversation_id, "pwd; echo $GREETING", env={"GREETING": "hello"})
    assert (shell.exit_code, shell.stdout) == (0, "/scratch\nhello\n")
    elsewhere = sandboxes.sh(tenant_id, user_id, conversation_id, "mkdir -p /workspace/sub && cd /workspace/sub && pwd")
    assert elsewhere.stdout == "/workspace/sub\n"
    workdir = sandboxes.exec(tenant_id, user_id, conversation_id, {"argv": ["pwd"], "workdir": "/workspace/sub"})
    assert workdir.stdout == "/workspace/sub\n"


@pytest.mark.spec("AGT-011")
def test_commands_get_end_of_file_on_stdin(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    result = sandboxes.sh(tenant_id, user_id, conversation_id, "cat; echo done", timeout_seconds=10)
    assert (result.exit_code, result.stdout, result.timed_out) == (0, "done\n", False)


@pytest.mark.spec("SBX-011")
def test_commands_are_stopped_at_their_timeout(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    started = time.monotonic()
    result = sandboxes.sh(tenant_id, user_id, conversation_id, "echo started; sleep 60", timeout_seconds=2)
    assert time.monotonic() - started < 20
    assert (result.timed_out, result.exit_code) == (True, None)
    assert result.stdout == "started\n"
    # Nothing of the command keeps running.
    assert "sleep 60" not in sandboxes.sh(tenant_id, user_id, conversation_id, "ps -eo args").stdout


@pytest.mark.spec("SBX-011")
def test_timeouts_are_capped_by_the_configuration(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    started = time.monotonic()
    # The test configuration caps commands at 8 seconds.
    result = sandboxes.sh(tenant_id, user_id, conversation_id, "sleep 120", timeout_seconds=3600)
    assert result.timed_out is True
    assert time.monotonic() - started < 60


@pytest.mark.spec("AGT-011", "AGT-014")
def test_output_beyond_the_limit_is_truncated(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    result = sandboxes.sh(
        tenant_id, user_id, conversation_id, "head -c 100000 /dev/zero | tr '\\0' a", max_output_bytes=1000
    )
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 1000
    assert result.exit_code == 0


@pytest.mark.spec("SBX-010")
def test_the_workspace_survives_stopping_the_sandbox(sandboxes: Driver) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    sandboxes.sh(tenant_id, user_id, conversation_id, "echo kept > /workspace/notes.txt")
    with sandboxes.client() as client:
        assert client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/stop").status_code == 204
        # Stopping a stopped sandbox is fine too.
        assert client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/stop").status_code == 204
    assert sandboxes.sh(tenant_id, user_id, conversation_id, "cat /workspace/notes.txt").stdout == "kept\n"


@pytest.mark.spec("AGT-011")
@pytest.mark.parametrize(
    "request_body",
    [
        {},
        {"argv": ["true"], "shell_command": "true"},
        {"argv": []},
        {"shell_command": ""},
        {"argv": ["true"], "privileged": True},
        {"argv": ["true"], "timeout_seconds": 0},
    ],
    ids=["nothing", "both", "empty-argv", "empty-shell", "unknown-field", "zero-timeout"],
)
def test_invalid_exec_requests_are_rejected(sandboxes: Driver, request_body: dict[str, Any]) -> None:
    tenant_id, user_id, conversation_id = _sandbox()
    with sandboxes.client() as client:
        response = client.post(f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}/exec", json=request_body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "driver.validation_failed"


@pytest.mark.spec("SBX-001")
@pytest.mark.parametrize(
    "path",
    [
        f"not-a-uuid/{uuid7()}/{uuid7()}",
        f"{uuid7()}/../x/{uuid7()}",
        f"{uuid7()}/{uuid7()}/not-a-uuid",
        f"{uuid7()}/{uuid7()}",
    ],
    ids=["tenant", "user", "conversation", "no-conversation"],
)
def test_sandboxes_are_addressed_only_by_identifiers(sandboxes: Driver, path: str) -> None:
    with sandboxes.client() as client:
        response = client.post(f"/sandboxes/{path}/ensure")
    assert response.status_code in {404, 422}, response.text


def _health_of(port: int, token: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/v1/health", headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
    except httpx.TransportError:
        return None
    return cast(dict[str, Any], response.json())


@pytest.mark.spec("SBX-017")
def test_the_driver_refuses_a_gvisor_release_older_than_its_minimum(sandboxes: Driver) -> None:
    port = free_port()
    minimum = "release-29991231.0"
    environment = driver_environment(
        sandboxes.token, sandboxes.image, sandboxes.netguard, port, MZM_SANDBOX_MINIMUM_GVISOR_RELEASE=minimum
    )
    process = start_driver_process(environment)
    try:
        health: dict[str, Any] | None = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            health = _health_of(port, sandboxes.token)
            if health is not None and health["checks"].get("runtime_version", {}).get("detail"):
                break
            time.sleep(0.5)
        assert health is not None, process.output()
        assert health["ready"] is False
        release = health["checks"]["runtime_version"]
        assert release["ok"] is False
        assert minimum in release["detail"]
        assert "https://gvisor.dev/docs/user_guide/install/" in release["detail"]
        refused = httpx.post(
            f"http://127.0.0.1:{port}/v1/sandboxes/{uuid7()}/{uuid7()}/{uuid7()}/ensure",
            headers={"Authorization": f"Bearer {sandboxes.token}"},
            timeout=30,
        )
        assert refused.status_code == 503
        assert refused.json()["code"] == "driver.runtime_too_old"
    finally:
        process.close()


@pytest.mark.spec("SBX-017")
def test_the_gvisor_minimum_cannot_be_lowered(sandboxes: Driver) -> None:
    variable = "MZM_SANDBOX_MINIMUM_GVISOR_RELEASE"
    environment = driver_environment(
        sandboxes.token, sandboxes.image, sandboxes.netguard, free_port(), **{variable: "release-20200101.0"}
    )
    process = start_driver_process(environment)
    try:
        deadline = time.monotonic() + 30
        while process.exited() is None:
            assert time.monotonic() < deadline, "the driver accepted a lower gVisor minimum"
            time.sleep(0.2)
        assert process.exited() == 2
        # The error names the setting and the built-in minimum it may not go below (ADR-0053).
        assert variable in process.output()
        assert "release-20261026.0" in process.output()
    finally:
        process.close()


def _tools(sandboxes: Driver, script: str) -> str:
    """Run a script of tool calls in a new sandbox, a step per paragraph, each in a command of its own (SBX-021).

    The test driver ends a command after a few seconds (SBX-011); the steps share the sandbox's /scratch.
    """
    sandbox = _sandbox()
    output = ""
    try:
        for step in textwrap.dedent(script).strip().split("\n\n"):
            result = sandboxes.sh(*sandbox, f"set -eu\n{step}")
            assert result.exit_code == 0, f"{step}\n{result.stdout}\n{result.stderr}"
            output += result.stdout
    finally:
        # Stopped at once, as after an answer, so that no test waits on it (SBX-018).
        sandboxes.stop(*sandbox)
    return output


@pytest.mark.spec("SBX-021")
def test_the_sandbox_reads_and_makes_documents(sandboxes: Driver) -> None:
    output = _tools(
        sandboxes,
        """
        python3 - <<'EOF'
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        figure = plt.figure()
        figure.text(0.1, 0.5, "Household budget")
        figure.savefig("budget.pdf")
        EOF

        pdftotext budget.pdf -
        pdfinfo budget.pdf | grep -c '^Pages:'
        qpdf --check budget.pdf >/dev/null && echo qpdf-ok

        printf '# Shopping\\n\\n- basil\\n' | pandoc -f markdown -t html
        printf '# Shopping\\n' | pandoc -o list.docx && test -s list.docx && echo pandoc-docx-ok

        printf -- '---\\ntitle: Dinner plan\\n---\\n\\n# Monday\\n\\n' > plan.md
        printf '| Dish | Cost |\\n|---|---|\\n| Pasta | 3 |\\n' >> plan.md
        pandoc plan.md -o plan.pdf --pdf-engine=typst && pdftotext plan.pdf - | tr -s ' \\n' ' '; echo
        pdffonts plan.pdf | grep -o 'Libertinus[A-Za-z]*' | head -1

        fc-list : family | sort -u
        """,
    )
    assert "Household budget" in output
    assert "qpdf-ok" in output
    assert "<li>basil</li>" in output
    assert "pandoc-docx-ok" in output
    # Typeset to PDF by Typst, with a plain command and its own font (ADR-0084).
    assert "Dinner plan Monday Dish Cost Pasta 3" in output
    assert "LibertinusSerif" in output
    for family in ("DejaVu Sans", "Liberation Sans", "Liberation Serif", "Noto Sans"):
        assert family in output, f"no {family} font"


@pytest.mark.spec("SBX-021")
def test_office_files_are_read_and_written_and_turned_into_markdown(sandboxes: Driver) -> None:
    output = _tools(
        sandboxes,
        """
        python3 - <<'EOF'
        import docx, openpyxl, pptx
        document = docx.Document()
        document.add_paragraph("Letter to the landlord")
        document.save("letter.docx")
        book = openpyxl.Workbook()
        book.active.append(["item", "cost"])
        book.active.append(["tomatoes", 3])
        book.save("costs.xlsx")
        deck = pptx.Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Holiday plan"
        deck.save("plan.pptx")
        print(openpyxl.load_workbook("costs.xlsx").active["A2"].value)
        EOF

        python3 -c "
        from markitdown import MarkItDown
        converter = MarkItDown()
        for name in ('letter.docx', 'costs.xlsx', 'plan.pptx'):
            print(converter.convert(name).text_content)
        "

        printf '<h1>Recipe</h1><p>Pesto</p>' > recipe.html
        markitdown recipe.html
        """,
    )
    assert "tomatoes" in output
    for text in ("Letter to the landlord", "| item | cost |", "Holiday plan", "# Recipe"):
        assert text in output, f"markitdown did not give {text!r}"


@pytest.mark.spec("SBX-021")
def test_images_audio_and_video_are_converted(sandboxes: Driver) -> None:
    output = _tools(
        sandboxes,
        """
        magick -size 40x20 xc:red photo.png
        magick photo.png -resize 20x10 small.jpg
        magick identify -format '%m %wx%h\\n' small.jpg

        ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=1 tone.mp3
        ffprobe -loglevel error -show_entries format=duration -of csv=p=0 tone.mp3

        ffmpeg -loglevel error -f lavfi -i testsrc=duration=1:size=64x48:rate=5 clip.mp4
        ffprobe -loglevel error -select_streams v -show_entries stream=width -of csv=p=0 clip.mp4

        python3 -c "from PIL import Image; print(Image.open('photo.png').size)"
        """,
    )
    assert "JPEG 20x10" in output
    assert "1.0" in output
    assert "64" in output.split()
    assert "(40, 20)" in output


@pytest.mark.spec("SBX-021")
def test_data_tools_and_node_are_there(sandboxes: Driver) -> None:
    output = _tools(
        sandboxes,
        """
        printf 'item,cost\\ntomatoes,3\\nbasil,2\\n' > costs.csv
        python3 -c "import pandas, numpy; print('total', int(numpy.sum(pandas.read_csv('costs.csv')['cost'])))"

        python3 -c "import pypdf; print('pypdf', pypdf.__version__ > '')"

        echo '{"name": "basil"}' | jq -r .name
        sqlite3 :memory: 'SELECT 6 * 7;'
        zip -q archive.zip costs.csv && unzip -l archive.zip | grep -c costs.csv
        file --brief --mime-type archive.zip

        node -e 'console.log("node", 2 + 3)'
        npm --version >/dev/null && echo npm-ok

        # The tools' Python is the one the agent gets, with its own pip.
        python3 -c 'import sys; print(sys.prefix)'
        pip --version
        """,
    )
    for text in ("total 5", "pypdf True", "basil", "42", "application/zip", "node 5", "npm-ok", "/opt/tools"):
        assert text in output, f"no {text!r} in the output"
    assert "/opt/tools" in output.splitlines()[-1]
