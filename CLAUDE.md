# Showcase

Read [README.md](README.md) for setup, transports and package layout.

- Keep the guide's existing MCP tool shapes and `ui://showcase/guide` address stable.
- `src/synapse_showcase/` owns tools, state, HTTP boundaries and packaged resources;
  `ui/` calls those tools through the Synapse bridge.
- `skills/` is packaged with the server. Match every tool name to the server's current surface.
- The optional installer adapter owns installation effects; the standalone guide does not.
- Preserve the dependency locks. Run `make verify` after preparing approved environments.
- Build the UI before a wheel or bundle. Test the installed package's resources as well as
  source-checkout imports.
- A contributor branch and review do not authorize an upstream release or settings change.
