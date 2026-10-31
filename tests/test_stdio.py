"""The stdio entry point, run the way a host runs the bundle."""

import json
import os
import subprocess
import sys

from synapse_showcase import __version__
from synapse_showcase.state import GuideStore


def test_stdio_entry_point_writes_only_mcp_to_stdout_and_saves_tool_results(data_file):
    process = subprocess.Popen(
        [sys.executable, "-m", "synapse_showcase.server", "--stdio"]
        + ["--data-file", str(data_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=os.environ.copy(),
    )
    assert process.stdin is not None and process.stdout is not None
    stray: list[str] = []

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def answer(request_id: int) -> dict:
        for line in process.stdout:
            try:
                packet = json.loads(line)
            except ValueError:
                stray.append(line)
                continue
            if packet.get("id") == request_id:
                return packet
        raise AssertionError(f"stdout closed before the answer to request {request_id}")

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-test", "version": "1"},
                },
            }
        )
        info = answer(1)["result"]["serverInfo"]
        assert info == {"name": "showcase", "version": __version__}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in answer(2)["result"]["tools"]}
        assert "board_add" in names
        assert "guide_connection_check" not in names, "stdio serves the native tool set"
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "board_add", "arguments": {"title": "Stdio sample"}},
            }
        )
        created = answer(3)["result"]["structuredContent"]
        assert created["cards"][-1]["title"] == "Stdio sample"
        assert GuideStore(data_file).read()["cards"][-1]["title"] == "Stdio sample"
        assert stray == []
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
