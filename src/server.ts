import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { VERSION } from "./constants.js";
import { FOCUS, STEPS } from "./content.js";
import type { GuideStore } from "./state.js";

const instructions =
  "An optional NimbleBrain guide. Read guide_status first. Follow the person's chosen pace; every lesson can be skipped. Buttons and agents share persistent state. guide_view affects only this guide's view; never cycle zoom. board_add/board_move change clearly labeled sample cards, separate from NimbleBrain Tasks. catalog_list describes choices; it does not install or authorize anything. External services provide their own tools and account data; their authorization belongs to the installation's supported setup. No tool handles provider keys or makes provider requests. Never change host DOM. An external connection check does not prove a provider-backed chat works.";

const result = (data: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data) }],
  structuredContent: data as Record<string, unknown>,
});

export function createGuide(store: GuideStore) {
  const snapshot = async () => ({ ...store.read(), steps: STEPS, catalog: store.catalogue() });
  const makeServer = (external = false) => {
    const server = new McpServer(
      { name: "showcase", version: VERSION },
      {
        instructions,
        capabilities: { extensions: { "io.modelcontextprotocol/skills": {} } },
        maxToolInputElements: 64,
      },
    );
    const readMeta = {
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    };
    const writeMeta = {
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
    };
    server.registerTool(
      "guide_status",
      {
        title: "Read the shared guide",
        description:
          "Read the current tutorial step, view and sample board. Does not change the chosen step.",
        inputSchema: z.object({}),
        ...readMeta,
      },
      async () => result(await snapshot()),
    );
    const mutate = async (edit: () => unknown) => {
      try {
        edit();
        return result(await snapshot());
      } catch (error) {
        return {
          content: [
            {
              type: "text" as const,
              text: error instanceof Error ? error.message : "The action could not finish.",
            },
          ],
          isError: true,
        };
      }
    };
    server.registerTool(
      "guide_step",
      {
        title: "Choose a guide step",
        description:
          "Move every open guide view to a named step; optionally record it as completed or skipped. Skipping never counts as completion. Does not change NimbleBrain settings.",
        inputSchema: z.object({
          step: z.enum(STEPS.map((s) => s.id) as [string, ...string[]]),
          complete: z.boolean().optional(),
          skip: z.boolean().optional(),
        }),
        ...writeMeta,
      },
      async ({ step, complete, skip }) => mutate(() => store.step(step, complete, skip)),
    );
    server.registerTool(
      "guide_preferences",
      {
        title: "Set guide preferences",
        description:
          "Choose guided or quick pace, and light, dark or host theme for Showcase only. Use the person's preference. Does not change NimbleBrain settings.",
        inputSchema: z.object({
          pace: z.enum(["guided", "quick"]).optional(),
          theme: z.enum(["host", "light", "dark"]).optional(),
        }),
        ...writeMeta,
      },
      async (input) => mutate(() => store.preferences(input)),
    );
    server.registerTool(
      "guide_view",
      {
        title: "Focus the guide's illustration",
        description:
          "Pause or highlight a known element inside the guide. Keep scale fixed; adjust zoom only when asked, never repeatedly zoom in and out. No access to the NimbleBrain shell or browser.",
        inputSchema: z.object({
          zoom: z.number().min(0.75).max(1.6).optional(),
          playing: z.boolean().optional(),
          focus: z.enum(FOCUS).nullable().optional(),
        }),
        ...writeMeta,
      },
      async (args) => mutate(() => store.view(args)),
    );
    server.registerTool(
      "board_add",
      {
        title: "Add a sample task",
        description: "Add a task to the guide's practice board, separate from the real Tasks app.",
        inputSchema: z.object({ title: z.string().min(1).max(120) }),
        ...writeMeta,
      },
      async ({ title }) => mutate(() => store.add(title)),
    );
    server.registerTool(
      "board_move",
      {
        title: "Move a sample task",
        description: "Move a guide practice card. Every open view follows the same saved board.",
        inputSchema: z.object({
          id: z.string().max(80),
          status: z.enum(["todo", "doing", "done"]),
        }),
        ...writeMeta,
      },
      async ({ id, status }) => mutate(() => store.move(id, status)),
    );
    server.registerTool(
      "catalog_list",
      {
        title: "Explore apps and guides",
        description:
          "List or search included examples, built-in Tasks, guides and existing connection settings. Does not install apps or authorize accounts.",
        inputSchema: z.object({ query: z.string().max(120).optional() }),
        ...readMeta,
      },
      async ({ query }) =>
        result({
          items: (await snapshot()).catalog.filter((item) =>
            `${item.title} ${item.description}`
              .toLowerCase()
              .includes((query ?? "").trim().toLowerCase()),
          ),
        }),
    );
    const skillSpecs = [
      {
        name: "guide-skill",
        uri: "skill://showcase/guide/SKILL.md",
        path: "",
        title: "Guide the first few steps",
      },
    ];
    const descriptors = skillSpecs.map((spec) => {
      const text = readFileSync(
        fileURLToPath(new URL(`${spec.path ? `${spec.path}/` : ""}SKILL.md`, import.meta.url)),
        "utf8",
      );
      server.registerResource(
        spec.name,
        spec.uri,
        { title: spec.title, mimeType: "text/markdown" },
        async () => ({ contents: [{ uri: spec.uri, mimeType: "text/markdown", text }] }),
      );
      const header = text.split("---")[1];
      if (!header) throw new Error("Bundled skill metadata is missing.");
      const frontmatter = Object.fromEntries(
        header
          .trim()
          .split("\n")
          .map((line) => {
            const colon = line.indexOf(":");
            return [line.slice(0, colon), line.slice(colon + 1).trim()];
          }),
      );
      return {
        uri: spec.uri,
        frontmatter,
        resources: [
          {
            uri: spec.uri,
            digest: `sha256:${createHash("sha256").update(text).digest("hex")}`,
            size: Buffer.byteLength(text),
          },
        ],
      };
    });
    server.server.setRequestHandler(
      "skills/list",
      { params: z.looseObject({ cursor: z.string().optional() }).optional() },
      async (params) => {
        if (params?.cursor !== undefined) throw new Error("Unknown skill cursor.");
        return { skills: descriptors };
      },
    );
    server.server.setRequestHandler(
      "skills/get",
      {
        params: z.looseObject({
          uri: z.enum(skillSpecs.map((spec) => spec.uri) as [string, ...string[]]),
        }),
      },
      async ({ uri }) => {
        const skill = descriptors.find((item) => item.uri === uri);
        if (!skill) throw new Error("Unknown skill URI.");
        return { skill };
      },
    );
    if (external) {
      server.registerTool(
        "guide_connection_check",
        {
          title: "Confirm the external guide connection",
          description:
            "When the person asks to test this connection, record a timestamp visible in Showcase. Proves an external MCP tool call, not a model provider or chat reply.",
          inputSchema: z.object({}),
          ...writeMeta,
          _meta: { ui: { visibility: ["model"] } },
        },
        async () => mutate(() => store.connected()),
      );
    }
    return server;
  };
  const handler = createMcpHandler(() => makeServer(false), { maxRequestBodySize: 64 * 1024 });
  const listeners = new Set<() => void>();
  const notify = () => {
    handler.notify.resourcesChanged();
    for (const listener of listeners) listener();
  };
  let last: number | undefined;
  try {
    last = store.read().revision;
  } catch {
    /* Explicit reads report an unreadable saved file without overwriting it. */
  }
  // Other processes write the same file, so the revision is polled. fs.watch on the file
  // stops reporting once an atomic rename replaces it, and its events differ by platform.
  const timer = setInterval(() => {
    try {
      const now = store.read().revision;
      if (now === last) return;
      last = now;
      notify();
    } catch {
      /* Explicit reads report an unreadable saved file without overwriting it. */
    }
  }, 250);
  timer.unref();
  return {
    makeServer,
    handler,
    snapshot,
    listeners,
    close: async () => {
      clearInterval(timer);
      await handler.close();
    },
  };
}
