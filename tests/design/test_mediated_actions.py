"""The agent acts only through mediated tools, and nothing runs on the host for users (AGT-001, OPS-004)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic_ai.native_tools import AbstractNativeTool

from mazzamurello_server import worker
from tests.support.database import ROOT

# Every capability of the agent: the gateway, the user's sandbox and the
# tools that work in it, durability, and what Pydantic AI adds by itself.
# None of them acts on the outside world except through the sandbox driver.
ALLOWED_CAPABILITIES = {
    "pydantic_ai.capabilities._tool_search.ToolSearch",
    "pydantic_ai.capabilities._pending_messages.PendingMessageDrainCapability",
    "pydantic_ai.durable_exec._workspace.WorkspaceEnsurer",
    "mazzamurello_server.gateway.Gateway",
    "mazzamurello_server.sandbox.SandboxWorkspace",
    "pydantic_ai_harness.shell._capability.Shell",
    "pydantic_ai_harness.filesystem._capability.FileSystem",
    "pydantic_ai_harness.tool_output_limits._capability.ToolOutputLimits",
    "pydantic_ai.durable_exec.dbos._durability.DBOSDurability",
}
# Tools the provider runs: only the search over the agent's own tools.
ALLOWED_NATIVE_TOOLS = {"tool_search"}
# The only places a component runs a command on the host, by file and
# enclosing function. Neither runs anything a user or the agent chose.
ALLOWED_HOST_COMMANDS = {
    ("src/netguard/mazzamurello_netguard/guard.py", "_nft"),
    ("src/sandboxd/mazzamurello_sandboxd/isolation.py", "_runtime_release"),
}
HOST_COMMANDS = {
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("asyncio", "create_subprocess_exec"),
    ("asyncio", "create_subprocess_shell"),
    ("os", "system"),
    ("os", "popen"),
    ("os", "execv"),
    ("os", "execvp"),
    ("os", "spawnv"),
}


@pytest.mark.spec("AGT-001")
def test_the_agent_has_only_mediated_capabilities() -> None:
    capabilities = {f"{type(c).__module__}.{type(c).__name__}" for c in worker.agent.root_capability.capabilities}
    assert capabilities == ALLOWED_CAPABILITIES


@pytest.mark.spec("AGT-001")
def test_the_agent_has_no_tools_of_its_own_and_no_provider_tools_that_act() -> None:
    tools = [tool for capability in worker.agent.root_capability.capabilities for tool in capability.get_native_tools()]
    # A native tool chosen at run time could be any tool: none is allowed.
    assert all(isinstance(tool, AbstractNativeTool) for tool in tools)
    assert {tool.kind for tool in tools if isinstance(tool, AbstractNativeTool)} <= ALLOWED_NATIVE_TOOLS
    assert list(worker.agent._function_toolset.tools) == []  # pyright: ignore[reportPrivateUsage]
    assert worker.agent._user_toolsets == []  # pyright: ignore[reportPrivateUsage]


def _host_commands(path: Path) -> set[str]:
    """The enclosing function of every call that runs a command on the host."""
    found: set[str] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and (child.value.id, child.attr) in HOST_COMMANDS
            ):
                found.add(function)
            visit(child, name)

    visit(ast.parse(path.read_text(), filename=str(path)), "<module>")
    return found


@pytest.mark.spec("OPS-004")
def test_components_run_no_host_commands_for_users() -> None:
    found = {
        (str(path.relative_to(ROOT)), function)
        for path in sorted((ROOT / "src").rglob("*.py"))
        for function in _host_commands(path)
    }
    assert found <= ALLOWED_HOST_COMMANDS, "new host commands: they must run in sandboxes instead"
