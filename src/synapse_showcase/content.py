"""The chapters, catalog and focus targets shared by the screen, the tools and the skills.

None of these scenes represents a change to the surrounding NimbleBrain interface.
"""

STEPS = (
    {
        "id": "welcome",
        "title": "Welcome to NimbleBrain",
        "body": "Use this guide to add apps and work with them through their screens or an agent.",
        "scene": "overview",
        "target": "shared",
    },
    {
        "id": "catalog",
        "title": "Add an app",
        "body": "Pick an app and open its screen in this workspace. Each app also gives your agent tools to work with it.",
        "scene": "catalog",
        "target": "catalog",
    },
    {
        "id": "control",
        "title": "You and your agent share the controls",
        "body": "A button calls an app tool. An agent calls that same tool. The app keeps one state and tells every open view when it changes. Ask a connected agent to open the board, or choose Next yourself.",
        "scene": "control",
        "target": "manual",
    },
    {
        "id": "board",
        "title": "Try the practice board",
        "body": "Add a sample task and move it from To do to Doing. You can also ask a connected agent to move it. These practice cards belong to Showcase; your real NimbleBrain Tasks stay separate.",
        "scene": "board",
        "target": "first-card",
    },
    {
        "id": "appearance",
        "title": "Preview appearance",
        "body": "The colors here are a preview inside the guide. To change NimbleBrain itself, use Profile → General for light or dark mode. Workspace branding is an operator setting.",
        "scene": "appearance",
        "target": "appearance",
    },
    {
        "id": "providers",
        "title": "Choose how you want to chat",
        "body": "NimbleBrain's own chat needs a model provider. Use your installation's supported setup to configure it; keep keys out of app tools and messages. An external Claude Code or Codex agent can use this guide's tools without adding a provider key to NimbleBrain.",
        "scene": "providers",
        "target": "providers",
    },
    {
        "id": "agents",
        "title": "Connect your coding agent",
        "body": "Setup skills teach Claude Code or Codex how to use your installation's supported tools. The MCP connection gives it access to this guide and its practice board. You approve the local connection in your agent. The connection check proves a tool call reached this guide; it does not test a model provider or give the agent access to every NimbleBrain app.",
        "scene": "agents",
        "target": "agents",
    },
    {
        "id": "build",
        "title": "Build an app",
        "body": "Describe what you want your app to do. Ask NimbleBrain or your coding agent to help make its tools, screen and skill. Try an action by hand, then ask the agent to make the same change.",
        "scene": "build",
        "target": "build",
    },
)

CATALOG = (
    {
        "id": "board",
        "title": "Practice board",
        "description": "Add and move sample tasks by hand or through an agent. Included in this guide.",
        "kind": "app",
        "availability": "included",
        "action": "board",
    },
    {
        "id": "tasks",
        "title": "NimbleBrain Tasks",
        "description": "Create, schedule and monitor unattended agent runs. Included with NimbleBrain; different from this practice board.",
        "kind": "app",
        "availability": "built-in",
        "action": "open-tasks",
    },
    {
        "id": "connectors",
        "title": "Manage existing connections",
        "description": "Review your existing connections in Settings. Connect new external accounts through your installation's supported setup.",
        "kind": "connector",
        "availability": "settings",
        "action": "browse-connectors",
        "actionLabel": "Open connection settings",
    },
    {
        "id": "appearance",
        "title": "Appearance",
        "description": "Try a local preview, then learn where real appearance settings live.",
        "kind": "guide",
        "availability": "guide",
        "action": "appearance",
    },
    {
        "id": "agents",
        "title": "Connect your coding agent",
        "description": "Use a skill for setup and MCP for the shared walkthrough.",
        "kind": "guide",
        "availability": "guide",
        "action": "agents",
    },
    {
        "id": "build",
        "title": "Build an app",
        "description": "Learn the tool, screen and skill pattern, then follow the installed runtime's development documentation.",
        "kind": "guide",
        "availability": "guide",
        "action": "build",
    },
)

FOCUS = (
    "manual",
    "agent",
    "shared",
    "first-card",
    "catalog",
    "appearance",
    "providers",
    "agents",
    "build",
    "appearance-blue",
    "appearance-green",
    "appearance-violet",
)

STEP_IDS = tuple(step["id"] for step in STEPS)
