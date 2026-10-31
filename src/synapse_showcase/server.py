"""Showcase MCP server: stdio by default, loopback HTTP with --http.

Progress is saved to --data-file, else SHOWCASE_DATA_FILE, else
<MPAK_WORKSPACE>/showcase/progress.json, else showcase/progress.json in the current directory.
"""

import argparse
import asyncio
import os
from pathlib import Path

from synapse_showcase.guide import Guide
from synapse_showcase.loopback import DEFAULT_PORT, create_http_app, run_host_http, run_http
from synapse_showcase.state import GuideStore


def data_file(explicit: str | None = None) -> Path:
    chosen = explicit or os.environ.get("SHOWCASE_DATA_FILE")
    if not chosen:
        workspace = os.environ.get("MPAK_WORKSPACE") or os.getcwd()
        chosen = os.path.join(workspace, "showcase", "progress.json")
    return Path(os.path.abspath(chosen))


guide = Guide(GuideStore(data_file()))
mcp = guide.make_server()

# ASGI entrypoint for `uvicorn synapse_showcase.server:app`: /mcp, /agent/mcp and /health
app = create_http_app(guide)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m synapse_showcase.server", description="Serve the Showcase guide over MCP."
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="serve stdio (the default)")
    transport.add_argument("--http", action="store_true", help="serve HTTP on 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port; 0 picks one")
    parser.add_argument("--data-file", help="where to save guide progress")
    parser.add_argument(
        "--host-stdio",
        action="store_true",
        help="use the installer's inherited control pipes with HTTP",
    )
    args = parser.parse_args(argv)
    if args.host_stdio and not args.http:
        parser.error("--host-stdio requires --http; standalone stdio belongs to MCP")
    if args.host_stdio:
        asyncio.run(run_host_http(GuideStore(data_file(args.data_file)), args.port))
        return
    chosen = Guide(GuideStore(data_file(args.data_file)))
    if args.http:
        run_http(chosen, args.port)
        return
    # Stdio is how NimbleBrain runs the bundle, so it serves the native tool set. Only /agent/mcp
    # adds guide_connection_check, which marks the agent chapter complete. Without the banner,
    # FastMCP also skips its release check, so stdio makes no network request.
    chosen.make_server().run(show_banner=False)


if __name__ == "__main__":
    main()
