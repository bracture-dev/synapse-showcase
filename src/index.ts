#!/usr/bin/env node
import { once } from "node:events";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  createMcpHandler,
  hostHeaderValidationResponse,
  localhostAllowedHostnames,
} from "@modelcontextprotocol/server";
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import { createGuide } from "./server.js";
import { GuideStore } from "./state.js";

export { createGuide, GuideStore };

export interface HttpGuideOptions {
  port: number;
  dataFile: string;
  /** Overrides the local-client marker header; it is not an authentication credential. */
  clientHeader?: { name: string; value: string };
}

/** Fetch handler is also usable by an embedding runtime without a Node listener. */
export function createHttpGuide(options: HttpGuideOptions) {
  const guide = createGuide(new GuideStore(options.dataFile));
  const agentHandler = createMcpHandler(() => guide.makeServer(true), {
    maxRequestBodySize: 64 * 1024,
  });
  guide.listeners.add(() => agentHandler.notify.resourcesChanged());
  const marker = options.clientHeader ?? { name: "x-showcase-client", value: "local" };
  return {
    guide,
    async fetch(request: Request): Promise<Response> {
      const invalidHost = hostHeaderValidationResponse(request, localhostAllowedHostnames());
      if (invalidHost) return invalidHost;
      if (request.headers.has("origin"))
        return new Response("Use the MCP app bridge.\n", { status: 403 });
      const path = new URL(request.url).pathname;
      if (path === "/health") return Response.json({ ok: true, app: "synapse-showcase" });
      if (path !== "/mcp" && path !== "/agent/mcp")
        return new Response("Not found\n", { status: 404 });
      if (request.headers.get(marker.name) !== marker.value)
        return new Response("Local MCP client header required\n", { status: 403 });
      return (path === "/agent/mcp" ? agentHandler : guide.handler).fetch(request);
    },
    async close() {
      await agentHandler.close();
      await guide.close();
    },
  };
}

async function serveRequest(
  request: IncomingMessage,
  response: ServerResponse,
  fetch: (request: Request) => Promise<Response>,
) {
  const abort = new AbortController();
  request.once("aborted", () => abort.abort());
  response.once("close", () => {
    if (!response.writableEnded) abort.abort();
  });
  try {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of request) {
      size += chunk.length;
      if (size > 64 * 1024) {
        response.writeHead(413).end("Request too large\n");
        return;
      }
      chunks.push(Buffer.from(chunk));
    }
    const headers = new Headers();
    for (const [name, value] of Object.entries(request.headers)) {
      if (Array.isArray(value))
        value.forEach((item) => {
          headers.append(name, item);
        });
      else if (value !== undefined) headers.set(name, value);
    }
    const method = request.method ?? "GET";
    const result = await fetch(
      new Request(`http://127.0.0.1${request.url ?? "/"}`, {
        method,
        headers,
        signal: abort.signal,
        body: method === "GET" || method === "HEAD" ? undefined : Buffer.concat(chunks),
      }),
    );
    response.writeHead(result.status, Object.fromEntries(result.headers));
    if (result.body) {
      const reader = result.body.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!response.write(value)) await once(response, "drain", { signal: abort.signal });
        }
      } finally {
        reader.releaseLock();
      }
    }
    response.end();
  } catch (error) {
    if (!response.headersSent) response.writeHead(500).end("Request failed\n");
    else response.destroy();
    if (!abort.signal.aborted) console.error("Showcase request failed:", error);
  }
}

/** Loopback-only local runner. A managed deployment supplies its own authenticated transport. */
export async function runHttpGuide(options: HttpGuideOptions) {
  if (!Number.isInteger(options.port) || options.port < 0 || options.port > 65535)
    throw new Error("Choose a valid local port.");
  const app = createHttpGuide(options);
  const server = createServer((request, response) => {
    void serveRequest(request, response, app.fetch);
  });
  try {
    server.listen(options.port, "127.0.0.1");
    await once(server, "listening");
  } catch (error) {
    await app.close();
    throw error;
  }
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("The local listener has no TCP address.");
  return {
    ...app,
    port: address.port,
    async close() {
      await app.close();
      server.closeIdleConnections();
      await new Promise<void>((done, reject) =>
        server.close((error) => (error ? reject(error) : done())),
      );
    },
  };
}

async function main(args: string[]) {
  const http = args.includes("--http");
  if (http && args.includes("--stdio")) throw new Error("Choose either HTTP or stdio transport.");
  const value = (flag: string) => {
    const index = args.indexOf(flag);
    return index < 0 ? undefined : args[index + 1];
  };
  for (let index = 0; index < args.length; index++) {
    const flag = args[index];
    if (flag === "--http" || flag === "--stdio") continue;
    if ((flag === "--port" || flag === "--data-file") && args[index + 1]) {
      index++;
      continue;
    }
    throw new Error(`Unknown or incomplete argument: ${flag}`);
  }
  const workspace = process.env.MPAK_WORKSPACE ?? process.cwd();
  const dataFile = resolve(
    value("--data-file") ??
      process.env.SHOWCASE_DATA_FILE ??
      join(workspace, "showcase", "progress.json"),
  );
  if (http) {
    const app = await runHttpGuide({ port: Number(value("--port") ?? 27249), dataFile });
    console.error(`Showcase is listening on 127.0.0.1:${app.port}`);
    const stop = async () => {
      await app.close();
    };
    process.once("SIGTERM", () => {
      void stop();
    });
    process.once("SIGINT", () => {
      void stop();
    });
  } else {
    const guide = createGuide(new GuideStore(dataFile));
    // Stdio is how NimbleBrain runs the bundle, so it serves the native tool set. Only
    // /agent/mcp adds guide_connection_check, which marks the agent chapter complete.
    const transport = serveStdio(
      () => {
        const server = guide.makeServer();
        guide.listeners.add(() => {
          void server.server.sendResourceListChanged().catch(() => {});
        });
        return server;
      },
      { onerror: (error) => console.error(error.message) },
    );
    const stop = async () => {
      await transport.close();
      await guide.close();
    };
    process.once("SIGTERM", () => {
      void stop();
    });
    process.once("SIGINT", () => {
      void stop();
    });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
