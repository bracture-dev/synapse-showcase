import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { get } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "vitest";
import { createHttpGuide, GuideStore, runHttpGuide } from "../build/index.js";

const isolated = () => join(mkdtempSync(join(tmpdir(), "showcase-test-")), "progress.json");
const meta = {
  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
  "io.modelcontextprotocol/clientInfo": { name: "showcase-test", version: "1" },
  "io.modelcontextprotocol/clientCapabilities": {},
};
let sequence = 0;
function request(method, params = {}, path = "/mcp") {
  const headers = {
    host: "127.0.0.1",
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "MCP-Protocol-Version": "2026-07-28",
    "Mcp-Method": method,
    "x-showcase-client": "local",
  };
  if (params.name || params.uri) headers["Mcp-Name"] = params.name ?? params.uri;
  return new Request(`http://127.0.0.1${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: ++sequence,
      method,
      params: { ...params, _meta: meta },
    }),
  });
}
async function rpc(app, method, params = {}, path = "/mcp") {
  const response = await app.fetch(request(method, params, path));
  assert.equal(response.status, 200, await response.clone().text());
  const text = await response.text();
  const packets = response.headers.get("content-type")?.includes("text/event-stream")
    ? text
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => JSON.parse(line.slice(6)))
    : [JSON.parse(text)];
  const packet = packets.find((value) => "id" in value);
  assert.ok(packet);
  assert.equal(packet.error, undefined, JSON.stringify(packet.error));
  return packet.result;
}
const tool = (app, name, args = {}, path) =>
  rpc(app, "tools/call", { name, arguments: args }, path);

test("native and external tools share saved state and remain usable after restart", async () => {
  const dataFile = isolated();
  const app = createHttpGuide({ dataFile, port: 0 });
  try {
    const native = await rpc(app, "tools/list");
    const external = await rpc(app, "tools/list", {}, "/agent/mcp");
    assert.equal(
      native.tools.some((item) => item.name === "guide_connection_check"),
      false,
    );
    assert.equal(
      external.tools.some((item) => item.name === "guide_connection_check"),
      true,
    );
    await tool(app, "guide_step", { step: "board" });
    const created = await tool(app, "board_add", { title: "A shared sample" }, "/agent/mcp");
    const card = created.structuredContent.cards.at(-1);
    await tool(app, "board_move", { id: card.id, status: "doing" });
    const saved = readFileSync(dataFile, "utf8");
    await tool(app, "board_move", { id: card.id, status: "doing" });
    assert.equal(readFileSync(dataFile, "utf8"), saved, "a no-op move does not rewrite progress");
    assert.equal(
      (await tool(app, "guide_status", {}, "/agent/mcp")).structuredContent.cards.at(-1).status,
      "doing",
    );
  } finally {
    await app.close();
  }
  const reopened = createHttpGuide({ dataFile, port: 0 });
  try {
    const current = (await tool(reopened, "guide_status")).structuredContent;
    assert.equal(current.step, "board");
    assert.equal(current.cards.at(-1).title, "A shared sample");
    assert.equal(current.cards.at(-1).status, "doing");
    assert.equal(current.revision, 3);
  } finally {
    await reopened.close();
  }
});

test("invalid writes, corrupt progress and a live writer lock preserve saved bytes", async () => {
  const store = new GuideStore(isolated());
  store.step("board");
  const before = readFileSync(store.path, "utf8");
  for (const action of [
    () => store.move("missing", "done"),
    () => store.step("body"),
    () => store.view({ zoom: Infinity }),
    () => store.add(" "),
    () => store.preferences({ theme: "unknown" }),
  ])
    assert.throws(action);
  assert.equal(readFileSync(store.path, "utf8"), before);
  mkdirSync(`${store.path}.lock`);
  assert.throws(() => store.add("Do not overwrite"), /Another guide action/);
  assert.equal(readFileSync(store.path, "utf8"), before);

  const corruptFile = isolated();
  writeFileSync(corruptFile, "interrupted personal progress");
  const app = createHttpGuide({ dataFile: corruptFile, port: 0 });
  try {
    assert.equal((await tool(app, "guide_status")).isError, true);
    assert.equal(readFileSync(corruptFile, "utf8"), "interrupted personal progress");
  } finally {
    await app.close();
  }
});

test("a lock left by a writer that stopped mid-write is cleared once it is stale", () => {
  const store = new GuideStore(isolated());
  store.step("board");
  const lock = `${store.path}.lock`;
  mkdirSync(lock);
  const old = new Date(Date.now() - 60_000);
  utimesSync(lock, old, old);
  store.add("After a crash");
  assert.equal(store.read().cards.at(-1).title, "After a crash");
  assert.equal(existsSync(lock), false);
});

test("legacy preferences are read without rewriting and skipping is distinct from completing", () => {
  const store = new GuideStore(isolated());
  const old = store.read();
  delete old.skipped;
  delete old.pace;
  delete old.theme;
  writeFileSync(store.path, JSON.stringify(old));
  const bytes = readFileSync(store.path, "utf8");
  assert.equal(store.read().theme, "host");
  assert.equal(readFileSync(store.path, "utf8"), bytes);
  store.step("catalog", false, true);
  assert.deepEqual(store.read().skipped, ["catalog"]);
  assert.deepEqual(store.read().completed, []);
  const other = new GuideStore(store.path);
  other.preferences({ pace: "quick", theme: "dark" });
  store.step("build");
  other.complete("catalog");
  assert.equal(store.read().step, "build");
  assert.deepEqual(store.read().skipped, []);
  assert.deepEqual(store.read().completed, ["catalog"]);
  assert.equal(store.read().pace, "quick");
  assert.equal(store.read().theme, "dark");
});

test("the bundled guide skill is discoverable without creating saved progress", async () => {
  const dataFile = isolated();
  const app = createHttpGuide({ dataFile, port: 0 });
  try {
    const skills = await rpc(app, "skills/list");
    assert.equal(skills.skills.length, 1);
    for (const skill of skills.skills) {
      assert.match(skill.resources[0].digest, /^sha256:[a-f0-9]{64}$/);
      assert.equal((await rpc(app, "skills/get", { uri: skill.uri })).skill.uri, skill.uri);
      assert.equal(
        (await rpc(app, "resources/read", { uri: skill.uri })).contents[0].mimeType,
        "text/markdown",
      );
    }
    assert.equal(existsSync(dataFile), false);
  } finally {
    await app.close();
  }
});

test("Node HTTP runner enforces local request boundaries and serves real MCP", async () => {
  const app = await runHttpGuide({ dataFile: isolated(), port: 0 });
  try {
    const url = `http://127.0.0.1:${app.port}`;
    assert.equal((await fetch(`${url}/health`)).status, 200);
    assert.equal((await fetch(`${url}/mcp`, { method: "POST" })).status, 403);
    assert.equal(
      (
        await fetch(`${url}/mcp`, {
          method: "POST",
          headers: { origin: "https://foreign.invalid", "x-showcase-client": "local" },
        })
      ).status,
      403,
    );
    // Fetch can normalize Host; use the HTTP client to exercise the actual untrusted header.
    const wrongHostStatus = await new Promise((resolve, reject) => {
      get(`${url}/health`, { headers: { host: "foreign.invalid" } }, (response) => {
        response.resume();
        response.on("end", () => resolve(response.statusCode));
      }).on("error", reject);
    });
    assert.equal(wrongHostStatus, 403);
    assert.equal(
      (await fetch(`${url}/mcp`, { method: "POST", body: "x".repeat(65537) })).status,
      413,
    );
    const original = request("tools/list");
    const response = await fetch(`${url}/mcp`, {
      method: original.method,
      headers: original.headers,
      body: await original.text(),
    });
    assert.equal(response.status, 200);
    assert.match(await response.text(), /guide_status/);
  } finally {
    await app.close();
  }
});

