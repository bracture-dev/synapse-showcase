# Showcase

Showcase is a guide app for NimbleBrain. It teaches how an MCP app works: a person uses the
app's screen while an agent calls the same tools, and both see one saved guide and practice
board. It is a Python FastMCP server with a React UI, released under the [MIT License](LICENSE).

## Develop

Use Python 3.13 or newer, Node.js 24 or newer, and the repository's reviewed dependency locks.
Prepare the Python environment with `uv sync --frozen --dev` and the UI with
`npm --prefix ui ci --ignore-scripts`, subject to your host's package policy. Then:

```sh
make dev       # Vite preview at /__preview, with a stdio Python server
make verify    # Python formatting, lint, types and tests; UI types and build
make run       # standalone MCP over stdio
make run-http  # MCP over HTTP on 127.0.0.1:27249
```

The build creates one HTML file in `ui/dist/index.html`. Build it before making a Python wheel
or MCPB bundle. The wheel includes this HTML and the guide skills, so an installed package
needs no source checkout or Node runtime to serve its screen. `SHOWCASE_UI_DIR` can select a
different directory containing `index.html`.

## Run and connect

The package entry point is `python -m synapse_showcase.server`. Stdio is the default. HTTP mode
uses `--http --port 27249` and exposes `/mcp`, `/agent/mcp` and `/health` on loopback only.
`/agent/mcp` adds `guide_connection_check`, which records that an external agent called the
guide. It does not verify a model provider or a chat reply.

The screen is the MCP resource `ui://showcase/guide`, served as
`text/html;profile=mcp-app`. The manifest declares its NimbleBrain sidebar placement. A host
must support MCP Apps to render it; opening the built HTML directly does not supply the MCP
bridge.

Progress and sample cards are stored in one JSON file. Select it with `--data-file` or
`SHOWCASE_DATA_FILE`; otherwise it is `showcase/progress.json` under `MPAK_WORKSPACE`, or under
the current directory. Every process sharing that file sees the same progress. The practice
board is separate from NimbleBrain Tasks and installed apps.

A standalone guide works without an installer. A local-install supervisor can supply the
optional app planning, installation, status and external-agent setup capabilities through the
server's `--http --host-stdio` mode. The supervisor owns package approval, processes, source
verification and recovery. Showcase does not acquire apps itself. Unavailable capabilities
are omitted from the tools and shown as unavailable in the guide.

## Package

`manifest.json` describes the Python entry point and app placement; `mpak.json` identifies the
canonical package. The release workflow follows the Synapse app platform matrix and builds
the UI before `mcpb-pack` vendors the Python package. It runs only for releases in the canonical
repository. Keep the version in `manifest.json`, `pyproject.toml`,
`src/synapse_showcase/__init__.py`, `ui/package.json` and `ui/package-lock.json` consistent
before a release.
