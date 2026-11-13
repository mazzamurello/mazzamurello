"""Offering a file of the workspace to download (AGT-023, ADR-0079).

The tool checks, through the sandbox driver, that the file is there and is a
regular file; clients show the call as a card with a download button, which
gets the file as it is when the user taps it.
"""

from __future__ import annotations

import posixpath
from typing import Any

import httpx
from pydantic_ai import RunContext, Tool

from sibillo_server.gateway import RunDeps

DRIVER_TIMEOUT_SECONDS = 60


async def offer_download(ctx: RunContext[RunDeps], path: str) -> str:
    """Offer one file of the workspace to the user, who gets a button that downloads it.

    Args:
        path: The file's path in /workspace, such as `/workspace/report.pdf` or `report.pdf`.
    """
    relative = path.strip().removeprefix("/workspace").strip("/")
    folder, name = posixpath.split(relative)
    deps = ctx.deps
    sandbox = f"{deps.sandboxd_url}/sandboxes/{deps.identity.tenant_id}/{deps.identity.user_id}/{deps.conversation_id}"
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {deps.sandboxd_token}"}, timeout=DRIVER_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(f"{sandbox}/entries", params={"path": folder})
    except httpx.HTTPError:
        return "The file was not offered: the workspace could not be reached now."
    entries: list[dict[str, Any]] = response.json().get("entries", []) if response.status_code == 200 else []
    found = next((entry for entry in entries if entry.get("name") == name), None)
    if not name or found is None:
        return f"The file was not offered: /workspace/{relative} does not exist."
    if found.get("type") != "file":
        return f"The file was not offered: /workspace/{relative} is not a regular file."
    return (
        f"Offered /workspace/{found['path']} ({found['size']} bytes) for download: the user sees a card with a"
        " download button."
    )


TOOLS = (Tool(offer_download),)
