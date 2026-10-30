import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";
import { CATALOG, FOCUS, STEPS } from "./content.js";

// A writer holds the lock for one synchronous read and replace, which takes milliseconds.
const STALE_LOCK_MS = 10_000;
const busy = () =>
  new Error("Another guide action is finishing. Read the current state, then try again.");

export type Card = { id: string; title: string; status: "todo" | "doing" | "done" };
type Saved = {
  version: 1;
  revision: number;
  step: string;
  completed: string[];
  skipped: string[];
  pace: "guided" | "quick";
  theme: "host" | "light" | "dark";
  agentCheck?: string;
  view: { zoom: number; playing: boolean; focus: string | null };
  cards: Card[];
};
const fresh = (): Saved => ({
  version: 1,
  revision: 0,
  step: "welcome",
  completed: [],
  skipped: [],
  pace: "guided",
  theme: "host",
  view: { zoom: 1, playing: false, focus: "shared" },
  cards: [
    { id: "first", title: "Try moving this task", status: "todo" },
    { id: "second", title: "Explore an app together", status: "todo" },
  ],
});

export class GuideStore {
  constructor(readonly path: string) {}
  read(): Saved {
    if (!existsSync(this.path)) return fresh();
    const state = JSON.parse(readFileSync(this.path, "utf8"));
    if (
      state.version !== 1 ||
      !Number.isSafeInteger(state.revision) ||
      !STEPS.some((s) => s.id === state.step) ||
      !Array.isArray(state.cards) ||
      !Array.isArray(state.completed) ||
      !state.view
    ) {
      throw new Error("The saved walkthrough could not be read. Its file was left unchanged.");
    }
    // Older guides acquire the new optional preferences in memory; reading never rewrites them.
    return {
      ...state,
      skipped: Array.isArray(state.skipped) ? state.skipped : [],
      pace: state.pace === "quick" ? "quick" : "guided",
      theme: ["light", "dark"].includes(state.theme) ? state.theme : "host",
    };
  }
  // A short, synchronous read-modify-write lock lets the HTTP server and any stdio
  // agent connections share progress without losing concurrent changes.
  change(edit: (state: Saved) => void): Saved {
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    const lock = `${this.path}.lock`;
    this.lock(lock);
    try {
      const state = this.read();
      const before = JSON.stringify(state);
      edit(state);
      if (before === JSON.stringify(state)) return state;
      state.revision++;
      const tmp = `${this.path}.tmp-${process.pid}`;
      writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
      renameSync(tmp, this.path);
      return state;
    } finally {
      rmdirSync(lock);
    }
  }
  private lock(lock: string) {
    try {
      mkdirSync(lock);
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
    // A lock older than STALE_LOCK_MS was left by a process that stopped mid-write.
    // Clear it once and retry; a lock that is still fresh belongs to a live writer.
    const held = statSync(lock, { throwIfNoEntry: false });
    if (held && Date.now() - held.mtimeMs < STALE_LOCK_MS) throw busy();
    try {
      if (held) rmdirSync(lock);
      mkdirSync(lock);
    } catch {
      throw busy();
    }
  }
  step(id: string, complete = false, skip = false) {
    const step = STEPS.find((s) => s.id === id);
    if (!step) throw new Error("Choose a step from guide_status.");
    if (complete && skip) throw new Error("A step can be completed or skipped, not both.");
    return this.change((state) => {
      state.step = id;
      state.view.focus = step.target;
      if (complete) this.markComplete(state, id);
      if (skip && !state.completed.includes(id) && !state.skipped.includes(id))
        state.skipped.push(id);
    });
  }
  private markComplete(state: Saved, id: string) {
    if (!state.completed.includes(id)) state.completed.push(id);
    state.skipped = state.skipped.filter((step) => step !== id);
  }
  complete(id: string) {
    if (!STEPS.some((s) => s.id === id)) throw new Error("Choose a step from guide_status.");
    return this.change((state) => this.markComplete(state, id));
  }
  preferences(input: { pace?: Saved["pace"]; theme?: Saved["theme"] }) {
    if (input.pace !== undefined && !["guided", "quick"].includes(input.pace))
      throw new Error("Choose guided or quick.");
    if (input.theme !== undefined && !["host", "light", "dark"].includes(input.theme))
      throw new Error("Choose host, light or dark.");
    return this.change((state) => {
      if (input.pace) state.pace = input.pace;
      if (input.theme) state.theme = input.theme;
    });
  }
  connected() {
    return this.change((state) => {
      state.agentCheck = new Date().toISOString();
      this.markComplete(state, "agents");
    });
  }
  view(input: { zoom?: number; playing?: boolean; focus?: string | null }) {
    if (
      input.zoom !== undefined &&
      (!Number.isFinite(input.zoom) || input.zoom < 0.75 || input.zoom > 1.6)
    )
      throw new Error("Zoom must be between 0.75 and 1.6.");
    if (
      input.focus !== undefined &&
      input.focus !== null &&
      !FOCUS.includes(input.focus as (typeof FOCUS)[number])
    )
      throw new Error("Choose a known guide focus target.");
    return this.change((state) => Object.assign(state.view, input));
  }
  add(title: string) {
    const clean = title.trim();
    if (!clean || clean.length > 120) throw new Error("Use 1–120 characters for a sample task.");
    return this.change((state) => {
      if (state.cards.length >= 100) throw new Error("This practice board holds up to 100 cards.");
      state.cards.push({ id: randomUUID(), title: clean, status: "todo" });
      this.markComplete(state, "board");
    });
  }
  move(id: string, status: Card["status"]) {
    if (!["todo", "doing", "done"].includes(status))
      throw new Error("Choose todo, doing, or done.");
    return this.change((state) => {
      const card = state.cards.find((c) => c.id === id);
      if (!card)
        throw new Error("That sample task is no longer on this board. Read the board again.");
      if (card.status !== status) {
        card.status = status;
        this.markComplete(state, "board");
      }
    });
  }
  catalogue(query = "") {
    const q = query.toLowerCase().trim();
    return CATALOG.filter((item) => `${item.title} ${item.description}`.toLowerCase().includes(q));
  }
}
