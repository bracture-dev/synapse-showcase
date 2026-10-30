import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
if (!/^0\.\d+\.\d+$/.test(manifest.version)) throw new Error("Use the app's 0.x.y version policy.");
for (const file of ["package.json", "package-lock.json"]) {
  const path = resolve(root, file);
  const data = JSON.parse(readFileSync(path, "utf8"));
  data.version = manifest.version;
  if (data.packages?.[""]) data.packages[""].version = manifest.version;
  writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);
}
writeFileSync(
  resolve(root, "src/constants.ts"),
  `// Generated from manifest.json by make sync.\nexport const VERSION = ${JSON.stringify(manifest.version)};\n`,
);
