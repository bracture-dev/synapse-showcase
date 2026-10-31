"""Shared fixtures: an isolated progress file, MCP clients and a real loopback listener.

Tests drive the server through `fastmcp.Client`, in memory or over real HTTP, so every check
crosses the same MCP boundary a host does.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import CallToolResult

from synapse_showcase.loopback import CLIENT_HEADER

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    return tmp_path / "showcase" / "progress.json"


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    """`synapse_showcase.server` reloaded so its module-level guide saves under tmp_path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("SHOWCASE_DATA_FILE", raising=False)
    monkeypatch.setenv("MPAK_WORKSPACE", str(workspace))
    import synapse_showcase.server as module

    return importlib.reload(module)


async def call(
    client: Client, name: str, arguments: dict[str, Any] | None = None
) -> CallToolResult:
    """Call a tool and return the raw MCP result, so an isError result can be inspected."""
    return await client.call_tool_mcp(name, arguments or {})


async def state(client: Client, name: str, arguments: dict[str, Any] | None = None) -> Any:
    result = await call(client, name, arguments)
    assert not result.isError, result.content
    return result.structuredContent


async def tool_names(client: Client) -> set[str]:
    return {tool.name for tool in await client.list_tools()}


def over_http(base: str, path: str = "/mcp", **options: Any) -> Client:
    name, value = CLIENT_HEADER
    return Client(StreamableHttpTransport(base + path, headers={name: value}), **options)


@contextlib.asynccontextmanager
async def serve(app) -> AsyncIterator[str]:
    """Run an ASGI app on a free 127.0.0.1 port with uvicorn and yield its base URL."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("The test listener stopped before it started.")
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        await task
        listener.close()


async def eventually(check, timeout: float = 2.0) -> None:
    """Wait until check() is true, polling the event loop."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("The expected change did not arrive in time.")
        await asyncio.sleep(0.01)
