"""The HTTP entry point keeps to loopback, local clients and small bodies, and serves real MCP."""

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from synapse_showcase.host import CAPABILITIES
from tests.conftest import over_http, state, tool_names


def start_http(data_file) -> tuple[subprocess.Popen, str]:
    """Start `python -m synapse_showcase.server --http --port 0` and return it with its URL."""
    process = subprocess.Popen(
        [sys.executable, "-m", "synapse_showcase.server", "--http", "--port", "0"]
        + ["--data-file", str(data_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    assert process.stderr is not None
    for line in process.stderr:
        if found := re.search(r"running on (http://127\.0\.0\.1:\d+)", line):
            return process, found.group(1)
    process.kill()
    raise AssertionError("The HTTP entry point never reported its address.")


async def test_http_entry_point_enforces_local_request_boundaries_and_serves_mcp(data_file):
    process, base = start_http(data_file)
    try:
        async with httpx.AsyncClient(base_url=base) as http:
            health = await http.get("/health")
            assert health.status_code == 200
            assert health.json() == {"ok": True, "app": "synapse-showcase"}
            assert (await http.post("/mcp")).status_code == 403
            browser = {"origin": "https://foreign.invalid", "x-showcase-client": "local"}
            assert (await http.post("/mcp", headers=browser)).status_code == 403
            assert (
                await http.get("/health", headers={"host": "foreign.invalid"})
            ).status_code == 403
            assert (await http.post("/mcp", content=b"x" * 65537)).status_code == 413
            assert (await http.get("/elsewhere")).status_code == 404
        async with over_http(base) as client:
            assert "guide_status" in await tool_names(client)
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.parametrize("disconnect", ["eof", "malformed"])
async def test_managed_child_handshakes_serves_mcp_and_stops_with_control_pipe(
    data_file, disconnect
):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "synapse_showcase.server",
        "--http",
        "--host-stdio",
        "--port",
        "0",
        "--data-file",
        str(data_file),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin and process.stdout and process.stderr
    requests = []
    addresses = asyncio.Queue()

    async def installer():
        while line := await process.stdout.readline():
            request = json.loads(line)  # stdout is control messages only, never logging.
            requests.append(request)
            method = request["method"]
            if method == "hello":
                response = {"version": 1, "capabilities": dict.fromkeys(CAPABILITIES, True)}
            elif method == "snapshot":
                response = {"installation": {"managed": True}, "apps": [], "appJob": None}
            else:
                response = {"method": method, "params": request["params"]}
            process.stdin.write(
                (json.dumps({"id": request["id"], "result": response}) + "\n").encode()
            )
            await process.stdin.drain()

    async def logs():
        while line := await process.stderr.readline():
            if found := re.search(rb"running on (http://127\.0\.0\.1:\d+)", line):
                await addresses.put(found.group(1).decode())

    control, logging = asyncio.create_task(installer()), asyncio.create_task(logs())
    try:
        base = await asyncio.wait_for(addresses.get(), 10)
        assert requests[0]["method"] == "hello"
        async with httpx.AsyncClient(base_url=base) as http:
            assert (await http.get("/health")).status_code == 200
            assert (
                await http.post("/mcp", headers={"x-showcase-client": "local"})
            ).status_code == 403
        async with Client(
            StreamableHttpTransport(base + "/mcp", headers={"x-nimble-bootstrap": "local"})
        ) as client:
            assert (await state(client, "guide_status"))["installation"] == {"managed": True}
            plan = await state(client, "app_plan", {"app": "crm"})
            assert plan == {"method": "appPlan", "params": {"app": "crm"}}
            assert not any(item["method"] in ("appInstall", "appLifecycle") for item in requests)
        if disconnect == "eof":
            process.stdin.close()
        else:
            process.stdin.write(b"not json\n")
            await process.stdin.drain()
        assert await asyncio.wait_for(process.wait(), 8) == 0
        await control
    finally:
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 8)
        for task in (control, logging):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
