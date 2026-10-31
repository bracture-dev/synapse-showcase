import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";
import { synapseVite } from "@nimblebrain/synapse/vite";

export default defineConfig({
  cacheDir: ".vite",
  plugins: [react(), viteSingleFile(), synapseVite({ serverCmd: "../.venv/bin/python -m synapse_showcase.server --stdio --data-file ../workspace/showcase/progress.json" })],
  build: { outDir: "dist", assetsInlineLimit: Infinity },
});
