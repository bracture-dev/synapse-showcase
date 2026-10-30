import { cpSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
mkdirSync(resolve(root, "build"), { recursive: true });
cpSync(resolve(root, "src/SKILL.md"), resolve(root, "build/SKILL.md"));
