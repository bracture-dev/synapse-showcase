# Showcase

Showcase is a guide app for NimbleBrain. It teaches how an MCP app works: a person uses the
app's screen while an agent calls the same tools, and both see one saved guide and practice
board. It is released under the [MIT License](LICENSE).

## Run from a checkout

Requires Node.js 24 or later.

```sh
npm ci
npm run build
node build/index.js --stdio
```

Stdio is the default transport and serves the same tools as `/mcp`. Diagnostics go to stderr,
and stdout carries MCP messages only. For loopback HTTP:

```sh
node build/index.js --http --port 27249 --data-file ./workspace/showcase/progress.json
```

`make run` and `make run-http` build first and keep progress in `workspace/showcase/`.

| Route | Use |
| --- | --- |
| `/mcp` | MCP for the app's own screen and other native clients |
| `/agent/mcp` | MCP for an external agent; it adds `guide_connection_check` |
| `/health` | Returns `{ "ok": true, "app": "synapse-showcase" }` |

Every MCP request needs the header `x-showcase-client: local`. The header marks an intended
local client; it is not authentication against other processes on the same computer. The
listener binds only to 127.0.0.1, rejects any other Host header and any request with an Origin
header, and refuses bodies over 64 KiB. Do not expose it publicly.

Progress is saved to `--data-file`, else `SHOWCASE_DATA_FILE`, else
`<MPAK_WORKSPACE>/showcase/progress.json`, else `showcase/progress.json` in the current
directory.

## Tools

| Tool | Effect |
| --- | --- |
| `guide_status` | Read the current chapter, cards and progress |
| `guide_step` | Select a known chapter; optionally record completion or a skip |
| `guide_preferences` | Save guided or quick pace, and host, light or dark appearance for this app |
| `guide_view` | Focus, pause or scale the guide's illustration |
| `board_add`, `board_move` | Change only the practice board |
| `catalog_list` | Search the guide's included entries |
| `guide_connection_check` | External-agent route only: record a connection check the person asked for |

`skills/list` and `skills/get` serve the [guide skill](src/SKILL.md) as
`skill://showcase/guide/SKILL.md`.

Saved progress is version 1 JSON. Reads never rewrite it. Writes check their input, take a short
file lock and replace the file atomically, so the HTTP server and any stdio connection can share
one file. A corrupt file is reported and left as it was.

## Where things live

| Change | File |
| --- | --- |
| Tools, resources and the embedded skill | `src/server.ts`, `src/SKILL.md` |
| Saved progress and practice cards | `src/state.ts` |
| Chapter and catalog content | `src/content.ts` |
| Stdio and HTTP entry points | `src/index.ts` |

## Checks

`make verify` runs the type check, Biome, the build and the Vitest suite. The tests run the
compiled server over real HTTP requests and a real stdio child process.