test("persisted agent writes announce a resource change and reads do not create refresh loops", async () => {
  const app = createHttpGuide({ dataFile: isolated(), port: 0 });
  let notices = 0;
  let changed;
  app.guide.listeners.add(() => {
    notices++;
    changed?.();
  });
  try {
    await tool(app, "guide_status");
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(notices, 0);
    const notice = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("No persisted-write notice")), 1000);
      changed = () => {
        clearTimeout(timeout);
        resolve();
      };
    });
    await tool(app, "board_add", { title: "Agent notification sample" }, "/agent/mcp");
    await notice;
    assert.equal(notices, 1);
    await tool(app, "guide_status");
    await tool(app, "catalog_list");
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(notices, 1);
  } finally {
    await app.close();
  }
});

test("compiled Node entry serves stdio with JSON-only stdout and saved tool results", async () => {
  const dataFile = isolated();
  const child = spawn(process.execPath, ["build/index.js", "--stdio", "--data-file", dataFile], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  const pending = new Map();
  const invalid = [];
  let buffer = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    for (;;) {
      const index = buffer.indexOf("\n");
      if (index < 0) break;
      const line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      try {
        const packet = JSON.parse(line);
        pending.get(packet.id)?.(packet);
      } catch {
        invalid.push(line);
      }
    }
  });
  const send = (id, method, params) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Stdio request timed out: ${method}`)), 8000);
      pending.set(id, (packet) => {
        clearTimeout(timer);
        pending.delete(id);
        resolve(packet);
      });
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  try {
    const initialize = await send(1, "initialize", {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "stdio-test", version: "1" },
    });
    assert.equal(initialize.result.serverInfo.name, "showcase");
    assert.equal(
      initialize.result.serverInfo.version,
      JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8")).version,
    );
    child.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`,
    );
    const stdioTools = (await send(2, "tools/list", {})).result.tools.map((item) => item.name);
    assert.ok(stdioTools.includes("board_add"));
    assert.equal(stdioTools.includes("guide_connection_check"), false, "stdio is a native route");
    const created = await send(3, "tools/call", {
      name: "board_add",
      arguments: { title: "Stdio sample" },
    });
    assert.equal(created.result.structuredContent.cards.at(-1).title, "Stdio sample");
    assert.equal(new GuideStore(dataFile).read().cards.at(-1).title, "Stdio sample");
    assert.deepEqual(invalid, []);
  } finally {
    child.stdin.end();
    await once(child, "exit", { signal: AbortSignal.timeout(8000) }).catch(() =>
      child.kill("SIGTERM"),
    );
  }
});
