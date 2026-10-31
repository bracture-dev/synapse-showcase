import { AppProvider } from "@nimblebrain/synapse/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@nimblebrain/synapse/ui/base";
import manifest from "../../manifest.json";
import App from "./App";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("Showcase root element is missing.");
createRoot(root).render(
  <StrictMode>
    <AppProvider name="showcase" version={manifest.version}>
      <App />
    </AppProvider>
  </StrictMode>,
);
